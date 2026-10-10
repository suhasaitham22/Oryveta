-- Oryveta startup identity/workspace foundation.
-- Run in a dedicated Supabase project after review; never in an unrelated project.
-- Auth identities are managed by Supabase Auth; only owner-created workspaces
-- are writable in v1. Team invitations and elevated roles require a later
-- audited server-side workflow, not client-side INSERT/UPDATE of memberships.

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 80),
  slug text not null check (slug ~ '^[a-z][a-z0-9-]{2,39}$'),
  description text not null default '' check (char_length(description) <= 500),
  created_by uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (created_by, slug)
);

create table if not exists public.workspace_memberships (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner','admin','engineer','reviewer','viewer')),
  created_at timestamptz not null default now(),
  primary key (workspace_id,user_id)
);
create index if not exists workspace_memberships_user_idx
  on public.workspace_memberships(user_id,workspace_id);

-- Deliberately private SECURITY DEFINER to avoid recursive membership RLS.
-- Fixed empty search_path, schema-qualified relations and auth.uid() check.
create or replace function private.is_workspace_member(target_workspace uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select (select auth.uid()) is not null and exists (
    select 1 from public.workspace_memberships m
    where m.workspace_id = target_workspace
      and m.user_id = (select auth.uid())
  )
$$;
revoke all on function private.is_workspace_member(uuid) from public, anon;
grant execute on function private.is_workspace_member(uuid) to authenticated;

create or replace function private.add_workspace_owner()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
begin
  if (select auth.uid()) is null or new.created_by <> (select auth.uid()) then
    raise exception 'workspace creator must be the authenticated user';
  end if;
  insert into public.workspace_memberships(workspace_id,user_id,role)
  values (new.id,new.created_by,'owner');
  return new;
end
$$;
revoke all on function private.add_workspace_owner() from public, anon, authenticated;

drop trigger if exists on_workspace_created on public.workspaces;
create trigger on_workspace_created
after insert on public.workspaces
for each row execute function private.add_workspace_owner();

create or replace function private.touch_workspace()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end
$$;
revoke all on function private.touch_workspace() from public, anon, authenticated;
drop trigger if exists on_workspace_updated on public.workspaces;
create trigger on_workspace_updated
before update on public.workspaces
for each row execute function private.touch_workspace();

alter table public.workspaces enable row level security;
alter table public.workspace_memberships enable row level security;

drop policy if exists workspace_select_member on public.workspaces;
create policy workspace_select_member on public.workspaces
for select to authenticated
using (private.is_workspace_member(id));

drop policy if exists workspace_insert_self on public.workspaces;
create policy workspace_insert_self on public.workspaces
for insert to authenticated
with check (created_by = (select auth.uid()));

drop policy if exists workspace_update_owner on public.workspaces;
create policy workspace_update_owner on public.workspaces
for update to authenticated
using (created_by = (select auth.uid()))
with check (created_by = (select auth.uid()));

drop policy if exists workspace_delete_owner on public.workspaces;
create policy workspace_delete_owner on public.workspaces
for delete to authenticated
using (created_by = (select auth.uid()));

drop policy if exists membership_select_member on public.workspace_memberships;
create policy membership_select_member on public.workspace_memberships
for select to authenticated
using (private.is_workspace_member(workspace_id));

revoke all on public.workspaces, public.workspace_memberships from anon;
grant select,insert,update,delete on public.workspaces to authenticated;
grant select on public.workspace_memberships to authenticated;
revoke insert,update,delete on public.workspace_memberships from authenticated;
