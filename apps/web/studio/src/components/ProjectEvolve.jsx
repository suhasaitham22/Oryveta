/* Reviewed Evolve surface for one project.

   Everything shown here is read from durable rows written by an operator-run
   worker: this browser never runs a model, never fabricates a phase and never
   advances a run. Role helpers only shape controls; PostgreSQL RLS and the
   SECURITY DEFINER RPCs authorize every read and write, so a visible button is
   never the thing that permits an approval.

   Approval records a human decision on one exact candidate archive. It does not
   deploy, merge or publish anything. */
import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { downloadBlob } from "@/lib/download";
import { canAdministerProject, canEditProject } from "@/lib/projects";
import { listProjectWorkers } from "@/lib/factoryRuns";
import * as api from "@/lib/evolveRuns";

/* Cancellable, and worth a fast poll: a worker is or should be executing. */
const activeStatuses = new Set(["queued", "running"]);
/* Not terminal, so cached stage/run detail may still change. */
const openStatuses = new Set(["queued", "running", "awaiting_approval"]);
const statusLabels = {
  queued: "Queued",
  running: "Running",
  awaiting_approval: "Awaiting human approval",
  succeeded: "Approved by a human",
  failed: "Failed",
  cancelled: "Canceled",
};
const phaseLabels = {
  claimed: "Claimed by worker",
  fetching_source: "Fetching source snapshot",
  requirements: "Drafting requirements",
  plan: "Planning the change",
  implementation: "Making bounded code changes",
  verification: "Running protected verification",
  audit: "Independent process audit",
  learning: "Extracting lessons",
  learning_review: "Reviewing extracted lessons",
  awaiting_approval: "Waiting for a human decision",
  done: "Finished",
};
const stageLabels = {
  requirements: "Requirements",
  plan: "Plan",
  implementation: "Implementation",
  verification: "Protected verification",
  audit: "Independent process audit",
  learning: "Learning extraction",
  learning_review: "Learning review",
};
const verdictLabels = {
  pass: "Review passed",
  rework: "Review sent back for rework",
  escalate: "Review escalated to a human",
};
const verdictVariants = { pass: "success", rework: "warning", escalate: "warning" };
/* Button names read "Download candidate ZIP", "Download patch", and so on. */
const artifactLabels = {
  candidate: "candidate ZIP",
  patch: "patch",
  receipt: "receipt",
  trace: "trace",
};
const artifactNouns = {
  candidate: "Reviewed candidate archive",
  patch: "Unified patch",
  receipt: "Run receipt",
  trace: "Execution trace",
};
const artifactSuffix = { candidate: "zip", patch: "patch", receipt: "json", trace: "json" };
const lessonStatusLabels = {
  candidate: "Candidate — not yet activated",
  approved: "Activated for this project",
  rejected: "Rejected in review",
  revoked: "Revoked by an admin",
};
const errorLabels = {
  review_rejected: "A review rejected this attempt. Read the stage findings below before submitting a revised goal.",
  verification_failed: "Protected verification did not pass, so no candidate was offered for approval.",
  invalid_baseline: "The baseline could not be established on the pinned snapshot.",
  not_reproduced: "The reported behavior could not be reproduced on the pinned snapshot.",
  no_change: "The attempt produced no code change, so there is nothing to review.",
  process_rejected: "The independent audit rejected the attempt's process evidence.",
  invalid_repository: "The saved source is not a supported public GitHub repository.",
  source_fetch_failed: "The source snapshot could not be fetched. Check the repository or retry later.",
  source_identity_conflict: "The worker's source did not match the pinned revision.",
  source_commit_unresolved: "The source commit could not be resolved safely.",
  control_plane_unavailable: "The worker could not reach the control service. Check service health before retrying.",
  creator_unauthorized: "The requester no longer has permission to run this work.",
  worker_credentials_rejected: "Worker sign-in was rejected. An operator must reauthorize it.",
  worker_storage_error: "The worker could not store its evidence or artifacts.",
  worker_revoked: "The worker's project access was revoked.",
  worker_error: "The worker stopped unexpectedly. An operator can inspect its logs.",
  lease_expired: "The worker lost its lease before completion.",
  attempts_exhausted: "The retry limit was reached. Inspect the failure before submitting again.",
};
const emptyDetails = { workItemId: "", run: null, events: [] };
const emptyEvidence = { runId: "", stages: [], artifacts: [] };
const sourcePattern = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;
const short = (hex) => `${String(hex || "").slice(0, 12)}…`;
const textOf = (value) => (typeof value === "string" ? value : JSON.stringify(value));
/* A recorded false is not the same as an unrecorded field, and neither is "yes". */
const flagLabel = (value) => (value === true ? "yes" : value === false ? "no" : "not recorded");

