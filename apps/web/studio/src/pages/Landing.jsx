import React, {useEffect, useRef, useState} from "react";
import {ArrowDown, ArrowRight, ArrowUpRight, Check, FileText, GitBranch, Layers3, Menu, ShieldCheck, Sparkles, X} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import Brand from "@/components/Brand.jsx";
import {IllustrativeSequence} from "@/components/RunProgress.jsx";

// Adapted from ShadcnStore's MIT Vite landing template, pinned in THIRD_PARTY.md.
// Its centered hero, framed product visual, alternating feature grids and sticky
// responsive navigation are retained; product examples replace template imagery.
const chapters = [
  {id: "start-new", label: "Start New", eyebrow: "01 / A better starting point", title: "The client has an idea. You need a useful brief.", body: "Give an onboarding portal a clear shape. Capture who uploads documents, who approves them, and what a successful handoff looks like.", output: "A shareable brief. Locally, a deterministic starter—not the finished portal.", action: "Shape a new project", page: "new"},
  {id: "evolve", label: "Evolve", eyebrow: "02 / A clearer next change", title: "The service already exists. Find where to begin.", body: "Take an authorized snapshot of a billing service. Local static analysis highlights review candidates, so the team can discuss a bounded change instead of a blind rewrite.", output: "Source findings for human review. No imported code is executed or changed.", action: "Explore an existing project", page: "evolve"},
  {id: "work", label: "See the work", eyebrow: "03 / Progress you can inspect", title: "Stay oriented while the work runs.", body: "See the local worker's current operation and elapsed time in one place. Expand recorded actions when you need detail, or cancel the run and move on.", output: "Recorded lifecycle events from your local engine. Detailed tool calls aren't reported.", action: "Explore local runs", page: "evolve"},
  {id: "handoff", label: "Explain the outcome", eyebrow: "04 / Less handoff friction", title: "Make the next conversation easier.", body: "Keep the demo beside the brief. Draft the customer action, visible result and known limitation while the context is fresh—not in a separate tool at the end.", output: "A contextual, editable storyboard. Not a rendered video or verified feature.", action: "Draft your product story", page: "new"},
];

export default function Landing({onPreview, children, toast, onDismiss}) {
  const [menu, setMenu] = useState(false);
  const menuButton = useRef(null);
  function closeMenu() {setMenu(false);}
  return <div className="landing" id="top">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="landing-nav"><div className="nav-inner"><a href="#top" aria-label="Oryveta home"><Brand/></a><nav className={`nav-menu ${menu ? "open" : ""}`} id="primary-menu" aria-label="Primary" onKeyDown={event => {if (event.key === "Escape") {closeMenu(); menuButton.current?.focus();}}}><a href="#workflow" onClick={closeMenu}>How it works</a><a href="#use-cases" onClick={closeMenu}>Use cases</a><a href="#boundaries" onClick={closeMenu}>What's available</a><a href="https://github.com/suhasaitham22/Oryveta" target="_blank" rel="noreferrer">Source <ArrowUpRight size={13}/></a></nav><div className="flex items-center gap-2"><Button asChild size="sm" variant="ghost" className="header-signin"><a href="#sign-in">Sign in</a></Button><Button size="sm" onClick={() => onPreview("overview")}>Open workspace <ArrowRight size={14}/></Button><Button ref={menuButton} className="mobile-menu-trigger" variant="ghost" size="icon" aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu} aria-controls="primary-menu" onClick={() => setMenu(value => !value)}>{menu ? <X size={20}/> : <Menu size={20}/>}</Button></div></div></header>
    <main id="main-content">
      <HeroSection onPreview={onPreview}/>
      <div className="principles-strip"><span><Layers3 size={16}/> Two focused journeys</span><span><ShieldCheck size={16}/> Human review, by design</span><span><FileText size={16}/> Evidence before claims</span></div>
      <ScrollStory onPreview={onPreview}/>
      <FeaturesSection onPreview={onPreview}/>
      <section className="availability-section section-container" id="boundaries"><div className="section-intro"><div className="section-label">A useful product. An honest boundary.</div><h2>Know exactly what you're opening.</h2><p>One interface, two distinct environments. Signing in doesn't silently enable an execution engine.</p></div><div className="availability-grid"><div className="surface-panel"><span className="status-tag">Hosted studio</span><h3>Plan, collaborate, explain.</h3><ul><li><Check size={16}/>Brief and storyboard JSON exports</li><li><Check size={16}/>Supabase identity and workspaces</li><li><Check size={16}/>Private human chats with explicit sharing</li></ul><p className="boundary-note">No hosted coding agent, application test runner or automatic deployment.</p></div><div className="surface-panel"><span className="status-tag">Self-hosted · /studio/</span><h3>Run the local foundation.</h3><ul><li><Check size={16}/>Template starter generation</li><li><Check size={16}/>ZIP snapshot import and static analysis</li><li><Check size={16}/>Real worker status, events and cancellation</li></ul><p className="boundary-note">Separate local identity. Analysis is heuristic, not a security audit or application verification.</p></div></div></section>
      <section className="signin-section" id="sign-in"><div className="section-container signin-grid"><div><div className="section-label">Your next useful step</div><h2>Start with the work.<br/><span>Keep the evidence close.</span></h2><p>Try both journeys without an account. Sign in when you want persistent workspaces and private conversations.</p><div className="signin-proof"><ShieldCheck size={19}/><span>Repository permissions are separate.<br/>No code access is granted by email sign-in.</span></div></div>{children}</div></section>
    </main>
    <footer className="landing-footer section-container"><Brand/><p>Open source. Clear boundaries. Human decisions.</p><a href={`${import.meta.env.BASE_URL}template-license.txt`}>Template credits</a><a href="https://github.com/suhasaitham22/Oryveta" target="_blank" rel="noreferrer">Explore the source <ArrowUpRight size={14}/></a></footer>
    {toast && <div role="alert" className="toast">{toast}<button aria-label="Dismiss notification" onClick={onDismiss}><X size={17}/></button></div>}
  </div>;
}

