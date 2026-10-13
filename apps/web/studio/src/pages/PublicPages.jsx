import React from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  Code2,
  FileText,
  GitBranch,
  LockKeyhole,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import ProductScene from "@/components/ProductScene.jsx";
import { useReducedMotion } from "@/lib/useReducedMotion";

function Reveal({ children, delay = 0, className = "" }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduced ? false : { y: 44 }}
      animate={reduced ? { y: 0 } : undefined}
      whileInView={{ y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{
        duration: reduced ? 0 : 0.7,
        delay: reduced ? 0 : delay,
        ease: [0.22, 1, 0.36, 1],
      }}
    >
      {children}
    </motion.div>
  );
}
export function Home() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page home-page">
      <section className="home-intro section-container">
        <Reveal>
          <span className="section-label">
            Software work. Made understandable.
          </span>
        </Reveal>
        <Reveal delay={0.08}>
          <h1>
            From a good idea
            <br />
            to a clearer next move.
          </h1>
        </Reveal>
        <Reveal delay={0.16}>
          <p>
            Bring intent, source evidence and the story together.
            <br className="desktop-break" /> An open workspace for people
            building useful software.
          </p>
        </Reveal>
        <Reveal delay={0.24} className="home-actions">
          <Button asChild size="lg">
            <Link to="/workspace/new">
              Start something new <ArrowRight size={17} />
            </Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link to="/workspace/evolve">
              Improve what exists <GitBranch size={17} />
            </Link>
          </Button>
        </Reveal>
        <ProductScene />
      </section>
      <section className="home-next section-container">
        <Reveal>
          <span className="section-label">
            Shared context. Better decisions.
          </span>
          <h2>
            Keep the work
            <br />
            and the explanation close.
          </h2>
        </Reveal>
        <Reveal delay={0.12}>
          <p>
            A useful handoff says what you intended, what you actually checked,
            and what still needs a human decision. Oryveta gives those three
            things a place to live.
          </p>
          <Link className="text-link" to="/what-we-do">
            See the two journeys <ArrowRight size={17} />
          </Link>
        </Reveal>
      </section>
    </main>
  );
}
export function About() {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="public-page section-container editorial-page"
    >
      <Reveal>
        <span className="section-label">About Oryveta</span>
        <h1>
          Clarity is part
          <br />
          of the craft.
        </h1>
        <p className="page-deck">
          Software is a collaboration between people who rarely have the same
          context. The handoff deserves as much care as the code.
        </p>
      </Reveal>
      <section className="editorial-split">
        <h2>
          Built for the space
          <br />
          between idea and delivery.
        </h2>
        <div>
          <p>
            Oryveta is for independent builders, technical consultants and small
            teams making software for someone else. It helps make an ambiguous
            request concrete and an existing codebase easier to discuss.
          </p>
          <p>
            The aim is not to make people disappear from the process. It is to
            make intent, evidence and responsibility easier to see.
          </p>
        </div>
      </section>
      <section className="principle-grid" aria-label="Open source principles">
        <Reveal>
          <Code2 size={24} />
          <h2>Open by design.</h2>
          <p>
            Apache-2.0 source. Read the implementation, run it yourself, and
            contribute improvements. Third-party licenses remain their own.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <LockKeyhole size={24} />
          <h2>Boundaries first.</h2>
          <p>
            Local repository work and hosted account features use separate
            identities. Sharing is explicit, not an accidental consequence of
            workspace membership.
          </p>
        </Reveal>
        <Reveal delay={0.2}>
          <FileText size={24} />
          <h2>Evidence over claims.</h2>
          <p>
            A draft is a draft. A static finding is not a passing test. A
            storyboard is not a rendered demo. The interface should tell you the
            difference.
          </p>
        </Reveal>
      </section>
      <section className="stage-note">
        <span className="section-label">Current stage</span>
        <h2>
          A working foundation.
          <br />
          Not an autonomous delivery service.
        </h2>
        <p>
          Today, Oryveta combines planning and storyboard exports, hosted
          workspaces and private human chats, and a self-hosted starter and
          source-analysis engine. Hosted coding agents, automatic patches and
          deployments are not available.
        </p>
        <a
          className="text-link"
          href="https://github.com/suhasaitham22/Oryveta"
          target="_blank"
          rel="noreferrer"
        >
          Explore the source <ArrowUpRight size={17} />
        </a>
      </section>
    </main>
  );
}
export function WhatWeDo() {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="public-page section-container editorial-page"
    >
      <Reveal>
        <span className="section-label">What We Do</span>
        <h1>
          Two ways in.
          <br />
          Something useful out.
        </h1>
        <p className="page-deck">
          Start with an idea or an existing repository. Leave with context you
          can inspect, edit and share—not a claim that work happened behind the
          curtain.
        </p>
      </Reveal>
      <section className="journey-detail">
        <Reveal>
          <span className="section-label">
            <Sparkles size={17} />
            01 / Start New
          </span>
          <h2>
            Give an idea
            <br />a practical foundation.
          </h2>
          <p>
            For a client portal, a small service, or the first version of an
            internal tool. Define the task before adding more software.
          </p>
          <Button asChild>
            <Link to="/workspace/new">
              Open Start New <ArrowRight size={16} />
            </Link>
          </Button>
        </Reveal>
        <ol>
          <li>
            <strong>Frame the outcome</strong>
            <p>
              Write a named brief with user needs and constraints. Export the
              planning JSON.
            </p>
          </li>
          <li>
            <strong>Prepare a starter locally</strong>
            <p>
              Choose a deterministic template with the self-hosted engine.
              Download its ZIP and inspect its source.
            </p>
          </li>
          <li>
            <strong>Draft the explanation</strong>
            <p>
              Edit the contextual storyboard and export its scenes with the same
              brief and project context.
            </p>
          </li>
        </ol>
      </section>
      <section className="journey-detail">
        <Reveal>
          <span className="section-label">
            <GitBranch size={17} />
            02 / Evolve
          </span>
          <h2>
            Make an existing
            <br />
            system easier to change.
          </h2>
          <p>
            For the service you inherited or the product that needs its next
            improvement. Start with an authorized snapshot and a clear question.
          </p>
          <Button asChild variant="outline">
            <Link to="/workspace/evolve">
              Open Evolve <ArrowRight size={16} />
            </Link>
          </Button>
        </Reveal>
        <ol>
          <li>
            <strong>Set a change goal</strong>
            <p>
              Record the repository name and what should improve. Keep the scope
              editable.
            </p>
          </li>
          <li>
            <strong>Inspect the snapshot locally</strong>
            <p>
              Import a ZIP. Start or cancel static analysis, then read persisted
              run events and findings. Imported code is never executed.
            </p>
          </li>
          <li>
            <strong>Explain the next decision</strong>
            <p>
              Turn the context into a draft story. Findings are a review queue,
              not applied patches or security certification.
            </p>
          </li>
        </ol>
      </section>
      <section className="delivery-boundaries">
        <div>
          <span className="section-label">Available here</span>
          <h2>
            A browser for planning.
            <br />
            Your engine for execution.
          </h2>
          <p>
            Hosted visitors can draft and export without an account. Sign in for
            Supabase workspaces and private human conversations. Local jobs
            require the separately operated same-origin engine.
          </p>
        </div>
        <div>
          <h3>What the exports mean</h3>
          <ul>
            <li>Brief JSON: intent, not executed work.</li>
            <li>Starter ZIP: template source, not a deployed product.</li>
            <li>Analysis: static findings, not test results.</li>
            <li>Storyboard JSON: unverified scenes, not rendered video.</li>
          </ul>
          <Link className="text-link" to="/workspace">
            Go to the workspace <ArrowRight size={17} />
          </Link>
        </div>
      </section>
    </main>
  );
}
export function NotFound() {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="section-container not-found"
    >
      <span className="section-label">404 / Page not found</span>
      <h1>That page isn't here.</h1>
      <p>
        The address may be incorrect. Your open workspace drafts are still
        available.
      </p>
      <Button asChild>
        <Link to="/">
          Go Home <ArrowRight size={16} />
        </Link>
      </Button>
      <Button asChild variant="outline">
        <Link to="/workspace">Open workspace</Link>
      </Button>
    </main>
  );
}
