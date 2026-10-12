# Demo-by-default product standard

Every feature, story or customer-facing change must ship with a concise storyboard in `apps/web/studio/public/demo-stories.json`. Each entry contains `id`, `title`, `description`, `state` and at least three `scenes` with `eyebrow`, `headline`, `body` and `receipt`.

## Demo contract
1. **Describe the customer problem and the actual implemented capability.** Never narrate an unimplemented feature as deployed.
2. **Show a visible before/after or engineering flow** with at least three clear beats.
3. **Record proof**: functional test, screenshot, actual capture, build run ID, commit, limitations and known gaps.
4. **Review demo claim quality** alongside CI; fail when a story is missing or makes fabricated claims.
5. **Produce video** through `apps/web/studio/demo`: actual vendored snapcn text-reveal + Remotion compositions. `npm run render:<story>` creates a video locally. Add device frames, real captures or further snapcn registry components as needed. These assets cannot replace feature tests or human sign-off.

The browser Demo Studio is a functioning editable **storyboard preview**, not video generation. Its JSON export preserves scenes and labels `verified: false`. An automated build/publishing agent should treat `state=storyboard` as an approval gate, not a green launch.

## Agent integration
The offline agent's evidence gate (`oryveta_engine.learning`) remains fail-closed. Use the same task IDs and outcome receipts to create a demo script after verification; never promote unreviewed candidate behavior. Feed approved receipts into story captions and version each demo with code/feature revision.

See [snapcn installation](https://snapcn.dev/docs/getting-started/installation) and [product demo skill](https://snapcn.dev/docs/getting-started/agent-skill). The initial shipped compositions cover Start New, Evolve, and Agent Evaluation. Add a scenario for **every** new shipped feature, never just the homepage.
