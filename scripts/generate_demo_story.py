"""Produce a reviewable, non-deployed feature storyboard from offline outcomes.

Example:
  python scripts/generate_demo_story.py outcomes.json --id search-caching \\
    --title "Search caching" --problem "Cold searches are slow." \\
    --capability "A local candidate caches bounded search results." \\
    --limitations "No real customer load test yet." --output /tmp/search-demo.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from oryveta_engine.demo import story_from_evidence
from oryveta_engine.learning import Outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--limitations", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.stat().st_size > 2_000_000:
        parser.error("evidence JSON exceeds the 2 MB limit")
    rows = json.loads(args.evidence.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        parser.error("evidence JSON must be a list of paired outcomes")
    story = story_from_evidence(
        args.id, args.title, args.problem, args.capability, args.limitations,
        [Outcome(**row) for row in rows],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(story, indent=2) + "\n", encoding="utf-8")
    print(f"Storyboard saved to {args.output}; status={story['evaluation_status']}; "
          "NOT verified, deployed, or rendered")


if __name__ == "__main__":
    main()
