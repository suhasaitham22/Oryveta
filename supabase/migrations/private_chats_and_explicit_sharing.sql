-- Apply after supabase/schema.sql. Dedicated Oryveta project only.
-- Chats are private to their creator; invites never confer access until accepted.
create table if not exists public.user_aliases(
 user_id uuid primary key references auth.users(id) on delete cascade,
 alias text not null unique check(alias ~ '^[a-z][a-z0-9_]{2,31}$'),
 created_at timestamptz not null default now());
create table if not exists public.chats(
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 workspace_id uuid references public.workspaces(id) on delete set null,
 title text not null default 'New conversation' check(char_length(title) between 1 and 120),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now());
create index if not exists chats_owner_created_idx on public.chats(owner_id,created_at desc);
create index if not exists chats_workspace_idx on public.chats(workspace_id) where workspace_id is not null;
create table if not exists public.chat_shares(
 id uuid primary key default gen_random_uuid(),
 chat_id uuid not null references public.chats(id) on delete cascade,
 invited_by uuid not null references auth.users(id) on delete cascade,
 recipient_email text,
 recipient_alias text,
 target_user_id uuid references auth.users(id) on delete cascade,
 permission text not null default 'viewer' check(permission in ('viewer','editor')),
 status text not null default 'pending' check(status in ('pending','accepted')),
 accepted_by uuid references auth.users(id) on delete set null,
 accepted_at timestamptz,
 created_at timestamptz not null default now(),
 check((recipient_email is null) <> (recipient_alias is null)),
 check(recipient_email is null or
  (recipient_email=lower(recipient_email) and char_length(recipient_email)<=254 and
   recipient_email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$')),
 check(recipient_alias is null or recipient_alias ~ '^[a-z][a-z0-9_]{2,31}$'),
 check((status='pending' and accepted_by is null and accepted_at is null) or
       (status='accepted' and accepted_by is not null and accepted_at is not null)));
create unique index if not exists chat_shares_one_email_idx on public.chat_shares(chat_id,recipient_email) where recipient_email is not null;
create unique index if not exists chat_shares_one_alias_idx on public.chat_shares(chat_id,recipient_alias) where recipient_alias is not null;
create index if not exists chat_shares_accepted_idx on public.chat_shares(accepted_by,chat_id) where status='accepted';
create index if not exists chat_shares_target_idx on public.chat_shares(target_user_id,status);
create index if not exists chat_shares_inviter_idx on public.chat_shares(invited_by);
create table if not exists public.chat_messages(
 id uuid primary key default gen_random_uuid(),
 chat_id uuid not null references public.chats(id) on delete cascade,
 author_id uuid not null references auth.users(id) on delete cascade,
 role text not null default 'user' check(role='user'),
 content text not null check(char_length(content) between 1 and 12000),
 created_at timestamptz not null default now());
create index if not exists chat_messages_order_idx on public.chat_messages(chat_id,created_at,id);
create index if not exists chat_messages_author_idx on public.chat_messages(author_id);

create or replace function private.verified_email()
returns text language sql stable security definer set search_path=''
as $$ select lower(u.email) from auth.users u
 where u.id=(select auth.uid()) and u.email_confirmed_at is not null $$;
revoke all on function private.verified_email() from public,anon;
grant execute on function private.verified_email() to authenticated;
create or replace function private.is_chat_owner(target_chat uuid)
returns boolean language sql stable security definer set search_path=''
as $$ select (select auth.uid()) is not null and exists(
 select 1 from public.chats c where c.id=target_chat and c.owner_id=(select auth.uid())) $$;
revoke all on function private.is_chat_owner(uuid) from public,anon;
grant execute on function private.is_chat_owner(uuid) to authenticated;
create or replace function private.can_read_chat(target_chat uuid)
returns boolean language sql stable security definer set search_path=''
as $$ select (select auth.uid()) is not null and (
 exists(select 1 from public.chats c where c.id=target_chat and c.owner_id=(select auth.uid()))
 or exists(select 1 from public.chat_shares s where s.chat_id=target_chat and s.status='accepted' and s.accepted_by=(select auth.uid()))) $$;
revoke all on function private.can_read_chat(uuid) from public,anon;
grant execute on function private.can_read_chat(uuid) to authenticated;
create or replace function private.can_write_chat(target_chat uuid)
returns boolean language sql stable security definer set search_path=''
as $$ select (select auth.uid()) is not null and (
 exists(select 1 from public.chats c where c.id=target_chat and c.owner_id=(select auth.uid()))
 or exists(select 1 from public.chat_shares s where s.chat_id=target_chat and s.status='accepted' and
  s.accepted_by=(select auth.uid()) and s.permission='editor')) $$;
revoke all on function private.can_write_chat(uuid) from public,anon;
grant execute on function private.can_write_chat(uuid) to authenticated;
create or replace function private.resolve_chat_share()
returns trigger language plpgsql security definer set search_path=''
as $$
begin
 if (select auth.uid()) is null or new.invited_by<>(select auth.uid()) or
   not private.is_chat_owner(new.chat_id) then raise exception 'only the owner can share';end if;
 if new.recipient_alias is not null then
  select a.user_id into new.target_user_id from public.user_aliases a where a.alias=new.recipient_alias;
  if new.target_user_id is null then raise exception 'recipient alias not found';end if;
  if new.target_user_id=new.invited_by then raise exception 'cannot invite yourself';end if;
 else
  new.target_user_id:=null;
  if new.recipient_email=private.verified_email() then raise exception 'cannot invite yourself';end if;
 end if;
 return new;
end
$$;
revoke all on function private.resolve_chat_share() from public,anon,authenticated;
drop trigger if exists chat_share_resolve_target on public.chat_shares;
create trigger chat_share_resolve_target before insert on public.chat_shares
for each row execute function private.resolve_chat_share();

alter table public.user_aliases enable row level security;
alter table public.chats enable row level security;
alter table public.chat_shares enable row level security;
alter table public.chat_messages enable row level security;
create policy aliases_select_self on public.user_aliases for select to authenticated using(user_id=(select auth.uid()));
create policy aliases_insert_self on public.user_aliases for insert to authenticated with check(user_id=(select auth.uid()));
create policy aliases_update_self on public.user_aliases for update to authenticated using(user_id=(select auth.uid())) with check(user_id=(select auth.uid()));
-- Owner predicate permits INSERT .. RETURNING before the new row exists to the definer read query.
create policy chats_read_explicit on public.chats for select to authenticated using(owner_id=(select auth.uid()) or private.can_read_chat(id));
create policy chats_insert_owner on public.chats for insert to authenticated
 with check(owner_id=(select auth.uid()) and (workspace_id is null or (select private.is_workspace_member(workspace_id))));
create policy chats_update_owner on public.chats for update to authenticated using(owner_id=(select auth.uid())) with check(owner_id=(select auth.uid()));
create policy chats_delete_owner on public.chats for delete to authenticated using(owner_id=(select auth.uid()));
create policy shares_select_invited on public.chat_shares for select to authenticated
 using(private.is_chat_owner(chat_id) or accepted_by=(select auth.uid()) or
  (status='pending' and (target_user_id=(select auth.uid()) or recipient_email=private.verified_email())));
create policy shares_insert_owner on public.chat_shares for insert to authenticated
 with check(private.is_chat_owner(chat_id) and invited_by=(select auth.uid()) and status='pending' and accepted_by is null and accepted_at is null);
create policy shares_accept_recipient on public.chat_shares for update to authenticated
 using(status='pending' and (target_user_id=(select auth.uid()) or recipient_email=private.verified_email()))
 with check(status='accepted' and accepted_by=(select auth.uid()) and accepted_at is not null and
  (target_user_id=(select auth.uid()) or recipient_email=private.verified_email()));
create policy shares_delete_owner on public.chat_shares for delete to authenticated using(private.is_chat_owner(chat_id));
create policy messages_read_granted on public.chat_messages for select to authenticated using(private.can_read_chat(chat_id));
create policy messages_write_granted on public.chat_messages for insert to authenticated
 with check(author_id=(select auth.uid()) and role='user' and private.can_write_chat(chat_id));

revoke all on public.user_aliases,public.chats,public.chat_shares,public.chat_messages from anon,authenticated;
grant select,insert on public.user_aliases to authenticated;
grant update(alias) on public.user_aliases to authenticated;
grant select,insert,delete on public.chats to authenticated;
grant update(title) on public.chats to authenticated;
grant select,delete on public.chat_shares to authenticated;
grant insert(chat_id,invited_by,recipient_email,recipient_alias,permission) on public.chat_shares to authenticated;
grant update(status,accepted_by,accepted_at) on public.chat_shares to authenticated;
grant select on public.chat_messages to authenticated;
grant insert(chat_id,author_id,role,content) on public.chat_messages to authenticated;
