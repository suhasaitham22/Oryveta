# Autonomous coding harness — research and implementation design

## Goal

Oryveta must perform verifiable software work in Start New and Evolve, while remaining fully inspectable, model-agnostic and free of mandatory commercial model APIs. This document describes the **target architecture**, not an already operational remote agent. There is no hosted coding service and no hosted autonomous fix.

**Implemented local subset.** `coding_runtime` runs a fixed, single-agent repair loop from an operator's shell: a versioned operator specification, exact file allowlists, scoped tools, a pinned local Ollama model, bounded Docker check execution, controller-owned JSON acceptance checks and private checkpointed trace/patch receipts. It stops repeated identical failures rather than widening permissions or budgets. Durable interruption receipts retain the phase, attempted work, observed usage, pending token reservation and source identities when the controller is killed, and each completed edit is checkpointed as an unverified patch with its digest. The same command also re-verifies a supplied candidate archive with **no model contact at all**. [Setup, operator contract and limits](IMPLEMENTATION.md#local-verified-repair-cli).

Keep edits and execution separate: model-driven edits are limited to the disposable source copy and exact file grants; checks run in fresh networkless, non-root containers under controller policy. The standalone CLI remains local. The new Reviewed Evolve worker attaches these capabilities to durable project work, without forwarding browser credentials or claiming multi-tenant sandbox assurance.

**Reviewed Evolve source.** `evolve_runtime` now runs independently reviewed requirements, planning, implementation, model-free verification, process audit and learning. Pydantic AI read-only roles use local schema-constrained JSON; the editor retains the small native tool set. Only an exact-candidate human decision activates successful-run lessons. Failure reports preserve observable checks and diagnostic lessons or explicit unavailability. No role can grant permissions, alter expected values or publish code.

The general knowledge graph, adaptive routing/branching, harness-improvement lab, on-call investigator and operated hosted coding service remain planned. Scoped lessons are evidence-linked guidance, not trained weights or self-authorized policy changes. Crashed work starts a new bounded attempt from pinned inputs, not replay of unknown side effects.

## Start minimal: the single-agent loop

1. Parse a versioned Outcome Contract: user goal, acceptance criteria, source state, allowed changes, limits, safety policies.
2. Collect precise context: repository symbols, tests, dependency graph, failure traces and relevant history.
3. Plan a bounded change, with explicit rollback and verification steps.
4. Select deterministic tools first; use a model only where reasoning or generation helps.
5. Make changes in a disposable workspace inside an isolated runner, recording tool calls and a structured trajectory. A Git worktree alone is not a security boundary.
6. Run independent acceptance tests, static checks, security rules and resource measurement.
7. At verification checkpoints, explicitly continue, switch approach, or stop. Cite evidence, name any alternative, retain the same safety/budget limits, and surface ambiguity or required human approval.
8. Persist the receipt and outcomes. Never report "fixed" merely because an LLM claims success.

## Harness components

**Context Compiler:** Tree-sitter, language server data, symbol/call graphs, Git history, relevant tests, semantic retrieval and compact evidence-linked context windows.

**Knowledge graph:** an explicit delivery before full Evolve. Start with typed PostgreSQL relationships linking repositories/packages, modules/APIs, services, releases, tests, findings, incidents, sessions, changes and evidence. Every relationship carries source/revision, scope and verification/confidence metadata. Derive access from the trusted principal and current grants before retrieval; a model-provided namespace is not authorization. Do not store every raw log line as a graph node or introduce a separate graph database without a demonstrated query need.

Use the graph for change impact, test selection, deployed-source lookup, incident/bug links and evidence-backed lessons. Track unsupported/stale sources, invalidate changed/deleted facts and keep uncertain causal links separate from confirmed relationships. Graph memory does not itself constitute learning.

**Model Adapter:** the text-only `ModelProvider`/`OllamaProvider` API retains SQLite daily reservations. The separate `LocalToolModel` uses native Ollama tool calls, pinned local model identity, bounded context/output and per-run token accounting. A real Qwen3 8B local repair was exercised; this is not broad coding-quality qualification. llama.cpp, vLLM and customer-provider adapters remain future work. Model inference requires user-provided compute.

**Adaptive Router:** versions of model-to-task policies; choose by observed quality, speed, cost and hardware constraints, not model brand. Permit splitting/defer rather than exceeding budget or silently using a paid service.

**Task Orchestrator:** durable task DAG, dependencies, priority, replay/resume points, bounded parallelism, per-tenant quotas and merge-conflict management. Add multi-agent roles only when tests show benefit.

**Typed Tool Runtime (target):** Git operations, code search, filesystem, shell, test runner, package manager, browser preview, observability and deployment. Validate every action outside the model. The implemented local tool set is deliberately much smaller: list, read and search granted files; apply a unique SHA-guarded replacement within the write allowlist; and request the **fixed** development check suite. There is no shell tool, no Git tool, no package manager, no network access, no file creation/deletion/rename and no way for the model to alter scope, model identity, runner, budgets or checks. Missing-argument errors name the required fields rather than guessing them.

