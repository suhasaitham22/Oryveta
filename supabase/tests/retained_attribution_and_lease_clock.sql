-- Referential-lifecycle and lease-timing regression for the hosted schema:
-- which deletions an operator and the Auth admin API must be able to perform,
-- which one must still be refused, what a retained terminal record keeps when
-- the account it was attributed to is gone, and that a lease deadline is
-- measured on the wall clock rather than on the transaction timestamp.
--
-- Run order (psql, ON_ERROR_STOP=1, on a superuser/owner connection to a
-- Supabase stack whose auth schema and anon/authenticated roles already exist
-- - the local `supabase start` stack or a dedicated development project):
--   1. supabase/schema.sql
--   2. supabase/migrations/private_chats_and_explicit_sharing.sql
--   3. supabase/migrations/projects_and_project_membership.sql
--   4. supabase/migrations/durable_factory_runtime.sql
--   5. supabase/migrations/retained_attribution_and_lease_clock.sql
--   6. this file
--
-- Requires SQL-editor/owner privileges and intentionally creates synthetic
-- auth.users. Everything here ROLLS BACK, even on success, so no fixture row
-- survives the run. Never run it on an unrelated project.
--
-- What is real and what is staged:
--   * Every grant, acceptance, submission, cancellation, claim, heartbeat,
--     completion and failure goes through the real RPCs and policies as the
--     authenticated role. Nothing is mocked.
--   * Account deletion is a table-owner DELETE on auth.users, which is what
--     the Auth admin API performs. Workspace deletion is the owner's own
--     client DELETE, allowed by workspace_delete_owner.
--   * public.workspace_memberships is provisioned by the owner role, and the
--     worker service designation is written into auth.users.raw_app_meta_data,
--     because no client role may write either one.
--   * Elapsed wall-clock time is NOT staged here. now() is the transaction
--     timestamp and never advances, while clock_timestamp() does, so
--     pg_sleep() inside this one transaction produces genuinely elapsed time
--     that the transaction timestamp cannot see. That difference is what the
--     lease cases measure. One lease is additionally placed a few hundred
--     milliseconds into the future *of the wall clock* and then waited out:
--     that deadline is still in the future according to now(), so only a
--     wall-clock comparison can call it expired.
--
-- Fixture identifiers cross the role switches in transaction-local settings,
-- because one DO block cannot share variables with the next.
begin;

-- ---------------------------------------------------------------------------
-- Fixtures: five ordinary accounts and one account that stands in for an Auth
-- service identity. Addresses are confirmed because invitation acceptance and
-- chat-share acceptance both require private.verified_email().
-- ---------------------------------------------------------------------------
insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,
   raw_app_meta_data,created_at,updated_at)
