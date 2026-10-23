import { supabase } from "./identity.js";

const WORK_FIELDS = "id,project_id,kind,status,source_url,input_digest,attempts,max_attempts,error_code,created_at,updated_at";
const RUN_FIELDS = "id,work_item_id,attempt,status,phase,source_ref,source_commit,source_digest,result,error_code,started_at,finished_at";
const EVENT_FIELDS = "id,run_id,work_item_id,kind,phase,detail,created_at";
const WORKER_FIELDS = "id,project_id,worker_user_id,label,enabled,created_at,revoked_at";
const MISSING_SCHEMA = new Set(["42P01", "42883", "PGRST202", "PGRST205"]);

function data(result) {
  if (!result.error) return result.data;
  const error = new Error(
    MISSING_SCHEMA.has(result.error.code)
      ? "Repository analysis is unavailable until the durable-runtime migration is applied."
      : result.error.message || "The analysis request failed.",
  );
  error.code = result.error.code;
  throw error;
}

export async function listAnalysisWork(projectId, signal) {
  return data(await supabase.from("work_items").select(WORK_FIELDS)
    .eq("project_id", projectId).order("created_at", { ascending: false })
    .limit(10).abortSignal(signal)) || [];
}

export async function readLatestAnalysis(workItemId, signal) {
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

export async function listProjectWorkers(projectId, signal) {
  return data(await supabase.from("project_workers").select(WORKER_FIELDS)
    .eq("project_id", projectId).order("created_at")
    .limit(50).abortSignal(signal)) || [];
}

export async function submitRepositoryAnalysis(projectId, idempotencyKey) {
  return data(await supabase.rpc("submit_repository_analysis", {
    p_project_id: projectId,
    p_idempotency_key: idempotencyKey,
  }).single());
}

export async function cancelAnalysis(workItemId) {
  return data(await supabase.rpc("cancel_work_item", {
    p_work_item_id: workItemId,
  }).single());
}

export async function registerProjectWorker(projectId, workerUserId, label) {
  const id = workerUserId.trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))
    throw new Error("Enter the dedicated worker's Supabase user ID.");
  return data(await supabase.rpc("register_project_worker", {
    p_project_id: projectId,
    p_worker_user_id: id,
    p_label: label.trim(),
  }).single());
}

export async function revokeProjectWorker(projectId, workerUserId) {
  return data(await supabase.rpc("revoke_project_worker", {
    p_project_id: projectId,
    p_worker_user_id: workerUserId,
  }).single());
}
