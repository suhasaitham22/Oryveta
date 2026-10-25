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
  authProviders,
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
            "We couldn't complete sign-in or restore your session. Request a new link in this browser.",
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
              "/workspace/projects",
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
  /* Provider availability comes from the project's own auth settings. Until it is
     confirmed, or if it cannot be confirmed, OAuth stays disabled and says why. */
  const [providers, setProviders] = useState({ state: "checking" });
  useEffect(() => {
    if (selfHosted) return;
    let live = true;
    authProviders()
      .then((external) => {
        if (live) setProviders({ state: "known", external });
      })
      .catch((problem) => {
        if (live)
          setProviders({ state: "unconfirmed", message: problem.message });
      });
    return () => {
      live = false;
    };
  }, [selfHosted]);
  const githubEnabled =
    providers.state === "known" && providers.external.github === true;
  const emailDisabled =
    providers.state === "known" && providers.external.email === false;
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
          Keep your projects
          <br />
          and conversations together.
        </h1>
        <p>
          Sign in to save project briefs, invite collaborators and create
          private conversations. You choose what to share and with whom.
        </p>
        <p>
          Drafts in Start New, Evolve and Demo Studio are different from saved
          project briefs: export them before closing or reloading the page.
        </p>
      </div>
      {selfHosted ? (
        <div className="surface-panel">
          <h2>You're in the local edition.</h2>
          <p>
            Open Local run inside Start New or Evolve to use this server.
            The local engine has a separate sign-in from cloud projects.
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
            <Button
              type="submit"
              className="w-full"
              disabled={busy || emailDisabled}
            >
              <Mail size={16} />
              {busy ? "Requesting secure link…" : "Continue with email"}
              <ArrowRight size={15} />
            </Button>
            {emailDisabled && (
              <p role="status" className="notice">
                Email sign-in is switched off for this project's Supabase Auth
                settings. No link can be sent until it is enabled.
              </p>
            )}
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
            disabled={!githubEnabled || busy}
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
          {providers.state === "checking" && (
            <p className="fine-print text-center" role="status">
              Checking which sign-in providers this project has enabled…
            </p>
          )}
          {providers.state === "unconfirmed" && (
            <p className="fine-print text-center">
              GitHub sign-in is unavailable: {providers.message}. Email link
              sign-in is unaffected.
            </p>
          )}
          {providers.state === "known" && !githubEnabled && (
            <p className="fine-print text-center">
              GitHub sign-in is not enabled in this project's Supabase Auth
              providers.
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
