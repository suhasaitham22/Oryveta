import React from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Code2,
  GitBranch,
  Sparkles,
  Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import ProductScene, { ArtifactDocument } from "@/components/ProductScene.jsx";
import Reveal from "@/components/Reveal.jsx";
import {
  LocalExampleReceipt,
  LocalExampleRecord,
} from "@/components/LocalExample.jsx";
import {
  JourneyMark,
  LostOrbit,
  PrincipleMark,
  StageRail,
} from "@/components/SiteArt.jsx";
import { productArtifacts } from "@/components/productArtifacts";
import { SOURCE_URL, plans } from "@/lib/plans";

/* Public pages render with CSS/SVG artwork only: no animation library and no
   WebGL in the initial path. Every claim below says where it runs today —
   hosted, on your own machine, or planned — and the one result we show is a
   stored file a visitor can download. */

const paths = [
  {
    variant: "new",
    label: "01 / Start New",
    title: "Scope a new application",
    text: "Describe the software you need and leave with requirements your team can act on.",
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
    title: "Scope a change to code you maintain",
    text: "Set the change goal, inspect an authorized snapshot and decide what deserves a repair attempt.",
    points: [
      "Change goal, current behavior and regressions to avoid",
      "Read-only analysis with persisted run events",
      "Candidate issues reported with files and lines",
    ],
    to: "/workspace/evolve",
    cta: "Open Evolve",
  },
];

/* available = hosted workspace, local = your machine, planned = not built. */
const stages = [
  {
    title: "Scope the change with your team",
    state: "available",
    detail:
      "Projects, roles, private chats and exportable briefs in the hosted workspace, free while it is in preview.",
  },
  {
    title: "Read the snapshot before touching it",
    state: "local",
    detail:
      "Bounded static analysis of an imported archive on a self-hosted engine. Imported code is never executed, and background analysis needs a configured worker.",
  },
  {
    title: "Repair one scoped target",
    state: "local",
    detail:
      "The command-line tool calls your own Ollama model and edits a disposable copy of your code. The configured checks then run in a network-disabled container, and a crash resumes from a checkpoint.",
  },
  {
    title: "Hand the patch to a human",
    state: "local",
    detail:
      "A run ends with a patch, its check results and a needs-review status. Nothing is committed, pushed or deployed for you.",
  },
  {
    title: "Hosted agent runs and shared history",
    state: "planned",
    detail:
      "Starting repairs from the workspace, with shared run history, a review workflow and budget administration.",
  },
  {
    title: "Pull requests, previews and on-call",
    state: "planned",
    detail:
      "Reviewed pull requests, deploy previews and maintenance follow-up.",
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
    text: "A change arrives as a patch with the checks that ran against it, the model that produced it and the hashes of what it read. Each result says what it does not prove.",
  },
];

