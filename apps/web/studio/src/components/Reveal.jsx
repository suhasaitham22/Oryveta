import React, { useEffect, useRef } from "react";

/* Positional scroll entrance without hiding readable content. Only arm the
   transform after an observer exists; unsupported browsers keep the natural
   layout. The observer disconnects after its first visible intersection. */
export default function Reveal({
  as: Tag = "div",
  delay = 0,
  className = "",
  children,
  ...rest
}) {
  const host = useRef(null);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    if (typeof IntersectionObserver !== "function") {
      node.dataset.revealed = "true";
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        node.dataset.revealed = "true";
        observer.disconnect();
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    node.dataset.revealPending = "true";
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <Tag
      ref={host}
      className={className ? `reveal ${className}` : "reveal"}
      style={delay ? { "--reveal-delay": `${delay}ms` } : undefined}
      {...rest}
    >
      {children}
    </Tag>
  );
}
