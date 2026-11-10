-- Authorization, fencing, idempotency, mixed-kind, revocation, result-validation
-- and lifecycle regression for the controlled repair runtime.
--
-- Run order (psql, ON_ERROR_STOP=1, on a superuser/owner connection to a
-- Supabase stack whose auth schema and anon/authenticated roles already exist
-- - the local `supabase start` stack or a dedicated development project):
--   1. supabase/schema.sql
--   2. supabase/migrations/private_chats_and_explicit_sharing.sql
--   3. supabase/migrations/projects_and_project_membership.sql
--   4. supabase/migrations/durable_factory_runtime.sql
--   5. supabase/migrations/retained_attribution_and_lease_clock.sql
--   6. supabase/migrations/controlled_repair_runtime.sql
--   7. this file
--
-- Requires SQL-editor/owner privileges and intentionally creates synthetic
-- auth.users. Everything here ROLLS BACK, even on success, so no fixture row
-- survives the run. Never run it on an unrelated project.
--
-- What is real and what is staged:
--   * Every enrollment, revocation, submission, cancellation, claim,
--     heartbeat, completion and failure goes through the real RPCs and
--     policies as the authenticated or anon role. Nothing is mocked and no
--     function is re-implemented here.
--   * The worker service designation lives in auth.users.raw_app_meta_data and
--     public.workspace_memberships is provisioned by the owner role, because
--     no client role may write either one. Account and workspace deletion are
--     performed exactly as the Auth admin API and the owner's own client do.
--   * The repair *payload* is staged: this file publishes a small synthetic
--     unified diff with a correctly computed SHA-256 instead of running a
--     model, a container or a check suite. That is what is under test here -
--     what the database accepts, refuses, freezes and fences - not whether a
--     candidate is any good. Worker and end-to-end behaviour are covered by
--     the worker unit tests and the operator's local integration run.
--   * Elapsed wall-clock time is staged with pg_sleep plus a deadline written
--     relative to clock_timestamp(), the technique
--     retained_attribution_and_lease_clock.sql established: now() is the
--     transaction timestamp and never advances inside this transaction.
--
-- Concurrency is NOT covered here - one connection cannot deadlock against
-- itself. The lock order the runtime relies on
-- (project_workers -> project_repair_policies -> work_items -> factory_runs),
-- and the two commit orders of a submission racing a revocation, are exercised
-- by the two-session cases in supabase/tests/controlled_repair_races.psql. The
-- sequential halves of those cases - where the revocation has already
-- committed before the submission starts - are covered here, in sections 9,
-- 10 and 15.
--
-- Fixture identifiers cross the role switches in transaction-local settings,
-- because one DO block cannot share variables with the next.
begin;

-- ---------------------------------------------------------------------------
-- Fixtures: seven ordinary accounts, three designated worker service
-- identities - the second one no policy names, the third one is offboarded in
-- section 15 - and one undesignated account that will be refused as a worker.
-- ---------------------------------------------------------------------------
insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,
   raw_app_meta_data,created_at,updated_at)