**Independent Verifier:** compile, lint, unit/integration/e2e, expected-behavior tests, performance benchmarks, security gates and source/build hashes. Tests invented by the agent must not be the only proof. Implemented locally for one narrow shape: the controller owns the check suites, their literal argv/stdin and their expected JSON, executes them outside the model's reach, compares exit status and parsed output, and can re-run that whole evaluation against a supplied candidate archive without any inference. A successful exit with wrong output is insufficient. Compilers, linters, benchmark gates, security gates and build provenance are not part of it yet.

**Experience Memory:** working memory, project decisions, reusable experience and evaluation history with tenant isolation, retention and human override.

**Harness Lab:** propose policy/tool/context changes, test blinded evaluations, reject regressions, stage rollout and enable rollback.

**On-call investigator:** consumes scoped incident work from the same orchestrator, queries bounded read-only evidence, records hypotheses and, when supported, starts the existing isolated repair/verifier path. Its telemetry credentials have no production write authority. Incident outcomes enter the learning lab only with provenance and verified/uncertain status; an agent's diagnosis is not self-authenticating training data.

## Factory as code and inspectable execution

**Planned implementation requirements, not shipped capabilities.** Ben Holmes's [software-factory article](https://x.com/BHolmesDev/status/2115862731610107965) and [factory-as-code walkthrough](https://www.warp.dev/blog/software-factory-as-code) provide a useful engineering checklist. The full linked article was read through its [accessible mirror](https://nitter.tiekoetter.com/i/article/2115862731610107965). These are practitioner/vendor observations, not controlled evidence that a particular product, cloud deployment or model judge is necessary.

| Requirement | Current Oryveta boundary | Implementation decision |
| --- | --- | --- |
| Configured as code | The local CLI validates and hashes its model/runner, scope, budgets and behavioral-check specification; no complete hosted factory loader or skill/evaluator registry | Extend the existing versioned specification for reviewed tool/skill/evaluator references. Secret **references**, never values, belong in version control. |
| Central conversation history | Private human conversations and durable analysis events exist; Reviewed Evolve adds stage/review records and sanitized trace manifests, while raw model/check evidence stays private to the worker | Retain project/session isolation; this is not a global prompt or shared-memory pool. General agent chat remains separate work. |
| Benchmarking tools | `benchmarks.py` runs small scikit-learn experiments; `learning.py` compares supplied outcome records | Build a software-task runner that restores a pinned pre-action repository/environment snapshot and obtains results from an independent evaluator. Existing helpers are not an agent benchmark or evidence-authentication system. |
| Factory chat | Saved human chat exists; no general coding-agent conversation loop or Slack execution adapter | Let authorized conversations submit and inspect the same canonical work/run records. Web and later Slack integrations must not invent separate execution state or widen the conversation audience. |
| Artifacts | Reviewed Evolve registers candidate archives, patches and sanitized receipt/trace manifests in private Storage, bound to the run and exact digests | Broader screenshots, recordings and external resource IDs still need their own bounded artifact contracts. Downloads must re-check current grants. |
| Computer use | Real browser QA scripts exist; an agent-controlled browser/desktop capability does not | Add a brokered, isolated preview session with approved origins/accounts. Prefer deterministic API/DOM operations; use visual interaction when required. A recording complements, rather than replaces, independent assertions and backend readback. |
| Agent debugger | Analysis events/checkpoints and the local ordered JSONL trace are inspectable by the operator; general tool/subagent inspection and safe forks are absent | Expose ordered tool spans, safe inputs/results, routing choices, retries, costs, parent/child runs and artifact links. Distinguish recorded playback from a new sandbox execution — the local CLI's candidate re-verification is the latter, and it is the only one implemented. |

### Configuration and privilege boundaries

The trusted operator configuration and current grants remain authoritative. A factory definition can request only a subset of that authority; an untrusted repository's instructions cannot register a tool, reveal a secret, loosen egress or replace an evaluator. Agents may propose configuration changes for review, but a running task does not activate its working-copy edits. Pin the active configuration, source, runner image/dependencies, model identifier/revision where available, skill versions and evaluator revision. If a provider exposes only a mutable model alias, record that limitation instead of claiming bit-for-bit reproducibility.

Keep control-plane storage independent of runner location: an authorized local or customer-owned runner can report to the same durable authority. Centralized operation does not require adopting a paid cloud factory or merging customers' raw transcripts. Private conversations, source grants and derived artifacts retain their visibility boundaries; retrieval, sharing and export re-check current permissions. Record concise decisions and observable execution, not a requirement to expose hidden model reasoning.

