/* Oryveta hosted identity and workspace adapter.
 * Supabase Auth owns OAuth PKCE, token refresh, identity verification and logout.
 * Database authorization is enforced by PostgreSQL RLS, never by this module.
 */
'use strict';
(function(){
  const config = window.ORYVETA_CLOUD || {};
  const valid = typeof config.url === 'string' &&
    /^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(config.url) &&
    typeof config.publishableKey === 'string' &&
    /^sb_publishable_[A-Za-z0-9_-]+$/.test(config.publishableKey);
  let clientPromise;
  let currentIdentity = null;

  function configured(){return valid && (config.githubEnabled === true || config.emailEnabled === true);}
  function githubConfigured(){return valid && config.githubEnabled === true;}
  function emailConfigured(){return valid && config.emailEnabled === true;}
  function hasSessionHint(){const ref=new URL(config.url).hostname.split('.')[0];return new URLSearchParams(location.search).has('code') || location.hash.includes('access_token=') || !!sessionStorage.getItem('sb-'+ref+'-auth-token');}
  async function client(){
    if(!valid)throw new Error('Cloud authentication is not configured yet.');
    if(!clientPromise){
      clientPromise=import('https://esm.sh/@supabase/supabase-js@2.57.0?bundle')
        .then(({createClient})=>createClient(config.url,config.publishableKey,{
          auth:{
            flowType:'pkce',detectSessionInUrl:true,
            storage:window.sessionStorage,persistSession:true,autoRefreshToken:true
          }
        })).catch(error=>{clientPromise=null;throw new Error('Authentication service could not load. Please try again.');});
    }
    return clientPromise;
  }
  function unwrap(result, fallback){
    if(result.error)throw new Error(result.error.message||fallback);
    return result.data;
  }
  async function identity(){
    const supabase=await client();
    const session=unwrap(await supabase.auth.getSession(),'Could not restore session').session;
    if(!session){currentIdentity=null;return null;}
    const data=unwrap(await supabase.auth.getUser(),'Could not verify account');
    currentIdentity=data.user||null;
    return currentIdentity;
  }
  async function signIn(){
    if(!githubConfigured())throw new Error('GitHub sign-in is not enabled yet.');
    const supabase=await client();
    const result=await supabase.auth.signInWithOAuth({
      provider:'github',
      options:{redirectTo:window.location.origin+'/',scopes:'read:user user:email'}
    });
    const data=unwrap(result,'Could not start GitHub sign-in');
    if(data.url)window.location.assign(data.url);
  }
  async function signInWithEmail(email){
    if(!emailConfigured())throw new Error('Email sign-in is not enabled yet.');
    const normalized=String(email||'').trim().toLowerCase();
    if(normalized.length>254 || !/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(normalized))throw new Error('Enter a valid email address.');
    const supabase=await client();
    unwrap(await supabase.auth.signInWithOtp({email:normalized,options:{emailRedirectTo:window.location.origin+'/',shouldCreateUser:true}}),'Could not send a sign-in link');
    return true;
  }
  async function signOut(){
    const supabase=await client();
    try{unwrap(await supabase.auth.signOut(),'Could not sign out');}
    finally{currentIdentity=null;window.sessionStorage.removeItem('oryveta.active-workspace');}
  }
  async function workspaces(){
    if(!currentIdentity)throw new Error('Sign in to access workspaces');
    const supabase=await client();
    const data=unwrap(await supabase.from('workspaces')
      .select('id,name,slug,description,created_by,created_at,updated_at')
      .order('created_at',{ascending:false}),'Could not load workspaces');
    return data||[];
  }
  async function createWorkspace({name,slug,description}){
    if(!currentIdentity)throw new Error('Sign in to create a workspace');
    const supabase=await client();
    const data=unwrap(await supabase.from('workspaces').insert({
      name,slug,description,created_by:currentIdentity.id
    }).select('id,name,slug,description,created_by,created_at,updated_at').single(),
    'Could not create workspace');
    return data;
  }
  async function updateWorkspace(id,{name,description}){
    if(!currentIdentity)throw new Error('Sign in to update a workspace');
    const supabase=await client();
    const data=unwrap(await supabase.from('workspaces').update({name,description})
      .eq('id',id).select('id,name,slug,description,created_by,created_at,updated_at').single(),
    'Could not update workspace');
    return data;
  }

  function requireUser(){if(!currentIdentity)throw new Error('Sign in to access private chats');}
  async function listChats(){requireUser();const sb=await client();return unwrap(await sb.from('chats').select('id,owner_id,workspace_id,title,created_at').order('created_at',{ascending:false}).limit(100),'Could not load chats')||[];}
  async function createChat(title,workspaceId){requireUser();const sb=await client();return unwrap(await sb.from('chats').insert({owner_id:currentIdentity.id,workspace_id:workspaceId||null,title}).select('id,owner_id,workspace_id,title,created_at').single(),'Could not create chat');}
  async function deleteChat(id){requireUser();const sb=await client();unwrap(await sb.from('chats').delete().eq('id',id),'Could not delete chat');}
  async function listMessages(chatId){requireUser();const sb=await client();return unwrap(await sb.from('chat_messages').select('id,chat_id,author_id,content,created_at').eq('chat_id',chatId).order('created_at').limit(200),'Could not load messages')||[];}
  async function addMessage(chatId,content){requireUser();const sb=await client();return unwrap(await sb.from('chat_messages').insert({chat_id:chatId,author_id:currentIdentity.id,role:'user',content}).select('id,content').single(),'Could not save message');}
  async function listInvites(){requireUser();const sb=await client();return (unwrap(await sb.from('chat_shares').select('id,chat_id,invited_by,recipient_email,recipient_alias,permission,status,accepted_by').eq('status','pending').limit(100),'Could not load invitations')||[]).filter(x=>x.invited_by!==currentIdentity.id);}
  async function listShares(chatId){requireUser();const sb=await client();return unwrap(await sb.from('chat_shares').select('id,chat_id,recipient_email,recipient_alias,permission,status,accepted_by').eq('chat_id',chatId).limit(100),'Could not load shares')||[];}
  async function inviteToChat(chatId,recipient,permission){requireUser();const target=String(recipient||'').trim().toLowerCase();const alias=target.startsWith('@');if(alias?!/^@[a-z][a-z0-9_]{2,31}$/.test(target):!(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)&&target.length<=254))throw new Error('Use a valid email or registered @alias');if(!['viewer','editor'].includes(permission))throw new Error('Invalid permission');const sb=await client();return unwrap(await sb.from('chat_shares').insert({chat_id:chatId,invited_by:currentIdentity.id,permission,...(alias?{recipient_alias:target.slice(1)}:{recipient_email:target})}).select('id,status').single(),'Could not send invitation');}
  async function acceptChatInvite(id){requireUser();const sb=await client();return unwrap(await sb.from('chat_shares').update({status:'accepted',accepted_by:currentIdentity.id,accepted_at:new Date().toISOString()}).eq('id',id).eq('status','pending').select('id,chat_id').single(),'Could not accept invitation');}
  async function revokeChatInvite(id){requireUser();const sb=await client();unwrap(await sb.from('chat_shares').delete().eq('id',id),'Could not revoke access');}
  async function getAlias(){requireUser();const sb=await client();return unwrap(await sb.from('user_aliases').select('alias').eq('user_id',currentIdentity.id).maybeSingle(),'Could not load alias')?.alias||'';}
  async function setAlias(alias){requireUser();const a=String(alias||'').trim().toLowerCase().replace(/^@/,'');if(!/^[a-z][a-z0-9_]{2,31}$/.test(a))throw new Error('Alias must be 3–32 lowercase letters, numbers or underscores');const sb=await client();const current=await getAlias();unwrap(current?await sb.from('user_aliases').update({alias:a}).eq('user_id',currentIdentity.id):await sb.from('user_aliases').insert({user_id:currentIdentity.id,alias:a}),'Could not save alias');return a;}
  window.OryvetaCloudAuth=Object.freeze({
    configured,githubConfigured,emailConfigured,hasSessionHint,identity,signIn,signInWithEmail,signOut,workspaces,createWorkspace,updateWorkspace,listChats,createChat,deleteChat,listMessages,addMessage,listInvites,listShares,inviteToChat,acceptChatInvite,revokeChatInvite,getAlias,setAlias
  });
})();