function HeroSection({onPreview}) {
  return <section id="hero" className="template-hero relative overflow-hidden pt-16 sm:pt-20 pb-16"><div className="hero-pattern" aria-hidden="true"/><div className="section-container relative"><div className="mx-auto max-w-4xl text-center"><div className="mb-8 flex justify-center"><Badge variant="outline" className="hero-badge"><span className="connection-dot"/> Software work, with the context intact</Badge></div><h1 className="hero-title">A clearer path from<br/><span>idea to understood change.</span></h1><p className="hero-lead mx-auto mb-10 max-w-2xl">Turn a new product into a useful brief. Bring an existing codebase into focus. Keep the evidence and the demo beside the work.</p><div className="flex flex-col gap-3 sm:flex-row sm:justify-center"><Button size="lg" onClick={() => onPreview("new")}><Sparkles size={17}/>Start New <ArrowRight size={16}/></Button><Button size="lg" variant="outline" onClick={() => onPreview("evolve")}><GitBranch size={17}/>Evolve existing code</Button></div><p className="hero-caption">Explore without an account · Hosted planning, real local analysis</p></div>
    <div className="mx-auto mt-14 max-w-6xl"><div className="hero-product-frame"><div className="product-topbar"><Brand/><span className="status-tag">Illustrative workspace · no agent running</span></div><div className="hero-product-body"><div className="preview-sidebar"><span className="selected"><Sparkles size={15}/>Start New</span><span><GitBranch size={15}/>Evolve</span><div className="preview-sidebar-note">One brief.<br/>One honest story.</div></div><div className="preview-project"><div className="section-label">Client onboarding portal</div><h2>A project worth understanding.</h2><div className="preview-artifacts"><div><span className="artifact-number">01</span><FileText size={20}/><strong>The brief</strong><p>Clients upload documents.<br/>The team reviews requests.</p><small>Acceptance criteria, not assumptions</small></div><div><span className="artifact-number">02</span><ShieldCheck size={20}/><strong>The evidence</strong><p>Local source findings.<br/>Explicit remaining work.</p><small>Never “verified” by default</small></div><div><span className="artifact-number">03</span><Layers3 size={20}/><strong>The story</strong><p>Show the customer action.<br/>Name the limitation.</p><small>Draft storyboard, ready to edit</small></div></div></div></div></div></div>
    <a className="scroll-invite" href="#workflow">Follow the work <ArrowDown size={15}/></a>
  </div></section>;
}