values
-- workspace and project owner: inviter, chat owner and submitter
('4a111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-owner@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- accepted the email project invitation; neither project creator nor inviter
('4b222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-invitee@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- workspace engineer who cancels a colleague's work item
('4c333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-editor@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- accepted the email chat share
('4d444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-reader@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- all three at once: accepted invitation, accepted share, cancelled work
('4e555555-5555-4555-8555-555555555555','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-everything@example.invalid','',now(),'{}'::jsonb,now(),now()),
-- designated worker service identity, registered for two projects
('4f666666-6666-4666-8666-666666666666','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-worker@example.invalid','',now(),'{"oryveta_role":"factory_worker"}'::jsonb,now(),now());

set local role authenticated;

do $tenancy$
declare
  v_owner uuid := '4a111111-1111-4111-8111-111111111111';
  v_worker uuid := '4f666666-6666-4666-8666-666666666666';
  v_ws uuid; v_ws_history uuid; v_ws_control uuid;
  v_p_run uuid; v_p_cancel uuid; v_p_invite uuid; v_p_history uuid; v_p_control uuid;
  v_chat uuid; v_inv_invitee uuid; v_inv_everything uuid;
  v_share_reader uuid; v_share_everything uuid;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  insert into public.workspaces(name,slug,created_by)
  values ('Lifecycle Main','lifecycle-main',v_owner) returning id into v_ws;
  insert into public.workspaces(name,slug,created_by)
  values ('Lifecycle History','lifecycle-history',v_owner) returning id into v_ws_history;
  insert into public.workspaces(name,slug,created_by)
  values ('Lifecycle Control','lifecycle-control',v_owner) returning id into v_ws_control;

  select t.id into v_p_run from public.create_project(
    v_ws, 'Lifecycle Runtime', 'lease timing', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  select t.id into v_p_cancel from public.create_project(
    v_ws, 'Lifecycle Cancellations', 'colleague cancellation', 'evolve',
    'https://github.com/octocat/Spoon-Knife') t;
  select t.id into v_p_invite from public.create_project(
    v_ws, 'Lifecycle Invitations', 'email invitations', 'new') t;
  select t.id into v_p_history from public.create_project(
    v_ws_history, 'Lifecycle Run History', 'terminal run history', 'evolve',
    'https://github.com/octocat/Hello-World') t;
  -- The control for the workspace deletion below: same owner, same privileges,
  -- no runtime history at all.
  select t.id into v_p_control from public.create_project(
    v_ws_control, 'Lifecycle Control', 'no run history', 'new') t;

  perform 1 from public.register_project_worker(v_p_run, v_worker, 'Lifecycle Worker') t;
  perform 1 from public.register_project_worker(v_p_history, v_worker, 'Lifecycle Worker') t;

  select t.id into v_inv_invitee from public.invite_project_member(
    v_p_invite, 'oryveta-lifecycle-invitee@example.invalid', 'engineer') t;
  select t.id into v_inv_everything from public.invite_project_member(
    v_p_invite, 'oryveta-lifecycle-everything@example.invalid', 'reviewer') t;

  insert into public.chats(owner_id,title)
  values (v_owner,'Lifecycle conversation') returning id into v_chat;
  -- One real message, so the read checks at the end of this file are about
  -- content a successor account must not reach, not about an empty chat.
  insert into public.chat_messages(chat_id,author_id,role,content)
  values (v_chat, v_owner, 'user', 'Lifecycle fixture message');
  insert into public.chat_shares(chat_id,invited_by,recipient_email,permission)
  values (v_chat,v_owner,'oryveta-lifecycle-reader@example.invalid','viewer')
  returning id into v_share_reader;
  insert into public.chat_shares(chat_id,invited_by,recipient_email,permission)
  values (v_chat,v_owner,'oryveta-lifecycle-everything@example.invalid','editor')
  returning id into v_share_everything;

  perform set_config('oryveta.lc_ws', v_ws::text, true);
  perform set_config('oryveta.lc_ws_history', v_ws_history::text, true);
  perform set_config('oryveta.lc_ws_control', v_ws_control::text, true);
  perform set_config('oryveta.lc_p_run', v_p_run::text, true);
  perform set_config('oryveta.lc_p_cancel', v_p_cancel::text, true);
  perform set_config('oryveta.lc_p_invite', v_p_invite::text, true);
  perform set_config('oryveta.lc_p_history', v_p_history::text, true);
  perform set_config('oryveta.lc_chat', v_chat::text, true);
  perform set_config('oryveta.lc_inv_invitee', v_inv_invitee::text, true);
  perform set_config('oryveta.lc_inv_everything', v_inv_everything::text, true);
  perform set_config('oryveta.lc_share_reader', v_share_reader::text, true);
  perform set_config('oryveta.lc_share_everything', v_share_everything::text, true);
end
$tenancy$;

-- Workspace engineer grants, written by the owner role exactly as the
-- administrative side does it: no client role may write this table.
reset role;
insert into public.workspace_memberships(workspace_id,user_id,role)
values (current_setting('oryveta.lc_ws')::uuid,
        '4c333333-3333-4333-8333-333333333333','engineer'),
       (current_setting('oryveta.lc_ws')::uuid,
        '4e555555-5555-4555-8555-555555555555','engineer');

set local role authenticated;

-- ---------------------------------------------------------------------------
-- Acceptances, submissions and the colleague cancellations, all through the
-- real RPCs and policies.
-- ---------------------------------------------------------------------------
do $acceptance$
declare
  v_owner uuid := '4a111111-1111-4111-8111-111111111111';
  v_invitee uuid := '4b222222-2222-4222-8222-222222222222';
  v_editor uuid := '4c333333-3333-4333-8333-333333333333';
  v_reader uuid := '4d444444-4444-4444-8444-444444444444';
  v_everything uuid := '4e555555-5555-4555-8555-555555555555';
  v_worker uuid := '4f666666-6666-4666-8666-666666666666';
  v_p_run uuid := current_setting('oryveta.lc_p_run')::uuid;
  v_p_cancel uuid := current_setting('oryveta.lc_p_cancel')::uuid;
  v_p_history uuid := current_setting('oryveta.lc_p_history')::uuid;
  v_inv_invitee uuid := current_setting('oryveta.lc_inv_invitee')::uuid;
  v_inv_everything uuid := current_setting('oryveta.lc_inv_everything')::uuid;
  v_share_reader uuid := current_setting('oryveta.lc_share_reader')::uuid;
  v_share_everything uuid := current_setting('oryveta.lc_share_everything')::uuid;
  v_item_editor uuid; v_item_everything uuid; v_item_run uuid; v_item_history uuid;
  v_run_history uuid; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_invitee::text, true);
  perform 1 from public.accept_project_invitation(v_inv_invitee) t;
  perform set_config('request.jwt.claim.sub', v_everything::text, true);
  perform 1 from public.accept_project_invitation(v_inv_everything) t;

  perform set_config('request.jwt.claim.sub', v_reader::text, true);
  update public.chat_shares s
     set status='accepted', accepted_by=v_reader, accepted_at=now()
   where s.id=v_share_reader;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'fixture: the reader could not accept the share'; end if;
  perform set_config('request.jwt.claim.sub', v_everything::text, true);
  update public.chat_shares s
     set status='accepted', accepted_by=v_everything, accepted_at=now()
   where s.id=v_share_everything;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'fixture: the second share was not accepted'; end if;

  -- Two items the owner submitted, cancelled by two different colleagues, plus
  -- the item the lease cases claim and the item that becomes run history.
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select t.work_item_id into v_item_editor from public.submit_repository_analysis(
    v_p_cancel, 'lifecycle-cancel-editor') t;
  select t.work_item_id into v_item_everything from public.submit_repository_analysis(
    v_p_cancel, 'lifecycle-cancel-everything') t;
  select t.work_item_id into v_item_run from public.submit_repository_analysis(v_p_run) t;
  select t.work_item_id into v_item_history
    from public.submit_repository_analysis(v_p_history) t;

  perform set_config('request.jwt.claim.sub', v_editor::text, true);
  perform 1 from public.cancel_work_item(v_item_editor) t;
  perform set_config('request.jwt.claim.sub', v_everything::text, true);
  perform 1 from public.cancel_work_item(v_item_everything) t;

  -- Terminal run history for the workspace deletion case: a real claimed
  -- attempt, cancelled by the owner, so the run is finished and still present.
  perform set_config('request.jwt.claim.sub', v_worker::text, true);
  select t.run_id into v_run_history from public.claim_analysis_work(v_p_history, 300) t;
  if v_run_history is null then
    raise exception 'fixture: the worker did not claim the history item';
  end if;
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  perform 1 from public.cancel_work_item(v_item_history) t;
  select count(*) into n from public.factory_runs r
   where r.id = v_run_history and r.status = 'cancelled' and r.finished_at is not null;
  if n <> 1 then raise exception 'fixture: the history attempt is not terminal'; end if;

  select count(*) into n from public.work_items w
   where w.id in (v_item_editor, v_item_everything)
     and w.status = 'cancelled' and w.cancel_requested_at is not null
     and w.created_by = v_owner and w.cancelled_by <> v_owner;
  if n <> 2 then
    raise exception 'fixture: the colleague cancellations were not recorded as expected';
  end if;

  perform set_config('oryveta.lc_item_editor', v_item_editor::text, true);
  perform set_config('oryveta.lc_item_everything', v_item_everything::text, true);
  perform set_config('oryveta.lc_item_run', v_item_run::text, true);
  perform set_config('oryveta.lc_item_history', v_item_history::text, true);
  perform set_config('oryveta.lc_run_history', v_run_history::text, true);
end
$acceptance$;

-- ---------------------------------------------------------------------------
-- 1. Lease creation and extension are measured on the wall clock.
--
-- A full second of real time elapses inside this transaction before the claim.
-- now() cannot see it, so a deadline built from now() would be exactly
-- p_lease_seconds away from the transaction timestamp; one built from the wall
-- clock is at least that second further out. This is the single-connection
-- form of the lock-wait defect: a claim that waits longer than its own lease
-- used to commit an attempt that was already expired.
-- ---------------------------------------------------------------------------
do $lease_creation$
declare
  v_worker uuid := '4f666666-6666-4666-8666-666666666666';
  v_p_run uuid := current_setting('oryveta.lc_p_run')::uuid;
  v_item_run uuid := current_setting('oryveta.lc_item_run')::uuid;
  v_claim record;
  v_beat record;
  v_first timestamptz;
begin
  perform set_config('request.jwt.claim.sub', v_worker::text, true);
  perform pg_sleep(1);
  select * into v_claim from public.claim_analysis_work(v_p_run, 300) t;
  if v_claim.run_id is null or v_claim.work_item_id <> v_item_run then
    raise exception 'the claim did not hand out the queued lease-timing item';
  end if;
  if v_claim.lease_expires_at <= now() + make_interval(secs => 300) then
    raise exception 'the claim measured its lease from the transaction timestamp, so a '
      'claim that waited on a lock would hand out an already-spent lease';
  end if;
  if v_claim.lease_expires_at
     < now() + make_interval(secs => 300) + interval '900 milliseconds' then
    raise exception 'the claim lost the second of real time that elapsed before it';
  end if;
  if v_claim.lease_expires_at <= clock_timestamp() then
    raise exception 'the claim handed out a lease that has already expired';
  end if;
  v_first := v_claim.lease_expires_at;

  perform pg_sleep(1);
  select * into v_beat from public.heartbeat_analysis_run(
    p_run_id => v_claim.run_id, p_lease_token => v_claim.lease_token,
    p_phase => 'fetching_source', p_lease_seconds => 300) t;
  if not v_beat.lease_valid then
    raise exception 'the first heartbeat of a fresh attempt was refused (%)', v_beat.reason;
  end if;
  if v_beat.lease_expires_at
     < now() + make_interval(secs => 300) + interval '1900 milliseconds' then
    raise exception 'the heartbeat extended the lease from the transaction timestamp';
  end if;
  if v_beat.lease_expires_at <= v_first then
    raise exception 'the heartbeat did not move the deadline forward';
  end if;

  perform set_config('oryveta.lc_run', v_claim.run_id::text, true);
  perform set_config('oryveta.lc_token', v_claim.lease_token::text, true);
end
$lease_creation$;

-- ---------------------------------------------------------------------------
-- 2. Lease expiry is decided on the wall clock too.
--
-- The deadline is placed a few hundred milliseconds into the future of the
-- wall clock and then waited out. Because this transaction has already spent
-- seconds, that deadline is still comfortably in the *future* of now(): a
-- transaction-timestamp comparison would report the lease live and let a
-- fenced worker keep going.
-- ---------------------------------------------------------------------------
reset role;
do $stage_expiry$
declare
  v_run uuid := current_setting('oryveta.lc_run')::uuid;
  v_lease timestamptz;
begin
  update public.factory_runs r
     set lease_expires_at = clock_timestamp() + interval '400 milliseconds'
   where r.id = v_run
  returning r.lease_expires_at into v_lease;
  if v_lease is null then raise exception 'the staged attempt was not found'; end if;
  if v_lease <= now() then
    raise exception 'this case needs a deadline that is still in the future of the '
      'transaction timestamp, so that only the wall clock can call it expired';
  end if;
  perform pg_sleep(1);
  if v_lease > clock_timestamp() then
    raise exception 'the staged deadline has not passed on the wall clock yet';
  end if;
end
$stage_expiry$;

set local role authenticated;
do $expiry$
declare
  v_worker uuid := '4f666666-6666-4666-8666-666666666666';
  v_run uuid := current_setting('oryveta.lc_run')::uuid;
  v_token uuid := current_setting('oryveta.lc_token')::uuid;
  v_beat record;
  v_finish record;
  v_fail record;
begin
  perform set_config('request.jwt.claim.sub', v_worker::text, true);
  select * into v_beat from public.heartbeat_analysis_run(
    p_run_id => v_run, p_lease_token => v_token, p_phase => 'analyzing',
    p_lease_seconds => 300) t;
  if v_beat.lease_valid or v_beat.reason <> 'lease_lost' then
    raise exception 'a heartbeat on a lease that expired on the wall clock was accepted (%)',
      coalesce(v_beat.reason, 'no reason');
  end if;

  select * into v_finish from public.finish_analysis_run(
    v_run, v_token, '{"summary":{"source_files_analyzed":3},"findings":[]}'::jsonb) t;
  if v_finish.accepted or v_finish.reason <> 'lease_lost' then
    raise exception 'a completion behind an expired lease was accepted (%)',
      coalesce(v_finish.reason, 'no reason');
  end if;

  select * into v_fail from public.fail_analysis_run(v_run, v_token, 'analysis_failed') t;
  if v_fail.accepted or v_fail.reason <> 'lease_lost' then
    raise exception 'a failure report behind an expired lease was accepted (%)',
      coalesce(v_fail.reason, 'no reason');
  end if;
end
$expiry$;

-- ---------------------------------------------------------------------------
-- 3. Reclaim uses the wall clock as well, so the stale attempt is recovered
--    and the work item is handed out again with its next attempt.
-- ---------------------------------------------------------------------------
do $reclaim$
declare
  v_worker uuid := '4f666666-6666-4666-8666-666666666666';
  v_p_run uuid := current_setting('oryveta.lc_p_run')::uuid;
  v_item_run uuid := current_setting('oryveta.lc_item_run')::uuid;
  v_run uuid := current_setting('oryveta.lc_run')::uuid;
  v_claim record; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_worker::text, true);
  select * into v_claim from public.claim_analysis_work(v_p_run, 300) t;
  if v_claim.run_id is null then
    raise exception 'the reclaim did not recover an attempt whose lease expired on the '
      'wall clock, so the work item stayed running with nobody holding it';
  end if;
  if v_claim.work_item_id <> v_item_run or v_claim.attempt <> 2 then
    raise exception 'the reclaimed work was handed out as attempt % of work item %',
      v_claim.attempt, v_claim.work_item_id;
  end if;
  if v_claim.lease_expires_at <= clock_timestamp() then
    raise exception 'the second claim handed out an already expired lease';
  end if;

  select count(*) into n from public.factory_runs r
   where r.id = v_run and r.status = 'failed' and r.error_code = 'lease_expired'
     and r.finished_at is not null;
  if n <> 1 then raise exception 'the stale attempt was not closed as lease_expired'; end if;
  select count(*) into n from public.factory_run_events e
   where e.run_id = v_run and e.kind = 'lease_expired';
  if n <> 1 then raise exception 'the reclaim recorded no lease_expired event'; end if;
end
$reclaim$;

-- ---------------------------------------------------------------------------
-- 4. Deleting a registration a surviving attempt still points at stays
--    refused. Only the table owner can even try: no client role holds DELETE
--    on public.project_workers, and revocation disables a registration rather
--    than removing it.
-- ---------------------------------------------------------------------------
reset role;
do $registration_restrict$
declare
  v_p_run uuid := current_setting('oryveta.lc_p_run')::uuid;
  v_state text; v_constraint text; n integer;
begin
  begin
    delete from public.project_workers k where k.project_id = v_p_run;
    set constraints all immediate;
    raise exception using errcode = 'triggered_data_change_violation',
      message = 'a worker registration was deleted while an attempt still '
                'references it, so run history can lose its worker identity';
  exception when foreign_key_violation then
    get stacked diagnostics v_state = returned_sqlstate, v_constraint = constraint_name;
    if v_constraint <> 'factory_runs_worker_registration_id_fkey' then
      raise exception 'the registration deletion was refused by % (%) instead of the '
        'attempt reference', coalesce(v_constraint,'an unnamed constraint'), v_state;
    end if;
  end;
  -- The refusal rolled that subtransaction back, so the registration is still
  -- here and its attempts still name it.
  select count(*) into n from public.project_workers k where k.project_id = v_p_run;
  if n <> 1 then raise exception 'the refused deletion did not leave the registration'; end if;
  select count(*) into n from public.factory_runs r
   where r.project_id = v_p_run and r.worker_registration_id is null;
  if n <> 0 then raise exception 'an attempt lost its worker registration reference'; end if;
end
$registration_restrict$;

-- ---------------------------------------------------------------------------
-- 5. The owner's own workspace deletion completes even though the workspace
--    carries a project, a worker registration, a work item, a finished attempt
--    and that attempt's event log. The control workspace, which has no runtime
--    history at all, deletes the same way.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $workspace_deletion$
declare
  v_owner uuid := '4a111111-1111-4111-8111-111111111111';
  v_ws_history uuid := current_setting('oryveta.lc_ws_history')::uuid;
  v_ws_control uuid := current_setting('oryveta.lc_ws_control')::uuid;
  v_run_history uuid := current_setting('oryveta.lc_run_history')::uuid;
  n integer;
begin
  perform set_config('request.jwt.claim.sub', v_owner::text, true);
  select count(*) into n from public.factory_run_events e where e.run_id = v_run_history;
  if n < 1 then raise exception 'the history attempt left no events to cascade'; end if;

  delete from public.workspaces w where w.id = v_ws_control;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the owner could not delete a workspace without history'; end if;

  delete from public.workspaces w where w.id = v_ws_history;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'the owner could not delete a workspace that carries terminal run history';
  end if;
  set constraints all immediate;
end
$workspace_deletion$;

-- The cascade is audited by the table owner, because an authenticated read of
-- a project that no longer exists is filtered by policy either way and would
-- prove nothing.
reset role;
do $workspace_deletion_audit$
declare
  v_ws_history uuid := current_setting('oryveta.lc_ws_history')::uuid;
  v_p_history uuid := current_setting('oryveta.lc_p_history')::uuid;
  v_item_history uuid := current_setting('oryveta.lc_item_history')::uuid;
  v_run_history uuid := current_setting('oryveta.lc_run_history')::uuid;
  n integer;
begin
  select count(*) into n from public.workspaces w where w.id = v_ws_history;
  if n <> 0 then raise exception 'the workspace survived its own deletion'; end if;
  select count(*) into n from public.projects p where p.id = v_p_history;
  if n <> 0 then raise exception 'the project outlived its workspace'; end if;
  select count(*) into n from public.project_workers k where k.project_id = v_p_history;
  if n <> 0 then raise exception 'the worker registration outlived its project'; end if;
  select count(*) into n from public.work_items w where w.id = v_item_history;
  if n <> 0 then raise exception 'the work item outlived its project'; end if;
  select count(*) into n from public.factory_runs r where r.id = v_run_history;
  if n <> 0 then raise exception 'the attempt outlived its work item'; end if;
  select count(*) into n from public.factory_run_events e where e.run_id = v_run_history;
  if n <> 0 then raise exception 'the event log outlived its attempt'; end if;
  select count(*) into n from private.factory_run_leases l where l.run_id = v_run_history;
  if n <> 0 then raise exception 'a fencing token outlived its attempt'; end if;
end
$workspace_deletion_audit$;

-- ---------------------------------------------------------------------------
-- 6. Deleting an account that is only the attribution of a retained terminal
--    record succeeds, and the record keeps its state and its timestamps.
--    These are table-owner DELETEs on auth.users, which is what the Auth admin
--    API performs when an account is removed.
-- ---------------------------------------------------------------------------
do $account_deletion$
declare
  v_owner uuid := '4a111111-1111-4111-8111-111111111111';
  v_invitee uuid := '4b222222-2222-4222-8222-222222222222';
  v_editor uuid := '4c333333-3333-4333-8333-333333333333';
  v_reader uuid := '4d444444-4444-4444-8444-444444444444';
  v_everything uuid := '4e555555-5555-4555-8555-555555555555';
  v_inv_invitee uuid := current_setting('oryveta.lc_inv_invitee')::uuid;
  v_inv_everything uuid := current_setting('oryveta.lc_inv_everything')::uuid;
  v_share_reader uuid := current_setting('oryveta.lc_share_reader')::uuid;
  v_share_everything uuid := current_setting('oryveta.lc_share_everything')::uuid;
  v_item_editor uuid := current_setting('oryveta.lc_item_editor')::uuid;
  v_item_everything uuid := current_setting('oryveta.lc_item_everything')::uuid;
  n integer;
begin
  delete from auth.users u where u.id = v_invitee;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the accepted email recipient was not deleted'; end if;

  delete from auth.users u where u.id = v_editor;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the cancelling editor was not deleted'; end if;

  delete from auth.users u where u.id = v_reader;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'the accepted chat-share recipient was not deleted'; end if;

  -- One account that is all three at once, in a single statement.
  delete from auth.users u where u.id = v_everything;
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'an account holding an accepted invitation, an accepted share and a '
      'colleague cancellation could not be deleted';
  end if;
  set constraints all immediate;

  select count(*) into n from public.project_invitations i
   where i.id in (v_inv_invitee, v_inv_everything)
     and i.status = 'accepted' and i.accepted_at is not null and i.accepted_by is null;
  if n <> 2 then
    raise exception 'the accepted invitations lost their state or their timestamp';
  end if;

  select count(*) into n from public.chat_shares s
   where s.id in (v_share_reader, v_share_everything)
     and s.status = 'accepted' and s.accepted_at is not null and s.accepted_by is null;
  if n <> 2 then raise exception 'the accepted shares lost their state or their timestamp'; end if;

  select count(*) into n from public.work_items w
   where w.id in (v_item_editor, v_item_everything)
     and w.status = 'cancelled' and w.cancel_requested_at is not null
     and w.cancelled_by is null and w.created_by = v_owner;
  if n <> 2 then
    raise exception 'the cancelled work items lost their state, their timestamp or '
      'their submitter';
  end if;

  -- The grants and audit rows those accounts held are gone with them.
  select count(*) into n from public.project_memberships m
   where m.user_id in (v_invitee, v_everything);
  if n <> 0 then raise exception 'a deleted account kept a project membership'; end if;
  select count(*) into n from public.workspace_memberships m
   where m.user_id in (v_editor, v_everything);
  if n <> 0 then raise exception 'a deleted account kept a workspace membership'; end if;
end
$account_deletion$;

-- ---------------------------------------------------------------------------
-- 7. The relaxation is exactly one step wide: a retained record may lose its
--    actor, never its state or its timestamp, and an attribution without its
--    timestamp stays impossible. The owner role writes directly, because these
--    states are unreachable through any RPC or policy.
-- ---------------------------------------------------------------------------
do $retained_invariants$
declare
  v_owner uuid := '4a111111-1111-4111-8111-111111111111';
  v_inv_invitee uuid := current_setting('oryveta.lc_inv_invitee')::uuid;
  v_share_reader uuid := current_setting('oryveta.lc_share_reader')::uuid;
  v_item_editor uuid := current_setting('oryveta.lc_item_editor')::uuid;
  ok boolean;
begin
  ok := false;
  begin
    update public.project_invitations i set accepted_at = null where i.id = v_inv_invitee;
  exception when check_violation then ok := true; end;
  if not ok then raise exception 'an accepted invitation was allowed to lose its timestamp'; end if;

  ok := false;
  begin
    update public.chat_shares s set accepted_at = null where s.id = v_share_reader;
  exception when check_violation then ok := true; end;
  if not ok then raise exception 'an accepted share was allowed to lose its timestamp'; end if;

  ok := false;
  begin
    update public.work_items w set cancel_requested_at = null, cancelled_by = v_owner
     where w.id = v_item_editor;
  exception when check_violation then ok := true; end;
  if not ok then
    raise exception 'a cancellation attribution was allowed without its timestamp';
  end if;

  ok := false;
  begin
    update public.project_invitations i
       set status = 'pending', accepted_at = now() where i.id = v_inv_invitee;
  exception when check_violation then ok := true; end;
  if not ok then
    raise exception 'a non-accepted invitation was allowed to carry an acceptance timestamp';
  end if;

  ok := false;
  begin
    update public.chat_shares s
       set status = 'pending', accepted_at = now() where s.id = v_share_reader;
  exception when check_violation then ok := true; end;
  if not ok then
    raise exception 'a pending share was allowed to carry an acceptance timestamp';
  end if;
end
$retained_invariants$;

-- ---------------------------------------------------------------------------
-- 8. A cleared attribution grants nothing. A new account that verifies the
--    same address as a deleted recipient cannot replay that acceptance into a
--    membership or into conversation access: the acceptance is on record and
--    inert, which is what accept_project_invitation's replay rule and the chat
--    read helpers already require.
-- ---------------------------------------------------------------------------
insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,
   raw_app_meta_data,created_at,updated_at)
values
('4b999999-9999-4999-8999-999999999999','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-invitee@example.invalid','',now(),'{}'::jsonb,now(),now()),
('4d999999-9999-4999-8999-999999999999','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-lifecycle-reader@example.invalid','',now(),'{}'::jsonb,now(),now());

set local role authenticated;
do $no_replay$
declare
  v_successor_invitee uuid := '4b999999-9999-4999-8999-999999999999';
  v_successor_reader uuid := '4d999999-9999-4999-8999-999999999999';
  v_inv_invitee uuid := current_setting('oryveta.lc_inv_invitee')::uuid;
  v_p_invite uuid := current_setting('oryveta.lc_p_invite')::uuid;
  v_chat uuid := current_setting('oryveta.lc_chat')::uuid;
  v_share_reader uuid := current_setting('oryveta.lc_share_reader')::uuid;
  ok boolean; v_message text; n integer;
begin
  perform set_config('request.jwt.claim.sub', v_successor_invitee::text, true);
  ok := false; v_message := null;
  begin perform 1 from public.accept_project_invitation(v_inv_invitee) t;
  exception when others then ok := true; v_message := sqlerrm; end;
  if not ok or v_message <> 'invitation already accepted' then
    raise exception 'a successor account replayed a cleared acceptance (%)',
      coalesce(v_message, 'no error');
  end if;
  select count(*) into n from public.project_memberships m
   where m.project_id = v_p_invite and m.user_id = v_successor_invitee;
  if n <> 0 then raise exception 'a successor account was granted project membership'; end if;
  select count(*) into n from public.project_invitations i where i.id = v_inv_invitee;
  if n <> 0 then
    raise exception 'a successor account can read the invitation it did not accept';
  end if;

  perform set_config('request.jwt.claim.sub', v_successor_reader::text, true);
  if private.can_read_chat(v_chat) then
    raise exception 'a cleared share attribution granted conversation read access';
  end if;
  if private.can_write_chat(v_chat) then
    raise exception 'a cleared share attribution granted conversation write access';
  end if;
  update public.chat_shares s
     set status = 'accepted', accepted_by = v_successor_reader, accepted_at = now()
   where s.id = v_share_reader;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'a successor account re-accepted a consumed share'; end if;
  select count(*) into n from public.chat_messages m where m.chat_id = v_chat;
  if n <> 0 then raise exception 'a successor account can read the conversation'; end if;
end
$no_replay$;

reset role;
rollback;
