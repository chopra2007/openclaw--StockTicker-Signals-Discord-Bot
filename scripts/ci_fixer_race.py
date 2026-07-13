"""#59: race cheap OpenRouter models on the job the CI auto-fixer actually does.

Cheap alone is worthless if the model can't fix a test. The selection rule (user,
2026-07-08): **capability is a GATE, not a score**. Any model that can't clear the
bar is out at any price; among those that clear it, take the cheapest.

The corpus is real, not toy:
  * `undeclared_dependency` — the 2026-07-02 pyarrow run (pandas' "Missing optional
    dependency" phrasing, the real signature the deterministic layer keys on).
  * `flaky` — the 2026-07-01 market-command test, which fails only when this VPS's
    IP is throttled by yfinance ("Not enough closes to compute trend").
  * `real_logic_bug` — `test_sunday_recap_and_addon_restart_safe`, the frozen-date
    bug that reddened 12 of the 13 red gates in the log history. Reproduced by
    reverting its real fix (db47044) in a scratch git worktree.

Scoring: classification correctness on all three, then — only for the real bug —
whether the model's edits actually make the test pass without breaking `.test-baseline`.
Cost and latency are tiebreakers among models that pass, never a reason to pick one
that fails.

    python3 scripts/ci_fixer_race.py --worktree /path/to/scratch/worktree
    python3 scripts/ci_fixer_race.py --models a/b c/d --out results.md
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import ci_ai_fixer as fixer  # noqa: E402

# Cheap + coding-capable + a different family from the code's author (never anthropic/*).
# Live OpenRouter prices, $ per million tokens, read 2026-07-09.
CANDIDATES = [
    # slug,                          in $/M, out $/M
    ("qwen/qwen3-coder-next",          0.110, 0.800),
    ("deepseek/deepseek-chat-v3.1",    0.210, 0.790),
    ("z-ai/glm-4.5-air",               0.130, 0.850),
]

REAL_BUG_TEST = "tests/test_wolf_digest.py::test_sunday_recap_and_addon_restart_safe"
REAL_BUG_FIX_COMMIT = "db47044"

PYARROW_ERROR = """\
tests/test_market_store.py::test_parquet_roundtrip FAILED
E   ImportError: Missing optional dependency 'pyarrow'. pyarrow is required for
E   parquet support. Use pip or conda to install pyarrow.
consensus_engine/market_data/store.py:41: in _write_parquet
    df.to_parquet(path, index=False)
=========================== short test summary info ============================
FAILED tests/test_market_store.py::test_parquet_roundtrip - ImportError: Missing optional dependency 'pyarrow'
"""

FLAKY_ERROR = """\
tests/test_market_command.py::test_market_command_renders_all_four_reads FAILED
[F3] Not enough closes to compute trend (got 19, need 220)
[F3] Not enough closes to compute trend (got 21, need 220)
    summary = await _seed_temp_db()
>   assert summary["sector_rs_daily"] > 0
E   assert 0 > 0
tests/test_market_command.py:118: AssertionError
=========================== short test summary info ============================
FAILED tests/test_market_command.py::test_market_command_renders_all_four_reads - assert 0 > 0
"""


def sh(cmd: list[str], cwd: Path, timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def reset_worktree(wt: Path) -> None:
    """`git checkout -- .` restores the tree FROM the index, so it cannot undo a
    staged `git revert --no-commit`. Reset the index too, or every model after the
    first races against the previous model's leftovers."""
    sh(["git", "revert", "--abort"], wt)
    sh(["git", "reset", "--hard", "HEAD"], wt)
    sh(["git", "clean", "-fd"], wt)


