-- Real authorization and durability regression for the durable factory
-- runtime: work items, fenced runs, typed events and project-scoped worker
-- identities.
--
-- Run order (psql, ON_ERROR_STOP=1, on a superuser/owner connection to a
-- Supabase stack whose auth schema and anon/authenticated roles already exist
-- - the local `supabase start` stack or a dedicated development project):
--   1. supabase/schema.sql
--   2. supabase/migrations/private_chats_and_explicit_sharing.sql
--   3. supabase/migrations/projects_and_project_membership.sql
--   4. supabase/migrations/durable_factory_runtime.sql
--   5. this file
--
-- Requires SQL-editor/owner privileges and intentionally creates synthetic
-- auth.users. Everything here ROLLS BACK, even on success, so no fixture row
-- survives the run. Never run it on an unrelated project. It exercises the real
-- grants, policies and RPCs as the anon and authenticated roles and mocks
-- nothing. Real OAuth-account browser tests and a live worker process remain
-- separate gates.
--
-- Three kinds of fact cannot be produced from inside one transaction, so each
-- is staged explicitly by switching back to the table owner role, and only the
-- staging is synthetic - every transition the runtime then performs is the real
-- one:
--   * now() is the transaction timestamp and never advances here, so a lease can
--     only be made stale by moving public.factory_runs.lease_expires_at into the
--     past. That stands in for elapsed wall-clock time.
--   * Designating or withdrawing a worker service identity is an Auth admin API
--     operation on auth.users.raw_app_meta_data. The fixtures and the withdrawal
--     test write that column directly, exactly as the admin API would.
--     public.workspace_memberships is provisioned and withdrawn the same way,
--     because no client role holds a write privilege on it.
--   * One connection cannot hold two concurrent attempts of one work item, so
--     the single column that makes an attempt's recorded source identity
--     disagree with the work item pin is staged directly. The parallel race
--     coverage for that state lives in the multi-connection driver (DR-004).
-- The table owner also states the facts no client role may read at all: that a
-- fenced attempt's row in private.factory_run_leases is gone, and that the pin
-- is both-or-neither.
-- Fixture identifiers cross those role switches in transaction-local settings,
-- because one DO block cannot share variables with the next.
begin;

-- ---------------------------------------------------------------------------
-- Fixtures: six ordinary accounts and four accounts that stand in for Auth
-- service identities. Addresses are confirmed because project invitation
-- acceptance requires private.verified_email(). Four accounts carry the
-- factory_worker designation, but only the two with no membership of any kind
-- are registrable as workers.
-- ---------------------------------------------------------------------------
insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,
   raw_app_meta_data,created_at,updated_at)
