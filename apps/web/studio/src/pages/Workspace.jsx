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
import "../workspace.css";

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
          <span className="rail-mark" aria-hidden="true">
            <Layers3 size={17} />
          </span>
          <span className="rail-id">
            <strong>Your workspace</strong>
            <span>
              {selfHosted
                ? "Local engine edition"
                : preview
                  ? "Preview · not signed in"
                  : active?.name || "No workspace yet"}
            </span>
          </span>
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
                ? "Repository work runs on this server. Cloud projects use a separate sign-in."
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
            size="sm"
            variant="ghost"
            className="mobile-menu-trigger"
            onClick={() => mobileNav.current.showModal()}
            aria-label="Open workspace menu"
          >
            <Menu size={20} />
            <span>Workspace</span>
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
                {preview
                  ? "Explore planning tools. Sign in to save projects and share private conversations."
                  : "Projects and chats are saved. Export Start New and Evolve drafts to keep them."}{" "}
                Code execution requires a configured self-hosted engine.
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
                <h1>{openWork.length ? "Continue your work." : "Start with an app or a codebase."}</h1>
                <p>{openWork.length ? "Reopen a planning draft or your selected local project." : "Plan a new application with Start New, or inspect existing code with Evolve."}</p>
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
                      <Link className="row-link" to={`${workspacePaths[work.page]}?tab=${work.tab}`}>
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
                  description="Write the app requirements and export a brief. Use the self-hosted engine to prepare a starter repository."
                  onClick={() => navigate("new")}
                />
                <JourneyCard
                  icon={GitBranch}
                  number="02"
                  title="Evolve"
                  description="Describe a change, analyze an authorized source snapshot locally, and review candidate issues before editing code."
                  onClick={() => navigate("evolve")}
                />
              </div>
              <div className="overview-bottom">
                <div>
                  <div className="section-label">Built into both journeys</div>
                  <h2>Explain the work with a demo script.</h2>
                  <p>
                    Demo Studio helps you plan what to show a teammate or client.
                    Write scenes beside your brief and export them as JSON.
                    Rendering a video is a separate step.
                  </p>
                </div>
                <div className="artifact-stack">
                  <span>
                    01 <strong>Brief</strong>
                    <small>Requirements & acceptance criteria</small>
                  </span>
                  <span>
                    02 <strong>Local run</strong>
                    <small>Starter code & source findings</small>
                  </span>
                  <span>
                    03 <strong>Demo Studio</strong>
                    <small>Editable demo script</small>
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
                  <div className="choice-column">
                    <div className="section-label">
                      Your workspaces · {spaces.length}
                    </div>
                    {spaces.map((space) => (
                      <button
                        key={space.id}
                        type="button"
                        className={`space-choice ${active?.id === space.id ? "selected" : ""}`}
                        aria-pressed={active?.id === space.id}
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
                <div className="section-label">Activity</div>
                <h1>See recorded work.</h1>
                <p>
                  {selfHosted
                    ? "Select a project in Local run to inspect its saved analysis events."
                    : "Open a project's analysis panel to see attempts and events when a repository worker is configured."}
                </p>
              </div>
              <div className="surface-panel">
                <HardDrive size={25} />
                <h2>
                  {selfHosted
                    ? "Each analysis keeps its own timeline."
                    : "Cloud analysis needs a running worker."}
                </h2>
                <p>
                  The worker records queued, running, completed, failed and
                  canceled analysis attempts. Writing or exporting a brief does
                  not start an agent or execute code.
                </p>
                <Button variant="outline" onClick={() => navigate(selfHosted ? "evolve" : "projects")}>
                  {selfHosted ? "Open Evolve" : "Open projects"} <ArrowRight size={15} />
                </Button>
              </div>
              <div className="research-note">
                <strong>Agent learning is planned</strong>
                <p>
                  Internal evaluation tools compare submitted results for human
                  review. They do not automatically improve or deploy an agent.
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
  return <ShieldCheck size={17} aria-hidden="true" />;
}
/* The heading carries the action, so the card is a real heading plus one button
   instead of a heading nested inside a button. The overlay keeps the whole card
   clickable without adding a second tab stop. */
function JourneyCard({ icon: Icon, number, title, description, onClick }) {
  return (
    <div className="journey-card">
      <span className="journey-card-top">
        <span className="feature-icon">
          <Icon size={22} />
        </span>
        <span className="card-number">{number}</span>
      </span>
      <h2>
        <button type="button" className="journey-card-action" onClick={onClick}>
          {title}
        </button>
      </h2>
      <p>{description}</p>
      <span className="journey-card-link" aria-hidden="true">
        Open {title} <ArrowRight size={17} />
      </span>
    </div>
  );
}
