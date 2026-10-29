import React from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Code2,
  FileText,
  GitBranch,
  LockKeyhole,
  ScanSearch,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import ProductScene, { ArtifactDocument } from "@/components/ProductScene.jsx";
import Reveal from "@/components/Reveal.jsx";
import {
  JourneyMark,
  LostOrbit,
  OrbitField,
  PrincipleMark,
  StageRail,
} from "@/components/SiteArt.jsx";
import { productArtifacts } from "@/components/productArtifacts";

/* Public pages render with CSS/SVG artwork only: no animation library and no
   WebGL in the initial path. Every claim below separates what the workspace
   does today from what is still being built. */

const capabilities = [
  {
    icon: FileText,
    title: "Write a brief you can export",
    where: "In your browser",
    text: "Record users, features, constraints and acceptance criteria, then download the requirements as a project brief.",
  },
  {
    icon: LockKeyhole,
    title: "Decide who sees what",
    where: "In your browser",
    text: "Invite people to a project and keep conversations separate. Project membership does not automatically share private chats.",
  },
  {
    icon: ScanSearch,
    title: "Read a codebase before changing it",
    where: "Self-hosted engine",
    text: "Import a source snapshot, run bounded static analysis and read persisted events and findings. Imported code is never executed.",
  },
];

const paths = [
  {
    variant: "new",
    label: "01 / Start New",
    title: "Turn an idea into an actionable brief",
    text: "Describe the application you need and leave with requirements your team can act on.",
    points: [
      "Users, features, constraints and acceptance criteria",
      "Exportable brief and demo script drafts",
      "Starter repository from the self-hosted engine",
    ],
    to: "/workspace/new",
    cta: "Open Start New",
  },
  {
    variant: "evolve",
    label: "02 / Evolve",
    title: "Understand a codebase before you touch it",
    text: "Set a change goal, inspect an authorized snapshot and decide what deserves investigation.",
    points: [
      "Change goal, current behavior and regressions to avoid",
      "Read-only analysis with persisted run events",
      "Candidate issues reported with files and lines",
    ],
    to: "/workspace/evolve",
    cta: "Open Evolve",
  },
];

const stages = [
  {
    title: "Plan the work",
    state: "available",
    detail: "Briefs, acceptance criteria, invitations and exports in the browser.",
  },
  {
    title: "Review the source",
    state: "available",
    detail: "Bounded read-only analysis with the self-hosted engine.",
  },
  {
    title: "Implement the change",
    state: "planned",
    detail: "Agents that edit code and explain every change they make.",
  },
  {
    title: "Prove it works",
    state: "planned",
    detail: "Independent tests and results you can check before review.",
  },
  {
    title: "Publish and maintain",
    state: "planned",
    detail: "Reviewed pull requests, previews and on-call follow-up.",
  },
];

const principles = [
  {
    title: "Open and self-hostable.",
    text: "Apache-2.0 source. Read the implementation, run it yourself, and contribute improvements. Third-party licenses remain their own.",
  },
  {
    title: "Private by default.",
    text: "Choose who can join a project and who can read a conversation. Project membership does not automatically share private chats.",
  },
  {
    title: "Results you can inspect.",
    text: "Export your brief, inspect source findings and download starter code. Each result says how it was produced and what still needs testing or review.",
  },
];

