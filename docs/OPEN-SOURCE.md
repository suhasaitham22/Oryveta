# Oryveta: open-source policy

## License

Original Oryveta code is licensed under **Apache License 2.0**. The full legal text is in [LICENSE](../LICENSE), and copyright attribution is in [NOTICE](../NOTICE). Copyright © 2026 Suhas Aitham and Oryveta contributors.

The prior empty GitHub scaffold included an MIT license. This project now uses Apache-2.0 as its documented default; the change does not silently alter third-party or earlier independently authored works outside Oryveta.

Apache-2.0 allows commercial use, forking, redistribution, and self-hosting while imposing applicable notice and license-preservation requirements. Contributors retain copyright in their contributions unless separately agreed. Trademark and branding rights are not implicitly granted.

Rights already granted under the licence are irrevocable, and no later commercial decision takes them back: anyone can keep running and modifying this source without a subscription. That is a statement about the **software licence only**. It is not a promise of perpetual free **hosted** capacity — the hosted workspace is a capacity-limited free preview whose quotas, retention and terms may change with advance notice, consent before the change binds an existing workspace, and a working export path. See [PRICING.md](PRICING.md).

## Community model

- Publish complete source, model adapters, harness, tests, and benchmarks as they are built.
- Self-hosted usage should not require commercial AI APIs or Oryveta subscription fees. The local repair CLI, its model-free candidate re-verification path and the local Ollama adapter are part of the open source and run on the operator's own machine and weights; hosted execution is a separate, still-planned capability.
- Dependency and model licenses must be reviewed individually; "open weights" alone does not guarantee unrestricted commercial usage.
- Preserve required license and attribution notices for all dependencies and media assets.
- Maintain public architecture decisions, reproducible tests, a security policy, and issue/PR contribution guidance.
- Do not include secrets, client datasets, or proprietary source code without permission.

## Product boundary

**Start New** creates applications; **Evolve** analyzes and improves existing repositories.
The sequence is deliberate: a verifiable maintenance change first, the wider factory afterwards.
Kaggle experiments and other benchmarks belong to internal evaluation.
Proof receipts must distinguish agent claims from independently observed results, and a
`needs_review` receipt is a request for human review rather than an approval, a publication
or a correctness guarantee.

## Security and governance

Open source does not mean every integration credential is public. OAuth secrets,
GitHub installation tokens, service credentials, and proprietary customer data
remain private. Agents are never authorization authorities: their tool requests
require host-side permission checks, constrained execution, and approval gates.