values
-- project owner / admin
('2a111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-owner@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- project engineer: may submit and cancel
('2b222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-engineer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- read-only project member
('2c333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-viewer@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- unrelated account with no grant anywhere
('2d444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-nonmember@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- designated worker service identity A, registered for project one
('2e555555-5555-4555-8555-555555555555','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-worker-a@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- designated worker service identity B, registered for project two
('2f666666-6666-4666-8666-666666666666','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-worker-b@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- designated, but a member of project one's workspace: never registrable
('3a777777-7777-4777-8777-777777777777','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-worker-c@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- designated, but a member of project one itself: never registrable
('3b888888-8888-4888-8888-888888888888','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-worker-d@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now()),
-- undesignated outsider: a project admin must not be able to promote it
('3c999999-9999-4999-8999-999999999999','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-outsider@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- ordinary account whose only authority over a project is its membership of
-- that project's workspace, so the creator reauthorization checks can exercise
-- both precedence paths of private.user_project_role (DR-001)
('3d000000-0000-4000-8000-000000000000','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-runtime-ws-engineer@example.invalid','',now(),'{}'::jsonb,now(),now());

-- ---------------------------------------------------------------------------
-- Structural facts that only the owner role can state authoritatively: the
-- fencing token exists exactly once, in the unexposed schema, and every
-- user-facing table is under row level security.
-- ---------------------------------------------------------------------------
do $structure$
declare
  n integer;
begin
  select count(*) into n from information_schema.columns c
   where c.table_schema = 'public' and c.column_name = 'lease_token';
  if n <> 0 then raise exception 'a table in schema public exposes a lease_token column'; end if;

  select count(*) into n from information_schema.columns c
   where c.table_schema = 'private' and c.table_name = 'factory_run_leases'
     and c.column_name = 'lease_token';
  if n <> 1 then
    raise exception 'the fencing token does not live in private.factory_run_leases';
  end if;

  select count(*) into n from pg_catalog.pg_class c
    join pg_catalog.pg_namespace ns on ns.oid = c.relnamespace
   where ns.nspname = 'public' and c.relrowsecurity
     and c.relname in ('work_items','factory_runs','factory_run_events','project_workers');
  if n <> 4 then
    raise exception 'row level security is not enabled on all four runtime tables';
  end if;

  select count(*) into n from pg_catalog.pg_class c
    join pg_catalog.pg_namespace ns on ns.oid = c.relnamespace
   where ns.nspname = 'private' and c.relname = 'factory_run_leases' and c.relrowsecurity;
  if n <> 1 then
    raise exception 'private.factory_run_leases is not under row level security';
  end if;
end
$structure$;

-- ---------------------------------------------------------------------------
-- 1. Anonymous callers. No ids are needed: every denial must happen before any
--    row, project or argument is considered.
-- ---------------------------------------------------------------------------
set local role anon;
do $anon$
declare
  n integer;
  ok boolean;
begin
  ok := false;
  begin select count(*) into n from public.work_items;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.work_items'; end if;

  ok := false;
  begin select count(*) into n from public.factory_runs;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.factory_runs'; end if;

  ok := false;
  begin select count(*) into n from public.factory_run_events;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.factory_run_events'; end if;

  ok := false;
  begin select count(*) into n from public.project_workers;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.project_workers'; end if;

  ok := false;
  begin select count(*) into n from private.factory_run_leases;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read private.factory_run_leases'; end if;

  ok := false;
  begin perform 1 from public.submit_repository_analysis(gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute submit_repository_analysis'; end if;

  ok := false;
  begin perform 1 from public.cancel_work_item(gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute cancel_work_item'; end if;

  ok := false;
  begin perform 1 from public.register_project_worker(
    gen_random_uuid(), gen_random_uuid(), 'Anon worker') t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute register_project_worker'; end if;

  ok := false;
  begin perform 1 from public.revoke_project_worker(gen_random_uuid(), gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute revoke_project_worker'; end if;

  ok := false;
  begin perform 1 from public.claim_analysis_work(gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute claim_analysis_work'; end if;

  ok := false;
  begin perform 1 from public.heartbeat_analysis_run(gen_random_uuid(), gen_random_uuid()) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute heartbeat_analysis_run'; end if;

  ok := false;
  begin perform 1 from public.finish_analysis_run(
    gen_random_uuid(), gen_random_uuid(), '{"summary":{}}'::jsonb) t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute finish_analysis_run'; end if;

  ok := false;
  begin perform 1 from public.fail_analysis_run(
    gen_random_uuid(), gen_random_uuid(), 'anon_probe') t;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute fail_analysis_run'; end if;
end
$anon$;

-- ---------------------------------------------------------------------------
-- 2-5. Authenticated actors. The acting principal is switched with the same
--      JWT claim Supabase uses, so auth.uid() drives every policy and every
--      server-side authority re-check under test.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $admission$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  engineer_id uuid := '2b222222-2222-4222-8222-222222222222';
  viewer_id uuid := '2c333333-3333-4333-8333-333333333333';
  nonmember_id uuid := '2d444444-4444-4444-8444-444444444444';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  worker_d uuid := '3b888888-8888-4888-8888-888888888888';
  email_engineer text := 'oryveta-runtime-engineer@example.invalid';
  email_viewer text := 'oryveta-runtime-viewer@example.invalid';
  email_worker_d text := 'oryveta-runtime-worker-d@example.invalid';
  url_one text := 'https://github.com/octocat/Hello-World';
  url_two text := 'https://github.com/octocat/Spoon-Knife';
  key_one text := 'oryveta-runtime-key-0001';
  ws_one uuid; ws_two uuid;
  p_one uuid; p_two uuid; p_three uuid;
  inv uuid;
  item_one uuid; item_project_two uuid; item_keyed uuid;
  v_actor uuid; v_relation text; v_candidate text;
  v_id uuid; v_status text; v_replayed boolean; v_kind text; v_url text;
  v_digest text; v_other_digest text; v_attempts integer; v_max integer;
  v_message text;
  n integer; ok boolean;
begin
  -- -- tenants, projects and membership ---------------------------------------
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  insert into public.workspaces(name,slug,created_by)
  values ('Oryveta Runtime One','runtime-test-one',owner_id) returning id into ws_one;
  insert into public.workspaces(name,slug,created_by)
  values ('Oryveta Runtime Two','runtime-test-two',owner_id) returning id into ws_two;

  select t.id into p_one from public.create_project(
    ws_one,'Runtime alpha','Durable analysis of a public repository','evolve',url_one) t;
  select t.id into p_two from public.create_project(
    ws_two,'Runtime beta','Second tenant durable analysis','evolve',url_two) t;
  -- A project with no source yet, used for the admission and idempotency
  -- checks. No worker is ever registered for it, so its queued row cannot
  -- disturb the claim ordering of project one.
  select t.id into p_three from public.create_project(
    ws_one,'Runtime source admission','Source URL admission checks','new') t;
  if p_one is null or p_two is null or p_three is null then
    raise exception 'project fixtures were not created';
  end if;

  select t.id into inv from public.invite_project_member(p_one,email_engineer,'engineer') t;
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.project_id into v_id from public.accept_project_invitation(inv) t;
  if v_id <> p_one then raise exception 'the engineer fixture did not join project one'; end if;

  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.id into inv from public.invite_project_member(p_one,email_viewer,'viewer') t;
  perform set_config('request.jwt.claim.sub', viewer_id::text, true);
  select t.project_id into v_id from public.accept_project_invitation(inv) t;
  if v_id <> p_one then raise exception 'the viewer fixture did not join project one'; end if;

  -- A designated account that is also a project member, so the registration
  -- refusal below is the membership rule and not the designation rule.
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.id into inv from public.invite_project_member(p_one,email_worker_d,'viewer') t;
  perform set_config('request.jwt.claim.sub', worker_d::text, true);
  select t.project_id into v_id from public.accept_project_invitation(inv) t;
  if v_id <> p_one then raise exception 'the member-worker fixture did not join project one'; end if;

  -- -- 2. no browser session holds a write privilege --------------------------
  -- Mutation goes exclusively through the RPCs, so a forgotten policy fails
  -- closed instead of exposing a write. Owner, read-only member and worker
  -- identity are all checked: the privilege is held by the role, not the row.
  foreach v_actor in array array[owner_id, viewer_id, worker_a] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    foreach v_relation in array array['public.work_items','public.factory_runs',
                                      'public.factory_run_events','public.project_workers'] loop
      ok := false; v_message := null;
      begin execute format('insert into %s default values', v_relation);
      exception when insufficient_privilege then ok := true;
                when others then v_message := sqlerrm; end;
      if not ok then
        raise exception 'INSERT on % is not refused for % (%)',
          v_relation, v_actor, coalesce(v_message,'no error');
      end if;

      ok := false;
      begin execute format('update %s set project_id = project_id where false', v_relation);
      exception when insufficient_privilege then ok := true; end;
      if not ok then raise exception 'UPDATE on % is not refused for %', v_relation, v_actor; end if;

      ok := false;
      begin execute format('delete from %s where false', v_relation);
      exception when insufficient_privilege then ok := true; end;
      if not ok then raise exception 'DELETE on % is not refused for %', v_relation, v_actor; end if;
    end loop;

    -- The same denial stated as the four writes a caller would actually want.
    ok := false;
    begin update public.factory_runs r set status = 'succeeded', result = '{"summary":{}}'::jsonb
     where r.id = gen_random_uuid();
    exception when insufficient_privilege then ok := true; end;
    if not ok then raise exception 'a run status and result are directly writable by %', v_actor; end if;

    ok := false; v_message := null;
    begin insert into public.factory_run_events(run_id,work_item_id,project_id,kind)
          values (gen_random_uuid(), gen_random_uuid(), p_one, 'succeeded');
    exception when insufficient_privilege then ok := true;
              when others then v_message := sqlerrm; end;
    if not ok then
      raise exception 'the event log accepts a client row from % (%)',
        v_actor, coalesce(v_message,'no error');
    end if;

    ok := false;
    begin update public.project_workers w set enabled = true where w.project_id = p_one;
    exception when insufficient_privilege then ok := true; end;
    if not ok then raise exception 'a worker registration flag is directly writable by %', v_actor; end if;

    -- -- 3. no lease token is reachable ---------------------------------------
    ok := false;
    begin select count(*) into n from private.factory_run_leases;
    exception when insufficient_privilege then ok := true; end;
    if not ok then raise exception 'private.factory_run_leases is readable by %', v_actor; end if;

    select count(*) into n from information_schema.columns c
     where c.table_schema = 'public' and c.column_name = 'lease_token';
    if n <> 0 then raise exception 'a lease_token column is reachable in public by %', v_actor; end if;
  end loop;

  -- -- 4. submission authority ------------------------------------------------
  perform set_config('request.jwt.claim.sub', viewer_id::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.submit_repository_analysis(p_one) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'not allowed to submit work for this project' then
    raise exception 'a read-only member could submit analysis work (%)',
      coalesce(v_message,'no error');
  end if;

  perform set_config('request.jwt.claim.sub', nonmember_id::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.submit_repository_analysis(p_one) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'not allowed to submit work for this project' then
    raise exception 'a non-member could submit analysis work (%)', coalesce(v_message,'no error');
  end if;

  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id, t.status, t.replayed, t.kind, t.source_url, t.input_digest,
         t.attempts, t.max_attempts
    into item_one, v_status, v_replayed, v_kind, v_url, v_digest, v_attempts, v_max
    from public.submit_repository_analysis(p_one) t;
  if item_one is null or v_status <> 'queued' or v_replayed
     or v_kind <> 'repository_analysis' or v_url <> url_one
     or v_attempts <> 0 or v_max <> 2 then
    raise exception 'the engineer submission did not return the documented queued row';
  end if;
  -- The digest is recomputed here from the task kind and the exact frozen URL,
  -- so a change in how input identity is derived cannot pass unnoticed.
  if v_digest is distinct from
     encode(sha256(convert_to('repository_analysis' || E'\n' || url_one, 'UTF8')), 'hex') then
    raise exception 'the submission did not freeze the canonical input digest';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_one and w.project_id = p_one and w.created_by = engineer_id
     and w.kind = 'repository_analysis' and w.status = 'queued'
     and w.source_url = url_one and w.source_owner = 'octocat'
     and w.source_repo = 'Hello-World' and w.input_digest = v_digest
     and w.attempts = 0 and w.max_attempts = 2 and w.error_code is null
     and w.idempotency_key is null and w.cancel_requested_at is null;
  if n <> 1 then
    raise exception 'the work item did not freeze the authorized source identity';
  end if;

  -- The project owner may submit too, in their own second tenant.
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.work_item_id, t.status, t.replayed
    into item_project_two, v_status, v_replayed
    from public.submit_repository_analysis(p_two) t;
  if item_project_two is null or v_status <> 'queued' or v_replayed then
    raise exception 'the project owner could not submit analysis work';
  end if;

  -- A project with no source, or a source that is not a public GitHub
  -- owner/repo URL, is refused at admission instead of reaching a worker.
  ok := false; v_message := null;
  begin perform 1 from public.submit_repository_analysis(p_three) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'project has no source repository to analyse' then
    raise exception 'a project without a source was accepted (%)', coalesce(v_message,'no error');
  end if;

  foreach v_candidate in array array['https://example.invalid/repo.git',
                                     'https://github.com/octocat/Hello-World?ref=main',
                                     'https://user:secret@github.com/octocat/Hello-World',
                                     'https://github.com/octocat'] loop
    perform 1 from public.update_project(
      p_three,'Runtime source admission','Source URL admission checks',v_candidate) t;
    ok := false; v_message := null;
    begin perform 1 from public.submit_repository_analysis(p_three) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or
       v_message <> 'only public https://github.com/owner/repo sources can be analysed' then
      raise exception 'source % was accepted for analysis (%)',
        v_candidate, coalesce(v_message,'no error');
    end if;
  end loop;

  -- -- 5. idempotency --------------------------------------------------------
  perform 1 from public.update_project(
    p_three,'Runtime source admission','Source URL admission checks',url_one) t;
  select t.work_item_id, t.replayed, t.input_digest into item_keyed, v_replayed, v_digest
    from public.submit_repository_analysis(p_three, key_one) t;
  if item_keyed is null or v_replayed then
    raise exception 'the first keyed submission was reported as a replay';
  end if;
  select t.work_item_id, t.replayed, t.status, t.input_digest
    into v_id, v_replayed, v_status, v_other_digest
    from public.submit_repository_analysis(p_three, key_one) t;
  if v_id <> item_keyed or not v_replayed or v_status <> 'queued'
     or v_other_digest <> v_digest then
    raise exception 'a repeated idempotency key did not replay the same work item';
  end if;
  select count(*) into n from public.work_items w
   where w.project_id = p_three and w.idempotency_key = key_one;
  if n <> 1 then raise exception 'a repeated idempotency key created a second work item'; end if;

  -- The frozen input decides a replay, not the project's current source: once
  -- the source moves, the same key describes a different request and is refused.
  perform 1 from public.update_project(
    p_three,'Runtime source admission','Source URL admission checks',url_two) t;
  ok := false; v_message := null;
  begin perform 1 from public.submit_repository_analysis(p_three, key_one) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'idempotency key already used for a different input' then
    raise exception 'a reused key silently replayed a different input (%)',
      coalesce(v_message,'no error');
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_keyed and w.source_url = url_one;
  if n <> 1 then raise exception 'an accepted work item lost its frozen source URL'; end if;

  foreach v_candidate in array array['short','has space here',
                                     'semicolon;and-more-characters'] loop
    ok := false; v_message := null;
    begin perform 1 from public.submit_repository_analysis(p_three, v_candidate) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or
       v_message <> 'idempotency key must be 8-120 characters of A-Z a-z 0-9 . _ : -' then
      raise exception 'idempotency key % was accepted (%)',
        v_candidate, coalesce(v_message,'no error');
    end if;
  end loop;

  perform set_config('oryveta_test.workspace_one', ws_one::text, true);
  perform set_config('oryveta_test.project_one', p_one::text, true);
  perform set_config('oryveta_test.project_two', p_two::text, true);
  perform set_config('oryveta_test.project_three', p_three::text, true);
  perform set_config('oryveta_test.item_one', item_one::text, true);
  perform set_config('oryveta_test.item_project_two', item_project_two::text, true);
end
$admission$;

-- ---------------------------------------------------------------------------
-- Grants and function hardening fail closed. Catalog facts, so any
-- authenticated session can state them.
-- ---------------------------------------------------------------------------
do $privileges$
declare
  n integer;
begin
  select count(*) into n from (values
    ('public.work_items'),('public.factory_runs'),
    ('public.factory_run_events'),('public.project_workers')) as t(rel)
   where not has_table_privilege('authenticated',t.rel,'select')
      or has_table_privilege('authenticated',t.rel,'insert')
      or has_table_privilege('authenticated',t.rel,'update')
      or has_table_privilege('authenticated',t.rel,'delete')
      or has_table_privilege('anon',t.rel,'select')
      or has_table_privilege('anon',t.rel,'insert')
      or has_table_privilege('anon',t.rel,'update')
      or has_table_privilege('anon',t.rel,'delete');
  if n <> 0 then
    raise exception 'the runtime tables do not hold exactly SELECT for authenticated and nothing for anon';
  end if;

  select count(*) into n from (values ('select'),('insert'),('update'),('delete')) as t(priv)
   where has_table_privilege('authenticated','private.factory_run_leases',t.priv)
      or has_table_privilege('anon','private.factory_run_leases',t.priv);
  if n <> 0 then raise exception 'a client role holds a privilege on the lease table'; end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'public'
     and p.proname in ('submit_repository_analysis','cancel_work_item',
       'register_project_worker','revoke_project_worker','claim_analysis_work',
       'heartbeat_analysis_run','finish_analysis_run','fail_analysis_run');
  if n <> 8 then raise exception 'expected exactly eight durable runtime RPCs, found %', n; end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'public'
     and p.proname in ('submit_repository_analysis','cancel_work_item',
       'register_project_worker','revoke_project_worker','claim_analysis_work',
       'heartbeat_analysis_run','finish_analysis_run','fail_analysis_run')
     and (not p.prosecdef
       or p.proconfig is null
       -- An empty search_path is stored either bare or quoted, never as a
       -- schema list such as search_path=public.
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon',p.oid,'execute'));
  if n <> 0 then
    raise exception 'a runtime RPC is not a hardened definer or is anon-executable';
  end if;

  -- Validation, recording and reclaim internals are callable by nobody but the
  -- definer RPCs above.
  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'private'
     and p.proname in ('assert_safe_json_tree','assert_run_checkpoint',
       'assert_analysis_result','record_run_event','settle_work_item_after_attempt',
       'expire_stale_runs','fence_running_runs','fence_unauthorized_creator',
       'touch_work_item')
     and (p.proconfig is null
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon',p.oid,'execute')
       or has_function_privilege('authenticated',p.oid,'execute'));
  if n <> 0 then
    raise exception 'a private runtime helper is reachable or is not search_path hardened';
  end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'private'
     and p.proname in ('is_service_worker_identity','is_project_worker','github_repo_parts')
     and (p.proconfig is null
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon',p.oid,'execute'));
  if n <> 0 then
    raise exception 'a worker authorization helper is anon-executable or not hardened';
  end if;

  -- DR-001: the creator reauthorization helpers are internals of the definer
  -- RPCs above, so they are search_path hardened and unreachable from anon.
  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'private'
     and p.proname in ('user_project_role','creator_may_run')
     and (p.proconfig is null
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon',p.oid,'execute'));
  if n <> 0 then
    raise exception 'DR-001: a creator reauthorization helper is anon-executable or not hardened';
  end if;
end
$privileges$;

-- ---------------------------------------------------------------------------
-- Workspace participation for the designated account that must still be
-- refused as a worker. No client role can write public.workspace_memberships,
-- so the deployment provisions it out of band and so does this fixture.
-- ---------------------------------------------------------------------------
reset role;
do $workspace_member$
declare
  n integer;
begin
  insert into public.workspace_memberships(workspace_id,user_id,role)
  values (current_setting('oryveta_test.workspace_one')::uuid,
          '3a777777-7777-4777-8777-777777777777','engineer');
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the workspace member fixture was not provisioned'; end if;
end
$workspace_member$;

-- ---------------------------------------------------------------------------
-- 6-10. Worker registration, read scope, claim fencing, durable progress,
--       completion and payload validation.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $runtime$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  engineer_id uuid := '2b222222-2222-4222-8222-222222222222';
  viewer_id uuid := '2c333333-3333-4333-8333-333333333333';
  nonmember_id uuid := '2d444444-4444-4444-8444-444444444444';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  worker_b uuid := '2f666666-6666-4666-8666-666666666666';
  worker_c uuid := '3a777777-7777-4777-8777-777777777777';
  worker_d uuid := '3b888888-8888-4888-8888-888888888888';
  outsider_id uuid := '3c999999-9999-4999-8999-999999999999';
  p_one uuid := current_setting('oryveta_test.project_one')::uuid;
  p_two uuid := current_setting('oryveta_test.project_two')::uuid;
  item_one uuid := current_setting('oryveta_test.item_one')::uuid;
  item_project_two uuid := current_setting('oryveta_test.item_project_two')::uuid;
  url_one text := 'https://github.com/octocat/Hello-World';
  ref_one text := 'github.com/octocat/Hello-World';
  ref_two text := 'github.com/octocat/Spoon-Knife';
  commit_one text := left(encode(sha256(convert_to('oryveta-commit-one','UTF8')),'hex'),40);
  commit_two text := left(encode(sha256(convert_to('oryveta-commit-two','UTF8')),'hex'),40);
  digest_one text := 'sha256:' || encode(sha256(convert_to('oryveta-archive-one','UTF8')),'hex');
  digest_two text := 'sha256:' || encode(sha256(convert_to('oryveta-archive-two','UTF8')),'hex');
  checkpoint_two jsonb;
  checkpoint_three jsonb := '{"step":"analyzing","elapsed_seconds":3}'::jsonb;
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object(
      'source_files_analyzed', 42,
      'findings_persisted', 2,
      'findings_persisted_truncated', false,
      'languages', jsonb_build_object('.py', 7, '.ts', 3)),
    'findings', jsonb_build_array(
      jsonb_build_object('path','engine/oryveta_engine/analysis.py','line',12,
        'category','maintainability','severity','medium','title','Long function',
        'recommendation','Split the function','confidence','high'),
      jsonb_build_object('path','apps/web/src/app/page.tsx','line',3,
        'category','security','severity','high','title','Unvalidated input',
        'recommendation','Validate the payload','confidence','medium')));
  -- Long strings are built from md5 digests rather than a repeated character,
  -- so the size limits are reached by content that does not compress away.
  long_text text := (select string_agg(md5(g::text), '') from generate_series(1,20) g);
  huge_text text := (select string_agg(md5(g::text), '') from generate_series(1,20000) g);
  bad_checkpoints jsonb[] := array[
    '{"step":{"nested":"value"}}'::jsonb,
    '{"step":["value"]}'::jsonb,
    '{"Step":"value"}'::jsonb,
    '{"step":"/etc/passwd"}'::jsonb,
    '[]'::jsonb,
    (select jsonb_object_agg('k' || g, g) from generate_series(1,17) g),
    jsonb_build_object('step',
      (select string_agg(md5(g::text), '') from generate_series(1,1000) g))];
  bad_checkpoint_errors text[] := array[
    'checkpoint values must be scalars',
    'checkpoint values must be scalars',
    'checkpoint keys must be snake_case identifiers',
    'checkpoint strings must be short plain identifiers',
    'checkpoint must be a JSON object',
    'checkpoint may contain at most 16 keys',
    'checkpoint exceeds 4096 bytes'];
  bad_results jsonb[] := array[
    '{"summary":{},"extra":1}'::jsonb,
    '{"findings":[]}'::jsonb,
    '{"summary":{},"findings":{}}'::jsonb,
    (select jsonb_build_object('summary','{}'::jsonb,'findings',
       jsonb_agg(jsonb_build_object('path','engine/a.py'))) from generate_series(1,401) g),
    '{"summary":{},"findings":[{"path":"/etc/shadow"}]}'::jsonb,
    '{"summary":{},"findings":[{"path":"../../secret.env"}]}'::jsonb,
    '{"summary":{},"findings":[{"path":"engine/a.py","command":"rm -rf"}]}'::jsonb,
    '{"summary":{},"findings":["engine/a.py"]}'::jsonb,
    '{"summary":{},"findings":[{"path":"engine/a.py","category":["security"]}]}'::jsonb,
    '{"summary":{"note":"C:\\Users"}}'::jsonb,
    '{"summary":{"note":"engine\\analysis.py"}}'::jsonb,
    '{"summary":{"Bad Key":1}}'::jsonb,
    '{"summary":{"a":{"b":{"c":{"d":{"e":{"f":{"g":1}}}}}}}}'::jsonb,
    '[]'::jsonb,
    jsonb_build_object('summary','{}'::jsonb,'findings',
      jsonb_build_array(jsonb_build_object('path','engine/a.py','title',long_text))),
    jsonb_build_object('summary', jsonb_build_object('note', long_text)),
    jsonb_build_object('summary', jsonb_build_object('note', huge_text))];
  bad_result_errors text[] := array[
    'result may only contain summary and findings',
    'result requires a summary object',
    'result findings must be an array',
    'result may contain at most 400 findings',
    'finding paths must be repository-relative',
    'finding paths must be repository-relative',
    'unknown finding field',
    'each finding must be an object',
    'finding fields must be scalars',
    'persisted JSON string looks like a filesystem path',
    'persisted JSON string looks like a filesystem path',
    'persisted JSON key is not a bounded identifier',
    'persisted JSON nests more than 6 levels deep',
    'result must be a JSON object',
    'finding fields must be at most 500 characters',
    'persisted JSON string exceeds 500 characters',
    'result exceeds the 256 KB persisted limit'];
  registration_a uuid; registration_b uuid;
  run_one uuid; token_one uuid;
  run_other uuid; token_other uuid;
  item_retry uuid; run_retry uuid; token_retry uuid;
  v_claim record;
  v_actor uuid;
  v_id uuid; v_user uuid; v_label text; v_enabled boolean;
  v_valid boolean; v_reason text; v_run_status text; v_item_status text;
  v_cancel boolean; v_expires timestamptz; v_phase text;
  v_accepted boolean; v_retry boolean; v_attempt integer;
  v_message text; v_detail text;
  n integer; ok boolean;
begin
  -- -- 7. worker registration -------------------------------------------------
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.register_project_worker(p_one, owner_id, 'Owner laptop') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or
     v_message <> 'a worker must be a separate service identity, not your own account' then
    raise exception 'a project admin registered their own account as a worker (%)',
      coalesce(v_message,'no error');
  end if;

  -- Designation is an Auth admin API fact. Neither an unrelated account nor a
  -- colleague's human account can be promoted by this RPC.
  foreach v_actor in array array[outsider_id, engineer_id] loop
    ok := false; v_message := null;
    begin perform 1 from public.register_project_worker(p_one, v_actor, 'Borrowed account') t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or
       v_message <> 'that account is not a provisioned factory worker service identity' then
      raise exception 'undesignated account % was registered as a worker (%)',
        v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  -- A designated identity that participates in the project, or merely in its
  -- workspace, is still refused: worker authority never rides on membership.
  foreach v_actor in array array[worker_d, worker_c] loop
    ok := false; v_message := null;
    begin perform 1 from public.register_project_worker(p_one, v_actor, 'Member worker') t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or
       v_message <> 'a project or workspace member cannot also be a worker identity' then
      raise exception 'participant % was registered as a worker (%)',
        v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  ok := false; v_message := null;
  begin perform 1 from public.register_project_worker(p_one, gen_random_uuid(), 'Ghost worker') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker identity not found' then
    raise exception 'a non-existent account was registered as a worker (%)',
      coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.register_project_worker(p_one, worker_a, 'x') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or
     v_message <> 'worker label must be 2-60 characters of A-Z a-z 0-9 space . _ -' then
    raise exception 'an out-of-bounds worker label was accepted (%)',
      coalesce(v_message,'no error');
  end if;

  select t.id, t.project_id, t.worker_user_id, t.label, t.enabled
    into registration_a, v_id, v_user, v_label, v_enabled
    from public.register_project_worker(p_one, worker_a, 'Factory worker A') t;
  if registration_a is null or v_id <> p_one or v_user <> worker_a
     or v_label <> 'Factory worker A' or not v_enabled then
    raise exception 'registering the designated worker for project one failed';
  end if;
  select t.id, t.enabled into registration_b, v_enabled
    from public.register_project_worker(p_two, worker_b, 'Factory worker B') t;
  if registration_b is null or not v_enabled then
    raise exception 'registering the designated worker for project two failed';
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.revoke_project_worker(p_one, worker_b) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker registration not found' then
    raise exception 'revoking an unregistered identity was accepted (%)',
      coalesce(v_message,'no error');
  end if;

  -- Only a project admin grants or withdraws worker authority.
  foreach v_actor in array array[engineer_id, viewer_id] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    ok := false; v_message := null;
    begin perform 1 from public.register_project_worker(p_one, worker_b, 'Side channel') t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'not allowed to manage this project' then
      raise exception 'non-admin % registered a worker (%)', v_actor, coalesce(v_message,'no error');
    end if;
    ok := false; v_message := null;
    begin perform 1 from public.revoke_project_worker(p_one, worker_a) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'not allowed to manage this project' then
      raise exception 'non-admin % revoked a worker (%)', v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  -- Registrations are operational configuration: the granting admins and the
  -- worker identity itself, nobody else.
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select count(*) into n from public.project_workers w where w.project_id = p_one;
  if n <> 1 then raise exception 'the project admin cannot read the registration they granted'; end if;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select count(*) into n from public.project_workers w where w.id = registration_a;
  if n <> 1 then raise exception 'a worker cannot confirm its own registration'; end if;
  select count(*) into n from public.project_workers w where w.id = registration_b;
  if n <> 0 then raise exception 'a worker reads another project''s registration'; end if;
  foreach v_actor in array array[viewer_id, engineer_id, nonmember_id] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    select count(*) into n from public.project_workers w;
    if n <> 0 then raise exception 'worker registrations are visible to %', v_actor; end if;
  end loop;

  -- -- 8. claim scope and fencing --------------------------------------------
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.claim_analysis_work(p_one, 5) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'lease seconds must be between 15 and 900' then
    raise exception 'an out-of-bounds lease length was accepted (%)', coalesce(v_message,'no error');
  end if;

  n := 0;
  for v_claim in select * from public.claim_analysis_work(p_one, 300) loop
    n := n + 1;
    run_one := v_claim.run_id;
    token_one := v_claim.lease_token;
    -- DR-004: a fresh work item carries no pinned source identity yet, and the
    -- claim reports that work-item pin instead of the ref and commit whichever
    -- attempt ran last happened to resolve.
    if v_claim.work_item_id <> item_one or v_claim.attempt <> 1 or v_claim.max_attempts <> 2
       or v_claim.kind <> 'repository_analysis' or v_claim.source_url <> url_one
       or v_claim.source_owner <> 'octocat' or v_claim.source_repo <> 'Hello-World'
       or v_claim.input_digest is null or v_claim.lease_token is null
       or v_claim.lease_expires_at <= now()
       or v_claim.pinned_source_ref is not null
       or v_claim.pinned_source_commit is not null
       or v_claim.previous_source_digest is not null
       or v_claim.previous_checkpoint <> '{}'::jsonb then
      raise exception 'the first claim did not describe the frozen work item';
    end if;
  end loop;
  if n <> 1 then raise exception 'the first claim returned % rows instead of one', n; end if;

  select count(*) into n from public.claim_analysis_work(p_one, 300) t;
  if n <> 0 then raise exception 'a second immediate claim handed out running work'; end if;

  ok := false; v_message := null;
  begin perform 1 from public.claim_analysis_work(p_two, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker identity is not registered for this project' then
    raise exception 'a worker claimed outside its registered project (%)',
      coalesce(v_message,'no error');
  end if;

  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.work_item_id = item_one and r.project_id = p_one
     and r.attempt = 1 and r.worker_user_id = worker_a
     and r.worker_registration_id = registration_a
     and r.status = 'running' and r.phase = 'claimed' and r.checkpoint = '{}'::jsonb
     and r.result is null and r.error_code is null and r.finished_at is null
     and r.source_ref is null and r.source_commit is null and r.source_digest is null;
  if n <> 1 then
    raise exception 'the claimed run was not recorded as a running first attempt';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_one and w.status = 'running' and w.attempts = 1
     -- DR-004: claiming resolves no source, so the pin is still empty.
     and w.pinned_source_ref is null and w.pinned_source_commit is null;
  if n <> 1 then raise exception 'the claim did not move the work item to running attempt 1'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.work_item_id = item_one and e.project_id = p_one
     and e.kind = 'claimed' and e.phase = 'claimed' and e.detail = 'attempt 1 of 2';
  if n <> 1 then raise exception 'the claim event was not recorded with a derived detail'; end if;

  -- A designated, registered worker of the other project is still a stranger to
  -- this attempt, and a run it does not own is indistinguishable from a missing
  -- one, so run ids cannot be probed across workers or projects.
  perform set_config('request.jwt.claim.sub', worker_b::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(run_one, token_one, 'analyzing') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'a foreign worker could heartbeat another attempt (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.finish_analysis_run(run_one, token_one, result_payload) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'a foreign worker could finish another attempt (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.fail_analysis_run(run_one, token_one, 'stolen_attempt') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'run not found' then
    raise exception 'a foreign worker could fail another attempt (%)',
      coalesce(v_message,'no error');
  end if;

  -- The owning worker without the right fencing token is reported as fenced
  -- rather than raising, so a worker has an unambiguous signal to stop.
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.lease_valid, t.reason, t.run_status, t.work_item_status, t.cancel_requested,
         t.lease_expires_at, t.phase
    into v_valid, v_reason, v_run_status, v_item_status, v_cancel, v_expires, v_phase
    from public.heartbeat_analysis_run(run_one, gen_random_uuid(), 'analyzing') t;
  if v_valid or v_reason <> 'lease_lost' or v_run_status <> 'running'
     or v_item_status <> 'running' or v_cancel or v_expires is not null
     or v_phase <> 'claimed' then
    raise exception 'a wrong lease token was accepted as a live lease';
  end if;
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_one, null) t;
  if v_valid or v_reason <> 'lease_lost' then
    raise exception 'a missing lease token was accepted as a live lease';
  end if;
  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_one, gen_random_uuid(), result_payload) t;
  if v_accepted or v_reason <> 'lease_lost' or v_item_status <> 'running' then
    raise exception 'a fenced attempt published a result (%)', coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_one, gen_random_uuid(), 'fenced_attempt') t;
  if v_accepted or v_reason <> 'lease_lost' or v_item_status <> 'running' or v_retry then
    raise exception 'a fenced attempt recorded a failure (%)', coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.status = 'running' and r.phase = 'claimed' and r.result is null;
  if n <> 1 then raise exception 'a fenced call mutated the run it could not hold'; end if;

  -- -- 6. read scope ---------------------------------------------------------
  -- Current project readers see the durable record; the worker identity sees
  -- exactly its own project; nobody else sees anything.
  foreach v_actor in array array[owner_id, engineer_id, viewer_id, worker_a] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    select count(*) into n from public.work_items w where w.id = item_one;
    if n <> 1 then raise exception 'authorized reader % cannot see the work item', v_actor; end if;
    select count(*) into n from public.factory_runs r where r.id = run_one;
    if n <> 1 then raise exception 'authorized reader % cannot see the run', v_actor; end if;
    select count(*) into n from public.factory_run_events e where e.run_id = run_one;
    if n < 1 then raise exception 'authorized reader % cannot see the run events', v_actor; end if;
  end loop;

  perform set_config('request.jwt.claim.sub', nonmember_id::text, true);
  select count(*) into n from public.work_items w;
  if n <> 0 then raise exception 'a non-member reads work items'; end if;
  select count(*) into n from public.factory_runs r;
  if n <> 0 then raise exception 'a non-member reads runs'; end if;
  select count(*) into n from public.factory_run_events e;
  if n <> 0 then raise exception 'a non-member reads run events'; end if;

  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select count(*) into n from public.work_items w where w.project_id = p_two;
  if n <> 0 then raise exception 'a worker reads work items of another project'; end if;
  select count(*) into n from public.factory_runs r where r.project_id = p_two;
  if n <> 0 then raise exception 'a worker reads runs of another project'; end if;
  select count(*) into n from public.factory_run_events e where e.project_id = p_two;
  if n <> 0 then raise exception 'a worker reads run events of another project'; end if;
  perform set_config('request.jwt.claim.sub', worker_b::text, true);
  select count(*) into n from public.work_items w where w.project_id = p_one;
  if n <> 0 then raise exception 'the second worker reads the first project''s work items'; end if;

  -- -- 9. durable progress and completion ------------------------------------
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.lease_valid, t.reason, t.run_status, t.work_item_status, t.cancel_requested,
         t.lease_expires_at, t.phase
    into v_valid, v_reason, v_run_status, v_item_status, v_cancel, v_expires, v_phase
    from public.heartbeat_analysis_run(run_one, token_one, 'fetching_source',
                                       '{"step":"fetching_source"}'::jsonb) t;
  if not v_valid or v_reason <> 'ok' or v_run_status <> 'running'
     or v_item_status <> 'running' or v_cancel or v_expires <= now()
     or v_phase <> 'fetching_source' then
    raise exception 'the first heartbeat did not extend the lease and record the phase';
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'phase_changed' and e.phase = 'fetching_source'
     and e.detail = 'fetching_source';
  if n <> 1 then raise exception 'a phase change was not recorded as an event'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'checkpoint';
  if n <> 0 then raise exception 'a phase change also wrote a redundant checkpoint event'; end if;

  -- A result without the complete recorded snapshot identity is not
  -- attributable to any source bytes, so it is refused (DR-004: ref, commit
  -- and digest are all required, not the digest alone).
  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_one, token_one, result_payload) t;
  if v_accepted or v_reason <> 'source_identity_missing' or v_item_status <> 'running' then
    raise exception 'a result was accepted before any source identity was recorded (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.result is null and r.status = 'running';
  if n <> 1 then raise exception 'a refused completion still touched the run'; end if;

  checkpoint_two := jsonb_build_object(
    'step','snapshot_ready','archive_bytes',2048,'archive_entries',12,
    'resumed_attempt',false,'source_commit',commit_one);
  select t.lease_valid, t.reason, t.phase into v_valid, v_reason, v_phase
    from public.heartbeat_analysis_run(run_one, token_one, 'analyzing', checkpoint_two,
                                       ref_one, commit_one, digest_one) t;
  if not v_valid or v_reason <> 'ok' or v_phase <> 'analyzing' then
    raise exception 'the snapshot heartbeat was refused';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.phase = 'analyzing' and r.checkpoint = checkpoint_two
     and r.source_ref = ref_one and r.source_commit = commit_one
     and r.source_digest = digest_one;
  if n <> 1 then raise exception 'the resolved snapshot identity was not recorded'; end if;
  select e.detail into v_detail from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'source_resolved';
  if v_detail is distinct from
     (ref_one || ' commit=' || commit_one || ' ' || digest_one) then
    raise exception 'the source_resolved detail was not derived server side (%)',
      coalesce(v_detail,'no event');
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'phase_changed' and e.phase = 'analyzing';
  if n <> 1 then raise exception 'the analyzing phase change was not recorded once'; end if;

  -- DR-004: the first attempt that resolves both a reference and a commit pins
  -- them on the work item, so every later attempt analyses the same source.
  select count(*) into n from public.work_items w
   where w.id = item_one and w.pinned_source_ref = ref_one
     and w.pinned_source_commit = commit_one;
  if n <> 1 then
    raise exception 'DR-004: the first resolved attempt did not pin the work item source identity';
  end if;

  -- DR-004: the snapshot identity is recorded once per attempt. A heartbeat
  -- that reports a reference, commit or digest conflicting with what this
  -- attempt already recorded is refused instead of being coalesced away, so a
  -- moved upstream can never be mistaken for the bytes that were analysed.
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, 'analyzing', p_source_commit => commit_two) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source identity already recorded for this attempt' then
    raise exception 'DR-004: a conflicting source commit was accepted (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, 'analyzing', p_source_ref => ref_two) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source identity already recorded for this attempt' then
    raise exception 'DR-004: a conflicting source reference was accepted (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, 'analyzing', p_source_digest => digest_two) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source identity already recorded for this attempt' then
    raise exception 'DR-004: a conflicting source digest was accepted (%)',
      coalesce(v_message,'no error');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.source_ref = ref_one and r.source_commit = commit_one
     and r.source_digest = digest_one and r.checkpoint = checkpoint_two;
  if n <> 1 then
    raise exception 'a refused source identity heartbeat still touched the attempt';
  end if;

  -- Re-reporting exactly what is already recorded stays an ordinary heartbeat:
  -- the identity is idempotent, not single-shot.
  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_one, token_one, 'analyzing', null,
                                       ref_one, commit_one, digest_one) t;
  if not v_valid then
    raise exception 'repeating the recorded source identity was refused';
  end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'source_resolved';
  if n <> 1 then raise exception 'the source_resolved event was recorded more than once'; end if;

  -- A progress heartbeat carries no source arguments at all and records a
  -- checkpoint instead of a phase change.
  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_one, token_one, 'analyzing', checkpoint_three) t;
  if not v_valid then raise exception 'a progress heartbeat was refused'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.source_ref = ref_one and r.source_commit = commit_one
     and r.source_digest = digest_one and r.checkpoint = checkpoint_three;
  if n <> 1 then raise exception 'a later heartbeat rewrote the resolved snapshot identity'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'checkpoint' and e.phase = 'analyzing'
     and e.detail = 'analyzing';
  if n <> 1 then raise exception 'a checkpoint was not recorded as an event'; end if;

  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_one, token_one, result_payload) t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'succeeded' then
    raise exception 'a valid completion was refused (%)', coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_one and r.status = 'succeeded' and r.phase = 'done'
     and r.error_code is null and r.finished_at is not null
     and r.result is not distinct from result_payload;
  if n <> 1 then raise exception 'the completed run does not hold the stored result'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_one and w.status = 'succeeded' and w.error_code is null and w.attempts = 1;
  if n <> 1 then raise exception 'completion did not settle the work item'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_one and e.kind = 'succeeded' and e.phase = 'done'
     and e.detail = 'findings=2 files=42';
  if n <> 1 then raise exception 'the success event detail was not derived from the result'; end if;

  -- The finished attempt is closed: its own token buys nothing afterwards.
  select t.lease_valid, t.reason, t.run_status, t.work_item_status
    into v_valid, v_reason, v_run_status, v_item_status
    from public.heartbeat_analysis_run(run_one, token_one, 'analyzing') t;
  if v_valid or v_reason <> 'not_running' or v_run_status <> 'succeeded'
     or v_item_status <> 'succeeded' then
    raise exception 'a completed attempt still reported a live lease';
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.finish_analysis_run(run_one, token_one, result_payload) t;
  if v_accepted or v_reason <> 'not_running' then
    raise exception 'a completed attempt published a second result (%)',
      coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.fail_analysis_run(run_one, token_one, 'late_failure') t;
  if v_accepted or v_reason <> 'not_running' then
    raise exception 'a completed attempt recorded a late failure (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- -- 10. payload and argument validation -----------------------------------
  -- Validation happens before the run is even looked up, so a malformed
  -- payload can never be stored and shown to users.
  for i in 1..array_length(bad_checkpoints,1) loop
    ok := false; v_message := null;
    begin perform 1 from public.heartbeat_analysis_run(
      run_one, token_one, 'analyzing', bad_checkpoints[i]) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> bad_checkpoint_errors[i] then
      raise exception 'checkpoint payload % was not refused as documented (%)',
        i, coalesce(v_message,'no error');
    end if;
  end loop;

  for i in 1..array_length(bad_results,1) loop
    ok := false; v_message := null;
    begin perform 1 from public.finish_analysis_run(run_one, token_one, bad_results[i]) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> bad_result_errors[i] then
      raise exception 'result payload % was not refused as documented (%)',
        i, coalesce(v_message,'no error');
    end if;
  end loop;

  ok := false; v_message := null;
  begin perform 1 from public.finish_analysis_run(run_one, token_one, null) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'result is required' then
    raise exception 'a missing result was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, p_source_ref => 'https://github.com/octocat/Hello-World') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source reference must be github.com/owner/repo' then
    raise exception 'a URL was accepted as a source reference (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, p_source_digest => 'sha256:not-hexadecimal') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source digest must be sha256:<hex>' then
    raise exception 'a malformed source digest was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_one, token_one, p_source_commit => 'deadbeef') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source commit must be a 40 character hexadecimal SHA' then
    raise exception 'a short source commit was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(run_one, token_one, 'uploading') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'unknown run phase' then
    raise exception 'an unknown run phase was accepted (%)', coalesce(v_message,'no error');
  end if;

  ok := false; v_message := null;
  begin perform 1 from public.fail_analysis_run(run_one, token_one, 'Bad-Code') t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'error code must be 3-48 characters of a-z 0-9 _' then
    raise exception 'a free-text error code was accepted (%)', coalesce(v_message,'no error');
  end if;

  -- -- bounded retry in the second project ------------------------------------
  perform set_config('request.jwt.claim.sub', worker_b::text, true);
  select t.work_item_id, t.run_id, t.attempt, t.lease_token
    into v_id, run_other, v_attempt, token_other
    from public.claim_analysis_work(p_two, 300) t;
  if v_id <> item_project_two or run_other is null or v_attempt <> 1 then
    raise exception 'the second project worker could not claim its own project''s work';
  end if;
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_other, token_other, 'source_fetch_failed') t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'queued' or not v_retry then
    raise exception 'a first failed attempt did not schedule a bounded retry (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_other and r.status = 'failed' and r.error_code = 'source_fetch_failed'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the failed attempt was not recorded with its code'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_project_two and w.status = 'queued'
     and w.error_code = 'source_fetch_failed' and w.attempts = 1;
  if n <> 1 then raise exception 'the retried work item was not returned to the queue'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_other and e.kind = 'failed' and e.phase = 'claimed'
     and e.detail = 'source_fetch_failed';
  if n <> 1 then raise exception 'the failure event was not recorded'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_other and e.kind = 'retry_scheduled'
     and e.detail = 'attempt 1 of 2 used';
  if n <> 1 then raise exception 'the scheduled retry was not recorded'; end if;

  -- -- the attempt that will be reclaimed ------------------------------------
  -- Its resolved snapshot identity is recorded so the next attempt can see
  -- what the lost attempt actually analysed.
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_retry from public.submit_repository_analysis(p_one) t;
  if item_retry is null then raise exception 'the reclaim fixture was not submitted'; end if;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.attempt, t.lease_token into run_retry, v_attempt, token_retry
    from public.claim_analysis_work(p_one, 300) t;
  if run_retry is null or v_attempt <> 1 then
    raise exception 'the reclaim fixture was not claimed as a first attempt';
  end if;
  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_retry, token_retry, 'analyzing', checkpoint_two,
                                       ref_one, commit_one, digest_one) t;
  if not v_valid then raise exception 'the reclaim fixture could not record its progress'; end if;

  perform set_config('oryveta_test.item_retry', item_retry::text, true);
  perform set_config('oryveta_test.run_retry', run_retry::text, true);
  perform set_config('oryveta_test.token_retry', token_retry::text, true);
end
$runtime$;

-- ---------------------------------------------------------------------------
-- Elapsed wall-clock time, staged. now() is the transaction timestamp and never
-- advances inside this transaction, so the only way to present a stale lease to
-- the reclaim path is to move the deadline into the past as the table owner.
-- Everything the reclaim path then does is real.
-- ---------------------------------------------------------------------------
reset role;
do $expire$
declare
  n integer;
begin
  update public.factory_runs r
     set lease_expires_at = now() - interval '2 minutes'
   where r.id = current_setting('oryveta_test.run_retry')::uuid;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the stale lease fixture did not match exactly one run'; end if;
end
$expire$;

-- ---------------------------------------------------------------------------
-- 11. Reclaim of an abandoned attempt, and the bounded attempt budget.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $reclaim$
declare
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_one uuid := current_setting('oryveta_test.project_one')::uuid;
  item_retry uuid := current_setting('oryveta_test.item_retry')::uuid;
  run_retry uuid := current_setting('oryveta_test.run_retry')::uuid;
  token_retry uuid := current_setting('oryveta_test.token_retry')::uuid;
  ref_one text := 'github.com/octocat/Hello-World';
  commit_one text := left(encode(sha256(convert_to('oryveta-commit-one','UTF8')),'hex'),40);
  digest_one text := 'sha256:' || encode(sha256(convert_to('oryveta-archive-one','UTF8')),'hex');
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 7),
    'findings', jsonb_build_array());
  run_second uuid; token_second uuid;
  v_claim record;
  v_accepted boolean; v_reason text; v_item_status text; v_retry boolean;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  -- Recovery needs no scheduler: the next claim reclaims the stale attempt and
  -- hands the work item back out as the next attempt.
  n := 0;
  for v_claim in select * from public.claim_analysis_work(p_one, 300) loop
    n := n + 1;
    run_second := v_claim.run_id;
    token_second := v_claim.lease_token;
    -- DR-004: the reference and commit the lost attempt resolved are the work
    -- item's pin, so attempt two is held to the same source instead of
    -- re-resolving the default branch; only the archive digest is per attempt.
    if v_claim.work_item_id <> item_retry or v_claim.attempt <> 2
       or v_claim.max_attempts <> 2
       or v_claim.pinned_source_ref <> ref_one
       or v_claim.pinned_source_commit <> commit_one
       or v_claim.previous_source_digest <> digest_one
       or v_claim.previous_checkpoint -> 'step' <> '"snapshot_ready"'::jsonb then
      raise exception 'the reclaimed work item was not handed out as attempt two';
    end if;
  end loop;
  if n <> 1 then raise exception 'the reclaimed work item was handed out % times', n; end if;
  if run_second = run_retry or token_second = token_retry then
    raise exception 'the new attempt reused the lost attempt''s run or lease token';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_retry and w.pinned_source_ref = ref_one
     and w.pinned_source_commit = commit_one;
  if n <> 1 then
    raise exception 'DR-004: the work item lost its source pin when the attempt expired';
  end if;

  select count(*) into n from public.factory_runs r
   where r.id = run_retry and r.status = 'failed' and r.error_code = 'lease_expired'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the expired attempt was not failed as lease_expired'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_retry and e.kind = 'lease_expired'
     and e.detail = 'lease expired without a result';
  if n <> 1 then raise exception 'the lease expiry was not recorded as an event'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_retry and e.kind = 'retry_scheduled'
     and e.detail = 'attempt 1 of 2 used';
  if n <> 1 then raise exception 'the reclaim did not record a scheduled retry'; end if;

  -- The worker that lost the lease cannot publish the work it finished anyway.
  select t.accepted, t.reason into v_accepted, v_reason
    from public.finish_analysis_run(run_retry, token_retry, result_payload) t;
  if v_accepted or v_reason <> 'not_running' then
    raise exception 'an expired attempt still published a result (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- The last attempt fails: exhaustion is terminal, never a silently idle row.
  -- private.settle_work_item_after_attempt keeps the last attempt's real cause
  -- in work_items.error_code, because that is the useful answer to "why did my
  -- analysis fail". Exhaustion itself is stated by status = 'failed',
  -- attempts = max_attempts and the terminal attempts_exhausted event. The
  -- literal code 'attempts_exhausted' belongs to the defensive claim branch,
  -- which is exercised separately below.
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_second, token_second, 'analysis_process_failed') t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'failed' or v_retry then
    raise exception 'the exhausting attempt was not settled terminally (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_retry and w.status = 'failed' and w.attempts = 2
     and w.max_attempts = 2 and w.error_code = 'analysis_process_failed';
  if n <> 1 then
    raise exception 'exhausting the attempt budget did not fail the work item terminally';
  end if;
  -- Each attempt keeps its own cause, so the durable history explains both
  -- the lost attempt and the one that ended the budget.
  select count(*) into n from public.factory_runs r
   where r.work_item_id = item_retry
     and ((r.attempt = 1 and r.error_code = 'lease_expired')
       or (r.attempt = 2 and r.error_code = 'analysis_process_failed'));
  if n <> 2 then raise exception 'the two attempts did not each keep their own cause'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_second and e.kind = 'attempts_exhausted'
     and e.detail = '2 of 2 attempts used';
  if n <> 1 then raise exception 'attempt exhaustion was not recorded as a terminal event'; end if;
  select count(*) into n from public.factory_run_events e
   where e.work_item_id = item_retry and e.kind = 'retry_scheduled';
  if n <> 1 then raise exception 'exhaustion scheduled a retry that does not exist'; end if;
end
$reclaim$;

-- ---------------------------------------------------------------------------
-- A queued work item with no remaining attempt cannot be produced through the
-- RPCs, because the failure path makes exhaustion terminal in the same call. It
-- is still the state public.claim_analysis_work defends against, so it is
-- staged here as the table owner to prove the defence.
-- ---------------------------------------------------------------------------
reset role;
do $unrunnable$
declare
  n integer;
begin
  update public.work_items w
     set status = 'queued', error_code = null
   where w.id = current_setting('oryveta_test.item_retry')::uuid
     and w.attempts = w.max_attempts;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the unrunnable work item fixture was not staged'; end if;
end
$unrunnable$;

-- ---------------------------------------------------------------------------
-- 12-13. The defensive claim branch, cancellation and worker revocation.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $control$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  engineer_id uuid := '2b222222-2222-4222-8222-222222222222';
  viewer_id uuid := '2c333333-3333-4333-8333-333333333333';
  nonmember_id uuid := '2d444444-4444-4444-8444-444444444444';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_one uuid := current_setting('oryveta_test.project_one')::uuid;
  item_retry uuid := current_setting('oryveta_test.item_retry')::uuid;
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 7),
    'findings', jsonb_build_array());
  item_cancel uuid; run_cancel uuid; token_cancel uuid;
  item_revoke uuid; run_revoke uuid; token_revoke uuid;
  registration_a uuid;
  v_id uuid; v_status text; v_terminal boolean; v_fenced integer;
  v_valid boolean; v_reason text; v_run_status text; v_item_status text;
  v_cancel boolean; v_accepted boolean; v_enabled boolean; v_attempt integer;
  v_actor uuid; v_message text;
  n integer; ok boolean;
begin
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select count(*) into n from public.claim_analysis_work(p_one, 300) t;
  if n <> 0 then raise exception 'a work item with no remaining attempt was handed out'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_retry and w.status = 'failed' and w.error_code = 'attempts_exhausted';
  if n <> 1 then raise exception 'claim left an unrunnable work item queued'; end if;

  -- -- 12. cancellation ------------------------------------------------------
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_cancel from public.submit_repository_analysis(p_one) t;
  if item_cancel is null then raise exception 'the cancellation fixture was not submitted'; end if;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.attempt, t.lease_token into run_cancel, v_attempt, token_cancel
    from public.claim_analysis_work(p_one, 300) t;
  if run_cancel is null or v_attempt <> 1 then
    raise exception 'the cancellation fixture was not claimed';
  end if;

  -- An unauthorized caller is told the same thing as for a missing row, so work
  -- item ids in other projects are not probeable.
  foreach v_actor in array array[viewer_id, nonmember_id] loop
    perform set_config('request.jwt.claim.sub', v_actor::text, true);
    ok := false; v_message := null;
    begin perform 1 from public.cancel_work_item(item_cancel) t;
    exception when others then ok := true; v_message := sqlerrm; end;
    if not ok or v_message <> 'work item not found' then
      raise exception '% could cancel accepted work (%)', v_actor, coalesce(v_message,'no error');
    end if;
  end loop;

  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id, t.status, t.already_terminal, t.fenced_runs
    into v_id, v_status, v_terminal, v_fenced
    from public.cancel_work_item(item_cancel) t;
  if v_id <> item_cancel or v_status <> 'cancelled' or v_terminal or v_fenced <> 1 then
    raise exception 'cancellation did not fence the live attempt';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_cancel and w.status = 'cancelled'
     and w.cancel_requested_at is not null and w.cancelled_by = engineer_id;
  if n <> 1 then raise exception 'the cancelled work item was not recorded as cancelled'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_cancel and r.status = 'cancelled' and r.error_code = 'cancelled'
     and r.finished_at is not null and r.result is null;
  if n <> 1 then raise exception 'the live attempt was not cancelled with the work item'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_cancel and e.kind = 'cancelled'
     and e.detail = 'cancelled by an authorized project editor';
  if n <> 1 then raise exception 'the cancellation was not recorded as an event'; end if;

  select t.status, t.already_terminal, t.fenced_runs into v_status, v_terminal, v_fenced
    from public.cancel_work_item(item_cancel) t;
  if v_status <> 'cancelled' or not v_terminal or v_fenced <> 0 then
    raise exception 'cancelling a terminal work item was not inert';
  end if;

  -- The fenced worker learns it must stop, and can publish nothing.
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.lease_valid, t.reason, t.run_status, t.work_item_status, t.cancel_requested
    into v_valid, v_reason, v_run_status, v_item_status, v_cancel
    from public.heartbeat_analysis_run(run_cancel, token_cancel, 'analyzing') t;
  if v_valid or v_reason <> 'cancelled' or v_run_status <> 'cancelled'
     or v_item_status <> 'cancelled' or not v_cancel then
    raise exception 'a cancelled attempt did not report cancellation to its worker';
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.finish_analysis_run(run_cancel, token_cancel, result_payload) t;
  if v_accepted or v_reason <> 'cancelled' then
    raise exception 'a cancelled attempt published a result (%)', coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.fail_analysis_run(run_cancel, token_cancel, 'late_failure') t;
  if v_accepted or v_reason <> 'not_running' then
    raise exception 'a cancelled attempt recorded a late failure (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- -- 13. revocation while a run is held ------------------------------------
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_revoke from public.submit_repository_analysis(p_one) t;
  if item_revoke is null then raise exception 'the revocation fixture was not submitted'; end if;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.attempt, t.lease_token into run_revoke, v_attempt, token_revoke
    from public.claim_analysis_work(p_one, 300) t;
  if run_revoke is null or v_attempt <> 1 then
    raise exception 'the revocation fixture was not claimed';
  end if;

  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select w.id into registration_a from public.project_workers w
   where w.project_id = p_one and w.worker_user_id = worker_a;
  select t.id, t.enabled, t.fenced_runs into v_id, v_enabled, v_fenced
    from public.revoke_project_worker(p_one, worker_a) t;
  if v_id <> registration_a or v_enabled or v_fenced <> 1 then
    raise exception 'revocation did not disable the registration and fence its run';
  end if;
  select count(*) into n from public.project_workers w
   where w.id = registration_a and not w.enabled and w.revoked_at is not null
     and w.revoked_by = owner_id;
  if n <> 1 then raise exception 'the revoked registration was not recorded as revoked'; end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_revoke and r.status = 'cancelled' and r.error_code = 'worker_revoked'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the revoked worker''s run was not cancelled'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = run_revoke and e.kind = 'cancelled'
     and e.detail = 'worker registration revoked';
  if n <> 1 then raise exception 'the revocation was not recorded against the run'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_revoke and w.status = 'queued' and w.error_code = 'worker_revoked'
     and w.attempts = 1;
  if n <> 1 then raise exception 'the work item of a revoked worker was not requeued'; end if;

  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.claim_analysis_work(p_one, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'worker identity is not registered for this project' then
    raise exception 'a revoked worker could still claim work (%)', coalesce(v_message,'no error');
  end if;
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_revoke, token_revoke, 'analyzing') t;
  if v_valid or v_reason <> 'worker_not_registered' then
    raise exception 'a revoked worker was not told its registration is gone (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.work_items w where w.project_id = p_one;
  if n <> 0 then raise exception 'a revoked worker identity still reads project work'; end if;

  -- Re-registration re-enables the same row rather than creating a second one.
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.id, t.enabled into v_id, v_enabled
    from public.register_project_worker(p_one, worker_a, 'Factory worker A') t;
  if v_id <> registration_a or not v_enabled then
    raise exception 're-registering the worker did not re-enable its registration';
  end if;
  select count(*) into n from public.project_workers w
   where w.project_id = p_one and w.worker_user_id = worker_a and w.enabled
     and w.revoked_at is null and w.revoked_by is null;
  if n <> 1 then raise exception 'the re-enabled registration is not clean'; end if;

  perform set_config('oryveta_test.item_revoke', item_revoke::text, true);
  perform set_config('oryveta_test.run_revoke', run_revoke::text, true);
  perform set_config('oryveta_test.token_revoke', token_revoke::text, true);
end
$control$;

-- ---------------------------------------------------------------------------
-- Workspace participation for the account whose only authority over a project
-- is its membership of that project's workspace. Provisioned as the table
-- owner because no client role may write public.workspace_memberships, and
-- withdrawn the same way further down so the second precedence path of
-- private.user_project_role is exercised too (DR-001).
-- ---------------------------------------------------------------------------
reset role;
do $creator_workspace_grant$
declare
  n integer;
begin
  insert into public.workspace_memberships(workspace_id,user_id,role)
  values (current_setting('oryveta_test.workspace_one')::uuid,
          '3d000000-0000-4000-8000-000000000000','owner');
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the workspace-only creator fixture was not provisioned';
  end if;
end
$creator_workspace_grant$;

-- ---------------------------------------------------------------------------
-- 14. DR-001: every worker transition reauthorizes the recorded creator. A
--     submitter who loses editing authority must not keep a worker analysing
--     their project's source, so a queued item of theirs is failed terminally
--     by the claim and a live attempt is fenced on its next transition. Each
--     refusal is terminal for its attempt, so heartbeat, finish and fail each
--     get their own live attempt. The authorized paths in the same section
--     prove the check does not fence ordinary work.
--
--     A dedicated project is used throughout, so revoking a grant cannot
--     disturb the membership fixtures or the claim ordering of the sections
--     above.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $creator_authority$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  engineer_id uuid := '2b222222-2222-4222-8222-222222222222';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  ws_creator uuid := '3d000000-0000-4000-8000-000000000000';
  ws_one uuid := current_setting('oryveta_test.workspace_one')::uuid;
  email_engineer text := 'oryveta-runtime-engineer@example.invalid';
  url_one text := 'https://github.com/octocat/Hello-World';
  ref_one text := 'github.com/octocat/Hello-World';
  commit_one text := left(encode(sha256(convert_to('oryveta-commit-one','UTF8')),'hex'),40);
  digest_ok text := 'sha256:' || encode(sha256(convert_to('oryveta-creator-ok','UTF8')),'hex');
  digest_live text := 'sha256:' || encode(sha256(convert_to('oryveta-creator-live','UTF8')),'hex');
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 5),
    'findings', jsonb_build_array());
  p_four uuid; inv uuid;
  item_ok uuid; run_ok uuid; token_ok uuid;
  item_beat uuid; run_beat uuid; token_beat uuid;
  item_finish uuid; run_finish uuid; token_finish uuid;
  item_fail uuid; run_fail uuid; token_fail uuid;
  item_queued uuid;
  item_auth uuid; run_auth uuid; token_auth uuid;
  item_ws uuid; run_ws uuid; token_ws uuid; item_ws_queued uuid;
  v_id uuid; v_valid boolean; v_reason text; v_accepted boolean; v_retry boolean;
  v_item_status text; v_attempt integer; v_message text;
  n integer; ok boolean;
begin
  -- -- a project of its own, with the real worker identity registered for it --
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.id into p_four from public.create_project(
    ws_one,'Runtime creator authority','Creator reauthorization checks','evolve',url_one) t;
  if p_four is null then
    raise exception 'the creator authority project fixture was not created';
  end if;
  perform 1 from public.register_project_worker(p_four, worker_a, 'Factory worker A') t;
  select t.id into inv from public.invite_project_member(p_four,email_engineer,'engineer') t;
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.project_id into v_id from public.accept_project_invitation(inv) t;
  if v_id <> p_four then
    raise exception 'the engineer fixture did not join the creator authority project';
  end if;

  -- -- an authorized creator's attempt runs end to end ----------------------
  select t.work_item_id into item_ok from public.submit_repository_analysis(p_four) t;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.work_item_id, t.run_id, t.attempt, t.lease_token
    into v_id, run_ok, v_attempt, token_ok
    from public.claim_analysis_work(p_four, 300) t;
  if v_id <> item_ok or run_ok is null or v_attempt <> 1 then
    raise exception 'DR-001: an authorized creator''s work item was not handed out';
  end if;
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_ok, token_ok, 'analyzing', null,
                                       ref_one, commit_one, digest_ok) t;
  if not v_valid or v_reason <> 'ok' then
    raise exception 'DR-001: an authorized creator''s attempt could not heartbeat (%)',
      coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_ok, token_ok, result_payload) t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'succeeded' then
    raise exception 'DR-001: an authorized creator''s attempt could not publish (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- -- three live attempts and one queued item, all submitted while their
  -- -- creator still holds the project grant. Each claim below sees exactly one
  -- -- queued candidate, because now() never advances inside this transaction
  -- -- and the claim order is therefore only total by id.
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_beat from public.submit_repository_analysis(p_four) t;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.lease_token into run_beat, token_beat
    from public.claim_analysis_work(p_four, 300) t;
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_finish from public.submit_repository_analysis(p_four) t;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.lease_token into run_finish, token_finish
    from public.claim_analysis_work(p_four, 300) t;
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_fail from public.submit_repository_analysis(p_four) t;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.run_id, t.lease_token into run_fail, token_fail
    from public.claim_analysis_work(p_four, 300) t;
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  select t.work_item_id into item_queued from public.submit_repository_analysis(p_four) t;
  if run_beat is null or run_finish is null or run_fail is null or item_queued is null then
    raise exception 'the creator reauthorization fixtures were not all claimed';
  end if;
  -- Each live attempt records a complete snapshot identity, so none of the
  -- refusals below can be mistaken for a missing or partial source identity.
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  for i in 1..3 loop
    select t.lease_valid into v_valid from public.heartbeat_analysis_run(
      (array[run_beat, run_finish, run_fail])[i],
      (array[token_beat, token_finish, token_fail])[i],
      'analyzing', null, ref_one, commit_one, digest_live) t;
    if not v_valid then
      raise exception 'creator reauthorization fixture % could not record its snapshot', i;
    end if;
  end loop;

  -- -- the creator's project grant is withdrawn ------------------------------
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  perform public.revoke_project_member(p_four, engineer_id);
  perform set_config('request.jwt.claim.sub', engineer_id::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.submit_repository_analysis(p_four) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'not allowed to submit work for this project' then
    raise exception 'the revoked creator still holds submission authority (%)',
      coalesce(v_message,'no error');
  end if;

  -- -- DR-001: a queued item whose creator lost authority is failed, not run --
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select count(*) into n from public.claim_analysis_work(p_four, 300) t;
  if n <> 0 then
    raise exception 'DR-001: the claim handed out work whose creator lost editing authority';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_queued and w.status = 'failed'
     and w.error_code = 'creator_unauthorized' and w.attempts = 0;
  if n <> 1 then
    raise exception 'DR-001: the claim did not terminally fail the unauthorized creator''s item';
  end if;
  select count(*) into n from public.factory_runs r where r.work_item_id = item_queued;
  if n <> 0 then
    raise exception 'DR-001: an attempt was created for an unauthorized creator''s work item';
  end if;

  -- -- DR-001: the next heartbeat of a live attempt fences it ----------------
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_beat, token_beat, 'analyzing') t;
  if v_valid or v_reason <> 'creator_unauthorized' then
    raise exception 'DR-001: a live attempt kept its lease after its creator lost authority (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_beat and r.status = 'cancelled'
     and r.error_code = 'creator_unauthorized' and r.finished_at is not null
     and r.result is null;
  if n <> 1 then
    raise exception 'DR-001: the fenced attempt was not cancelled as creator_unauthorized';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_beat and w.status = 'failed'
     and w.error_code = 'creator_unauthorized';
  if n <> 1 then
    raise exception 'DR-001: the fenced attempt''s work item was not failed terminally';
  end if;

  -- -- DR-001: completion and failure of such an attempt are refused ---------
  select t.accepted, t.reason into v_accepted, v_reason
    from public.finish_analysis_run(run_finish, token_finish, result_payload) t;
  if v_accepted or v_reason <> 'creator_unauthorized' then
    raise exception 'DR-001: a result was published after its creator lost authority (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_finish and r.status <> 'running' and r.result is null
     and r.finished_at is not null;
  if n <> 1 then
    raise exception 'DR-001: the refused completion left its attempt live';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_finish and w.status = 'failed'
     and w.error_code = 'creator_unauthorized';
  if n <> 1 then
    raise exception 'DR-001: the refused completion did not fail its work item terminally';
  end if;

  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_fail, token_fail, 'analysis_process_failed') t;
  if v_accepted or v_reason <> 'creator_unauthorized'
     or v_item_status <> 'failed' or v_retry then
    raise exception 'DR-001: a failure report was accepted for an unauthorized creator (%)',
      coalesce(v_reason,'no reason');
  end if;
  -- The attempt budget is irrelevant here: an item nobody is authorized to run
  -- is terminal, never queued for another attempt.
  select count(*) into n from public.work_items w
   where w.id = item_fail and w.status = 'failed'
     and w.error_code = 'creator_unauthorized'
     and w.attempts = 1 and w.attempts < w.max_attempts;
  if n <> 1 then
    raise exception 'DR-001: the unauthorized creator''s item was requeued instead of failed';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_fail and r.status <> 'running' and r.finished_at is not null;
  if n <> 1 then
    raise exception 'DR-001: the refused failure left its attempt live';
  end if;

  -- A still-authorized creator's failed attempt is untouched by the new check:
  -- the attempt's own cause is recorded and the item is retried in budget. It
  -- is then cancelled, so the claims below see exactly one queued candidate.
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.work_item_id into item_auth from public.submit_repository_analysis(p_four) t;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.work_item_id, t.run_id, t.lease_token into v_id, run_auth, token_auth
    from public.claim_analysis_work(p_four, 300) t;
  if v_id <> item_auth or run_auth is null then
    raise exception 'DR-001: an authorized creator''s item was not handed out after a revocation';
  end if;
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_auth, token_auth, 'source_fetch_failed') t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'queued' or not v_retry then
    raise exception 'DR-001: an authorized creator''s failed attempt was not retried (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_auth and w.status = 'queued'
     and w.error_code = 'source_fetch_failed' and w.attempts = 1;
  if n <> 1 then
    raise exception 'DR-001: an authorized creator''s retry did not stay queued';
  end if;
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  perform 1 from public.cancel_work_item(item_auth) t;

  -- -- the same rule through the workspace precedence path -------------------
  -- ws_creator holds no explicit grant on this project at all: its authority
  -- is the workspace membership private.project_role caps at 'admin'.
  select count(*) into n from public.project_memberships m
   where m.project_id = p_four and m.user_id = ws_creator;
  if n <> 0 then
    raise exception 'the workspace-only creator fixture holds an explicit project grant';
  end if;
  perform set_config('request.jwt.claim.sub', ws_creator::text, true);
  select t.work_item_id into item_ws from public.submit_repository_analysis(p_four) t;
  if item_ws is null then
    raise exception 'the workspace-only creator could not submit analysis work';
  end if;
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.work_item_id, t.run_id, t.lease_token into v_id, run_ws, token_ws
    from public.claim_analysis_work(p_four, 300) t;
  if v_id <> item_ws or run_ws is null then
    raise exception 'DR-001: a workspace-authorized creator''s work item was not handed out';
  end if;
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_ws, token_ws, 'analyzing', null,
                                       ref_one, commit_one, digest_live) t;
  if not v_valid or v_reason <> 'ok' then
    raise exception 'DR-001: a workspace-authorized creator''s attempt was fenced (%)',
      coalesce(v_reason,'no reason');
  end if;
  perform set_config('request.jwt.claim.sub', ws_creator::text, true);
  select t.work_item_id into item_ws_queued from public.submit_repository_analysis(p_four) t;
  if item_ws_queued is null then
    raise exception 'the workspace-only queued fixture was not submitted';
  end if;

  perform set_config('oryveta_test.project_four', p_four::text, true);
  perform set_config('oryveta_test.run_beat', run_beat::text, true);
  perform set_config('oryveta_test.item_ws', item_ws::text, true);
  perform set_config('oryveta_test.run_ws', run_ws::text, true);
  perform set_config('oryveta_test.token_ws', token_ws::text, true);
  perform set_config('oryveta_test.item_ws_queued', item_ws_queued::text, true);
