"""#59 re-race: does ANY model reliably do the CI-fixer job? (n trials, real field)

The first race (2026-07-09) put three bargain-tier slugs on the board and shipped the
least-bad of them at 1 pass in 5. That inverted the selection rule:

    Capability is a GATE, not a score. Any model that can't clear the bar is out at
    any price. Among those that DO clear it, take the cheapest.

So this run spans three price tiers and asks the only question that matters first:
*is this job reliably solvable at all?* Then it walks DOWN in price to the cheapest
model that still clears the bar.

Each model gets its own git worktree, so trials run in parallel without racing each
other's leftovers. Every trial is verified by actually running the test.

Note: max_tokens / deadline are raised above production defaults so reasoning models
aren't truncated mid-thought. The winner is re-verified at production settings.

    sudo -u openclaw python3 scripts/ci_fixer_trials.py --trials 5
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import ci_ai_fixer as fixer  # noqa: E402
from ci_fixer_race import (  # noqa: E402
    PYARROW_ERROR,
    REAL_BUG_FIX_COMMIT,
    REAL_BUG_TEST,
    cost_usd,
    reset_worktree,
    sh,
    stage_real_bug,
    verify_real_fix,
)

# slug, in $/M, out $/M, tier — live OpenRouter prices read 2026-07-10.
#
# Chosen on CAPABILITY first (the gate), then price. The prompt is ~45k tokens in and
# ~1k out, so the INPUT price is what drives cost — ranking on output price, as the
# first race did, ranks on the wrong axis. $/month assumes 6 attempts.
#
# `codex/gpt-5.5` is not billed per token: it runs through the logged-in Codex CLI on
# the user's $20 ChatGPT Plus plan. It is the strongest model that plan exposes.
# Re-race field, 2026-07-10: the STRONG coders that fit under the 25¢/mo cap (raised
# from 10¢ by the user same day). Live OpenRouter prices verified against the /models
# catalog on 2026-07-10 — every slug exists, every one ≤25¢/mo at 6 attempts/month.
# Codex and the old cheap/weak field are gone: Codex was a control (retired), and the
# 0/5 bargain models don't belong in a capability race. $/mo comment = 6 * (0.045*in +
# 0.001*out), the ~45k-in / ~1k-out shape this job actually has.
CANDIDATES = [
    ("deepseek/deepseek-v3.2",             0.214,  0.322, "cheap"),   # ~6c/mo
    ("qwen/qwen3-coder-flash",             0.195,  0.975, "cheap"),   # ~6c/mo
    ("deepseek/deepseek-v3.1-terminus",    0.270,  0.950, "cheap"),   # ~8c/mo
    ("mistralai/codestral-2508",           0.300,  0.900, "cheap"),   # ~9c/mo
    ("qwen/qwen3.7-plus",                  0.320,  1.280, "cheap"),   # ~9c/mo
    ("deepseek/deepseek-v4-pro",           0.435,  0.870, "strong"),  # ~12c/mo — already 1/5 pre-audit
    ("z-ai/glm-5",                         0.600,  1.920, "strong"),  # ~17c/mo
    ("qwen/qwen3-coder-plus",              0.650,  3.250, "strong"),  # ~19c/mo
    ("moonshotai/kimi-k2.7-code",          0.720,  3.490, "strong"),  # ~22c/mo
    ("qwen/qwen3-max",                     0.780,  3.900, "strong"),  # ~23c/mo
]

# ROUND 2 (2026-07-10): under-cap coders MISSED in round 1 — round-1 field was the
# stale pre-written TODO list, not a catalog sweep. Highest-value bets first: cheaper
# COUSINS of kimi-k2.7-code (the only round-1 model to clear the bar, 3/3), which are
# all under the 25c cap. Then glm-5.2 (newer+cheaper than the glm-5 that went 1/3),
# Mistral's devstral, and two dedicated coder models. Live OpenRouter prices 2026-07-10.
# Run these EXPLICITLY so round 1 isn't re-burned:
#   sudo -u openclaw python3 scripts/ci_fixer_trials.py --trials 3 --workers 7 \
#     --models moonshotai/kimi-k2.5 moonshotai/kimi-k2 moonshotai/kimi-k2.6 \
#     z-ai/glm-5.2 mistralai/devstral-2512 kwaipilot/kat-coder-pro-v2 arcee-ai/coder-large \
#     --out .omc/ci_fixer_trials_round2.json
CANDIDATES_ROUND2 = [
    ("moonshotai/kimi-k2.5",               0.375,  2.025, "strong"),  # ~11c/mo — kimi cousin
    ("moonshotai/kimi-k2",                 0.570,  2.300, "strong"),  # ~17c/mo — kimi cousin
    ("moonshotai/kimi-k2.6",               0.660,  3.410, "strong"),  # ~20c/mo — kimi cousin
    ("z-ai/glm-5.2",                       0.420,  1.320, "strong"),  # ~12c/mo — newer/cheaper than glm-5 (1/3)
    ("mistralai/devstral-2512",            0.400,  2.000, "strong"),  # ~12c/mo — Mistral coder
    ("kwaipilot/kat-coder-pro-v2",         0.300,  1.200, "strong"),  # ~9c/mo — dedicated coder
    ("arcee-ai/coder-large",               0.500,  0.800, "strong"),  # ~14c/mo — dedicated coder
]
CANDIDATES += CANDIDATES_ROUND2

CODEX_DEADLINE_S = 400.0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% CI on a pass rate. n=5 is thin; report the interval, never a bare %."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def call_codex(model: str, prompt: str, **_kw) -> dict:
    """Route `codex/<model>` through the logged-in Codex CLI instead of OpenRouter.

    Parity with the OpenRouter candidates matters more than showing Codex at its best:
    it gets the identical system+user prompt, an empty read-only cwd, and no project
    config, so it cannot open the repo and out-inform the others. Agentic Codex, free
    to read files and run the test, would very likely do better than this measures.
    """
    import tempfile, time  # noqa: E401
    slug = model.split("/", 1)[1]
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "last.json"
        proc = subprocess.run(
            ["codex", "exec", "-m", slug, "--ignore-user-config", "--ignore-rules",
             "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
             "-C", td, "-o", str(out), "-"],
            input=fixer.SYSTEM + "\n\n" + prompt, text=True,
            capture_output=True, timeout=CODEX_DEADLINE_S)
        text = out.read_text() if out.exists() else ""
    if not text.strip():
        raise fixer.FixerError(f"codex returned nothing (rc={proc.returncode}): "
                               f"{proc.stderr[:200]}")
    # Subscription: no marginal token cost, so usage stays zero by design.
    return {"text": text, "usage": {}, "latency_s": time.time() - t0}


def make_worktree(slug: str) -> Path:
    wt = Path("/home/openclaw") / ("wt-race-" + slug.replace("/", "-").replace(".", "_"))
    if not wt.exists():
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"],
                       cwd=_ROOT, check=True, capture_output=True)
    return wt


def one_trial(model: str, pin: float, pout: float, wt: Path, err: str) -> dict:
    reset_worktree(wt)
    sh(["git", "revert", "--no-commit", REAL_BUG_FIX_COMMIT], wt)
    try:
        out = fixer.run(REAL_BUG_TEST, err, model, wt)
        cls = out["classification"]
        cost = cost_usd(out["usage"], pin, pout)
        if cls != "real_logic_bug":
            return {"ok": False, "note": f"classified as {cls}", "cost": cost,
                    "latency": out["latency_s"]}
        if not out["touched"]:
            return {"ok": False, "note": "no edits returned", "cost": cost,
                    "latency": out["latency_s"]}
        ok, note = verify_real_fix(wt)
        # A patch that only weakens a test is a FAKE green, not a fix. Record where the
        # edits landed and the diff itself, so a "pass" can be audited rather than
        # trusted. `git diff` here is exactly the model's edits: the staged revert put
        # the buggy code in the index, so the worktree delta is the model's alone.
        touched = list(out["touched"])
        _, diff = sh(["git", "diff"], wt)
        return {"ok": ok, "note": note, "cost": cost, "latency": out["latency_s"],
                "touched": touched,
                "test_only": bool(touched) and all(t.startswith("tests/") for t in touched),
                "diff": diff[:4000]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"{type(e).__name__}: {e}", "cost": 0.0, "latency": 0.0}
    finally:
        reset_worktree(wt)


def race_model(model: str, pin: float, pout: float, tier: str, trials: int) -> dict:
    wt = make_worktree(model)
    err = stage_real_bug(wt)
    reset_worktree(wt)

    # One sample of the dependency case — part of the gate, but the deterministic
    # layer catches it in production, so it does not need n trials.
    try:
        files = fixer.relevant_files("", PYARROW_ERROR, _ROOT)
        reply = fixer.call_model(model, fixer.build_prompt("(see traceback)", PYARROW_ERROR, files))
        dep = fixer.parse_response(reply["text"])["classification"]
    except Exception as e:  # noqa: BLE001
        dep = f"ERROR: {type(e).__name__}"

    rows = [one_trial(model, pin, pout, wt, err) for _ in range(trials)]
    passes = sum(r["ok"] for r in rows)
    lo, hi = wilson(passes, trials)
    per_trial = sum(r["cost"] for r in rows) / max(1, len(rows))
    print(f"  {model:34s} {passes}/{trials} pass  ${per_trial:.4f}/attempt", flush=True)
    return {
        "model": model, "tier": tier, "price_out": pout, "dep_class": dep,
        "trials": trials, "passes": passes, "wilson_lo": lo, "wilson_hi": hi,
        "cost_per_attempt": per_trial,
        "latency_mean": sum(r["latency"] for r in rows) / max(1, len(rows)),
        "notes": [r["note"] for r in rows],
        # passes_source_only excludes fake greens that merely weakened a test.
        "passes_source_only": sum(1 for r in rows if r["ok"] and not r.get("test_only")),
        "test_only_passes": sum(1 for r in rows if r["ok"] and r.get("test_only")),
        "trial_detail": [{"ok": r["ok"], "touched": r.get("touched", []),
                          "test_only": r.get("test_only"), "diff": r.get("diff", "")}
                         for r in rows],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=16000)
    p.add_argument("--deadline", type=float, default=300.0)
    p.add_argument("--models", nargs="*", default=None)
    p.add_argument("--out", default=".omc/ci_fixer_trials_raw.json")
    a = p.parse_args()

    # Headroom so a reasoning model isn't truncated mid-thought. call_model binds its
    # deadline default at def time, so wrap it rather than patching the constant.
    fixer.MAX_TOKENS = a.max_tokens
    _orig = fixer.call_model

    def _dispatch(m: str, prompt: str, **kw):
        if m.startswith("codex/"):
            return call_codex(m, prompt, **kw)
        return _orig(m, prompt, deadline_s=a.deadline, **kw)

    fixer.call_model = _dispatch

    cands = CANDIDATES
    if a.models:
        keep = set(a.models)
        cands = [c for c in CANDIDATES if c[0] in keep]

    print(f"racing {len(cands)} models x {a.trials} trials on {REAL_BUG_TEST}\n", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(lambda c: race_model(c[0], c[1], c[2], c[3], a.trials), cands))

    rows.sort(key=lambda r: (-r["passes"], r["price_out"]))
    Path(a.out).write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
