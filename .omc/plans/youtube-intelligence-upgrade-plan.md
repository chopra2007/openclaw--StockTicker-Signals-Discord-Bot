# YouTube Intelligence Upgrade — Phased Implementation Plan

This plan is scoped only to the current YouTube intelligence path and only to free/cheap LLM options:

- OpenRouter free-tier models
- `minimax/minimax-m2.5`
- GLM models exposed through OpenRouter

Priority order is fixed:

1. Prompt decomposition
2. Options extraction
3. Trade setup linking

The current implementation is still a single-pass parser centered on [`parse_video_transcript()`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:520), with one JSON schema in [`_SYSTEM_PROMPT`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:26), merged by [`_merge_chunk_results()`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:425), then persisted in [`process_video()`](/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:187) to `youtube_signals`, `youtube_levels`, and `youtube_macro` via [`insert_youtube_signal()`](/root/.openclaw/workspace/consensus_engine/db.py:1000), [`insert_youtube_level()`](/root/.openclaw/workspace/consensus_engine/db.py:1021), and [`insert_youtube_macro()`](/root/.openclaw/workspace/consensus_engine/db.py:1142). That is the surface this plan extends.

## Phase 1. Decompose the parser into focused passes

### Goal
Replace the current single mega-prompt with a staged extraction pipeline so cheaper models can handle narrower tasks more reliably. This phase creates the orchestration skeleton the later options/setup phases depend on.

### Files to change
- [`consensus_engine/analysis/video_parser.py`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:1)
- [`consensus_engine/models.py`](/root/.openclaw/workspace/consensus_engine/models.py:322)
- [`config/consensus.yaml`](/root/.openclaw/workspace/config/consensus.yaml:151)
- [`models/model_config.py`](/root/.openclaw/workspace/models/model_config.py:1)
- [`tests/test_video_parser.py`](/root/.openclaw/workspace/tests/test_video_parser.py:1)
- [`tests/test_youtube_scanner.py`](/root/.openclaw/workspace/tests/test_youtube_scanner.py:1)

### Specific code changes / new functions
- In `video_parser.py`, split `_SYSTEM_PROMPT` into task-specific prompts:
  - `_MENTIONS_PROMPT` for ticker + raw price mention extraction
  - `_DIRECTION_PROMPT` for direction/conviction classification per ticker
  - `_MACRO_PROMPT` for macro thesis only
  - Reserve `_OPTIONS_PROMPT` and `_SETUPS_PROMPT` for later phases
- Add an internal extraction pipeline, for example:
  - `_call_extraction_model(task_name: str, system_prompt: str, user_prompt: str, model_override: str | None = None) -> tuple[str, str]`
  - `_extract_mentions_pass(transcript_text: str) -> dict`
  - `_extract_direction_pass(transcript_text: str, tickers: list[dict]) -> list[dict]`
  - `_extract_macro_pass(transcript_text: str) -> dict`
  - `_merge_decomposed_passes(...) -> dict`
- Update `_chunk_and_analyze()` to run the decomposed passes per chunk, rather than one all-in-one prompt per chunk.
- Update `_merge_chunk_results()` so it can merge per-pass outputs cleanly, especially mention counts and raw price evidence.
- Extend `ParsedVideo` in `models.py` to carry decomposition-friendly data without yet changing DB persistence:
  - add `raw_price_mentions: list[dict] = field(default_factory=list)`
  - keep `tickers`, `price_levels`, `macro_thesis`, `overall_conviction` backward-compatible
- Introduce explicit config keys in `config/consensus.yaml`, e.g.:
  - `video_parser.models.mentions`
  - `video_parser.models.direction`
  - `video_parser.models.macro`
  - `video_parser.enable_decomposed_pipeline`
- Keep the default OpenRouter fallback path but stop centering the parser on Groq-specific helpers. The new path should call a provider-agnostic model selector first and only use configured cheap models.

### Model selection
- Mentions pass: `minimax/minimax-m2.5`
  - Best fit for broad transcript extraction with longer context and decent structured output at low cost.
- Direction pass: OpenRouter free-tier GLM model
  - Cheapest pass, tiny prompt, simple label classification; GLM is sufficient and cost-efficient here.
- Macro pass: `minimax/minimax-m2.5`
  - Macro summarization is fuzzier than raw extraction; minimax is the safer cheap model for consistency.

