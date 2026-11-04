/* One source for both plan cards and the home summary, so a price is never
   stated twice. Nothing here can be purchased: there is no billing service and
   no checkout in this application. */

export const TEAM_BUILDERS = 5;
export const TEAM_PRICE = "$49";
export const SOURCE_URL = "https://github.com/suhasaitham22/Oryveta";

export const plans = [
  {
    id: "community",
    name: "Community",
    price: "$0",
    unit: "open-source software · free hosted preview",
    availability: "available",
    availabilityLabel: "Free preview · capacity-limited",
    summary:
      "Plan with your team in the free hosted preview. Run the open-source repair tools on your own machine.",
    includes: [
      "Projects, roles, private chats and exportable briefs",
      "Open-source local repair tools and model gateway",
      "Controller-owned checks and inspectable patch records",
    ],
    excludes: [
      "Your own model and runner are required",
      "Hosted agent runs are not available",
    ],
    cta: { to: "/workspace", label: "Open a free workspace" },
    note: "Preview capacity is limited. No uptime or perpetual free-hosting promise; no payment is required.",
  },
  {
    id: "team",
    name: "Team",
    price: TEAM_PRICE,
    unit: "USD per workspace / month · proposed",
    availability: "proposed",
    availabilityLabel: "Proposed · not available",
    summary: `Proposed coordination tools for up to ${TEAM_BUILDERS} builders. Bring your own model and runner.`,
    includes: [
      "Everything in Community",
      "Planned: shared run history and patch records",
      "Planned: named reviewers and approval workflow",
      "Planned: workspace budget controls",
    ],
    excludes: [
      "No hosted inference or compute included",
      "Paid features and billing are not available",
    ],
    cta: { to: "/workspace", label: "Try the free workspace" },
    note: "No purchase today. Final pricing and terms will be confirmed before launch.",
  },
];
