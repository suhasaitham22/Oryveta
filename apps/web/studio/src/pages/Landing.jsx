import React, { useEffect, useRef, useState } from "react";
import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "motion/react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Code2,
  FileText,
  GitBranch,
  Layers3,
  Menu,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import Brand from "@/components/Brand.jsx";

const chapters = [
  {
    id: "start-new",
    label: "Start New",
    eyebrow: "01 / Define the intent",
    title: "Every good build starts with a better question.",
    body: "Who is this for? What should it do? Shape a client onboarding idea into a brief your team can actually use.",
    output: "A portable brief. A deterministic starter when you work locally.",
    action: "Shape a new project",
    page: "new",
  },
  {
    id: "evolve",
    label: "Evolve",
    eyebrow: "02 / Find your bearings",
    title: "Understand the code before changing the code.",
    body: "Bring an authorized snapshot of your service. Put source findings beside the context, and turn a sprawling codebase into a focused review conversation.",
    output:
      "Read-only heuristic analysis. Findings are candidates for human review.",
    action: "Explore an existing project",
    page: "evolve",
  },
  {
    id: "work",
    label: "See the work",
    eyebrow: "03 / Keep a clear record",
    title: "Less wondering. More knowing where things stand.",
    body: "Follow your local worker from queue to result. Open the recorded tasks, inspect the events, or cancel. The evidence stays attached to the work.",
    output:
      "Real local lifecycle events. No invented tool calls or private reasoning.",
    action: "Explore local runs",
    page: "evolve",
  },
  {
    id: "handoff",
    label: "Explain the outcome",
    eyebrow: "04 / Bring the story with you",
    title: "Make the handoff as thoughtful as the brief.",
    body: "Turn the next customer action into a clear narrative. Edit the scenes in context, keep the limitations visible, and take a storyboard into your next conversation.",
    output:
      "Editable storyboard JSON, beside Start New or Evolve. Not a rendered video.",
    action: "Draft your product story",
    page: "new",
  },
];

