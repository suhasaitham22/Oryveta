-- Hosted projects, explicit project membership and project-associated sessions.
-- Apply AFTER supabase/schema.sql and
-- supabase/migrations/private_chats_and_explicit_sharing.sql, in that order.
-- Dedicated Oryveta project only. Additive: it creates new objects and replaces
-- exactly one existing policy (chats_insert_owner); it never drops or rewrites
-- existing user data.
--
-- Boundaries this migration deliberately keeps:
--   * Projects are persisted briefs/metadata. Nothing here executes anything,
--     schedules an agent, or connects a repository.
--   * Project membership never grants private-conversation access. The chats
--     SELECT policies are untouched; chats.project_id is an association only.
--   * Workspace membership is tenant context, never conversation access.
--   * A pending invitation grants nothing at all until the intended, verified
--     recipient accepts it in-app.
--   * Every mutation goes through a narrow SECURITY DEFINER RPC. The
--     authenticated role holds SELECT only on the four new tables, so a
--     forgotten policy fails closed instead of exposing a write path.

-- Keep table creation, RLS and privilege changes in one atomic rollout.
begin;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists public.projects(
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  name text not null check(char_length(name) between 2 and 80),
  brief text not null default '' check(char_length(brief) <= 2000),
  kind text not null check(kind in ('new','evolve')),
  source_url text check(source_url is null or
    (char_length(source_url) <= 500 and source_url ~ '^https?://[^[:space:]]{3,}$')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists projects_workspace_idx
  on public.projects(workspace_id,created_at desc);
create index if not exists projects_creator_idx on public.projects(created_by);

-- The creator's 'owner' row is provisioned inside create_project and is
-- protected from member operations; see revoke_project_member.
create table if not exists public.project_memberships(
  project_id uuid not null references public.projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check(role in ('owner','admin','engineer','reviewer','viewer')),
  created_at timestamptz not null default now(),
  primary key (project_id,user_id)
);
create index if not exists project_memberships_user_idx
  on public.project_memberships(user_id,project_id);

-- Invitation target identity mirrors public.chat_shares: either a lowercase
-- email that must match the recipient's *verified* address at acceptance time,
-- or an @alias resolved once, at insert time, to an immutable user id.
create table if not exists public.project_invitations(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  invited_by uuid not null references auth.users(id) on delete cascade,
  recipient_email text,
  recipient_alias text,
  target_user_id uuid references auth.users(id) on delete cascade,
  role text not null check(role in ('admin','engineer','reviewer','viewer')),
  status text not null default 'pending' check(status in ('pending','accepted','cancelled')),
  accepted_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  check((recipient_email is null) <> (recipient_alias is null)),
  check(recipient_email is null or
   (recipient_email=lower(recipient_email) and char_length(recipient_email)<=254 and
    recipient_email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$')),
  check(recipient_alias is null or recipient_alias ~ '^[a-z][a-z0-9_]{2,31}$'),
  check((status='accepted' and accepted_by is not null and accepted_at is not null) or
        (status<>'accepted' and accepted_by is null and accepted_at is null))
);
-- Uniqueness covers pending invitations only, so a cancelled invitation can be
-- reissued while an accepted one stays on record for replay determinism.
create unique index if not exists project_invitations_pending_email_idx
  on public.project_invitations(project_id,recipient_email)
  where status='pending' and recipient_email is not null;
create unique index if not exists project_invitations_pending_alias_idx
  on public.project_invitations(project_id,recipient_alias)
  where status='pending' and recipient_alias is not null;
create index if not exists project_invitations_target_idx
  on public.project_invitations(target_user_id,status);
create index if not exists project_invitations_email_idx
  on public.project_invitations(recipient_email,status) where recipient_email is not null;
create index if not exists project_invitations_project_idx
  on public.project_invitations(project_id,status);

-- Minimal grant/revoke/accept trail. Columns are ids, roles and timestamps
-- only: there is no free-text column, so briefs, prompts, emails and secrets
-- cannot be written here even by mistake.
create table if not exists public.project_audit_events(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  actor_id uuid not null references auth.users(id) on delete cascade,
  action text not null check(action in
    ('project_created','project_updated','member_invited',
     'invitation_accepted','invitation_cancelled','member_revoked')),
  subject_user_id uuid references auth.users(id) on delete set null,
  invitation_id uuid references public.project_invitations(id) on delete set null,
  role text check(role is null or role in ('owner','admin','engineer','reviewer','viewer')),
  created_at timestamptz not null default now()
);
create index if not exists project_audit_project_idx
  on public.project_audit_events(project_id,created_at desc);

-- ---------------------------------------------------------------------------
-- Authorization helpers. SECURITY DEFINER with a fixed empty search_path and
-- schema-qualified relations, so project policies never recurse into project
-- RLS and a caller cannot shadow a referenced object.
-- ---------------------------------------------------------------------------

create or replace function private.project_role_rank(target_role text)
returns integer language sql immutable set search_path='' as $$
  select case target_role
    when 'owner' then 5 when 'admin' then 4 when 'engineer' then 3
    when 'reviewer' then 2 when 'viewer' then 1 else 0 end
$$;
revoke all on function private.project_role_rank(text) from public,anon;
grant execute on function private.project_role_rank(text) to authenticated;

-- Effective authority over a project: an explicit project grant first,
-- otherwise the caller's membership in the project's workspace capped at
-- 'admin'. The cap keeps 'owner' meaning exactly one thing - the creator's
-- protected project_memberships row - while still letting a workspace
-- owner/admin administer projects inside their own tenant.
create or replace function private.project_role(target_project uuid)
returns text language sql stable security definer set search_path='' as $$
  select case when (select auth.uid()) is null then null else coalesce(
    (select m.role from public.project_memberships m
      where m.project_id=target_project and m.user_id=(select auth.uid())),
    (select case w.role when 'owner' then 'admin' else w.role end
      from public.projects p
      join public.workspace_memberships w
        on w.workspace_id=p.workspace_id and w.user_id=(select auth.uid())
      where p.id=target_project)) end
$$;
revoke all on function private.project_role(uuid) from public,anon;
grant execute on function private.project_role(uuid) to authenticated;

create or replace function private.can_read_project(target_project uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select private.project_role(target_project) is not null
$$;
revoke all on function private.can_read_project(uuid) from public,anon;
grant execute on function private.can_read_project(uuid) to authenticated;

create or replace function private.is_project_admin(target_project uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select private.project_role_rank(private.project_role(target_project))
       >= private.project_role_rank('admin')
$$;
revoke all on function private.is_project_admin(uuid) from public,anon;
grant execute on function private.is_project_admin(uuid) to authenticated;

-- A chat may name a project the author can read, and must not claim a
-- workspace different from that project's workspace. A project-only invitee is
-- not a workspace member, so their project chat simply carries no workspace_id.
create or replace function private.can_attach_chat_to_project(
  target_project uuid, target_workspace uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select private.project_role(target_project) is not null and exists(
    select 1 from public.projects p
     where p.id=target_project
       and (target_workspace is null or p.workspace_id=target_workspace))
$$;
revoke all on function private.can_attach_chat_to_project(uuid,uuid) from public,anon;
grant execute on function private.can_attach_chat_to_project(uuid,uuid) to authenticated;

create or replace function private.touch_project()
returns trigger language plpgsql set search_path='' as $$
begin
  new.updated_at = now();
  return new;
end
$$;
revoke all on function private.touch_project() from public,anon,authenticated;
drop trigger if exists on_project_updated on public.projects;
create trigger on_project_updated
before update on public.projects
for each row execute function private.touch_project();

-- ---------------------------------------------------------------------------
-- Row level security. SELECT only; there is no write policy because no write
-- privilege is granted - mutation goes exclusively through the RPCs below.
-- ---------------------------------------------------------------------------

alter table public.projects enable row level security;
alter table public.project_memberships enable row level security;
alter table public.project_invitations enable row level security;
alter table public.project_audit_events enable row level security;

drop policy if exists projects_select_authorized on public.projects;
create policy projects_select_authorized on public.projects
for select to authenticated
using(created_by=(select auth.uid()) or (select private.can_read_project(id)));

drop policy if exists project_memberships_select_member on public.project_memberships;
create policy project_memberships_select_member on public.project_memberships
for select to authenticated
using(user_id=(select auth.uid()) or (select private.can_read_project(project_id)));

-- Outstanding invitations are visible to the project's own admins, who entered
-- those recipients. Recipients use list_project_invitations(), which never
-- returns an address, so no account email list is ever exposed.
drop policy if exists project_invitations_select_admin on public.project_invitations;
create policy project_invitations_select_admin on public.project_invitations
for select to authenticated
using((select private.is_project_admin(project_id)));

drop policy if exists project_audit_select_admin on public.project_audit_events;
create policy project_audit_select_admin on public.project_audit_events
for select to authenticated
using((select private.is_project_admin(project_id)));

revoke all on public.projects, public.project_memberships,
  public.project_invitations, public.project_audit_events from anon, authenticated;
grant select on public.projects, public.project_memberships,
  public.project_invitations, public.project_audit_events to authenticated;

-- ---------------------------------------------------------------------------
-- Sessions: reuse public.chats. No second conversation store.
-- ---------------------------------------------------------------------------

alter table public.chats
  add column if not exists project_id uuid references public.projects(id) on delete set null;
create index if not exists chats_project_idx
  on public.chats(project_id) where project_id is not null;

-- Replaces the pre-project INSERT policy: identical owner/workspace rules plus
-- project read access and workspace consistency. Read policies are unchanged,
-- so naming a project still grants nobody else access to the conversation.
drop policy if exists chats_insert_owner on public.chats;
create policy chats_insert_owner on public.chats for insert to authenticated
with check(owner_id=(select auth.uid())
  and (workspace_id is null or (select private.is_workspace_member(workspace_id)))
  and (project_id is null or
       (select private.can_attach_chat_to_project(project_id,workspace_id))));

-- Clients keep UPDATE on chats.title only, so project association cannot be
-- rewritten from the browser; re-stated here as explicit intent.
revoke update(project_id,workspace_id,owner_id) on public.chats from anon, authenticated;

-- ---------------------------------------------------------------------------
-- Narrow mutation RPCs. Every one re-derives the actor from auth.uid(),
-- re-checks authority server side, runs with an empty search_path and is
-- executable by the authenticated role only.
-- ---------------------------------------------------------------------------

create or replace function public.create_project(
  p_workspace_id uuid, p_name text, p_brief text, p_kind text,
  p_source_url text default null)
returns table(id uuid, workspace_id uuid, created_by uuid, name text, brief text,
              kind text, source_url text, created_at timestamptz, updated_at timestamptz)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_ws_role text;
  v_row public.projects;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_kind is null or p_kind not in ('new','evolve') then
    raise exception 'project kind must be new or evolve';
  end if;
  select m.role into v_ws_role from public.workspace_memberships m
   where m.workspace_id=p_workspace_id and m.user_id=v_actor;
  if v_ws_role is null or v_ws_role not in ('owner','admin','engineer') then
    raise exception 'not allowed to create projects in this workspace';
  end if;
  insert into public.projects as p
    (workspace_id,created_by,name,brief,kind,source_url)
  values (p_workspace_id, v_actor, btrim(coalesce(p_name,'')),
          btrim(coalesce(p_brief,'')), p_kind,
          nullif(btrim(coalesce(p_source_url,'')),''))
  returning p.* into v_row;
  -- Atomic with the project row: the creator is the owner, in one call, so
  -- there is no window where a project exists without an owner.
  insert into public.project_memberships(project_id,user_id,role)
  values (v_row.id, v_actor, 'owner');
  insert into public.project_audit_events(project_id,actor_id,action,subject_user_id,role)
  values (v_row.id, v_actor, 'project_created', v_actor, 'owner');
  return query select v_row.id, v_row.workspace_id, v_row.created_by, v_row.name,
                      v_row.brief, v_row.kind, v_row.source_url,
                      v_row.created_at, v_row.updated_at;
end
$$;
revoke all on function public.create_project(uuid,text,text,text,text) from public,anon;
grant execute on function public.create_project(uuid,text,text,text,text) to authenticated;

-- Name, brief and source only. workspace_id, created_by and kind are never
-- taken from the client, so a project cannot be moved or re-owned this way.
create or replace function public.update_project(
  p_project_id uuid, p_name text, p_brief text, p_source_url text default null)
returns table(id uuid, workspace_id uuid, created_by uuid, name text, brief text,
              kind text, source_url text, created_at timestamptz, updated_at timestamptz)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_row public.projects;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if private.project_role_rank(private.project_role(p_project_id))
     < private.project_role_rank('engineer') then
    raise exception 'not allowed to edit this project';
  end if;
  update public.projects p
     set name=btrim(coalesce(p_name,'')),
         brief=btrim(coalesce(p_brief,'')),
         source_url=nullif(btrim(coalesce(p_source_url,'')),'')
   where p.id=p_project_id
  returning p.* into v_row;
  if v_row.id is null then raise exception 'project not found'; end if;
  insert into public.project_audit_events(project_id,actor_id,action)
  values (p_project_id, v_actor, 'project_updated');
  return query select v_row.id, v_row.workspace_id, v_row.created_by, v_row.name,
                      v_row.brief, v_row.kind, v_row.source_url,
                      v_row.created_at, v_row.updated_at;
end
$$;
revoke all on function public.update_project(uuid,text,text,text) from public,anon;
grant execute on function public.update_project(uuid,text,text,text) to authenticated;

-- p_recipient is a verified-email target or an existing @alias. Owner is never
-- grantable. An already-granted member is rejected outright rather than being
-- silently downgraded, and a repeated pending invitation is reused, not
-- duplicated.
create or replace function public.invite_project_member(
  p_project_id uuid, p_recipient text, p_role text)
returns table(id uuid, status text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_recipient text := lower(btrim(coalesce(p_recipient,'')));
  v_email text;
  v_alias text;
  v_target uuid;
  v_existing_target uuid;
  v_id uuid;
  v_status text;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if not private.is_project_admin(p_project_id) then
    raise exception 'not allowed to manage this project';
  end if;
  if p_role is null or p_role not in ('admin','engineer','reviewer','viewer') then
    raise exception 'role must be admin, engineer, reviewer or viewer';
  end if;
  if v_recipient like '@%' then
    v_alias := substring(v_recipient from 2);
    select a.user_id into v_target from public.user_aliases a
     where a.alias=v_alias for share;
    if v_target is null then raise exception 'recipient alias not found'; end if;
    if v_target = v_actor then raise exception 'cannot invite yourself'; end if;
  else
    v_email := v_recipient;
    if v_email = '' or char_length(v_email) > 254 or
       v_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' then
      raise exception 'recipient must be an email address or an @alias';
    end if;
    if v_email = private.verified_email() then
      raise exception 'cannot invite yourself';
    end if;
  end if;
  if v_target is not null and exists(
      select 1 from public.project_memberships m
       where m.project_id=p_project_id and m.user_id=v_target) then
    raise exception 'that user is already a project member';
  end if;
  select i.id, i.status, i.target_user_id into v_id, v_status, v_existing_target
    from public.project_invitations i
   where i.project_id=p_project_id and i.status='pending'
     and ((v_email is not null and i.recipient_email=v_email)
       or (v_alias is not null and i.recipient_alias=v_alias))
   for update;
  if v_id is not null then
    if v_alias is not null and v_existing_target is distinct from v_target then
      raise exception 'alias ownership changed; cancel the old invitation before inviting again';
    end if;
    -- Only amend an offer for the same immutable recipient.
    update public.project_invitations i
       set role=p_role, invited_by=v_actor
     where i.id=v_id and i.status='pending';
    insert into public.project_audit_events
      (project_id,actor_id,action,subject_user_id,invitation_id,role)
    values (p_project_id, v_actor, 'member_invited', v_target, v_id, p_role);
    return query select v_id, v_status;
    return;
  end if;
  insert into public.project_invitations as i
    (project_id,invited_by,recipient_email,recipient_alias,target_user_id,role)
  values (p_project_id, v_actor, v_email, v_alias, v_target, p_role)
  returning i.id, i.status into v_id, v_status;
  insert into public.project_audit_events
    (project_id,actor_id,action,subject_user_id,invitation_id,role)
  values (p_project_id, v_actor, 'member_invited', v_target, v_id, p_role);
  return query select v_id, v_status;
end
$$;
revoke all on function public.invite_project_member(uuid,text,text) from public,anon;
grant execute on function public.invite_project_member(uuid,text,text) to authenticated;

-- Pending invitations addressed to the caller. project_name is the minimal
-- disclosure that comes with being invited; it is not project read access, and
-- no recipient address is ever returned.
create or replace function public.list_project_invitations()
returns table(id uuid, project_id uuid, project_name text, invited_by uuid,
              role text, created_at timestamptz)
language sql stable security definer set search_path='' as $$
  select i.id, i.project_id, p.name, i.invited_by, i.role, i.created_at
    from public.project_invitations i
    join public.projects p on p.id=i.project_id
   where (select auth.uid()) is not null
     and i.status='pending'
     and (i.target_user_id=(select auth.uid())
       or (i.recipient_email is not null
           and i.recipient_email=private.verified_email()))
   order by i.created_at desc
$$;
revoke all on function public.list_project_invitations() from public,anon;
grant execute on function public.list_project_invitations() to authenticated;

create or replace function public.accept_project_invitation(p_invitation_id uuid)
returns table(project_id uuid)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_inv public.project_invitations;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  select i.* into v_inv from public.project_invitations i
   where i.id=p_invitation_id for update;
  if v_inv.id is null then raise exception 'invitation not found'; end if;
  -- Alias invitations are bound to an immutable user id; email invitations
  -- require the caller's confirmed address. Each branch is coalesced to false
  -- so an unmatched or unverifiable identity can never pass as unknown.
  -- Unauthorized callers get the same message as a missing row, so invitation
  -- ids are not probeable.
  if not (coalesce(v_inv.target_user_id = v_actor, false)
          or coalesce(v_inv.recipient_email = private.verified_email(), false)) then
    raise exception 'invitation not found';
  end if;
  if v_inv.status='accepted' then
    -- Deterministic replay: the recipient who accepted learns the project id
    -- again, but no membership is (re)created, so a revoked grant stays gone.
    if coalesce(v_inv.accepted_by = v_actor, false) then
      return query select v_inv.project_id;
      return;
    end if;
    raise exception 'invitation already accepted';
  end if;
  if v_inv.status<>'pending' then
    raise exception 'invitation is no longer available';
  end if;
  update public.project_invitations i
     set status='accepted', accepted_by=v_actor, accepted_at=now()
   where i.id=v_inv.id and i.status='pending';
  if not found then raise exception 'invitation is no longer available'; end if;
  -- Membership and consumed invitation land in the same statement sequence of
  -- one call. An existing grant is never downgraded and owner is never touched.
  insert into public.project_memberships as m(project_id,user_id,role)
  values (v_inv.project_id, v_actor, v_inv.role)
  on conflict on constraint project_memberships_pkey do update
     set role=v_inv.role
   where m.role<>'owner'
     and private.project_role_rank(v_inv.role) > private.project_role_rank(m.role);
  insert into public.project_audit_events
    (project_id,actor_id,action,subject_user_id,invitation_id,role)
  values (v_inv.project_id, v_actor, 'invitation_accepted', v_actor, v_inv.id, v_inv.role);
  return query select v_inv.project_id;
end
$$;
revoke all on function public.accept_project_invitation(uuid) from public,anon;
grant execute on function public.accept_project_invitation(uuid) to authenticated;

-- Removes an active grant immediately. The creator's owner row is protected.
-- An accepted invitation is kept on record but can never re-create the
-- membership (see accept_project_invitation); a still-pending invitation for
-- the same person remains acceptable until an admin cancels it.
create or replace function public.revoke_project_member(
  p_project_id uuid, p_user_id uuid)
returns void
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_target_role text;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if not private.is_project_admin(p_project_id) then
    raise exception 'not allowed to manage this project';
  end if;
  select m.role into v_target_role from public.project_memberships m
   where m.project_id=p_project_id and m.user_id=p_user_id for update;
  if v_target_role is null then return; end if;
  if v_target_role='owner' then
    raise exception 'the project owner cannot be removed';
  end if;
  delete from public.project_memberships m
   where m.project_id=p_project_id and m.user_id=p_user_id;
  insert into public.project_audit_events
    (project_id,actor_id,action,subject_user_id,role)
  values (p_project_id, v_actor, 'member_revoked', p_user_id, v_target_role);
end
$$;
revoke all on function public.revoke_project_member(uuid,uuid) from public,anon;
grant execute on function public.revoke_project_member(uuid,uuid) to authenticated;

create or replace function public.cancel_project_invitation(p_invitation_id uuid)
returns void
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_inv public.project_invitations;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  select i.* into v_inv from public.project_invitations i
   where i.id=p_invitation_id for update;
  if v_inv.id is null then raise exception 'invitation not found'; end if;
  if not private.is_project_admin(v_inv.project_id) then
    raise exception 'invitation not found';
  end if;
  if v_inv.status='accepted' then
    raise exception 'invitation already accepted';
  end if;
  if v_inv.status<>'pending' then return; end if;
  update public.project_invitations i
     set status='cancelled' where i.id=v_inv.id and i.status='pending';
  insert into public.project_audit_events
    (project_id,actor_id,action,subject_user_id,invitation_id,role)
  values (v_inv.project_id, v_actor, 'invitation_cancelled',
          v_inv.target_user_id, v_inv.id, v_inv.role);
end
$$;
revoke all on function public.cancel_project_invitation(uuid) from public,anon;
grant execute on function public.cancel_project_invitation(uuid) to authenticated;

commit;