export function Home() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page home-page">
      <section className="home-hero">
        <div className="section-container home-hero-inner">
          <div className="home-hero-copy">
            <span className="section-label hero-rise">
              Open-source software delivery
            </span>
            <h1 className="hero-rise hero-rise-2">
              Build new apps.
              <br />
              Improve your code.
            </h1>
            <p className="home-deck hero-rise hero-rise-3">
              Oryveta brings project planning, repository analysis and team
              collaboration into one workspace. Start with an app idea or a
              codebase you want to improve.
            </p>
            <div className="home-actions hero-rise hero-rise-4">
              <Button asChild size="lg">
                <Link to="/workspace/new">
                  Plan a new app <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link to="/workspace/evolve">
                  Explore existing code{" "}
                  <GitBranch size={17} aria-hidden="true" />
                </Link>
              </Button>
            </div>
            <dl className="home-editions hero-rise hero-rise-5">
              <div>
                <dt>Available in your browser</dt>
                <dd>Briefs, projects &amp; private conversations</dd>
              </div>
              <div>
                <dt>With the self-hosted engine</dt>
                <dd>Starter code &amp; repository analysis</dd>
              </div>
            </dl>
          </div>
          <div className="home-hero-art hero-rise hero-rise-2">
            <OrbitField />
          </div>
        </div>
      </section>

      <section className="home-capabilities section-container">
        <Reveal className="band-head">
          <span className="section-label">Available today</span>
          <h2>What the workspace already does.</h2>
          <p>
            Three capabilities are working now. Everything else on this page is
            labelled as planned.
          </p>
        </Reveal>
        <ul className="capability-grid">
          {capabilities.map(({ icon: Icon, title, where, text }, index) => (
            <Reveal as="li" key={title} delay={index * 90} className="capability">
              <span className="capability-mark" aria-hidden="true">
                <Icon size={19} />
              </span>
              <h3>{title}</h3>
              <p>{text}</p>
              <span className="capability-where">{where}</span>
            </Reveal>
          ))}
        </ul>
      </section>

      <section className="home-paths section-container">
        <Reveal className="band-head">
          <span className="section-label">Two ways in</span>
          <h2>
            Start something new.
            <br />
            Or understand what exists.
          </h2>
        </Reveal>
        <div className="path-cards">
          {paths.map(
            ({ variant, label, title, text, points, to, cta }, index) => (
              <Reveal
                as="article"
                key={variant}
                delay={index * 110}
                className={`path-card path-card-${variant}`}
              >
                <div className="path-card-top">
                  <JourneyMark variant={variant} />
                  <span className="section-label">{label}</span>
                </div>
                <h3>{title}</h3>
                <p>{text}</p>
                <ul>
                  {points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
                <Link className="text-link" to={to}>
                  {cta} <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </Reveal>
            ),
          )}
        </div>
      </section>

      <section className="home-stage section-container">
        <Reveal className="band-head">
          <span className="section-label">Artifacts, not promises</span>
          <h2>Everything you produce stays readable.</h2>
          <p>
            Briefs, source reviews and demo scripts leave the workspace as files
            you can keep. The documents below are illustrative examples of that
            output.
          </p>
        </Reveal>
        <Reveal delay={80}>
          <ProductScene />
        </Reveal>
      </section>

      <section className="home-next section-container">
        <Reveal className="home-next-copy">
          <span className="section-label">The goal · in development</span>
          <h2>
            An AI software factory.
            <br />
            You stay in control.
          </h2>
          <p>
            Describe the software you need. Our goal is agents that plan,
            implement and test the work, then prepare changes for your approval.
            Automated coding, publishing and on-call maintenance are planned—not
            running in the hosted app today.
          </p>
          <Link className="text-link" to="/what-we-do">
            See what you can do today{" "}
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </Reveal>
        <Reveal className="home-next-rail" delay={120}>
          <StageRail stages={stages} />
        </Reveal>
      </section>

      <section className="home-cta">
        <div className="section-container home-cta-inner">
          <div className="home-cta-copy">
            <span className="section-label">Start here</span>
            <h2>
              Bring your next change
              <br />
              into one workspace.
            </h2>
            <p>
              Write the brief in your browser, or run the engine yourself to
              inspect a repository. The implementation is Apache-2.0, so you can
              read exactly how every result was produced.
            </p>
            <div className="home-actions">
              <Button asChild size="lg">
                <Link to="/workspace/new">
                  Plan a new app <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </Button>
              <a
                className="text-link"
                href="https://github.com/suhasaitham22/Oryveta"
                target="_blank"
                rel="noreferrer"
              >
                Read the source <ArrowUpRight size={17} aria-hidden="true" />
              </a>
            </div>
          </div>
          <ul className="home-cta-notes">
            <li>
              Drafts in Start New, Evolve and Demo Studio live in the open tab.
              Export them before reloading.
            </li>
            <li>
              Background analysis needs a configured worker, and cloud hosting
              is not ready yet.
            </li>
          </ul>
        </div>
      </section>
    </main>
  );
}

export function About() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page editorial-page">
      <header className="page-hero section-container">
        <span className="section-label hero-rise">About Oryveta</span>
        <h1 className="hero-rise hero-rise-2">
          One workspace
          <br />
          for software work.
        </h1>
        <p className="page-deck hero-rise hero-rise-3">
          For developers, independent builders and teams turning requirements
          into new applications or improvements to existing code.
        </p>
      </header>
      <section className="editorial-split section-container">
        <Reveal>
          <h2>
            From a requirement
            <br />
            to a reviewed change.
          </h2>
        </Reveal>
        <Reveal delay={90}>
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
        </Reveal>
      </section>
      <section
        className="principle-grid section-container"
        aria-label="Open source principles"
      >
        {principles.map(({ title, text }, index) => (
          <Reveal key={title} delay={index * 100}>
            <PrincipleMark index={index} />
            <h2>{title}</h2>
            <p>{text}</p>
          </Reveal>
        ))}
      </section>
      <section className="section-container">
        <Reveal className="stage-note">
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
            repositories and analyze source snapshots. The complete AI coding
            and delivery workflow is still being built.
          </p>
          <a
            className="text-link"
            href="https://github.com/suhasaitham22/Oryveta"
            target="_blank"
            rel="noreferrer"
          >
            Explore the source <ArrowUpRight size={17} aria-hidden="true" />
          </a>
        </Reveal>
      </section>
    </main>
  );
}

