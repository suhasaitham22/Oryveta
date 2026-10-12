# Soft Modern / Minimalist design system

**Design direction LOCKED:** Oryveta uses the calm "Soft Modern" identity, not a glass-heavy futuristic AI dashboard. Our design reference is high-quality minimalist productivity software with strong typography, space and restrained micro-interactions.

## Color tokens

| Token | Value | Use |
| --- | --- | --- |
| Canvas | #F7F8FA | Warm page background |
| Surface | #FFFFFF | Panels and forms |
| Primary text | #1D2636 | Main information |
| Muted text | #59677C | Descriptions with stronger contrast |
| Accent | #4866A8 | Primary actions and selection |
| Border | #DCE3EB | Dividers and cards |

The React studio uses these tokens for a light-first experience. It does not add a dark/neon mode or external font requests. Inter is preferred when available; a system sans-serif fallback works under the self-hosted CSP.

## Typography and components

The current studio uses React, Tailwind, Radix/shadcn primitives and Lucide. The landing refines the maintained MIT **ShadcnStore dashboard + landing template**, Vite version, pinned at `953300fa5176608a9d682943edfc359ce809f2c7`. It retains the centered hero/product frame, alternating feature layouts and sticky responsive navigation while replacing sample imagery and marketplace copy with concrete Oryveta scenarios. See [source mappings and full license](../apps/web/studio/THIRD_PARTY.md). No paid assets, fictional testimonials, customer metrics or unsupported outcome claims are included.

## Information architecture

Home/Overview; **Start New**; **Evolve**. Workspaces, Private chats and Activity are secondary context. Each journey has **Brief**, **Local run** and **Demo Studio** tabs; Demo Studio has no standalone navigation entry or default/fallback journey. Arena remains internal; its protocol is linked from Activity rather than positioned as a product start.

## UX details

- Landing: a client onboarding brief, billing-service snapshot, recorded local work and contextual handoff form a scroll-linked story. Explicit chapter buttons offer keyboard navigation; Start New and Evolve are alternative starting points, not a fabricated execution sequence. All product illustrations are labeled.
- Login: hosted Supabase email-link identity remains separate from local GitHub/demo cookies. Repository permissions are not granted by email sign-in. Local sign-in is explicit; `/api/config` must return the expected JSON contract, not a static host's SPA fallback.
- Onboarding: two primary entry cards. No standalone demo option, fake project metrics or fabricated activity.
- Start New: export an unexecuted planning brief; on the self-hosted studio, create a deterministic template starter, export it and request actual source analysis. Custom brief implementation and application test execution are not provided.
- Evolve: export a change brief; locally import an authorized ZIP, inspect the recorded analysis run and review heuristic findings. Imported code is never executed; analysis does not apply patches or establish security/correctness.
- Demo Studio: exact journey selection, no fallback to another story; headline/narration edits and scene selection live with the brief. Drafts are retained while switching tabs, journeys and workspace context within the mounted workspace. They are not saved to an account or across reload/sign-out. Exports remain `storyboard_only_not_rendered`, `verified: false`, with journey/brief/project context. The Remotion/snapcn pipeline remains separate.
- Working UI: show waiting/running/completed/failed/canceled from persisted job state. Lifecycle task rows represent queue acceptance, worker analysis and result persistence only. Running tasks animate subtly; stopped tasks do not acquire false completion marks. One elapsed label uses API timestamps; success becomes compact with expandable recorded tasks and events. User-expanded details remain open across ordinary polling updates.
- Event summaries are recorded actions, not private reasoning. Event counts are never labeled tool counts. No invented percentage, ETA, file-by-file task state or fine-grained agent success. A polling error freezes the last confirmed state and offers explicit refresh; it never implies completion. Latest project findings are labeled separately because an older selected job may have a different result.
- Mobile: responsive cards/forms, native modal workspace navigation with Escape/focus management, no horizontal overflow and meaningful touch targets. Existing Supabase workspace CRUD and explicit private-chat sharing remain in place.

## Motion and accessibility

Use 120–220ms transitions for affordances. Scroll changes the selected illustrative chapter; there is no auto-playing video or invented timer-driven task completion. Reduced-motion disables animation and smooth scrolling. Important status announcements remain outside the `aria-busy` task list; elapsed seconds are not announced repeatedly. Provide visible focus, skip links, native labeled form controls and keyboard-operable Radix tabs. The only continuous motion is a real running-state indicator; reduced-motion replaces it with a static icon and text.

## Current implementation

The source supports two environments without conflating identities:

- **Hosted React (Vercel):** Supabase identity/workspaces/private human chats, plus browser-only planning and storyboard exports. No hosted coding engine, application test runner or deployment automation. Authenticated integration code is not evidence of a real two-account/mailbox acceptance test.
- **Self-hosted React (`/studio/` on FastAPI):** built assets use relative URLs, while requests use same-origin `/api` and `/auth` routes with existing cookie/CSRF protection. Local starter/import/analyze/cancel operations consume the real worker job contract. Disconnect/identity changes clear mounted owner-scoped data, and project/job selections are owner-bound. The deliberately separate legacy `/` UI remains supported.

`public/demo-stories.json` includes at least three scenes for Start New, Evolve, recorded local work, private chats and internal evaluation. `npm run check` validates scene/receipt metadata and completion-evidence references rather than pinning source formatting or component file names. It also performs a narrow privileged-Supabase-credential scan, not a security certification. Build/browser/runtime evidence belongs in the change's verification report; screenshots of sample product states are not proof of engine execution.

## Redesign visual evidence

These are local browser captures of the built studio, not a production deployment claim.

![Template-based Soft Modern landing with two product journeys](media/studio-landing.png)

The landing's product frame is explicitly illustrative. It communicates a brief, source evidence and draft story rather than a completed customer application.

![Real local source-analysis worker with recorded lifecycle tasks](media/studio-local-run.png)

The task panel was captured while a real worker inspected a synthetic repository fixture through the self-hosted React consumer. Its elapsed value includes queue wait; it is not a performance benchmark or time-saved claim. The same run later reported success with persisted queued/started/completed events. Source analysis does not run application tests or establish feature correctness.
