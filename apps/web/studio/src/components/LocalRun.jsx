import React, {useEffect, useState} from "react";
import {ArrowUpRight, FileArchive, FolderOpen, HardDrive, LogOut, RefreshCw, ShieldCheck} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Input} from "@/components/ui/input";
import RunProgress, {IllustrativeSequence} from "./RunProgress.jsx";

export default function LocalRun({engine, kind, draft, onChange, selfHosted}) {
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [job, setJob] = useState(null);
  const [project, setProject] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [revision, setRevision] = useState(0);
  const isNew = kind === "start-new";
  const ready = engine.status === "ready";
  const request = engine.request;

  useEffect(() => {
    setProjects([]);
    if (!ready) return;
    const controller = new AbortController();
    request("/api/projects", {signal: controller.signal}).then(setProjects).catch(error => {
      if (error.name !== "AbortError") setError(error.message);
    });
    return () => controller.abort();
  }, [ready, request, engine.user?.id, draft.projectId]);

  useEffect(() => {
    setProject(null); setJobs([]);
    if (!ready || !draft.projectId) return;
    const controller = new AbortController();
    Promise.all([
      request(`/api/projects/${encodeURIComponent(draft.projectId)}`, {signal: controller.signal}),
      request(`/api/jobs?project_id=${encodeURIComponent(draft.projectId)}`, {signal: controller.signal}),
    ]).then(([value, runs]) => {setProject(value); setJobs(runs.filter(run => run.kind === "analyze"));}).catch(error => {
      if (error.name !== "AbortError") setError(error.message);
    });
    return () => controller.abort();
  }, [ready, request, engine.user?.id, draft.projectId, revision]);

  useEffect(() => {
    setJob(null); setPollError("");
    if (!ready || !draft.jobId) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const value = await request(`/api/jobs/${encodeURIComponent(draft.jobId)}`, {signal: controller.signal});
        setJob(value);
        if (value.status === "queued" || value.status === "running") timer = setTimeout(poll, 1500);
        else if (value.status === "succeeded" && value.project_id) {
          try {
            const result = await request(`/api/projects/${encodeURIComponent(value.project_id)}`, {signal: controller.signal});
            setProject(result);
          } catch (error) {
            if (error.name !== "AbortError") setError(`Analysis completed, but its latest project findings could not be loaded: ${error.message}`);
          }
        }
      } catch (error) {
        if (error.name !== "AbortError") setPollError(error.message);
      }
    }
    poll();
    return () => {controller.abort(); clearTimeout(timer);};
  }, [ready, request, engine.user?.id, draft.jobId, revision]);

  async function action(name, operation) {
    setBusy(name); setError("");
    try { await operation(); } catch (error) { setError(error.message); }
    finally { setBusy(""); }
  }
  async function createStarter() {
    const value = await request("/api/projects", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name: draft.name.trim(), brief: draft.brief.trim(), blueprint: draft.blueprint || "python-api"})});
    onChange({projectId: value.id, jobId: null});
  }
  async function importSnapshot(event) {
    event.preventDefault();
    if (!file) return;
    await action("import", async () => {
      const value = await request("/api/projects/import/zip", {method: "POST", headers: {"Content-Type": "application/zip", "X-Project-Name": (draft.name || file.name.replace(/\.zip$/i, "")).slice(0, 90).replace(/[^\x20-\x7e]/g, "_")}, body: file});
      onChange({projectId: value.id, jobId: value.analysis_job_id});
    });
  }
  async function analyze() {
    const value = await request(`/api/projects/${encodeURIComponent(draft.projectId)}/analyze`, {method: "POST"});
    onChange({jobId: value.id});
    setRevision(value => value + 1);
  }
  async function cancel() {
    await request(`/api/jobs/${encodeURIComponent(draft.jobId)}/cancel`, {method: "POST"});
    setRevision(value => value + 1);
  }

  if (engine.status === "checking") return <p role="status" className="empty-state">Checking the same-origin local engine…</p>;
  if (!selfHosted || engine.status === "unavailable") return <div className="local-unavailable">
    <div className="surface-panel"><HardDrive size={24}/><h3>Cloud execution is not connected.</h3><p>This hosted workspace prepares briefs and draft stories. It does not generate custom code, run a worker, or verify your application.</p><p>To run a real starter or source analysis, build the studio and open <code>/studio/</code> on your self-hosted FastAPI origin.</p><Button asChild variant="outline"><a href="https://github.com/suhasaitham22/Oryveta/blob/main/docs/IMPLEMENTATION.md" target="_blank" rel="noreferrer">Local setup guide <ArrowUpRight size={15}/></a></Button>{engine.error && <p className="fine-print">{engine.error}</p>}</div>
    <IllustrativeSequence/>
  </div>;

  if (!ready) return <div className="surface-panel local-login">
    <ShieldCheck size={26}/><h3>Connect to your local engine.</h3><p>This is a separate, same-origin cookie session. Signing in here does not use or grant access to a Supabase account.</p>
    {engine.config?.local_demo_enabled && <><p className="fine-print">Local demo uses the shared demo account on this loopback server. Only use an isolated development environment.</p><Button disabled={!!busy} onClick={() => action("login", engine.signIn)}>{busy ? "Signing in…" : "Sign in to local demo"}</Button></>}
    {engine.config?.github_auth_enabled && <Button asChild variant="outline"><a href="/auth/github">Sign in to local engine with GitHub <ArrowUpRight size={15}/></a></Button>}
    {!engine.config?.local_demo_enabled && !engine.config?.github_auth_enabled && <p>No local sign-in method is configured. Ask the server owner to configure GitHub OAuth; loopback demo mode is for local development only.</p>}
    {error && <p role="alert" className="alert-error">{error}</p>}
  </div>;

  const working = job && ["queued", "running"].includes(job.status);
  const availableProjects = projects.filter(value => value.origin === (isNew ? "new" : "import"));
  return <div className="local-run-layout">
    <div className="local-session"><span><span className="connection-dot"/> Local engine · {engine.user.display_name || engine.user.login}</span><Button size="sm" variant="ghost" disabled={!!busy} onClick={() => action("logout", engine.signOut)}><LogOut size={14}/> Disconnect local session</Button></div>
    {error && <p role="alert" className="alert-error">{error}</p>}
    {draft.jobId && !job && !pollError && <p role="status">Loading recorded job…</p>}
    {pollError && <div className="alert-error" role="alert"><p>{pollError} Live updates stopped; no new outcome is assumed.</p><Button variant="outline" size="sm" onClick={() => setRevision(value => value + 1)}><RefreshCw size={14}/> Refresh run</Button></div>}
    {job && <RunProgress job={job} projectName={project?.name} stale={!!pollError} onCancel={() => action("cancel", cancel)} canceling={busy === "cancel"}/>}
    {project?.analysis && <AnalysisResult analysis={project.analysis}/>}
    <div className="surface-panel">
      <div className="section-label"><FileArchive size={15}/> {isNew ? "Runnable starter · not custom feature generation" : "Read-only repository snapshot"}</div>
      {isNew ? <><h3>Create a foundation, not a finished product.</h3><p>The deterministic template preserves your brief and writes starter files. Requested business logic still needs implementation and tests.</p>
        <div className="field-label"><label htmlFor={`${kind}-blueprint`}>Starter template</label><select id={`${kind}-blueprint`} value={draft.blueprint || "python-api"} onChange={event => onChange({blueprint: event.target.value})}><option value="python-api">Python API · FastAPI / SQLite / pytest</option><option value="web-app">Web app · HTML / CSS / JavaScript</option><option value="ai-service">AI service · provider interface (unconfigured)</option></select></div>
        <Button disabled={!!busy || draft.name.trim().length < 2 || draft.name.length > 90 || draft.brief.trim().length < 10} onClick={() => action("create", createStarter)}>{busy === "create" ? "Creating starter…" : "Create starter"}</Button>
        {(!draft.name || draft.brief.trim().length < 10) && <p className="fine-print">Fill in the project name and product brief in the Brief tab first.</p>}
      </> : <form onSubmit={importSnapshot}><h3>Inspect the code you choose.</h3><p>Import a ZIP you are authorized to inspect. Source is read, never executed. No repository credentials are requested.</p><label className="field-label">Repository ZIP<Input type="file" accept=".zip,application/zip" required onChange={event => setFile(event.target.files?.[0] || null)}/></label><p className="fine-print">Maximum archive size: 12 MB. Do not include secrets or private data without authorization.</p><Button type="submit" disabled={!file || !!busy}>{busy === "import" ? "Importing snapshot…" : "Import & analyze"}</Button></form>}
    </div>
    <div className="surface-panel">
      <h3 className="flex items-center gap-2"><FolderOpen size={19}/> Your local {isNew ? "starters" : "snapshots"}</h3>
      <div className="field-label"><label htmlFor={`${kind}-project`}>Selected project</label><select id={`${kind}-project`} value={draft.projectId || ""} onChange={event => onChange({projectId: event.target.value || null, jobId: null})}><option value="">Choose a saved project</option>{availableProjects.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}</select></div>
      {project && <><div className="artifact-receipt"><strong>{project.name}</strong><span>{project.files?.length ?? "—"} files in this snapshot · {project.origin === "new" ? "starter" : "imported"}</span></div>
        <div className="flex flex-wrap gap-3"><Button disabled={!!busy || working} onClick={() => action("analyze", analyze)}>{busy === "analyze" ? "Queueing…" : "Analyze snapshot"}</Button><Button asChild variant="outline"><a href={`/api/projects/${encodeURIComponent(project.id)}/export`}>Download source ZIP</a></Button></div>
        <p className="fine-print">Analysis requires a running local worker. It does not run application tests or modify the snapshot.</p>
      </>}
      {jobs.length > 0 && <div className="field-label"><label htmlFor={`${kind}-run`}>Analysis run</label><select id={`${kind}-run`} value={draft.jobId || ""} onChange={event => onChange({jobId: event.target.value || null})}><option value="">Choose a recorded run</option>{jobs.map(value => <option key={value.id} value={value.id}>{new Date(value.created_at * 1000).toLocaleString()} · {value.id === job?.id ? job.status : value.status}</option>)}</select></div>}
    </div>
  </div>;
}

