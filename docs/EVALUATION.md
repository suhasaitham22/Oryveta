# Internal Arena: objective evaluation and feedback-driven learning

## What Arena means

Arena is the **internal test/research system**, not a third consumer product screen. The public product has Start New and Evolve. Kaggle is one benchmark source among software engineering tasks; strong Kaggle scores do **not** by themselves prove superior coding or consultancy delivery.

## Test categories

- Repository repair: bounded bug fixes, regression tests, CI and documentation.
- Build from brief: create an application from written requirements and hidden acceptance criteria.
- Evolve / modernization: behavior-preserving refactor, dependency upgrade and performance migration.
- Terminal/environment tasks: tools, setup, build, debugging and environment constraints.
- Kaggle / MLE-Bench: data analysis, experiment design, classification/regression, validation discipline and resource allocation, complying with every competition rule.

Possible public references: SWE-Bench Pro, SWE-bench Verified (a distinct suite), Terminal-Bench 2.0, MLE-Bench (including Lite), AutoGluon, mini-SWE-agent, OpenHands and OpenCode. Recheck benchmark integrity and license/usage terms before selecting tasks. Guard against contamination and leaked evaluation answers.

## Scientific protocol

Pin task snapshot, hardware class, execution environment, model identifier and revision, harness version, seeds, dependencies, available tools, compute/time budgets and evaluator revision. Compare **same model with different harnesses** to measure harness quality, then whole-system configurations separately. Pre-register development, selection and locked report splits, their absolute sample counts, grouping rules and allowed evaluation budget. Model/provider aliases that cannot be pinned remain an explicit reproducibility limit.

Record successful **and failed** attempts, retries, output patches, real reviewer minutes and all compute resources. Include proposal, probe, composition, selection, reflection and setup costs, not just the final executor's steps. Use matched repeated trials and task/repository-clustered uncertainty where applicable; publish exclusions and per-stratum counts. A small pilot can establish feasibility, not a universal improvement claim.

## Metrics

Accepted completion rate; critical regressions; end-to-end time; total human review and intervention; inference tokens/CPU/GPU time; peak memory; cost at equal resource class; evidence quality; rollback frequency. Also report continued/revised/stopped decisions, repeated unproductive attempts and measured gains from controlled approach forks. Switch frequency and model preference are diagnostics, not objectives to maximize. Report cost/quality/latency tradeoffs rather than a single benchmark percentage.

## Hypothesis and feedback graph

Experiment record: task/dataset/repository fingerprint, proposed change, reason, alternative hypotheses, baseline, control, configuration, validation scores with variance, resource use, failure cause, owner, confidence and evidence references.

Self-learning sequence: collect run evidence → distill candidate experience → propose one harness modification (e.g. retrieval tool, router policy, migration precheck) → run benchmark A/B with blinded unseen tasks → enforce quality/security/cost gates → promote version or reject/rollback. No unconstrained agent edits to its own production security policies.

## ProofLoop and receipts

Outcome Contract states baseline/target/guardrails. Proof Receipt links code, tests, deployment and measured results with status: Proposed, Tested, Verified in staging, or Verified in production. Hashes demonstrate integrity, not causal correctness. Production impact measurement may require carefully designed canaries or controlled experiments.

## Competition integrity

Respect Kaggle consent, entry/submission limits, team account and external-data restrictions. Public leaderboard feedback is not a substitute for sound offline cross-validation and private-final evaluation. Live submissions should be approval-controlled initially.

## Current status

A local earlier MVP ran small scikit-learn cross-validation benchmarks on built-in datasets. **No Kaggle medals, leaderboard domination, third-party benchmark wins, automated learning gains or deployed Arena worker are established.**

## Implemented fail-closed evidence gate (2026-10-12)

`oryveta_engine.learning` compares paired baseline/candidate outcomes on pinned dataset and evaluator fingerprints. It rejects unmatched, duplicate or insufficient tasks, candidate security failures, any previously passing task regression, no improvement, or cost overruns. Accepted cases produce only **NEEDS_HUMAN_REVIEW**, never an automatic deployment. A SHA-256 receipt allows reviewers to identify a precise evidence payload, not prove the truth of caller-submitted results. `python scripts/evaluate_candidate.py evidence.json` reads JSON evidence and prints the decision. Independent harness execution, genuine held-out task selection, human approval, live agents, persistent experience retrieval and model fine-tuning remain future integrations. Do not call this autonomous self-training.

## Research-led experiments

