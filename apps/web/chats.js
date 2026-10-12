'use strict';
/* No frontend filtering is an authorization boundary: Supabase RLS owns it. */
(function(){
 const s={rows:[],invites:[],messages:[],shares:[],alias:'',selected:null,busy:false};
 const one=id=>document.getElementById(id);
 const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const api=()=>window.OryvetaCloudAuth;
 const selected=()=>s.rows.find(x=>x.id===s.selected);
 const owner=()=>selected()?.owner_id===state.user?.id;
 const editor=()=>owner()||s.shares.some(x=>x.status==='accepted'&&x.accepted_by===state.user?.id&&x.permission==='editor');
 function shell(){
  return pageHeader('PRIVATE CONVERSATIONS','Your thinking stays yours.','Start a private discussion. Share only with verified recipients you select.')+
   '<div class="notice chat-trust">Private by default. Workspace members do not automatically see any conversation. Share links are not public; invitations require acceptance.</div>'+
   '<div class="chat-grid"><aside class="card chat-sidebar">'+
   '<form id="chat-create" class="chat-create"><label for="chat-new-title">New private conversation</label><input id="chat-new-title" name="title" required maxlength="120" placeholder="Feature planning, architecture…"><button class="btn" type="submit">Create conversation →</button></form>'+
   '<div class="chat-heading">YOUR CONVERSATIONS <span id="chat-count"></span></div><div id="chat-options" class="chat-options"></div>'+
   '<div class="chat-heading">SHARED WITH YOU <span id="chat-invites-count"></span></div><div id="chat-invites"></div>'+
   '<form id="chat-alias" class="chat-alias"><label for="chat-alias-value">My @alias</label><input id="chat-alias-value" name="alias" maxlength="32" placeholder="e.g. alex_dev"><button class="btn btn-outline" type="submit">Save alias</button><p class="chat-hint">Teammates can invite your alias without knowing your email address.</p></form>'+
   '</aside><section class="chat-main" aria-label="Private conversation"><div id="chat-content"></div></section></div>';
 }
 function empty(title,desc,signIn){
  return '<div class="chat-empty"><span class="brand-symbol">◈</span><h2>'+e(title)+'</h2><p>'+e(desc)+'</p>'+
   (signIn?'<button class="btn" id="workspace-signin" type="button">Return to sign in →</button>':'')+'</div>';
 }
 async function pullSelected(){
  if(!s.selected){s.messages=[];s.shares=[];return;}
  [s.messages,s.shares]=await Promise.all([api().listMessages(s.selected),api().listShares(s.selected)]);
 }
 async function refresh(){
  [s.rows,s.invites,s.alias]=await Promise.all([api().listChats(),api().listInvites(),api().getAlias()]);
  if(!s.rows.some(x=>x.id===s.selected))s.selected=s.rows[0]?.id||null;
  await pullSelected();render();
 }
 function render(){
  if(state.current!=='chats'||!one('chat-options'))return;
  one('chat-count').textContent=String(s.rows.length);
  one('chat-invites-count').textContent=String(s.invites.length);
  one('chat-alias-value').value=s.alias;
  one('chat-options').innerHTML=s.rows.length?s.rows.map(x=>'<button type="button" data-chat-open="'+e(x.id)+'" class="chat-choice '+(x.id===s.selected?'selected':'')+'"><strong>'+e(x.title)+'</strong><small>'+(x.owner_id===state.user.id?'Private · Owner':'Shared with you')+'</small></button>').join(''):'<p class="chat-hint">No conversations yet.</p>';
  one('chat-invites').innerHTML=s.invites.length?s.invites.map(x=>'<div class="chat-invite"><strong>'+e(x.recipient_email||'@'+x.recipient_alias)+'</strong><small>'+e(x.permission)+' invitation · acceptance required</small><button class="btn btn-outline" type="button" data-chat-accept="'+e(x.id)+'">Accept invitation</button></div>').join(''):'<p class="chat-hint">No pending invitations.</p>';
  const row=selected();
  if(!row){one('chat-content').innerHTML=empty('A space for your next big idea.','Start a private conversation, or accept an invitation. Messages are saved securely for signed-in users.',false);return;}
  const canWrite=editor();
  let out='<header class="chat-main-header"><div><span class="eyebrow">PRIVATE CONVERSATION</span><h2>'+e(row.title)+'</h2></div><span class="workspace-badge">'+(owner()?'Owner':canWrite?'Editor':'Viewer')+'</span></header>';
  out+='<div class="chat-thread" role="log" aria-label="Chat messages" aria-live="polite">';
  out+=s.messages.length?s.messages.map(m=>'<article class="chat-message '+(m.author_id===state.user.id?'mine':'')+'"><small>'+(m.author_id===state.user.id?'You':'Collaborator')+'</small><p>'+e(m.content)+'</p></article>').join(''):'<p class="chat-hint">No messages yet. Start the conversation.</p>';
  out+='</div>';
  out+=canWrite?'<form id="chat-compose" class="chat-compose"><label for="chat-message">Write a message</label><textarea id="chat-message" name="content" maxlength="4000" required placeholder="Add your thoughts, decisions, or review notes…"></textarea><button class="btn" type="submit">Send message →</button></form>':'<p class="chat-hint">You have view-only access to this conversation.</p>';
  if(owner()){
   out+='<section class="chat-share"><span class="eyebrow">SHARING & ACCESS</span><p class="chat-hint">Invite a person by email (including Outlook and work addresses) or an existing @alias. Recipients must accept before viewing.</p>';
   out+='<form id="chat-share" class="chat-share-form"><label for="chat-recipient">Recipient</label><label for="chat-role">Permissions</label><span></span><input id="chat-recipient" name="recipient" maxlength="254" required placeholder="person@company.com or @alias"><select id="chat-role" name="permission"><option value="viewer">Can view</option><option value="editor">Can add messages</option></select><button class="btn" type="submit">Invite →</button></form>';
   out+='<div class="chat-shares-list">'+(s.shares.length?s.shares.map(x=>'<div class="chat-share-row"><div><strong>'+e(x.recipient_email||'@'+x.recipient_alias)+'</strong><small>'+e(x.permission)+' · '+e(x.status)+'</small></div><button class="btn btn-outline" type="button" data-chat-revoke="'+e(x.id)+'">Revoke</button></div>').join(''):'<p class="chat-hint">No access invitations yet.</p>')+'</div>';
   out+='<button type="button" class="chat-delete" data-chat-delete="'+e(row.id)+'">Delete conversation permanently</button></section>';
  }else out+='<p class="chat-hint">The owner controls this conversation and can revoke access at any time.</p>';
  one('chat-content').innerHTML=out;
  const log=one('chat-content').querySelector('.chat-thread');if(log)log.scrollTop=log.scrollHeight;
 }
 async function mount(){
  if(!one('chat-content')||state.current!=='chats')return;
  if(!state.cloud){
   one('chat-create').classList.add('hidden');one('chat-alias').classList.add('hidden');
   one('chat-options').innerHTML='<p class="chat-hint">Sign in to store private conversations.</p>';
   one('chat-invites').innerHTML='<p class="chat-hint">Sign in to view invitations.</p>';
   one('chat-content').innerHTML=empty('Your private space starts with an account.','The public preview cannot read, send, or share private messages.',true);
   return;
  }
  try{await refresh()}catch(err){one('chat-content').innerHTML=empty('Could not load conversations.',err.message,false);toast(err.message,true)}
 }
 document.addEventListener('submit',async event=>{
  const form=event.target;if(!['chat-create','chat-compose','chat-share','chat-alias'].includes(form.id))return;
  event.preventDefault();if(s.busy)return;s.busy=true;
  const submit=form.querySelector('[type="submit"]');if(submit)submit.disabled=true;
  try{
   if(!state.cloud)throw new Error('Sign in before saving conversations');
   if(form.id==='chat-create'){
    const title=form.elements.title.value.trim();if(!title||title.length>120)throw new Error('Enter a title between 1 and 120 characters');
    const newChat=await api().createChat(title,state.activeWorkspaceId);s.selected=newChat.id;
   }else if(form.id==='chat-compose'){
    const msg=form.elements.content.value.trim();if(!msg||msg.length>4000)throw new Error('Messages need 1–4000 characters');
    await api().addMessage(s.selected,msg);
   }else if(form.id==='chat-share'){
    await api().inviteToChat(s.selected,form.elements.recipient.value,form.elements.permission.value);
    toast('Invitation created. It becomes accessible once accepted.');
   }else {await api().setAlias(form.elements.alias.value);toast('Alias saved.');}
   await refresh();
  }catch(err){toast(err.message,true)}
  finally{s.busy=false;if(submit?.isConnected)submit.disabled=false;}
 });
 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-chat-open],[data-chat-accept],[data-chat-revoke],[data-chat-delete]');
  if(!button||state.current!=='chats'||!state.cloud||s.busy)return;s.busy=true;
  try{
   if(button.dataset.chatOpen){s.selected=button.dataset.chatOpen;await pullSelected();render();}
   else if(button.dataset.chatAccept){await api().acceptChatInvite(button.dataset.chatAccept);await refresh();toast('Invitation accepted.');}
   else if(button.dataset.chatRevoke){await api().revokeChatInvite(button.dataset.chatRevoke);await refresh();toast('Access revoked.');}
   else if(button.dataset.chatDelete){
    if(!window.confirm('Permanently delete this conversation and its messages?'))return;
    await api().deleteChat(button.dataset.chatDelete);s.selected=null;await refresh();toast('Conversation deleted.');
   }
  }catch(err){toast(err.message,true)}finally{s.busy=false;}
 });
 window.OryvetaChats=Object.freeze({shell,mount});
})();
