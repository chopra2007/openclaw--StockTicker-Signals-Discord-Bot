# YouTube Fallback Chain — Next Steps Brief

Read this file fully before proposing anything. Your job is to think through solutions, not just list tasks.

---

## What was built (context)

A multi-method YouTube evidence extraction chain in `consensus_engine/local_video_ingest.py`:

- **F1** (captions via `youtube_transcript_api`) — disabled by default; wired but untested
- **F2** (Gemini `Part.from_uri`) — primary method; calls `gemini_video_parser.extract_evidence_with_gemini`
- **F3** (yt-dlp audio → Groq Whisper) — fallback; downloads mp3, transcribes, runs grounding filter
- **F4** (FFmpeg frames) — Phase 2 stub, always returns `[]`

Chain short-circuits on first success. F2 → F3 is the load-bearing path.

Key files:
- `consensus_engine/local_video_ingest.py` — chain orchestrator + F1/F3 implementations
- `consensus_engine/analysis/gemini_video_parser.py` — F2 implementation
- `consensus_engine/analysis/hallucination_grounding.py` — ticker grounding filter used by F3
- `/root/.openclaw/youtube_cookies.txt` — Netscape-format auth cookies (read-only, `chmod 444`)
- `config/consensus.yaml` — `youtube.cookies_path`, `youtube.whisper.enabled`, `youtube.captions.enabled`

---

## What is working

- **F2**: Confirmed working on real videos (`FIgmrf23IoA`, `dhK-Wdz0gzo`). Produces 279–461 spans. ~64s per video.
- **F3**: Confirmed working after adding `--remote-components ejs:github` and `--js-runtimes node` to yt-dlp. 3/3 success on `WiQorxqBdlI`. ~20s per video.
- **Grounding filter**: Runs on all F3 tickers; rejects bundles where all tickers are ungrounded.

---

## Open issues (no solutions proposed — think through each)

### Issue 1: F2 reliability is poor
The user reports F2 fails ~5 out of 7 runs in production. We do not yet know the failure mode — it could be:
- Gemini quota/rate-limits
- Timeout (current timeout is 240s)
- Specific video characteristics (length, type, region-locked)
- Gemini's `Part.from_uri` rejecting certain YouTube URLs

We have not instrumented what specifically causes F2 to return `None` vs raise. The failure reason is swallowed in `_stage_gemini`'s broad `except Exception` handler.

**Human input needed**: Can the user share a sample F2 failure log? What do the logs say when it fails?

### Issue 2: Whisper hallucinated tickers
Groq Whisper is given this finance prompt:
```
"Finance: tickers like $SPY $NVDA $AAPL $TSLA $QQQ $BTC"
```
This causes the model to hallucinate $-prefixed symbols mid-transcript (observed: `$GOODPAL`, `$VYD`, `$SOPL`, `$IQGT`, `$GQ`, `$BQ`, etc.). The grounding filter catches some but not all — some hallucinated tickers happen to be valid stock symbols and pass grounding.

The prompt was added to bias Whisper toward financial vocabulary. Removing it may reduce transcription accuracy for real finance terms; keeping it injects noise.

**Questions to resolve**: Is the finance prompt actually helping real ticker recall, or is the noise outweighing the benefit? What's the right tradeoff between recall and precision here?

### Issue 3: Cookies file lifecycle
The cookies file is at `/root/.openclaw/youtube_cookies.txt`, `chmod 444` to prevent yt-dlp overwriting it. The auth session tokens (`PSID`, `SAPISID`) are stable for ~1-2 years. The rotating tokens (`PSIDTS`, `PSIDCC`) refresh every few weeks.

yt-dlp will log a warning when it cannot write to the file, but the download still proceeds. However:
- If the session is ever invalidated by Google (e.g., suspicious activity, password change, account switch), the file will silently serve stale cookies.
- There is no alerting when cookies go stale.
- The user must manually re-export from the browser and paste new content.

**Human input needed**: How often is the user willing to re-export cookies? Is there a monitoring signal we could use to detect stale cookies automatically (e.g., log pattern from yt-dlp failure)?

### Issue 4: F1 (captions) is untested
`fetch_captions` now uses `youtube_transcript_api` v1.2.4 (instance API + cookies). It is gated behind `youtube.captions.enabled: false` in config. The implementation was written but never run against a real video. It's unclear:
- Whether the v1.2.4 API works correctly with the cookies format we're using
- Whether auto-captions are available on the types of finance videos we process
- Whether caption quality is better or worse than Whisper for this use case

### Issue 5: End-to-end chain not tested in production
We have only tested F2 and F3 **in isolation** via `run_chain_test.py`. The full chain (`extract_evidence_via_chain`) — including the semaphore, F6 pre-flight, `cleanup_run_workspace`, and the actual F2→F3 fallover — has not been run against real production videos. It's possible the chain-level logic has issues that don't surface in isolated stage tests.

### Issue 6: No signal when F3 produces low-quality output
F3 currently returns a bundle as long as at least one ticker is grounded. There is no quality threshold on span count, transcript length, or grounded ticker ratio. A very short or garbled transcript would pass through to the consensus engine unchanged.

---

## Technical details for reference

**yt-dlp command (current)**:
```python
cmd = [
    "yt-dlp",
    "--js-runtimes", "node",
    "--remote-components", "ejs:github",
    url,
    "-x", "--audio-format", "mp3", "--audio-quality", "5",
    "-o", out_template,
    "--no-playlist", "--quiet",
]
# cookies appended conditionally if file exists
```

**F3 grounding logic** (`_stage_whisper`):
- Extracts `$TICKER` patterns from transcript
- Calls `ground_transcript_tickers(raw_tickers, transcript)`
- Rejects bundle only if `raw_tickers` is non-empty AND `all_ungrounded(grounded_results)`
- Passes through if no tickers found at all (even if transcript is garbage)

**Chain telemetry fields**: `chain_winner`, `chain_attempts`, `chain_durations`, `hallucinated_ticker_count`, `span_count`, `input_tokens`, `output_tokens`

**Pending git push**: commit `d664261` (F3 yt-dlp JS challenge fix) is local only, not pushed to remote.