export function Home() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page home-page">
      <section className="home-hero">
        <div className="section-container home-hero-inner">
          <div className="home-hero-copy">
            <span className="section-label hero-rise">
              Open source · for teams maintaining existing code
            </span>
            <h1 className="hero-rise hero-rise-2">
              A code change you can
              <br />
              review, with its evidence.
            </h1>
            <p className="home-deck hero-rise hero-rise-3">
              Oryveta is for small engineering teams who maintain software
              someone else wrote. We start narrow: one scoped repair in a Python
              service, done on your own machine with your own model, checked
              against tests it has to pass, then stopped for human review. The
              hosted workspace is where your team scopes that change and keeps
              the record.
            </p>
            <div className="home-actions hero-rise hero-rise-4">
              <Button asChild size="lg">
                <Link to="/workspace">
                  Open a free workspace{" "}
                  <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link to="/#local-example">
                  See the recorded example{" "}
                  <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </Button>
            </div>
            <dl className="home-editions hero-rise hero-rise-5">
              <div>
                <dt>Free preview, in your browser</dt>
                <dd>Projects, roles, private chats &amp; exportable briefs</dd>
              </div>
              <div>
                <dt>Open source, on your machine</dt>
                <dd>Checked repairs with your own Ollama models</dd>
              </div>
              <div>
                <dt>Not built yet</dt>
                <dd>Hosted agent runs, shared history &amp; review workflow</dd>
              </div>
            </dl>
          </div>
          <div className="home-hero-art hero-rise hero-rise-2">
            <LocalExampleReceipt />
          </div>
        </div>
      </section>

      <div className="home-example section-container">
        <LocalExampleRecord />
      </div>

      <section className="home-next section-container">
        <Reveal className="home-next-copy">
          <span className="section-label">Honest status</span>
          <h2>
            What runs where,
            <br />
            as of today.
          </h2>
          <p>
            The hosted site coordinates the work. The agent that edits code runs
            locally, under your control, against models you host. We label every
            step rather than implying one continuous automated pipeline.
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

      <section className="home-paths section-container">
        <Reveal className="band-head">
          <span className="section-label">Two ways in</span>
          <h2>
            Scope a change.
            <br />
            Or scope something new.
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

      <section className="home-plans section-container">
        <Reveal className="band-head">
          <span className="section-label">Pricing</span>
          <h2>Free to start. The paid plan is still a proposal.</h2>
          <p>
            The software is Apache-2.0 at $0 and always self-hostable. The
            hosted workspace is free while it is in preview, inside shared
            capacity. You supply the compute for anything that runs code.
          </p>
        </Reveal>
        <ul className="plan-teasers">
          {plans.map((plan, index) => (
            <Reveal as="li" key={plan.id} delay={index * 90}>
              <span className={`plan-state plan-state-${plan.availability}`}>
                {plan.availabilityLabel}
              </span>
              <h3>{plan.name}</h3>
              <p className="plan-price">
                <strong>{plan.price}</strong>
                <span>{plan.unit}</span>
              </p>
              <p>{plan.summary}</p>
            </Reveal>
          ))}
        </ul>
        <Link className="text-link" to="/pricing">
          Read the full pricing page{" "}
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </section>

      <section className="home-stage section-container">
        <Reveal className="band-head">
          <span className="section-label">Artifacts, not transcripts</span>
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
              Scope the change in your browser, then run the engine yourself to
              inspect the repository or attempt a checked repair. The
              implementation is Apache-2.0, so you can read exactly how every
              result was produced.
            </p>
            <div className="home-actions">
              <Button asChild size="lg">
                <Link to="/workspace">
                  Open a free workspace{" "}
                  <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </Button>
              <a
                className="text-link"
                href={SOURCE_URL}
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
              Hosted background analysis needs a configured worker, and agent
              runs are not hosted yet. The checked repair tool runs on your
              machine.
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
          One workspace for the
          <br />
          code you already maintain.
        </h1>
        <p className="page-deck hero-rise hero-rise-3">
          An open-source project for small engineering teams who spend most of
          their time changing software they did not write. The first group we
          are trying to qualify is teams maintaining Python services.
        </p>
      </header>
      <section className="editorial-split section-container">
        <Reveal>
          <h2>
            Why we start with a patch,
            <br />
            not a chat transcript.
          </h2>
        </Reveal>
        <Reveal delay={90}>
          <p>
            An assistant that answers in prose leaves the hard part — deciding
            whether a change is safe — exactly where it was. The unit of work we
            care about is a reviewable diff with the checks that ran against it,
            the model digest that produced it and the hashes of what it read.
          </p>
          <p>
            So the first thing we built is narrow on purpose: a local agent that
            repairs one scoped target, re-runs behavioral checks it has to pass,
            checkpoints itself so a crash does not lose the attempt, then stops
            at needs-review. The hosted workspace coordinates that work —
            projects, roles, private conversations and briefs — and keeps the
            record.
          </p>
          <p>
            What we have not solved, in plain terms: the agent only runs on your
            machine, hosted agent runs and shared run history are not built, our
            published evidence is one stored example rather than a track record,
            and small local models still fail on changes that cross several
            files. Those limits ship next to every result.
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
            Repair locally.
          </h2>
          <p>
            In the browser: project briefs, invitations, private conversations
            and draft exports, free while the hosted workspace is in preview.
            With the self-hosted engine: starter repositories and bounded source
            analysis. On your own machine: the command-line tool that attempts a
            checked repair and hands back a patch. Hosted agent runs, a review
            workflow and billing are not built yet.
          </p>
          <div className="home-actions">
            <a
              className="text-link"
              href={SOURCE_URL}
              target="_blank"
              rel="noreferrer"
            >
              Explore the source <ArrowUpRight size={17} aria-hidden="true" />
            </a>
            <Link className="text-link" to="/pricing">
              See what it costs <ArrowRight size={17} aria-hidden="true" />
            </Link>
          </div>
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
          Scope the work here.
          <br />
          Repair the code locally.
        </h1>
        <p className="page-deck hero-rise hero-rise-3">
          Three things work today: Start New for an application idea, Evolve for
          a codebase you maintain, and the local command-line tool that attempts
          one checked repair and hands back a patch for review.
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
              <strong>Review findings, then choose a target</strong>
              <p>
                Use the reported files, lines and limitations to pick one scoped
                repair for the local tool below. Starting that repair from the
                hosted workspace, and opening pull requests, are still planned.
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

      <section className="journey-detail journey-detail-local section-container">
        <Reveal className="journey-detail-main">
          <span className="section-label">
            <Terminal size={17} aria-hidden="true" />
            03 / Checked repair · your machine
          </span>
          <h2>
            Attempt one repair,
            <br />
            then prove it was checked.
          </h2>
          <p>
            This part is a command-line tool from the open-source repository,
            not a button in this website. It needs Docker and your own Ollama
            model. It never publishes code: a run ends with a patch marked
            needs-review.
          </p>
          <div className="home-actions">
            <Button asChild variant="outline">
              <Link to="/#local-example">
                See a recorded run <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </Button>
            <a
              className="text-link"
              href={SOURCE_URL}
              target="_blank"
              rel="noreferrer"
            >
              Get the tool <ArrowUpRight size={16} aria-hidden="true" />
            </a>
          </div>
          <ol>
            <li>
              <strong>Point it at one scoped target</strong>
              <p>
                A single failing behavior in a Python module, with the checks
                that should pass once it is fixed.
              </p>
            </li>
            <li>
              <strong>Let it edit, then re-check</strong>
              <p>
                The model edits a disposable copy of your code on your machine,
                then the configured checks execute inside a network-disabled
                container. A checkpoint means a crash does not lose the attempt.
              </p>
            </li>
            <li>
              <strong>Review the patch and the record</strong>
              <p>
                You receive the diff, each check result, the model digest and the
                hashes of what was read. Applying it stays your decision.
              </p>
            </li>
          </ol>
        </Reveal>
        <Reveal className="journey-detail-art" delay={120}>
          <LocalExampleReceipt />
          <p className="art-caption">
            One stored local run · synthetic example, not live activity
          </p>
        </Reveal>
      </section>

      <section className="section-container">
        <Reveal className="delivery-boundaries">
          <div>
            <span className="section-label">Available now</span>
            <h2>
              Hosted planning.
              <br />
              Local source tools.
            </h2>
            <p>
              The browser supports project briefs, invitations, private
              conversations and draft exports, free while the hosted workspace
              is in preview. The self-hosted engine adds starter repositories
              and bounded source analysis; background analysis requires a
              configured worker. The repair tool runs on your machine, with your
              models.
            </p>
            <div className="home-actions">
              <Link className="text-link" to="/workspace">
                Go to the workspace <ArrowRight size={17} aria-hidden="true" />
              </Link>
              <Link className="text-link" to="/pricing">
                See what it costs <ArrowRight size={17} aria-hidden="true" />
              </Link>
            </div>
          </div>
          <div className="boundary-planned">
            <h3>Still in development</h3>
            <ul>
              <li>Starting agent runs from the hosted workspace at all.</li>
              <li>Shared run history, review workflow and budget limits.</li>
              <li>Reviewed GitHub pull requests, previews and deployments.</li>
              <li>Repairs that span several files or non-Python services.</li>
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
