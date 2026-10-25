-- Retained terminal attribution, and lease deadlines measured on the wall
-- clock instead of the transaction timestamp.
--
-- Apply AFTER supabase/schema.sql,
-- supabase/migrations/private_chats_and_explicit_sharing.sql,
-- supabase/migrations/projects_and_project_membership.sql and
-- supabase/migrations/durable_factory_runtime.sql, in that order. An existing
-- installation is repaired by applying this file alone; a fresh deployment
-- reaches the same state by applying all five in order. This repair can be
-- re-applied; do not assume the earlier initial-setup files are repeatable.
--
-- Dedicated Oryveta project only. This file re-owns three constraints and five
-- functions the files above created. It creates no table, column, policy or
-- privilege, changes no RPC argument list or return shape, and relaxes no
-- authorization or source-pinning check.
--
-- Two defects, both reproduced against an isolated local stack before this was
-- written.
--
-- 1. Deleting an ordinary account failed with SQLSTATE 23514 whenever that
--    account was only the *attribution* of a record the product keeps on
--    purpose. Three retained-record constraints demanded an attribution that
--    the matching foreign key is declared to clear:
--      * public.chat_shares.accepted_by          ON DELETE SET NULL
--      * public.project_invitations.accepted_by   ON DELETE SET NULL
--      * public.work_items.cancelled_by           ON DELETE SET NULL
--    An email-addressed share or invitation has no target_user_id cascade to
--    remove the row, and a work item cancelled by a colleague survives on the
--    submitter's created_by, so each clearing produced a row its own CHECK
--    evaluated to FALSE. Observed as: accepted email recipient delete ->
--    23514 on project_invitations_check1; cancelling editor delete -> 23514 on
--    work_items_check1; accepted email chat-share recipient delete -> 23514 on
--    chat_shares_check1. Offboarding one account therefore required repairing
--    or deleting unrelated project records first.
--
--    The repair keeps the state and the timestamps and allows only the actor
--    reference to become unknown. 'accepted' still requires accepted_at, a
--    non-accepted row still carries neither field, and a cancellation
--    attribution still requires its timestamp. Who may accept an invitation or
--    a share and who may cancel work is decided by the RPCs and policies in
--    the files above, which are untouched: they always write the acting
--    account, never NULL. An accepted row whose attribution has been cleared
--    is inert rather than re-usable - public.accept_project_invitation
--    compares accepted_by to the caller through coalesce(..., false) and so
--    refuses it, private.can_read_chat and private.can_write_chat match
--    accepted_by against auth.uid() and so grant nothing, and no UPDATE
--    policy can move such a row back to 'pending'.
--
-- 2. Lease deadlines and lease-expiry decisions used now(), which is fixed at
--    transaction start - before the registration and work-item locks these
--    calls wait on. A wait longer than the requested lease committed an
--    attempt whose lease was already expired. Reproduced with two sessions: an
--    open public.register_project_worker upsert held the registration row for
--    20s while public.claim_analysis_work(project, 15) waited on its FOR
--    SHARE; the claim returned an attempt with 5.1 seconds of lease *already
--    spent*, its first heartbeat answered lease_lost, and the work item was
--    left at attempts 1 of 2 with nothing to show for it.
--
--    One rule now applies throughout the runtime: a deadline, and every
--    comparison against a deadline, is taken from clock_timestamp(), which is
--    read after the locks have been acquired, while a timestamp that records
--    when a transaction happened keeps now(), so all rows one transaction
--    writes still agree with each other. That is why started_at, heartbeat_at,
--    finished_at and the event log are unchanged here and only
--    lease_expires_at and the lease comparisons move.

begin;

-- ---------------------------------------------------------------------------
-- 1. Retained terminal records tolerate a deleted actor
-- ---------------------------------------------------------------------------

