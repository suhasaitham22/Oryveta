# Branding and domain decisions

## Locked product identity

**Oryveta** (previous working name: MASGENT). **Build thoughtfully. Evolve continuously.** remains a secondary brand statement, not a substitute for explaining the product. Current public copy leads with reviewable maintenance changes and their evidence, for small engineering teams. The implemented Home and footer wording live in `apps/web/studio/src/pages/PublicPages.jsx` and `components/SiteFooter.jsx`; do not reintroduce the superseded “Build new apps. Improve your code.” hero as the current design.

Two workspace journeys remain **Start New** and **Evolve**. The current evidence-led design uses off-white surfaces, Geist typography, a dark working rail and cobalt accents. The decorative orbital hero is retired; the optional illustrative spatial viewer remains. Keep olive/yellow styling in historical records only, not new interfaces. Public navigation is **Home / About / What We Do / Pricing / Workspace**; see [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md). Avoid names that imply Kaggle-only functionality.

## Domain

Current hosted product: https://oryveta.vercel.app. This Vercel alias serves the React Studio; production authentication and collaboration verification are recorded in [STATUS.md](STATUS.md). A deployed frontend does not establish that a cloud coding worker is running.

Earlier Namecheap checks reported oryveta.com around $10.98 for the initial year and oryveta.xyz around $2 first year. These are historical quotes, not current availability or renewal commitments. No paid domain purchase is recorded in this repository; confirm ownership and current terms before presenting a domain as owned.

## Copyright and licensing

Copyright © 2026 Suhas Aitham and Oryveta contributors. Original source licensed Apache-2.0; see LICENSE and NOTICE. Open source does not automatically grant exclusive trademark rights. Name uniqueness and trademark clearance require further professional assessment before broad commercialization.

## Voice and wording

Say what the product does before anything stylish. A slogan never replaces the one-sentence explanation: *Oryveta is an open-source software delivery workspace, being built into an AI software factory.* Wherever a reader first lands, name the audience and the two entry points: **Start New** for a new application, **Evolve** for an existing application or package. Keep both names spelled exactly that way. Name the audience honestly: the team being written for today is a **small team maintaining an existing codebase**; individual builders, developers, consultants and teams are the wider long-term audience, not a claim about who is already served.

Write input → action → output, and lead with the concrete task and its value. Prefer **app**, **code**, **project brief**, **source findings**, **demo script** and **private conversation** over intent, artifact, handoff and proofloop jargon. The three example documents are named **Project brief**, **Code review** and **Demo script** everywhere they appear.

State what is available and what is planned once, in a clear section, instead of hedging every sentence. Label planned capabilities as planned: **hosted** agents that implement, test and repair code, repository publication, on-call response, learned skills and enterprise operation are goals, not features. Do not overcorrect in the other direction either — the local repair CLI and the local Ollama adapter exist and run on an operator's own machine, so never write that model tooling is absent. Distinguish hosted collaboration, self-hosted analysis and operator-run local tools when a capability exists in only one of them, and distinguish production from merged `main` and from an open review candidate. No superlatives, and no invented availability, model results, benchmark scores, customers, founder claims or uptime. Y Combinator is a goal being prepared for, never an affiliation or an admission.

## Brand expression

Use the off-white/Geist/cobalt system with restrained original graphics and readable evidence. The hero's recorded local example must retain its synthetic/historical label; it is not a live agent dashboard. The spatial viewer is opt-in and illustrates example documents, not execution. Working screens prioritize the current project, conversation, recorded task and result. Preserve static alternatives, reduced-motion behavior and contrast; no excessive effects, fictional activity or inflated AI claims.