### Model rationale
- The current single-shot schema in `video_parser.py` asks one model to do extraction, classification, macro synthesis, and price logic together. That is exactly the failure mode described in the ideas file for cheap models.
- The mentions pass benefits most from the strongest cheap model because missing entities upstream cascades into every later pass.
- Direction classification is narrow enough that a weaker free-tier model is acceptable if the candidate ticker list is already constrained.
- Macro is semantically looser and should stay on minimax rather than the weakest free-tier choice.

### Deliverables
- Decomposed parser orchestration in `video_parser.py`
- New config surface for task-specific models
- Backward-compatible `ParsedVideo` output consumed unchanged by `scanners/youtube.py`
- Tests covering multi-pass success and fallback behavior

### Verification
- Add parser unit tests that mock different pass outputs and verify:
  - mentions can succeed even if macro fails
  - direction pass only classifies extracted tickers
  - merged output still produces a valid `ParsedVideo`
- Update YouTube scanner tests so `process_video()` still persists signals/levels/macro after the parser refactor.
- Manual verification target:
  - a long transcript (>2000 words) still parses through chunking and produces non-empty `youtube_signals` rows without changing scanner behavior.

## Phase 2. Add dedicated options extraction

### Goal
Add first-class options extraction as a separate pass and persistence layer, without overloading `tickers` or `price_levels`.

### Files to change
- [`consensus_engine/analysis/video_parser.py`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:1)
- [`consensus_engine/models.py`](/root/.openclaw/workspace/consensus_engine/models.py:322)
- [`consensus_engine/db.py`](/root/.openclaw/workspace/consensus_engine/db.py:1)
- [`consensus_engine/scanners/youtube.py`](/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:187)
- [`consensus_engine/alerts/commands.py`](/root/.openclaw/workspace/consensus_engine/alerts/commands.py:928)
- [`consensus_engine/cross_reference.py`](/root/.openclaw/workspace/consensus_engine/cross_reference.py:160)
- [`tests/test_video_parser.py`](/root/.openclaw/workspace/tests/test_video_parser.py:1)
- [`tests/test_db_youtube.py`](/root/.openclaw/workspace/tests/test_db_youtube.py:1)
- [`tests/test_youtube_scanner.py`](/root/.openclaw/workspace/tests/test_youtube_scanner.py:1)
- [`tests/test_commands.py`](/root/.openclaw/workspace/tests/test_commands.py:165)

### Specific code changes / new functions
- In `models.py`, add a new dataclass:
  - `VideoOptionIdea`
  - Fields: `ticker`, `option_type`, `strike`, `expiry`, `strategy`, `source`, `conviction`, `context`
- Extend `ParsedVideo` with:
  - `options: list[VideoOptionIdea] = field(default_factory=list)`
- In `video_parser.py`, add:
  - `_OPTIONS_PROMPT`
  - `_extract_options_pass(transcript_text: str, tickers: list[dict], raw_price_mentions: list[dict]) -> list[dict]`
  - `_normalize_option_record(raw: dict) -> dict | None`
- Add cheap regex pre-processing before the options LLM call:
  - detect `call(s)`, `put(s)`, date-like expiries, strike-like dollar amounts, `spread`, `debit`, `credit`, `LEAPS`
  - pass those snippets into the options prompt to reduce transcript noise
- In `db.py`, add a new table in `SCHEMA`:
  - `youtube_options`
  - columns: `id`, `video_id`, `ticker`, `option_type`, `strike`, `expiry`, `strategy`, `source`, `conviction`, `context_text`, `channel_name`, `published_at`, `extracted_at`
- Add helpers in `db.py`:
  - `insert_youtube_option(...)`
  - `get_youtube_options_for_ticker(ticker: str, days: int = 7) -> list[dict]`
  - optional `get_youtube_options_for_video(video_id: str) -> list[dict]`
- In `scanners/youtube.py`, update [`process_video()`](/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:187) to persist `parsed.options` after the existing signal/level inserts.
- In `alerts/commands.py`, update `!yt` output so it includes top option ideas when present.
- Do not mix YouTube-extracted options with live market options flow logic in `OptionsResult`; keep them separate. `cross_reference.py` can consume them later as enrichment, but not in this phase.

### Model selection
- Options extraction pass: OpenRouter free-tier GLM model first, `minimax/minimax-m2.5` fallback

