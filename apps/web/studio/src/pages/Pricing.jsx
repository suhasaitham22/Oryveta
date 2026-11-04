import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, Check, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";
import Reveal from "@/components/Reveal.jsx";
import { ExampleDownloads } from "@/components/LocalExample.jsx";
import { SOURCE_URL, TEAM_BUILDERS, TEAM_PRICE, plans } from "@/lib/plans";

/* Two plans, one of them a published proposal. There is no billing service in
   this repository, so every call to action on this page opens the free
   workspace or the source: nothing pretends to take money. */

const questions = [
  {
    q: "Can I pay you today?",
    a: "No. There is no checkout, invoice or subscription in the product, and no payment processor is connected. The Team price is published so teams can tell us whether it is close before we build billing.",
  },
  {
    q: "Who supplies the compute?",
    a: "You do, in both plans. The local command-line tool calls your own Ollama model and edits a disposable copy of your code on your machine; the configured checks then execute inside a network-disabled Docker container. Hosted background analysis only runs where an operator has configured a worker. We do not resell inference.",
  },
  {
    q: "What is actually available right now?",
    a: "The hosted workspace is a free preview: projects, roles, private chats and exportable briefs. The open-source local tool attempts scoped repairs, runs its checks and stops at needs-review. Hosted agent runs, a review workflow and shared run history are not built yet.",
  },
  {
    q: "Is anything I use today being put behind the paid plan?",
    a: "No. This change paywalls nothing that already exists: the preview workspace, its roles and its private chats stay exactly as they are. The other half of the answer matters too — the hosted workspace is free while it is in preview, inside shared capacity we may throttle or pause, so it is not a perpetual free-hosting promise. Any later change to hosted terms requires advance notice, your consent before it binds an existing workspace, and a working export path. The Apache-2.0 software stays at $0 and self-hosting never needs a subscription.",
  },
  {
    q: `Why ${TEAM_PRICE} per workspace instead of per seat?`,
    a: `The proposed workspace plan covers up to ${TEAM_BUILDERS} builders and coordination around their runs. It does not include inference or sandbox capacity. This is a pricing hypothesis to validate with teams, not a claim of equivalent features or savings against other coding tools.`,
  },
  {
    q: "How do I check your quality claim before trusting it?",
    a: "Download the recorded local example. It contains the patch, every configured check, the model digest and the hashes of the source archive and implementation, plus the limits of what one stored run can show.",
  },
];

export default function Pricing() {
  return (
    <main id="main-content" tabIndex={-1} className="public-page pricing-page">
      <header className="page-hero section-container">
        <span className="section-label hero-rise">Pricing</span>
        <h1 className="hero-rise hero-rise-2">
          Free software.
          <br />
          Your compute.
        </h1>
        <p className="page-deck hero-rise hero-rise-3">
          Start with free, open-source tools and a capacity-limited hosted
          preview. Team is a proposed subscription for shared run review.
          No hosted compute is included, and nothing is charged today.
        </p>
      </header>

      <section
        className="plan-grid section-container"
        aria-label="Plans"
      >
        {plans.map((plan, index) => (
          <Reveal
            as="article"
            key={plan.id}
            delay={index * 90}
            className={`plan-card plan-card-${plan.availability}`}
          >
            <header>
              <h2>{plan.name}</h2>
              <span className={`plan-state plan-state-${plan.availability}`}>
                {plan.availabilityLabel}
              </span>
            </header>
            <p className="plan-price">
              <strong>{plan.price}</strong>
              <span>{plan.unit}</span>
            </p>
            <p className="plan-summary">{plan.summary}</p>
            <ul className="plan-includes" aria-label={`${plan.name}: included`}>
              {plan.includes.map((item) => (
                <li key={item}>
                  <Check size={15} aria-hidden="true" />
                  {item}
                </li>
              ))}
            </ul>
            <ul
              className="plan-excludes"
              aria-label={`${plan.name}: not included`}
            >
              {plan.excludes.map((item) => (
                <li key={item}>
                  <Minus size={15} aria-hidden="true" />
                  {item}
                </li>
              ))}
            </ul>
            <div className="plan-actions">
              <Button asChild variant={index === 0 ? "default" : "outline"}>
                <Link to={plan.cta.to}>
                  {plan.cta.label} <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </Button>
            </div>
            <p className="plan-note">{plan.note}</p>
          </Reveal>
        ))}
      </section>

      <section className="pricing-evidence section-container">
        <Reveal className="pricing-evidence-copy">
          <span className="section-label">Before you decide</span>
          <h2>Judge the work, not the pitch.</h2>
          <p>
            One recorded local run is published on this site as files: the
            proposed patch, the checks that ran against it, the model digest
            and the source hashes. It is a single synthetic example from a
            local session, not current activity and not a customer result.
          </p>
          <Link className="text-link" to="/#local-example">
            See the recorded example on the home page{" "}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </Reveal>
        <Reveal className="pricing-evidence-files" delay={80}>
          <ExampleDownloads />
          <a
            className="text-link"
            href={SOURCE_URL}
            target="_blank"
            rel="noreferrer"
          >
            Read the implementation <ArrowUpRight size={16} aria-hidden="true" />
          </a>
        </Reveal>
      </section>

      <section className="pricing-faq section-container">
        <Reveal className="band-head">
          <span className="section-label">Straight answers</span>
          <h2>What you are and are not buying.</h2>
        </Reveal>
        <div className="faq-list">
          {questions.map(({ q, a }, index) => (
            <Reveal as="details" key={q} delay={index * 50} className="faq-item">
              <summary>{q}</summary>
              <p>{a}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="pricing-close section-container">
        <Reveal className="stage-note">
          <span className="section-label">Try Oryveta</span>
          <h2>Start with a maintenance task.</h2>
          <p>
            Plan a change in the workspace, then use the local setup guide for
            checked repairs. Share feedback on the workflow or proposed price
            through a public issue—without private code or credentials.
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
              href={`${SOURCE_URL}/issues`}
              target="_blank"
              rel="noreferrer"
            >
              Open an issue <ArrowUpRight size={17} aria-hidden="true" />
            </a>
          </div>
        </Reveal>
      </section>
    </main>
  );
}
