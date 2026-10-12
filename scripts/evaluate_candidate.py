"""Evaluate independent JSON evidence. Read-only; never promotes/deploys."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from oryveta_engine.learning import Outcome, evaluate

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("evidence",type=Path)
    path=parser.parse_args().evidence
    if path.stat().st_size>2_000_000:
        raise SystemExit("Evidence file >2MB")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,list):
        raise SystemExit("Expected JSON array")
    decision=evaluate([Outcome(**item) for item in data])
    print(json.dumps(asdict(decision),indent=2))
    return 0 if decision.status=="NEEDS_HUMAN_REVIEW" else 1

if __name__=="__main__":
    raise SystemExit(main())