### Model rationale
- Options extraction is schema-heavy and local to a small set of transcript spans once regex narrowing is added.
- The ideas file is right that this is a structured extraction problem. With explicit fields and snippet-level prompts, a free-tier GLM model should be good enough for most cases.
- Minimax remains the fallback because malformed options JSON is more damaging than a missed optional field.

### Deliverables
- New `ParsedVideo.options` output
- New `youtube_options` table and DB helpers
- Scanner persistence for options
- `!yt` reply path surfaces extracted options

### Verification
- Unit tests for parser normalization:
  - `"buying the 450 calls next Friday"` maps to type, strike, expiry, source=`personal_idea`
  - `"seeing unusual call buying"` maps to source=`flow_observation`
  - invalid options records are dropped, not persisted
- DB tests validate insert/read ordering for `youtube_options`.
- Scanner test verifies `process_video()` writes options rows when parser returns them.
- Manual verification target:
  - a transcript mentioning both stock direction and options produces `youtube_signals` and `youtube_options` independently.

## Phase 3. Link entry/stop/target into trade setups

### Goal
Promote fragmented price levels into coherent setups so the system can represent an actual trade idea instead of disconnected `youtube_levels` rows.

### Files to change
- [`consensus_engine/analysis/video_parser.py`](/root/.openclaw/workspace/consensus_engine/analysis/video_parser.py:1)
- [`consensus_engine/models.py`](/root/.openclaw/workspace/consensus_engine/models.py:322)
- [`consensus_engine/db.py`](/root/.openclaw/workspace/consensus_engine/db.py:1)
- [`consensus_engine/scanners/youtube.py`](/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:187)
- [`consensus_engine/alerts/commands.py`](/root/.openclaw/workspace/consensus_engine/alerts/commands.py:889)
- [`consensus_engine/cross_reference.py`](/root/.openclaw/workspace/consensus_engine/cross_reference.py:160)
- [`consensus_engine/main.py`](/root/.openclaw/workspace/consensus_engine/main.py:424)
- [`tests/test_video_parser.py`](/root/.openclaw/workspace/tests/test_video_parser.py:1)
- [`tests/test_db_youtube.py`](/root/.openclaw/workspace/tests/test_db_youtube.py:1)
- [`tests/test_commands.py`](/root/.openclaw/workspace/tests/test_commands.py:165)

### Specific code changes / new functions
- In `models.py`, add:
  - `VideoTradeSetup`
  - fields: `ticker`, `entry_low`, `entry_high`, `stop`, `targets`, `timeframe`, `setup_type`, `context`, `risk_reward`
- Extend `ParsedVideo` with:
  - `setups: list[VideoTradeSetup] = field(default_factory=list)`
- In `video_parser.py`, add:
  - `_SETUPS_PROMPT`
  - `_extract_setups_pass(transcript_text: str, tickers: list[dict], price_levels: list[dict]) -> list[dict]`
  - `_link_price_levels_into_candidate_setups(price_levels: list[dict]) -> list[dict]`
  - `_compute_risk_reward(entry_low, entry_high, stop, targets) -> float | None`
- The setup pass should consume outputs from prior passes, not raw transcript alone:
  - use extracted tickers
  - use normalized `price_levels`
  - optionally use `options` when the transcript frames the setup as an options trade
- In `db.py`, add a new table:
  - `youtube_setups`
  - columns: `id`, `video_id`, `ticker`, `entry_low`, `entry_high`, `stop_price`, `targets_json`, `timeframe`, `setup_type`, `context_text`, `risk_reward`, `channel_name`, `published_at`, `extracted_at`
- Add DB helpers:
  - `insert_youtube_setup(...)`
  - `get_youtube_setups_for_ticker(ticker: str, days: int = 14) -> list[dict]`
- In `scanners/youtube.py`, persist setups after levels/options.
- In `alerts/commands.py`:
  - enhance `!yt` to show the top setup
  - consider upgrading [`_handle_levels()`](/root/.openclaw/workspace/consensus_engine/alerts/commands.py:889) to query setups first and then fall back to raw levels
- In `cross_reference.py`, extend `_get_youtube_context()` to load setups and carry them alongside levels for downstream scoring or alert formatting.
- In `main.py`, the existing YouTube level proximity checker can remain unchanged initially; do not couple Phase 3 to live setup outcome tracking yet.

