#!/usr/bin/env python3
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
if value.get("uniqueCompleteRecords") != 4:
    raise SystemExit(1)
print(json.dumps({"status":"PASS", "uniqueCompleteRecords":4}))
