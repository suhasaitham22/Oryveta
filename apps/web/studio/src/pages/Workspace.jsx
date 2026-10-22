import React, { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  FolderGit2,
  GitBranch,
  HardDrive,
  Layers3,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  Plus,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { workspacePaths } from "@/components/SiteHeader.jsx";
import {
  listWorkspaces,
  createWorkspace,
  updateWorkspace,
} from "@/lib/identity";
import { useWorkspaceState } from "@/lib/WorkspaceState.jsx";
import Journey, { emptyDraft } from "./Journey.jsx";
import PrivateChats from "./PrivateChats.jsx";
import Projects from "./Projects.jsx";

const primaryNavigation = [
  ["overview", LayoutDashboard, "Overview"],
  ["new", Sparkles, "Start New"],
  ["evolve", GitBranch, "Evolve"],
];
const secondaryNavigation = [
  ["workspace", Layers3, "Workspaces"],
  ["projects", FolderGit2, "Projects"],
  ["chats", MessageSquareText, "Private chats"],
  ["activity", Activity, "Activity"],
];

export default function Workspace({
  user,
  preview,
  onExit,
  stories,
  selfHosted = false,
  engine,
}) {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const page = Object.keys(workspacePaths).find(
    (key) => workspacePaths[key] === location.pathname.replace(/\/+$/, ""),
  );
  const {
    spaces,
    setSpaces,
    selected,
    setSelected,
    drafts,
    setDrafts,
    settings,
    setSettings,
  } = useWorkspaceState();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const mobileNav = useRef(null);
  const active =
    selected === ""
      ? null
      : spaces.find((space) => space.id === selected) || spaces[0] || null;
  const settingsKey = active?.id || "new";
  const settingsDraft = settings[settingsKey] || {};
  const name = settingsDraft.name ?? active?.name ?? "";
  const slug = settingsDraft.slug ?? active?.slug ?? "";
  const description = settingsDraft.description ?? active?.description ?? "";
  function editSetting(field, value) {
    setSettings((current) => ({
      ...current,
      [settingsKey]: { ...current[settingsKey], [field]: value },
    }));
  }
  const setName = (value) => editSetting("name", value);
  const setSlug = (value) => editSetting("slug", value);
  const setDescription = (value) => editSetting("description", value);
  const kind = page === "new" ? "start-new" : "evolve";
  const draftKey = `${selfHosted ? "local" : active?.id || "guest"}:${kind}`;
  const storedDraft = drafts[draftKey] || emptyDraft();
  const ownsLocalSelection =
    !selfHosted || storedDraft.localOwnerId === engine.user?.id;
  const draft = ownsLocalSelection
    ? storedDraft
    : { ...storedDraft, projectId: null, jobId: null };

  async function refresh() {
    if (preview || selfHosted) return;
    const values = await listWorkspaces();
    setSpaces(values);
    setSelected((id) =>
      values.some((space) => space.id === id) ? id : values[0]?.id || null,
    );
  }
  useEffect(() => {
    if (preview || selfHosted) return;
    let live = true;
    listWorkspaces()
      .then((values) => {
        if (live) setSpaces(values);
      })
      .catch((error) => {
        if (live) setError(error.message);
      });
    return () => {
      live = false;
    };
  }, [preview, selfHosted, setSpaces]);
  function navigate(id) {
    setError("");
    setSuccess("");
    mobileNav.current?.close();
    routerNavigate(workspacePaths[id]);
  }
  async function save(event) {
    event.preventDefault();
    if (preview || selfHosted) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      if (active) {
        if (active.created_by !== user.id)
          throw new Error("Only workspace owner may edit these settings");
        await updateWorkspace(active.id, {
          name: name.trim(),
          description: description.trim(),
        });
        setSuccess("Workspace settings saved");
      } else {
        const created = await createWorkspace(user, {
          name: name.trim(),
          slug: slug.trim().toLowerCase(),
          description: description.trim(),
        });
        setSelected(created.id);
        setSuccess("Your private workspace is ready");
      }
      await refresh();
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }
  function updateDraft(values) {
    const owner =
      selfHosted && ("projectId" in values || "jobId" in values)
        ? { localOwnerId: engine.user?.id }
        : {};
    setDrafts((current) => ({
      ...current,
      [draftKey]: {
        ...(current[draftKey] || emptyDraft()),
        ...values,
        ...owner,
      },
    }));
  }
  function navItems(items) {
    return items.map(([id, Icon, label]) => (
      <Link
        key={id}
        to={workspacePaths[id]}
        className={`workspace-nav-item ${page === id ? "active" : ""}`}
        aria-current={page === id ? "page" : undefined}
        onClick={() => mobileNav.current?.close()}
      >
        <Icon size={17} />
        {label}
      </Link>
    ));
  }
  function sidebar() {
    return (
      <>
        <Link className="workspace-sidebar-title" to="/workspace">
          Your workspace
        </Link>
        <nav aria-label="Workspace navigation">
          <div className="nav-group-label">Create & improve</div>
          {navItems(primaryNavigation)}
          <div className="nav-group-label">Your space</div>
          {navItems(secondaryNavigation)}
        </nav>
        <div className="sidebar-base">
          <div className="sidebar-note">
            <ShieldCheck size={18} />
            <strong>
              {selfHosted
                ? "Self-hosted engine"
                : preview
                  ? "Explore without an account"
                  : "Private by default"}
            </strong>
            <p>
              {selfHosted
                ? "Local cookie identity. Separate from Supabase workspaces."
                : preview
                  ? "Drafts stay open across site navigation. Export a copy to keep them."
                  : "Workspace membership never grants access to private chats."}
            </p>
          </div>
          <Link className="workspace-nav-item" to="/">
            <ArrowUpRight size={16} />
            Home
          </Link>
        </div>
      </>
    );
  }
  const locked = preview || selfHosted;
  const hasWorkspaceSwitch = !locked && spaces.length > 0;
  const openWork = [
    { page: "new", kind: "start-new", title: "Start New" },
    { page: "evolve", kind: "evolve", title: "Evolve" },
  ].flatMap((journey) => {
    const value = drafts[`${selfHosted ? "local" : active?.id || "guest"}:${journey.kind}`];
    if (!value || (!value.name && !value.brief && !value.projectId)) return [];
    const hasLocalProject = selfHosted && value.localOwnerId === engine.user?.id && value.projectId;
    return [{ ...journey, draft: value, tab: hasLocalProject ? "local" : "brief" }];
  });
  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar" aria-label="Workspace menu">{sidebar()}</aside>
      <dialog
        className="mobile-workspace-nav"
        ref={mobileNav}
        aria-label="Workspace menu"
      >
        <Button
          size="icon"
          variant="ghost"
          className="mobile-nav-close"
          onClick={() => mobileNav.current.close()}
          aria-label="Close workspace menu"
        >
          <X size={20} />
        </Button>
        {sidebar()}
      </dialog>
      <div className="workspace-content">
        <div
          className={`workspace-controls ${hasWorkspaceSwitch ? "has-workspace-switch" : ""}`}
        >
          <Button
            size="icon"
            variant="ghost"
            className="mobile-menu-trigger"
            onClick={() => mobileNav.current.showModal()}
            aria-label="Open workspace menu"
          >
            <Menu size={20} />
          </Button>
          {hasWorkspaceSwitch && (
            <select
              className="workspace-switch"
              aria-label="Active workspace"
              value={active?.id || ""}
              onChange={(event) => setSelected(event.target.value)}
            >
              {spaces.map((space) => (
                <option key={space.id} value={space.id}>
                  {space.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <main className="workspace-main" id="main-content" tabIndex={-1}>
          {!selfHosted && (
            <div className="preview-ribbon">
              <InfoMark />
              <span>
                {preview ? "Preview mode. " : "Hosted workspace. "}Briefs and
                storyboards are drafts; no cloud coding agent is running.{" "}
                {preview && "Private workspaces and chats require sign-in."}
              </span>
            </div>
          )}
          {error && (
            <p role="alert" className="alert-error">
              {error}
            </p>
          )}
          {success && (
            <p role="status" className="alert-success">
              {success}
            </p>
          )}
          {page === "overview" && (
            <>
              <div className="page-heading">
                <div className="section-label">{active?.name || "Your working space"}</div>
                <h1>{openWork.length ? "Pick up the work." : "What are you working on?"}</h1>
                <p>{openWork.length ? "Your open briefs and selected local projects, kept in context." : "Start with a product brief or a codebase you want to understand."}</p>
              </div>
              {openWork.length > 0 && (
                <section className="open-work" aria-label="Continue your work">
                  <div className="section-label">Open in this workspace</div>
                  {openWork.map((work) => (
                    <div className="open-work-row" key={work.kind}>
                      <div className="open-work-icon"><Layers3 size={20} /></div>
                      <div className="open-work-copy">
                        <span>{work.title} · {work.tab === "local" ? "Local snapshot selected" : "Planning draft"}</span>
                        <h2>{work.draft.name || "Untitled brief"}</h2>
                        {work.draft.brief && <p>{work.draft.brief}</p>}
                      </div>
                      <Link className="text-link" to={`${workspacePaths[work.page]}?tab=${work.tab}`}>
                        Continue <ArrowRight size={16} />
                      </Link>
                    </div>
                  ))}
                </section>
              )}
              <div className={`overview-journeys ${openWork.length ? "has-open-work" : ""}`}>
                <JourneyCard
                  icon={Sparkles}
                  number="01"
                  title="Start New"
                  description="Turn a client onboarding idea into a scoped brief. Create a starter locally, then explain what is—and isn't—built."
                  onClick={() => navigate("new")}
                />
                <JourneyCard
                  icon={GitBranch}
                  number="02"
                  title="Evolve"
                  description="Bring an existing service into focus. Inspect a snapshot locally, review findings, and make the next change understandable."
                  onClick={() => navigate("evolve")}
                />
              </div>
              <div className="overview-bottom">
                <div>
                  <div className="section-label">Built into both journeys</div>
                  <h2>Don't leave the explanation until last.</h2>
                  <p>
                    Demo Studio stays beside your brief and local run. The right
                    story opens with the right context, without losing your
                    edits when you switch journeys.
                  </p>
                </div>
                <div className="artifact-stack">
                  <span>
                    01 <strong>Brief</strong>
                    <small>Intent & constraints</small>
                  </span>
                  <span>
                    02 <strong>Local run</strong>
                    <small>Recorded actions</small>
                  </span>
                  <span>
                    03 <strong>Demo Studio</strong>
                    <small>Unverified draft story</small>
                  </span>
                </div>
              </div>
            </>
          )}
          {(page === "new" || page === "evolve") && (
            <Journey
              key={draftKey}
              kind={kind}
              stories={stories}
              draft={draft}
              onChange={updateDraft}
              engine={engine}
              selfHosted={selfHosted}
              workspaceId={active?.id || null}
            />
          )}
          {page === "workspace" && (
            <>
              <div className="page-heading">
                <div className="section-label">Organization</div>
                <h1>Your space, your standards.</h1>
                <p>
                  Supabase workspaces keep membership and settings separate from
                  engine access.
                </p>
              </div>
              {locked ? (
                <div className="surface-panel">
                  <ShieldCheck size={26} />
                  <h2>Workspace setup needs a hosted sign-in.</h2>
                  <p>
                    {selfHosted
                      ? "Local engine identity is not a Supabase identity. Use the hosted workspace to manage your team; local sessions are never forwarded."
                      : "Preview mode never creates fake accounts or database entries."}
                  </p>
                  {!selfHosted && (
                    <Button onClick={onExit}>
                      Return to sign in <ArrowRight size={16} />
                    </Button>
                  )}
                </div>
              ) : (
                <div className="settings-layout">
                  <div className="space-y-3">
                    {spaces.map((space) => (
                      <button
                        key={space.id}
                        className={`space-choice ${active?.id === space.id ? "selected" : ""}`}
                        onClick={() => setSelected(space.id)}
                      >
                        <strong>{space.name}</strong>
                        <span>
                          {space.slug} ·{" "}
                          {space.created_by === user.id ? "Owner" : "Member"}
                        </span>
                      </button>
                    ))}
                    {active && (
                      <Button variant="outline" onClick={() => setSelected("")}>
                        <Plus size={15} />
                        New workspace
                      </Button>
                    )}
                  </div>
                  <form className="surface-panel" onSubmit={save}>
                    <h2>
                      {active ? "Workspace details" : "Your first workspace"}
                    </h2>
                    <p>
                      {active
                        ? "Owners may edit these settings."
                        : "Private by default. Chat sharing uses explicit in-app invitations."}
                    </p>
                    <label className="field-label">
                      Workspace name
                      <Input
                        required
                        minLength={2}
                        maxLength={80}
                        value={name}
                        disabled={
                          busy || (!!active && active.created_by !== user.id)
                        }
                        onChange={(event) => {
                          setName(event.target.value);
                          if (!active)
                            setSlug(
                              event.target.value
                                .toLowerCase()
                                .replace(/[^a-z0-9]+/g, "-")
                                .replace(/^-|-$/g, "")
                                .slice(0, 40),
                            );
                        }}
                      />
                    </label>
                    <label className="field-label">
                      Identifier
                      <Input
                        required
                        pattern="[a-z][a-z0-9-]{2,39}"
                        maxLength={40}
                        value={slug}
                        disabled={busy || !!active}
                        onChange={(event) => setSlug(event.target.value)}
                      />
                    </label>
                    <label className="field-label">
                      What are you building?
                      <Textarea
                        maxLength={500}
                        value={description}
                        disabled={
                          busy || (!!active && active.created_by !== user.id)
                        }
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </label>
                    {(!active || active.created_by === user.id) && (
                      <Button type="submit" disabled={busy}>
                        {busy
                          ? "Saving…"
                          : active
                            ? "Save settings"
                            : "Create workspace"}
                      </Button>
                    )}
                  </form>
                </div>
              )}
            </>
          )}
          {page === "projects" &&
            (selfHosted ? (
              <>
                <div className="page-heading">
                  <div className="section-label">Separate identities</div>
                  <h1>Projects live in the hosted workspace.</h1>
                  <p>
                    This local engine session has no Supabase identity, so it
                    cannot read hosted projects or accept their invitations.
                  </p>
                </div>
                <div className="surface-panel">
                  <FolderGit2 size={26} />
                  <h2>Hosted projects keep their own membership.</h2>
                  <p>
                    Sign in to the hosted edition to create a project brief and
                    invite people explicitly. Your local cookie and repository
                    snapshots are never forwarded to that account.
                  </p>
                </div>
              </>
            ) : (
              <Projects user={user} preview={preview} onExit={onExit} />
            ))}
          {page === "chats" &&
            (selfHosted ? (
              <>
                <div className="page-heading">
                  <div className="section-label">Separate identities</div>
                  <h1>Private chats live in the hosted workspace.</h1>
                  <p>
                    This local engine session cannot read Supabase conversations
                    or accept their invitations. Local sign-in never grants
                    hosted chat access.
                  </p>
                </div>
                <div className="surface-panel">
                  <MessageSquareText size={26} />
                  <h2>Keep the right conversation private.</h2>
                  <p>
                    Use your hosted Supabase account for private human messages
                    and explicit sharing. Your local cookie and repository
                    snapshots are not forwarded to that account.
                  </p>
                </div>
              </>
            ) : (
              <PrivateChats
                user={user}
                preview={preview}
                workspaceId={active?.id || null}
                onExit={onExit}
              />
            ))}
          {page === "activity" && (
            <>
              <div className="page-heading">
                <div className="section-label">Accountability</div>
                <h1>Actions, not assertions.</h1>
                <p>
                  {selfHosted
                    ? "Select a project and run inside Start New or Evolve to see persisted worker events."
                    : "There are no hosted execution events. A planning export is not an agent run."}
                </p>
              </div>
              <div className="surface-panel">
                <HardDrive size={25} />
                <h2>
                  {selfHosted
                    ? "Your run timeline stays with its project."
                    : "Real execution is local today."}
                </h2>
                <p>
                  Queued, running, completed, failed and canceled states come
                  from the engine. No invented task completions, tool counts or
                  private reasoning.
                </p>
                <Button variant="outline" onClick={() => navigate("evolve")}>
                  Open Evolve <ArrowRight size={15} />
                </Button>
              </div>
              <div className="research-note">
                <strong>Internal evaluation, not autonomous learning</strong>
                <p>
                  The Python evidence gate compares matched outcomes and
                  recommends human review. It does not promote its own changes.
                </p>
                <a
                  href="https://github.com/suhasaitham22/Oryveta/blob/main/docs/EVALUATION.md"
                  target="_blank"
                  rel="noreferrer"
                >
                  Read the evaluation protocol <ArrowUpRight size={14} />
                </a>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function InfoMark() {
  return <ShieldCheck size={17} className="shrink-0" />;
}
function JourneyCard({ icon: Icon, number, title, description, onClick }) {
  return (
    <button className="journey-card" onClick={onClick}>
      <div className="flex justify-between items-center">
        <span className="feature-icon">
          <Icon size={23} />
        </span>
        <span className="card-number">{number}</span>
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <span className="journey-card-link">
        Open {title} <ArrowRight size={17} />
      </span>
    </button>
  );
}
