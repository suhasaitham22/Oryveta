/* Browser data access for the reviewed Evolve workflow. PostgreSQL RLS and the
   SECURITY DEFINER RPCs below authorize every read and write: nothing here is a
   permission check, and no value read from a row is treated as authority.
   Evolve work shares the durable runtime tables with repository analysis and is
   separated only by work_items.kind = 'evolve'. Artifacts are read from the
   private Storage bucket with the signed-in user's own session, never through a
   public or long-lived URL. */
import { supabase } from "./identity.js";

const WORK_FIELDS =
  "id,project_id,kind,status,goal,source_url,input_digest,evolve_config_sha256," +
  "attempts,max_attempts,error_code,decided_at,decided_by,created_at,updated_at";
const RUN_FIELDS =
  "id,work_item_id,attempt,status,phase,source_ref,source_commit,source_digest,result,error_code,started_at,finished_at";
const EVENT_FIELDS = "id,run_id,work_item_id,kind,phase,detail,created_at";
const STAGE_FIELDS = "id,run_id,work_item_id,project_id,stage,payload,created_at";
const ARTIFACT_FIELDS =
  "id,run_id,work_item_id,project_id,kind,sha256,bytes,storage_path,created_at";
/* lesson_index plus the source and config digests are the scope a worker may
   retrieve this lesson for, so they are shown rather than summarized away. */
const LESSON_FIELDS =
  "id,project_id,work_item_id,run_id,status,origin,lesson,lesson_index," +
  "source_sha256,config_sha256,revoked_at,created_at";

export const WORK_KIND = "evolve";
export const ARTIFACT_BUCKET = "evolve-artifacts";
/* Declared order of the reviewed pipeline. Used for display only; the server
   enforces admission order and the finish requirements. */
export const STAGE_ORDER = [
  "requirements",
  "plan",
  "implementation",
  "verification",
  "audit",
  "learning",
  "learning_review",
];
export const GOAL_LIMIT = 4000;
export const GOAL_MINIMUM = 1;

/* Postgres/PostgREST codes meaning the Evolve schema has not been applied yet:
   missing table, missing function, missing column, unknown RPC, stale schema cache. */
const MISSING_SCHEMA = new Set(["42P01", "42883", "42703", "PGRST202", "PGRST204", "PGRST205"]);
const HEX64 = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function data(result, fallback) {
  if (!result.error) return result.data;
  const missing = MISSING_SCHEMA.has(result.error.code);
  const error = new Error(
    missing
      ? "Evolve is unavailable until the Evolve migration is applied to this database."
      : result.error.message || fallback,
  );
  error.code = result.error.code;
  error.missingSchema = missing;
  throw error;
}

/* The same bounds the RPC enforces, checked here only so the message is
   readable. Line endings are normalized so a pasted goal is the exact text the
   requirements stage must repeat verbatim. */
export function goalText(value) {
  const clean = String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .trim();
  if (clean.length < GOAL_MINIMUM)
    throw new Error(
      GOAL_MINIMUM > 1
        ? `Describe the change you want in at least ${GOAL_MINIMUM} characters before submitting.`
        : "Describe the change you want before submitting.",
    );
  if (clean.length > GOAL_LIMIT)
    throw new Error(`Keep the goal under ${GOAL_LIMIT} characters.`);
  /* Control characters other than line breaks and tabs are not storable text. */
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(clean))
    throw new Error("Remove control characters from the goal before submitting.");
  return clean;
}

/* Recent Evolve work for one project. Repository analyses are a different kind
   and are listed by the analysis panel instead. */
export async function listEvolveWork(projectId, signal) {
  return (
    data(
      await supabase
        .from("work_items")
        .select(WORK_FIELDS)
        .eq("project_id", projectId)
        .eq("kind", WORK_KIND)
        .order("created_at", { ascending: false })
        .limit(10)
        .abortSignal(signal),
      "The Evolve request failed.",
    ) || []
  );
}

/* Latest attempt plus its recent durable events. An absent run is normal while
   the item is still queued. */
export async function readLatestEvolveRun(workItemId, signal) {
  const [run, events] = await Promise.all([
    supabase
      .from("factory_runs")
      .select(RUN_FIELDS)
      .eq("work_item_id", workItemId)
      .order("attempt", { ascending: false })
      .limit(1)
      .abortSignal(signal)
      .maybeSingle(),
    supabase
      .from("factory_run_events")
      .select(EVENT_FIELDS)
      .eq("work_item_id", workItemId)
      .order("id", { ascending: false })
      .limit(40)
      .abortSignal(signal),
  ]);
  return {
    run: data(run, "The Evolve run could not be read."),
    events: (data(events, "The Evolve run events could not be read.") || []).reverse(),
  };
}

/* Immutable stage artifacts/reviews and registered artifact records for one
   attempt. Both are SELECT-only for project readers and registered workers. */
