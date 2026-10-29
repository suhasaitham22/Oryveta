import React, { Component, lazy, Suspense, useCallback, useRef, useState } from "react";
import { Boxes, Layers3, Pause, Play, X } from "lucide-react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { productArtifacts } from "./productArtifacts";

/* The scene paints as flat CSS/SVG artwork. The WebGL renderer is only fetched
   when a visitor asks for the spatial view, and never under reduced motion, so
   nothing here is downloaded or started for a first paint. */
const ThreeScene = lazy(() => import("./ThreeScene.jsx"));

export function ArtifactDocument({ artifact }) {
  return (
    <article className="artifact-document">
      <div className="artifact-document-bar">
        <span />
        {artifact.file}
      </div>
      <div className="artifact-document-body">
        <span className="section-label">{artifact.label}</span>
        <p className="artifact-document-title">{artifact.heading}</p>
        <span className="artifact-document-tag">{artifact.tag}</span>
        <dl>
          {artifact.rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="artifact-document-footer">{artifact.footer}</p>
    </article>
  );
}

function StaticScene({ selected, note }) {
  return (
    <div className={`scene-alternative artifact-${selected}`}>
      <ArtifactDocument artifact={productArtifacts[selected]} />
      {note && (
        <p className="scene-note" role="status">
          {note}
        </p>
      )}
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
      <StaticScene
        selected={this.props.selected}
        note="The spatial view stopped. The artifact below is the same content."
      />
    ) : (
      this.props.children
    );
  }
}

export default function ProductScene() {
  const reduced = useReducedMotion();
  const [selected, setSelected] = useState(0);
  const [spatial, setSpatial] = useState(false);
  const [paused, setPaused] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const spatialTrigger = useRef(null);
  const reportUnavailable = useCallback(() => {
    setUnavailable(true);
    setSpatial(false);
  }, []);
  const chapter = productArtifacts[selected];
  const showSpatial = spatial && !reduced && !unavailable;
  return (
    <section className="product-scene" aria-label="Illustrative product scene">
      <div className="scene-meta">
        <span>
          <Layers3 size={15} aria-hidden="true" /> Inside the workspace
        </span>
        <span>Example · not a live run</span>
      </div>
      <div className="scene-viewport">
        {showSpatial ? (
          <SceneBoundary selected={selected}>
            <Suspense
              fallback={
                <StaticScene
                  selected={selected}
                  note="Preparing the spatial view…"
                />
              }
            >
              <ThreeScene
                selected={selected}
                paused={paused}
                onUnavailable={reportUnavailable}
              />
              <div className="sr-only">
                <ArtifactDocument artifact={chapter} />
              </div>
            </Suspense>
          </SceneBoundary>
        ) : (
          <StaticScene
            selected={selected}
            note={
              unavailable
                ? "This browser could not start the spatial view. The artifact is unchanged."
                : null
            }
          />
        )}
      </div>
      <div className="scene-rail">
        <div className="scene-controls" role="group" aria-label="Scene viewpoints">
          {productArtifacts.map(({ title, label }, index) => (
            <button
              key={title}
              type="button"
              onClick={() => setSelected(index)}
              aria-pressed={selected === index}
              aria-describedby="scene-description"
            >
              <span className="scene-chapter-index" aria-hidden="true">
                {label.slice(0, 2)}
              </span>
              <span className="scene-chapter-title">{title}</span>
              <span className="scene-chapter-meta" aria-hidden="true">
                {label.split(" / ")[1]}
              </span>
            </button>
          ))}
        </div>
        <div className="scene-footer">
          <div className="scene-caption" aria-live="polite">
            <p id="scene-description">{chapter.text}</p>
          </div>
          {!reduced && !unavailable && (
            <div className="scene-dimension">
              {showSpatial ? (
                <>
                  <button
                    type="button"
                    className="scene-action"
                    aria-pressed={paused}
                    onClick={() => setPaused((value) => !value)}
                  >
                    {paused ? (
                      <Play size={14} aria-hidden="true" />
                    ) : (
                      <Pause size={14} aria-hidden="true" />
                    )}
                    {paused ? "Resume motion" : "Pause motion"}
                  </button>
                  <button
                    type="button"
                    className="scene-action"
                    onClick={() => {
                      setSpatial(false);
                      setPaused(false);
                      requestAnimationFrame(() => spatialTrigger.current?.focus({ preventScroll: true }));
                    }}
                  >
                    <X size={14} aria-hidden="true" />
                    Close spatial view
                  </button>
                </>
              ) : (
                <button
                  ref={spatialTrigger}
                  type="button"
                  className="scene-action scene-action-primary"
                  aria-describedby="scene-dimension-note"
                  onClick={() => setSpatial(true)}
                >
                  <Boxes size={14} aria-hidden="true" />
                  Open spatial view
                  <small aria-hidden="true">loads a 3D renderer</small>
                </button>
              )}
              <p id="scene-dimension-note" className="sr-only">
                Opens an optional three-dimensional view of the same artifacts.
                It downloads a renderer and adds motion you can pause.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
