-- Durable, project-authorized factory work: work items, fenced runs, typed
-- events and project-scoped worker identities.
--
-- Apply AFTER supabase/schema.sql,
-- supabase/migrations/private_chats_and_explicit_sharing.sql and
-- supabase/migrations/projects_and_project_membership.sql, in that order.
-- Dedicated Oryveta project only. Additive: it creates new objects and does not
-- drop, rewrite or re-policy anything an earlier file owns.
--
-- Boundaries this migration deliberately keeps:
--   * One metadata authority. Local SQLite stays a development-mode engine;
--     nothing here mirrors or synchronizes it.
--   * Exactly one real task kind, 'repository_analysis'. It analyses the
--     project's own frozen public GitHub source URL with the existing bounded
--     importer and static analyzer. No arbitrary command, host path, model
--     inference or private-repository claim exists in this schema.
--   * Browsers never mutate run state. The authenticated role holds SELECT
--     only, so a forgotten policy fails closed instead of exposing a write.
--   * Workers authenticate as their own Supabase Auth users and must hold an
--     enabled public.project_workers registration for the exact project they
--     act on. No anonymous RPC, shared secret or service-role key participates.
--   * The lease fencing token lives in the unexposed `private` schema, so a
--     user-facing read of a run can never return it.
--   * Every text column is either an id, a short enumerated code or a bounded
--     derived detail. There is no free-text column a credential or host
--     filesystem path could be written into.

