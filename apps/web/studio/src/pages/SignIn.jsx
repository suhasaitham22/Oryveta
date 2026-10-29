import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Github, LockKeyhole, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { sendEmailLink, signInWithGitHub, authProviders } from "@/lib/identity";

export default SignIn;

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
      <div className="signin-intro">
        <span className="section-label">
          <LockKeyhole size={15} />
          Your private workspace
        </span>
        <h1>
          Make space
          <br />
          for your next idea.
        </h1>
        <p>
          Sign in to save project briefs, invite collaborators and create
          private conversations. You choose what to share and with whom.
        </p>
        <div className="signin-visual" aria-hidden="true">
          <svg viewBox="0 0 480 240" fill="none" focusable="false">
            <ellipse cx="230" cy="200" rx="174" ry="19" fill="var(--accent)" opacity=".06" />
            <path d="M48 132C48 28 423 14 437 124C452 231 71 258 48 132Z" stroke="var(--border)" strokeDasharray="3 7" />
            <g transform="translate(92 42) rotate(-7 142 78)">
              <rect x="24" y="26" width="284" height="150" rx="18" fill="var(--accent-soft)" stroke="var(--border)" />
              <rect x="12" y="13" width="284" height="150" rx="18" fill="var(--surface)" stroke="var(--border)" />
              <rect width="284" height="150" rx="18" fill="var(--ink)" />
              <circle cx="24" cy="23" r="4" fill="var(--accent)" />
              <text x="38" y="28" fill="white" fontSize="12" fontFamily="inherit">A place for the work that matters</text>
              <path d="M20 43H264" stroke="white" strokeOpacity=".15" />
              <rect x="20" y="61" width="104" height="8" rx="4" fill="white" fillOpacity=".8" />
              <rect x="20" y="82" width="182" height="5" rx="2.5" fill="white" fillOpacity=".22" />
              <rect x="20" y="96" width="154" height="5" rx="2.5" fill="white" fillOpacity=".22" />
              <rect x="20" y="118" width="77" height="16" rx="8" fill="var(--accent)" />
              <circle cx="232" cy="120" r="12" fill="#495473" stroke="var(--ink)" strokeWidth="3" />
              <circle cx="248" cy="120" r="12" fill="#657ba8" stroke="var(--ink)" strokeWidth="3" />
              <circle cx="264" cy="120" r="12" fill="#9bacd3" stroke="var(--ink)" strokeWidth="3" />
            </g>
          </svg>
        </div>
        <p className="signin-detail">
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
          <h2>Welcome to Oryveta.</h2>
          <p>One account for your projects and private conversations.</p>
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