values
-- workspace owner: creates everything, enrols the main policy
('7a111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-owner@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- workspace admin who enrols one policy and is then deleted
('7a222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-admin@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- workspace admin who revokes one policy and is then deleted
('7a333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-revoker@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- engineer: may submit goals, may not enrol a policy
('7a444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-engineer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- viewer: may read, may not submit or enrol
('7a555555-5555-4555-8555-555555555555','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-viewer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- outsider: no workspace or project grant at all
('7a666666-6666-4666-8666-666666666666','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-outsider@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- engineer who submits one goal and then loses the editing role
('7a777777-7777-4777-8777-777777777777','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-demoted@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- the designated worker identity the policies are bound to
('7b111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-worker-a@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- a second designated and registered worker that no policy names
('7b222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-worker-b@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- an ordinary account that was never designated as a service principal
('7b333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-worker-c@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- the designated worker identity whose Auth account is deleted in section 15
('7b444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-repair-worker-d@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now());

set local role authenticated;

do $tenancy$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_worker_b uuid := '7b222222-2222-4222-8222-222222222222';
  v_ws uuid; v_ws_history uuid;
  v_p_repair uuid; v_p_scope uuid; v_p_blank uuid; v_p_audit uuid; v_p_history uuid;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  insert into public.workspaces(name,slug,created_by)
  values ('Repair Main','repair-main',v_owner) returning id into v_ws;
  insert into public.workspaces(name,slug,created_by)
  values ('Repair History','repair-history',v_owner) returning id into v_ws_history;

  select t.id into v_p_repair from public.create_project(
    v_ws, 'Repair Runtime', 'controlled repair', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  select t.id into v_p_scope from public.create_project(
    v_ws, 'Repair Scope', 'scope and revocation', 'evolve',
    'https://github.com/octocat/Spoon-Knife') t;
  select t.id into v_p_blank from public.create_project(
    v_ws, 'Repair Unsourced', 'no source repository', 'new') t;
  select t.id into v_p_audit from public.create_project(
    v_ws, 'Repair Audit', 'attribution lifecycle', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  select t.id into v_p_history from public.create_project(
    v_ws_history, 'Repair History', 'terminal run history', 'evolve',
    'https://github.com/octocat/Hello-World') t;

  -- Ordinary worker registrations, which is the authority a repair policy
  -- narrows. Enrolling a policy never creates one.
  perform 1 from public.register_project_worker(v_p_repair, v_worker_a, 'Repair Worker A') t;
  perform 1 from public.register_project_worker(v_p_repair, v_worker_b, 'Repair Worker B') t;
  perform 1 from public.register_project_worker(v_p_scope, v_worker_a, 'Repair Worker A') t;
  perform 1 from public.register_project_worker(v_p_audit, v_worker_a, 'Repair Worker A') t;
  perform 1 from public.register_project_worker(v_p_history, v_worker_a, 'Repair Worker A') t;

  perform set_config('oryveta.rp_ws', v_ws::text, true);
  perform set_config('oryveta.rp_ws_history', v_ws_history::text, true);
  perform set_config('oryveta.rp_p_repair', v_p_repair::text, true);
  perform set_config('oryveta.rp_p_scope', v_p_scope::text, true);
  perform set_config('oryveta.rp_p_blank', v_p_blank::text, true);
  perform set_config('oryveta.rp_p_audit', v_p_audit::text, true);
  perform set_config('oryveta.rp_p_history', v_p_history::text, true);
end
$tenancy$;

reset role;
insert into public.workspace_memberships(workspace_id,user_id,role)
values (current_setting('oryveta.rp_ws')::uuid,
        '7a222222-2222-4222-8222-222222222222','admin'),
       (current_setting('oryveta.rp_ws')::uuid,
        '7a333333-3333-4333-8333-333333333333','admin'),
       (current_setting('oryveta.rp_ws')::uuid,
        '7a444444-4444-4444-8444-444444444444','engineer'),
       (current_setting('oryveta.rp_ws')::uuid,
        '7a555555-5555-4555-8555-555555555555','viewer'),
       (current_setting('oryveta.rp_ws')::uuid,
        '7a777777-7777-4777-8777-777777777777','engineer'),
       (current_setting('oryveta.rp_ws_history')::uuid,
        '7a444444-4444-4444-8444-444444444444','engineer');
set local role authenticated;

-- ---------------------------------------------------------------------------
-- 1. Enrollment is an owner/admin decision about an already-provisioned
--    worker identity, a reviewed configuration digest and one approved commit.
--    Nothing about it is self-service, inferred or client-chosen.
-- ---------------------------------------------------------------------------
do $enrollment$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_admin uuid := '7a222222-2222-4222-8222-222222222222';
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_viewer uuid := '7a555555-5555-4555-8555-555555555555';
  v_outsider uuid := '7a666666-6666-4666-8666-666666666666';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_worker_c uuid := '7b333333-3333-4333-8333-333333333333';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_p_scope uuid := current_setting('oryveta.rp_p_scope')::uuid;
  v_p_blank uuid := current_setting('oryveta.rp_p_blank')::uuid;
  v_p_audit uuid := current_setting('oryveta.rp_p_audit')::uuid;
  v_p_history uuid := current_setting('oryveta.rp_p_history')::uuid;
  v_commit_one text := '1111111111111111111111111111111111111111';
  v_commit_two text := '2222222222222222222222222222222222222222';
  v_config_one text := repeat('ab', 32);
  v_config_two text := repeat('cd', 32);
  v_row record;
  v_pol_main uuid; v_pol_scope uuid; v_pol_audit uuid;
  v_pol_revoked uuid; v_pol_history uuid;
  v_message text;
begin
  -- An engineer, a viewer and an outsider are all refused, and the outsider's
  -- refusal is the same message as a project they cannot see.
  for v_row in select unnest(array[v_engineer, v_viewer, v_outsider]) as actor loop
    perform set_config('request.jwt.claim.sub', v_row.actor::text, true);
    v_message := null;
    begin
      perform 1 from public.register_project_repair_policy(
        v_p_repair, v_worker_a, 'Attempted', v_commit_one, v_config_one) t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from 'not allowed to manage this project' then
      raise exception 'account % enrolled or was refused unexpectedly (%)',
        v_row.actor, coalesce(v_message, 'no error');
    end if;
  end loop;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);

  -- An undesignated account cannot become a repair worker, and neither can the
  -- caller's own account.
  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_repair, v_worker_c, 'Undesignated', v_commit_one, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'that account is not a provisioned factory worker service identity' then
    raise exception 'an undesignated account was enrolled as a repair worker (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_repair, v_owner, 'Myself', v_commit_one, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'a worker must be a separate service identity, not your own account' then
    raise exception 'an admin enrolled their own account as a repair worker (%)',
      coalesce(v_message, 'no error');
  end if;

  -- A designated worker with no enabled registration for THIS project is
  -- refused: enrollment narrows an existing grant, it does not create one.
  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_blank, v_worker_a, 'Unregistered', v_commit_one, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'worker identity is not registered for this project' then
    raise exception 'a policy was enrolled for a project the worker is not registered '
      'for (%)', coalesce(v_message, 'no error');
  end if;

  -- Malformed identities are refused rather than normalized, so a
  -- transcription error cannot be hidden by the database.
  for v_row in
    select * from (values
      (repeat('A', 40), v_config_one,
       'source commit must be a 40 character lowercase hexadecimal SHA'),
      ('11111111111111111111111111111111111111', v_config_one,
       'source commit must be a 40 character lowercase hexadecimal SHA'),
      (v_commit_one, upper(v_config_one),
       'configuration digest must be 64 lowercase hexadecimal characters'),
      (v_commit_one, 'abc',
       'configuration digest must be 64 lowercase hexadecimal characters')
    ) as t(src_commit, src_config, expected)
  loop
    v_message := null;
    begin
      perform 1 from public.register_project_repair_policy(
        v_p_repair, v_worker_a, 'Malformed', v_row.src_commit, v_row.src_config) t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from v_row.expected then
      raise exception 'a malformed identity was accepted or misreported: % (%)',
        v_row.expected, coalesce(v_message, 'no error');
    end if;
  end loop;

  -- The enrollment the rest of this file uses. The frozen source identity is
  -- derived from the project's own saved source, never supplied by the caller.
  select * into v_row from public.register_project_repair_policy(
    v_p_repair, v_worker_a, 'Repair Worker A', v_commit_one, v_config_one) t;
  if v_row.id is null or not v_row.enabled then
    raise exception 'the owner could not enrol a repair policy';
  end if;
  if v_row.source_url <> 'https://github.com/octocat/Hello-World'
     or v_row.source_owner <> 'octocat' or v_row.source_repo <> 'Hello-World' then
    raise exception 'the policy did not freeze the project source identity (% % %)',
      v_row.source_url, v_row.source_owner, v_row.source_repo;
  end if;
  if v_row.source_commit <> v_commit_one
     or v_row.configuration_sha256 <> v_config_one then
    raise exception 'the policy did not freeze the approved commit and configuration';
  end if;
  if v_row.last_seen_at is not null then
    raise exception 'a freshly enrolled policy claims the worker has already been seen';
  end if;
  if v_row.created_by <> v_owner or v_row.revoked_at is not null
     or v_row.revoked_by is not null then
    raise exception 'the policy recorded the wrong enrollment attribution';
  end if;
  v_pol_main := v_row.id;

  -- Re-enrolling the identical policy is an operator mistake, not an idempotent
  -- no-op: it would silently double a worker's claim surface.
  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_repair, v_worker_a, 'Repair Worker A', v_commit_one, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'an identical enabled policy already exists for this worker, commit '
                  'and configuration' then
    raise exception 'a duplicate enabled policy was accepted (%)',
      coalesce(v_message, 'no error');
  end if;

  -- A different commit or configuration is a different decision, so it is a
  -- second policy rather than an edit of the first.
  select t.id into v_pol_revoked from public.register_project_repair_policy(
    v_p_repair, v_worker_a, 'Repair Worker A Two', v_commit_two, v_config_two) t;
  if v_pol_revoked is null or v_pol_revoked = v_pol_main then
    raise exception 'a second commit and configuration did not produce a second policy';
  end if;

  select t.id into v_pol_scope from public.register_project_repair_policy(
    v_p_scope, v_worker_a, 'Repair Worker A', v_commit_two, v_config_two) t;
  select t.id into v_pol_history from public.register_project_repair_policy(
    v_p_history, v_worker_a, 'Repair Worker A', v_commit_one, v_config_one) t;

  -- The workspace admin, not the owner, enrols this one: it is deleted later
  -- to show that attribution is not authority.
  perform set_config('request.jwt.claim.sub', v_admin::text, true);
  select t.id into v_pol_audit from public.register_project_repair_policy(
    v_p_audit, v_worker_a, 'Repair Worker A', v_commit_one, v_config_one) t;
  if v_pol_audit is null then
    raise exception 'a workspace admin could not enrol a repair policy';
  end if;

  perform set_config('oryveta.rp_pol_main', v_pol_main::text, true);
  perform set_config('oryveta.rp_pol_revoked', v_pol_revoked::text, true);
  perform set_config('oryveta.rp_pol_scope', v_pol_scope::text, true);
  perform set_config('oryveta.rp_pol_audit', v_pol_audit::text, true);
  perform set_config('oryveta.rp_pol_history', v_pol_history::text, true);
end
$enrollment$;

-- A project with no saved source has nothing to enrol, and a designated worker
-- that has become a workspace member is no longer a service identity. The
-- membership is staged by the owner role, because public.register_project_worker
-- already refuses a member and this state is otherwise unreachable.
reset role;
insert into public.workspace_memberships(workspace_id,user_id,role)
values (current_setting('oryveta.rp_ws')::uuid,
        '7b111111-1111-4111-8111-111111111111','reviewer');
set local role authenticated;

do $enrollment_scope$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_scope uuid := current_setting('oryveta.rp_p_scope')::uuid;
  v_p_blank uuid := current_setting('oryveta.rp_p_blank')::uuid;
  v_message text;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_scope, v_worker_a, 'Member Worker',
      '3333333333333333333333333333333333333333', repeat('ef', 32)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'a project or workspace member cannot also be a worker identity' then
    raise exception 'a human workspace member was enrolled as a repair worker (%)',
      coalesce(v_message, 'no error');
  end if;

  v_message := null;
  begin
    perform 1 from public.register_project_repair_policy(
      v_p_blank, v_worker_a, 'Unsourced',
      '3333333333333333333333333333333333333333', repeat('ef', 32)) t;
  exception when others then v_message := sqlerrm; end;
  -- The registration check runs first for this project, which is itself the
  -- point: an unregistered worker is refused before anything else is examined.
  if v_message is null then
    raise exception 'a policy was enrolled for a project with no source repository';
  end if;
end
$enrollment_scope$;

reset role;
delete from public.workspace_memberships m
 where m.workspace_id = current_setting('oryveta.rp_ws')::uuid
   and m.user_id = '7b111111-1111-4111-8111-111111111111';
set local role authenticated;

-- ---------------------------------------------------------------------------
-- 2. The policy read model, the absence of any client write path, and the
--    immutability of what was approved.
-- ---------------------------------------------------------------------------
do $read_model$
declare
  v_viewer uuid := '7a555555-5555-4555-8555-555555555555';
  v_outsider uuid := '7a666666-6666-4666-8666-666666666666';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_worker_b uuid := '7b222222-2222-4222-8222-222222222222';
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_state text; n integer;
begin
  -- A project viewer sees the enrollment, including the frozen commit and the
  -- configuration digest the panel displays.
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_main and k.source_commit is not null
     and k.configuration_sha256 is not null;
  if n <> 1 then raise exception 'a project viewer cannot read the enrollment'; end if;

  -- An account with no grant on the project sees nothing.
  perform set_config('request.jwt.claim.sub', v_outsider::text, true);
  select count(*) into n from public.project_repair_policies k where k.id = v_pol_main;
  if n <> 0 then raise exception 'an outsider can read another project enrollment'; end if;

  -- The bound worker identity sees its own policy; a different registered
  -- worker does not, because it is neither a project reader nor the subject.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.project_repair_policies k where k.id = v_pol_main;
  if n <> 1 then raise exception 'the bound worker cannot read its own policy'; end if;
  perform set_config('request.jwt.claim.sub', v_worker_b::text, true);
  select count(*) into n from public.project_repair_policies k where k.id = v_pol_main;
  if n <> 0 then raise exception 'an unrelated worker identity can read the policy'; end if;

  -- No client write path exists at all: not for an admin, not for the bound
  -- worker. Enrollment and revocation are RPC-only.
  perform set_config('request.jwt.claim.sub', '7a111111-1111-4111-8111-111111111111', true);
  begin
    update public.project_repair_policies k set last_seen_at = now() where k.id = v_pol_main;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'an authenticated project admin can write a repair policy directly';
  exception when insufficient_privilege then null; end;
  begin
    insert into public.project_repair_policies
      (project_id, worker_user_id, label, source_url, source_owner, source_repo,
       source_commit, configuration_sha256)
    values (current_setting('oryveta.rp_p_repair')::uuid, v_worker_a, 'Forged',
            'https://github.com/octocat/Hello-World', 'octocat', 'Hello-World',
            repeat('4', 40), repeat('0a', 32));
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'an authenticated caller can insert a repair policy directly';
  exception when insufficient_privilege then null; end;
  begin
    delete from public.project_repair_policies k where k.id = v_pol_main;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'an authenticated caller can delete a repair policy directly';
  exception when insufficient_privilege then null; end;

  -- The private fencing token is not reachable from any client role, which is
  -- what keeps a lease out of every read model.
  begin
    select count(*) into n from private.factory_run_leases;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'an authenticated caller can read lease tokens';
  exception when insufficient_privilege then null; end;
end
$read_model$;

-- anon holds nothing: no read, no RPC.
set local role anon;
do $anonymous$
declare
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', '', true);
  begin
    select count(*) into n from public.project_repair_policies k where k.id = v_pol_main;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'the anonymous role can read repair policies';
  exception when insufficient_privilege then null; end;
  begin
    perform 1 from public.submit_repository_repair(
      current_setting('oryveta.rp_p_repair')::uuid, v_pol_main, 'anonymous goal') t;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'the anonymous role can submit repair work';
  exception when insufficient_privilege then null; end;
  begin
    perform 1 from public.claim_repair_work(v_pol_main, repeat('ab', 32)) t;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'the anonymous role can claim repair work';
  exception when insufficient_privilege then null; end;
end
$anonymous$;

-- What was approved cannot be edited afterwards, not even by the table owner:
-- a different commit, a different configuration or a re-enabled revocation is
-- a new policy, not an update.
reset role;
do $immutability$
declare
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  -- The contact-time case below leaves a value behind, so it uses a policy
  -- whose contact time no later assertion depends on being unset.
  v_pol_history uuid := current_setting('oryveta.rp_pol_history')::uuid;
  v_case record;
begin
  -- Every frozen field, with the refusal it must produce. The live worker
  -- reference has a rule of its own - it may be cleared by an account
  -- deletion and nothing else - so it has a message of its own.
  for v_case in
    select * from (values
      ('set source_commit = ' || quote_literal(repeat('5', 40)),
       'a repair policy identity%'),
      ('set configuration_sha256 = ' || quote_literal(repeat('0b', 32)),
       'a repair policy identity%'),
      ('set source_url = ' || quote_literal('https://github.com/octocat/Spoon-Knife'),
       'a repair policy identity%'),
      -- The frozen enrollment identity is as immutable as the commit it
      -- approved: it is the record of which account an operator designated.
      ('set worker_identity = ' || quote_literal('7b222222-2222-4222-8222-222222222222'),
       'a repair policy identity%'),
      ('set label = ' || quote_literal('Renamed'),
       'a repair policy identity%'),
      -- Redirecting the live reference to another account is refused, and so
      -- is clearing it and re-pointing the enrollment in one statement: an
      -- offboarded identity is re-enrolled and reviewed again, never revived.
      ('set worker_user_id = ' || quote_literal('7b222222-2222-4222-8222-222222222222'),
       'a repair policy keeps the worker identity%'),
      ('set worker_user_id = null, worker_identity = ' ||
       quote_literal('7b222222-2222-4222-8222-222222222222'),
       'a repair policy identity%')
    ) as f(fragment, expected)
  loop
    begin
      execute 'update public.project_repair_policies ' || v_case.fragment
              || ' where id = ' || quote_literal(v_pol_main);
      raise exception using errcode = 'triggered_data_change_violation',
        message = 'a frozen repair policy field was edited: ' || v_case.fragment;
    exception when raise_exception then
      if sqlerrm not like v_case.expected then raise; end if;
    end;
  end loop;

  -- The two identities cannot be made to disagree, not even by the table
  -- owner: a live reference may only ever be the account that was enrolled.
  begin
    insert into public.project_repair_policies
      (project_id, worker_identity, worker_user_id, label, source_url, source_owner,
       source_repo, source_commit, configuration_sha256)
    values (current_setting('oryveta.rp_p_repair')::uuid,
            '7b111111-1111-4111-8111-111111111111',
            '7b222222-2222-4222-8222-222222222222', 'Mismatched',
            'https://github.com/octocat/Hello-World', 'octocat', 'Hello-World',
            repeat('6', 40), repeat('0c', 32));
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'a repair policy named one identity live and a different one frozen';
  exception when check_violation then null; end;

  -- A withdrawn enrollment is never re-enabled, and contact time only moves
  -- forward, so a stale or backdated write cannot make an idle worker look
  -- like it just polled.
  begin
    update public.project_repair_policies k
       set enabled = false, revoked_at = now() where k.id = v_pol_history;
    update public.project_repair_policies k
       set enabled = true, revoked_at = null where k.id = v_pol_history;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'a revoked repair policy was re-enabled';
  exception when raise_exception then
    if sqlerrm not like 'a revoked repair policy cannot be re-enabled%' then raise; end if;
  end;
  begin
    update public.project_repair_policies k
       set last_seen_at = now() - interval '1 day' where k.id = v_pol_history;
    update public.project_repair_policies k
       set last_seen_at = now() - interval '2 days' where k.id = v_pol_history;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'worker contact time was moved backwards';
  exception when raise_exception then
    if sqlerrm not like 'worker contact time only moves forward%' then raise; end if;
  end;
  -- Both refusals rolled their own subtransaction back, so the enrollment is
  -- untouched apart from the one forward contact write.
  if not exists(select 1 from public.project_repair_policies k
                 where k.id = v_pol_history and k.enabled and k.revoked_at is null) then
    raise exception 'the refused re-enable left the enrollment in a revoked state';
  end if;
end
$immutability$;
set local role authenticated;

-- ---------------------------------------------------------------------------
-- 3. Submission: engineer and above, under an enabled policy of this project,
--    against the source that was actually approved, with a bounded goal and
--    one idempotency scope.
-- ---------------------------------------------------------------------------
do $submission$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_viewer uuid := '7a555555-5555-4555-8555-555555555555';
  v_outsider uuid := '7a666666-6666-4666-8666-666666666666';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_p_scope uuid := current_setting('oryveta.rp_p_scope')::uuid;
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_pol_scope uuid := current_setting('oryveta.rp_pol_scope')::uuid;
  v_row record;
  v_item uuid;
  v_message text;
  v_actor uuid;
begin
  -- A viewer and an outsider cannot submit, and the outsider cannot tell a
  -- project they may not see from one that does not exist.
  foreach v_actor in array array[v_viewer, v_outsider] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    v_message := null;
    begin
      perform 1 from public.submit_repository_repair(v_p_repair, v_pol_main, 'fix it') t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from 'not allowed to submit work for this project' then
      raise exception 'account % submitted repair work or was misreported (%)',
        v_actor, coalesce(v_message, 'no error');
    end if;
  end loop;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);

  -- A policy belonging to another project is indistinguishable from a missing
  -- one, so policy ids are not probeable across projects.
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(v_p_repair, v_pol_scope, 'fix it') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'a policy from another project was accepted (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_repair, gen_random_uuid(), 'fix it') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'an unknown policy id was reported differently from a foreign one (%)',
      coalesce(v_message, 'no error');
  end if;

  -- The goal is bounded human text, and an empty or oversized one is refused.
  for v_row in
    select f.goal from (values
      (''), ('   '), (repeat('x', 4097)), ('control' || chr(1) || 'character')
    ) as f(goal)
  loop
    v_message := null;
    begin
      perform 1 from public.submit_repository_repair(v_p_repair, v_pol_main, v_row.goal) t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from 'goal must be 1-4096 bytes of text' then
      raise exception 'an invalid goal was accepted (%)', coalesce(v_message, 'no error');
    end if;
  end loop;

  -- A real admission. Everything the attempt will be judged against is frozen
  -- now, including the pin, which a repair item carries from the start.
  select * into v_row from public.submit_repository_repair(
    v_p_repair, v_pol_main, E'  Make add() return a + b.\n\tSee the failing case.  ',
    'repair-main-key-0001') t;
  if v_row.work_item_id is null or v_row.status <> 'queued' or v_row.replayed then
    raise exception 'the engineer could not submit a repair goal';
  end if;
  if v_row.kind <> 'repository_repair' or v_row.repair_policy_id <> v_pol_main then
    raise exception 'the admitted work item is not repair work under the named policy';
  end if;
  if v_row.max_attempts <> 2 or v_row.attempts <> 0 then
    raise exception 'a repair work item was admitted with % of % attempts',
      v_row.attempts, v_row.max_attempts;
  end if;
  if v_row.goal <> E'Make add() return a + b.\n\tSee the failing case.' then
    raise exception 'the stored goal was not the trimmed submitted text (%)', v_row.goal;
  end if;
  v_item := v_row.work_item_id;

  -- The same key replays the same work rather than queueing a second attempt.
  select * into v_row from public.submit_repository_repair(
    v_p_repair, v_pol_main, E'  Make add() return a + b.\n\tSee the failing case.  ',
    'repair-main-key-0001') t;
  if not v_row.replayed or v_row.work_item_id <> v_item then
    raise exception 'a replayed submission created new work';
  end if;

  -- The same key with a different goal, a different policy or a different kind
  -- is refused: one key describes one request.
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_repair, v_pol_main, 'a different goal entirely', 'repair-main-key-0001') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'idempotency key already used for a different input' then
    raise exception 'one idempotency key described two different goals (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_repair, current_setting('oryveta.rp_pol_revoked')::uuid,
      E'Make add() return a + b.\n\tSee the failing case.', 'repair-main-key-0001') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'idempotency key already used for a different input' then
    raise exception 'one idempotency key described two different policies (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.submit_repository_analysis(v_p_repair, 'repair-main-key-0001') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'idempotency key already used for a different input' then
    raise exception 'one idempotency key described both a repair and an analysis (%)',
      coalesce(v_message, 'no error');
  end if;
  -- And the reverse direction: an analysis key cannot be reused for a repair.
  perform 1 from public.submit_repository_analysis(v_p_repair, 'repair-analysis-key-01') t;
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_repair, v_pol_main, 'fix it', 'repair-analysis-key-01') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'idempotency key already used for a different input' then
    raise exception 'an analysis key was reused for repair work (%)',
      coalesce(v_message, 'no error');
  end if;

  perform set_config('oryveta.rp_item_main', v_item::text, true);
end
$submission$;

-- A project that has moved to another repository needs a new review: the
-- enrolled policy no longer describes its source, so new admission stops while
-- work already admitted keeps its own frozen pin.
do $source_drift$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_p_audit uuid := current_setting('oryveta.rp_p_audit')::uuid;
  v_pol_audit uuid := current_setting('oryveta.rp_pol_audit')::uuid;
  v_item uuid;
  v_message text;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  -- One item admitted while the source still matches.
  select t.work_item_id into v_item from public.submit_repository_repair(
    v_p_audit, v_pol_audit, 'Admitted before the source moved') t;
  if v_item is null then raise exception 'the pre-drift submission was refused'; end if;

  perform 1 from public.update_project(
    v_p_audit, 'Repair Audit', 'attribution lifecycle',
    'https://github.com/octocat/Spoon-Knife') t;

  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_audit, v_pol_audit, 'Admitted after the source moved') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'the project source no longer matches this policy; enroll a new policy' then
    raise exception 'a repair was admitted against a source the policy never approved (%)',
      coalesce(v_message, 'no error');
  end if;

  -- Put the project back, so the item admitted above can still be claimed.
  perform 1 from public.update_project(
    v_p_audit, 'Repair Audit', 'attribution lifecycle',
    'https://github.com/octocat/Hello-World') t;
  perform set_config('oryveta.rp_item_audit', v_item::text, true);
end
$source_drift$;

-- ---------------------------------------------------------------------------
-- 4. Claiming is bound to the policy's own worker, its project registration,
--    its service designation and its configuration digest.
-- ---------------------------------------------------------------------------
do $claim_authorization$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_worker_b uuid := '7b222222-2222-4222-8222-222222222222';
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_config_one text := repeat('ab', 32);
  v_message text;
  v_seen timestamptz;
begin
  -- A human account is not a worker, whatever else it may be allowed to do.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  v_message := null;
  begin
    perform 1 from public.claim_repair_work(v_pol_main, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from
     'worker identity is not a provisioned factory worker service identity' then
    raise exception 'a human account reached the repair claim path (%)',
      coalesce(v_message, 'no error');
  end if;

  -- A designated, registered worker that this policy does not name gets the
  -- same answer as for a policy that does not exist.
  perform set_config('request.jwt.claim.sub', v_worker_b::text, true);
  v_message := null;
  begin
    perform 1 from public.claim_repair_work(v_pol_main, v_config_one) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'an unrelated worker could address another worker policy (%)',
      coalesce(v_message, 'no error');
  end if;

  -- The bound worker must still prove which configuration it loaded.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  v_message := null;
  begin
    perform 1 from public.claim_repair_work(v_pol_main, repeat('cd', 32)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'configuration digest does not match this repair policy' then
    raise exception 'a worker claimed work with the wrong configuration (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.claim_repair_work(v_pol_main, upper(v_config_one)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'configuration digest must be 64 lowercase hexadecimal characters' then
    raise exception 'an uppercase configuration digest was normalized (%)',
      coalesce(v_message, 'no error');
  end if;

  -- None of the refusals above counts as contact.
  select k.last_seen_at into v_seen from public.project_repair_policies k
   where k.id = v_pol_main;
  if v_seen is not null then
    raise exception 'a refused claim was recorded as worker contact';
  end if;
end
$claim_authorization$;

-- An authorized claim that finds nothing still records contact, because the
-- credential did poll. A policy with no queued work is the idle case.
do $idle_contact$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_pol_scope uuid := current_setting('oryveta.rp_pol_scope')::uuid;
  v_claim record;
  v_seen timestamptz;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol_scope, repeat('cd', 32), 300) t;
  if v_claim.run_id is not null then
    raise exception 'an idle policy handed out work it has none of';
  end if;
  select k.last_seen_at into v_seen from public.project_repair_policies k
   where k.id = v_pol_scope;
  if v_seen is null then
    raise exception 'an authorized idle poll was not recorded as worker contact';
  end if;
end
$idle_contact$;

-- ---------------------------------------------------------------------------
-- 5. Two task kinds, one queue, no crossing over. The analysis claim never
--    sees repair work, the repair claim never sees analysis work, and the
--    analysis completion and failure APIs refuse a repair attempt outright.
-- ---------------------------------------------------------------------------
do $mixed_kind$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_item_main uuid := current_setting('oryveta.rp_item_main')::uuid;
  v_config_one text := repeat('ab', 32);
  v_claim record;
  v_analysis record;
  v_run_main uuid;
  v_token_main uuid;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);

  -- There is one queued analysis item and one queued repair item in this
  -- project. The analysis claim must take the analysis one.
  select count(*) into n from public.work_items w
   where w.project_id = v_p_repair and w.status = 'queued';
  if n <> 2 then
    raise exception 'the mixed-kind fixture does not have both kinds queued (% queued)', n;
  end if;
  select * into v_analysis from public.claim_analysis_work(v_p_repair, 300) t;
  if v_analysis.run_id is null then
    raise exception 'the analysis claim stopped working';
  end if;
  if v_analysis.work_item_id = v_item_main or v_analysis.kind <> 'repository_analysis' then
    raise exception 'the analysis claim handed out repair work (% %)',
      v_analysis.work_item_id, v_analysis.kind;
  end if;

  -- And the repair claim must take the repair one, with the whole frozen
  -- binding the worker validates before it fetches anything.
  select * into v_claim from public.claim_repair_work(v_pol_main, v_config_one, 300) t;
  if v_claim.run_id is null then raise exception 'the repair claim handed out nothing'; end if;
  if v_claim.work_item_id <> v_item_main or v_claim.kind <> 'repository_repair' then
    raise exception 'the repair claim handed out % of kind %',
      v_claim.work_item_id, v_claim.kind;
  end if;
  if v_claim.attempt <> 1 or v_claim.max_attempts <> 2 then
    raise exception 'the repair attempt is % of %', v_claim.attempt, v_claim.max_attempts;
  end if;
  if v_claim.project_id <> v_p_repair or v_claim.repair_policy_id <> v_pol_main
     or v_claim.configuration_sha256 <> v_config_one then
    raise exception 'the claim did not hand back the policy binding';
  end if;
  if v_claim.source_url <> 'https://github.com/octocat/Hello-World'
     or v_claim.source_owner <> 'octocat' or v_claim.source_repo <> 'Hello-World'
     or v_claim.pinned_source_ref <> 'github.com/octocat/Hello-World'
     or v_claim.pinned_source_commit <> repeat('1', 40) then
    raise exception 'the claim did not hand back the frozen approved snapshot';
  end if;
  if v_claim.goal is null or octet_length(v_claim.goal) > 4096 then
    raise exception 'the claim did not hand back a bounded goal';
  end if;
  if v_claim.previous_source_digest is not null
     or v_claim.previous_checkpoint <> '{}'::jsonb then
    raise exception 'a first attempt was handed a previous attempt progress record';
  end if;
  if v_claim.lease_token is null or v_claim.lease_expires_at <= clock_timestamp() then
    raise exception 'the repair claim handed out an expired or tokenless lease';
  end if;
  v_run_main := v_claim.run_id;
  v_token_main := v_claim.lease_token;

  -- The repair claim takes nothing else: the analysis attempt is not its work,
  -- and there is no second queued repair item.
  select * into v_claim from public.claim_repair_work(v_pol_main, v_config_one, 300) t;
  if v_claim.run_id is not null then
    raise exception 'the repair claim handed out a second attempt of the same work';
  end if;

  perform set_config('oryveta.rp_run_analysis', v_analysis.run_id::text, true);
  perform set_config('oryveta.rp_token_analysis', v_analysis.lease_token::text, true);
  perform set_config('oryveta.rp_item_analysis', v_analysis.work_item_id::text, true);
  -- The lease token is carried from the claim's own return value, which is the
  -- only place a worker ever sees one; nothing here reads private.
  perform set_config('oryveta.rp_run_main', v_run_main::text, true);
  perform set_config('oryveta.rp_token_main', v_token_main::text, true);
end
$mixed_kind$;

-- Each analysis RPC refuses the live repair attempt.
do $cross_api$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_item_main uuid := current_setting('oryveta.rp_item_main')::uuid;
  v_run uuid := current_setting('oryveta.rp_run_main')::uuid;
  v_token uuid := current_setting('oryveta.rp_token_main')::uuid;
  v_beat record; v_finish record; v_fail record;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);

  select * into v_beat from public.heartbeat_analysis_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'analyzing') t;
  if v_beat.lease_valid or v_beat.reason <> 'wrong_kind' then
    raise exception 'the analysis heartbeat accepted a repair attempt (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  select * into v_finish from public.finish_analysis_run(
    v_run, v_token, '{"summary":{"source_files_analyzed":1},"findings":[]}'::jsonb) t;
  if v_finish.accepted or v_finish.reason <> 'wrong_kind' then
    raise exception 'the analysis completion published a result onto a repair attempt (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;

  select * into v_fail from public.fail_analysis_run(v_run, v_token, 'analysis_failed') t;
  if v_fail.accepted or v_fail.reason <> 'wrong_kind' then
    raise exception 'the analysis failure path settled a repair attempt (%)',
      coalesce(v_fail.reason, 'no reason');
  end if;

  -- None of the three touched anything.
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'running' and r.phase = 'claimed'
     and r.result is null and r.error_code is null;
  if n <> 1 then raise exception 'a refused analysis call still changed the repair attempt'; end if;
  select count(*) into n from public.work_items w
   where w.id = v_item_main and w.status = 'running' and w.attempts = 1;
  if n <> 1 then raise exception 'a refused analysis call still changed the repair work item'; end if;

  perform set_config('oryveta.rp_run_main', v_run::text, true);
  perform set_config('oryveta.rp_token_main', v_token::text, true);
end
$cross_api$;

-- And the repair RPCs refuse an analysis attempt in the same way.
do $cross_api_reverse$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_run uuid := current_setting('oryveta.rp_run_analysis')::uuid;
  v_token uuid := current_setting('oryveta.rp_token_analysis')::uuid;
  v_beat record; v_fail record;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'repairing') t;
  if v_beat.lease_valid or v_beat.reason <> 'wrong_kind' then
    raise exception 'the repair heartbeat accepted an analysis attempt (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  select * into v_fail from public.fail_repair_run(v_run, v_token, 'repair_failed') t;
  if v_fail.accepted or v_fail.reason <> 'wrong_kind' then
    raise exception 'the repair failure path settled an analysis attempt (%)',
      coalesce(v_fail.reason, 'no reason');
  end if;
end
$cross_api_reverse$;

-- ---------------------------------------------------------------------------
-- 6. Progress: bounded checkpoints, the fixed step enum, the write-once source
--    identity and the pin the attempt may not leave.
-- ---------------------------------------------------------------------------
do $progress$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_run uuid := current_setting('oryveta.rp_run_main')::uuid;
  v_token uuid := current_setting('oryveta.rp_token_main')::uuid;
  v_commit_one text := repeat('1', 40);
  v_config_one text := repeat('ab', 32);
  v_beat record;
  v_row record;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);

  -- A stale or absent token is a lost lease, reported rather than raised, so
  -- the worker has an unambiguous signal to stop its child process group.
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => gen_random_uuid(),
    p_phase => 'fetching_source') t;
  if v_beat.lease_valid or v_beat.reason <> 'lease_lost' then
    raise exception 'a heartbeat with a forged lease token was accepted (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  -- An analysis phase is not a repair phase.
  v_message := null;
  begin
    perform 1 from public.heartbeat_repair_run(
      p_run_id => v_run, p_lease_token => v_token, p_phase => 'analyzing') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'unknown run phase' then
    raise exception 'a repair attempt accepted an analysis phase (%)',
      coalesce(v_message, 'no error');
  end if;

  -- The checkpoint is a closed contract: unknown keys, nested values, unknown
  -- steps and out-of-range counters are all refused, not ignored.
  for v_row in
    select * from (values
      ('{"step":"repairing","prompt":"you are a helpful"}'::jsonb,
       'checkpoint field prompt is not part of the repair progress contract'),
      ('{"step":"model_call"}'::jsonb, 'checkpoint step is not a known repair step'),
      ('{"step":"done"}'::jsonb, 'checkpoint step is not a known repair step'),
      ('{"turns":{"a":1}}'::jsonb, 'checkpoint field turns must be a number'),
      ('{"turns":-1}'::jsonb, 'checkpoint field turns must be between 0 and 50'),
      ('{"turns":51}'::jsonb, 'checkpoint field turns must be between 0 and 50'),
      ('{"turns":1.5}'::jsonb, 'checkpoint field turns must be a whole number'),
      ('{"tool_calls":101}'::jsonb, 'checkpoint field tool_calls must be between 0 and 100'),
      ('{"tokens_observed":500001}'::jsonb,
       'checkpoint field tokens_observed must be between 0 and 500000'),
      ('{"source_commit":"not-a-sha"}'::jsonb,
       'checkpoint source_commit must be a 40 character hexadecimal SHA'),
      ('{"configuration_sha256":"short"}'::jsonb,
       'checkpoint configuration_sha256 must be 64 hexadecimal characters'),
      ('{"source_pinned":"yes"}'::jsonb, 'checkpoint source_pinned must be a boolean'),
      ('[]'::jsonb, 'checkpoint must be a JSON object')
    ) as t(checkpoint, expected)
  loop
    v_message := null;
    begin
      perform 1 from public.heartbeat_repair_run(
        p_run_id => v_run, p_lease_token => v_token, p_checkpoint => v_row.checkpoint) t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from v_row.expected then
      raise exception 'checkpoint % was accepted or misreported (expected %, got %)',
        v_row.checkpoint, v_row.expected, coalesce(v_message, 'no error');
    end if;
  end loop;

  -- The real progress sequence, with the whole resolved snapshot identity.
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'fetching_source',
    p_checkpoint => jsonb_build_object('step', 'fetching_source',
      'source_pinned', true, 'configuration_sha256', v_config_one)) t;
  if not v_beat.lease_valid or v_beat.phase <> 'fetching_source' then
    raise exception 'the first repair heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  -- A commit other than the frozen pin is refused: the worker would be
  -- reporting bytes this request never authorized.
  v_message := null;
  begin
    perform 1 from public.heartbeat_repair_run(
      p_run_id => v_run, p_lease_token => v_token,
      p_source_ref => 'github.com/octocat/Hello-World',
      p_source_commit => repeat('9', 40),
      p_source_digest => 'sha256:' || repeat('0f', 32)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'source identity conflicts with the work item pin' then
    raise exception 'an attempt reported a commit outside its pin (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.heartbeat_repair_run(
      p_run_id => v_run, p_lease_token => v_token,
      p_source_ref => 'github.com/octocat/Spoon-Knife',
      p_source_commit => v_commit_one,
      p_source_digest => 'sha256:' || repeat('0f', 32)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'source identity conflicts with the work item pin' then
    raise exception 'an attempt reported another repository (%)',
      coalesce(v_message, 'no error');
  end if;

  -- The approved snapshot, recorded once.
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'repairing',
    p_source_ref => 'github.com/octocat/Hello-World',
    p_source_commit => v_commit_one,
    p_source_digest => 'sha256:' || repeat('0f', 32),
    p_checkpoint => jsonb_build_object('step', 'repairing', 'turns', 3,
      'tool_calls', 7, 'tokens_observed', 4096, 'unsettled_token_reservation', 0,
      'elapsed_seconds', 12.5, 'archive_bytes', 20480, 'archive_entries', 42,
      'source_commit', v_commit_one, 'configuration_sha256', v_config_one,
      'source_pinned', true)) t;
  if not v_beat.lease_valid or v_beat.phase <> 'repairing' then
    raise exception 'the repair progress heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  -- Re-reporting the same identity is an ordinary heartbeat; changing it is not.
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'verifying',
    p_source_ref => 'github.com/octocat/Hello-World',
    p_source_commit => v_commit_one,
    p_source_digest => 'sha256:' || repeat('0f', 32)) t;
  if not v_beat.lease_valid or v_beat.phase <> 'verifying' then
    raise exception 're-reporting the recorded snapshot was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  v_message := null;
  begin
    perform 1 from public.heartbeat_repair_run(
      p_run_id => v_run, p_lease_token => v_token,
      p_source_digest => 'sha256:' || repeat('1e', 32)) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'source identity already recorded for this attempt' then
    raise exception 'an attempt rewrote the archive digest it had already recorded (%)',
      coalesce(v_message, 'no error');
  end if;

  -- Progress is on record, and contact moved with it.
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'phase_changed'
     and e.phase in ('fetching_source','repairing','verifying');
  if n <> 3 then raise exception 'the repair phases were not recorded (% events)', n; end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.phase = 'verifying'
     and r.checkpoint->>'step' = 'repairing'
     and r.source_commit = v_commit_one;
  if n <> 1 then raise exception 'the durable progress record is not what was reported'; end if;
  select count(*) into n from public.project_repair_policies k
   where k.id = current_setting('oryveta.rp_pol_main')::uuid and k.last_seen_at is not null;
  if n <> 1 then raise exception 'a valid heartbeat was not recorded as worker contact'; end if;