end
$creator_authority$;

-- ---------------------------------------------------------------------------
-- Two facts only the table owner can state or stage: the fencing token of the
-- attempt DR-001 just fenced is really gone, and the workspace membership that
-- is the workspace-only creator's sole authority is withdrawn, which no client
-- role holds a write privilege for.
-- ---------------------------------------------------------------------------
reset role;
do $creator_workspace_revoke$
declare
  n integer;
begin
  select count(*) into n from private.factory_run_leases l
   where l.run_id = current_setting('oryveta_test.run_beat')::uuid;
  if n <> 0 then
    raise exception 'DR-001: the fenced attempt kept its fencing token';
  end if;

  delete from public.workspace_memberships m
   where m.workspace_id = current_setting('oryveta_test.workspace_one')::uuid
     and m.user_id = '3d000000-0000-4000-8000-000000000000';
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the workspace-only creator''s membership was not withdrawn';
  end if;
end
$creator_workspace_revoke$;

-- ---------------------------------------------------------------------------
-- 15. DR-001 through the second precedence path: the creator's authority came
--     only from the workspace membership that has just been withdrawn, so the
--     live attempt is fenced and the queued item fails terminally exactly as
--     for a withdrawn project grant.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $creator_workspace$
declare
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_four uuid := current_setting('oryveta_test.project_four')::uuid;
  item_ws uuid := current_setting('oryveta_test.item_ws')::uuid;
  run_ws uuid := current_setting('oryveta_test.run_ws')::uuid;
  token_ws uuid := current_setting('oryveta_test.token_ws')::uuid;
  item_ws_queued uuid := current_setting('oryveta_test.item_ws_queued')::uuid;
  v_valid boolean; v_reason text;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_ws, token_ws, 'analyzing') t;
  if v_valid or v_reason <> 'creator_unauthorized' then
    raise exception 'DR-001: losing the workspace membership did not fence the attempt (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_ws and r.status = 'cancelled'
     and r.error_code = 'creator_unauthorized' and r.finished_at is not null;
  if n <> 1 then
    raise exception 'DR-001: the workspace-path attempt was not cancelled as creator_unauthorized';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_ws and w.status = 'failed'
     and w.error_code = 'creator_unauthorized';
  if n <> 1 then
    raise exception 'DR-001: the workspace-path work item was not failed terminally';
  end if;

  select count(*) into n from public.claim_analysis_work(p_four, 300) t;
  if n <> 0 then
    raise exception 'DR-001: the claim handed out work whose creator lost workspace authority';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_ws_queued and w.status = 'failed'
     and w.error_code = 'creator_unauthorized' and w.attempts = 0;
  if n <> 1 then
    raise exception 'DR-001: the claim did not terminally fail the workspace-path queued item';
  end if;
  select count(*) into n from public.factory_runs r
   where r.work_item_id = item_ws_queued;
  if n <> 0 then
    raise exception 'DR-001: an attempt was created for the workspace-path queued item';
  end if;