function ScrollStory({onPreview}) {
  const [active, setActive] = useState(0);
  const nodes = useRef([]);
  useEffect(() => {
    if (!window.IntersectionObserver) return;
    const observer = new IntersectionObserver(() => {
      // Observer entries contain only changed intersections, not every visible chapter.
      // Select from current geometry so an outgoing chapter cannot undo a keyboard jump.
      const readingLine = innerHeight * (matchMedia("(max-width: 600px) and (min-height: 721px)").matches ? 0.62 : 0.5);
      let current = 0;
      nodes.current.forEach((node, index) => {
        if (node && node.getBoundingClientRect().top <= readingLine) current = index;
      });
      setActive(current);
    }, {rootMargin: "-28% 0px -32% 0px", threshold: [0, 0.2, 0.5]});
    nodes.current.forEach(node => node && observer.observe(node));
    return () => observer.disconnect();
  }, []);
  function select(index) {
    setActive(index);
    nodes.current[index]?.scrollIntoView({
      block: matchMedia("(max-width: 600px)").matches ? "start" : "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
  }
  return <section className="scroll-story section-container" id="workflow"><div className="section-intro"><div className="section-label">A little structure. A lot more clarity.</div><h2>From “where do I start?”<br/>to “here's what comes next.”</h2><p>Start New and Evolve are alternatives. Both keep the explanation close to the work.</p></div><div className="scroll-story-grid"><div className="scroll-story-visual"><div className="story-step-controls" aria-label="Product story chapters">{chapters.map((chapter, index) => <button key={chapter.id} aria-current={active === index ? "step" : undefined} onClick={() => select(index)}><span>0{index + 1}</span>{chapter.label}</button>)}</div><div className="story-artifact" data-active-chapter={chapters[active].id}><div className="artifact-browser"><span>oryveta / {chapters[active].label.toLowerCase()}</span><span>Illustrative</span></div><StoryArtifact index={active}/></div><p className="story-visual-caption">Example product states, not a live run. Use the chapter buttons or keep scrolling.</p></div><div className="scroll-chapters">{chapters.map((chapter, index) => <article key={chapter.id} id={`chapter-${chapter.id}`} data-chapter={index} ref={node => {nodes.current[index] = node;}} className={`scroll-chapter ${active === index ? "active" : ""}`}><div className="section-label">{chapter.eyebrow}</div><h3>{chapter.title}</h3><p>{chapter.body}</p><div className="chapter-output"><FileText size={17}/><p>{chapter.output}</p></div><Button variant="outline" onClick={() => onPreview(chapter.page)}>{chapter.action}<ArrowRight size={15}/></Button></article>)}</div></div></section>;
}

function StoryArtifact({index}) {
  if (index === 2) return <div className="artifact-content scene-enter"><div className="section-label">Working state / local only</div><h3>See the operation.<br/>Open the detail.</h3><IllustrativeSequence/></div>;
  if (index === 3) return <div className="artifact-content scene-enter"><span className="status-tag">Demo Studio / Start New</span><div className="mini-storyboard"><div className="section-label">03 / Explain the remaining work</div><h3>Show the action.<br/>Name the limitation.</h3><p>“A client submits their documents. A reviewer sees the request.”</p><small>Draft narration · this feature has not been built or verified</small></div><div className="artifact-bottom"><span>Brief context retained</span><span>Storyboard JSON</span></div></div>;
  if (index === 1) return <div className="artifact-content scene-enter"><span className="status-tag">Evolve / review candidates</span><h3>Billing service snapshot</h3><p className="fine-print">Example findings, not a scan of your repository</p><div className="sample-finding"><span className="finding-dot"/><div><strong>Unconstrained dependency</strong><code>requirements.txt</code></div><span>Review</span></div><div className="sample-finding"><span className="finding-dot"/><div><strong>Bare exception handler</strong><code>billing.py</code></div><span>Review</span></div><div className="artifact-bottom"><ShieldCheck size={16}/><span>Read-only · human review required</span></div></div>;
  return <div className="artifact-content scene-enter"><span className="status-tag">Start New / planning brief</span><h3>Client onboarding portal</h3><div className="sample-field"><span>Who is it for?</span><p>New clients and the account team</p></div><div className="sample-field"><span>What should they be able to do?</span><p>Submit documents, review requests, see what's missing.</p></div><div className="artifact-bottom"><FileText size={16}/><span>Planning brief · not executed</span></div></div>;
}

function FeaturesSection({onPreview}) {
  const scenarios = [
    {icon: Sparkles, title: "For the builder starting a client project", heading: "Less setup ambiguity.", body: "Put roles, outcomes and constraints in one brief. The local starter gives you a runnable baseline; the remaining product work stays explicit.", features: ["A brief you can export", "Starter files you can inspect", "Explicit remaining work", "A story tied to your intent"], page: "new", label: "Start New", artifact: "brief → starter → draft story"},
    {icon: GitBranch, title: "For the maintainer inheriting a service", heading: "A smaller review conversation.", body: "Bring source findings into the team's next review. Agree on a bounded change, keep confidence and limitations visible, and prepare a narrative stakeholders can follow.", features: ["Authorized ZIP snapshots", "Read-only source analysis", "Recorded worker events", "A clear change narrative"], page: "evolve", label: "Evolve", artifact: "snapshot → findings → review"},
  ];
  return <section className="use-cases-section" id="use-cases"><div className="section-container"><div className="section-intro text-center mx-auto"><Badge variant="outline">Work you recognize</Badge><h2>Built around a useful next step.</h2><p>Prepare a stronger handoff, focus the review, and give your next project a clearer starting point.</p></div>{scenarios.map((scenario, index) => <div className={`template-feature-grid ${index ? "flipped" : ""}`} key={scenario.page}><div className="scenario-artifact"><scenario.icon size={35} strokeWidth={1.3}/><div className="section-label">{scenario.title}</div><h3>{scenario.heading}</h3><code>{scenario.artifact}</code></div><div className="flex flex-col gap-6"><div><h3>{scenario.title}</h3><p>{scenario.body}</p></div><ul className="grid gap-4 sm:grid-cols-2">{scenario.features.map(feature => <li key={feature} className="flex items-start gap-3"><Check size={17} className="shrink-0"/><span>{feature}</span></li>)}</ul><div><Button variant="outline" onClick={() => onPreview(scenario.page)}>Open {scenario.label} <ArrowRight size={15}/></Button></div></div></div>)}</div></section>;
}