end
$progress$;

-- ---------------------------------------------------------------------------
-- 7. Publication: the only result shape that exists is a verified candidate
--    awaiting review, with an untruncated hash-verified patch.
-- ---------------------------------------------------------------------------
do $result_validation$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_run uuid := current_setting('oryveta.rp_run_main')::uuid;
  v_token uuid := current_setting('oryveta.rp_token_main')::uuid;
  v_commit_one text := repeat('1', 40);
  v_config_one text := repeat('ab', 32);
  v_patch text :=
    '--- a/calculator.py' || E'\n' ||
    '+++ b/calculator.py' || E'\n' ||
    '@@ -1,2 +1,2 @@' || E'\n' ||
    ' def add(a, b):' || E'\n' ||
    '-    return a - b' || E'\n' ||
    '+    return a + b' || E'\n';
  v_result jsonb;
  v_row record;
  v_outcome record;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  v_result := jsonb_build_object(
    'kind', 'repository_repair', 'status', 'needs_review', 'verification', 'passed',
    'configuration_sha256', v_config_one, 'source_commit', v_commit_one,
    'source_tree_sha256', repeat('0f', 32), 'candidate_tree_sha256', repeat('1e', 32),
    'patch_sha256', encode(sha256(convert_to(v_patch, 'UTF8')), 'hex'),
    'patch', v_patch, 'checks_passed', 4, 'turns', 3, 'tool_calls', 7,
    'tokens_observed', 4096, 'model_name', 'qwen2.5-coder:7b',
    'model_digest', repeat('9a', 32));

  -- Everything that is not a verified, bounded, hash-consistent candidate is
  -- refused before any state is touched.
  for v_row in
    select * from (values
      (v_result - 'patch', 'repair result is missing patch'),
      (v_result - 'model_digest', 'repair result is missing model_digest'),
      (v_result || '{"stdout":"check output"}'::jsonb,
       'repair result may only contain the bounded receipt fields'),
      (v_result || '{"status":"fixed"}'::jsonb,
       'a persisted repair result is always needs_review'),
      (v_result || '{"verification":"not_accepted"}'::jsonb,
       'an unverified repair candidate is not a result'),
      (v_result || '{"kind":"repository_analysis"}'::jsonb,
       'repair result kind must be repository_repair'),
      (v_result || '{"turns":"three"}'::jsonb,
       'repair result fields have the wrong JSON types'),
      (v_result || '{"checks_passed":0}'::jsonb,
       'repair result checks_passed is outside its bound or not a whole number'),
      (v_result || '{"checks_passed":49}'::jsonb,
       'repair result checks_passed is outside its bound or not a whole number'),
      (v_result || '{"turns":51}'::jsonb,
       'repair result turns is outside its bound or not a whole number'),
      (v_result || '{"tool_calls":101}'::jsonb,
       'repair result tool_calls is outside its bound or not a whole number'),
      (v_result || '{"tokens_observed":500001}'::jsonb,
       'repair result tokens_observed is outside its bound or not a whole number'),
      (v_result || '{"source_commit":"0123456789"}'::jsonb,
       'repair result source_commit must be a 40 character hexadecimal SHA'),
      (v_result || jsonb_build_object('model_digest', upper(repeat('9a', 32))),
       'repair result hashes must be 64 lowercase hexadecimal characters'),
      (v_result || '{"model_name":"../../etc/passwd"}'::jsonb,
       'repair result model_name is not a plain local model name'),
      (v_result || jsonb_build_object('candidate_tree_sha256', repeat('0f', 32)),
       'a repair result whose candidate tree equals its source tree changed nothing, '
       'so it is not a candidate'),
      (v_result || '{"patch":""}'::jsonb,
       'a repair result must carry its patch; metadata alone is not a result'),
      (v_result || jsonb_build_object('patch', v_patch || 'tampered'),
       'repair result patch does not match its patch_sha256')
    ) as t(result, expected)
  loop
    v_message := null;
    begin
      perform 1 from public.finish_repair_run(v_run, v_token, v_row.result) t;
    exception when others then v_message := sqlerrm; end;
    if v_message is distinct from v_row.expected then
      raise exception 'an invalid repair result was accepted or misreported '
        '(expected %, got %)', v_row.expected, coalesce(v_message, 'no error');
    end if;
  end loop;

  -- An over-limit patch is refused, never truncated.
  v_message := null;
  begin
    perform 1 from public.finish_repair_run(v_run, v_token,
      v_result || jsonb_build_object('patch', repeat('a', 70000), 'patch_sha256',
        encode(sha256(convert_to(repeat('a', 70000), 'UTF8')), 'hex'))) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is null or v_message not like 'repair result patch is 70000 bytes%' then
    raise exception 'a 70000 byte patch was not refused by the 64 KiB limit (%)',
      coalesce(v_message, 'no error');
  end if;
  v_message := null;
  begin
    perform 1 from public.finish_repair_run(v_run, v_token,
      v_result || jsonb_build_object('patch', repeat('a', 250000), 'patch_sha256',
        encode(sha256(convert_to(repeat('a', 250000), 'UTF8')), 'hex'))) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is null
     or (v_message not like '%192 KiB persisted limit%'
         and v_message not like 'repair result patch is 250000 bytes%') then
    raise exception 'a 250000 byte result was not refused by either bound (%)',
      coalesce(v_message, 'no error');
  end if;

  -- A structurally valid result that was not computed from this policy's
  -- configuration, or not from the pinned commit, is a typed refusal rather
  -- than an exception: the worker must stop, not retry blindly.
  select * into v_outcome from public.finish_repair_run(v_run, v_token,
    v_result || jsonb_build_object('configuration_sha256', repeat('cd', 32))) t;
  if v_outcome.accepted or v_outcome.reason <> 'configuration_mismatch' then
    raise exception 'a result computed from another configuration was accepted (%)',
      coalesce(v_outcome.reason, 'no reason');
  end if;
  select * into v_outcome from public.finish_repair_run(v_run, v_token,
    v_result || jsonb_build_object('source_commit', repeat('2', 40))) t;
  if v_outcome.accepted or v_outcome.reason <> 'source_identity_conflict' then
    raise exception 'a result computed from another commit was accepted (%)',
      coalesce(v_outcome.reason, 'no reason');
  end if;

  -- Nothing above published anything.
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'running' and r.result is null;
  if n <> 1 then raise exception 'a refused completion still wrote a result'; end if;

  -- The real publication.
  select * into v_outcome from public.finish_repair_run(v_run, v_token, v_result) t;
  if not v_outcome.accepted or v_outcome.work_item_status <> 'succeeded' then
    raise exception 'a verified repair candidate was refused (%)',
      coalesce(v_outcome.reason, 'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'succeeded' and r.phase = 'done'
     and r.finished_at is not null and r.error_code is null
     and r.result->>'status' = 'needs_review' and r.result->>'verification' = 'passed'
     and r.result->>'patch' = v_patch
     and r.result->>'patch_sha256' = encode(sha256(convert_to(v_patch,'UTF8')),'hex');
  if n <> 1 then
    raise exception 'the stored repair result is not the verified candidate that was '
      'published';
  end if;
  select count(*) into n from public.work_items w
   where w.id = current_setting('oryveta.rp_item_main')::uuid
     and w.status = 'succeeded' and w.error_code is null and w.attempts = 1;
  if n <> 1 then raise exception 'the repair work item did not succeed on its first attempt'; end if;
  -- Succeeded means ready for review, and the event log says so in those words.
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'succeeded' and e.phase = 'done'
     and e.detail like 'needs_review %';
  if n <> 1 then raise exception 'the success event does not record a reviewable candidate'; end if;

  -- A second completion of the same attempt is refused.
  select * into v_outcome from public.finish_repair_run(v_run, v_token, v_result) t;
  if v_outcome.accepted or v_outcome.reason <> 'not_running' then
    raise exception 'a settled attempt was completed twice (%)',
      coalesce(v_outcome.reason, 'no reason');
  end if;
end
$result_validation$;

-- The fencing token of the completed attempt is gone, so no late call of it
-- can do anything. Only the table owner can look: no client role holds any
-- privilege on private.factory_run_leases, which is checked above.
reset role;
do $lease_released$
declare
  v_run uuid := current_setting('oryveta.rp_run_main')::uuid;
  n integer;
begin
  select count(*) into n from private.factory_run_leases l where l.run_id = v_run;
  if n <> 0 then raise exception 'a completed repair attempt kept its lease token'; end if;
end
$lease_released$;
set local role authenticated;

-- The published patch is readable by the project's members and by nobody else.
do $result_visibility$
declare
  v_viewer uuid := '7a555555-5555-4555-8555-555555555555';
  v_outsider uuid := '7a666666-6666-4666-8666-666666666666';
  v_run uuid := current_setting('oryveta.rp_run_main')::uuid;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.result->>'patch' is not null;
  if n <> 1 then raise exception 'a project viewer cannot read the published candidate'; end if;
  perform set_config('request.jwt.claim.sub', v_outsider::text, true);
  select count(*) into n from public.factory_runs r where r.id = v_run;
  if n <> 0 then raise exception 'an outsider can read another project candidate'; end if;
end
$result_visibility$;

-- ---------------------------------------------------------------------------
-- 8. Generic cancellation fences repair work exactly as it fences analysis
--    work, and a cancelled attempt can publish nothing afterwards.
-- ---------------------------------------------------------------------------
do $cancellation$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_config_one text := repeat('ab', 32);
  v_item uuid; v_claim record; v_cancel record; v_beat record; v_finish record;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_item from public.submit_repository_repair(
    v_p_repair, v_pol_main, 'Cancel this one while it runs') t;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol_main, v_config_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the cancellation fixture claimed the wrong work item';
  end if;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select * into v_cancel from public.cancel_work_item(v_item) t;
  if v_cancel.status <> 'cancelled' or v_cancel.fenced_runs <> 1 then
    raise exception 'cancelling repair work fenced % attempts', v_cancel.fenced_runs;
  end if;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_claim.run_id, p_lease_token => v_claim.lease_token,
    p_phase => 'verifying') t;
  if v_beat.lease_valid or v_beat.reason <> 'cancelled' then
    raise exception 'a heartbeat after cancellation was accepted (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  select * into v_finish from public.finish_repair_run(
    v_claim.run_id, v_claim.lease_token, jsonb_build_object(
      'kind','repository_repair','status','needs_review','verification','passed',
      'configuration_sha256',v_config_one,'source_commit',repeat('1',40),
      'source_tree_sha256',repeat('0f',32),'candidate_tree_sha256',repeat('1e',32),
      'patch_sha256',encode(sha256(convert_to('diff','UTF8')),'hex'),'patch','diff',
      'checks_passed',1,'turns',1,'tool_calls',0,'tokens_observed',0,
      'model_name','qwen2.5-coder:7b','model_digest',repeat('9a',32))) t;
  if v_finish.accepted or v_finish.reason <> 'cancelled' then
    raise exception 'a cancelled attempt published a candidate (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_claim.run_id and r.status = 'cancelled' and r.result is null;
  if n <> 1 then raise exception 'the cancelled attempt is not terminal and empty'; end if;
  -- Nothing is left queued for the worker either.
  select * into v_claim from public.claim_repair_work(v_pol_main, v_config_one, 300) t;
  if v_claim.run_id is not null then
    raise exception 'a cancelled work item was handed out again';
  end if;
