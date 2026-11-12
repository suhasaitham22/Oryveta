-- Reviewed Evolve runtime: a second durable work kind whose attempts must
-- publish an ordered, digest-bound chain of reviewed stages and a privately
-- stored candidate archive, and whose result is never a deployment - only a
-- review candidate a human project administrator can approve or reject.
--
-- Apply AFTER supabase/schema.sql,
-- supabase/migrations/private_chats_and_explicit_sharing.sql,
-- supabase/migrations/projects_and_project_membership.sql,
-- supabase/migrations/durable_factory_runtime.sql and
-- supabase/migrations/retained_attribution_and_lease_clock.sql, in that order.
-- This file is re-appliable. It requires the Supabase Storage schema, because
-- candidate archives live in a private bucket whose policies are part of the
-- authorization model rather than an afterthought.
--
-- Dedicated Oryveta project only. What this file re-owns from the two files
-- above is deliberately narrow and listed here:
--   * public.work_items: the kind and status enumerations, plus the new
--     columns goal, evolve_config_sha256, decided_at and decided_by.
--   * public.factory_runs: the status and phase enumerations, and the
--     finished_at rule, which now admits the one non-running state that has
--     already stopped executing (awaiting_approval).
--   * public.factory_run_events: the kind and phase enumerations.
--   * private.fence_running_runs and private.expire_stale_runs, so a
--     cancellation or an expiry also closes an Evolve attempt that is waiting
--     for a human decision and buries its candidate lessons.
--   * public.heartbeat_analysis_run, public.finish_analysis_run and
--     public.fail_analysis_run, which now refuse a run whose work item is not
--     a repository_analysis. Without that refusal an Evolve attempt could be
--     completed through the analysis RPC and skip every review this file
--     exists to require. Their analysis behaviour is otherwise unchanged.
-- No existing authorization check is relaxed, no existing argument list or
-- return shape changes, and public.claim_analysis_work already filters on
-- kind = 'repository_analysis'.
--
-- Boundaries this migration keeps:
--   * One work queue and one worker identity model. Evolve reuses
--     public.work_items, public.factory_runs, public.factory_run_events,
--     public.project_workers and private.factory_run_leases. The two kinds
--     cannot cross-route: every Evolve RPC refuses analysis work and every
--     analysis RPC refuses Evolve work.
--   * Browsers never mutate run state and never hold worker authority. The
--     authenticated role keeps SELECT only on every table here, uploads into
--     the private bucket are restricted to the live worker of the exact
--     attempt, and a stored artifact row is readable only once it has been
--     registered by that worker.
--   * A model can publish nothing. Stage admission is ordered, stage payloads
--     are strictly typed and bounded, the candidate digest must match bytes
--     the worker actually uploaded, and the final transition is to
--     awaiting_approval - never to succeeded. Only a current project admin,
--     naming the exact run and candidate digest, can approve.
--   * Learning is not memory until a human says so. Lessons are extracted as
--     candidates, carry the exact source and config digests of the attempt
--     that produced them, become readable to workers only when an approval
--     activates the ones their reviewer passed, and an admin can revoke them.
--   * A failed attempt is evidence too, and its evidence is a terminal
--     diagnostic side branch rather than a stage. One immutable failure report
--     is stored in the attempt's own result, the lessons its failure analysis
--     extracted are recorded as rejected diagnostic rows that no approval can
--     activate, and once that report exists the attempt may only heartbeat,
--     fail or be cancelled: it can publish no further stage and can never
--     finish as a candidate a human could approve.
--   * An attempt that was expired, cancelled or revoked instead of reporting
--     carries a server-built learning-unavailable record. The server owns no
--     model identity, so that record states only that no learning analysis
--     exists and why - it never names a reviewer or a lesson.
--   * Every text column is an id, a short enumerated code, a digest, a
--     bounded derived detail or the submitter's own goal. No column holds a
--     URL, a host path, a credential or a model's chain of thought.

begin;

-- ---------------------------------------------------------------------------
-- 0. Preflight
-- ---------------------------------------------------------------------------

-- Candidate archives are private objects, and "private" here means the bucket
-- plus the two policies below. Applying the rest of this file without a
-- Storage schema would create a runtime that registers artifacts nobody can
-- fetch, so this stops instead.
do $storage_preflight$
declare
  v_exempt boolean;
begin
  if to_regclass('storage.buckets') is null or to_regclass('storage.objects') is null then
    raise exception 'this migration requires the Supabase Storage schema '
      '(storage.buckets and storage.objects); apply it to a Supabase stack with '
      'Storage enabled';
  end if;
  -- public.register_evolve_artifact verifies, server side, that the object a
  -- worker claims to have uploaded really exists with the declared size. That
  -- read runs with the privileges of the role that owns the function, which is
  -- the role applying this file, so a role that row level security would
  -- filter on storage.objects would see no object and refuse every honest
  -- registration. That is worth failing on now rather than in production.
  select r.rolsuper or r.rolbypassrls
       or pg_catalog.pg_has_role(r.rolname, c.relowner, 'USAGE')
    into v_exempt
    from pg_catalog.pg_roles r, pg_catalog.pg_class c
   where r.rolname = current_user and c.oid = 'storage.objects'::regclass;
  if not coalesce(v_exempt, false) then
    raise exception 'apply this migration as a role that owns storage.objects or bypasses '
      'row level security on it, because register_evolve_artifact has to verify an '
      'uploaded candidate archive';
  end if;
end
$storage_preflight$;

-- ---------------------------------------------------------------------------
-- 1. Canonical state: one more kind, one more lifecycle state, and the three
--    columns an Evolve request needs.
-- ---------------------------------------------------------------------------

-- The submitted goal. Bounded, printable, and required exactly for the new
-- kind: an analysis item still carries none, so the frozen-input rules of the
-- existing migration are untouched.
alter table public.work_items add column if not exists goal text;
-- The resolved trusted operator specification this work item is pinned to,
-- recorded by the first attempt that publishes a requirements stage. A
-- replacement worker running a different configuration is refused rather than
-- silently continuing the same request under other rules.
alter table public.work_items add column if not exists evolve_config_sha256 text;
-- The human approval decision. ON DELETE SET NULL, and the attribution rule
-- below matches retained_attribution_and_lease_clock.sql: the decision and its
-- timestamp are retained when the deciding account is deleted.
alter table public.work_items add column if not exists decided_at timestamptz;
alter table public.work_items add column if not exists decided_by uuid
  references auth.users(id) on delete set null;

alter table public.work_items drop constraint if exists work_items_goal_bounded_check;
alter table public.work_items add constraint work_items_goal_bounded_check
  check(goal is null or (char_length(goal) between 1 and 4000
                         and goal ~ '[^[:space:]]'
                         and goal !~ '[^[:print:]\n\t]'));

alter table public.work_items drop constraint if exists work_items_goal_kind_check;
alter table public.work_items add constraint work_items_goal_kind_check
  check((kind = 'evolve') = (goal is not null));

alter table public.work_items drop constraint if exists work_items_evolve_config_check;
alter table public.work_items add constraint work_items_evolve_config_check
  check(evolve_config_sha256 is null
     or (kind = 'evolve' and evolve_config_sha256 ~ '^[0-9a-f]{64}$'));

alter table public.work_items drop constraint if exists work_items_decision_attribution_check;
alter table public.work_items add constraint work_items_decision_attribution_check
  check((decided_by is null or decided_at is not null)
    and (decided_at is null or kind = 'evolve'));

-- The enumerations the files above created without names. They are retired by
-- predicate rather than by generated name, so this runs on a deployment whose
-- constraint names differ and is a no-op on one that already carries the
-- replacements below. The assertion after them fails loudly instead of leaving
-- an unreachable state behind.
do $retire_enumerations$
declare
  v_target record;
  v_name text;
begin
  for v_target in
    select * from (values
      -- relation, predicate that identifies the superseded constraint, text
      -- the replacement contains and the superseded one cannot.
      ('public.work_items',       '%repository_analysis%',        '%evolve%'),
      ('public.work_items',       '%''queued''%',                 '%awaiting_approval%'),
      ('public.factory_runs',     '%''cancelled''%',              '%awaiting_approval%'),
      ('public.factory_runs',     '%recording_result%',           '%learning_review%'),
      ('public.factory_runs',     '%(finished_at IS NULL)%',      '%CASE%'),
      ('public.factory_run_events', '%retry_scheduled%',          '%approved%'),
      ('public.factory_run_events', '%recording_result%',         '%learning_review%')
    ) as t(relation, superseded, replacement)
  loop
    for v_name in
      select c.conname from pg_catalog.pg_constraint c
       where c.conrelid = v_target.relation::regclass
         and c.contype = 'c'
         and pg_catalog.pg_get_constraintdef(c.oid) like v_target.superseded
         and pg_catalog.pg_get_constraintdef(c.oid) not like v_target.replacement
    loop
      execute format('alter table %s drop constraint %I', v_target.relation, v_name);
    end loop;
  end loop;
end
$retire_enumerations$;

-- awaiting_approval belongs to Evolve only: an analysis item cannot reach a
-- state the analysis RPCs have no transition out of.
alter table public.work_items drop constraint if exists work_items_kind_allowed_check;
alter table public.work_items add constraint work_items_kind_allowed_check
  check(kind in ('repository_analysis','evolve'));
alter table public.work_items drop constraint if exists work_items_status_allowed_check;
alter table public.work_items add constraint work_items_status_allowed_check
  check(status in ('queued','running','awaiting_approval','succeeded','failed','cancelled')
    and (status <> 'awaiting_approval' or kind = 'evolve'));

alter table public.factory_runs drop constraint if exists factory_runs_status_allowed_check;
alter table public.factory_runs add constraint factory_runs_status_allowed_check
  check(status in ('running','awaiting_approval','succeeded','failed','cancelled'));
alter table public.factory_runs drop constraint if exists factory_runs_phase_allowed_check;
alter table public.factory_runs add constraint factory_runs_phase_allowed_check
  check(phase in ('claimed','fetching_source','analyzing','recording_result',
                  'requirements','plan','implementation','verification','audit',
                  'learning','learning_review','awaiting_approval','done'));
-- A running attempt has no finish time; every other state has one. An attempt
-- that is waiting for a human decision has stopped executing, holds no lease
-- and therefore carries finished_at, which the superseded biconditional made
-- impossible.
alter table public.factory_runs drop constraint if exists factory_runs_finished_state_check;
alter table public.factory_runs add constraint factory_runs_finished_state_check
  check(case when status = 'running' then finished_at is null
             else finished_at is not null end);

alter table public.factory_run_events
  drop constraint if exists factory_run_events_kind_allowed_check;
alter table public.factory_run_events add constraint factory_run_events_kind_allowed_check
  check(kind in ('claimed','source_resolved','phase_changed','checkpoint','succeeded',
                 'failed','cancelled','lease_expired','retry_scheduled','attempts_exhausted',
                 'stage_recorded','artifact_registered','failure_report','awaiting_approval',
                 'approved','rejected'));
alter table public.factory_run_events
  drop constraint if exists factory_run_events_phase_allowed_check;
alter table public.factory_run_events add constraint factory_run_events_phase_allowed_check
  check(phase is null or phase in ('claimed','fetching_source','analyzing','recording_result',
                                   'requirements','plan','implementation','verification',
                                   'audit','learning','learning_review','awaiting_approval',
                                   'done'));

do $assert_enumerations$
declare
  v_target record;
  v_survivor text;
begin
  for v_target in
    select * from (values
      ('public.work_items',         '%repository_analysis%',   '%evolve%'),
      ('public.work_items',         '%''queued''%',            '%awaiting_approval%'),
      ('public.factory_runs',       '%''cancelled''%',         '%awaiting_approval%'),
      ('public.factory_runs',       '%recording_result%',      '%learning_review%'),
      ('public.factory_runs',       '%(finished_at IS NULL)%', '%CASE%'),
      ('public.factory_run_events', '%retry_scheduled%',       '%approved%'),
      ('public.factory_run_events', '%recording_result%',      '%learning_review%')
    ) as t(relation, superseded, replacement)
  loop
    select c.conname into v_survivor
      from pg_catalog.pg_constraint c
     where c.conrelid = v_target.relation::regclass
       and c.contype = 'c'
       and pg_catalog.pg_get_constraintdef(c.oid) like v_target.superseded
       and pg_catalog.pg_get_constraintdef(c.oid) not like v_target.replacement
     limit 1;
    if v_survivor is not null then
      raise exception 'check constraint % on % still rejects the reviewed Evolve states this '
        'migration introduces; drop that constraint by name and re-apply this file',
        v_survivor, v_target.relation;
    end if;
  end loop;
end
$assert_enumerations$;

-- ---------------------------------------------------------------------------
-- 2. Tables
-- ---------------------------------------------------------------------------

-- One accepted stage of one attempt: the artifact the worker produced and the
-- independent review that passed it, bound to the snapshot, the operator
-- configuration and - from the implementation stage onwards - the candidate
-- archive they describe. Immutable and unique per attempt: there is no update
-- or delete privilege and no RPC that rewrites a stage, so the chain a human
-- approves is the chain that was recorded.
create table if not exists public.evolve_stages(
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.factory_runs(id) on delete cascade,
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  stage text not null check(stage in ('requirements','plan','implementation','verification',
                                      'audit','learning','learning_review')),
  payload jsonb not null
    check(jsonb_typeof(payload) = 'object' and pg_column_size(payload) <= 65536),
  created_at timestamptz not null default now(),
  constraint evolve_stages_attempt_key unique (run_id, stage)
);
create index if not exists evolve_stages_work_item_idx
  on public.evolve_stages(work_item_id, created_at);
create index if not exists evolve_stages_project_idx
  on public.evolve_stages(project_id, created_at desc);

-- A registered artifact is a row that names bytes already uploaded into the
-- private bucket. storage_path is derived, never supplied: the check below ties
-- it to this row's own run, kind and digest, so no arbitrary path or URL can be
-- stored and a reader cannot be pointed at another attempt's object.
create table if not exists public.evolve_artifacts(
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.factory_runs(id) on delete cascade,
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  kind text not null check(kind in ('patch','candidate','receipt','trace')),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  bytes integer not null check(bytes > 0),
  storage_path text not null,
  created_at timestamptz not null default now(),
  constraint evolve_artifacts_attempt_key unique (run_id, kind, sha256),
  constraint evolve_artifacts_path_derived_check
    check(storage_path = run_id::text || '/' || kind || '/' || sha256),
  -- A candidate is a source archive; everything else is a bounded receipt,
  -- patch or trace.
  constraint evolve_artifacts_bytes_bounded_check
    check(case when kind = 'candidate' then bytes <= 12582912 else bytes <= 1048576 end)
);
create index if not exists evolve_artifacts_run_idx
  on public.evolve_artifacts(run_id, kind);
create index if not exists evolve_artifacts_project_idx
  on public.evolve_artifacts(project_id, created_at desc);
create unique index if not exists evolve_artifacts_path_idx
  on public.evolve_artifacts(storage_path);