function bytesLabel(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size < 0) return "unknown size";
  if (size >= 1048576) return `${(size / 1048576).toFixed(1)} MiB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KiB`;
  return `${size} bytes`;
}

function Bullets({ label, items }) {
  const rows = Array.isArray(items) ? items.filter((row) => row !== null && row !== undefined) : [];
  if (!rows.length) return null;
  return (
    <div className="evolve-field">
      <h4>{label}</h4>
      <ul>
        {rows.map((row, index) => (
          <li key={`${index}:${textOf(row)}`}>{textOf(row)}</li>
        ))}
      </ul>
    </div>
  );
}

/* Typed per-stage artifact. Fields are rendered only when the stored payload
   actually has them, so a partially recorded stage reads as incomplete instead
   of as an empty success. */
function StageArtifact({ stage, artifact }) {
  if (!artifact || typeof artifact !== "object")
    return <p className="muted-note">This stage recorded no artifact fields.</p>;
  if (stage === "requirements")
    return (
      <>
        {artifact.goal && <p className="evolve-text">{artifact.goal}</p>}
        <Bullets label="Acceptance criteria" items={artifact.acceptance_criteria} />
        <Bullets label="Constraints" items={artifact.constraints} />
      </>
    );
  if (stage === "plan")
    return (
      <>
        <Bullets label="Steps" items={artifact.steps} />
        <Bullets label="Paths the worker was allowed to change" items={artifact.allowed_paths} />
        <Bullets label="Risks" items={artifact.risks} />
      </>
    );
  if (stage === "implementation")
    return (
      <>
        {artifact.summary && <p className="evolve-text">{artifact.summary}</p>}
        <Bullets label="Changed paths" items={artifact.changed_paths} />
        <dl className="digest-list">
          {artifact.candidate_sha256 && (
            <div>
              <dt>Candidate archive</dt>
              <dd><code>{artifact.candidate_sha256}</code></dd>
            </div>
          )}
          {artifact.patch_sha256 && (
            <div>
              <dt>Patch</dt>
              <dd><code>{artifact.patch_sha256}</code></dd>
            </div>
          )}
        </dl>
      </>
    );
  if (stage === "verification") {
    const checks = Array.isArray(artifact.checks) ? artifact.checks : [];
    return (
      <>
        <ul className="check-list" aria-label="Verification checks">
          {checks.length ? (
            checks.map((check, index) => (
              <li key={`${index}:${check?.name}`}>
                <Badge variant={check?.passed ? "success" : "warning"}>
                  {check?.passed ? "Passed" : "Failed"}
                </Badge>
                <span>{textOf(check?.name)}</span>
              </li>
            ))
          ) : (
            <li className="muted-note">No checks were recorded for this attempt.</li>
          )}
        </ul>
        <p className="meta-line">
          Baseline reproduced: {flagLabel(artifact.baseline_reproduced)} · Existing behavior
          preserved: {flagLabel(artifact.preservation_passed)}
          {artifact.verification ? ` · Verification: ${textOf(artifact.verification)}` : ""}
        </p>
      </>
    );
  }
  if (stage === "audit")
    return (
      <>
        {artifact.summary && <p className="evolve-text">{artifact.summary}</p>}
        <Bullets label="Stages the auditor required" items={artifact.required_stages} />
        {Array.isArray(artifact.violations) && artifact.violations.length ? (
          <Bullets label="Process violations" items={artifact.violations} />
        ) : (
          <p className="muted-note">No process violations were recorded.</p>
        )}
      </>
    );
  if (stage === "learning") {
    const lessons = Array.isArray(artifact.lessons) ? artifact.lessons : [];
    if (!lessons.length)
      return (
        <p className="muted-note">
          No supported lesson was extracted from this attempt. Nothing becomes project memory.
        </p>
      );
    return (
      <ol className="finding-list" aria-label="Extracted lesson candidates">
        {lessons.map((lesson, index) => (
          <li key={`${index}:${lesson?.summary}`}>
            <strong>{textOf(lesson?.summary)}</strong>
            {lesson?.applicability && <code>Applies to: {textOf(lesson.applicability)}</code>}
            <Bullets label="Evidence" items={lesson?.evidence_ids} />
            <Bullets label="Counterexamples" items={lesson?.counterexamples} />
          </li>
        ))}
      </ol>
    );
  }
  if (stage === "learning_review") {
    const decisions = Array.isArray(artifact.decisions) ? artifact.decisions : [];
    if (!decisions.length)
      return <p className="muted-note">No lesson decisions were recorded.</p>;
    return (
      <ul className="check-list" aria-label="Lesson review decisions">
        {decisions.map((decision, index) => (
          <li key={`${index}:${decision?.index}`}>
            <Badge variant={decision?.verdict === "pass" ? "success" : "outline"}>
              {decision?.verdict === "pass" ? "Keep" : "Reject"}
            </Badge>
            <span>
              Lesson {typeof decision?.index === "number" ? decision.index + 1 : "?"} ·{" "}
              {textOf(decision?.reason)}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  return <p className="muted-note">This stage recorded no readable artifact fields.</p>;
}

function FailureReport({ report }) {
  if (!report || typeof report !== "object") return null;
  return (
    <details className="evolve-stage">
      <summary>Failed-attempt evidence</summary>
      {report.failed_stage && <p>Stopped during {textOf(report.failed_stage)}.</p>}
      {Array.isArray(report.checks) && (
        <StageArtifact stage="verification" artifact={{ checks: report.checks }} />
      )}
      <p className="evolve-text">
        Failure learning: {textOf(report.learning_status) || "not recorded"}
        {report.learning_reason ? ` (${textOf(report.learning_reason)})` : ""}.
        Failure lessons are diagnostic only and are not activated as project memory.
      </p>
      {report.learning_status === "reviewed" && (
        <>
          <StageArtifact stage="learning" artifact={report} />
          <StageArtifact stage="learning_review" artifact={report} />
          <p className="meta-line">Lesson reviewer: {textOf(report.reviewer_model)}</p>
        </>
      )}
    </details>
  );
}

/* Observable review evidence exactly as stored: verdict, reasons, the evidence
   references it cited and its findings. */
function StageReview({ review }) {
  if (!review || typeof review !== "object")
    return <p className="muted-note">This stage has no recorded review.</p>;
  const evidenceIds = Array.isArray(review.evidence_ids) ? review.evidence_ids : [];
  const findings = Array.isArray(review.findings) ? review.findings : [];
  return (
    <div className="evolve-review">
      <h4>Review</h4>
      {review.summary && <p className="evolve-text">{review.summary}</p>}
      <p className="meta-line">
        Reviewer {textOf(review.reviewer_model) || "not recorded"}
        {review.reviewer_digest ? ` · model digest ${short(review.reviewer_digest)}` : ""}
      </p>
      {evidenceIds.length ? (
        <ul className="evidence-list" aria-label="Cited review evidence">
          {evidenceIds.map((id, index) => (
            <li key={`${index}:${textOf(id)}`}><code>{textOf(id)}</code></li>
          ))}
        </ul>
      ) : (
        <p className="muted-note">This review cited no evidence references.</p>
      )}
      {findings.length ? (
        <ul className="finding-rows" aria-label="Review findings">
          {findings.map((finding, index) => (
            <li key={`${index}:${textOf(finding?.detail)}`}>
              <Badge variant={finding?.severity === "blocking" ? "warning" : "outline"}>
                {finding?.severity === "blocking" ? "Blocking" : "Warning"}
              </Badge>
              <span>{textOf(finding?.detail)}</span>
              {finding?.evidence_id && <code>{textOf(finding.evidence_id)}</code>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted-note">This review recorded no findings.</p>
      )}
    </div>
  );
}

export default function ProjectEvolve({ project, role }) {
  const [work, setWork] = useState([]);
  const [selected, setSelected] = useState("");
  const [details, setDetails] = useState(emptyDetails);
  const [evidence, setEvidence] = useState(emptyEvidence);
  const [lessons, setLessons] = useState([]);
  const [lessonError, setLessonError] = useState("");
  /* null until read: only project admins may list worker registrations. */
  const [workers, setWorkers] = useState(null);
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");
  const [schemaMissing, setSchemaMissing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState("");
  const [revision, setRevision] = useState(0);
  const cachedDetails = useRef(null);
  /* The exact goal text and source a queued submission was made for, with its
     idempotency key. Kept across an ambiguous failure so a retry cannot queue a
     second attempt; replaced as soon as the goal or the project source differs. */
  const submission = useRef(null);
  /* Every pending callback captures this token. A reply that arrives after this
     panel moved to another project, or unmounted, is dropped instead of writing
     state or a draft that belongs to a newer selection. */
  const token = useRef(0);

  const administer = canAdministerProject(role);
  const edit = canEditProject(role);
  const current = selected ? work.find((item) => item.id === selected) || null : work[0] || null;
  const visibleDetails = details.workItemId === current?.id ? details : emptyDetails;
  const run = visibleDetails.run;
  const visibleEvidence = run && evidence.runId === run.id ? evidence : emptyEvidence;
  const stages = [...visibleEvidence.stages].sort(
    (left, right) =>
      api.STAGE_ORDER.indexOf(left.stage) - api.STAGE_ORDER.indexOf(right.stage) ||
      String(left.created_at).localeCompare(String(right.created_at)),
  );
  const implementation = stages.find((stage) => stage.stage === "implementation")?.payload?.artifact;
  const candidates = visibleEvidence.artifacts.filter((artifact) => artifact.kind === "candidate");
  /* Approval names one archive digest. More than one registered candidate for
     the same attempt is not a choice to make in a dropdown: there is no single
     exact candidate, so nothing is offered for approval. */
  const candidate = candidates.length === 1 ? candidates[0] : null;
  const ambiguousCandidate = candidates.length > 1;
  /* The digest recorded by the implementation stage and the digest of the
     registered archive must be the same bytes. The RPC re-checks this; the UI
     refuses early rather than sending a decision it knows is inconsistent. */
  const candidateMismatch = Boolean(
    candidate && implementation?.candidate_sha256 && implementation.candidate_sha256 !== candidate.sha256,
  );
  const awaiting = current?.status === "awaiting_approval";
  const sourceReady = sourcePattern.test(project.source_url || "");
  const noWorker = administer && workers !== null && !workers.some((worker) => worker.enabled);

  useEffect(() => {
    token.current += 1;
    return () => {
      token.current += 1;
    };
  }, [project.id]);

  useEffect(() => {
    let alive = true;
    let timer;
    let controller;
    let inFlight = false;
    let firstLoad = true;
    setLoading(true);
    setDetails(emptyDetails);
    setEvidence(emptyEvidence);
    setWorkers(null);
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
        const [items, registrations, lessonResult] = await Promise.all([
          api.listEvolveWork(project.id, controller.signal),
          administer ? listProjectWorkers(project.id, controller.signal) : Promise.resolve(null),
          /* Lesson visibility is role-scoped in the database. A refusal there
             must not blank the rest of the panel. */
          api.listEvolveLessons(project.id, controller.signal).then(
            (rows) => ({ rows }),
            (problem) => ({ problem }),
          ),
        ]);
        const item = items.find((entry) => entry.id === selected) || items[0];
        let nextDetails = emptyDetails;
        let nextEvidence = emptyEvidence;
        if (item) {
          const key = `${item.id}:${item.status}:${item.updated_at}`;
          if (!openStatuses.has(item.status) && cachedDetails.current?.key === key) {
            nextDetails = cachedDetails.current.details;
            nextEvidence = cachedDetails.current.evidence;
          } else {
            const read = await api.readLatestEvolveRun(item.id, controller.signal);
            if (!alive) return;
            nextDetails = { ...read, workItemId: item.id };
            if (read.run) {
              const found = await api.readEvolveEvidence(read.run.id, controller.signal);
              if (!alive) return;
              nextEvidence = { ...found, runId: read.run.id };
            }
            cachedDetails.current = { key, details: nextDetails, evidence: nextEvidence };
          }
        } else {
          cachedDetails.current = null;
        }
        if (!alive) return;
        setWork(items);
        if (selected && !items.some((entry) => entry.id === selected)) setSelected(item?.id || "");
        setWorkers(registrations);
        setDetails(item ? { ...nextDetails, workItemId: item.id } : emptyDetails);
        setEvidence(nextEvidence);
        setLessons(lessonResult.rows || []);
        setLessonError(lessonResult.problem?.message || "");
        setLoadError("");
        setSchemaMissing(false);
        timer = setTimeout(
          load,
          items.some((entry) => activeStatuses.has(entry.status))
            ? 5000
            : items.some((entry) => entry.status === "awaiting_approval")
              ? 15000
              : 30000,
        );
      } catch (problem) {
        if (!alive || controller.signal.aborted) return;
        setLoadError(problem.message);
        setSchemaMissing(Boolean(problem.missingSchema));
        setWork([]);
        setWorkers(null);
        setLessons([]);
        setDetails(emptyDetails);
        setEvidence(emptyEvidence);
        cachedDetails.current = null;
        timer = setTimeout(load, 15000);
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
  }, [project.id, selected, revision, administer]);

  /* One place where a write is attempted, its outcome is reported and the panel
     is reloaded. A task returns the sentence to show; a reply that lands after
     this panel moved to another project writes nothing at all. */
  async function action(task) {
    if (busy) return;
    const stamp = token.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const message = await task();
      if (stamp !== token.current) return;
      if (message) setNotice(message);
      setRevision((value) => value + 1);
    } catch (problem) {
      if (stamp !== token.current) return;
      setError(problem.message);
    } finally {
      if (stamp === token.current) setBusy(false);
    }
  }

  async function submit() {
    const text = api.goalText(goal);
    /* A new key for different input; the stored key for the same input, so a
       retry after an ambiguous network failure returns the original work item
       instead of queueing a second attempt. */
    if (submission.current?.goal !== text || submission.current?.source !== project.source_url) {
      submission.current = { goal: text, source: project.source_url, key: crypto.randomUUID() };
    }
    const stamp = token.current;
    const item = await api.submitEvolveWork(project.id, text, submission.current.key);
    submission.current = null;
    /* A reply that lands after the panel moved on must not select work or clear
       a draft that belongs to a newer project. */
    if (stamp !== token.current) return "";
    setSelected(item.id);
    /* Only clear the box if it still holds exactly what was sent. */
    setGoal((value) => (value.trim() === text ? "" : value));
    return item.replayed
      ? "This exact goal was already recorded; showing the existing Evolve work."
      : "Evolve work is recorded. An authorized worker runs it independently of this browser; you can close this tab.";
  }

  /* Decisions report exactly what the server answered, including an idempotent
     repeat and the two outcomes where the server fences the work instead of
     deciding it. None of these is a retryable error. */
  function decisionNotice(row, approve) {
    if (row?.reason === "creator_unauthorized")
      return "Not approved: the account that requested this work no longer has permission to run it, so the server closed the request as failed and discarded the candidate.";
    if (row?.reason === "worker_unauthorized")
      return "Not approved: the worker identity that produced this candidate has been revoked, so the server closed the request as failed and discarded the candidate.";
    if (row?.reason === "already_decided") return "This run was already decided; nothing changed.";
    if (!(row?.approved ?? approve))
      return "Candidate rejected. The request is closed as failed and no lesson was activated.";
    const activated = Number(row?.lessons_activated);
    return `Candidate approved for archive ${short(row?.candidate_sha256)}. ${
      Number.isFinite(activated) && activated > 0
        ? `${activated} reviewed lesson${activated === 1 ? "" : "s"} activated for this project.`
        : "No lesson was activated."
    } Nothing was deployed, merged or published.`;
  }

  async function download(artifact) {
    if (downloading) return;
    const stamp = token.current;
    setDownloading(artifact.id);
    setError("");
    try {
      const blob = await api.downloadEvolveArtifact(artifact);
      if (stamp !== token.current) return;
      downloadBlob(
        `${artifact.kind}-${String(artifact.sha256).slice(0, 12)}.${artifactSuffix[artifact.kind] || "bin"}`,
        blob,
      );
    } catch (problem) {
      if (stamp === token.current) setError(problem.message);
    } finally {
      if (stamp === token.current) setDownloading("");
    }
  }

  return (
    <section className="surface-panel" aria-labelledby="project-evolve-heading" aria-busy={loading}>
      <div className="panel-head">
        <h2 id="project-evolve-heading">Reviewed Evolve</h2>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => {
            setError("");
            setNotice("");
            setRevision((value) => value + 1);
          }}
        >
          Refresh Evolve work
        </Button>
      </div>
      <p className="panel-note">
        Ask for a bounded change to this project's frozen public GitHub snapshot. A supervised
        worker process with a pinned self-hosted model drafts requirements, plans, changes code,
        runs protected verification, audits its own process and extracts lessons — each step
        reviewed and recorded. This browser runs no model and reports only what the worker stored.
        The result is a reviewed candidate for a human to approve; nothing is deployed, merged or
        published to GitHub.
      </p>
      {(error || loadError) && (
        <p role="alert" className="alert-error">
          {error || loadError}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {loading && (
        <p role="status" className="loading-line">
          Loading Evolve work…
        </p>
      )}
      {noWorker && (
        <p className="notice">
          No authorized worker is registered for this project. This browser cannot run inference, so
          submitted work stays queued until an operator runs a supervised worker process with a
          pinned self-hosted model and registers its identity under Repository analysis → Worker
          access.
        </p>
      )}
      {edit && (
        <form
          className="evolve-goal-form"
          onSubmit={(event) => {
            event.preventDefault();
            action(submit);
          }}
        >
          <div className="field-label">
            <label htmlFor="evolve-goal">Change goal</label>
            <Textarea
              id="evolve-goal"
              value={goal}
              maxLength={api.GOAL_LIMIT}
              disabled={busy || schemaMissing}
              placeholder="What should change in the snapshot, and how will we know it worked?"
              onChange={(event) => setGoal(event.target.value)}
            />
          </div>
          <p className="muted-note">
            {goal.trim().length} of {api.GOAL_LIMIT} characters. The goal is stored with the
            request, repeated verbatim by the requirements stage and visible to this project's
            members.
          </p>
          <Button
            type="submit"
            disabled={
              busy || schemaMissing || !sourceReady || goal.trim().length < api.GOAL_MINIMUM
            }
          >
            Submit Evolve work
          </Button>
          {!sourceReady && (
            <p className="muted-note">
              Save a public https://github.com/owner/repository source URL for this project first.
            </p>
          )}
        </form>
      )}
      {!edit && !loading && (
        <p className="muted-note">
          You can read this project's Evolve work and its review evidence. Submitting a goal
          requires an engineer, admin or owner role.
        </p>
      )}
      {!loading && !work.length && !error && !loadError && (
        <p className="loading-line">No Evolve work yet.</p>
      )}
      {work.length > 0 && (
        <div className="field-label">
          <label htmlFor="evolve-work-item">Recent Evolve work</label>
          <select
            id="evolve-work-item"
            value={current?.id || ""}
            onChange={(event) => setSelected(event.target.value)}
          >
            {work.map((item) => (
              <option key={item.id} value={item.id}>
                {statusLabels[item.status] || item.status} ·{" "}
                {new Date(item.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </div>
      )}
      {current && (
        <div className="panel-section">
          <div className="status-row">
            <Badge variant={current.status === "awaiting_approval" ? "warning" : "outline"}>
              {statusLabels[current.status] || current.status}
            </Badge>
            <span>
              Attempt {current.attempts} of {current.max_attempts}
            </span>
            {activeStatuses.has(current.status) && run?.phase && (
              <span>{phaseLabels[run.phase] || run.phase}</span>
            )}
            {/* cancel_work_item fences a running attempt and a request waiting for a
                human decision; it is refused once the item is terminal. */}
            {edit && openStatuses.has(current.status) && (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    const row = await api.cancelEvolveWork(current.id);
                    return row?.already_terminal
                      ? "This Evolve work had already finished; nothing was canceled."
                      : "Cancel recorded. Any running attempt is fenced and no further inference runs.";
                  })
                }
              >
                Cancel Evolve work
              </Button>
            )}
          </div>
          {current.goal && <p className="evolve-text evolve-goal">{current.goal}</p>}
          <p className="meta-line">{current.source_url}</p>
          {current.status === "queued" && (
            <p role="status" className="meta-line">
              Waiting for an authorized worker with a configured self-hosted model. You may close
              this browser.
            </p>
          )}
          {current.error_code && (
            <p className="alert-error">
              {Object.hasOwn(errorLabels, current.error_code)
                ? errorLabels[current.error_code]
                : `Evolve stopped (${current.error_code}).`}
            </p>
          )}
          <FailureReport report={run?.result?.failure_report || run?.result?.learning_unavailable} />
          {run?.source_commit && <p className="meta-line">Source commit: {run.source_commit}</p>}
          {run?.source_digest && <p className="meta-line">Snapshot digest: {run.source_digest}</p>}
          {current.evolve_config_sha256 && (
            <p className="meta-line">Operator configuration: {current.evolve_config_sha256}</p>
          )}
          {current.decided_at && (
            <p className="meta-line">
              Human decision recorded {new Date(current.decided_at).toLocaleString()}
              {current.decided_by ? ` by account ${String(current.decided_by).slice(0, 8)}…` : ""}
            </p>
          )}
          <ol className="event-list findings-scroll" aria-label="Recent Evolve events">
            {visibleDetails.events.map((event) => (
              <li key={event.id}>
                <time dateTime={event.created_at}>
                  {new Date(event.created_at).toLocaleTimeString()}
                </time>{" "}
                · {event.detail}
              </li>
            ))}
          </ol>

          <h3 className="panel-subhead">Reviewed stages</h3>
          {stages.length ? (
            <div className="evolve-stages">
              {stages.map((stage) => (
                <details key={stage.id} className="evolve-stage">
                  <summary>
                    <span>{stageLabels[stage.stage] || stage.stage}</span>
                    {stage.payload?.review?.verdict && (
                      <Badge variant={verdictVariants[stage.payload.review.verdict] || "outline"}>
                        {verdictLabels[stage.payload.review.verdict] || stage.payload.review.verdict}
                      </Badge>
                    )}
                  </summary>
                  <StageArtifact stage={stage.stage} artifact={stage.payload?.artifact} />
                  <dl className="digest-list">
                    {stage.payload?.source_sha256 && (
                      <div>
                        <dt>Snapshot</dt>
                        <dd><code>{stage.payload.source_sha256}</code></dd>
                      </div>
                    )}
                    {stage.payload?.config_sha256 && (
                      <div>
                        <dt>Operator configuration</dt>
                        <dd><code>{stage.payload.config_sha256}</code></dd>
                      </div>
                    )}
                    {stage.payload?.artifact_sha256 && (
                      <div>
                        <dt>Stage artifact</dt>
                        <dd><code>{stage.payload.artifact_sha256}</code></dd>
                      </div>
                    )}
                  </dl>
                  <StageReview review={stage.payload?.review} />
                  <p className="muted-note">
                    Recorded {new Date(stage.created_at).toLocaleString()} · immutable
                  </p>
                </details>
              ))}
            </div>
          ) : (
            <p className="muted-note">
              {run
                ? "No stage has been recorded for this attempt yet."
                : "No attempt has started, so there is no review evidence yet."}
            </p>
          )}

          <h3 className="panel-subhead">Candidate and evidence files</h3>
          {visibleEvidence.artifacts.length ? (
            <ul className="record-list findings-scroll evolve-artifacts" aria-label="Registered Evolve artifacts">
              {visibleEvidence.artifacts.map((artifact) => (
                <li key={artifact.id} className="record">
                  <div className="record-main">
                    <strong>{artifactNouns[artifact.kind] || artifact.kind}</strong>
                    <small>
                      {bytesLabel(artifact.bytes)} · sha256 {short(artifact.sha256)}
                    </small>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={Boolean(downloading)}
                    onClick={() => download(artifact)}
                  >
                    {downloading === artifact.id
                      ? "Downloading…"
                      : `Download ${artifactLabels[artifact.kind] || artifact.kind}`}
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted-note">
              No artifact has been registered for this attempt. Files appear here only after the
              worker uploads and registers them.
            </p>
          )}
          {candidates.length > 0 && (
            <p className="candidate-note">
              A candidate archive is a review candidate, not a deployment. It contains proposed
              source code that has not been merged, released or published anywhere.
            </p>
          )}

          {awaiting && (
            <div className="panel-section">
              <h3 className="panel-subhead">Human approval</h3>
              <p className="muted-note">
                Execution has finished and the worker holds no lease. Approving records a human
                decision on this exact candidate archive digest and activates only the lessons its
                review kept. Rejecting closes the request as failed. Neither action deploys,
                merges or publishes anything.
              </p>
              {candidateMismatch && (
                <p role="alert" className="alert-error">
                  The registered archive digest does not match the digest recorded by the
                  implementation stage, so there is no single exact candidate to approve.
                </p>
              )}
              {ambiguousCandidate && (
                <p role="alert" className="alert-error">
                  More than one candidate archive is registered for this attempt, so there is no
                  single exact candidate to decide. An operator must inspect the run first.
                </p>
              )}
              {!candidate && !ambiguousCandidate && (
                <p className="muted-note">
                  No candidate archive is registered for this run, so it cannot be approved or
                  rejected here. An editor can cancel the request instead.
                </p>
              )}
              {administer ? (
                <div className="status-row decision-row">
                  <Button
                    disabled={busy || !candidate || candidateMismatch}
                    onClick={() =>
                      action(async () =>
                        decisionNotice(
                          await api.decideEvolveWork(current.id, run.id, candidate.sha256, true),
                          true,
                        ),
                      )
                    }
                  >
                    Approve candidate
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy || !candidate}
                    onClick={() =>
                      action(async () =>
                        decisionNotice(
                          await api.decideEvolveWork(current.id, run.id, candidate.sha256, false),
                          false,
                        ),
                      )
                    }
                  >
                    Reject candidate
                  </Button>
                  {candidate && <span>Candidate sha256 {short(candidate.sha256)}</span>}
                </div>
              ) : (
                <p className="muted-note">
                  A project admin or the owner decides this candidate. Your role can read the
                  evidence and download the files.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <details className="disclosure">
        <summary>Project lessons</summary>
        <p className="muted-note">
          Lessons are extracted from this project's own Evolve attempts and reviewed before a human
          approval can activate them. A worker retrieves activated lessons only; candidate, rejected
          and revoked lessons are never used as instructions or authority. No private conversation
          is read into this workflow.
        </p>
        {lessonError && (
          <p role="alert" className="alert-error">
            {lessonError}
          </p>
        )}
        {lessons.length ? (
          <ul className="record-list findings-scroll" aria-label="Project Evolve lessons">
            {lessons.map((lesson) => (
              <li key={lesson.id} className="record">
                <div className="record-main">
                  <strong>{textOf(lesson.lesson?.summary) || "Lesson"}</strong>
                  <small>
                    {typeof lesson.lesson_index === "number"
                      ? `Lesson ${lesson.lesson_index + 1} · `
                      : ""}
                    {lessonStatusLabels[lesson.status] || lesson.status} ·{" "}
                    {lesson.origin === "failure_report" ? "Failure diagnostic · " : ""}
                    {new Date(lesson.created_at).toLocaleString()}
                  </small>
                  {lesson.lesson?.applicability && (
                    <p className="muted-note">Applies to: {textOf(lesson.lesson.applicability)}</p>
                  )}
                  <Bullets label="Evidence" items={lesson.lesson?.evidence_ids} />
                  <Bullets label="Counterexamples" items={lesson.lesson?.counterexamples} />
                  {/* The digests a worker must match to retrieve this lesson at all:
                      the snapshot and operator configuration it was learned from. */}
                  {(lesson.source_sha256 || lesson.config_sha256) && (
                    <dl className="digest-list">
                      {lesson.source_sha256 && (
                        <div>
                          <dt>Retrievable only for snapshot</dt>
                          <dd><code>{lesson.source_sha256}</code></dd>
                        </div>
                      )}
                      {lesson.config_sha256 && (
                        <div>
                          <dt>and operator configuration</dt>
                          <dd><code>{lesson.config_sha256}</code></dd>
                        </div>
                      )}
                    </dl>
                  )}
                  {lesson.revoked_at && (
                    <p className="muted-note">
                      Revoked {new Date(lesson.revoked_at).toLocaleString()}
                    </p>
                  )}
                </div>
                {administer && (lesson.status === "approved" || lesson.status === "candidate") && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    aria-label={`Revoke lesson ${textOf(lesson.lesson?.summary) || lesson.id}`}
                    onClick={() =>
                      action(async () => {
                        const row = await api.revokeEvolveLesson(lesson.id);
                        return row?.already_revoked
                          ? "That lesson was already revoked."
                          : "Lesson revoked. No worker retrieves it again.";
                      })
                    }
                  >
                    Revoke lesson
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted-note">
            {administer
              ? "No lesson has been extracted for this project yet."
              : "No activated lesson is visible for your role in this project."}
          </p>
        )}
      </details>
    </section>
  );
}