-- The three originals were declared without names, so PostgreSQL generated
-- them deterministically from the fixed table definitions in the files above.
-- The assertion after the replacements fails loudly if any deployment still
-- carries one of the old predicates under some other name, instead of silently
-- leaving the defect in place.
alter table public.chat_shares drop constraint if exists chat_shares_check1;
alter table public.chat_shares
  drop constraint if exists chat_shares_accepted_state_check;
alter table public.chat_shares add constraint chat_shares_accepted_state_check
  check((status='pending' and accepted_by is null and accepted_at is null)
     or (status='accepted' and accepted_at is not null));

alter table public.project_invitations drop constraint if exists project_invitations_check1;
alter table public.project_invitations
  drop constraint if exists project_invitations_accepted_state_check;
alter table public.project_invitations
  add constraint project_invitations_accepted_state_check
  check((status='accepted' and accepted_at is not null)
     or (status<>'accepted' and accepted_by is null and accepted_at is null));

-- Attribution without its timestamp stays impossible; a timestamp whose actor
-- has been deleted is now allowed.
alter table public.work_items drop constraint if exists work_items_check1;
alter table public.work_items
  drop constraint if exists work_items_cancellation_attribution_check;
alter table public.work_items add constraint work_items_cancellation_attribution_check
  check(cancelled_by is null or cancel_requested_at is not null);

do $assert_relaxed$
declare
  v_target record;
  v_survivor text;
begin
  for v_target in
    select *
      from (values
        ('public.chat_shares', '(accepted_by IS NOT NULL)'),
        ('public.project_invitations', '(accepted_by IS NOT NULL)'),
        ('public.work_items', '((cancel_requested_at IS NULL) = (cancelled_by IS NULL))')
      ) as t(relation, predicate)
  loop
    select c.conname into v_survivor
      from pg_catalog.pg_constraint c
     where c.conrelid = v_target.relation::regclass
       and c.contype = 'c'
       and strpos(pg_catalog.pg_get_constraintdef(c.oid), v_target.predicate) > 0
     limit 1;
    if v_survivor is not null then
      raise exception 'check constraint % on % still demands the attribution this '
        'migration clears; drop that constraint by name and re-apply this file',
        v_survivor, v_target.relation;
    end if;
  end loop;
end
$assert_relaxed$;

-- ---------------------------------------------------------------------------
-- 2. Lease deadlines and lease expiry on the wall clock
-- ---------------------------------------------------------------------------

-- Reclaim: a run whose lease expired is terminated and its work item either
-- becomes claimable again or fails terminally. Called inside claim so recovery
-- needs no separate scheduler, cron job or privileged process.
--
-- Locks are always taken work item first, then run, matching cancel_work_item
-- and revoke_project_worker. A reclaim racing a cancellation therefore queues
-- behind it instead of deadlocking, and the re-checked UPDATE below makes a
-- lost race a no-op rather than a double transition.
--
-- Both expiry comparisons read clock_timestamp(): the scan uses the time it
-- actually runs, and the re-check after the work item lock uses the time that
-- lock was obtained. A reclaim that waited is therefore deciding on elapsed
-- wall-clock time, not on the moment its transaction began.
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
    perform private.record_run_event(v_run.id, 'lease_expired', null,
      'lease expired without a result');
    perform private.settle_work_item_after_attempt(v_run.work_item_id, v_run.id, 'lease_expired');
    v_count := v_count + 1;
  end loop;
  return v_count;
end
$$;
revoke all on function private.expire_stale_runs(uuid) from public, anon, authenticated;

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
  -- leaves nothing to find here. This wait is unbounded, which is why the
  -- lease below is not measured from the start of this transaction.
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
  -- The wall clock *after* the registration and reclaim locks above, not
  -- now(). now() is the transaction timestamp, so a claim that spent longer
  -- than its own lease waiting for those locks used to hand out an attempt
  -- whose deadline had already passed: the worker's first heartbeat was
  -- refused with lease_lost and the attempt below was spent for nothing.
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

commit;
