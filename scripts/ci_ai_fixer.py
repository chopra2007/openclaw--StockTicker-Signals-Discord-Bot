"""#59: the AI half of the CI auto-fixer — classify a red gate, and patch a real bug.

The deterministic layer in `/root/task_system/scripts/ci_autofix.sh` already handles
the two easy classes: a missing package, and a test that passes locally twice (flaky).
Everything left over is a genuine code failure, and until now that meant "wake a human".

This module asks one cheap, pinned OpenRouter model to do two things:

  1. classify the failure as `undeclared_dependency` / `flaky` / `real_logic_bug`
  2. for a real bug, return exact search/replace edits that make the test pass

Search/replace beats a unified diff here: a model that miscounts a line number
produces a diff that silently applies to the wrong place, while an exact string that
doesn't match exactly once is simply rejected. Failing loudly is the whole point.

The model NEVER pushes. `ci_autofix.sh` commits a verified logic fix locally and
shouts; a human presses the button. Missing-package fixes keep auto-pushing, because
those are mechanical.

    python3 scripts/ci_ai_fixer.py --failing "tests/test_x.py::test_y" \
        --error-file /tmp/pytest.log [--model SLUG] [--dry-run]

Exit codes: 0 = edits applied, 2 = classified but no edit needed (flaky/dep),
3 = model failed or produced nothing usable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

# Pinned by the 2026-07-11 v3 race (.omc/plans/ci-fixer-race-v3-2026-07-10.md; harness
# scripts/ci_fixer_trials.py, corpus .omc/trials/corpus_v3.json). Capability is a GATE,
# not a score: this model cleared ≥70% per-incident success (production retries 3×) on a
# 4-case real-source-bug corpus, and among all qualifiers it is the cheapest — the whole
# strong-coder field now prices under 25¢/mo once the prompt is trimmed, so price stopped
# being the constraint and the cheapest capable model wins. Measured: SCORE 0.86 (deep,
# 5 trials/case), 4/4 cases, 0 timeouts, ~$0.007/mo; confirm run 8/8. Expect to re-race
# when this slug is retired — they churn; the harness + corpus re-run for ~$1-2.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

# A different model FAMILY from the one that wrote most of this code (Claude), on the
# same reasoning as the Wolf verifier (#64): a model cannot rubber-stamp its own work.
FORBIDDEN_FAMILIES = ("anthropic/",)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# `requests`' read timeout only measures the gap BETWEEN bytes. OpenRouter sends SSE
# keepalive comments while a model thinks, which resets that clock forever — a stalled
# call once hung for 25 minutes with a 240s timeout set. So: stream, and enforce a hard
# wall-clock deadline ourselves. A CI fixer that hangs is worse than one that gives up.
CONNECT_TIMEOUT_S = 15
READ_TIMEOUT_S = 90
# 600s, not 210: this is a background job run ~monthly, nobody waits on it, and a
# reasoning model needs room to finish. A hung call still surfaces — the deadline is a
# hard wall-clock cap, it just gives a slow-but-working model the time it needs.
HARD_DEADLINE_S = 600
# 16000, not 8000: this is a CAP, not a spend — it costs nothing unless used, and 8000
# demonstrably truncated reasoning models mid-thought (they emit hidden reasoning tokens
# before the JSON). The reply itself is still one small JSON object.
MAX_TOKENS = 16000
# 20k, not 60k: input tokens dominate every attempt's cost, so trimming each context
# file roughly halves the cost of the race AND of production per incident.
MAX_FILE_CHARS = 20_000
# Total prompt budget. Files past this are dropped/truncated deepest-import first; the
# failing test file and any traceback-named file are protected and never dropped.
MAX_PROMPT_CHARS = 80_000
# Reasoning control, e.g. {"max_tokens": 3000} or {"effort": "low"}. Left None in
# production; the race sets it as a cost arm on models that burn reasoning tokens.
REASONING: dict | None = None

CLASSES = ("undeclared_dependency", "flaky", "real_logic_bug")

# Never let the model touch these, even if it asks. Mirrors ci_autofix.sh's gate;
# duplicated here so a direct call is safe too.
FORBIDDEN_RE = re.compile(
    r"^(config/consensus\.yaml"
    r"|\.claude/go-live-evidence/"
    r"|\.github/"
    r"|scripts/pre-push"
    r"|scripts/session_close\.sh"
    r"|\.git/)"
)

SYSTEM = """You repair a failing Python test suite. You are precise and minimal.

Reply with ONE JSON object and nothing else. No markdown fence, no prose.

