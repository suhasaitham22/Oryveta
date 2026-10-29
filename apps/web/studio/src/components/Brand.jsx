import React from "react";

/* Original wordmark glyph: one workspace core inside a single tilted orbit. */
export default function Brand() {
  return (
    <span className="brand-wordmark">
      <span className="brand-glyph">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
          <g transform="rotate(-28 12 12)">
            <ellipse
              cx="12"
              cy="12"
              rx="10"
              ry="5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <circle cx="22" cy="12" r="2.1" fill="currentColor" />
          </g>
          <circle cx="12" cy="12" r="3.3" fill="currentColor" />
        </svg>
      </span>
      oryveta<span className="brand-dot">.</span>
    </span>
  );
}
