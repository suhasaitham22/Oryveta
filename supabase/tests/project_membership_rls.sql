-- Real authorization regression for hosted projects, project membership and
-- project-associated private sessions.
--
-- Run order (psql, ON_ERROR_STOP=1, on a superuser/owner connection to a
-- Supabase stack whose auth schema and anon/authenticated roles already exist
-- - the local `supabase start` stack or a dedicated development project):
--   1. supabase/schema.sql
--   2. supabase/migrations/private_chats_and_explicit_sharing.sql
--   3. supabase/migrations/projects_and_project_membership.sql
--   4. this file
--
-- Requires SQL-editor/owner privileges and intentionally creates synthetic
-- auth.users. Everything here ROLLS BACK, even on success, so no fixture row
-- survives the run. Never run it on an unrelated project. It exercises the
-- real policies, grants and RPCs as the anon and authenticated roles and mocks
-- nothing. Real OAuth-account browser tests remain a separate gate.
begin;

insert into auth.users
  (id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,created_at,updated_at)
values
('0a111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-proj-test-a@example.invalid','',now(),now(),now()),
('0b222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-proj-test-b@example.invalid','',now(),now(),now()),
('0c333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-proj-test-c@example.invalid','',now(),now(),now()),
-- Deliberately unconfirmed: an unverified address must never accept an
-- email-addressed invitation.
('0d444444-4444-4444-8444-444444444444','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-proj-test-d@example.invalid','',null,now(),now());

-- ---------------------------------------------------------------------------
-- Anonymous callers. No ids are needed: the privilege denial must happen
-- before any row or argument is considered.
-- ---------------------------------------------------------------------------
set local role anon;
do $anon$
declare
  n integer;
  ok boolean;
begin
  ok := false;
  begin select count(*) into n from public.projects;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.projects'; end if;

  ok := false;
  begin select count(*) into n from public.project_memberships;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.project_memberships'; end if;

  ok := false;
  begin select count(*) into n from public.project_invitations;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.project_invitations'; end if;

  ok := false;
  begin select count(*) into n from public.project_audit_events;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can read public.project_audit_events'; end if;

  ok := false;
  begin perform 1 from public.list_project_invitations();
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute list_project_invitations'; end if;

  ok := false;
  begin perform 1 from public.create_project(gen_random_uuid(),'Anon','x','new');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute create_project'; end if;

  ok := false;
  begin perform 1 from public.accept_project_invitation(gen_random_uuid());
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute accept_project_invitation'; end if;

  ok := false;
  begin perform public.revoke_project_member(gen_random_uuid(),gen_random_uuid());
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute revoke_project_member'; end if;

  ok := false;
  begin perform public.cancel_project_invitation(gen_random_uuid());
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute cancel_project_invitation'; end if;

  ok := false;
  begin perform 1 from public.invite_project_member(gen_random_uuid(),'x@example.invalid','viewer');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute invite_project_member'; end if;

  ok := false;
  begin perform 1 from public.update_project(gen_random_uuid(),'x','y');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'anon can execute update_project'; end if;
end
$anon$;

-- ---------------------------------------------------------------------------
-- Authenticated actors. The acting principal is switched with the same JWT
-- claim Supabase uses, so auth.uid() drives every policy under test.
-- ---------------------------------------------------------------------------
set local role authenticated;
do $main$
declare
  a uuid := '0a111111-1111-4111-8111-111111111111';
  b uuid := '0b222222-2222-4222-8222-222222222222';
  c uuid := '0c333333-3333-4333-8333-333333333333';
  d uuid := '0d444444-4444-4444-8444-444444444444';
  email_a text := 'oryveta-proj-test-a@example.invalid';
  email_b text := 'oryveta-proj-test-b@example.invalid';
  email_d text := 'oryveta-proj-test-d@example.invalid';
  ws_a uuid; ws_b uuid; p1 uuid; p2 uuid;
  inv_b uuid; inv_b2 uuid; inv_c uuid; inv_d uuid; inv_d2 uuid;
  chat_b uuid;
  v_id uuid; v_status text; v_role text; v_name text;
  n integer; ok boolean;
