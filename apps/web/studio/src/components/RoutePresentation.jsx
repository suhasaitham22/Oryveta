import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const titles = {
  "/": "Home",
  "/about": "About",
  "/what-we-do": "What We Do",
  "/sign-in": "Sign in",
  "/workspace": "Workspace",
  "/workspace/new": "Start New",
  "/workspace/evolve": "Evolve",
  "/workspace/settings": "Workspaces",
  "/workspace/chats": "Private chats",
  "/workspace/activity": "Activity",
};

// Inside Suspense so lazy route content exists before focus is moved.
export default function RoutePresentation({ checking }) {
  const { pathname } = useLocation();
  const waiting = pathname.startsWith("/workspace") && checking;
  useEffect(() => {
    document.title = `${titles[pathname.replace(/\/+$/, "") || "/"] || "Page not found"} · Oryveta`;
    window.scrollTo({ top: 0, behavior: "instant" });
    const frame = requestAnimationFrame(() =>
      document.getElementById("main-content")?.focus({ preventScroll: true }),
    );
    return () => cancelAnimationFrame(frame);
  }, [pathname, waiting]);
  return null;
}