These are planned evaluations, not results already obtained by Oryveta. The source mechanisms and their transfer limits are recorded in [AGENT-HARNESS.md](AGENT-HARNESS.md#research-backed-adaptation-design). No new model training, paid provider or external benchmark run is implied by this document.

### Evidence and split discipline

1. Build task packages from the **pre-action** repository/environment checkpoint, user requirements and authorized context. Remove the original solution, later conversation answers, final patch and evaluator-only expected values. Curate relevant fail-to-pass and pass-to-pass checks; verify environment/test stability before the campaign and record any excluded cases. The candidate cannot remove failing checks or alter the acceptance criteria.
2. Keep development/optimizer evidence, candidate selection and locked reporting separate. Group related tasks by repository/project and, where relevant, time so near-duplicate changes do not leak across splits. Resolve dataset and repository licensing/data consent before ingestion. A public benchmark's name or copyleft license does not prove absence from model pretraining.
3. Repeated selection-set queries can overfit it. Log every candidate and query, cap adaptive search, freeze the chosen configuration before opening the report split, and do not silently reuse an exposed report set as fresh holdout evidence. A deliberately forward-only online-learning study must be labelled separately from a frozen held-out evaluation.
4. Separate `predicted`, `model_assessed` and `observed` records. An observed result needs a trusted evaluator execution, task/source/configuration/environment identity, artifact references and provenance. Hashes bind bytes; they do not authenticate the producer or prove that the work happened. Infrastructure errors, missing verdicts and unevaluated cases are explicit states, never silently successful outcomes.
5. Freeze the permission boundary, evaluator implementation/expected values and release policy outside candidate workspaces. A different model acting as a judge is not sufficient independence. Use real tests/state checks for measurable requirements and retain human assessment for unresolved/open-ended requirements; an unverified deliverable remains unverified.
6. Count the **entire** campaign: all attempted rollouts, model roles, context tokens, tools, failed runs, verifier execution, environment setup and human review. Record prices/assumptions separately from usage. “No additional optimizer call at deployment” still leaves skill-context tokens, and a faster final rollout can conceal a more expensive multi-probe campaign.

### Bounded experiment sequence

| Experiment | Fair comparison | Required evidence before adoption |
| --- | --- | --- |
| Fixed coding loop and tool interface (SWE-agent / SWE-Bench Pro) | Same model, tasks, runner, scope and budget; vary the bounded interface, not its privileges | A real source repair passes independent relevant checks while retaining existing behavior. Stale/invalid patches do not corrupt files; capped observations remain useful; benign tasks still complete. |
| Skill-version optimization (SkillOpt) | One skill/hypothesis, fixed executor/evaluator, matched trials and capped edits/tokens/selection queries | The applied artifact/diff is recorded; gains survive the pre-registered reporting protocol and cost/safety/regression gates. Rejection leaves the approved version intact. |
| Task-local harness/approach forks (Harness² / strategy study) | Predeclared checkpoint/trigger, matched continuation and named-alternative branches, same remaining budget; include any composition cost | Record which changes were supported, harmful or confounded. A selected candidate is not automatically a transferable lesson. Stop/escalation and a justified decision to keep the baseline are valid outcomes. |
| Structured experience (ACE) | Memory off/on from development-only evidence; freeze updates for the held-out comparison, or explicitly run a separate forward-only study | Measure verified task outcomes and context cost. Test stale/conflicting entries, revoked sources, deletions and poisoning. No cross-scope deduplication or promotion based only on an agent's usefulness rating. |
| Optional proposal ranker (LM2LM adaptation, not RL replication) | Compare ranked versus simple/random prioritization on the same candidate pool and total execution budget | Audit predicted versus real rankings and harmful false positives on held-out outcomes. Recalibrate when the proposal distribution changes; real verification remains authoritative. Skip the ranker if running the real checks is cheaper or better. |
| Adversarial execution (AgentDojo adaptation) | Benign and attacked versions of the same useful tasks; attacks in repository files, issues, logs, fetched pages and candidate memories | Observe actual environment state for denied credential access, scope escape, evaluator mutation and unapproved publication. Include adaptive/persistent attacks and retained benign utility. Any critical violation blocks promotion; zero observed violations is not a universal security proof. |

For each experiment, state the sample size, candidate/retry budget, primary outcome, minimum effect worth adopting and uncertainty method before inspecting results. Do not copy a paper's model-specific numerical gain or arbitrary sample size into our acceptance threshold. Large benchmarks and RL training remain separate authorized compute/data programs.

### Promotion and current helper limits

A positive selection result produces a candidate for independent reporting and review, not a deployment command. A reviewed version has its parent hash, actual edit report, evidence scope, evaluation manifest, rejection history and rollback target. Observe later outcomes before further expansion. Do not let a learned skill, synthetic reward or ranker change the verifier, permissions or approval policy.

The current `learning.evaluate` helper's default minimum of five pairs is an input gate, not a statistically justified experiment size. Do not lower a campaign's required sample size or omit variance estimates merely to satisfy that helper.
