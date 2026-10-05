"""Bias regressions: directional meaning, image provenance, and split media."""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import db, config as cfg
from consensus_engine.analysis.tweet_parser import _parse_model_payload
from consensus_engine.models import TickerSignal, SourceType, Sentiment


def payload(text, ticker="NVDA", direction="long", kind="setup"):
    return {
        "type": "A", "tickers": [ticker], "direction": direction,
        "ticker_views": [{"ticker": ticker, "direction": direction,
                          "reason_text": text, "reason_kind": kind,
                          "decision_code": "explicit_clause"}],
    }


@pytest.mark.parametrize("text,ticker,direction,kind", [
    ("$NVDA is the top semiconductor pick", "NVDA", "long", "event_claim"),
    ("$AMD this breaks out next week", "AMD", "long", "setup"),
    ("$AMD to 700 coming", "AMD", "long", "setup"),
    ("$NVDA winding up for a move to 250", "NVDA", "long", "setup"),
    ("$NVDA cup and handle", "NVDA", "long", "setup"),
    ("$TSLA delivered 486,532 vehicles vs consensus of 461,974", "TSLA", "long", "event_claim"),
    ("$MU revenue $54.23B vs $51.07B est.", "MU", "long", "event_claim"),
    ("$MU EPS $33.42 vs $31.61 est.", "MU", "long", "event_claim"),
    ("$MU beat earnings and raised guidance", "MU", "long", "event_claim"),
    ("$GME purchased 700,000 shares in the open market", "GME", "long", "event_claim"),
    ("$NKE is down more than 6% today", "NKE", "short", "event_claim"),
    ("$NVDA this breaks down next week", "NVDA", "short", "setup"),
    ("$MU missed earnings estimates and cut guidance", "MU", "short", "event_claim"),
    ("$MU revenue $40B vs $50B estimated", "MU", "short", "event_claim"),
    ("$NVDA downgrade to underweight", "NVDA", "short", "event_claim"),
])
def test_directional_meaning_survives_parser_and_storage(text, ticker, direction, kind):
    view = _parse_model_payload(payload(text, ticker, direction, kind), "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == direction
    signal = TickerSignal(ticker=ticker, source_type=SourceType.TWITTER,
                          source_detail="analyst", raw_text=text, sentiment=Sentiment.NEUTRAL)
    stored = db._storage_safe_ticker_view(signal, view)
    assert stored.direction == direction
    assert stored.reason_text == text


@pytest.mark.parametrize("text", [
    "$NVDA earnings tomorrow", "$NVDA 150 calls Friday", "$NVDA watching",
    "$NVDA no breakout yet", "$NVDA not bullish", "$NVDA failed breakout",
    "$NVDA breakout failed", "$NVDA breakout did not happen", "$NVDA no longer bullish",
    "$NVDA is not looking bullish", "$NVDA has long-term debt",
])
def test_unsupported_or_negated_model_direction_stays_unclear(text):
    view = _parse_model_payload(payload(text), "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "unclear"


def test_stock_setup_is_not_vetoed_by_unsided_option_recap():
    text = "$NVDA breakout coming. Now calls are up over 100%."
    reason = "$NVDA breakout coming"
    view = _parse_model_payload(payload(reason), "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "long"
    assert db._storage_safe_ticker_view(TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst", raw_text=text,
    ), view).direction == "long"


def image_payload():
    return {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "ticker_views": [{"ticker": "NVDA", "direction": "long",
                          "decision_code": "image_evidence", "vision_index": 0}],
        "vision_outputs": [{"ticker": "NVDA", "sentiment": "bullish", "confidence": .9,
                            "direction_basis": "annotated_setup",
                            "direction_evidence": "NVDA chart labels a bullish breakout above resistance",
                            "image_url": "https://example.test/chart.png"}],
    }


def test_image_view_keeps_separate_provenance_without_inventing_text_quote():
    view = _parse_model_payload(image_payload(), "https://example.test/post", "analyst", "$NVDA chart").ticker_views[0]
    assert view.direction == "long"
    assert view.reason_text is None
    assert view.reason_start is None
    assert view.image_evidence["image_url"].endswith("chart.png")
    stored = db._storage_safe_ticker_view(TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst", raw_text="$NVDA chart",
    ), view)
    assert stored.direction == "long"
    assert stored.image_evidence == view.image_evidence


@pytest.mark.parametrize("change", [
    {"ticker": "AMD"}, {"sentiment": "bearish"}, {"confidence": .1},
    {"direction_basis": "none"}, {"image_url": ""}, {"direction_evidence": ""},
])
def test_unreliable_or_unattributable_image_stays_unclear(change):
    p = image_payload()
    p["vision_outputs"][0].update(change)
    view = _parse_model_payload(p, "https://example.test/post", "analyst", "$NVDA chart").ticker_views[0]
    assert view.direction == "unclear"


@pytest.mark.parametrize("text", ["$NVDA bearish below support", "$NVDA bullish but chart disagrees"])
def test_image_cannot_override_conflicting_text_or_charts(text):
    p = image_payload()
    if "disagrees" in text:
        p["vision_outputs"].append({**p["vision_outputs"][0], "sentiment": "bearish"})
    view = _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "unclear"


@pytest.mark.parametrize("text,direction", [
    ("$NVDA buying 150 puts", "short"), ("$NVDA selling 150 puts", "long"),
    ("$NVDA buying 150 calls", "long"), ("$NVDA selling 150 calls", "short"),
    ("$NVDA bought shares and sold puts", "long"), ("$NVDA buying 150.5 puts", "short"),
])
def test_option_contract_side_preserves_correct_stock_bias(text, direction):
    p = payload(text, direction=direction, kind="position")
    view = _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == direction
    wrong = "short" if direction == "long" else "long"
    view = _parse_model_payload(payload(text, direction=wrong, kind="position"),
                                "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "unclear"


@pytest.mark.parametrize("text,reason", [
    ("$NVDA breakout failed", "$NVDA breakout"), ("$NVDA is not bullish", "bullish"),
    ("$NVDA calls are up 100%, buyers in control", "$NVDA calls are up 100%, buyers in control"),
])
def test_selected_quote_cannot_hide_unsafe_context(text, reason):
    view = _parse_model_payload(payload(reason), "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "unclear"


def test_conflicting_option_legs_stay_unclear():
    text = "$NVDA buying calls and puts"
    assert _parse_model_payload(payload(text), "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


@pytest.mark.parametrize("text,reason", [
    ("$AMD bearish $MSFT bearish $NVDA not bullish $GOOG bullish", "$NVDA not bullish"),
    ("$AMD bullish $NVDA watching", "$NVDA watching"),
])
def test_previous_ticker_predicate_cannot_leak_into_view(text, reason):
    p = payload(reason)
    p["tickers"] = ["NVDA", "AMD", "MSFT", "GOOG"]
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


@pytest.mark.parametrize("text", ["$NVDA watching. Bought $AMD shares", "$NVDA not bullish. Bullish on $AMD"])
def test_context_cannot_extend_past_its_sentence(text):
    p = payload(text.split('.')[0])
    p["tickers"] = ["NVDA", "AMD"]
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


@pytest.mark.parametrize("text", ["$NVDA reports $10 billion of long-term debt", "$NVDA added to my watchlist"])
def test_neutral_event_is_not_promoted_from_generic_words(text):
    p = payload(text)
    p["ticker_views"][0].update(direction="unclear", decision_code="reason_only", reason_kind="event_claim")
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


def test_bearish_text_for_one_ticker_vetoes_its_bullish_image_in_multi_ticker_post():
    p = image_payload()
    p["tickers"] = ["NVDA", "AMD"]
    assert _parse_model_payload(p, "https://example.test/post", "analyst", "$NVDA breakdown. $AMD watching").ticker_views[0].direction == "unclear"


def test_different_tickers_text_cannot_veto_image():
    assert _parse_model_payload(image_payload(), "https://example.test/post", "analyst", "$AMD bearish").ticker_views[0].direction == "long"


def test_directional_text_is_not_allowed_to_hide_opposing_chart():
    text = "$NVDA bullish breakout"
    p = payload(text)
    p["vision_outputs"] = [{**image_payload()["vision_outputs"][0], "sentiment": "bearish"}]
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


async def test_vision_uses_configured_backup_after_provider_failure(monkeypatch):
    from models import vision_model, model_config
    monkeypatch.setattr(model_config, "VISION_FALLBACK_MODELS", ["backup-vision"], raising=False)
    with patch("models.vision_model.chat_completion", new=AsyncMock(side_effect=["", json.dumps(image_payload()["vision_outputs"][0])])) as call:
        out = await vision_model.analyze_image("https://example.test/chart.png")
    assert out["ticker"] == "NVDA"
    assert call.await_count == 2


async def test_text_uses_existing_backup_after_provider_failure(monkeypatch):
    from models import text_model, model_config
    monkeypatch.setattr(model_config, "TEXT_FALLBACK_MODELS", ["backup-text"], raising=False)
    with patch("models.text_model.chat_completion", new=AsyncMock(side_effect=["", json.dumps(payload("$NVDA bullish"))])) as call:
        out = await text_model.analyze_tweet("$NVDA bullish", "analyst")
    assert out["tickers"] == ["NVDA"]
    assert call.await_count == 2


async def test_text_retries_response_that_discards_named_stock(monkeypatch):
    from models import text_model, model_config
    monkeypatch.setattr(model_config, "TEXT_FALLBACK_MODELS", ["backup-text"])
    omitted = {"type": "D", "tickers": [], "summary": "factual news"}
    with patch("models.text_model.chat_completion", new=AsyncMock(side_effect=[json.dumps(omitted), json.dumps(payload("$NVDA bullish"))])) as call:
        assert (await text_model.analyze_tweet("$NVDA bullish", "analyst"))["tickers"] == ["NVDA"]
    assert call.await_count == 2


def test_trailing_etf_does_not_erase_ticker_header_setup():
    text = "$NVDA\n\nAnother ATH Breakout Setup\n220 is buy zone that needs to hold on weekly $SOXL"
    p = payload(text)
    p["tickers"] = ["NVDA", "SOXL"]
    p["ticker_views"][0].update(direction="unclear", decision_code="multi_ticker_ambiguous", reason_text=None)
    view = _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0]
    assert view.direction == "long"
    assert "SOXL" not in view.reason_text


def test_independent_chart_can_resolve_unsided_option_recap():
    p = image_payload()
    p["ticker_views"][0].update(direction="unclear", decision_code="unsided_option")
    view = _parse_model_payload(p, "https://example.test/post", "analyst", "$NVDA calls up 100%").ticker_views[0]
    assert view.direction == "long"
    assert view.reason_kind == "image"


def test_annotated_setup_direction_is_separate_from_consolidation_sentiment():
    p = image_payload()
    p["vision_outputs"][0].update(sentiment="neutral", setup_direction="long")
    view = _parse_model_payload(p, "https://example.test/post", "analyst", "$NVDA chart").ticker_views[0]
    assert view.direction == "long"
    stored = db._storage_safe_ticker_view(TickerSignal(ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst", raw_text="$NVDA chart"), view)
    assert stored.image_evidence["overall_sentiment"] == "neutral"


@pytest.mark.parametrize("text,expected", [
    ("$TSLA deliveries hit 486,532, beating estimates of 461,974", "long"),
    ("$MU EPS 2.00 vs 2.50 estimate", "short"),
    ("$MU EPS 2.00 vs 2.50 estimate; revenue 10B vs 9B estimate", "unclear"),
    ("$NVDA bullish", "unclear"),
])
def test_neutral_model_can_recover_only_unmixed_numeric_surprise(text, expected):
    ticker = "TSLA" if "TSLA" in text else "NVDA" if "NVDA" in text else "MU"
    p = payload(text)
    p["tickers"] = [ticker]
    p["ticker_views"][0].update(ticker=ticker, direction="unclear", decision_code="neutral", reason_text=None)
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == expected


def test_numeric_neutral_recovery_does_not_guess_multi_ticker_metric_ownership():
    text = "$MU EPS 2.00 vs 2.50 estimate; revenue 10B vs 9B estimate. $AMD watching"
    p = payload(text)
    p["tickers"] = ["MU", "AMD"]
    p["ticker_views"][0].update(ticker="MU", direction="unclear", decision_code="neutral", reason_text=None)
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


@pytest.mark.parametrize("text,ticker,expected", [
    ("Tesla, $TSLA, deliveries 486,532 vs 461,974 estimate. $AMD watching", "TSLA", "long"),
    ("$TSLA and $AMD deliveries 486,532 vs 461,974 estimate", "TSLA", "unclear"),
    ("$TSLA and $AMD deliveries 486,532 vs 461,974 estimate", "AMD", "unclear"),
])
def test_quote_symbol_expansion_is_attributable_in_parser_and_storage(text, ticker, expected):
    reason = "deliveries 486,532 vs 461,974 estimate"
    p = payload(reason)
    p["tickers"] = ["TSLA", "AMD"]
    p["ticker_views"][0].update(ticker=ticker, direction="long", reason_kind="event_claim")
    view = _parse_model_payload(p, "https://example.test/post", "analyst", text).view_for_ticker(ticker)
    stored = db._storage_safe_ticker_view(TickerSignal(ticker=ticker, source_type=SourceType.TWITTER, source_detail="analyst", raw_text=text), view)
    assert stored.direction == expected


@pytest.mark.parametrize("decision_code", ["explicit_clause", "multi_ticker_ambiguous"])
def test_last_symbol_cannot_borrow_shared_numeric_subject(decision_code):
    text = "$TSLA and $AMD deliveries 486,532 vs 461,974 estimate"
    p = payload("$AMD deliveries 486,532 vs 461,974 estimate")
    p["tickers"] = ["TSLA", "AMD"]
    p["ticker_views"][0].update(ticker="AMD", direction="long", decision_code=decision_code)
    view = _parse_model_payload(p, "https://example.test/post", "analyst", text).view_for_ticker("AMD")
    assert view.direction == "unclear"


@pytest.mark.parametrize("opposing", ["breakdown", "bearish", "sell", "below support"])
def test_conflicting_own_setups_are_not_recovered_as_one_direction(opposing):
    text = f"$NVDA breakout. $NVDA {opposing}. $AMD watching"
    p = payload(text)
    p["tickers"] = ["NVDA", "AMD"]
    p["ticker_views"][0].update(direction="unclear", decision_code="multi_ticker_ambiguous", reason_text=None)
    assert _parse_model_payload(p, "https://example.test/post", "analyst", text).ticker_views[0].direction == "unclear"


async def test_image_evidence_is_durable_and_visible_in_group_card(tmp_path):
    from consensus_engine.analysis.herding import _swarm_members
    from consensus_engine.alerts.discord import format_swarm_alert
    from consensus_engine.analysis.herding import SwarmResult
    cfg.load_config()
    with patch.dict(cfg._config["database"], {"path": str(tmp_path / "images.db")}):
        db._db = None
        conn = await db.init_db()
        try:
            now = time.time()
            view = _parse_model_payload(image_payload(), "https://example.test/post", "analyst", "$NVDA chart").ticker_views[0]
            await db.insert_signal(TickerSignal(
                ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
                raw_text="$NVDA chart", detected_at=now, source_link="https://example.test/post",
            ), ticker_view=view, source_url="https://example.test/post")
            row = await (await conn.execute("SELECT * FROM analyst_post_views")).fetchone()
            assert json.loads(row["image_evidence_json"])["ticker"] == "NVDA"
            members, times, details = await _swarm_members(conn, "NVDA", now - 1, now + 1, {"analyst"})
            assert details[0].direction == "long"
            assert "bullish breakout" in details[0].reason
            card = format_swarm_alert(SwarmResult(
                fired=True, reason="joined", ticker="NVDA", analysts=members, count=1, opened_at=now - 1,
                now_ts=now + 1, member_times=times, member_details=details,
            ), {})
            assert "Bullish" in str(card)
            assert "Chart read:" in str(card)
        finally:
            await db.close_db()


def split_messages():
    from consensus_engine.scanners.discord_tweetshift import _DISCORD_EPOCH_MS
    mid = str((int((time.time() - 10) * 1000) - _DISCORD_EPOCH_MS) << 22)
    parent = {"id": mid, "channel_id": "feed", "author": {"id": "relay"},
              "embeds": [{"author": {"name": "@analyst"}, "description": "$NVDA chart",
                          "footer": {"text": "TweetShift • 📷1"}}]}
    media = {"id": str(int(mid) + (1000 << 22)), "channel_id": "feed",
             "author": {"id": "relay"}, "content": "[📷](https://example.test/chart.png)",
             "embeds": [{"thumbnail": {"url": "https://example.test/chart.png"}}]}
    return parent, media


async def test_split_chart_joins_only_its_immediately_preceding_tweet():
    from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
    listener = DiscordTweetShiftListener(AsyncMock())
    listener._token = "test-token"
    parent, media = split_messages()
    with patch.object(listener, "_fetch_messages_since", new=AsyncMock(return_value=[media])):
        urls, ids = await listener._collect_tweet_media(parent, [])
    assert urls == ["https://example.test/chart.png"]
    assert ids == {media["id"]}


@pytest.mark.parametrize("mismatch", ["author", "interleaved", "late", "missing", "prose"])
async def test_split_chart_cannot_be_borrowed_from_another_post(mismatch):
    from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
    listener = DiscordTweetShiftListener(AsyncMock())
    listener._token = "test-token"
    parent, media = split_messages()
    page = [media]
    if mismatch == "author":
        media["author"]["id"] = "other-relay"
    elif mismatch == "interleaved":
        other = {**parent, "id": str(int(parent["id"]) + 1)}
        page.append(other)
    elif mismatch == "late":
        media["id"] = str(int(parent["id"]) + (20000 << 22))
    elif mismatch == "prose":
        media["content"] = "Separate $AMD bearish trade " + media["content"]
    else:
        page = []
    with patch.object(listener, "_fetch_messages_since", new=AsyncMock(return_value=page)):
        urls, ids = await listener._collect_tweet_media(parent, [])
    assert urls == []
    assert ids == set()
