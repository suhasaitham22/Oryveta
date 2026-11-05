import React from "react";

/* Original Oryveta artwork. Everything here is plain SVG drawn with the shared
   design tokens, so the first paint of a public page needs no renderer, no
   image download and no animation library. The home page leads with a real
   stored result instead of decorative art, so only these small marks remain. */

/* Journey marks: one isometric plate each, with the motion of that journey. */
export function JourneyMark({ variant }) {
  return (
    <svg
      className="journey-mark"
      viewBox="0 0 72 72"
      aria-hidden="true"
      focusable="false"
    >
      <polygon
        points="36,46 8,56 36,66 64,56"
        fill="var(--accent-soft, #e6ebfd)"
        stroke="var(--border)"
        strokeWidth="1.2"
      />
      {variant === "evolve" ? (
        <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M22 44V26a8 8 0 0 1 8-8h12" />
          <path d="M50 44V32a8 8 0 0 0-8-8" strokeDasharray="3 5" />
          <path d="M36 42V14" strokeOpacity=".35" />
          <circle cx="22" cy="20" r="4.5" fill="var(--surface, #fff)" />
          <circle cx="50" cy="20" r="4.5" fill="var(--accent)" stroke="var(--accent)" />
        </g>
      ) : (
        <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M36 42V16" />
          <path d="M26 26l10-10 10 10" />
          <path d="M18 38h8M46 38h8" strokeOpacity=".35" />
          <circle cx="36" cy="14" r="5" fill="var(--accent)" stroke="var(--accent)" />
        </g>
      )}
    </svg>
  );
}

const PRINCIPLE_MARKS = [
  /* Open lattice: a readable structure with one side deliberately left open. */
  <g key="open" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M10 10h20M10 10v20M38 10h-8M10 38v-8" />
    <path d="M38 38H18M38 38V18" strokeOpacity=".4" strokeDasharray="3 5" />
    <circle cx="24" cy="24" r="7" fill="var(--accent-soft, #e6ebfd)" stroke="var(--accent)" />
    <circle cx="24" cy="24" r="2.4" fill="var(--accent)" stroke="none" />
  </g>,
  /* Aperture: concentric shutters closing around a single private core. */
  <g key="private" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M24 6a18 18 0 0 1 15.6 9" />
    <path d="M39.6 33A18 18 0 0 1 8.4 33" />
    <path d="M8.4 15A18 18 0 0 1 24 6" strokeOpacity=".4" />
    <circle cx="24" cy="24" r="9" stroke="var(--accent)" fill="var(--accent-soft, #e6ebfd)" />
    <path d="M24 19v10" stroke="var(--accent)" />
  </g>,
  /* Ledger: rows you can read back, one of them carrying a result. */
  <g key="inspect" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M9 12h30M9 22h18M9 32h12" />
    <rect
      x="26"
      y="26"
      width="14"
      height="14"
      rx="3"
      fill="var(--accent-soft, #e6ebfd)"
      stroke="var(--accent)"
    />
    <path d="M29.5 33l3 3 5-6" stroke="var(--accent)" />
  </g>,
];

export function PrincipleMark({ index }) {
  return (
    <svg
      className="principle-mark"
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
    >
      {PRINCIPLE_MARKS[index]}
    </svg>
  );
}

/* 404 fragment: the same orbit, interrupted. */
export function LostOrbit() {
  return (
    <svg
      className="lost-orbit"
      viewBox="0 0 320 200"
      aria-hidden="true"
      focusable="false"
    >
      <ellipse
        cx="160"
        cy="108"
        rx="140"
        ry="56"
        fill="none"
        stroke="var(--border)"
        strokeWidth="1"
      />
      <ellipse
        cx="160"
        cy="108"
        rx="92"
        ry="37"
        fill="none"
        stroke="var(--accent-soft, #e6ebfd)"
        strokeWidth="1.5"
        strokeDasharray="3 8"
      />
      <polygon
        points="160,112 104,134 160,156 216,134"
        fill="var(--surface, #fff)"
        stroke="var(--border)"
        strokeWidth="1"
      />
      <path
        d="M160 108a140 56 0 0 1 140 0"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="22 14"
        opacity=".55"
      />
      <circle cx="252" cy="62" r="6" fill="var(--accent)" />
      <circle cx="68" cy="152" r="4" fill="var(--muted)" opacity=".4" />
    </svg>
  );
}

/* Delivery rail: hosted steps are solid, local steps ringed, planned hollow. */
const STAGE_STATES = {
  available: "Hosted now",
  local: "Local only",
  planned: "Planned",
};
export function StageRail({ stages }) {
  return (
    <ol className="stage-rail">
      {stages.map(({ title, state, detail }) => (
        <li key={title} className={`stage-rail-item stage-${state}`}>
          <span className="stage-rail-dot" aria-hidden="true" />
          <strong>{title}</strong>
          <span className="stage-rail-state">
            {STAGE_STATES[state] || STAGE_STATES.planned}
          </span>
          <p>{detail}</p>
        </li>
      ))}
    </ol>
  );
}
