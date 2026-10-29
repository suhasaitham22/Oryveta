import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { downloadJson } from "@/lib/download";
import { canAdministerProject, canEditProject } from "@/lib/projects";
import * as api from "@/lib/factoryRuns";

const activeStatuses = new Set(["queued", "running"]);
const statusLabels = {
  queued: "Queued", running: "Running", succeeded: "Completed",
  failed: "Failed", cancelled: "Canceled",
};
const emptyDetails = { workItemId: "", run: null, events: [] };
const phaseLabels = {
  claimed: "Claimed by worker", fetching_source: "Fetching source",
  analyzing: "Analyzing snapshot", recording_result: "Recording result", done: "Finished",
};
const errorLabels = {
  invalid_repository: "The saved source is not a supported public GitHub repository.",
  source_fetch_failed: "The source snapshot could not be fetched. Check the repository or retry later.",
  control_plane_unavailable: "The worker could not reach the control service. Check service health before retrying.",
  creator_unauthorized: "The requester no longer has permission to run this analysis.",
  source_identity_conflict: "The worker's source did not match the pinned revision.",
  source_commit_unresolved: "The source commit could not be resolved safely.",
  analysis_timeout: "Analysis reached its execution deadline.",
  analysis_process_failed: "The analysis process failed. An operator can inspect the worker logs.",
  analysis_output_invalid: "The analysis result did not satisfy the evidence contract.",
  worker_credentials_rejected: "Worker sign-in was rejected. An operator must reauthorize it.",
  worker_storage_error: "The worker could not store its temporary analysis data.",
  worker_error: "The worker stopped unexpectedly. An operator can inspect its logs.",
  lease_expired: "The worker lost its lease before completion.",
  attempts_exhausted: "The retry limit was reached. Inspect the failure before submitting again.",
  worker_revoked: "The worker's project access was revoked.",
};