def stage_real_bug(wt: Path) -> str:
    """Revert the real fix so the historical failure reappears. Returns pytest output."""
    reset_worktree(wt)
    rc, out = sh(["git", "revert", "--no-commit", REAL_BUG_FIX_COMMIT], wt)
    if rc != 0:
        raise SystemExit(f"could not stage the real bug: {out[:400]}")
    rc, out = sh(["python3", "-m", "pytest", REAL_BUG_TEST, "-q", "--tb=short",
                  "-p", "no:cacheprovider"], wt)
    if rc == 0:
        raise SystemExit("the staged bug does not fail — the corpus is invalid")
    return out


def verify_real_fix(wt: Path) -> tuple[bool, str]:
    """Did the edits make the failing test pass? Then: did they break the baseline?"""
    rc, out = sh(["python3", "-m", "pytest", REAL_BUG_TEST, "-q", "-p", "no:cacheprovider"], wt)
    if rc != 0:
        return False, "the failing test still fails"
    # Cheap regression guard: the rest of that test file must stay green.
    rc2, out2 = sh(["python3", "-m", "pytest", "tests/test_wolf_digest.py", "-q",
                    "-p", "no:cacheprovider"], wt)
    if rc2 != 0:
        return False, "fixed the target test but broke a sibling test"
    return True, "target test passes, siblings still green"


def cost_usd(usage: dict, price_in: float, price_out: float) -> float:
    pin = (usage.get("prompt_tokens") or 0) / 1e6 * price_in
    pout = (usage.get("completion_tokens") or 0) / 1e6 * price_out
    return pin + pout


def race_one(model: str, price_in: float, price_out: float, wt: Path,
             real_bug_error: str) -> dict:
    row: dict = {"model": model, "classified": {}, "cost": 0.0, "latency": 0.0,
                 "patch_ok": False, "patch_note": "", "errors": []}

    # --- classification-only cases (no worktree writes) ---
    for name, error, expected in (
        ("undeclared_dependency", PYARROW_ERROR, "undeclared_dependency"),
        ("flaky", FLAKY_ERROR, "flaky"),
    ):
        try:
            files = fixer.relevant_files("", error, _ROOT)
            prompt = fixer.build_prompt("(see traceback)", error, files)
            reply = fixer.call_model(model, prompt)
            parsed = fixer.parse_response(reply["text"])
            row["classified"][name] = parsed["classification"]
            row["cost"] += cost_usd(reply["usage"], price_in, price_out)
            row["latency"] += reply["latency_s"]
        except Exception as e:  # noqa: BLE001
            row["classified"][name] = f"ERROR"
            row["errors"].append(f"{name}: {type(e).__name__}: {e}")

    # --- the real bug: classify AND patch ---
    reset_worktree(wt)
    sh(["git", "revert", "--no-commit", REAL_BUG_FIX_COMMIT], wt)
    try:
        out = fixer.run(REAL_BUG_TEST, real_bug_error, model, wt)
        row["classified"]["real_logic_bug"] = out["classification"]
        row["cost"] += cost_usd(out["usage"], price_in, price_out)
        row["latency"] += out["latency_s"]
        if out["classification"] == "real_logic_bug" and out["touched"]:
            ok, note = verify_real_fix(wt)
            row["patch_ok"], row["patch_note"] = ok, note
        else:
            row["patch_note"] = ("classified as " + out["classification"]
                                 if out["classification"] != "real_logic_bug"
                                 else "no edits returned")
    except Exception as e:  # noqa: BLE001
        row["classified"].setdefault("real_logic_bug", "ERROR")
        row["patch_note"] = f"{type(e).__name__}: {e}"
        row["errors"].append(f"real_logic_bug: {type(e).__name__}: {e}")
    finally:
        reset_worktree(wt)

    row["class_score"] = sum(
        1 for k, v in row["classified"].items() if v == k)
    return row


def clears_gate(r: dict) -> bool:
    """The capability gate = the job the model is ACTUALLY asked to do in production.

    `ci_autofix.sh` only reaches the AI branch after its deterministic layers have
    already ruled out a missing package AND reproduced the failure locally twice (so
    it is not flaky). The model therefore never has to recognise a flaky test — that
    column is reported for interest, not scored. What it must do: see a real logic bug
    for what it is, and patch it so the test passes and its siblings stay green.
    """
    return (r["classified"].get("undeclared_dependency") == "undeclared_dependency"
            and r["classified"].get("real_logic_bug") == "real_logic_bug"
            and r["patch_ok"])


