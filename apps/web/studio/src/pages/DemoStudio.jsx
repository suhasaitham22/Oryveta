import React from "react";
import { motion } from "motion/react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import {
  ArrowLeft,
  ArrowRight,
  Clapperboard,
  Download,
  FilePenLine,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { downloadJson } from "@/lib/download";

// The journey supplies its exact story and owns edits. There is no global/default story.
export default function DemoStudio({
  stories,
  storyId,
  draft,
  onChange,
  context,
}) {
  const reduced = useReducedMotion();
  const story = stories.find((value) => value.id === storyId);
  if (!story)
    return (
      <div className="surface-panel" role="status">
        <h3>This journey's storyboard is unavailable.</h3>
        <p>
          The manifest did not provide a matching story. Your brief is still
          available; no other journey is substituted.
        </p>
      </div>
    );
  const scenes = draft.scenes || story.scenes;
  const frame = Math.min(draft.frame || 0, scenes.length - 1);
  const scene = scenes[frame];
  function editScene(key, value) {
    onChange({
      scenes: scenes.map((item, index) =>
        index === frame ? { ...item, [key]: value } : item,
      ),
    });
  }
  function exportStory() {
    downloadJson(`${story.id}-demo.json`, {
      id: story.id,
      title: story.title,
      description: story.description,
      scenes,
      context,
      source: "oryveta-demo-studio",
      status: "storyboard_only_not_rendered",
      renderPipeline: "Remotion + snapcn",
      verified: false,
    });
  }
  return (
    <section className="demo-root" aria-label={`${story.title} story`}>
      <div className="demo-heading">
        <div>
          <div className="section-label">
            <Clapperboard size={15} /> Demo Studio / {story.title}
          </div>
          <h2>Make the handoff easier to understand.</h2>
          <p>
            {context.title || "Untitled brief"} · Draft scenes stay with this
            journey while you work.
          </p>
        </div>
        <span className="status-tag">Draft · unverified</span>
      </div>
      <div className="storyboard-stage">
        <div className="storyboard-meta">
          <span>{story.title} story</span>
          <span>
            Scene {frame + 1} / {scenes.length}
          </span>
        </div>
        <div aria-live="polite" aria-atomic="true">
          <motion.div
            key={frame}
            className="storyboard-scene"
            initial={reduced ? false : { x: 16 }}
            animate={{ x: 0 }}
            transition={
              reduced
                ? { duration: 0 }
                : { type: "spring", stiffness: 340, damping: 32 }
            }
          >
            <div className="section-label">{scene.eyebrow}</div>
            <h3>{scene.headline}</h3>
            <p>{scene.body}</p>
            <div className="scene-receipt">
              <Info size={17} />
              <span>{scene.receipt}</span>
            </div>
          </motion.div>
        </div>
        <div className="demo-controls">
          <div className="flex items-center gap-2">
            <Button
              size="icon"
              variant="outline"
              disabled={frame === 0}
              onClick={() => onChange({ frame: frame - 1 })}
              aria-label="Previous demo scene"
            >
              <ArrowLeft size={16} />
            </Button>
            <Button
              size="icon"
              variant="outline"
              disabled={frame === scenes.length - 1}
              onClick={() => onChange({ frame: frame + 1 })}
              aria-label="Next demo scene"
            >
              <ArrowRight size={16} />
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onChange({ editing: !draft.editing })}
              aria-expanded={!!draft.editing}
              aria-controls={`${storyId}-scene-editor`}
            >
              <FilePenLine size={15} />
              {draft.editing ? "Close editor" : "Edit script"}
            </Button>
            <Button size="sm" onClick={exportStory}>
              <Download size={15} />
              Export storyboard
            </Button>
          </div>
        </div>
      </div>
      {draft.editing && (
        <div className="demo-editor" id={`${storyId}-scene-editor`}>
          <label className="field-label">
            Headline
            <Input
              maxLength={140}
              value={scene.headline}
              onChange={(event) => editScene("headline", event.target.value)}
            />
          </label>
          <label className="field-label">
            Narration
            <Textarea
              maxLength={700}
              value={scene.body}
              onChange={(event) => editScene("body", event.target.value)}
            />
          </label>
        </div>
      )}
      <p className="fine-print">
        This exports an editable storyboard, not a video or proof of a working
        feature. Edits are retained in this open workspace, not saved to your
        account. MP4 rendering uses the separate Remotion + snapcn pipeline.
      </p>
    </section>
  );
}