{
  "classification": "undeclared_dependency" | "flaky" | "real_logic_bug",
  "reason": "<one sentence>",
  "missing_package": "<pypi name, only when undeclared_dependency>",
  "edits": [
    {"file": "<repo-relative path>",
     "search": "<exact text that appears EXACTLY ONCE in that file>",
     "replace": "<replacement text>"}
  ]
}

Rules:
- "undeclared_dependency": the failure is an ImportError/ModuleNotFoundError or a
  "Missing optional dependency" for a package that is simply not installed. edits: [].
- "flaky": the failure comes from a live network/data source, a clock, or ordering —
  not from the code under test. edits: [].
- "real_logic_bug": anything else. Provide the minimal edits that make the named
  failing tests pass.
- Each "search" string MUST appear character-for-character exactly once in the file,
  including indentation. Copy it from the file content given to you. Do not
  abbreviate it, and do not include line numbers.
- Keep edits surgical. Never reformat, rename, or "improve" nearby code.
- Never edit config/consensus.yaml, .github/, scripts/pre-push, scripts/session_close.sh,
  or anything under .claude/go-live-evidence/.
"""


class FixerError(Exception):
    pass


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------

def _read(path: Path) -> str | None:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + "\n# ...(truncated)...\n"
    return text


def local_imports(source: str, root: Path) -> list[str]:
    """Repo modules a file imports, as repo-relative paths.

    Without this the model sees only the failing test and has to guess at the code
    under test. The 2026-07-09 race proved the point: the frozen-date bug is caused by
    `wolf_news.post_event()` stamping `time.time()`, and every model failed because
    `wolf_news.py` was never in the prompt — the traceback never names it.
    """
    import ast

    mods: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
            # `from consensus_engine.alerts import wolf_digest` — the interesting file
            # is the SUBMODULE, not the package __init__. Resolving only node.module
            # hands the model a 30-character __init__.py and none of the real code.
            for alias in node.names:
                mods.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)

    paths: list[str] = []
    for mod in mods:
        if not mod.startswith("consensus_engine"):
            continue
        cand = mod.replace(".", "/") + ".py"
        if (root / cand).is_file() and cand not in paths:
            paths.append(cand)
    return paths


MAX_CONTEXT_FILES = 8
# How far to follow imports out from the failing test. 1 = the modules it imports.
# 2 also picks up what THOSE import — needed for the frozen-date bug, whose cause is
# in wolf_news.py, imported by wolf_digest.py, imported by the test.
IMPORT_DEPTH = 2


def named_paths(failing: str, error_text: str) -> list[str]:
    """The failing test files + any repo source file named in the traceback. These are
    the files the model most needs, so they are protected from prompt trimming."""
    paths: list[str] = []
    for tid in failing.split():
        if "::" in tid:
            paths.append(tid.split("::", 1)[0])
        elif tid.endswith(".py"):
            paths.append(tid)
    for m in re.finditer(r"((?:tests|consensus_engine|scripts)/[\w/]+\.py)", error_text):
        paths.append(m.group(1))
    return [p for p in dict.fromkeys(paths) if not FORBIDDEN_RE.match(p)]


def relevant_files(failing: str, error_text: str, root: Path) -> dict[str, str]:
    """Everything the model needs to see: the failing test files, any repo file named
    in the traceback, and the repo modules those tests import (the code under test)."""
    paths = named_paths(failing, error_text)

    out: dict[str, str] = {}
    for p in dict.fromkeys(paths):
        if FORBIDDEN_RE.match(p):
            continue
        content = _read(root / p)
        if content is not None:
            out[p] = content

    # Walk out along imports. The named files are already in, so a cap can never evict
    # the test that is actually failing.
    frontier = list(out)
    for _ in range(IMPORT_DEPTH):
        if len(out) >= MAX_CONTEXT_FILES:
            break
        next_frontier: list[str] = []
        for p in frontier:
            for dep in local_imports(out[p], root):
                if len(out) >= MAX_CONTEXT_FILES:
                    break
                if dep in out or FORBIDDEN_RE.match(dep):
                    continue
                content = _read(root / dep)
                if content is None or len(content.strip()) < 200:
                    continue   # an empty package __init__ teaches the model nothing
                out[dep] = content
                next_frontier.append(dep)
        frontier = next_frontier
    return out


def build_prompt(failing: str, error_text: str, files: dict[str, str],
                 protected: set[str] | None = None) -> str:
    """Assemble the prompt under a total-char budget. `files` is in priority order
    (named files first, then import-followed). Protected files are always included
    (capped per-file); non-protected files are dropped once the budget is spent — so
    the deepest-import files go first and the failing test never does."""
    protected = protected or set()
    header = f"The regression gate is red. These tests fail:\n{failing}\n"
    err = "Local pytest output (tail):\n```\n" + error_text.strip()[-6000:] + "\n```\n"
    tail = ("Classify the failure and, if it is a real logic bug, return the "
            "minimal edits that make exactly these tests pass.")
    parts = [header, err]
    used = len(header) + len(err) + len(tail)
    for path, content in files.items():
        wrap = len(f"--- FILE: {path} ---\n```python\n") + len("\n```\n")
        room = MAX_PROMPT_CHARS - used - wrap
        body = content
        if len(body) > room:
            if path not in protected and room < 500:
                continue                       # no room for a non-essential file — drop it
            body = body[:max(room, 0)] + "\n# ...(truncated)...\n"
        parts.append(f"--- FILE: {path} ---\n```python\n{body}\n```\n")
        used += wrap + len(body)
    parts.append(tail)
    return "\n".join(parts)


# --------------------------------------------------------------------------
# model call
# --------------------------------------------------------------------------

def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path.home() / ".openclaw" / ".env")
        except ImportError:
            pass
        key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise FixerError("OPENROUTER_API_KEY not set")
    return key


_MODEL_META: dict[str, dict] = {}


def model_meta(slug: str) -> dict:
    """OpenRouter's `context_length` and `supported_parameters` for a slug, fetched once
    and cached. Empty dict if the catalog can't be read — callers degrade gracefully."""
    if not _MODEL_META:
        try:
            import requests
            r = requests.get("https://openrouter.ai/api/v1/models",
                             headers={"Authorization": f"Bearer {_api_key()}"}, timeout=20)
            for m in (r.json().get("data") or []):
                _MODEL_META[m.get("id", "")] = {
                    "context_length": m.get("context_length") or 0,
                    "supported_parameters": set(m.get("supported_parameters") or []),
                    "pricing": m.get("pricing") or {},
                }
        except Exception:  # noqa: BLE001 — no catalog just means no JSON enforcement
            pass
        _MODEL_META.setdefault("__loaded__", {})
    return _MODEL_META.get(slug, {})