def render(rows: list[dict]) -> str:
    lines = [
        "# CI auto-fixer model race (#59)",
        "",
        "Capability is a **gate**, not a score. Among models that clear the bar, the "
        "cheapest wins; a model that fails it is out at any price.",
        "",
        "**The gate** is the job the fixer actually does: `ci_autofix.sh` reaches the AI "
        "branch only after it has ruled out a missing package and reproduced the failure "
        "locally twice. So the model must (a) recognise a real logic bug and (b) patch it "
        "so the failing test passes and its siblings stay green. The `flaky` column is "
        "informational — the deterministic layer catches those before a model ever sees them.",
        "",
        "| model | dep | flaky (not scored) | real bug | patch passes? | $ / race | latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        c = r["classified"]
        tick = lambda k: "✅" if c.get(k) == k else f"❌ {c.get(k, '—')}"  # noqa: E731
        patch = "✅ yes" if r["patch_ok"] else f"❌ {r['patch_note'][:44]}"
        lines.append(
            f"| `{r['model']}` | {tick('undeclared_dependency')} | {tick('flaky')} | "
            f"{tick('real_logic_bug')} | {patch} | ${r['cost']:.4f} | {r['latency']:.0f}s |")

    passers = [r for r in rows if clears_gate(r)]
    lines.append("")
    if passers:
        win = min(passers, key=lambda r: r["cost"])
        lines.append(f"**Winner: `{win['model']}`** — cleared the capability gate at the "
                     f"lowest cost (${win['cost']:.4f} for the whole race).")
        others = [r["model"] for r in passers if r["model"] != win["model"]]
        if others:
            lines.append(f"Also cleared it, but cost more: {', '.join('`%s`' % m for m in others)}.")
    else:
        lines.append("**No model cleared the capability gate.** Do not wire an AI branch on "
                     "a model that cannot do the job — keep escalating a real logic bug to a "
                     "human, which is exactly what the script does today.")
    errs = [e for r in rows for e in r["errors"]]
    if errs:
        lines += ["", "### Errors seen", ""] + [f"- {e}" for e in errs]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Race cheap models on the CI-fixer job (#59).")
    p.add_argument("--worktree", required=True,
                   help="a scratch git worktree of this repo (it gets dirtied and reset)")
    p.add_argument("--models", nargs="*", default=None, help="override the candidate slugs")
    p.add_argument("--out", default=None, help="also write the report here")
    args = p.parse_args()

    wt = Path(args.worktree).resolve()
    if not (wt / ".git").exists():
        raise SystemExit(f"{wt} is not a git worktree")

    cands = CANDIDATES
    if args.models:
        known = {m: (i, o) for m, i, o in CANDIDATES}
        cands = [(m, *known.get(m, (0.0, 0.0))) for m in args.models]

    print(f"staging the real bug in {wt} …", file=sys.stderr)
    real_bug_error = stage_real_bug(wt)
    reset_worktree(wt)
    print("corpus verified: the staged bug fails as expected.\n", file=sys.stderr)

    rows = []
    for model, pin, pout in cands:
        print(f"racing {model} …", file=sys.stderr)
        row = race_one(model, pin, pout, wt, real_bug_error)
        rows.append(row)
        print(f"  classification {row['class_score']}/3, patch_ok={row['patch_ok']}, "
              f"${row['cost']:.4f}, {row['latency']:.0f}s", file=sys.stderr)

    report = render(rows)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report + "\n")
    Path(_ROOT / ".omc").mkdir(exist_ok=True)
    (_ROOT / ".omc" / "ci_fixer_race_raw.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
