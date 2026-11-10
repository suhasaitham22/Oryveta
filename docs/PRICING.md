# Pricing and launch plan

**Status: proposal.** Two plans are published. No plan can be bought today: there is no billing, no metering and no checkout. Billing, hosted agent runs and the Team-only features below are **not implemented**, so the Team price is labelled as proposed everywhere it appears. Every number in [Hypothetical unit economics](#hypothetical-unit-economics) is arithmetic on invented inputs — not a quote, a forecast or an observed bill. Incremental authorized spend for this plan is **$0**.

## Buyer and job

**Buyer (initial hypothesis, unvalidated):** a small engineering team — roughly 2–8 people — that maintains an existing codebase it did not fully write, and whose first qualification cohort is **Python services with a runnable test suite**.

**Job:** "A defect or small maintenance change is known. I want a change I can review, plus evidence that the defect actually failed before the change and that the behavior I care about still passes after it — without handing a stranger's agent broad access to my repository."

This is deliberately narrower than "AI builds your app". A narrow entry point is the format [YC asks applicants to use](https://www.ycombinator.com/howtoapply): a matter-of-fact description beats a sweeping one.

**Not the buyer today:** teams wanting hosted autonomous coding, greenfield app generation from a prompt, on-call automation, or an availability commitment. None of those exist; see [STATUS.md](STATUS.md) and [ROADMAP.md](ROADMAP.md).

## Value hypothesis

The unit we intend to sell is **a reviewable code change plus a reproducible verification record** — not another chat transcript.

Mechanism, as implemented locally today ([setup and limits](IMPLEMENTATION.md#local-verified-repair-cli)):

1. The operator writes the checks, outside the source archive and outside model context.
2. The controller reproduces the defect **before** inference and refuses a baseline where preservation checks already fail.
3. The model may only read/search granted files and apply SHA-guarded replacements to an explicit write allowlist. Those edits are applied by the controller's source tools to a **disposable copy on the host**; the original archive is untouched. Editing is not what runs in a container.
4. **Check execution** — and only check execution — runs in a fresh network-disabled container with a non-root UID, dropped capabilities, read-only root/source and bounded tmpfs/memory/CPU/PIDs/output.
5. The controller, not the model, re-runs both suites afterward and compares exit status and parsed JSON. The result is `needs_review`: declared contracts passed, which is not permission to publish.
6. A reviewer can re-run step 5 independently of the producing run: with `--candidate-zip`, the candidate archive is re-checked against the operator's reviewed configuration, with no model or inference endpoint contacted, nothing added or removed from the file inventory, no edit outside the write allowlist, the baseline reproduced, and all declared final cases re-run in fresh local containers. The receipt records `mode='verification'` with zero model calls and zero observed tokens. It is not resume, approval, remote attestation or hosted verification, and it does not accept any supplied "passed" claim.

The hypothesis to be tested with design partners is that **reviewer minutes per accepted change fall** when the fail→pass transition and the preservation set are shown mechanically rather than asserted. This is unmeasured outside the project, and the opposite outcome — review effort moving rather than shrinking — is entirely possible. Gate G3 exists to detect that.

**Evidence that exists:** one synthetic local repair — run `f635c7c92c6b4e5fbea11a0d35d20def`, recorded 2026-11-04 in [STATUS.md](STATUS.md) and published as a single downloadable example asset (`repair-example.json` with its `repair-example.patch`, resolved through `import.meta.env.BASE_URL`). It is one dated local integration example, labelled `needs_review`, with `limitations` in the file itself. It is not current activity, a benchmark, a success rate or a customer run, and a later run never overwrites it as if it were a new result. The same review candidate adds durable interruption receipts to that loop, which improves the accuracy of an interrupted run's record — it is not automatic resume and not additional outcome evidence.

**What the re-verification path is, evidentially:** implemented source in the open review candidate. Step 6 above describes behavior that exists in the CLI; this repository records no run of it as outcome evidence, and the design-partner gates G1–G5 are unaffected by adding it. A capability is not a result.

## The two plans

Two plans only. No speculative enterprise tier, no annual toggle, no "most popular" badge, no unlimited-inference claim.

### Community — $0 software, hosted workspace free during preview

- **The software is $0 and open source.** Apache-2.0 rights already granted cannot be revoked by any later commercial decision; self-hosting never requires a subscription or a commercial AI API ([OPEN-SOURCE.md](OPEN-SOURCE.md)).
- **The hosted workspace is free during preview, subject to documented capacity.** It runs on shared free-tier allowances where quotas and pausing apply; that is a capacity boundary, not an availability commitment, and preview access is not a perpetual free-hosting commitment. The hosted site is a preview candidate, not a commercial service: offering it commercially — paid or free — requires the hosting entitlement in precondition 5 first.
- **This pricing change paywalls nothing that exists.** Projects, roles, invitations, private conversations, briefs and demo exports stay available to existing preview workspaces on the same terms as before.
- **Changing hosted terms later has conditions.** Any change to hosted capacity, retention or price requires advance notice, explicit consent before it binds an existing workspace, and a working data-export path available beforehand. No hosted-terms change can retract source rights under the license.
- **Compute is yours.** The operator supplies the machine, the model weights and the container runtime. There is no hosted inference and no included compute in any plan.

Covered today: the hosted workspace (sign-in, saved briefs, projects with explicit roles and invitations, separately shared private conversations, Demo Studio storyboard export); the self-hosted engine (template starters, authorized ZIP / public-snapshot import, read-only file-linked candidate findings); and the local tools (the verified repair CLI and the local Ollama model gateway).

### Team — proposed, $49 USD per workspace per month, up to 5 builders

**Not available. Not billable. Nothing here is live.** Published as the intended commercial shape so the price is reviewable before it is charged.

Proposed contents, each of which must be built first:

- Workspace-wide agent-run history (runs, receipts, patches, check outcomes), beyond the project-scoped bounded history in the controlled-repair source candidate. Existing project history is not paywalled.
- A review workflow over candidate patches: assignment, accept/reject with reason, and the exact verified source revision.
- Budget administration: per-workspace limits, visible usage, and owner-set stop-rules.

Still **bring-your-own-compute**: $49 would cover the control plane, not inference or sandbox capacity.

Call to action on the public page: **try a free workspace** (both plan cards link to `/workspace`). Not "subscribe", not a waitlist confirmation, not a contact-form success state — none of those backends exist, and no checkout appears anywhere in the UI.

Public surface: a dedicated `/pricing` page renders both plan cards from one shared source (`apps/web/studio/src/lib/plans.js`), so the published price cannot drift between surfaces. It links to the Home `#local-example` section for the example-asset downloads and does not repeat that run's metrics. Presentation details are in [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md). PR #48 merged this source; production deployment remains a separate claim recorded in [STATUS.md](STATUS.md).

### Availability matrix

| Capability | Community — $0 software, hosted preview | Team $49 (proposed, not live) |
| --- | --- | --- |
| Projects, roles, invitations, private chats, briefs | Available in preview | Same, unchanged |
| Demo Studio storyboard export | Available in preview | Same, unchanged |
| Self-hosted import + read-only analysis | Available, self-hosted | Same, unchanged |
| Local verified repair CLI (own compute) | Available, Apache-2.0 | Same, unchanged |
| Hosted capacity | Shared free-tier allowances; quotas and pausing apply; no availability commitment | Would require compliant commercial hosting first |
| Hosted inference / included compute | None | None |
| Project-scoped controlled repair history/downloads | Implemented in this source candidate; requires migration and an operator worker | Same; not paywalled |
| Workspace-wide history, review assignment/decisions, budget admin | Not built | Not built — the reason the plan is not sellable |
| Billing, metering, quota enforcement | None | None |

## What must be true before commercial use or charging

These are preconditions, not features of a plan.

1. **Nothing existing is paywalled by this change, and changes are announced.** Current preview capabilities stay available to existing workspaces. Any later change to hosted terms requires advance notice, explicit consent before it binds an existing workspace, and a working export path — and cannot retract Apache-2.0 source rights.
2. **Metering before charging.** A per-workspace usage record — runs, container minutes, tokens observed, evidence bytes retained — must be visible to the workspace owner, and reconcilable from persisted worker events, before any invoice is possible.
3. **Consent per run.** Repository access is granted per run against a named source revision. Evidence retention (source, prompts, model output, private expected values) is opt-in with a working deletion path, because receipts contain customer source.
4. **Hard limits, not silent overage.** Limits stop a run; they never escalate budgets, widen permissions or fall back to a paid provider automatically. This preserves the existing no-paid-fallback contract in [ROADMAP.md](ROADMAP.md) and [MODEL-GATEWAY.md](MODEL-GATEWAY.md).
5. **Compliant hosting entitlement, required before commercial use — not merely before the first payment.** Vercel Hobby is non-commercial personal use only ([ROADMAP.md](ROADMAP.md#free-architecture-and-scaling)). A free pilot is not automatically non-commercial, so a commercial launch of any kind requires an approved commercial plan or a compliant alternative host **before** launch, not after the first invoice. Entitlement for any such plan is **unverified and not in evidence** here, and no account or plan has been changed by this work: what is delivered is a source and preview candidate, not a commercial production rollout.
6. **A real refund/cancellation and tax posture**, plus a reviewed data-processing description. Not drafted.

## Controlled design-partner release decision

**Source candidate, not an opened commercial or always-on service.** The selected scope is operator-approved public repositories, dedicated worker identities and explicitly submitted goals. No arbitrary self-service code execution, private repository grant, automatic PR/deploy, billing or incremental spend is enabled.

| Gate | Required before onboarding a partner | Current boundary |
| --- | --- | --- |
| Executable evidence | Browser-to-queue-to-worker checks, cancellation, lost-parent recovery, authorization and patch download | Use the dated results in [STATUS.md](STATUS.md); synthetic local checks are not partner outcomes |
| Production control plane | Reviewed forward migration, deployment, actual provider/RLS checks and rollback procedure | Not performed by this source change |
| Worker host | Approved account/host, private persistent state, local Docker/Ollama, supervisor, cold-start/cancellation/reboot checks and measured capacity on that machine | No cloud worker provisioned; a local macOS/VM result is not proof on a free cloud VM |
| Hosting entitlement | A plan/host that permits the intended commercial use, even if the pilot is free | Vercel Hobby is personal/non-commercial; current commercial entitlement remains unverified |
| Partner consent and support | Named consenting repository owner, frozen revision/configuration, shared-goal/patch audience, evidence retention/deletion agreement and a named incident contact | Requires founder/operator agreement with each partner; no customer consent is inferred |
| Identity and recovery | Use an actually verified sign-in path; demonstrate worker re-provisioning with current credentials and a private evidence backup/restore | Production GitHub login has dated evidence; local Mailpit is not external email delivery, and no cloud restore or uptime guarantee is established |

Free-tier capacity, pausing and reclamation remain operational limits, not bugs to bypass with artificial traffic. Follow [OPERATIONS.md](OPERATIONS.md) for the conditional host choice and recovery boundaries. If a gate fails, keep execution closed rather than quietly enabling a paid fallback or presenting a queued goal as running. Founder account creation, payment-card/plan decisions, partner consent and final launch authorization cannot be supplied by code or a local test.

## Hypothetical unit economics

**All inputs below are invented for arithmetic.** They are not vendor quotes, not observed costs and not a revenue forecast. Nothing here authorizes spend: current authorized incremental spend is $0, and the fixed-cost table is a **budget proposal requiring explicit approval** before any plan is purchased or any card is attached.

### Proposed fixed monthly platform cost (hypothetical, unapproved)

| Line | Hypothetical monthly |
| --- | --- |
| Compliant commercial static hosting | $20 |
| Managed Postgres on a paid tier (leaving the free allowance) | $25 |
| Always-on control-plane/worker host | $60 |
| Backup + evidence object storage and egress | $10 |
| Domain, amortized | $5 |
| **Proposed infrastructure total, `F`** | **$120** |

### Variable cost per paying workspace (hypothetical)

| Component | Hypothetical monthly |
| --- | --- |
| Infrastructure: run-history rows, 200 MB retained evidence, logs, patch/receipt download egress | $6.000 |
| Support allowance | $5.000 |
| Payment processing, assumed 2.9% of $49 plus $0.30 | $1.721 |
| **Total variable, `v`** | **$12.721** |

Inference and sandbox CPU are absent because the customer supplies them.

### Contribution before fixed and omitted costs

- Price `P = $49` per workspace per month, up to 5 builders → **$9.80 per builder per month** at full occupancy.
- Contribution per workspace `P − v = $36.279`, i.e. **74.0% of price**. This is contribution **before** the fixed costs above and before the omitted costs below. It is not gross margin and it is not profit.
- Infrastructure-only break-even against the proposed `F`: `ceil(120 / 36.279) = 4` paying workspaces. That covers the proposed infrastructure lines only — it is **not** company break-even.
- Sensitivity: if infrastructure were $15 instead of $6, `v = $21.721`, contribution falls to `$27.279` (55.7%), and infrastructure-only break-even rises to `ceil(120 / 27.279) = 5` workspaces.

**Explicitly excluded from every figure above:** founder salaries and founder time, customer acquisition cost, taxes, refunds and chargebacks, and the cost of subsidizing the free hosted preview. Including them changes the picture materially. **No company break-even, profitability or runway claim is made here.**

### Why no hosted compute is bundled

- Hypothetical cost per attempted repair: 200,000 tokens at a blended $2.00 per million = `$0.400`, plus 8 container-minutes at $0.004/min = `$0.032`, totalling **`$0.432`**. The 200,000-token figure is an invented placeholder; it is not derived from the one recorded local run.
- At 3 attempts per accepted change: `3 × $0.432 = $1.296` per accepted change.
- Against a 70%-of-price contribution threshold, the available variable budget is `0.30 × 49 = $14.70`. Variable cost already consumes `$12.721`, leaving **`$1.979`** — roughly one and a half accepted changes.

The published plan therefore includes **no hosted compute allowance, and implies none**. Hosted runs remain bring-your-own-compute. Any future allowance requires measured cost per accepted change on consented repositories (gate G5) and its own approval; it is not a consequence of this arithmetic.

## Next delivery allocation

Effort for the next increment, summing to 100%. This is where engineering time goes, not money.

| Share | Area | Concretely |
| --- | --- | --- |
| **40%** | Product reliability | Move the local repair loop toward Stage 3's remaining gates: durable integration, safe restart after interruption, a real decision protocol beyond `no_progress`, and target-repository qualification for the Python cohort. |
| **25%** | Design-partner discovery | Recruit a small number of consenting teams with real Python repositories; run their defects through the operator contract; record refusals and the reasons. |
| **20%** | Repeatable demo and onboarding | One reproducible path from "fresh machine" to "patch plus verification record", including the published example asset and the operator JSON specification, so a reviewer can reproduce rather than watch. |
| **15%** | Cost and security measurement | Measure tokens, container minutes and wall time per accepted change; re-examine sandbox assumptions against untrusted customer source; document what local defense in depth does not cover. |

## Evidence gates

Observable gates with defined measurements. **No gate below has a recorded result in this repository.** The only recorded execution evidence is one synthetic local repair ([STATUS.md](STATUS.md)). No target is claimed as achieved.

| Gate | What is observed | How it is recorded | Current state |
| --- | --- | --- | --- |
| **G1 — Real consented repairs** | Repairs on repositories owned by consenting teams where the development suite fails before the change, and acceptance plus at least one preservation check passes after it, with checks authored outside model context | Private receipts: `baseline.json`, `verification.json`, `verified.patch`, run/model/implementation digests | Not evidenced in this repository; one synthetic local example exists |
| **G2 — Repeat usage** | A team runs further repairs without a maintainer initiating them, inside a stated window | Run records per workspace, with who started each run | Not evidenced in this repository; not yet measurable |
| **G3 — Review time** | Reviewer minutes from candidate delivered to accept/reject, and the accept rate, against that team's existing review path | Timestamps on delivery and decision, plus the reviewer's stated baseline | Not evidenced in this repository; not yet measurable |
| **G4 — Willingness to pay** | A named team states, in writing, a price and seat count it would pay for the Team contents — and later, once billing exists, commits | Written statement; no payment is collected before metering, limits and consent exist | Not evidenced in this repository |
| **G5 — Cost per accepted change** | Tokens, container minutes and attempts per accepted change on real repositories | Receipt usage fields aggregated per accepted patch | Not evidenced in this repository; one synthetic data point exists |

Failure is a valid outcome of each gate. A refused or abandoned design partner is evidence; so is a repair loop that cannot qualify real repositories.

## YC application positioning

Format follows [How to Apply](https://www.ycombinator.com/howtoapply): clear and concise, matter-of-fact, a narrow entry point, a specific insight, honest obstacles, and a demo. **Applying is a goal, nothing more.** Nothing in this repository asserts an affiliation, an application, a batch, an interview or an admission, and no such outcome may ever be written here or shown in the product.

**What it makes (one sentence, deliberately narrow):** a local coding agent for existing Python services that produces review-ready patches only after controller-owned checks reproduce the defect and verify the behavior the team wants preserved.

**The insight, stated as a hypothesis:** the expensive part of agent-written code is trusting it, not generating it. In this loop the checks, the expected values and the final verifying run belong to the controller rather than the model; the model's file access is an explicit allowlist; and the output is `needs_review` rather than a merge. The hypothesis is that **this boundary, more than model capability, is what decides review cost** — and that is exactly what G3 tests. It is not a measured result, and no comparison to other tools' internal behavior is claimed here.

**Why start this narrow:** one language cohort with runnable tests, one defect at a time, on the operator's own machine and weights, so there is no per-token bill and no hosted multi-tenant execution risk while the loop is still being proven.

**Honest obstacles, stated rather than hidden:**

- Only one synthetic repair has been verified end to end; real repositories are not yet qualified.
- A local 8B model on an operator's hardware may not reach useful quality or throughput on real defects. That is a measurement we have not taken, and it may fail.
- Local Docker is defense in depth, not multi-tenant isolation. Hosted execution of untrusted customer source needs a stronger boundary.
- No always-on cloud worker has been provisioned or demonstrated, so no availability claim is possible.
- The source candidate connects approved repair goals to an operator-provisioned worker. Production migration, compliant hosting, dedicated worker enrollment and target-host verification remain deployment gates; the one-shot CLI remains separate.
- Review effort could move rather than shrink. G3 exists to detect that.
- Free hosted preview is a subsidy with no agreed term; capacity, retention and terms are open questions, not settled commitments.

**Demo:** the reproducible local run plus the published single example asset — patch, checks, digests and limitations. A reviewer can re-run the operator contract; they are not asked to trust a video. The rendered pricing film is a **captioned storyboard**, not footage of the application or of an agent run, and the product screenshots are application captures of the review candidate rather than customer usage; those three kinds of material are never presented as one another.

### Proof and missing-evidence checklist

| Claim an application might make | Evidence in this repository | Missing |
| --- | --- | --- |
| A fixed agent loop produces independently verified patches | One synthetic repair with retained failed and successful receipts; 604 Python tests and 87.13% branch-inclusive coverage recorded 2026-11-04 ([STATUS.md](STATUS.md)) | Repairs on consented real repositories (G1) |
| Teams would use it repeatedly | None | G2 |
| It reduces review effort | None | G3 |
| Teams would pay $49 per workspace | None | G4 |
| Unit economics work | Hypothetical arithmetic above only | Measured cost per accepted change (G5) |
| Hosted collaboration works | Production GitHub OAuth, Supabase RLS roles/invitations/private sessions and all 8 collaboration ordering cases; 24 public route/viewport checks in the 2026-11-04 candidate, and 48 from the earlier 2026-10-29 UI verification ([STATUS.md](STATUS.md)) | Controlled repair source integration is separate from a production rollout or an always-on cloud worker |

Each metric above keeps its recorded scope: the 604-test/87.13% gate is the 2026-11-04 Python baseline; the 24 route/viewport checks cover the 2026-11-04 candidate's six routes at four widths; and the 48 route/viewport checks belong to the separate 2026-10-29 UI verification. Each stays attached to its own date and surfaces, and none is restated as covering the others.

**What this repository does not evidence:** consented external repository runs, repeat usage, measured review time, stated willingness to pay, revenue or customers. Absence here is absence of evidence in this repository, not a measured zero.

**Where founder and traction facts belong:** founder experience, biography, prior achievements and any real traction are supplied and verified by the founder in the YC submission itself. They are out of scope for this repository, which holds only what the code and recorded runs support. Nothing of that kind may be fabricated here or invented to fill a gap. Likewise, market sizing, growth rates, customer names, testimonials, logos and benchmark rankings are not published without evidence.

**Website polish is not product-market fit and not an admission signal.** A credible public page only makes real evidence legible; it does not substitute for G1–G5, and no design work implies any YC relationship. **No YC name, logo, batch reference or affiliation appears anywhere in the public UI**, and none is implied by this document.

### Founder completion and submission

**Prepared material is not a submitted application.** Use the product description, insight, obstacles, pricing proposal and dated proof above as draft answers; founder review is required before copying them into the application. Suggested short description: **“Verified code repairs on your own compute.”** Technology: React/Vite, Supabase Auth/PostgreSQL, Python, local Ollama tool-calling models and Docker checks. The initial customer cohort is a hypothesis, not a customer list.

The [official application page](https://www.ycombinator.com/apply), checked 2026-11-08, accepts **late Winter 2027 applications** after the November 2, 8pm PT on-time deadline; it does not promise a response date for late applicants. The batch is January–March in San Francisco. Confirm the current batch and requirements in the application account before submission; this is timing information, not an affiliation or an application-status claim.

Only the founder can supply and confirm these missing facts:

- Every founder's identity, role, relevant achievement, employment/time commitment and history together; who actually wrote the code and any contractors or outside contributions.
- Incorporation, ownership/equity, existing investment, fundraising, location and ability to attend. Unknown funding is **not** entered as zero.
- Actual users, customers, revenue, growth, interviews and any prior applications. Repository absence is not proof that these values are zero.
- A working contact address, an application account, a chosen batch and final consent to submit the representations.

The [founder video](https://www.ycombinator.com/video) is one minute of the founders talking, all founders included, using spontaneous bullet points rather than a recited script. The existing captioned product storyboards do **not** satisfy it. Keep a separate product demo: show the approved source/configuration, submission, independently recorded checks and downloadable candidate; identify synthetic fixtures and the operator's machine explicitly. Do not expose credentials, private expected values, or claim an always-on cloud service from a local recording.

Before submission, verify every answer against the current dated evidence, open each supplied demo/link from a signed-out browser, and let the founder review the complete form and attestations. No account creation, founder video, application entry or submission is performed by this repository change.

## Pricing context (not a comparison claim)

Read 2026-11-04, [devin.ai/pricing](https://devin.ai/pricing): Free $0 with a light quota; Pro $20/month; Max $200/month; Teams $80/month for the team plan plus $40/month per full developer seat, with Enterprise quoted. Those plans **include hosted agent compute quotas**, so the $49 bring-your-own-compute proposal is not like-for-like, and the comparison is not evidence of equivalent quality, capability or cost advantage. It is used only to check that a $49 workspace price is inside the range teams already encounter for agentic coding tools.

## Review

Revisit this document when any gate in G1–G5 produces its first real data point, when hosting compliance is resolved, when hosted preview capacity or terms need to change, or before any billing work starts — whichever comes first. Capability claims belong in [STATUS.md](STATUS.md); this file holds the commercial proposal only.
