#!/usr/bin/env python3
"""Replay the TODO #85 feature-question set through the REAL agent path.

Not a reimplementation: it formats the question with the live
``consensus_engine.main._STEERING_TEMPLATE`` and spawns the same
``openclaw agent --local --json --agent main`` command ``_handle_mention``
spawns. The only thing it skips is the Discord send, so answers can be graded
offline. ``--model`` maps to the same ``--model`` override ``_handle_mention``
uses for a retry, which is how the model race swaps candidates.

Usage:
    python3 scripts/qa_feature_questions.py --out results.jsonl [--model M] [--only Q05,Q06]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUESTION_SET = REPO / ".omx/evidence/todo-85/question-set.md"
SESSION_DIR = Path("/home/openclaw/.openclaw/agents/main/sessions")
# The channel the owner actually asks in; the steering template embeds it in the
# chat_memory_rollups query, so a fake id would change what the agent can recall.
CHAT_CHANNEL_ID = "1510722777923981432"


def parse_question_set(path: Path) -> list[dict]:
    """Pull (id, turns[]) out of the markdown set. Multi-turn blocks carry
    `**turn 1:**` / `**turn 2:**`; single-turn blocks carry `**Question:**`."""
    text = path.read_text()
    blocks = re.split(r"^### ", text, flags=re.M)[1:]
    out = []
    for b in blocks:
        qid = b.split()[0].strip()
        turns = [t.strip().strip('"') for t in re.findall(r"^\*\*turn \d+:\*\*\s*(.+)$", b, re.M)]
        if not turns:
            turns = [t.strip().strip('"') for t in re.findall(r"^\*\*Question:\*\*\s*(.+)$", b, re.M)]
        # strip a trailing italic annotation like *(re-asked, ...)*
        turns = [re.sub(r"\s*\*\(.*\)\*\s*$", "", t) for t in turns]
        if turns:
            out.append({"id": qid, "turns": turns})
    return out


def wrap(content: str, channel_id: str) -> str:
    """Format the question exactly as _handle_mention does."""
    sys.path.insert(0, str(REPO))
    from consensus_engine.main import _STEERING_TEMPLATE
    from consensus_engine.utils.time_context import build_time_context_oneliner
    return _STEERING_TEMPLATE.format(
        tctx=build_time_context_oneliner(),
        ticker_anchor="",
        channel_id=channel_id,
        room_context="",
        content=content.replace("```", "′′′"),
    )


def tools_used(session_id: str) -> list[str]:
    """Every tool call the agent actually made, read back from the session
    transcript openclaw writes: lines are {"type":"message","message":{"role":
    "assistant","content":[{"type":"toolCall","name":...,"arguments":{...}}]}}.

    This is the evidence for "did it open the right file, or guess?" — a run
    whose only call is the disabled `memory_search` answered from thin air.
    """
    f = SESSION_DIR / f"{session_id}.jsonl"
    if not f.exists():
        return []
    seen = []
    for line in f.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "toolCall":
                args = part.get("arguments") or {}
                detail = (args.get("path") or args.get("file_path")
                          or args.get("command") or args.get("query") or "")
                entry = f"{part.get('name')}({str(detail)[:160]})"
                if entry not in seen:
                    seen.append(entry)
    return seen


def spend_so_far() -> float | None:
    """Dollars this OpenRouter key has spent TODAY, read straight from the key
    endpoint. The race is billed against a $3/day cap, so every turn is metered
    and the run stops itself rather than draining the cap on one model."""
    import urllib.request
    sys.path.insert(0, str(REPO))
    from consensus_engine import config as cfg
    key = cfg.get_api_key("openrouter_api_key")
    if not key:
        return None
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return float(json.load(resp)["data"]["usage_daily"])
    except Exception:
        return None


def run_turn(message: str, session_id: str, model: str | None, timeout: int) -> dict:
    argv = ["openclaw", "agent", "--local", "--json", "--agent", "main",
            "--session-id", session_id, "--message", message, "--timeout", str(timeout)]
    if model:
        # openclaw wants the provider-qualified id (openclaw.json stores
        # "openrouter/openai/gpt-4.1-nano"); config/consensus.yaml stores the bare
        # one and sync_gateway_models.py adds the prefix. Accept either here.
        argv += ["--model", model if model.startswith("openrouter/") else f"openrouter/{model}"]
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 60)
    elapsed = time.monotonic() - t0
    reply, meta = "", {}
    try:
        doc = json.loads(proc.stdout.strip())
        reply = "\n".join(p.get("text", "") for p in doc.get("payloads", []) if p.get("text")).strip()
        m = doc.get("meta", {})
        meta = {
            "model": m.get("agentMeta", {}).get("model"),
            "aborted": m.get("aborted"),
            "stop_reason": m.get("stopReason"),
            "prompt_tokens": m.get("agentMeta", {}).get("promptTokens"),
            "usage": m.get("agentMeta", {}).get("usage"),
        }
    except ValueError:
        reply = f"(unparseable stdout) {proc.stdout[:500]}"
    return {"reply": reply or "(agent returned no content)", "elapsed_s": round(elapsed, 1),
            "meta": meta, "stderr_tail": proc.stderr[-300:] if proc.returncode else ""}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=None, help="model override; omit to use the live chain")
    ap.add_argument("--only", default="", help="comma-separated question ids")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--tag", default="", help="label for this run in the output")
    ap.add_argument("--max-spend", type=float, default=0.50,
                    help="stop the run once it has cost this many dollars")
    args = ap.parse_args()

    questions = parse_question_set(QUESTION_SET)
    if args.only:
        want = {q.strip() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in want]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    start_spend = spend_so_far()
    if start_spend is not None:
        print(f"  spend meter: ${start_spend:.4f} used today, budget ${args.max_spend:.2f}",
              flush=True)
    with out.open("w") as fh:
        for q in questions:
            now = spend_so_far()
            if start_spend is not None and now is not None and now - start_spend > args.max_spend:
                print(f"  STOPPING before {q['id']}: spent ${now - start_spend:.4f} "
                      f"of the ${args.max_spend:.2f} budget", flush=True)
                break
            # One session per question so turn 2 lands with turn 1 in context,
            # and so an earlier question can never bleed into a later one.
            session_id = f"qa85-{args.tag or 'run'}-{q['id']}-{uuid.uuid4().hex[:6]}"
            rec = {"id": q["id"], "model_requested": args.model or "(live chain)",
                   "tag": args.tag, "session_id": session_id, "turns": []}
            for i, turn in enumerate(q["turns"], 1):
                print(f"  {q['id']} turn {i}: {turn[:70]}...", flush=True)
                r = run_turn(wrap(turn, CHAT_CHANNEL_ID), session_id, args.model, args.timeout)
                r["turn"] = i
                r["question"] = turn
                rec["turns"].append(r)
            rec["tools_seen"] = tools_used(session_id)
            after = spend_so_far()
            if now is not None and after is not None:
                rec["cost_usd"] = round(after - now, 5)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"  -> {q['id']} done ({sum(t['elapsed_s'] for t in rec['turns']):.0f}s"
                  f"{', $%.4f' % rec['cost_usd'] if 'cost_usd' in rec else ''})", flush=True)
    end_spend = spend_so_far()
    if start_spend is not None and end_spend is not None:
        print(f"run cost: ${end_spend - start_spend:.4f}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