end
$creator_workspace$;

-- ---------------------------------------------------------------------------
-- 16. DR-004: the source identity a work item is analysed against is pinned on
--     the work item, not re-resolved by whichever attempt runs next. The pin is
--     both-or-neither, set by the first attempt that resolves a reference and a
--     commit together, handed to every later attempt by the claim, and a
--     completion needs the whole identity. The archive digest stays per
--     attempt, so each attempt's digest here differs from the last.
-- ---------------------------------------------------------------------------
do $pinned_identity$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_four uuid := current_setting('oryveta_test.project_four')::uuid;
  ref_one text := 'github.com/octocat/Hello-World';
  ref_two text := 'github.com/octocat/Spoon-Knife';
  commit_one text := left(encode(sha256(convert_to('oryveta-commit-one','UTF8')),'hex'),40);
  commit_two text := left(encode(sha256(convert_to('oryveta-commit-two','UTF8')),'hex'),40);
  digest_first text :=
    'sha256:' || encode(sha256(convert_to('oryveta-pin-attempt-one','UTF8')),'hex');
  digest_second text :=
    'sha256:' || encode(sha256(convert_to('oryveta-pin-attempt-two','UTF8')),'hex');
  checkpoint_first jsonb := '{"step":"snapshot_ready","archive_entries":9}'::jsonb;
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 5),
    'findings', jsonb_build_array());
  item_pin uuid; run_first uuid; token_first uuid;
  run_second uuid; token_second uuid;
  v_claim record;
  v_valid boolean; v_reason text; v_accepted boolean;
  v_item_status text; v_retry boolean; v_message text;
  n integer; ok boolean;
