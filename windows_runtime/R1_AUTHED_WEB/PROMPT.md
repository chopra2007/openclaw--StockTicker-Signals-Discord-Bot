# R1 — AUTHED WEB Routine

You are a Claude Desktop automation agent executing the **R1_AUTHED_WEB** routine.
Follow every step in order without skipping. Do not ask for confirmation — execute immediately.

---

## PREFLIGHT (run once at session start)

### 1. Pull latest code

```bash
git -C <workspace_path> pull
```

Replace `<workspace_path>` with the absolute path to the openclaw workspace on this machine.

### 2. Verify PROMPT.md integrity

Compute the SHA-256 of this file and compare it to the expected value recorded in your bearer config:

```bash
python3 -c "
import hashlib, pathlib
p = pathlib.Path('<workspace_path>/windows_runtime/R1_AUTHED_WEB/PROMPT.md')
print(hashlib.sha256(p.read_bytes()).hexdigest())
"
```

If the hash does not match the expected value, stop immediately and alert the operator.

### 3. Check Python version

```bash
python3 -c "import sys; assert sys.version_info >= (3, 11), f'Need Python 3.11+, got {sys.version}'; print('Python OK:', sys.version)"
```

If the assertion fails, stop and notify the operator to upgrade Python.

### 4. Verify bearer token

```bash
python3 -c "
import pathlib
p = pathlib.Path('<workspace_path>/windows_runtime/ingest_client/.bearer.R1.local')
tok = p.read_text().strip()
assert tok, 'Bearer token is empty'
print('Bearer OK, length:', len(tok))
"
```

If the file is missing or empty, stop and ask the operator to provision the bearer token.

### 5. Send preflight heartbeat

```bash
python3 -c "
import sys, time
sys.path.insert(0, '<workspace_path>/windows_runtime')
from ingest_client import submit
ok = submit('R1', 'heartbeat', 'preflight', 'routine started')
print('Heartbeat sent:', ok)
"
```

### 6. Record start time

```bash
python3 -c "import time; print('START_TIME:', time.time())"
```

Copy the printed float value — you will need it for the wall-clock guard in the next section.

---

## PER-TARGET LOOP

Read `target_sites.yaml` (located next to this file) for the site list.
For each site **in order**:

### Step A — Wall-clock guard

Before processing each site, check elapsed time:

```python
import time
elapsed = time.time() - START_TIME   # use the value from PREFLIGHT step 6
if elapsed > 360:
    print("ABORT: wall-clock guard triggered after", elapsed, "seconds")
    # skip to POSTFLIGHT immediately
    raise SystemExit("wall-clock guard")
```

### Step B — Inter-site jitter sleep

Sleep a random number of seconds between `jitter_min_s` and `jitter_min_s + 10`:

```python
import random, time
jitter = random.uniform(site['jitter_min_s'], site['jitter_min_s'] + 10)
print(f"Sleeping {jitter:.1f}s before {site['name']}")
time.sleep(jitter)
```

### Step C — Load the page

Use **Playwright** (preferred) or `requests` as fallback:

**Playwright example:**
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(site['url_template'], timeout=30000)
    # dwell
    import random, time
    time.sleep(random.uniform(site['dwell_min_s'], site['dwell_max_s']))
    html = page.content()
    browser.close()
```

**requests fallback (API endpoints only):**
```python
import requests, time, random
resp = requests.get(site['url_template'], timeout=20,
                    headers={'User-Agent': 'Mozilla/5.0'})
resp.raise_for_status()
html = resp.text
time.sleep(random.uniform(site['dwell_min_s'], site['dwell_max_s']))
```

### Step D — Sentinel check

If `sentinel_selector` is non-null, check whether a paywall / block element is present:

```python
# Playwright example
if site['sentinel_selector']:
    found = page.locator(site['sentinel_selector']).count() > 0
    if found:
        print(f"Sentinel found on {site['name']} — skipping")
        sites_skipped += 1
        continue
```

If the sentinel is found, increment `sites_skipped` and **skip to the next site**.

### Step E — Extract text content

Extract visible text using the `css_selector`:

```python
# Playwright example
elements = page.locator(site['css_selector']).all()
texts = [el.inner_text() for el in elements]
extracted_text = '\n'.join(texts)[:8000]   # cap at 8 000 chars
```

If no elements are found, log a warning and set `extracted_text = ""`.

### Step F — Submit to ingest

```python
import sys
sys.path.insert(0, '<workspace_path>/windows_runtime')
from ingest_client import submit

ok = submit(
    routine_id='R1',
    source_type='desktop_auth',
    source_detail=site['url_template'],
    raw_text=extracted_text,
)
if ok:
    sites_processed += 1
    print(f"Submitted {site['name']} OK")
else:
    errors += 1
    print(f"Submit failed for {site['name']} (queued to outbox)")
```

---

## POSTFLIGHT

### 1. Compute runtime

```python
import time
runtime = time.time() - START_TIME
partial = runtime > 360
```

### 2. Send final heartbeat with stats

```python
from ingest_client import submit

stats_msg = (
    f"routine finished | sites_processed={sites_processed} "
    f"sites_skipped={sites_skipped} errors={errors} "
    f"runtime={runtime:.1f}s partial={partial}"
)

submit(
    routine_id='R1',
    source_type='heartbeat',
    source_detail='postflight',
    raw_text=stats_msg,
)
print("Postflight heartbeat sent:", stats_msg)
```

### 3. Exit cleanly

```python
print("R1_AUTHED_WEB routine complete.")
```

---

## Variable Tracker

Keep these variables in scope throughout the routine:

| Variable | Initial value | Updated by |
|---|---|---|
| `START_TIME` | `time.time()` at PREFLIGHT step 6 | — |
| `sites_processed` | `0` | Step F on success |
| `sites_skipped` | `0` | Step D sentinel hit |
| `errors` | `0` | Step F on failure |

---

## Error Handling Summary

| Condition | Action |
|---|---|
| Hash mismatch on PROMPT.md | Stop, alert operator |
| Python < 3.11 | Stop, notify operator |
| Missing / empty bearer | Stop, notify operator |
| Wall-clock > 360 s | Abort loop, go to POSTFLIGHT |
| Sentinel found | Skip site, increment `sites_skipped` |
| No elements from CSS selector | Log warning, submit empty string |
| `submit()` returns False | Increment `errors` (outbox handles retry) |
| Unhandled exception on a site | Log, increment `errors`, continue next site |
