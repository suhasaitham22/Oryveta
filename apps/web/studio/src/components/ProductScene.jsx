import React, { Component, lazy, Suspense, useCallback, useState } from "react";
import { FileText, Code2, Clapperboard, Rotate3D } from "lucide-react";
import { useReducedMotion } from "@/lib/useReducedMotion";

const ThreeScene = lazy(() => import("./ThreeScene.jsx"));
const chapters = [
  {
    title: "The brief",
    icon: FileText,
    label: "01 / Intent",
    text: "Name the customer task. Keep the outcome and constraints together.",
  },
  {
    title: "The evidence",
    icon: Code2,
    label: "02 / Source",
    text: "Inspect source locally. Keep findings separate from claims of correctness.",
  },
  {
    title: "The handoff",
    icon: Clapperboard,
    label: "03 / Story",
    text: "Explain what exists, what is unverified, and what comes next.",
  },
];
function StaticScene({ reason }) {
  return (
    <div className="scene-alternative">
      <p>{reason} — visual alternative</p>
      <div className="static-artifacts" aria-hidden="true">
        <div>
          <Code2 />
          <span>Source</span>
          <i />
          <i />
          <i />
        </div>
        <div>
          <FileText />
          <span>Brief</span>
          <i />
          <i />
          <i />
        </div>
        <div>
          <Clapperboard />
          <span>Story</span>
          <i />
          <i />
          <i />
        </div>
      </div>
    </div>
  );
}
class SceneBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <StaticScene reason="3D unavailable" />
    ) : (
      this.props.children
    );
  }
}
export default function ProductScene() {
  const reduced = useReducedMotion();
  const [selected, setSelected] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  const reportUnavailable = useCallback(() => setUnavailable(true), []);
  const chapter = chapters[selected];
  return (
    <section className="product-scene" aria-label="Illustrative product scene">
      <div className="scene-meta">
        <span>
          <Rotate3D size={15} /> A little perspective changes everything.
        </span>
        <span>Original illustration · not a running agent</span>
      </div>
      <div className="scene-viewport">
        {reduced || unavailable ? (
          <StaticScene
            reason={reduced ? "Reduced motion" : "WebGL unavailable"}
          />
        ) : (
          <SceneBoundary>
            <Suspense fallback={<StaticScene reason="Loading 3D" />}>
              <ThreeScene
                selected={selected}
                onUnavailable={reportUnavailable}
              />
            </Suspense>
          </SceneBoundary>
        )}
      </div>
      <div className="scene-caption">
        <div>
          <span className="section-label">{chapter.label}</span>
          <p id="scene-description">{chapter.text}</p>
        </div>
        <div
          className="scene-controls"
          role="group"
          aria-label="Scene viewpoints"
        >
          {chapters.map(({ title, icon: Icon }, index) => (
            <button
              key={title}
              onClick={() => setSelected(index)}
              aria-pressed={selected === index}
              aria-describedby="scene-description"
            >
              <Icon size={16} />
              <span>{title}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
