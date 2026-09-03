"""Cached DoltHub SQL fetcher for the TODO #111 option-chain pull."""
import hashlib
import json
import os
import time

import requests

BASE = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"
CACHE_DIR = "/home/openclaw/.openclaw/research-data/todo-111/chains"


def _cache_path(sql):
    h = hashlib.sha1(sql.encode()).hexdigest()
    d = os.path.join(CACHE_DIR, h[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, h + ".json")


def query(sql, session=None, retries=6, timeout=120):
    """Run one SQL query, caching the successful response body on disk."""
    path = _cache_path(sql)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    sess = session or requests
    last = None
    for attempt in range(retries):
        try:
            r = sess.get(BASE, params={"q": sql}, timeout=timeout)
            j = r.json()
        except Exception as exc:  # network / decode
            last = str(exc)
            time.sleep(2 + 3 * attempt)
            continue
        status = j.get("query_execution_status")
        if status == "Success" or status == "RowLimit":
            with open(path, "w") as f:
                json.dump(j, f)
            return j
        last = j.get("query_execution_message", status)
        time.sleep(2 + 3 * attempt)
    raise RuntimeError("dolt query failed after retries: %s :: %s" % (last, sql))