end
$cancellation$;

-- ---------------------------------------------------------------------------
-- 9. Revoking an enrollment settles the work it authorized instead of leaving
--    it queued forever, and a revoked policy can publish nothing.
-- ---------------------------------------------------------------------------
do $policy_revocation$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_revoker uuid := '7a333333-3333-4333-8333-333333333333';
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_viewer uuid := '7a555555-5555-4555-8555-555555555555';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_pol uuid := current_setting('oryveta.rp_pol_revoked')::uuid;
  v_config_two text := repeat('cd', 32);
  v_item_running uuid; v_item_queued uuid;
  v_claim record; v_revoke record; v_beat record; v_fail record;
  v_message text; n integer;
begin
  -- Two items under the policy that is about to be withdrawn: one running, one
  -- still waiting.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_item_running from public.submit_repository_repair(
    v_p_repair, v_pol, 'Running when the policy is withdrawn') t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol, v_config_two, 300) t;
  if v_claim.work_item_id <> v_item_running then
    raise exception 'the revocation fixture claimed the wrong item';
  end if;
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_item_queued from public.submit_repository_repair(
    v_p_repair, v_pol, 'Queued when the policy is withdrawn') t;

  -- A viewer and the bound worker itself cannot withdraw an enrollment.
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  v_message := null;
  begin perform 1 from public.revoke_project_repair_policy(v_pol) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'a project viewer revoked an enrollment (%)',
      coalesce(v_message, 'no error');
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  v_message := null;
  begin perform 1 from public.revoke_project_repair_policy(v_pol) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'the worker identity revoked its own enrollment (%)',
      coalesce(v_message, 'no error');
  end if;

  -- The workspace admin withdraws it.
  perform set_config('request.jwt.claim.sub', v_revoker::text, true);
  select * into v_revoke from public.revoke_project_repair_policy(v_pol) t;
  if v_revoke.enabled or v_revoke.fenced_runs <> 1 then
    raise exception 'withdrawing an enrollment fenced % attempts and reported enabled=%',
      v_revoke.fenced_runs, v_revoke.enabled;
  end if;
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol and not k.enabled and k.revoked_at is not null
     and k.revoked_by = v_revoker;
  if n <> 1 then raise exception 'the withdrawn enrollment was not recorded as revoked'; end if;

  -- Both items are settled, with a reason, and neither is left waiting.
  select count(*) into n from public.work_items w
   where w.id in (v_item_running, v_item_queued)
     and w.status = 'failed' and w.error_code = 'policy_revoked';
  if n <> 2 then
    raise exception 'withdrawing an enrollment left % of its 2 work items unsettled',
      2 - n;
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_claim.run_id and r.status = 'cancelled'
     and r.error_code = 'policy_revoked' and r.finished_at is not null;
  if n <> 1 then raise exception 'the running attempt was not fenced by the revocation'; end if;

  -- The worker learns why, and can neither publish nor claim any more.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_claim.run_id, p_lease_token => v_claim.lease_token,
    p_phase => 'verifying') t;
  if v_beat.lease_valid or v_beat.reason <> 'policy_revoked' then
    raise exception 'a heartbeat under a withdrawn enrollment was accepted (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  select * into v_fail from public.fail_repair_run(
    v_claim.run_id, v_claim.lease_token, 'repair_failed') t;
  if v_fail.accepted or v_fail.reason <> 'policy_revoked' then
    raise exception 'a failure report under a withdrawn enrollment was accepted (%)',
      coalesce(v_fail.reason, 'no reason');
  end if;
  v_message := null;
  begin perform 1 from public.claim_repair_work(v_pol, v_config_two, 300) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy is disabled' then
    raise exception 'a withdrawn enrollment still hands out work (%)',
      coalesce(v_message, 'no error');
  end if;

  -- And no new goal can be submitted under it.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(v_p_repair, v_pol, 'after revocation') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy is disabled' then
    raise exception 'a goal was admitted under a withdrawn enrollment (%)',
      coalesce(v_message, 'no error');
  end if;
