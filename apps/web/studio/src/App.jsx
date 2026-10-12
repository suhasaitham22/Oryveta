import React, {useEffect, useState} from "react";
import {ArrowRight, Github, LockKeyhole, Mail} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Input} from "@/components/ui/input";
import Brand from "@/components/Brand.jsx";
import {supabase, verifiedUser, sendEmailLink, signInWithGitHub, oauthGitHubEnabled} from "@/lib/identity";
import Workspace from "./pages/Workspace.jsx";
import Landing from "./pages/Landing.jsx";

const selfHosted = window.location.pathname === "/studio" || window.location.pathname.startsWith("/studio/");

export default function App() {
  const [mode, setMode] = useState(selfHosted ? "local" : "landing");
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(!selfHosted);
  const [stories, setStories] = useState([]);
  const [initialPage, setInitialPage] = useState("overview");
  const [toast, setToast] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}demo-stories.json`, {signal: controller.signal})
      .then(response => response.ok ? response.json() : Promise.reject(new Error("Story manifest unavailable")))
      .then(value => {if (Array.isArray(value)) setStories(value);})
      .catch(error => {if (error.name !== "AbortError") setStories([]);});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (selfHosted) return;
    let live = true;
    async function verify() {
      try {
        const value = await verifiedUser();
        if (live && value) {setUser(value); setMode("workspace");}
      } catch {if (live) setToast("We couldn't restore your session. You can try signing in again.");}
      finally {if (live) setChecking(false);}
    }
    verify();
    const {data: {subscription}} = supabase.auth.onAuthStateChange((event, session) => {
      if (!live) return;
      if (session) setTimeout(verify, 0);
      else if (event === "SIGNED_OUT") {setUser(null); setMode("landing");}
    });
    return () => {live = false; subscription.unsubscribe();};
  }, []);
  function preview(page = "overview") {
    setInitialPage(page); setMode("preview"); window.scrollTo(0, 0);
  }
  async function exit() {
    if (selfHosted) {window.location.assign("/"); return;}
    if (user) {
      const {error} = await supabase.auth.signOut();
      if (error) {setToast(error.message); return;}
      setUser(null);
    }
    setMode("landing"); window.scrollTo(0, 0);
  }
  if (checking) return <div className="boot-screen" role="status"><Brand/><p>Restoring your workspace…</p></div>;
  if (mode !== "landing") return <><Workspace key={mode} user={user} preview={mode === "preview"} onExit={exit} stories={stories} initialPage={initialPage} selfHosted={selfHosted}/>{toast && <div role="alert" className="toast">{toast}<button onClick={() => setToast("")} aria-label="Dismiss notification">Dismiss</button></div>}</>;
  return <Landing onPreview={preview} toast={toast} onDismiss={() => setToast("")}><LoginCard onPreview={() => preview("overview")}/></Landing>;
}

function LoginCard({onPreview}) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(""); setSent(false);
    try {await sendEmailLink(email); setSent(true);} catch (error) {setError(error.message);} finally {setBusy(false);}
  }
  return <div className="auth-panel"><div className="section-label"><LockKeyhole size={15}/> Your private workspace</div><h3>Good work starts with clarity.</h3><p>Continue with a secure email link.</p><form onSubmit={submit}><label className="field-label" htmlFor="login-email">Your work email<Input id="login-email" type="email" required maxLength={254} autoComplete="email" placeholder="you@company.com" value={email} onChange={event => {setEmail(event.target.value); setError(""); setSent(false);}}/></label><Button type="submit" className="w-full" disabled={busy}><Mail size={16}/>{busy ? "Requesting secure link…" : "Continue with email"}<ArrowRight size={15}/></Button>{sent && <p role="status" className="notice">If email delivery is configured, a single-use sign-in link has been sent. Check your inbox.</p>}{error && <p role="alert" className="alert-error">{error}</p>}</form><Button className="w-full mt-3" variant="outline" disabled={!oauthGitHubEnabled || busy} onClick={async () => {try {await signInWithGitHub();} catch (error) {setError(error.message);}}}><Github size={16}/>Continue with GitHub</Button>{!oauthGitHubEnabled && <p className="fine-print text-center">GitHub sign-in needs OAuth setup.</p>}<Button variant="ghost" className="w-full" onClick={onPreview}>Explore without signing in <ArrowRight size={15}/></Button><p className="auth-footnote">Passwordless identity is provided by Supabase Auth. Brief and storyboard drafts are not saved to your account; export them to keep a copy.</p></div>;
}