export default function Landing({ onPreview, children, toast, onDismiss }) {
  const [menu, setMenu] = useState(false);
  const menuButton = useRef(null);
  const closeMenu = () => setMenu(false);
  return (
    <div className="landing" id="top">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="landing-nav">
        <div className="nav-inner">
          <a href="#top" aria-label="Oryveta home">
            <Brand />
          </a>
          <nav
            className={`nav-menu ${menu ? "open" : ""}`}
            id="primary-menu"
            aria-label="Primary"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                closeMenu();
                menuButton.current?.focus();
              }
            }}
          >
            <a href="#workflow" onClick={closeMenu}>
              The workflow
            </a>
            <a href="#use-cases" onClick={closeMenu}>
              Made for your work
            </a>
            <a href="#boundaries" onClick={closeMenu}>
              What's available
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <Button asChild size="sm" variant="ghost" className="header-signin">
              <a href="#sign-in">Sign in</a>
            </Button>
            <Button size="sm" onClick={() => onPreview("overview")}>
              Open workspace <ArrowUpRight size={15} />
            </Button>
            <Button
              ref={menuButton}
              size="icon"
              variant="ghost"
              className="mobile-menu-trigger"
              aria-label={menu ? "Close navigation" : "Open navigation"}
              aria-expanded={menu}
              aria-controls="primary-menu"
              onClick={() => setMenu((value) => !value)}
            >
              {menu ? <X size={20} /> : <Menu size={20} />}
            </Button>
          </div>
        </div>
      </header>
      <main id="main-content">
        <HeroSection onPreview={onPreview} />
        <div className="principles-strip section-container">
          <span>
            <Layers3 size={16} /> Intent, source & story
          </span>
          <span>
            <ShieldCheck size={16} /> Human decisions at the center
          </span>
          <a
            href="https://github.com/suhasaitham22/Oryveta"
            target="_blank"
            rel="noreferrer"
          >
            Open source. Yours to inspect. <ArrowUpRight size={15} />
          </a>
        </div>
        <ScrollStory onPreview={onPreview} />
        <FeaturesSection onPreview={onPreview} />
        <section
          className="availability-section section-container"
          id="boundaries"
        >
          <div className="section-intro">
            <div className="section-label">The operating model</div>
            <h2>
              Clear capabilities.
              <br />
              <em>No hidden asterisks.</em>
            </h2>
            <p>
              Choose the environment that fits the work. Identity and execution
              remain deliberately separate.
            </p>
          </div>
          <div className="availability-grid">
            <article>
              <span className="environment-number">01</span>
              <span className="status-tag">Hosted studio</span>
              <h3>
                A place to shape
                <br />
                the next step.
              </h3>
              <ul>
                <li>
                  <Check size={16} />
                  Brief and storyboard JSON exports
                </li>
                <li>
                  <Check size={16} />
                  Supabase identity and workspaces
                </li>
                <li>
                  <Check size={16} />
                  Private human chats with explicit sharing
                </li>
              </ul>
              <p className="boundary-note">
                No hosted coding agent, application test runner or automatic
                deployment. Hosted account capabilities require configured
                Supabase services.
              </p>
            </article>
            <article>
              <span className="environment-number">02</span>
              <span className="status-tag">Self-hosted /studio/</span>
              <h3>
                Your source.
                <br />
                Your local engine.
              </h3>
              <ul>
                <li>
                  <Check size={16} />
                  Deterministic starters and source ZIP exports
                </li>
                <li>
                  <Check size={16} />
                  Authorized ZIP import and read-only analysis
                </li>
                <li>
                  <Check size={16} />
                  Recorded jobs, cancellation and source findings
                </li>
              </ul>
              <p className="boundary-note">
                Imported code is never executed. Analysis does not apply patches
                or prove correctness. Local cookie identity is separate from
                Supabase.
              </p>
              <a
                className="text-link"
                href="https://github.com/suhasaitham22/Oryveta#functional-mvp--run-locally"
                target="_blank"
                rel="noreferrer"
              >
                Set up your local engine <ArrowUpRight size={16} />
              </a>
            </article>
          </div>
        </section>
        <section className="signin-section" id="sign-in">
          <div className="section-container signin-grid">
            <div>
              <div className="section-label">The next chapter is yours</div>
              <h2>
                Make something
                <br />
                <em>worth understanding.</em>
              </h2>
              <p>
                Explore both journeys without an account. Sign in for persistent
                workspaces and private conversations.
              </p>
              <div className="signin-proof">
                <ShieldCheck size={19} />
                <span>
                  Repository permissions are separate.
                  <br />
                  Email sign-in never grants code access.
                </span>
              </div>
            </div>
            {children}
          </div>
        </section>
      </main>
      <footer className="landing-footer section-container">
        <Brand />
        <p>Build thoughtfully. Evolve continuously.</p>
        <a href={`${import.meta.env.BASE_URL}template-license.txt`}>
          Design credits
        </a>
        <a
          href="https://github.com/suhasaitham22/Oryveta"
          target="_blank"
          rel="noreferrer"
        >
          Explore the source <ArrowUpRight size={14} />
        </a>
      </footer>
      {toast && (
        <div role="alert" className="toast">
          {toast}
          <button aria-label="Dismiss notification" onClick={onDismiss}>
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}

function HeroSection({ onPreview }) {
  const hero = useRef(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: hero,
    offset: ["start start", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [0, 45]);
  const rotate = useTransform(scrollYProgress, [0, 1], [-3, 2]);
  return (
    <section className="editorial-hero section-container" ref={hero} id="hero">
      <div className="context-sculpture" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="hero-copy">
        <div className="hero-eyebrow">
          <span className="connection-dot" /> A clearer space for software work
        </div>
        <h1 className="hero-title">
          Good software starts
          <br />
          with a clear direction.
        </h1>
        <p className="hero-lead">
          Shape the idea. Understand the code. Bring the story along.
          <br className="desktop-break" /> Your next useful step starts here.
        </p>
        <div className="hero-actions">
          <Button size="lg" onClick={() => onPreview("new")}>
            Start New <ArrowUpRight size={18} />
          </Button>
          <Button
            size="lg"
            variant="outline"
            onClick={() => onPreview("evolve")}
          >
            Evolve <ArrowRight size={18} />
          </Button>
        </div>
        <p className="hero-caption">
          Open source. Two ways in. No account needed to explore.
        </p>
      </div>
      <motion.div
        className="hero-artwork"
        aria-label="Illustrative Oryveta project workspace"
        initial={reduced ? false : { opacity: 0.7, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={
          reduced
            ? { duration: 0 }
            : { type: "spring", stiffness: 130, damping: 22 }
        }
      >
        <div className="artwork-topline">
          <span>YOUR NEXT CHAPTER / ORYVETA</span>
          <span>Illustrative workspace</span>
        </div>
        <motion.div
          className="hero-brief-sheet"
          style={{ y: reduced ? 0 : y, rotate: reduced ? -3 : rotate }}
        >
          <div className="paper-meta">
            <FileText size={15} />
            <span>START NEW / PROJECT BRIEF</span>
            <ArrowUpRight size={16} />
          </div>
          <h2>
            Better onboarding.
            <br />
            Less back-and-forth.
          </h2>
          <p>
            A single place for clients to submit documents and teams to review
            what's missing.
          </p>
          <div className="paper-tags">
            <span>Client portal</span>
            <span>Draft / 01</span>
          </div>
          <div className="paper-footer">
            <span>Intent, before implementation.</span>
            <Sparkles size={18} />
          </div>
        </motion.div>
        <div className="hero-code-sheet">
          <div className="code-topbar">
            <GitBranch size={14} />
            <span>Evolve / source review</span>
            <span className="code-dot" />
          </div>
          <div className="code-lines">
            <span>
              <b>12</b>
              <i>def</i> process_invoice(record):
            </span>
            <span>
              <b>13</b> <i>try</i>:
            </span>
            <span>
              <b>14</b> submit(record)
            </span>
            <span className="code-highlight">
              <b>15</b> <i>except</i>: <small>← review</small>
            </span>
            <span>
              <b>16</b> <i>pass</i>
            </span>
          </div>
          <div className="code-receipt">
            <span className="connection-dot" /> Example finding{" "}
            <span>Read-only</span>
          </div>
        </div>
        <div className="hero-story-sheet">
          <div className="paper-meta">
            <Layers3 size={15} />
            <span>DEMO STUDIO</span>
          </div>
          <span className="hero-story-number">01 / ACTION</span>
          <h3>
            Make the next
            <br />
            step make sense.
          </h3>
          <div className="hero-story-lines">
            <span />
            <span />
            <span />
          </div>
          <p>Context stays with the brief.</p>
          <div className="paper-footer">Storyboard draft · not a video</div>
        </div>
        <span className="artwork-bottomline">
          A brief. A finding. A more useful next step.
        </span>
      </motion.div>
      <a className="scroll-invite" href="#workflow">
        <span>Follow the work</span>
        <ArrowDown size={18} />
      </a>
    </section>
  );
}

function ScrollStory({ onPreview }) {
  const [active, setActive] = useState(0);
  const [compact, setCompact] = useState(
    () => matchMedia("(max-width: 600px) and (min-height: 741px)").matches,
  );
  useEffect(() => {
    const query = matchMedia("(max-width: 600px) and (min-height: 741px)");
    const update = () => setCompact(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const nodes = useRef([]);
  const visual = useRef(null);
  const [unpin, setUnpin] = useState(false);
  const reduced = useReducedMotion();
  const { scrollY } = useScroll();
  const storyProgress = useMotionValue(0);
  function updateProgress() {
    const fitsViewport =
      (visual.current?.getBoundingClientRect().height || 0) <
      window.innerHeight - 120;
    setUnpin(!fitsViewport);
    const readingLine =
      window.innerHeight * (compact && fitsViewport ? 0.75 : 0.5);
    let index = 0;
    nodes.current.forEach((node, candidate) => {
      if (node && node.getBoundingClientRect().top <= readingLine)
        index = candidate;
    });
    const bounds = nodes.current[index]?.getBoundingClientRect();
    if (!bounds) return;
    const fraction = Math.max(
      0,
      Math.min(1, (readingLine - bounds.top) / bounds.height),
    );
    // Normalize each actual chapter, not four assumed equal-height sections.
    // Bounding rectangles also account for browser/text zoom.
    storyProgress.set((index + fraction) / chapters.length);
    setActive(index);
  }
  useMotionValueEvent(scrollY, "change", updateProgress);
  useEffect(() => {
    updateProgress();
    window.addEventListener("resize", updateProgress);
    return () => window.removeEventListener("resize", updateProgress);
  }, [compact]);
  function select(index) {
    setActive(index);
    const bounds = nodes.current[index]?.getBoundingClientRect();
    if (!bounds) return;
    const fitsViewport =
      (visual.current?.getBoundingClientRect().height || 0) <
      window.innerHeight - 120;
    const top =
      compact && fitsViewport
        ? window.innerHeight * 0.64
        : (window.innerHeight - bounds.height) / 2;
    window.scrollTo({
      top: window.scrollY + bounds.top - top,
      behavior: reduced ? "instant" : "smooth",
    });
  }
  return (
    <section className="scroll-story section-container" id="workflow">
      <div className="story-intro">
        <div className="section-label">A continuous thread</div>
        <h2>
          Context isn't overhead.
          <br />
          <em>It's how good work happens.</em>
        </h2>
        <p>
          Start with an idea or an existing codebase.
          <br />
          Keep the next decision connected to the last.
        </p>
      </div>
      <div className="scroll-story-grid">
        <div
          ref={visual}
          className={`scroll-story-visual${unpin ? " is-unpinned" : ""}`}
        >
          <div
            className="story-step-controls"
            aria-label="Product story chapters"
          >
            {chapters.map((chapter, index) => (
              <button
                key={chapter.id}
                aria-current={active === index ? "step" : undefined}
                onClick={() => select(index)}
              >
                <span>0{index + 1}</span>
                {chapter.label}
              </button>
            ))}
          </div>
          <div
            className="story-artifact"
            data-active-chapter={chapters[active].id}
          >
            <div className="artifact-browser">
              <span>
                <span className="connection-dot" /> Oryveta / working context
              </span>
              <span>Illustrative scenes</span>
            </div>
            <div className="artifact-deck">
              {chapters.map((chapter, index) => (
                <ArtifactSheet
                  key={chapter.id}
                  index={index}
                  progress={storyProgress}
                  active={active}
                  reduced={reduced}
                />
              ))}
            </div>
            <div className="artifact-route">
              <span>Intent</span>
              <ChevronRight size={13} />
              <span>Evidence</span>
              <ChevronRight size={13} />
              <span>Explanation</span>
            </div>
          </div>
          <p className="story-visual-caption">
            Start New and Evolve are alternative entry points. These scenes
            explain the product, not a live agent run.
          </p>
        </div>
        <div className="scroll-chapters">
          {chapters.map((chapter, index) => (
            <article
              className="scroll-chapter"
              id={chapter.id}
              ref={(node) => {
                nodes.current[index] = node;
              }}
              key={chapter.id}
            >
              <div className="section-label">{chapter.eyebrow}</div>
              <h3>{chapter.title}</h3>
              <p>{chapter.body}</p>
              <div className="chapter-output">
                <FileText size={16} />
                <p>{chapter.output}</p>
              </div>
              <Button variant="outline" onClick={() => onPreview(chapter.page)}>
                {chapter.action}
                <ArrowUpRight size={16} />
              </Button>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ArtifactSheet({ index, progress, active, reduced }) {
  const start = index / 4;
  const end = (index + 1) / 4;
  const y = useTransform(
    progress,
    [Math.max(0, start - 0.14), start, end - 0.08, end + 0.05],
    [index ? 560 : 0, 0, 0, -65],
  );
  const rotate = useTransform(
    progress,
    [Math.max(0, start - 0.14), start, end - 0.08, end + 0.05],
    [index ? 7 : 0, 0, 0, -4],
  );
  const scale = useTransform(progress, [end - 0.08, end + 0.05], [1, 0.92]);
  const opacity = useTransform(progress, [end - 0.02, end + 0.05], [1, 0]);
  return (
    <motion.div
      className={`artifact-content sheet-${index}`}
      aria-hidden={active !== index}
      style={{
        y: reduced ? 0 : y,
        rotate: reduced ? 0 : rotate,
        scale: reduced ? 1 : scale,
        opacity: reduced || index === 3 ? 1 : opacity,
        display: reduced && active !== index ? "none" : "block",
        zIndex: index + 1,
      }}
    >
      {index === 0 && (
        <>
          <div className="sheet-label">
            <FileText size={16} />
            <span>START NEW / THE BRIEF</span>
            <span>01</span>
          </div>
          <h3>
            A smoother start.
            <br />
            For every client.
          </h3>
          <div className="brief-note">
            <span>THE PEOPLE</span>
            <p>New clients & the account team</p>
          </div>
          <div className="brief-note">
            <span>THE OUTCOME</span>
            <p>
              Submit documents. Review requests.
              <br />
              Know exactly what's missing.
            </p>
          </div>
          <div className="sheet-receipt">
            <span className="mini-square" /> Planning brief · not executed
          </div>
        </>
      )}
      {index === 1 && (
        <>
          <div className="sheet-label">
            <GitBranch size={16} />
            <span>EVOLVE / THE SOURCE</span>
            <span>02</span>
          </div>
          <h3>
            Small signals.
            <br />
            Better questions.
          </h3>
          <div className="source-excerpt">
            <span>billing.py</span>
            <code>
              <span>try:</span>
              <br /> submit(invoice)
              <br />
              <mark>except:</mark>
              <br /> pass
            </code>
          </div>
          <div className="finding-receipt">
            <span className="finding-dot" />
            <div>
              <strong>Bare exception handler</strong>
              <p>Could this hide a failed payment?</p>
            </div>
            <span>Review</span>
          </div>
          <div className="sheet-receipt">
            Example finding · read-only · human review
          </div>
        </>
      )}
      {index === 2 && (
        <>
          <div className="sheet-label">
            <Layers3 size={16} />
            <span>LOCAL RUN / THE RECORD</span>
            <span>03</span>
          </div>
          <h3>
            See the operation.
            <br />
            Open the detail.
          </h3>
          <div className="illustration-task">
            <span>01</span>
            <div>
              <strong>Snapshot submitted</strong>
              <p>Queue acceptance recorded by the API</p>
            </div>
          </div>
          <div className="illustration-task emphasized">
            <span>02</span>
            <div>
              <strong>Source analysis</strong>
              <p>The local worker inspects, never executes</p>
            </div>
            <Code2 size={18} />
          </div>
          <div className="illustration-task">
            <span>03</span>
            <div>
              <strong>Findings for review</strong>
              <p>A persisted result, not a correctness claim</p>
            </div>
          </div>
          <div className="sheet-receipt">
            Illustrative sequence · no agent running
          </div>
        </>
      )}
      {index === 3 && (
        <>
          <div className="sheet-label">
            <Sparkles size={16} />
            <span>DEMO STUDIO / THE STORY</span>
            <span>04</span>
          </div>
          <div className="story-frame">
            <span>SCENE 01 / CLIENT ONBOARDING</span>
            <h3>
              “Here's what
              <br />
              happens next.”
            </h3>
            <div className="story-frame-line" />
            <p>
              A client submits their documents.
              <br />A reviewer sees the request.
            </p>
          </div>
          <div className="story-strip">
            <span className="selected">01 / Action</span>
            <span>02 / Result</span>
            <span>03 / Boundary</span>
          </div>
          <div className="sheet-receipt">
            Draft storyboard · not built or verified
          </div>
        </>
      )}
    </motion.div>
  );
}

function FeaturesSection({ onPreview }) {
  return (
    <section className="use-cases-section" id="use-cases">
      <div className="section-container">
        <div className="use-case-heading">
          <div className="section-label">For the work in front of you</div>
          <h2>
            A blank page.
            <br />
            An unfamiliar codebase.
            <br />
            <em>Both are a beginning.</em>
          </h2>
        </div>
        <div className="use-case-spread">
          <article className="use-case-new">
            <div className="use-case-meta">
              <span>01 / THE BUILDER</span>
              <Sparkles size={22} />
            </div>
            <h3>
              Give the idea
              <br />
              some structure.
            </h3>
            <p>
              A client portal. An internal tool. Your next side project. Start
              with the people, the outcome, and the constraints that matter.
            </p>
            <div
              className="use-case-sketch"
              aria-label="Illustrative planning outline"
            >
              <div>
                <FileText size={17} />
                <span>Client onboarding</span>
                <small>Brief</small>
              </div>
              <span className="sketch-connector" />
              <div>
                <Code2 size={17} />
                <span>Deterministic starter</span>
                <small>Local</small>
              </div>
              <span className="sketch-connector" />
              <div>
                <Layers3 size={17} />
                <span>A story worth sharing</span>
                <small>Draft</small>
              </div>
            </div>
            <button className="text-link" onClick={() => onPreview("new")}>
              Start New <ArrowUpRight size={20} />
            </button>
          </article>
          <article className="use-case-evolve">
            <div className="use-case-meta">
              <span>02 / THE MAINTAINER</span>
              <GitBranch size={22} />
            </div>
            <h3>
              Find a considered
              <br />
              way forward.
            </h3>
            <p>
              Inherit a service without inheriting the guesswork. Inspect an
              authorized snapshot, discuss the findings, and define a bounded
              next change.
            </p>
            <div className="review-sheet">
              <span className="review-sheet-label">REVIEW NOTES / EXAMPLE</span>
              <div>
                <span>01</span>
                <p>
                  Unconstrained dependency<code>requirements.txt</code>
                </p>
                <ArrowUpRight size={17} />
              </div>
              <div>
                <span>02</span>
                <p>
                  Bare exception handler<code>billing.py</code>
                </p>
                <ArrowUpRight size={17} />
              </div>
              <small>Source findings, not verified fixes.</small>
            </div>
            <button className="text-link" onClick={() => onPreview("evolve")}>
              Evolve <ArrowUpRight size={20} />
            </button>
          </article>
        </div>
      </div>
    </section>
  );
}