begin
  perform set_config('request.jwt.claim.sub', owner_id::text, true);
  select t.work_item_id into item_pin from public.submit_repository_analysis(p_four) t;
  if item_pin is null then raise exception 'the source pin fixture was not submitted'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_pin and w.pinned_source_ref is null
     and w.pinned_source_commit is null;
  if n <> 1 then
    raise exception 'DR-004: a newly submitted work item already carries a source pin';
  end if;

  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  n := 0;
  for v_claim in select * from public.claim_analysis_work(p_four, 300) loop
    n := n + 1;
    run_first := v_claim.run_id;
    token_first := v_claim.lease_token;
    if v_claim.work_item_id <> item_pin or v_claim.attempt <> 1
       or v_claim.pinned_source_ref is not null
       or v_claim.pinned_source_commit is not null
       or v_claim.previous_source_digest is not null
       or v_claim.previous_checkpoint <> '{}'::jsonb then
      raise exception 'DR-004: the first claim did not describe an unpinned work item';
    end if;
  end loop;
  if n <> 1 then raise exception 'the source pin fixture was handed out % times', n; end if;

  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_first, token_first, 'analyzing', checkpoint_first,
                                       ref_one, commit_one, digest_first) t;
  if not v_valid then raise exception 'the first pin heartbeat was refused'; end if;
  select count(*) into n from public.work_items w
   where w.id = item_pin and w.pinned_source_ref = ref_one
     and w.pinned_source_commit = commit_one;
  if n <> 1 then
    raise exception 'DR-004: the resolved source identity was not pinned on the work item';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_first and r.source_ref = ref_one and r.source_commit = commit_one
     and r.source_digest = digest_first;
  if n <> 1 then
    raise exception 'the first attempt did not record its own snapshot identity';
  end if;

  -- -- the retry is held to the pin ------------------------------------------
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_first, token_first, 'analysis_process_failed') t;
  if not v_accepted or v_item_status <> 'queued' or not v_retry then
    raise exception 'the pinned work item was not returned to the queue (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_pin and w.pinned_source_ref = ref_one
     and w.pinned_source_commit = commit_one;
  if n <> 1 then
    raise exception 'DR-004: the work item lost its source pin when the attempt failed';
  end if;

  n := 0;
  for v_claim in select * from public.claim_analysis_work(p_four, 300) loop
    n := n + 1;
    run_second := v_claim.run_id;
    token_second := v_claim.lease_token;
    if v_claim.work_item_id <> item_pin or v_claim.attempt <> 2
       or v_claim.pinned_source_ref <> ref_one
       or v_claim.pinned_source_commit <> commit_one
       or v_claim.previous_source_digest <> digest_first
       or v_claim.previous_checkpoint -> 'step' <> '"snapshot_ready"'::jsonb then
      raise exception 'DR-004: the retry was not handed the work item source pin';
    end if;
  end loop;
  if n <> 1 then raise exception 'the pinned retry was handed out % times', n; end if;

  -- A retry that resolved something else fetched a moved upstream, not the
  -- source this work item was authorized for, so the heartbeat refuses it
  -- instead of silently recording a second identity for the same work.
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_second, token_second, 'fetching_source', p_source_commit => commit_two) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source identity conflicts with the work item pin' then
    raise exception 'DR-004: a retry recorded a commit outside the work item pin (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin perform 1 from public.heartbeat_analysis_run(
    run_second, token_second, 'fetching_source', p_source_ref => ref_two) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'source identity conflicts with the work item pin' then
    raise exception 'DR-004: a retry recorded a reference outside the work item pin (%)',
      coalesce(v_message,'no error');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_second and r.source_ref is null and r.source_commit is null
     and r.source_digest is null;
  if n <> 1 then
    raise exception 'a refused pin heartbeat still recorded a source identity';
  end if;

  -- The archive digest is this attempt's bytes, not the identity of the source.
  -- A completion that cannot name the reference and commit it analysed is
  -- refused even though a digest is recorded.
  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_second, token_second, 'analyzing',
                                       p_source_digest => digest_second) t;
  if not v_valid then
    raise exception 'the retry could not record its own archive digest';
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_pin and w.pinned_source_ref = ref_one
     and w.pinned_source_commit = commit_one;
  if n <> 1 then
    raise exception 'DR-004: a per-attempt archive digest changed the work item pin';
  end if;
  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_second, token_second, result_payload) t;
  if v_accepted or v_reason <> 'source_identity_missing' or v_item_status <> 'running' then
    raise exception 'DR-004: a result was accepted with a digest but no source identity (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- With the pinned reference and commit recorded too, this attempt holds the
  -- whole identity, so only a disagreement with the pin can refuse it.
  select t.lease_valid into v_valid
    from public.heartbeat_analysis_run(run_second, token_second, 'analyzing',
                                       p_source_ref => ref_one,
                                       p_source_commit => commit_one) t;
  if not v_valid then
    raise exception 'the retry could not record the pinned source identity';
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_second and r.source_ref = ref_one and r.source_commit = commit_one
     and r.source_digest = digest_second;
  if n <> 1 then
    raise exception 'the retry did not record the pinned identity with its own digest';
  end if;

  perform set_config('oryveta_test.item_pin', item_pin::text, true);
  perform set_config('oryveta_test.run_pin_second', run_second::text, true);
  perform set_config('oryveta_test.token_pin_second', token_second::text, true);
