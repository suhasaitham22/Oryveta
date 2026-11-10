import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { downloadJson } from "@/lib/download";
import { canAdministerProject, canEditProject } from "@/lib/projects";
import * as api from "@/lib/repairRuns";

/* Controlled repair, separate from the read-only Repository analysis panel. Everything on
   screen is a persisted row: approved policies, the frozen source and configuration
   identity they were enrolled with, the last authenticated worker poll, the phase and
   checkpoint a worker actually wrote, and the bounded result it recorded. There is no
   simulated progress, no uptime claim, and a recorded candidate is only ever "ready for
   review": nothing here commits, merges, applies or deploys a patch. PostgreSQL authorizes
   every action; the role checks below only shape which controls are rendered. */

const activeStatuses = new Set(["queued", "running"]);
const statusLabels = {
  queued: "Queued", running: "Running", succeeded: "Ready for review",
  failed: "Failed", cancelled: "Canceled",
};
const phaseLabels = {
  claimed: "Claimed by worker", fetching_source: "Fetching approved commit",
  repairing: "Attempting repair", verifying: "Running operator checks",
  recording_result: "Recording result", done: "Finished",
};
/* The worker's derived checkpoint step enum. */
const stepLabels = {
  fetching_source: "Fetching approved commit", snapshot_ready: "Snapshot ready",
  repairing: "Attempting repair", verifying: "Running operator checks",
  recording_result: "Recording result",
};
/* Only these checkpoint keys are shown, in this order. An unknown key is ignored rather
   than printed: durable progress is a fixed set of counters, not a message channel, and a
   counter the worker has not written yet is simply absent instead of shown as zero. */
const progressOrder = [
  ["step", "Step"],
  ["turns", "Model turns"],
  ["tool_calls", "Tool calls"],
  ["tokens_observed", "Tokens observed"],
  ["unsettled_token_reservation", "Unsettled token reservation"],
  ["elapsed_seconds", "Elapsed seconds"],
  ["archive_entries", "Archive entries"],
  ["archive_bytes", "Archive bytes"],
  ["source_pinned", "Approved commit pinned"],
  ["source_commit", "Source commit"],
  ["configuration_sha256", "Configuration digest"],
];
/* Bounded failure codes the queue or the worker can record. An unknown code is printed as
   itself rather than guessed at. */
