import React,{useEffect,useRef,useState} from "react";
import {AtSign,ArrowRight,CheckCircle2,FolderGit2,LockKeyhole,MessageSquareText,Plus,Send,ShieldCheck,Trash2,UserPlus,UsersRound} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {Input} from "@/components/ui/input";
import {Textarea} from "@/components/ui/textarea";
import * as chatsApi from "@/lib/privateChats.js";
import * as projectsApi from "@/lib/projects.js";
import {useWorkspaceState} from "@/lib/WorkspaceState.jsx";

/* This UI never treats a workspace membership as consent to read a conversation. */
export default function PrivateChats({user,preview,workspaceId,onExit}){
 const [conversations,setConversations]=useState([]);
 const [invitations,setInvitations]=useState([]);
 const [alias,setAlias]=useState("");
 const {chatDraft,setChatDraft,spaces}=useWorkspaceState();
 const [projects,setProjects]=useState([]);
 const [projectNotice,setProjectNotice]=useState("");
 const selected=chatDraft.selected;
 const setSelected=value=>setChatDraft(current=>({...current,selected:typeof value==="function"?value(current.selected):value}));
 /* Loaded details carry the conversation that produced them. Anything belonging to another
    conversation is neither rendered nor actionable, so a slow or failed replacement load can
    never offer one conversation's invitations under another one's title. */
 const [details,setDetails]=useState({chatId:null,messages:[],shares:[],olderOmitted:false});
 const detailsReady=!!selected&&details.chatId===selected;
 const messages=detailsReady?details.messages:[];
 const shares=detailsReady?details.shares:[];
 const olderOmitted=detailsReady&&details.olderOmitted;
 const title=chatDraft.title;
 const project=chatDraft.project||"";
 const setProject=project=>setChatDraft(current=>({...current,project}));
 const setTitle=title=>setChatDraft(current=>({...current,title}));
 const message=chatDraft.messages[selected]||"";
 const recipient=chatDraft.recipients[selected]||"";
 const permission=chatDraft.permissions[selected]||"viewer";
 const setMessage=message=>setChatDraft(current=>({...current,messages:{...current.messages,[selected]:message}}));
 /* A completed send clears the text it submitted, never whatever is in the composer when its
    acknowledgement happens to arrive. */
 const clearSubmittedMessage=(chatId,submitted)=>setChatDraft(current=>current.messages[chatId]!==submitted?current:{...current,messages:{...current.messages,[chatId]:""}});
 const setRecipient=recipient=>setChatDraft(current=>({...current,recipients:{...current.recipients,[selected]:recipient}}));
 const setPermission=permission=>setChatDraft(current=>({...current,permissions:{...current.permissions,[selected]:permission}}));
 const [busy,setBusy]=useState(false);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");
 const [rev,setRev]=useState(0);
 const active=conversations.find(c=>c.id===selected)||null;
 const isOwner=!!active&&active.owner_id===user?.id;
 const canWrite=isOwner||shares.some(s=>s.status==="accepted"&&s.accepted_by===user?.id&&s.permission==="editor");
 /* Each load is numbered and tied to this mounted page. An older response, or one that belongs
    to a page the user has already left, is dropped instead of overwriting newer state or the
    shared selection and drafts that outlive this page. */
 const loadRequest=useRef(0);
 const mounted=useRef(false);
 async function refresh(prefer){
  if(preview||!user||!mounted.current)return;
  const request=++loadRequest.current;
  const live=()=>mounted.current&&request===loadRequest.current;
  let items,inbox,handle,readable;
  try{[items,inbox,handle,readable]=await Promise.all([chatsApi.listChats(),chatsApi.listInvitations(user),chatsApi.getAlias(user),projectsApi.listProjects().then(rows=>({rows}),problem=>({problem:problem.message}))]);}
  catch(problem){if(!live())return;setError(problem.message);setLoading(false);throw problem;}
  if(!live())return;
  setConversations(items);setInvitations(inbox);setAlias(handle);setLoading(false);
  /* Projects are listed only to offer an association and to name the one already chosen.
     A failure here never blocks conversations, and names are resolved from this
     RLS-filtered list rather than joined onto a chat we may not be allowed to link. */
  setProjects(readable.rows||[]);setProjectNotice(readable.problem||"");
  setChatDraft(current=>current.project&&!(readable.rows||[]).some(p=>p.id===current.project)?{...current,project:""}:current);
  setSelected(old=>items.some(c=>c.id===(prefer||old))?(prefer||old):items[0]?.id||null);
  setRev(x=>x+1);
 }
 useEffect(()=>{
  if(preview||!user)return;
  mounted.current=true;
  setLoading(true);
  refresh().catch(()=>{}); // The current refresh reports its own error and loading state.
  return()=>{mounted.current=false;loadRequest.current++;};
 },[preview,user?.id]);
 useEffect(()=>{
  if(!selected||preview){setDetails({chatId:null,messages:[],shares:[],olderOmitted:false});return;}
  let alive=true;
  Promise.all([chatsApi.listMessages(selected),chatsApi.listShares(selected)]).then(([history,s])=>{if(alive)setDetails({chatId:selected,messages:history.messages,shares:s,olderOmitted:history.olderOmitted});}).catch(e=>{if(alive)setError(e.message)});
  return()=>{alive=false};
 },[selected,rev,preview]);
 async function action(task){
  if(busy||preview||!user)return;
  setBusy(true);setError("");setNotice("");
  try{await task();}catch(e){if(mounted.current)setError(e.message)}finally{if(mounted.current)setBusy(false)}
 }
 if(preview)return <>
  <div className="page-heading">
   <div className="section-label">Private conversations</div>
   <h1>Sign in to start a private conversation.</h1>
   <p>Keep project decisions and reviews together. These are conversations with people, not an AI agent.</p>
  </div>
  <div className="surface-panel">
   <LockKeyhole size={26}/>
   <h2>Invite only the people you choose.</h2>
   <p>Sign in to create a conversation, then invite specific people by email or @alias. Project membership never shares a conversation.</p>
   <Button onClick={onExit}>Return to sign in <ArrowRight size={16}/></Button>
  </div>
 </>;
 return <>
  <div className="page-heading">
   <div className="section-label">Conversations · confidential</div>
   <h1>Your private conversations</h1>
   <p>Discuss requirements, decisions and reviews with invited people. Each conversation stays private until specific verified accounts accept your invitation. AI agent chat is not connected.</p>
  </div>
  <div className="preview-ribbon">
   <ShieldCheck size={17} aria-hidden="true"/>
   <span>Workspace membership alone never grants access. Invitations are in-app, not emails; a pending invitation reveals no messages.</span>
  </div>
  {error&&<div role="alert" className="alert-error">{error}</div>}
  {notice&&<div role="status" className="alert-success">{notice}</div>}
  <div className="chat-layout">
   <div className="chat-aside">
    <div className="surface-panel chat-panel">
     <form onSubmit={e=>{e.preventDefault();action(async()=>{const clean=title.trim();if(!clean||clean.length>120)throw Error("Enter a title up to 120 characters");const chosen=project?projects.find(p=>p.id===project):null;if(project&&!chosen)throw Error("That project is no longer available to you");
      /* Only claim the workspace when this account actually belongs to it: a project-only
         invitee links the conversation to the project without joining the workspace. */
      const scope=chosen?(spaces.some(s=>s.id===chosen.workspace_id)?chosen.workspace_id:null):workspaceId;
      const created=await chatsApi.createChat(user,scope,clean,chosen?.id||null);
      if(!mounted.current)return;
      setChatDraft(current=>({...current,title:current.title===title?"":current.title,project:(current.project||"")===project?"":current.project}));
      await refresh(created.id);
      if(mounted.current)setNotice(chosen?`Private conversation created and linked to ${chosen.name}. The link grants nobody else access.`:"Private conversation created.");});}}>
      <div className="field-label">
       <label htmlFor="chat-title">New private conversation</label>
       <Input id="chat-title" required maxLength={120} placeholder="What are we deciding?" value={title} onChange={e=>setTitle(e.target.value)}/>
      </div>
      <div className="field-label">
       <label htmlFor="chat-project">Related project (optional)</label>
       <select id="chat-project" aria-describedby="chat-project-help" value={project} onChange={e=>setProject(e.target.value)}>
        <option value="">No project</option>
        {projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
       </select>
       <span id="chat-project-help" className="field-help">{projectNotice?projectNotice:projects.length?"Linking records which project this conversation belongs to. It stays private: project members gain no access to it.":"You have no projects to link yet."}</span>
      </div>
      <Button type="submit" disabled={busy}><Plus size={16}/> Create conversation</Button>
     </form>
     <div className="section-label chat-list-head">Your conversations · {conversations.length}</div>
     <div className="chat-list" role="group" aria-label="Conversations">
      {conversations.length?conversations.map(c=>(
       <button type="button" key={c.id} aria-pressed={selected===c.id} className={`space-choice ${selected===c.id?"selected":""}`} onClick={()=>setSelected(c.id)}>
        <strong>{c.title}</strong>
        <span>{c.owner_id===user.id?"Private · Owner":"Shared with you"}</span>
        {c.project_id&&<span className="chat-list-project">{projects.find(p=>p.id===c.project_id)?.name||"Linked project not visible to you"}</span>}
       </button>
      )):<p className="record-empty">Your conversations will appear here.</p>}
     </div>
    </div>
    <div className="surface-panel chat-panel">
     <div className="section-label">Invitations · {invitations.length}</div>
     {invitations.length?<div className="record-list">
      {invitations.map(inv=>(
       <div className="record" key={inv.id}>
        <div className="record-main">
         <strong>{inv.recipient_email||"@"+inv.recipient_alias}</strong>
         <small>{inv.permission} · Pending acceptance</small>
        </div>
        <Button variant="outline" size="sm" disabled={busy} onClick={()=>action(async()=>{await chatsApi.accept(user,inv.id);await refresh(inv.chat_id);setNotice("Invitation accepted.");})}><CheckCircle2 size={14}/> Accept</Button>
       </div>
      ))}
     </div>:<p className="record-empty">Nothing pending. Invites are visible only to their intended recipient.</p>}
     <form className="panel-section" onSubmit={e=>{e.preventDefault();action(async()=>{await chatsApi.saveAlias(user,alias);await refresh();setNotice("Your alias has been saved.");});}}>
      <div className="field-label">
       <label htmlFor="chat-alias">Your optional @alias</label>
       <Input id="chat-alias" aria-describedby="chat-alias-help" placeholder="e.g. alex_dev" maxLength={32} value={alias} onChange={e=>setAlias(e.target.value)}/>
       <span id="chat-alias-help" className="field-help">A registered alias lets teammates invite you without learning your email.</span>
      </div>
      <Button type="submit" disabled={busy} variant="outline" size="sm"><AtSign size={14}/> Save alias</Button>
     </form>
    </div>
   </div>
   <div className="surface-panel chat-thread">
    {loading?<p className="loading-line">Loading private conversations…</p>:!active?(
     <div className="chat-empty">
      <span className="chat-empty-mark"><MessageSquareText size={27}/></span>
      <h2>Discuss a project privately.</h2>
      <p>Create a conversation for a requirement, decision or review. Invite collaborators only when you want to share it.</p>
     </div>
    ):<>
     <header className="chat-thread-head">
      <div>
       <div className="section-label">Protected conversation</div>
       <h2>{active.title}</h2>
       {active.project_id&&<p className="chat-thread-link"><FolderGit2 size={13} aria-hidden="true"/> {projects.find(p=>p.id===active.project_id)?.name||"Linked project not visible to you"} · project members do not get this conversation</p>}
      </div>
      <Badge variant="outline">{isOwner?"Owner":canWrite?"Editor":"Viewer"}</Badge>
     </header>
     <div role="log" aria-label="Chat messages" aria-live="polite" className="chat-log">
      {olderOmitted&&<p className="muted-note">Showing the most recent {chatsApi.MESSAGE_WINDOW} messages. Older messages in this conversation are not shown here.</p>}
      {!detailsReady?<p className="muted-note">Loading this conversation…</p>:messages.length?messages.map(m=>(
       <article key={m.id} className={`chat-message ${m.author_id===user.id?"is-mine":""}`}>
        <small>{m.author_id===user.id?"You":"Collaborator"}</small>
        <p>{m.content}</p>
       </article>
      )):<p className="muted-note">No messages yet. You can start with a decision or a project brief.</p>}
     </div>
     {canWrite?<form className="chat-composer" onSubmit={e=>{e.preventDefault();action(async()=>{const submitted=message;const clean=submitted.trim();if(!clean||clean.length>4000)throw Error("Messages must be 1–4000 characters");await chatsApi.sendMessage(user,active.id,clean);clearSubmittedMessage(active.id,submitted);setRev(n=>n+1);});}}>
      <div className="field-label">
       <label htmlFor="chat-compose">Message</label>
       <Textarea id="chat-compose" required maxLength={4000} value={message} onChange={e=>setMessage(e.target.value)} placeholder="Write a thought, decision or review note…"/>
      </div>
      <div className="chat-composer-actions"><Button type="submit" disabled={busy}><Send size={15}/> Send message</Button></div>
     </form>:<div className="read-only-note">You have view-only access. Ask the owner to grant editor access if needed.</div>}
     {isOwner?<section className="panel-section">
       <h3 className="panel-subhead"><UserPlus size={18}/> Share intentionally</h3>
       <p className="muted-note">Invite by Outlook, work email, Gmail or an existing @alias. Recipients cannot read until they accept in-app.</p>
       <form className="invite-grid" onSubmit={e=>{e.preventDefault();action(async()=>{
        await chatsApi.invite(user,active.id,recipient,permission);
        if(!mounted.current)return;
        setChatDraft(current=>current.recipients[active.id]!==recipient?current:{...current,recipients:{...current.recipients,[active.id]:""}});
        setRev(n=>n+1);setNotice("In-app invitation created. Recipient must accept to gain access.");});}}>
        <div className="field-label">
         <label htmlFor="chat-invite-recipient">Recipient</label>
         <Input id="chat-invite-recipient" required maxLength={254} placeholder="user@company.com or @alias" value={recipient} onChange={e=>setRecipient(e.target.value)}/>
        </div>
        <div className="field-label">
         <label htmlFor="chat-invite-access">Access</label>
         <select id="chat-invite-access" value={permission} onChange={e=>setPermission(e.target.value)}>
          <option value="viewer">Can view</option>
          <option value="editor">Can add</option>
         </select>
        </div>
        <Button type="submit" disabled={busy}>Invite <ArrowRight size={15}/></Button>
       </form>
       <div className="record-list">
        {!detailsReady?<p className="record-empty">Loading this conversation's invitations…</p>:shares.length?shares.map(share=>(
         <div key={share.id} className="record">
          <div className="record-main">
           <strong>{share.recipient_email||"@"+share.recipient_alias}</strong>
           <small>{share.permission} · {share.status}</small>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={()=>action(async()=>{await chatsApi.revoke(share.id,active.id);setRev(n=>n+1);setNotice("Access revoked.");})}>Revoke</Button>
         </div>
        )):<p className="record-empty">No invitations yet. This chat remains private.</p>}
       </div>
       <button type="button" className="danger-link" disabled={busy} onClick={()=>{if(!window.confirm("Permanently delete this conversation and all messages?"))return;action(async()=>{await chatsApi.deleteChat(active.id);await refresh(null);setNotice("Conversation permanently deleted.");});}}><Trash2 size={14}/> Delete conversation</button>
      </section>:<p className="muted-note panel-section">Only the owner manages sharing and can revoke access.</p>}
     <p className="fine-print">This chat stores human messages securely; hosted AI responses and automatic email notifications are not connected.</p>
    </>}
   </div>
  </div>
 </>;
}
