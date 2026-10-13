// Illustrative documents, not engine output. Shared by the 3D and semantic views.
export const productArtifacts = [
  {
    title: "The brief",
    label: "01 / Intent",
    file: "onboarding / brief.json",
    heading: "Client onboarding",
    tag: "Planning draft",
    text: "A specific customer task, an explicit boundary, and a brief you can export.",
    rows: [
      ["Customer task", "Give clients one place to submit their documents."],
      ["Acceptance criteria", "A reviewer can see what is still missing."],
      ["Constraint", "Keep each client's documents private."],
    ],
    footer: "Brief JSON · authored by you",
  },
  {
    title: "The evidence",
    label: "02 / Source",
    file: "onboarding / source review",
    heading: "Look inside the source.",
    tag: "Illustrative review",
    text: "A local source snapshot and findings to review—not a claim that tests passed.",
    rows: [
      ["01  app/", "02    main.py"],
      ["03  tests/", "04    test_health.py"],
      ["Review boundary", "Static analysis reads code. It does not run it."],
    ],
    footer: "Local engine · no automatic code changes",
  },
  {
    title: "The handoff",
    label: "03 / Story",
    file: "onboarding / storyboard.json",
    heading: "Explain the next step.",
    tag: "Unverified storyboard",
    text: "An editable story beside the work, with its limitations kept in the frame.",
    rows: [
      ["01 / Customer action", "A client submits the requested documents."],
      ["02 / Visible result", "A reviewer sees the remaining requirements."],
      ["03 / Proof needed", "Verify access boundaries before sharing."],
    ],
    footer: "Storyboard JSON · not a rendered video",
  },
];
