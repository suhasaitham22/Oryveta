/* Data access for the controlled repair queue: approved policies, queued goals and the
   bounded result a worker recorded. PostgreSQL RLS and the SECURITY DEFINER RPCs—not this
   module—authorize every read and write; the checks here only stop an obviously malformed
   request from being sent and keep the panel from rendering a result that does not match
   the published contract. Nothing here executes repository code, applies a patch, or
   reports that a worker is available. */
import { supabase } from "./identity.js";

export const REPAIR_KIND = "repository_repair";
export const GOAL_MAX_BYTES = 4096;
export const LABEL_MAX = 60;

const POLICY_FIELDS =
  "id,project_id,worker_identity,worker_user_id,label,enabled,source_url,source_owner,source_repo," +
  "source_commit,configuration_sha256,last_seen_at,created_at,created_by,revoked_at,revoked_by";
const WORK_FIELDS =
  "id,project_id,kind,status,goal,repair_policy_id,source_url,input_digest," +
  "pinned_source_ref,pinned_source_commit,attempts,max_attempts,error_code,created_at,updated_at";
const RUN_FIELDS =
  "id,work_item_id,attempt,status,phase,checkpoint,source_ref,source_commit,source_digest," +
  "result,error_code,started_at,finished_at";
const EVENT_FIELDS = "id,run_id,work_item_id,kind,phase,detail,created_at";
/* Postgres/PostgREST codes meaning the repair schema has not been applied yet. */
const MISSING_SCHEMA = new Set(["42P01", "42883", "PGRST202", "PGRST205"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const COMMIT = /^[0-9a-f]{40}$/;
const DIGEST = /^[0-9a-f]{64}$/;
/* Goal text is human prose: newlines and tabs are kept, other control characters are not. */
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;

export const goalBytes = (value) => new TextEncoder().encode(value).length;

function data(result) {
  if (!result.error) return result.data;
  const setup = MISSING_SCHEMA.has(result.error.code);
  const error = new Error(
    setup
      ? "Controlled repair is unavailable until the durable repair migration is applied to this database."
      : result.error.message || "The repair request failed.",
  );
  error.code = result.error.code;
  /* The panel renders a setup state for a missing schema instead of an error. */
  error.setup = setup;
  throw error;
}

/* Every policy row for the project, newest first. Revoked rows are kept so history can
   still name the policy a past repair ran under. */
export async function listRepairPolicies(projectId, signal) {
  return data(await supabase.from("project_repair_policies").select(POLICY_FIELDS)
    .eq("project_id", projectId).order("created_at", { ascending: false })
    .limit(50).abortSignal(signal)) || [];
}

export async function listRepairWork(projectId, signal) {
  return data(await supabase.from("work_items").select(WORK_FIELDS)
    .eq("project_id", projectId).eq("kind", REPAIR_KIND)
    .order("created_at", { ascending: false })
    .limit(10).abortSignal(signal)) || [];
}

/* The latest attempt and its recorded events. Progress is whatever the worker persisted:
   this module never interpolates a phase or a percentage. */
export async function readLatestRepairRun(workItemId, signal) {
  const [run, events] = await Promise.all([
    supabase.from("factory_runs").select(RUN_FIELDS)
      .eq("work_item_id", workItemId).order("attempt", { ascending: false })
      .limit(1).abortSignal(signal).maybeSingle(),
    supabase.from("factory_run_events").select(EVENT_FIELDS)
      .eq("work_item_id", workItemId).order("id", { ascending: false })
      .limit(30).abortSignal(signal),
  ]);
  return { run: data(run), events: (data(events) || []).reverse() };
}

export function normalizeGoal(value) {
  const goal = String(value ?? "").trim();
  if (!goal) throw new Error("Describe the bounded change the worker should attempt.");
  if (CONTROL.test(goal)) throw new Error("Remove control characters from the goal text.");
  if (goalBytes(goal) > GOAL_MAX_BYTES)
    throw new Error(`The goal must be at most ${GOAL_MAX_BYTES} bytes of text.`);
  return goal;
}

export async function submitRepositoryRepair(projectId, policyId, goal, idempotencyKey) {
  if (!UUID.test(String(policyId || "")))
    throw new Error("Choose an enabled repair policy first.");
  return data(await supabase.rpc("submit_repository_repair", {
    p_project_id: projectId,
    p_policy_id: policyId,
    p_goal: normalizeGoal(goal),
    p_idempotency_key: idempotencyKey,
  }).single());
}

/* The same generic cancellation the analysis panel uses: it requests cancellation of the
   work item and lets the database fence the running attempt. */
export async function cancelRepair(workItemId) {
  return data(await supabase.rpc("cancel_work_item", {
    p_work_item_id: workItemId,
  }).single());
}

/* Enrollment binds an already-registered worker identity to one reviewed configuration
   digest and one pinned commit. No configuration, command, model or credential is sent. */
export async function registerRepairPolicy(projectId, { workerUserId, label, sourceCommit, configurationSha256 }) {
  const worker = String(workerUserId || "").trim();
  const name = String(label || "").trim();
  const commit = String(sourceCommit || "").trim().toLowerCase();
  const digest = String(configurationSha256 || "").trim().toLowerCase();
  if (!UUID.test(worker))
    throw new Error("Enter the dedicated worker's Supabase user ID. Register it under Worker access first.");
  if (name.length < 2 || name.length > LABEL_MAX)
    throw new Error(`The policy label must be 2 to ${LABEL_MAX} characters.`);
  if (!COMMIT.test(commit))
    throw new Error("Enter the 40-character lowercase commit SHA the worker is approved to repair.");
  if (!DIGEST.test(digest))
    throw new Error("Enter the 64-character SHA-256 digest of the configuration the operator reviewed.");
  return data(await supabase.rpc("register_project_repair_policy", {
    p_project_id: projectId,
    p_worker_user_id: worker,
    p_label: name,
    p_source_commit: commit,
    p_configuration_sha256: digest,
  }).single());
}

/* Revocation disables the policy and settles its pending and running work, so nothing
   stays queued against an identity that is no longer approved. */
export async function revokeRepairPolicy(policyId) {
  return data(await supabase.rpc("revoke_project_repair_policy", {
    p_policy_id: policyId,
  }).single());
}

/* The compact persisted result, or null. A completion is only reviewable when it carries
   the contract's own shape: a repair candidate that passed verification and kept its
   untruncated patch. Anything else is reported as an unreadable result rather than
   presented as a reviewable change. */
export function readRepairResult(run) {
  const result = run?.result;
  if (!result || typeof result !== "object") return null;
  if (result.kind !== REPAIR_KIND || result.status !== "needs_review") return null;
  if (result.verification !== "passed") return null;
  if (typeof result.patch !== "string" || !result.patch.length) return null;
  if (!COMMIT.test(String(result.source_commit || ""))) return null;
  if (!DIGEST.test(String(result.patch_sha256 || ""))) return null;
  return result;
}

/* Saves the patch exactly as the worker recorded it; the browser never rewrites or
   truncates the bytes the result hash covers. */
export function downloadPatch(name, patch) {
  const url = URL.createObjectURL(new Blob([patch], { type: "text/x-patch" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
