"""Embed parts get trimmed to Discord's limits before the POST.

2026-07-31: four $AMZN alerts came back as a flat 400 —
`embeds.0.fields.0.value: Must be 1024 or fewer in length`. _safe_send answers a
400 by stripping the embed and re-posting bare text, so one over-long field cost
the user the whole alert card. Trimming is strictly better: they still get the
card, just with a "…" on the end of the one long field.
"""
from consensus_engine.alerts.discord import _safe_send_kwargs


def test_a_long_field_value_is_trimmed_not_rejected():
    payload = _safe_send_kwargs({"embeds": [{
        "fields": [{"name": "Thesis", "value": "x" * 5000}],
    }]})
    value = payload["embeds"][0]["fields"][0]["value"]
    assert len(value) == 1024
    assert value.endswith("…")


def test_title_and_description_are_trimmed():
    payload = _safe_send_kwargs({"embeds": [{
        "title": "T" * 400,
        "description": "D" * 9000,
    }]})
    embed = payload["embeds"][0]
    assert len(embed["title"]) == 256
    assert len(embed["description"]) == 4096


def test_a_long_field_name_is_trimmed():
    payload = _safe_send_kwargs({"embeds": [{
        "fields": [{"name": "N" * 900, "value": "ok"}],
    }]})
    assert len(payload["embeds"][0]["fields"][0]["name"]) == 256


def test_more_than_25_fields_are_dropped():
    payload = _safe_send_kwargs({"embeds": [{
        "fields": [{"name": f"f{i}", "value": "v"} for i in range(40)],
    }]})
    assert len(payload["embeds"][0]["fields"]) == 25


def test_content_that_already_fits_is_untouched():
    payload = _safe_send_kwargs({"embeds": [{
        "title": "AMZN",
        "description": "short",
        "fields": [{"name": "Score", "value": "72/100"}],
    }]})
    embed = payload["embeds"][0]
    assert embed["title"] == "AMZN"
    assert embed["description"] == "short"
    assert embed["fields"][0]["value"] == "72/100"


def test_plain_content_payloads_still_work():
    payload = _safe_send_kwargs({"content": "hello"})
    assert payload["content"] == "hello"
    assert payload["allowed_mentions"] == {"parse": []}
