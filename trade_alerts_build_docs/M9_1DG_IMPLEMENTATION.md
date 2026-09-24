# M9.1DG candidate-boundary record implementation — 2026-09-22 Pacific

M9.1DG adds the immutable record used for the concrete retained training-nine
candidate run. It records candidate, no-event and unavailable totals by
playbook and ticker. It also records the exact count and SHA256 commitment for
the full retained source-identity set and a separate SHA256 commitment for the
full candidate-event stream.

The record keeps original availability, finality, correction and point-in-time
membership dependent rules OFF and labelled untested. It records that held-out
names were not opened and that no fill, return or supervised package was
calculated. An identical retry is allowed; a conflicting output is refused.

Focused coverage is
`tests/trade_alerts_contracts/test_retained_training_candidate_record.py`. Its
recording selector is
`tests/trade_alerts_contracts/test_retained_training_candidate_record.py::test_recording_training_candidate_boundary_is_deterministic`, and its output is
`m91dg-retained-training-candidate-record.json`.

Complete M9.1DG delta so far:

- `consensus_engine/retained_training_candidate_record.py`
- `tests/trade_alerts_contracts/test_retained_training_candidate_record.py`
- `trade_alerts_build_docs/M9_1DG_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

This session does not claim a real retained-market result. The one-year
retained files are a long offline job and must follow D-114's detached-run and
D-116's 2% inspection rules. M9.1DH must connect the three verified retained
file groups to this record, run the 2% check, and only then release and collect
the full training-nine job. It must not open held-out names or calculate fills,
returns or supervised packages.