export default function ProjectAnalysis({ project, role }) {
  const [work, setWork] = useState([]);
  const [selected, setSelected] = useState("");
  const [details, setDetails] = useState(emptyDetails);
  const [workers, setWorkers] = useState([]);
  const [workerId, setWorkerId] = useState("");
  const [workerLabel, setWorkerLabel] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const cachedDetails = useRef(null);
  const submission = useRef(null);
  const administer = canAdministerProject(role);
  const edit = canEditProject(role);
  const current = selected ? work.find((item) => item.id === selected) || null : work[0] || null;
  const visibleDetails = details.workItemId === current?.id ? details : emptyDetails;
  const summary = visibleDetails.run?.result?.summary;
  const findings = visibleDetails.run?.result?.findings || [];
  const truncated = summary && (summary.findings_truncated || summary.findings_persisted_truncated || findings.length < summary.findings_count);
  const sourceReady = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(project.source_url || "");

  useEffect(() => {
    let alive = true;
    let timer;
    let controller;
    let inFlight = false;
    let firstLoad = true;
    setLoading(true);
    setDetails(emptyDetails);
    setWorkers([]);
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
        const [items, registrations] = await Promise.all([
          api.listAnalysisWork(project.id, controller.signal),
          administer ? api.listProjectWorkers(project.id, controller.signal) : Promise.resolve([]),
        ]);
        const item = items.find((entry) => entry.id === selected) || items[0];
        let next = emptyDetails;
        if (item) {
          const key = `${item.id}:${item.status}:${item.updated_at}`;
          if (!activeStatuses.has(item.status) && cachedDetails.current?.key === key) {
            next = cachedDetails.current.value;
          } else {
            next = await api.readLatestAnalysis(item.id, controller.signal);
            if (!alive) return;
            cachedDetails.current = { key, value: next };
          }
        } else {
          cachedDetails.current = null;
        }
        if (!alive) return;
        setWork(items);
        if (selected && !items.some((entry) => entry.id === selected)) setSelected(item?.id || "");
        setWorkers(registrations);
        setDetails({ ...next, workItemId: item?.id || "" });
        setLoadError("");
        timer = setTimeout(load, items.some((entry) => activeStatuses.has(entry.status)) ? 5000 : 15000);
      } catch (problem) {
        if (!alive || controller.signal.aborted) return;
        setLoadError(problem.message);
        setWork([]);
        setWorkers([]);
        setDetails(emptyDetails);
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

  async function action(run) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await run();
      setRevision((value) => value + 1);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (submission.current?.source !== project.source_url) {
      submission.current = { source: project.source_url, key: crypto.randomUUID() };
    }
    const result = await api.submitRepositoryAnalysis(project.id, submission.current.key);
    submission.current = null;
    setSelected(result.work_item_id);
  }

  return (
    <section className="surface-panel" aria-labelledby="project-analysis-heading" aria-busy={loading}>
      <div className="panel-head">
        <h2 id="project-analysis-heading">Repository analysis</h2>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => { setError(""); setRevision((value) => value + 1); }}>
          Refresh analyses
        </Button>
      </div>
      <p className="panel-note">
        Queue a bounded, read-only review of a public GitHub snapshot. An authorized worker processes it independently of this browser; repository code is never executed.
      </p>
      {(error || loadError) && <p role="alert" className="alert-error">{error || loadError}</p>}
      {loading && <p role="status" className="loading-line">Loading repository analyses…</p>}
      {edit && (
        <div className="panel-action">
          <Button disabled={busy || !sourceReady} onClick={() => action(submit)}>
            Analyze public repository
          </Button>
          {!sourceReady && <p className="muted-note">Save a public https://github.com/owner/repository source URL first.</p>}
        </div>
      )}
      {!loading && !work.length && !error && !loadError && <p className="loading-line">No repository analyses yet.</p>}
      {work.length > 0 && (
        <div className="field-label">
          <label htmlFor="analysis-work-item">Recent analyses</label>
          <select id="analysis-work-item" value={current?.id || ""} onChange={(event) => setSelected(event.target.value)}>
            {work.map((item) => <option key={item.id} value={item.id}>{statusLabels[item.status] || item.status} · {new Date(item.created_at).toLocaleString()}</option>)}
          </select>
        </div>
      )}
      {current && (
        <div className="panel-section">
          <div className="status-row">
            <Badge variant="outline">{statusLabels[current.status] || current.status}</Badge>
            <span>Attempt {current.attempts} of {current.max_attempts}</span>
            {activeStatuses.has(current.status) && visibleDetails.run?.phase && (
              <span>{phaseLabels[visibleDetails.run.phase] || visibleDetails.run.phase}</span>
            )}
            {edit && activeStatuses.has(current.status) && (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => action(() => api.cancelAnalysis(current.id))}>Cancel analysis</Button>
            )}
          </div>
          <p className="meta-line">{current.source_url}</p>
          {current.status === "queued" && <p role="status" className="meta-line">Waiting for an authorized worker. You may close this browser.</p>}
          {current.error_code && <p className="alert-error">{Object.hasOwn(errorLabels, current.error_code) ? errorLabels[current.error_code] : `Analysis stopped (${current.error_code}).`}</p>}
          {visibleDetails.run?.source_commit && <p className="meta-line">Source commit: {visibleDetails.run.source_commit}</p>}
          {visibleDetails.run?.source_digest && <p className="meta-line">Snapshot: {visibleDetails.run.source_digest}</p>}
          <ol className="event-list" aria-label="Recent analysis events">
            {visibleDetails.events.map((event) => <li key={event.id}><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString()}</time> · {event.detail}</li>)}
          </ol>
          {summary && (
            <div className="summary-block">
              <p>{summary.source_files_analyzed} source files analyzed · {summary.files_skipped} skipped · {summary.findings_count} candidate findings</p>
              <p className="muted-note">{summary.disclaimer}</p>
              {truncated && <p className="notice">Stored {findings.length} of {summary.findings_count} findings. The report and download contain only this bounded subset.</p>}
              <Button variant="outline" size="sm" onClick={() => downloadJson(`analysis-${current.id}.json`, visibleDetails.run.result)}>Download analysis JSON</Button>
              <details className="disclosure">
                <summary>Inspect candidate findings</summary>
                <ol className="finding-list findings-scroll" aria-label="Static analysis findings">
                  {findings.map((finding, index) => (
                    <li key={`${finding.path}:${finding.line}:${index}`}>
                      <strong>{finding.title}</strong>
                      <code>{finding.path}:{finding.line} · {finding.severity} · {finding.confidence} confidence</code>
                      <p>{finding.recommendation}</p>
                    </li>
                  ))}
                </ol>
              </details>
            </div>
          )}
        </div>
      )}
      {administer && (
        <details className="disclosure">
          <summary>Worker access</summary>
          <p className="muted-note">Provision a dedicated worker identity through operator setup, then register its user ID. Never use a personal account or place worker credentials in this form.</p>
          <form className="inline-fields" onSubmit={(event) => {
            event.preventDefault();
            action(async () => {
              await api.registerProjectWorker(project.id, workerId, workerLabel);
              setWorkerId("");
              setWorkerLabel("");
            });
          }}>
            <div className="field-label">
              <label htmlFor="analysis-worker-id">Dedicated worker user ID</label>
              <Input id="analysis-worker-id" required value={workerId} onChange={(event) => setWorkerId(event.target.value)} />
            </div>
            <div className="field-label">
              <label htmlFor="analysis-worker-label">Worker label</label>
              <Input id="analysis-worker-label" required maxLength={80} value={workerLabel} onChange={(event) => setWorkerLabel(event.target.value)} />
            </div>
            <Button type="submit" disabled={busy}>Register project worker</Button>
          </form>
          <ul className="record-list" aria-label="Registered project workers">
            {workers.map((worker) => (
              <li key={worker.id} className="record">
                <span className="record-main">{worker.label} · {worker.enabled ? "Authorized" : "Revoked"}</span>
                {worker.enabled && <Button variant="outline" size="sm" disabled={busy} onClick={() => action(() => api.revokeProjectWorker(project.id, worker.worker_user_id))} aria-label={`Revoke worker ${worker.label}`}>Revoke worker</Button>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
