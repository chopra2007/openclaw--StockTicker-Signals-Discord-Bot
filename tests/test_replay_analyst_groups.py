import json

from scripts.replay_analyst_groups import (
    apply_adjudication_results,
    apply_final_review_views,
    attach_review_results,
    build_blind_review_rows,
    compare_card_facts,
    reconstruct_groups,
    summarize_counts,
)


def _event(event_id, ticker, analyst, recorded_at, direction="long", source_link=None):
    return {
        "id": event_id,
        "ticker": ticker,
        "source_detail": analyst,
        "recorded_at": recorded_at,
        "direction": direction,
        "source_link": source_link,
    }


def _post(post_id, ticker, analyst, detected_at, raw_text, sentiment="bullish"):
    return {
        "id": post_id,
        "ticker": ticker,
        "source_detail": analyst,
        "detected_at": detected_at,
        "raw_text": raw_text,
        "sentiment": sentiment,
    }


def _group(group_id, ticker, first_seen_at, fired_at, analysts):
    return {
        "id": group_id,
        "ticker": ticker,
        "first_seen_at": first_seen_at,
        "last_seen_at": fired_at,
        "fired_at": fired_at,
        "members_json": json.dumps([{"analyst": analyst} for analyst in analysts]),
        "regime_label": "",
    }


def test_reconstructs_exact_posts_and_keeps_repeated_join_events():
    events = [
        _event(1, "NVDA", "alpha", 100.0),
        _event(2, "NVDA", "alpha", 115.0, direction="short"),
        _event(3, "NVDA", "beta", 120.0, direction=None),
        _event(4, "NVDA", "gamma", 180.0),
    ]
    posts = [
        _post(11, "NVDA", "alpha", 100.0, "first post"),
        _post(12, "NVDA", "alpha", 115.0, "later post", sentiment="bearish"),
        _post(13, "NVDA", "beta", 120.0, "watching", sentiment="neutral"),
        _post(14, "NVDA", "gamma", 180.0, "breakout"),
    ]
    groups = [
        _group(21, "NVDA", 100.0, 120.0, ["alpha", "beta"]),
        _group(22, "NVDA", 100.0, 180.0, ["alpha", "beta", "gamma"]),
    ]

    result = reconstruct_groups(groups, events, posts)

    assert len(result.recoverable) == 2
    assert result.unrecoverable == []
    assert result.recoverable[0]["event_kind"] == "opened"
    assert result.recoverable[1]["event_kind"] == "joined"
    assert result.recoverable[1]["chain_event_number"] == 2
    alpha = result.recoverable[1]["members"][0]
    assert alpha["signal_event_id"] == 1
    assert alpha["post_id"] == 11
    assert alpha["source_text"] == "first post"
    assert alpha["proposed_direction"] == "bullish"


def test_group_is_not_recoverable_when_one_exact_member_post_is_missing():
    groups = [_group(21, "MU", 100.0, 120.0, ["alpha", "beta"])]
    events = [_event(1, "MU", "alpha", 100.0), _event(2, "MU", "beta", 120.0)]
    posts = [_post(11, "MU", "alpha", 100.0, "source retained")]

    result = reconstruct_groups(groups, events, posts)

    assert result.recoverable == []
    assert result.unrecoverable[0]["missing_members"] == ["beta"]


def test_blind_review_rows_hide_proposed_read_and_deduplicate_join_reuse():
    groups = reconstruct_groups(
        [
            _group(21, "NVDA", 100.0, 120.0, ["alpha", "beta"]),
            _group(22, "NVDA", 100.0, 180.0, ["alpha", "beta", "gamma"]),
        ],
        [
            _event(1, "NVDA", "alpha", 100.0),
            _event(2, "NVDA", "beta", 120.0, direction=None),
            _event(3, "NVDA", "gamma", 180.0),
        ],
        [
            _post(11, "NVDA", "alpha", 100.0, "first post"),
            _post(12, "NVDA", "beta", 120.0, "watching", sentiment="neutral"),
            _post(13, "NVDA", "gamma", 180.0, "breakout"),
        ],
    ).recoverable

    rows = build_blind_review_rows(groups, batch_size=2)

    assert len(rows) == 3
    assert [row["batch_number"] for row in rows] == [1, 1, 2]
    assert all("proposed_direction" not in row for row in rows)
    assert all("proposed_reason" not in row for row in rows)
    assert all("analyst" not in row for row in rows)
    assert {row["source_text"] for row in rows} == {"first post", "watching", "breakout"}


