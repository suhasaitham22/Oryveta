## Purpose and scope

Explain the user-visible problem, change and non-goals. Link a relevant issue or Outcome Contract.

## Verification

- [ ] Python 3.11 / 3.12 / 3.13 tests and branch-coverage gate pass
- [ ] Ruff, JS syntax, packaging and Docker smoke pass
- [ ] Dependency audit and Bandit checks pass (or documented approved exceptions)
- [ ] New behavior has regression tests, including failure/authorization paths
- [ ] No secrets, client data, unsafe external effects or unapproved model usage
- [ ] Documentation and status updated; rollback/compatibility considered

## Evidence and limitations

Link exact test/CI results and any reproducible before/after evidence. Describe known gaps; do not claim a feature is live based only on a scaffold or mock.
