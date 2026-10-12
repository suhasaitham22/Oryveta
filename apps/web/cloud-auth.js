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
  window.OryvetaCloudAuth=Object.freeze({
    configured,githubConfigured,emailConfigured,hasSessionHint,identity,signIn,signInWithEmail,signOut,workspaces,createWorkspace,updateWorkspace
  });
})();