def _request_body(model: str, messages: list, temperature: float,
                  stream: bool, response_format: bool) -> dict:
    body: dict[str, Any] = {"model": model, "temperature": temperature,
                            "max_tokens": MAX_TOKENS, "messages": messages}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if response_format:
        body["response_format"] = {"type": "json_object"}
    if REASONING is not None:
        body["reasoning"] = REASONING
    return body


def call_model(model: str, prompt: str, temperature: float = 0.0,
               deadline_s: float = HARD_DEADLINE_S) -> dict[str, Any]:
    """Backwards-compatible single-prompt entry point (system + one user message)."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt}]
    return call_messages(model, messages, temperature, deadline_s)


def call_messages(model: str, messages: list, temperature: float = 0.0,
                  deadline_s: float = HARD_DEADLINE_S) -> dict[str, Any]:
    """One completion for a full message list, streamed under a hard wall-clock deadline.

    Returns {text, usage, latency_s, finish_reason, provider}. Raises FixerError on any
    failure, including running past `deadline_s` — a hung model call must surface as
    "escalate to a human", never as an indefinite wait. Sends OpenRouter's JSON-object
    response_format when the model advertises support for it, and drops it on a 4xx that
    complains about that param.
    """
    if model.startswith(FORBIDDEN_FAMILIES):
        raise FixerError(
            f"{model} is the same family that wrote this code — a cross-family "
            f"reviewer cannot rubber-stamp its own work (see #64)")
    use_json = "response_format" in model_meta(model).get("supported_parameters", set())
    try:
        return _stream_call(model, messages, temperature, deadline_s, use_json)
    except FixerError as e:
        low = str(e).lower()
        if use_json and "http 4" in low and ("response_format" in low or "json" in low):
            return _stream_call(model, messages, temperature, deadline_s, False)
        raise


def _stream_call(model: str, messages: list, temperature: float, deadline_s: float,
                 response_format: bool) -> dict[str, Any]:
    import requests

    t0 = time.time()
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {_api_key()}",
                 "Content-Type": "application/json"},
        json=_request_body(model, messages, temperature, True, response_format),
        stream=True,
        timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
    )
    if resp.status_code != 200:
        body = resp.text[:300]
        resp.close()
        raise FixerError(f"{model}: HTTP {resp.status_code}: {body}")

    chunks: list[str] = []
    usage: dict = {}
    provider = None
    finish_reason = None
    deadline = t0 + deadline_s
    try:
        for raw in resp.iter_lines(decode_unicode=False):
            if time.time() > deadline:
                raise FixerError(
                    f"{model}: no complete reply within {deadline_s:.0f}s — giving up")
            if not raw:
                continue
            line = raw.decode("utf-8", "replace")
            if line.startswith(":"):
                continue                       # SSE keepalive comment
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if obj.get("usage"):
                usage = obj["usage"]
            if obj.get("provider"):
                provider = obj["provider"]
            for choice in obj.get("choices") or []:
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    chunks.append(piece)
    except requests.RequestException as e:
        raise FixerError(f"{model}: stream failed: {e}")
    finally:
        resp.close()

    text = "".join(chunks)
    if not text.strip():
        # OpenRouter load-balances across upstream providers per call, and some of
        # them deliver a reasoning model's answer in a way the SSE `delta.content`
        # path never sees. The same request without `stream` returns it intact.
        # Retry once, inside whatever is left of the deadline, before giving up.
        left = deadline - time.time()
        if left > 5:
            return _call_unstreamed(model, messages, temperature, left, t0, response_format)
        raise FixerError(f"{model}: empty reply")
    return {"text": text, "usage": usage, "latency_s": time.time() - t0,
            "finish_reason": finish_reason, "provider": provider}


def _call_unstreamed(model: str, messages: list, temperature: float,
                     timeout_s: float, t0: float,
                     response_format: bool) -> dict[str, Any]:
    """Non-streaming fallback. Safe here: with no SSE keepalive comments arriving, a
    plain read timeout does measure the silence, so it cannot hang the way #59's
    25-minute stall did."""
    import requests

    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {_api_key()}",
                 "Content-Type": "application/json"},
        json=_request_body(model, messages, temperature, False, response_format),
        timeout=(CONNECT_TIMEOUT_S, timeout_s),
    )
    if resp.status_code != 200:
        raise FixerError(f"{model}: HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    choice = (body.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        if choice.get("finish_reason") == "length":
            raise FixerError(f"{model}: reply truncated at max_tokens={MAX_TOKENS}")
        raise FixerError(f"{model}: empty reply")
    return {"text": text, "usage": body.get("usage") or {},
            "latency_s": time.time() - t0,
            "finish_reason": choice.get("finish_reason"), "provider": body.get("provider")}


def parse_response(text: str) -> dict:
    """Pull the JSON object out, tolerating a stray markdown fence or leading prose."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise FixerError(f"no JSON object in reply: {text[:200]}")
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise FixerError(f"unparseable JSON: {e}")
    if not isinstance(obj, dict) or obj.get("classification") not in CLASSES:
        raise FixerError(f"missing/invalid classification: {str(obj)[:200]}")
    edits = obj.get("edits") or []
    if not isinstance(edits, list):
        raise FixerError("edits must be a list")
    obj["edits"] = edits
    return obj


