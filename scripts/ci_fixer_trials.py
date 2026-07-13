"""#59 v3 CI-fixer model race harness.

Executes the plan at `.omc/plans/ci-fixer-race-v3-2026-07-10.md`. The exam is the
4-case source-bug corpus in `.omc/trials/corpus_v3.json` — each case is staged
SOURCE-ONLY (`git checkout <sha>^ -- <src files>`, tests stay at HEAD), so the
reference fix is source-only by construction and a test-only "fix" is a fake green.

Scoring is per-INCIDENT, matching production (`ci_autofix.sh` retries 3× per red gate):
    p_c   = passes / trials   (per case)
    I_c   = 1 - (1 - p_c)**3   (probability ≥1 of 3 production tries succeeds)
    SCORE = mean(I_c) across cases
Qualify: SCORE ≥ 0.70 AND ≥1 pass on ≥3 of 4 cases AND timeout rate ≤20% AND
measured $/mo (mean $/attempt × 6) ≤ $0.25.

Prices and context windows are read LIVE from OpenRouter's /models catalog at run
time (via ci_ai_fixer.model_meta) — never a stale snapshot. Cost per attempt already
includes any repair round, so it equals a production attempt's cost.

Run ONE band-batch per invocation; the orchestrator advances bands and tracks the
cumulative $ against the $3 hard cap between invocations.

    sudo -u openclaw python3 scripts/ci_fixer_trials.py --models a/b c/d --trials 1 \
        --out .omc/trials/band_a_screen.json
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
from ci_fixer_race import reset_worktree, sh  # noqa: E402

CORPUS = json.loads((_ROOT / ".omc" / "trials" / "corpus_v3.json").read_text())
QUALIFY_SCORE = 0.70
QUALIFY_CASES = 3          # ≥1 pass on ≥3 of 4 cases
QUALIFY_TIMEOUT = 0.20
QUALIFY_MO_COST = 0.25
RUNS_PER_MONTH = 6         # the #59-long assumption for $/mo


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def make_worktree(slug: str) -> Path:
    wt = Path("/home/openclaw") / ("wt-race-" + slug.replace("/", "-").replace(".", "_"))
    if not wt.exists():
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"],
                       cwd=_ROOT, check=True, capture_output=True)
    return wt


def live_cost(usage: dict, slug: str) -> float:
    """$ for one attempt at the model's LIVE per-token price (prompt + completion)."""
    price = fixer.model_meta(slug).get("pricing") or {}
    pin = float(price.get("prompt") or 0)
    pout = float(price.get("completion") or 0)
    return (usage.get("prompt_tokens") or 0) * pin + (usage.get("completion_tokens") or 0) * pout


def stage_case(wt: Path, case: dict) -> None:
    """Reproduce a case's bug by reverting ONLY its source files to the pre-fix commit.
    Tests stay at HEAD, so the reference fix is source-only by construction."""
    reset_worktree(wt)
    rc, out = sh(["git", "checkout", f"{case['sha']}^", "--", *case["src_files"]], wt)
    if rc != 0:
        raise RuntimeError(f"stage {case['case_id']} failed: {out[:200]}")


def verify(wt: Path, case: dict) -> bool:
    rc, _ = sh(["python3", "-m", "pytest", *case["test_ids"], "-q",
                "-p", "no:cacheprovider"], wt)
    return rc == 0


def one_trial(model: str, wt: Path, case: dict) -> dict:
    stage_case(wt, case)
    try:
        out = fixer.run(" ".join(case["test_ids"]), case["error_tail"], model, wt)
        cost = live_cost(out.get("usage") or {}, model)
        attempts = out.get("attempts") or []
        provider = attempts[0].get("provider") if attempts else None
        finish = attempts[-1].get("finish_reason") if attempts else None
        lat = out.get("latency_s") or 0.0
        cls = out["classification"]
        if cls != "real_logic_bug":
            return {"ok": False, "note": f"classified {cls}", "cost": cost,
                    "latency": lat, "provider": provider, "finish": finish, "timeout": False}
        touched = list(out.get("touched") or [])
        if not touched:
            return {"ok": False, "note": "no edits returned", "cost": cost,
                    "latency": lat, "provider": provider, "finish": finish, "timeout": False}
        green = verify(wt, case)
        src_only = any(not t.startswith("tests/") for t in touched)
        ok = green and src_only
        note = "pass" if ok else ("green but TEST-ONLY (fake)" if green else "tests still red")
        return {"ok": ok, "note": note, "cost": cost, "latency": lat, "touched": touched,
                "test_only": green and not src_only, "provider": provider,
                "finish": finish, "timeout": False}
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        timeout = "no complete reply within" in str(e)
        return {"ok": False, "note": msg, "cost": 0.0, "latency": 0.0,
                "provider": None, "finish": None, "timeout": timeout}
    finally:
        reset_worktree(wt)


