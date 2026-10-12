import React,{useEffect,useState} from "react";
import {AtSign,ArrowRight,CheckCircle2,LockKeyhole,MessageSquareText,Plus,Send,ShieldCheck,Trash2,UserPlus,UsersRound} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {Card} from "@/components/ui/card";
import {Input} from "@/components/ui/input";
import {Textarea} from "@/components/ui/textarea";
import * as chatsApi from "@/lib/privateChats.js";

/* This UI never treats a workspace membership as consent to read a conversation. */
export default function PrivateChats({user,preview,workspaceId,onExit}){
 const [conversations,setConversations]=useState([]);
 const [invitations,setInvitations]=useState([]);
 const [alias,setAlias]=useState("");
 const [selected,setSelected]=useState(null);
 const [messages,setMessages]=useState([]);
 const [shares,setShares]=useState([]);
 const [title,setTitle]=useState("");
 const [message,setMessage]=useState("");
 const [recipient,setRecipient]=useState("");
 const [permission,setPermission]=useState("viewer");
 const [busy,setBusy]=useState(false);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");
 const [rev,setRev]=useState(0);
 const active=conversations.find(c=>c.id===selected)||null;
 const isOwner=!!active&&active.owner_id===user?.id;
 const canWrite=isOwner||shares.some(s=>s.status==="accepted"&&s.accepted_by===user?.id&&s.permission==="editor");
 async function refresh(prefer){
  if(preview||!user)return;
  const [items,inbox,handle]=await Promise.all([chatsApi.listChats(),chatsApi.listInvitations(user),chatsApi.getAlias(user)]);
  setConversations(items);setInvitations(inbox);setAlias(handle);
  setSelected(old=>items.some(c=>c.id===(prefer||old))?(prefer||old):items[0]?.id||null);
  setRev(x=>x+1);
 }
 useEffect(()=>{if(!preview&&user){setLoading(true);refresh().catch(e=>setError(e.message)).finally(()=>setLoading(false));}},[preview,user?.id]);
 useEffect(()=>{
  if(!selected||preview){setMessages([]);setShares([]);return;}
  let alive=true;
  Promise.all([chatsApi.listMessages(selected),chatsApi.listShares(selected)]).then(([m,s])=>{if(alive){setMessages(m);setShares(s);}}).catch(e=>{if(alive)setError(e.message)});
  return()=>{alive=false};
 },[selected,rev,preview]);
 async function action(task){
  if(busy||preview||!user)return;
  setBusy(true);setError("");setNotice("");
  try{await task();}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 if(preview)return <div className="max-w-4xl"><div className="eyebrow">PRIVATE CONVERSATIONS</div><h1 className="font-display text-3xl md:text-5xl tracking-tight font-bold text-slate-800 mt-3">Private chats need a real account.</h1><Card className="p-7 md:p-10 mt-8"><LockKeyhole size={32} className="text-indigo-500"/><p className="text-sm leading-7 text-slate-500 max-w-lg mt-5">Preview mode has no access to other people's chats, invitations or saved messages. Sign in to create your own, then explicitly invite teammates by email or @alias.</p><Button className="mt-6" onClick={onExit}>Return to sign in <ArrowRight size={16}/></Button></Card></div>;
 return <div>
  <div className="eyebrow">CONVERSATIONS / CONFIDENTIAL</div>
  <h1 className="font-display text-3xl md:text-5xl tracking-tight font-bold text-slate-800 mt-3">Your thinking stays yours.</h1>
  <p className="text-slate-500 leading-7 text-sm max-w-3xl mt-3">Conversations are private to their creator. Share only with specific verified accounts that accept your invitation.</p>
  <div className="rounded-2xl border border-indigo-200/70 bg-indigo-50/70 p-4 flex items-start gap-3 text-xs text-indigo-800 mt-7 mb-6"><ShieldCheck size={19} className="shrink-0 text-indigo-500"/><span>Workspace membership alone never grants access. Invitations are in-app, not emails; a pending invitation reveals no messages.</span></div>
  {error&&<div role="alert" className="alert-error mb-5">{error}</div>}
  {notice&&<div role="status" className="alert-success mb-5">{notice}</div>}
  <div className="grid xl:grid-cols-[310px_minmax(0,1fr)] gap-5 items-start">
   <div className="space-y-4">
    <Card className="p-5">
     <form onSubmit={e=>{e.preventDefault();action(async()=>{const clean=title.trim();if(!clean||clean.length>120)throw Error("Enter a title up to 120 characters");const created=await chatsApi.createChat(user,workspaceId,clean);setTitle("");await refresh(created.id);setNotice("Private conversation created.");});}}>
      <label htmlFor="chat-title" className="block text-xs font-bold text-slate-600 mb-2">New private conversation</label>
      <Input id="chat-title" required maxLength={120} placeholder="What are we deciding?" value={title} onChange={e=>setTitle(e.target.value)}/>
      <Button type="submit" disabled={busy} className="w-full mt-3"><Plus size={16}/> Create conversation</Button>
     </form>
     <div className="eyebrow mt-9 mb-3">YOUR CONVERSATIONS · {conversations.length}</div>
     <div className="grid gap-2" aria-label="Conversations">{conversations.length?conversations.map(c=><button type="button" key={c.id} onClick={()=>setSelected(c.id)} className={"rounded-xl border p-3.5 text-left transition-all "+(selected===c.id?"bg-indigo-50 border-indigo-300":"bg-white/70 border-slate-100 hover:border-indigo-200")}><strong className="text-xs font-bold text-slate-700 block truncate">{c.title}</strong><small className="text-[11px] text-slate-400 mt-2 block">{c.owner_id===user.id?"Private · Owner":"Shared with you"}</small></button>):<p className="text-xs text-slate-400 leading-6">Your conversations will appear here.</p>}</div>
    </Card>
    <Card className="p-5">
     <div className="eyebrow mb-4">INVITATIONS · {invitations.length}</div>
     {invitations.length?invitations.map(inv=><div className="rounded-xl border border-slate-100 p-3 mb-3" key={inv.id}><div className="text-xs font-bold text-slate-700 truncate">{inv.recipient_email||"@"+inv.recipient_alias}</div><p className="text-[11px] text-slate-400 my-2">{inv.permission} · Pending acceptance</p><Button variant="outline" size="sm" disabled={busy} onClick={()=>action(async()=>{await chatsApi.accept(user,inv.id);await refresh(inv.chat_id);setNotice("Invitation accepted.");})}><CheckCircle2 size={14}/> Accept</Button></div>):<p className="text-xs text-slate-400 leading-6">Nothing pending. Invites are visible only to their intended recipient.</p>}
     <form className="border-t border-indigo-100 mt-5 pt-5" onSubmit={e=>{e.preventDefault();action(async()=>{await chatsApi.saveAlias(user,alias);await refresh();setNotice("Your alias has been saved.");});}}>
      <label htmlFor="chat-alias" className="text-xs font-bold text-slate-600 block mb-2">Your optional @alias</label><Input id="chat-alias" placeholder="e.g. alex_dev" maxLength={32} value={alias} onChange={e=>setAlias(e.target.value)}/><p className="text-[11px] text-slate-400 leading-5 mt-2">A registered alias lets teammates invite you without learning your email.</p><Button type="submit" disabled={busy} variant="outline" size="sm" className="mt-3"><AtSign size={14}/> Save alias</Button>
     </form>
    </Card>
   </div>
   <Card className="p-6 md:p-8 min-h-[540px] bg-white/85">
    {loading?<p className="text-sm text-slate-400">Loading private conversations…</p>:!active?<div className="flex flex-col items-center justify-center text-center min-h-[450px]"><span className="w-16 h-16 rounded-2xl bg-indigo-50 text-indigo-500 grid place-items-center"><MessageSquareText size={29}/></span><h2 className="font-display font-bold text-2xl text-slate-800 mt-5">A private place for your best thinking.</h2><p className="text-sm text-slate-500 mt-3 max-w-md leading-7">Create a conversation to keep decisions, plans and reviews in one place. No one else can see it until you share.</p></div>:<>
     <header className="flex gap-3 justify-between items-center border-b border-slate-100 pb-5"><div><div className="eyebrow">PROTECTED CONVERSATION</div><h2 className="font-display text-xl md:text-2xl font-bold tracking-tight text-slate-800 mt-2">{active.title}</h2></div><Badge variant="outline">{isOwner?"Owner":canWrite?"Editor":"Viewer"}</Badge></header>
     <div role="log" aria-label="Chat messages" aria-live="polite" className="min-h-[180px] max-h-[400px] overflow-y-auto py-6 flex flex-col gap-3">
      {messages.length?messages.map(m=><article key={m.id} className={"rounded-2xl px-4 py-3 text-sm max-w-[90%] border "+(m.author_id===user.id?"self-end bg-indigo-50 border-indigo-100":"self-start bg-white border-slate-100")}><small className="text-indigo-500 text-[10px] font-bold">{m.author_id===user.id?"You":"Collaborator"}</small><p className="whitespace-pre-wrap break-words leading-6 text-slate-700 mt-1">{m.content}</p></article>):<p className="text-xs text-slate-400">No messages yet. You can start with a decision or a project brief.</p>}
     </div>
     {canWrite?<form className="border-t border-slate-100 pt-5" onSubmit={e=>{e.preventDefault();action(async()=>{const clean=message.trim();if(!clean||clean.length>4000)throw Error("Messages must be 1–4000 characters");await chatsApi.sendMessage(user,active.id,clean);setMessage("");setRev(n=>n+1);});}}><label htmlFor="chat-compose" className="text-xs font-bold text-slate-600 block mb-2">Message</label><Textarea id="chat-compose" required maxLength={4000} value={message} onChange={e=>setMessage(e.target.value)} placeholder="Write a thought, decision or review note…"/><div className="flex justify-end mt-3"><Button type="submit" disabled={busy}><Send size={15}/> Send message</Button></div></form>:<div className="text-xs text-slate-500 bg-slate-50 rounded-xl p-4">You have view-only access. Ask the owner to grant editor access if needed.</div>}
     {isOwner?<section className="border-t border-slate-100 mt-7 pt-6">
       <h3 className="text-sm font-bold text-slate-800 flex gap-2 items-center"><UserPlus size={18} className="text-indigo-500"/> Share intentionally</h3>
       <p className="text-xs text-slate-500 leading-6 mt-2">Invite by Outlook, work email, Gmail or an existing @alias. Recipients cannot read until they accept in-app.</p>
       <form className="grid sm:grid-cols-[1fr_130px_auto] gap-3 mt-4 items-end" onSubmit={e=>{e.preventDefault();action(async()=>{await chatsApi.invite(user,active.id,recipient,permission);setRecipient("");setRev(n=>n+1);setNotice("In-app invitation created. Recipient must accept to gain access.");});}}>
        <label className="text-[11px] font-bold text-slate-600">Recipient<Input className="mt-2" required maxLength={254} placeholder="user@company.com or @alias" value={recipient} onChange={e=>setRecipient(e.target.value)}/></label>
        <label className="text-[11px] font-bold text-slate-600">Access<select className="w-full mt-2 h-10 rounded-xl border border-slate-200 px-2 text-xs text-slate-600 bg-white" value={permission} onChange={e=>setPermission(e.target.value)}><option value="viewer">Can view</option><option value="editor">Can add</option></select></label>
        <Button type="submit" disabled={busy}>Invite <ArrowRight size={15}/></Button>
       </form>
       <div className="grid gap-2 mt-5">{shares.length?shares.map(share=><div key={share.id} className="flex flex-wrap justify-between items-center gap-3 border rounded-xl border-slate-100 p-3"><div className="min-w-0"><strong className="text-xs text-slate-700 break-words">{share.recipient_email||"@"+share.recipient_alias}</strong><small className="text-[11px] text-slate-400 block mt-1">{share.permission} · {share.status}</small></div><Button variant="outline" size="sm" disabled={busy} onClick={()=>action(async()=>{await chatsApi.revoke(share.id);setRev(n=>n+1);setNotice("Access revoked.");})}>Revoke</Button></div>):<p className="text-xs text-slate-400">No invitations yet. This chat remains private.</p>}</div>
       <button type="button" className="text-[11px] text-rose-500 hover:underline mt-8 flex gap-2 items-center" disabled={busy} onClick={()=>{if(!window.confirm("Permanently delete this conversation and all messages?"))return;action(async()=>{await chatsApi.deleteChat(active.id);await refresh(null);setNotice("Conversation permanently deleted.");});}}><Trash2 size={14}/> Delete conversation</button>
      </section>:<p className="text-xs text-slate-400 mt-6 border-t pt-5 border-slate-100">Only the owner manages sharing and can revoke access.</p>}
     <p className="text-[11px] text-slate-400 leading-5 mt-6">This chat stores human messages securely; hosted AI responses and automatic email notifications are not connected.</p>
    </>}
   </Card>
  </div>
 </div>;
}