def test_card_comparison_allows_only_requested_display_changes():
    legacy = {
        "title": "🚨 SWARM: $NVDA — 2 analysts tweeting in 20 min",
        "color": 0xED4245,
        "fields": [
            {"name": "Analysts", "value": "[@alpha](https://example.test/a), @beta", "inline": False},
            {"name": "Window", "value": "2 posts, old clock range", "inline": False},
            {"name": "Price", "value": "$101.25", "inline": True},
        ],
        "footer": {"text": "OpenClaw Signal Engine | analyst swarm"},
    }
    new = {
        "title": "🚨 $NVDA — 2 analysts tweeting in 20 min",
        "color": 0xED4245,
        "fields": [
            {"name": "Group bias", "value": "Bullish", "inline": False},
            {
                "name": "Analyst views",
                "value": "[@alpha](https://example.test/a) — Bullish — setup\n@beta — Unclear — reason not stated",
                "inline": False,
            },
            {"name": "Price", "value": "$101.25", "inline": True},
        ],
        "footer": {"text": "OpenClaw Signal Engine"},
    }

    comparison = compare_card_facts(legacy, new, ticker="NVDA", count=2, span="20 min")

    assert comparison["unchanged_facts_pass"] is True
    assert comparison["missing_facts"] == []


def test_summary_reports_counts_before_rates_and_hides_thin_rates():
    groups = [
        {"event_kind": "opened", "members": [{"review_id": "one"}]},
        {"event_kind": "joined", "members": [{"review_id": "one"}, {"review_id": "two"}]},
    ]
    summary = summarize_counts(
        total_group_events=5,
        recoverable_groups=groups,
        unresolved_group_count=3,
        exact_anchor_count=1,
        daily_anchor_count=1,
        direction_results=[True, False],
    )

    assert summary["counts"]["recoverable_group_events"] == 2
    assert summary["counts"]["repeated_join_events"] == 1
    assert summary["counts"]["unique_contributing_tweets"] == 2
    assert summary["rates"]["direction_later_worked"] is None
    assert summary["rates"]["direction_later_worked_note"] == "2 resolved cases; rate withheld below 10"


def test_review_comparison_checks_direction_catalyst_and_exact_support_phrase():
    groups = [
        {
            "members": [
                {
                    "review_id": "supported",
                    "proposed_direction": "bullish",
                    "proposed_reason": "Breaking above resistance after a strong earnings beat",
                    "source_text": "Breaking above resistance after a strong earnings beat",
                },
                {
                    "review_id": "unsupported",
                    "proposed_direction": "unclear",
                    "proposed_reason": "High option volume names today",
                    "source_text": "High option volume names today",
                },
            ]
        }
    ]
    results = {
        "supported": {
            "review_id": "supported",
            "direction": "bullish",
            "catalyst_or_setup": "earnings beat and resistance breakout",
            "support_phrase": "strong earnings beat",
            "event_verification": "unverified",
        },
        "unsupported": {
            "review_id": "unsupported",
            "direction": "neutral",
            "catalyst_or_setup": "not stated",
            "support_phrase": "High option volume names today",
            "event_verification": "unverified",
        },
    }

    counts = attach_review_results(groups, results)

    assert counts["reviewed"] == 2
    assert counts["direction_agreements"] == 2
    assert counts["catalyst_agreements"] == 1
    assert counts["unsupported_reasons"] == 1
    assert groups[0]["members"][0]["tweet_read_accurate"] is True
    assert groups[0]["members"][1]["tweet_read_accurate"] is False


