import React, { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ChevronRight, Menu, X } from "lucide-react";
import Brand from "./Brand.jsx";
import { Button } from "./ui/button";

export const workspacePaths = {
  overview: "/workspace",
  new: "/workspace/new",
  evolve: "/workspace/evolve",
  workspace: "/workspace/settings",
  projects: "/workspace/projects",
  chats: "/workspace/chats",
  activity: "/workspace/activity",
};
const labels = {
  about: "About",
  "what-we-do": "What We Do",
  "sign-in": "Sign in",
  workspace: "Workspace",
  new: "Start New",
  evolve: "Evolve",
  settings: "Workspaces",
  projects: "Projects",
  chats: "Private chats",
  activity: "Activity",
};
const links = [
  ["/", "Home"],
  ["/about", "About"],
  ["/what-we-do", "What We Do"],
  ["/workspace", "Workspace"],
];

export default function SiteHeader({ user, onSignOut, selfHosted }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const trigger = useRef(null);
  const menu = useRef(null);
  useEffect(() => {
    if (!open) return;
    function close(event) {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
      if (
        event.type === "pointerdown" &&
        !menu.current?.contains(event.target) &&
        !trigger.current?.contains(event.target)
      )
        setOpen(false);
    }
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("pointerdown", close);
    };
  }, [open]);
  const segments = location.pathname.split("/").filter(Boolean);
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header-inner">
          <Link to="/" aria-label="Oryveta Home">
            <Brand />
          </Link>
          <nav className="site-links" aria-label="Primary navigation">
            {links.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="site-account">
            {selfHosted ? (
              <span className="status-tag">Local edition</span>
            ) : user ? (
              <Button variant="ghost" size="sm" onClick={onSignOut}>
                Sign out
              </Button>
            ) : (
              <Button asChild variant="outline" size="sm">
                <Link to="/sign-in">Sign in</Link>
              </Button>
            )}
            <Button
              ref={trigger}
              className="site-menu-trigger"
              variant="ghost"
              size="icon"
              aria-label={open ? "Close navigation" : "Open navigation"}
              aria-expanded={open}
              aria-controls="site-mobile-menu"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? <X size={20} /> : <Menu size={20} />}
            </Button>
          </div>
        </div>
        {open && (
          <nav
            ref={menu}
            id="site-mobile-menu"
            className="site-mobile-menu"
            aria-label="Mobile primary navigation"
          >
            {links.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                onClick={() => setOpen(false)}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      {segments.length > 0 && (
        <div className="route-trail">
          <nav aria-label="Breadcrumb">
            <ol>
              <li>
                <Link to="/">Home</Link>
              </li>
              {segments.map((part, index) => (
                <li key={index}>
                  <ChevronRight size={12} aria-hidden="true" />
                  {index === segments.length - 1 ? (
                    <span aria-current="page">
                      {labels[part] || "Page not found"}
                    </span>
                  ) : (
                    <Link to={`/${segments.slice(0, index + 1).join("/")}`}>
                      {labels[part] || part}
                    </Link>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        </div>
      )}
    </>
  );
}