### Traces, artifacts and replay

Minimum execution lineage includes work/run and parent/fork identifiers, the resolved execution-specification digest, source/environment/evaluator revisions, tool call IDs, timestamps, safe result summaries, failure/cancellation causes and artifact references. Keep truncation explicit. Raw HTTP headers, credentials and private lease/session tokens must not enter model context or ordinary traces.

Playback is read-only inspection of recorded evidence. Re-execution restores a declared checkpoint into a fresh isolated run, obtains fresh scoped authority and records a new lineage edge. It must not replay old writes to GitHub, messaging, email or deployment systems. Changed tool arguments invalidate a recorded-response replay; they require a real sandbox execution or an explicit unsupported result. Pausing prevents new work admission; cancellation and revocation retain the real runtime's fencing and child-termination semantics.

The implemented local behavior is narrower than either of those words suggests, and the distinction matters. **Candidate re-verification is not replay and not resume.** It takes the operator's reviewed current configuration plus a source archive and a candidate archive and performs a *new* run with its own run identifier: it reproduces the baseline from scratch, re-executes every declared check in fresh containers, and records fresh evidence. It does not restore a prior checkpoint, does not continue an interrupted conversation, does not re-issue any recorded tool result, does not replay side effects (there are none to replay) and makes no model call even when no model is reachable. A supplied `"passed"` claim is never trusted; the candidate's own files are never executed on the host and are never applied with a shell patch tool. The authority comes from the configuration and the operator's access, never from the earlier receipt.

An interruption receipt is likewise a record, not a resume point: a pending action may already have executed and its effects may be newer than the saved patch, so it must never be automatically replayed. Such a receipt still reads `incomplete`, which is **not an outcome** — only `needs_review`, `rejected`, `failed` and `cancelled` are terminal execution statuses, and `incomplete` means initializing, in flight, or killed before finalizing. Reading it as a result, or as a liveness signal, is a mistake. Older runs that recorded only a patch cannot be re-verified from that evidence alone, because a unified diff is not an archive — reproducing them requires the original source archive and an equivalent candidate, and absent that the historical record stays exactly what it was.

Store original evidence separately from optional reviewer-friendly clips and summaries, with a mapping back to the run/source. Screenshots do not prove backend state or access control. A claimed external side effect needs an independently observed resource ID/state, and publication still requires approval of the exact verified revision.

## Research-backed adaptation design

Reviewed on 2026-10-29. The following are **source-reported findings and proposed Oryveta adaptations**, not replicated results or implemented learning capabilities. Do not add the papers' gains together, use their model rankings as our defaults, or claim that their task distributions represent customer software work.

