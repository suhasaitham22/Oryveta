import {readFileSync, readdirSync} from "node:fs";
import {resolve, join} from "node:path";

const base = resolve(import.meta.dirname, "..");
const stories = JSON.parse(readFileSync(join(base, "public/demo-stories.json"), "utf8"));
if (!Array.isArray(stories) || stories.length === 0) throw new Error("The storyboard manifest must contain stories.");
const ids = new Set();
const requiredText = (value) => typeof value === "string" && value.trim().length > 0;
for (const story of stories) {
  if (!requiredText(story.id) || !/^[a-z][a-z0-9-]*$/.test(story.id) || ids.has(story.id)) {
    throw new Error("Story IDs must be unique, nonempty Remotion composition identifiers.");
  }
  ids.add(story.id);
  if (!["title", "description"].every(key => requiredText(story[key])) || !Number.isInteger(story.version) || story.version < 1) {
    throw new Error(`Invalid story metadata: ${story.id}`);
  }
  if (!["storyboard", "complete"].includes(story.state) || !Array.isArray(story.scenes) || story.scenes.length < 3) {
    throw new Error(`Every story needs a known state and at least three scenes: ${story.id}`);
  }
  for (const [index, scene] of story.scenes.entries()) {
    if (!["eyebrow", "headline", "body", "receipt"].every(key => requiredText(scene[key]))) {
      throw new Error(`Scene ${index + 1} needs narration and a proof/limitation receipt: ${story.id}`);
    }
  }
  if (story.state === "complete" && (!Array.isArray(story.evidence) || story.evidence.length === 0 || !story.evidence.every(requiredText))) {
    throw new Error(`Completed stories require a nonempty list of evidence references: ${story.id}`);
  }
}

// A narrow credential check, not a general security audit or an auth-config assertion.
function scan(directory) {
  for (const entry of readdirSync(directory, {withFileTypes: true})) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {scan(path); continue;}
    if (!/\.(jsx?|tsx?|json|html)$/.test(entry.name)) continue;
    const text = readFileSync(path, "utf8");
    if (/\bsb_secret_[A-Za-z0-9_-]{20,}/.test(text)) throw new Error(`Privileged Supabase credential in browser source: ${path}`);
    for (const match of text.matchAll(/\beyJ[A-Za-z0-9_-]+\.([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]+/g)) {
      let payload;
      try {payload = JSON.parse(Buffer.from(match[1], "base64url").toString("utf8"));} catch {continue;}
      if (payload.role === "service_role") throw new Error(`Service-role JWT in browser source: ${path}`);
    }
  }
}
scan(join(base, "src"));
scan(join(base, "public"));
console.log(`Validated ${stories.length} story schemas, scene receipts and completion evidence references; no recognized privileged Supabase credentials in browser source.`);
