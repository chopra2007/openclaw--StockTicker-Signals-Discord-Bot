# YouTube DB Score Weighting Research

**Status:** OPEN
**Created:** 2026-05-30

## Goal

Decide whether YouTube database signals (captions, ticker mentions, chart levels from videos) should be explicitly weighted in the `!all` scoring formula, and if so, figure out how to do it.

## Background

The `!all` footer currently shows a score breakdown like:
`Score: 45 (news=15, ape=10, tech=6, llm=14)`

YouTube sources (`youtube_signals_db`, `youtube_levels_db`, `youtube_evidence_db`) show up in the **sources** list, meaning they were fetched and passed to the narrator — but their contribution to the numeric score is unclear or absent from the visible breakdown.

## Questions to answer

1. Does the scorer currently receive YouTube DB data as an input? If so, is it weighted at all, or silently ignored?
2. If YouTube data IS reaching the scorer, why doesn't it appear in the score breakdown?
3. What weight would be appropriate? YouTube mentions tend to lag (video posted hours before the move), so over-weighting could introduce noise.
4. Should levels extracted from YouTube (buy zone, TP) influence the score, or only the text thesis?

## Files to start with

- `consensus_engine/scoring/` — find the main score computation
- `consensus_engine/alerts/all_command/aggregator.py` — where youtube_* keys are gathered
- `consensus_engine/alerts/all_command/narrator.py` — how YouTube data feeds the LLM

## Possible next steps (priority order)

1. Grep the scorer for `youtube` to see if it's referenced at all.
2. Add a test: monkeypatch a non-empty `youtube_signals_db` and assert the score changes.
3. If unweighted: decide on a weight (suggest starting at 5–10 pts, capped) and add it.
4. Add `yt=N` to the score breakdown display so it's visible.
