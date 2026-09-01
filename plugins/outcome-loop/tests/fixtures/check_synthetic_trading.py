#!/usr/bin/env python3
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
if value != {"qualifiedSyntheticRows": 2, "claim": "workflow-only-no-edge-claim"}:
    raise SystemExit(1)
print(json.dumps({"status":"PASS", "scope":"synthetic-workflow-only"}))
