"""A2: chart visual_evidence -> structured youtube_levels (classify_visual_levels).

Grounded in the real chart-price values Gemini read off video 2UUTK-lntus:
gridlines 0..24,30,40,50, a real ~$70 cluster 65..73, and a second ticker's
~$400 cluster 380..440. A single price anchor must keep only the cluster near
it and drop the gridlines + the other ticker's numbers.
"""
import pytest

from consensus_engine.analysis.video_classifier import classify_visual_levels

# Real values pulled from youtube_visual_evidence for video 2UUTK-lntus (kind='price').
REAL_2UUTK = [str(v) for v in
    [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,30,40,50,
     65,66,67,68,69,70,71,72,73, 380,390,400,410,420,430,440]]


def _rows(values, kind="price"):
    return [{"value": v, "kind": kind, "where_seen": "y-axis", "ts_sec": 10} for v in values]


def test_band_keeps_only_near_anchor_drops_gridlines_and_other_ticker():
    levels = classify_visual_levels(_rows(REAL_2UUTK), "USCI", live_price=70.0, band_pct=0.10)
    prices = sorted(lv.price for lv in levels)
    # ±10% of 70 = [63, 77] -> 65..73 kept (9 values)
    assert prices == [65, 66, 67, 68, 69, 70, 71, 72, 73]
    # gridlines and the $400 cluster are gone
    assert all(p not in prices for p in (0, 10, 20, 30, 40, 50, 380, 410, 440))


def test_support_resistance_split_from_anchor():
    levels = classify_visual_levels(_rows(REAL_2UUTK), "XYZ", live_price=410.0, band_pct=0.10)
    by_price = {lv.price: lv.level_type for lv in levels}
    # ±10% of 410 = [369, 451] -> 380..440 kept
    assert set(by_price) == {380, 390, 400, 410, 420, 430, 440}
    assert by_price[380] == "support" and by_price[400] == "support"
    assert by_price[420] == "resistance" and by_price[440] == "resistance"
    assert by_price[410] == "resistance"  # == anchor -> not below -> resistance


def test_no_price_anchor_files_nothing():
    assert classify_visual_levels(_rows(REAL_2UUTK), "USCI", live_price=None) == []
    assert classify_visual_levels(_rows(REAL_2UUTK), "USCI", live_price=0.0) == []


def test_no_ticker_files_nothing():
    assert classify_visual_levels(_rows(["70"]), "", live_price=70.0) == []


def test_only_price_kind_considered():
    rows = _rows(["745"], kind="label") + _rows(["70"], kind="price")
    levels = classify_visual_levels(rows, "USCI", live_price=70.0, band_pct=0.10)
    assert [lv.price for lv in levels] == [70]


def test_dedup_and_cap():
    levels = classify_visual_levels(_rows(["70", "70", "71", "71"]), "USCI", live_price=70.0)
    assert sorted(lv.price for lv in levels) == [70, 71]
    capped = classify_visual_levels(_rows([str(70 + i * 0.01) for i in range(30)]),
                                    "USCI", live_price=70.0, max_levels=5)
    assert len(capped) == 5


def test_context_prefix_identifies_visual_levels():
    levels = classify_visual_levels(_rows(["70"]), "USCI", live_price=70.0)
    assert levels[0].context.startswith("chart shows")
    assert levels[0].classifier_confidence == 0.55
