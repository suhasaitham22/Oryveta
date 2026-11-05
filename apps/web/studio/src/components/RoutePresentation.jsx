import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const titles = {
  "/": "Home",
  "/about": "About",
  "/what-we-do": "What We Do",
  "/pricing": "Pricing",
  "/sign-in": "Sign in",
  "/workspace": "Workspace",
  "/workspace/new": "Start New",
  "/workspace/evolve": "Evolve",
  "/workspace/settings": "Workspaces",
  "/workspace/projects": "Projects",
  "/workspace/chats": "Private chats",
  "/workspace/activity": "Activity",
};

// Inside Suspense so lazy route content exists before focus is moved.
export default function RoutePresentation({ checking }) {
  const { pathname, hash } = useLocation();
  const waiting = pathname.startsWith("/workspace") && checking;
  useEffect(() => {
    document.title = `${titles[pathname.replace(/\/+$/, "") || "/"] || "Page not found"} · Oryveta`;
    // A cross-page link may target a section: focus it instead of the top.
    if (!hash) window.scrollTo({ top: 0, behavior: "instant" });
    const frame = requestAnimationFrame(() => {
      const section = hash && document.getElementById(hash.slice(1));
      if (section) {
        section.focus({ preventScroll: true });
        section.scrollIntoView({ behavior: "instant", block: "start" });
        return;
      }
      document.getElementById("main-content")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname, hash, waiting]);
  return null;
}
