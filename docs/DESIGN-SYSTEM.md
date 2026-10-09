# Soft Modern / Minimalist design system

**Design direction LOCKED:** Oryveta uses the calm "Soft Modern" identity, not a glass-heavy futuristic AI dashboard. Our design reference is high-quality minimalist productivity software with strong typography, space and restrained micro-interactions.

## Initial color tokens

| Token | Value | Use |
| --- | --- | --- |
| Canvas | #F7F8FA | Warm page background |
| Surface | #FFFFFF | Panels and forms |
| Primary text | #1D2636 | Main information |
| Muted text | #667489 | Descriptions |
| Accent | #4866A8 | Primary actions and selection |
| Border | #DCE3EB | Dividers and cards |

These are design targets, not a guarantee that all current prototype CSS exactly matches every token. Support light mode first and meaningful dark mode later.

## Typography and components

Inter or Geist; hierarchy by weight/spacing rather than oversized marketing headlines. React + TypeScript + Tailwind + Radix/shadcn planned for the production application, Lucide icons and Motion for React. Monaco for editor/diffs, React Flow only where dependency diagrams improve understanding, Recharts for measured results. Load heavy code-editor bundles lazily.

## Information architecture

Home/Overview; **Start New**; **Evolve**. Secondary context: Activity/Approvals, Projects, Workspaces and Settings. Do **not** put Kaggle Arena in primary navigation; Arena is the internal evaluation lab.

## UX details

- Landing: open-source premise, clear product promise and evidence; no false performance claims.
- Login: minimal GitHub identity OAuth; permissions transparent; accessible error recovery.
- Onboarding: two clear, equally understandable entry cards; capture brief or repository.
- Start New: requirements panel, architecture review, generated project tree, diff/code, test evidence, safe publish and deployment controls.
- Evolve: repo architecture, findings with confidence, prioritized actions, before/after diff, risk gates and PR progress.
- Agent workspace: natural language chat plus task plan/status; never replace deterministic evidence with chatbot assertions.
- Consultancy view: client engagements, milestones, budgets, ownership, audit-ready receipts.
- Mobile: usable project/approval flows, responsive navigation, no horizontal overflow.

## Motion and accessibility

120–220ms subtle transitions for affordances; no intrusive pointer tricks, parallax or continuous animation. Honor reduced-motion preference. Provide accessible labeling, full keyboard navigation, visible focus, WCAG-conscious contrast, skeletons and comprehensible error states.

## Current implementation

The public site at https://oryveta.vercel.app is an interactive **static preview**. It includes two journeys and editable form previews; it is **not** a functioning authenticated agent application. Actual local MVP screenshots and earlier video walkthrough are concept/design materials, not production telemetry.
