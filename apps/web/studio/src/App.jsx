import RoutePresentation from "./components/RoutePresentation.jsx";
import React, { lazy, Suspense, useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { ArrowRight, Github, LockKeyhole, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import SiteHeader from "@/components/SiteHeader.jsx";
import {
  supabase,
  verifiedUser,
  sendEmailLink,
  signInWithGitHub,
  oauthGitHubEnabled,
} from "@/lib/identity";
import { WorkspaceState } from "@/lib/WorkspaceState.jsx";
import { useLocalEngine } from "@/lib/localEngine";
import Footer from "./components/SiteFooter.jsx";

const Workspace = lazy(() => import("./pages/Workspace.jsx"));
const Home = lazy(() =>
  import("./pages/PublicPages.jsx").then((module) => ({
    default: module.Home,
  })),
);
const About = lazy(() =>
  import("./pages/PublicPages.jsx").then((module) => ({
    default: module.About,
  })),
);
const WhatWeDo = lazy(() =>
  import("./pages/PublicPages.jsx").then((module) => ({
    default: module.WhatWeDo,
  })),
);
const NotFound = lazy(() =>
  import("./pages/PublicPages.jsx").then((module) => ({
    default: module.NotFound,
  })),
);
const selfHosted = import.meta.env.BASE_URL === "/studio/";

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Application />
    </BrowserRouter>
  );
}
function Application() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(!selfHosted);
  const [stories, setStories] = useState([]);
  const [toast, setToast] = useState("");
  const engine = useLocalEngine(selfHosted);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}demo-stories.json`, {
      signal: controller.signal,
    })
      .then((response) =>
        response.ok
          ? response.json()
          : Promise.reject(new Error("Story manifest unavailable")),
      )
      .then((value) => {
        if (!controller.signal.aborted && Array.isArray(value))
          setStories(value);
      })
      .catch((error) => {
        if (error.name !== "AbortError") setStories([]);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (selfHosted) return;
    let live = true,
      revision = 0,
      timer;
    async function verify() {
      const request = ++revision;
      try {
        const value = await verifiedUser();
        if (live && request === revision) setUser(value);
      } catch {
        if (live && request === revision) {
          setUser(null);
          setToast(
            "We couldn't restore your session. You can try signing in again.",
          );
        }
      } finally {
        if (live && request === revision) setChecking(false);
      }
    }
    verify();
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (!live) return;
      clearTimeout(timer);
      if (session) {
        revision++;
        setUser((current) =>
          current?.id === session.user.id ? current : null,
        );
        if (event === "SIGNED_IN") setChecking(true);
        timer = setTimeout(verify, 0);
      } else if (event === "SIGNED_OUT") {
        revision++;
        setUser(null);
        setChecking(false);
      }
    });
    return () => {
      live = false;
      revision++;
      clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, []);
  async function signOut() {
    const { error } = await supabase.auth.signOut();
    if (error) {
      setToast(error.message);
      return;
    }
    setUser(null);
    navigate("/");
  }
  const owner = selfHosted
    ? `local:${engine.ownerRevision}`
    : user?.id || "guest";
  const workspace = (
    <Workspace
      user={user}
      preview={!user && !selfHosted}
      onExit={() => navigate("/sign-in")}
      stories={stories}
      selfHosted={selfHosted}
      engine={engine}
    />
  );
  return (
    <>
      <SiteHeader
        key={location.pathname}
        user={user}
        onSignOut={signOut}
        selfHosted={selfHosted}
      />
      <WorkspaceState key={owner}>
        <Suspense
          fallback={
            <main
              id="main-content"
              tabIndex={-1}
              className="route-loading"
              role="status"
            >
              Opening page…
            </main>
          }
        >
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/about" element={<About />} />
            <Route path="/what-we-do" element={<WhatWeDo />} />
            <Route
              path="/sign-in"
              element={<SignIn user={user} selfHosted={selfHosted} />}
            />
            {[
              "/workspace",
              "/workspace/new",
              "/workspace/evolve",
              "/workspace/settings",
              "/workspace/chats",
              "/workspace/activity",
            ].map((path) => (
              <Route
                key={path}
                path={path}
                element={
                  checking ? (
                    <main
                      id="main-content"
                      tabIndex={-1}
                      className="route-loading"
                      role="status"
                    >
                      Restoring your session…
                    </main>
                  ) : (
                    workspace
                  )
                }
              />
            ))}
            <Route path="*" element={<NotFound />} />
          </Routes>
          <RoutePresentation checking={checking} />
        </Suspense>
      </WorkspaceState>
      {!location.pathname.startsWith("/workspace") && <Footer />}
      {toast && (
        <div role="alert" className="toast">
          {toast}
          <button
            onClick={() => setToast("")}
            aria-label="Dismiss notification"
          >
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}
function SignIn({ user, selfHosted }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSent(false);
    try {
      await sendEmailLink(email);
      setSent(true);
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="signin-page section-container"
    >
      <div>
        <span className="section-label">
          <LockKeyhole size={15} />
          Your private workspace
        </span>
        <h1>
          Good work starts
          <br />
          with clarity.
        </h1>
        <p>
          Hosted sign-in adds workspace membership and private human
          conversations. It never grants access to your local engine.
        </p>
        <p>
          Briefs and storyboards remain in this open browser session. Export a
          copy to keep them.
        </p>
      </div>
      {selfHosted ? (
        <div className="surface-panel">
          <h2>You're in the local edition.</h2>
          <p>
            Use Local run inside a journey to connect to this engine. Hosted
            Supabase identity is separate; no tokens or cookies are forwarded.
          </p>
          <Button asChild>
            <Link to="/workspace">Open local workspace</Link>
          </Button>
        </div>
      ) : user ? (
        <div className="surface-panel">
          <h2>You're signed in.</h2>
          <p>
            Continue to your workspace, or use the navigation to explore the
            site without ending your session.
          </p>
          <Button asChild>
            <Link to="/workspace">
              Continue to workspace <ArrowRight size={16} />
            </Link>
          </Button>
        </div>
      ) : (
        <div className="auth-panel">
          <h2>Continue with a secure email link.</h2>
          <form onSubmit={submit}>
            <label className="field-label" htmlFor="login-email">
              Your work email
              <Input
                id="login-email"
                type="email"
                required
                maxLength={254}
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setError("");
                  setSent(false);
                }}
              />
            </label>
            <Button type="submit" className="w-full" disabled={busy}>
              <Mail size={16} />
              {busy ? "Requesting secure link…" : "Continue with email"}
              <ArrowRight size={15} />
            </Button>
            {sent && (
              <p role="status" className="notice">
                If email delivery is configured, a single-use link has been
                sent. It returns to Home; use Workspace in the shared navigation
                to continue after signing in.
              </p>
            )}
            {error && (
              <p role="alert" className="alert-error">
                {error}
              </p>
            )}
          </form>
          <Button
            className="w-full mt-3"
            variant="outline"
            disabled={!oauthGitHubEnabled || busy}
            onClick={async () => {
              try {
                await signInWithGitHub();
              } catch (error) {
                setError(error.message);
              }
            }}
          >
            <Github size={16} />
            Continue with GitHub
          </Button>
          {!oauthGitHubEnabled && (
            <p className="fine-print text-center">
              GitHub sign-in needs OAuth setup.
            </p>
          )}
          <Button asChild variant="ghost" className="w-full">
            <Link to="/workspace">
              Explore without signing in <ArrowRight size={15} />
            </Link>
          </Button>
          <p className="auth-footnote">
            Passwordless identity is provided by Supabase Auth.
          </p>
        </div>
      )}
    </main>
  );
}