-- One transaction: Supabase grants default table privileges to anon and
-- authenticated in the public schema, so CREATE TABLE and the matching
-- REVOKE/RLS statements must not be separately visible to a concurrent session.
begin;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- A worker identity is a separate Supabase Auth user, registered for one
-- project by that project's owner/admin. It is not a project member: it never
-- receives project read access through membership, and a member's browser
-- session never receives worker authority.
create table if not exists public.project_workers(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  worker_user_id uuid not null references auth.users(id) on delete cascade,
  label text not null check(label ~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{1,59}$'),
  enabled boolean not null default true,
  registered_by uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  -- Named explicitly so register_project_worker can infer the conflict target
  -- by constraint name: an ON CONFLICT column list would collide with that
  -- function's identically named OUT parameters.
  constraint project_workers_scope_key unique (project_id, worker_user_id),
  check((enabled and revoked_at is null and revoked_by is null)
     or (not enabled and revoked_at is not null))
);
create index if not exists project_workers_worker_idx
  on public.project_workers(worker_user_id, project_id) where enabled;

-- Accepted work. created_by, source identity and input_digest are frozen at
-- submission: the request that was authorized is the request that runs, even if
-- the project's source_url is edited afterwards.
create table if not exists public.work_items(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  kind text not null check(kind in ('repository_analysis')),
  status text not null default 'queued'
    check(status in ('queued','running','succeeded','failed','cancelled')),
  source_url text not null check(char_length(source_url) <= 500),
  source_owner text not null check(source_owner ~ '^[A-Za-z0-9_.-]{1,100}$'),
  source_repo text not null check(source_repo ~ '^[A-Za-z0-9_.-]{1,100}$'),
  input_digest text not null check(input_digest ~ '^[0-9a-f]{64}$'),
  idempotency_key text check(idempotency_key ~ '^[A-Za-z0-9._:-]{8,120}$'),
  attempts integer not null default 0 check(attempts between 0 and 5),
  max_attempts integer not null default 2 check(max_attempts between 1 and 5),
  error_code text check(error_code ~ '^[a-z][a-z0-9_]{2,47}$'),
  -- The source identity every attempt of this work item must analyse. It is
  -- empty until the first attempt resolves a repository reference and a commit
  -- together, and immutable afterwards: a later attempt fetches exactly this
  -- commit instead of re-resolving a default branch that may have moved, so
  -- one work item and one input_digest can only ever describe one source.
  pinned_source_ref text
    check(pinned_source_ref ~ '^github\.com/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$'),
  pinned_source_commit text check(pinned_source_commit ~ '^[0-9a-f]{40}$'),
  cancel_requested_at timestamptz,
  cancelled_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check(attempts <= max_attempts),
  check((cancel_requested_at is null) = (cancelled_by is null)),
  -- Both or neither: half a pin would let a retry choose its own commit.
  check((pinned_source_ref is null) = (pinned_source_commit is null))
);
create index if not exists work_items_project_idx
  on public.work_items(project_id, created_at desc);
-- Supports the claim scan without touching other projects' rows.
create index if not exists work_items_claimable_idx
  on public.work_items(project_id, created_at)
  where status = 'queued' and cancel_requested_at is null;
-- Idempotency is scoped to one actor inside one project, so two accounts
-- cannot collide and a reused key cannot cross a project boundary.
create unique index if not exists work_items_idempotency_idx
  on public.work_items(project_id, created_by, idempotency_key)
  where idempotency_key is not null;

-- One attempt of one work item by one worker identity. phase, checkpoint and
-- the resolved source identity are the durable progress record; result holds
-- the bounded analysis output of the attempt that actually completed.
create table if not exists public.factory_runs(
  id uuid primary key default gen_random_uuid(),
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  attempt integer not null check(attempt between 1 and 5),
  worker_user_id uuid not null references auth.users(id) on delete cascade,
  worker_registration_id uuid not null references public.project_workers(id) on delete restrict,
  status text not null default 'running'
    check(status in ('running','succeeded','failed','cancelled')),
  phase text not null default 'claimed'
    check(phase in ('claimed','fetching_source','analyzing','recording_result','done')),
  checkpoint jsonb not null default '{}'::jsonb
    check(jsonb_typeof(checkpoint) = 'object' and pg_column_size(checkpoint) <= 4096),
  -- Resolved snapshot identity for this attempt. source_commit is the commit
  -- the archive actually resolved to, source_ref names the repository and
  -- source_digest pins the exact archive bytes analysed. All three are set
  -- once per attempt and then immutable, and the reference and commit must
  -- agree with public.work_items.pinned_source_ref/pinned_source_commit: the
  -- first attempt to resolve them pins them, every later attempt fetches that
  -- same commit, and the digest stays per attempt so an archive that is not
  -- the pinned bytes is still visible.
  source_ref text check(source_ref ~ '^github\.com/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$'),
  source_commit text check(source_commit ~ '^[0-9a-f]{40}$'),
  source_digest text check(source_digest ~ '^sha256:[0-9a-f]{64}$'),
  result jsonb check(result is null or
    (jsonb_typeof(result) = 'object' and pg_column_size(result) <= 262144)),
  error_code text check(error_code ~ '^[a-z][a-z0-9_]{2,47}$'),
  -- Liveness, not fencing: the fencing token is private.factory_run_leases.
  lease_expires_at timestamptz not null,
  heartbeat_at timestamptz not null default now(),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (work_item_id, attempt),
  check((status = 'running') = (finished_at is null)),
  check(status <> 'succeeded' or result is not null)
);
create index if not exists factory_runs_work_item_idx
  on public.factory_runs(work_item_id, attempt desc);
create index if not exists factory_runs_project_idx
  on public.factory_runs(project_id, started_at desc);
create index if not exists factory_runs_active_idx
  on public.factory_runs(project_id, lease_expires_at) where status = 'running';

-- Append-only typed event log. Details are derived server side from validated
-- arguments, never copied from a client-supplied message.
create table if not exists public.factory_run_events(
  id bigint generated always as identity primary key,
  run_id uuid not null references public.factory_runs(id) on delete cascade,
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  kind text not null check(kind in ('claimed','source_resolved','phase_changed','checkpoint',
    'succeeded','failed','cancelled','lease_expired','retry_scheduled','attempts_exhausted')),
  phase text check(phase is null or phase in
    ('claimed','fetching_source','analyzing','recording_result','done')),
  detail text not null default '' check(char_length(detail) <= 200),
  created_at timestamptz not null default now()
);
create index if not exists factory_run_events_run_idx
  on public.factory_run_events(run_id, id);
create index if not exists factory_run_events_project_idx
  on public.factory_run_events(project_id, id desc);

-- The fencing token. `private` is not an exposed PostgREST schema and the
-- authenticated role holds no privilege on this table, so no user-facing read
-- or policy mistake can return a live lease token.
create table if not exists private.factory_run_leases(
  run_id uuid primary key references public.factory_runs(id) on delete cascade,
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  lease_token uuid not null,
  created_at timestamptz not null default now()
);
alter table private.factory_run_leases enable row level security;
revoke all on table private.factory_run_leases from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Authorization and validation helpers. SECURITY DEFINER with a fixed empty
-- search_path and schema-qualified relations, matching the existing project
-- helpers so policies never recurse into the tables they protect.
-- ---------------------------------------------------------------------------

-- A worker must be an explicitly designated service principal, not merely some
-- account that happens not to be a member today. Designation lives in
-- auth.users.raw_app_meta_data, which only the Auth admin API (service role)
-- can write: a user cannot self-assign it, and a project admin cannot promote
-- a colleague's ordinary human account by calling an RPC. Stripping the marker
-- fences the identity exactly like revoking its registration, because every
-- worker path goes through private.is_project_worker below.
create or replace function private.is_service_worker_identity(target_user uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select exists(
    select 1 from auth.users u
     where u.id = target_user
       and coalesce(u.raw_app_meta_data->>'oryveta_role', '') = 'factory_worker')
$$;
revoke all on function private.is_service_worker_identity(uuid) from public, anon;
grant execute on function private.is_service_worker_identity(uuid) to authenticated;

create or replace function private.is_project_worker(target_project uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select (select auth.uid()) is not null
     and private.is_service_worker_identity((select auth.uid()))
     and exists(
    select 1 from public.project_workers w
     where w.project_id = target_project
       and w.worker_user_id = (select auth.uid())
       and w.enabled)
$$;
revoke all on function private.is_project_worker(uuid) from public, anon;
grant execute on function private.is_project_worker(uuid) to authenticated;

-- The effective authority of a *named* account over a project, independent of
-- who is calling. This is private.project_role's precedence rule - an explicit
-- project grant first, otherwise the account's workspace membership capped at
-- 'admin' - applied to a stored user id instead of auth.uid(), because the
-- runtime has to re-check the recorded creator's authority while a worker
-- identity is the caller. projects_and_project_membership.sql owns
-- private.project_role and this migration is additive, so the rule is restated
-- here rather than rewritten there; the two must stay in step.
create or replace function private.user_project_role(
  target_project uuid, target_user uuid)
returns text language sql stable security definer set search_path='' as $$
  select case when target_user is null then null else coalesce(
    (select m.role from public.project_memberships m
      where m.project_id = target_project and m.user_id = target_user),
    (select case w.role when 'owner' then 'admin' else w.role end
      from public.projects p
      join public.workspace_memberships w
        on w.workspace_id = p.workspace_id and w.user_id = target_user
      where p.id = target_project)) end
$$;
revoke all on function private.user_project_role(uuid,uuid)
  from public, anon, authenticated;

-- Whether the account that submitted a work item may still have it run.
-- Submission requires an editing role, so keeping work alive requires the same
-- one: losing it fences the work item instead of leaving a worker analysing a
-- project the requester no longer participates in.
create or replace function private.creator_may_run(
  target_project uuid, target_user uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select private.project_role_rank(private.user_project_role(target_project, target_user))
       >= private.project_role_rank('engineer')
$$;
revoke all on function private.creator_may_run(uuid,uuid)
  from public, anon, authenticated;

-- Structural GitHub validation that mirrors
-- engine/oryveta_engine/repositories.py:parse_github_url. It rejects any URL
-- carrying credentials, a port, a query or a fragment, so a work item can only
-- ever name https://github.com/owner/repo. The worker re-parses the frozen URL
-- with the real importer before any network access; this is the admission gate,
-- not a substitute for it.
create or replace function private.github_repo_parts(p_url text)
returns text[] language plpgsql immutable set search_path='' as $$
declare
  v_value text := btrim(coalesce(p_url, ''));
  v_parts text[];
begin
  if char_length(v_value) > 500 then return null; end if;
  v_parts := regexp_match(v_value,
    '^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$');
  if v_parts is null then return null; end if;
  if v_parts[1] in ('.', '..') or v_parts[2] in ('.', '..') then return null; end if;
  return array[v_parts[1], v_parts[2]];
end
$$;
revoke all on function private.github_repo_parts(text) from public, anon;
grant execute on function private.github_repo_parts(text) to authenticated;

-- Structural validation for the two JSONB payloads a worker may write. Size
-- and type checks alone cannot promise that a credential, URL or host
-- filesystem path stayed out of a nested value, so every key is checked
-- against an identifier pattern and every string leaf is bounded and refused
-- when it looks like an absolute path, a home-relative path, a UNC/Windows
-- path or anything containing a backslash.
create or replace function private.assert_safe_json_tree(
  p_value jsonb, p_depth integer, p_max_string integer, p_max_nodes integer)
returns integer language plpgsql immutable set search_path='' as $$
declare
  v_kind text := jsonb_typeof(p_value);
  v_key text;
  v_child jsonb;
  v_text text;
  v_nodes integer := 1;
begin
  if p_depth > 6 then
    raise exception 'persisted JSON nests more than 6 levels deep';
  end if;
  if v_kind = 'object' then
    for v_key, v_child in select key, value from jsonb_each(p_value) loop
      -- A leading dot is allowed because the analyzer keys its per-language
      -- file counts by file extension ('.py', '.ts'). Slashes, spaces, colons
      -- and control characters stay rejected.
      if v_key !~ '^[.A-Za-z][A-Za-z0-9_.+-]{0,59}$' then
        raise exception 'persisted JSON key is not a bounded identifier';
      end if;
      v_nodes := v_nodes
        + private.assert_safe_json_tree(v_child, p_depth + 1, p_max_string, p_max_nodes);
    end loop;
  elsif v_kind = 'array' then
    for v_child in select value from jsonb_array_elements(p_value) loop
      v_nodes := v_nodes
        + private.assert_safe_json_tree(v_child, p_depth + 1, p_max_string, p_max_nodes);
    end loop;
  elsif v_kind = 'string' then
    v_text := p_value #>> '{}';
    if char_length(v_text) > p_max_string then
      raise exception 'persisted JSON string exceeds % characters', p_max_string;
    end if;
    if v_text ~ '^(/|~/|//)' or v_text ~ '^[A-Za-z]:[/\\]' or v_text ~ '\\' then
      raise exception 'persisted JSON string looks like a filesystem path';
    end if;
  end if;
  if v_nodes > p_max_nodes then
    raise exception 'persisted JSON has more than % nodes', p_max_nodes;
  end if;
  return v_nodes;
end
$$;
revoke all on function private.assert_safe_json_tree(jsonb,integer,integer,integer)
  from public, anon, authenticated;

-- A checkpoint is durable progress, not a payload channel: a flat object of at
-- most 16 snake_case keys whose values are scalars, with strings restricted to
-- a character set that cannot express a URL, a path or a token.
create or replace function private.assert_run_checkpoint(p_checkpoint jsonb)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_key text;
  v_child jsonb;
  v_count integer := 0;
begin
  if jsonb_typeof(p_checkpoint) <> 'object' then
    raise exception 'checkpoint must be a JSON object';
  end if;
  if pg_column_size(p_checkpoint) > 4096 then
    raise exception 'checkpoint exceeds 4096 bytes';
  end if;
  for v_key, v_child in select key, value from jsonb_each(p_checkpoint) loop
    v_count := v_count + 1;
    if v_key !~ '^[a-z][a-z0-9_]{1,39}$' then
      raise exception 'checkpoint keys must be snake_case identifiers';
    end if;
    if jsonb_typeof(v_child) in ('object', 'array') then
      raise exception 'checkpoint values must be scalars';
    end if;
    if jsonb_typeof(v_child) = 'string'
       and (v_child #>> '{}') !~ '^[A-Za-z0-9 _.:+-]{0,120}$' then
      raise exception 'checkpoint strings must be short plain identifiers';
    end if;
  end loop;
  if v_count > 16 then
    raise exception 'checkpoint may contain at most 16 keys';
  end if;
end
$$;
revoke all on function private.assert_run_checkpoint(jsonb) from public, anon, authenticated;

-- An analysis result is exactly the analyzer's shape: a summary object plus a
-- bounded findings array of flat rows with known keys and repository-relative
-- paths. Anything else is refused instead of being stored and shown to users.
create or replace function private.assert_analysis_result(p_result jsonb)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_finding jsonb;
  v_key text;
  v_child jsonb;
  v_path text;
begin
  if jsonb_typeof(p_result) <> 'object' then
    raise exception 'result must be a JSON object';
  end if;
  if pg_column_size(p_result) > 262144 then
    raise exception 'result exceeds the 256 KB persisted limit';
  end if;
  if exists(select 1 from jsonb_object_keys(p_result) k
             where k not in ('summary', 'findings')) then
    raise exception 'result may only contain summary and findings';
  end if;
  if jsonb_typeof(p_result->'summary') is distinct from 'object' then
    raise exception 'result requires a summary object';
  end if;
  perform private.assert_safe_json_tree(p_result->'summary', 1, 500, 4000);
  if p_result ? 'findings' then
    if jsonb_typeof(p_result->'findings') <> 'array' then
      raise exception 'result findings must be an array';
    end if;
    if jsonb_array_length(p_result->'findings') > 400 then
      raise exception 'result may contain at most 400 findings';
    end if;
    for v_finding in select value from jsonb_array_elements(p_result->'findings') loop
      if jsonb_typeof(v_finding) <> 'object' then
        raise exception 'each finding must be an object';
      end if;
      for v_key, v_child in select key, value from jsonb_each(v_finding) loop
        if v_key not in ('path','line','category','severity','title',
                         'recommendation','confidence') then
          raise exception 'unknown finding field';
        end if;
        if jsonb_typeof(v_child) in ('object', 'array') then
          raise exception 'finding fields must be scalars';
        end if;
        if jsonb_typeof(v_child) = 'string' and char_length(v_child #>> '{}') > 500 then
          raise exception 'finding fields must be at most 500 characters';
        end if;
      end loop;
      -- Findings carry repository-relative evidence paths. An absolute or
      -- traversing path would be a worker bug or a leak of the run host.
      v_path := coalesce(v_finding->>'path', '');
      if v_path ~ '^(/|~|[A-Za-z]:[/\\])' or v_path ~ '\\'
         or v_path = '..' or v_path like '../%' or v_path like '%/../%'
         or v_path like '%/..' then
        raise exception 'finding paths must be repository-relative';
      end if;
    end loop;
  end if;
end
$$;
revoke all on function private.assert_analysis_result(jsonb) from public, anon, authenticated;

create or replace function private.touch_work_item()
returns trigger language plpgsql set search_path='' as $$
begin
  new.updated_at = now();
  return new;
end
$$;
revoke all on function private.touch_work_item() from public, anon, authenticated;
drop trigger if exists on_work_item_updated on public.work_items;
create trigger on_work_item_updated
before update on public.work_items
for each row execute function private.touch_work_item();

-- Bounded event recorder with a split budget. The per-run cap keeps a looping
-- or misbehaving worker from growing an unbounded log inside the metadata
-- authority, but a single cap lets progress chatter consume the slots the
-- outcome needs: a worker that changes phase and checkpoint often would fill
-- the log while its lease is still valid, and the succeeded, cancelled,
-- lease_expired, retry_scheduled and attempts_exhausted events would then be
-- silently dropped while completion still committed. Progress events are
-- therefore capped well below the per-run cap, which reserves the remainder
-- for the handful of events that state how an attempt ended.
create or replace function private.record_run_event(
  p_run_id uuid, p_kind text, p_phase text default null, p_detail text default '')
returns void language plpgsql security definer set search_path='' as $$
declare
  v_run public.factory_runs;
  v_count integer;
begin
  select r.* into v_run from public.factory_runs r where r.id = p_run_id;
  if v_run.id is null then return; end if;
  if p_kind in ('phase_changed','checkpoint','source_resolved') then
    select count(*) into v_count from public.factory_run_events e
     where e.run_id = p_run_id
       and e.kind in ('phase_changed','checkpoint','source_resolved');
    if v_count >= 180 then return; end if;
  else
    select count(*) into v_count from public.factory_run_events e where e.run_id = p_run_id;
    if v_count >= 200 then return; end if;
  end if;
  insert into public.factory_run_events(run_id, work_item_id, project_id, kind, phase, detail)
  values (p_run_id, v_run.work_item_id, v_run.project_id, p_kind, p_phase,
          left(coalesce(p_detail, ''), 200));
end
$$;
revoke all on function private.record_run_event(uuid,text,text,text)
  from public, anon, authenticated;

-- Terminal handling for a work item whose current attempt ended without a
-- result. Retries are bounded by max_attempts and exhaustion is an explicit
-- terminal failure, never a silently idle row.
create or replace function private.settle_work_item_after_attempt(
  p_work_item_id uuid, p_run_id uuid, p_error_code text)
returns text language plpgsql security definer set search_path='' as $$
declare
  v_item public.work_items;
begin
  select w.* into v_item from public.work_items w where w.id = p_work_item_id for update;
  if v_item.id is null then return null; end if;
  if v_item.status in ('succeeded','failed','cancelled') then return v_item.status; end if;
  if v_item.cancel_requested_at is not null then
    update public.work_items w set status = 'cancelled' where w.id = p_work_item_id;
    return 'cancelled';
  end if;
  if v_item.attempts < v_item.max_attempts then
    update public.work_items w set status = 'queued', error_code = p_error_code
     where w.id = p_work_item_id;
    perform private.record_run_event(p_run_id, 'retry_scheduled', null,
      format('attempt %s of %s used', v_item.attempts, v_item.max_attempts));
    return 'queued';
  end if;
  update public.work_items w set status = 'failed', error_code = p_error_code
   where w.id = p_work_item_id;
  perform private.record_run_event(p_run_id, 'attempts_exhausted', null,
    format('%s of %s attempts used', v_item.attempts, v_item.max_attempts));
  return 'failed';
end
$$;
revoke all on function private.settle_work_item_after_attempt(uuid,uuid,text)
  from public, anon, authenticated;

-- Reclaim: a run whose lease expired is terminated and its work item either
-- becomes claimable again or fails terminally. Called inside claim so recovery
-- needs no separate scheduler, cron job or privileged process.
--
-- Locks are always taken work item first, then run, matching cancel_work_item
-- and revoke_project_worker. A reclaim racing a cancellation therefore queues
-- behind it instead of deadlocking, and the re-checked UPDATE below makes a
-- lost race a no-op rather than a double transition.
create or replace function private.expire_stale_runs(p_project_id uuid)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_run record;
  v_count integer := 0;
begin
  for v_run in
    select r.id, r.work_item_id from public.factory_runs r
     where r.project_id = p_project_id and r.status = 'running'
       and r.lease_expires_at < now()
     order by r.started_at
  loop
    perform 1 from public.work_items w where w.id = v_run.work_item_id for update;
    update public.factory_runs r
       set status = 'failed', error_code = 'lease_expired', finished_at = now()
     where r.id = v_run.id and r.status = 'running' and r.lease_expires_at < now();
    if not found then continue; end if;
    delete from private.factory_run_leases l where l.run_id = v_run.id;
    perform private.record_run_event(v_run.id, 'lease_expired', null,
      'lease expired without a result');
    perform private.settle_work_item_after_attempt(v_run.work_item_id, v_run.id, 'lease_expired');
    v_count := v_count + 1;
  end loop;
  return v_count;
end
$$;
revoke all on function private.expire_stale_runs(uuid) from public, anon, authenticated;

-- Fence every live run of a work item: the token disappears, so an in-flight
-- worker's next heartbeat reports an invalid lease and no later call of that
-- attempt can publish a result or a misleading success event. Callers hold the
-- work item lock already, which is why no deadlock is possible against the
-- reclaim and revocation paths.
create or replace function private.fence_running_runs(
  p_work_item_id uuid, p_error_code text, p_detail text)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_run record;
  v_count integer := 0;
begin
  for v_run in
    select r.id from public.factory_runs r
     where r.work_item_id = p_work_item_id and r.status = 'running'
     for update
  loop
    update public.factory_runs r
       set status = 'cancelled', error_code = p_error_code, finished_at = now()
     where r.id = v_run.id and r.status = 'running';
    if not found then continue; end if;
    delete from private.factory_run_leases l where l.run_id = v_run.id;
    perform private.record_run_event(v_run.id, 'cancelled', null, p_detail);
    v_count := v_count + 1;
  end loop;
  return v_count;
end
$$;
revoke all on function private.fence_running_runs(uuid,text,text)
  from public, anon, authenticated;

-- Terminal fence for work whose recorded creator no longer holds an editing
-- role on the project. Unlike a failed attempt this is never retried: no
-- worker is authorized to run the request at all, so the attempt is cancelled
-- and the work item fails immediately, whatever its remaining attempt budget.
-- Callers hold the work item lock and then the run lock, the one lock order.
create or replace function private.fence_unauthorized_creator(
  p_work_item_id uuid, p_run_id uuid)
returns void language plpgsql security definer set search_path='' as $$
begin
  if p_run_id is not null then
    update public.factory_runs r
       set status = 'cancelled', error_code = 'creator_unauthorized', finished_at = now()
     where r.id = p_run_id and r.status = 'running';
    if found then
      delete from private.factory_run_leases l where l.run_id = p_run_id;
      perform private.record_run_event(p_run_id, 'cancelled', null,
        'the requester no longer has an editing role on this project');
    end if;
  end if;
  update public.work_items w
     set status = 'failed', error_code = 'creator_unauthorized'
   where w.id = p_work_item_id
     and w.status not in ('succeeded','failed','cancelled');
end
$$;
revoke all on function private.fence_unauthorized_creator(uuid,uuid)
  from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Row level security. SELECT only, for current project readers and for the
-- project's own enabled worker identities. There is no write policy because no
-- write privilege is granted: mutation goes exclusively through the RPCs below.
-- ---------------------------------------------------------------------------

alter table public.project_workers enable row level security;
alter table public.work_items enable row level security;
alter table public.factory_runs enable row level security;
alter table public.factory_run_events enable row level security;

-- Registrations are private operational configuration: project admins who own
-- the grant, plus the worker identity itself so a worker can confirm its scope.
drop policy if exists project_workers_select_admin on public.project_workers;
create policy project_workers_select_admin on public.project_workers
for select to authenticated
using(worker_user_id = (select auth.uid()) or (select private.is_project_admin(project_id)));

drop policy if exists work_items_select_authorized on public.work_items;
create policy work_items_select_authorized on public.work_items
for select to authenticated
using((select private.can_read_project(project_id))
   or (select private.is_project_worker(project_id)));

drop policy if exists factory_runs_select_authorized on public.factory_runs;
create policy factory_runs_select_authorized on public.factory_runs
for select to authenticated
using((select private.can_read_project(project_id))
   or (select private.is_project_worker(project_id)));

drop policy if exists factory_run_events_select_authorized on public.factory_run_events;
create policy factory_run_events_select_authorized on public.factory_run_events
for select to authenticated
using((select private.can_read_project(project_id))
   or (select private.is_project_worker(project_id)));

revoke all on public.project_workers, public.work_items, public.factory_runs,
  public.factory_run_events from anon, authenticated;
grant select on public.project_workers, public.work_items, public.factory_runs,
  public.factory_run_events to authenticated;

-- ---------------------------------------------------------------------------
-- Submitter and administrator RPCs. Every one re-derives the actor from
-- auth.uid() and re-checks current project authority server side.
-- ---------------------------------------------------------------------------

-- Accepts a repository analysis for the project's own configured source URL.
-- The URL, its parsed owner/repo and the input digest are frozen into the work
-- item, which is committed before this call returns: the request survives the
-- browser closing immediately afterwards.
create or replace function public.submit_repository_analysis(
  p_project_id uuid, p_idempotency_key text default null)
returns table(work_item_id uuid, status text, replayed boolean, kind text,
              source_url text, input_digest text, attempts integer, max_attempts integer)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_project public.projects;
  v_key text := nullif(btrim(coalesce(p_idempotency_key, '')), '');
  v_parts text[];
  v_digest text;
  v_existing public.work_items;
  v_row public.work_items;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if private.project_role_rank(private.project_role(p_project_id))
     < private.project_role_rank('engineer') then
    raise exception 'not allowed to submit work for this project';
  end if;
  select p.* into v_project from public.projects p where p.id = p_project_id;
  if v_project.id is null then raise exception 'project not found'; end if;
  if v_project.source_url is null then
    raise exception 'project has no source repository to analyse';
  end if;
  v_parts := private.github_repo_parts(v_project.source_url);
  if v_parts is null then
    raise exception 'only public https://github.com/owner/repo sources can be analysed';
  end if;
  -- Canonical input identity: task kind plus the exact frozen source URL. A
  -- reused idempotency key must describe this same input or be rejected.
  v_digest := encode(sha256(convert_to('repository_analysis' || E'\n' || v_project.source_url,
                                       'UTF8')), 'hex');
  if v_key is not null and v_key !~ '^[A-Za-z0-9._:-]{8,120}$' then
    raise exception 'idempotency key must be 8-120 characters of A-Z a-z 0-9 . _ : -';
  end if;
  -- Admission is one statement, so two callers holding the same scoped key
  -- cannot both pass an existence check and then collide on
  -- work_items_idempotency_idx: the second insertion waits for the first,
  -- records nothing, and re-reads the committed row below as a replay. A
  -- SELECT first could not do this, because no lock exists on a key that is
  -- not there yet.
  insert into public.work_items as w
    (project_id, created_by, kind, source_url, source_owner, source_repo,
     input_digest, idempotency_key)
  values (p_project_id, v_actor, 'repository_analysis', v_project.source_url,
          v_parts[1], v_parts[2], v_digest, v_key)
  on conflict (project_id, created_by, idempotency_key)
    where idempotency_key is not null do nothing
  returning w.* into v_row;
  if v_row.id is null then
    select w.* into v_existing from public.work_items w
     where w.project_id = p_project_id and w.created_by = v_actor
       and w.idempotency_key = v_key
     for update;
    if v_existing.id is null then
      raise exception 'the submission could not be recorded; retry the request';
    end if;
    -- A reused key must describe the same work. The frozen input decides that,
    -- not the project's current source URL.
    if v_existing.input_digest <> v_digest then
      raise exception 'idempotency key already used for a different input';
    end if;
    return query select v_existing.id, v_existing.status, true, v_existing.kind,
                        v_existing.source_url, v_existing.input_digest,
                        v_existing.attempts, v_existing.max_attempts;
    return;
  end if;
  return query select v_row.id, v_row.status, false, v_row.kind, v_row.source_url,
                      v_row.input_digest, v_row.attempts, v_row.max_attempts;
end
$$;
revoke all on function public.submit_repository_analysis(uuid,text) from public, anon;
grant execute on function public.submit_repository_analysis(uuid,text) to authenticated;

-- Cancels accepted work and fences any attempt already running. Requires a
-- current editing role, which is re-checked here: a revoked submitter cannot
-- cancel, and an editor can stop work their colleague submitted.
create or replace function public.cancel_work_item(p_work_item_id uuid)
returns table(work_item_id uuid, status text, already_terminal boolean, fenced_runs integer)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_item public.work_items;
  v_fenced integer := 0;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  select w.* into v_item from public.work_items w where w.id = p_work_item_id for update;
  -- Unauthorized callers get the same message as a missing row, so work item
  -- ids in other projects are not probeable.
  if v_item.id is null
     or private.project_role_rank(private.project_role(v_item.project_id))
        < private.project_role_rank('engineer') then
    raise exception 'work item not found';
  end if;
  if v_item.status in ('succeeded','failed','cancelled') then
    return query select v_item.id, v_item.status, true, 0;
    return;
  end if;
  v_fenced := private.fence_running_runs(p_work_item_id, 'cancelled',
                                         'cancelled by an authorized project editor');
  update public.work_items w
     set status = 'cancelled', cancel_requested_at = now(), cancelled_by = v_actor
   where w.id = p_work_item_id;
  return query select v_item.id, 'cancelled'::text, false, v_fenced;
end
$$;
revoke all on function public.cancel_work_item(uuid) from public, anon;
grant execute on function public.cancel_work_item(uuid) to authenticated;

-- Registers an already-provisioned Supabase Auth *service* identity as this
-- project's worker. Creating that identity and marking it
-- app_metadata.oryveta_role = 'factory_worker' is a separate administrative
-- step performed with the Auth admin API; this RPC deliberately cannot create
-- users or designate them. An undesignated account and any human project or
-- workspace participant are refused, so worker authority never rides on a
-- browser session and a project admin cannot repurpose a colleague's account.
create or replace function public.register_project_worker(
  p_project_id uuid, p_worker_user_id uuid, p_label text)
returns table(id uuid, project_id uuid, worker_user_id uuid, label text, enabled boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_label text := btrim(coalesce(p_label, ''));
  v_project public.projects;
  v_row public.project_workers;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if not private.is_project_admin(p_project_id) then
    raise exception 'not allowed to manage this project';
  end if;
  if p_worker_user_id is null then raise exception 'worker identity is required'; end if;
  if v_label !~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{1,59}$' then
    raise exception 'worker label must be 2-60 characters of A-Z a-z 0-9 space . _ -';
  end if;
  if p_worker_user_id = v_actor then
    raise exception 'a worker must be a separate service identity, not your own account';
  end if;
  if not exists(select 1 from auth.users u where u.id = p_worker_user_id) then
    raise exception 'worker identity not found';
  end if;
  if not private.is_service_worker_identity(p_worker_user_id) then
    raise exception 'that account is not a provisioned factory worker service identity';
  end if;
  select p.* into v_project from public.projects p where p.id = p_project_id;
  if v_project.id is null then raise exception 'project not found'; end if;
  if exists(select 1 from public.project_memberships m
             where m.project_id = p_project_id and m.user_id = p_worker_user_id)
     or exists(select 1 from public.workspace_memberships m
                where m.workspace_id = v_project.workspace_id
                  and m.user_id = p_worker_user_id) then
    raise exception 'a project or workspace member cannot also be a worker identity';
  end if;
  insert into public.project_workers as w
    (project_id, worker_user_id, label, registered_by)
  values (p_project_id, p_worker_user_id, v_label, v_actor)
  on conflict on constraint project_workers_scope_key do update
     set label = v_label, enabled = true, registered_by = v_actor,
         revoked_at = null, revoked_by = null
  returning w.* into v_row;
  return query select v_row.id, v_row.project_id, v_row.worker_user_id,
                      v_row.label, v_row.enabled;
end
$$;
revoke all on function public.register_project_worker(uuid,uuid,text) from public, anon;
grant execute on function public.register_project_worker(uuid,uuid,text) to authenticated;

-- Revocation takes effect immediately: the registration is disabled and every
-- run that identity still holds is fenced, so its child process loses the lease
-- and its late completion is refused.
create or replace function public.revoke_project_worker(
  p_project_id uuid, p_worker_user_id uuid)
returns table(id uuid, enabled boolean, fenced_runs integer)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_row public.project_workers;
  v_run record;
  v_fenced integer := 0;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if not private.is_project_admin(p_project_id) then
    raise exception 'not allowed to manage this project';
  end if;
  select w.* into v_row from public.project_workers w
   where w.project_id = p_project_id and w.worker_user_id = p_worker_user_id
   for update;
  if v_row.id is null then raise exception 'worker registration not found'; end if;
  if v_row.enabled then
    update public.project_workers w
       set enabled = false, revoked_at = now(), revoked_by = v_actor
     where w.id = v_row.id;
  end if;
  -- Work item before run, the same lock order the reclaim and cancellation
  -- paths use, and the re-checked UPDATE keeps a lost race a no-op.
  for v_run in
    select r.id, r.work_item_id from public.factory_runs r
     where r.project_id = p_project_id and r.worker_user_id = p_worker_user_id
       and r.status = 'running'
     order by r.started_at
  loop
    perform 1 from public.work_items w where w.id = v_run.work_item_id for update;
    update public.factory_runs r
       set status = 'cancelled', error_code = 'worker_revoked', finished_at = now()
     where r.id = v_run.id and r.status = 'running';
    if not found then continue; end if;
    delete from private.factory_run_leases l where l.run_id = v_run.id;
    perform private.record_run_event(v_run.id, 'cancelled', null, 'worker registration revoked');
    perform private.settle_work_item_after_attempt(v_run.work_item_id, v_run.id, 'worker_revoked');
    v_fenced := v_fenced + 1;
  end loop;
  return query select v_row.id, false, v_fenced;
end
$$;
revoke all on function public.revoke_project_worker(uuid,uuid) from public, anon;
grant execute on function public.revoke_project_worker(uuid,uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Worker RPCs. Each one requires auth.uid() plus an enabled registration for
-- the project of the row it touches, so a worker can neither read nor claim
-- outside its own scope, and a revoked worker cannot act at all.
-- ---------------------------------------------------------------------------

-- Atomically reclaims expired attempts, then takes at most one queued work
-- item with FOR UPDATE SKIP LOCKED. Two concurrent workers therefore receive
-- different items or nothing; they never share an attempt or a lease token.
--
-- Locks are taken registration, then work item, then run. The registration
-- lock is a share lock held to commit, so a revocation that runs concurrently
-- either waits and then fences the attempt this claim committed, or commits
-- first and leaves this claim with no enabled registration to find.
create or replace function public.claim_analysis_work(
  p_project_id uuid, p_lease_seconds integer default 300)
returns table(work_item_id uuid, run_id uuid, attempt integer, max_attempts integer,
              lease_token uuid, lease_expires_at timestamptz, kind text,
              source_url text, source_owner text, source_repo text, input_digest text,
              pinned_source_ref text, pinned_source_commit text,
              previous_source_digest text,
              previous_checkpoint jsonb)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_registration public.project_workers;
  v_item public.work_items;
  v_previous public.factory_runs;
  v_run_id uuid;
  v_token uuid := gen_random_uuid();
  v_expires timestamptz;
  v_attempt integer;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  -- Both conditions are re-checked on every protected transition below: the
  -- identity must still be a designated service principal and must still hold
  -- an enabled registration for this exact project.
  if not private.is_service_worker_identity(v_actor) then
    raise exception 'worker identity is not a provisioned factory worker service identity';
  end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 900 then
    raise exception 'lease seconds must be between 15 and 900';
  end if;
  -- FOR SHARE, before any item or run lock and held to commit: a concurrent
  -- public.revoke_project_worker takes FOR UPDATE on this same row, so it
  -- cannot slip between this check and the insertion below and commit a
  -- revocation that never saw the attempt. The row lock re-evaluates the
  -- `enabled` predicate after waiting, so a revocation that committed first
  -- leaves nothing to find here.
  select w.* into v_registration from public.project_workers w
   where w.project_id = p_project_id and w.worker_user_id = v_actor and w.enabled
   for share;
  if v_registration.id is null then
    raise exception 'worker identity is not registered for this project';
  end if;
  perform private.expire_stale_runs(p_project_id);
  select w.* into v_item from public.work_items w
   where w.project_id = p_project_id and w.kind = 'repository_analysis'
     and w.status = 'queued' and w.cancel_requested_at is null
   -- The id tiebreaker keeps the order total, so two items submitted inside
   -- one transaction (which share now()) are still handed out deterministically.
   order by w.created_at, w.id
   for update skip locked
   limit 1;
  if v_item.id is null then return; end if;
  -- Submission required an editing role, and so does running the work. A
  -- requester who has since lost project access cannot keep a worker analysing
  -- that project, so their queued item is failed terminally instead of being
  -- handed out, and no attempt is created for it.
  if not private.creator_may_run(p_project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, null::uuid);
    return;
  end if;
  if v_item.attempts >= v_item.max_attempts then
    -- Defensive: a queued row with no remaining attempt is a terminal failure,
    -- not work to hand out again.
    update public.work_items w
       set status = 'failed', error_code = coalesce(w.error_code, 'attempts_exhausted')
     where w.id = v_item.id;
    return;
  end if;
  v_attempt := v_item.attempts + 1;
  v_expires := now() + make_interval(secs => p_lease_seconds);
  select r.* into v_previous from public.factory_runs r
   where r.work_item_id = v_item.id order by r.attempt desc limit 1;
  update public.work_items w set status = 'running', attempts = v_attempt
   where w.id = v_item.id;
  insert into public.factory_runs as r
    (work_item_id, project_id, attempt, worker_user_id, worker_registration_id,
     lease_expires_at)
  values (v_item.id, p_project_id, v_attempt, v_actor, v_registration.id, v_expires)
  returning r.id into v_run_id;
  insert into private.factory_run_leases(run_id, work_item_id, lease_token)
  values (v_run_id, v_item.id, v_token);
  perform private.record_run_event(v_run_id, 'claimed', 'claimed',
    format('attempt %s of %s', v_attempt, v_item.max_attempts));
  -- The work item's pin, not the previous attempt's resolved reference: a
  -- retry must fetch exactly this commit rather than re-resolving a default
  -- branch. The previous attempt's archive digest and checkpoint are handed
  -- over as the progress record it left behind.
  return query select v_item.id, v_run_id, v_attempt, v_item.max_attempts, v_token,
                      v_expires, v_item.kind, v_item.source_url, v_item.source_owner,
                      v_item.source_repo, v_item.input_digest,
                      v_item.pinned_source_ref, v_item.pinned_source_commit,
                      v_previous.source_digest,
                      coalesce(v_previous.checkpoint, '{}'::jsonb);
end
$$;
revoke all on function public.claim_analysis_work(uuid,integer) from public, anon;
grant execute on function public.claim_analysis_work(uuid,integer) to authenticated;

-- Extends the lease and records durable progress. Fencing failures are
-- reported as lease_valid = false rather than raised, so a fenced worker has an
-- unambiguous signal to terminate its child process and stop. Only an
-- unauthorized caller raises.
create or replace function public.heartbeat_analysis_run(
  p_run_id uuid, p_lease_token uuid, p_phase text default null,
  p_checkpoint jsonb default null, p_source_ref text default null,
  p_source_commit text default null, p_source_digest text default null,
  p_lease_seconds integer default 300)
returns table(lease_valid boolean, reason text, run_status text, work_item_status text,
              cancel_requested boolean, lease_expires_at timestamptz, phase text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_expires timestamptz;
  v_phase text;
  v_step text;
  v_ref text;
  v_commit text;
  v_digest text;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 900 then
    raise exception 'lease seconds must be between 15 and 900';
  end if;
  if p_phase is not null and p_phase not in
     ('claimed','fetching_source','analyzing','recording_result','done') then
    raise exception 'unknown run phase';
  end if;
  if p_checkpoint is not null then
    -- Key, scalar-value, string-shape, depth and size validation, so no URL,
    -- credential or host path can hide inside a nested checkpoint value.
    perform private.assert_run_checkpoint(p_checkpoint);
  end if;
  if p_source_ref is not null and
     p_source_ref !~ '^github\.com/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$' then
    raise exception 'source reference must be github.com/owner/repo';
  end if;
  if p_source_digest is not null and p_source_digest !~ '^sha256:[0-9a-f]{64}$' then
    raise exception 'source digest must be sha256:<hex>';
  end if;
  if p_source_commit is not null and p_source_commit !~ '^[0-9a-f]{40}$' then
    raise exception 'source commit must be a 40 character hexadecimal SHA';
  end if;
  -- One lock order everywhere - work item, then run - so this call can never
  -- deadlock against a cancellation, a revocation or the reclaim path. The
  -- work item id is resolved without a lock first, because taking the run lock
  -- to find it is exactly the inverted order those paths would deadlock with.
  -- A run belonging to another identity is indistinguishable from a missing
  -- one, so run ids cannot be probed across workers or projects.
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor then
    raise exception 'run not found';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if not private.is_project_worker(v_run.project_id) then
    return query select false, 'worker_not_registered'::text, v_run.status, v_item.status,
                        v_item.cancel_requested_at is not null, null::timestamptz, v_run.phase;
    return;
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running'
     or v_item.cancel_requested_at is not null then
    return query select false,
      case when v_item.cancel_requested_at is not null then 'cancelled' else 'not_running' end,
      v_run.status, v_item.status, v_item.cancel_requested_at is not null,
      null::timestamptz, v_run.phase;
    return;
  end if;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= now() then
    return query select false, 'lease_lost'::text, v_run.status, v_item.status,
                        v_item.cancel_requested_at is not null, null::timestamptz, v_run.phase;
    return;
  end if;
  -- The recorded creator is reauthorized on every protected transition, not
  -- only at submission: losing the editing role ends this attempt and the work
  -- item with it, so the worker stops instead of finishing the analysis.
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    return query select false, 'creator_unauthorized'::text, 'cancelled'::text, 'failed'::text,
                        false, null::timestamptz, v_run.phase;
    return;
  end if;
  -- Source identity is write-once per attempt. Re-reporting what is already
  -- recorded is an ordinary heartbeat, but reporting something else means the
  -- worker analysed other bytes than it said it did, so it is refused rather
  -- than coalesced away.
  if (p_source_ref is not null and v_run.source_ref is not null
      and p_source_ref <> v_run.source_ref)
     or (p_source_commit is not null and v_run.source_commit is not null
         and p_source_commit <> v_run.source_commit)
     or (p_source_digest is not null and v_run.source_digest is not null
         and p_source_digest <> v_run.source_digest) then
    raise exception 'source identity already recorded for this attempt';
  end if;
  v_ref := coalesce(v_run.source_ref, p_source_ref);
  v_commit := coalesce(v_run.source_commit, p_source_commit);
  v_digest := coalesce(v_run.source_digest, p_source_digest);
  -- And it must be the identity this work item is pinned to. A retry that
  -- fetched a moved upstream is refused here instead of completing against a
  -- source the request was never authorized for.
  if v_item.pinned_source_ref is not null
     and ((v_ref is not null and v_ref <> v_item.pinned_source_ref)
       or (v_commit is not null and v_commit <> v_item.pinned_source_commit)) then
    raise exception 'source identity conflicts with the work item pin';
  end if;
  v_expires := now() + make_interval(secs => p_lease_seconds);
  v_phase := coalesce(p_phase, v_run.phase);
  update public.factory_runs r
     set lease_expires_at = v_expires,
         heartbeat_at = now(),
         phase = v_phase,
         checkpoint = coalesce(p_checkpoint, r.checkpoint),
         source_ref = v_ref,
         source_commit = v_commit,
         source_digest = v_digest
   where r.id = p_run_id;
  -- The first attempt that resolves a reference and a commit together pins
  -- them on the work item, under the work item lock taken above, so every
  -- later attempt is held to the same source. The archive digest stays per
  -- attempt: it describes the bytes this attempt actually fetched.
  if v_item.pinned_source_ref is null and v_ref is not null and v_commit is not null then
    update public.work_items w
       set pinned_source_ref = v_ref, pinned_source_commit = v_commit
     where w.id = v_item.id;
  end if;
  if v_run.source_digest is null and p_source_digest is not null then
    perform private.record_run_event(p_run_id, 'source_resolved', v_phase,
      left(coalesce(p_source_ref, '') || ' commit='
           || coalesce(p_source_commit, 'unresolved') || ' ' || p_source_digest, 200));
  end if;
  if v_phase <> v_run.phase then
    perform private.record_run_event(p_run_id, 'phase_changed', v_phase, v_phase);
  elsif p_checkpoint is not null and p_checkpoint is distinct from v_run.checkpoint then
    v_step := coalesce(p_checkpoint->>'step', '');
    if v_step !~ '^[A-Za-z0-9 _.:+-]{0,60}$' then v_step := ''; end if;
    perform private.record_run_event(p_run_id, 'checkpoint', v_phase, v_step);
  end if;
  return query select true, 'ok'::text, 'running'::text, v_item.status, false, v_expires, v_phase;
end
$$;
revoke all on function
  public.heartbeat_analysis_run(uuid,uuid,text,jsonb,text,text,text,integer)
  from public, anon;
grant execute on function
  public.heartbeat_analysis_run(uuid,uuid,text,jsonb,text,text,text,integer)
  to authenticated;

-- Atomic completion behind the same fence. A stale, cancelled, revoked or
-- expired attempt is refused with accepted = false and writes neither a result
-- nor a success event, so a fenced worker can never report false progress.
create or replace function public.finish_analysis_run(
  p_run_id uuid, p_lease_token uuid, p_result jsonb)
returns table(accepted boolean, reason text, work_item_status text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_files text;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_result is null then raise exception 'result is required'; end if;
  -- Full structural validation: allowed top-level keys, summary shape, bounded
  -- findings with known fields and repository-relative paths, nesting depth,
  -- string length and total size.
  perform private.assert_analysis_result(p_result);
  -- The one lock order: resolve the work item id without a lock, then lock the
  -- work item and only then the run, and revalidate every predicate against
  -- the locked rows. Locking the run first is what deadlocked this call
  -- against cancellation, revocation and reclaim, which all take the work item
  -- first.
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor then
    raise exception 'run not found';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if not private.is_project_worker(v_run.project_id) then
    return query select false, 'worker_not_registered'::text, v_item.status;
    return;
  end if;
  if v_item.cancel_requested_at is not null then
    return query select false, 'cancelled'::text, v_item.status;
    return;
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running' then
    return query select false, 'not_running'::text, v_item.status;
    return;
  end if;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= now() then
    return query select false, 'lease_lost'::text, v_item.status;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    -- No result is published for a request nobody is authorized to run.
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    return query select false, 'creator_unauthorized'::text, 'failed'::text;
    return;
  end if;
  if v_run.source_ref is null or v_run.source_commit is null
     or v_run.source_digest is null then
    -- A completed attempt must carry the whole snapshot identity it analysed -
    -- repository, commit and archive digest - so a stored result is always
    -- attributable to specific source bytes of a named revision.
    return query select false, 'source_identity_missing'::text, v_item.status;
    return;
  end if;
  if v_item.pinned_source_ref is null
     or v_run.source_ref <> v_item.pinned_source_ref
     or v_run.source_commit <> v_item.pinned_source_commit then
    -- The attempt analysed a different revision than this work item is pinned
    -- to, so its result does not describe the authorized request.
    return query select false, 'source_identity_conflict'::text, v_item.status;
    return;
  end if;
  update public.factory_runs r
     set status = 'succeeded', phase = 'done', result = p_result,
         error_code = null, finished_at = now(), heartbeat_at = now()
   where r.id = p_run_id;
  update public.work_items w set status = 'succeeded', error_code = null
   where w.id = v_item.id;
  delete from private.factory_run_leases l where l.run_id = p_run_id;
  -- Event detail is derived from the stored result, never from a worker string.
  v_files := coalesce(p_result->'summary'->>'source_files_analyzed', '');
  if v_files !~ '^[0-9]{1,9}$' then v_files := 'unreported'; end if;
  perform private.record_run_event(p_run_id, 'succeeded', 'done',
    format('findings=%s files=%s',
           coalesce(jsonb_array_length(p_result->'findings'), 0), v_files));
  return query select true, 'ok'::text, 'succeeded'::text;
end
$$;
revoke all on function public.finish_analysis_run(uuid,uuid,jsonb) from public, anon;
grant execute on function public.finish_analysis_run(uuid,uuid,jsonb) to authenticated;

-- Records a failed attempt behind the same fence. error_code is a short
-- enumerated-style code, so an exception message, credential or host path
-- cannot be smuggled into the metadata authority.
create or replace function public.fail_analysis_run(
  p_run_id uuid, p_lease_token uuid, p_error_code text)
returns table(accepted boolean, reason text, work_item_status text, retry_scheduled boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_code text := lower(btrim(coalesce(p_error_code, '')));
  v_status text;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if v_code !~ '^[a-z][a-z0-9_]{2,47}$' then
    raise exception 'error code must be 3-48 characters of a-z 0-9 _';
  end if;
  -- The same single lock order as the completion path: work item, then run.
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor then
    raise exception 'run not found';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if not private.is_project_worker(v_run.project_id) then
    return query select false, 'worker_not_registered'::text, v_item.status, false;
    return;
  end if;
  if v_run.status <> 'running' then
    return query select false, 'not_running'::text, v_item.status, false;
    return;
  end if;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= now() then
    return query select false, 'lease_lost'::text, v_item.status, false;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    -- Work nobody is authorized to run is terminal, whatever the remaining
    -- attempt budget, so this is not recorded as a retryable attempt failure.
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    return query select false, 'creator_unauthorized'::text, 'failed'::text, false;
    return;
  end if;
  update public.factory_runs r
     set status = 'failed', error_code = v_code, finished_at = now(), heartbeat_at = now()
   where r.id = p_run_id;
  delete from private.factory_run_leases l where l.run_id = p_run_id;
  perform private.record_run_event(p_run_id, 'failed', v_run.phase, v_code);
  v_status := private.settle_work_item_after_attempt(v_item.id, p_run_id, v_code);
  return query select true, 'ok'::text, v_status, v_status = 'queued';
end
$$;
revoke all on function public.fail_analysis_run(uuid,uuid,text) from public, anon;
grant execute on function public.fail_analysis_run(uuid,uuid,text) to authenticated;

commit;
