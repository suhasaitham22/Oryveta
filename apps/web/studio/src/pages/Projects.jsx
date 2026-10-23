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
  const clearForm = (key) =>
    setProjectDraft((current) => {
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
    if (request !== refreshRequest.current) return items;
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
    setLoading(true);
    refresh()
      .catch((problem) => setError(problem.message))
      .finally(() => setLoading(false));
    return () => { refreshRequest.current++; };
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
          <h1>Projects need a real account.</h1>
          <p>
            Preview mode never creates accounts or database rows, and it cannot
            read anyone's projects, members or invitations.
          </p>
        </div>
        <div className="surface-panel">
          <LockKeyhole size={26} />
          <h2>Sign in to create or join a project.</h2>
          <p>
            A project keeps a brief and its membership. Being invited to a
            project never grants access to someone's private conversations.
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
        <h1>Shared work, explicit access.</h1>
        <p>
          A project is a persisted brief with its own membership. Project access
          is granted per person and is separate from private conversations.
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
        className="surface-panel mb-6"
        aria-labelledby="project-invitations-heading"
      >
        <h2 id="project-invitations-heading" className="text-xl">
          Invitations · {invitations.length}
        </h2>
        <p className="text-sm text-slate-500 leading-7 mt-2">
          Pending invitations are visible only to their intended recipient. A
          pending invitation shows the project name and nothing else until you
          accept it.
        </p>
        {inboxError && <p role="alert" className="alert-error">{inboxError}</p>}
        {invitations.length ? (
          <ul className="grid gap-2 mt-4" aria-label="Pending project invitations">
            {invitations.map((invitation) => (
              <li
                key={invitation.id}
                className="flex flex-wrap items-center justify-between gap-3 border border-slate-100 rounded-xl p-3"
              >
                <div className="min-w-0">
                  <strong className="text-xs font-bold text-slate-700 break-words">
                    {invitation.project_name}
                  </strong>
                  <small className="block text-[11px] text-slate-400 mt-1">
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
          <p className="text-xs text-slate-400 leading-6 mt-4">
            Nothing pending.
          </p>
        )}
      </section>
      <div className="settings-layout">
        <div className="space-y-3">
          <div className="section-label">
            Your projects · {projects.length}
          </div>
          {loading && (
            <p role="status" className="text-xs text-slate-400">
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
            <p className="text-xs text-slate-400 leading-6">
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
        <div className="space-y-5">
          <form
            className="surface-panel"
            aria-labelledby="project-form-heading"
            onSubmit={(event) => {
              event.preventDefault();
              action(async () => {
                if (active) {
                  await projectsApi.updateProject(active.id, {
                    name,
                    brief,
                    sourceUrl,
                  });
                  clearForm(active.id);
                  await refresh(active.id);
                  setNotice("Project saved.");
                } else {
                  const created = await projectsApi.createProject(
                    user,
                    workspaceId,
                    { name, brief, kind, sourceUrl },
                  );
                  clearForm("new");
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
              <p className="text-xs text-slate-500 mt-2">
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
                    className="w-full"
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
                  <span id="project-workspace-help" className="text-[11px] text-slate-400 leading-5">
                    Creating a project requires owner, admin or engineer
                    membership in that workspace. The server rejects anything
                    else.
                  </span>
                </div>
              ) : (
                <p className="notice">
                  You need a workspace first.{" "}
                  <Link className="underline" to="/workspace/settings">
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
                  className="w-full"
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
              <h2 id="project-members-heading" className="text-xl">
                <UsersRound size={18} className="inline mr-2" />
                Members · {members.length}
              </h2>
              <p className="text-sm text-slate-500 leading-7 mt-2">
                Project membership is explicit. It never grants access to
                anyone's private conversations, and the owner cannot be removed
                or demoted here.
              </p>
              {memberNotice && (
                <p role="status" className="notice">
                  {memberNotice}
                </p>
              )}
              <ul className="grid gap-2 mt-4" aria-label="Project members">
                {members.length ? (
                  members.map((member) => (
                    <li
                      key={member.user_id}
                      className="flex flex-wrap items-center justify-between gap-3 border border-slate-100 rounded-xl p-3"
                    >
                      <div className="min-w-0">
                        <strong className="text-xs font-bold text-slate-700">
                          Account {shortId(member.user_id)}
                          {member.user_id === user.id ? " (you)" : ""}
                        </strong>
                        <small className="block text-[11px] text-slate-400 mt-1">
                          {roleLabels[member.role] || member.role}
                        </small>
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
                  <li className="text-xs text-slate-400">
                    No member list is available to you for this project.
                  </li>
                )}
              </ul>
              {canAdmin ? (
                <>
                  <h3 className="text-sm font-bold text-slate-800 flex gap-2 items-center mt-8">
                    <UserPlus size={18} /> Invite someone
                  </h3>
                  <p className="text-xs text-slate-500 leading-6 mt-2">
                    Invite a verified work email or a registered @alias.
                    Recipients gain nothing until they accept in-app, and owner
                    cannot be granted.
                  </p>
                  <form
                    className="grid sm:grid-cols-[1fr_150px_auto] gap-3 mt-4 items-end"
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
                    <label
                      className="text-[11px] font-bold text-slate-600"
                      htmlFor="project-invite-recipient"
                    >
                      Recipient
                      <Input
                        id="project-invite-recipient"
                        className="mt-2"
                        required
                        maxLength={254}
                        placeholder="user@company.com or @alias"
                        value={recipient}
                        onChange={(event) => setRecipient(event.target.value)}
                      />
                    </label>
                    <div className="text-[11px] font-bold text-slate-600">
                      <label htmlFor="project-invite-role">Role</label>
                      <select
                        id="project-invite-role"
                        className="w-full mt-2 h-10 rounded-xl border border-slate-200 px-2 text-xs text-slate-600 bg-white"
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
                  <div className="section-label mt-8">
                    Pending invitations · {sentInvites.length}
                  </div>
                  <ul
                    className="grid gap-2 mt-3"
                    aria-label="Outstanding project invitations"
                  >
                    {sentInvites.length ? (
                      sentInvites.map((invitation) => (
                        <li
                          key={invitation.id}
                          className="flex flex-wrap items-center justify-between gap-3 border border-slate-100 rounded-xl p-3"
                        >
                          <div className="min-w-0">
                            <strong className="text-xs text-slate-700 break-words">
                              {invitation.recipient_email ||
                                `@${invitation.recipient_alias}`}
                            </strong>
                            <small className="block text-[11px] text-slate-400 mt-1">
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
                      <li className="text-xs text-slate-400">
                        No outstanding invitations.
                      </li>
                    )}
                  </ul>
                </>
              ) : (
                <p className="text-xs text-slate-400 leading-6 mt-6 border-t border-slate-100 pt-5">
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
