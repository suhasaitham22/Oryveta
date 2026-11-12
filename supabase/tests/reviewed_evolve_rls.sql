-- Consumer-visible security and race regression for the reviewed Evolve
-- runtime: which accounts may submit, run, publish, read and approve, and
-- which transitions must stay impossible no matter what a browser session, a
-- worker process or a model asks for.
--
-- Run order (psql, ON_ERROR_STOP=1, on a superuser/owner connection to a
-- Supabase stack whose auth and storage schemas and anon/authenticated roles
-- already exist - the local `supabase start` stack with Storage enabled, or a
-- dedicated development project):
--   1. supabase/schema.sql
--   2. supabase/migrations/private_chats_and_explicit_sharing.sql
--   3. supabase/migrations/projects_and_project_membership.sql
--   4. supabase/migrations/durable_factory_runtime.sql
--   5. supabase/migrations/retained_attribution_and_lease_clock.sql
--   6. supabase/migrations/reviewed_evolve_runtime.sql
--   7. this file
--
-- Requires SQL-editor/owner privileges and intentionally creates synthetic
-- auth.users. Everything here ROLLS BACK, even on success, so no fixture row,
-- storage object or temporary function survives the run. Never run it on an
-- unrelated project.
--
-- What is real and what is staged:
--   * Every submission, claim, heartbeat, stage, artifact registration,
--     completion, failure report, failure, cancellation, revocation, approval
--     and lesson revocation goes through the real RPCs and policies as the
--     authenticated role, with the acting account's id in
--     request.jwt.claim.sub. Nothing is mocked and no check is bypassed.
--   * Storage object rows are written by the table owner, because that is what
--     the Storage service does server side; the browser and worker upload
--     *authority* is checked by evaluating the real policy predicate as each
--     account, by a real INSERT denial, and by real RLS-filtered SELECTs.
--   * public.workspace_memberships and the worker service designation in
--     auth.users.raw_app_meta_data are provisioned by the owner role, because
--     no client role may write either one.
--   * An expired lease is staged by moving a deadline into the past of
--     clock_timestamp(), the same clock the runtime judges leases on.
--
-- Fixture identifiers cross the role switches in transaction-local settings,
-- because one DO block cannot share variables with the next.
begin;

-- ---------------------------------------------------------------------------
-- Fixtures: four ordinary accounts and two designated worker service
-- identities. Addresses are confirmed because invitation acceptance requires
-- private.verified_email().
-- ---------------------------------------------------------------------------
insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,
   raw_app_meta_data,created_at,updated_at)
