# Studio design attribution

## Original visual composition and public references

The current landing artwork, responsive composition and scroll transforms are original Oryveta work. The primary inspiration is the public [Galileo preview](https://galileo.shadcn.io): bright sculptural materiality, centered sans-serif hierarchy, yellow action and large product imagery. Supporting public references are [Reframe](https://reframe.shadcn.io) (editorial/product-art scale), [Lightbox](https://lightbox.shadcn.io) (contrast/process hierarchy), [Solaris](https://solaris.shadcn.io) (technical product framing), and the [catalogue](https://www.shadcn.io/template)/[Prodexa](https://prodexa.shadcn.io) (marketing-to-workspace continuity). All were viewed as public previews on 2026-10-12.

No source, images, sphere/ribbon geometry, brand marks, marketing copy, customer claims or paid assets from these templates are included. Their licenses were not assumed from catalogue metadata. Preview Download/Get PRO bars are not reproduced. Reference observation does not establish or copy their motion implementations.

## Historical ShadcnStore adaptation

The preceding landing implementation adapted the MIT-licensed **Vite version** of [ShadcnStore's shadcn-dashboard-landing-template](https://github.com/shadcnstore/shadcn-dashboard-landing-template), pinned at **`953300fa5176608a9d682943edfc359ce809f2c7`**. Its notice is retained through this redesign.

Honest source-to-current mapping:

- `vite-version/src/app/landing/components/hero-section.tsx`: the earlier centered badge/paired-action/bordered-product-frame adaptation has been replaced by the original product composition in `Landing.jsx` / `HeroSection`.
- `vite-version/src/app/landing/components/features-section.tsx`: earlier alternating feature-grid adaptation is replaced by the original open use-case spread in `FeaturesSection`.
- `vite-version/src/app/landing/components/navbar.tsx`: the earlier responsive navigation adaptation is retained conceptually as native links and a keyboard-operable mobile disclosure, restyled with the current tokens. No upstream mega-menu, theme switcher or backend is imported.

The full upstream notice also ships in `public/template-license.txt`, linked from the landing footer. No unused template application is vendored. React, Vite, Tailwind, Radix/shadcn primitives and Lucide remain the existing framework/component stack.

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

`motion` **14.1.0** is pinned with the npm dependency lock. Registry metadata and the installed package's `LICENSE.md` identify it as MIT. Source: [motiondivision/motion](https://github.com/motiondivision/motion), documentation: [motion.dev](https://motion.dev). Used only for scroll-linked transforms, brief spring entrances, contextual scene transitions and actual run-panel layout. A shared live reduced-motion preference hook supplements the library's mount-time preference snapshot. No WebGL, shader or second animation library is added.

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


## Existing components

The studio continues to use existing shadcn-style Radix primitives and Lucide icons; their package licenses remain applicable. The independent Remotion/snapcn rendering package retains its own [third-party notices](demo/THIRD_PARTY.md). Storyboard JSON is not a rendered video, and template styling is not evidence of product execution.
