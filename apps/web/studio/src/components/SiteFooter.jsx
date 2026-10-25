import React from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

export default function SiteFooter() {
  return (
    <footer className="site-footer section-container">
      <span>Oryveta · Plan software. Review source. Work together.</span>
      <nav aria-label="Footer">
        <Link to="/about">About</Link>
        <a
          href="https://github.com/suhasaitham22/Oryveta"
          target="_blank"
          rel="noreferrer"
        >
          Source <ArrowUpRight size={12} />
        </a>
        <a href={`${import.meta.env.BASE_URL}template-license.txt`}>Attribution</a>
      </nav>
    </footer>
  );
}
