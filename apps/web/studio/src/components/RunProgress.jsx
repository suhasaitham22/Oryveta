import React, { useEffect, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Clock3,
  LoaderCircle,
  OctagonX,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const states = {
  queued: {
    label: "Waiting for worker",
    operation:
      "Analysis is queued. Start the local worker to process this job.",
    icon: Clock3,
  },
  running: {
    label: "Working",
    operation: "Inspecting the source snapshot with the static analyzer.",
    icon: LoaderCircle,
  },
  succeeded: {
    label: "Completed",
    operation:
      "Static analysis finished. Review the findings; application behavior has not been verified.",
    icon: CheckCircle2,
  },
  failed: {
    label: "Failed",
    operation:
      "The worker could not finish this analysis. No successful outcome is claimed.",
    icon: XCircle,
  },
  canceled: {
    label: "Canceled",
    operation:
      "Result delivery was canceled. In-flight computation may continue until the worker returns.",
    icon: OctagonX,
  },
};

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "Not recorded";
  const value = Math.max(0, Math.floor(seconds));
  return value < 60 ? `${value}s` : `${Math.floor(value / 60)}m ${value % 60}s`;
}

function timestamp(value) {
  return new Date(value * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export default function RunProgress({
  job,
  projectName,
  stale,
  onCancel,
  canceling,
}) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  const active = job.status === "queued" || job.status === "running";
  useEffect(() => {
    if (!active || stale) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [active, stale, job.id]);
  const state = states[job.status];
  if (!state)
    return (
      <p role="alert" className="alert-error">
        The engine returned an unsupported job state.
      </p>
    );
  const Icon = state.icon;
  const events = job.events || [];
  const end = active ? now : job.finished_at || job.updated_at;
  const elapsed = formatDuration(end - job.created_at);
  return (
    <section
      className={`run-progress run-${job.status}`}
      aria-label="Real analysis progress"
    >
      <div className="run-heading">
        <span
          className={`run-icon ${job.status === "running" && !stale ? "is-working" : ""}`}
        >
          <Icon size={21} aria-hidden="true" />
        </span>
        <div className="run-heading-copy">
          <h3>{stale ? "Connection interrupted" : state.label}</h3>
          <p>
            {projectName ? `${projectName} · ` : ""}Static analysis · local
            engine
          </p>
        </div>
        <span
          className="run-elapsed"
          aria-label={`${elapsed} elapsed since queued`}
        >
          {elapsed}
          <small>elapsed</small>
        </span>
      </div>
      <p className="run-operation" role="status">
        {stale
          ? "Showing the last confirmed state. Completion is unknown until refreshed."
          : state.operation}
      </p>
      {job.error && (
        <p className="alert-error" role="alert">
          {job.error}
        </p>
      )}
      {job.status !== "succeeded" && <LifecycleTasks job={job} stale={stale} />}
      <details className="run-details">
        <summary>
          Task timeline <span>{events.length} recorded events</span>
        </summary>
        {job.status === "succeeded" && (
          <LifecycleTasks job={job} stale={stale} />
        )}
        <ol className="event-timeline">
          {events.length ? (
            events.map((event) => (
              <li key={event.id}>
                <Circle size={10} aria-hidden="true" />
                <div>
                  <strong>{event.detail}</strong>
                  <time
                    dateTime={new Date(event.created_at * 1000).toISOString()}
                  >
                    {timestamp(event.created_at)}
                  </time>
                </div>
              </li>
            ))
          ) : (
            <li>No event records were returned by the engine.</li>
          )}
        </ol>
        <dl className="run-metadata">
          <div>
            <dt>Queued</dt>
            <dd>{timestamp(job.created_at)}</dd>
          </div>
          {job.started_at && (
            <div>
              <dt>Worker started</dt>
              <dd>{timestamp(job.started_at)}</dd>
            </div>
          )}
          {job.finished_at && (
            <div>
              <dt>Finished</dt>
              <dd>{timestamp(job.finished_at)}</dd>
            </div>
          )}
          <div>
            <dt>Worker attempts</dt>
            <dd>{job.attempts}</dd>
          </div>
        </dl>
        <p className="fine-print">
          These are recorded actions, not private reasoning. The engine does not
          report individual tool calls or granular task progress.
        </p>
      </details>
      {active && (
        <div className="run-footer">
          <span className="fine-print">No percentage or ETA is available.</span>
          <Button
            size="sm"
            variant="outline"
            disabled={canceling}
            onClick={onCancel}
          >
            {canceling ? "Canceling…" : "Cancel analysis"}
          </Button>
        </div>
      )}
    </section>
  );
}

function LifecycleTasks({ job, stale }) {
  const complete = job.status === "succeeded";
  const active = job.status === "running";
  const stopped = job.status === "failed" || job.status === "canceled";
  const started = !!job.started_at || active || complete;
  const tasks = [
    {
      label: "Queue submission accepted",
      state: "complete",
      note: "Persisted by the local API",
    },
    {
      label: "Worker source analysis",
      state: complete
        ? "complete"
        : active
          ? "active"
          : stopped
            ? "stopped"
            : "waiting",
      note: complete
        ? "Worker reported completion"
        : active
          ? "Static analyzer is inspecting the snapshot"
          : stopped
            ? `${job.status === "failed" ? "Failed" : "Canceled"}${started ? " after worker start" : " before a recorded worker start"}`
            : "Waiting for a local worker",
    },
    {
      label: "Analysis result",
      state: complete ? "complete" : stopped ? "stopped" : "waiting",
      note: complete
        ? "Persisted for human review; not application verification"
        : stopped
          ? "No successful result from this run"
          : "Not available yet",
    },
  ];
  return (
    <ol
      className="lifecycle-tasks"
      aria-label="Recorded analysis tasks"
      aria-busy={active && !stale}
    >
      {tasks.map((task) => {
        const Icon =
          task.state === "complete"
            ? CheckCircle2
            : task.state === "active"
              ? LoaderCircle
              : task.state === "stopped"
                ? OctagonX
                : Circle;
        return (
          <li
            key={task.label}
            className={`task-${task.state} ${task.state === "active" && !stale ? "is-working" : ""}`}
          >
            <Icon size={17} aria-hidden="true" />
            <div>
              <strong>{task.label}</strong>
              <span>{task.note}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function IllustrativeSequence() {
  return (
    <div className="illustrative-sequence">
      <div className="illustrative-head">
        <strong>What an analysis can report</strong>
        <span className="status-tag">Illustration · not running</span>
      </div>
      <ol>
        {[
          "Snapshot submitted by you",
          "Worker inspects source without executing it",
          "Findings returned for human review",
        ].map((label, index) => (
          <li key={label}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            {label}
          </li>
        ))}
      </ol>
      <p className="fine-print">
        A sample sequence, not an agent transcript. No cloud coding agent is
        connected.
      </p>
    </div>
  );
}
