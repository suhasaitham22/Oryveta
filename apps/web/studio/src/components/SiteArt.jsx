import React from "react";

/* Original Oryveta artwork. Everything here is plain SVG drawn with the shared
   design tokens, so the first paint of a public page needs no renderer, no
   image download and no animation library. The only motion is a CSS dash
   traveling along an orbit path; pages.css stops it under reduced motion. */

const TICKS = Array.from({ length: 36 }, (_, index) => {
  const angle = (index / 36) * Math.PI * 2;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const inner = index % 3 === 0 ? 246 : 252;
  return {
    key: index,
    x1: 300 + cos * inner,
    y1: 268 + sin * (inner * 0.4),
    x2: 300 + cos * 262,
    y2: 268 + sin * 104.8,
    major: index % 3 === 0,
  };
});

function Slab({ cx, cy, a, b, t, detail = false, accented = false }) {
  const face = `${cx - a},${cy} ${cx},${cy - b} ${cx + a},${cy} ${cx},${cy + b}`;
  const side = `${cx - a},${cy} ${cx},${cy + b} ${cx + a},${cy} ${cx + a},${cy + t} ${cx},${cy + b + t} ${cx - a},${cy + t}`;
  return (
    <g>
      <polygon
        points={side}
        fill={accented ? "var(--accent-strong)" : "var(--accent-soft, #e6ebfd)"}
        stroke={accented ? "var(--accent-strong)" : "var(--border-strong)"}
        strokeWidth="1"
      />
      <polygon
        points={face}
        fill={accented ? "url(#orbit-core-face)" : "var(--surface, #ffffff)"}
        stroke={accented ? "var(--accent)" : "var(--border-strong)"}
        strokeWidth="1"
      />
      {detail && (
        <g stroke={accented ? "#ffffff" : "var(--accent-soft, #e6ebfd)"} strokeWidth="1.4">
          <line
            x1={cx - a * 0.52}
            y1={cy - b * 0.48}
            x2={cx + a * 0.3}
            y2={cy + b * 0.33}
          />
          <line
            x1={cx - a * 0.26}
            y1={cy - b * 0.63}
            x2={cx + a * 0.56}
            y2={cy + b * 0.18}
          />
          <line
            x1={cx + a * 0.08}
            y1={cy - b * 0.74}
            x2={cx + a * 0.74}
            y2={cy - b * 0.11}
            stroke={accented ? "#ffffff" : "var(--accent)"}
            strokeOpacity=".8"
          />
        </g>
      )}
    </g>
  );
}

/* Hero composition: levitating workspace strata inside two orbit planes. */
export function OrbitField() {
  return (
    <div className="orbit-field" aria-hidden="true">
      <svg className="orbit-field-art" viewBox="0 0 600 520" focusable="false">
        <defs>
          <radialGradient id="orbit-glow" cx="50%" cy="44%" r="56%">
            <stop offset="0" stopColor="#ffffff" stopOpacity=".98" />
            <stop
              offset=".58"
              stopColor="var(--accent-soft, #e6ebfd)"
              stopOpacity=".6"
            />
            <stop offset="1" stopColor="var(--canvas)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="orbit-core-face" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#7895ff" />
            <stop offset=".55" stopColor="var(--accent)" />
            <stop offset="1" stopColor="var(--accent-strong)" />
          </linearGradient>
        </defs>
        <circle cx="300" cy="252" r="256" fill="url(#orbit-glow)" />
        <g fill="none">
          <ellipse
            cx="300"
            cy="268"
            rx="250"
            ry="100"
            stroke="var(--border)"
            strokeWidth="1"
          />
          <ellipse
            cx="300"
            cy="268"
            rx="196"
            ry="78"
            stroke="var(--border)"
            strokeWidth="1"
          />
          <ellipse
            cx="300"
            cy="268"
            rx="142"
            ry="57"
            stroke="var(--accent-soft, #e6ebfd)"
            strokeWidth="1.5"
            strokeDasharray="2 9"
          />
          <ellipse
            className="orbit-trace orbit-trace-outer"
            cx="300"
            cy="268"
            rx="250"
            ry="100"
            pathLength="100"
            stroke="var(--accent)"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeDasharray="9 91"
          />
          <ellipse
            className="orbit-trace orbit-trace-inner"
            cx="300"
            cy="268"
            rx="196"
            ry="78"
            pathLength="100"
            stroke="var(--ink)"
            strokeOpacity=".4"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeDasharray="4 96"
          />
        </g>
        <g strokeWidth="1">
          {TICKS.map(({ key, x1, y1, x2, y2, major }) => (
            <line
              key={key}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={major ? "var(--muted)" : "var(--border)"}
              strokeOpacity={major ? ".45" : "1"}
            />
          ))}
        </g>
        <ellipse cx="300" cy="354" rx="152" ry="33" fill="var(--ink)" opacity=".1" />
        <line
          x1="300"
          y1="182"
          x2="300"
          y2="340"
          stroke="var(--border)"
          strokeWidth="1"
          strokeDasharray="2 6"
        />
        <Slab cx={300} cy={332} a={118} b={47} t={13} />
        <Slab cx={300} cy={276} a={92} b={37} t={12} detail accented />
        <Slab cx={300} cy={224} a={64} b={26} t={10} />
        <circle
          className="orbit-core"
          cx="300"
          cy="176"
          r="22"
          fill="var(--accent-soft, #e6ebfd)"
        />
        <circle
          cx="300"
          cy="176"
          r="15"
          fill="none"
          stroke="var(--accent)"
          strokeOpacity=".4"
          strokeWidth="1"
        />
        <circle cx="300" cy="176" r="8.5" fill="var(--accent)" />
        <g>
          <circle cx="84" cy="218" r="5" fill="var(--muted)" opacity=".45" />
          <circle cx="116" cy="295" r="5.5" fill="var(--surface, #fff)" stroke="var(--accent)" strokeWidth="1.6" />
          <circle cx="450" cy="219" r="4.5" fill="var(--ink)" opacity=".32" />
          <circle cx="505" cy="318" r="6" fill="var(--accent)" />
        </g>
      </svg>
      <div className="orbit-chips">
        <span className="orbit-chip orbit-chip-brief">
          <em>01</em>Project brief
        </span>
        <span className="orbit-chip orbit-chip-source">
          <em>02</em>Source snapshot
        </span>
        <span className="orbit-chip orbit-chip-chat">
          <em>03</em>Private chat
        </span>
      </div>
    </div>
  );
}

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

/* Delivery rail: available steps are solid, planned steps stay hollow. */
export function StageRail({ stages }) {
  return (
    <ol className="stage-rail">
      {stages.map(({ title, state, detail }) => (
        <li key={title} className={`stage-rail-item stage-${state}`}>
          <span className="stage-rail-dot" aria-hidden="true" />
          <strong>{title}</strong>
          <span className="stage-rail-state">
            {state === "available" ? "Available" : "Planned"}
          </span>
          <p>{detail}</p>
        </li>
      ))}
    </ol>
  );
}