end
$policy_revocation$;

-- ---------------------------------------------------------------------------
-- 10. Revoking the worker registration settles the repair work it orphans,
--     while the analysis retry semantics it already had stay exactly as they
--     were.
-- ---------------------------------------------------------------------------
do $worker_revocation$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_scope uuid := current_setting('oryveta.rp_p_scope')::uuid;
  v_pol_scope uuid := current_setting('oryveta.rp_pol_scope')::uuid;
  v_config_two text := repeat('cd', 32);
  v_item_repair uuid; v_item_analysis uuid;
  v_claim record; v_analysis record; v_revoke record;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_item_repair from public.submit_repository_repair(
    v_p_scope, v_pol_scope, 'Queued when the worker is revoked') t;
  select t.work_item_id into v_item_analysis
    from public.submit_repository_analysis(v_p_scope) t;

  -- An analysis attempt is running when the registration is withdrawn, which
  -- is the behaviour this migration must not have changed.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_analysis from public.claim_analysis_work(v_p_scope, 300) t;
  if v_analysis.work_item_id <> v_item_analysis then
    raise exception 'the analysis fixture claimed the wrong item';
  end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select * into v_revoke from public.revoke_project_worker(v_p_scope, v_worker_a) t;
  if v_revoke.enabled or v_revoke.fenced_runs <> 1 then
    raise exception 'revoking the registration fenced % attempts', v_revoke.fenced_runs;
  end if;

  -- Unchanged analysis semantics: the attempt is fenced and the work item gets
  -- its remaining attempt back.
  select count(*) into n from public.work_items w
   where w.id = v_item_analysis and w.status = 'queued' and w.error_code = 'worker_revoked';
  if n <> 1 then
    raise exception 'a revoked worker no longer requeues analysis work for another worker';
  end if;
  -- New: repair work bound to that identity cannot be claimed by anyone ever
  -- again, so it is settled with a reason instead of waiting forever.
  select count(*) into n from public.work_items w
   where w.id = v_item_repair and w.status = 'failed' and w.error_code = 'worker_revoked';
  if n <> 1 then
    raise exception 'queued repair work survived the revocation of the only worker that '
      'could run it';
  end if;

  -- REGRESSION, the reverse commit order of the race in
  -- supabase/tests/controlled_repair_races.psql: admission re-derives the
  -- bound worker's authority, so once the registration is withdrawn no new
  -- goal is admitted under its enrollments at all. The enrollment itself is
  -- still enabled here, which is the whole point - before this check the
  -- submission succeeded and queued work that public.claim_repair_work then
  -- refused to hand to the only identity allowed to consume it, leaving a
  -- queue nobody could ever drain.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_p_scope, v_pol_scope, 'Submitted after the bound worker was revoked') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'the worker identity bound to this repair policy is no longer '
                  'registered for this project' then
    raise exception 'a goal was admitted under an enrollment whose worker registration '
      'was revoked (%)', coalesce(v_message, 'no error');
  end if;
  -- Read back as the project's owner, whose read model covers every work item
  -- of the project, so an empty queue here is an empty queue and not a row
  -- that row-level security merely hid from the submitter.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  if not exists(select 1 from public.project_repair_policies k
                 where k.id = v_pol_scope and k.enabled) then
    raise exception 'this case must refuse admission while the enrollment itself is '
      'still enabled, otherwise it proves nothing new';
  end if;
  select count(*) into n from public.work_items w
   where w.repair_policy_id = v_pol_scope and w.status in ('queued','running');
  if n <> 0 then
    raise exception '% repair items are live under an enrollment whose worker was '
      'revoked', n;
  end if;
  -- The other half of the same conjunction: the identity cannot consume either.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  v_message := null;
  begin perform 1 from public.claim_repair_work(v_pol_scope, v_config_two, 300) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'worker identity is not registered for this project' then
    raise exception 'a revoked registration still claims repair work (%)',
      coalesce(v_message, 'no error');
  end if;
