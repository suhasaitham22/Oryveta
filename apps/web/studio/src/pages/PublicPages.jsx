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
        <div className="home-copy">
          <Reveal>
            <span className="section-label">Open-source software delivery</span>
          </Reveal>
          <Reveal delay={0.08}>
            <h1>Build new apps.<br />Improve your code.</h1>
          </Reveal>
          <Reveal delay={0.16}>
            <p className="home-deck">
              Oryveta brings project planning, repository analysis and team
              collaboration into one workspace. Start with an app idea or a
              codebase you want to improve.
            </p>
          </Reveal>
          <Reveal delay={0.24} className="home-actions">
            <Button asChild size="lg">
              <Link to="/workspace/new">
                Plan a new app <ArrowRight size={17} />
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link to="/workspace/evolve">
                Explore existing code <GitBranch size={17} />
              </Link>
            </Button>
          </Reveal>
          <div className="home-editions">
            <div><span>Available in your browser</span><strong>Briefs, projects & private conversations</strong></div>
            <div><span>With the self-hosted engine</span><strong>Starter code & repository analysis</strong></div>
          </div>
        </div>
        <ProductScene />
      </section>
      <section className="home-next section-container">
        <Reveal>
          <span className="section-label">The goal · in development</span>
          <h2>An AI software factory.<br />You stay in control.</h2>
        </Reveal>
        <Reveal delay={0.12}>
          <p>
            Describe the software you need. Our goal is agents that plan,
            implement and test the work, then prepare changes for your approval.
            Automated coding, publishing and on-call maintenance are planned—not
            running in the hosted app today.
          </p>
          <Link className="text-link" to="/what-we-do">
            See what you can do today <ArrowRight size={17} />
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
          One workspace
          <br />
          for software work.
        </h1>
        <p className="page-deck">
          For developers, independent builders and teams turning requirements
          into new applications or improvements to existing code.
        </p>
      </Reveal>
      <section className="editorial-split">
        <h2>
          From a requirement
          <br />
          to a reviewed change.
        </h2>
        <div>
          <p>
            Requirements, source findings and team decisions often live in
            separate tools. Oryveta organizes them around a project, so you can
            understand the requested change and decide what to do next.
          </p>
          <p>
            We are building toward AI agents that implement and test that work.
            People will still control repository access, review results and
            approve publishing or deployment.
          </p>
        </div>
      </section>
      <section className="principle-grid" aria-label="Open source principles">
        <Reveal>
          <Code2 size={24} />
          <h2>Open and self-hostable.</h2>
          <p>
            Apache-2.0 source. Read the implementation, run it yourself, and
            contribute improvements. Third-party licenses remain their own.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <LockKeyhole size={24} />
          <h2>Private by default.</h2>
          <p>
            Choose who can join a project and who can read a conversation.
            Project membership does not automatically share private chats.
          </p>
        </Reveal>
        <Reveal delay={0.2}>
          <FileText size={24} />
          <h2>Results you can inspect.</h2>
          <p>
            Export your brief, inspect source findings and download starter
            code. Each result says how it was produced and what still needs
            testing or review.
          </p>
        </Reveal>
      </section>
      <section className="stage-note">
        <span className="section-label">Available today</span>
        <h2>
          Plan together.
          <br />
          Inspect source locally.
        </h2>
        <p>
          In the browser, create project briefs, manage invitations and share
          private conversations. Start New and Evolve also offer exportable
          planning drafts. With the self-hosted engine, prepare starter
          repositories and analyze source snapshots. The complete AI coding and
          delivery workflow is still being built.
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
        <span className="section-label">What you can do</span>
        <h1>
          Start a new app.
          <br />
          Understand an existing one.
        </h1>
        <p className="page-deck">
          Choose Start New for an application idea or Evolve for an existing
          codebase. Both help you define the work, inspect the available results
          and explain the next step to your team.
        </p>
      </Reveal>
      <section className="journey-detail">
        <Reveal>
          <span className="section-label">
            <Sparkles size={17} />
            01 / Start New
          </span>
          <h2>
            Turn an idea
            <br />into an actionable brief.
          </h2>
          <p>
            Describe who the app is for, what it should do and how you will
            check it. Export the brief, then use the self-hosted engine if you
            want a starter repository.
          </p>
          <Button asChild>
            <Link to="/workspace/new">
              Open Start New <ArrowRight size={16} />
            </Link>
          </Button>
        </Reveal>
        <ol>
          <li>
            <strong>Define the application</strong>
            <p>
              Record users, features, constraints and acceptance criteria.
              Download the requirements as a project brief.
            </p>
          </li>
          <li>
            <strong>Prepare starter code locally</strong>
            <p>
              Choose a template in the self-hosted engine and download its
              source ZIP. It is a starting point, not an AI-built custom app.
            </p>
          </li>
          <li>
            <strong>Write a demo script</strong>
            <p>
              Use Demo Studio to describe the intended user experience.
              Export editable scenes as JSON; video rendering is separate.
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
            Understand a codebase
            <br />
            before changing it.
          </h2>
          <p>
            Set a change goal, inspect an authorized source snapshot and
            review candidate issues. Current analysis is read-only: it does not
            change your code or prove that the application works.
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
              Describe the current behavior, the improvement you need and
              the regressions to avoid.
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
            <strong>Review findings and plan the change</strong>
            <p>
              Use the reported files, lines and limitations to decide what
              needs investigation. Verified fixes and automatic PRs are planned.
            </p>
          </li>
        </ol>
      </section>
      <section className="delivery-boundaries">
        <div>
          <span className="section-label">Available now</span>
          <h2>
            Planning and collaboration.
            <br />
            Self-hosted source tools.
          </h2>
          <p>
            The browser supports project briefs, invitations, private
            conversations and draft exports. The self-hosted engine adds starter
            repositories and bounded source analysis. Running background
            analysis requires a configured worker; cloud hosting is not ready yet.
          </p>
        </div>
        <div>
          <h3>Still in development</h3>
          <ul>
            <li>AI agents that implement changes and run independent tests.</li>
            <li>Reviewed GitHub pull requests, previews and deployments.</li>
            <li>On-call investigation, maintenance and reusable lessons.</li>
            <li>AI-native modernization of applications and packages.</li>
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