### Model selection
- Setup-linking pass: `minimax/minimax-m2.5`

### Model rationale
- Setup linking is the hardest semantic step in this upgrade.
- It requires relational reasoning across multiple extracted fields: entry, stop, one or more targets, timeframe, and setup type.
- That is a worse fit for the weakest free-tier models and a better fit for minimax, even if used on a much smaller prompt built from prior-pass outputs rather than the full transcript.

### Deliverables
- New `ParsedVideo.setups` output
- New `youtube_setups` persistence
- Command formatting that shows coherent setups instead of only raw levels
- Cross-reference can access setups as structured YouTube context

### Verification
- Parser tests cover:
  - `"buy NVDA at 850, stop 820, target 920"` becomes one linked setup
  - target arrays with multiple targets
  - zone entries like `"430 to 445"` become `entry_low`/`entry_high`
  - setups are not created when only isolated levels exist with no relationship
- DB tests validate JSON target storage and retrieval for `youtube_setups`.
- Command tests verify `!yt` and/or `!levels` output includes setup formatting when present.
- Manual verification target:
  - a real transcript that currently emits three separate `youtube_levels` rows now also emits one coherent `youtube_setups` row with computed risk/reward.

## Phase 4. Tighten downstream use after the new structures exist

### Goal
Use the decomposed outputs consistently in read paths and alerts without expanding scope beyond the three priorities above.

### Files to change
- [`consensus_engine/scanners/youtube.py`](/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:147)
- [`consensus_engine/alerts/commands.py`](/root/.openclaw/workspace/consensus_engine/alerts/commands.py:928)
- [`consensus_engine/cross_reference.py`](/root/.openclaw/workspace/consensus_engine/cross_reference.py:160)
- [`tests/test_commands.py`](/root/.openclaw/workspace/tests/test_commands.py:165)
- [`tests/test_cross_reference.py`](/root/.openclaw/workspace/tests/test_cross_reference.py:1)

### Specific code changes / new functions
- In `youtube.py`, enrich standalone alerts so they prefer setup-aware messages:
  - ticker + direction + conviction
  - entry / stop / target if available
  - options mention if available
- In `commands.py`, add lightweight DB-backed display helpers:
  - `_format_youtube_option_summary(...)`
  - `_format_youtube_setup_summary(...)`
- In `cross_reference.py`, extend `YouTubeContext` usage so it can surface:
  - setup count
  - options count
  - whether a setup and an options idea agree on ticker bias
- Keep scoring changes conservative in this phase. The objective is better context quality, not a new scoring regime.

### Model selection
- No new extraction model required.
- This phase should reuse stored outputs; LLM calls should not increase.

### Model rationale
- Once structured options and setups exist, downstream formatting should be deterministic and cheap.
- This phase should reduce, not expand, inference cost.

### Deliverables
- Better standalone YouTube alerts
- Better `!yt`, `!yt-mentions`, and `!levels` UX
- Cross-reference reads richer YouTube context

### Verification
- Command tests verify the richer formatting paths.
- Cross-reference tests verify setup/options context can be loaded without breaking current score calculation.
- Manual verification target:
  - a high-conviction YouTube alert includes setup details when available and does not regress when only old-style levels exist.

## Recommended model map

Use the cheapest model that matches the task shape:

1. Mentions extraction: `minimax/minimax-m2.5`
   Reason: strongest cheap option for long transcript extraction and schema adherence.
2. Direction classification: OpenRouter free-tier GLM
   Reason: tiny prompt, bounded labels, low semantic complexity.
3. Macro extraction: `minimax/minimax-m2.5`
   Reason: summary quality matters more than raw cost here.
4. Options extraction: OpenRouter free-tier GLM, minimax fallback
   Reason: schema-first extraction works well when transcript spans are pre-filtered.
5. Setup linking: `minimax/minimax-m2.5`
   Reason: highest reasoning load among the three prioritized upgrades.

## Implementation order

1. Phase 1 first. Do not add options or setups before decomposition exists.
2. Phase 2 second. Options extraction is the easiest new structured object once the pipeline is decomposed.
3. Phase 3 third. Setup linking should consume normalized outputs from phases 1 and 2.
4. Phase 4 last. Only tighten downstream formatting after persistence and parser contracts stabilize.
