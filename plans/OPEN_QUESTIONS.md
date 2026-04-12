# Open Questions — Answer Before Week 2

**Status:** awaiting answers from Akash. Week 2 work is blocked until these are resolved.

Reply inline (add `**Answer:** ...` under each) or in chat.

---

## 1. Plan reconciliation
`ytplan.md` and `ytplan2.md` overlap but differ in philosophy:
- `ytplan.md` = pragmatic 10-subsystem build (what we're shipping)
- `ytplan2.md` = full reliability/calibration/probabilistic architecture

**Question:** Should `ytplan2.md` **replace** `ytplan.md` Weeks 4+ or **extend** it as a hardening layer on top?

**My default:** extend (treat ytplan2 as Weeks 4–5 hardening).

**Answer:**

---

## 2. Precision engine (IMPLEMENTATION_PLAN.md)
`IMPLEMENTATION_PLAN.md` describes a separate precision-first signal routing engine with budget manager (Finnhub → Brave → Exa → SerpApi → Firecrawl cascade, STRONG_ALERT/WATCHLIST/IGNORE outputs).

**Question:** Is this a **replacement** for the existing `cross_reference.py` tweet routing, or a **parallel track** (e.g., for a different signal class)?

**Answer:**

---

## 3. Channel credibility cold start
Before outcome tracking accumulates data, `youtube_channels.credibility_score` needs a seed.

**Options:**
- (a) all 0.5 (neutral, safest)
- (b) manual per-channel config in YAML
- (c) derived from subscriber count

**My default:** (a).

**Answer:**

---

## 4. Level proximity alerter cadence
The background loop that fires Discord alerts when price approaches stored S/R levels.

**Options:** 1 min / 5 min / 15 min / on every tweet poll cycle

Cheaper = less responsive. Finnhub quote cap is 3000/day.

**Answer:**

---

## 5. Metadata fetch for `!yt <URL>` command
`parse_video_transcript()` needs `channel_name` + `published_at`. RSS provides this in the scanner path, but ad-hoc `!yt <URL>` commands need a fresh lookup.

**Options:**
- **oEmbed** (`https://www.youtube.com/oembed?url=...&format=json`) — simple, official, rate-limit friendly
- **Invidious** (`/api/v1/videos/{id}`) — richer (duration, description), already cascaded in transcript fetch

**My default:** oEmbed.

**Answer:**

---

## 6. Macro digest format
The `!macro` command + daily summary posts.

**Options:**
- Daily auto-post to a Discord channel (set time, e.g., 8:30 AM ET)
- On-demand `!macro` only
- Both

**Answer:**

---

*Once answered, I'll update `plans/ROADMAP.md` accordingly and start Week 2.*