end
$pinned_identity$;

-- ---------------------------------------------------------------------------
-- Two more facts one connection cannot produce. Both-or-neither is a table
-- constraint, so it is stated against a real pinned row as the table owner;
-- and an attempt whose recorded reference and commit disagree with the pin can
-- only arise from a concurrent attempt that pinned first, so that single
-- column is staged here. Everything finish_analysis_run then does is real.
-- ---------------------------------------------------------------------------
reset role;
do $pinned_identity_stage$
declare
  item_pin uuid := current_setting('oryveta_test.item_pin')::uuid;
  commit_two text := left(encode(sha256(convert_to('oryveta-commit-two','UTF8')),'hex'),40);
  n integer; ok boolean; v_message text;
begin
  ok := false; v_message := null;
  begin update public.work_items w set pinned_source_commit = null where w.id = item_pin;
  exception when check_violation then ok := true;
            when others then v_message := sqlerrm; end;
  if not ok then
    raise exception 'DR-004: a work item kept a pinned reference with no pinned commit (%)',
      coalesce(v_message,'no error');
  end if;
  ok := false; v_message := null;
  begin update public.work_items w set pinned_source_ref = null where w.id = item_pin;
  exception when check_violation then ok := true;
            when others then v_message := sqlerrm; end;
  if not ok then
    raise exception 'DR-004: a work item kept a pinned commit with no pinned reference (%)',
      coalesce(v_message,'no error');
  end if;

  update public.factory_runs r set source_commit = commit_two
   where r.id = current_setting('oryveta_test.run_pin_second')::uuid;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the conflicting source identity fixture did not match one run';
  end if;
