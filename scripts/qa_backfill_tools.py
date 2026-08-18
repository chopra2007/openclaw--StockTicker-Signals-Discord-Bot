#!/usr/bin/env python3
"""Refresh `tools_seen` on an existing QA results file from the session
transcripts, so a run captured before the extractor was fixed still shows what
the agent actually called.

Usage: python3 scripts/qa_backfill_tools.py results.jsonl [results2.jsonl ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.qa_feature_questions import tools_used  # noqa: E402

for path in sys.argv[1:]:
    p = Path(path)
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    for r in recs:
        r["tools_seen"] = tools_used(r["session_id"])
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    print(f"{p}: refreshed {len(recs)} records")
