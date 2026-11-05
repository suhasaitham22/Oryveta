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

The on-site **Demo Studio** edits/previews/exports storyboards, **not MP4 videos**. `src/Root.tsx` registers a Remotion composition for each story in `../public/demo-stories.json`, using the vendored `TextReveal` component. The source includes the captioned proof/pricing story as well as the product workflows. Run `npx remotion render src/index.ts <story-id> out/<story-id>.mp4` from this directory with the pinned dependencies and a supported local browser. Inspect the rendered frames; an offline storyboard is not footage of working software, a founder video, customer evidence or a YC endorsement. Reviewed workflow evidence and its source/limitations remain separate.

Future additions: add more snapcn components with `npx shadcn@latest add @snapcn/<name>` within this directory and review the source diff. Snapcn's video components are not shadcn/ui's interactive app elements.