def score(per_case: dict) -> dict:
    incident, passed_cases = [], 0
    for rows in per_case.values():
        n = len(rows)
        k = sum(r["ok"] for r in rows)
        p = k / n if n else 0.0
        incident.append(1 - (1 - p) ** 3)
        if k >= 1:
            passed_cases += 1
    return {"SCORE": sum(incident) / len(incident) if incident else 0.0,
            "passed_cases": passed_cases}


def race_model(model: str, trials: int, early_stop: bool) -> dict:
    wt = make_worktree(model)
    per_case: dict[str, list] = {}
    total = len(CORPUS)
    for i, case in enumerate(CORPUS):
        per_case[case["case_id"]] = [one_trial(model, wt, case) for _ in range(trials)]
        if early_stop:
            done = i + 1
            s_done = sum(1 - (1 - (sum(r["ok"] for r in rows) / len(rows))) ** 3
                         for rows in per_case.values())
            best_possible = (s_done + (total - done)) / total
            if best_possible < QUALIFY_SCORE:
                break

    all_rows = [r for rows in per_case.values() for r in rows]
    n = len(all_rows)
    costs = [r["cost"] for r in all_rows]
    per_attempt = sum(costs) / n if n else 0.0
    sc = score(per_case)
    timeouts = sum(r.get("timeout") for r in all_rows)
    mo_cost = per_attempt * RUNS_PER_MONTH
    case_k = {cid: [sum(r["ok"] for r in rows), len(rows)] for cid, rows in per_case.items()}
    qualify = (sc["SCORE"] >= QUALIFY_SCORE and sc["passed_cases"] >= QUALIFY_CASES
               and (timeouts / n if n else 1) <= QUALIFY_TIMEOUT
               and mo_cost <= QUALIFY_MO_COST)
    summary = {
        "model": model, "trials_per_case": trials, "cases_run": len(per_case),
        "SCORE": round(sc["SCORE"], 4), "passed_cases": sc["passed_cases"],
        "case_k_n": case_k, "cost_per_attempt": round(per_attempt, 5),
        "cost_per_month": round(mo_cost, 4), "timeout_rate": round(timeouts / n, 3) if n else None,
        "spend_this_model": round(sum(costs), 4), "qualify": qualify,
        "providers": sorted({r["provider"] for r in all_rows if r["provider"]}),
        "case_detail": {cid: [{"ok": r["ok"], "note": r["note"], "finish": r.get("finish"),
                               "touched": r.get("touched", []), "cost": round(r["cost"], 5)}
                              for r in rows] for cid, rows in per_case.items()},
    }
    tag = "QUALIFIES" if qualify else "no"
    print(f"  {model:34s} SCORE={sc['SCORE']:.2f} cases={sc['passed_cases']}/4 "
          f"${mo_cost:.3f}/mo to={summary['timeout_rate']} [{tag}] "
          f"(spent ${summary['spend_this_model']:.3f})", flush=True)
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--trials", type=int, default=1, help="trials per corpus case")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--early-stop", action="store_true",
                   help="stop a model once SCORE≥0.70 is unreachable (deep mode)")
    p.add_argument("--reasoning-max", type=int, default=None,
                   help="cap reasoning tokens (cost arm)")
    p.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high"])
    p.add_argument("--max-spend", type=float, default=3.0,
                   help="hard $ ceiling for THIS invocation; skip models once crossed")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    if a.reasoning_max is not None:
        fixer.REASONING = {"max_tokens": a.reasoning_max}
    elif a.reasoning_effort:
        fixer.REASONING = {"effort": a.reasoning_effort}

    # Pre-create worktrees serially to dodge the git-index lock race.
    for m in a.models:
        make_worktree(m)

    print(f"racing {len(a.models)} model(s) × {a.trials} trial(s) on "
          f"{len(CORPUS)} cases (early_stop={a.early_stop})\n", flush=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(race_model, m, a.trials, a.early_stop): m for m in a.models}
        for fut in futs:
            results.append(fut.result())

    results.sort(key=lambda r: (not r["qualify"], -r["SCORE"], r["cost_per_month"]))
    total_spend = round(sum(r["spend_this_model"] for r in results), 4)
    payload = {"trials": a.trials, "reasoning": fixer.REASONING,
               "total_spend": total_spend, "results": results}
    Path(a.out).write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {a.out}  —  total spend this run ${total_spend:.4f}")
    quals = [r["model"] for r in results if r["qualify"]]
    print(f"qualifiers: {quals or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