-- An extracted lesson. It is a candidate until a human approval activates the
-- ones the learning review passed, and it carries the exact snapshot and
-- operator-config digests of the attempt that produced it: retrieval is keyed
-- on that identity, not on a namespace a model chose. A revoked lesson leaves
-- the approved set immediately and cannot be reinstated by this schema.
--
-- origin separates the two things a lesson can come from. A 'learning' lesson
-- is the proposal of a reviewed learning stage and an approval may activate it.
-- A 'failure_report' lesson is what the failure analysis of an attempt that
-- did not succeed extracted: it is recorded as rejected, and the state check
-- below makes an activated one unrepresentable rather than merely unreachable,
-- so neither a future code path nor a hostile client can turn a failed
-- attempt's analysis into production memory. The two origins share the index
-- space of one attempt - a learning stage may be on record before the failure
-- branch runs - which is why the uniqueness key names the origin as well.
create table if not exists public.evolve_lessons(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  work_item_id uuid not null references public.work_items(id) on delete cascade,
  run_id uuid not null references public.factory_runs(id) on delete cascade,
  lesson_index integer not null check(lesson_index between 0 and 4),
  origin text not null default 'learning',
  status text not null default 'candidate'
    check(status in ('candidate','approved','rejected','revoked')),
  lesson jsonb not null
    check(jsonb_typeof(lesson) = 'object' and pg_column_size(lesson) <= 8192),
  source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
  config_sha256 text not null check(config_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  constraint evolve_lessons_origin_check
    check(origin in ('learning','failure_report')),
  constraint evolve_lessons_diagnostic_state_check
    check(origin = 'learning' or status in ('rejected','revoked')),
  constraint evolve_lessons_origin_attempt_key unique (run_id, origin, lesson_index),
  constraint evolve_lessons_revocation_state_check
    check((status = 'revoked') = (revoked_at is not null)),
  constraint evolve_lessons_revocation_attribution_check
    check(revoked_by is null or revoked_at is not null)
);
-- Re-applied over a deployment that already carries the first version of this
-- table: the column and the two constraints the diagnostic origin needs, and
-- the retirement of the uniqueness key that did not know about it. Identical
-- to the declarations above, so a fresh install simply recreates them.
alter table public.evolve_lessons add column if not exists origin text
  not null default 'learning';
alter table public.evolve_lessons drop constraint if exists evolve_lessons_origin_check;
alter table public.evolve_lessons add constraint evolve_lessons_origin_check
  check(origin in ('learning','failure_report'));
alter table public.evolve_lessons
  drop constraint if exists evolve_lessons_diagnostic_state_check;
alter table public.evolve_lessons add constraint evolve_lessons_diagnostic_state_check
  check(origin = 'learning' or status in ('rejected','revoked'));
alter table public.evolve_lessons drop constraint if exists evolve_lessons_attempt_key;
alter table public.evolve_lessons
  drop constraint if exists evolve_lessons_origin_attempt_key;
alter table public.evolve_lessons add constraint evolve_lessons_origin_attempt_key
  unique (run_id, origin, lesson_index);
-- The retrieval path: approved lessons of one project for one exact source and
-- operator configuration, newest first. A diagnostic lesson can never be
-- approved, so it is never in this index.
create index if not exists evolve_lessons_retrieval_idx
  on public.evolve_lessons(project_id, source_sha256, config_sha256, created_at desc)
  where status = 'approved';
create index if not exists evolve_lessons_run_idx
  on public.evolve_lessons(run_id, lesson_index);

-- ---------------------------------------------------------------------------
-- 3. Row level security. SELECT only, as in the files above: no write
--    privilege is granted to any client role, so mutation goes exclusively
--    through the RPCs below and a forgotten policy fails closed.
-- ---------------------------------------------------------------------------

alter table public.evolve_stages enable row level security;
alter table public.evolve_artifacts enable row level security;
alter table public.evolve_lessons enable row level security;

drop policy if exists evolve_stages_select_authorized on public.evolve_stages;
create policy evolve_stages_select_authorized on public.evolve_stages
for select to authenticated
using((select private.can_read_project(project_id))
   or (select private.is_project_worker(project_id)));

drop policy if exists evolve_artifacts_select_authorized on public.evolve_artifacts;
create policy evolve_artifacts_select_authorized on public.evolve_artifacts
for select to authenticated
using((select private.can_read_project(project_id))
   or (select private.is_project_worker(project_id)));

-- An approved lesson is project-shared knowledge: current readers and the
-- project's own workers may retrieve it. A candidate, rejected or revoked
-- lesson is only inspectable by a project admin - the account that decides
-- whether it ever becomes memory - so a worker can never read, and therefore
-- never act on, a lesson no human activated.
drop policy if exists evolve_lessons_select_scoped on public.evolve_lessons;
create policy evolve_lessons_select_scoped on public.evolve_lessons
for select to authenticated
using((status = 'approved'
       and ((select private.can_read_project(project_id))
         or (select private.is_project_worker(project_id))))
   or (select private.is_project_admin(project_id)));

revoke all on public.evolve_stages, public.evolve_artifacts, public.evolve_lessons
  from anon, authenticated;
grant select on public.evolve_stages, public.evolve_artifacts, public.evolve_lessons
  to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Private artifact storage
-- ---------------------------------------------------------------------------

-- Private bucket. No public flag, no signed-forever URL and no second bucket:
-- a browser fetches an object with its own authenticated session or not at all.
insert into storage.buckets(id, name, public)
values ('evolve-artifacts','evolve-artifacts',false)
on conflict (id) do update set public = false;

-- file_size_limit exists in current Storage schemas and not in the earliest
-- ones, so it is set only when the column is there. The per-kind byte bounds
-- on public.evolve_artifacts are the authority either way.
do $bucket_limits$
begin
  if exists(select 1 from information_schema.columns c
             where c.table_schema = 'storage' and c.table_name = 'buckets'
               and c.column_name = 'file_size_limit') then
    execute 'update storage.buckets set file_size_limit = 12582912
              where id = ''evolve-artifacts''';
  end if;
end
$bucket_limits$;

-- The only object name shape this bucket accepts: <run_id>/<kind>/<sha256>.
create or replace function private.evolve_storage_parts(p_name text)
returns text[] language sql immutable set search_path='' as $$
  select regexp_match(coalesce(p_name, ''),
    '^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    '/(patch|candidate|receipt|trace)/([0-9a-f]{64})$')
$$;
-- An internal of the two predicates below, which are definers: the path
-- grammar is not something a client needs to call.
revoke all on function private.evolve_storage_parts(text)
  from public, anon, authenticated;

-- Upload authority: the designated, currently registered worker identity that
-- holds the running attempt named by the first path segment, and nobody else.
-- A browser session fails this test even for its own project, which is why no
-- member can stage bytes a reviewer might mistake for worker output.
create or replace function private.may_upload_evolve_artifact(p_name text)
returns boolean language sql stable security definer set search_path='' as $$
  with parts as (select private.evolve_storage_parts(p_name) as p)
  select exists(
    select 1
      from parts
      join public.factory_runs r on r.id = (parts.p)[1]::uuid
      join public.work_items w on w.id = r.work_item_id
     where parts.p is not null
       and w.kind = 'evolve'
       and r.status = 'running'
       and r.worker_user_id = (select auth.uid())
       and private.is_project_worker(r.project_id))
$$;
revoke all on function private.may_upload_evolve_artifact(text) from public, anon;
grant execute on function private.may_upload_evolve_artifact(text) to authenticated;

-- Read authority: the object must be a *registered* artifact, and the caller
-- must hold a current grant on its project. Bytes a worker staged but never
-- registered are invisible, so an abandoned or fenced attempt leaves nothing
-- fetchable, and a removed member loses access with their grant.
create or replace function private.may_read_evolve_artifact(p_name text)
returns boolean language sql stable security definer set search_path='' as $$
  select exists(
    select 1 from public.evolve_artifacts a
     where a.storage_path = p_name
       and (private.can_read_project(a.project_id)
         or private.is_project_worker(a.project_id)))
$$;
revoke all on function private.may_read_evolve_artifact(text) from public, anon;
grant execute on function private.may_read_evolve_artifact(text) to authenticated;

drop policy if exists evolve_artifacts_worker_insert on storage.objects;
create policy evolve_artifacts_worker_insert on storage.objects
for insert to authenticated
with check(bucket_id = 'evolve-artifacts' and private.may_upload_evolve_artifact(name));

drop policy if exists evolve_artifacts_registered_select on storage.objects;
create policy evolve_artifacts_registered_select on storage.objects
for select to authenticated
using(bucket_id = 'evolve-artifacts' and private.may_read_evolve_artifact(name));

-- Deliberately no UPDATE and no DELETE policy: an uploaded artifact is
-- immutable to every client role, so the bytes a review cites cannot be
-- swapped for others after the fact.

-- ---------------------------------------------------------------------------
-- 5. Stage ordering and payload validation
-- ---------------------------------------------------------------------------

create or replace function private.evolve_stage_order(p_stage text)
returns integer language sql immutable set search_path='' as $$
  select case p_stage
    when 'requirements' then 1 when 'plan' then 2 when 'implementation' then 3
    when 'verification' then 4 when 'audit' then 5 when 'learning' then 6
    when 'learning_review' then 7 else 0 end
$$;
revoke all on function private.evolve_stage_order(text) from public, anon, authenticated;

-- How many reviewed stages must already exist before a phase may be entered.
-- A worker can therefore report progress, but it cannot announce itself into a
-- phase whose evidence has not been published; finish re-checks the whole
-- chain regardless, so phase is a progress record and never an authorization.
create or replace function private.evolve_phase_requirement(p_phase text)
returns integer language sql immutable set search_path='' as $$
  select case p_phase
    when 'claimed' then 0 when 'fetching_source' then 0 when 'requirements' then 0
    when 'plan' then 1 when 'implementation' then 2 when 'verification' then 3
    when 'audit' then 4 when 'learning' then 5 when 'learning_review' then 6
    when 'awaiting_approval' then 7 when 'done' then 7 else null end
$$;
revoke all on function private.evolve_phase_requirement(text)
  from public, anon, authenticated;

-- A bounded list of bounded printable text entries.
create or replace function private.assert_evolve_text_list(
  p_value jsonb, p_label text, p_min integer, p_max integer, p_max_length integer)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_item jsonb;
  v_text text;
  v_count integer := 0;
begin
  if p_value is null or jsonb_typeof(p_value) <> 'array' then
    raise exception 'stage artifact field % must be a JSON array', p_label;
  end if;
  for v_item in select value from jsonb_array_elements(p_value) loop
    v_count := v_count + 1;
    if jsonb_typeof(v_item) <> 'string' then
      raise exception 'stage artifact field % must hold text entries only', p_label;
    end if;
    v_text := v_item #>> '{}';
    if char_length(v_text) < 1 or char_length(v_text) > p_max_length
       or v_text ~ '[^[:print:]\n\t]' then
      raise exception 'stage artifact field % entries must be 1 to % printable characters',
        p_label, p_max_length;
    end if;
  end loop;
  if v_count < p_min or v_count > p_max then
    raise exception 'stage artifact field % must hold between % and % entries',
      p_label, p_min, p_max;
  end if;
end
$$;
revoke all on function private.assert_evolve_text_list(jsonb,text,integer,integer,integer)
  from public, anon, authenticated;

-- A bounded list of repository-relative paths. Absolute, traversing, Windows
-- and UNC forms are refused, so a plan or a change list cannot describe the
-- worker's host filesystem.
create or replace function private.assert_evolve_path_list(
  p_value jsonb, p_label text, p_min integer, p_max integer)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_item jsonb;
  v_text text;
  v_count integer := 0;
begin
  if p_value is null or jsonb_typeof(p_value) <> 'array' then
    raise exception 'stage artifact field % must be a JSON array', p_label;
  end if;
  for v_item in select value from jsonb_array_elements(p_value) loop
    v_count := v_count + 1;
    if jsonb_typeof(v_item) <> 'string' then
      raise exception 'stage artifact field % must hold text entries only', p_label;
    end if;
    v_text := v_item #>> '{}';
    if v_text !~ '^[A-Za-z0-9._][A-Za-z0-9._/*+-]{0,199}$' or v_text like '%..%' then
      raise exception 'stage artifact field % entries must be repository-relative paths',
        p_label;
    end if;
  end loop;
  if v_count < p_min or v_count > p_max then
    raise exception 'stage artifact field % must hold between % and % entries',
      p_label, p_min, p_max;
  end if;
end
$$;
revoke all on function private.assert_evolve_path_list(jsonb,text,integer,integer)
  from public, anon, authenticated;

-- The bounded shape of a stage payload: snake_case keys, bounded depth, a
-- node budget and bounded printable strings.
--
-- This is deliberately NOT private.assert_safe_json_tree, which additionally
-- refuses any string that looks like a filesystem path or contains a
-- backslash. That rule is right for an analyzer result, where every string is
-- a repository path or a short derived detail, and wrong here: a submitted
-- goal, an acceptance criterion, a risk or a reviewer's explanation is
-- ordinary prose about code, and may legitimately contain a regular
-- expression, a backslash or a path-like example. Because the requirements
-- stage must repeat the submitted goal verbatim, that rule accepted such a
-- goal at submission and then made the request impossible to review. The
-- analysis helper is left exactly as it is.
--
-- No text heuristic is what keeps this record free of credentials and host
-- detail. The fields are a fixed typed set per stage, every path list keeps
-- the strict repository-relative grammar, every digest is checked against
-- bytes that were actually stored, and every event detail is constructed
-- server side from validated values instead of copied from a worker string.
create or replace function private.assert_evolve_json_tree(
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
    raise exception 'stage payload nests more than 6 levels deep';
  end if;
  if v_kind = 'object' then
    for v_key, v_child in select key, value from jsonb_each(p_value) loop
      if v_key !~ '^[a-z][a-z0-9_]{0,39}$' then
        raise exception 'stage payload keys must be snake_case identifiers';
      end if;
      v_nodes := v_nodes
        + private.assert_evolve_json_tree(v_child, p_depth + 1, p_max_string, p_max_nodes);
    end loop;
  elsif v_kind = 'array' then
    for v_child in select value from jsonb_array_elements(p_value) loop
      v_nodes := v_nodes
        + private.assert_evolve_json_tree(v_child, p_depth + 1, p_max_string, p_max_nodes);
    end loop;
  elsif v_kind = 'string' then
    v_text := p_value #>> '{}';
    if char_length(v_text) > p_max_string then
      raise exception 'stage payload strings may be at most % characters', p_max_string;
    end if;
    if v_text ~ '[^[:print:]\n\t]' then
      raise exception 'stage payload strings must be printable text';
    end if;
  end if;
  if v_nodes > p_max_nodes then
    raise exception 'stage payload has more than % nodes', p_max_nodes;
  end if;
  return v_nodes;
end
$$;
revoke all on function private.assert_evolve_json_tree(jsonb,integer,integer,integer)
  from public, anon, authenticated;

-- Every scalar these payloads interpret as text is read through here, because
-- SQL's three-valued logic makes a missing or JSON-null field invisible to a
-- grammar check: `(obj->>'field') !~ pattern` and `(obj->>'field') not in (...)`
-- are both NULL - and therefore not a failure - when the field is absent or
-- null. A payload could otherwise carry a null digest, verdict, model name or
-- severity straight past its gate and be stored. The field must be a JSON
-- string of bounded printable text before any grammar is applied to it.
create or replace function private.assert_evolve_scalar_text(
  p_value jsonb, p_label text, p_max_length integer)
returns text language plpgsql immutable set search_path='' as $$
declare
  v_text text;
begin
  if p_value is null or jsonb_typeof(p_value) <> 'string' then
    raise exception 'stage field % must be a JSON string', p_label;
  end if;
  v_text := p_value #>> '{}';
  if char_length(v_text) < 1 or char_length(v_text) > p_max_length then
    raise exception 'stage field % must be 1 to % characters', p_label, p_max_length;
  end if;
  if v_text ~ '[^[:print:]\n\t]' then
    raise exception 'stage field % must be printable text', p_label;
  end if;
  return v_text;
end
$$;
revoke all on function private.assert_evolve_scalar_text(jsonb,text,integer)
  from public, anon, authenticated;

create or replace function private.assert_evolve_object_keys(
  p_value jsonb, p_label text, p_keys text[])
returns void language plpgsql immutable set search_path='' as $$
begin
  if p_value is null or jsonb_typeof(p_value) <> 'object' then
    raise exception 'stage artifact field % must be a JSON object', p_label;
  end if;
  if exists(select 1 from jsonb_object_keys(p_value) k where k <> all(p_keys))
     or exists(select 1 from unnest(p_keys) k where not p_value ? k) then
    raise exception 'stage artifact field % must contain exactly the fields %',
      p_label, array_to_string(p_keys, ', ');
  end if;
  -- Every key of these objects is required, so a key present with a JSON null
  -- value is a missing field wearing a value, and NULL comparisons downstream
  -- would quietly accept it.
  if exists(select 1 from jsonb_each(p_value) e where jsonb_typeof(e.value) = 'null') then
    raise exception 'stage artifact field % may not carry a JSON null value', p_label;
  end if;
end
$$;
revoke all on function private.assert_evolve_object_keys(jsonb,text,text[])
  from public, anon, authenticated;

-- The whole stage payload, validated against the attempt it claims to belong
-- to. This is the gate that makes a stage row evidence rather than an
-- assertion: the snapshot digest must be the archive this attempt actually
-- fetched, the operator-config digest must be the one the work item is pinned
-- to, the candidate digest must name bytes already uploaded and registered by
-- this worker, and every cited evidence id must resolve to a stage, check or
-- artifact that exists.
--
-- What SQL cannot do here is recompute a canonical-JSON digest, so
-- artifact_sha256 for the requirements and plan stages is accepted as a
-- bounded digest and verified by the engine, while every stage from
-- implementation onwards is checked against real stored bytes.
create or replace function private.assert_evolve_stage_payload(
  p_run_id uuid, p_work_item_id uuid, p_stage text, p_payload jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare
  v_run public.factory_runs;
  v_item public.work_items;
  v_artifact jsonb;
  v_review jsonb;
  v_source text;
  v_config text;
  v_digest text;
  v_candidate text;
  v_patch text;
  v_impl_candidate text;
  v_checks jsonb := '[]'::jsonb;
  v_check jsonb;
  v_decision jsonb;
  v_lesson jsonb;
  v_finding jsonb;
  v_evidence jsonb;
  v_text text;
  v_verdict text;
  v_count integer;
  v_expected integer;
  v_indexes integer[] := array[]::integer[];
begin
  if jsonb_typeof(p_payload) <> 'object' then
    raise exception 'stage payload must be a JSON object';
  end if;
  if pg_column_size(p_payload) > 65536 then
    raise exception 'stage payload exceeds the 65536 byte persisted limit';
  end if;
  -- Keys, string bounds, nesting depth and the node budget of a stage payload.
  -- Prose about code is allowed to contain backslashes and path-like text; the
  -- strict per-field shapes below, not a text heuristic, are what bound this
  -- record.
  perform private.assert_evolve_json_tree(p_payload, 1, 4000, 6000);
  perform private.assert_evolve_object_keys(p_payload, 'payload',
    array['schema_version','source_sha256','config_sha256','artifact_sha256',
          'artifact','review']);
  if p_payload->'schema_version' <> '1'::jsonb then
    raise exception 'stage payload schema_version must be 1';
  end if;
  -- Read as JSON strings rather than as text: a field that is absent, null or
  -- of another type is refused here instead of becoming a NULL that the
  -- grammar check below cannot see.
  v_source := private.assert_evolve_scalar_text(
    p_payload->'source_sha256', 'payload.source_sha256', 64);
  v_config := private.assert_evolve_scalar_text(
    p_payload->'config_sha256', 'payload.config_sha256', 64);
  v_digest := private.assert_evolve_scalar_text(
    p_payload->'artifact_sha256', 'payload.artifact_sha256', 64);
  if v_source !~ '^[0-9a-f]{64}$' or v_config !~ '^[0-9a-f]{64}$'
     or v_digest !~ '^[0-9a-f]{64}$' then
    raise exception 'stage payload digests must be 64 character lowercase hexadecimal';
  end if;

  select r.* into v_run from public.factory_runs r where r.id = p_run_id;
  select w.* into v_item from public.work_items w where w.id = p_work_item_id;
  if v_run.source_digest is null then
    raise exception 'the snapshot this attempt analyses must be recorded before a stage';
  end if;
  if v_run.source_digest <> 'sha256:' || v_source then
    raise exception 'stage payload source digest is not the snapshot this attempt recorded';
  end if;
  -- The operator configuration is pinned per work item at the requirements
  -- stage, so a replacement worker cannot continue the same request under
  -- different trusted rules.
  if v_item.evolve_config_sha256 is not null and v_item.evolve_config_sha256 <> v_config then
    raise exception 'stage payload config digest is not the operator config this work '
      'item is pinned to';
  end if;
  -- And it is identical across the stages of one attempt.
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id and s.payload->>'config_sha256' <> v_config) then
    raise exception 'stage payload config digest disagrees with an earlier stage of this attempt';
  end if;

  v_artifact := p_payload->'artifact';
  v_review := p_payload->'review';
  if jsonb_typeof(v_artifact) <> 'object' or jsonb_typeof(v_review) <> 'object' then
    raise exception 'stage payload artifact and review must be JSON objects';
  end if;
  perform private.assert_evolve_object_keys(v_review, 'review',
    array['verdict','summary','evidence_ids','findings','reviewer_model','reviewer_digest']);
  v_verdict := private.assert_evolve_scalar_text(v_review->'verdict', 'review.verdict', 20);
  if v_verdict not in ('pass','rework','escalate') then
    raise exception 'a review verdict must be pass, rework or escalate';
  end if;
  -- The verdict decides how much of the stage has to hold up. A passing review
  -- publishes accepted work and is held to every binding below. A terminal
  -- rework or escalation is the reviewer's retained evidence for an attempt
  -- that is about to fail, so it may describe checks that failed, violations
  -- that were found and a candidate that was never published - and the
  -- ordering rule in record_evolve_stage refuses to build anything on top of
  -- it, while finish_evolve_run refuses the run outright.

  -- The candidate digest every stage from implementation onwards is bound to.
  select s.payload->'artifact'->>'candidate_sha256' into v_impl_candidate
    from public.evolve_stages s where s.run_id = p_run_id and s.stage = 'implementation';

  if p_stage = 'requirements' then
    perform private.assert_evolve_object_keys(v_artifact, 'requirements.artifact',
      array['goal','acceptance_criteria','constraints']);
    if jsonb_typeof(v_artifact->'goal') <> 'string'
       or (v_artifact->>'goal') <> v_item.goal then
      raise exception 'the requirements artifact must repeat the submitted goal verbatim';
    end if;
    perform private.assert_evolve_text_list(v_artifact->'acceptance_criteria',
      'requirements.acceptance_criteria', 1, 20, 500);
    perform private.assert_evolve_text_list(v_artifact->'constraints',
      'requirements.constraints', 0, 20, 500);

  elsif p_stage = 'plan' then
    perform private.assert_evolve_object_keys(v_artifact, 'plan.artifact',
      array['steps','allowed_paths','risks']);
    perform private.assert_evolve_text_list(v_artifact->'steps', 'plan.steps', 1, 30, 500);
    perform private.assert_evolve_path_list(v_artifact->'allowed_paths',
      'plan.allowed_paths', 1, 50);
    perform private.assert_evolve_text_list(v_artifact->'risks', 'plan.risks', 0, 20, 500);

  elsif p_stage = 'implementation' then
    perform private.assert_evolve_object_keys(v_artifact, 'implementation.artifact',
      array['candidate_sha256','patch_sha256','changed_paths','summary']);
    v_candidate := private.assert_evolve_scalar_text(
      v_artifact->'candidate_sha256', 'implementation.candidate_sha256', 64);
    v_patch := private.assert_evolve_scalar_text(
      v_artifact->'patch_sha256', 'implementation.patch_sha256', 64);
    if v_candidate !~ '^[0-9a-f]{64}$' or v_patch !~ '^[0-9a-f]{64}$' then
      raise exception 'the implementation artifact digests must be 64 character lowercase '
        'hexadecimal';
    end if;
    if v_candidate <> v_digest then
      raise exception 'the implementation stage digest must be the candidate archive digest';
    end if;
    perform private.assert_evolve_path_list(v_artifact->'changed_paths',
      'implementation.changed_paths', 1, 200);
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_artifact->'summary'), 'implementation.summary', 1, 1, 4000);
    -- A published candidate must be real bytes: the archive and its patch have
    -- to be in the private bucket and registered by this worker before a
    -- passing implementation review can describe them. A rejected
    -- implementation review is exempt, because the candidate it refused is
    -- never uploaded.
    if v_verdict = 'pass' then
      if not exists(select 1 from public.evolve_artifacts a
                     where a.run_id = p_run_id and a.kind = 'candidate'
                       and a.sha256 = v_candidate) then
        raise exception 'the candidate archive must be uploaded and registered before the '
          'implementation stage';
      end if;
      if not exists(select 1 from public.evolve_artifacts a
                     where a.run_id = p_run_id and a.kind = 'patch'
                       and a.sha256 = v_patch) then
        raise exception 'the patch must be uploaded and registered before the implementation '
          'stage';
      end if;
    end if;

  elsif p_stage = 'verification' then
    perform private.assert_evolve_object_keys(v_artifact, 'verification.artifact',
      array['candidate_sha256','checks','baseline_reproduced','preservation_passed',
            'verification']);
    v_candidate := private.assert_evolve_scalar_text(
      v_artifact->'candidate_sha256', 'verification.candidate_sha256', 64);
    if jsonb_typeof(v_artifact->'checks') <> 'array' then
      raise exception 'stage artifact field verification.checks must be a JSON array';
    end if;
    v_count := jsonb_array_length(v_artifact->'checks');
    if v_count < 1 or v_count > 50 then
      raise exception 'stage artifact field verification.checks must hold between 1 and 50 '
        'entries';
    end if;
    for v_check in select value from jsonb_array_elements(v_artifact->'checks') loop
      perform private.assert_evolve_object_keys(v_check, 'verification.checks',
        array['name','passed']);
      if private.assert_evolve_scalar_text(
           v_check->'name', 'verification.checks.name', 60)
         !~ '^[A-Za-z0-9][A-Za-z0-9 ._:+-]{0,59}$' then
        raise exception 'verification check names must be bounded identifiers';
      end if;
      if jsonb_typeof(v_check->'passed') <> 'boolean' then
        raise exception 'a verification check must report a boolean result';
      end if;
      if v_verdict = 'pass' and v_check->'passed' <> 'true'::jsonb then
        raise exception 'a passing verification stage cannot record a check that failed';
      end if;
      v_checks := v_checks || jsonb_build_array(v_check->'name');
    end loop;
    if jsonb_typeof(v_artifact->'baseline_reproduced') <> 'boolean'
       or jsonb_typeof(v_artifact->'preservation_passed') <> 'boolean'
       or private.assert_evolve_scalar_text(
            v_artifact->'verification', 'verification.verification', 20)
          not in ('passed','failed') then
      raise exception 'a verification stage must report boolean baseline and preservation '
        'results and an overall passed or failed verification';
    end if;
    if v_verdict = 'pass'
       and (v_artifact->'baseline_reproduced' <> 'true'::jsonb
         or v_artifact->'preservation_passed' <> 'true'::jsonb
         or (v_artifact->>'verification') <> 'passed') then
      raise exception 'a passing verification stage requires a reproduced baseline, passed '
        'preservation and an overall passed verification';
    end if;

  elsif p_stage = 'audit' then
    perform private.assert_evolve_object_keys(v_artifact, 'audit.artifact',
      array['candidate_sha256','required_stages','violations','summary']);
    v_candidate := private.assert_evolve_scalar_text(
      v_artifact->'candidate_sha256', 'audit.candidate_sha256', 64);
    if v_artifact->'required_stages' <>
       '["requirements","plan","implementation","verification"]'::jsonb then
      raise exception 'the audit artifact must state the four required process stages';
    end if;
    perform private.assert_evolve_text_list(v_artifact->'violations',
      'audit.violations', 0, 20, 500);
    if v_verdict = 'pass' and v_artifact->'violations' <> '[]'::jsonb then
      raise exception 'an audit stage with recorded violations cannot be published as passed';
    end if;
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_artifact->'summary'), 'audit.summary', 1, 1, 4000);

  elsif p_stage = 'learning' then
    perform private.assert_evolve_object_keys(v_artifact, 'learning.artifact',
      array['candidate_sha256','lessons']);
    v_candidate := private.assert_evolve_scalar_text(
      v_artifact->'candidate_sha256', 'learning.candidate_sha256', 64);
    if jsonb_typeof(v_artifact->'lessons') <> 'array' then
      raise exception 'stage artifact field learning.lessons must be a JSON array';
    end if;
    if jsonb_array_length(v_artifact->'lessons') > 5 then
      raise exception 'a learning stage may propose at most 5 lessons';
    end if;
    for v_lesson in select value from jsonb_array_elements(v_artifact->'lessons') loop
      perform private.assert_evolve_object_keys(v_lesson, 'learning.lessons',
        array['summary','applicability','evidence_ids','counterexamples']);
      perform private.assert_evolve_text_list(
        jsonb_build_array(v_lesson->'summary'), 'learning.lessons.summary', 1, 1, 1000);
      perform private.assert_evolve_text_list(
        jsonb_build_array(v_lesson->'applicability'), 'learning.lessons.applicability',
        1, 1, 500);
      perform private.assert_evolve_text_list(v_lesson->'evidence_ids',
        'learning.lessons.evidence_ids', 1, 10, 200);
      perform private.assert_evolve_text_list(v_lesson->'counterexamples',
        'learning.lessons.counterexamples', 0, 5, 500);
    end loop;

  elsif p_stage = 'learning_review' then
    perform private.assert_evolve_object_keys(v_artifact, 'learning_review.artifact',
      array['candidate_sha256','decisions']);
    v_candidate := private.assert_evolve_scalar_text(
      v_artifact->'candidate_sha256', 'learning_review.candidate_sha256', 64);
    select coalesce(jsonb_array_length(s.payload->'artifact'->'lessons'), 0) into v_expected
      from public.evolve_stages s where s.run_id = p_run_id and s.stage = 'learning';
    if v_expected is null then
      raise exception 'the learning stage must be recorded before its review';
    end if;
    if jsonb_typeof(v_artifact->'decisions') <> 'array' then
      raise exception 'stage artifact field learning_review.decisions must be a JSON array';
    end if;
    if jsonb_array_length(v_artifact->'decisions') <> v_expected then
      raise exception 'the learning review must decide every proposed lesson exactly once';
    end if;
    for v_decision in select value from jsonb_array_elements(v_artifact->'decisions') loop
      perform private.assert_evolve_object_keys(v_decision, 'learning_review.decisions',
        array['index','verdict','reason']);
      if jsonb_typeof(v_decision->'index') <> 'number'
         or (v_decision->>'index') !~ '^[0-4]$' then
        raise exception 'a learning review decision index must name a proposed lesson';
      end if;
      if (v_decision->>'index')::integer >= v_expected
         or (v_decision->>'index')::integer = any(v_indexes) then
        raise exception 'the learning review must decide every proposed lesson exactly once';
      end if;
      v_indexes := v_indexes || (v_decision->>'index')::integer;
      if private.assert_evolve_scalar_text(
           v_decision->'verdict', 'learning_review.decisions.verdict', 20)
         not in ('pass','reject') then
        raise exception 'a learning review decision verdict must be pass or reject';
      end if;
      perform private.assert_evolve_text_list(
        jsonb_build_array(v_decision->'reason'), 'learning_review.decisions.reason',
        1, 1, 1000);
    end loop;
  else
    raise exception 'unknown evolve stage';
  end if;

  -- Every stage that follows the implementation stage describes that exact
  -- candidate archive, and the implementation stage's own digest is the one
  -- later stages must repeat.
  if p_stage <> 'requirements' and p_stage <> 'plan' then
    if v_candidate !~ '^[0-9a-f]{64}$' then
      raise exception 'stage payload digests must be 64 character lowercase hexadecimal';
    end if;
    if p_stage <> 'implementation' then
      if v_impl_candidate is null then
        raise exception 'the implementation stage must be recorded before this stage';
      end if;
      if v_candidate <> v_impl_candidate then
        raise exception 'this stage describes a different candidate than the implementation '
          'stage recorded';
      end if;
      if v_digest <> v_candidate then
        raise exception 'the stage digest must be the candidate archive digest';
      end if;
    end if;
    if v_verdict = 'pass' and not exists(
         select 1 from public.evolve_artifacts a
          where a.run_id = p_run_id and a.kind = 'candidate'
            and a.sha256 = v_candidate) then
      raise exception 'the candidate archive this stage describes is not a registered '
        'artifact of this attempt';
    end if;
  end if;

  -- The independent review itself. Its keys and verdict were validated before
  -- the artifact above, because the verdict decides which of those bindings
  -- apply.
  perform private.assert_evolve_text_list(
    jsonb_build_array(v_review->'summary'), 'review.summary', 1, 1, 4000);
  if private.assert_evolve_scalar_text(
       v_review->'reviewer_model', 'review.reviewer_model', 80)
     !~ '^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,79}$' then
    raise exception 'a review must name a bounded reviewer model';
  end if;
  if private.assert_evolve_scalar_text(
       v_review->'reviewer_digest', 'review.reviewer_digest', 64)
     !~ '^[0-9a-f]{64}$' then
    raise exception 'a review reviewer_digest must be 64 character lowercase hexadecimal';
  end if;
  if jsonb_typeof(v_review->'evidence_ids') <> 'array'
     or jsonb_array_length(v_review->'evidence_ids') < 1
     or jsonb_array_length(v_review->'evidence_ids') > 20 then
    raise exception 'a review must cite between 1 and 20 evidence ids';
  end if;
  -- Citations are resolved against what actually exists for this attempt: a
  -- recorded stage, a check the verification stage reported, or registered
  -- artifact bytes. An invented reference is refused rather than displayed to
  -- a human as evidence.
  if p_stage <> 'verification' then
    select coalesce(jsonb_agg(c.value->'name'), '[]'::jsonb) into v_checks
      from public.evolve_stages s,
           jsonb_array_elements(s.payload->'artifact'->'checks') c
     where s.run_id = p_run_id and s.stage = 'verification';
  end if;
  for v_evidence in select value from jsonb_array_elements(v_review->'evidence_ids') loop
    if jsonb_typeof(v_evidence) <> 'string' then
      raise exception 'a review evidence id must be text';
    end if;
    v_text := v_evidence #>> '{}';
    if v_text ~ '^stage:' then
      v_text := substring(v_text from 7);
      if private.evolve_stage_order(v_text) = 0 then
        raise exception 'review evidence names an unknown stage';
      end if;
      if v_text <> p_stage and not exists(
           select 1 from public.evolve_stages s
            where s.run_id = p_run_id and s.stage = v_text) then
        raise exception 'review evidence names a stage this attempt has not recorded';
      end if;
    elsif v_text ~ '^check:' then
      v_text := substring(v_text from 7);
      if not v_checks @> jsonb_build_array(v_text) then
        raise exception 'review evidence names a check no verification stage reported';
      end if;
    elsif v_text ~ '^artifact:' then
      v_text := substring(v_text from 10);
      if v_text !~ '^[0-9a-f]{64}$' then
        raise exception 'review evidence must name an artifact by its 64 character digest';
      end if;
      -- Registered bytes of this attempt, or one of the digests this payload
      -- itself declares: a reviewer may cite the artifact it is reviewing even
      -- when it refused to let that artifact be published.
      if v_text <> v_digest
         and v_text is distinct from (v_artifact->>'candidate_sha256')
         and v_text is distinct from (v_artifact->>'patch_sha256')
         and not exists(
           select 1 from public.evolve_artifacts a
            where a.run_id = p_run_id and a.sha256 = v_text)
         and not exists(
           select 1 from public.evolve_stages s
            where s.run_id = p_run_id and s.payload->>'artifact_sha256' = v_text) then
        raise exception 'review evidence names an artifact this attempt has not registered';
      end if;
    else
      raise exception 'a review evidence id must be a stage, check or artifact reference';
    end if;
  end loop;
  if jsonb_typeof(v_review->'findings') <> 'array'
     or jsonb_array_length(v_review->'findings') > 50 then
    raise exception 'a review may record at most 50 findings';
  end if;
  for v_finding in select value from jsonb_array_elements(v_review->'findings') loop
    perform private.assert_evolve_object_keys(v_finding, 'review.findings',
      array['severity','detail','evidence_id']);
    if private.assert_evolve_scalar_text(
         v_finding->'severity', 'review.findings.severity', 20)
       not in ('blocking','warning') then
      raise exception 'a review finding severity must be blocking or warning';
    end if;
    -- A blocking finding is exactly what a rework or escalation records; what
    -- cannot exist is a pass that carries one.
    if v_verdict = 'pass' and (v_finding->>'severity') = 'blocking' then
      raise exception 'a passing review cannot carry a blocking finding';
    end if;
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_finding->'detail'), 'review.findings.detail', 1, 1, 1000);
    if not (v_review->'evidence_ids') @> jsonb_build_array(v_finding->'evidence_id') then
      raise exception 'a review finding must cite one of the review evidence ids';
    end if;
  end loop;
end
$$;
revoke all on function private.assert_evolve_stage_payload(uuid,uuid,text,jsonb)
  from public, anon, authenticated;

-- The terminal diagnostic report of an attempt that did not succeed, validated
-- against the attempt it describes. It is not a stage: it may follow a rejected
-- review or no stage at all, it names no candidate archive, and nothing can be
-- built on top of it. What it must be is honest, which is what this gate is
-- for:
--   * the snapshot and operator-config identity are the ones this attempt and
--     this work item are already pinned to, and only an attempt that has in
--     fact recorded no snapshot may report that it fetched none;
--   * the stage it says it failed in is not a stage it published as passed;
--   * the check outcomes are bounded names with real boolean results that do
--     not contradict a verification stage this attempt recorded, and a report
--     of a failed verification has to name the outcomes that failed;
--   * 'reviewed' means an extractor and an independent lesson reviewer really
--     ran: there is exactly one decision for every extracted lesson;
--   * 'unavailable' is the opposite claim and must therefore carry no lesson,
--     no decision and a reason other than 'completed';
--   * every lesson citation resolves to this report's own error code, a stage
--     this attempt recorded, a check outcome on record, or registered bytes.
-- Every field is a fixed typed scalar, a bounded enumeration, a digest or
-- bounded prose about code. This shape has no path, no argument list, no
-- expected value and no captured output to carry.
create or replace function private.assert_evolve_failure_report(
  p_run_id uuid, p_work_item_id uuid, p_report jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare
  v_keys text[] := array['schema_version','error_code','failed_stage','source_sha256',
                         'config_sha256','checks','learning_status','learning_reason',
                         'lessons','decisions','reviewer_model','reviewer_digest'];
  v_run public.factory_runs;
  v_item public.work_items;
  v_source text;
  v_config text;
  v_code text;
  v_stage text;
  v_status text;
  v_reason text;
  v_check jsonb;
  v_lesson jsonb;
  v_decision jsonb;
  v_evidence jsonb;
  v_text text;
  v_names jsonb := '[]'::jsonb;
  v_count integer;
  v_lessons integer;
  v_failed integer := 0;
  v_indexes integer[] := array[]::integer[];
begin
  if p_report is null or jsonb_typeof(p_report) <> 'object' then
    raise exception 'a failure report must be a JSON object';
  end if;
  if pg_column_size(p_report) > 65536 then
    raise exception 'a failure report exceeds the 65536 byte persisted limit';
  end if;
  if exists(select 1 from jsonb_object_keys(p_report) k where k <> all(v_keys))
     or exists(select 1 from unnest(v_keys) k where not p_report ? k) then
    raise exception 'a failure report must contain exactly the fields %',
      array_to_string(v_keys, ', ');
  end if;
  -- source_sha256 is the one field a JSON null means something in: it states
  -- that this attempt never fetched a snapshot. Anywhere else a null is a
  -- missing field wearing a value, which the grammar checks below could not
  -- see.
  if exists(select 1 from jsonb_each(p_report) e
             where jsonb_typeof(e.value) = 'null' and e.key <> 'source_sha256') then
    raise exception 'only source_sha256 may be a JSON null in a failure report';
  end if;
  if p_report->'schema_version' <> '1'::jsonb then
    raise exception 'failure report schema_version must be 1';
  end if;
  v_code := private.assert_evolve_scalar_text(
    p_report->'error_code', 'report.error_code', 48);
  -- The same bounded code grammar public.fail_evolve_run accepts, because the
  -- report describes the failure that call is about to record.
  if v_code !~ '^[a-z][a-z0-9_]{2,47}$' then
    raise exception 'a failure report error code must be 3-48 characters of a-z 0-9 _';
  end if;
  v_stage := private.assert_evolve_scalar_text(
    p_report->'failed_stage', 'report.failed_stage', 20);
  if v_stage not in ('claimed','fetching_source','requirements','plan','implementation',
                     'verification','audit','learning','learning_review') then
    raise exception 'a failure report must name the stage this attempt failed in';
  end if;
  -- A stage this attempt published as passed is on record as accepted work, so
  -- it cannot also be the stage the attempt failed in.
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id and s.stage = v_stage
               and s.payload->'review'->>'verdict' = 'pass') then
    raise exception 'this attempt published that stage as passed, so it is not the stage it '
      'failed in';
  end if;

  select r.* into v_run from public.factory_runs r where r.id = p_run_id;
  select w.* into v_item from public.work_items w where w.id = p_work_item_id;
  if jsonb_typeof(p_report->'source_sha256') = 'null' then
    if v_run.source_digest is not null then
      raise exception 'this attempt recorded a snapshot, so the report may not claim it '
        'fetched none';
    end if;
  else
    v_source := private.assert_evolve_scalar_text(
      p_report->'source_sha256', 'report.source_sha256', 64);
    if v_source !~ '^[0-9a-f]{64}$' then
      raise exception 'failure report digests must be 64 character lowercase hexadecimal';
    end if;
    if v_run.source_digest is null or v_run.source_digest <> 'sha256:' || v_source then
      raise exception 'the report source digest is not the snapshot this attempt recorded';
    end if;
  end if;
  v_config := private.assert_evolve_scalar_text(
    p_report->'config_sha256', 'report.config_sha256', 64);
  if v_config !~ '^[0-9a-f]{64}$' then
    raise exception 'failure report digests must be 64 character lowercase hexadecimal';
  end if;
  if v_item.evolve_config_sha256 is not null and v_item.evolve_config_sha256 <> v_config then
    raise exception 'the report config digest is not the operator config this work item is '
      'pinned to';
  end if;
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id and s.payload->>'config_sha256' <> v_config) then
    raise exception 'the report config digest disagrees with a recorded stage of this attempt';
  end if;

  if jsonb_typeof(p_report->'checks') <> 'array' then
    raise exception 'failure report checks must be a JSON array';
  end if;
  v_count := jsonb_array_length(p_report->'checks');
  if v_count > 50 then
    raise exception 'a failure report may record at most 50 check outcomes';
  end if;
  for v_check in select value from jsonb_array_elements(p_report->'checks') loop
    perform private.assert_evolve_object_keys(v_check, 'report.checks',
      array['name','passed']);
    if private.assert_evolve_scalar_text(v_check->'name', 'report.checks.name', 60)
       !~ '^[A-Za-z0-9][A-Za-z0-9 ._:+-]{0,59}$' then
      raise exception 'failure report check names must be bounded identifiers';
    end if;
    if jsonb_typeof(v_check->'passed') <> 'boolean' then
      raise exception 'a failure report check must report a boolean result';
    end if;
    -- One outcome per check: two entries for one name would be a record that
    -- says both things.
    if v_names @> jsonb_build_array(v_check->'name') then
      raise exception 'a failure report may report each check outcome once';
    end if;
    v_names := v_names || jsonb_build_array(v_check->'name');
    if v_check->'passed' = 'false'::jsonb then v_failed := v_failed + 1; end if;
  end loop;
  -- A failed protected verification is observable as the outcomes that actually
  -- failed, not as an opaque code.
  if v_code = 'verification_failed' and v_failed = 0 then
    raise exception 'a verification_failed report must record the check outcomes that failed';
  end if;
  -- And it may not contradict the immutable record: where a verification stage
  -- of this attempt already reported a check, the report repeats that outcome.
  if exists(
    select 1 from public.evolve_stages s,
         jsonb_array_elements(s.payload->'artifact'->'checks') v,
         jsonb_array_elements(p_report->'checks') c
     where s.run_id = p_run_id and s.stage = 'verification'
       and (v.value->>'name') = (c.value->>'name')
       and v.value->'passed' is distinct from c.value->'passed') then
    raise exception 'a failure report contradicts a check outcome this attempt recorded';
  end if;
  -- Citable check names: this report's own outcomes plus any a verification
  -- stage of this attempt recorded.
  select v_names || coalesce(jsonb_agg(c.value->'name'), '[]'::jsonb) into v_names
    from public.evolve_stages s,
         jsonb_array_elements(s.payload->'artifact'->'checks') c
   where s.run_id = p_run_id and s.stage = 'verification';

  v_status := private.assert_evolve_scalar_text(
    p_report->'learning_status', 'report.learning_status', 20);
  if v_status not in ('reviewed','unavailable') then
    raise exception 'a failure report learning_status must be reviewed or unavailable';
  end if;
  v_reason := private.assert_evolve_scalar_text(
    p_report->'learning_reason', 'report.learning_reason', 30);
  if v_reason not in ('completed','no_source','model_unavailable','budget_exhausted',
                      'extraction_failed','authority_lost','worker_interrupted') then
    raise exception 'a failure report learning_reason must be one of the recorded reasons';
  end if;
  -- 'reviewed' is exactly the completed analysis. Anything else has to say what
  -- stopped it, which is what makes unavailability a truthful outcome rather
  -- than a quiet claim of success.
  if (v_status = 'reviewed') <> (v_reason = 'completed') then
    raise exception 'a reviewed failure analysis is the completed one; an unavailable '
      'analysis must record why it is unavailable';
  end if;
  if v_source is null and (v_status <> 'unavailable' or v_reason <> 'no_source') then
    raise exception 'an attempt that never fetched a snapshot has no admissible lesson';
  end if;
  if v_source is not null and v_reason = 'no_source' then
    raise exception 'this attempt recorded a snapshot, so no_source is not why its analysis '
      'is unavailable';
  end if;

  if jsonb_typeof(p_report->'lessons') <> 'array'
     or jsonb_typeof(p_report->'decisions') <> 'array' then
    raise exception 'failure report lessons and decisions must be JSON arrays';
  end if;
  v_lessons := jsonb_array_length(p_report->'lessons');
  if v_lessons > 5 then
    raise exception 'a failure report may extract at most 5 lessons';
  end if;
  if v_status = 'unavailable'
     and (v_lessons <> 0 or jsonb_array_length(p_report->'decisions') <> 0) then
    raise exception 'an unavailable failure analysis may carry no lesson and no decision';
  end if;
  -- Zero lessons is a valid reviewed outcome; what is not valid is a lesson
  -- without a decision or a decision without a lesson.
  if jsonb_array_length(p_report->'decisions') <> v_lessons then
    raise exception 'the failure analysis review must decide every extracted lesson exactly '
      'once';
  end if;
  for v_lesson in select value from jsonb_array_elements(p_report->'lessons') loop
    perform private.assert_evolve_object_keys(v_lesson, 'report.lessons',
      array['summary','applicability','evidence_ids','counterexamples']);
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_lesson->'summary'), 'report.lessons.summary', 1, 1, 1000);
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_lesson->'applicability'), 'report.lessons.applicability', 1, 1, 500);
    perform private.assert_evolve_text_list(v_lesson->'evidence_ids',
      'report.lessons.evidence_ids', 1, 10, 200);
    perform private.assert_evolve_text_list(v_lesson->'counterexamples',
      'report.lessons.counterexamples', 0, 5, 500);
    for v_evidence in select value from jsonb_array_elements(v_lesson->'evidence_ids') loop
      v_text := v_evidence #>> '{}';
      if v_text ~ '^failure:' then
        -- The failure reference of this report is this report's own code; it
        -- cannot cite some other attempt's failure.
        if substring(v_text from 9) <> v_code then
          raise exception 'a failure citation must name this report''s own error code';
        end if;
      elsif v_text ~ '^stage:' then
        v_text := substring(v_text from 7);
        if private.evolve_stage_order(v_text) = 0 then
          raise exception 'failure report evidence names an unknown stage';
        end if;
        if not exists(select 1 from public.evolve_stages s
                       where s.run_id = p_run_id and s.stage = v_text) then
          raise exception 'failure report evidence names a stage this attempt has not '
            'recorded';
        end if;
      elsif v_text ~ '^check:' then
        if not v_names @> jsonb_build_array(substring(v_text from 7)) then
          raise exception 'failure report evidence names a check outcome that is not on '
            'record';
        end if;
      elsif v_text ~ '^artifact:' then
        v_text := substring(v_text from 10);
        if v_text !~ '^[0-9a-f]{64}$' then
          raise exception 'failure report evidence must name an artifact by its 64 character '
            'digest';
        end if;
        if not exists(select 1 from public.evolve_artifacts a
                       where a.run_id = p_run_id and a.sha256 = v_text)
           and not exists(select 1 from public.evolve_stages s
                           where s.run_id = p_run_id
                             and s.payload->>'artifact_sha256' = v_text) then
          raise exception 'failure report evidence names an artifact this attempt has not '
            'registered';
        end if;
      else
        raise exception 'a failure report evidence id must be a failure, stage, check or '
          'artifact reference';
      end if;
    end loop;
  end loop;
  for v_decision in select value from jsonb_array_elements(p_report->'decisions') loop
    perform private.assert_evolve_object_keys(v_decision, 'report.decisions',
      array['index','verdict','reason']);
    if jsonb_typeof(v_decision->'index') <> 'number'
       or (v_decision->>'index') !~ '^[0-4]$' then
      raise exception 'a failure analysis decision index must name an extracted lesson';
    end if;
    if (v_decision->>'index')::integer >= v_lessons
       or (v_decision->>'index')::integer = any(v_indexes) then
      raise exception 'the failure analysis review must decide every extracted lesson exactly '
        'once';
    end if;
    v_indexes := v_indexes || (v_decision->>'index')::integer;
    if private.assert_evolve_scalar_text(
         v_decision->'verdict', 'report.decisions.verdict', 20) not in ('pass','reject') then
      raise exception 'a failure analysis decision verdict must be pass or reject';
    end if;
    perform private.assert_evolve_text_list(
      jsonb_build_array(v_decision->'reason'), 'report.decisions.reason', 1, 1, 1000);
  end loop;
  -- The reviewer identity of the pinned configuration. It is required in both
  -- outcomes because it names who would have judged these lessons; what states
  -- whether that reviewer actually ran is learning_status, never this field.
  if private.assert_evolve_scalar_text(
       p_report->'reviewer_model', 'report.reviewer_model', 80)
     !~ '^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,79}$' then
    raise exception 'a failure report must name a bounded reviewer model';
  end if;
  if private.assert_evolve_scalar_text(
       p_report->'reviewer_digest', 'report.reviewer_digest', 64)
     !~ '^[0-9a-f]{64}$' then
    raise exception 'a failure report reviewer_digest must be 64 character lowercase '
      'hexadecimal';
  end if;
end
$$;
revoke all on function private.assert_evolve_failure_report(uuid,uuid,jsonb)
  from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 6. Fencing helpers, including the state the existing runtime never had
-- ---------------------------------------------------------------------------

-- A candidate lesson of an attempt that did not end in a human approval is
-- buried immediately. Nothing in this schema can move it back, so a cancelled,
-- failed, expired or rejected attempt cannot leave production memory behind.
create or replace function private.reject_candidate_lessons(p_run_id uuid)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_count integer := 0;
begin
  update public.evolve_lessons l set status = 'rejected'
   where l.run_id = p_run_id and l.status = 'candidate';
  get diagnostics v_count = row_count;
  return v_count;
end
$$;
revoke all on function private.reject_candidate_lessons(uuid)
  from public, anon, authenticated;

-- The honest terminal record for an Evolve attempt that was expired, cancelled
-- or revoked instead of reporting. No worker can run an extraction or a lesson
-- review once its authority or its process is gone, and the server holds no
-- model identity of its own, so this writes the only two things it actually
-- knows: that no learning analysis exists for this attempt, and why.
--
-- It never fabricates a reviewer, a lesson or a decision, it never touches a
-- report a worker really produced, and it never claims unavailability for an
-- attempt whose learning review is on record as a stage - that attempt's
-- analysis happened and was simply not approved. Existing result evidence is
-- merged with, not replaced.
create or replace function private.record_evolve_learning_unavailable(
  p_run_id uuid, p_error_code text)
returns boolean language plpgsql security definer set search_path='' as $$
declare
  v_reason text;
  v_count integer := 0;
begin
  -- A revocation or a lost requester authority is an authority loss; an expiry
  -- or a cancellation stopped a process that was still authorized.
  v_reason := case when coalesce(p_error_code, '') in ('worker_revoked','creator_unauthorized')
                   then 'authority_lost' else 'worker_interrupted' end;
  update public.factory_runs r
     set result = coalesce(r.result, '{}'::jsonb)
                  || jsonb_build_object('learning_unavailable',
                       jsonb_build_object('learning_status', 'unavailable',
                                          'learning_reason', v_reason))
   where r.id = p_run_id
     and not coalesce(r.result ? 'failure_report', false)
     and not coalesce(r.result ? 'learning_unavailable', false)
     and exists(select 1 from public.work_items w
                 where w.id = r.work_item_id and w.kind = 'evolve')
     and not exists(select 1 from public.evolve_stages s
                     where s.run_id = r.id and s.stage = 'learning_review');
  get diagnostics v_count = row_count;
  return v_count = 1;
end
$$;
revoke all on function private.record_evolve_learning_unavailable(uuid,text)
  from public, anon, authenticated;

-- Re-owned from durable_factory_runtime.sql: an attempt that is waiting for a
-- human decision is fenced like a running one. It holds no lease, so the
-- delete below is a no-op for it; what matters is that a cancellation makes the
-- candidate undecidable instead of leaving an approvable row behind.
-- Analysis attempts never reach awaiting_approval, so their behaviour is
-- unchanged. Callers hold the work item lock already.
create or replace function private.fence_running_runs(
  p_work_item_id uuid, p_error_code text, p_detail text)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_run record;
  v_count integer := 0;
begin
  for v_run in
    select r.id from public.factory_runs r
     where r.work_item_id = p_work_item_id
       and r.status in ('running','awaiting_approval')
     for update
  loop
    update public.factory_runs r
       set status = 'cancelled', error_code = p_error_code,
           finished_at = coalesce(r.finished_at, now())
     where r.id = v_run.id and r.status in ('running','awaiting_approval');
    if not found then continue; end if;
    delete from private.factory_run_leases l where l.run_id = v_run.id;
    perform private.reject_candidate_lessons(v_run.id);
    -- No worker can produce an analysis of an attempt that has just been
    -- fenced, so the attempt records that no analysis exists rather than
    -- nothing at all.
    perform private.record_evolve_learning_unavailable(v_run.id, p_error_code);
    perform private.record_run_event(v_run.id, 'cancelled', null, p_detail);
    v_count := v_count + 1;
  end loop;
  return v_count;
end
$$;
revoke all on function private.fence_running_runs(uuid,text,text)
  from public, anon, authenticated;

-- Re-owned from retained_attribution_and_lease_clock.sql: identical wall-clock
-- reclaim, plus the lesson burial above. An attempt waiting for approval has no
-- lease and is therefore never reclaimed here.
create or replace function private.expire_stale_runs(p_project_id uuid)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_run record;
  v_count integer := 0;
begin
  for v_run in
    select r.id, r.work_item_id from public.factory_runs r
     where r.project_id = p_project_id and r.status = 'running'
       and r.lease_expires_at < clock_timestamp()
     order by r.started_at
  loop
    perform 1 from public.work_items w where w.id = v_run.work_item_id for update;
    update public.factory_runs r
       set status = 'failed', error_code = 'lease_expired', finished_at = now()
     where r.id = v_run.id and r.status = 'running'
       and r.lease_expires_at < clock_timestamp();
    if not found then continue; end if;
    delete from private.factory_run_leases l where l.run_id = v_run.id;
    perform private.reject_candidate_lessons(v_run.id);
    perform private.record_evolve_learning_unavailable(v_run.id, 'lease_expired');
    perform private.record_run_event(v_run.id, 'lease_expired', null,
      'lease expired without a result');
    perform private.settle_work_item_after_attempt(v_run.work_item_id, v_run.id,
      'lease_expired');
    v_count := v_count + 1;
  end loop;
  return v_count;
end
$$;
revoke all on function private.expire_stale_runs(uuid) from public, anon, authenticated;

-- Whether the worker identity that produced an attempt still holds the
-- authority it produced it with. An approval must not reauthorize work whose
-- worker has been revoked or stripped of its service designation, so this is
-- re-checked at the human decision as well as on every worker transition.
create or replace function private.run_worker_still_authorized(p_run_id uuid)
returns boolean language sql stable security definer set search_path='' as $$
  select exists(
    select 1 from public.factory_runs r
      join public.project_workers k on k.id = r.worker_registration_id
     where r.id = p_run_id
       and k.enabled
       and k.project_id = r.project_id
       and k.worker_user_id = r.worker_user_id
       and private.is_service_worker_identity(r.worker_user_id))
$$;
revoke all on function private.run_worker_still_authorized(uuid)
  from public, anon, authenticated;

-- Re-owned from durable_factory_runtime.sql: revocation takes effect
-- immediately for both kinds of work. The running-attempt loop is unchanged -
-- an analysis attempt is cancelled and its work item requeued or failed
-- exactly as before - and a second loop handles the state Evolve added. An
-- attempt waiting for a human decision holds no lease, so there is nothing to
-- fence in flight; what must not survive is an approvable candidate produced
-- by an identity that is no longer authorized to act for this project. That
-- candidate is therefore closed and its work item fails terminally rather
-- than being handed to another worker, because the request's remaining
-- attempts describe execution and this candidate has already been built.
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
    perform private.reject_candidate_lessons(v_run.id);
    -- The revoked identity cannot analyse the attempt it was running, so the
    -- attempt records that no analysis exists and that authority was lost.
    perform private.record_evolve_learning_unavailable(v_run.id, 'worker_revoked');
    perform private.record_run_event(v_run.id, 'cancelled', null, 'worker registration revoked');
    perform private.settle_work_item_after_attempt(v_run.work_item_id, v_run.id, 'worker_revoked');
    v_fenced := v_fenced + 1;
  end loop;
  -- The Evolve state the existing loop cannot see: a finished attempt whose
  -- candidate is still awaiting a human decision.
  for v_run in
    select r.id, r.work_item_id from public.factory_runs r
     where r.project_id = p_project_id and r.worker_user_id = p_worker_user_id
       and r.status = 'awaiting_approval'
     order by r.started_at
  loop
    perform 1 from public.work_items w where w.id = v_run.work_item_id for update;
    update public.factory_runs r
       set status = 'cancelled', error_code = 'worker_revoked',
           finished_at = coalesce(r.finished_at, now())
     where r.id = v_run.id and r.status = 'awaiting_approval';
    if not found then continue; end if;
    perform private.reject_candidate_lessons(v_run.id);
    perform private.record_run_event(v_run.id, 'cancelled', null,
      'worker registration revoked before the candidate was decided');
    update public.work_items w
       set status = 'failed', error_code = 'worker_revoked'
     where w.id = v_run.work_item_id
       and w.status not in ('succeeded','failed','cancelled');
    v_fenced := v_fenced + 1;
  end loop;
  return query select v_row.id, false, v_fenced;
end
$$;
revoke all on function public.revoke_project_worker(uuid,uuid) from public, anon;
grant execute on function public.revoke_project_worker(uuid,uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 7. The analysis RPCs stay analysis-only
--
-- Re-owned from retained_attribution_and_lease_clock.sql with exactly one
-- added predicate each: the work item must be a repository_analysis. Without
-- it an Evolve attempt could heartbeat, publish a result or fail through the
-- analysis path, which has no stage, review, artifact or approval
-- requirements - the whole reviewed chain would be optional. A run of the
-- other kind is reported as missing, exactly as a run of another worker is, so
-- nothing becomes probeable. public.claim_analysis_work already filters on
-- kind and is untouched.
-- ---------------------------------------------------------------------------

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
  -- The one added predicate: this path serves repository analysis only.
  if v_item.kind <> 'repository_analysis' then
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
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, v_run.status, v_item.status,
                        v_item.cancel_requested_at is not null, null::timestamptz, v_run.phase;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    return query select false, 'creator_unauthorized'::text, 'cancelled'::text, 'failed'::text,
                        false, null::timestamptz, v_run.phase;
    return;
  end if;
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
  if v_item.pinned_source_ref is not null
     and ((v_ref is not null and v_ref <> v_item.pinned_source_ref)
       or (v_commit is not null and v_commit <> v_item.pinned_source_commit)) then
    raise exception 'source identity conflicts with the work item pin';
  end if;
  v_expires := clock_timestamp() + make_interval(secs => p_lease_seconds);
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
  perform private.assert_analysis_result(p_result);
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
  -- Reviewed Evolve work cannot be completed through the analysis path, which
  -- requires no stage, review, artifact or human approval at all.
  if v_item.kind <> 'repository_analysis' then
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
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, v_item.status;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    return query select false, 'creator_unauthorized'::text, 'failed'::text;
    return;
  end if;
  if v_run.source_ref is null or v_run.source_commit is null
     or v_run.source_digest is null then
    return query select false, 'source_identity_missing'::text, v_item.status;
    return;
  end if;
  if v_item.pinned_source_ref is null
     or v_run.source_ref <> v_item.pinned_source_ref
     or v_run.source_commit <> v_item.pinned_source_commit then
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
  if v_item.kind <> 'repository_analysis' then
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
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, v_item.status, false;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
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

-- ---------------------------------------------------------------------------
-- 8. Submitter, worker and administrator RPCs for reviewed Evolve work.
--    Every one re-derives the actor from auth.uid(), re-checks current project
--    authority server side, takes the one lock order (work item, then run) and
--    judges leases on the wall clock read after those locks.
-- ---------------------------------------------------------------------------

-- Accepts an Evolve request for the project's own frozen source URL. The goal,
-- the source identity and the canonical input digest are committed before this
-- returns: the request survives the browser closing immediately afterwards.
create or replace function public.submit_evolve_work(
  p_project_id uuid, p_goal text, p_idempotency_key text default null)
returns table(id uuid, project_id uuid, kind text, status text, goal text,
              source_url text, input_digest text, attempts integer, max_attempts integer,
              created_at timestamptz, replayed boolean)
language plpgsql security definer set search_path='' as $$
#variable_conflict use_column
declare
  v_actor uuid := (select auth.uid());
  v_project public.projects;
  v_goal text := btrim(coalesce(p_goal, ''));
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
  if char_length(v_goal) < 1 or char_length(v_goal) > 4000
     or v_goal !~ '[^[:space:]]' then
    raise exception 'the goal must be nonblank and at most 4000 characters';
  end if;
  if v_goal ~ '[^[:print:]\n\t]' then
    raise exception 'the goal must be printable text';
  end if;
  select p.* into v_project from public.projects p where p.id = p_project_id;
  if v_project.id is null then raise exception 'project not found'; end if;
  if v_project.source_url is null then
    raise exception 'project has no source repository to evolve';
  end if;
  v_parts := private.github_repo_parts(v_project.source_url);
  if v_parts is null then
    raise exception 'only public https://github.com/owner/repo sources can be evolved';
  end if;
  -- Canonical input identity: the kind, the exact frozen source URL and the
  -- exact goal. A reused key describing another goal is a different request.
  v_digest := encode(sha256(convert_to('evolve' || E'\n' || v_project.source_url
                                       || E'\n' || v_goal, 'UTF8')), 'hex');
  if v_key is not null and v_key !~ '^[A-Za-z0-9._:-]{8,120}$' then
    raise exception 'idempotency key must be 8-120 characters of A-Z a-z 0-9 . _ : -';
  end if;
  -- One statement, as in the analysis path: two callers holding the same
  -- scoped key cannot both pass an existence check and then collide.
  insert into public.work_items as w
    (project_id, created_by, kind, goal, source_url, source_owner, source_repo,
     input_digest, idempotency_key)
  values (p_project_id, v_actor, 'evolve', v_goal, v_project.source_url,
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
    if v_existing.kind <> 'evolve' or v_existing.input_digest <> v_digest then
      raise exception 'idempotency key already used for a different input';
    end if;
    return query select v_existing.id, v_existing.project_id, v_existing.kind,
                        v_existing.status, v_existing.goal, v_existing.source_url,
                        v_existing.input_digest, v_existing.attempts,
                        v_existing.max_attempts, v_existing.created_at, true;
    return;
  end if;
  return query select v_row.id, v_row.project_id, v_row.kind, v_row.status, v_row.goal,
                      v_row.source_url, v_row.input_digest, v_row.attempts,
                      v_row.max_attempts, v_row.created_at, false;
end
$$;
revoke all on function public.submit_evolve_work(uuid,text,text) from public, anon;
grant execute on function public.submit_evolve_work(uuid,text,text) to authenticated;

-- Reclaims expired attempts, then takes at most one queued Evolve item with
-- FOR UPDATE SKIP LOCKED. Lock order is registration, work item, run, matching
-- the analysis claim, and the lease is measured from the wall clock after those
-- waits. The kind filter is what keeps the two queues apart: an Evolve worker
-- can never be handed repository analysis.
create or replace function public.claim_evolve_work(
  p_project_id uuid, p_lease_seconds integer default 300)
returns table(work_item_id uuid, run_id uuid, attempt integer, max_attempts integer,
              lease_token uuid, lease_expires_at timestamptz, kind text,
              source_url text, source_owner text, source_repo text, input_digest text,
              pinned_source_ref text, pinned_source_commit text,
              previous_source_digest text, previous_checkpoint jsonb, goal text)
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
  if not private.is_service_worker_identity(v_actor) then
    raise exception 'worker identity is not a provisioned factory worker service identity';
  end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 900 then
    raise exception 'lease seconds must be between 15 and 900';
  end if;
  select w.* into v_registration from public.project_workers w
   where w.project_id = p_project_id and w.worker_user_id = v_actor and w.enabled
   for share;
  if v_registration.id is null then
    raise exception 'worker identity is not registered for this project';
  end if;
  perform private.expire_stale_runs(p_project_id);
  select w.* into v_item from public.work_items w
   where w.project_id = p_project_id and w.kind = 'evolve'
     and w.status = 'queued' and w.cancel_requested_at is null
   order by w.created_at, w.id
   for update skip locked
   limit 1;
  if v_item.id is null then return; end if;
  if not private.creator_may_run(p_project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, null::uuid);
    return;
  end if;
  if v_item.attempts >= v_item.max_attempts then
    update public.work_items w
       set status = 'failed', error_code = coalesce(w.error_code, 'attempts_exhausted')
     where w.id = v_item.id;
    return;
  end if;
  v_attempt := v_item.attempts + 1;
  v_expires := clock_timestamp() + make_interval(secs => p_lease_seconds);
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
  return query select v_item.id, v_run_id, v_attempt, v_item.max_attempts, v_token,
                      v_expires, v_item.kind, v_item.source_url, v_item.source_owner,
                      v_item.source_repo, v_item.input_digest,
                      v_item.pinned_source_ref, v_item.pinned_source_commit,
                      v_previous.source_digest,
                      coalesce(v_previous.checkpoint, '{}'::jsonb), v_item.goal;
end
$$;
revoke all on function public.claim_evolve_work(uuid,integer) from public, anon;
grant execute on function public.claim_evolve_work(uuid,integer) to authenticated;

-- Extends the lease, pins the snapshot identity once per work item and records
-- the phase. Fencing failures are reported rather than raised, so a fenced
-- worker has an unambiguous signal to kill its child process and stop. Phase
-- admission requires the reviewed stages that phase claims to be past; finish
-- re-checks the whole chain regardless.
create or replace function public.heartbeat_evolve_run(
  p_run_id uuid, p_lease_token uuid, p_phase text default null,
  p_source_ref text default null, p_source_commit text default null,
  p_source_digest text default null, p_lease_seconds integer default 300)
returns table(lease_valid boolean, reason text, lease_expires_at timestamptz)
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
  v_ref text;
  v_commit text;
  v_digest text;
  v_required integer;
  v_recorded integer;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 900 then
    raise exception 'lease seconds must be between 15 and 900';
  end if;
  if p_phase is not null and private.evolve_phase_requirement(p_phase) is null then
    raise exception 'unknown run phase';
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
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
    raise exception 'run not found';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if not private.is_project_worker(v_run.project_id) then
    return query select false, 'worker_not_registered'::text, null::timestamptz;
    return;
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running'
     or v_item.cancel_requested_at is not null then
    return query select false,
      case when v_item.cancel_requested_at is not null then 'cancelled'
           else 'not_running' end,
      null::timestamptz;
    return;
  end if;
  -- The wall clock read after both locks, as in the analysis runtime: a
  -- heartbeat that waited must be told that time passed.
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, null::timestamptz;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    perform private.record_evolve_learning_unavailable(p_run_id, 'creator_unauthorized');
    return query select false, 'creator_unauthorized'::text, null::timestamptz;
    return;
  end if;
  -- A terminal diagnostic record is already on this attempt. The heartbeat
  -- itself stays allowed, because a worker that is shutting down has to be able
  -- to hold its lease while it calls public.fail_evolve_run; what it may no
  -- longer do is pin a snapshot identity after a report that states this
  -- attempt fetched none.
  if coalesce(v_run.result ?| array['failure_report','learning_unavailable'], false)
     and v_run.source_digest is null
     and (p_source_ref is not null or p_source_commit is not null
       or p_source_digest is not null) then
    raise exception 'source identity cannot be recorded after a terminal failure record';
  end if;
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
  if v_item.pinned_source_ref is not null
     and ((v_ref is not null and v_ref <> v_item.pinned_source_ref)
       or (v_commit is not null and v_commit <> v_item.pinned_source_commit)) then
    raise exception 'source identity conflicts with the work item pin';
  end if;
  v_phase := coalesce(p_phase, v_run.phase);
  if p_phase is not null then
    v_required := private.evolve_phase_requirement(p_phase);
    -- Only passing stages admit a phase. A recorded rework or escalation ends
    -- the attempt; it does not carry the worker forward.
    select count(*) into v_recorded from public.evolve_stages s
     where s.run_id = p_run_id and s.payload->'review'->>'verdict' = 'pass';
    if v_recorded < v_required then
      raise exception 'phase % cannot be entered before its reviewed stages are recorded',
        p_phase;
    end if;
  end if;
  v_expires := clock_timestamp() + make_interval(secs => p_lease_seconds);
  update public.factory_runs r
     set lease_expires_at = v_expires,
         heartbeat_at = now(),
         phase = v_phase,
         source_ref = v_ref,
         source_commit = v_commit,
         source_digest = v_digest
   where r.id = p_run_id;
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
  end if;
  return query select true, 'ok'::text, v_expires;
end
$$;
revoke all on function
  public.heartbeat_evolve_run(uuid,uuid,text,text,text,text,integer) from public, anon;
grant execute on function
  public.heartbeat_evolve_run(uuid,uuid,text,text,text,text,integer) to authenticated;

-- Registers bytes the worker has already uploaded into the private bucket. The
-- object must exist at the canonical path, belong to this worker and report the
-- declared size, so the row always names real stored bytes; the content hash
-- comes from the worker because only it has read the bytes, and no browser can
-- reach either side of this.
create or replace function public.register_evolve_artifact(
  p_run_id uuid, p_lease_token uuid, p_kind text, p_sha256 text, p_bytes integer)
returns table(id uuid, run_id uuid, work_item_id uuid, project_id uuid, kind text,
              sha256 text, bytes integer, storage_path text, created_at timestamptz,
              replayed boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_kind text := lower(btrim(coalesce(p_kind, '')));
  v_sha text := lower(btrim(coalesce(p_sha256, '')));
  v_path text;
  v_existing public.evolve_artifacts;
  v_row public.evolve_artifacts;
  v_owner uuid;
  v_size bigint;
  v_count integer;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if v_kind not in ('patch','candidate','receipt','trace') then
    raise exception 'artifact kind must be patch, candidate, receipt or trace';
  end if;
  if v_sha !~ '^[0-9a-f]{64}$' then
    raise exception 'artifact sha256 must be 64 character lowercase hexadecimal';
  end if;
  if p_bytes is null or p_bytes <= 0
     or (v_kind = 'candidate' and p_bytes > 12582912)
     or (v_kind <> 'candidate' and p_bytes > 1048576) then
    raise exception 'artifact bytes must be within the bound for its kind';
  end if;
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
    raise exception 'run not found';
  end if;
  if not private.is_project_worker(v_run.project_id) then
    raise exception 'worker identity is not registered for this project';
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running'
     or v_item.cancel_requested_at is not null then
    raise exception 'this attempt is no longer running';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
    raise exception 'the lease for this attempt is no longer valid';
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    raise exception 'the requester no longer has an editing role on this project';
  end if;
  v_path := p_run_id::text || '/' || v_kind || '/' || v_sha;
  select a.* into v_existing from public.evolve_artifacts a
   where a.run_id = p_run_id and a.kind = v_kind and a.sha256 = v_sha;
  if v_existing.id is not null then
    -- Immutable: an exact repetition is a replay, a different size is a
    -- conflicting claim about the same digest.
    if v_existing.bytes <> p_bytes then
      raise exception 'this artifact is already registered with a different size';
    end if;
    return query select v_existing.id, v_existing.run_id, v_existing.work_item_id,
                        v_existing.project_id, v_existing.kind, v_existing.sha256,
                        v_existing.bytes, v_existing.storage_path, v_existing.created_at,
                        true;
    return;
  end if;
  select count(*) into v_count from public.evolve_artifacts a where a.run_id = p_run_id;
  if v_count >= 24 then
    raise exception 'an attempt may register at most 24 artifacts';
  end if;
  -- The bytes must already be there, under this worker's own upload, and the
  -- stored size must agree with the declaration.
  select o.owner,
         case when o.metadata->>'size' ~ '^[0-9]{1,15}$'
              then (o.metadata->>'size')::bigint end
    into v_owner, v_size
    from storage.objects o
   where o.bucket_id = 'evolve-artifacts' and o.name = v_path;
  if not found then
    raise exception 'the artifact must be uploaded to the private bucket before it is '
      'registered';
  end if;
  if v_owner is not null and v_owner <> v_actor then
    raise exception 'the uploaded artifact was not stored by this worker identity';
  end if;
  if v_size is not null and v_size <> p_bytes then
    raise exception 'the uploaded artifact size does not match the registered size';
  end if;
  insert into public.evolve_artifacts as a
    (run_id, work_item_id, project_id, kind, sha256, bytes, storage_path)
  values (p_run_id, v_item.id, v_run.project_id, v_kind, v_sha, p_bytes, v_path)
  returning a.* into v_row;
  perform private.record_run_event(p_run_id, 'artifact_registered', v_run.phase,
    v_kind || ' ' || left(v_sha, 12));
  return query select v_row.id, v_row.run_id, v_row.work_item_id, v_row.project_id,
                      v_row.kind, v_row.sha256, v_row.bytes, v_row.storage_path,
                      v_row.created_at, false;
end
$$;
revoke all on function public.register_evolve_artifact(uuid,uuid,text,text,integer)
  from public, anon;
grant execute on function public.register_evolve_artifact(uuid,uuid,text,text,integer)
  to authenticated;

-- Publishes one reviewed stage. Admission is ordered, the payload is validated
-- against this attempt's snapshot, pinned operator config and registered
-- artifacts, and the row is immutable: an exact repetition replays, anything
-- else is refused. The learning stage additionally materializes its proposed
-- lessons as candidates, which only a human approval can activate.
create or replace function public.record_evolve_stage(
  p_run_id uuid, p_lease_token uuid, p_stage text, p_payload jsonb)
returns table(id uuid, run_id uuid, work_item_id uuid, project_id uuid, stage text,
              created_at timestamptz, replayed boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_stage text := lower(btrim(coalesce(p_stage, '')));
  v_order integer;
  v_recorded integer;
  v_existing public.evolve_stages;
  v_row public.evolve_stages;
  v_lesson jsonb;
  v_index integer := 0;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  v_order := private.evolve_stage_order(v_stage);
  if v_order = 0 then raise exception 'unknown evolve stage'; end if;
  if p_payload is null then raise exception 'stage payload is required'; end if;
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
    raise exception 'run not found';
  end if;
  if not private.is_project_worker(v_run.project_id) then
    raise exception 'worker identity is not registered for this project';
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running'
     or v_item.cancel_requested_at is not null then
    raise exception 'this attempt is no longer running';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
    raise exception 'the lease for this attempt is no longer valid';
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    raise exception 'the requester no longer has an editing role on this project';
  end if;
  -- The diagnostic side branch is terminal. Once this attempt has recorded a
  -- failure report - or the server has recorded that no analysis of it exists -
  -- no normal stage may be published on it, not even a repetition of one it
  -- already holds: the record a human reads must not grow past the point where
  -- the attempt was declared failed.
  if coalesce(v_run.result ?| array['failure_report','learning_unavailable'], false) then
    raise exception 'this attempt has recorded a terminal failure record and may not publish '
      'another stage';
  end if;
  select s.* into v_existing from public.evolve_stages s
   where s.run_id = p_run_id and s.stage = v_stage;
  if v_existing.id is not null then
    if v_existing.payload <> p_payload then
      raise exception 'this stage is already recorded with a different payload';
    end if;
    return query select v_existing.id, v_existing.run_id, v_existing.work_item_id,
                        v_existing.project_id, v_existing.stage, v_existing.created_at,
                        true;
    return;
  end if;
  -- Ordered admission: the stages this one depends on must all be published,
  -- and none of them may be a review that stopped the attempt. A recorded
  -- rework or escalation is retained evidence for a run that must now fail,
  -- not a step the next stage can build on.
  select count(*) into v_recorded from public.evolve_stages s
   where s.run_id = p_run_id and private.evolve_stage_order(s.stage) < v_order;
  if v_recorded <> v_order - 1 then
    raise exception 'stage % cannot be recorded before the stages it depends on', v_stage;
  end if;
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id
               and s.payload->'review'->>'verdict' is distinct from 'pass') then
    raise exception 'stage % cannot follow a review that did not pass', v_stage;
  end if;
  perform private.assert_evolve_stage_payload(p_run_id, v_item.id, v_stage, p_payload);
  -- The operator config is pinned here, under the work item lock, by the first
  -- attempt that publishes requirements. A later attempt running another
  -- trusted configuration is refused by the validator above.
  if v_stage = 'requirements' and v_item.evolve_config_sha256 is null then
    update public.work_items w set evolve_config_sha256 = p_payload->>'config_sha256'
     where w.id = v_item.id;
  end if;
  insert into public.evolve_stages as s (run_id, work_item_id, project_id, stage, payload)
  values (p_run_id, v_item.id, v_run.project_id, v_stage, p_payload)
  returning s.* into v_row;
  if v_stage = 'learning' then
    -- Candidates only, carrying the exact snapshot and operator-config
    -- identity of this attempt so retrieval can never widen their scope.
    for v_lesson in select value from jsonb_array_elements(p_payload->'artifact'->'lessons')
    loop
      insert into public.evolve_lessons
        (project_id, work_item_id, run_id, lesson_index, lesson,
         source_sha256, config_sha256)
      values (v_run.project_id, v_item.id, p_run_id, v_index, v_lesson,
              p_payload->>'source_sha256', p_payload->>'config_sha256');
      v_index := v_index + 1;
    end loop;
  end if;
  perform private.record_run_event(p_run_id, 'stage_recorded', v_run.phase, v_stage);
  return query select v_row.id, v_row.run_id, v_row.work_item_id, v_row.project_id,
                      v_row.stage, v_row.created_at, false;
end
$$;
revoke all on function public.record_evolve_stage(uuid,uuid,text,jsonb) from public, anon;
grant execute on function public.record_evolve_stage(uuid,uuid,text,jsonb) to authenticated;

-- Ends execution and hands the attempt to a human. The server re-derives every
-- requirement from stored rows: the complete ordered chain, one operator config
-- and one snapshot across all of it, an independent verification whose checks
-- all passed, an audit with no violations, a learning review that decided every
-- proposed lesson, and a registered candidate archive whose digest the later
-- stages all name. The lease is released and the work item becomes
-- awaiting_approval - never succeeded, because no model may approve.
create or replace function public.finish_evolve_run(
  p_run_id uuid, p_lease_token uuid)
returns table(accepted boolean, reason text, work_item_status text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_impl jsonb;
  v_candidate text;
  v_patch text;
  v_config text;
  v_source text;
  v_stages integer;
  v_lessons integer;
  v_passed integer;
  v_result jsonb;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
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
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, v_item.status;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    perform private.record_evolve_learning_unavailable(p_run_id, 'creator_unauthorized');
    return query select false, 'creator_unauthorized'::text, 'failed'::text;
    return;
  end if;
  -- A successful normal finish is exactly what the diagnostic side branch is
  -- not. An attempt that recorded a failure report - or whose analysis the
  -- server recorded as unavailable - is failed evidence, so it can never become
  -- a candidate a human is asked to approve, however complete its stage chain
  -- looks.
  if coalesce(v_run.result ?| array['failure_report','learning_unavailable'], false) then
    return query select false, 'failure_report_recorded'::text, v_item.status;
    return;
  end if;
  if v_run.source_ref is null or v_run.source_commit is null
     or v_run.source_digest is null then
    return query select false, 'source_identity_missing'::text, v_item.status;
    return;
  end if;
  if v_item.pinned_source_ref is null
     or v_run.source_ref <> v_item.pinned_source_ref
     or v_run.source_commit <> v_item.pinned_source_commit then
    return query select false, 'source_identity_conflict'::text, v_item.status;
    return;
  end if;
  -- The complete chain, re-counted from the stored rows rather than trusted
  -- from the worker's phase.
  select count(*) into v_stages from public.evolve_stages s where s.run_id = p_run_id;
  if v_stages <> 7 then
    return query select false, 'stages_incomplete'::text, v_item.status;
    return;
  end if;
  v_source := right(v_run.source_digest, 64);
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id and s.payload->>'source_sha256' <> v_source) then
    return query select false, 'source_digest_mismatch'::text, v_item.status;
    return;
  end if;
  select s.payload->>'config_sha256' into v_config from public.evolve_stages s
   where s.run_id = p_run_id and s.stage = 'requirements';
  if v_config is null or v_item.evolve_config_sha256 is null
     or v_config <> v_item.evolve_config_sha256
     or exists(select 1 from public.evolve_stages s
                where s.run_id = p_run_id and s.payload->>'config_sha256' <> v_config) then
    return query select false, 'config_digest_mismatch'::text, v_item.status;
    return;
  end if;
  select s.payload into v_impl from public.evolve_stages s
   where s.run_id = p_run_id and s.stage = 'implementation';
  v_candidate := v_impl->'artifact'->>'candidate_sha256';
  v_patch := v_impl->'artifact'->>'patch_sha256';
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id
               and s.stage in ('verification','audit','learning','learning_review')
               and s.payload->'artifact'->>'candidate_sha256' is distinct from v_candidate)
  then
    return query select false, 'candidate_digest_mismatch'::text, v_item.status;
    return;
  end if;
  if not exists(select 1 from public.evolve_artifacts a
                 where a.run_id = p_run_id and a.kind = 'candidate'
                   and a.sha256 = v_candidate)
     or not exists(select 1 from public.evolve_artifacts a
                    where a.run_id = p_run_id and a.kind = 'patch' and a.sha256 = v_patch) then
    return query select false, 'artifact_missing'::text, v_item.status;
    return;
  end if;
  -- Exactly one candidate archive per attempt. "Approve this candidate" has to
  -- name one archive, so an attempt that registered a second one is refused
  -- here rather than leaving a human to choose between two review candidates
  -- that the stage chain describes identically.
  if (select count(*) from public.evolve_artifacts a
       where a.run_id = p_run_id and a.kind = 'candidate') <> 1 then
    return query select false, 'candidate_ambiguous'::text, v_item.status;
    return;
  end if;
  -- Verification and audit are re-read, not re-asserted: the record must still
  -- say every check passed, the baseline reproduced, preservation held and no
  -- process violation was found.
  if not exists(select 1 from public.evolve_stages s
                 where s.run_id = p_run_id and s.stage = 'verification'
                   and s.payload->'artifact'->'baseline_reproduced' = 'true'::jsonb
                   and s.payload->'artifact'->'preservation_passed' = 'true'::jsonb
                   and s.payload->'artifact'->>'verification' = 'passed'
                   and not exists(select 1
                       from jsonb_array_elements(s.payload->'artifact'->'checks') c
                      where c.value->'passed' is distinct from 'true'::jsonb)) then
    return query select false, 'verification_incomplete'::text, v_item.status;
    return;
  end if;
  if not exists(select 1 from public.evolve_stages s
                 where s.run_id = p_run_id and s.stage = 'audit'
                   and s.payload->'artifact'->'violations' = '[]'::jsonb) then
    return query select false, 'audit_incomplete'::text, v_item.status;
    return;
  end if;
  if exists(select 1 from public.evolve_stages s
             where s.run_id = p_run_id
               and s.payload->'review'->>'verdict' is distinct from 'pass') then
    return query select false, 'review_incomplete'::text, v_item.status;
    return;
  end if;
  -- Every proposed lesson exists as a candidate and has exactly one decision.
  select count(*) into v_lessons from public.evolve_lessons l where l.run_id = p_run_id;
  if v_lessons <> (select coalesce(jsonb_array_length(s.payload->'artifact'->'lessons'), 0)
                     from public.evolve_stages s
                    where s.run_id = p_run_id and s.stage = 'learning')
     or v_lessons <> (select jsonb_array_length(s.payload->'artifact'->'decisions')
                        from public.evolve_stages s
                       where s.run_id = p_run_id and s.stage = 'learning_review') then
    return query select false, 'learning_review_incomplete'::text, v_item.status;
    return;
  end if;
  select count(*) into v_passed from public.evolve_stages s,
       jsonb_array_elements(s.payload->'artifact'->'decisions') d
   where s.run_id = p_run_id and s.stage = 'learning_review'
     and d.value->>'verdict' = 'pass';

  v_result := jsonb_build_object(
    'summary', jsonb_build_object(
      'kind', 'evolve',
      'candidate_sha256', v_candidate,
      'patch_sha256', v_patch,
      'config_sha256', v_config,
      'source_sha256', v_source,
      'stages_recorded', v_stages,
      'lessons_proposed', v_lessons,
      'lessons_passed', v_passed),
    'findings', '[]'::jsonb);
  -- The same structural validation the analysis result goes through, so the
  -- stored summary cannot carry a path, a URL or an unbounded string either.
  perform private.assert_analysis_result(v_result);
  update public.factory_runs r
     set status = 'awaiting_approval', phase = 'awaiting_approval', result = v_result,
         error_code = null, finished_at = now(), heartbeat_at = now()
   where r.id = p_run_id;
  update public.work_items w set status = 'awaiting_approval', error_code = null
   where w.id = v_item.id;
  -- Execution is over, so the fencing token is gone: there is no lease to
  -- renew and no late worker call that can touch this attempt again.
  delete from private.factory_run_leases l where l.run_id = p_run_id;
  perform private.record_run_event(p_run_id, 'awaiting_approval', 'awaiting_approval',
    format('candidate=%s lessons=%s of %s', left(v_candidate, 12), v_passed, v_lessons));
  return query select true, 'ok'::text, 'awaiting_approval'::text;
end
$$;
revoke all on function public.finish_evolve_run(uuid,uuid) from public, anon;
grant execute on function public.finish_evolve_run(uuid,uuid) to authenticated;

-- The terminal diagnostic report of an attempt that is about to fail. It is
-- not a stage: there is no order to admit it into, it may follow a rejected
-- review or no stage at all, it names no candidate archive, and nothing can be
-- recorded on top of it. The worker calls this while it still holds the
-- authority the report describes - a live lease, a current registration and a
-- requester who may still run the work - and then calls public.fail_evolve_run,
-- whose signature and behaviour are unchanged and which leaves this report in
-- place.
--
-- Exactly one report per attempt, stored in the attempt's own result. A
-- repetition of the same report is a replay; a different one is refused,
-- because the evidence a human reads about a failure must not be rewritten
-- afterwards. The lessons a reviewed report carries are materialized as
-- diagnostic rows that are rejected on arrival - a failed attempt does not
-- qualify for promotion, so nothing here can become memory - while the
-- decisions its reviewer actually made stay in the report for a project
-- administrator to inspect.
--
-- After this, public.record_evolve_stage and public.finish_evolve_run refuse
-- the attempt outright and only a heartbeat, a failure and a cancellation are
-- left. Registering an artifact deliberately stays open while the lease is
-- live, because a worker that is shutting down may still have a trace or a
-- receipt to store, and immutable bytes promote nothing on their own: without
-- a finish the attempt never reaches awaiting_approval, and
-- public.decide_evolve_work refuses an attempt that holds a failure report.
create or replace function public.record_evolve_failure_report(
  p_run_id uuid, p_lease_token uuid, p_report jsonb)
returns table(accepted boolean, reason text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_item_id uuid;
  v_run_owner uuid;
  v_token uuid;
  v_existing jsonb;
  v_source text;
  v_config text;
  v_lesson jsonb;
  v_index integer := 0;
  v_failed integer;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_report is null then raise exception 'a failure report is required'; end if;
  -- The one lock order: resolve the work item id without a lock, lock the work
  -- item, then the run, and judge every predicate on the locked rows and the
  -- clock read after them.
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
    raise exception 'run not found';
  end if;
  select l.lease_token into v_token from private.factory_run_leases l where l.run_id = p_run_id;
  -- The same fence every other worker transition passes, reported rather than
  -- raised as public.fail_evolve_run reports it: a worker whose authority is
  -- gone is told so and stops, instead of retrying a call it can never make.
  if not private.is_project_worker(v_run.project_id) then
    return query select false, 'worker_not_registered'::text;
    return;
  end if;
  -- A cancellation stops work. It is not a request for more analysis, and a
  -- report arriving afterwards does not reauthorize the attempt it cancelled.
  if v_item.cancel_requested_at is not null then
    return query select false, 'cancelled'::text;
    return;
  end if;
  if v_run.status <> 'running' or v_item.status <> 'running' then
    return query select false, 'not_running'::text;
    return;
  end if;
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    perform private.record_evolve_learning_unavailable(p_run_id, 'creator_unauthorized');
    return query select false, 'creator_unauthorized'::text;
    return;
  end if;
  -- Immutable: an exact repetition is the replay of a call whose answer was
  -- lost, anything else is a second and conflicting account of one failure.
  v_existing := v_run.result->'failure_report';
  if v_existing is not null then
    if v_existing <> p_report then
      return query select false, 'report_conflict'::text;
      return;
    end if;
    return query select true, 'replayed'::text;
    return;
  end if;
  perform private.assert_evolve_failure_report(p_run_id, v_item.id, p_report);
  -- Merged rather than assigned: evidence this attempt already stored is
  -- retained beside the report. The status stays running and the error code is
  -- untouched, because recording evidence is not the failure itself - the
  -- worker's public.fail_evolve_run call is, and its code stays authoritative.
  update public.factory_runs r
     set result = coalesce(r.result, '{}'::jsonb)
                  || jsonb_build_object('failure_report', p_report),
         heartbeat_at = now()
   where r.id = p_run_id;
  -- The diagnostic lessons, carrying the same project, attempt, snapshot and
  -- operator-config identity as the report, rejected on arrival and - by the
  -- state check on the table - unable to be anything else. A report with no
  -- snapshot has no admissible lesson and the validator above has already
  -- refused one.
  v_source := p_report->>'source_sha256';
  v_config := p_report->>'config_sha256';
  if v_source is not null then
    for v_lesson in select value from jsonb_array_elements(p_report->'lessons') loop
      insert into public.evolve_lessons
        (project_id, work_item_id, run_id, lesson_index, origin, status, lesson,
         source_sha256, config_sha256)
      values (v_run.project_id, v_item.id, p_run_id, v_index, 'failure_report', 'rejected',
              v_lesson, v_source, v_config);
      v_index := v_index + 1;
    end loop;
  end if;
  -- Event detail is derived from the validated report, never copied from a
  -- worker string.
  select count(*) into v_failed from jsonb_array_elements(p_report->'checks') c
   where c.value->'passed' = 'false'::jsonb;
  perform private.record_run_event(p_run_id, 'failure_report', v_run.phase,
    format('%s at %s learning=%s/%s failed_checks=%s lessons=%s',
           p_report->>'error_code', p_report->>'failed_stage',
           p_report->>'learning_status', p_report->>'learning_reason', v_failed, v_index));
  return query select true, 'ok'::text;
end
$$;
revoke all on function public.record_evolve_failure_report(uuid,uuid,jsonb)
  from public, anon;
grant execute on function public.record_evolve_failure_report(uuid,uuid,jsonb)
  to authenticated;

-- Records a failed attempt behind the same fence. A rejected review, a failed
-- or unreproduced verification, an invalid baseline, an empty change set and a
-- rejected process audit are judgements, not infrastructure faults: they end
-- the work item terminally instead of consuming another attempt. Any other
-- bounded code keeps the existing retry budget.
--
-- The UPDATE below does not touch result, so a failure report this attempt
-- recorded through public.record_evolve_failure_report survives the failure it
-- describes - which is the only reason that report exists.
create or replace function public.fail_evolve_run(
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
  v_terminal boolean;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if v_code !~ '^[a-z][a-z0-9_]{2,47}$' then
    raise exception 'error code must be 3-48 characters of a-z 0-9 _';
  end if;
  v_terminal := v_code in ('review_rejected','verification_failed','invalid_baseline',
                           'not_reproduced','no_change','process_rejected');
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.* into v_item from public.work_items w where w.id = v_item_id for update;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  if v_run.id is null or v_run.worker_user_id <> v_actor or v_item.kind <> 'evolve' then
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
     or v_run.lease_expires_at <= clock_timestamp() then
    return query select false, 'lease_lost'::text, v_item.status, false;
    return;
  end if;
  if not private.creator_may_run(v_run.project_id, v_item.created_by) then
    perform private.fence_unauthorized_creator(v_item.id, p_run_id);
    perform private.record_evolve_learning_unavailable(p_run_id, 'creator_unauthorized');
    return query select false, 'creator_unauthorized'::text, 'failed'::text, false;
    return;
  end if;
  update public.factory_runs r
     set status = 'failed', error_code = v_code, finished_at = now(), heartbeat_at = now()
   where r.id = p_run_id;
  delete from private.factory_run_leases l where l.run_id = p_run_id;
  -- Whatever this attempt proposed is dead; nothing it extracted can become
  -- memory later.
  perform private.reject_candidate_lessons(p_run_id);
  perform private.record_run_event(p_run_id, 'failed', v_run.phase, v_code);
  if v_terminal then
    update public.work_items w set status = 'failed', error_code = v_code
     where w.id = v_item.id and w.status not in ('succeeded','failed','cancelled');
    perform private.record_run_event(p_run_id, 'rejected', null, v_code);
    return query select true, 'ok'::text, 'failed'::text, false;
    return;
  end if;
  v_status := private.settle_work_item_after_attempt(v_item.id, p_run_id, v_code);
  return query select true, 'ok'::text, v_status, v_status = 'queued';
end
$$;
revoke all on function public.fail_evolve_run(uuid,uuid,text) from public, anon;
grant execute on function public.fail_evolve_run(uuid,uuid,text) to authenticated;

-- The human decision. A current project admin or owner, naming the exact
-- attempt and the exact candidate digest it produced, approves or rejects.
-- Approval requires that both the authority that requested the work and the
-- worker identity that produced it still hold it, so a revoked request or a
-- revoked worker can never be reauthorized by an approval, and an approval of
-- an earlier attempt can never cover a later one. Nothing is published
-- anywhere: a succeeded Evolve work item is an approved review candidate.
create or replace function public.decide_evolve_work(
  p_work_item_id uuid, p_run_id uuid, p_candidate_sha256 text, p_approve boolean)
returns table(work_item_id uuid, status text, run_id uuid, candidate_sha256 text,
              approved boolean, lessons_activated integer, reason text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_item public.work_items;
  v_run public.factory_runs;
  v_latest uuid;
  v_candidate text := lower(btrim(coalesce(p_candidate_sha256, '')));
  v_recorded text;
  v_activated integer := 0;
  v_decision jsonb;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_approve is null then raise exception 'a decision is required'; end if;
  select w.* into v_item from public.work_items w where w.id = p_work_item_id for update;
  -- An unauthorized caller is told the same thing as for a missing row, so
  -- work item ids in other projects are not probeable.
  if v_item.id is null or v_item.kind <> 'evolve'
     or not private.is_project_admin(v_item.project_id) then
    raise exception 'work item not found';
  end if;
  select r.* into v_run from public.factory_runs r where r.id = p_run_id for update;
  select r.id into v_latest from public.factory_runs r
   where r.work_item_id = v_item.id order by r.attempt desc limit 1;
  if v_run.id is null or v_run.work_item_id <> v_item.id or v_run.id <> v_latest then
    raise exception 'that attempt is not the candidate awaiting approval';
  end if;
  select s.payload->'artifact'->>'candidate_sha256' into v_recorded
    from public.evolve_stages s where s.run_id = v_run.id and s.stage = 'implementation';
  if v_recorded is null or v_candidate <> v_recorded then
    raise exception 'that candidate digest is not the one this attempt produced';
  end if;
  -- The decision names one archive and the attempt must hold exactly that one.
  -- finish_evolve_run already refuses an ambiguous attempt; this re-check is
  -- what makes the approval itself artifact-exact rather than attempt-exact.
  if (select count(*) from public.evolve_artifacts a
       where a.run_id = v_run.id and a.kind = 'candidate') <> 1
     or not exists(select 1 from public.evolve_artifacts a
                    where a.run_id = v_run.id and a.kind = 'candidate'
                      and a.sha256 = v_candidate) then
    raise exception 'that candidate digest is not the one this attempt produced';
  end if;
  -- Idempotent for the same decision on the same candidate; a changed or stale
  -- decision is refused rather than silently applied.
  if v_item.status in ('succeeded','failed','cancelled') then
    if v_item.status = 'succeeded' and p_approve and v_item.decided_at is not null then
      select count(*) into v_activated from public.evolve_lessons l
       where l.run_id = v_run.id and l.status = 'approved';
      return query select v_item.id, v_item.status, v_run.id, v_recorded, true,
                          v_activated, 'already_decided'::text;
      return;
    end if;
    if v_item.status = 'failed' and not p_approve
       and v_item.error_code = 'approval_rejected' then
      return query select v_item.id, v_item.status, v_run.id, v_recorded, false, 0,
                          'already_decided'::text;
      return;
    end if;
    raise exception 'this work item is no longer awaiting approval';
  end if;
  if v_item.status <> 'awaiting_approval' or v_run.status <> 'awaiting_approval' then
    raise exception 'that attempt is not the candidate awaiting approval';
  end if;
  -- A diagnostic side branch is terminal and un-promotable. An attempt that
  -- recorded a failure report, or whose analysis the server recorded as
  -- unavailable, is failed evidence: it is not the candidate a human approves,
  -- whatever state another path left it in.
  if coalesce(v_run.result ?| array['failure_report','learning_unavailable'], false) then
    raise exception 'that attempt is not the candidate awaiting approval';
  end if;
  -- Approval is not a second authorization path. If the requester lost their
  -- editing role, the work is fenced here exactly as a worker transition would
  -- fence it, and no candidate is approved.
  if not private.creator_may_run(v_item.project_id, v_item.created_by) then
    perform private.fence_running_runs(v_item.id, 'creator_unauthorized',
      'the requester no longer has an editing role on this project');
    update public.work_items w set status = 'failed', error_code = 'creator_unauthorized'
     where w.id = v_item.id;
    return query select v_item.id, 'failed'::text, v_run.id, v_recorded, false, 0,
                        'creator_unauthorized'::text;
    return;
  end if;
  if not private.run_worker_still_authorized(v_run.id) then
    perform private.fence_running_runs(v_item.id, 'worker_revoked',
      'the worker identity that produced this candidate is no longer authorized');
    update public.work_items w set status = 'failed', error_code = 'worker_revoked'
     where w.id = v_item.id;
    return query select v_item.id, 'failed'::text, v_run.id, v_recorded, false, 0,
                        'worker_unauthorized'::text;
    return;
  end if;
  if not p_approve then
    update public.factory_runs r
       set status = 'failed', error_code = 'approval_rejected'
     where r.id = v_run.id;
    update public.work_items w
       set status = 'failed', error_code = 'approval_rejected',
           decided_at = now(), decided_by = v_actor
     where w.id = v_item.id;
    perform private.reject_candidate_lessons(v_run.id);
    perform private.record_run_event(v_run.id, 'rejected', null,
      'rejected by an authorized project administrator');
    return query select v_item.id, 'failed'::text, v_run.id, v_recorded, false, 0,
                        'ok'::text;
    return;
  end if;
  -- Only the lessons this attempt's learning review passed become memory, and
  -- only now, and only lessons a learning stage proposed: a diagnostic lesson
  -- of a failed analysis is not in the candidate state this activates, and the
  -- table forbids it from ever being. Every other candidate of the attempt is
  -- buried in the same statement pair.
  for v_decision in
    select d.value from public.evolve_stages s,
         jsonb_array_elements(s.payload->'artifact'->'decisions') d
     where s.run_id = v_run.id and s.stage = 'learning_review'
  loop
    if (v_decision->>'verdict') = 'pass' then
      update public.evolve_lessons l set status = 'approved'
       where l.run_id = v_run.id and l.lesson_index = (v_decision->>'index')::integer
         and l.origin = 'learning' and l.status = 'candidate';
      if found then v_activated := v_activated + 1; end if;
    end if;
  end loop;
  perform private.reject_candidate_lessons(v_run.id);
  update public.factory_runs r set status = 'succeeded', phase = 'done', error_code = null
   where r.id = v_run.id;
  update public.work_items w
     set status = 'succeeded', error_code = null, decided_at = now(), decided_by = v_actor
   where w.id = v_item.id;
  perform private.record_run_event(v_run.id, 'approved', 'done',
    format('candidate=%s lessons_activated=%s', left(v_recorded, 12), v_activated));
  return query select v_item.id, 'succeeded'::text, v_run.id, v_recorded, true,
                      v_activated, 'ok'::text;
end
$$;
revoke all on function public.decide_evolve_work(uuid,uuid,text,boolean) from public, anon;
grant execute on function public.decide_evolve_work(uuid,uuid,text,boolean) to authenticated;

-- Withdraws an activated lesson. A current project admin can always revoke;
-- the lesson leaves the approved set immediately, which is what a worker's
-- retrieval reads, and nothing here can reinstate it.
create or replace function public.revoke_evolve_lesson(p_lesson_id uuid)
returns table(id uuid, status text, already_revoked boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_lesson public.evolve_lessons;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  select l.* into v_lesson from public.evolve_lessons l where l.id = p_lesson_id for update;
  if v_lesson.id is null or not private.is_project_admin(v_lesson.project_id) then
    raise exception 'lesson not found';
  end if;
  if v_lesson.status = 'revoked' then
    return query select v_lesson.id, v_lesson.status, true;
    return;
  end if;
  update public.evolve_lessons l
     set status = 'revoked', revoked_at = now(), revoked_by = v_actor
   where l.id = p_lesson_id;
  return query select v_lesson.id, 'revoked'::text, false;
end
$$;
revoke all on function public.revoke_evolve_lesson(uuid) from public, anon;
grant execute on function public.revoke_evolve_lesson(uuid) to authenticated;

commit;
