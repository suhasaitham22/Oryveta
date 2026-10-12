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


## Agent-to-demo generation (offline, review gated)

Oryveta's deterministic evaluator now provides a `story_from_evidence()` bridge to a
three-scene storyboard. Its input is the same paired task evidence used by the
self-improvement gate; its output includes the evidence digest, pass counts,
limitations, and an explicitly **unverified** status. Rejected experiments produce
rejection-labelled demos, not victory stories. No source repository or model output
can change a demo to verified without human review.

Create a standalone candidate story from a JSON evidence file:

```bash
python scripts/generate_demo_story.py outcomes.json \
  --id example-feature --title "Example feature" \
  --problem "A problem with a measurable outcome." \
  --capability "Implemented local capability and its scope." \
  --limitations "No deployed customer validation." \
  --output /tmp/example-feature.json
```

Review the generated scenes and the associated tests, add an approved entry to
`apps/web/studio/public/demo-stories.json`, and include real captures where
appropriate. The Remotion root registers story IDs dynamically; a reviewer can
render `npx remotion render src/index.ts example-feature out/example-feature.mp4`
inside the demo package after assets are reviewed. Rendering remains a local,
explicit action; this module is **not** a cloud worker or a continually running agent.
