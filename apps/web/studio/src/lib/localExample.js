import { useEffect, useState } from "react";

/* One source for the recorded local repair example. The numbers live only in
   public/repair-example.json, so no page restates a run metric by hand. The
   loader never substitutes placeholder values: a failed or unexpected payload
   surfaces as an explicit failure that the UI reports instead of rendering a
   verified-looking result. */

export const EXAMPLE_RECORD_FILE = "repair-example.json";
export const EXAMPLE_PATCH_FILE = "repair-example.patch";
export const exampleAssetUrl = (file) => `${import.meta.env.BASE_URL}${file}`;

let pending = null;

export function loadLocalExample() {
  if (!pending)
    pending = fetch(exampleAssetUrl(EXAMPLE_RECORD_FILE), {
      headers: { Accept: "application/json" },
    })
      .then((response) => {
        if (!response.ok)
          throw new Error(`Example record unavailable (${response.status})`);
        return response.json();
      })
      .then((record) => {
        if (!record || record.kind !== "local_integration_example")
          throw new Error("That file is not a recorded local example");
        return record;
      })
      .catch((error) => {
        pending = null;
        throw error;
      });
  return pending;
}

export function useLocalExample() {
  const [state, setState] = useState({ record: null, failed: false });
  useEffect(() => {
    let live = true;
    loadLocalExample().then(
      (record) => live && setState({ record, failed: false }),
      () => live && setState({ record: null, failed: true }),
    );
    return () => {
      live = false;
    };
  }, []);
  return state;
}

export function exampleSummary(record) {
  const checks = record.checks || [];
  return {
    passed: checks.filter((check) => check.passed).length,
    total: checks.length,
    shortRun: record.run_id ? record.run_id.slice(0, 12) : "",
  };
}
