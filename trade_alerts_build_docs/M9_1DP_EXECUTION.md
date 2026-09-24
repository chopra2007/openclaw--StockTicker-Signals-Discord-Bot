# M9.1DP exact D-116 sample result — 2026-09-22 Pacific

Status: **blocked by the current producers, not by missing retained market data**.

The supervisor ran the exact preserved 47-session command from the M9.1DK
attempt after independent review accepted the M9.1DL reader proof. The command
finished with exit code zero. It planned all 47 required training
ticker-sessions, built 46 normal or half-day sessions, and explicitly skipped
the degraded `NVDA` 2025-10-10 session. It read 789,181 matching market records
and emitted 184 decisions. Every decision was `UNAVAILABLE`, leaving zero
usable decisions for every one of the nine training tickers and all four
current playbooks. `full_run_released` remained false.

The exact result is preserved outside the working tree at
`/root/trade-alerts-builder/supervisor-evidence/m91dn-d116-sample-20260922-1756.json`.
That record identifies the raw Codex execution log, exact event and output
ordinals, and exact output text for both the sample and coverage count. The
older M9.1DK build log is identified only as the source of the preserved
command template; its failed result is not claimed as this successful run.
The preserved sample command SHA256 is
`61009ecc26e162b9178ba200c6b9ae49d00632bc6080aa56b03f92ca3eef458c`.

A separate read-only coverage count checked the cause. All 47 planned sessions
have both retained quote and trade records. It counted 22,695 matching BBO-1m
records and 833,962 matching trade records. There were no missing quote
sessions and no missing trade sessions. Available/degraded counts were also
preserved in the supervisor evidence record and its identified raw execution
log.

D-116's per-day-type and consumed-field unit inspection was not reached.
Its zero-usable hard stop was reached for every ticker and every playbook.
The remaining required checks are still unperformed: separate usable counts
for normal, half-day and degraded sessions, and one moment's complete consumed
field list with unit labels for each adapter. The degraded-session skip is
recorded, but is not a passing day-type inspection. No complete field/unit
output exists for this run; no missing or unknown unit has been accepted.
These checks remain required after the producer inputs are connected.

The real stop is the current producer boundary. Both
`retained_first_two_producers.py` and `retained_remaining_producers.py` always
return `UNAVAILABLE` while required non-market inputs remain unknown. These
include halt status, macro blackout, catalyst coverage, ATR, quote-decision and
confidence inputs; the latter producers also preserve missing parent evidence
where applicable. The three D-114 shards cannot be released until those inputs
are connected or the frozen rules explicitly determine that a decision can be
made without them. No input may be invented merely to make the sample pass.

No held-out name was opened. No fill, return or supervised package was
calculated. No provider call or spending occurred. No full shard was started.
All switches remain off.

M9.1DQ is the bounded next step: connect the already-authorized offline sources
for the required producer inputs, preserve every genuinely unavailable field,
and rerun the same sample only after protected tests and independent review.

## Corrected raw evidence identity

The review found a source-attribution error: the earlier evidence pointed to
the command-template log as if it held the successful result. This repair
reads the original supervisor execution events and publishes their output
below. It does not rerun the sample, coverage scan or application.

The failed run remains at
`/root/trade-alerts-builder/runs/20260922-170321-850330-build/build.log`,
line 28, completed command `item_12`, exit code 1. Its final error is:

```text
consensus_engine.trade_alerts_models.RecordError: row 23753 session 2025-10-05 is not in the retained condition list
```

That failure remains the M9.1DK result. It contains no successful sample output.
The supervisor result cited above retains `milestone: M9.1DN` as its original
label; this M9.1DP record reconciles that evidence without relabelling the raw
run or claiming M9.1DN acceptance.

The actual successful execution and separate coverage scan are in:
`/root/.codex/sessions/2026/09/20/rollout-2026-09-20T23-14-42-01a0c29a-3b4c-74f1-86ba-9a320f3decc3.jsonl`.
The ordinals below are the log's stored `ordinal` values, not line numbers.

Sample: completed command event ordinal `28989`, output ordinal `28990`,
exit code 0, completed 2026-09-22 17:55:02 Pacific. Its command extracts the
preserved sample command from the failed log and executes it; the failed log
is only the template source. Original sample output:

```text
{'planned_sessions': 47, 'required_2_percent': 47, 'built_sessions': 46, 'skipped': (('NVDA', '2025-10-10', 'DEGRADED_SESSION'),), 'without_prior_count': 9, 'events': 184, 'statuses': {'UNAVAILABLE': 184}, 'per_ticker_usable': {'NVDA': 0, 'MSFT': 0, 'AAPL': 0, 'TSLA': 0, 'LLY': 0, 'SPY': 0, 'QQQ': 0, 'XLV': 0, 'USO': 0}, 'per_playbook_usable': {'CRVOL_ORB5': 0, 'HOD_COMP_RS': 0, 'OR_FAILURE_REV': 0, 'FIRST_PULLBACK_VWAP': 0}, 'market_records': 789181, 'full_run_released': False}
```

Coverage: completed command event ordinal `29083`, output ordinal `29084`,
exit code 0, completed 2026-09-22 18:02:51 Pacific. The original read-only
command counts the nine training names on 2025-10-01, 2025-10-02, 2025-10-03,
2025-10-06 and 2025-10-07, plus NVDA 2025-10-10 and SPY 2025-11-28, in the
retained October/November BBO-1m and trades files. Original coverage output:

```text
schema_totals {'bbo-1m': 22695, 'trades': 833962}
covered_keys {'bbo-1m': 47, 'trades': 47}
conditions {('bbo-1m', 'AVAILABLE'): 22050, ('bbo-1m', 'DEGRADED'): 645, ('trades', 'AVAILABLE'): 767131, ('trades', 'DEGRADED'): 66831}
missing_bbo []
missing_trades []
```

This establishes record presence for each selected session, not complete or
qualified coverage. The coverage scan includes degraded records; its totals
are separate from the sample's consumed-record total. Neither count proves
field units, source finality, original availability or usable decisions.
Source-gap dependents remain OFF and untested.

## Records-only verification

The controller record is
`/root/trade-alerts-builder/runs/20260922-180317-176814-build/controller-evidence.json`.
Its published `tests` fields are copied without substituting sample counts:

```json
{
  "artifacts_path": "",
  "exit_code": 0,
  "runs": 0,
  "selection_reason": "blocked milestone changed records only; no product tests required",
  "selectors": [],
  "test_count": 0,
  "wall_seconds": 0.0
}
```

No phase, focused stage or repeatability section was supplied for this
records-only milestone. There is no product-test pass claimed here. This
repair changes only this record and ROADMAP; code, tests, protected inputs,
previous failures and attempt history remain unchanged. Independent review
must confirm the blocked assessment and M9.1DQ's bounded eligibility.
