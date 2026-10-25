/* Data access for private chats. PostgreSQL RLS—not client filters—authorizes reads/writes. */
import {supabase} from "./identity.js";
/* Missing-column/relation codes mean the private chats or projects migration is not applied yet. */
const MISSING_SCHEMA=["42P01","42703","PGRST204","PGRST205"];
function data(result,context){if(!result.error)return result.data;if(MISSING_SCHEMA.includes(result.error.code))throw Error("Conversations are unavailable until the private chats and projects migrations are applied to this Supabase project.");throw new Error(result.error.message||context);}
export async function listChats(){return data(await supabase.from("chats").select("id,title,owner_id,workspace_id,project_id,created_at").order("created_at",{ascending:false}).limit(100),"Could not load chats")||[];}
/* projectId is an explicit association chosen by the creator; it grants no one else access to this chat.
   Association is set at creation only: there is no client-side project reassignment. */
export async function createChat(user,workspaceId,title,projectId){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("chats").insert({owner_id:user.id,workspace_id:workspaceId||null,project_id:projectId||null,title}).select("id,title,owner_id,workspace_id,project_id,created_at").single(),"Could not create chat");}
export async function deleteChat(id){data(await supabase.from("chats").delete().eq("id",id),"Could not delete conversation");}
/* One bounded page of conversation history. */
export const MESSAGE_WINDOW=200;
/* The newest window, not the oldest: a conversation keeps accepting messages, so reading from
   the start of it would hide every message past the window, including one just sent.
   (created_at,id) descending matches chat_messages_order_idx and stays deterministic when
   messages share a creation timestamp. One row beyond the window is read so that omitted older
   history is reported only when it actually exists; the window itself stays bounded.
   Messages are returned oldest-first for display. */
export async function listMessages(id){
 const rows=data(await supabase.from("chat_messages").select("id,chat_id,author_id,content,created_at").eq("chat_id",id).order("created_at",{ascending:false}).order("id",{ascending:false}).limit(MESSAGE_WINDOW+1),"Could not load messages")||[];
 return {messages:rows.slice(0,MESSAGE_WINDOW).reverse(),olderOmitted:rows.length>MESSAGE_WINDOW};
}
export async function sendMessage(user,id,content){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("chat_messages").insert({chat_id:id,author_id:user.id,role:"user",content}).select("id,content").single(),"Could not send message");}
export async function listInvitations(user){if(!user?.id)throw Error("Authentication required");const result=data(await supabase.from("chat_shares").select("id,chat_id,invited_by,recipient_email,recipient_alias,permission,status,accepted_by").eq("status","pending").limit(100),"Could not load invitations")||[];return result.filter(row=>row.invited_by!==user.id);}
export async function listShares(id){return data(await supabase.from("chat_shares").select("id,chat_id,invited_by,recipient_email,recipient_alias,permission,status,accepted_by").eq("chat_id",id).limit(100),"Could not load shares")||[];}
export async function invite(user,id,recipient,permission){
 if(!user?.id)throw Error("Authentication required");
 const value=String(recipient||"").trim().toLowerCase();
 const alias=value.startsWith("@");
 if(alias?!/^@[a-z][a-z0-9_]{2,31}$/.test(value):!(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)&&value.length<=254))throw Error("Use an email address or registered @alias");
 if(!["viewer","editor"].includes(permission))throw Error("Invalid access level");
 return data(await supabase.from("chat_shares").insert({chat_id:id,invited_by:user.id,permission,...(alias?{recipient_alias:value.slice(1)}:{recipient_email:value})}).select("id,status").single(),"Could not invite user");
}
export async function accept(user,id){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("chat_shares").update({status:"accepted",accepted_by:user.id,accepted_at:new Date().toISOString()}).eq("id",id).eq("status","pending").select("id,chat_id").single(),"Could not accept invite");}
/* The chat is part of the identity of what is being revoked: owners may delete shares in any
   conversation they own, so the intended conversation must be named, not inferred on screen. */
export async function revoke(id,chatId){if(!chatId)throw Error("Select a conversation first");data(await supabase.from("chat_shares").delete().eq("id",id).eq("chat_id",chatId),"Could not revoke access");}
export async function getAlias(user){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("user_aliases").select("alias").eq("user_id",user.id).maybeSingle(),"Could not load alias")?.alias||"";}
export async function saveAlias(user,alias){
 if(!user?.id)throw Error("Authentication required");
 const value=String(alias||"").trim().toLowerCase().replace(/^@/,"");
 if(!/^[a-z][a-z0-9_]{2,31}$/.test(value))throw Error("Use 3–32 lowercase letters, numbers or underscores");
 const previous=await getAlias(user);
 data(previous?await supabase.from("user_aliases").update({alias:value}).eq("user_id",user.id):await supabase.from("user_aliases").insert({user_id:user.id,alias:value}),"Could not save alias");
 return value;
}
