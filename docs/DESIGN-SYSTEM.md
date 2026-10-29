# Oryveta Studio — orbital studio

The current visual system pairs an off-white canvas and confident Geist typography with a dark product rail, cobalt actions and original orbital artwork. It replaces the previous olive/yellow treatment across public pages, sign-in, workspace, projects, conversations, briefs, demos and execution views. The redesign preserves the working product and its available-versus-planned boundaries.

## Reference synthesis and attribution

Public references reviewed on 2026-10-29:

- [Antigravity](https://antigravity.google/): spacious editorial hierarchy and restrained dimensional motion.
- [Lunon](https://lunon.ai/): cinematic composition and clear section hierarchy.
- [Linear](https://linear.app/): precise product surfaces, contrast and information density.
- [Raycast](https://www.raycast.com/): product-led graphics and purposeful interaction.

Antigravity, Lunon and Linear were inspected in Chromium; Raycast's public product presentation was also reviewed. These are inspiration, not implementation dependencies. No reference-site source, videos, models, brand marks, customer logos or performance claims were copied. Orbital geometry, illustrations and product examples are original. Geist is self-hosted under OFL-1.1; historical ShadcnStore notices remain. See [THIRD_PARTY.md](../apps/web/studio/THIRD_PARTY.md).

Home leads with the product's job, then capability cards, Start New/Evolve choices, an illustrative artifact viewer, a clearly labelled planned-delivery sequence and a closing CTA. The hero's SVG strata and orbital traces need no 3D renderer or external image. The heavier spatial artifact view is a separate, explicitly opened interaction. Working views use the same typography and controls without ambient graphics competing with forms, messages or results.

## Compact shared navigation

A single shared header exposes **Home / About / What We Do / Workspace**, the Home logo, and the appropriate sign-in action or local-edition label. A compact trail provides semantic linked breadcrumbs; normal pages do not have a generic Back button. Inside Demo Studio only, **Back to brief** returns to the same journey's Brief tab and focuses that tab, including direct demo links. It never relies on browser history to choose the destination. Native browser Back/Forward remains available. Mobile uses an explicitly labelled Workspace menu, separate from site navigation. Desktop context controls appear only when a workspace switcher is needed.

React Router owns pathname and query history. `BrowserRouter` uses Vite's `BASE_URL` as its basename. Hosted `npm run build` uses `/` and writes `dist`; `npm run build:local` uses `--mode selfhost`, `/studio/`, and a separate `dist-local`. FastAPI serves extensionless local page URLs with the SPA index; asset-like and reserved paths remain real 404s. Unknown page routes render an honest page-not-found view. Vercel serves the hosted SPA. The same source produces both builds without relative-asset ambiguity on deep reload.

Public content is deliberately divided:

| Route | Purpose |
| --- | --- |
| `/` | Product story, original orbital illustration, capability/journey sections and optional spatial artifact viewer |
| `/about` | Purpose, audience, open-source principles and current stage |
| `/what-we-do` | Detailed Start New/Evolve journeys, deliverables and boundaries |
| `/sign-in` | Real hosted identity setup, or a clear local-identity explanation |
| `/workspace` | Choose and do work, not another marketing page |
| `/workspace/new`, `/workspace/evolve` | Brief, Local run and contextual Demo Studio |
| `/workspace/projects` | Persisted briefs, explicit project roles, invitations and membership administration |
| `/workspace/settings`, `/workspace/chats`, `/workspace/activity` | Existing workspace functionality with actual URLs |

Journey tabs use `?tab=brief|local|demo`; unknown tab values show an explicit error. Radix tabs use manual activation: arrow keys move focus, Enter/Space activate. This avoids duplicate history entries from simultaneous pointer/focus activation. There is no global Demo Studio navigation option.

## Tokens and typography

| Token | Value | Role |
| --- | --- | --- |
| Canvas | `#F7F8FC` | Off-white page |
| Ink | `#151923` | Headings and technical surfaces |
| Muted | `#5F6676` | Readable secondary text |
| Signal | `#385CE3` | Primary actions and selected states |
| Border | `#E1E5EC` | Quiet dividers |
| Product rail | `#11151F` | Dark workspace navigation |

Geist Variable 5.3.0 is bundled locally, with a Latin WOFF2 preload and platform fallbacks. No third-party font server is contacted. The complete font notice ships at `public/geist-license.txt`. Body copy is 16px; product text is generally 13–14px, with larger labelled mobile inputs. Solid panels, semantic status colors and readable secondary text take precedence over translucent effects.

`index.css` owns shared foundations; `pages.css` owns public/chrome/sign-in presentation; `workspace.css` is imported by the lazy Workspace module. Base element resets stay in Tailwind's base layer so they cannot override component text colors or input sizes. Shared gutters, wrapping content, 44px coarse-pointer targets, visible focus and native scrolling apply throughout.

## Dimensional composition and motion

`SiteArt` paints the original orbital hero, journey marks, principle illustrations and planned-delivery rail as SVG/HTML. Small positional entrances keep text at full contrast; observer-dependent transforms are armed only when an observer exists. The hero's two slow orbital traces respect reduced motion. No page-wide animation runtime or loading-screen introduction is shipped.

`ProductScene` initially renders a readable semantic document. Its native chapter buttons select **Project brief**, **Code review** and **Demo script**. **Open spatial view** explicitly imports Three.js 0.180.0; the initial public load does not request that chunk. Original beveled document geometry, canvas textures, perspective and shadows explain the same example content, never live execution.

The spatial viewer has Pause/Resume and Close controls. Paused chapter and resize changes repaint once without interpolation or a continuing loop. Closing restores keyboard focus to the opener. Rendering is demand-driven and stops offscreen or in a hidden document; DPR is capped at 1.5. Teardown removes listeners and observers and disposes geometry, materials, textures, shadows, renderer and context.

Motion is implemented with CSS and browser APIs; the previous `motion` dependency and unused Card primitive have been removed. Run indicators still reflect actual engine state. No fabricated completion, percentage, ETA or private reasoning is animated into existence.

## Accessibility and React state

Reduced motion is a live `useSyncExternalStore` media-query subscription. Enabling it removes an open WebGL scene and displays the selected semantic artifact; disabling it restores only a view the visitor had already explicitly opened. The chapter controls remain usable. Unavailable WebGL, context loss and load errors preserve readable content. The static stage grows with its document rather than clipping it to a fixed canvas height. Public and product transitions respect the preference without requiring a reload.

Effects synchronize external systems only: Supabase/network subscriptions with stale-response guards, browser title/focus/scroll, real engine polling, renderer/observer lifetime and renderer control updates. Pathnames, tabs, breadcrumbs, active workspaces and draft lookup are derived during render. Navigation and mutations happen in handlers. Keyed identity trees reset owner data without chains of state-synchronizing Effects. Mobile menu state resets by route key and closes explicitly on selection/Escape; Escape returns focus to its trigger. Route presentation waits for lazy content before moving focus.

Workspace drafts, settings edits, selected context and unsent chat composition live above the route switch, so internal navigation does not discard them. Local anonymous brief/story edits survive the first explicit local sign-in. Local sign-out or identity change clears the owner tree; hosted identity changes do likewise. Nothing persists those drafts across a full reload. Hosted accounts may freely visit public pages without an automatic workspace redirect. `/sign-in` is the UI entry page; email/provider callbacks retain the established hosted root URL. Home restores the verified session and Workspace remains available through shared navigation, with no provider-configuration migration.

## A workspace for the current task

The dark navigation rail identifies the active context and keeps product routes distinct. Overview derives **Continue your work** from the current owner's actual drafts and selected local projects, never invented history or timestamps. Start New/Evolve cards retain a single keyboard target and proper heading semantics. Forms, record lists, invitations, memberships, messages, empty states, errors and execution receipts share the same restrained panel system.

Journey headings are compact and retain Start New/Evolve as distinct workflow names. A named brief appears as context rather than another hero. Brief, Local run and contextual Demo Studio remain accessible query-string tabs; no route, export or identity contract changes.

The local workbench leads with the selected source snapshot and its real file count, analysis and ZIP actions. The main column contains recorded progress and the latest project findings. Run selection and the worker boundary sit in a secondary control column; **Create another starter / Import another snapshot** is a native disclosure, not a permanently expanded card above the work. Without a selected project, setup is immediately available. Mobile stacks these controls without hiding actions. The newly available manifest-derived repository technology profile remains intact.

The selected historical run and latest project analysis remain explicitly distinct. No status, percentage, finding, elapsed time or task completion is derived from the illustration.

## Product contracts preserved

Hosted Supabase workspaces and private human chats stay separate from self-hosted same-origin cookie/CSRF APIs. Local sessions are never forwarded. Legacy `/` remains intentionally supported but is not the React Home destination.

Start New retains deterministic starter creation and ZIP export. Evolve retains authorized ZIP import and read-only static analysis. Both retain cancel/results, owner-bound project/run selections, contextual brief/story exports and editable drafts. Imported code is not executed. Static findings do not prove correctness/security or apply changes. Storyboard exports remain `storyboard_only_not_rendered` and `verified: false` with their exact journey/brief/project context.

Persisted queued/running/succeeded/failed/canceled states, event records, stale/disconnected behavior, user-opened details and the single elapsed label remain real engine data. A selected old run is not confused with the latest project findings. Hosted coding, automatic patches and deployments remain unavailable. Any capability sentence on any surface names its edition — hosted, self-hosted or planned; an unqualified capability claim is a defect, not a style choice.

## Browser evidence

Current media records the compiled implementation, not customer usage:

- [Desktop Home](media/studio-landing.png) and [mobile Home](media/studio-mobile.png).
- [Spatial artifact view](media/studio-story.png), explicitly illustrative and shown paused.
- [Workspace](media/studio-workspace.png), with an actually authored in-memory verification draft.
- [Short browser recording](media/studio-navigation.webm) of Home and the spatial interaction, plus a [current UI contact sheet](media/studio-motion-contact.png) assembled from actual screenshots.
- [Real local analysis](media/studio-local-run.png), completed by a one-off worker against an isolated synthetic source snapshot.

Verification includes actual hosted/self-hosted browser navigation, draft/export flows, paused canvas updates, live reduced-motion teardown and close-focus restoration; real local Supabase email/PKCE, project/session authorization and all eight collaboration ordering cases; and 48 public/guest route/viewport checks at 1440, 768, 390 and 320px with no overflow or violations in the selected axe-core WCAG A/AA rules. This is not a full accessibility certification or a physical-device test.

Initial Home JavaScript measured through the browser is 438,846 decoded bytes versus the previous deployed page's 1,058,449 (58.5% less). Public pages render with the entry module rather than briefly showing a footer beneath a loading placeholder; controlled desktop/mobile checks recorded zero Home layout shift after this change. The optional Three.js chunk is still large and its build advisory remains visible; it is absent from initial requests. Sign-in/auth code and storyboard data are deferred, product CSS is route-loaded, and font assets are self-hosted. Lab timing comparisons belong in release evidence; no field INP or availability claim is inferred from a build.

## Agent chat direction

The next chat iteration keeps the existing shadcn/Radix foundation: a compact project/session sidebar, readable conversation and optional task/file/diff/evidence inspector. On mobile, secondary panes become sheets and the composer stays keyboard-safe.

Use stable message/run IDs, concise decision summaries, real agent todos, grouped tool results, source links, exact-artifact approvals and clear cancellation/error/reconnect states. Summary blocks are not raw private model reasoning. No invented percentages, task completion or background execution claims may be rendered.

Premium means consistent spacing/typography, restrained color, safe Markdown, accessible focus/contrast, reduced motion and stable scroll while streaming—not more decorative animation or duplicate status panels. These are roadmap requirements; the current private conversations store human messages and do not run an AI agent.