end
$pinned_identity_stage$;

-- ---------------------------------------------------------------------------
-- 17. DR-004: a completion whose attempt disagrees with the work item pin is
--     refused, so a result can never be attributed to a source the work item
--     is not pinned to.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $pinned_identity_finish$
declare
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  item_pin uuid := current_setting('oryveta_test.item_pin')::uuid;
  run_second uuid := current_setting('oryveta_test.run_pin_second')::uuid;
  token_second uuid := current_setting('oryveta_test.token_pin_second')::uuid;
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 5),
    'findings', jsonb_build_array());
  v_accepted boolean; v_reason text; v_item_status text; v_retry boolean;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select t.accepted, t.reason, t.work_item_status into v_accepted, v_reason, v_item_status
    from public.finish_analysis_run(run_second, token_second, result_payload) t;
  if v_accepted or v_reason <> 'source_identity_conflict' or v_item_status <> 'running' then
    raise exception 'DR-004: a result was accepted for a source outside the work item pin (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.factory_runs r
   where r.id = run_second and r.status = 'running' and r.result is null;
  if n <> 1 then
    raise exception 'the refused completion still touched the attempt';
  end if;

  -- The attempt budget is spent, so reporting the conflict as this attempt's
  -- failure settles the work item terminally.
  select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
    into v_accepted, v_reason, v_item_status, v_retry
    from public.fail_analysis_run(run_second, token_second, 'source_identity_conflict') t;
  if not v_accepted or v_reason <> 'ok' or v_item_status <> 'failed' or v_retry then
    raise exception 'the conflicting attempt was not settled terminally (%)',
      coalesce(v_reason,'no reason');
  end if;
  select count(*) into n from public.work_items w
   where w.id = item_pin and w.status = 'failed' and w.attempts = 2
     and w.error_code = 'source_identity_conflict';
  if n <> 1 then
    raise exception 'the conflicting work item was not failed terminally';
  end if;
