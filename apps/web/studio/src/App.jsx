import RoutePresentation from "./components/RoutePresentation.jsx";
import React, { lazy, Suspense, useEffect, useState } from "react";
import {
  BrowserRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import SiteHeader from "@/components/SiteHeader.jsx";
import { WorkspaceState } from "@/lib/WorkspaceState.jsx";
import { useLocalEngine } from "@/lib/localEngine";
import Footer from "./components/SiteFooter.jsx";
import { Home, About, WhatWeDo, NotFound } from "./pages/PublicPages.jsx";

const Workspace = lazy(() => import("./pages/Workspace.jsx"));
const SignIn = lazy(() => import("./pages/SignIn.jsx"));
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
  const inWorkspace = location.pathname.startsWith("/workspace");
  useEffect(() => {
    if (!inWorkspace || stories.length) return;
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
  }, [inWorkspace, stories.length]);
  useEffect(() => {
    if (selfHosted) return;
    let live = true, revision = 0, timer, subscription, identity;
    async function verify() {
      const request = ++revision;
      try {
        const value = await identity.verifiedUser();
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
    async function connectIdentity() {
      identity = await import("./lib/identity");
      if (!live) return;
      verify();
      const { data } = identity.supabase.auth.onAuthStateChange((event, session) => {
        if (!live) return;
        clearTimeout(timer);
        if (session) {
          revision++;
          setUser((current) => current?.id === session.user.id ? current : null);
          if (event === "SIGNED_IN") setChecking(true);
          timer = setTimeout(verify, 0);
        } else if (event === "SIGNED_OUT") {
          revision++;
          setUser(null);
          setChecking(false);
        }
      });
      subscription = data.subscription;
    }
    connectIdentity().catch(() => {
      if (!live) return;
      setChecking(false);
      setToast("Sign-in could not load. Refresh the page to reconnect.");
    });
    return () => {
      live = false;
      revision++;
      clearTimeout(timer);
      subscription?.unsubscribe();
    };
  }, []);
  async function signOut() {
    const { supabase } = await import("./lib/identity");
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
