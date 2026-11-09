# Oryveta implementation status

## Current capability and release map

**Source snapshot: 2026-11-09.** PR #48 is merged. This checkout adds the controlled durable repair integration on `feat/controlled-repair-runtime`; it is a follow-on source candidate, not a production migration or cloud-worker deployment. A review preview, merged source and production execution remain separate evidence levels.

| Surface | Implemented boundary | Not implied |
| --- | --- | --- |
| Hosted collaboration | Supabase sign-in, saved projects/briefs, roles/invitations and separately shared private conversations; production authorization evidence is recorded below | Hosted coding or a general availability SLA |
| Durable analysis | Deployed work/run/event/lease authority; production analysis exercised with an operator-run one-off worker | A continuously hosted worker |
| Public design and pricing | Evidence-led Home, Pricing, labelled synthetic example downloads and a free-preview entry, verified in the review preview | Billing, customer traction, YC affiliation or a commercial launch |
| Local FastAPI/SQLite engine | Separate identity, deterministic starters and bounded read-only source analysis | A bridge that forwards hosted sessions into local tools |
| Local coding CLI | Model-driven scoped repair, interruption checkpoints and private candidate export; model-free re-verification of an explicitly supplied candidate | Resume/replay, automatic approval, GitHub publication, remote attestation or multi-tenant production isolation |
| Controlled durable repair | Approved public commit/configuration policy, project queue, dedicated operator worker, bounded recorded progress and candidate-patch downloads | Provisioned cloud compute, arbitrary self-service execution, automatic publication, billing or an availability promise |

The goal is verifiable maintenance changes for small teams first, then the broader Start New/Evolve factory. Community software is $0; hosted preview capacity and proposed Team pricing remain governed by [PRICING.md](PRICING.md). Consented real-repository outcomes, repeat use, review effort and willingness to pay—not additional website polish—are the next qualification evidence.

## State-machine audit and browser lifecycle fixes — source verification, 2026-11-09

The [39-family lifecycle inventory](STATE-MACHINES.md) separates already-explicit business states from implicit request ordering, draft ownership, observation, evidence and process coordination. The decision is to reuse the existing authorities and local guards, not add a global state machine, dependency, queue or wire-status migration.

- The controlled-repair panel no longer says no policy is enrolled after its policy read fails. Real local Auth/PostgREST and Chromium reproduced the conflicting error/enrollment guidance at 1440px and 390px before the fix; afterward only the read error remains, queueing stays disabled, and a successful empty refresh restores enrollment guidance. The browser smoke aborts the failed request without inventing a response.
- Legacy navigation now commits list/detail state, rendering and feedback only for its current request generation. A real temporary FastAPI/cookie-login/browser scenario reproduced late Projects/detail/error responses replacing newer routes and drafts before the fix. The corrected source passed all 13 checks, including preserved newer drafts, ordinary create/navigation and reporting an error belonging to the current request. The permanent static-server regression uses explicit deterministic API fixtures; it is separate from that real-API smoke.
- Workspace initial and post-mutation reads now share one generation, including errors. Abandoned save/create acknowledgements cannot overwrite the newer selection; successful mutations consume only the submitted settings draft. Real-response browser cases failed before correction: an acknowledged creation disappeared, a stale failure replaced successful-save feedback, an abandoned creation replaced a newer form, and the next new-workspace form retained the already-created name. All four workspace cases then passed against the compiled application.
- Integrated gates passed: hosted/self-hosted builds and nine storyboard checks; all five transactional SQL suites; real new-tab email/PKCE and project/private-session authorization; all **12** collaboration-ordering cases; the repair policy failure/recovery case; and browser-closed execution by the real public-repository analysis worker with exact result download and cancellation of a subsequent run.
- Compiled hosted and self-hosted browser flows passed at desktop/tablet/mobile sizes, including navigation, drafts, downloads, local cookie/ZIP/job lifecycle and reduced motion. The legacy smoke also passed its navigation regression. Ruff passed. The existing optional Three.js chunk-size and Starlette/httpx deprecation advisories remain visible.
- Python verification initially passed **733 cases** with **45 container-gated cases skipped**, leaving coverage below the unchanged 84% floor. Those cases were then exercised using the existing local Colima context and pinned image. An initial bind-mount setup failure was corrected by placing task data under the VM's already-approved mount, without changing application code or mount policy. All previously skipped cases subsequently passed; combined branch-inclusive coverage is **86.59%**. This is full-suite plus targeted-container evidence, not a single uninterrupted 778-case run or live-model quality result.

