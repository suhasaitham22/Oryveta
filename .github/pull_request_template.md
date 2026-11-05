## Purpose and scope

Explain the user-visible problem, change and non-goals. Link a relevant issue or Outcome Contract.

## Verification

- [ ] Python 3.11 / 3.12 / 3.13 tests and branch-coverage gate pass
- [ ] Ruff, JS syntax, packaging and Docker smoke pass
- [ ] Dependency audit and Bandit checks pass (or documented approved exceptions)
- [ ] New behavior has regression tests, including failure/authorization paths
- [ ] No secrets, unapproved client data, unsafe external effects or unapproved model usage
- [ ] Documentation and status updated; rollback/compatibility considered
- [ ] Availability, pricing and product-goal claims match current source and release state; planned features and historical examples are labelled

## Evidence and limitations

Link exact test/CI results and any reproducible before/after evidence. Describe known gaps; do not claim a feature is live based only on a scaffold or mock.

For local repair/verification changes, include the real-container and CLI result, candidate/source identity and denied-scope cases. A model-free verification must not contact inference, replay tools or treat a previous success claim as approval. Do not attach private source archives or operator checks to a public PR.

## Product demo contract
- [ ] New customer-facing feature has an entry or updated scenes in `apps/web/studio/public/demo-stories.json`, or this change is internal-only with justification.
- [ ] Storyboard matches implemented capability and does not misrepresent mocks as live features.
- [ ] Demo receipt/limitations reviewed; MP4 capture available where useful.
- [ ] React build + desktop/mobile browser checks pass (if UI changed).
