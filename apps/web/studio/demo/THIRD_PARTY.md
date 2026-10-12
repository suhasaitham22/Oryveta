# snapcn in Oryveta Demo Studio

Source: https://github.com/shadcn-labs/snapcn (registry `text-reveal` and `snap-cn-ui`).
Components are copied from snapcn's official **MIT-licensed** shadcn registry, as is customary with shadcn components. Keep attribution and review licenses/dependencies when updating the registry source.

Install after reviewing the pinned dependencies:

```sh
cd apps/web/studio/demo
npm install
npm run check
npm run start
npm run render:start-new
npm run render:evolve
npm run render:agent-evaluation
```

The on-site **Demo Studio** supports edit/preview/export of real storyboards, **not MP4 rendering in the browser**. The Remotion composition uses the vendored `TextReveal` component across each of the three scenarios, exporting an offline video when `@remotion/cli` and a supported renderer are installed. Recorded real workflow evidence, device frames and measurements should be reviewed/attached prior to any public claims. Never substitute scripted scenes for actual feature execution.

Future additions: add more snapcn components with `npx shadcn@latest add @snapcn/<name>` within this directory and review the source diff. Snapcn's video components are not shadcn/ui's interactive app elements.
