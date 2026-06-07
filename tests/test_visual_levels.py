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


# ---------------------------------------------------------------------------
# B3 #13 — structured-path per-number ticker tagging (gated by the caller via
# youtube.visual.tag_structured_levels; here exercised through the optional
# `ticker_prices` map that the gated caller passes in).
# ---------------------------------------------------------------------------

def _tagged_row(value, ticker, kind="price"):
    return {"value": value, "kind": kind, "where_seen": "y-axis",
            "ts_sec": 10, "ticker": ticker}


def _untagged_row(value, kind="price"):
    return {"value": value, "kind": kind, "where_seen": "y-axis", "ts_sec": 10}


def test_tagged_row_filed_under_own_ticker_with_own_anchor():
    # Top ticker = DELL (anchor 420.50). A tagged SMCI row at 510.43 is far
    # outside DELL's ±10% band but inside SMCI's own ±10% band (anchor 505).
    rows = [
        _tagged_row("510.43", "SMCI"),   # tagged -> SMCI anchor
        _untagged_row("420.50"),         # untagged -> top ticker DELL
    ]
    levels = classify_visual_levels(
        rows, "DELL", live_price=420.50, band_pct=0.10,
        ticker_prices={"SMCI": 505.0},
    )
    by_ticker = {(lv.ticker, lv.price) for lv in levels}
    # SMCI level filed under SMCI using SMCI's anchor (510.43 > 505 -> resistance)
    assert ("SMCI", 510.43) in by_ticker
    smci = next(lv for lv in levels if lv.ticker == "SMCI")
    assert smci.level_type == "resistance"  # 510.43 > 505 anchor
    # Untagged stays on DELL
    assert ("DELL", 420.50) in by_ticker
    dell = next(lv for lv in levels if lv.ticker == "DELL")
    assert dell.level_type == "resistance"  # 420.50 == anchor -> not below -> resistance
    # exactly the two expected levels, no cross-attribution
    assert by_ticker == {("SMCI", 510.43), ("DELL", 420.50)}


def test_tagged_row_uses_tagged_band_not_top_band():
    # Without the per-ticker anchor the SMCI 510.43 number would be dropped
    # (outside DELL's ±10% of 420.50 = [378.45, 462.55]). Prove the tag rescues
    # it ONLY because SMCI's own anchor is supplied.
    rows = [_tagged_row("510.43", "SMCI")]
    # No ticker_prices -> falls to top ticker DELL's band -> dropped.
    none_map = classify_visual_levels(rows, "DELL", live_price=420.50, band_pct=0.10)
    assert none_map == []
    # With SMCI anchor -> kept under SMCI.
    with_map = classify_visual_levels(
        rows, "DELL", live_price=420.50, band_pct=0.10, ticker_prices={"SMCI": 505.0},
    )
    assert [(lv.ticker, lv.price) for lv in with_map] == [("SMCI", 510.43)]


def test_tagged_row_without_anchor_falls_back_to_top_ticker():
    # Tag present but no usable anchor for it in the map -> treat as untagged
    # (top-ticker attribution + top band). 425.0 is inside DELL's band, kept.
    rows = [_tagged_row("425.0", "SMCI")]
    levels = classify_visual_levels(
        rows, "DELL", live_price=420.50, band_pct=0.10, ticker_prices={"SMCI": None},
    )
    assert [(lv.ticker, lv.price) for lv in levels] == [("DELL", 425.0)]


def test_flag_off_is_byte_identical_to_top_ticker_behavior():
    # With no ticker_prices (flag OFF), tagged rows MUST behave exactly like the
    # pre-B3 top-ticker path: identical objects to the no-tag call.
    tagged = [_tagged_row(v, "SMCI") for v in REAL_2UUTK]
    plain = _rows(REAL_2UUTK)

    off = classify_visual_levels(tagged, "USCI", live_price=70.0, band_pct=0.10)
    baseline = classify_visual_levels(plain, "USCI", live_price=70.0, band_pct=0.10)

    def fields(levels):
        return [(lv.ticker, lv.level_type, lv.price, lv.context,
                 lv.classifier_confidence, lv.video_timestamp_sec) for lv in levels]

    assert fields(off) == fields(baseline)
    # every level still on the top ticker, none diverted to SMCI
    assert all(lv.ticker == "USCI" for lv in off)


def test_empty_ticker_prices_map_is_top_ticker_behavior():
    # An empty (falsy) map is treated like None -> top-ticker behavior.
    tagged = [_tagged_row("70", "SMCI"), _untagged_row("71")]
    levels = classify_visual_levels(
        tagged, "USCI", live_price=70.0, band_pct=0.10, ticker_prices={},
    )
    assert sorted((lv.ticker, lv.price) for lv in levels) == [("USCI", 70.0), ("USCI", 71.0)]
