/* Data access for hosted projects. PostgreSQL RLS and SECURITY DEFINER RPCs—not these
   helpers—authorize every read and write. Role checks exported here are presentation only:
   a hidden button is never the thing that stops an unauthorized write.
   Projects are persisted briefs and metadata. Nothing here starts or reports a run. */
import { supabase } from "./identity.js";

/* Owner is the creator and is never granted through an invitation. */
export const INVITABLE_ROLES = ["admin", "engineer", "reviewer", "viewer"];
export const PROJECT_KINDS = ["new", "evolve"];
const EDITOR_ROLES = ["owner", "admin", "engineer"];
const ADMIN_ROLES = ["owner", "admin"];
export const canEditProject = (role) => EDITOR_ROLES.includes(role);
export const canAdministerProject = (role) => ADMIN_ROLES.includes(role);

const PROJECT_FIELDS =
  "id,workspace_id,created_by,name,brief,kind,source_url,created_at,updated_at";
const MEMBER_FIELDS = "project_id,user_id,role,created_at";
const INVITATION_FIELDS =
  "id,project_id,invited_by,recipient_email,recipient_alias,role,status,created_at";
/* Postgres/PostgREST codes meaning the projects schema has not been applied yet. */
const MISSING_SCHEMA = ["42P01", "42883", "PGRST202", "PGRST205"];

function data(result, context) {
  if (!result.error) return result.data;
  const { code, message } = result.error;
  if (MISSING_SCHEMA.includes(code))
    throw Error(
      "Projects are unavailable because the projects migration has not been applied to this Supabase project yet.",
    );
  throw Error(message || context);
}
function text(value, label, { min = 0, max }) {
  const clean = String(value ?? "").trim();
  if (clean.length < min || clean.length > max)
    throw Error(
      min
        ? `${label} must be ${min}–${max} characters`
        : `${label} must be ${max} characters or fewer`,
    );
  return clean;
}
function sourceUrl(value) {
  const clean = String(value ?? "").trim();
  if (!clean) return null;
  if (clean.length > 500) throw Error("Source URL must be 500 characters or fewer");
  let parsed;
  try {
    parsed = new URL(clean);
  } catch {
    throw Error("Enter a full source URL, for example https://github.com/org/repo");
  }
  if (!["http:", "https:"].includes(parsed.protocol))
    throw Error("Source URL must use http or https");
  return clean;
}
function recipientTarget(recipient) {
  const value = String(recipient || "").trim().toLowerCase();
  const alias = value.startsWith("@");
  if (
    alias
      ? !/^@[a-z][a-z0-9_]{2,31}$/.test(value)
      : !(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length <= 254)
  )
    throw Error("Use an email address or registered @alias");
  return value;
}

/* Every project the signed-in user may read, including projects shared from a
   workspace they are not a member of. Workspace names are deliberately not joined. */
export async function listProjects() {
  return (
    data(
      await supabase
        .from("projects")
        .select(PROJECT_FIELDS)
        .order("created_at", { ascending: false })
        .limit(200),
      "Could not load projects",
    ) || []
  );
}
/* The caller's own membership rows, used to label roles without reading other members. */
export async function listProjectRoles(user) {
  if (!user?.id) throw Error("Authentication required");
  return (
    data(
      await supabase
        .from("project_memberships")
        .select(MEMBER_FIELDS)
        .eq("user_id", user.id)
        .limit(200),
      "Could not load your project roles",
    ) || []
  );
}
export async function listProjectMembers(projectId) {
  if (!projectId) throw Error("Select a project first");
  return (
    data(
      await supabase
        .from("project_memberships")
        .select(MEMBER_FIELDS)
        .eq("project_id", projectId)
        .order("created_at")
        .limit(200),
      "Could not load project members",
    ) || []
  );
}
/* Outstanding invitations for one project, readable by its admins. Recipients use
   listProjectInvitations() instead; this never lists accounts outside this project. */
export async function listSentProjectInvitations(projectId) {
  if (!projectId) throw Error("Select a project first");
  return (
    data(
      await supabase
        .from("project_invitations")
        .select(INVITATION_FIELDS)
        .eq("project_id", projectId)
        .eq("status", "pending")
        .order("created_at")
        .limit(100),
      "Could not load project invitations",
    ) || []
  );
}
export async function createProject(user, workspaceId, { name, brief, kind, sourceUrl: source }) {
  if (!user?.id) throw Error("Authentication required");
  if (!workspaceId) throw Error("Choose a workspace for this project");
  if (!PROJECT_KINDS.includes(kind)) throw Error("Choose a project type");
  return data(
    await supabase
      .rpc("create_project", {
        p_workspace_id: workspaceId,
        p_name: text(name, "Project name", { min: 2, max: 80 }),
        p_brief: text(brief, "Brief", { max: 2000 }),
        p_kind: kind,
        p_source_url: sourceUrl(source),
      })
      .select(PROJECT_FIELDS)
      .single(),
    "Could not create the project",
  );
}
export async function updateProject(projectId, { name, brief, sourceUrl: source }) {
  if (!projectId) throw Error("Select a project first");
  return data(
    await supabase
      .rpc("update_project", {
        p_project_id: projectId,
        p_name: text(name, "Project name", { min: 2, max: 80 }),
        p_brief: text(brief, "Brief", { max: 2000 }),
        p_source_url: sourceUrl(source),
      })
      .select(PROJECT_FIELDS)
      .single(),
    "Could not save the project",
  );
}
export async function inviteProjectMember(projectId, recipient, role) {
  if (!projectId) throw Error("Select a project first");
  if (!INVITABLE_ROLES.includes(role)) throw Error("Choose a role to grant");
  return data(
    await supabase
      .rpc("invite_project_member", {
        p_project_id: projectId,
        p_recipient: recipientTarget(recipient),
        p_role: role,
      })
      .select("id,status")
      .single(),
    "Could not create the invitation",
  );
}
/* Pending invitations addressed to the signed-in account. A pending invitation
   discloses the project name only; it is not project membership or project read access. */
export async function listProjectInvitations() {
  return (
    data(
      await supabase
        .rpc("list_project_invitations")
        .select("id,project_id,project_name,invited_by,role,created_at"),
      "Could not load your invitations",
    ) || []
  );
}
export async function acceptProjectInvitation(invitationId) {
  if (!invitationId) throw Error("Invitation is no longer available");
  return data(
    await supabase
      .rpc("accept_project_invitation", { p_invitation_id: invitationId })
      .select("project_id")
      .single(),
    "Could not accept the invitation",
  );
}
export async function revokeProjectMember(projectId, userId) {
  if (!projectId || !userId) throw Error("Select a member to remove");
  data(
    await supabase.rpc("revoke_project_member", {
      p_project_id: projectId,
      p_user_id: userId,
    }),
    "Could not remove this member",
  );
}
export async function cancelProjectInvitation(invitationId) {
  if (!invitationId) throw Error("Invitation is no longer available");
  data(
    await supabase.rpc("cancel_project_invitation", {
      p_invitation_id: invitationId,
    }),
    "Could not cancel this invitation",
  );
}