export async function readEvolveEvidence(runId, signal) {
  const [stages, artifacts] = await Promise.all([
    supabase
      .from("evolve_stages")
      .select(STAGE_FIELDS)
      .eq("run_id", runId)
      .order("created_at")
      .limit(STAGE_ORDER.length)
      .abortSignal(signal),
    supabase
      .from("evolve_artifacts")
      .select(ARTIFACT_FIELDS)
      .eq("run_id", runId)
      .order("created_at")
      .limit(40)
      .abortSignal(signal),
  ]);
  return {
    stages: data(stages, "The Evolve stage records could not be read.") || [],
    artifacts: data(artifacts, "The Evolve artifact records could not be read.") || [],
  };
}

/* Lessons for this project only. Readers see activated lessons; candidate rows
   are visible to project admins. RLS decides, not this query. */
export async function listEvolveLessons(projectId, signal) {
  return (
    data(
      await supabase
        .from("evolve_lessons")
        .select(LESSON_FIELDS)
        .eq("project_id", projectId)
        .order("created_at", { ascending: false })
        .limit(50)
        .abortSignal(signal),
      "The Evolve lessons could not be read.",
    ) || []
  );
}

/* Durable submission. The goal is bounded here for a readable message, and
   again by the server, which also pins the project's frozen source. The
   idempotency key is chosen by the caller so an ambiguous network failure can
   be retried without queueing a second attempt. */
export async function submitEvolveWork(projectId, goal, idempotencyKey) {
  const row = data(
    await supabase
      .rpc("submit_evolve_work", {
        p_project_id: projectId,
        p_goal: goalText(goal),
        p_idempotency_key: idempotencyKey,
      })
      .single(),
    "The Evolve submission failed.",
  );
  return workItemId(row);
}

/* Shared control: cancel_work_item fences Evolve running and awaiting states too. */
export async function cancelEvolveWork(workItemIdValue) {
  return data(
    await supabase.rpc("cancel_work_item", { p_work_item_id: workItemIdValue }).single(),
    "The cancel request failed.",
  );
}

/* Human decision on one exact run and candidate archive digest. Project admins
   only; the RPC re-checks the role, the latest run and the digest.

   The server answers with a row, and `reason` is part of the outcome rather than
   a transport failure: ok and already_decided are decisions, while
   creator_unauthorized and worker_unauthorized mean the server fenced the work
   because the requester lost their editing role or the producing worker
   identity was revoked. In those cases the item is terminal and the candidate
   is gone — a real result the panel must report, not an error to retry. Only an
   unrecognized reason is raised, because its meaning is unknown. */
export const DECISION_REASONS = new Set([
  "ok",
  "already_decided",
  "creator_unauthorized",
  "worker_unauthorized",
]);

export async function decideEvolveWork(workItemIdValue, runId, candidateSha256, approve) {
  if (!HEX64.test(String(candidateSha256 || "")))
    throw new Error("The candidate digest is missing, so this run cannot be decided.");
  const row = data(
    await supabase
      .rpc("decide_evolve_work", {
        p_work_item_id: workItemIdValue,
        p_run_id: runId,
        p_candidate_sha256: candidateSha256,
        p_approve: approve,
      })
      .single(),
    "The approval decision failed.",
  );
  if (row?.reason && !DECISION_REASONS.has(row.reason))
    throw new Error(`The decision was refused (${row.reason}).`);
  return row;
}

export async function revokeEvolveLesson(lessonId) {
  return data(
    await supabase.rpc("revoke_evolve_lesson", { p_lesson_id: lessonId }).single(),
    "The lesson could not be revoked.",
  );
}

/* Storage path of a registered artifact, recomputed from the record's own run,
   kind and digest. A row whose stored path does not match is not downloaded:
   the UI reads registered artifacts, never an arbitrary or staged object path. */
export function artifactPath(artifact) {
  const kind = String(artifact?.kind || "");
  const sha = String(artifact?.sha256 || "");
  const run = String(artifact?.run_id || "");
  if (!UUID.test(run) || !HEX64.test(sha) || !/^[a-z]{4,16}$/.test(kind))
    throw new Error("This artifact record is not a recognizable Evolve artifact.");
  const expected = `${run}/${kind}/${sha}`;
  if (String(artifact.storage_path || "") !== expected)
    throw new Error("This artifact record does not match its private storage path.");
  return expected;
}

/* Authenticated download with the signed-in user's session. The bucket is
   private: no signed or public URL is created or retained. */
export async function downloadEvolveArtifact(artifact) {
  const path = artifactPath(artifact);
  const { data: blob, error } = await supabase.storage.from(ARTIFACT_BUCKET).download(path);
  if (error)
    throw new Error(
      error.message ||
        "The artifact could not be downloaded. Project access may have changed.",
    );
  if (!blob) throw new Error("The artifact is registered but its stored bytes are missing.");
  return blob;
}

function workItemId(row) {
  const id = row?.id || row?.work_item_id;
  if (!id) throw new Error("The Evolve submission returned no work item.");
  return { ...row, id };
}