end
$worker_revocation$;

-- ---------------------------------------------------------------------------
-- 11. The submitter's authority is re-checked on every protected transition,
--     not only at submission.
-- ---------------------------------------------------------------------------
do $creator_authority$
declare
  v_demoted uuid := '7a777777-7777-4777-8777-777777777777';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_repair uuid := current_setting('oryveta.rp_p_repair')::uuid;
  v_pol_main uuid := current_setting('oryveta.rp_pol_main')::uuid;
  v_config_one text := repeat('ab', 32);
  v_item uuid; v_claim record;
begin
  perform set_config('request.jwt.claim.sub', v_demoted::text, true);
  select t.work_item_id into v_item from public.submit_repository_repair(
    v_p_repair, v_pol_main, 'Submitted by an engineer who is about to be demoted') t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol_main, v_config_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the creator-authority fixture claimed the wrong item';
  end if;
  perform set_config('oryveta.rp_item_demoted', v_item::text, true);
  perform set_config('oryveta.rp_run_demoted', v_claim.run_id::text, true);
  perform set_config('oryveta.rp_token_demoted', v_claim.lease_token::text, true);
end
$creator_authority$;

reset role;
update public.workspace_memberships m set role = 'viewer'
 where m.workspace_id = current_setting('oryveta.rp_ws')::uuid
   and m.user_id = '7a777777-7777-4777-8777-777777777777';
set local role authenticated;

do $creator_authority_lost$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_item uuid := current_setting('oryveta.rp_item_demoted')::uuid;
  v_run uuid := current_setting('oryveta.rp_run_demoted')::uuid;
  v_token uuid := current_setting('oryveta.rp_token_demoted')::uuid;
  v_beat record; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'repairing') t;
  if v_beat.lease_valid or v_beat.reason <> 'creator_unauthorized' then
    raise exception 'a repair continued for a submitter who lost the editing role (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = v_item and w.status = 'failed' and w.error_code = 'creator_unauthorized';
  if n <> 1 then
    raise exception 'the work item of a deauthorized submitter was not failed terminally';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'cancelled' and r.error_code = 'creator_unauthorized';
  if n <> 1 then raise exception 'the attempt of a deauthorized submitter was not fenced'; end if;
end
$creator_authority_lost$;

-- ---------------------------------------------------------------------------
-- 12. Lease expiry, reclaim, the stale token of the reclaimed attempt, and the
--     two-attempt budget a repair work item is admitted with.
-- ---------------------------------------------------------------------------
do $retry_setup$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_audit uuid := current_setting('oryveta.rp_p_audit')::uuid;
  v_pol_audit uuid := current_setting('oryveta.rp_pol_audit')::uuid;
  v_config_one text := repeat('ab', 32);
  v_item uuid := current_setting('oryveta.rp_item_audit')::uuid;
  v_claim record;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol_audit, v_config_one, 300) t;
  if v_claim.work_item_id <> v_item or v_claim.attempt <> 1 then
    raise exception 'the retry fixture claimed % as attempt %',
      v_claim.work_item_id, v_claim.attempt;
  end if;
  perform set_config('oryveta.rp_run_retry', v_claim.run_id::text, true);
  perform set_config('oryveta.rp_token_retry', v_claim.lease_token::text, true);
end
$retry_setup$;

-- The deadline is placed a few hundred milliseconds into the future of the
-- wall clock and then waited out. It is still in the future of now(), so only
-- a wall-clock comparison can call it expired - the rule
-- retained_attribution_and_lease_clock.sql established, re-checked here for
-- the repair paths.
reset role;
do $stage_expiry$
declare
  v_run uuid := current_setting('oryveta.rp_run_retry')::uuid;
  v_lease timestamptz;
begin
  update public.factory_runs r
     set lease_expires_at = clock_timestamp() + interval '400 milliseconds'
   where r.id = v_run
  returning r.lease_expires_at into v_lease;
  if v_lease is null then raise exception 'the staged repair attempt was not found'; end if;
  if v_lease <= now() then
    raise exception 'this case needs a deadline that is still in the future of the '
      'transaction timestamp';
  end if;
  perform pg_sleep(1);
  if v_lease > clock_timestamp() then
    raise exception 'the staged deadline has not passed on the wall clock yet';
  end if;
end
$stage_expiry$;
set local role authenticated;

do $retry$
declare
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_pol_audit uuid := current_setting('oryveta.rp_pol_audit')::uuid;
  v_config_one text := repeat('ab', 32);
  v_item uuid := current_setting('oryveta.rp_item_audit')::uuid;
  v_run_one uuid := current_setting('oryveta.rp_run_retry')::uuid;
  v_token_one uuid := current_setting('oryveta.rp_token_retry')::uuid;
  v_beat record; v_claim record; v_fail record; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run_one, p_lease_token => v_token_one, p_phase => 'repairing') t;
  if v_beat.lease_valid or v_beat.reason <> 'lease_lost' then
    raise exception 'a heartbeat on a repair lease that expired on the wall clock was '
      'accepted (%)', coalesce(v_beat.reason, 'no reason');
  end if;

  -- The next claim reclaims the stale attempt and hands out attempt 2 of 2,
  -- re-fetching the same pinned commit rather than resolving anything new.
  select * into v_claim from public.claim_repair_work(v_pol_audit, v_config_one, 300) t;
  if v_claim.run_id is null or v_claim.work_item_id <> v_item or v_claim.attempt <> 2 then
    raise exception 'the repair reclaim handed out % as attempt %',
      v_claim.work_item_id, v_claim.attempt;
  end if;
  if v_claim.pinned_source_commit <> repeat('1', 40) then
    raise exception 'a retry was handed a different commit than the approved one';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_one and r.status = 'failed' and r.error_code = 'lease_expired';
  if n <> 1 then raise exception 'the stale repair attempt was not closed as lease_expired'; end if;

  -- The reclaimed attempt's token is dead, and its holder cannot publish.
  select * into v_beat from public.heartbeat_repair_run(
    p_run_id => v_run_one, p_lease_token => v_token_one, p_phase => 'verifying') t;
  if v_beat.lease_valid then
    raise exception 'the token of a reclaimed repair attempt still works';
  end if;

  -- The second failure exhausts the two attempts a repair item is admitted
  -- with: no third attempt is ever handed out.
  select * into v_fail from public.fail_repair_run(
    v_claim.run_id, v_claim.lease_token, 'verification_failed') t;
  if not v_fail.accepted or v_fail.retry_scheduled
     or v_fail.work_item_status <> 'failed' then
    raise exception 'the second repair failure did not end the work item (% %)',
      v_fail.work_item_status, v_fail.retry_scheduled;
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_claim.run_id and e.kind = 'attempts_exhausted';
  if n <> 1 then raise exception 'the exhausted attempt budget was not recorded'; end if;
  select count(*) into n from public.work_items w
   where w.id = v_item and w.attempts = 2 and w.max_attempts = 2 and w.status = 'failed';
  if n <> 1 then raise exception 'the repair work item is not terminally failed at 2 of 2'; end if;
  select * into v_claim from public.claim_repair_work(v_pol_audit, v_config_one, 300) t;
  if v_claim.run_id is not null then
    raise exception 'a third attempt of an exhausted repair work item was handed out';
  end if;
