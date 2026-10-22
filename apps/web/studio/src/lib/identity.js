import { createClient } from "@supabase/supabase-js";
import { DEFAULT_SUPABASE_URL, DEFAULT_SUPABASE_PUBLISHABLE_KEY } from "./publicConfig.js";
/* Public browser configuration. Defaults are the deployed Oryveta project values;
   never a secret/service-role key. */
const url =
  (import.meta.env.VITE_SUPABASE_URL || DEFAULT_SUPABASE_URL).replace(/\/+$/, "");
const key =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  DEFAULT_SUPABASE_PUBLISHABLE_KEY;
export const supabase = createClient(url, key, {
  auth: {
    flowType: "pkce",
    detectSessionInUrl: true,
    persistSession: true,
    autoRefreshToken: true,
    // Shared browser storage lets an emailed PKCE link open in a new tab.
    storage: window.localStorage,
  },
});
/* Provider availability is read from the project's own auth settings, never declared
   by a hard-coded flag. Resolves to the GoTrue "external" map; rejects when the real
   configuration cannot be confirmed so the UI can say so instead of guessing. */
let providerRequest = null;
export function authProviders() {
  if (!providerRequest)
    providerRequest = fetch(`${url}/auth/v1/settings`, {
      headers: { apikey: key },
      credentials: "omit",
    })
      .then((response) =>
        response.ok
          ? response.json()
          : Promise.reject(
              Error(
                `Sign-in providers could not be confirmed (HTTP ${response.status})`,
              ),
            ),
      )
      .then((settings) => {
        const external = settings?.external;
        if (!external || typeof external !== "object")
          throw Error("Sign-in providers could not be confirmed");
        return external;
      })
      .catch((error) => {
        providerRequest = null;
        throw error;
      });
  return providerRequest;
}
export async function providerEnabled(name) {
  const external = await authProviders();
  return external[name] === true;
}
export async function verifiedUser() {
  const { error: initializationError } = await supabase.auth.initialize();
  const {
    data: { session },
    error: e1,
  } = await supabase.auth.getSession();
  if (e1) throw e1;
  if (!session) {
    if (initializationError || new URLSearchParams(window.location.search).has("code"))
      throw Error("Sign-in did not complete. Request a new link in this browser.");
    return null;
  }
  const { data, error } = await supabase.auth.getUser();
  if (error) throw error;
  return data.user || null;
}
export async function sendEmailLink(email) {
  const clean = email.trim().toLowerCase();
  if (clean.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean))
    throw Error("Enter a valid email address");
  const { error } = await supabase.auth.signInWithOtp({
    email: clean,
    options: {
      emailRedirectTo: window.location.origin + "/",
      shouldCreateUser: true,
    },
  });
  if (error) throw error;
}
export async function signInWithGitHub() {
  if (!(await providerEnabled("github")))
    throw Error(
      "GitHub sign-in is not enabled for this Supabase project. Use the email link instead.",
    );
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "github",
    options: {
      redirectTo: window.location.origin + "/",
      scopes: "read:user user:email",
    },
  });
  if (error) throw error;
}
export async function listWorkspaces() {
  const { data, error } = await supabase
    .from("workspaces")
    .select("id,name,slug,description,created_by,created_at,updated_at")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data || [];
}
export async function createWorkspace(user, { name, slug, description }) {
  if (!user) throw Error("Not authenticated");
  const { data, error } = await supabase
    .from("workspaces")
    .insert({ created_by: user.id, name, slug, description })
    .select("id,name,slug,description,created_by,created_at,updated_at")
    .single();
  if (error) throw error;
  return data;
}
export async function updateWorkspace(id, { name, description }) {
  const { data, error } = await supabase
    .from("workspaces")
    .update({ name, description })
    .eq("id", id)
    .select("id,name,slug,description,created_by,created_at,updated_at")
    .single();
  if (error) throw error;
  return data;
}