const errorLabels = {
  invalid_repository: "The enrolled source is not a supported public GitHub repository.",
  invalid_source: "The fetched snapshot was not a usable source tree.",
  source_fetch_failed: "The approved commit could not be fetched. Check the repository or retry later.",
  source_identity_conflict: "The worker's source did not match the commit this policy pinned.",
  source_commit_unresolved: "The approved commit could not be resolved safely.",
  configuration_mismatch: "The worker's configuration digest no longer matches the enrolled policy.",
  policy_mismatch: "The worker's startup inputs did not match this policy, so it refused the work.",
  invalid_config: "The worker refused its own configuration, so no attempt was made.",
  invalid_goal: "The worker refused the goal text as unusable for a bounded attempt.",
  control_plane_unavailable: "The worker could not reach the control service. Check service health before retrying.",
  creator_unauthorized: "The requester no longer has permission to run repairs on this project.",
  policy_revoked: "The repair policy was revoked while this item was outstanding.",
  worker_revoked: "The worker's project access was revoked.",
  worker_identity_deleted: "The enrolled worker account was deleted; this policy can no longer authorize work.",
  worker_credentials_rejected: "Worker sign-in was rejected. An operator must reauthorize it.",
  worker_storage_error: "The worker could not store its temporary run data.",
  worker_error: "The worker stopped unexpectedly. An operator can inspect its logs.",
  lease_expired: "The worker lost its lease before completion.",
  cancelled: "The repair was canceled before a result was recorded.",
  repair_cancelled: "The worker stopped the attempt after cancellation was requested.",
  attempts_exhausted: "Both attempts were used. Inspect the failure before queuing another goal.",
  repair_timeout: "The attempt reached its bounded deadline before a candidate passed every check.",
  repair_process_failed: "The repair process failed. An operator can inspect the worker logs.",
  repair_output_invalid: "The recorded output did not satisfy the result contract, so nothing was accepted.",
  repair_result_too_large: "The candidate patch exceeded the stored result limit, so it was refused rather than truncated.",
  repair_failed: "The attempt stopped on a worker-side failure. An operator can inspect the private receipt.",
  verification_failed: "The candidate did not pass the operator's checks, so no patch is offered for review.",
  not_reproduced: "The defect did not reproduce against the approved commit, so no repair was attempted.",
  invalid_baseline: "The baseline checks did not hold on the unmodified source.",
  no_change: "The attempt produced no change to review.",
  no_progress: "The attempt stopped making progress before a candidate was complete.",
  candidate_scope: "The candidate edited files outside the operator's write allowlist and was refused.",
  candidate_inventory: "The candidate added or removed files and was refused.",
  candidate_limit: "The candidate exceeded the operator's size limit.",
  turn_budget: "The attempt reached the operator's model-turn budget.",
  tool_budget: "The attempt reached the operator's tool-call budget.",
  token_budget: "The attempt reached the operator's token budget.",
  context_budget: "The attempt reached the model's usable context budget.",
  wall_budget: "The attempt reached the operator's wall-clock budget.",
  trace_limit: "The attempt produced more private trace data than the operator's limit allows.",
  model_unavailable: "The operator's local model was unavailable to the worker.",
  model_timeout: "The local model did not answer within its bounded deadline.",
  model_changed: "The local model digest drifted from the approved configuration.",
  provider_contract: "The local model returned a reply the worker refused to accept.",
  evidence_write_failed: "The worker could not write its private evidence, so no result was published.",
  runner_context: "The worker could not resolve a trusted container context for the checks.",
  runner_daemon: "The worker could not reach its container daemon.",
  runner_image: "The configured container image was unavailable to the worker.",
  runner_create: "A check container could not be created.",
  runner_start: "A check container could not be started.",
  runner_state: "A check container ended in a state the worker refused to trust.",
  runner_timeout: "An isolated check outlived its supervision window.",
  runner_oom: "An isolated check exhausted the operator's memory limit.",
  runner_setup: "The worker's isolated runner could not start a check.",
  runner_cleanup: "The worker could not clean up a check container.",
  runner_cli: "The worker's container command line failed.",
  runner_output_limit: "A check produced more output than the operator's limit allows.",
  runner_unusable: "The worker's container runner was unusable on this host.",
};
const emptyDetails = { workItemId: "", run: null, events: [] };
const emptyPolicyForm = { workerUserId: "", label: "", sourceCommit: "", configurationSha256: "" };
/* A poll older than this is reported as "no recent contact". It is a statement about the
   last authenticated poll, never a capacity or uptime guarantee. */
const CONTACT_WINDOW_MS = 5 * 60 * 1000;

const shortHash = (value) => (value ? `${String(value).slice(0, 12)}…` : "—");
const count = (value) =>
  typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US") : String(value ?? "");
const stamp = (value) => (value ? new Date(value).toLocaleString() : "");

/* Renders one persisted checkpoint value: the step enum gets a readable label, a flag gets
   yes or no, elapsed time keeps one fractional digit, and anything else is shown as the
   worker wrote it. */
function progressValue(key, value) {
  if (key === "step") return stepLabels[value] || String(value ?? "");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key === "elapsed_seconds" && typeof value === "number" && Number.isFinite(value))
    return `${value.toFixed(1)} s`;
  return count(value);
}

function contactLine(policy) {
  if (!policy?.last_seen_at) return "No authenticated worker poll recorded yet.";
  const seen = new Date(policy.last_seen_at);
  const recent = Date.now() - seen.getTime() < CONTACT_WINDOW_MS;
  return `Last authenticated worker poll ${seen.toLocaleString()}${recent ? "" : " (nothing more recent)"}.`;
}

/* What a queued item is actually waiting for. A queue is not progress, so this says who
   has to act next instead of implying that something is already running. */
function queuedLine(policy) {
  if (!policy) return "Queued. The policy this item was admitted under is no longer readable here.";
  if (!policy.enabled) return "This policy is revoked, so the item is being settled rather than left queued.";
  const recent = Date.now() - new Date(policy.last_seen_at || 0).getTime() < CONTACT_WINDOW_MS;
  return recent
    ? "Waiting for the enrolled worker to claim it. You can close this browser; nothing runs here."
    : "Waiting for the enrolled worker. No authenticated poll was recorded in the last five minutes, so this stays queued until the operator's worker polls again. Nothing is running yet.";
}

