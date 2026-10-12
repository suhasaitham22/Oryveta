# Studio design attribution

## ShadcnStore dashboard + landing template

The React landing page refines the **Vite version** of [ShadcnStore's shadcn-dashboard-landing-template](https://github.com/shadcnstore/shadcn-dashboard-landing-template), an MIT-licensed React/shadcn template. The source was pinned at **`953300fa5176608a9d682943edfc359ce809f2c7`**. GitHub repository metadata reported the project unarchived and last pushed on 2026-10-09 when selected on 2026-10-12.

Source-to-adaptation map:

- [`vite-version/src/app/landing/components/hero-section.tsx`](https://github.com/shadcnstore/shadcn-dashboard-landing-template/blob/953300fa5176608a9d682943edfc359ce809f2c7/vite-version/src/app/landing/components/hero-section.tsx) → `src/pages/Landing.jsx` / `HeroSection`: centered announcement badge, responsive headline and paired actions, constrained hero container, and bordered product-visual frame. Oryveta replaces the stock dashboard image/play overlay with an explicitly illustrative brief/evidence/story workspace.
- [`vite-version/src/app/landing/components/features-section.tsx`](https://github.com/shadcnstore/shadcn-dashboard-landing-template/blob/953300fa5176608a9d682943edfc359ce809f2c7/vite-version/src/app/landing/components/features-section.tsx) → `Landing.jsx` / `FeaturesSection`: section intro, alternating two-column feature layouts, mapped icon lists and responsive action groups. Product tasks replace marketplace claims.
- [`vite-version/src/app/landing/components/navbar.tsx`](https://github.com/shadcnstore/shadcn-dashboard-landing-template/blob/953300fa5176608a9d682943edfc359ce809f2c7/vite-version/src/app/landing/components/navbar.tsx) → `Landing.jsx` header: sticky bordered navigation, desktop links/actions and separate mobile navigation. Oryveta uses native anchor behavior and a disclosure instead of the template's marketplace mega-menu, theme switcher and sheet dependencies.

The full upstream notice also ships as `public/template-license.txt`; the landing footer links to this built artifact, so attribution remains available with the distributed site.

The adaptation uses Oryveta's existing React, Tailwind, Radix/shadcn primitives and Lucide installation. It does not copy the template's authentication backend, sample metrics, testimonials, stock imagery, paid marketplace assets, or pricing. Soft Modern tokens, scroll chapters, contextual journey editor and engine consumer are Oryveta-specific. There is no new framework/runtime dependency and no vendored unused template application.

### Upstream license (verbatim)

Source: [`License.md`](https://github.com/shadcnstore/shadcn-dashboard-landing-template/blob/953300fa5176608a9d682943edfc359ce809f2c7/License.md)

```text
MIT License

Copyright (c) 2025 ShadcnStore

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Existing components

The studio continues to use existing shadcn-style Radix primitives and Lucide icons; their package licenses remain applicable. The independent Remotion/snapcn rendering package retains its own [third-party notices](demo/THIRD_PARTY.md). Storyboard JSON is not a rendered video, and template styling is not evidence of product execution.
