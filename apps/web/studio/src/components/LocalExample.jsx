import React from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  Download,
  FileDiff,
  Hash,
  ScanSearch,
} from "lucide-react";
import {
  EXAMPLE_PATCH_FILE,
  EXAMPLE_RECORD_FILE,
  exampleAssetUrl,
  exampleSummary,
  useLocalExample,
} from "@/lib/localExample";

/* The recorded example is read from public/repair-example.json, the same files
   a visitor downloads. One stored run from a local CLI session: it is not
   current activity, not a benchmark and not a customer result. When the asset
   cannot be read we say so and still offer the files; we never fill the gap
   with numbers that would look verified. */

const count = (value) =>
  typeof value === "number" ? value.toLocaleString("en-US") : "—";

export function ExampleDownloads({ compact = false }) {
  return (
    <div className={compact ? "example-downloads compact" : "example-downloads"}>
      <a
        className="example-download"
        href={exampleAssetUrl(EXAMPLE_RECORD_FILE)}
        download={EXAMPLE_RECORD_FILE}
      >
        <Download size={15} aria-hidden="true" />
        Download the run record (JSON)
      </a>
      <a
        className="example-download"
        href={exampleAssetUrl(EXAMPLE_PATCH_FILE)}
        download={EXAMPLE_PATCH_FILE}
      >
        <FileDiff size={15} aria-hidden="true" />
        Download the patch (.patch)
      </a>
    </div>
  );
}

function ExampleUnavailable({ children }) {
  return (
    <div className="example-unavailable" role="status">
      <AlertTriangle size={17} aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}

/* Hero receipt: the shortest honest summary of the stored run. */
export function LocalExampleReceipt() {
  const { record, failed } = useLocalExample();
  if (failed)
    return (
      <div className="example-receipt example-receipt-plain">
        <ExampleUnavailable>
          This page could not read the recorded example file, so no result is
          shown. The stored files are still downloadable below.
        </ExampleUnavailable>
        <ExampleDownloads compact />
      </div>
    );
  if (!record)
    return (
      <div className="example-receipt example-receipt-plain">
        <p className="example-loading" role="status">
          Reading the recorded example…
        </p>
        <ExampleDownloads compact />
      </div>
    );
  const { passed, total, shortRun } = exampleSummary(record);
  return (
    <figure className="example-receipt">
      <figcaption>
        <span className="section-label">
          Recorded local example · {record.recorded_at}
        </span>
        <strong>{record.title}</strong>
      </figcaption>
      <ul className="example-verdict">
        <li className="verdict-pass">
          <Check size={14} aria-hidden="true" />
          {passed} of {total} configured checks passed
        </li>
        <li className="verdict-review">
          <ScanSearch size={14} aria-hidden="true" />
          Stopped for human review
        </li>
      </ul>
      <dl className="example-metrics">
        <div>
          <dt>Turns</dt>
          <dd>{count(record.metrics?.turns)}</dd>
        </div>
        <div>
          <dt>Tool calls</dt>
          <dd>{count(record.metrics?.tool_calls)}</dd>
        </div>
        <div>
          <dt>Tokens observed</dt>
          <dd>{count(record.metrics?.tokens_observed)}</dd>
        </div>
      </dl>
      <p className="example-receipt-source">
        Local model {record.model?.name} · run {shortRun} · no code published
      </p>
      <Link className="text-link" to="/#local-example">
        Read the whole record
      </Link>
    </figure>
  );
}

/* Full record: the patch, every check, the hashes and the limits. */
export function LocalExampleRecord() {
  const { record, failed } = useLocalExample();
  return (
    <section
      id="local-example"
      tabIndex={-1}
      className="example-record"
      aria-label="Recorded local repair example"
    >
      <div className="example-record-head">
        <span className="section-label">
          <Hash size={15} aria-hidden="true" />
          One recorded local run · synthetic example
        </span>
        <h2>A change you can read, and checks you can re-run.</h2>
        <p>
          This is a single stored session from the local command-line tool,
          kept as a file in this site. It is not live activity, not a benchmark
          and not a customer result. Download both files and compare them with
          the script that produced them.
        </p>
      </div>
      {failed && (
        <ExampleUnavailable>
          The recorded example file could not be read in this browser, so
          nothing about the run is shown here. The stored files remain
          downloadable.
        </ExampleUnavailable>
      )}
      {!record && !failed && (
        <p className="example-loading" role="status">
          Reading the recorded example…
        </p>
      )}
      {record && (
        <div className="example-record-body">
          <div className="example-record-main">
            <figure className="example-patch">
              <figcaption>
                <FileDiff size={15} aria-hidden="true" />
                {record.title} · proposed patch
                <span className="example-state">{record.status === "needs_review" ? "Needs review" : record.status}</span>
              </figcaption>
              <pre tabIndex={0}>
                <code>{record.patch}</code>
              </pre>
            </figure>
            <div className="example-checks">
              <h3>
                Declared checks ·{" "}
                {record.verification === "passed" ? "all passed" : record.verification}
              </h3>
              <ul>
                {(record.checks || []).map(({ name, passed }) => (
                  <li key={name} className={passed ? "check-pass" : "check-fail"}>
                    {passed ? (
                      <Check size={14} aria-hidden="true" />
                    ) : (
                      <AlertTriangle size={14} aria-hidden="true" />
                    )}
                    <code>{name}</code>
                    <span>{passed ? "passed" : "failed"}</span>
                  </li>
                ))}
              </ul>
              <p>
                These checks were declared for this task and executed in a
                network-disabled container after the edit. They bound the claim;
                they do not prove the module is correct.
              </p>
            </div>
          </div>
          <div className="example-record-side">
            <dl className="example-facts">
              <div>
                <dt>Run</dt>
                <dd>
                  <code>{record.run_id}</code>
                </dd>
              </div>
              <div>
                <dt>Recorded</dt>
                <dd>{record.recorded_at}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>
                  {record.model?.name}
                  <code>{record.model?.digest?.slice(0, 16)}…</code>
                </dd>
              </div>
              <div>
                <dt>Work done</dt>
                <dd>
                  {count(record.metrics?.turns)} turns ·{" "}
                  {count(record.metrics?.tool_calls)} tool calls ·{" "}
                  {count(record.metrics?.tokens_observed)} tokens observed
                </dd>
              </div>
              {Object.entries(record.provenance || {}).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replace(/_sha256$/, "").replace(/_/g, " ")} sha256</dt>
                  <dd>
                    <code className="example-hash">{value}</code>
                  </dd>
                </div>
              ))}
            </dl>
            <div className="example-limits">
              <h3>What this does not show</h3>
              <ul>
                {(record.limitations || []).map((limit) => (
                  <li key={limit}>{limit}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
      <div className="example-record-foot">
        <ExampleDownloads />
        {record?.source_url && (
          <a
            className="text-link"
            href={record.source_url}
            target="_blank"
            rel="noreferrer"
          >
            Read the script that produced it
          </a>
        )}
      </div>
    </section>
  );
}
