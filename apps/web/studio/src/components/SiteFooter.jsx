import React from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import Brand from "./Brand.jsx";

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner section-container">
        <div className="footer-brand">
          <Brand />
          <p>
            Plan software, review source and work together in one workspace.
            Planning and source review are available today; the AI delivery
            workflow is still being built.
          </p>
          <span className="status-tag">Apache-2.0 · self-hostable</span>
        </div>
        <nav className="footer-columns" aria-label="Footer">
          <div>
            <h2>Explore</h2>
            <ul>
              <li>
                <Link to="/what-we-do">What We Do</Link>
              </li>
              <li>
                <Link to="/about">About</Link>
              </li>
              <li>
                <Link to="/workspace">Workspace</Link>
              </li>
              <li>
                <Link to="/sign-in">Sign in</Link>
              </li>
            </ul>
          </div>
          <div>
            <h2>Open source</h2>
            <ul>
              <li>
                <a
                  href="https://github.com/suhasaitham22/Oryveta"
                  target="_blank"
                  rel="noreferrer"
                >
                  Source <ArrowUpRight size={13} aria-hidden="true" />
                </a>
              </li>
              <li>
                <a href={`${import.meta.env.BASE_URL}template-license.txt`}>
                  Attribution
                </a>
              </li>
              <li>
                <a href={`${import.meta.env.BASE_URL}geist-license.txt`}>
                  Font license
                </a>
              </li>
            </ul>
          </div>
        </nav>
      </div>
      <div className="site-footer-base section-container">
        <span>Oryveta · Plan software. Review source. Work together.</span>
        <span>Starter templates and third-party licenses remain their own.</span>
      </div>
    </footer>
  );
}
