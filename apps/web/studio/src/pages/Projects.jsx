import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Layers3,
  LockKeyhole,
  Plus,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import * as projectsApi from "@/lib/projects.js";
import { useWorkspaceState } from "@/lib/WorkspaceState.jsx";
import ProjectAnalysis from "@/components/ProjectAnalysis.jsx";

/* PostgreSQL authorizes project metadata, membership and bounded analysis.
   UI role checks only shape controls; an analysis never executes repository code. */
const roleLabels = {
  owner: "Owner",
  admin: "Admin",
  engineer: "Engineer",
  reviewer: "Reviewer",
  viewer: "Viewer",
};
const shortId = (id) => `${String(id || "").slice(0, 8)}…`;

export default function Projects({ user, preview, onExit }) {
  const { spaces, projectDraft, setProjectDraft } = useWorkspaceState();
  const [projects, setProjects] = useState([]);
  const [roles, setRoles] = useState({});
  const [invitations, setInvitations] = useState([]);
  const [inboxError, setInboxError] = useState("");
  const [members, setMembers] = useState([]);
  const [sentInvites, setSentInvites] = useState([]);
  const [memberNotice, setMemberNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [rev, setRev] = useState(0);
  const refreshRequest = useRef(0);
  /* False once this page instance has been left. Drafts and the selection live in the
     workspace provider and outlive the page, so a mutation that completes afterwards must
     not write to them. */
  const mounted = useRef(false);

  const selected = projectDraft.selected;
  const active = projects.find((project) => project.id === selected) || null;
  const role = active ? roles[active.id] : undefined;
  const canEdit = projectsApi.canEditProject(role);
  const canAdmin = projectsApi.canAdministerProject(role);
  const formKey = active?.id || "new";
  const form = projectDraft.forms[formKey] || {};
  const name = form.name ?? active?.name ?? "";
  const brief = form.brief ?? active?.brief ?? "";
  const kind = form.kind ?? active?.kind ?? "new";
  const sourceUrl = form.sourceUrl ?? active?.source_url ?? "";
  const workspaceId = projectDraft.workspaceId || spaces[0]?.id || "";
  const recipient = projectDraft.recipients[formKey] || "";
  const grantRole = projectDraft.roles[formKey] || "viewer";

  const select = (value) =>
    setProjectDraft((current) => ({ ...current, selected: value }));
  const editForm = (field, value) =>
    setProjectDraft((current) => ({
      ...current,
      forms: {
        ...current.forms,
        [formKey]: { ...current.forms[formKey], [field]: value },
      },
    }));
  /* `submitted` is the exact draft object that was sent. If the draft has changed since, the
     newer text is kept: a completion only clears what it saved. */
  const clearForm = (key, submitted) =>
    setProjectDraft((current) => {
      if (current.forms[key] !== submitted) return current;
      const forms = { ...current.forms };
      delete forms[key];
      return { ...current, forms };
    });
  const setRecipient = (value) =>
    setProjectDraft((current) => ({
      ...current,
      recipients: { ...current.recipients, [formKey]: value },
    }));
  const setGrantRole = (value) =>
    setProjectDraft((current) => ({
      ...current,
      roles: { ...current.roles, [formKey]: value },
    }));

  async function refresh(prefer) {
    if (preview || !user) return;
    const request = ++refreshRequest.current;
    const [items, mine, inbox] = await Promise.all([
      projectsApi.listProjects(),
      projectsApi.listProjectRoles(user),
      projectsApi.listProjectInvitations().then(
        (items) => ({ items }),
        (error) => ({ error }),
      ),
    ]);
    if (request !== refreshRequest.current || !mounted.current) return items;
    setProjects(items);
    setRoles(
      Object.fromEntries(mine.map((row) => [row.project_id, row.role])),
    );
    setInvitations(inbox.items || []);
    setInboxError(inbox.error?.message || "");
    /* Access can disappear between loads (membership revoked, different account).
       Drop the selection and every cached draft for projects we can no longer read,
       so no brief, member list or invitation stays on screen. */
    setProjectDraft((current) => {
      const readable = (key) => key === "new" || items.some((p) => p.id === key);
      const keep = (source) =>
        Object.fromEntries(
          Object.entries(source).filter(([key]) => readable(key)),
        );
      const next = prefer ?? current.selected;
      return {
        ...current,
        selected: items.some((project) => project.id === next) ? next : "",
        forms: keep(current.forms),
        recipients: keep(current.recipients),
        roles: keep(current.roles),
      };
    });
    setRev((value) => value + 1);
    return items;
  }
  useEffect(() => {
    if (preview || !user) return;
    mounted.current = true;
    setLoading(true);
    refresh()
      .catch((problem) => {
        if (mounted.current) setError(problem.message);
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
      refreshRequest.current++;
    };
  }, [preview, user?.id]);
  useEffect(() => {
    if (!selected || preview) {
      setMembers([]);
      setSentInvites([]);
      setMemberNotice("");
      return;
    }
    let alive = true;
    setMembers([]);
    setSentInvites([]);
    setMemberNotice("");
    Promise.allSettled([
      projectsApi.listProjectMembers(selected),
      projectsApi.listSentProjectInvitations(selected),
    ]).then(([memberResult, inviteResult]) => {
      if (!alive) return;
      setMembers(
        memberResult.status === "fulfilled" ? memberResult.value : [],
      );
      setSentInvites(
        inviteResult.status === "fulfilled" ? inviteResult.value : [],
      );
      setMemberNotice(
        memberResult.status === "rejected"
          ? memberResult.reason.message
          : inviteResult.status === "rejected"
            ? inviteResult.reason.message
            : "",
      );
    });
    return () => {
      alive = false;
    };
  }, [selected, rev, preview]);

  async function action(task) {
    if (busy || preview || !user) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  if (preview)
    return (
      <>
        <div className="page-heading">
          <div className="section-label">Projects</div>
          <h1>Sign in to manage your projects.</h1>
          <p>
            Save a project brief, invite collaborators and choose who can
            view or edit the project.
          </p>
        </div>
        <div className="surface-panel">
          <LockKeyhole size={26} />
          <h2>Sign in to create or join a project.</h2>
          <p>
            Projects organize the work and its members. Private conversations
            have separate invitations, so joining a project does not share chats.
          </p>
          <Button onClick={onExit}>
            Return to sign in <ArrowRight size={16} />
          </Button>
        </div>
      </>
    );

  return (
    <>
      <div className="page-heading">
        <div className="section-label">Projects</div>
        <h1>Your projects</h1>
        <p>
          Keep each project's brief, source link and collaborators together.
          Project access and private-conversation sharing are managed separately.
        </p>
      </div>
      {error && (
        <p role="alert" className="alert-error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="alert-success">
          {notice}
        </p>
      )}
      <section
        className="surface-panel invitations-panel"
        aria-labelledby="project-invitations-heading"
      >
        <h2 id="project-invitations-heading">
          Invitations · {invitations.length}
        </h2>
        <p className="panel-note">
          Pending invitations are visible only to their intended recipient. A
          pending invitation shows the project name and nothing else until you
          accept it.
        </p>
        {inboxError && <p role="alert" className="alert-error">{inboxError}</p>}
        {invitations.length ? (
          <ul className="record-list" aria-label="Pending project invitations">
            {invitations.map((invitation) => (
              <li key={invitation.id} className="record">
                <div className="record-main">
                  <strong>
                    {invitation.project_name}
                  </strong>
                  <small>
                    {roleLabels[invitation.role] || invitation.role} · invited by{" "}
                    {shortId(invitation.invited_by)}
                  </small>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  aria-label={`Accept invitation to ${invitation.project_name}`}
                  onClick={() =>
                    action(async () => {
                      const accepted =
                        await projectsApi.acceptProjectInvitation(
                          invitation.id,
                        );
                      /* Accepting is a re-check, not a guarantee: replaying an
                         invitation never restores access that was revoked. */
                      const readable = await refresh(accepted.project_id);
                      setNotice(
                        (readable || []).some(
                          (project) => project.id === accepted.project_id,
                        )
                          ? "Invitation accepted. You now have access to this project."
                          : "That invitation no longer grants access, because your membership was removed. Ask a project admin to invite you again.",
                      );
                    })
                  }
                >
                  <CheckCircle2 size={14} /> Accept invitation
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="record-empty">Nothing pending.</p>
        )}
      </section>
      <div className="settings-layout">
        <div className="choice-column">
          <div className="section-label">
            Your projects · {projects.length}
          </div>
          {loading && (
            <p role="status" className="record-empty">
              Loading projects…
            </p>
          )}
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={`space-choice ${active?.id === project.id ? "selected" : ""}`}
              aria-pressed={active?.id === project.id}
              onClick={() => select(project.id)}
            >
              <strong>{project.name}</strong>
              <span>
                {project.kind === "evolve" ? "Evolve" : "Start new"} ·{" "}
                {roles[project.id]
                  ? roleLabels[roles[project.id]]
                  : "Workspace access, no project role"}
                {!spaces.some((space) => space.id === project.workspace_id) &&
                  " · shared from a workspace you are not in"}
              </span>
            </button>
          ))}
          {!loading && !projects.length && (
            <p className="record-empty">
              No projects you can read yet. Create one below, or accept an
              invitation when someone shares theirs.
            </p>
          )}
          {active && (
            <Button
              variant="outline"
              onClick={() => select("")}
              aria-label="Start a new project"
            >
              <Plus size={15} />
              New project
            </Button>
          )}
        </div>
        <div className="detail-column">
          <form
            className="surface-panel"
            aria-labelledby="project-form-heading"
            onSubmit={(event) => {
              event.preventDefault();
              /* The draft exactly as submitted, so a completion that arrives after further
                 edits — or after this page was left and reopened — clears nothing newer. */
              const submitted = projectDraft.forms[formKey];
              action(async () => {
                if (active) {
                  await projectsApi.updateProject(active.id, {
                    name,
                    brief,
                    sourceUrl,
                  });
                  if (!mounted.current) return;
                  clearForm(active.id, submitted);
                  await refresh(active.id);
                  setNotice("Project saved.");
                } else {
                  const created = await projectsApi.createProject(
                    user,
                    workspaceId,
                    { name, brief, kind, sourceUrl },
                  );
                  if (!mounted.current) return;
                  clearForm("new", submitted);
                  await refresh(created.id);
                  setNotice(
                    "Project created. You are its owner; invite people explicitly.",
                  );
                }
              });
            }}
          >
            <h2 id="project-form-heading">
              {active ? "Project brief" : "New project"}
            </h2>
            <p>
              {active
                ? canEdit
                  ? "Owners, admins and engineers may edit this brief."
                  : "You have read access to this project. Editing is restricted to owner, admin and engineer roles."
                : "Persisted as a brief in a workspace you belong to. Creating a project does not build or deploy anything."}
            </p>
            {active && (
              <p className="role-line">
                Your role:{" "}
                <Badge variant="outline">
                  {roles[active.id]
                    ? roleLabels[roles[active.id]]
                    : "No project role"}
                </Badge>
              </p>
            )}
            {!active &&
              (spaces.length ? (
                <div className="field-label">
                  <label htmlFor="project-workspace">Workspace</label>
                  <select
                    id="project-workspace"
                    aria-describedby="project-workspace-help"
                    value={workspaceId}
                    disabled={busy}
                    onChange={(event) =>
                      setProjectDraft((current) => ({
                        ...current,
                        workspaceId: event.target.value,
                      }))
                    }
                  >
                    {spaces.map((space) => (
                      <option key={space.id} value={space.id}>
                        {space.name}
                      </option>
                    ))}
                  </select>
                  <span id="project-workspace-help" className="field-help">
                    Creating a project requires owner, admin or engineer
                    membership in that workspace. The server rejects anything
                    else.
                  </span>
                </div>
              ) : (
                <p className="notice">
                  You need a workspace first.{" "}
                  <Link to="/workspace/settings">
                    Create a workspace
                  </Link>
                  , then return here.
                </p>
              ))}
            {!active && (
              <div className="field-label">
                <label htmlFor="project-kind">Project type</label>
                <select
                  id="project-kind"
                  value={kind}
                  disabled={busy}
                  onChange={(event) => editForm("kind", event.target.value)}
                >
                  <option value="new">Start new</option>
                  <option value="evolve">Evolve an existing codebase</option>
                </select>
              </div>
            )}
            <label className="field-label" htmlFor="project-name">
              Project name
              <Input
                id="project-name"
                required
                minLength={2}
                maxLength={80}
                value={name}
                disabled={busy || (!!active && !canEdit)}
                onChange={(event) => editForm("name", event.target.value)}
              />
            </label>
            <div className="field-label">
              <label htmlFor="project-brief">What is this project for?</label>
              <Textarea
                id="project-brief"
                maxLength={2000}
                value={brief}
                disabled={busy || (!!active && !canEdit)}
                placeholder="Intent, constraints and what done looks like."
                onChange={(event) => editForm("brief", event.target.value)}
              />
            </div>
            {(kind === "evolve" || sourceUrl) && (
              <label className="field-label" htmlFor="project-source">
                Source URL (optional)
                <Input
                  id="project-source"
                  type="url"
                  maxLength={500}
                  value={sourceUrl}
                  disabled={busy || (!!active && !canEdit)}
                  placeholder="https://github.com/org/repo"
                  onChange={(event) =>
                    editForm("sourceUrl", event.target.value)
                  }
                />
              </label>
            )}
            {(!active || canEdit) && (
              <Button
                type="submit"
                disabled={busy || (!active && !spaces.length)}
              >
                {busy
                  ? "Saving…"
                  : active
                    ? "Save project"
                    : "Create project"}
              </Button>
            )}
          </form>
          {active && <ProjectAnalysis key={active.id} project={active} role={role} />}
          {active && (
            <section
              className="surface-panel"
              aria-labelledby="project-members-heading"
            >
              <h2 id="project-members-heading" className="panel-head-title">
                <UsersRound size={18} aria-hidden="true" />
                Members · {members.length}
              </h2>
              <p className="panel-note">
                Project membership is explicit. It never grants access to
                anyone's private conversations, and the owner cannot be removed
                or demoted here.
              </p>
              {memberNotice && (
                <p role="status" className="notice">
                  {memberNotice}
                </p>
              )}
              <ul className="record-list" aria-label="Project members">
                {members.length ? (
                  members.map((member) => (
                    <li key={member.user_id} className="record">
                      <div className="record-main">
                        <strong>
                          Account {shortId(member.user_id)}
                          {member.user_id === user.id ? " (you)" : ""}
                        </strong>
                        <small>{roleLabels[member.role] || member.role}</small>
                      </div>
                      {canAdmin && member.role !== "owner" && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          aria-label={`Remove account ${shortId(member.user_id)} from this project`}
                          onClick={() =>
                            action(async () => {
                              await projectsApi.revokeProjectMember(
                                active.id,
                                member.user_id,
                              );
                              await refresh();
                              setNotice("Project access removed.");
                            })
                          }
                        >
                          Remove member
                        </Button>
                      )}
                    </li>
                  ))
                ) : (
                  <li className="record-empty">
                    No member list is available to you for this project.
                  </li>
                )}
              </ul>
              {canAdmin ? (
                <>
                  <h3 className="panel-subhead panel-section">
                    <UserPlus size={18} /> Invite someone
                  </h3>
                  <p className="muted-note">
                    Invite a verified work email or a registered @alias.
                    Recipients gain nothing until they accept in-app, and owner
                    cannot be granted.
                  </p>
                  <form
                    className="invite-grid"
                    onSubmit={(event) => {
                      event.preventDefault();
                      action(async () => {
                        const result = await projectsApi.inviteProjectMember(
                          active.id,
                          recipient,
                          grantRole,
                        );
                        setRecipient("");
                        setRev((value) => value + 1);
                        setNotice(
                          sentInvites.some(
                            (invitation) => invitation.id === result?.id,
                          )
                            ? "Existing invitation updated. The recipient still has no access until they accept."
                            : "Invitation created. It grants no access until the recipient accepts.",
                        );
                      });
                    }}
                  >
                    <label className="field-label" htmlFor="project-invite-recipient">
                      Recipient
                      <Input
                        id="project-invite-recipient"
                        required
                        maxLength={254}
                        placeholder="user@company.com or @alias"
                        value={recipient}
                        onChange={(event) => setRecipient(event.target.value)}
                      />
                    </label>
                    <div className="field-label">
                      <label htmlFor="project-invite-role">Role</label>
                      <select
                        id="project-invite-role"
                        value={grantRole}
                        onChange={(event) => setGrantRole(event.target.value)}
                      >
                        {projectsApi.INVITABLE_ROLES.map((value) => (
                          <option key={value} value={value}>
                            {roleLabels[value]}
                          </option>
                        ))}
                      </select>
                    </div>
                    <Button type="submit" disabled={busy}>
                      Send invitation <ArrowRight size={15} />
                    </Button>
                  </form>
                  <div className="section-label panel-section">
                    Pending invitations · {sentInvites.length}
                  </div>
                  <ul
                    className="record-list"
                    aria-label="Outstanding project invitations"
                  >
                    {sentInvites.length ? (
                      sentInvites.map((invitation) => (
                        <li key={invitation.id} className="record">
                          <div className="record-main">
                            <strong>
                              {invitation.recipient_email ||
                                `@${invitation.recipient_alias}`}
                            </strong>
                            <small>
                              {roleLabels[invitation.role] || invitation.role} ·
                              not yet accepted, no access
                            </small>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            aria-label={`Cancel invitation for ${invitation.recipient_email || `@${invitation.recipient_alias}`}`}
                            onClick={() =>
                              action(async () => {
                                await projectsApi.cancelProjectInvitation(
                                  invitation.id,
                                );
                                setRev((value) => value + 1);
                                setNotice("Invitation cancelled.");
                              })
                            }
                          >
                            Cancel invitation
                          </Button>
                        </li>
                      ))
                    ) : (
                      <li className="record-empty">
                        No outstanding invitations.
                      </li>
                    )}
                  </ul>
                </>
              ) : (
                <p className="muted-note panel-section">
                  Only the project owner and admins can invite, cancel
                  invitations or remove members.
                </p>
              )}
            </section>
          )}
        </div>
      </div>
      <div className="research-note">
        <ShieldCheck size={18} />
        <strong>Access is checked in the database, not in this page</strong>
        <p>
          Controls you cannot use are shown honestly instead of silently
          failing. Hidden buttons are never the protection: every create,
          invite, accept, cancel and removal is authorized server-side, and a
          project association never exposes a private conversation.
        </p>
        <Link to="/workspace/chats">
          <Layers3 size={15} /> Open conversations
        </Link>
      </div>
    </>
  );
}