| Supplied paper | Mechanism worth testing | Boundary on the evidence and our adoption |
| --- | --- | --- |
| [SkillOpt, 2605.23904v2](https://arxiv.org/pdf/2605.23904v2), §§3–4, Appendix B/C | Optimize a versioned skill with bounded edits, scored rollouts, an explicit selection gate, rejected-edit history and slower consolidation; keep the execution model fixed during comparison. | Evaluated on QA, documents, spreadsheets, math and embodied tasks, not our repository-repair distribution. Training consumes rollout/optimizer calls; “no extra optimizer calls at deployment” does not mean zero prompt-token cost. Use independent software verification and reviewed promotion, not a scalar score alone. |
| [Language Models Learn to Improve Language Models / LM2LM, 2610.23344v1](https://arxiv.org/pdf/2610.23344v1), §§3–4, 6–7 | A proposal ranker grounded in measured experiments must be recalibrated on the proposals it currently favors; record predicted and observed outcomes separately. | This is RL for LM-development proposals, with real model-training runs and substantial compute. The reported 33% reduction concerns data-generation cost, not a free end-to-end factory. A ranker may prioritize experiments; it cannot certify correctness, security or release. Prefer executing cheap checks to predicting them. |
| [Harness², 2610.14224v1](https://arxiv.org/pdf/2610.14224v1), §2, Appendix B/F | Propose, probe under matched conditions, then selectively compose task-local harness candidates. Retain evidence-backed refinement lessons separately from the execution baseline. | The paper explicitly says behavioral contrasts do not verify correctness or guarantee transfer. Its editable prompts/guardrails/plugins are not permission to edit Oryveta's trust boundary. More probing adds total work even when the selected execution uses fewer steps. |
| [What is Missing from AI Post-Training AI, 2608.19072v2](https://arxiv.org/pdf/2608.19072v2), §§3–5, 7, Appendix D | Make approach revision an explicit decision rather than hoping that longer reasoning or a larger journal causes it. Compare continue/switch branches from the same checkpoint and remaining budget. | The 2.1% switch rate describes that post-training corpus. Controlled interventions used one small base model and three benchmarks; mid-run alternatives/branch points were chosen by the authors. This motivates testing a decision protocol, not automatically switching after every failure or assuming the reported gains transfer. |

Reproduction discipline matters: SkillOpt's Table 2 and Appendix C describe different splits for the training-size ablation. Resolve the exact configuration against the linked implementation before reproduction; this ambiguity is not, by itself, proof of test-set leakage. Across all sources, record sample counts, configurations, exclusions and uncertainty rather than copying headline percentages.

### Bounded learning, not self-authorized mutation

Keep two separate loops. The task loop may evaluate an allowlisted, task-local guidance/skill overlay against a frozen baseline. The improvement lab may later propose a persistent skill or harness version from those records. The next task starts from the approved baseline, not the previous task's unreviewed overlay. Authorization, credential grants, egress, source identity, evaluator code/expected values and publication approval remain outside the optimizer's writable surface.

Start with one skill and one hypothesis. Bound **edit count, changed bytes/tokens and total artifact size**, not merely the number of patch operations. Require an expected parent hash, record the actual applied diff and rejected/skipped edits, and evaluate the resulting artifact's hash. A rejected proposal belongs in the lab's diagnostic history, not automatically in production memory. Selection and report-split evaluation follow [EVALUATION.md](EVALUATION.md#research-led-experiments).

Use explicit decision records at verifier checkpoints: current approach, observed failure/progress evidence, continue/switch/stop, any named alternative and falsifier, remaining budget and checkpoint lineage. Distinguish a repairable execution problem, a weak approach and an infrastructure failure. Configure and test limits on unproductive attempts; do not reward raw switch counts or reset the budget by opening another branch. The initial policy remains a bounded single-agent executor, with multi-candidate adaptation disabled until it demonstrates benefit.

### Scoped experience and cheap-to-expensive evaluation

Store small versioned experience entries with stable IDs, applicability, source/revision, audience, supporting run/evaluator references, counterexamples and expiry/revocation state. Use explicit deltas rather than rewriting one ever-growing prompt. An agent's “helpful” label is a hypothesis, not causal evidence; distinguish observed use, verified task outcomes and controlled evidence that an entry helped. Failed experiments can supply verified negative evidence. Keep confounded or unverified lessons as candidates rather than silently promoting them.

Retrieve within a declared context budget and re-check permissions/freshness. Deduplication must never merge audiences or turn project-specific facts into global rules. Preserve access to the underlying evidence when summarizing. A predicted score, synthetic outcome or model preference must never be relabelled as an observed verifier result.

Use staged checks: cheap schema/path/syntax checks, targeted behavior checks, broader regression/security checks, then relevant browser/API/performance acceptance. All required gates still run before acceptance; early screening must not hide regressions. An optional calibrated ranker can allocate a limited experiment budget, but the final result comes from actual execution and review.

### Complementary engineering evidence

| Primary source | Decision for Oryveta | Transfer limit |
| --- | --- | --- |
| [SWE-agent, 2405.15793v3](https://arxiv.org/html/2405.15793v3), §§2–3 | Provide simple typed search/read/edit tools, bounded line-numbered observations, atomic edits with useful diagnostics and recoverable history. | Its interface settings and 2024-model results are experimental choices, not universal window sizes or a reason to remove necessary context. |
| [SWE-Bench Pro, 2509.16941v1](https://arxiv.org/html/2509.16941v1), §§3–4, 7 | Use real repository tasks, pinned runnable environments, relevant fail-to-pass and pass-to-pass tests, and repository-disjoint evaluation. | A test suite is incomplete; public/private distributions differ. Copyleft licensing is not proof that a model has never seen a repository. Check each dataset/repository's terms. |
| [AgentDojo, 2406.13352v3](https://arxiv.org/html/2406.13352v3), §3 | Exercise hostile tool output with state-based utility and attack predicates. Test benign task completion as well as denied exfiltration/scope/publication attempts. | Its text-oriented application environments do not establish security for our code runners or multimodal browser. Delimiters, filters and model judges do not replace code-enforced scope. |
| [Agentic Context Engineering, 2510.04618v1](https://arxiv.org/html/2510.04618v1), §§3–4 | Test itemized, provenance-bearing experience and localized updates against no-memory baselines. | Its task/model cohorts and feedback assumptions differ from ours. Long context is not free, model-assessed usefulness is not proof, and memory-poisoning resistance must be tested separately. |

## Rewrite to Rust

Rust modernization is not a default instruction. First compare defects, latency, throughput, runtime costs, maintainability and migration risk against targeted improvements in the current stack. Use characterization tests and behavior parity before incremental migration; require approval for changes to production behavior.

## Safety / non-goals

No privileged autonomous production deployment; no self-modifying security policy; no untested auto-merge; no silent cost escalation; no cross-tenant training on customer data; no unlimited background agent promises. Single-agent verified patching should work before scaling to agent swarms.
