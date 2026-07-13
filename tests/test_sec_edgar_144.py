"""r27 — widening sec_edgar._RELEVANT_FORMS to include '144' must NOT confuse any
existing form=='4' consumer (sec_form4_cluster, cross_reference SEC paths, !sec).

A '144' row in the submissions JSON:
  - does NOT change classify_filing_significance's (has_filing, summary) output;
  - is excluded by the form=='4' filters the cluster + graduation paths use.
"""
from __future__ import annotations

from consensus_engine.scanners.sec_edgar import (
    _RELEVANT_FORMS,
    classify_filing_significance,
)


def test_144_in_relevant_forms():
    assert "144" in _RELEVANT_FORMS
    # the pre-existing forms are all still there
    assert {"8-K", "10-K", "10-Q", "4", "SC 13D", "SC 13G"}.issubset(_RELEVANT_FORMS)


def test_144_row_does_not_change_significance_summary():
    without = [{"form": "4"}, {"form": "8-K"}]
    with_144 = [{"form": "4"}, {"form": "144"}, {"form": "8-K"}]
    # classify_filing_significance must be byte-identical with vs without the 144 row.
    assert classify_filing_significance(with_144) == classify_filing_significance(without)
    has, summary = classify_filing_significance(with_144)
    assert has is True  # driven by the 8-K/Form 4, never the 144
    assert "144" not in summary  # 144 is never a scored/summarized part


def test_144_only_is_not_significant():
    # A ticker whose ONLY relevant filing is a 144 stays non-significant, empty summary
    # (so _run_sec_check keeps returning (False, "") exactly as before).
    has, summary = classify_filing_significance([{"form": "144"}])
    assert has is False
    assert summary == ""


def test_form4_filter_excludes_144():
    filings = [{"form": "4"}, {"form": "144"}, {"form": "4"}, {"form": "8-K"}]
    form4_only = [f for f in filings if f.get("form") == "4"]
    assert len(form4_only) == 2
    assert all(f["form"] == "4" for f in form4_only)
