-- Dedicated Oryveta test project only. Synthetic identities, NOT real sign-ins.
-- All fixtures and messages roll back; no invitation email is sent.
begin;
insert into auth.users
 (id,instance_id,aud,role,email,email_confirmed_at,created_at,updated_at)
values
 ('31111111-1111-4111-8111-111111111111','00000000-0000-0000-0000-000000000000',
  'authenticated','authenticated','chat-review-owner@example.invalid',now(),now(),now()),
 ('32222222-2222-4222-8222-222222222222','00000000-0000-0000-0000-000000000000',
  'authenticated','authenticated','chat-review-recipient@example.invalid',now(),now(),now()),
 ('33333333-3333-4333-8333-333333333333','00000000-0000-0000-0000-000000000000',
  'authenticated','authenticated','chat-review-outsider@example.invalid',now(),now(),now());
set local role authenticated;
do $test$
declare
 owner_id uuid := '31111111-1111-4111-8111-111111111111';
 recipient_id uuid := '32222222-2222-4222-8222-222222222222';
 outsider_id uuid := '33333333-3333-4333-8333-333333333333';
 conversation_id uuid;
 invitation_id uuid;
 n integer;
begin
 perform set_config('request.jwt.claim.sub',owner_id::text,true);
 insert into public.chats(owner_id,title)
 values(owner_id,'Rollback-only review') returning id into conversation_id;
 insert into public.chat_messages(chat_id,author_id,content)
 values(conversation_id,owner_id,'Private test message');
 insert into public.chat_shares(chat_id,invited_by,recipient_email,permission)
 values(conversation_id,owner_id,'chat-review-recipient@example.invalid','viewer')
 returning id into invitation_id;

 perform set_config('request.jwt.claim.sub',recipient_id::text,true);
 select count(*) into n from public.chats where id=conversation_id;
 if n<>0 then raise exception 'Pending invitation exposes chat'; end if;
 select count(*) into n from public.chat_messages where chat_id=conversation_id;
 if n<>0 then raise exception 'Pending invitation exposes messages'; end if;
 update public.chat_shares set status='accepted',accepted_by=recipient_id,accepted_at=now()
 where id=invitation_id;
 get diagnostics n = row_count;
 if n<>1 then raise exception 'Recipient cannot accept invitation'; end if;
 select count(*) into n from public.chat_messages where chat_id=conversation_id;
 if n<>1 then raise exception 'Accepted viewer cannot read'; end if;
 begin
  insert into public.chat_messages(chat_id,author_id,content)
  values(conversation_id,recipient_id,'Viewer must not write');
  raise exception 'Viewer write unexpectedly succeeded';
 exception when insufficient_privilege then null;
 end;
 if has_column_privilege('authenticated','public.chat_shares','permission','update') or
    has_column_privilege('authenticated','public.chat_shares','chat_id','update')
 then raise exception 'Recipient may escalate share permissions'; end if;

 perform set_config('request.jwt.claim.sub',owner_id::text,true);
 delete from public.chat_shares where id=invitation_id;
 get diagnostics n = row_count;
 if n<>1 then raise exception 'Owner cannot revoke'; end if;
 perform set_config('request.jwt.claim.sub',recipient_id::text,true);
 select count(*) into n from public.chat_messages where chat_id=conversation_id;
 if n<>0 then raise exception 'Revoked viewer retains access'; end if;
 insert into public.user_aliases(user_id,alias) values(recipient_id,'chat_review_recipient');
 perform set_config('request.jwt.claim.sub',owner_id::text,true);
 insert into public.chat_shares(chat_id,invited_by,recipient_alias,permission)
 values(conversation_id,owner_id,'chat_review_recipient','editor')
 returning id into invitation_id;
 perform set_config('request.jwt.claim.sub',recipient_id::text,true);
 update public.chat_shares set status='accepted',accepted_by=recipient_id,accepted_at=now()
 where id=invitation_id;
 get diagnostics n = row_count;
 if n<>1 then raise exception 'Alias recipient cannot accept'; end if;
 insert into public.chat_messages(chat_id,author_id,content)
 values(conversation_id,recipient_id,'Editor test message');
 select count(*) into n from public.chat_messages where chat_id=conversation_id;
 if n<>2 then raise exception 'Editor message missing'; end if;

 perform set_config('request.jwt.claim.sub',outsider_id::text,true);
 select count(*) into n from public.chats where id=conversation_id;
 if n<>0 then raise exception 'Outsider reads chat'; end if;
 select count(*) into n from public.chat_messages where chat_id=conversation_id;
 if n<>0 then raise exception 'Outsider reads messages'; end if;
 select count(*) into n from public.chat_shares where chat_id=conversation_id;
 if n<>0 then raise exception 'Outsider reads invitations'; end if;
 begin
  insert into public.chat_messages(chat_id,author_id,content)
  values(conversation_id,outsider_id,'Outsider must not write');
  raise exception 'Outsider write unexpectedly succeeded';
 exception when insufficient_privilege then null;
 end;
end
$test$;
rollback;
