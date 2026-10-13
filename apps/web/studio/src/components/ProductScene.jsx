import React, { Component, lazy, Suspense, useCallback, useState } from "react";
import { FileText, Code2, Clapperboard, Layers3 } from "lucide-react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { productArtifacts } from "./productArtifacts";

const ThreeScene = lazy(() => import("./ThreeScene.jsx"));
const icons = [FileText, Code2, Clapperboard];

function ArtifactDocument({ artifact }) {
  return (
    <article className="artifact-document">
      <div className="artifact-document-bar"><span />{artifact.file}</div>
      <div className="artifact-document-body">
        <span className="section-label">{artifact.label}</span>
        <h2>{artifact.heading}</h2>
        <span className="artifact-document-tag">{artifact.tag}</span>
        <dl>
          {artifact.rows.map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      </div>
      <p className="artifact-document-footer">{artifact.footer}</p>
    </article>
  );
}

function StaticScene({ reason, selected }) {
  return (
    <div className={`scene-alternative artifact-${selected}`}>
      <p>{reason} — visual alternative</p>
      <ArtifactDocument artifact={productArtifacts[selected]} />
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
      <StaticScene reason="3D unavailable" selected={this.props.selected} />
    ) : this.props.children;
  }
}

export default function ProductScene() {
  const reduced = useReducedMotion();
  const [selected, setSelected] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  const reportUnavailable = useCallback(() => setUnavailable(true), []);
  const chapter = productArtifacts[selected];
  return (
    <section className="product-scene" aria-label="Illustrative product scene">
      <div className="scene-meta">
        <span><Layers3 size={15} /> Inside the workspace</span>
        <span>Example · not a live run</span>
      </div>
      <div className="scene-viewport">
        {reduced || unavailable ? (
          <StaticScene reason={reduced ? "Reduced motion" : "WebGL unavailable"} selected={selected} />
        ) : (
          <SceneBoundary selected={selected}>
            <Suspense fallback={<StaticScene reason="Loading 3D" selected={selected} />}>
              <ThreeScene selected={selected} onUnavailable={reportUnavailable} />
              <div className="sr-only"><ArtifactDocument artifact={chapter} /></div>
            </Suspense>
          </SceneBoundary>
        )}
      </div>
      <div className="scene-controls" role="group" aria-label="Scene viewpoints">
        {productArtifacts.map(({ title, label }, index) => {
          const Icon = icons[index];
          return (
            <button key={title} onClick={() => setSelected(index)} aria-pressed={selected === index} aria-describedby="scene-description">
              <Icon size={16} />
              <span>{title}</span>
              <small aria-hidden="true">{label.slice(0, 2)}</small>
            </button>
          );
        })}
      </div>
      <div className="scene-caption" aria-live="polite">
        <p id="scene-description">{chapter.text}</p>
      </div>
    </section>
  );
}
