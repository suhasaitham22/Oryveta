# Studio design attribution

## Original visual composition and public references

The current page composition and dimensional product scene are original Oryveta work. The primary inspiration is the public [Galileo preview](https://galileo.shadcn.io): bright sculptural materiality, centered sans-serif hierarchy, yellow action and large product imagery. Supporting public references are [Reframe](https://reframe.shadcn.io) (editorial/product-art scale), [Lightbox](https://lightbox.shadcn.io) (contrast/process hierarchy), [Solaris](https://solaris.shadcn.io) (technical product framing), and the [catalogue](https://www.shadcn.io/template)/[Prodexa](https://prodexa.shadcn.io) (marketing-to-workspace continuity). All were viewed as public previews on 2026-10-12.

No source, images, sphere/ribbon geometry, brand marks, marketing copy, customer claims or paid assets from these templates are included. Supplied Galileo HTML shows its hero using a looping muted video, translated header/word reveals and staggered sticky compositions. Those observations informed choreography, not implementation reuse: Oryveta uses its own live Three.js geometry, native scroll, semantic links and accessible visual alternatives. No video, minified Next hydration code, Lenis, expired countdown, payment claims or template assets were copied.

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

## Motion

`motion` **14.1.0** is pinned with the npm dependency lock. Registry metadata and the installed package's `LICENSE.md` identify it as MIT. Source: [motiondivision/motion](https://github.com/motiondivision/motion), documentation: [motion.dev](https://motion.dev). It remains the sole DOM animation runtime: translated page entrances and actual run-panel layout. Text retains full contrast before entrance. A shared live reduced-motion subscription supplements the library's mount-time preference snapshot.

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

`three` **0.180.0**, MIT ([source](https://github.com/mrdoob/three.js)), renders original box-based artifact panels, rails and a plinth with simple lights and shadows. No third-party models, textures, shaders or 3D framework are vendored. It is imported only through the lazy Home scene; frames are scheduled on demand and stop offscreen/hidden. Cleanup disposes geometry, materials, renderer and WebGL context.

`react-router-dom` / `react-router` **7.9.4**, MIT ([source](https://github.com/remix-run/react-router)), supply browser-owned route/query history and basename handling. Their complete MIT notices and the Three.js notice are included in `public/template-license.txt` alongside the historical template and Motion notices. Installed package license files were the attribution source.



## Existing components

The studio continues to use existing shadcn-style Radix primitives and Lucide icons; their package licenses remain applicable. The independent Remotion/snapcn rendering package retains its own [third-party notices](demo/THIRD_PARTY.md). Storyboard JSON is not a rendered video, and template styling is not evidence of product execution.