export function WhatWeDo() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page editorial-page">
      <header className="page-hero section-container">
        <span className="section-label hero-rise">What you can do</span>
        <h1 className="hero-rise hero-rise-2">
          Start a new app.
          <br />
          Understand an existing one.
        </h1>
        <p className="page-deck hero-rise hero-rise-3">
          Choose Start New for an application idea or Evolve for an existing
          codebase. Both help you define the work, inspect the available results
          and explain the next step to your team.
        </p>
      </header>

      <section className="journey-detail section-container">
        <Reveal className="journey-detail-main">
          <span className="section-label">
            <Sparkles size={17} aria-hidden="true" />
            01 / Start New
          </span>
          <h2>
            Turn an idea
            <br />
            into an actionable brief.
          </h2>
          <p>
            Describe who the app is for, what it should do and how you will
            check it. Export the brief, then use the self-hosted engine if you
            want a starter repository.
          </p>
          <Button asChild>
            <Link to="/workspace/new">
              Open Start New <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </Button>
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
                Use Demo Studio to describe the intended user experience. Export
                editable scenes as JSON; video rendering is separate.
              </p>
            </li>
          </ol>
        </Reveal>
        <Reveal className="journey-detail-art" delay={120}>
          <ArtifactDocument artifact={productArtifacts[0]} />
          <p className="art-caption">
            Illustrative brief · authored by you, not generated
          </p>
        </Reveal>
      </section>

      <section className="journey-detail section-container">
        <Reveal className="journey-detail-main">
          <span className="section-label">
            <GitBranch size={17} aria-hidden="true" />
            02 / Evolve
          </span>
          <h2>
            Understand a codebase
            <br />
            before changing it.
          </h2>
          <p>
            Set a change goal, inspect an authorized source snapshot and review
            candidate issues. Current analysis is read-only: it does not change
            your code or prove that the application works.
          </p>
          <Button asChild variant="outline">
            <Link to="/workspace/evolve">
              Open Evolve <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </Button>
          <ol>
            <li>
              <strong>Set a change goal</strong>
              <p>
                Describe the current behavior, the improvement you need and the
                regressions to avoid.
              </p>
            </li>
            <li>
              <strong>Inspect the snapshot locally</strong>
              <p>
                Import a ZIP. Start or cancel static analysis, then read
                persisted run events and findings. Imported code is never
                executed.
              </p>
            </li>
            <li>
              <strong>Review findings and plan the change</strong>
              <p>
                Use the reported files, lines and limitations to decide what
                needs investigation. Verified fixes and automatic PRs are
                planned.
              </p>
            </li>
          </ol>
        </Reveal>
        <Reveal className="journey-detail-art" delay={120}>
          <ArtifactDocument artifact={productArtifacts[1]} />
          <p className="art-caption">
            Illustrative review · read-only analysis, no code changes
          </p>
        </Reveal>
      </section>

      <section className="section-container">
        <Reveal className="delivery-boundaries">
          <div>
            <span className="section-label">Available now</span>
            <h2>
              Planning and collaboration.
              <br />
              Self-hosted source tools.
            </h2>
            <p>
              The browser supports project briefs, invitations, private
              conversations and draft exports. The self-hosted engine adds
              starter repositories and bounded source analysis. Running
              background analysis requires a configured worker; cloud hosting is
              not ready yet.
            </p>
            <Link className="text-link" to="/workspace">
              Go to the workspace <ArrowRight size={17} aria-hidden="true" />
            </Link>
          </div>
          <div className="boundary-planned">
            <h3>Still in development</h3>
            <ul>
              <li>AI agents that implement changes and run independent tests.</li>
              <li>Reviewed GitHub pull requests, previews and deployments.</li>
              <li>On-call investigation, maintenance and reusable lessons.</li>
              <li>AI-native modernization of applications and packages.</li>
            </ul>
            <Code2 size={20} aria-hidden="true" />
          </div>
        </Reveal>
      </section>
    </main>
  );
}

export function NotFound() {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="public-page not-found section-container"
    >
      <div className="not-found-copy">
        <span className="section-label">404 / Page not found</span>
        <h1>That page isn&apos;t here.</h1>
        <p>
          The address may be incorrect. Your open workspace drafts are still
          available.
        </p>
        <div className="home-actions">
          <Button asChild>
            <Link to="/">
              Go Home <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/workspace">Open workspace</Link>
          </Button>
        </div>
      </div>
      <LostOrbit />
    </main>
  );
}