# --------------------------------------------------------------------------
# edit application
# --------------------------------------------------------------------------

def apply_edits(edits: list[dict], root: Path) -> list[str]:
    """Apply exact search/replace edits. All-or-nothing: on any rejection, nothing
    is written. Returns the repo-relative paths touched.

    An edit is rejected when the file is forbidden, missing, or the search string
    does not appear EXACTLY once. Ambiguity is a failure, never a guess.
    """
    staged: dict[Path, str] = {}
    touched: list[str] = []
    for i, edit in enumerate(edits):
        rel = str(edit.get("file") or "")
        search = edit.get("search")
        replace = edit.get("replace")
        if not rel or search is None or replace is None:
            raise FixerError(f"edit {i}: needs file, search and replace")
        if FORBIDDEN_RE.match(rel) or rel.startswith("/") or ".." in rel:
            raise FixerError(f"edit {i}: forbidden path {rel!r}")
        path = (root / rel).resolve()
        if not str(path).startswith(str(root.resolve())):
            raise FixerError(f"edit {i}: path escapes the repo: {rel!r}")
        if not path.is_file():
            raise FixerError(f"edit {i}: no such file {rel!r}")

        current = staged.get(path) or path.read_text()
        hits = current.count(search)
        if hits != 1:
            raise FixerError(
                f"edit {i}: search string appears {hits} times in {rel} (need exactly 1)")
        staged[path] = current.replace(search, replace, 1)
        if rel not in touched:
            touched.append(rel)

    for path, content in staged.items():
        path.write_text(content)
    return touched


