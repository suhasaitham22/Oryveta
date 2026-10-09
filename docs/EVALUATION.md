# Internal Arena: objective evaluation and feedback-driven learning

## What Arena means

Arena is the **internal test/research system**, not a third consumer product screen. The public product has Start New and Evolve. Kaggle is one benchmark source among software engineering tasks; strong Kaggle scores do **not** by themselves prove superior coding or consultancy delivery.

## Test categories

- Repository repair: bounded bug fixes, regression tests, CI and documentation.
- Build from brief: create an application from written requirements and hidden acceptance criteria.
- Evolve / modernization: behavior-preserving refactor, dependency upgrade and performance migration.
- Terminal/environment tasks: tools, setup, build, debugging and environment constraints.
- Kaggle / MLE-Bench: data analysis, experiment design, classification/regression, validation discipline and resource allocation, complying with every competition rule.

Possible public references: SWE-bench Pro Verified, Terminal-Bench 2.0, MLE-Bench (including Lite), AutoGluon, mini-SWE-agent, OpenHands and OpenCode. Recheck benchmark integrity and license/usage terms before selecting tasks. Guard against contamination and leaked evaluation answers.

## Scientific protocol

Pin task snapshot, hardware class, execution environment, model identifier and revision, harness version, seeds, dependencies, available tools, compute/time budgets and evaluator revision. Use held-out/blinded tasks and independent tests. Compare **same model with different harnesses** to measure harness quality, then whole-system default configurations separately.

Record successful **and failed** attempts, retries, output patches, real reviewer minutes and all compute resources. Publish reproducible configuration and aggregate uncertainty rather than cherry-picked public leaderboard positions.

## Metrics

Accepted completion rate; critical regressions; end-to-end time; total human review and intervention; inference tokens/CPU/GPU time; peak memory; cost at equal resource class; evidence quality; rollback frequency. Report tradeoffs, not just a single invented benchmark percentage.

## Hypothesis and feedback graph

Experiment record: task/dataset/repository fingerprint, proposed change, reason, alternative hypotheses, baseline, control, configuration, validation scores with variance, resource use, failure cause, owner, confidence and evidence references.

Self-learning sequence: collect run evidence → distill candidate experience → propose one harness modification (e.g. retrieval tool, router policy, migration precheck) → run benchmark A/B with blinded unseen tasks → enforce quality/security/cost gates → promote version or reject/rollback. No unconstrained agent edits to its own production security policies.

## ProofLoop and receipts

Outcome Contract states baseline/target/guardrails. Proof Receipt links code, tests, deployment and measured results with status: Proposed, Tested, Verified in staging, or Verified in production. Hashes demonstrate integrity, not causal correctness. Production impact measurement may require carefully designed canaries or controlled experiments.

## Competition integrity

Respect Kaggle consent, entry/submission limits, team account and external-data restrictions. Public leaderboard feedback is not a substitute for sound offline cross-validation and private-final evaluation. Live submissions should be approval-controlled initially.

## Current status

A local earlier MVP ran small scikit-learn cross-validation benchmarks on built-in datasets. **No Kaggle medals, leaderboard domination, third-party benchmark wins, automated learning gains or deployed Arena worker are established.**
