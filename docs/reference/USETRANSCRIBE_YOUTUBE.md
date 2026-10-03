# Usetranscribe and the YouTube workflow

## Comparison on the same video

Sample: [Click Capital video](https://www.youtube.com/watch?v=Z2h0LIK-FPU),
[Usetranscribe result](https://www.usetranscribe.io/yt/Z2h0LIK-FPU/stocks-and-bonds-update).
Checked October 2, 2026, Pacific time.

The existing Supadata transcript had 22,780 characters. Usetranscribe's source
segments joined into 22,766 characters. After ignoring punctuation and casing,
the words matched except for two censorship placeholders in Supadata's copy.
Both copies contain the same apparent caption mistakes, including `Eyesshar's`
for iShares and `route` where the financial term is rout. This sample gives no
evidence of better speech recognition. An independent audio reference would be
needed to measure transcription accuracy; agreement is not proof of correctness.

| Question | Finding |
|---|---|
| Does it transcribe this video more accurately? | No demonstrated improvement; effectively the same caption text. |
| Does it add anything useful? | 598 timed segments, five section insights, a general summary, suggested questions, a public reading page, and transcript Q&A. Speaker labels are supported on its audio transcription path, but this sample has none. |
| Can OpenClaw read those features? | Yes. The API returns transcript segments, summary, sections and suggested questions directly. Q&A has its own streaming endpoint. Screenshots are not required. |
| Is its summary a reliable substitute for OpenClaw's analysis? | No. It is general prose without OpenClaw's ticker grounding, stock evidence checks or chart-price extraction. Its sections in this sample start at roughly four-minute intervals, rather than matching the video's chapter boundaries. |
| Does transcript Q&A work? | A live question returned Tesla's stated delivery and estimate figures. It omitted the timestamp requested in that probe, despite the documentation describing timestamp citations. |
| What does OpenClaw do better? | Gemini can inspect the video itself and read charts. OpenClaw stores structured ticker signals, price levels, setups, catalysts and analysis telemetry. These outputs still need grounding and are not guaranteed correct. |
| Is the service unlimited? | The [API documentation](https://www.usetranscribe.io/AGENTS.md) specifies 50 new jobs daily per IP/session, two concurrent jobs per IP and a 90-minute source limit. Q&A has a separate 50-question daily IP limit. There is no API key or service guarantee. |

The sample also exposes an existing OpenClaw classification problem: it stored
an unsuppressed LONG TLT signal beside a snippet describing falling Treasury bond
prices. The wrong direction predates this integration. Neither a more polished
summary nor a different transcript supplier fixes that stock-context attribution.
The finding is recorded in the existing video-reader validation TODO.

## Implemented routing

Video evidence keeps its current order:

1. Gemini video analysis, which retains chart evidence.
2. Caption/text evidence when Gemini fails or exhausts quota:
   Usetranscribe first, then Supadata, then OpenClaw's existing caption evidence
   extractor and classifier.

The shared `fetch_transcript_cascade` also gives the free source first to existing
transcript commands and the catch-up script. The old legacy video parser remains
disabled. Raw segment text is the only Usetranscribe content passed to extraction;
its generated summary and section answers are archived separately.

The adapter reads the local cache first, then checks Usetranscribe's shared cache.
Only a cache miss can start a job. New jobs are serialized within a process,
time out after six minutes by default, and use bounded SSE chunk parsing. Local
and shared cached reads do not queue behind a new job. A rate-limit response
persists a cooldown across restarts: 24 hours for daily limits, 60 seconds for
concurrency limits, or longer when requested by a numeric Retry-After header.
Transient job errors back off; permanent duration/auth/URL errors do not resubmit
the same job. Cached content remains usable during a job cooldown.

Normalized records live at
`artifacts/transcripts/usetranscribe/<video_id>.json`. They include source segments,
language, available speaker labels, sections, suggested questions, summary and
permalink. OpenClaw's existing database transcript storage still receives plain
source text. `!transcript <url>` adds a link to the provider's reading page, where
the full transcript, summary, sections and interactive Q&A are available.

## Limits that remain

This supplements Gemini rather than eliminating Gemini's model quotas. Text-only
fallback cannot recover chart visuals. The current caption evidence extractor
processes at most the first 15,000 characters and assigns approximate evidence
timestamps; the full provider transcript and exact segment timestamps are archived
even when that extractor truncates its input. Changing that extractor is outside
this provider integration. Usetranscribe Q&A is linked through its page, not added
as a new Discord command. Its API supplies suggested questions, not precomputed
answers to every question shown on the page.

## Controls

`youtube.usetranscribe.enabled` enables the provider; disable it to return to
Supadata-only transcript fetching. `timeout_seconds` bounds new jobs and
`cache_dir` controls its archive location. No credentials are required.

Validation covers cached and new streaming jobs, source identity/language,
malformed or empty transcripts, quota cooldowns, permanent errors, a large SSE
payload, concurrent cached reads, Supadata fallback and the transcript reply link.
Live probes read the sample and created a transcript for an existing failed-queue
video. An isolated database probe exercised real free-source text through
OpenClaw's caption evidence extraction without posting alerts.
