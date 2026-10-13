# Oryveta Studio — clear direction

The primary visual reference remains the public **Galileo** preview: a bright canvas, bold sans-serif hierarchy, yellow primary actions and a product-centered composition. This navigation/interaction redesign replaces the old state-only landing/workspace switch and CSS relief loops with real pages and an original, genuinely rendered 3D product scene.

## Reference synthesis and attribution

Public previews were inspected in Chromium on 2026-10-12:

- [Galileo](https://galileo.shadcn.io): primary light/sculptural composition and yellow action. Supplied rendered HTML identifies its hero as a looping muted video, plus a translated header, word reveals and staggered sticky sections. These informed motion hierarchy, not copied implementation.
- [Reframe](https://reframe.shadcn.io): editorial scale and product artwork carrying the page.
- [Lightbox](https://lightbox.shadcn.io): contrast and process-oriented hierarchy.
- [Solaris](https://solaris.shadcn.io): technical product framing, without fictional execution metrics.
- [Catalogue](https://www.shadcn.io/template) / [Prodexa](https://prodexa.shadcn.io): continuity between marketing and a calmer working interface.

No paid source, template video/models, brands, customer claims, expired countdowns or payment assertions are reused. No Lenis, scroll hijacking, minified Next hydration code or text-selection restrictions are imported. Historical ShadcnStore notices remain; see [THIRD_PARTY.md](../apps/web/studio/THIRD_PARTY.md). All new 3D geometry is original.

## Compact shared navigation

A single shared header exposes **Home / About / What We Do / Workspace**, the Home logo, and the appropriate hosted sign-in action or local-edition label. It does not repeat a giant page title. A separate compact trail offers Back and semantic linked breadcrumbs. Native links support opening a route in a new tab. A direct-entry Back action falls back to Home, which resolves to `/studio/` locally, never the legacy `/` interface.

React Router owns pathname and query history. `BrowserRouter` uses Vite's `BASE_URL` as its basename. Hosted `npm run build` uses `/` and writes `dist`; `npm run build:local` uses `--mode selfhost`, `/studio/`, and a separate `dist-local`. FastAPI serves extensionless local page URLs with the SPA index; asset-like and reserved paths remain real 404s. Unknown page routes render an honest page-not-found view. Vercel serves the hosted SPA. The same source produces both builds without relative-asset ambiguity on deep reload.

Public content is deliberately divided:

| Route | Purpose |
| --- | --- |
| `/` | Short product story, dimensional scene and two entry CTAs |
| `/about` | Purpose, audience, open-source principles and current stage |
| `/what-we-do` | Detailed Start New/Evolve journeys, deliverables and boundaries |
| `/sign-in` | Real hosted identity setup, or a clear local-identity explanation |
| `/workspace` | Choose and do work, not another marketing page |
| `/workspace/new`, `/workspace/evolve` | Brief, Local run and contextual Demo Studio |
| `/workspace/settings`, `/workspace/chats`, `/workspace/activity` | Existing workspace functionality with actual URLs |

Journey tabs use `?tab=brief|local|demo`; unknown tab values show an explicit error. Radix tabs use manual activation: arrow keys move focus, Enter/Space activate. This avoids duplicate history entries from simultaneous pointer/focus activation. There is no global Demo Studio navigation option.

## Tokens and typography

| Token | Value | Role |
| --- | --- | --- |
| Canvas | `#F8F9F6` | Bright neutral page |
| Ink | `#232521` | Headings and technical surfaces |
| Muted | `#58604F` | Readable secondary text |
| Signal | `#F5D84C` | Primary actions |
| Border | `#DCE0D5` | Quiet dividers |

Use the shipped system-font stack: Helvetica Neue, Helvetica, Arial, sans-serif. No external font request or unshipped Inter assumption. Forms are solid and labelled, navigation has visible keyboard focus, and status colors remain semantic rather than decorative success claims.

## Dimensional composition and motion

`ProductScene` is the single accessible scene boundary. Its lazily imported `ThreeScene` uses **Three.js 0.180.0**: three solid artifact panels, raised diagram bars, offset rails and a two-level plinth, with perspective, simple lights, occlusion and cast shadows. There are no image textures, imported models, complex shaders or additional 3D framework.

A finite entrance assembles the panels from visibly displaced positions. Three keyboard-operable viewpoint controls rotate the composition and elevate the selected artifact. Native scroll separates the layers and changes perspective; mouse depth is restrained, and touch scrolling remains native. At least 35% of the scene must intersect before its animation starts. The compact desktop hero puts the panels into the ordinary first viewport rather than finishing their entrance below the fold.

Rendering is demand-driven: frames stop once interpolation settles, when the scene is sufficiently offscreen, or when the document is hidden. Cleanup disconnects observers/listeners, cancels the frame, disposes geometry/materials/renderer, and releases the WebGL context. Route-level lazy loading keeps Three out of direct workspace loads; no bundle-size warning threshold is raised.

**Motion 14.1.0** remains the only DOM animation runtime. Public copy enters through visible translation, not unreadable low-opacity text. The working UI retains quieter hover/press responses and real run-panel layout transitions. No splash, invented completion, percentages, ETAs or private reasoning are animated into existence.

## Accessibility and React state

Reduced motion is a live `useSyncExternalStore` media-query subscription. Enabling it removes the WebGL scene and its resources, displays a labelled static visual alternative, and stops DOM entrance transforms. Disabling it may restore the scene. WebGL unavailability, context loss and lazy-load errors also show an explicitly labelled alternative; no information or navigation depends on a canvas. All scene meaning and controls exist in accessible DOM outside it.

Effects synchronize external systems only: Supabase/network subscriptions with stale-response guards, browser title/focus/scroll, real engine polling, renderer/observer lifetime and renderer control updates. Pathnames, tabs, breadcrumbs, active workspaces and draft lookup are derived during render. Navigation and mutations happen in handlers. Keyed identity trees reset owner data without chains of state-synchronizing Effects. Mobile menu state resets by route key and closes explicitly on selection/Escape; Escape returns focus to its trigger. Route presentation waits for lazy content before moving focus.

Workspace drafts, settings edits, selected context and unsent chat composition live above the route switch, so internal navigation does not discard them. Local anonymous brief/story edits survive the first explicit local sign-in. Local sign-out or identity change clears the owner tree; hosted identity changes do likewise. Nothing persists those drafts across a full reload. Hosted accounts may freely visit public pages without an automatic workspace redirect. Hosted email/provider callbacks return predictably to `/sign-in`, with an explicit Continue action.

## Product contracts preserved

Hosted Supabase workspaces and private human chats stay separate from self-hosted same-origin cookie/CSRF APIs. Local sessions are never forwarded. Legacy `/` remains intentionally supported but is not the React Home destination.

Start New retains deterministic starter creation and ZIP export. Evolve retains authorized ZIP import and read-only static analysis. Both retain cancel/results, owner-bound project/run selections, contextual brief/story exports and editable drafts. Imported code is not executed. Static findings do not prove correctness/security or apply changes. Storyboard exports remain `storyboard_only_not_rendered` and `verified: false` with their exact journey/brief/project context.

Persisted queued/running/succeeded/failed/canceled states, event records, stale/disconnected behavior, user-opened details and the single elapsed label remain real engine data. A selected old run is not confused with the latest project findings. Hosted coding, automatic patches and deployments remain unavailable.

## Browser evidence

Intentional media records the compiled implementation, not customer usage or deployment claims:

- [Desktop Home](media/studio-landing.png) and [mobile Home](media/studio-mobile.png).
- [3D viewpoint](media/studio-story.png), an illustrative product composition.
- [Short browser recording](media/studio-navigation.webm) and [timestamped decoded frames](media/studio-motion-contact.png), showing entrance, viewpoints and actual About/Back navigation.
- [Real local analysis](media/studio-local-run.png), using isolated synthetic source and persisted worker state; not a security certification or performance benchmark.

Record exact verification commands and environment limitations in the PR evidence. Browser screenshots and animation are not proof of live email delivery, OAuth configuration, two-account Supabase authorization or rendered storyboard video.
