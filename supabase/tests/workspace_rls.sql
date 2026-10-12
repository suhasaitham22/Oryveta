-- Transactional RLS regression for a DEDICATED DEVELOPMENT or controlled test project.
-- Requires SQL-editor/owner privileges and intentionally creates synthetic auth.users.
-- This test ROLLS BACK all inserts and updates, even on success. Never run on
-- an unrelated project. Real OAuth-account browser tests remain a separate gate.
begin;
insert into auth.users (id,instance_id,aud,role,email,encrypted_password,created_at,updated_at)
values
('11111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-rls-test-a@example.invalid','',now(),now()),
('22222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000','authenticated','authenticated','oryveta-rls-test-b@example.invalid','',now(),now());
set local role authenticated;
do $test$
declare
 a uuid := '11111111-1111-4111-8111-111111111111';
 b uuid := '22222222-2222-4222-8222-222222222222';
 aid uuid; bid uuid; n integer;
begin
 perform set_config('request.jwt.claim.sub',a::text,true);
 insert into public.workspaces(name,slug,created_by)
 values ('Oryveta Test A','isolation-test-a',a) returning id into aid;
 select count(*) into n from public.workspace_memberships
  where workspace_id=aid and user_id=a and role='owner';
 if n<>1 then raise exception 'Owner membership not provisioned'; end if;
 perform set_config('request.jwt.claim.sub',b::text,true);
 select count(*) into n from public.workspaces where id=aid;
 if n<>0 then raise exception 'Cross-tenant workspace read'; end if;
 select count(*) into n from public.workspace_memberships where workspace_id=aid;
 if n<>0 then raise exception 'Cross-tenant membership read'; end if;
 update public.workspaces set name='Unauthorized' where id=aid;
 get diagnostics n = row_count;
 if n<>0 then raise exception 'Cross-tenant workspace update'; end if;
 delete from public.workspaces where id=aid;
 get diagnostics n = row_count;
 if n<>0 then raise exception 'Cross-tenant workspace delete'; end if;
 insert into public.workspaces(name,slug,created_by)
 values ('Oryveta Test B','isolation-test-b',b) returning id into bid;
 select count(*) into n from public.workspaces;
 if n<>1 then raise exception 'Cross-tenant workspace listing'; end if;
 if has_table_privilege('authenticated','public.workspace_memberships','insert') or
    has_table_privilege('authenticated','public.workspace_memberships','update') or
    has_table_privilege('authenticated','public.workspace_memberships','delete')
 then raise exception 'Membership mutation privilege exposed'; end if;
 perform set_config('request.jwt.claim.sub',a::text,true);
 update public.workspaces set name='Oryveta Test A Updated' where id=aid;
 get diagnostics n = row_count;
 if n<>1 then raise exception 'Owner workspace update blocked'; end if;
 select count(*) into n from public.workspaces;
 if n<>1 then raise exception 'Owner sees more than own workspace'; end if;
end
$test$;
rollback;