values
-- workspace and project owner: the project admin who decides approvals
('6a111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-owner@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- project engineer: may submit and cancel, may never approve
('6b222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-engineer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- project viewer: may read, may never submit, cancel or approve
('6c333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-viewer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- holds no grant on either project
('6d444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-stranger@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- designated worker service identity for the first project
('6e555555-5555-4555-8555-555555555555','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-worker-a@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- designated worker service identity for the second project only
('6f666666-6666-4666-8666-666666666666','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-evolve-worker-b@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now());

set local role authenticated;

do $tenancy$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_worker_b uuid := '6f666666-6666-4666-8666-666666666666';
  v_ws uuid;
  v_p_one uuid;
  v_p_two uuid;
  v_inv uuid;
  v_joined uuid;
  v_reg_a uuid;
  v_reg_b uuid;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  insert into public.workspaces(name,slug,created_by)
  values ('Evolve Security','evolve-security',v_owner) returning id into v_ws;

  select t.id into v_p_one from public.create_project(
    v_ws, 'Reviewed Evolve', 'reviewed candidate workflow', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  select t.id into v_p_two from public.create_project(
    v_ws, 'Other Evolve', 'a project this worker may not serve', 'evolve',
    'https://github.com/octocat/Spoon-Knife') t;
  if v_p_one is null or v_p_two is null then
    raise exception 'fixture: the project fixtures were not created';
  end if;

  select t.id into v_inv from public.invite_project_member(
    v_p_one, 'oryveta-evolve-engineer@example.invalid', 'engineer') t;
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.project_id into v_joined from public.accept_project_invitation(v_inv) t;
  if v_joined <> v_p_one then raise exception 'fixture: the engineer did not join'; end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.id into v_inv from public.invite_project_member(
    v_p_one, 'oryveta-evolve-viewer@example.invalid', 'viewer') t;
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  select t.project_id into v_joined from public.accept_project_invitation(v_inv) t;
  if v_joined <> v_p_one then raise exception 'fixture: the viewer did not join'; end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.id into v_reg_a from public.register_project_worker(
    v_p_one, v_worker_a, 'Evolve worker A') t;
  select t.id into v_reg_b from public.register_project_worker(
    v_p_two, v_worker_b, 'Evolve worker B') t;
  if v_reg_a is null or v_reg_b is null then
    raise exception 'fixture: the worker registrations were not created';
  end if;

  perform set_config('oryveta.ev_ws', v_ws::text, true);
  perform set_config('oryveta.ev_p_one', v_p_one::text, true);
  perform set_config('oryveta.ev_p_two', v_p_two::text, true);
  perform set_config('oryveta.ev_reg_a', v_reg_a::text, true);
end
$tenancy$;

reset role;

-- ---------------------------------------------------------------------------
-- Drivers. ev_payload builds a stage payload in the one accepted shape;
-- ev_store stands in for the Storage service, which writes object rows server
-- side with the uploader as owner; ev_chain drives one complete reviewed
-- attempt through the real RPCs as the worker identity. Everything they create
-- is rolled back with this transaction.
-- ---------------------------------------------------------------------------
create function pg_temp.ev_payload(
  p_source text, p_config text, p_digest text, p_artifact jsonb, p_evidence jsonb)
returns jsonb language sql immutable as $payload$
  select jsonb_build_object(
    'schema_version', 1,
    'source_sha256', p_source,
    'config_sha256', p_config,
    'artifact_sha256', p_digest,
    'artifact', p_artifact,
    'review', jsonb_build_object(
      'verdict', 'pass',
      'summary', 'reviewed against the recorded evidence of this attempt',
      'evidence_ids', p_evidence,
      'findings', '[]'::jsonb,
      'reviewer_model', 'qwen3:8b',
      'reviewer_digest', repeat('b', 64)))
$payload$;

create function pg_temp.ev_store(
  p_run uuid, p_kind text, p_sha text, p_bytes integer, p_owner uuid)
returns void language plpgsql security definer as $store$
begin
  insert into storage.objects(bucket_id, name, owner, metadata)
  values ('evolve-artifacts', p_run::text || '/' || p_kind || '/' || p_sha, p_owner,
          jsonb_build_object('size', p_bytes, 'mimetype', 'application/octet-stream'));
end
$store$;

create function pg_temp.ev_chain(
  p_project uuid, p_worker uuid, p_source_digest text, p_config text,
  p_candidate text, p_patch text)
returns uuid language plpgsql as $chain$
declare
  v_claim record;
  v_beat record;
  v_finish record;
  v_source text := right(p_source_digest, 64);
  v_goal text;
  v_run uuid;
  v_token uuid;
begin
  perform set_config('request.jwt.claim.sub', p_worker::text, true);
  select * into v_claim from public.claim_evolve_work(p_project, 300) t;
  if v_claim.run_id is null then
    raise exception 'chain: no queued Evolve work was handed out';
  end if;
  v_run := v_claim.run_id;
  v_token := v_claim.lease_token;
  v_goal := v_claim.goal;
  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f', 40), p_source_digest, 300) t;
  if not v_beat.lease_valid then
    raise exception 'chain: the snapshot heartbeat was refused (%)', v_beat.reason;
  end if;
  -- The archive and its patch exist as bytes before any stage describes them.
  perform pg_temp.ev_store(v_run, 'candidate', p_candidate, 4096, p_worker);
  perform pg_temp.ev_store(v_run, 'patch', p_patch, 512, p_worker);
  perform 1 from public.register_evolve_artifact(
    v_run, v_token, 'candidate', p_candidate, 4096) t;
  perform 1 from public.register_evolve_artifact(
    v_run, v_token, 'patch', p_patch, 512) t;

  perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, p_config, repeat('1', 64),
      jsonb_build_object(
        'goal', v_goal,
        'acceptance_criteria', jsonb_build_array('the documented behaviour is preserved'),
        'constraints', jsonb_build_array('no new dependency')),
      jsonb_build_array('stage:requirements'))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'plan',
    pg_temp.ev_payload(v_source, p_config, repeat('2', 64),
      jsonb_build_object(
        'steps', jsonb_build_array('reproduce the reported behaviour', 'bound the change'),
        'allowed_paths', jsonb_build_array('engine/oryveta_engine'),
        'risks', jsonb_build_array('the fix could widen the public interface')),
      jsonb_build_array('stage:requirements', 'artifact:' || repeat('1', 64)))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'implementation',
    pg_temp.ev_payload(v_source, p_config, p_candidate,
      jsonb_build_object(
        'candidate_sha256', p_candidate,
        'patch_sha256', p_patch,
        'changed_paths', jsonb_build_array('engine/oryveta_engine/patches.py'),
        'summary', 'one bounded change inside the planned paths'),
      jsonb_build_array('artifact:' || p_candidate, 'artifact:' || p_patch))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'verification',
    pg_temp.ev_payload(v_source, p_config, p_candidate,
      jsonb_build_object(
        'candidate_sha256', p_candidate,
        'checks', jsonb_build_array(
          jsonb_build_object('name', 'pytest', 'passed', true),
          jsonb_build_object('name', 'preservation', 'passed', true)),
        'baseline_reproduced', true,
        'preservation_passed', true,
        'verification', 'passed'),
      jsonb_build_array('check:pytest', 'check:preservation'))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'audit',
    pg_temp.ev_payload(v_source, p_config, p_candidate,
      jsonb_build_object(
        'candidate_sha256', p_candidate,
        'required_stages', jsonb_build_array('requirements','plan','implementation',
                                             'verification'),
        'violations', jsonb_build_array(),
        'summary', 'every required stage is present and reviewed'),
      jsonb_build_array('stage:verification', 'check:pytest'))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'learning',
    pg_temp.ev_payload(v_source, p_config, p_candidate,
      jsonb_build_object(
        'candidate_sha256', p_candidate,
        'lessons', jsonb_build_array(
          jsonb_build_object(
            'summary', 'the regression reproduces only with the pinned fixture',
            'applicability', 'this repository at this snapshot',
            'evidence_ids', jsonb_build_array('check:pytest'),
            'counterexamples', jsonb_build_array()),
          jsonb_build_object(
            'summary', 'an unsupported generalisation about all repositories',
            'applicability', 'any project',
            'evidence_ids', jsonb_build_array('stage:audit'),
            'counterexamples', jsonb_build_array('no evidence outside this snapshot')))),
      jsonb_build_array('stage:audit'))) t;
  -- Admission for the review phase: six reviewed stages are on record.
  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_token, 'learning_review', null, null, null, 300) t;
  if not v_beat.lease_valid then
    raise exception 'chain: the learning_review heartbeat was refused (%)', v_beat.reason;
  end if;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'learning_review',
    pg_temp.ev_payload(v_source, p_config, p_candidate,
      jsonb_build_object(
        'candidate_sha256', p_candidate,
        'decisions', jsonb_build_array(
          jsonb_build_object('index', 0, 'verdict', 'pass',
            'reason', 'supported by the recorded checks'),
          jsonb_build_object('index', 1, 'verdict', 'reject',
            'reason', 'generalises beyond the evidence'))),
      jsonb_build_array('stage:learning'))) t;

  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if not v_finish.accepted or v_finish.reason <> 'ok'
     or v_finish.work_item_status <> 'awaiting_approval' then
    raise exception 'chain: the completed attempt was refused (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;
  perform set_config('oryveta.ev_token', v_token::text, true);
  return v_run;
end
$chain$;

-- ---------------------------------------------------------------------------
-- 1. Structure: the new state is under row level security, the client roles
--    hold reads only, the RPCs are hardened definers, and the artifact bucket
--    is private with exactly two narrow policies.
-- ---------------------------------------------------------------------------
do $structure$
declare
  n integer;
  v_public boolean;
begin
  select count(*) into n from pg_catalog.pg_class c
    join pg_catalog.pg_namespace ns on ns.oid = c.relnamespace
   where ns.nspname = 'public'
     and c.relname in ('evolve_stages','evolve_artifacts','evolve_lessons')
     and c.relrowsecurity;
  if n <> 3 then
    raise exception 'row level security is not enabled on all three Evolve tables';
  end if;

  select count(*) into n from (values
      ('public.evolve_stages'),('public.evolve_artifacts'),('public.evolve_lessons')
    ) as t(rel)
   where not has_table_privilege('authenticated', t.rel, 'select')
      or has_table_privilege('authenticated', t.rel, 'insert')
      or has_table_privilege('authenticated', t.rel, 'update')
      or has_table_privilege('authenticated', t.rel, 'delete')
      or has_table_privilege('anon', t.rel, 'select')
      or has_table_privilege('anon', t.rel, 'insert');
  if n <> 0 then
    raise exception 'the Evolve tables do not hold exactly SELECT for authenticated and '
      'nothing for anon';
  end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'public'
     and p.proname in ('submit_evolve_work','claim_evolve_work','heartbeat_evolve_run',
       'record_evolve_stage','register_evolve_artifact','finish_evolve_run',
       'record_evolve_failure_report','fail_evolve_run','decide_evolve_work',
       'revoke_evolve_lesson');
  if n <> 10 then raise exception 'expected exactly ten reviewed Evolve RPCs, found %', n; end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'public'
     and p.proname in ('submit_evolve_work','claim_evolve_work','heartbeat_evolve_run',
       'record_evolve_stage','register_evolve_artifact','finish_evolve_run',
       'record_evolve_failure_report','fail_evolve_run','decide_evolve_work',
       'revoke_evolve_lesson')
     and (not p.prosecdef
       or p.proconfig is null
       -- An empty search_path is stored either bare or quoted, never as a
       -- schema list such as search_path=public.
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon', p.oid, 'execute'));
  if n <> 0 then
    raise exception 'an Evolve RPC is not a hardened definer or is anon-executable';
  end if;

  -- The validators, the storage predicates and the fencing helpers are
  -- internals of those definers and must be reachable by nobody.
  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'private'
     and p.proname in ('assert_evolve_stage_payload','assert_evolve_failure_report',
       'assert_evolve_json_tree',
       'assert_evolve_scalar_text','assert_evolve_text_list','assert_evolve_path_list',
       'assert_evolve_object_keys','evolve_stage_order','evolve_phase_requirement',
       'evolve_storage_parts','reject_candidate_lessons','run_worker_still_authorized',
       'record_evolve_learning_unavailable')
     and (has_function_privilege('anon', p.oid, 'execute')
       or has_function_privilege('authenticated', p.oid, 'execute')
       or p.proconfig is null
       or not (p.proconfig && array['search_path=','search_path=""']));
  if n <> 0 then
    raise exception 'an Evolve validation or fencing helper is reachable by a client role '
      'or is not search_path hardened';
  end if;

  -- No table in public exposes a lease token, and the private lease table is
  -- still unreachable: an Evolve worker holds its fence the same way.
  select count(*) into n from information_schema.columns c
   where c.table_schema = 'public' and c.column_name = 'lease_token';
  if n <> 0 then raise exception 'a table in schema public exposes a lease_token column'; end if;

  select b.public into v_public from storage.buckets b where b.id = 'evolve-artifacts';
  if v_public is null then
    raise exception 'the private evolve-artifacts bucket does not exist';
  end if;
  if v_public then
    raise exception 'the evolve-artifacts bucket is public, so a candidate archive is '
      'readable without a project grant';
  end if;

  select count(*) into n from pg_catalog.pg_policies p
   where p.schemaname = 'storage' and p.tablename = 'objects'
     and p.policyname in ('evolve_artifacts_worker_insert',
                          'evolve_artifacts_registered_select');
  if n <> 2 then
    raise exception 'the two private artifact storage policies are not both installed';
  end if;
  select count(*) into n from pg_catalog.pg_policies p
   where p.schemaname = 'storage' and p.tablename = 'objects'
     and (coalesce(p.qual, '') like '%evolve-artifacts%'
       or coalesce(p.with_check, '') like '%evolve-artifacts%')
     and (p.cmd not in ('SELECT','INSERT') or p.roles <> '{authenticated}'::name[]);
  if n <> 0 then
    raise exception 'a storage policy for the Evolve bucket is not a SELECT or INSERT policy '
      'restricted to the authenticated role';
  end if;
end
$structure$;

-- ---------------------------------------------------------------------------
-- 2. Anonymous callers. No ids are needed: every denial happens before any
--    row, project or argument is considered.
-- ---------------------------------------------------------------------------
set local role anon;
do $anon$
declare
  n integer;
  ok boolean;
begin
  ok := false;
  begin select count(*) into n from public.evolve_stages;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.evolve_stages'; end if;

  ok := false;
  begin select count(*) into n from public.evolve_artifacts;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.evolve_artifacts'; end if;

  ok := false;
  begin select count(*) into n from public.evolve_lessons;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.evolve_lessons'; end if;

  ok := false;
  begin perform 1 from public.submit_evolve_work(gen_random_uuid(), 'a goal') t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute submit_evolve_work'; end if;

  ok := false;
  begin perform 1 from public.claim_evolve_work(gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute claim_evolve_work'; end if;

  ok := false;
  begin perform 1 from public.heartbeat_evolve_run(gen_random_uuid(), gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute heartbeat_evolve_run'; end if;

  ok := false;
  begin perform 1 from public.record_evolve_stage(
    gen_random_uuid(), gen_random_uuid(), 'requirements', '{}'::jsonb) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute record_evolve_stage'; end if;

  ok := false;
  begin perform 1 from public.register_evolve_artifact(
    gen_random_uuid(), gen_random_uuid(), 'candidate', repeat('c',64), 10) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute register_evolve_artifact'; end if;

  ok := false;
  begin perform 1 from public.finish_evolve_run(gen_random_uuid(), gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute finish_evolve_run'; end if;

  ok := false;
  begin perform 1 from public.fail_evolve_run(
    gen_random_uuid(), gen_random_uuid(), 'review_rejected') t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute fail_evolve_run'; end if;

  ok := false;
  begin perform 1 from public.decide_evolve_work(
    gen_random_uuid(), gen_random_uuid(), repeat('c',64), true) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute decide_evolve_work'; end if;

  ok := false;
  begin perform 1 from public.revoke_evolve_lesson(gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute revoke_evolve_lesson'; end if;

  ok := false;
  begin perform 1 from public.record_evolve_failure_report(
    gen_random_uuid(), gen_random_uuid(), '{}'::jsonb) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute record_evolve_failure_report'; end if;
end
$anon$;

-- ---------------------------------------------------------------------------
-- 3. No browser session and no worker process holds a write privilege on the
--    reviewed record. Mutation goes exclusively through the RPCs, so a
--    forgotten policy fails closed instead of exposing a write.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $write_denial$
declare
  v_actor uuid;
  v_relation text;
  ok boolean;
  v_message text;
begin
  foreach v_actor in array array['6a111111-1111-4111-8111-111111111111'::uuid,
                                 '6b222222-2222-4222-8222-222222222222'::uuid,
                                 '6c333333-3333-4333-8333-333333333333'::uuid,
                                 '6d444444-4444-4444-8444-444444444444'::uuid,
                                 '6e555555-5555-4555-8555-555555555555'::uuid] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    foreach v_relation in array array['public.evolve_stages','public.evolve_artifacts',
                                      'public.evolve_lessons'] loop
      ok := false; v_message := null;
      begin
        execute format('insert into %s default values', v_relation);
      exception
        when insufficient_privilege then ok := true;
        when others then v_message := sqlerrm;
      end;
      if not ok then
        raise exception 'INSERT on % is not refused for % (%)',
          v_relation, v_actor, coalesce(v_message, 'no error');
      end if;

      ok := false;
      begin execute format('update %s set id = id where false', v_relation);
      exception when insufficient_privilege then ok := true; end;
      if not ok then raise exception 'UPDATE on % is not refused for %', v_relation, v_actor; end if;

      ok := false;
      begin execute format('delete from %s where false', v_relation);
      exception when insufficient_privilege then ok := true; end;
      if not ok then raise exception 'DELETE on % is not refused for %', v_relation, v_actor; end if;
    end loop;
  end loop;
end
$write_denial$;

-- ---------------------------------------------------------------------------
-- 4. Submission authority, the goal contract and duplicate submission.
-- ---------------------------------------------------------------------------
do $submission$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_stranger uuid := '6d444444-4444-4444-8444-444444444444';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_goal text := 'Preserve the documented behaviour of the pinned snapshot.'
                 || E'\n' || E'\tSecond line of the same request.';
  v_other_goal text := 'A different request about different behaviour.';
  v_key text := 'evolve-duplicate-key-001';
  v_item uuid;
  v_actor uuid;
  v_again uuid;
  v_status text;
  v_kind text;
  v_replayed boolean;
  v_stored_goal text;
  v_digest text;
  ok boolean;
  v_message text;
  n integer;
begin
  -- A read-only member and a stranger are both refused, with the same message.
  foreach v_actor in array array[v_viewer, v_stranger] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    ok := false; v_message := null;
    begin perform 1 from public.submit_evolve_work(v_p_one, v_goal, null) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'not allowed to submit work for this project' then
      raise exception '% could submit Evolve work (%)', v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.submit_evolve_work(v_p_one, '   ', null) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'the goal must be nonblank and at most 4000 characters' then
    raise exception 'a blank goal was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.submit_evolve_work(
    v_p_one, 'a goal with a control' || chr(1) || 'character', null) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'the goal must be printable text' then
    raise exception 'a control character was accepted in a goal (%)',
      coalesce(v_message,'no error');
  end if;

  -- A multi-line goal is ordinary text and must survive verbatim.
  select t.id, t.status, t.kind, t.goal, t.input_digest, t.replayed
    into v_item, v_status, v_kind, v_stored_goal, v_digest, v_replayed
    from public.submit_evolve_work(v_p_one, v_goal, v_key) t;
  if v_item is null or v_status <> 'queued' or v_kind <> 'evolve' or v_replayed then
    raise exception 'the engineer submission did not return a queued Evolve row';
  end if;
  if v_stored_goal <> v_goal then
    raise exception 'the submitted multi-line goal was not stored verbatim';
  end if;
  if v_digest <> encode(sha256(convert_to('evolve' || E'\n'
       || 'https://github.com/octocat/Hello-World' || E'\n' || v_goal, 'UTF8')), 'hex') then
    raise exception 'the submission did not freeze the canonical Evolve input digest';
  end if;

  -- The same key with the same input replays exactly one row.
  select count(*) into n from public.submit_evolve_work(v_p_one, v_goal, v_key) t;
  if n <> 1 then raise exception 'a replayed submission returned % rows instead of one', n; end if;
  select t.id, t.replayed into v_again, v_replayed
    from public.submit_evolve_work(v_p_one, v_goal, v_key) t;
  if v_again <> v_item or not v_replayed then
    raise exception 'a repeated idempotency key did not replay the same work item';
  end if;

  -- The same key with a different goal is a different request and is refused.
  ok := false; v_message := null;
  begin perform 1 from public.submit_evolve_work(v_p_one, v_other_goal, v_key) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'idempotency key already used for a different input' then
    raise exception 'a reused key silently replayed a different goal (%)',
      coalesce(v_message,'no error');
  end if;
  select count(*) into n from public.work_items w
   where w.project_id = v_p_one and w.idempotency_key = v_key;
  if n <> 1 then raise exception 'a repeated idempotency key created a second work item'; end if;

  -- The queue is left empty for the routing cases below.
  perform 1 from public.cancel_work_item(v_item) t;
  select count(*) into n from public.work_items w
   where w.id = v_item and w.status = 'cancelled';
  if n <> 1 then raise exception 'the duplicate-submission fixture was not cancelled'; end if;
end
$submission$;

-- ---------------------------------------------------------------------------
-- 5. The two work kinds cannot cross-route. An Evolve claim never hands out
--    analysis work, an analysis claim never hands out Evolve work, and neither
--    runtime's RPCs accept the other's attempt - which is what stops an Evolve
--    attempt from being completed through the analysis path, where no stage,
--    review, artifact or human approval is required at all.
-- ---------------------------------------------------------------------------
do $routing$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_worker_b uuid := '6f666666-6666-4666-8666-666666666666';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_goal text := 'Fix the reported regression in the pinned snapshot.';
  v_item_analysis uuid;
  v_item_evolve uuid;
  v_run_analysis uuid;
  v_token_analysis uuid;
  v_claim_item uuid;
  v_claim record;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.work_item_id into v_item_analysis
    from public.submit_repository_analysis(v_p_one, 'evolve-routing-analysis') t;
  if v_item_analysis is null then
    raise exception 'the analysis routing fixture was not submitted';
  end if;

  -- Only analysis work is queued, so an Evolve claim must come back empty.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.claim_evolve_work(v_p_one, 300) t;
  if n <> 0 then
    raise exception 'an Evolve claim handed out repository analysis work';
  end if;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item_evolve
    from public.submit_evolve_work(v_p_one, v_goal, 'evolve-routing-evolve') t;
  if v_item_evolve is null then raise exception 'the Evolve routing fixture was not submitted'; end if;

  -- And an analysis claim must still take the analysis item, not the Evolve one.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select t.work_item_id, t.run_id, t.lease_token
    into v_claim_item, v_run_analysis, v_token_analysis
    from public.claim_analysis_work(v_p_one, 300) t;
  if v_run_analysis is null then
    raise exception 'the analysis claim handed out nothing while analysis work was queued';
  end if;
  if v_claim_item <> v_item_analysis then
    raise exception 'the analysis claim handed out the Evolve work item';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_analysis and r.work_item_id = v_item_analysis;
  if n <> 1 then
    raise exception 'the analysis claim handed out the Evolve work item';
  end if;

  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.run_id is null or v_claim.work_item_id <> v_item_evolve
     or v_claim.kind <> 'evolve' or v_claim.goal <> v_goal then
    raise exception 'the Evolve claim did not describe the queued Evolve work item';
  end if;

  -- The analysis RPCs refuse the Evolve attempt, and are indistinguishable
  -- from a missing run so nothing becomes probeable.
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    v_claim.run_id, v_claim.lease_token, 'analyzing') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an Evolve attempt could heartbeat through the analysis runtime (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.finish_analysis_run(v_claim.run_id, v_claim.lease_token,
    '{"summary":{"source_files_analyzed":3},"findings":[]}'::jsonb) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an Evolve attempt was completed through the analysis runtime, skipping '
      'every review (%)', coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.fail_analysis_run(
    v_claim.run_id, v_claim.lease_token, 'analysis_failed') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an Evolve attempt was failed through the analysis runtime (%)',
      coalesce(v_message,'no error');
  end if;

  -- And the Evolve RPCs refuse the analysis attempt.
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_evolve_run(v_run_analysis, v_token_analysis) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an analysis attempt could heartbeat through the Evolve runtime (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(
    v_run_analysis, v_token_analysis, 'requirements', '{}'::jsonb) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an analysis attempt could record an Evolve stage (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_run_analysis, v_token_analysis, 'candidate', repeat('c',64), 4096) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an analysis attempt could register an Evolve artifact (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.finish_evolve_run(v_run_analysis, v_token_analysis) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an analysis attempt could finish through the Evolve runtime (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.fail_evolve_run(
    v_run_analysis, v_token_analysis, 'review_rejected') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'an analysis attempt could fail through the Evolve runtime (%)',
      coalesce(v_message,'no error');
  end if;

  -- A designated worker of the other project is a stranger to this one.
  perform set_config('request.jwt.claim.sub', v_worker_b::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.claim_evolve_work(v_p_one, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker identity is not registered for this project' then
    raise exception 'a foreign worker claimed Evolve work (%)', coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(
    v_claim.run_id, v_claim.lease_token, 'requirements', '{}'::jsonb) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'a foreign worker could record a stage on another attempt (%)',
      coalesce(v_message,'no error');
  end if;

  -- The analysis attempt has served its purpose as the other kind of work. It
  -- is cancelled here so the later revocation cases count only the Evolve
  -- attempts they fence.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  perform 1 from public.cancel_work_item(v_item_analysis) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_analysis and r.status = 'cancelled';
  if n <> 1 then
    raise exception 'the analysis routing fixture was not fenced by its cancellation';
  end if;

  perform set_config('oryveta.ev_item_reject', v_item_evolve::text, true);
  perform set_config('oryveta.ev_run_reject', v_claim.run_id::text, true);
  perform set_config('oryveta.ev_token_reject', v_claim.lease_token::text, true);
  perform set_config('oryveta.ev_item_analysis', v_item_analysis::text, true);
  perform set_config('oryveta.ev_run_analysis', v_run_analysis::text, true);
end
$routing$;

-- ---------------------------------------------------------------------------
-- 6. Stage bypass. Ordering, phase admission, payload strictness, digest
--    binding and evidence resolution are all server side, and a rejected
--    review is retained as evidence that nothing may be built on.
-- ---------------------------------------------------------------------------
do $bypass$
declare
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_item uuid := current_setting('oryveta.ev_item_reject')::uuid;
  v_run uuid := current_setting('oryveta.ev_run_reject')::uuid;
  v_token uuid := current_setting('oryveta.ev_token_reject')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_source text := repeat('e', 64);
  v_config text := repeat('9', 64);
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_goal text;
  v_req jsonb;
  v_payload jsonb;
  v_beat record;
  v_finish record;
  v_fail record;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select w.goal into v_goal from public.work_items w where w.id = v_item;
  v_req := jsonb_build_object(
    'goal', v_goal,
    'acceptance_criteria', jsonb_build_array('the regression no longer reproduces'),
    'constraints', jsonb_build_array('no new dependency'));

  -- Stages cannot be recorded before the snapshot they describe is pinned.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'the snapshot this attempt analyses must be recorded before a stage' then
    raise exception 'a stage was recorded before any snapshot identity (%)',
      coalesce(v_message,'no error');
  end if;

  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the snapshot heartbeat was refused (%)', v_beat.reason;
  end if;

  -- Out of order.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'plan',
    pg_temp.ev_payload(v_source, v_config, repeat('2',64),
      jsonb_build_object('steps', jsonb_build_array('skip the requirements'),
        'allowed_paths', jsonb_build_array('engine'), 'risks', jsonb_build_array()),
      jsonb_build_array('stage:plan'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'stage plan cannot be recorded before the stages it depends on' then
    raise exception 'a stage was published out of order (%)', coalesce(v_message,'no error');
  end if;

  -- Phase admission cannot run ahead of the reviewed record.
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_evolve_run(v_run, v_token, 'implementation') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'phase implementation cannot be entered before its reviewed stages are recorded' then
    raise exception 'a worker announced itself past its reviewed stages (%)',
      coalesce(v_message,'no error');
  end if;

  -- Completion before the chain exists.
  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'stages_incomplete' then
    raise exception 'an attempt with no reviewed stages was accepted for approval (%)',
      coalesce(v_finish.reason,'no reason');
  end if;

  -- Digest binding: the snapshot must be the one this attempt recorded.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(repeat('7',64), v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'stage payload source digest is not the snapshot this attempt recorded' then
    raise exception 'a stage claimed a snapshot the attempt never fetched (%)',
      coalesce(v_message,'no error');
  end if;

  -- The requirements artifact must repeat the authorized goal.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      jsonb_build_object('goal', 'a goal the submitter never wrote',
        'acceptance_criteria', jsonb_build_array('something else'),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'the requirements artifact must repeat the submitted goal verbatim' then
    raise exception 'a model restated the authorized goal (%)', coalesce(v_message,'no error');
  end if;

  -- Strict payloads.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      v_req || jsonb_build_object('extra', 'unknown field'),
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message is null
     or v_message not like 'stage artifact field requirements.artifact must contain exactly%' then
    raise exception 'an unknown artifact field was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin
    v_payload := pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      jsonb_build_object('goal', v_goal,
        'acceptance_criteria', (select jsonb_agg('criterion ' || g::text)
                                  from generate_series(1, 21) g),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'));
    perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements', v_payload) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'stage artifact field requirements.acceptance_criteria must hold between 1 and 20 entries' then
    raise exception 'an unbounded acceptance criteria list was accepted (%)',
      coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin
    v_payload := pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'));
    perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
      jsonb_set(v_payload, array['schema_version'], '2'::jsonb)) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'stage payload schema_version must be 1' then
    raise exception 'an unknown payload schema version was accepted (%)',
      coalesce(v_message,'no error');
  end if;

  -- Evidence must resolve against what exists.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:verification'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'review evidence names a stage this attempt has not recorded' then
    raise exception 'a review cited a stage that does not exist (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('check:pytest'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'review evidence names a check no verification stage reported' then
    raise exception 'a review cited a check nothing reported (%)', coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('artifact:' || repeat('a',64)))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'review evidence names an artifact this attempt has not registered' then
    raise exception 'a review cited artifact bytes nobody uploaded (%)',
      coalesce(v_message,'no error');
  end if;

  -- A pass cannot carry a blocking finding.
  ok := false; v_message := null;
  begin
    v_payload := pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'));
    perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
      jsonb_set(v_payload, array['review','findings'], jsonb_build_array(
        jsonb_build_object('severity','blocking','detail','the goal is not covered',
          'evidence_id','stage:requirements')))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'a passing review cannot carry a blocking finding' then
    raise exception 'a passing review carried a blocking finding (%)',
      coalesce(v_message,'no error');
  end if;

  -- The terminal rejection itself is retained evidence: a rework verdict with
  -- its blocking finding is stored, and nothing may be built on top of it.
  v_payload := pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
    jsonb_build_array('stage:requirements'));
  v_payload := jsonb_set(v_payload, array['review','verdict'], '"rework"'::jsonb);
  v_payload := jsonb_set(v_payload, array['review','findings'], jsonb_build_array(
    jsonb_build_object('severity','blocking',
      'detail','the acceptance criteria do not cover the submitted goal',
      'evidence_id','stage:requirements')));
  perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements', v_payload) t;
  select count(*) into n from public.evolve_stages s
   where s.run_id = v_run and s.stage = 'requirements'
     and s.payload->'review'->>'verdict' = 'rework'
     and s.payload->'review'->'findings'->0->>'severity' = 'blocking';
  if n <> 1 then
    raise exception 'a terminal rework review was not retained as evidence';
  end if;
  -- The operator configuration is now pinned to this work item.
  select count(*) into n from public.work_items w
   where w.id = v_item and w.evolve_config_sha256 = v_config;
  if n <> 1 then
    raise exception 'the first recorded requirements stage did not pin the operator config';
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'plan',
    pg_temp.ev_payload(v_source, v_config, repeat('2',64),
      jsonb_build_object('steps', jsonb_build_array('continue anyway'),
        'allowed_paths', jsonb_build_array('engine'), 'risks', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'stage plan cannot follow a review that did not pass' then
    raise exception 'a stage was built on top of a rejected review (%)',
      coalesce(v_message,'no error');
  end if;

  -- Immutability of a recorded stage.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this stage is already recorded with a different payload' then
    raise exception 'a recorded stage was rewritten (%)', coalesce(v_message,'no error');
  end if;
  select count(*) into n from public.record_evolve_stage(
    v_run, v_token, 'requirements', v_payload) t;
  if n <> 1 then
    raise exception 'an exact stage repetition returned % rows instead of one replay', n;
  end if;

  -- And the attempt cannot be handed to a human.
  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'stages_incomplete' then
    raise exception 'an attempt stopped by its own reviewer was accepted for approval (%)',
      coalesce(v_finish.reason,'no reason');
  end if;

  -- A review rejection is a judgement, not an infrastructure fault: it is
  -- terminal even though an attempt remains in the budget.
  select * into v_fail from public.fail_evolve_run(v_run, v_token, 'review_rejected') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' or v_fail.retry_scheduled then
    raise exception 'a review rejection was treated as a retryable failure (%)',
      coalesce(v_fail.reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = v_item and w.status = 'failed' and w.error_code = 'review_rejected'
     and w.attempts = 1 and w.max_attempts = 2;
  if n <> 1 then
    raise exception 'a rejected review did not end the work item terminally';
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'rejected' and e.detail = 'review_rejected';
  if n <> 1 then raise exception 'the review rejection was not recorded as an event'; end if;
  select count(*) into n from public.claim_evolve_work(v_p_one, 300) t;
  if n <> 0 then
    raise exception 'a terminally rejected work item was handed out again';
  end if;
end
$bypass$;

-- ---------------------------------------------------------------------------
-- 7. The operator configuration is pinned per work item, so a replacement
--    worker cannot continue the same request under different trusted rules.
-- ---------------------------------------------------------------------------
do $config_pin$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_source text := repeat('e', 64);
  v_config text := repeat('9', 64);
  v_other_config text := repeat('8', 64);
  v_item uuid;
  v_claim record;
  v_beat record;
  v_fail record;
  v_req jsonb;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'Keep the operator configuration stable across attempts.', null) t;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the config pin fixture was not the item handed out';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'requirements', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then raise exception 'the config pin heartbeat was refused'; end if;
  v_req := jsonb_build_object('goal', v_claim.goal,
    'acceptance_criteria', jsonb_build_array('the behaviour is preserved'),
    'constraints', jsonb_build_array());
  perform 1 from public.record_evolve_stage(v_claim.run_id, v_claim.lease_token,
    'requirements', pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;

  -- An infrastructure failure keeps the retry budget.
  select * into v_fail from public.fail_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'source_fetch_failed') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'queued' or not v_fail.retry_scheduled then
    raise exception 'an infrastructure failure did not schedule a bounded retry (%)',
      coalesce(v_fail.reason,'no reason');
  end if;

  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item or v_claim.attempt <> 2 then
    raise exception 'the retried Evolve item was not handed out as attempt two';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'requirements', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the second attempt could not record the pinned snapshot (%)', v_beat.reason;
  end if;

  v_req := jsonb_build_object('goal', v_claim.goal,
    'acceptance_criteria', jsonb_build_array('the behaviour is preserved'),
    'constraints', jsonb_build_array());
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_claim.run_id, v_claim.lease_token,
    'requirements', pg_temp.ev_payload(v_source, v_other_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'stage payload config digest is not the operator config this work item is pinned to' then
    raise exception 'a replacement attempt ran the same request under another trusted '
      'configuration (%)', coalesce(v_message,'no error');
  end if;
  -- The pinned configuration is accepted.
  perform 1 from public.record_evolve_stage(v_claim.run_id, v_claim.lease_token,
    'requirements', pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
      jsonb_build_array('stage:requirements'))) t;
  select count(*) into n from public.evolve_stages s
   where s.run_id = v_claim.run_id and s.stage = 'requirements';
  if n <> 1 then raise exception 'the pinned configuration stage was not recorded'; end if;

  -- Clear the queue for the cases below.
  select * into v_fail from public.fail_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'process_rejected') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' then
    raise exception 'the config pin fixture was not closed terminally';
  end if;
end
$config_pin$;

-- ---------------------------------------------------------------------------
-- 8. Semantic admission. A goal is ordinary prose about code, so it may carry
--    a backslash or path-like text and must still be reviewable - the
--    requirements stage has to repeat it verbatim. And a field that is absent,
--    JSON null or of another scalar type must be refused rather than compared
--    as NULL, which SQL's three-valued logic would treat as "not a failure".
-- ---------------------------------------------------------------------------
do $semantic_admission$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_source text := repeat('e', 64);
  v_config text := repeat('9', 64);
  -- A real request about code: a regular expression with a backslash, and a
  -- second line that starts with a slash.
  v_goal text := 'Escape the \d digit class in the import matcher.' || E'\n'
                 || '/usr/local/bin examples in the docs must keep working.';
  v_item uuid;
  v_stored_goal text;
  v_claim record;
  v_beat record;
  v_fail record;
  v_req jsonb;
  v_good jsonb;
  v_broken jsonb;
  v_case text;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  -- Whitespace is not a goal, even though it is printable and within bounds.
  foreach v_case in array array[E'\n\t', '    ', E' \n '] loop
    ok := false; v_message := null;
    begin perform 1 from public.submit_evolve_work(v_p_one, v_case, null) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'the goal must be nonblank and at most 4000 characters' then
      raise exception 'a whitespace-only goal was accepted (%)',
        coalesce(v_message,'no error');
    end if;
  end loop;

  select t.id, t.goal into v_item, v_stored_goal
    from public.submit_evolve_work(v_p_one, v_goal, null) t;
  if v_item is null or v_stored_goal <> v_goal then
    raise exception 'a goal containing a backslash and path-like text was not accepted '
      'and stored verbatim';
  end if;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the semantic admission fixture was not the item handed out';
  end if;
  if v_claim.goal <> v_goal then
    raise exception 'the claim did not hand the worker the submitted goal verbatim';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the semantic admission heartbeat was refused (%)', v_beat.reason;
  end if;

  v_req := jsonb_build_object(
    'goal', v_claim.goal,
    -- Prose that mentions a regex and a path, which is what a reviewer of this
    -- request would actually write.
    'acceptance_criteria', jsonb_build_array(
      'the matcher accepts \d+ and rejects a bare backslash',
      'the /usr/local/bin example in the documentation still resolves'),
    'constraints', jsonb_build_array('no change outside the import matcher'));
  v_good := pg_temp.ev_payload(v_source, v_config, repeat('1',64), v_req,
    jsonb_build_array('stage:requirements'));
  v_good := jsonb_set(v_good, array['review','summary'],
    to_jsonb('the \d escape and the /usr/local/bin example are both covered'::text));

  -- A null or wrong-typed field is refused, and nothing is recorded. The
  -- assertion is on the behaviour, not on which message explains it: some of
  -- these are caught by the shared no-JSON-null rule and the rest by the
  -- per-field JSON string requirement.
  foreach v_case in array array['payload.source_sha256.null','payload.source_sha256.number',
                                'payload.artifact_sha256.number','payload.goal.null',
                                'review.verdict.null','review.verdict.number',
                                'review.reviewer_model.null','review.reviewer_digest.number',
                                'review.findings.severity.null'] loop
    v_broken := v_good;
    if v_case = 'payload.source_sha256.null' then
      v_broken := jsonb_set(v_broken, array['source_sha256'], 'null'::jsonb);
    elsif v_case = 'payload.source_sha256.number' then
      v_broken := jsonb_set(v_broken, array['source_sha256'], '1234'::jsonb);
    elsif v_case = 'payload.artifact_sha256.number' then
      v_broken := jsonb_set(v_broken, array['artifact_sha256'], '1'::jsonb);
    elsif v_case = 'payload.goal.null' then
      v_broken := jsonb_set(v_broken, array['artifact','goal'], 'null'::jsonb);
    elsif v_case = 'review.verdict.null' then
      v_broken := jsonb_set(v_broken, array['review','verdict'], 'null'::jsonb);
    elsif v_case = 'review.verdict.number' then
      v_broken := jsonb_set(v_broken, array['review','verdict'], '0'::jsonb);
    elsif v_case = 'review.reviewer_model.null' then
      v_broken := jsonb_set(v_broken, array['review','reviewer_model'], 'null'::jsonb);
    elsif v_case = 'review.reviewer_digest.number' then
      v_broken := jsonb_set(v_broken, array['review','reviewer_digest'], '64'::jsonb);
    else
      v_broken := jsonb_set(v_broken, array['review','verdict'], '"rework"'::jsonb);
      v_broken := jsonb_set(v_broken, array['review','findings'], jsonb_build_array(
        jsonb_build_object('severity', null::text, 'detail', 'an unlabelled objection',
          'evidence_id', 'stage:requirements')));
    end if;
    ok := false; v_message := null;
    begin perform 1 from public.record_evolve_stage(
      v_claim.run_id, v_claim.lease_token, 'requirements', v_broken) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok then
      raise exception 'payload case % was accepted, so a null or wrong-typed field passed '
        'its grammar check as NULL', v_case;
    end if;
    select count(*) into n from public.evolve_stages s where s.run_id = v_claim.run_id;
    if n <> 0 then
      raise exception 'payload case % was refused but still recorded a stage', v_case;
    end if;
  end loop;

  -- And the honest request records, which is the whole point: a goal about
  -- regular expressions and paths can be reviewed.
  perform 1 from public.record_evolve_stage(
    v_claim.run_id, v_claim.lease_token, 'requirements', v_good) t;
  select count(*) into n from public.evolve_stages s
   where s.run_id = v_claim.run_id and s.stage = 'requirements'
     and s.payload->'artifact'->>'goal' = v_goal;
  if n <> 1 then
    raise exception 'a requirements stage repeating an ordinary prose goal verbatim was '
      'not recorded';
  end if;

  select * into v_fail from public.fail_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'process_rejected') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' then
    raise exception 'the semantic admission fixture was not closed terminally';
  end if;
end
$semantic_admission$;

-- ---------------------------------------------------------------------------
-- 9. Artifact authority. A browser cannot upload or register, a worker cannot
--    stage bytes for another attempt, a registration must name bytes that
--    exist with the declared size, and an object that was never registered is
--    invisible to every reader.
-- ---------------------------------------------------------------------------
do $artifacts$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_stranger uuid := '6d444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_worker_b uuid := '6f666666-6666-4666-8666-666666666666';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_candidate text := repeat('c', 64);
  v_orphan text := repeat('7', 64);
  v_item uuid;
  v_claim record;
  v_beat record;
  v_path text;
  v_orphan_path text;
  v_id uuid;
  v_again uuid;
  v_replayed boolean;
  v_stored text;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'Register a candidate archive for review.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the artifact fixture was not the item handed out';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then raise exception 'the artifact fixture heartbeat was refused'; end if;
  v_path := v_claim.run_id::text || '/candidate/' || v_candidate;
  v_orphan_path := v_claim.run_id::text || '/candidate/' || v_orphan;

  -- Nothing can be registered before the bytes exist.
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 4096) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'the artifact must be uploaded to the private bucket before it is registered' then
    raise exception 'an artifact row was created for bytes nobody uploaded (%)',
      coalesce(v_message,'no error');
  end if;

  -- Bounds and kinds.
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'archive', v_candidate, 4096) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'artifact kind must be patch, candidate, receipt or trace' then
    raise exception 'an unknown artifact kind was accepted (%)', coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 12582913) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'artifact bytes must be within the bound for its kind' then
    raise exception 'an oversized candidate was accepted (%)', coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'receipt', v_candidate, 1048577) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'artifact bytes must be within the bound for its kind' then
    raise exception 'an oversized receipt was accepted (%)', coalesce(v_message,'no error');
  end if;

  -- Upload authority, evaluated as each account against the real policy
  -- predicate the storage policy uses.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  if private.may_upload_evolve_artifact(v_path) then
    raise exception 'a project engineer may upload into the private artifact bucket';
  end if;
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  if private.may_upload_evolve_artifact(v_path) then
    raise exception 'a project viewer may upload into the private artifact bucket';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_b::text, true);
  if private.may_upload_evolve_artifact(v_path) then
    raise exception 'a foreign worker may upload into another attempt''s artifact path';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  if not private.may_upload_evolve_artifact(v_path) then
    raise exception 'the live worker of this attempt may not upload its own candidate';
  end if;
  if private.may_upload_evolve_artifact(
       gen_random_uuid()::text || '/candidate/' || v_candidate) then
    raise exception 'a worker may upload into a path that names no attempt of its own';
  end if;
  if private.may_upload_evolve_artifact('../etc/passwd')
     or private.may_upload_evolve_artifact(v_claim.run_id::text || '/secret/' || v_candidate)
     or private.may_upload_evolve_artifact(v_claim.run_id::text || '/candidate/not-a-digest') then
    raise exception 'a path outside <run_id>/<kind>/<sha256> was accepted for upload';
  end if;

  -- And the same denial as a real INSERT: the engineer's session is refused by
  -- row level security.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  ok := false; v_message := null;
  begin
    insert into storage.objects(bucket_id, name, owner, metadata)
    values ('evolve-artifacts', v_path, v_engineer,
            jsonb_build_object('size', 4096));
  exception
    when insufficient_privilege then ok := true;
    when others then v_message := sqlstate || ' ' || sqlerrm;
  end;
  if not ok then
    raise exception 'a browser session was not refused by row level security when uploading '
      'into the private artifact bucket (%)', coalesce(v_message, 'the insert succeeded');
  end if;

  -- The Storage service writes the object row for the worker's upload.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  perform pg_temp.ev_store(v_claim.run_id, 'candidate', v_candidate, 4096, v_worker_a);
  perform pg_temp.ev_store(v_claim.run_id, 'candidate', v_orphan, 2048, v_worker_a);

  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 512) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'the uploaded artifact size does not match the registered size' then
    raise exception 'a registration disagreed with the stored bytes and was accepted (%)',
      coalesce(v_message,'no error');
  end if;

  select t.id, t.storage_path, t.replayed into v_id, v_stored, v_replayed
    from public.register_evolve_artifact(
      v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 4096) t;
  if v_id is null or v_replayed or v_stored <> v_path then
    raise exception 'the candidate registration did not derive the canonical storage path';
  end if;
  select count(*) into n from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 4096) t;
  if n <> 1 then
    raise exception 'an exact artifact repetition returned % rows instead of one replay', n;
  end if;
  select t.id, t.replayed into v_again, v_replayed
    from public.register_evolve_artifact(
      v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 4096) t;
  if v_again <> v_id or not v_replayed then
    raise exception 'a repeated registration created a second artifact row';
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_claim.run_id, v_claim.lease_token, 'candidate', v_candidate, 8192) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this artifact is already registered with a different size' then
    raise exception 'a registered artifact was redescribed (%)', coalesce(v_message,'no error');
  end if;

  -- Read scope. Registered bytes are readable with a current project grant;
  -- the staged object nobody registered is readable by no client at all.
  foreach v_id in array array[v_engineer, v_viewer, v_worker_a] loop
    perform set_config('request.jwt.claim.sub', v_id::text, true);
    select count(*) into n from storage.objects o
     where o.bucket_id = 'evolve-artifacts' and o.name = v_path;
    if n <> 1 then
      raise exception 'authorized reader % cannot fetch the registered candidate', v_id;
    end if;
    select count(*) into n from storage.objects o
     where o.bucket_id = 'evolve-artifacts' and o.name = v_orphan_path;
    if n <> 0 then
      raise exception 'reader % can fetch an object that was never registered', v_id;
    end if;
    select count(*) into n from public.evolve_artifacts a where a.id = v_again;
    if n <> 1 then
      raise exception 'authorized reader % cannot see the registered artifact row', v_id;
    end if;
  end loop;
  foreach v_id in array array[v_stranger, v_worker_b] loop
    perform set_config('request.jwt.claim.sub', v_id::text, true);
    select count(*) into n from storage.objects o
     where o.bucket_id = 'evolve-artifacts';
    if n <> 0 then
      raise exception '% can fetch private candidate archives of a project it does not hold', v_id;
    end if;
    select count(*) into n from public.evolve_artifacts a;
    if n <> 0 then
      raise exception '% can read artifact rows of a project it does not hold', v_id;
    end if;
  end loop;

  -- Cancellation fences the running attempt that holds these bytes.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  perform 1 from public.cancel_work_item(v_item) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_claim.run_id and r.status = 'cancelled';
  if n <> 1 then raise exception 'cancelling the artifact fixture did not fence its attempt'; end if;
end
$artifacts$;

-- ---------------------------------------------------------------------------
-- 10. One complete reviewed attempt, then the human decision: who may approve,
--     what exactly they approve, and what an approval activates.
-- ---------------------------------------------------------------------------
do $approval$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_stranger uuid := '6d444444-4444-4444-8444-444444444444';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_worker_b uuid := '6f666666-6666-4666-8666-666666666666';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_config text := repeat('9', 64);
  v_candidate text := repeat('c', 64);
  v_patch text := repeat('d', 64);
  v_item uuid;
  v_run uuid;
  v_token uuid;
  v_actor uuid;
  v_decision record;
  v_beat record;
  v_finish record;
  v_fail record;
  v_lesson uuid;
  v_status text;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'Repair the reported regression and prove the behaviour is preserved.', null) t;
  v_run := pg_temp.ev_chain(v_p_one, v_worker_a, v_source_digest, v_config,
                            v_candidate, v_patch);
  v_token := current_setting('oryveta.ev_token')::uuid;

  -- The attempt is finished, unleased and waiting for a human.
  select count(*) into n from public.work_items w
   where w.id = v_item and w.status = 'awaiting_approval' and w.decided_at is null
     and w.evolve_config_sha256 = v_config;
  if n <> 1 then raise exception 'the completed attempt did not leave the work item awaiting approval'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'awaiting_approval' and r.phase = 'awaiting_approval'
     and r.finished_at is not null
     and r.result->'summary'->>'candidate_sha256' = v_candidate
     and r.result->'summary'->>'config_sha256' = v_config;
  if n <> 1 then raise exception 'the attempt that ended execution was not recorded as awaiting approval'; end if;
  select count(*) into n from public.evolve_stages s where s.run_id = v_run;
  if n <> 7 then raise exception 'the reviewed chain is % stages instead of seven', n; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'awaiting_approval';
  if n <> 1 then raise exception 'the hand-off to a human was not recorded as an event'; end if;

  -- No lease survives, so the worker can publish nothing further.
  select * into v_beat from public.heartbeat_evolve_run(v_run, v_token, 'done') t;
  if v_beat.lease_valid or v_beat.reason <> 'not_running' then
    raise exception 'an attempt awaiting approval still reported a live lease (%)',
      coalesce(v_beat.reason,'no reason');
  end if;
  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'not_running' then
    raise exception 'an attempt awaiting approval was finished twice (%)',
      coalesce(v_finish.reason,'no reason');
  end if;
  select * into v_fail from public.fail_evolve_run(v_run, v_token, 'review_rejected') t;
  if v_fail.accepted or v_fail.reason <> 'not_running' then
    raise exception 'an attempt awaiting approval recorded a late failure (%)',
      coalesce(v_fail.reason,'no reason');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'learning_review',
    '{}'::jsonb) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this attempt is no longer running' then
    raise exception 'a stage was recorded after execution ended (%)',
      coalesce(v_message,'no error');
  end if;

  -- Read scope of the reviewed record.
  foreach v_actor in array array[v_owner, v_engineer, v_viewer, v_worker_a] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    select count(*) into n from public.evolve_stages s where s.run_id = v_run;
    if n <> 7 then raise exception 'authorized reader % cannot see the reviewed stages', v_actor; end if;
  end loop;
  foreach v_actor in array array[v_stranger, v_worker_b] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    select count(*) into n from public.evolve_stages s;
    if n <> 0 then raise exception '% can read reviewed stages of another project', v_actor; end if;
    select count(*) into n from public.evolve_lessons l;
    if n <> 0 then raise exception '% can read lessons of another project', v_actor; end if;
  end loop;

  -- Candidate lessons are not memory: the worker cannot see them at all, and
  -- an admin can inspect them.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then
    raise exception 'a worker can retrieve lessons no human has approved';
  end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'candidate'
     and l.source_sha256 = right(v_source_digest, 64) and l.config_sha256 = v_config;
  if n <> 2 then
    raise exception 'the proposed lessons were not recorded as digest-scoped candidates';
  end if;

  -- Nobody below admin may decide, and the refusal is the same as for a
  -- missing row.
  foreach v_actor in array array[v_engineer, v_viewer, v_stranger, v_worker_a] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    ok := false; v_message := null;
    begin perform 1 from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'work item not found' then
      raise exception '% approved a review candidate (%)', v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(v_item, v_run, repeat('0',64), true) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'that candidate digest is not the one this attempt produced' then
    raise exception 'an approval named a candidate this attempt never produced (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(
    v_item, current_setting('oryveta.ev_run_reject')::uuid, v_candidate, true) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'that attempt is not the candidate awaiting approval' then
    raise exception 'an approval named an attempt that is not the candidate (%)',
      coalesce(v_message,'no error');
  end if;

  -- The real decision.
  select * into v_decision from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
  if not v_decision.approved or v_decision.status <> 'succeeded'
     or v_decision.reason <> 'ok' or v_decision.lessons_activated <> 1
     or v_decision.candidate_sha256 <> v_candidate then
    raise exception 'the administrator approval was not applied as documented (%)',
      coalesce(v_decision.reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = v_item and w.status = 'succeeded' and w.error_code is null
     and w.decided_by = v_owner and w.decided_at is not null;
  if n <> 1 then raise exception 'the approval was not attributed to the deciding admin'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'succeeded' and r.phase = 'done';
  if n <> 1 then raise exception 'the approved attempt was not closed as succeeded'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'approved';
  if n <> 1 then raise exception 'the approval was not recorded as an event'; end if;

  -- Only the lesson its reviewer passed became memory, and only for the exact
  -- source and configuration it was learned under.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'approved' and l.lesson_index = 0
     and l.source_sha256 = right(v_source_digest, 64) and l.config_sha256 = v_config;
  if n <> 1 then
    raise exception 'the approved lesson is not retrievable by the project worker';
  end if;
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 1 then
    raise exception 'a worker can retrieve a lesson the learning review rejected';
  end if;
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'approved'
     and l.config_sha256 = repeat('8', 64);
  if n <> 0 then
    raise exception 'an approved lesson is retrievable under a configuration it was never '
      'learned under';
  end if;

  -- Idempotent and stale decisions.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
  if n <> 1 then raise exception 'a replayed approval returned % rows instead of one', n; end if;
  select * into v_decision from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
  if not v_decision.approved or v_decision.reason <> 'already_decided'
     or v_decision.lessons_activated <> 1 then
    raise exception 'a repeated identical approval was not idempotent (%)',
      coalesce(v_decision.reason,'no reason');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(v_item, v_run, v_candidate, false) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this work item is no longer awaiting approval' then
    raise exception 'an approved candidate was rejected afterwards (%)',
      coalesce(v_message,'no error');
  end if;

  -- Lesson revocation is an admin act and takes effect immediately.
  select l.id into v_lesson from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'approved';
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.revoke_evolve_lesson(v_lesson) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'lesson not found' then
    raise exception 'a project engineer revoked an activated lesson (%)',
      coalesce(v_message,'no error');
  end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.status, t.already_revoked into v_status, ok
    from public.revoke_evolve_lesson(v_lesson) t;
  if v_status <> 'revoked' or ok then
    raise exception 'the admin revocation did not withdraw the lesson';
  end if;
  select count(*) into n from public.revoke_evolve_lesson(v_lesson) t;
  if n <> 1 then raise exception 'a repeated revocation returned % rows instead of one', n; end if;
  select t.already_revoked into ok from public.revoke_evolve_lesson(v_lesson) t;
  if not ok then raise exception 'a repeated revocation was not idempotent'; end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then
    raise exception 'a revoked lesson is still retrievable by the project worker';
  end if;
end
$approval$;

-- ---------------------------------------------------------------------------
-- 11. A stale lease. The deadline is moved into the past of clock_timestamp(),
--     the clock the runtime judges leases on, and every publishing call of
--     that attempt is refused before the reclaim recovers the work item.
-- ---------------------------------------------------------------------------
do $stale_setup$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_item uuid;
  v_claim record;
  v_beat record;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'Prove a stale lease cannot publish anything.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the stale lease fixture was not the item handed out';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), v_source_digest, 300) t;
  if not v_beat.lease_valid then raise exception 'the stale lease fixture heartbeat was refused'; end if;
  perform set_config('oryveta.ev_item_stale', v_item::text, true);
  perform set_config('oryveta.ev_run_stale', v_claim.run_id::text, true);
  perform set_config('oryveta.ev_token_stale', v_claim.lease_token::text, true);
end
$stale_setup$;

reset role;
do $stale_stage$
declare
  v_run uuid := current_setting('oryveta.ev_run_stale')::uuid;
  n integer;
begin
  update public.factory_runs r
     set lease_expires_at = clock_timestamp() - interval '1 second'
   where r.id = v_run and r.status = 'running';
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the stale lease fixture did not match exactly one attempt'; end if;
end
$stale_stage$;

set local role authenticated;
do $stale$
declare
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_item uuid := current_setting('oryveta.ev_item_stale')::uuid;
  v_run uuid := current_setting('oryveta.ev_run_stale')::uuid;
  v_token uuid := current_setting('oryveta.ev_token_stale')::uuid;
  v_source text := repeat('e', 64);
  v_config text := repeat('9', 64);
  v_goal text;
  v_beat record;
  v_finish record;
  v_fail record;
  v_claim record;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select w.goal into v_goal from public.work_items w where w.id = v_item;

  select * into v_beat from public.heartbeat_evolve_run(v_run, v_token, 'requirements') t;
  if v_beat.lease_valid or v_beat.reason <> 'lease_lost' then
    raise exception 'a heartbeat on a lease that expired on the wall clock was accepted (%)',
      coalesce(v_beat.reason,'no reason');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      jsonb_build_object('goal', v_goal,
        'acceptance_criteria', jsonb_build_array('published behind a dead lease'),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'the lease for this attempt is no longer valid' then
    raise exception 'a stage was published behind an expired lease (%)',
      coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.register_evolve_artifact(
    v_run, v_token, 'candidate', repeat('c',64), 4096) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'the lease for this attempt is no longer valid' then
    raise exception 'an artifact was registered behind an expired lease (%)',
      coalesce(v_message,'no error');
  end if;

  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'lease_lost' then
    raise exception 'a completion behind an expired lease was accepted (%)',
      coalesce(v_finish.reason,'no reason');
  end if;
  select * into v_fail from public.fail_evolve_run(v_run, v_token, 'review_rejected') t;
  if v_fail.accepted or v_fail.reason <> 'lease_lost' then
    raise exception 'a failure report behind an expired lease was accepted (%)',
      coalesce(v_fail.reason,'no reason');
  end if;
  select count(*) into n from public.evolve_stages s where s.run_id = v_run;
  if n <> 0 then raise exception 'a refused call still wrote a stage'; end if;

  -- The reclaim recovers the work item on the same clock.
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.run_id is null or v_claim.work_item_id <> v_item or v_claim.attempt <> 2 then
    raise exception 'the abandoned Evolve attempt was not reclaimed as attempt two';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'failed' and r.error_code = 'lease_expired'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the stale attempt was not closed as lease_expired'; end if;

  select * into v_fail from public.fail_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'process_rejected') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' then
    raise exception 'the stale lease fixture was not closed terminally';
  end if;
end
$stale$;

-- ---------------------------------------------------------------------------
-- 12. Cancellation of a candidate that is already awaiting a human decision.
--     Cancelling must stop the work, not leave an approvable row behind.
-- ---------------------------------------------------------------------------
do $cancel_awaiting$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_config text := repeat('9', 64);
  v_candidate text := repeat('c', 64);
  v_patch text := repeat('d', 64);
  v_item uuid;
  v_run uuid;
  v_status text;
  v_terminal boolean;
  v_fenced integer;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'A candidate the submitter changes their mind about.', null) t;
  v_run := pg_temp.ev_chain(v_p_one, v_worker_a, v_source_digest, v_config,
                            v_candidate, v_patch);

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.status, t.already_terminal, t.fenced_runs into v_status, v_terminal, v_fenced
    from public.cancel_work_item(v_item) t;
  if v_status <> 'cancelled' or v_terminal or v_fenced <> 1 then
    raise exception 'cancelling a candidate awaiting approval did not fence its attempt';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'cancelled' and r.error_code = 'cancelled'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the cancelled candidate attempt was not closed'; end if;
  -- Rejected lessons are admin-visible only; inspect retention as the owner.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'rejected';
  if n <> 2 then
    raise exception 'the lessons of a cancelled attempt were left as candidates';
  end if;
  -- This attempt's learning review is on record, so its analysis happened and
  -- was simply never approved. Cancelling it must retain that evidence and must
  -- not claim the attempt received no learning analysis.
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.result ? 'summary'
     and not (r.result ? 'learning_unavailable');
  if n <> 1 then
    raise exception 'cancelling a reviewed candidate rewrote its retained result evidence';
  end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this work item is no longer awaiting approval' then
    raise exception 'a cancelled candidate was approved afterwards (%)',
      coalesce(v_message,'no error');
  end if;
end
$cancel_awaiting$;

-- ---------------------------------------------------------------------------
-- 13. Worker revocation. It fences an attempt that is still running and an
--     attempt whose candidate is waiting for a decision, and an approval can
--     never reauthorize work whose producer lost its authority.
-- ---------------------------------------------------------------------------
do $revocation$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_reg_a uuid := current_setting('oryveta.ev_reg_a')::uuid;
  v_source_digest text := 'sha256:' || repeat('e', 64);
  v_config text := repeat('9', 64);
  v_candidate text := repeat('c', 64);
  v_patch text := repeat('d', 64);
  v_item_wait uuid;
  v_run_wait uuid;
  v_item_run uuid;
  v_claim record;
  v_beat record;
  v_id uuid;
  v_enabled boolean;
  v_fenced integer;
  ok boolean;
  v_message text;
  n integer;
begin
  -- (a) a candidate waiting for a decision
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item_wait from public.submit_evolve_work(
    v_p_one, 'A candidate whose worker identity is revoked before the decision.', null) t;
  v_run_wait := pg_temp.ev_chain(v_p_one, v_worker_a, v_source_digest, v_config,
                                 v_candidate, v_patch);

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.id, t.enabled, t.fenced_runs into v_id, v_enabled, v_fenced
    from public.revoke_project_worker(v_p_one, v_worker_a) t;
  if v_id <> v_reg_a or v_enabled or v_fenced <> 1 then
    raise exception 'revocation did not fence the candidate awaiting a decision';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_wait and r.status = 'cancelled' and r.error_code = 'worker_revoked'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the revoked worker''s candidate attempt was not closed'; end if;
  select count(*) into n from public.work_items w
   where w.id = v_item_wait and w.status = 'failed' and w.error_code = 'worker_revoked'
     and w.decided_at is null;
  if n <> 1 then
    raise exception 'the work item of a revoked worker''s candidate was not failed terminally';
  end if;
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run_wait and l.status = 'rejected';
  if n <> 2 then
    raise exception 'the lessons of a revoked worker''s attempt were left as candidates';
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(v_item_wait, v_run_wait, v_candidate, true) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this work item is no longer awaiting approval' then
    raise exception 'an approval reauthorized work whose worker was revoked (%)',
      coalesce(v_message,'no error');
  end if;

  -- A revoked worker identity loses its read scope as well.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.evolve_stages s;
  if n <> 0 then raise exception 'a revoked worker identity still reads reviewed stages'; end if;
  select count(*) into n from public.evolve_artifacts a;
  if n <> 0 then raise exception 'a revoked worker identity still reads artifact rows'; end if;
  select count(*) into n from storage.objects o where o.bucket_id = 'evolve-artifacts';
  if n <> 0 then
    raise exception 'a revoked worker identity can still fetch private candidate archives';
  end if;
  -- While the project's readers keep theirs.
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  select count(*) into n from public.evolve_stages s where s.run_id = v_run_wait;
  if n <> 7 then
    raise exception 'revoking a worker removed the reviewed record from the project readers';
  end if;

  -- (b) a running attempt. Re-registration re-enables the same row.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.id, t.enabled into v_id, v_enabled
    from public.register_project_worker(v_p_one, v_worker_a, 'Evolve worker A') t;
  if v_id <> v_reg_a or not v_enabled then
    raise exception 're-registering the worker did not re-enable its registration';
  end if;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item_run from public.submit_evolve_work(
    v_p_one, 'An attempt interrupted by a revocation while it is running.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item_run then
    raise exception 'the running revocation fixture was not the item handed out';
  end if;

  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.fenced_runs into v_fenced
    from public.revoke_project_worker(v_p_one, v_worker_a) t;
  if v_fenced <> 1 then raise exception 'revocation did not fence the running attempt'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_claim.run_id and r.status = 'cancelled'
     and r.error_code = 'worker_revoked';
  if n <> 1 then raise exception 'the running attempt of a revoked worker was not cancelled'; end if;
  select count(*) into n from public.work_items w
   where w.id = v_item_run and w.status = 'queued' and w.error_code = 'worker_revoked'
     and w.attempts = 1;
  if n <> 1 then
    raise exception 'the running work item of a revoked worker was not returned to the queue';
  end if;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'requirements') t;
  if v_beat.lease_valid or v_beat.reason <> 'worker_not_registered' then
    raise exception 'a revoked worker was not told its registration is gone (%)',
      coalesce(v_beat.reason,'no reason');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.claim_evolve_work(v_p_one, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker identity is not registered for this project' then
    raise exception 'a revoked worker could still claim Evolve work (%)',
      coalesce(v_message,'no error');
  end if;

  -- The queue is left with one requeued item and no enabled worker, which is
  -- exactly the state an operator sees after revoking a worker mid-flight.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  perform 1 from public.cancel_work_item(v_item_run) t;
end
$revocation$;

-- ---------------------------------------------------------------------------
-- Drivers for the diagnostic side branch. ev_report builds a failure report in
-- the one accepted shape, where a NULL source becomes the JSON null that says
-- no snapshot was ever fetched; ev_rejected turns a stage payload into the
-- retained evidence of a review that refused it; ev_report_error reduces what
-- the real RPC did with a report to one comparable string, so a table of
-- forged reports can be driven without hiding which rule refused which.
-- ---------------------------------------------------------------------------
reset role;

create function pg_temp.ev_report(
  p_code text, p_stage text, p_source text, p_config text, p_checks jsonb,
  p_status text, p_reason text, p_lessons jsonb, p_decisions jsonb)
returns jsonb language sql immutable as $report$
  select jsonb_build_object(
    'schema_version', 1,
    'error_code', p_code,
    'failed_stage', p_stage,
    'source_sha256', p_source,
    'config_sha256', p_config,
    'checks', p_checks,
    'learning_status', p_status,
    'learning_reason', p_reason,
    'lessons', p_lessons,
    'decisions', p_decisions,
    'reviewer_model', 'qwen3:8b',
    'reviewer_digest', repeat('b', 64))
$report$;

create function pg_temp.ev_check(p_name text, p_passed boolean)
returns jsonb language sql immutable as $check$
  select jsonb_build_object('name', p_name, 'passed', p_passed)
$check$;

create function pg_temp.ev_lesson(p_summary text, p_evidence jsonb)
returns jsonb language sql immutable as $lesson$
  select jsonb_build_object(
    'summary', p_summary,
    'applicability', 'this repository at this snapshot',
    'evidence_ids', p_evidence,
    'counterexamples', jsonb_build_array())
$lesson$;

create function pg_temp.ev_decision(p_index integer, p_verdict text)
returns jsonb language sql immutable as $decision$
  select jsonb_build_object('index', p_index, 'verdict', p_verdict,
    'reason', 'judged against the recorded evidence of this attempt')
$decision$;

create function pg_temp.ev_rejected(p_payload jsonb, p_detail text, p_evidence text)
returns jsonb language sql immutable as $rejected$
  select jsonb_set(
           jsonb_set(p_payload, '{review,verdict}', '"rework"'::jsonb),
           '{review,findings}',
           jsonb_build_array(jsonb_build_object(
             'severity', 'blocking', 'detail', p_detail, 'evidence_id', p_evidence)))
$rejected$;

create function pg_temp.ev_report_error(p_run uuid, p_token uuid, p_report jsonb)
returns text language plpgsql as $report_error$
declare
  v_accepted boolean;
  v_reason text;
begin
  select t.accepted, t.reason into v_accepted, v_reason
    from public.record_evolve_failure_report(p_run, p_token, p_report) t;
  return case when v_accepted then 'accepted:' else 'refused:' end || coalesce(v_reason, '');
exception when others then return 'error:' || sqlerrm;
end
$report_error$;

set local role authenticated;

-- ---------------------------------------------------------------------------
-- 14. A protected verification that failed. What a human is shown has to be
--     the outcomes the attempt actually measured: a report cannot invent a
--     snapshot, a configuration, a check or a citation, cannot contradict the
--     stage that recorded an outcome, cannot be rewritten once stored, and
--     cannot carry the attempt forward to a finish or an approval.
-- ---------------------------------------------------------------------------
do $failed_verification$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_viewer uuid := '6c333333-3333-4333-8333-333333333333';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_worker_b uuid := '6f666666-6666-4666-8666-666666666666';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source text := repeat('7', 64);
  v_config text := repeat('9', 64);
  v_candidate text := repeat('3', 64);
  v_patch text := repeat('4', 64);
  v_checks jsonb;
  v_report jsonb;
  v_item uuid;
  v_run uuid;
  v_token uuid;
  v_goal text;
  v_claim record;
  v_beat record;
  v_finish record;
  v_fail record;
  v_case record;
  v_got text;
  v_accepted boolean;
  v_reason text;
  ok boolean;
  v_message text;
  n integer;
begin
  -- Section 13 leaves worker A revoked, which is the state an operator ends a
  -- revocation in. This fixture needs a serving worker identity again.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  perform 1 from public.register_project_worker(v_p_one, v_worker_a, 'Evolve worker A') t;

  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'Prove a failed protected verification stays observable.', null) t;
  select w.goal into v_goal from public.work_items w where w.id = v_item;

  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the failed verification fixture was not the item handed out';
  end if;
  v_run := v_claim.run_id;
  v_token := v_claim.lease_token;
  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f', 40), 'sha256:' || v_source, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the failed verification fixture heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  perform pg_temp.ev_store(v_run, 'candidate', v_candidate, 4096, v_worker_a);
  perform pg_temp.ev_store(v_run, 'patch', v_patch, 512, v_worker_a);
  perform 1 from public.register_evolve_artifact(
    v_run, v_token, 'candidate', v_candidate, 4096) t;
  perform 1 from public.register_evolve_artifact(v_run, v_token, 'patch', v_patch, 512) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1', 64),
      jsonb_build_object('goal', v_goal,
        'acceptance_criteria', jsonb_build_array('the protected behaviour is preserved'),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'plan',
    pg_temp.ev_payload(v_source, v_config, repeat('2', 64),
      jsonb_build_object('steps', jsonb_build_array('reproduce, then bound the change'),
        'allowed_paths', jsonb_build_array('engine/oryveta_engine'),
        'risks', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  perform 1 from public.record_evolve_stage(v_run, v_token, 'implementation',
    pg_temp.ev_payload(v_source, v_config, v_candidate,
      jsonb_build_object('candidate_sha256', v_candidate, 'patch_sha256', v_patch,
        'changed_paths', jsonb_build_array('engine/oryveta_engine/patches.py'),
        'summary', 'one bounded change inside the planned paths'),
      jsonb_build_array('artifact:' || v_candidate))) t;
  -- The honest failed verification: a stage whose independent review refused
  -- the candidate, retained as the evidence nothing may be built on.
  perform 1 from public.record_evolve_stage(v_run, v_token, 'verification',
    pg_temp.ev_rejected(
      pg_temp.ev_payload(v_source, v_config, v_candidate,
        jsonb_build_object('candidate_sha256', v_candidate,
          'checks', jsonb_build_array(pg_temp.ev_check('pytest', false),
                                      pg_temp.ev_check('preservation', true)),
          'baseline_reproduced', true,
          'preservation_passed', true,
          'verification', 'failed'),
        jsonb_build_array('check:pytest', 'check:preservation')),
      'the protected regression check did not pass', 'check:pytest')) t;

  v_checks := jsonb_build_array(pg_temp.ev_check('pytest', false),
                                pg_temp.ev_check('preservation', true));
  v_report := pg_temp.ev_report('verification_failed', 'verification', v_source, v_config,
    v_checks, 'reviewed', 'completed',
    jsonb_build_array(
      pg_temp.ev_lesson('the protected check fails before the candidate is rebuilt',
        jsonb_build_array('check:pytest', 'failure:verification_failed')),
      pg_temp.ev_lesson('an unsupported generalisation about every repository',
        jsonb_build_array('stage:verification'))),
    jsonb_build_array(pg_temp.ev_decision(0, 'pass'), pg_temp.ev_decision(1, 'reject')));

  -- Every forged account of this failure, each refused by the rule it breaks.
  for v_case in select * from (values
      -- a code that names a failed verification must name what failed
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,
         jsonb_build_array(pg_temp.ev_check('build', true)),
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:a verification_failed report must record the check outcomes that failed'),
      -- and it may not contradict the stage that recorded an outcome
      (pg_temp.ev_report('review_rejected','verification',v_source,v_config,
         jsonb_build_array(pg_temp.ev_check('pytest', true)),
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:a failure report contradicts a check outcome this attempt recorded'),
      -- nor report one check twice
      (pg_temp.ev_report('review_rejected','verification',v_source,v_config,
         jsonb_build_array(pg_temp.ev_check('pytest', false),
                           pg_temp.ev_check('pytest', false)),
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:a failure report may report each check outcome once'),
      -- a forged snapshot identity
      (pg_temp.ev_report('verification_failed','verification',repeat('8',64),v_config,
         v_checks,'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:the report source digest is not the snapshot this attempt recorded'),
      -- a snapshot this attempt did fetch cannot be reported as never fetched
      (pg_temp.ev_report('verification_failed','verification',null,v_config,
         v_checks,'unavailable','no_source','[]'::jsonb,'[]'::jsonb),
       'error:this attempt recorded a snapshot, so the report may not claim it fetched none'),
      -- a forged operator configuration
      (pg_temp.ev_report('verification_failed','verification',v_source,repeat('1',64),
         v_checks,'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:the report config digest is not the operator config this work item is pinned to'),
      -- a stage this attempt published as passed is not the stage it failed in
      (pg_temp.ev_report('verification_failed','requirements',v_source,v_config,
         v_checks,'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:this attempt published that stage as passed, so it is not the stage it failed in'),
      -- a citation has to resolve to this attempt's own record
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed',
         jsonb_build_array(pg_temp.ev_lesson('cites a check nobody measured',
           jsonb_build_array('check:integration'))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:failure report evidence names a check outcome that is not on record'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed',
         jsonb_build_array(pg_temp.ev_lesson('cites a stage nobody recorded',
           jsonb_build_array('stage:audit'))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:failure report evidence names a stage this attempt has not recorded'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed',
         jsonb_build_array(pg_temp.ev_lesson('cites bytes nobody registered',
           jsonb_build_array('artifact:' || repeat('5',64)))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:failure report evidence names an artifact this attempt has not registered'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed',
         jsonb_build_array(pg_temp.ev_lesson('cites another attempt''s failure',
           jsonb_build_array('failure:review_rejected'))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:a failure citation must name this report''s own error code'),
      -- a lesson without a decision, and a decision without a lesson
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed',
         jsonb_build_array(pg_temp.ev_lesson('nobody judged this lesson',
           jsonb_build_array('check:pytest'))),
         '[]'::jsonb),
       'error:the failure analysis review must decide every extracted lesson exactly once'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','completed','[]'::jsonb,
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:the failure analysis review must decide every extracted lesson exactly once'),
      -- a reviewed analysis is exactly the completed one, in both directions
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'reviewed','extraction_failed','[]'::jsonb,'[]'::jsonb),
       'error:a reviewed failure analysis is the completed one; an unavailable analysis must '
       || 'record why it is unavailable'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'unavailable','completed','[]'::jsonb,'[]'::jsonb),
       'error:a reviewed failure analysis is the completed one; an unavailable analysis must '
       || 'record why it is unavailable'),
      -- an unavailable analysis has no lesson and no decision to carry
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'unavailable','model_unavailable',
         jsonb_build_array(pg_temp.ev_lesson('a lesson no reviewer judged',
           jsonb_build_array('check:pytest'))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:an unavailable failure analysis may carry no lesson and no decision'),
      -- and the shape itself is fixed: no extra field, no missing field and no
      -- JSON null standing in for a value
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb)
         || jsonb_build_object('operator_note','read from a host path'),
       'error:a failure report must contain exactly the fields schema_version, error_code, '
       || 'failed_stage, source_sha256, config_sha256, checks, learning_status, '
       || 'learning_reason, lessons, decisions, reviewer_model, reviewer_digest'),
      (pg_temp.ev_report('verification_failed','verification',v_source,v_config,v_checks,
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb) - 'checks',
       'error:a failure report must contain exactly the fields schema_version, error_code, '
       || 'failed_stage, source_sha256, config_sha256, checks, learning_status, '
       || 'learning_reason, lessons, decisions, reviewer_model, reviewer_digest'),
      (jsonb_set(pg_temp.ev_report('verification_failed','verification',v_source,v_config,
         v_checks,'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
         '{learning_reason}', 'null'::jsonb),
       'error:only source_sha256 may be a JSON null in a failure report')
    ) as t(report, expected)
  loop
    v_got := pg_temp.ev_report_error(v_run, v_token, v_case.report);
    if v_got <> v_case.expected then
      raise exception 'a forged failure report was not refused as expected: got % wanted %',
        v_got, v_case.expected;
    end if;
  end loop;

  -- Nothing a refused report claimed was stored.
  select count(*) into n from public.factory_runs r where r.id = v_run and r.result is null;
  if n <> 1 then raise exception 'a refused failure report still wrote a result'; end if;
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then raise exception 'a refused failure report still materialized a lesson'; end if;

  -- Only the live worker of this exact attempt may report on it. A worker of
  -- another project, a browser session and a reader are all told the same thing
  -- they are told about any attempt that is not theirs.
  perform set_config('request.jwt.claim.sub', v_worker_b::text, true);
  if pg_temp.ev_report_error(v_run, v_token, v_report) <> 'error:run not found' then
    raise exception 'a worker of another project could report on this attempt';
  end if;
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  if pg_temp.ev_report_error(v_run, v_token, v_report) <> 'error:run not found' then
    raise exception 'the submitter''s browser session could record a failure report';
  end if;
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  if pg_temp.ev_report_error(v_run, v_token, v_report) <> 'error:run not found' then
    raise exception 'a project reader could record a failure report';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  if pg_temp.ev_report_error(v_run, gen_random_uuid(), v_report) <> 'refused:lease_lost' then
    raise exception 'a failure report was accepted with a lease token the worker never held';
  end if;

  select t.accepted, t.reason into v_accepted, v_reason
    from public.record_evolve_failure_report(v_run, v_token, v_report) t;
  if not v_accepted or v_reason <> 'ok' then
    raise exception 'the honest failure report was refused (%)', coalesce(v_reason, 'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.result = jsonb_build_object('failure_report', v_report);
  if n <> 1 then
    raise exception 'the stored result is not exactly the one report that was accepted';
  end if;
  -- The failed outcome is readable as an outcome, not as an opaque code.
  select count(*) into n from public.factory_runs r,
       jsonb_array_elements(r.result->'failure_report'->'checks') c
   where r.id = v_run and c.value->>'name' = 'pytest' and c.value->'passed' = 'false'::jsonb;
  if n <> 1 then
    raise exception 'the check outcome that failed is not readable from the stored report';
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'failure_report';
  if n <> 1 then raise exception 'the failure report was not recorded as exactly one event'; end if;
  -- Its lessons are diagnostic rows carrying this attempt's own identity.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.origin = 'failure_report' and l.status = 'rejected'
     and l.source_sha256 = v_source and l.config_sha256 = v_config;
  if n <> 2 then
    raise exception 'the diagnostic lessons of a failed attempt were not recorded as rejected';
  end if;
  -- The decisions its reviewer actually made are retained for an administrator.
  select count(*) into n from public.factory_runs r
   where r.id = v_run
     and r.result->'failure_report'->'decisions'->1->>'verdict' = 'reject';
  if n <> 1 then raise exception 'the real review decisions were not retained in the result'; end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);

  -- Immutable: the same report replays, a different one is refused, and neither
  -- changes what is stored.
  if pg_temp.ev_report_error(v_run, v_token, v_report) <> 'accepted:replayed' then
    raise exception 'an exact repetition of a stored failure report was not a replay';
  end if;
  if pg_temp.ev_report_error(v_run, v_token,
       pg_temp.ev_report('review_rejected','verification',v_source,v_config,v_checks,
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb))
     <> 'refused:report_conflict' then
    raise exception 'a second and different account of one failure was accepted';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.result = jsonb_build_object('failure_report', v_report);
  if n <> 1 then raise exception 'a refused second report changed the stored one'; end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 2 then raise exception 'a replayed failure report materialized its lessons twice'; end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);

  -- The attempt may still hold its lease in order to fail, and may do nothing
  -- else: a finish is refused as the diagnostic branch it is on.
  select * into v_beat from public.heartbeat_evolve_run(v_run, v_token, null) t;
  if not v_beat.lease_valid then
    raise exception 'a worker that reported a failure could not hold its lease to fail (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  select * into v_finish from public.finish_evolve_run(v_run, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'failure_report_recorded' then
    raise exception 'a finish after a failure report was not refused as such (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;

  select * into v_fail from public.fail_evolve_run(v_run, v_token, 'verification_failed') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' or v_fail.retry_scheduled then
    raise exception 'the failed attempt was not closed terminally';
  end if;
  -- Failing the attempt preserves the report it is about, and adds no
  -- server-built unavailability over a report a worker really produced.
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'failed' and r.error_code = 'verification_failed'
     and r.result = jsonb_build_object('failure_report', v_report);
  if n <> 1 then
    raise exception 'failing the attempt did not preserve its failure report unchanged';
  end if;

  -- A diagnostic lesson is memory for nobody. The project's own worker identity
  -- and its readers see none of them; an administrator can inspect them.
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then
    raise exception 'a worker identity can read a failed attempt''s diagnostic lessons';
  end if;
  perform set_config('request.jwt.claim.sub', v_viewer::text, true);
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then
    raise exception 'a project reader can read a failed attempt''s diagnostic lessons';
  end if;
  -- While the failure report itself is exactly what a reader must be able to see.
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.result->'failure_report'->>'error_code' = 'verification_failed';
  if n <> 1 then raise exception 'a project reader cannot read the failure report'; end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run and l.status = 'rejected' and l.origin = 'failure_report';
  if n <> 2 then
    raise exception 'a project administrator cannot inspect the diagnostic lessons';
  end if;
  -- And a failed attempt is not a candidate anybody can approve.
  ok := false; v_message := null;
  begin perform 1 from public.decide_evolve_work(v_item, v_run, v_candidate, true) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this work item is no longer awaiting approval' then
    raise exception 'a failed attempt was approved as a review candidate (%)',
      coalesce(v_message, 'no error');
  end if;
end
$failed_verification$;

-- ---------------------------------------------------------------------------
-- 15. Unavailability is a truthful outcome. An attempt that never fetched a
--     snapshot, and one whose model never answered, record that no analysis
--     exists rather than a lesson nobody extracted - and once either record is
--     stored the attempt cannot publish a stage. A later attempt's approval
--     activates only what its own learning review passed: a failed attempt's
--     diagnostic lesson is never promoted by approving something else.
-- ---------------------------------------------------------------------------
do $unavailable_learning$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source text := repeat('7', 64);
  v_config text := repeat('9', 64);
  v_candidate text := repeat('a', 64);
  v_patch text := repeat('6', 64);
  v_item uuid;
  v_item_two uuid;
  v_run_one uuid;
  v_run_two uuid;
  v_run_three uuid;
  v_token uuid;
  v_goal text;
  v_claim record;
  v_beat record;
  v_finish record;
  v_fail record;
  v_decide record;
  v_case record;
  v_got text;
  v_report jsonb;
  ok boolean;
  v_message text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'An attempt whose snapshot never arrived.', null) t;
  select w.goal into v_goal from public.work_items w where w.id = v_item;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the unavailable learning fixture was not the item handed out';
  end if;
  v_run_one := v_claim.run_id;
  v_token := v_claim.lease_token;
  -- No snapshot heartbeat: this attempt never fetched source bytes.
  select * into v_beat from public.heartbeat_evolve_run(v_run_one, v_token, 'fetching_source') t;
  if not v_beat.lease_valid then
    raise exception 'the fixture heartbeat without a snapshot was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  for v_case in select * from (values
      -- without a snapshot there is nothing a lesson could be about
      (pg_temp.ev_report('fetch_failed','fetching_source',null,v_config,'[]'::jsonb,
         'reviewed','completed','[]'::jsonb,'[]'::jsonb),
       'error:an attempt that never fetched a snapshot has no admissible lesson'),
      (pg_temp.ev_report('fetch_failed','fetching_source',null,v_config,'[]'::jsonb,
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:an attempt that never fetched a snapshot has no admissible lesson'),
      -- and an attempt that fetched none cannot name one
      (pg_temp.ev_report('fetch_failed','fetching_source',v_source,v_config,'[]'::jsonb,
         'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb),
       'error:the report source digest is not the snapshot this attempt recorded'),
      (pg_temp.ev_report('fetch_failed','fetching_source',repeat('z',64),v_config,'[]'::jsonb,
         'unavailable','no_source','[]'::jsonb,'[]'::jsonb),
       'error:failure report digests must be 64 character lowercase hexadecimal'),
      -- an unavailable analysis still carries no lesson
      (pg_temp.ev_report('fetch_failed','fetching_source',null,v_config,'[]'::jsonb,
         'unavailable','no_source',
         jsonb_build_array(pg_temp.ev_lesson('extracted by nobody',
           jsonb_build_array('failure:fetch_failed'))),
         jsonb_build_array(pg_temp.ev_decision(0,'pass'))),
       'error:an unavailable failure analysis may carry no lesson and no decision')
    ) as t(report, expected)
  loop
    v_got := pg_temp.ev_report_error(v_run_one, v_token, v_case.report);
    if v_got <> v_case.expected then
      raise exception 'a forged unavailable report was not refused as expected: got % wanted %',
        v_got, v_case.expected;
    end if;
  end loop;

  v_report := pg_temp.ev_report('fetch_failed','fetching_source',null,v_config,'[]'::jsonb,
    'unavailable','no_source','[]'::jsonb,'[]'::jsonb);
  if pg_temp.ev_report_error(v_run_one, v_token, v_report) <> 'accepted:ok' then
    raise exception 'the honest unavailable report was refused';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_one
     and r.result = jsonb_build_object('failure_report', v_report)
     and jsonb_typeof(r.result->'failure_report'->'source_sha256') = 'null'
     and r.result->'failure_report'->>'learning_status' = 'unavailable';
  if n <> 1 then
    raise exception 'the unavailable report was not stored as the only result of the attempt';
  end if;
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run_one;
  if n <> 0 then
    raise exception 'an attempt with no snapshot still recorded a lesson';
  end if;

  -- A terminal record ends normal publication: no stage, no finish, and no
  -- snapshot identity recorded after a report that says none was fetched.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run_one, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      jsonb_build_object('goal', v_goal,
        'acceptance_criteria', jsonb_build_array('published after the attempt failed'),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this attempt has recorded a terminal failure record and may not '
                            'publish another stage' then
    raise exception 'a stage was published after a failure report (%)',
      coalesce(v_message, 'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_evolve_run(
    v_run_one, v_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), 'sha256:' || v_source, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok
     or v_message <> 'source identity cannot be recorded after a terminal failure record' then
    raise exception 'a snapshot was pinned after a report that claimed none (%)',
      coalesce(v_message, 'no error');
  end if;
  select * into v_finish from public.finish_evolve_run(v_run_one, v_token) t;
  if v_finish.accepted or v_finish.reason <> 'failure_report_recorded' then
    raise exception 'a finish after an unavailable report was not refused as such (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;

  -- An infrastructure failure keeps the attempt budget, so this request is
  -- retried rather than failed - and the report of the attempt that ended
  -- stays on it.
  select * into v_fail from public.fail_evolve_run(v_run_one, v_token, 'fetch_failed') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'queued' or not v_fail.retry_scheduled then
    raise exception 'an infrastructure failure after a report did not keep the retry budget (%)',
      coalesce(v_fail.work_item_status, 'no status');
  end if;

  -- Attempt two: the model answers, its lessons are reviewed, and the review
  -- rejects one of them. The attempt still failed, so the lesson is a
  -- diagnostic row and the decision is retained in the report.
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item or v_claim.attempt <> 2 then
    raise exception 'the retried request was not handed out as attempt two';
  end if;
  v_run_two := v_claim.run_id;
  v_token := v_claim.lease_token;
  select * into v_beat from public.heartbeat_evolve_run(
    v_run_two, v_token, 'fetching_source', 'github.com/octocat/Hello-World',
    repeat('f',40), 'sha256:' || v_source, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the second attempt heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  perform 1 from public.record_evolve_stage(v_run_two, v_token, 'requirements',
    pg_temp.ev_payload(v_source, v_config, repeat('1',64),
      jsonb_build_object('goal', v_goal,
        'acceptance_criteria', jsonb_build_array('the protected behaviour is preserved'),
        'constraints', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  perform 1 from public.record_evolve_stage(v_run_two, v_token, 'plan',
    pg_temp.ev_payload(v_source, v_config, repeat('2',64),
      jsonb_build_object('steps', jsonb_build_array('bound the change to one module'),
        'allowed_paths', jsonb_build_array('engine/oryveta_engine'),
        'risks', jsonb_build_array()),
      jsonb_build_array('stage:requirements'))) t;
  v_report := pg_temp.ev_report('runner_crashed','implementation',v_source,v_config,
    '[]'::jsonb,'reviewed','completed',
    jsonb_build_array(pg_temp.ev_lesson('the planned module needs a fixture before a change',
      jsonb_build_array('stage:plan','failure:runner_crashed'))),
    jsonb_build_array(pg_temp.ev_decision(0,'reject')));
  if pg_temp.ev_report_error(v_run_two, v_token, v_report) <> 'accepted:ok' then
    raise exception 'the reviewed failure report of the second attempt was refused';
  end if;
  -- The stage this attempt was about to publish is exactly what it may no
  -- longer publish, even though its chain is otherwise admissible.
  ok := false; v_message := null;
  begin perform 1 from public.record_evolve_stage(v_run_two, v_token, 'implementation',
    pg_temp.ev_payload(v_source, v_config, v_candidate,
      jsonb_build_object('candidate_sha256', v_candidate, 'patch_sha256', v_patch,
        'changed_paths', jsonb_build_array('engine/oryveta_engine/patches.py'),
        'summary', 'a candidate published after the attempt was declared failed'),
      jsonb_build_array('stage:plan'))) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'this attempt has recorded a terminal failure record and may not '
                            'publish another stage' then
    raise exception 'an admissible stage was still published after a failure report (%)',
      coalesce(v_message, 'no error');
  end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run_two and l.origin = 'failure_report' and l.status = 'rejected'
     and l.lesson_index = 0;
  if n <> 1 then
    raise exception 'the reviewed failure lesson was not recorded as a rejected diagnostic row';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_fail from public.fail_evolve_run(v_run_two, v_token, 'runner_crashed') t;
  if not v_fail.accepted or v_fail.work_item_status <> 'failed' then
    raise exception 'the exhausted request was not failed after its last attempt (%)',
      coalesce(v_fail.work_item_status, 'no status');
  end if;

  -- A different request now succeeds and is approved. Its approval activates
  -- the lessons its own learning review passed and nothing else: the diagnostic
  -- lesson of the failed request stays rejected and unreadable to the worker.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item_two from public.submit_evolve_work(
    v_p_one, 'A request that succeeds while another one failed.', null) t;
  v_run_three := pg_temp.ev_chain(v_p_one, v_worker_a, 'sha256:' || v_source, v_config,
                                  v_candidate, v_patch);
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select * into v_decide from public.decide_evolve_work(
    v_item_two, v_run_three, v_candidate, true) t;
  if not v_decide.approved or v_decide.status <> 'succeeded'
     or v_decide.lessons_activated <> 1 then
    raise exception 'the approval did not activate exactly the one lesson its review passed (%)',
      coalesce(v_decide.lessons_activated::text, 'none');
  end if;
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run_two and l.origin = 'failure_report' and l.status = 'rejected';
  if n <> 1 then
    raise exception 'approving another request changed a failed attempt''s diagnostic lesson';
  end if;
  select count(*) into n from public.evolve_lessons l
   where l.project_id = v_p_one and l.status = 'approved' and l.origin <> 'learning';
  if n <> 0 then
    raise exception 'a lesson that no learning review approved became production memory';
  end if;
  -- What the worker may retrieve as memory is the lesson this approval
  -- activated, and nothing at all from either failed attempt.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select count(*) into n from public.evolve_lessons l
   where l.run_id = v_run_three and l.status = 'approved' and l.origin = 'learning'
     and l.lesson_index = 0;
  if n <> 1 then
    raise exception 'the approved lesson of the succeeding request is not retrievable';
  end if;
  select count(*) into n from public.evolve_lessons l
   where l.run_id in (v_run_one, v_run_two, v_run_three);
  if n <> 1 then
    raise exception 'a worker identity retrieves a lesson no human activated (%)', n;
  end if;
end
$unavailable_learning$;

-- ---------------------------------------------------------------------------
-- 16. When no worker can analyse anything, the server records that and only
--     that. An expiry, a cancellation and a revocation leave a learning
--     unavailable record with no reviewer, no lesson and no decision in it;
--     they never overwrite a report a worker really produced; and they never
--     claim unavailability for an attempt whose learning review is on record.
-- ---------------------------------------------------------------------------
do $interrupted_setup$
declare
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_source text := repeat('7', 64);
  v_item uuid;
  v_claim record;
  v_beat record;
begin
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'An attempt whose process disappears mid-flight.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the interrupted attempt fixture was not the item handed out';
  end if;
  select * into v_beat from public.heartbeat_evolve_run(
    v_claim.run_id, v_claim.lease_token, 'requirements', 'github.com/octocat/Hello-World',
    repeat('f',40), 'sha256:' || v_source, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the interrupted attempt fixture heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  perform set_config('oryveta.ev_item_gone', v_item::text, true);
  perform set_config('oryveta.ev_run_gone', v_claim.run_id::text, true);
end
$interrupted_setup$;

reset role;
do $interrupted_stage$
declare
  v_run uuid := current_setting('oryveta.ev_run_gone')::uuid;
  n integer;
begin
  update public.factory_runs r
     set lease_expires_at = clock_timestamp() - interval '1 second'
   where r.id = v_run and r.status = 'running';
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the interrupted attempt fixture did not match exactly one attempt';
  end if;
end
$interrupted_stage$;

set local role authenticated;
do $server_built_records$
declare
  v_owner uuid := '6a111111-1111-4111-8111-111111111111';
  v_engineer uuid := '6b222222-2222-4222-8222-222222222222';
  v_worker_a uuid := '6e555555-5555-4555-8555-555555555555';
  v_p_one uuid := current_setting('oryveta.ev_p_one')::uuid;
  v_item_gone uuid := current_setting('oryveta.ev_item_gone')::uuid;
  v_run_gone uuid := current_setting('oryveta.ev_run_gone')::uuid;
  v_source text := repeat('7', 64);
  v_config text := repeat('9', 64);
  v_unavailable jsonb := jsonb_build_object('learning_unavailable',
    jsonb_build_object('learning_status','unavailable','learning_reason','worker_interrupted'));
  v_item uuid;
  v_run uuid;
  v_token uuid;
  v_report jsonb;
  v_claim record;
  v_beat record;
  n integer;
begin
  -- (a) An expiry. The reclaim closes the attempt and records that no analysis
  -- of it exists, without naming a model, a lesson or a decision.
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item_gone or v_claim.attempt <> 2 then
    raise exception 'the interrupted attempt was not reclaimed as attempt two';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_gone and r.status = 'failed' and r.error_code = 'lease_expired'
     and r.result = v_unavailable;
  if n <> 1 then
    raise exception 'an expired attempt did not record an honest learning unavailable result';
  end if;
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run_gone;
  if n <> 0 then
    raise exception 'an expired attempt recorded a lesson nobody extracted';
  end if;

  -- (b) A cancellation of the attempt the reclaim handed out. Cancelling stops
  -- the work; it does not commission more inference, and what it leaves behind
  -- says exactly that.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  perform 1 from public.cancel_work_item(v_item_gone) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_claim.run_id and r.status = 'cancelled' and r.result = v_unavailable;
  if n <> 1 then
    raise exception 'a cancelled attempt did not record an honest learning unavailable result';
  end if;

  -- (c) A report a worker really produced is never overwritten by the server,
  -- and a cancelled attempt cannot be reauthorized by reporting afterwards.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'An attempt that reports before it is cancelled.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the reported-then-cancelled fixture was not the item handed out';
  end if;
  v_run := v_claim.run_id;
  v_token := v_claim.lease_token;
  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_token, 'requirements', 'github.com/octocat/Hello-World',
    repeat('f',40), 'sha256:' || v_source, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the reported-then-cancelled fixture heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  v_report := pg_temp.ev_report('model_unreachable','requirements',v_source,v_config,
    '[]'::jsonb,'unavailable','model_unavailable','[]'::jsonb,'[]'::jsonb);
  if pg_temp.ev_report_error(v_run, v_token, v_report) <> 'accepted:ok' then
    raise exception 'the unavailable report of a reachable worker was refused';
  end if;
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  perform 1 from public.cancel_work_item(v_item) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'cancelled'
     and r.result = jsonb_build_object('failure_report', v_report);
  if n <> 1 then
    raise exception 'a cancellation overwrote the failure report the worker produced';
  end if;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  if pg_temp.ev_report_error(v_run, v_token,
       pg_temp.ev_report('model_unreachable','plan',v_source,v_config,'[]'::jsonb,
         'unavailable','budget_exhausted','[]'::jsonb,'[]'::jsonb))
     <> 'refused:cancelled' then
    raise exception 'a cancelled attempt accepted a report after its cancellation';
  end if;

  -- (d) A revocation. The identity that was running the attempt can analyse
  -- nothing, and the record says the authority was lost rather than inventing
  -- an interruption.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  select t.id into v_item from public.submit_evolve_work(
    v_p_one, 'An attempt whose worker identity is revoked while it runs.', null) t;
  perform set_config('request.jwt.claim.sub', v_worker_a::text, true);
  select * into v_claim from public.claim_evolve_work(v_p_one, 300) t;
  if v_claim.work_item_id <> v_item then
    raise exception 'the revoked-while-running fixture was not the item handed out';
  end if;
  v_run := v_claim.run_id;
  select * into v_beat from public.heartbeat_evolve_run(
    v_run, v_claim.lease_token, 'requirements', 'github.com/octocat/Hello-World',
    repeat('f',40), 'sha256:' || v_source, 300) t;
  if not v_beat.lease_valid then
    raise exception 'the revoked-while-running fixture heartbeat was refused (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  perform 1 from public.revoke_project_worker(v_p_one, v_worker_a) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'cancelled' and r.error_code = 'worker_revoked'
     and r.result = jsonb_build_object('learning_unavailable',
          jsonb_build_object('learning_status','unavailable',
                             'learning_reason','authority_lost'));
  if n <> 1 then
    raise exception 'a revoked attempt did not record that its authority was lost';
  end if;
  select count(*) into n from public.evolve_lessons l where l.run_id = v_run;
  if n <> 0 then
    raise exception 'a revoked attempt recorded a lesson nobody extracted';
  end if;
  -- The queue is left with one requeued request and no enabled worker, the
  -- state an operator sees after revoking a worker mid-flight.
  perform set_config('request.jwt.claim.sub', v_engineer::text, true);
  perform 1 from public.cancel_work_item(v_item) t;
end
$server_built_records$;

reset role;
rollback;
