# Studio design attribution

## Original visual composition and public references

The current orbital studio composition and dimensional product scene are original Oryveta work. Public references reviewed on 2026-10-29 were [Antigravity](https://antigravity.google/), [Lunon](https://lunon.ai/), [Linear](https://linear.app/) and [Raycast](https://www.raycast.com/): editorial hierarchy, cinematic composition, precise product surfaces and purposeful interaction. Antigravity, Lunon and Linear were inspected in Chromium. Earlier Galileo/template references informed a superseded iteration, not the current palette.

No reference-site source, images, videos, models, logos, copy, customer claims or paid assets are included. The orbital hero and supporting SVGs are original; the optional Three.js scene uses original geometry and canvas-drawn documents. Native scrolling and readable static content remain available. No animation framework, scroll hijacking or reference-site hydration code is imported.

## Historical ShadcnStore adaptation

The preceding landing implementation adapted the MIT-licensed **Vite version** of [ShadcnStore's shadcn-dashboard-landing-template](https://github.com/shadcnstore/shadcn-dashboard-landing-template), pinned at **`953300fa5176608a9d682943edfc359ce809f2c7`**. Its notice is retained through this redesign.

Honest source-to-current mapping:

- `vite-version/src/app/landing/components/hero-section.tsx`: the earlier centered badge/paired-action/bordered-product-frame adaptation has been replaced by `PublicPages.jsx`, `ProductScene.jsx` and original `ThreeScene.jsx` geometry.
- `vite-version/src/app/landing/components/features-section.tsx`: the earlier feature-grid adaptation has been replaced by distinct About and What We Do route content.
- `vite-version/src/app/landing/components/navbar.tsx`: the earlier responsive-navigation concept is now a compact shared React Router header with native links and keyboard-operable disclosure. No upstream mega-menu, theme switcher or backend is imported.

The full upstream notice ships in `public/template-license.txt`, linked from the site footer. No unused template application is vendored. React, Vite, Tailwind, Radix/shadcn primitives and Lucide remain the existing framework/component stack.

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

## Historical Motion notice

The previous DOM animation dependency `motion` 14.1.0 has been removed. Current entrances and state transitions use CSS/browser APIs. Its historical MIT notice is retained below and in `public/template-license.txt`; it is not a current runtime dependency.

```text
The MIT License (MIT)

Copyright (c) 2024 [Motion](https://motion.dev) B.V.

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

## Three.js and React Router

`three` **0.180.0**, MIT ([source](https://github.com/mrdoob/three.js)), renders original rounded extruded document panels with lit beveled edges, canvas-textured faces and shadows. `productArtifacts.js` supplies the same original example content to textures and semantic documents. No third-party models, images, shaders or 3D framework are vendored. The renderer is imported only after **Open spatial view**; initial pages and reduced-motion visitors use the semantic presentation. Frames stop when paused, settled, offscreen or hidden. Paused selections/resize repaint once; cleanup disposes renderer resources and context.

`react-router-dom` / `react-router` **7.9.4**, MIT ([source](https://github.com/remix-run/react-router)), supply browser-owned route/query history and basename handling. Their complete MIT notices and the Three.js notice are included in `public/template-license.txt` alongside the historical template and Motion notices. Installed package license files were the attribution source.

## Self-hosted typography

`@fontsource-variable/geist` **5.3.0** supplies Geist Variable WOFF2 assets under **OFL-1.1**. Copyright 2024 The Geist Project Authors ([source](https://github.com/vercel/geist-font)). The font is not modified and is served from the application's own origin. The complete installed-package copyright and license are included in `public/geist-license.txt`, linked from the footer.

## Existing components

The studio continues to use existing shadcn-style Radix primitives and Lucide icons; their package licenses remain applicable. The independent Remotion/snapcn rendering package retains its own [third-party notices](demo/THIRD_PARTY.md). Storyboard JSON is not a rendered video, and template styling is not evidence of product execution.
