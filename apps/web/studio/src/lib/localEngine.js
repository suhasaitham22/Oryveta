import {useCallback, useEffect, useState} from "react";

// Local cookies and CSRF stay on this origin. Supabase tokens never enter this client.
export async function engineRequest(path, {csrf, body, headers = {}, ...options} = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {...(csrf ? {"X-Oryveta-CSRF": csrf} : {}), ...headers},
    body,
  });
  if (response.status === 204) return null;
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("No same-origin Oryveta engine is available. The hosted studio cannot run local jobs.");
  }
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : `Engine request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

export function useLocalEngine(enabled) {
  const [connection, setConnection] = useState({status: enabled ? "checking" : "unavailable", config: null, user: null, error: ""});
  const connect = useCallback(async (signal) => {
    try {
      const config = await engineRequest("/api/config", {signal});
      if (config.name !== "Oryveta" || typeof config.local_demo_enabled !== "boolean") {
        throw new Error("This origin does not expose the Oryveta local engine.");
      }
      let user = null;
      try { user = await engineRequest("/api/me", {signal}); }
      catch (error) { if (error.status !== 401) throw error; }
      setConnection({status: user ? "ready" : "signed-out", config, user, error: ""});
    } catch (error) {
      if (error.name !== "AbortError") setConnection({status: "unavailable", config: null, user: null, error: error.message});
    }
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    connect(controller.signal);
    return () => controller.abort();
  }, [enabled, connect]);
  async function signIn() {
    await engineRequest("/auth/local-demo", {method: "POST"});
    await connect();
  }
  async function signOut() {
    await engineRequest("/auth/logout", {method: "POST", csrf: connection.user?.csrf_token});
    setConnection(value => ({...value, status: "signed-out", user: null}));
  }
  const request = useCallback((path, options = {}) => engineRequest(path, {
    ...options, csrf: connection.user?.csrf_token,
  }), [connection.user?.csrf_token]);
  return {...connection, request, signIn, signOut};
}