end
$retry$;

-- ---------------------------------------------------------------------------
-- 13. Continuous consumption: one worker, one policy, more than one task, and
--     the terminal run history the deletion cases below need.
-- ---------------------------------------------------------------------------
do $consumption$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_history uuid := current_setting('oryveta.rp_p_history')::uuid;
  v_pol uuid := current_setting('oryveta.rp_pol_history')::uuid;
  v_config_one text := repeat('ab', 32);
  v_commit_one text := repeat('1', 40);
  v_patch text := '--- a/a.py' || E'\n' || '+++ b/a.py' || E'\n'
                  || '@@ -1 +1 @@' || E'\n' || '-x' || E'\n' || '+y' || E'\n';
  v_first uuid; v_second uuid;
  v_claim_one record; v_claim_two record; v_claim_three record;
  v_finish record; v_fail record; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_first from public.submit_repository_repair(
    v_p_history, v_pol, 'First of two queued goals', 'repair-history-key-01') t;
  select t.work_item_id into v_second from public.submit_repository_repair(
    v_p_history, v_pol, 'Second of two queued goals', 'repair-history-key-02') t;

  -- Two claims hand out the two distinct items, and a third hands out nothing.
  -- The order between two items submitted inside one transaction is not
  -- asserted, only that each is handed out exactly once.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim_one from public.claim_repair_work(v_pol, v_config_one, 300) t;
  if v_claim_one.run_id is null then raise exception 'the first of two goals was not claimed'; end if;
  -- One attempt per work item at a time: the second claim cannot take the item
  -- that is already running.
  select * into v_claim_two from public.claim_repair_work(v_pol, v_config_one, 300) t;
  if v_claim_two.run_id is null then
    raise exception 'a worker that already holds one attempt could not take the second '
      'queued goal, so continuous consumption would stall';
  end if;
  if v_claim_two.work_item_id = v_claim_one.work_item_id then
    raise exception 'two claims handed out the same work item twice';
  end if;
  if (v_claim_one.work_item_id, v_claim_two.work_item_id) not in
     ((v_first, v_second), (v_second, v_first)) then
    raise exception 'the two claims did not hand out the two submitted goals';
  end if;
  if v_claim_one.lease_token = v_claim_two.lease_token then
    raise exception 'two concurrent attempts share one lease token';
  end if;
  select * into v_claim_three from public.claim_repair_work(v_pol, v_config_one, 300) t;
  if v_claim_three.run_id is not null then
    raise exception 'a third claim invented work that was never submitted';
  end if;

  -- One succeeds as a reviewable candidate, one fails and keeps its retry.
  perform 1 from public.heartbeat_repair_run(
    p_run_id => v_claim_one.run_id, p_lease_token => v_claim_one.lease_token,
    p_phase => 'repairing', p_source_ref => 'github.com/octocat/Hello-World',
    p_source_commit => v_commit_one,
    p_source_digest => 'sha256:' || repeat('0f', 32)) t;
  select * into v_finish from public.finish_repair_run(
    v_claim_one.run_id, v_claim_one.lease_token, jsonb_build_object(
      'kind','repository_repair','status','needs_review','verification','passed',
      'configuration_sha256',v_config_one,'source_commit',v_commit_one,
      'source_tree_sha256',repeat('0f',32),'candidate_tree_sha256',repeat('1e',32),
      'patch_sha256',encode(sha256(convert_to(v_patch,'UTF8')),'hex'),'patch',v_patch,
      -- A one-turn, zero-tool-call run is a legal outcome.
      'checks_passed',2,'turns',1,'tool_calls',0,'tokens_observed',0,
      'model_name','qwen2.5-coder:7b','model_digest',repeat('9a',32))) t;
  if not v_finish.accepted then
    raise exception 'the first of two goals could not publish its candidate (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;
  select * into v_fail from public.fail_repair_run(
    v_claim_two.run_id, v_claim_two.lease_token, 'runner_timeout') t;
  if not v_fail.accepted or not v_fail.retry_scheduled
     or v_fail.work_item_status <> 'queued' then
    raise exception 'the first failure of two attempts did not schedule a retry (% %)',
      v_fail.work_item_status, v_fail.retry_scheduled;
  end if;
  select count(*) into n from public.factory_runs r where r.project_id = v_p_history;
  if n <> 2 then raise exception 'the run history fixture has % attempts', n; end if;
end
$consumption$;

-- ---------------------------------------------------------------------------
-- 14. Lifecycle: what an operator and the Auth admin API must be able to
--     delete, what stays refused, and what a retained record keeps when the
--     account it was attributed to is gone.
-- ---------------------------------------------------------------------------

-- Deleting an enrollment that work still names stays refused. The reference is
-- deferred, so the refusal is surfaced by forcing the check, and only the
-- table owner can even try: no client role holds DELETE.
reset role;
do $policy_reference$
declare
  v_pol uuid := current_setting('oryveta.rp_pol_history')::uuid;
  v_constraint text; n integer;
begin
  begin
    delete from public.project_repair_policies k where k.id = v_pol;
    set constraints all immediate;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'a repair policy was deleted while work items still name it, so repair '
                'history can lose the enrollment it was authorized by';
  exception when foreign_key_violation then
    get stacked diagnostics v_constraint = constraint_name;
    if v_constraint <> 'work_items_repair_policy_id_fkey' then
      raise exception 'the policy deletion was refused by % instead of the work item '
        'reference', coalesce(v_constraint, 'an unnamed constraint');
    end if;
  end;
  -- The refusal rolled that subtransaction back, so the enrollment is still
  -- here and its work still names it.
  select count(*) into n from public.project_repair_policies k where k.id = v_pol;
  if n <> 1 then raise exception 'the refused deletion did not leave the enrollment'; end if;
  select count(*) into n from public.work_items w
   where w.repair_policy_id = v_pol;
  if n <> 2 then raise exception 'the work items lost their enrollment reference'; end if;

  -- The separately owned protection of a worker registration an attempt still
  -- names is unchanged by this migration.
  begin
    delete from public.project_workers k
     where k.project_id = current_setting('oryveta.rp_p_history')::uuid;
    set constraints all immediate;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'a worker registration was deleted while an attempt still references it';
  exception when foreign_key_violation then
    get stacked diagnostics v_constraint = constraint_name;
    if v_constraint <> 'factory_runs_worker_registration_id_fkey' then
      raise exception 'the registration deletion was refused by % instead of the attempt '
        'reference', coalesce(v_constraint, 'an unnamed constraint');
    end if;
  end;
end
$policy_reference$;

-- The owner's own workspace deletion completes even though the workspace
-- carries a project, a worker registration, two enrollments' worth of repair
-- work, two finished attempts, their event logs and a live fencing token.
set local role authenticated;
do $workspace_deletion$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_ws_history uuid := current_setting('oryveta.rp_ws_history')::uuid;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  delete from public.workspaces w where w.id = v_ws_history;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the owner could not delete a workspace that carries repair history';
  end if;
  -- Force every deferred reference to be checked now rather than at commit, so
  -- this case proves the cascade rather than deferring the question.
  set constraints all immediate;
end
$workspace_deletion$;

reset role;
do $workspace_deletion_audit$
declare
  v_p_history uuid := current_setting('oryveta.rp_p_history')::uuid;
  v_pol uuid := current_setting('oryveta.rp_pol_history')::uuid;
  n integer;
begin
  select count(*) into n from public.projects p where p.id = v_p_history;
  if n <> 0 then raise exception 'the project outlived its workspace'; end if;
  select count(*) into n from public.project_repair_policies k where k.id = v_pol;
  if n <> 0 then raise exception 'the enrollment outlived its project'; end if;
  select count(*) into n from public.work_items w where w.project_id = v_p_history;
  if n <> 0 then raise exception 'repair work outlived its project'; end if;
  select count(*) into n from public.factory_runs r where r.project_id = v_p_history;
  if n <> 0 then raise exception 'a repair attempt outlived its work item'; end if;
  select count(*) into n from public.factory_run_events e where e.project_id = v_p_history;
  if n <> 0 then raise exception 'the event log outlived its attempt'; end if;
  select count(*) into n from private.factory_run_leases l
   where l.work_item_id not in (select w.id from public.work_items w);
  if n <> 0 then raise exception 'a fencing token outlived its work item'; end if;
end
$workspace_deletion_audit$;

-- Deleting the accounts that enrolled and revoked a policy succeeds. The
-- enrollment keeps its state, its timestamps, its frozen source and its
-- configuration digest, and only the actor reference becomes unknown -
-- attribution is not authority, so the policy still works afterwards.
do $actor_deletion$
declare
  v_admin uuid := '7a222222-2222-4222-8222-222222222222';
  v_revoker uuid := '7a333333-3333-4333-8333-333333333333';
  v_pol_audit uuid := current_setting('oryveta.rp_pol_audit')::uuid;
  v_pol_revoked uuid := current_setting('oryveta.rp_pol_revoked')::uuid;
  n integer;
begin
  delete from auth.users u where u.id = v_admin;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the account that enrolled a repair policy could not be deleted';
  end if;
  delete from auth.users u where u.id = v_revoker;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the account that revoked a repair policy could not be deleted';
  end if;
  set constraints all immediate;

  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_audit and k.enabled and k.created_by is null
     and k.created_at is not null
     and k.source_url = 'https://github.com/octocat/Hello-World'
     and k.source_commit = repeat('1', 40)
     and k.configuration_sha256 = repeat('ab', 32);
  if n <> 1 then
    raise exception 'the enrollment lost its state, its timestamps or its frozen identity '
      'when the account that enrolled it was deleted';
  end if;
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_revoked and not k.enabled
     and k.revoked_at is not null and k.revoked_by is null;
  if n <> 1 then
    raise exception 'the withdrawn enrollment lost its revocation state or timestamp';
  end if;
end
$actor_deletion$;