# --------------------------------------------------------------------------

def _attempt_meta(reply: dict) -> dict:
    u = reply.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    return {"provider": reply.get("provider"), "finish_reason": reply.get("finish_reason"),
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "reasoning_tokens": det.get("reasoning_tokens"), "latency_s": reply.get("latency_s")}


def _merge_usage(a: dict, b: dict) -> dict:
    out = dict(a or {})
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        out[k] = (a.get(k) or 0) + (b.get(k) or 0)
    return out


def _repair_message(err: Exception) -> str:
    return ("Your previous reply could not be used: " + str(err) +
            "\nRe-emit the FULL corrected JSON object and nothing else — no prose, no "
            "markdown fence. Every \"search\" string must appear character-for-character "
            "exactly once in the file content shown above.")


def run(failing: str, error_text: str, model: str, root: Path,
        dry_run: bool = False) -> dict:
    files = relevant_files(failing, error_text, root)
    if not files:
        raise FixerError("could not locate any source file for the failing tests")
    protected = set(named_paths(failing, error_text))
    prompt = build_prompt(failing, error_text, files, protected)

    # Context guard: a model whose window can't hold prompt + reply can't do the job;
    # skip it loudly rather than let it truncate and silently fail.
    ctx = model_meta(model).get("context_length") or 0
    est_tokens = len(prompt) // 4 + MAX_TOKENS
    if ctx and ctx < est_tokens:
        raise FixerError(f"{model}: context_length {ctx} < needed ~{est_tokens} "
                         f"(prompt+max_tokens) — skipping")

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt}]
    reply = call_messages(model, messages)
    usage = dict(reply["usage"] or {})
    attempts = [_attempt_meta(reply)]

    def _finish(parsed: dict) -> dict:
        parsed["usage"] = usage
        parsed["latency_s"] = sum(a.get("latency_s") or 0 for a in attempts)
        parsed["model"] = model
        parsed["attempts"] = attempts
        return parsed

    try:
        parsed = parse_response(reply["text"])
        if parsed["classification"] != "real_logic_bug" or dry_run:
            parsed["touched"] = []
            return _finish(parsed)
        parsed["touched"] = apply_edits(parsed["edits"], root)
        return _finish(parsed)
    except FixerError as first_err:
        # ONE repair round: show the model its own reply and the exact error, and ask
        # for a corrected JSON object. Mirrors what production would do; the tokens
        # count into this incident's cost. apply_edits is all-or-nothing, so a rejected
        # patch left the tree clean — safe to retry.
        messages.append({"role": "assistant", "content": reply["text"]})
        messages.append({"role": "user", "content": _repair_message(first_err)})
        reply2 = call_messages(model, messages)
        usage = _merge_usage(usage, reply2["usage"] or {})
        attempts.append(_attempt_meta(reply2))
        parsed = parse_response(reply2["text"])          # a 2nd failure propagates out
        if parsed["classification"] != "real_logic_bug" or dry_run:
            parsed["touched"] = []
            return _finish(parsed)
        parsed["touched"] = apply_edits(parsed["edits"], root)
        return _finish(parsed)


def main() -> int:
    p = argparse.ArgumentParser(description="AI half of the CI auto-fixer (#59).")
    p.add_argument("--failing", required=True, help="space-separated pytest ids")
    p.add_argument("--error-file", required=True, help="file holding the pytest output")
    p.add_argument("--model", default=os.environ.get("CI_FIXER_MODEL", DEFAULT_MODEL))
    p.add_argument("--root", default=str(_ROOT))
    p.add_argument("--dry-run", action="store_true", help="classify only, write nothing")
    args = p.parse_args()

    try:
        error_text = Path(args.error_file).read_text(errors="replace")
    except OSError as e:
        print(f"cannot read error file: {e}", file=sys.stderr)
        return 3

    try:
        out = run(args.failing, error_text, args.model, Path(args.root), args.dry_run)
    except FixerError as e:
        print(f"AI fixer failed: {e}", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 — a crash here must not look like "fixed"
        print(f"AI fixer crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    print(json.dumps({k: out[k] for k in
                      ("classification", "reason", "touched", "model", "latency_s")
                      if k in out}))
    if out["classification"] != "real_logic_bug":
        return 2
    return 0 if out["touched"] else 3


if __name__ == "__main__":
    sys.exit(main())
