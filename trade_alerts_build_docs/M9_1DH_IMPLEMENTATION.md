# M9.1DH sharded candidate-run boundary — 2026-09-22 Pacific

The initial M9.1DH implementation added the bounded code needed to keep the retained training-nine run
inside the D-114 memory and restart boundary. A run may be reduced by disjoint
ticker/session parts and merged only when all nine training names are present.
Overlapping parts, held-out names, missing playbooks and changed D-104 switches
are refused. The final record commits separately to each session's complete
retained source identities and candidate decisions, without copying millions of
source ids into the result file.

The initial D-116 inspection contract recorded counts separately for every ticker, every
playbook and normal, half-day and degraded sessions. It stops before full
release when a ticker or playbook has zero usable events, a required day type is
absent, a degraded day is not explicitly skipped, or a consumed field has a
missing or `UNKNOWN` unit. The inspection record keeps `full_run_released`
false; only the later supervisor-owned real-file job may change that boundary
after reading the actual inspection result.

No retained market file was opened and no full job was started in this bounded
implementation session. M9.1DI must connect the verified OHLCV-1m, BBO-1m and
trades folders to these parts, inspect the real 2% sample, and only after a clean
sample start and collect the three detached D-114 shards. It must keep the eight
held-out names sealed and must not calculate fills, returns or supervised
packages.

The focused protected selector set is:

- `tests/trade_alerts_contracts/test_retained_training_candidate_parts.py`
- `tests/trade_alerts_contracts/test_retained_training_candidate_record.py`
- `tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py`
- `tests/trade_alerts_contracts/test_retained_candidate_events.py`

The protected launcher stopped before collection at line 27 with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-etcspm4x'`. It was
not retried. The controller must supply fresh focused, broad acceptance and two
fresh-process recording proof. The new recording selector is
`tests/trade_alerts_contracts/test_retained_training_candidate_parts.py::test_recording_sharded_candidate_contract_is_deterministic` and its output is
`m91dh-retained-training-candidate-parts-proof.json`.

Complete M9.1DH delta:

- `consensus_engine/retained_candidate_events.py`
- `consensus_engine/retained_first_four_candidate_run.py`
- `consensus_engine/retained_training_candidate_record.py`
- `consensus_engine/retained_training_candidate_parts.py`
- `tests/trade_alerts_contracts/test_retained_training_candidate_parts.py`
- `trade_alerts_build_docs/M9_1DH_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`


## Current escalated repair — 2026-09-22 Pacific

The earlier implementation and launcher note above are historical. Independent
review rejected the inspection even though the earlier collected tests passed:
`inspect_retained_candidate_sample` trusted the caller's days and counts, did
not know the full job size, and accepted an arbitrary nonempty field list.
Its passing fixture included a degraded day absent from the part. Its recording
used only `bar_price`. Unavailable decisions also counted as usable events.
Those tests did not establish D-116. Prior failures and attempts are preserved.

The different approach is to reconstruct the entire supplied part from the
sample run before checking it. The declared days must exactly match that part
and belong to the declared full job. Counts come from matching session decisions;
`UNAVAILABLE` never counts as usable. The sample must contain exactly the full
job's 2%, rounded up to whole ticker-sessions. It must still cover every training
name, every playbook and all three day types. Normal and half-day labels are
checked against the session calendar. A degraded annotation cannot add a day
that was never run. The report saves the exact days, counts and commitments to
the full plan and sampled part.

The V2 inspection requires a separate one-moment input snapshot for every
playbook. `candidate_sample_fields` expands the entire typed adapter input:
bar history, request boundaries, conventions, trades, quotes, source metadata,
record identities and disabled rules. It includes every leaf, including leaves
unused on that particular branch, instead of maintaining a caller-selected
field list. Numeric price and size units come from the canonical normalized
record contract; bar price/volume labels must agree with the batch. Each
inspected path, value and unit must match that complete snapshot. Removing a
field, changing its value/unit, duplicating it, omitting a playbook, or citing an
unrelated sampled session/source set is refused. The moment must belong to the
frozen decision grid. Missing consumed prices/times and the OR-failure trade
delay flag are refused. Inapplicable optional slots are printed as absent;
source finality marked UNKNOWN stays UNKNOWN with its dependent rules off.

The new positive examples explicitly supply synthetic NO_EVENT decisions and
synthetic inspected inputs. They prove only the offline contract. The actual
retained producers still emit UNAVAILABLE for missing required inputs; those
outputs cannot establish usable sample counts. No retained files were opened,
no real D-116 pass exists, and no full run was released. The supervisor must
capture the actual adapter inputs and verify full-plan/source provenance against
the retained folders; matching supplied record identities is not independent
verification of the files' contents.

### Verification state

The unchanged protected launcher was attempted for
`tests/trade_alerts_contracts/test_retained_training_candidate_parts.py`.
It stopped before collection at its ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-pzcti01_'
```

It was not retried. No application tests were run outside protection and the
full contracts family was not self-run. Source syntax was checked without
importing the application. The controller must supply fresh focused, broader
acceptance and separate fresh-process recording proof for this repair. Current
phase counts, timings, tested hashes and recording comparisons remain pending;
the controller stage will supply them. No earlier passing count is current
repair proof.

Preserved earlier controller evidence (historical tested source only):

- `/root/trade-alerts-builder/runs/20260922-140831-386423-build/controller-evidence.json`
- Focused selection and artifacts:
  `/root/trade-alerts-builder/runs/20260922-140831-386423-build/published-artifacts-5d895db0a670/summary.json`
- Broad acceptance selection and artifacts:
  `/root/trade-alerts-builder/runs/20260922-140831-386423-build/published-artifacts-88d76ec98c43/summary.json`
- Separate repeatability selections and both run artifacts:
  `/root/trade-alerts-builder/runs/20260922-140831-386423-build/published-artifacts-5fc07f5311d2/summary.json`

Each publication's `publication.json` retains its original file list and hashes.
The source/test edits in this repair invalidate that earlier proof for current
acceptance; they do not erase it. The exact recording selector remains
`tests/trade_alerts_contracts/test_retained_training_candidate_parts.py::test_recording_sharded_candidate_contract_is_deterministic`.
Its named output remains `m91dh-retained-training-candidate-parts-proof.json`;
the expanded proof now includes the full per-playbook field snapshots and sample
size/identity commitments. The controller must collect and compare it in both
fresh repeatability runs before anyone claims repeatability.

M9.1DH remains blocked on the real retained-file inspection and detached
three-shard execution, in addition to pending protected verification of this
repair. M9.1DI remains the proposed execution handoff after independent review.
No data, final-validation, live or profit gate is closed. All switches stay off.
The complete milestone delta remains the seven paths listed above.