end
$pinned_identity_finish$;

-- ---------------------------------------------------------------------------
-- 18. DR-006: progress chatter cannot crowd out the outcome. The per-run event
--     budget is split, so phase changes, checkpoints and resolved sources stop
--     at 180 recorded events while the event that states how the attempt ended
--     is always recorded. Each case below fills one attempt's progress budget
--     with real heartbeats and then ends that attempt a different way.
-- ---------------------------------------------------------------------------
do $event_capacity$
declare
  owner_id uuid := '2a111111-1111-4111-8111-111111111111';
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_four uuid := current_setting('oryveta_test.project_four')::uuid;
  ref_one text := 'github.com/octocat/Hello-World';
  commit_one text := left(encode(sha256(convert_to('oryveta-commit-one','UTF8')),'hex'),40);
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 11),
    'findings', jsonb_build_array());
  v_case integer;
  v_item uuid; v_run uuid; v_token uuid; v_id uuid;
  v_digest text; v_phase text;
  v_valid boolean; v_reason text; v_accepted boolean;
  v_item_status text; v_retry boolean; v_attempt integer;
  n integer;
begin
  for v_case in 1..4 loop
    -- Case 4 is the second attempt of case 3's work item: exhaustion must be
    -- recordable on an attempt whose own progress budget is already spent.
    if v_case < 4 then
      perform set_config('request.jwt.claim.sub', owner_id::text, true);
      select t.work_item_id into v_item from public.submit_repository_analysis(p_four) t;
      if v_item is null then
        raise exception 'the event capacity fixture % was not submitted', v_case;
      end if;
    end if;
    perform set_config('request.jwt.claim.sub', worker_a::text, true);
    select t.work_item_id, t.run_id, t.attempt, t.lease_token
      into v_id, v_run, v_attempt, v_token
      from public.claim_analysis_work(p_four, 300) t;
    if v_id <> v_item or v_run is null
       or v_attempt <> (case when v_case = 4 then 2 else 1 end) then
      raise exception 'the event capacity fixture % was not claimed as expected', v_case;
    end if;
    v_digest := 'sha256:'
      || encode(sha256(convert_to('oryveta-capacity-' || v_case, 'UTF8')), 'hex');
    -- Two progress events: the resolved source and the phase change.
    select t.lease_valid into v_valid
      from public.heartbeat_analysis_run(v_run, v_token, 'fetching_source', null,
                                         ref_one, commit_one, v_digest) t;
    if not v_valid then
      raise exception 'the event capacity fixture % could not resolve its source', v_case;
    end if;
    -- 200 further progress events are attempted, alternating a phase change
    -- with a checkpoint inside that phase. A single 200-event budget is spent
    -- before the attempt ends; the split budget stops at 180 and keeps the
    -- outcome event recordable.
    for i in 1..100 loop
      v_phase := case when i % 2 = 1 then 'analyzing' else 'recording_result' end;
      select t.lease_valid into v_valid
        from public.heartbeat_analysis_run(v_run, v_token, v_phase,
               jsonb_build_object('step', v_phase, 'tick', i)) t;
      if not v_valid then
        raise exception 'a phase change heartbeat was refused at tick % of case %', i, v_case;
      end if;
      select t.lease_valid into v_valid
        from public.heartbeat_analysis_run(v_run, v_token, v_phase,
               jsonb_build_object('step', v_phase, 'tick', i, 'pass', 2)) t;
      if not v_valid then
        raise exception 'a checkpoint heartbeat was refused at tick % of case %', i, v_case;
      end if;
    end loop;

    select count(*) into n from public.factory_run_events e
     where e.run_id = v_run
       and e.kind in ('phase_changed','checkpoint','source_resolved');
    if n <> 180 then
      raise exception 'DR-006: attempt of case % recorded % progress events instead of the 180 progress budget',
        v_case, n;
    end if;
    select count(*) into n from public.factory_run_events e
     where e.run_id = v_run and e.kind = 'source_resolved';
    if n <> 1 then
      raise exception 'DR-006: case % recorded % source_resolved events', v_case, n;
    end if;
    select count(*) into n from public.factory_run_events e
     where e.run_id = v_run and e.kind = 'phase_changed';
    if n <> 90 then
      raise exception 'DR-006: case % recorded % phase_changed events', v_case, n;
    end if;
    select count(*) into n from public.factory_run_events e
     where e.run_id = v_run and e.kind = 'checkpoint';
    if n <> 89 then
      raise exception 'DR-006: case % recorded % checkpoint events', v_case, n;
    end if;

    if v_case = 1 then
      select t.accepted, t.reason into v_accepted, v_reason
        from public.finish_analysis_run(v_run, v_token, result_payload) t;
      if not v_accepted or v_reason <> 'ok' then
        raise exception 'the completion of an attempt at capacity was refused (%)',
          coalesce(v_reason,'no reason');
      end if;
      select count(*) into n from public.factory_run_events e
       where e.run_id = v_run and e.kind = 'succeeded';
      if n <> 1 then
        raise exception 'DR-006: the succeeded event was dropped by progress chatter';
      end if;
    elsif v_case = 2 then
      perform set_config('request.jwt.claim.sub', owner_id::text, true);
      perform 1 from public.cancel_work_item(v_item) t;
      perform set_config('request.jwt.claim.sub', worker_a::text, true);
      select count(*) into n from public.factory_run_events e
       where e.run_id = v_run and e.kind = 'cancelled';
      if n <> 1 then
        raise exception 'DR-006: the cancelled event was dropped by progress chatter';
      end if;
    else
      select t.accepted, t.reason, t.work_item_status, t.retry_scheduled
        into v_accepted, v_reason, v_item_status, v_retry
        from public.fail_analysis_run(v_run, v_token, 'analysis_process_failed') t;
      if not v_accepted or v_reason <> 'ok' then
        raise exception 'the failure of an attempt at capacity was refused (%)',
          coalesce(v_reason,'no reason');
      end if;
      select count(*) into n from public.factory_run_events e
       where e.run_id = v_run and e.kind = 'failed';
      if n <> 1 then
        raise exception 'DR-006: the failed event of case % was dropped by progress chatter',
          v_case;
      end if;
      if v_case = 3 then
        if v_item_status <> 'queued' or not v_retry then
          raise exception 'the retry of an attempt at capacity was not scheduled (%)',
            coalesce(v_reason,'no reason');
        end if;
        select count(*) into n from public.factory_run_events e
         where e.run_id = v_run and e.kind = 'retry_scheduled';
        if n <> 1 then
          raise exception 'DR-006: the retry_scheduled event was dropped by progress chatter';
        end if;
      else
        if v_item_status <> 'failed' or v_retry then
          raise exception 'the exhausting attempt at capacity was not settled terminally (%)',
            coalesce(v_reason,'no reason');
        end if;
        select count(*) into n from public.factory_run_events e
         where e.run_id = v_run and e.kind = 'attempts_exhausted';
        if n <> 1 then
          raise exception 'DR-006: the attempts_exhausted event was dropped by progress chatter';
        end if;
      end if;
    end if;
  end loop;
end
$event_capacity$;

-- ---------------------------------------------------------------------------
-- Withdrawal of the service designation, staged the way the Auth admin API
-- would do it. The project_workers row stays enabled on purpose: designation
-- and registration are two independent conditions and either one fences.
-- ---------------------------------------------------------------------------
reset role;
do $withdraw$
declare
  n integer;
begin
  update auth.users u
     set raw_app_meta_data = coalesce(u.raw_app_meta_data,'{}'::jsonb) - 'oryveta_role'
   where u.id = '2e555555-5555-4555-8555-555555555555';
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the designation withdrawal fixture did not match one account'; end if;
end
$withdraw$;

-- ---------------------------------------------------------------------------
-- 19. An undesignated identity is fenced even with an enabled registration.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $undesignated$
declare
  worker_a uuid := '2e555555-5555-4555-8555-555555555555';
  p_one uuid := current_setting('oryveta_test.project_one')::uuid;
  run_revoke uuid := current_setting('oryveta_test.run_revoke')::uuid;
  token_revoke uuid := current_setting('oryveta_test.token_revoke')::uuid;
  result_payload jsonb := jsonb_build_object(
    'summary', jsonb_build_object('source_files_analyzed', 7),
    'findings', jsonb_build_array());
  v_valid boolean; v_reason text; v_accepted boolean;
  v_message text;
  n integer; ok boolean;
begin
  perform set_config('request.jwt.claim.sub', worker_a::text, true);
  select count(*) into n from public.project_workers w
   where w.project_id = p_one and w.worker_user_id = worker_a and w.enabled;
  if n <> 1 then raise exception 'the withdrawal test did not keep the registration enabled'; end if;

  ok := false; v_message := null;
  begin perform 1 from public.claim_analysis_work(p_one, 300) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or
     v_message <> 'worker identity is not a provisioned factory worker service identity' then
    raise exception 'an undesignated identity could claim work (%)', coalesce(v_message,'no error');
  end if;

  select t.lease_valid, t.reason into v_valid, v_reason
    from public.heartbeat_analysis_run(run_revoke, token_revoke, 'analyzing') t;
  if v_valid or v_reason <> 'worker_not_registered' then
    raise exception 'an undesignated identity kept a live lease (%)', coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.finish_analysis_run(run_revoke, token_revoke, result_payload) t;
  if v_accepted or v_reason <> 'worker_not_registered' then
    raise exception 'an undesignated identity published a result (%)',
      coalesce(v_reason,'no reason');
  end if;
  select t.accepted, t.reason into v_accepted, v_reason
    from public.fail_analysis_run(run_revoke, token_revoke, 'worker_error') t;
  if v_accepted or v_reason <> 'worker_not_registered' then
    raise exception 'an undesignated identity recorded a failure (%)',
      coalesce(v_reason,'no reason');
  end if;

  -- The read path goes through the same condition, so it closes too.
  select count(*) into n from public.work_items w where w.project_id = p_one;
  if n <> 0 then raise exception 'an undesignated worker identity still reads project work'; end if;
end
$undesignated$;

-- ---------------------------------------------------------------------------
-- Closing audit, as the table owner: no fencing token outlived its attempt and
-- nothing is left half-running behind a worker that is gone.
-- ---------------------------------------------------------------------------
reset role;
do $audit$
declare
  p_one uuid := current_setting('oryveta_test.project_one')::uuid;
  p_two uuid := current_setting('oryveta_test.project_two')::uuid;
  p_three uuid := current_setting('oryveta_test.project_three')::uuid;
  p_four uuid := current_setting('oryveta_test.project_four')::uuid;
  n integer;
begin
  -- The creator reauthorization fixtures end in refusals, so every one of them
  -- has to leave its attempt settled and its token destroyed as well.
  select count(*) into n from private.factory_run_leases l
    join public.factory_runs r on r.id = l.run_id
   where r.project_id in (p_one, p_two, p_four);
  if n <> 0 then raise exception '% fencing tokens outlived their attempts', n; end if;

  select count(*) into n from public.factory_runs r
   where r.project_id in (p_one, p_two, p_four) and r.status = 'running';
  if n <> 0 then raise exception 'a run is still running after every attempt settled'; end if;

  select count(*) into n from public.work_items w
   where w.project_id in (p_one, p_two, p_three, p_four) and w.status = 'running';
  if n <> 0 then raise exception 'a work item is still running with no live attempt'; end if;

  -- A work item whose creator is no longer authorized is terminal, so none of
  -- them may be left queued for a worker to pick up later (DR-001).
  select count(*) into n from public.work_items w
   where w.project_id = p_four and w.status = 'queued';
  if n <> 0 then raise exception 'DR-001: % work items are queued behind a revoked creator', n; end if;

  -- Every event detail is derived server side from validated arguments, so none
  -- of them can carry a URL, a credential or a host filesystem path.
  select count(*) into n from public.factory_run_events e
   where e.project_id in (p_one, p_two, p_four)
     and (e.detail ~ '://' or e.detail ~ '\\' or e.detail ~ '^(/|~)');
  if n <> 0 then raise exception 'an event detail carries a URL or a filesystem path'; end if;
end
$audit$;

rollback;