These are local source changes layered on the controlled-repair candidate, not a production deployment or hosted-worker rollout. PostgreSQL/SQLite state transitions, identity/RLS, policy/lease fencing, model budgets and human-review/publication semantics are unchanged.

## Controlled durable repair — verification, 2026-11-09

The project panel and `coding_worker` connect explicitly submitted goals to the existing Supabase work/run/lease authority. The worker uses an ordinary dedicated Auth identity; its credential-free child runs the fixed local model/tool/verifier loop. Policies freeze the public source commit and operator configuration; retries recompute rather than resume a model trajectory. Full private evidence stays on the operator host; the bounded shared result remains `needs_review`.

Exercised implementation checks:

- The forward migration upgraded the original repair shape and applied twice successfully. All five transactional SQL suites passed, including controlled repair, existing factory runtime, project/workspace authorization and retained attribution.
- Ten existing analysis concurrency cases and the controlled-repair two-session suite passed. Repair admission serializes with policy/worker revocation in both commit orders; revoked authority cannot leave newly admitted unclaimable work.
- Real local Auth account deletion with a human-created, never-claimed goal retained the frozen worker identity, cleared the live reference, settled the goal and denied further admission. Both enabled and already-revoked policies passed, including the mobile UI's deleted-identity display. A reproduced long-hash overflow was fixed by wrapping record metadata, not hiding content.
- Git-applicable patch round trips passed for LF, missing final LF, quoted Unicode filenames, U+2028, form feed, bare CR and CRLF. The U+2028 case failed before the LF-only serialization fix.
- The 2026-11-08 full Python gate passed **778 tests at 86.67% branch-inclusive coverage**. After recovering the temporary workspace and narrowing Docker-context propagation, **144 worker/tool regressions** and Ruff passed on the recovered source. Other contexts, arbitrary metadata, TLS keys and registry credentials no longer reach the child.
- Hosted-style and self-hosted Chromium flows passed on desktop/tablet/mobile, including real local API lifecycle and reduced motion. Bandit, dependency consistency and a built-wheel worker CLI launch also passed before workspace recovery. The existing Starlette/httpx deprecation and optional Three.js chunk-size advisory remain visible.

The source/verification work does not apply production migrations, provision a cloud VM, enroll customer repositories, change hosting plans or spend money. The [controlled design-partner gates and YC founder checklist](PRICING.md) explicitly retain those external prerequisites. Free-tier quota, pausing/reclamation, target-host throughput and recovery are not established by a local test.

## Candidate re-verification and documentation alignment — 2026-11-04