def test_review_comparison_cannot_pass_with_missing_review():
    groups = [
        {
            "members": [
                {
                    "review_id": "reviewed",
                    "proposed_direction": "bearish",
                    "proposed_reason": "Lost support and guiding lower",
                    "source_text": "Lost support and guiding lower",
                },
                {
                    "review_id": "missing",
                    "proposed_direction": "unclear",
                    "proposed_reason": "reason not stated",
                    "source_text": "",
                },
            ]
        }
    ]
    results = {
        "reviewed": {
            "review_id": "reviewed",
            "direction": "bearish",
            "catalyst_or_setup": "lost support and lower guidance",
            "support_phrase": "Lost support",
            "event_verification": "unverified",
        }
    }

    counts = attach_review_results(groups, results)

    assert counts["reviewed"] == 1
    assert counts["missing"] == 1
    assert counts["gate_pass"] is False


def test_adjudication_override_replaces_bad_first_pass_and_requires_every_mismatch():
    groups = [
        {
            "members": [
                {
                    "review_id": "wrong_blind_read",
                    "proposed_direction": "bullish",
                    "proposed_reason": "Raised guidance supports the breakout",
                    "displayed_reason": "Raised guidance supports the breakout",
                    "source_text": "Raised guidance supports the breakout",
                    "direction_agreement": False,
                    "reason_supported": False,
                    "direction_reversal": True,
                },
                {
                    "review_id": "missing_override",
                    "proposed_direction": "unclear",
                    "proposed_reason": "reason not stated",
                    "displayed_reason": "reason not stated",
                    "source_text": "Watching this name",
                    "direction_agreement": False,
                    "reason_supported": True,
                    "direction_reversal": False,
                },
            ]
        }
    ]
    overrides = {
        "wrong_blind_read": {
            "review_id": "wrong_blind_read",
            "final_direction": "bullish",
            "final_catalyst_or_setup": "raised guidance and breakout",
            "final_support_phrase": "Raised guidance supports the breakout",
            "corroboration_status": "unverified",
            "root_cause": "independent_review_wrong_or_uncorroborated",
        }
    }

    counts = apply_adjudication_results(groups, overrides)

    assert groups[0]["members"][0]["tweet_read_accurate"] is True
    assert counts["adjudicated"] == 1
    assert counts["missing_adjudications"] == 1
    assert counts["gate_pass"] is False


def test_final_review_views_build_exact_safe_per_ticker_replay_values():
    groups = [
        {
            "ticker": "NVDA",
            "members": [
                {
                    "review_id": "corrected",
                    "source_text": "NVDA reclaimed support after guidance rose.",
                    "proposed_direction": "bearish",
                    "proposed_reason": "old wrong reason",
                },
                {
                    "review_id": "accepted_blind",
                    "source_text": "Watching NVDA option volume.",
                    "proposed_direction": "unclear",
                    "proposed_reason": "old raw text",
                },
            ],
        }
    ]
    blind = {
        "accepted_blind": {
            "direction": "neutral",
            "catalyst_or_setup": "not stated",
            "support_phrase": "Watching NVDA option volume.",
            "event_verification": "unverified",
        }
    }
    overrides = {
        "corrected": {
            "final_direction": "bullish",
            "final_catalyst_or_setup": "guidance rose and support reclaimed",
            "final_support_phrase": "reclaimed support after guidance rose",
            "corroboration_status": "unverified",
            "root_cause": "source_signal_direction_wrong",
        }
    }

    result = apply_final_review_views(groups, blind, overrides)

    corrected, neutral = groups[0]["members"]
    assert result["applied"] == 2
    assert result["missing"] == 0
    assert corrected["proposed_direction"] == "bullish"
    assert corrected["proposed_reason"] == "reclaimed support after guidance rose"
    assert corrected["reason_kind"] == "event_claim"
    assert neutral["proposed_direction"] == "unclear"
    assert neutral["proposed_reason"] == "reason not stated"
