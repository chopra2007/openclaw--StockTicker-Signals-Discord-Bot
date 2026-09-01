#!/usr/bin/env python3
import hashlib, json, pathlib, sys
kind, path = sys.argv[1], pathlib.Path(sys.argv[2])
try:
    data = path.read_bytes(); value = json.loads(data)
except Exception:
    raise SystemExit(2)
if value.get("check") != kind or value.get("available") is not True:
    raise SystemExit(3)
print(json.dumps({"status":"PASS", "evidenceSha256":hashlib.sha256(data).hexdigest(), "facts":[value.get("fact", kind + " available")]}))
