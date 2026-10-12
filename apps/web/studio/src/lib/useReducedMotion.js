import { useSyncExternalStore } from "react";

// Motion 14's hook snapshots the preference on mount. Subscribe so changing the
// OS/browser preference also stops transforms in an already-open workspace.
const query = window.matchMedia("(prefers-reduced-motion: reduce)");
const subscribe = (listener) => {
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
};
const snapshot = () => query.matches;

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, snapshot, () => true);
}
