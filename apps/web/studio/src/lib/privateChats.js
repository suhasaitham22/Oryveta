/* Data access for private chats. PostgreSQL RLS—not client filters—authorizes reads/writes. */
import {supabase} from "./identity.js";
function data(result,context){if(result.error)throw new Error(result.error.message||context);return result.data;}
export async function listChats(){return data(await supabase.from("chats").select("id,title,owner_id,workspace_id,created_at").order("created_at",{ascending:false}).limit(100),"Could not load chats")||[];}
export async function createChat(user,workspaceId,title){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("chats").insert({owner_id:user.id,workspace_id:workspaceId||null,title}).select("id,title,owner_id,workspace_id,created_at").single(),"Could not create chat");}
export async function deleteChat(id){data(await supabase.from("chats").delete().eq("id",id),"Could not delete conversation");}
export async function listMessages(id){return data(await supabase.from("chat_messages").select("id,chat_id,author_id,content,created_at").eq("chat_id",id).order("created_at").limit(200),"Could not load messages")||[];}
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
export async function revoke(id){data(await supabase.from("chat_shares").delete().eq("id",id),"Could not revoke access");}
export async function getAlias(user){if(!user?.id)throw Error("Authentication required");return data(await supabase.from("user_aliases").select("alias").eq("user_id",user.id).maybeSingle(),"Could not load alias")?.alias||"";}
export async function saveAlias(user,alias){
 if(!user?.id)throw Error("Authentication required");
 const value=String(alias||"").trim().toLowerCase().replace(/^@/,"");
 if(!/^[a-z][a-z0-9_]{2,31}$/.test(value))throw Error("Use 3–32 lowercase letters, numbers or underscores");
 const previous=await getAlias(user);
 data(previous?await supabase.from("user_aliases").update({alias:value}).eq("user_id",user.id):await supabase.from("user_aliases").insert({user_id:user.id,alias:value}),"Could not save alias");
 return value;
}