function AnalysisResult({analysis}) {
  const summary = analysis.summary;
  const technology = summary.technology;
  return <section className="analysis-result" aria-label="Latest project analysis"><div className="section-label">Latest project analysis · may differ from an older selected run</div><h3>{summary.source_files_analyzed} source files inspected · {summary.findings_count} findings</h3><p>{summary.disclaimer}</p>
  {technology && <div className="artifact-receipt" aria-label="Repository technology profile"><strong>Repository profile · {summary.language}</strong><span>{technology.frameworks_and_tools.length ? technology.frameworks_and_tools.join(" · ") : "No known framework detected from supported manifests"}</span><span>Test directory: {technology.test_directory_present ? "present" : "not found"} · CI config: {technology.ci_config_present ? "present" : "not found"}</span><span>{technology.manifests.length} supported manifests inspected · {technology.confidence}</span>{technology.unreadable_manifests.length > 0 && <span>{technology.unreadable_manifests.length} unreadable manifests · these were not classified</span>}</div>}
  <p className="fine-print">{summary.files_skipped} files skipped. {summary.findings_truncated ? `Only ${summary.findings_returned} of ${summary.findings_count} findings are shown; refine the scope.` : "Findings are not evidence of exploited vulnerabilities."} No code changes applied. No application tests executed.</p><details><summary>Review findings</summary><ul className="finding-list">{analysis.findings.map((finding, index) => <li key={`${finding.path}:${finding.line}:${index}`}><strong>{finding.title}</strong><code>{finding.path || "Repository"}{finding.line ? `:${finding.line}` : ""}</code><p>{finding.recommendation}</p><span>{finding.severity} severity · {finding.confidence} confidence</span></li>)}</ul>{!analysis.findings.length && <p>No findings from these heuristics. This does not establish correctness or security.</p>}</details></section>;
}