-- The surviving enrollment is still usable: its authority was never the
-- account that created it.
set local role authenticated;
do $authority_outlives_attribution$
declare
  v_engineer uuid := '7a444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_p_audit uuid := current_setting('oryveta.rp_p_audit')::uuid;
  v_pol_audit uuid := current_setting('oryveta.rp_pol_audit')::uuid;
  v_config_one text := repeat('ab', 32);
  v_item uuid; v_claim record;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.work_item_id into v_item from public.submit_repository_repair(
    v_p_audit, v_pol_audit, 'Submitted after the enrolling admin was deleted') t;
  if v_item is null then
    raise exception 'an enrollment stopped working when its attribution was cleared';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_repair_work(v_pol_audit, v_config_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the worker could not claim work under an enrollment whose '
      'attribution was cleared';
  end if;
end
$authority_outlives_attribution$;

-- ---------------------------------------------------------------------------
-- 15. Offboarding a worker identity. The whole authority chain is re-derived
--     at admission, and deleting the worker's Auth account retains what was
--     approved instead of being refused by the work a colleague submitted
--     under it.
--
--     Its own workspace, project and worker identity, so the deletions below
--     cannot disturb anything above and nothing above leaves it an attempt:
--     the defect needed no attempt at all.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $offboarding_setup$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_worker_d uuid := '7b444444-4444-4444-8444-444444444444';
  v_commit_one text := repeat('1', 40);
  v_commit_two text := repeat('2', 40);
  v_config_one text := repeat('ab', 32);
  v_config_two text := repeat('cd', 32);
  v_ws uuid; v_project uuid;
  v_pol_live uuid; v_pol_revoked uuid;
  v_item_live uuid; v_item_revoked uuid;
  v_revoke record;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  insert into public.workspaces(name,slug,created_by)
  values ('Repair Offboarding','repair-offboarding',v_owner) returning id into v_ws;
  select t.id into v_project from public.create_project(
    v_ws, 'Repair Offboarding', 'worker account deletion', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  perform 1 from public.register_project_worker(v_project, v_worker_d, 'Repair Worker D') t;

  -- Two enrollments of the one identity, because an offboarding has to survive
  -- both a live enrollment and one that was already withdrawn.
  select t.id into v_pol_live from public.register_project_repair_policy(
    v_project, v_worker_d, 'Repair Worker D', v_commit_one, v_config_one) t;
  select t.id into v_pol_revoked from public.register_project_repair_policy(
    v_project, v_worker_d, 'Repair Worker D Two', v_commit_two, v_config_two) t;
  -- A freshly enrolled policy names the same account live and frozen.
  if not exists(select 1 from public.project_repair_policies k
                 where k.id = v_pol_live and k.worker_identity = v_worker_d
                   and k.worker_user_id = v_worker_d) then
    raise exception 'an enrollment did not record the designated identity twice';
  end if;

  -- Two goals a human submitted and no worker ever claimed. That is the entire
  -- precondition: work_items.created_by is the submitter, never the worker, so
  -- these rows do not cascade away with the worker's account.
  select t.work_item_id into v_item_live from public.submit_repository_repair(
    v_project, v_pol_live, 'Never claimed under a live enrollment') t;
  select t.work_item_id into v_item_revoked from public.submit_repository_repair(
    v_project, v_pol_revoked, 'Never claimed under an enrollment withdrawn first') t;
  if v_item_live is null or v_item_revoked is null then
    raise exception 'the offboarding fixture could not admit its two goals';
  end if;

  select * into v_revoke from public.revoke_project_repair_policy(v_pol_revoked) t;
  if v_revoke.enabled then
    raise exception 'the offboarding fixture did not withdraw its second enrollment';
  end if;

  perform set_config('oryveta.rp_p_offboard', v_project::text, true);
  perform set_config('oryveta.rp_pol_offboard_live', v_pol_live::text, true);
  perform set_config('oryveta.rp_pol_offboard_revoked', v_pol_revoked::text, true);
  perform set_config('oryveta.rp_item_offboard_live', v_item_live::text, true);
  perform set_config('oryveta.rp_item_offboard_revoked', v_item_revoked::text, true);
  perform set_config('oryveta.rp_offboard_revoked_at',
    (select k.revoked_at::text from public.project_repair_policies k
      where k.id = v_pol_revoked), true);
end
$offboarding_setup$;

-- Stripping the Auth service designation fences the identity everywhere at
-- once, and that now includes admission: the enrollment is enabled and the
-- registration is enabled, but the account is no longer a service principal,
-- so no new goal is admitted under it. Only the Auth admin API can write this
-- field, which is why the owner role stages it here.
reset role;
update auth.users u set raw_app_meta_data = '{}'::jsonb
 where u.id = '7b444444-4444-4444-8444-444444444444';
set local role authenticated;

do $offboarding_designation$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_project uuid := current_setting('oryveta.rp_p_offboard')::uuid;
  v_pol uuid := current_setting('oryveta.rp_pol_offboard_live')::uuid;
  v_message text; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_project, v_pol, 'Submitted while the worker designation was stripped') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'the worker identity bound to this repair policy is no longer a '
                  'provisioned factory worker service identity' then
    raise exception 'a goal was admitted under an enrollment whose worker is no longer a '
      'designated service identity (%)', coalesce(v_message, 'no error');
  end if;
  -- The refusal admitted nothing: the one queued goal from the fixture is all
  -- that is there.
  select count(*) into n from public.work_items w
   where w.repair_policy_id = v_pol and w.status = 'queued';
  if n <> 1 then
    raise exception 'the refused admission changed the queue (% queued instead of 1)', n;
  end if;
end
$offboarding_designation$;

reset role;
update auth.users u set raw_app_meta_data = '{"oryveta_role":"factory_worker"}'::jsonb
 where u.id = '7b444444-4444-4444-8444-444444444444';

-- THE OFFBOARDING REGRESSION. Deleting the worker's Auth account must succeed
-- even though a colleague's never-claimed goal still names the enrollment it
-- was admitted under. The enrollment used to cascade away with the account,
-- and the surviving work item then made the deferred reference unsatisfiable,
-- so the deletion was refused at the constraint check - revoking the policy or
-- the registration first did not help, and no attempt had to exist.
do $offboarding_deletion$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_worker_d uuid := '7b444444-4444-4444-8444-444444444444';
  v_project uuid := current_setting('oryveta.rp_p_offboard')::uuid;
  v_pol_live uuid := current_setting('oryveta.rp_pol_offboard_live')::uuid;
  v_pol_revoked uuid := current_setting('oryveta.rp_pol_offboard_revoked')::uuid;
  v_item_live uuid := current_setting('oryveta.rp_item_offboard_live')::uuid;
  v_item_revoked uuid := current_setting('oryveta.rp_item_offboard_revoked')::uuid;
  v_revoked_at timestamptz := current_setting('oryveta.rp_offboard_revoked_at')::timestamptz;
  n integer;
begin
  delete from auth.users u where u.id = v_worker_d;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the Auth account of a worker identity could not be deleted';
  end if;
  -- Force every deferred reference to be checked now rather than at commit, so
  -- this case proves the lifecycle instead of deferring the question.
  set constraints all immediate;

  -- Both enrollments are retained in full: the frozen identity, the approved
  -- commit, the reviewed configuration digest and the enrollment attribution.
  -- Only the live reference is gone, and with it any authority.
  select count(*) into n from public.project_repair_policies k
   where k.id in (v_pol_live, v_pol_revoked)
     and k.worker_identity = v_worker_d and k.worker_user_id is null
     and not k.enabled and k.revoked_at is not null
     and k.source_url = 'https://github.com/octocat/Hello-World'
     and k.configuration_sha256 in (repeat('ab', 32), repeat('cd', 32))
     and k.created_by = v_owner;
  if n <> 2 then
    raise exception 'the enrollments of a deleted worker identity did not survive with '
      'their frozen record (% of 2)', n;
  end if;
  -- The one that was already withdrawn keeps its own revocation, actor and
  -- timestamp: the deletion did not rewrite a decision a human had made.
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_revoked and k.revoked_at = v_revoked_at
     and k.revoked_by = v_owner;
  if n <> 1 then
    raise exception 'the already withdrawn enrollment lost its revocation timestamp or '
      'attribution when the worker account was deleted';
  end if;
  -- An account deletion is not a project actor's decision, so the enrollment
  -- it withdrew records a timestamp and no actor rather than an invented one.
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_live and k.revoked_by is null;
  if n <> 1 then
    raise exception 'the deletion invented a revocation attribution';
  end if;

  -- The human's work item is retained with its goal and its enrollment
  -- reference, and settled with a reason rather than left queued for an
  -- identity that no longer exists.
  select count(*) into n from public.work_items w
   where w.id = v_item_live and w.repair_policy_id = v_pol_live
     and w.created_by = v_owner
     and w.goal = 'Never claimed under a live enrollment'
     and w.status = 'failed' and w.error_code = 'worker_identity_deleted';
  if n <> 1 then
    raise exception 'a never-claimed goal was lost, left queued or left unattributed '
      'when its worker identity was deleted';
  end if;
  -- The item the earlier withdrawal already settled keeps that reason: this
  -- settlement only touches what is still queued or running.
  select count(*) into n from public.work_items w
   where w.id = v_item_revoked and w.status = 'failed' and w.error_code = 'policy_revoked';
  if n <> 1 then
    raise exception 'the deletion overwrote the settlement reason of work a revocation '
      'had already settled';
  end if;

  -- The ordinary registration cascades away with the account exactly as it
  -- already did, because no attempt ever referenced it. The separately owned
  -- RESTRICT protection of a registration an attempt names is covered above.
  select count(*) into n from public.project_workers k where k.project_id = v_project;
  if n <> 0 then
    raise exception 'the worker registration survived the deletion of its own account';
  end if;
  select count(*) into n from public.factory_runs r where r.project_id = v_project;
  if n <> 0 then
    raise exception 'this case is only a regression while its work was never claimed, '
      'and % attempts exist', n;
  end if;
end
$offboarding_deletion$;

-- A cleared live identity is a refusal everywhere, never a wildcard: the
-- deleted subject reaches nothing, no other designated worker inherits the
-- enrollment, and no new goal is admitted under it.
set local role authenticated;
do $offboarding_fenced$
declare
  v_owner uuid := '7a111111-1111-4111-8111-111111111111';
  v_worker_a uuid := '7b111111-1111-4111-8111-111111111111';
  v_worker_d uuid := '7b444444-4444-4444-8444-444444444444';
  v_project uuid := current_setting('oryveta.rp_p_offboard')::uuid;
  v_pol_live uuid := current_setting('oryveta.rp_pol_offboard_live')::uuid;
  v_config_one text := repeat('ab', 32);
  v_message text; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_d::text, true);
  v_message := null;
  begin perform 1 from public.claim_repair_work(v_pol_live, v_config_one, 300) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from
     'worker identity is not a provisioned factory worker service identity' then
    raise exception 'a deleted worker identity still reached the repair claim path (%)',
      coalesce(v_message, 'no error');
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  v_message := null;
  begin perform 1 from public.claim_repair_work(v_pol_live, v_config_one, 300) t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy not found' then
    raise exception 'another designated worker inherited an enrollment whose identity was '
      'deleted (%)', coalesce(v_message, 'no error');
  end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  v_message := null;
  begin
    perform 1 from public.submit_repository_repair(
      v_project, v_pol_live, 'Submitted after the worker account was deleted') t;
  exception when others then v_message := sqlerrm; end;
  if v_message is distinct from 'repair policy is disabled' then
    raise exception 'a goal was admitted under an enrollment whose worker account was '
      'deleted (%)', coalesce(v_message, 'no error');
  end if;
  select count(*) into n from public.work_items w
   where w.project_id = v_project and w.status in ('queued','running');
  if n <> 0 then
    raise exception '% repair items are still live under a deleted worker identity', n;
  end if;

  -- There is no subject left to read the row as, but the project's own readers
  -- still see what was approved, which is the point of retaining it.
  select count(*) into n from public.project_repair_policies k
   where k.id = v_pol_live and k.worker_identity = v_worker_d
     and k.worker_user_id is null;
  if n <> 1 then
    raise exception 'a project owner cannot read the retained enrollment of a deleted '
      'worker identity';
  end if;
end
$offboarding_fenced$;

reset role;
rollback;
