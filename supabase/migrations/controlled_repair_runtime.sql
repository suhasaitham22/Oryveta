-- Controlled design-partner repair runtime: operator-enrolled repair policies,
-- a second task kind on the existing durable queue, and the bounded verified
-- patch result a registered coding worker may publish.
--
-- Apply AFTER supabase/schema.sql,
-- supabase/migrations/private_chats_and_explicit_sharing.sql,
-- supabase/migrations/projects_and_project_membership.sql,
-- supabase/migrations/durable_factory_runtime.sql and
-- supabase/migrations/retained_attribution_and_lease_clock.sql, in that order.
-- A fresh deployment reaches this state by applying all six in order; an
-- existing installation reaches it by applying this file alone. This file is
-- repeatable: every object is created with IF NOT EXISTS, replaced in place, or
-- dropped by name and re-added. Do not assume the earlier initial-setup files
-- are repeatable.
--
-- Dedicated Oryveta project only. It is additive: it creates new tables,
-- columns, policies, triggers and RPCs, and it re-owns three generated CHECK
-- constraints plus four existing functions so a second task kind can exist.
-- It changes no existing RPC argument list or return shape, relaxes no
-- authorization, pinning or fencing check, and adds no write privilege for any
-- client role.
--
-- What this runtime deliberately is, and is not:
--   * Code execution is NOT a capability any existing analysis worker gains.
--     It is bound by a public.project_repair_policies row that an owner/admin
--     enrols, naming ONE project, ONE already-designated and registered worker
--     Auth identity, ONE public GitHub URL and 40-hex commit, and ONE operator
--     configuration SHA-256. The policy's identity, source and configuration
--     are immutable; a change means a new policy.
--   * The policy row installs nothing and grants no inference budget. It
--     records that an operator reviewed a configuration and designated a
--     worker for one frozen snapshot.
--   * There is NO second queue. Repair work is public.work_items of kind
--     'repository_repair' with attempts on public.factory_runs, events on
--     public.factory_run_events and fencing tokens in
--     private.factory_run_leases, exactly as analysis work is. One metadata
--     authority, one reclaim path, one cancellation path, one revocation path.
--   * The commands, expected cases, file/model/runner grants and budgets stay
--     in the operator's local configuration file. Nothing in this schema can
--     name a command, a host path, a model endpoint or a container image. The
--     only client-supplied free text is a bounded human goal, which is shared
--     with the project by the act of submitting it.
--   * 'succeeded' means a worker computed a candidate that passed the
--     operator's own checks and is READY FOR REVIEW. It is not an approval, a
--     merge, a deployment or a remote attestation. The registered worker is a
--     trusted producer; the JSON validation below bounds what it may persist,
--     and nothing more.
--   * A repair attempt may be fenced at any point - cancellation, policy
--     revocation, worker revocation, loss of the submitter's editing role,
--     lease expiry or a stale token - and a fenced attempt can never publish a
--     result or a misleading success event.
--   * Offboarding is a lifecycle, not a deletion puzzle. Withdrawing an
--     enrollment, revoking the worker's registration, stripping its service
--     designation and deleting its Auth account all converge on one outcome:
--     the frozen record of what was approved is retained, nothing can admit or
--     claim work under it any more, and the unfinished work it leaves behind
--     is settled terminally with a reason instead of queued forever.
--   * Admission re-derives the whole authority chain, not just the enrollment
--     row. A new goal is admitted only while the policy is enabled AND its
--     bound identity still holds an enabled registration for the project AND
--     is still a designated service principal - the same conjunction the claim
--     path requires - and both rows are held under share locks until the work
--     item is inserted, so a concurrent revocation either settles the new item
--     or prevents it. Work nobody may run is never admitted or left queued.
--
-- Lock order, one rule for the whole runtime. Any transaction that needs more
-- than one of these rows takes them in this order and never in another:
--
--     public.project_workers  ->  public.project_repair_policies
--                             ->  public.work_items
--                             ->  public.factory_runs
--
-- The new policy row is inserted between the registration and the work item,
-- so the existing work-item-then-run order inside the runtime is preserved
-- unchanged and the analysis paths, which never touch a policy, keep exactly
-- the ordering they already had. Every repair RPC resolves ids with unlocked
-- reads first and then takes the locks in that order, which is why a heartbeat
-- that refreshes last_seen_at cannot deadlock against a policy revocation.
-- Deadlines and every comparison against a deadline read clock_timestamp()
-- after the locks are held, as retained_attribution_and_lease_clock.sql
-- established; timestamps that record when a transaction happened keep now().

begin;

-- ---------------------------------------------------------------------------
-- 1. Repair policies: the enrollment record that binds one project, one
--    worker identity, one frozen source snapshot and one reviewed operator
--    configuration.
-- ---------------------------------------------------------------------------

