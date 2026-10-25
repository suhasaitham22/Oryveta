// Illustrative documents, not engine output. Shared by the 3D and semantic views.
export const productArtifacts = [
  {
    title: "Project brief",
    label: "01 / Intent",
    file: "onboarding / brief.json",
    heading: "Client onboarding",
    tag: "Planning draft",
    text: "Describe who the app is for, what it must do and how you will check it.",
    rows: [
      ["Customer task", "Give clients one place to submit their documents."],
      ["Acceptance criteria", "A reviewer can see what is still missing."],
      ["Constraint", "Keep each client's documents private."],
    ],
    footer: "Brief JSON · authored by you",
  },
  {
    title: "Code review",
    label: "02 / Source",
    file: "onboarding / source review",
    heading: "Review a source snapshot.",
    tag: "Illustrative review",
    text: "Inspect files and candidate issues from read-only analysis of a source snapshot.",
    rows: [
      ["01  app/", "02    main.py"],
      ["03  tests/", "04    test_health.py"],
      ["Review boundary", "Static analysis reads code. It does not run it."],
    ],
    footer: "Local engine · no automatic code changes",
  },
  {
    title: "Demo script",
    label: "03 / Story",
    file: "onboarding / storyboard.json",
    heading: "Show the user experience.",
    tag: "Unverified storyboard",
    text: "Draft the scenes for a product demo and export the script for later editing.",
    rows: [
      ["01 / Customer action", "A client submits the requested documents."],
      ["02 / Visible result", "A reviewer sees the remaining requirements."],
      ["03 / Proof needed", "Verify access boundaries before sharing."],
    ],
    footer: "Storyboard JSON · not a rendered video",
  },
];
