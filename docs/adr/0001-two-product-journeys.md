# ADR 0001: Exactly two primary user journeys

Status: **Accepted**. Date: 2026-10-09.

## Context

Oryveta was originally discussed with a separate Kaggle Arena screen, a generic Build flow and a repo optimization experience. The goal evolved toward consultancy-scale autonomous engineering, not a Kaggle tool.

## Decision

Primary entry points are **Start New** (new runnable repository and application) and **Evolve** (import existing repo, detect and independently verify improvement opportunities, implement approved patches). Home and Activity may appear in navigation for context. Internal **Arena** is an engineering evaluation subsystem, with Kaggle only one benchmark dataset.

## Consequences

Simpler onboarding, lower UI complexity, clearer scope and unified proof/evaluation harness. Never market a scaffold as a complete custom app or heuristic flag as proven dead code. New proposed third journeys require a new ADR.