begin
  -- -- creation requires real workspace authority -----------------------------
  perform set_config('request.jwt.claim.sub',a::text,true);
  insert into public.workspaces(name,slug,created_by)
  values ('Oryveta Projects A','proj-test-a',a) returning id into ws_a;

  select t.id into p1 from public.create_project(
    ws_a,'Alpha brief','Rebuild onboarding','new') t;
  if p1 is null then raise exception 'create_project returned no row'; end if;
  select count(*) into n from public.project_memberships m
   where m.project_id=p1 and m.user_id=a and m.role='owner';
  if n<>1 then raise exception 'creator owner membership was not provisioned'; end if;
  select count(*) into n from public.projects p where p.id=p1;
  if n<>1 then raise exception 'creator cannot read their own project'; end if;

  ok := false;
  begin perform 1 from public.create_project(ws_a,'Bad kind','x','sideways');
  exception when others then ok := true; end;
  if not ok then raise exception 'invalid project kind was accepted'; end if;

  ok := false;
  begin perform 1 from public.create_project(ws_a,'A','x','new');
  exception when others then ok := true; end;
  if not ok then raise exception 'out-of-bounds project name was accepted'; end if;

  ok := false;
  begin perform 1 from public.create_project(
    ws_a,'Bad source','x','evolve','javascript:alert(1)');
  exception when others then ok := true; end;
  if not ok then raise exception 'non-http project source was accepted'; end if;

  -- Bounds agreed with the frontend: name 2-80, brief <=2000, source <=500.
  ok := false;
  begin perform 1 from public.create_project(ws_a,repeat('x',81),'x','new');
  exception when others then ok := true; end;
  if not ok then raise exception 'over-long project name was accepted'; end if;

  ok := false;
  begin perform 1 from public.create_project(ws_a,'Long brief',repeat('x',2001),'new');
  exception when others then ok := true; end;
  if not ok then raise exception 'over-long project brief was accepted'; end if;

  ok := false;
  begin perform 1 from public.create_project(
    ws_a,'Long source','x','evolve','https://example.invalid/'||repeat('a',500));
  exception when others then ok := true; end;
  if not ok then raise exception 'over-long project source was accepted'; end if;

  -- An evolve project with a real https source is accepted and readable.
  select t.id into v_id from public.create_project(
    ws_a,'Evolve brief','Analyse an existing repository','evolve',
    'https://example.invalid/repo.git') t;
  if v_id is null then raise exception 'valid evolve project was rejected'; end if;
  select count(*) into n from public.projects p
   where p.id=v_id and p.kind='evolve' and p.source_url='https://example.invalid/repo.git';
  if n<>1 then raise exception 'evolve project was not stored as given'; end if;

  -- -- a second tenant that must stay invisible -------------------------------
  perform set_config('request.jwt.claim.sub',b::text,true);
  ok := false;
  begin perform 1 from public.create_project(ws_a,'Intruder','x','new');
  exception when others then ok := true; end;
  if not ok then raise exception 'non-member created a project in another workspace'; end if;

  select count(*) into n from public.projects p where p.id=p1;
  if n<>0 then raise exception 'cross-tenant project read'; end if;
  select count(*) into n from public.project_memberships m where m.project_id=p1;
  if n<>0 then raise exception 'cross-tenant project membership read'; end if;
  select count(*) into n from public.project_invitations i where i.project_id=p1;
  if n<>0 then raise exception 'cross-tenant invitation read'; end if;
  select count(*) into n from public.project_audit_events e where e.project_id=p1;
  if n<>0 then raise exception 'cross-tenant audit read'; end if;

  ok := false;
  begin perform 1 from public.update_project(p1,'Hijacked','x');
  exception when others then ok := true; end;
  if not ok then raise exception 'non-member update_project was allowed'; end if;

  ok := false;
  begin update public.projects set name='Hijacked' where id=p1;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'direct project UPDATE privilege is exposed'; end if;

  ok := false;
  begin insert into public.project_memberships(project_id,user_id,role)
        values (p1,b,'owner');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'direct membership INSERT privilege is exposed'; end if;

  ok := false;
  begin delete from public.project_invitations where project_id=p1;
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'direct invitation DELETE privilege is exposed'; end if;

  insert into public.workspaces(name,slug,created_by)
  values ('Oryveta Projects B','proj-test-b',b) returning id into ws_b;
  select t.id into p2 from public.create_project(
    ws_b,'Beta brief','Second tenant','new') t;

  -- -- invitation grants nothing until accepted -------------------------------
  perform set_config('request.jwt.claim.sub',a::text,true);
  select t.id, t.status into inv_b, v_status
    from public.invite_project_member(p1,email_b,'engineer') t;
  if inv_b is null or v_status<>'pending' then
    raise exception 'invitation was not created pending';
  end if;

  ok := false;
  begin perform 1 from public.invite_project_member(p1,'someone@example.invalid','owner');
  exception when others then ok := true; end;
  if not ok then raise exception 'owner role was grantable by invitation'; end if;

  ok := false;
  begin perform 1 from public.invite_project_member(p1,email_a,'admin');
  exception when others then ok := true; end;
  if not ok then raise exception 'self invitation was accepted'; end if;

  ok := false;
  begin perform 1 from public.invite_project_member(p1,'not-an-address','viewer');
  exception when others then ok := true; end;
  if not ok then raise exception 'malformed recipient was accepted'; end if;

  -- A repeated pending invitation is reused, never duplicated.
  select t.id into v_id from public.invite_project_member(p1,email_b,'reviewer') t;
  if v_id<>inv_b then raise exception 'repeat invitation created a second pending row'; end if;
  select count(*) into n from public.project_invitations i
   where i.project_id=p1 and i.recipient_email=email_b;
  if n<>1 then raise exception 'duplicate pending invitation rows exist'; end if;
  select t.id into v_id from public.invite_project_member(p1,email_b,'engineer') t;
  if v_id<>inv_b then raise exception 'repeat invitation created a second pending row'; end if;

  perform set_config('request.jwt.claim.sub',b::text,true);
  select count(*) into n from public.projects p where p.id=p1;
  if n<>0 then raise exception 'pending invitation granted project read'; end if;
  select count(*) into n from public.project_invitations i where i.project_id=p1;
  if n<>0 then raise exception 'recipient reads the invitation table directly'; end if;
  select count(*) into n from public.list_project_invitations() t where t.project_id=p1;
  if n<>1 then raise exception 'recipient cannot see their own pending invitation'; end if;
  select t.project_name, t.role into v_name, v_role
    from public.list_project_invitations() t where t.project_id=p1;
  if v_name<>'Alpha brief' or v_role<>'engineer' then
    raise exception 'invitation listing exposes the wrong payload';
  end if;

  perform set_config('request.jwt.claim.sub',c::text,true);
  select count(*) into n from public.list_project_invitations() t;
  if n<>0 then raise exception 'invitation leaked to an unrelated user'; end if;
  ok := false;
  begin perform 1 from public.accept_project_invitation(inv_b);
  exception when others then ok := true; end;
  if not ok then raise exception 'an unintended recipient accepted an invitation'; end if;

  -- -- acceptance grants exactly the project, not the workspace ---------------
  perform set_config('request.jwt.claim.sub',b::text,true);
  select t.project_id into v_id from public.accept_project_invitation(inv_b) t;
  if v_id<>p1 then raise exception 'accept did not return the project'; end if;
  select count(*) into n from public.projects p where p.id=p1;
  if n<>1 then raise exception 'accepted member cannot read the project'; end if;
  select m.role into v_role from public.project_memberships m
   where m.project_id=p1 and m.user_id=b;
  if v_role<>'engineer' then raise exception 'accepted membership has the wrong role'; end if;
  select count(*) into n from public.workspaces w where w.id=ws_a;
  if n<>0 then raise exception 'project invitation leaked workspace read access'; end if;
  select count(*) into n from public.workspace_memberships m
   where m.workspace_id=ws_a and m.user_id=b;
  if n<>0 then raise exception 'project invitation created workspace membership'; end if;

  select t.name into v_name
    from public.update_project(p1,'Alpha brief v2','Updated by the engineer') t;
  if v_name<>'Alpha brief v2' then raise exception 'engineer edit was rejected'; end if;

  ok := false;
  begin perform 1 from public.invite_project_member(p1,'extra@example.invalid','viewer');
  exception when others then ok := true; end;
  if not ok then raise exception 'engineer could invite project members'; end if;

  ok := false;
  begin perform public.revoke_project_member(p1,a);
  exception when others then ok := true; end;
  if not ok then raise exception 'engineer could revoke project members'; end if;

  select count(*) into n from public.project_invitations i where i.project_id=p1;
  if n<>0 then raise exception 'engineer reads invitation recipients'; end if;
  select count(*) into n from public.project_audit_events e where e.project_id=p1;
  if n<>0 then raise exception 'engineer reads the project audit trail'; end if;

  -- -- project association never shares a private session --------------------
  insert into public.chats(owner_id,workspace_id,project_id,title)
  values (b,null,p1,'Beta session') returning id into chat_b;
  insert into public.chat_messages(chat_id,author_id,role,content)
  values (chat_b,b,'user','a private note');

  ok := false;
  begin insert into public.chats(owner_id,workspace_id,project_id,title)
        values (b,ws_a,p1,'Workspace claim');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'project-only member claimed a workspace chat'; end if;

  ok := false;
  begin insert into public.chats(owner_id,workspace_id,project_id,title)
        values (b,ws_b,p1,'Mismatched pairing');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'cross-workspace project association was accepted'; end if;

  perform set_config('request.jwt.claim.sub',a::text,true);
  select count(*) into n from public.chats ch where ch.id=chat_b;
  if n<>0 then raise exception 'project ownership leaked a private conversation'; end if;
  select count(*) into n from public.chat_messages cm where cm.chat_id=chat_b;
  if n<>0 then raise exception 'project ownership leaked conversation messages'; end if;

  ok := false;
  begin insert into public.chats(owner_id,workspace_id,project_id,title)
        values (a,ws_a,p2,'Foreign project');
  exception when insufficient_privilege then ok := true; end;
  if not ok then raise exception 'chat was associated with an unreadable project'; end if;

  insert into public.chats(owner_id,workspace_id,project_id,title)
  values (a,ws_a,p1,'Owner session');
  if has_column_privilege('authenticated','public.chats','project_id','update') then
    raise exception 'clients can rewrite a chat project association';
  end if;

  -- -- alias invitations and read-only roles ---------------------------------
  perform set_config('request.jwt.claim.sub',c::text,true);
  insert into public.user_aliases(user_id,alias) values (c,'oryveta_c');

  perform set_config('request.jwt.claim.sub',a::text,true);
  ok := false;
  begin perform 1 from public.invite_project_member(p1,'@missing_alias','viewer');
  exception when others then ok := true; end;
  if not ok then raise exception 'unknown alias invitation was accepted'; end if;
  select t.id into inv_c from public.invite_project_member(p1,'@oryveta_c','viewer') t;

  -- Reassigning a mutable alias must not amend the old immutable recipient's
  -- offer. In particular, a viewer offer must not become an admin grant.
  perform set_config('request.jwt.claim.sub',c::text,true);
  update public.user_aliases set alias='oryveta_c_new' where user_id=c;
  perform set_config('request.jwt.claim.sub',d::text,true);
  insert into public.user_aliases(user_id,alias) values (d,'oryveta_c');
  ok := false;
  begin perform 1 from public.accept_project_invitation(inv_c);
  exception when others then ok := true; end;
  if not ok then raise exception 'new alias owner accepted the old invitation'; end if;
  perform set_config('request.jwt.claim.sub',a::text,true);
  ok := false;
  begin perform 1 from public.invite_project_member(p1,'@oryveta_c','admin');
  exception when others then ok := true; end;
  if not ok then raise exception 'alias reassignment upgraded the former recipient'; end if;
  select i.role into v_role from public.project_invitations i where i.id=inv_c;
  if v_role<>'viewer' then raise exception 'old alias offer changed privilege'; end if;

  perform set_config('request.jwt.claim.sub',c::text,true);
  select t.project_id into v_id from public.accept_project_invitation(inv_c) t;
  if v_id<>p1 then raise exception 'alias invitation acceptance failed'; end if;
  select count(*) into n from public.projects p where p.id=p1;
  if n<>1 then raise exception 'viewer cannot read the project'; end if;
  ok := false;
  begin perform 1 from public.update_project(p1,'Viewer edit','x');
  exception when others then ok := true; end;
  if not ok then raise exception 'viewer could edit the project'; end if;
  select count(*) into n from public.chats ch where ch.project_id=p1;
  if n<>0 then raise exception 'viewer read conversations of their project'; end if;

  perform set_config('request.jwt.claim.sub',a::text,true);
  ok := false;
  begin perform 1 from public.invite_project_member(p1,'@oryveta_c_new','admin');
  exception when others then ok := true; end;
  if not ok then raise exception 'an existing member was re-invited'; end if;

  -- -- owner protection, revocation and replay -------------------------------
  ok := false;
  begin perform public.revoke_project_member(p1,a);
  exception when others then ok := true; end;
  if not ok then raise exception 'the project owner was removable'; end if;
  select count(*) into n from public.project_memberships m
   where m.project_id=p1 and m.user_id=a and m.role='owner';
  if n<>1 then raise exception 'owner membership was disturbed'; end if;

  perform public.revoke_project_member(p1,b);
  select count(*) into n from public.project_memberships m
   where m.project_id=p1 and m.user_id=b;
  if n<>0 then raise exception 'revoke did not remove the grant'; end if;

  perform set_config('request.jwt.claim.sub',b::text,true);
  select count(*) into n from public.projects p where p.id=p1;
  if n<>0 then raise exception 'revoked member still reads the project'; end if;
  -- Replay of the already-accepted invitation is deterministic and inert.
  select t.project_id into v_id from public.accept_project_invitation(inv_b) t;
  if v_id<>p1 then raise exception 'accept replay changed its answer'; end if;
  select count(*) into n from public.projects p where p.id=p1;
  if n<>0 then raise exception 'invitation replay restored project access'; end if;
  ok := false;
  begin perform 1 from public.update_project(p1,'After revoke','x');
  exception when others then ok := true; end;
  if not ok then raise exception 'revoked member could still edit the project'; end if;
  select count(*) into n from public.chats ch where ch.id=chat_b;
  if n<>1 then raise exception 'revocation destroyed the member own conversation'; end if;

  perform set_config('request.jwt.claim.sub',a::text,true);
  select count(*) into n from public.project_memberships m
   where m.project_id=p1 and m.user_id=b;
  if n<>0 then raise exception 'invitation replay recreated a revoked membership'; end if;

  -- -- cancellation ----------------------------------------------------------
  select t.id into inv_b2 from public.invite_project_member(p1,email_b,'viewer') t;
  if inv_b2=inv_b then raise exception 'an accepted invitation was reused as pending'; end if;
  perform public.cancel_project_invitation(inv_b2);
  select i.status into v_status from public.project_invitations i where i.id=inv_b2;
  if v_status<>'cancelled' then raise exception 'cancel did not change the status'; end if;

  perform set_config('request.jwt.claim.sub',b::text,true);
  select count(*) into n from public.list_project_invitations() t;
  if n<>0 then raise exception 'a cancelled invitation is still listed'; end if;
  ok := false;
  begin perform 1 from public.accept_project_invitation(inv_b2);
  exception when others then ok := true; end;
  if not ok then raise exception 'a cancelled invitation was still acceptable'; end if;
  select count(*) into n from public.projects p where p.id=p1;
  if n<>0 then raise exception 'a cancelled invitation granted access'; end if;

  -- -- unverified recipient and non-admin cancellation ------------------------
  perform set_config('request.jwt.claim.sub',a::text,true);
  select t.id into inv_d from public.invite_project_member(p1,email_d,'reviewer') t;

  perform set_config('request.jwt.claim.sub',d::text,true);
  select count(*) into n from public.list_project_invitations() t;
  if n<>0 then raise exception 'an unverified address listed an invitation'; end if;
  ok := false;
  begin perform 1 from public.accept_project_invitation(inv_d);
  exception when others then ok := true; end;
  if not ok then raise exception 'an unverified address accepted an invitation'; end if;

  perform set_config('request.jwt.claim.sub',c::text,true);
  ok := false;
  begin perform public.cancel_project_invitation(inv_d);
  exception when others then ok := true; end;
  if not ok then raise exception 'a viewer cancelled an invitation'; end if;

  perform set_config('request.jwt.claim.sub',a::text,true);
  perform public.cancel_project_invitation(inv_d);
  -- A cancelled recipient can be invited again; uniqueness covers pending only.
  select t.id into inv_d2 from public.invite_project_member(p1,email_d,'viewer') t;
  if inv_d2=inv_d then raise exception 'a cancelled invitation row was reused'; end if;

  -- -- audit trail -----------------------------------------------------------
  select count(*) into n from public.project_audit_events e
   where e.project_id=p1 and e.action='member_revoked' and e.subject_user_id=b;
  if n<>1 then raise exception 'revocation was not recorded'; end if;
  -- Exactly the two genuine acceptances: the replay above wrote nothing.
  select count(*) into n from public.project_audit_events e
   where e.project_id=p1 and e.action='invitation_accepted';
  if n<>2 then raise exception 'acceptances were not recorded exactly once'; end if;
  select count(*) into n from public.project_audit_events e
   where e.project_id=p1 and e.action='invitation_cancelled';
  if n<>2 then raise exception 'cancellations were not recorded'; end if;

  -- -- grants and function hardening fail closed ------------------------------
  select count(*) into n from (values
    ('public.projects'),('public.project_memberships'),
    ('public.project_invitations'),('public.project_audit_events')) as t(rel)
   where has_table_privilege('authenticated',t.rel,'insert')
      or has_table_privilege('authenticated',t.rel,'update')
      or has_table_privilege('authenticated',t.rel,'delete')
      or has_table_privilege('anon',t.rel,'select')
      or has_table_privilege('anon',t.rel,'insert')
      or has_table_privilege('anon',t.rel,'update')
      or has_table_privilege('anon',t.rel,'delete');
  if n<>0 then raise exception 'project tables expose a write or anonymous privilege'; end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid=p.pronamespace
   where ns.nspname='public'
     and p.proname in ('create_project','update_project','invite_project_member',
       'list_project_invitations','accept_project_invitation',
       'revoke_project_member','cancel_project_invitation');
  if n<>7 then raise exception 'expected exactly seven project RPCs'; end if;

  select count(*) into n from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace ns on ns.oid=p.pronamespace
   where ns.nspname in ('public','private')
     and p.proname in ('create_project','update_project','invite_project_member',
       'list_project_invitations','accept_project_invitation',
       'revoke_project_member','cancel_project_invitation',
       'project_role','can_read_project','is_project_admin',
       'can_attach_chat_to_project')
     and (not p.prosecdef
       or p.proconfig is null
       -- An empty search_path is stored either bare or quoted, never as a
       -- schema list such as search_path=public.
       or not (p.proconfig && array['search_path=','search_path=""'])
       or has_function_privilege('anon',p.oid,'execute'));
  if n<>0 then
    raise exception 'a project function is not a hardened definer or is anon-executable';
  end if;
end
$main$;

rollback;