export default function ProjectRepairs({ project, role }) {
  const [policies, setPolicies] = useState([]);
  const [work, setWork] = useState([]);
  const [selected, setSelected] = useState("");
  const [details, setDetails] = useState(emptyDetails);
  const [policyChoice, setPolicyChoice] = useState("");
  const [goal, setGoal] = useState("");
  const [policyForm, setPolicyForm] = useState(emptyPolicyForm);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");
  const [setup, setSetup] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const cachedDetails = useRef(null);
  /* The idempotency key is reused while the submitted policy and goal are unchanged, so a
     retried submission cannot create a second work item for the same request. */
  const submission = useRef(null);

  const administer = canAdministerProject(role);
  const edit = canEditProject(role);
  const enabledPolicies = policies.filter((policy) => policy.enabled);
  /* Derived rather than synchronized: a refresh can never move the operator's choice. */
  const chosenPolicy = enabledPolicies.some((policy) => policy.id === policyChoice)
    ? policyChoice
    : enabledPolicies[0]?.id || "";
  const current = selected ? work.find((item) => item.id === selected) || null : work[0] || null;
  /* Details belong to one work item: a result for a previous selection is never shown. */
  const visibleDetails = details.workItemId === current?.id ? details : emptyDetails;
  const run = visibleDetails.run;
  const result = api.readRepairResult(run);
  const currentPolicy = current ? policies.find((policy) => policy.id === current.repair_policy_id) || null : null;
  const checkpoint = run?.checkpoint && typeof run.checkpoint === "object" ? run.checkpoint : {};
  const progress = progressOrder.filter(([key]) => Object.hasOwn(checkpoint, key));
  const bytes = api.goalBytes(goal.trim());
  const goalTooLong = bytes > api.GOAL_MAX_BYTES;
  const resultUnreadable = current?.status === "succeeded" && !!run?.result && !result;
  /* Enrollment freezes the project's saved source, so there has to be one to freeze. */
  const sourceReady = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(project.source_url || "");

  useEffect(() => {
    let alive = true;
    let timer;
    let controller;
    let inFlight = false;
    let firstLoad = true;
    setLoading(true);
    setDetails(emptyDetails);
    setPolicies([]);
    async function load() {
      if (!alive || inFlight) return;
      if (document.hidden) {
        setLoading(false);
        timer = setTimeout(load, 5000);
        return;
      }
      inFlight = true;
      if (firstLoad) setLoading(true);
      controller = new AbortController();
      try {
        const [approved, items] = await Promise.all([
          api.listRepairPolicies(project.id, controller.signal),
          api.listRepairWork(project.id, controller.signal),
        ]);
        const item = items.find((entry) => entry.id === selected) || items[0];
        let next = emptyDetails;
        if (item) {
          const key = `${item.id}:${item.status}:${item.updated_at}`;
          if (!activeStatuses.has(item.status) && cachedDetails.current?.key === key) {
            next = cachedDetails.current.value;
          } else {
            next = await api.readLatestRepairRun(item.id, controller.signal);
            if (!alive) return;
            cachedDetails.current = { key, value: next };
          }
        } else {
          cachedDetails.current = null;
        }
        if (!alive) return;
        setPolicies(approved);
        setWork(items);
        if (selected && !items.some((entry) => entry.id === selected)) setSelected(item?.id || "");
        setDetails({ ...next, workItemId: item?.id || "" });
        setLoadError("");
        setSetup("");
        timer = setTimeout(load, items.some((entry) => activeStatuses.has(entry.status)) ? 5000 : 15000);
      } catch (problem) {
        if (!alive || controller.signal.aborted) return;
        /* A missing migration is a setup state, not a failure of this request. */
        if (problem.setup) {
          setSetup(problem.message);
          setLoadError("");
        } else {
          setLoadError(problem.message);
          setSetup("");
        }
        setPolicies([]);
        setWork([]);
        setDetails(emptyDetails);
        cachedDetails.current = null;
        timer = setTimeout(load, problem.setup ? 60000 : 15000);
      } finally {
        inFlight = false;
        firstLoad = false;
        if (alive) setLoading(false);
      }
    }
    function wake() {
      if (!document.hidden && !inFlight) {
        clearTimeout(timer);
        load();
      }
    }
    document.addEventListener("visibilitychange", wake);
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
      controller?.abort();
    };
  }, [project.id, selected, revision]);

  async function action(mutation) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await mutation();
      setRevision((value) => value + 1);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    const text = api.normalizeGoal(goal);
    if (submission.current?.policy !== chosenPolicy || submission.current?.goal !== text) {
      submission.current = { policy: chosenPolicy, goal: text, key: crypto.randomUUID() };
    }
    const queued = await api.submitRepositoryRepair(project.id, chosenPolicy, text, submission.current.key);
    submission.current = null;
    /* Only the text that was submitted is cleared; anything typed since is kept. */
    setGoal((value) => (value.trim() === text ? "" : value));
    setSelected(queued.work_item_id);
    setNotice(
      queued.replayed
        ? "That goal was already queued under this policy. The existing work item is shown."
        : "Queued for the enrolled worker. Progress is persisted, so you can close this browser.",
    );
  }

  async function revoke(policy) {
    const outcome = await api.revokeRepairPolicy(policy.id);
    const fenced = Number(outcome?.fenced_runs || 0);
    setNotice(
      `Policy "${policy.label}" is revoked. ${fenced
        ? `${count(fenced)} outstanding ${fenced === 1 ? "run was" : "runs were"} settled.`
        : "No outstanding run had to be settled."}`,
    );
  }

  return (
    <section className="surface-panel" aria-labelledby="project-repairs-heading" aria-busy={loading}>
      <div className="panel-head">
        <h2 id="project-repairs-heading">Controlled repair</h2>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => { setError(""); setNotice(""); setRevision((value) => value + 1); }}
        >
          Refresh repairs
        </Button>
      </div>
      <p className="panel-note">
        Queue a bounded goal against an approved repair policy. A dedicated worker your operator provisioned
        polls for the work independently of this browser, fetches only the commit the policy pinned and attempts
        one checked change. A result arrives as a patch marked ready for review: nothing is committed, merged,
        applied or deployed for you.
      </p>
      {setup && (
        <p role="status" className="notice">
          {setup}{" "}
          {administer
            ? "An operator applies the durable repair migration to this database, then enrolls a policy here."
            : "An operator must apply the durable repair migration before repairs can be queued."}
        </p>
      )}
      {(error || loadError) && <p role="alert" className="alert-error">{error || loadError}</p>}
      {notice && <p role="status" className="notice">{notice}</p>}
      {loading && <p role="status" className="loading-line">Loading controlled repairs…</p>}

      {!setup && (
        <div className="panel-section">
          <h3 className="panel-subhead">Approved policies</h3>
          <p className="muted-note">
            A policy binds one project to one already-registered worker identity, one pinned commit and one
            configuration digest the operator reviewed. The configuration itself—commands, checks, file grants,
            model and budgets—stays on the operator's host and is never uploaded or edited here.
          </p>
          {!loading && !loadError && !policies.length && (
            <p className="loading-line">
              {administer
                ? "No repair policy is enrolled yet. Register the dedicated worker under Worker access in Repository analysis, then enroll it below."
                : "No repair policy is enrolled yet. An owner or admin must enroll one before a goal can be queued. Nothing is queued or running."}
            </p>
          )}
          {policies.length > 0 && (
            <ul className="record-list" aria-label="Approved repair policies">
              {policies.map((policy) => (
                <li key={policy.id} className="record">
                  <div className="record-main">
                    <strong>
                      {policy.label} · {policy.enabled ? "Enabled" : "Revoked"}
                    </strong>
                    <small>
                      {policy.source_owner}/{policy.source_repo} · commit {policy.source_commit}
                    </small>
                    <small>Configuration SHA-256 {policy.configuration_sha256}</small>
                    <small>
                      Worker account {policy.worker_user_id || policy.worker_identity}
                      {!policy.worker_user_id && " (identity deleted)"}
                    </small>
                    <small>
                      {policy.enabled
                        ? `${contactLine(policy)} A poll records authentication only; it is not a guarantee of availability, capacity or uptime.`
                        : `Revoked ${stamp(policy.revoked_at)}.`}
                    </small>
                  </div>
                  {administer && policy.enabled && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      aria-label={`Revoke repair policy ${policy.label}`}
                      onClick={() => action(() => revoke(policy))}
                    >
                      Revoke policy
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!setup && edit && (
        <div className="panel-section">
          <h3 className="panel-subhead">Queue a repair goal</h3>
          {enabledPolicies.length > 1 && (
            <div className="field-label">
              <label htmlFor="repair-policy-choice">Repair policy</label>
              <select
                id="repair-policy-choice"
                value={chosenPolicy}
                onChange={(event) => setPolicyChoice(event.target.value)}
              >
                {enabledPolicies.map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {policy.label} · {policy.source_commit.slice(0, 12)}…
                  </option>
                ))}
              </select>
            </div>
          )}
          <form
            className="inline-fields"
            onSubmit={(event) => {
              event.preventDefault();
              action(submit);
            }}
          >
            <div className="field-label">
              <label htmlFor="repair-goal">What should the worker attempt?</label>
              <Textarea
                id="repair-goal"
                rows={4}
                maxLength={api.GOAL_MAX_BYTES}
                value={goal}
                aria-describedby="repair-goal-audience repair-goal-count"
                placeholder="One bounded change: the behaviour that is wrong and what done looks like."
                onChange={(event) => setGoal(event.target.value)}
              />
            </div>
            <p id="repair-goal-audience" className="muted-note">
              Submitting shares this text with every member of this project and sends it to the enrolled worker.
              Nothing is copied from your private conversations: only what you type here is submitted.
            </p>
            <p id="repair-goal-count" className={goalTooLong ? "alert-error" : "muted-note"}>
              {count(bytes)} of {count(api.GOAL_MAX_BYTES)} bytes.
            </p>
            {!!enabledPolicies.length && (
              <p className="muted-note">
                Queues against {enabledPolicies.find((policy) => policy.id === chosenPolicy)?.label} at commit{" "}
                {enabledPolicies.find((policy) => policy.id === chosenPolicy)?.source_commit}. Each item gets at
                most two attempts against that same commit.
              </p>
            )}
            <Button type="submit" disabled={busy || !chosenPolicy || !bytes || goalTooLong}>
              Queue repair under this policy
            </Button>
            {!enabledPolicies.length && !loading && !loadError && (
              <p className="muted-note">An enabled repair policy is required before a goal can be queued.</p>
            )}
          </form>
        </div>
      )}
      {!setup && !edit && !loading && (
        <p className="muted-note">
          Your project role can review repairs and their recorded results but cannot queue, cancel or enroll one.
        </p>
      )}

      {!setup && !loading && !work.length && !loadError && (
        <p className="loading-line">No repairs have been queued for this project yet.</p>
      )}
      {work.length > 0 && (
        <div className="field-label">
          <label htmlFor="repair-work-item">Recent repairs</label>
          <select
            id="repair-work-item"
            value={current?.id || ""}
            onChange={(event) => setSelected(event.target.value)}
          >
            {work.map((item) => (
              <option key={item.id} value={item.id}>
                {statusLabels[item.status] || item.status} · {new Date(item.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </div>
      )}

      {current && (
        <div className="panel-section">
          <div className="status-row">
            <Badge variant="outline">{statusLabels[current.status] || current.status}</Badge>
            <span>Attempt {current.attempts} of {current.max_attempts}</span>
            {activeStatuses.has(current.status) && run?.phase && (
              <span>{phaseLabels[run.phase] || run.phase}</span>
            )}
            {edit && activeStatuses.has(current.status) && (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => action(() => api.cancelRepair(current.id))}
              >
                Cancel repair
              </Button>
            )}
          </div>
          <p className="meta-line">Goal: {current.goal}</p>
          <p className="meta-line">
            {current.source_url} · pinned commit {current.pinned_source_commit || "not pinned"}
          </p>
          {currentPolicy && (
            <p className="meta-line">
              Policy {currentPolicy.label} · configuration {shortHash(currentPolicy.configuration_sha256)}
              {currentPolicy.enabled ? "" : " · revoked"}
            </p>
          )}
          {current.status === "queued" && (
            <p role="status" className="meta-line">{queuedLine(currentPolicy)}</p>
          )}
          {current.status === "running" && (
            <p role="status" className="meta-line">
              A worker holds a lease on this attempt. Progress below is what the worker has written down.
            </p>
          )}
          {current.error_code && (
            <p className="alert-error">
              {Object.hasOwn(errorLabels, current.error_code)
                ? errorLabels[current.error_code]
                : `Repair stopped (${current.error_code}).`}
              {current.status === "queued" ? " A second attempt is scheduled against the same commit." : ""}
            </p>
          )}
          {run?.source_commit && <p className="meta-line">Fetched commit: {run.source_commit}</p>}
          {run?.source_digest && <p className="meta-line">Snapshot: {run.source_digest}</p>}
          {progress.length > 0 && (
            <dl className="repair-progress" aria-label="Recorded worker progress">
              {progress.map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>{progressValue(key, checkpoint[key])}</dd>
                </div>
              ))}
            </dl>
          )}
          <ol className="event-list" aria-label="Recent repair events">
            {visibleDetails.events.map((event) => (
              <li key={event.id}>
                <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString()}</time> ·{" "}
                {event.detail || event.kind}
              </li>
            ))}
          </ol>
          {resultUnreadable && (
            <p role="alert" className="alert-error">
              A completion was recorded whose result does not match the published repair contract, so no patch is
              offered for review.
            </p>
          )}
          {result && (
            <div className="summary-block">
              <p>
                Ready for review · {count(result.checks_passed)} operator-owned checks passed on the candidate ·{" "}
                {count(result.turns)} model turns · {count(result.tool_calls)} tool calls ·{" "}
                {count(result.tokens_observed)} tokens observed
              </p>
              <p className="muted-note">
                A human review is the next step. Nothing was committed, pushed, merged, applied or deployed, and
                passing the operator's checks is evidence about those checks only.
              </p>
              <dl className="repair-receipt" aria-label="Repair result receipt">
                <div><dt>Model</dt><dd>{result.model_name}</dd></div>
                <div><dt>Model digest</dt><dd>{result.model_digest}</dd></div>
                <div><dt>Source commit</dt><dd>{result.source_commit}</dd></div>
                <div><dt>Source tree</dt><dd>{result.source_tree_sha256}</dd></div>
                <div><dt>Candidate tree</dt><dd>{result.candidate_tree_sha256}</dd></div>
                <div><dt>Patch SHA-256</dt><dd>{result.patch_sha256}</dd></div>
                <div><dt>Configuration</dt><dd>{result.configuration_sha256}</dd></div>
              </dl>
              <figure className="repair-patch">
                <figcaption>Proposed patch · needs review</figcaption>
                <pre tabIndex={0} aria-label="Proposed patch"><code>{result.patch}</code></pre>
              </figure>
              <div className="repair-downloads">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => api.downloadPatch(`repair-${current.id}.patch`, result.patch)}
                >
                  Download patch (.patch)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadJson(`repair-${current.id}.json`, result)}
                >
                  Download repair record (JSON)
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {!setup && administer && (
        <details className="disclosure">
          <summary>Enroll a repair policy</summary>
          <p className="muted-note">
            Enrollment records an approval; it installs nothing and designates no worker. Provision the worker
            identity through operator setup and register it for this project first. The commit and configuration
            digest come from the operator's reviewed configuration and are frozen: a change needs a new policy.
            Never paste credentials, commands or configuration content into this form.
          </p>
          <form
            className="inline-fields"
            onSubmit={(event) => {
              event.preventDefault();
              action(async () => {
                await api.registerRepairPolicy(project.id, policyForm);
                setPolicyForm(emptyPolicyForm);
                setNotice("Repair policy enrolled. Engineers and above can now queue a goal under it.");
              });
            }}
          >
            <div className="field-label">
              <label htmlFor="repair-policy-worker">Dedicated worker user ID</label>
              <Input
                id="repair-policy-worker"
                required
                value={policyForm.workerUserId}
                onChange={(event) => setPolicyForm((form) => ({ ...form, workerUserId: event.target.value }))}
              />
            </div>
            <div className="field-label">
              <label htmlFor="repair-policy-label">Policy label</label>
              <Input
                id="repair-policy-label"
                required
                maxLength={api.LABEL_MAX}
                value={policyForm.label}
                onChange={(event) => setPolicyForm((form) => ({ ...form, label: event.target.value }))}
              />
            </div>
            <div className="field-label">
              <label htmlFor="repair-policy-commit">Approved commit SHA (40 hex)</label>
              <Input
                id="repair-policy-commit"
                required
                maxLength={40}
                spellCheck={false}
                value={policyForm.sourceCommit}
                onChange={(event) => setPolicyForm((form) => ({ ...form, sourceCommit: event.target.value }))}
              />
            </div>
            <div className="field-label">
              <label htmlFor="repair-policy-config">Configuration SHA-256 (64 hex)</label>
              <Input
                id="repair-policy-config"
                required
                maxLength={64}
                spellCheck={false}
                value={policyForm.configurationSha256}
                onChange={(event) =>
                  setPolicyForm((form) => ({ ...form, configurationSha256: event.target.value }))
                }
              />
            </div>
            <Button type="submit" disabled={busy || !sourceReady}>Enroll repair policy</Button>
            {!sourceReady && (
              <p className="muted-note">
                Save a public https://github.com/owner/repository source URL on this project first: a policy
                freezes the source it was approved with.
              </p>
            )}
          </form>
          <p className="muted-note">
            The enrolled source is derived from this project's saved repository URL. If that URL changes, enroll a
            new policy: an existing one keeps the source it was approved with.
          </p>
        </details>
      )}
    </section>
  );
}