-- source_url/owner/repo are copied from the project's saved source at
-- enrollment and frozen here, so editing the project's source URL afterwards
-- can never redirect an enrolled policy. created_by and revoked_by are
-- attribution, never authority: authority is re-derived from the caller's
-- current project role and from the worker's designation on every call, which
-- is why both may become NULL when an account is deleted (the lesson of
-- retained_attribution_and_lease_clock.sql).
--
-- The worker identity is recorded twice, for exactly the reason that file
-- separated a retained record from its actor:
--   * worker_identity is the frozen enrollment. It is the Auth id an operator
--     designated for this snapshot, it has no foreign key, it never changes,
--     and it outlives the account, so what was approved stays readable after
--     an offboarding. It is evidence and it carries NO authority: nothing
--     below authorizes anything from it.
--   * worker_user_id is the LIVE reference every authorization check reads. It
--     is CLEARED rather than cascaded when the account is deleted, the
--     enrollment is withdrawn and its unfinished work settled in the same
--     statement (private.settle_repair_policy_after_identity_loss below), and
--     a NULL live identity is a refusal everywhere, never a wildcard.
-- Deleting a worker Auth account therefore succeeds and leaves the enrollment
-- and the repair history behind, instead of being refused by a human-created
-- work item the account never owned. Deleting a policy on its own while work
-- items still name it stays refused, by work_items_repair_policy_id_fkey.
create table if not exists public.project_repair_policies(
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  worker_identity uuid not null,
  worker_user_id uuid references auth.users(id) on delete set null,
  label text not null check(label ~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{1,59}$'),
  enabled boolean not null default true,
  source_url text not null check(char_length(source_url) <= 500),
  source_owner text not null check(source_owner ~ '^[A-Za-z0-9_.-]{1,100}$'),
  source_repo text not null check(source_repo ~ '^[A-Za-z0-9_.-]{1,100}$'),
  source_commit text not null check(source_commit ~ '^[0-9a-f]{40}$'),
  configuration_sha256 text not null check(configuration_sha256 ~ '^[0-9a-f]{64}$'),
  -- The last authenticated, authorized contact from the bound worker. It is
  -- evidence that a credential still polls, NOT capacity, availability or an
  -- uptime promise, and no scheduling decision reads it.
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  -- The live reference is the frozen one until it is cleared. It can never
  -- name an account the enrollment was not reviewed for.
  constraint project_repair_policies_worker_identity_check
    check(worker_user_id is null or worker_user_id = worker_identity),
  constraint project_repair_policies_revocation_state_check
    check((enabled and revoked_at is null) or (not enabled and revoked_at is not null)),
  constraint project_repair_policies_revocation_attribution_check
    check(revoked_by is null or revoked_at is not null)
);

-- An installation created by an earlier application of this file carries one
-- NOT NULL, ON DELETE CASCADE worker column instead of the two above, so the
-- split and the clearing reference are established here as well; both paths
-- converge on the same definition.
alter table public.project_repair_policies
  add column if not exists worker_identity uuid;
update public.project_repair_policies k
   set worker_identity = k.worker_user_id
 where k.worker_identity is null;
alter table public.project_repair_policies
  alter column worker_identity set not null;
alter table public.project_repair_policies
  alter column worker_user_id drop not null;
alter table public.project_repair_policies
  drop constraint if exists project_repair_policies_worker_identity_check;
alter table public.project_repair_policies
  add constraint project_repair_policies_worker_identity_check
  check(worker_user_id is null or worker_user_id = worker_identity);

do $repair_policy_worker_reference$
declare
  v_delete_action "char";
begin
  select c.confdeltype into v_delete_action
    from pg_catalog.pg_constraint c
   where c.conrelid = 'public.project_repair_policies'::regclass
     and c.conname = 'project_repair_policies_worker_user_id_fkey';
  -- 'n' is SET NULL. A cascade here deletes the enrollment and is then refused
  -- by the human-created work items that still name it, which is exactly the
  -- offboarding deadlock this split removes.
  if v_delete_action is distinct from 'n' then
    alter table public.project_repair_policies
      drop constraint if exists project_repair_policies_worker_user_id_fkey;
    alter table public.project_repair_policies
      add constraint project_repair_policies_worker_user_id_fkey
      foreign key (worker_user_id) references auth.users(id) on delete set null;
  end if;
end
$repair_policy_worker_reference$;

do $assert_identity_clears$
begin
  if not exists(
    select 1 from pg_catalog.pg_constraint c
     where c.conrelid = 'public.project_repair_policies'::regclass
       and c.contype = 'f' and c.confrelid = 'auth.users'::regclass
       and c.confdeltype = 'n'
       and (select a.attnum from pg_catalog.pg_attribute a
             where a.attrelid = c.conrelid and a.attname = 'worker_user_id')
           = any(c.conkey)) then
    raise exception 'the live worker reference on public.project_repair_policies must be '
      'cleared rather than cascaded when an account is deleted; drop that foreign key by '
      'name and re-apply this file';
  end if;
end
$assert_identity_clears$;

create index if not exists project_repair_policies_project_idx
  on public.project_repair_policies(project_id, created_at desc);
-- Lookups by live identity: the revocation path asks which enrollments an
-- account still has authority over, and a cleared reference has none.
create index if not exists project_repair_policies_worker_idx
  on public.project_repair_policies(worker_user_id, project_id) where enabled;
-- One live enrollment per (worker, commit, configuration). A second identical
-- one would be an operator mistake that silently doubles a worker's claim
-- surface; a genuinely different commit or configuration is a new policy. The
-- frozen identity carries this uniqueness, so it keeps meaning one enrollment
-- per designated identity even once a live reference has been cleared. It is
-- dropped by name first because an installation from an earlier application of
-- this file indexes the live column here.
drop index if exists public.project_repair_policies_identity_idx;
create unique index if not exists project_repair_policies_identity_idx
  on public.project_repair_policies(project_id, worker_identity, source_commit,
                                    configuration_sha256)
  where enabled;

-- A policy is operational configuration with a frozen identity. Updates are
-- restricted to the three things that may legitimately change after
-- enrollment: revocation, the cleared attribution of a deleted account, and
-- the worker's last contact time. Everything else is immutable here rather
-- than only in the RPCs, so a mistaken direct UPDATE by the table owner cannot
-- silently redirect an approved policy to another commit or configuration.
create or replace function private.guard_repair_policy_immutable()
returns trigger language plpgsql set search_path='' as $$
begin
  if new.id <> old.id or new.project_id <> old.project_id
     or new.worker_identity <> old.worker_identity or new.label <> old.label
     or new.source_url <> old.source_url or new.source_owner <> old.source_owner
     or new.source_repo <> old.source_repo or new.source_commit <> old.source_commit
     or new.configuration_sha256 <> old.configuration_sha256
     or new.created_at <> old.created_at then
    raise exception 'a repair policy identity, source and configuration are immutable; '
                    'enroll a new policy instead';
  end if;
  -- The live worker reference may only be cleared, which is what the
  -- auth.users ON DELETE SET NULL path does. It may never be redirected to
  -- another account, and it may never come back: an identity that was
  -- offboarded is re-enrolled as a new policy, reviewed again.
  if new.worker_user_id is not null
     and new.worker_user_id is distinct from old.worker_user_id then
    raise exception 'a repair policy keeps the worker identity it was enrolled for; '
                    'enroll a new policy instead';
  end if;
  -- Attribution may only be cleared, which is what the auth.users ON DELETE
  -- SET NULL path does. It may never be moved to another account.
  if new.created_by is not null and new.created_by is distinct from old.created_by then
    raise exception 'a repair policy keeps the account that enrolled it';
  end if;
  if old.revoked_by is not null and new.revoked_by is not null
     and new.revoked_by <> old.revoked_by then
    raise exception 'a repair policy keeps the account that revoked it';
  end if;
  if not old.enabled and new.enabled then
    raise exception 'a revoked repair policy cannot be re-enabled; enroll a new policy instead';
  end if;
  if old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at then
    raise exception 'a repair policy revocation timestamp is immutable';
  end if;
  -- Worker contact only moves forward, so a stale or backdated write cannot
  -- make an idle worker look like it just polled.
  if new.last_seen_at is distinct from old.last_seen_at
     and (new.last_seen_at is null
          or (old.last_seen_at is not null and new.last_seen_at < old.last_seen_at)) then
    raise exception 'worker contact time only moves forward';
  end if;
  return new;
end
$$;
revoke all on function private.guard_repair_policy_immutable()
  from public, anon, authenticated;
drop trigger if exists on_repair_policy_updated on public.project_repair_policies;
create trigger on_repair_policy_updated
before update on public.project_repair_policies
for each row execute function private.guard_repair_policy_immutable();

-- Reads only, for current project readers and for the bound worker identity
-- itself, which needs to confirm the scope it was started with. There is no
-- write policy because no client role holds a write privilege: enrollment and
-- revocation go exclusively through the two RPCs below.
alter table public.project_repair_policies enable row level security;

drop policy if exists project_repair_policies_select_authorized
  on public.project_repair_policies;
create policy project_repair_policies_select_authorized
on public.project_repair_policies
for select to authenticated
using((select private.can_read_project(project_id))
   or worker_user_id = (select auth.uid()));

revoke all on public.project_repair_policies from anon, authenticated;
grant select on public.project_repair_policies to authenticated;

-- ---------------------------------------------------------------------------
-- 2. A second task kind on the existing queue.
-- ---------------------------------------------------------------------------

-- durable_factory_runtime.sql wrote these three predicates inline, so
-- PostgreSQL generated their names deterministically from fixed table
-- definitions. They are dropped by the generated name, re-added under an
-- explicit name, and an assertion below fails loudly if any deployment still
-- carries an old restrictive predicate under some other name.
alter table public.work_items drop constraint if exists work_items_kind_check;
alter table public.work_items drop constraint if exists work_items_kind_allowed_check;
alter table public.work_items add constraint work_items_kind_allowed_check
  check(kind in ('repository_analysis','repository_repair'));

alter table public.factory_runs drop constraint if exists factory_runs_phase_check;
alter table public.factory_runs drop constraint if exists factory_runs_phase_allowed_check;
alter table public.factory_runs add constraint factory_runs_phase_allowed_check
  check(phase in ('claimed','fetching_source','analyzing','repairing','verifying',
                  'recording_result','done'));

alter table public.factory_run_events
  drop constraint if exists factory_run_events_phase_check;
alter table public.factory_run_events
  drop constraint if exists factory_run_events_phase_allowed_check;
alter table public.factory_run_events add constraint factory_run_events_phase_allowed_check
  check(phase is null or phase in ('claimed','fetching_source','analyzing','repairing',
                                   'verifying','recording_result','done'));

-- The frozen enrollment this work item was admitted under, and the bounded
-- human goal it was admitted with. The reference is DEFERRABLE INITIALLY
-- DEFERRED NO ACTION rather than RESTRICT on purpose: deleting a policy that
-- still has work history must stay refused, while deleting a whole project -
-- where the work items and the policies both cascade away inside one statement
-- - must still succeed. A RESTRICT reference is checked immediately and would
-- have blocked that cleanup. Deleting the worker Auth account an enrollment
-- names is the third case, and it is why that enrollment clears a live
-- reference instead of cascading: a worker's offboarding cannot remove a
-- human's work item, so a cascading policy would leave this reference dangling
-- and the account deletion would be refused. The separately owned protection
-- of a worker registration that an attempt still names (factory_runs' RESTRICT
-- reference) is untouched.
alter table public.work_items
  add column if not exists repair_policy_id uuid,
  add column if not exists goal text;

do $repair_policy_reference$
begin
  if not exists(select 1 from pg_catalog.pg_constraint c
                 where c.conrelid = 'public.work_items'::regclass
                   and c.conname = 'work_items_repair_policy_id_fkey') then
    alter table public.work_items add constraint work_items_repair_policy_id_fkey
      foreign key (repair_policy_id)
      references public.project_repair_policies(id)
      deferrable initially deferred;
  end if;
end
$repair_policy_reference$;

-- A goal is bounded human text, measured in bytes because that is the limit
-- the worker and the UI agree on, stored already trimmed, and free of control
-- characters other than the newline and tab a multi-line description needs.
alter table public.work_items drop constraint if exists work_items_goal_shape_check;
alter table public.work_items add constraint work_items_goal_shape_check
  check(goal is null or (octet_length(goal) between 1 and 4096
        and btrim(goal) = goal
        and translate(goal, E'\n\t', '') !~ '[[:cntrl:]]'));

-- Kind decides which fields a row must and must not carry. A repair row is
-- pinned to its approved commit at admission, unlike an analysis row whose pin
-- is resolved by its first attempt, so the pin is required here from the start.
alter table public.work_items drop constraint if exists work_items_kind_fields_check;
alter table public.work_items add constraint work_items_kind_fields_check
  check((kind = 'repository_analysis' and repair_policy_id is null and goal is null)
     or (kind = 'repository_repair' and repair_policy_id is not null and goal is not null
         and pinned_source_ref is not null and pinned_source_commit is not null));

-- Supports the repair claim scan and the revocation settlement without
-- touching another policy's or another project's rows.
create index if not exists work_items_repair_claimable_idx
  on public.work_items(repair_policy_id, created_at, id)
  where kind = 'repository_repair' and status = 'queued' and cancel_requested_at is null;
create index if not exists work_items_repair_policy_idx
  on public.work_items(repair_policy_id, created_at desc)
  where kind = 'repository_repair';

do $assert_kinds_widened$
declare
  v_target record;
  v_survivor text;
begin
  for v_target in
    select *
      from (values
        ('public.work_items', 'kind', '%repository_repair%'),
        ('public.factory_runs', 'phase', '%repairing%'),
        ('public.factory_run_events', 'phase', '%repairing%')
      ) as t(relation, column_name, requires)
  loop
    select c.conname into v_survivor
      from pg_catalog.pg_constraint c
     where c.conrelid = v_target.relation::regclass
       and c.contype = 'c'
       and (select a.attnum from pg_catalog.pg_attribute a
             where a.attrelid = c.conrelid and a.attname = v_target.column_name)
           = any(c.conkey)
       and pg_catalog.pg_get_constraintdef(c.oid) not like v_target.requires
     limit 1;
    if v_survivor is not null then
      raise exception 'check constraint % on % still refuses the repair task kind; drop '
        'that constraint by name and re-apply this file', v_survivor, v_target.relation;
    end if;
  end loop;
end
$assert_kinds_widened$;

-- ---------------------------------------------------------------------------
-- 3. Validation of the two payloads a repair worker may write.
-- ---------------------------------------------------------------------------

-- A repair checkpoint is durable numeric progress and nothing else: a fixed
-- step enum, bounded non-negative counters, the two hashes that identify what
-- is being worked on, and one boolean. There is no key a prompt, a tool
-- argument, a host path, an upstream error message or a credential could be
-- written into, and an unknown key is refused rather than ignored.
create or replace function private.assert_repair_checkpoint(p_checkpoint jsonb)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_key text;
  v_child jsonb;
  v_kind text;
  v_value numeric;
  v_limit numeric;
begin
  if jsonb_typeof(p_checkpoint) <> 'object' then
    raise exception 'checkpoint must be a JSON object';
  end if;
  if pg_column_size(p_checkpoint) > 4096 then
    raise exception 'checkpoint exceeds 4096 bytes';
  end if;
  for v_key, v_child in select key, value from jsonb_each(p_checkpoint) loop
    v_kind := jsonb_typeof(v_child);
    if v_key = 'step' then
      -- The five steps the repair worker derives from its own supervision
      -- state. It is deliberately not the coding runtime's internal phase
      -- list: a step the worker cannot produce is a bug, not progress to
      -- display, and the model-loop detail stays in the private receipt.
      if v_kind <> 'string' or (v_child #>> '{}') not in
         ('fetching_source','snapshot_ready','repairing','verifying','recording_result') then
        raise exception 'checkpoint step is not a known repair step';
      end if;
    elsif v_key in ('turns','tool_calls','tokens_observed','unsettled_token_reservation',
                    'elapsed_seconds','archive_bytes','archive_entries') then
      if v_kind <> 'number' then
        raise exception 'checkpoint field % must be a number', v_key;
      end if;
      v_value := (v_child #>> '{}')::numeric;
      v_limit := case v_key
                   when 'turns' then 50
                   when 'tool_calls' then 100
                   when 'tokens_observed' then 500000
                   when 'unsettled_token_reservation' then 500000
                   when 'elapsed_seconds' then 86400
                   when 'archive_bytes' then 1073741824
                   else 1000000 end;
      if v_value < 0 or v_value > v_limit then
        raise exception 'checkpoint field % must be between 0 and %', v_key, v_limit;
      end if;
      if v_key <> 'elapsed_seconds' and v_value <> trunc(v_value) then
        raise exception 'checkpoint field % must be a whole number', v_key;
      end if;
    elsif v_key = 'source_commit' then
      if v_kind <> 'string' or (v_child #>> '{}') !~ '^[0-9a-f]{40}$' then
        raise exception 'checkpoint source_commit must be a 40 character hexadecimal SHA';
      end if;
    elsif v_key = 'configuration_sha256' then
      if v_kind <> 'string' or (v_child #>> '{}') !~ '^[0-9a-f]{64}$' then
        raise exception 'checkpoint configuration_sha256 must be 64 hexadecimal characters';
      end if;
    elsif v_key = 'source_pinned' then
      if v_kind <> 'boolean' then
        raise exception 'checkpoint source_pinned must be a boolean';
      end if;
    else
      raise exception 'checkpoint field % is not part of the repair progress contract', v_key;
    end if;
  end loop;
end
$$;
revoke all on function private.assert_repair_checkpoint(jsonb)
  from public, anon, authenticated;

-- The whole persisted repair result. Exactly these fifteen fields, all of them
-- required, each one typed and bounded, and the patch hash recomputed here so
-- the stored diff is the diff the worker said it produced.
--
-- What is deliberately absent: command lines, check stdout/stderr, the
-- operator's expected acceptance values, the model trajectory, container
-- names, host paths and run receipts. Those stay in the operator's private
-- evidence root. What is present is what a reviewer needs to judge a candidate
-- - the diff itself, the identities it was computed from, and bounded counts.
--
-- An over-limit patch is REFUSED, never truncated: half a diff that still
-- carried a 'needs_review' status would be worse than a failed attempt.
create or replace function private.assert_repair_result(p_result jsonb)
returns void language plpgsql immutable set search_path='' as $$
declare
  v_fields text[] := array['kind','status','verification','configuration_sha256',
    'source_commit','source_tree_sha256','candidate_tree_sha256','patch_sha256','patch',
    'checks_passed','turns','tool_calls','tokens_observed','model_name','model_digest'];
  v_missing text;
  v_offender text;
  v_patch text;
  v_bytes integer;
begin
  if jsonb_typeof(p_result) <> 'object' then
    raise exception 'result must be a JSON object';
  end if;
  if pg_column_size(p_result) > 196608 then
    raise exception 'repair result exceeds the 192 KiB persisted limit';
  end if;
  if exists(select 1 from jsonb_object_keys(p_result) k where k <> all(v_fields)) then
    raise exception 'repair result may only contain the bounded receipt fields';
  end if;
  select string_agg(f.name, ', ' order by f.name) into v_missing
    from unnest(v_fields) as f(name) where not p_result ? f.name;
  if v_missing is not null then
    raise exception 'repair result is missing %', v_missing;
  end if;
  if exists(select 1 from jsonb_each(p_result) e
             where (e.key in ('kind','status','verification','configuration_sha256',
                              'source_commit','source_tree_sha256','candidate_tree_sha256',
                              'patch_sha256','patch','model_name','model_digest')
                    and jsonb_typeof(e.value) <> 'string')
                or (e.key in ('checks_passed','turns','tool_calls','tokens_observed')
                    and jsonb_typeof(e.value) <> 'number')) then
    raise exception 'repair result fields have the wrong JSON types';
  end if;
  -- A stored repair result describes one outcome only: a verified candidate
  -- that is ready for human review. A partial, unverified or self-declared
  -- 'fixed' result has no representation here.
  if p_result->>'kind' <> 'repository_repair' then
    raise exception 'repair result kind must be repository_repair';
  end if;
  if p_result->>'status' <> 'needs_review' then
    raise exception 'a persisted repair result is always needs_review';
  end if;
  if p_result->>'verification' <> 'passed' then
    raise exception 'an unverified repair candidate is not a result';
  end if;
  if p_result->>'source_commit' !~ '^[0-9a-f]{40}$' then
    raise exception 'repair result source_commit must be a 40 character hexadecimal SHA';
  end if;
  if exists(select 1 from unnest(array['configuration_sha256','source_tree_sha256',
                                       'candidate_tree_sha256','patch_sha256',
                                       'model_digest']) as f(name)
             where (p_result->>f.name) !~ '^[0-9a-f]{64}$') then
    raise exception 'repair result hashes must be 64 lowercase hexadecimal characters';
  end if;
  -- The same safe native model name the operator configuration accepts.
  if (p_result->>'model_name') !~ '^[A-Za-z0-9._:-]{1,100}$' then
    raise exception 'repair result model_name is not a plain local model name';
  end if;
  if (p_result->>'candidate_tree_sha256') = (p_result->>'source_tree_sha256') then
    raise exception 'a repair result whose candidate tree equals its source tree changed '
                    'nothing, so it is not a candidate';
  end if;
  -- Bounded counts, whole numbers, and the one-turn zero-tool-call run that a
  -- genuinely easy repair produces is legal.
  select f.name into v_offender
    from (values ('checks_passed', 1, 48), ('turns', 1, 50),
                 ('tool_calls', 0, 100), ('tokens_observed', 0, 500000))
           as f(name, lowest, highest)
   where (p_result->>f.name)::numeric < f.lowest
      or (p_result->>f.name)::numeric > f.highest
      or (p_result->>f.name)::numeric <> trunc((p_result->>f.name)::numeric)
   limit 1;
  if v_offender is not null then
    raise exception 'repair result % is outside its bound or not a whole number', v_offender;
  end if;
  v_patch := p_result->>'patch';
  v_bytes := octet_length(v_patch);
  if v_bytes < 1 then
    raise exception 'a repair result must carry its patch; metadata alone is not a result';
  end if;
  if v_bytes > 65536 then
    raise exception 'repair result patch is % bytes; the 64 KiB limit refuses it rather '
                    'than storing a truncated diff', v_bytes;
  end if;
  -- Recomputed here, not trusted: the stored diff and the stored hash the UI
  -- shows beside it must agree.
  if encode(sha256(convert_to(v_patch, 'UTF8')), 'hex') <> (p_result->>'patch_sha256') then
    raise exception 'repair result patch does not match its patch_sha256';
  end if;
end
$$;
revoke all on function private.assert_repair_result(jsonb) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. One attempt, one kind. The structural guarantee that the two task kinds
--    cannot contaminate each other's durable state, independent of which RPC
--    is calling.
-- ---------------------------------------------------------------------------

-- The phase enums and the result shapes are per kind. The RPCs below already
-- refuse a run of the wrong kind with a typed reason, but this trigger is what
-- makes that structural: an analysis completion path can never write an
-- analysis-shaped result or an 'analyzing' phase onto a repair attempt, and a
-- repair result can never appear on an analysis attempt, whatever path is
-- taken. SECURITY DEFINER because it reads public.work_items, which is behind
-- row level security.
create or replace function private.enforce_run_kind_contract()
returns trigger language plpgsql security definer set search_path='' as $$
declare
  v_kind text;
  v_validate boolean;
begin
  select w.kind into v_kind from public.work_items w where w.id = new.work_item_id;
  if v_kind is null then
    raise exception 'an attempt must belong to a work item';
  end if;
  -- OLD only exists on UPDATE, so it is read in that branch alone. A result
  -- that is unchanged by this statement was validated when it was written.
  if tg_op = 'UPDATE' then
    v_validate := new.result is not null and new.result is distinct from old.result;
  else
    v_validate := new.result is not null;
  end if;
  if v_kind = 'repository_repair' then
    if new.phase not in ('claimed','fetching_source','repairing','verifying',
                         'recording_result','done') then
      raise exception '% is not a phase of a repair attempt', new.phase;
    end if;
    if v_validate then
      perform private.assert_repair_result(new.result);
    end if;
  else
    if new.phase not in ('claimed','fetching_source','analyzing','recording_result','done') then
      raise exception '% is not a phase of an analysis attempt', new.phase;
    end if;
    if v_validate then
      perform private.assert_analysis_result(new.result);
    end if;
  end if;
  return new;
end
$$;
revoke all on function private.enforce_run_kind_contract() from public, anon, authenticated;
drop trigger if exists on_factory_run_kind_contract on public.factory_runs;
create trigger on_factory_run_kind_contract
before insert or update on public.factory_runs
for each row execute function private.enforce_run_kind_contract();

-- ---------------------------------------------------------------------------
-- 5. Settlement of the work a withdrawn enrollment leaves behind.
-- ---------------------------------------------------------------------------

-- Repair work is claimable by exactly one worker identity under exactly one
-- policy, so withdrawing either leaves its queued items unclaimable forever.
-- They are therefore settled terminally rather than left queued: a request
-- nobody is authorized to run is a failure with a reason, not an open promise.
-- The caller holds the policy lock; this function takes the work item lock and
-- then the run lock, which is the one lock order.
create or replace function private.settle_repair_policy_work(
  p_policy_id uuid, p_error_code text, p_detail text)
returns integer language plpgsql security definer set search_path='' as $$
declare
  v_item record;
  v_fenced integer := 0;
begin
  for v_item in
    select w.id from public.work_items w
     where w.repair_policy_id = p_policy_id
       and w.status in ('queued','running')
     order by w.created_at, w.id
  loop
    perform 1 from public.work_items w where w.id = v_item.id for update;
    v_fenced := v_fenced + private.fence_running_runs(v_item.id, p_error_code, p_detail);
    update public.work_items w
       set status = 'failed', error_code = p_error_code
     where w.id = v_item.id and w.status in ('queued','running');
  end loop;
  return v_fenced;
end
$$;
revoke all on function private.settle_repair_policy_work(uuid,text,text)
  from public, anon, authenticated;

-- The same settlement, reached from the other direction: an offboarded worker
-- Auth account clears the live reference on its enrollments (ON DELETE SET
-- NULL above) instead of cascading them away, so the frozen record of what was
-- approved and the work history that names it both survive the deletion. The
-- record must not stay actionable, though - nothing can ever claim this
-- policy's work again - so the enrollment is withdrawn and its unfinished work
-- settled inside the same statement that cleared the reference.
--
-- SECURITY DEFINER because the Auth admin role that deletes the account holds
-- no privilege on the runtime tables. AFTER UPDATE OF with a WHEN clause so
-- the withdrawal below, which does not touch worker_user_id, cannot re-enter
-- this function, and so no other update pays for the check. The policy row is
-- already locked by the statement that fired this trigger and the settlement
-- takes work items and then runs, which is the one lock order.
create or replace function private.settle_repair_policy_after_identity_loss()
returns trigger language plpgsql security definer set search_path='' as $$
begin
  if new.enabled then
    -- revoked_by stays NULL: an Auth account deletion is not a project actor's
    -- decision, and attribution is never invented.
    update public.project_repair_policies k
       set enabled = false, revoked_at = now()
     where k.id = new.id;
  end if;
  perform private.settle_repair_policy_work(new.id, 'worker_identity_deleted',
    'the worker identity bound to this repair policy was deleted');
  return null;
end
$$;
revoke all on function private.settle_repair_policy_after_identity_loss()
  from public, anon, authenticated;
drop trigger if exists on_repair_policy_identity_cleared
  on public.project_repair_policies;
create trigger on_repair_policy_identity_cleared
after update of worker_user_id on public.project_repair_policies
for each row
when (old.worker_user_id is not null and new.worker_user_id is null)
execute function private.settle_repair_policy_after_identity_loss();

-- ---------------------------------------------------------------------------
-- 6. The analysis RPCs refuse a repair attempt.
--
-- These three are reproduced from
-- retained_attribution_and_lease_clock.sql unchanged except for one added
-- guard each: a run whose work item is not of kind 'repository_analysis' is
-- refused with reason 'wrong_kind' and no state change. public.claim_analysis_work
-- already filters on kind and needs no change, so the analysis worker can
-- neither consume repair work nor settle a repair attempt it somehow learned
-- the id of. Argument lists, return shapes, authorization, pinning, fencing
-- and the wall-clock lease rules are identical.
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
  -- The analysis API owns analysis attempts only. A repair attempt has other
  -- phases, another result shape and a policy-bound authorization rule, so it
  -- is refused here before any state is touched.
  if v_item.kind <> 'repository_analysis' then
    return query select false, 'wrong_kind'::text, v_run.status, v_item.status,
                        v_item.cancel_requested_at is not null, null::timestamptz, v_run.phase;
    return;
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
  -- clock_timestamp(), read after the work item and run locks above: the
  -- deadline this call is judging against was itself set on the wall clock,
  -- and a heartbeat that waited for those locks must be told that time passed.
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
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
  -- The extension starts where the worker actually is, not where its
  -- transaction began, so a heartbeat that waited does not hand back a lease
  -- that is already partly spent.
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
  -- An analysis result can never be published onto a repair attempt. The
  -- trigger on public.factory_runs refuses it structurally as well; this is
  -- the typed refusal a worker can act on.
  if v_item.kind <> 'repository_analysis' then
    return query select false, 'wrong_kind'::text, v_item.status;
    return;
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
  -- The same wall clock the deadline was set on, read after the two locks
  -- above: a completion that waited out its own lease is refused, and one that
  -- did not is accepted, on elapsed time rather than transaction start.
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
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
  -- A repair attempt is settled by public.fail_repair_run, which additionally
  -- re-checks the policy binding. Refusing it here keeps one attempt from
  -- having two settlement paths with different authorization rules.
  if v_item.kind <> 'repository_analysis' then
    return query select false, 'wrong_kind'::text, v_item.status, false;
    return;
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
  -- As in the completion path: the lease is judged on the wall clock, read
  -- after this call's two row locks were acquired.
  if v_token is null or p_lease_token is null or v_token <> p_lease_token
     or v_run.lease_expires_at <= clock_timestamp() then
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

-- ---------------------------------------------------------------------------
-- 7. Worker revocation also settles the repair work it orphans.
--
-- Reproduced from durable_factory_runtime.sql unchanged except for the final
-- step. A repair work item is claimable only by the one worker identity its
-- policy names, so disabling that registration would otherwise leave queued
-- repair work waiting for a worker that is no longer allowed to exist. The
-- analysis behaviour - fence the running attempt, then let the generic
-- settlement decide retry or terminal failure - is untouched.
-- ---------------------------------------------------------------------------
create or replace function public.revoke_project_worker(
  p_project_id uuid, p_worker_user_id uuid)
returns table(id uuid, enabled boolean, fenced_runs integer)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_row public.project_workers;
  v_run record;
  v_policy record;
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
  -- Registration, then policies, then work items, then runs. Every policy row
  -- this identity is bound to is locked here, in one statement, before either
  -- loop below takes a work item lock: that is what keeps this path from
  -- deadlocking against a claim or a heartbeat, which lock a policy first and
  -- a work item second.
  perform 1 from public.project_repair_policies k
   where k.project_id = p_project_id and k.worker_user_id = p_worker_user_id
   order by k.created_at, k.id
   for update;
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
  -- Nothing can claim this identity's repair work any more, so its queued
  -- items - including one the settlement above just handed another attempt -
  -- are failed terminally with a reason instead of waiting forever. The
  -- running attempts were already fenced and counted, so this adds nothing to
  -- fenced_runs.
  for v_policy in
    select k.id from public.project_repair_policies k
     where k.project_id = p_project_id and k.worker_user_id = p_worker_user_id
     order by k.created_at, k.id
  loop
    perform private.settle_repair_policy_work(v_policy.id, 'worker_revoked',
      'the worker identity bound to this repair policy was revoked');
  end loop;
  return query select v_row.id, false, v_fenced;
end
$$;
revoke all on function public.revoke_project_worker(uuid,uuid) from public, anon;
grant execute on function public.revoke_project_worker(uuid,uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 8. Enrollment and revocation, by the project's owner or admin.
-- ---------------------------------------------------------------------------

-- Enrols one reviewed operator configuration and one approved commit for one
-- already-provisioned worker identity. This RPC installs nothing, starts
-- nothing and grants no inference or execution budget: the operator separately
-- starts a worker process with the matching configuration file, and that
-- process refuses to run if the policy id, configuration digest, source URL or
-- commit it was given disagree with this row.
--
-- The frozen source URL is derived from the project's own saved source, never
-- supplied by the caller, so an admin cannot point a repair policy at an
-- unrelated repository.
create or replace function public.register_project_repair_policy(
  p_project_id uuid, p_worker_user_id uuid, p_label text,
  p_source_commit text, p_configuration_sha256 text)
returns table(id uuid, project_id uuid, worker_user_id uuid, label text, enabled boolean,
              source_url text, source_owner text, source_repo text, source_commit text,
              configuration_sha256 text, last_seen_at timestamptz, created_at timestamptz,
              created_by uuid, revoked_at timestamptz, revoked_by uuid)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_label text := btrim(coalesce(p_label, ''));
  v_commit text := btrim(coalesce(p_source_commit, ''));
  v_config text := btrim(coalesce(p_configuration_sha256, ''));
  v_project public.projects;
  v_registration public.project_workers;
  v_parts text[];
  v_row public.project_repair_policies;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if not private.is_project_admin(p_project_id) then
    raise exception 'not allowed to manage this project';
  end if;
  if p_worker_user_id is null then raise exception 'worker identity is required'; end if;
  if v_label !~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{1,59}$' then
    raise exception 'worker label must be 2-60 characters of A-Z a-z 0-9 space . _ -';
  end if;
  -- Lowercase hex is required rather than normalized: the digest and the
  -- commit the operator reviewed are what the worker will compare against, and
  -- silently rewriting them would hide a transcription error.
  if v_commit !~ '^[0-9a-f]{40}$' then
    raise exception 'source commit must be a 40 character lowercase hexadecimal SHA';
  end if;
  if v_config !~ '^[0-9a-f]{64}$' then
    raise exception 'configuration digest must be 64 lowercase hexadecimal characters';
  end if;
  if p_worker_user_id = v_actor then
    raise exception 'a worker must be a separate service identity, not your own account';
  end if;
  if not exists(select 1 from auth.users u where u.id = p_worker_user_id) then
    raise exception 'worker identity not found';
  end if;
  -- The same two conditions every worker call re-checks: a designated service
  -- principal, and an enabled registration for this exact project. Code
  -- execution authority is therefore never created here out of nothing - it is
  -- narrowed from an existing registration to one frozen snapshot.
  if not private.is_service_worker_identity(p_worker_user_id) then
    raise exception 'that account is not a provisioned factory worker service identity';
  end if;
  -- FOR SHARE, taken before the enrollment row below is inserted, which is the
  -- one lock order: a concurrent public.revoke_project_worker either waits and
  -- then sees this enrollment, or commits first and leaves no enabled
  -- registration for this re-evaluated predicate to find. Enrolling against an
  -- identity that is being withdrawn would otherwise record an approval that
  -- can never admit or claim anything.
  select k.* into v_registration from public.project_workers k
   where k.project_id = p_project_id
     and k.worker_user_id = p_worker_user_id and k.enabled
   for share;
  if v_registration.id is null then
    raise exception 'worker identity is not registered for this project';
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
  if v_project.source_url is null then
    raise exception 'project has no source repository to enroll';
  end if;
  v_parts := private.github_repo_parts(v_project.source_url);
  if v_parts is null then
    raise exception 'only public https://github.com/owner/repo sources can be repaired';
  end if;
  if exists(select 1 from public.project_repair_policies k
             where k.project_id = p_project_id
               -- The frozen identity, so an enrollment whose live reference
               -- has been cleared still counts as the one that was approved.
               and k.worker_identity = p_worker_user_id
               and k.source_commit = v_commit
               and k.configuration_sha256 = v_config
               and k.enabled) then
    raise exception 'an identical enabled policy already exists for this worker, commit '
                    'and configuration';
  end if;
  -- The frozen identity and the live reference start out as the same account.
  -- Only the live one can ever change, and only by being cleared.
  insert into public.project_repair_policies as k
    (project_id, worker_identity, worker_user_id, label, source_url, source_owner,
     source_repo, source_commit, configuration_sha256, created_by)
  values (p_project_id, p_worker_user_id, p_worker_user_id, v_label, v_project.source_url,
          v_parts[1], v_parts[2], v_commit, v_config, v_actor)
  returning k.* into v_row;
  return query select v_row.id, v_row.project_id, v_row.worker_user_id, v_row.label,
                      v_row.enabled, v_row.source_url, v_row.source_owner, v_row.source_repo,
                      v_row.source_commit, v_row.configuration_sha256, v_row.last_seen_at,
                      v_row.created_at, v_row.created_by, v_row.revoked_at, v_row.revoked_by;
end
$$;
revoke all on function
  public.register_project_repair_policy(uuid,uuid,text,text,text) from public, anon;
grant execute on function
  public.register_project_repair_policy(uuid,uuid,text,text,text) to authenticated;

-- Withdraws an enrollment immediately. The policy is disabled - never deleted,
-- so the record of what was approved survives - every attempt running under it
-- is fenced, its lease token disappears, and the work it can no longer run is
-- settled terminally rather than left queued. Policies are never re-enabled: a
-- renewed decision is a new policy.
create or replace function public.revoke_project_repair_policy(p_policy_id uuid)
returns table(id uuid, enabled boolean, fenced_runs integer)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_row public.project_repair_policies;
  v_fenced integer := 0;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  -- Policy first, then work items, then runs: the one lock order.
  select k.* into v_row from public.project_repair_policies k
   where k.id = p_policy_id for update;
  -- An unauthorized caller gets the same message as a missing row, so policy
  -- ids in other projects are not probeable.
  if v_row.id is null or not private.is_project_admin(v_row.project_id) then
    raise exception 'repair policy not found';
  end if;
  if v_row.enabled then
    update public.project_repair_policies k
       set enabled = false, revoked_at = now(), revoked_by = v_actor
     where k.id = v_row.id;
  end if;
  v_fenced := private.settle_repair_policy_work(v_row.id, 'policy_revoked',
    'the repair policy authorizing this work was revoked');
  return query select v_row.id, false, v_fenced;
end
$$;
revoke all on function public.revoke_project_repair_policy(uuid) from public, anon;
grant execute on function public.revoke_project_repair_policy(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 9. Submission, by any project editor.
-- ---------------------------------------------------------------------------

-- Accepts one bounded goal against one enabled policy. Everything the attempt
-- will be judged against is frozen into the work item here: the policy, the
-- source URL and its parsed owner/repo, the pinned commit, the configuration
-- digest the policy names, and the goal text. Editing the project's source URL
-- afterwards cannot redirect this request, and a later retry re-fetches
-- exactly this commit.
--
-- Submitting shares the goal with everyone who can read the project. It is
-- never copied from a private conversation; the caller types it here.
create or replace function public.submit_repository_repair(
  p_project_id uuid, p_policy_id uuid, p_goal text, p_idempotency_key text default null)
returns table(work_item_id uuid, status text, replayed boolean, kind text, source_url text,
              input_digest text, attempts integer, max_attempts integer,
              repair_policy_id uuid, goal text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_goal text := btrim(coalesce(p_goal, ''));
  v_key text := nullif(btrim(coalesce(p_idempotency_key, '')), '');
  v_policy public.project_repair_policies;
  v_registration public.project_workers;
  v_project public.projects;
  v_parts text[];
  v_ref text;
  v_digest text;
  v_existing public.work_items;
  v_row public.work_items;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if private.project_role_rank(private.project_role(p_project_id))
     < private.project_role_rank('engineer') then
    raise exception 'not allowed to submit work for this project';
  end if;
  if v_goal = '' or octet_length(v_goal) > 4096
     or translate(v_goal, E'\n\t', '') ~ '[[:cntrl:]]' then
    raise exception 'goal must be 1-4096 bytes of text';
  end if;
  if v_key is not null and v_key !~ '^[A-Za-z0-9._:-]{8,120}$' then
    raise exception 'idempotency key must be 8-120 characters of A-Z a-z 0-9 . _ : -';
  end if;
  -- Unlocked resolution first, exactly as the claim and heartbeat paths resolve
  -- their ids, so the locks below can be taken in the one order: registration,
  -- then policy. A policy in another project is indistinguishable from a
  -- missing one.
  select k.* into v_policy from public.project_repair_policies k where k.id = p_policy_id;
  if v_policy.id is null or v_policy.project_id <> p_project_id then
    raise exception 'repair policy not found';
  end if;
  -- Reported before any lock is taken so a withdrawn enrollment keeps its own
  -- message; the authoritative re-check happens under the share lock below.
  if not v_policy.enabled then raise exception 'repair policy is disabled'; end if;
  if v_policy.worker_user_id is null then
    raise exception 'the worker identity bound to this repair policy no longer exists';
  end if;
  -- Admission requires everything consumption requires. public.claim_repair_work
  -- demands an enabled registration and a live service designation for the
  -- bound identity, so admission that did not check them would accept work
  -- nobody is allowed to run - which is what revoking a worker without
  -- withdrawing its enrollments used to leave queued.
  --
  -- FOR SHARE, taken before the policy and held to commit:
  -- public.revoke_project_worker takes this same row FOR UPDATE before it
  -- touches a policy or a work item, so it either waits here and then settles
  -- the item this call admits, or commits first and leaves the re-evaluated
  -- `enabled` predicate nothing to find.
  select w.* into v_registration from public.project_workers w
   where w.project_id = v_policy.project_id
     and w.worker_user_id = v_policy.worker_user_id and w.enabled
   for share;
  if v_registration.id is null then
    raise exception 'the worker identity bound to this repair policy is no longer '
                    'registered for this project';
  end if;
  -- Designation is re-derived from Auth on every call and never inherited from
  -- the enrollment row, so stripping the service marker stops new admission
  -- exactly as it already stops claiming.
  if not private.is_service_worker_identity(v_policy.worker_user_id) then
    raise exception 'the worker identity bound to this repair policy is no longer a '
                    'provisioned factory worker service identity';
  end if;
  -- Now the policy, in the one lock order. FOR SHARE rather than FOR UPDATE
  -- because admission writes nothing here, so two submissions do not serialize
  -- behind each other, and it is held through the insertion below: a concurrent
  -- public.revoke_project_repair_policy therefore cannot slip between this
  -- check and the admitted row. It waits and then settles the new item, or it
  -- commits first and this re-read sees the withdrawal. Without this lock the
  -- deferred foreign key would still be satisfied - it checks that the policy
  -- exists, not that it is enabled - and the goal would stay queued forever
  -- under an enrollment nothing may claim.
  select k.* into v_policy from public.project_repair_policies k
   where k.id = p_policy_id for share;
  if v_policy.id is null or v_policy.project_id <> p_project_id then
    raise exception 'repair policy not found';
  end if;
  if not v_policy.enabled then raise exception 'repair policy is disabled'; end if;
  -- The locked row must still name the identity whose registration is held
  -- above. The live reference is clear-only, so it cannot have been redirected
  -- to another account; one cleared while this call waited must fail closed
  -- rather than admit under a lock taken for an identity this enrollment no
  -- longer names.
  if v_policy.worker_user_id is distinct from v_registration.worker_user_id then
    raise exception 'the worker identity bound to this repair policy no longer exists';
  end if;
  select p.* into v_project from public.projects p where p.id = p_project_id;
  if v_project.id is null then raise exception 'project not found'; end if;
  -- New admission requires the project's *current* saved source to still be
  -- the one that was approved. A project that has moved to another repository
  -- needs a new review, not an inherited authorization. Work already admitted
  -- keeps running against its own frozen pin regardless.
  v_parts := private.github_repo_parts(v_project.source_url);
  if v_project.source_url is null or v_parts is null
     or v_project.source_url <> v_policy.source_url
     or v_parts[1] <> v_policy.source_owner or v_parts[2] <> v_policy.source_repo then
    raise exception 'the project source no longer matches this policy; enroll a new policy';
  end if;
  v_ref := 'github.com/' || v_policy.source_owner || '/' || v_policy.source_repo;
  -- Canonical input identity. Kind, source, commit, configuration, policy and
  -- goal all participate, so a reused idempotency key that describes different
  -- work - including an analysis request, another policy or another goal -
  -- fails the comparison below instead of replaying the wrong run.
  v_digest := encode(sha256(convert_to('repository_repair' || E'\n' || v_policy.source_url
    || E'\n' || v_policy.source_commit || E'\n' || v_policy.configuration_sha256
    || E'\n' || v_policy.id::text || E'\n' || v_goal, 'UTF8')), 'hex');
  -- Admission is one statement, so two callers holding the same scoped key
  -- cannot both pass an existence check and then collide on
  -- work_items_idempotency_idx: the second insertion waits for the first,
  -- records nothing, and re-reads the committed row below as a replay.
  insert into public.work_items as w
    (project_id, created_by, kind, source_url, source_owner, source_repo,
     input_digest, idempotency_key, repair_policy_id, goal,
     pinned_source_ref, pinned_source_commit, max_attempts)
  values (p_project_id, v_actor, 'repository_repair', v_policy.source_url,
          v_policy.source_owner, v_policy.source_repo, v_digest, v_key, v_policy.id, v_goal,
          v_ref, v_policy.source_commit, 2)
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
    if v_existing.input_digest <> v_digest then
      raise exception 'idempotency key already used for a different input';
    end if;
    return query select v_existing.id, v_existing.status, true, v_existing.kind,
                        v_existing.source_url, v_existing.input_digest, v_existing.attempts,
                        v_existing.max_attempts, v_existing.repair_policy_id, v_existing.goal;
    return;
  end if;
  return query select v_row.id, v_row.status, false, v_row.kind, v_row.source_url,
                      v_row.input_digest, v_row.attempts, v_row.max_attempts,
                      v_row.repair_policy_id, v_row.goal;
end
$$;
revoke all on function public.submit_repository_repair(uuid,uuid,text,text) from public, anon;
grant execute on function public.submit_repository_repair(uuid,uuid,text,text) to authenticated;

-- ---------------------------------------------------------------------------
-- 10. Worker RPCs for repair work. Each one requires the caller to BE the
--     worker identity the policy names, to still hold an enabled registration
--     for that policy's project, to still be a designated service principal,
--     and to present the configuration digest the policy was enrolled with.
-- ---------------------------------------------------------------------------

-- Reclaims expired attempts, then takes at most one queued item of this policy
-- with FOR UPDATE SKIP LOCKED, so two processes of the same worker receive
-- different items or nothing and never share an attempt or a lease token.
--
-- last_seen_at is refreshed even when there is nothing to do, but only after
-- every authorization check has passed, so it records authenticated authorized
-- contact and nothing weaker. It is not capacity or availability.
create or replace function public.claim_repair_work(
  p_policy_id uuid, p_configuration_sha256 text, p_lease_seconds integer default 300)
returns table(work_item_id uuid, run_id uuid, attempt integer, max_attempts integer,
              lease_token uuid, lease_expires_at timestamptz, kind text, project_id uuid,
              source_url text, source_owner text, source_repo text,
              pinned_source_ref text, pinned_source_commit text,
              previous_source_digest text, previous_checkpoint jsonb,
              repair_policy_id uuid, goal text, configuration_sha256 text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_config text := btrim(coalesce(p_configuration_sha256, ''));
  v_project uuid;
  v_registration public.project_workers;
  v_policy public.project_repair_policies;
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
  if v_config !~ '^[0-9a-f]{64}$' then
    raise exception 'configuration digest must be 64 lowercase hexadecimal characters';
  end if;
  -- Unlocked resolution first, exactly as the heartbeat path resolves its work
  -- item id, so the locks below can be taken in the one order: registration,
  -- then policy, then work item, then run. A policy bound to another identity
  -- is indistinguishable from a missing one.
  select k.project_id into v_project from public.project_repair_policies k
   where k.id = p_policy_id and k.worker_user_id = v_actor;
  if v_project is null then raise exception 'repair policy not found'; end if;
  -- FOR SHARE, held to commit: a concurrent public.revoke_project_worker takes
  -- FOR UPDATE on this same row before it touches any policy or work item, so
  -- it cannot slip between this check and the insertion below. The row lock
  -- re-evaluates the `enabled` predicate after waiting, so a revocation that
  -- committed first leaves nothing to find here. This wait is unbounded, which
  -- is why the lease is not measured from the start of this transaction.
  select w.* into v_registration from public.project_workers w
   where w.project_id = v_project and w.worker_user_id = v_actor and w.enabled
   for share;
  if v_registration.id is null then
    raise exception 'worker identity is not registered for this project';
  end if;
  -- FOR UPDATE rather than FOR SHARE because this call writes last_seen_at on
  -- the same row: two concurrent claims would otherwise both hold a share lock
  -- and then both need to upgrade it, which is a deadlock. Claims under one
  -- policy therefore serialize, which is what a single bound worker wants
  -- anyway, and a revocation either waits here or is already committed.
  select k.* into v_policy from public.project_repair_policies k
   where k.id = p_policy_id for update;
  -- A cleared live reference authorizes nobody, so it is refused here as well
  -- as by the resolution above: NULL is never a wildcard.
  if v_policy.id is null or v_policy.worker_user_id is null
     or v_policy.worker_user_id <> v_actor then
    raise exception 'repair policy not found';
  end if;
  if not v_policy.enabled then raise exception 'repair policy is disabled'; end if;
  -- The worker proves it loaded the configuration this policy was enrolled
  -- with. A worker started against another configuration file gets no work.
  if v_policy.configuration_sha256 <> v_config then
    raise exception 'configuration digest does not match this repair policy';
  end if;
  -- Contact is recorded even when this poll finds nothing, because the
  -- credential did authenticate and was authorized. The predicate keeps the
  -- write monotonic: the policy row serializes these transactions, but their
  -- now() values are transaction start times and two of them can arrive out
  -- of order, so an older stamp is skipped rather than refused.
  update public.project_repair_policies k set last_seen_at = now()
   where k.id = v_policy.id and (k.last_seen_at is null or k.last_seen_at < now());
  perform private.expire_stale_runs(v_project);
  select w.* into v_item from public.work_items w
   where w.repair_policy_id = p_policy_id and w.kind = 'repository_repair'
     and w.status = 'queued' and w.cancel_requested_at is null
   -- The id tiebreaker keeps the order total, so two items submitted inside
   -- one transaction (which share now()) are still handed out deterministically.
   order by w.created_at, w.id
   for update skip locked
   limit 1;
  if v_item.id is null then return; end if;
  -- Submission required an editing role, and so does running the work.
  if not private.creator_may_run(v_project, v_item.created_by) then
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
  -- The frozen identities must still agree. A work item whose pin is not the
  -- policy's approved commit cannot be run under this policy at all, so it is
  -- failed terminally instead of being handed to a worker that would fetch
  -- something the request was never authorized for.
  if v_item.pinned_source_commit <> v_policy.source_commit
     or v_item.source_url <> v_policy.source_url then
    perform private.fence_running_runs(v_item.id, 'source_identity_conflict',
      'the work item pin is not this policy approved snapshot');
    update public.work_items w
       set status = 'failed', error_code = 'source_identity_conflict'
     where w.id = v_item.id;
    return;
  end if;
  v_attempt := v_item.attempts + 1;
  -- The wall clock after the locks above, not now(): a claim that spent longer
  -- than its own lease waiting must not hand out an already expired attempt.
  v_expires := clock_timestamp() + make_interval(secs => p_lease_seconds);
  select r.* into v_previous from public.factory_runs r
   where r.work_item_id = v_item.id order by r.attempt desc limit 1;
  update public.work_items w set status = 'running', attempts = v_attempt
   where w.id = v_item.id;
  insert into public.factory_runs as r
    (work_item_id, project_id, attempt, worker_user_id, worker_registration_id,
     lease_expires_at)
  values (v_item.id, v_project, v_attempt, v_actor, v_registration.id, v_expires)
  returning r.id into v_run_id;
  insert into private.factory_run_leases(run_id, work_item_id, lease_token)
  values (v_run_id, v_item.id, v_token);
  perform private.record_run_event(v_run_id, 'claimed', 'claimed',
    format('repair attempt %s of %s', v_attempt, v_item.max_attempts));
  -- The work item's own pin, frozen at admission from the policy: a retry
  -- re-fetches exactly this commit and recomputes, it never replays a model
  -- trajectory. The previous attempt's archive digest and checkpoint are
  -- handed over as the progress record it left behind.
  return query select v_item.id, v_run_id, v_attempt, v_item.max_attempts, v_token,
                      v_expires, v_item.kind, v_project, v_item.source_url,
                      v_item.source_owner, v_item.source_repo, v_item.pinned_source_ref,
                      v_item.pinned_source_commit, v_previous.source_digest,
                      coalesce(v_previous.checkpoint, '{}'::jsonb), v_policy.id,
                      v_item.goal, v_policy.configuration_sha256;
end
$$;
revoke all on function public.claim_repair_work(uuid,text,integer) from public, anon;
grant execute on function public.claim_repair_work(uuid,text,integer) to authenticated;

-- Extends the lease and records durable progress for a repair attempt. Every
-- authority the attempt depends on is re-checked here, not only at claim time:
-- the worker's designation and registration, the policy's enrollment, the
-- submitter's editing role, the fencing token, the lease deadline and the
-- pinned source. Fencing failures are reported as lease_valid = false rather
-- than raised, so the worker has an unambiguous signal to stop its child
-- process group and publish nothing.
create or replace function public.heartbeat_repair_run(
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
  v_policy public.project_repair_policies;
  v_item_id uuid;
  v_run_owner uuid;
  v_kind text;
  v_item_status text;
  v_cancelled boolean;
  v_run_status text;
  v_run_phase text;
  v_policy_id uuid;
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
     ('claimed','fetching_source','repairing','verifying','recording_result','done') then
    raise exception 'unknown run phase';
  end if;
  if p_checkpoint is not null then
    -- Fixed step enum, bounded non-negative counters and two hashes. No raw
    -- source, tool argument, prompt, path, credential or upstream error can be
    -- expressed here at all.
    perform private.assert_repair_checkpoint(p_checkpoint);
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
  -- Unlocked resolution, then the one lock order: policy, work item, run. A
  -- run belonging to another identity is indistinguishable from a missing one.
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.kind, w.repair_policy_id, w.status, w.cancel_requested_at is not null
    into v_kind, v_policy_id, v_item_status, v_cancelled
    from public.work_items w where w.id = v_item_id;
  if v_kind <> 'repository_repair' then
    -- An analysis attempt is heartbeaten by public.heartbeat_analysis_run. No
    -- lock is taken and no state is touched on the way out.
    select r.status, r.phase into v_run_status, v_run_phase
      from public.factory_runs r where r.id = p_run_id;
    return query select false, 'wrong_kind'::text, v_run_status, v_item_status,
                        v_cancelled, null::timestamptz, v_run_phase;
    return;
  end if;
  select k.* into v_policy from public.project_repair_policies k
   where k.id = v_policy_id for update;
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
  -- The enrollment itself must still stand, and must still name this caller.
  -- `is distinct from` rather than `<>`: an enrollment whose live identity was
  -- cleared names nobody, so it fences this attempt instead of comparing NULL.
  if v_policy.id is null or not v_policy.enabled
     or v_policy.worker_user_id is distinct from v_actor then
    return query select false, 'policy_revoked'::text, v_run.status, v_item.status,
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
  -- clock_timestamp(), read after the locks above: the deadline was itself set
  -- on the wall clock, and a heartbeat that waited must be told time passed.
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
  -- Source identity is write-once per attempt, and a repair work item is
  -- pinned from admission, so anything other than the approved snapshot means
  -- the worker fetched bytes this request never authorized.
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
  if (v_ref is not null and v_ref <> v_item.pinned_source_ref)
     or (v_commit is not null and v_commit <> v_item.pinned_source_commit) then
    raise exception 'source identity conflicts with the work item pin';
  end if;
  if v_commit is not null and v_commit <> v_policy.source_commit then
    raise exception 'source identity conflicts with the repair policy';
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
  -- An authenticated, authorized, still-leased heartbeat is contact, so a
  -- worker busy inside a long attempt does not look idle to the operator. The
  -- policy row is already locked, in the one lock order.
  update public.project_repair_policies k set last_seen_at = now()
   where k.id = v_policy.id and (k.last_seen_at is null or k.last_seen_at < now());
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
  public.heartbeat_repair_run(uuid,uuid,text,jsonb,text,text,text,integer)
  from public, anon;
grant execute on function
  public.heartbeat_repair_run(uuid,uuid,text,jsonb,text,text,text,integer)
  to authenticated;

-- Atomic publication of a verified candidate, behind the same fence. A stale,
-- cancelled, revoked or expired attempt is refused with accepted = false and
-- writes neither a result nor a success event.
--
-- 'succeeded' here means exactly one thing: this attempt computed a candidate
-- that passed the operator's own checks and is ready for a human to review. It
-- is not an approval, a merge or a deployment, and the result must have been
-- computed from this policy's configuration and this work item's pinned commit.
create or replace function public.finish_repair_run(
  p_run_id uuid, p_lease_token uuid, p_result jsonb)
returns table(accepted boolean, reason text, work_item_status text)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_policy public.project_repair_policies;
  v_item_id uuid;
  v_run_owner uuid;
  v_kind text;
  v_item_status text;
  v_policy_id uuid;
  v_token uuid;
begin
  if v_actor is null then raise exception 'authentication required'; end if;
  if p_result is null then raise exception 'result is required'; end if;
  -- Exactly the fifteen bounded receipt fields, each typed and in range, the
  -- patch present, under 64 KiB and hash-verified against its own digest.
  perform private.assert_repair_result(p_result);
  select r.work_item_id, r.worker_user_id into v_item_id, v_run_owner
    from public.factory_runs r where r.id = p_run_id;
  if v_item_id is null or v_run_owner <> v_actor then
    raise exception 'run not found';
  end if;
  select w.kind, w.repair_policy_id, w.status
    into v_kind, v_policy_id, v_item_status
    from public.work_items w where w.id = v_item_id;
  if v_kind <> 'repository_repair' then
    -- An analysis attempt is completed by public.finish_analysis_run. No lock
    -- is taken and no result is written on the way out.
    return query select false, 'wrong_kind'::text, v_item_status;
    return;
  end if;
  -- Policy, then work item, then run: the one lock order.
  select k.* into v_policy from public.project_repair_policies k
   where k.id = v_policy_id for update;
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
  if v_policy.id is null or not v_policy.enabled
     or v_policy.worker_user_id is distinct from v_actor then
    return query select false, 'policy_revoked'::text, v_item.status;
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
  -- The result must describe the authorized request: the pinned repository and
  -- commit, and the configuration this policy was enrolled with.
  if v_run.source_ref <> v_item.pinned_source_ref
     or v_run.source_commit <> v_item.pinned_source_commit
     or (p_result->>'source_commit') <> v_item.pinned_source_commit
     or v_item.pinned_source_commit <> v_policy.source_commit then
    return query select false, 'source_identity_conflict'::text, v_item.status;
    return;
  end if;
  if (p_result->>'configuration_sha256') <> v_policy.configuration_sha256 then
    return query select false, 'configuration_mismatch'::text, v_item.status;
    return;
  end if;
  update public.factory_runs r
     set status = 'succeeded', phase = 'done', result = p_result,
         error_code = null, finished_at = now(), heartbeat_at = now()
   where r.id = p_run_id;
  update public.work_items w set status = 'succeeded', error_code = null
   where w.id = v_item.id;
  delete from private.factory_run_leases l where l.run_id = p_run_id;
  update public.project_repair_policies k set last_seen_at = now()
   where k.id = v_policy.id and (k.last_seen_at is null or k.last_seen_at < now());
  -- Event detail is derived from the validated result, never from a worker
  -- string, and names what a reviewer gets: a candidate awaiting review.
  perform private.record_run_event(p_run_id, 'succeeded', 'done',
    format('needs_review checks=%s turns=%s patch_bytes=%s',
           p_result->>'checks_passed', p_result->>'turns',
           octet_length(p_result->>'patch')));
  return query select true, 'ok'::text, 'succeeded'::text;
end
$$;
revoke all on function public.finish_repair_run(uuid,uuid,jsonb) from public, anon;
grant execute on function public.finish_repair_run(uuid,uuid,jsonb) to authenticated;

-- Records a failed repair attempt behind the same fence. error_code is a short
-- enumerated-style code, so an exception message, prompt, credential or host
-- path cannot be smuggled into the metadata authority. Retries are bounded by
-- the work item's two attempts; a loss of authority - revoked policy, revoked
-- registration or a submitter who lost the editing role - is terminal and is
-- not recorded as a retryable attempt failure.
create or replace function public.fail_repair_run(
  p_run_id uuid, p_lease_token uuid, p_error_code text)
returns table(accepted boolean, reason text, work_item_status text, retry_scheduled boolean)
language plpgsql security definer set search_path='' as $$
declare
  v_actor uuid := (select auth.uid());
  v_run public.factory_runs;
  v_item public.work_items;
  v_policy public.project_repair_policies;
  v_item_id uuid;
  v_run_owner uuid;
  v_kind text;
  v_item_status text;
  v_policy_id uuid;
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
  select w.kind, w.repair_policy_id, w.status
    into v_kind, v_policy_id, v_item_status
    from public.work_items w where w.id = v_item_id;
  if v_kind <> 'repository_repair' then
    -- An analysis attempt is settled by public.fail_analysis_run. No lock is
    -- taken and no attempt is spent on the way out.
    return query select false, 'wrong_kind'::text, v_item_status, false;
    return;
  end if;
  select k.* into v_policy from public.project_repair_policies k
   where k.id = v_policy_id for update;
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
  if v_policy.id is null or not v_policy.enabled
     or v_policy.worker_user_id is distinct from v_actor then
    return query select false, 'policy_revoked'::text, v_item.status, false;
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
  update public.project_repair_policies k set last_seen_at = now()
   where k.id = v_policy.id and (k.last_seen_at is null or k.last_seen_at < now());
  perform private.record_run_event(p_run_id, 'failed', v_run.phase, v_code);
  v_status := private.settle_work_item_after_attempt(v_item.id, p_run_id, v_code);
  return query select true, 'ok'::text, v_status, v_status = 'queued';
end
$$;
revoke all on function public.fail_repair_run(uuid,uuid,text) from public, anon;
grant execute on function public.fail_repair_run(uuid,uuid,text) to authenticated;

commit;