The local CLI now exports a changed candidate as private `candidate.zip` and accepts `--candidate-zip` for a new model-free verification run. It compares normalized inventories and file bytes against the original source and write allowlist before candidate execution, reproduces the defect and checks preservation on the baseline, then runs every declared final case in fresh bounded containers. It does not trust an old success claim or modify the source archive. [Commands, limits and receipt semantics](IMPLEMENTATION.md#candidate-export-and-model-free-re-verification).

Exercised evidence:

- `smoke_reverify.py` passed seven behavioral cases with a deliberately nonexistent model configuration, **zero model calls and zero inference tokens**, and rejected an out-of-scope edit before execution (`candidate_scope`).
- Real Qwen3 8B repair run `369041c04db04083ac1b13a12f8913c2` exported a candidate. Fresh verification run `cc564a7c99e54b1eb81f68ef49127842` passed the same seven cases with zero model calls/tokens. Candidate archive/tree, configuration and check-suite digests matched across runs. Implementation digest: `9e0da006aecffd8242d4aa98f35807720d23e6e57b6adb42b795aa4dd90bc19a`.
- **630 Python tests passed**, **87.47% branch-inclusive coverage**, Ruff, Bandit, compilation and dependency consistency passed. Subprocess regressions now explicitly use the current checkout rather than an unrelated editable installation; the single-folder archive fixture preserves its intended layout before testing export/re-import.
- Hosted and self-hosted builds, real Chromium navigation/download/history flows, local cookie/ZIP/cancellation flows and reduced-motion checks passed. The broken self-hosted Font license link was reproduced and repaired with an explicit static route, not a wider filesystem exposure.
- All 38 Markdown documents were reviewed for current design, goals, storage/identity boundaries and pricing/release claims. Local links/anchors were checked; historical evidence, legal notices and original ADR decisions remain dated and intact. Advisor results must reflect actual observations, not assumed cleanliness.
- Nine storyboard contracts and the Remotion TypeScript gate passed. The [12-second re-verification storyboard](media/candidate-reverification-storyboard.mp4) was rendered and its three scenes inspected. It is a captioned workflow explanation, not a recorded agent session or customer result.

These are additional implementation checks on the same synthetic task family, not new real-repository qualification or benchmark results. No paid service, billing path, hosted coding worker or production rollout was enabled. The existing Starlette/httpx deprecation and optional Three.js size advisory remain visible.

## Evidence-led public UI and pricing — source verification, 2026-11-04

The public experience now focuses on small teams reviewing maintenance changes: an evidence-led Home, a dedicated `/pricing` route, updated About/What We Do, consistent navigation and a downloadable **synthetic local repair example**. Community is $0 software with a capacity-limited free hosted preview. Team is a **proposed $49 USD/workspace/month for up to five builders**; paid features, billing and hosted compute are not enabled. [Pricing, hypothetical economics, effort allocation and YC evidence gates](PRICING.md) distinguish the product plan from observed customer results.

The example JSON and patch were extracted from the recorded local run below, without private host paths or raw prompts. Their patch digest matches the original. They are historical build assets, not a live agent feed or customer/benchmark result. The self-hosted API exposes only those two additional static filenames; other dotted routes remain blocked.

Local verification:

- **604 Python tests passed**, **87.13% branch-inclusive coverage**, Ruff and Bandit passed. The checkpoint commit from PR #47 is included: that PR was merged into the feature branch after PR #46's main snapshot, so its already-reviewed change was carried forward rather than silently lost.
- Hosted and self-hosted production builds passed. Real Chromium exercised Pricing reloads, breadcrumbs, cross-page evidence-anchor focus/scroll, free-workspace entry, JSON/patch downloads with matching hashes, existing draft/history/export behavior and the optional spatial viewer.
- The actual self-hosted API also passed local cookie login, ZIP intake, analysis cancellation and reduced-motion lifecycle checks at desktop/tablet/mobile sizes.
- **24 public route/viewport combinations** (six routes at 1440, 768, 390 and 320px) had no document overflow or violations in the selected axe-core WCAG A/AA rules. A 320px pricing-grid overflow was fixed at the grid minimum, not hidden with clipping. This is not full accessibility certification or physical-device coverage.
- A blocked example request showed an explicit unavailable state without a verification verdict or fabricated record.
- All **eight** storyboard contracts and Remotion TypeScript checks passed. The three-scene `proof-and-pricing` composition rendered as a 12-second, 1920×1080 H.264 storyboard and its scenes were inspected. The title's containing block was corrected after visual review. This is a captioned storyboard, not recorded application execution or a YC founder video.

Screenshots: [Home desktop](media/yc-home-desktop.png), [Home mobile](media/yc-home-mobile.png), [Pricing desktop](media/yc-pricing-desktop.png), [Pricing mobile](media/yc-pricing-mobile.png). [Rendered pricing storyboard](media/yc-pricing-storyboard.mp4).

This is a review/preview candidate, not a commercial production launch. No payment method, paid service or YC affiliation was added. Commercial hosting entitlement, actual customer validation, founder-verified application facts and the remaining hosted execution gates are still prerequisites. The existing optional Three.js chunk-size advisory and Starlette/httpx deprecation warning remain visible; no Lighthouse or field-performance claim is made.

## Durable local repair checkpoints — verification, 2026-11-04

The local coding CLI now persists progress before model/tool admission and independent verification, and after completed results. Receipts retain the phase, attempted work, observed usage, pending token reservation and source identities when the controller is interrupted. Each completed edit is checkpointed as an unverified patch with its digest. Checkpoint storage failure stops new work, and failure to commit the terminal receipt demotes the verified artifact.

A real child-process SIGKILL test reproduced the previous defect: a controller already inside its first model call left a receipt claiming zero turns. The repaired test and all eight SIGKILL/SIGTERM boundary cases passed, covering initial inference, inference after an edit, a development-check tool and final verification. They use deterministic paused proposals/check boundaries with real-container baselines; they are not live-model quality tests. Storage-failure and complete-edit-reversion regressions also passed.

Local verification: **604 Python tests passed**, **87.17% branch-inclusive coverage** against the unchanged 84% gate, Ruff, Bandit, compilation and dependency consistency passed. One existing Starlette/httpx deprecation warning remains. A separate real Qwen3 8B/Docker repair passed all seven behavioral checks, with six model turns, five tool calls and 6,852 observed tokens. Its receipt finished with zero unsettled reservation and matching candidate/verified patch hashes.

Live evidence: run `f635c7c92c6b4e5fbea11a0d35d20def`, implementation digest `bb510466f1a2f484f0a82ecb83be4a4439e132b19a4406d88fee0183aaf2c09f`. This improves interruption accounting and diagnosis, not automatic resume/replay, abandoned-container cleanup, host-power-loss recovery, durable hosted coding or 24/7 service. The trace is ordered JSONL, not a hash chain; the previous documentation overstated that property. [Receipt semantics and limitations](IMPLEMENTATION.md#evidence-and-limitations).

## Fixed local repair loop — execution verification, 2026-11-02

The separate `python -m oryveta_engine.coding_runtime` CLI now performs model-driven edits of an operator-selected ZIP in a disposable workspace, with a versioned configuration, exact file grants, pinned local model/image identities, bounded tools/execution and independent controller-owned JSON checks. It emits a review candidate, not a commit, PR or deployment. [Setup and limitations](IMPLEMENTATION.md#local-verified-repair-cli).

Real local Qwen3 8B and Linux/arm64 Docker execution repaired the numeric-version ordering defect in `scripts/smoke_coding.py`. The model edited only `versions.py`; the input archive was unchanged. All **seven** development/acceptance cases passed, covering numeric component ordering, prefixes, stable equivalent versions, original spelling, empty input and invalid-input behavior. Acceptance inputs/expected values were kept out of model context. The successful run used **six model turns, five tool calls and 6,852 observed tokens**.

The first live attempt failed after 20 turns because the model repeatedly omitted the edit's required `path`. That failed receipt was retained. After generic schema diagnostics were made actionable, the model corrected its own argument on the next turn and completed the repair. No task-specific patch or implicit path was supplied by the controller. Two identical tool/check failures on the same source revision now terminate the run with `no_progress`; an intervening edit permits another attempt.

Evidence identity: final run `e4c2623e212e4276965c08728879b2e3`, model digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, implementation digest `7be316eb7193b7fdf9ab3ac4afd9608f1c4ed19cc846d352b0e42767f7c8dbb7`, patch digest `232f8b30bf9744f3f12931482aec1a083d12b613e02827e88e15b9c90f694744`. Full private local receipts retain configuration, baseline/final results, model/tool events and runner provenance.

Final local gate: **593 Python tests passed, 87.07% branch-inclusive coverage** against the unchanged 84% floor; Ruff passed. Compilation and dependency consistency also passed. Overflow/cancellation/timeout tests exercise actual subprocess and container cleanup. The output-overflow pipe leak found during validation was fixed and its EOF regression passed; only the existing Starlette/httpx deprecation warning remained. Real-model inference is a separate smoke, not a mocked test result.

Linux preflight exposed quota rounding above the configured CPU ceiling. The runner now uses an explicit downward-quantized quota; the original strict kernel-bound assertion remains intact. The container uses a dedicated scratch mount rather than system `/tmp`; targeted real-container CPU/tempfile/credential checks and the unchanged Bandit gate passed locally after these changes.

This proves one synthetic repair integration—not a benchmark success rate, real-repository qualification, hosted coding, production sandbox assurance or 24/7 operation. The web/API analysis flows remain unchanged. No paid provider, hosted inference key, automatic publication or learned/self-modifying policy was enabled.

## Orbital studio UI — browser verification, 2026-10-29

The web interface has been redesigned across Home, About, What We Do, sign-in, workspace navigation, project and conversation views, Start New/Evolve briefs, Demo Studio and local execution. It uses self-hosted Geist typography, a shared off-white/cobalt palette, dark product navigation, original SVG artwork and an explicitly opened 3D artifact viewer. Product capabilities and authorization boundaries are unchanged.

- Hosted and self-hosted production builds pass. **302 Python tests**, Ruff and all seven storyboard/security-scan contracts passed.
- Real Chromium flows passed at desktop/tablet/mobile widths: routing and browser history, drafts and exports, local cookie login, ZIP intake, cancellation, and reduced-motion behavior. A real one-off worker also completed the synthetic source analysis shown in the refreshed UI evidence.
- The spatial regression exercises actual canvas rendering, a visible chapter change while paused, a stable paused frame, live reduced-motion teardown, semantic content and close-focus restoration.
- Real isolated Supabase email/new-tab PKCE, project roles/invitations, private-session isolation and revocation passed. All **eight** collaboration response-order cases passed; no auth or database rules were loosened.
- **48** public/guest route/viewport combinations at 1440, 768, 390 and 320px had no horizontal overflow or violations in the selected axe-core WCAG A/AA rules. This is not a full accessibility certification or a physical-device test.
- Initial Home JavaScript is **438,846 decoded bytes**, down from **1,058,449** on the previous deployed page (**58.5% less**). Three.js is absent from initial requests, Motion is removed, product CSS is deferred, and the public loading-placeholder/footer shift is removed. Controlled local desktop/mobile runs recorded Home CLS `0`; deployed lab timing evidence is recorded with the UI PR, not treated as field performance.

The design references, original-asset/Geist licensing, screenshots and motion recording are documented in [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md). This work does not deploy a continuous worker, enable model-driven coding or change provider plans.

## Unattended worker service — source verification, 2026-10-29

The analysis worker now has a container-oriented `factory_service` entry point. It initializes a private credential from a secret only when no persisted file exists, preserves rotated sessions across restart, excludes another service using that private directory, drops root after mounted-volume initialization, and handles SIGTERM through the existing worker teardown. Invalid persisted state is refused rather than replaced by a stale bootstrap.

Local verification: **320 Python tests passed**, with **85.27% branch-inclusive coverage** against the 84% gate; Ruff and Python compilation passed. An actual CLI smoke exercised private first-start storage, restart with a rotated credential and corrupt-state refusal without network or real credentials. A reproduced `0600` FIFO startup hang is now rejected as a non-regular credential file. The CI gates additionally exercise real Supabase/GitHub analysis through first-start/restart, continuous-service SIGTERM, and credential preservation/privilege drop across replacement Docker containers.

This is a deployable source change, **not a hosted rollout**. Railway authorization, actual free-plan entitlement/capacity checks, persistent worker operation and model/isolation compute remain outstanding. No payment method, paid plan or paid inference fallback has been enabled.

## Production runtime rollout — 2026-10-25 UTC

The Vercel production deployment for merged commit `1c3e731c2d4b3ffd434dcfd5719fb57b679b658c` succeeded. The reviewed `durable_factory_runtime.sql` and `retained_attribution_and_lease_clock.sql` migrations are now applied to Oryveta project `nydtmiseclkwauiepqxn`; existing prerequisite migrations were not replayed.

- All four public runtime tables and the private lease table have RLS enabled. Anonymous reads and direct authenticated writes are denied; authenticated callers cannot read private leases. All 15 exposed security-definer RPCs have fixed empty search paths and deny anonymous execution.
- `production_auth_smoke.py --runtime` passed against the deployed site and API: browser-submitted public-repository analysis survived browser closure, a separately authenticated **one-off local worker** completed it, and the downloaded JSON matched the stored result. The worker rotated its ordinary session and received no administrative key.
- Production cancellation rejected a late heartbeat/completion; worker revocation removed access. Deleting the cancelling/invited account preserved terminal metadata, and a new account at the same email address inherited no project or chat access.
- Five controlled test identities and their application rows were removed. An independent catalog/data query found no release-test accounts, workspaces, projects, chats, registrations, work items, runs, events or leases remaining. Provider audit logs may remain.
- Security advisors still report the intentional authenticated-only `SECURITY DEFINER` RPC pattern and disabled leaked-password protection. The RPCs require their reviewed actor/role/lease checks; switching them to invoker mode would break the no-direct-write contract. Supabase leaked-password protection requires Pro or above, so no paid plan was enabled. The advisor output is not claimed to be clean.

**Still pending:** an authorized always-on worker host and measured free-tier capacity. This rollout proves the production control plane and one-off execution path, not 24/7 availability, model-driven coding, host recovery or enterprise readiness.

## Auth and collaboration changes

PR #31 is deployed to Vercel production. Its atomic project/collaboration migration is applied to Supabase, with RLS enabled and direct client mutation grants denied on all four new tables. Production GitHub sign-in and deployed multi-user project/private-session authorization have been exercised. This release does not add a hosted coding factory.

The React Studio builds a hosted `dist` and a self-hosted `dist-local`. FastAPI serves the latter at `/studio/`; the legacy `/` remains a separate self-hosted surface. Hosted Supabase identity and local FastAPI engine sessions are deliberately separate. No hosted engine bridge exists.

**Identity:** Supabase email links use PKCE with shared browser storage; identity is verified with `getUser()`. GitHub provider discovery is dynamic. The production site URL and exact redirects are configured, and GitHub OAuth is enabled using an identity-only OAuth App. A real GitHub consent/callback reached the production origin and `/auth/v1/user` returned 200. Existing email identities are not silently merged with a new GitHub identity.

**Projects:** PostgreSQL RLS and narrow RPCs enforce owner/admin/engineer/reviewer/viewer roles. Pending email or immutable-user-bound alias invitations confer no project access. Acceptance is atomic; replay cannot recreate a revoked grant. Reassigned aliases cannot silently upgrade an invitation for the former owner. Workspace membership and project membership are distinct.

**Private sessions:** Existing `chats`/`chat_shares` remain owner-private until explicitly shared and accepted. A project association grants no conversation access; a conversation guest does not gain project access. The browser cannot rewrite the association. Automatic external invitation emails are not implemented.

## Exercised verification

- Actual Supabase CLI 2.121.0 native PostgreSQL 17, Auth/GoTrue, PostgREST and Mailpit; no mocked auth responses.
- Transactional workspace and project RLS suites, including anonymous/unauthorized access, roles, owner protection, project/session boundaries, revoke/replay and the failing-before/passing-after alias-reassignment regression.
- Production-built React Studio in headless Chromium: actual email link opened in a new tab, original-tab session restoration, three users, project create/invite/accept, read-only mutation denial, session-only sharing, project/admin-self revocation, sign-out and desktop/mobile-width rendering. The new-tab PKCE regression failed before the storage fix and passed afterward.
- Python suite: 151 tests passed. Ruff and the seven storyboard/security-scan contracts passed.
- Vercel-target build succeeds for the canonical configuration; a privileged browser key and a Supabase origin absent from the deployed CSP are rejected before building.
- Exact-head GitHub preflight and PR checks passed, including Python 3.11–3.13, security/Docker, React browser QA and the real local Supabase integration.
- Production browser OAuth: identity-only GitHub consent, production callback, verified user and a Projects page without schema errors.
- `scripts/production_auth_smoke.py`: three controlled production identities authenticated through the real Auth password grant; ordinary user sessions exercised the deployed create/invite/accept/read-only/session-sharing/revocation paths and mobile rendering. The admin key only provisioned/removed test identities, never entered a browser. All three test identities and their cascading application rows were removed; cleanup was independently checked.

Local Mailpit coverage is not external email delivery. Production GitHub OAuth and authorization checks are separate evidence from the API-issued test-session setup; the latter does not claim email or OAuth-consent coverage. The default hosted SMTP remains limited and unverified for general delivery. Physical mobile devices, a 24-hour worker soak, enterprise recovery and uptime remain unproven. The existing lazy Three.js size advisory is not hidden.

## Runtime and collaboration hardening — local verification, 2026-10-24

- Worker results observed after the execution deadline are rejected. Process-group cleanup also stops helpers when their leader has already exited. Raw control-plane responses and protocol-error text cannot expose reflected credentials through the normal error/traceback paths.
- Conversation details and sharing controls remain tied to their chat. Old refreshes cannot hide a newly created conversation. Delayed message, conversation, invitation and project-save acknowledgements preserve newer drafts, including after navigation.
- The conversation view shows the newest 200 messages, including newly accepted messages beyond the old cutoff, and announces omitted older history.
- The forward migration `retained_attribution_and_lease_clock.sql` permits deletion of attribution accounts while preserving terminal timestamps/state and refusing inherited grants. Lease timing uses wall-clock observations after locks: a 17-second lock wait still returned a fresh 15-second lease in the real concurrency test.
- A suspected workspace-cascade conflict did not reproduce. Its existing foreign key was kept; successful workspace deletion and forbidden standalone registration deletion now have regression coverage.

Verification before rollout: **302 Python tests passed**, all four SQL suites passed, all **10 concurrent-session cases** passed, and all **8 real-browser collaboration ordering cases** passed. Existing real Supabase email/PKCE, project/session authorization and compiled desktop/tablet/mobile navigation checks passed. The real GitHub worker smoke also passed completion, rotating credentials, crash recovery, cancellation and revocation. Production rollout evidence is recorded above.

## Product explanation and navigation — local verification, 2026-10-24

The product explanation now starts with project planning, repository analysis and private collaboration. Public pages, workspace introductions, demo scripts, metadata, the legacy interface, historical prototype and product docs distinguish hosted features, self-hosted tools and the planned AI software factory.

Normal pages no longer show generic Back controls. Demo Studio provides **Back to brief**, including direct links, while preserving the draft and returning keyboard focus to the Brief tab. Shared gutters, readable supporting text, explicit mobile workspace navigation, larger touch targets and restrained hover feedback keep the existing visual style consistent.

Exercised verification:

- Python suite: **295 passed**; Ruff, JavaScript syntax and seven storyboard/security contracts passed.
- Hosted and self-hosted production builds passed. Chromium exercised navigation, demo return, draft retention and contextual exports at desktop, tablet and mobile widths. The self-hosted path also exercised real local login, ZIP analysis and cancellation.
- Real local Supabase/Chromium collaboration passed: new-tab email/PKCE login, project invitations and viewer denial, private-session sharing and isolation, revocation and sign-out.
- Additional 320px/768px browser scenarios preserved drafts and focus after demo return. Eight signed-out routes at 1440px and 390px produced no horizontal overflow or axe-core 4.10.3 violations for the selected WCAG A/AA rules. This is automated coverage, not a full accessibility certification or a physical-device test.
- Legacy browser flows passed, with the existing auth-adapter mock clearly distinguished from the real Supabase checks. Historical prototype checks now exercise escaped draft export, local-only repository preview and navigation instead of asserting marketing phrases. They cover the repaired inline-script parse error and the missing mobile Activity link.

These source/local checks preceded the production UI rollout. Free worker hosting still requires provider authorization and measured allowance fit; no card, paid plan or paid inference fallback has been added.

## Durable runtime candidate — local verification, 2026-10-23

Stage 2 implements real project-authorized public-repository analysis, not an empty queue or a coding agent. Work items, attempts, events, leases, checkpoints, cancellation, creator/worker revocation and source pins are persisted in Supabase. The browser can submit, inspect, cancel and download a completed report independently of the worker.

Exercised against isolated native Supabase and real GitHub downloads:

- SQL authorization/transition suite and all nine concurrent PostgreSQL-session cases pass: cancellation/completion, reclaim, registration revocation, concurrent source pinning and idempotent admission.
- A separately authenticated worker completed `pallets/click` analysis (91 source files) after the submitting session signed out; its rotating credential stayed private.
- SIGKILL recovery stopped the orphaned child, reclaimed its expired lease, swept its snapshot directory and completed attempt 2 at the pinned commit. Cancellation and revoked registrations could not publish late results.
- Production-built Chromium UI submitted work, closed the page, reopened the completed report and downloaded the persisted JSON. A new queued run did not show the previous run's result and could be cancelled.
- Python suite: **295 passed**. Ruff and all seven frontend storyboard/security-scan contracts pass. A startup-race regression and a separate actual-child-entrypoint smoke prove that a worker dying before child initialization produces exit 3 and no result.

These initial checks proved local runtime behavior. The production database and one-off execution path were subsequently verified as recorded above; no always-on worker host is configured. A host-reboot/restore drill, 24-hour soak, model-driven code changes and an availability commitment remain unproven. Worker operation, credential limitations and source-pin semantics are in [OPERATIONS.md](OPERATIONS.md), [IMPLEMENTATION.md](IMPLEMENTATION.md) and [API.md](API.md).

## Existing engine and product boundaries

The local FastAPI/SQLite worker supports deterministic starter repositories, bounded ZIP/public GitHub snapshots, read-only heuristic analysis, cancellation/result fencing and exports. Analysis includes bounded full-file fingerprints, manifest hints, AST-based Python security checks and explicit truncation. Imported code is not executed or modified autonomously.

Demo Studio edits contextual storyboards; exports remain unverified drafts. Local Remotion rendering and model/benchmark demonstrations do not establish application-generation correctness.

`oryveta_engine.learning` compares submitted evidence and requires human review. It does not authenticate execution evidence, train a model, retrieve cross-session memory or promote its own production harness.

**Not implemented:** hosted factory execution, production-isolated arbitrary customer-code execution, full knowledge graph/analysis, hosted autonomous Evolve fixes, AI-native application/package rewriting, custom Start New application generation, project on-call telemetry/correlation/repair, GitHub App repository publication, Slack integration, native mobile distribution, continuously running recursive improvement, enterprise SSO/billing or an availability SLA. The separate local repair CLI above does not provide these product capabilities.

See [identity and testing](IDENTITY-WORKSPACES.md), [architecture](ARCHITECTURE.md) and the [staged roadmap](ROADMAP.md). A source change, local test, preview deployment and production release are different evidence levels.
