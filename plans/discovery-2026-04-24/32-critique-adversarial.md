# 32 — Critique: Adversarial (Red-Team C)

**Date:** 2026-04-24
**Lens:** Single threat-model lens — a sophisticated adversary knows our full alert logic. Inputs include: 14 ranked Phase-2 candidates (`20-candidate-features.md`), historical confirmed-fragility patterns (`AUDIT_RESEARCH_2026-04-24.md`, `00-system-map.md`).
**Threat model assumptions reaffirmed:**
- Public Discord, real-money followers; attacker profits by front-running spurious alerts or suppressing legitimate ones.
- Full alert logic is observable: thresholds, second-source rules, cooldown windows, weight tables.
- Attacker is patient (months) and capitalized ($100k–$1M working capital), but not a market-maker. Cannot manufacture fundamentals; CAN manufacture *appearance* of features.
- Regulated filings (Form 4, 13D) are not free to spoof — but their *timing* and *amendment cadence* are.
- The audit-confirmed `kpak82` 26-min cooldown race (a parallel-read race in `db.py:672`) shows the system is already exploitable in production, even without an adversarial counterparty. Adversarial inputs raise this from "race condition" to "first-class attack surface".

---

## Executive Summary

**Verdict counts (14 features):**
- KEEP as-designed: **3** (Features 1 — Form 4 cluster (with one tweak), 4 — Credit-equity divergence, 11 — Reg SHO threshold)
- STRENGTHEN before shipping: **8** (Features 2, 3, 5, 6, 8, 9, 10, 14)
- KILL: **3** (Features 7, 12, 13)

**Highest-EV attack themes across the surviving candidate set:**

1. **The cooldown-race exploit generalizes to every standalone-trigger feature.** The audit already documents a 26-min same-ticker race through a 6h cooldown for tweet ingestion. Every new instant-trigger feature in this batch (1, 2, 3, 5, 8, 11, 12) plugs into the *same* `db.py:672` path. An adversary who can spoof a single feature (e.g., a low-cost FinBERT poisoning, a single sock-puppet 13G filer) gets two chances to fire because of the parallel-read bug. This is a *systemic* vulnerability that no single-feature hardening fixes.

2. **Cross-form / cross-feature stacking is more dangerous than any single-feature spoof.** The composite scoring approach treats SourceTypes as approximately independent — but an adversary who plants a forged-but-cheap signal in one feature (e.g., a low-quality 425, a Wikipedia pageview brigade, a coordinated TweetShift cluster) and *waits 1–14 days* for a real signal in a stacked feature (Form 4 cluster filing window, Reg SHO 5-day window) gets a multiplicative score from the cross-reference path that is FAR larger than either signal would justify alone. The framework's own Section 3 stacking notes are an attack manual.

3. **News-text features (FinBERT softmax, catalyst lexicon, headline velocity) are the single most attackable surface.** The cost of placing a paid PR-wire story is $300–$2,500. The cost of placing a Reuters/Bloomberg-syndicated story is $0 if the attacker is the issuer. FinBERT can be poisoned with crafted token sequences that exploit BERT's tokenizer and attention quirks for ~$0 (no compute, just text). The defender's only real countermeasure is "require a regulated source as second leg" — which collapses Feature 7 to nearly zero standalone value.

---

## 1. Cluster Form 4 Open-Market Buys — VERDICT: KEEP (with one minor tweak)

**Composite score (P2):** 5.00

**Attack vectors:**
- **A1 — 10b5-1 "compliance laundering."** Attacker (acting as friendly CEO of a small-cap) instructs 2–3 directors to file open-market buys with `aff10b5One=false` field carefully unchecked, but in reality executes them under an unfiled informal coordination. Cost to attacker: $500k–$1M of buys (real money committed to issuer's stock; partial recoupment from the alert-induced rally). Profit: dump retail follow-through over the subsequent 1–3 days. The proposed feature filter (`aff10b5One==false`) catches the *checkbox*, not the *real coordination*.
- **A2 — Director-grant timing games.** Issuer (insider acting in concert with bot's known logic) schedules a board-grant cycle so that 2 directors file `P` (purchase) instead of `A` (grant) in the same 14-day window. Costs the directors no incremental capital (they're getting compensation either way) but registers as discretionary cluster. Cost to attacker: ~$0 if directors are aligned; signal-to-the-bot value: full-weight cluster trigger.
- **A3 — Multi-CIK trust splitting.** Same beneficial owner controls 3–4 separate trust CIKs (e.g., spouse, family-trust-A, family-trust-B, custodian-IRA). Each files a $25k buy from same underlying funds → cluster threshold met from one economic actor. Cost: $100k of real exposure; alert effect: full cluster weight.

**Defender vs attacker cost:**
- A1 defense requires footnote-NLP (parse "no plan in effect" affirmative language) — moderate effort (~150 LOC) but never bulletproof. Attack cost: real capital commitment, modest. Verdict: defense roughly tracks attack cost.
- A2 defense requires looking past `transactionCode` into the cost basis vs market price (a "purchase" at exactly the grant price suggests cosmetic). ~50 LOC. Cheap defense.
- A3 defense is the proposed feature's own "fuzzy name+address match" — the spec already covers this. Need to also add a beneficial-owner detector (look at Form 3 history; if multi-CIKs all appeared on same Form 3, treat as one).

**Verdict: KEEP**

**Minimum hardening tweak:**
1. Reject cluster trigger if any constituent buy is at exactly the same price (within $0.01) as a recent grant (Form 4 with `transactionCode='A'`) — flags A2.
2. Require ≥2 *independent beneficial owners* (defined by non-overlapping prior Form 3 disclosures), not just ≥2 CIKs — closes A3 fully.
3. Add a "real cost" check: cluster aggregate USD-volume must equal at least the median recent week's open-market activity in the issuer (defends against tiny token buys for cosmetic effect).

This feature is the highest-leverage feature in the basket, it's a regulated event, and the attack costs scale with real capital deployed. KEEP — the attack-defense ratio favors the defender.

---

## 2. SEC S-4 / 425 Real-Time M&A Detection — VERDICT: STRENGTHEN

**Composite score (P2):** 4.50

**Attack vectors:**
- **A1 — Sham-425 by sub-shell.** Attacker creates a shell entity, files a 425 referencing the target ticker as a "potential strategic alternative" with vaguely worded "merger agreement" verbiage just sufficient to pass the spec's regex (`merger agreement|definitive agreement|per share`). 425 filings have minimal SEC pre-screening. Cost: ~$2k of legal fees + filer registration. Effect on bot: standalone alert if paired with any second source; if attacker also seeds a Discord tweet 60 min later (cost: $0, just post in the public server), the 2-source rule fires.
- **A2 — Withdrawal cascade.** Attacker files a 425 with deal-language → bot fires alert → 6h later, same filer files 425/A withdrawing the deal. The bot's auto-retract logic only handles Form 4 amendments, not 425/A withdrawals — alert stays out, retail flow has been pumped.
- **A3 — 13D + 425 same-week stack.** Attacker accumulates 5%+ position in target (real capital, ~$5–10M), files Schedule 13D with "strategic alternatives" language, then files 425 on a sham-affiliate via A1. Activist-watcher (Feature 8) + S-4/425 (Feature 2) BOTH fire → high-conviction takeout score. Profit: dump 13D position into pump.

**Defender vs attacker cost:**
- A1 defense costs ~250 LOC to require *target-side* corroboration (target's CIK appears in 425 cover-page AS A FILER, not just as a referenced security). Attack cost is moderate (~$2k); ratio favors defender if hardened.
- A2 is cheap to fix (~30 LOC: monitor 425/A and trigger retract-message on prior alerts within 7 days). MUST add this.
- A3 is the cross-feature attack. Single-feature hardening cannot fix it; only the systemic correlation-penalty (see final section) addresses.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Require both filer and target to be on the 425.** Many sham-425s are filed by would-be acquirers with no target involvement; require target's CIK to appear as a co-filer or named party.
2. **Add 425/A withdrawal monitor with retract-message.**
3. **Penalty if filer has no prior SEC filing history** (CIK age < 90 days or first 10-K never filed).
4. **Cross-validate with at least one of:** elevated options activity in target (>3σ vs 30d), or major-wire (Bloomberg, Reuters) headline within ±15 min. (Cross-validation creates *real* second source, vs attacker's sock-puppet Discord post.)

If even one of these can't be implemented cheaply, downgrade to xref-only.

---

## 3. Pre-FOMC Drift Trade — VERDICT: STRENGTHEN

**Composite score (P2):** 4.20

**Attack vectors:**
- **A1 — VIX print game at T-1 14:00 ET.** This is an INDEX-LEVEL alert. Attacker positions a small (~$5M) basket of out-of-the-money SPX puts at T-2 expiring T+1, making profit if the bot triggers a buy at T-1 and the announcement is hawkish. Critically, the *attacker doesn't need to manipulate VIX itself* — they need to manipulate the bot's *publication timing* relative to the real institutional pre-positioning. By having a bot of their own that listens to our Discord, they can sniff our long alert at 14:00 ET T-1 and front-run the *retail follow-through* into long SPY at 14:01–14:30, then fade their position into the bot's directed flow.
- **A2 — Inter-meeting emergency-day exploit.** The spec says "Suppress on inter-meeting emergency days (only act on scheduled meetings)" — but the calendar source is the FOMC website, scraped *annually*. If the Fed adds an unscheduled meeting (2020-style emergency), the cache is stale and the bot doesn't know. Attacker monitors Fed-monitor services (Bloomberg, Politico Fed Pulse) for a hint of unscheduled action, knowing the bot will fire on the next scheduled date as if nothing happened, and reverses into the unscheduled action's volatility surge.

**Defender vs attacker cost:**
- A1 is structurally hard to defend — any public alert is front-runnable by definition. Mitigation is to *delay* alert dissemination by 5–10 min relative to entry-time, or to publish only post-event analysis (defeats the point).
- A2 defense is cheap (~50 LOC): refresh FOMC calendar weekly, not annually; add a Fed-emergency-monitor (FRED `EFFR` rate-deviation alert) as a kill-switch.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Refresh FOMC calendar weekly**, not annually. Add a fail-closed flag if the calendar is older than 7 days.
2. **Add an EFFR (effective-funds-rate) deviation kill-switch.** If the realized fed-funds rate moves >5bps inside the day (signal of emergency action), suppress the alert chain for 24h.
3. **Acknowledge the front-running cost:** publish the alert only when SPY auction-imbalance data shows expected exit liquidity (e.g., minimum trailing 10-min ADV ≥ 90th percentile). This is a soft mitigation but increases attacker's slippage.
4. **Consider a slight randomization of alert send time** (±90 sec around 14:00 ET) — adds noise to the front-runner's expected pickoff window.

---

## 4. FRED Credit-Equity Divergence — VERDICT: KEEP

**Composite score (P2):** 4.00

**Attack vectors:**
- **A1 — HYG / LQD coordinated tape-paint.** Theoretically: attacker shorts HYG aggressively for 5 sessions and longs SPY to manufacture the gap. Cost: massive ($50M+ to move HYG meaningfully; high borrow cost on HYG; opposite-direction in SPY costs another $20M+). Achievable alpha from the bot's resulting "macro caution" thesis: ~$10k of retail flow. Cost-to-alpha ratio is ~5,000:1.
- **A2 — FRED API spoofing.** FRED is a public US-government API; spoofing is impossible without compromising Fed infrastructure. Effectively unattackable.

**Defender vs attacker cost:**
- A1 is theoretically possible but economically irrational. Even a sophisticated attacker is not going to commit $70M to manufacture a $10k retail-flow alert.
- A2 is non-attackable.

**Verdict: KEEP**

**Note:** This feature is largely *self-defending* because (a) it's regime-classification, NOT instant-trigger (per spec — "fires as confidence multiplier on existing alerts"), and (b) the underlying inputs are public infrastructure that cannot be moved. The spec is correctly humble about it being a regime signal not a trade trigger. No hardening needed beyond what's already specified.

---

## 5. Volume-Confirmed N-Day Breakout with ATR Levels — VERDICT: STRENGTHEN

**Composite score (P2):** 4.00

**Attack vectors:**
- **A1 — Coordinated wash-trading at the close.** A pump group (group of 30–50 retail traders coordinated via Telegram or Discord) targets a $300–500M small-cap. Each trader buys 500–2000 shares at 15:55–15:59 ET on a day when the price is already near its 20-day high. Aggregate volume crosses the 2.0× ADV threshold; close prints above the 20d high. The bot fires a breakout alert at 16:00 ET with entry/stop/targets — retail follows. Pump group exits in pre-market the next day. Cost to attacker: $200k–$500k position aggregate, dispersed across the group; profit: $50k–$200k from retail follow-through. Cost-to-alpha ratio ~4:1 — economically viable.
- **A2 — Single-actor dual-print at low-float close.** On a $50–80M micro-cap (the spec says floor is $300M, but recall the audit shows the system has historically not enforced this gate cleanly), a single actor prints buys at every minute from 15:50 onward, printing the close above the 60d high on volume. Cost: $50k–$100k. Profit: pump-and-dump; the bot's "1.5×ATR target" creates a clear retail-flow ceiling at which the attacker can dump. Cost-to-alpha ratio ~1:3.
- **A3 — Stop-hunting cooperation between group of attackers.** Attacker A pumps to fire alert. Attacker B is short the underlying. Bot's "stop = close − 1.5×ATR" is published in alert text. Attacker B knows where every retail-follow stop will sit; dumps next morning to take them out. Bot's "publishing levels" is itself an attack vector.

**Defender vs attacker cost:**
- A1: defense requires "no single-trader concentration" check (need top-of-book depth-of-trade data — NOT available in yfinance). Practical mitigation is dollar-volume floor (~$10M), not just share-volume z-score. ~50 LOC. Cheap.
- A2: defense is the spec's own market-cap floor of $300M. **MUST be enforced as hard floor; the audit shows quality gates are leaky.**
- A3: defense is to NOT publish stop-loss in the alert. Provide entry/target only; let the user compute their own stop. ~30 LOC delete. Counter-intuitive but cheap defense.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Replace volume-z-score with dollar-volume z-score** AND require dollar volume ≥ $10M (filters $50M floats from gaming the rule).
2. **Hard market-cap floor at $500M** (raise from $300M); the manipulation-economics for $300–500M names is too attractive.
3. **Require the rolling-max breakout's prior 5 days to NOT show abnormal late-session volume concentration** (last hour vs first 5h ratio < 0.45).
4. **Stop publishing stop-loss in the alert**; publish entry + targets only.
5. **Delay alert send by 30 min post-close** to require AH price corroboration; many manipulated breakouts fade post-close.

---

## 6. Earnings-Window Risk Gate — VERDICT: STRENGTHEN

**Composite score (P2):** 4.00

**Attack vectors:**
- **A1 — Earnings-date confusion exploit.** This is a *gate*, so the attack vector inverts: an adversary can either (a) push a bogus pre-announcement to confuse the gate ("we'll report on Date X" → press release), making the gate suppress legitimate alerts; or (b) game the cross-source disagreement (Yahoo vs Nasdaq vs Finnhub return different dates) to force the gate into "uncertain" mode, which fail-closes — suppressing alerts the attacker is positioned against. Cost: $0 if the attacker is the issuer; gate suppression is enough for them.
- **A2 — Pre-announce timing.** Attacker (insider at issuer) issues a pre-announce in their PR room *on a specific date*, intending to shift the bot's "T-0" forward by 5 days. Now any alerts in the original T-3 to T+1 window get suppressed; their illicit position can flow without bot-driven contra-flow.

**Defender vs attacker cost:**
- A1 is built into the spec's failure modes ("companies that pre-announce shift their effective T-0 unpredictably"). The spec's mitigation (cross-check 3 sources, treat mismatch as "uncertain", fail-closed) is correct but means an adversary can *deliberately* create mismatch to suppress alerts. Defense cost ~0 (already specified); attacker cost ~0 (just pre-announce). Roughly equal — but this is acceptable because the attack only suppresses; it doesn't manufacture false positives. ALSO: the attack is regulated (selectively pre-announcing favorable info is Reg FD-violating).
- A2: Defense is to add a "pre-announce skepticism" rule — ignore the bot's pre-announce-driven date shift unless the new date is published by Finnhub (the most-curated source). ~30 LOC.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Trust Finnhub-curated date over self-disclosed pre-announce dates.** Self-disclosed date moves are too easy to game.
2. **Make the gate a *score modifier*, not a hard-suppress.** A confidence multiplier 0.6× during T-3 to T+1 still lets high-conviction signals fire, vs full suppression which is binary and gameable.
3. **Add an "earnings-week tweet density" sanity check** — if tweet volume on a ticker spikes 10x normal in the gate window, treat as *evidence* the event is not just earnings (e.g., simultaneous M&A) and override gate.

---

## 7. FinBERT Headline Sentiment + Catalyst Lexicon — VERDICT: KILL

**Composite score (P2):** 4.00

**Attack vectors:**
- **A1 — Paid PR-wire placement.** GlobeNewswire / PR Newswire / BusinessWire ingest stories from anyone for $300–$2,500. The wire syndicates to Yahoo Finance RSS within 5–15 min. An attacker writes a headline with the exact catalyst-lexicon tokens ("Company X raises FY guidance, FDA approves"; "Company Y settles patent dispute for $XXM") — FinBERT's 0.6 weight returns high-positive, lexicon's 0.4 weight crosses the catalyst score. Cost: $300; signal: triggers as FinBERT confirmer. The Yahoo/Nasdaq/CNBC RSS sources don't fact-check.
- **A2 — Adversarial-tokenizer headline attack.** FinBERT (`ProsusAI/finbert`) tokenizer is BERT-WordPiece. Crafted headlines using known adversarial sequences (zero-width characters, homoglyphs, repeated rare tokens) can flip softmax classification. Cost: $0 (just text). This is established BERT vulnerability — works on the 768-dim embedding even at high precision. The "EWMA smoothing α=0.4" specified is no defense — α=0.4 still passes most of a single spiked classification through.
- **A3 — Velocity hijacking.** Spec says "minimum 8 headlines in 8h window before computing velocity." Attacker generates 8+ syndicated headlines (each at $300 = $2,400 total) on a single ticker in 8h. Velocity component fires alone.
- **A4 — Bot-coordinated FinBERT poisoning over time.** Attacker drips low-cost adversarial headlines for 30+ days, *learning the bot's threshold* by observing which days alerts fire. Calibrates the cheapest possible adversarial input. Total cost over 30 days: ~$5–10k; long-term ROI on industrialized exploitation: multiple per-month alert hijacks.

**Defender vs attacker cost:**
- A1 defense: require ≥2 *independent* news domains (not just ≥2 RSS sources — the SPEC says ≥2 RSS sources, but Yahoo+Nasdaq+CNBC can ALL syndicate the same wire-service story). Need to detect syndication via story-text similarity. ~300 LOC + a reference corpus. Moderate; STILL vulnerable to attacker placing on 2 different wires for $600.
- A2 defense: requires actual security work — input sanitization of zero-width chars, homoglyph normalization, fingerprint-based adversarial-input detection. ~500–1000 LOC of security engineering. Expensive and never complete (the cat-and-mouse is permanent).
- A3 defense: dollar-volume corroboration (require ticker's intraday volume to actually move during the 8h headline burst). ~50 LOC. Cheap. But this collapses Feature 7 to "options-flow confirmer" — at which point Feature 7 isn't really FinBERT, it's flow.
- A4 is the asymmetric long-game attack. Defense is essentially impossible without making the feature uneconomic.

**Verdict: KILL** (downgrade to no-FinBERT, lexicon-only, second-source-required confirmer)

**Reason (≤2 sentences):** PR-wire placement at $300–2,500 is a publicly-priced direct attack on the feature's primary input; the kill criterion in the spec ("if catalyst-lexicon component alone … achieves the same lift, kill the FinBERT model") is essentially predicting the answer. The attacker's cost is bounded; defender's cost (per-token sanitization, syndication detection, model-shipping pipeline) grows unbounded.

**Minimum recovery path if not killed:** require options-flow corroboration (>2σ vs 30d ADV) AND ≥2 independent first-class news domains (Bloomberg, Reuters, WSJ — NOT wire-services like GlobeNewswire/PRNewswire). This essentially eliminates the FinBERT contribution; the feature becomes "first-class news + options flow", which is fine but doesn't justify the engineering.

---

## 8. New 13D Activist-Filer Detection (with 13G→13D conversion) — VERDICT: STRENGTHEN

**Composite score (P2):** 4.00

**Attack vectors:**
- **A1 — Sham-13D from sub-shell.** Attacker creates a CIK with a "sub-shell investment fund" history, files 13D on a target with Item 4 = "explore strategic alternatives" verbiage (cheap legal phrasing), holds for 5 business days, then files 13D/A withdrawing or reducing. Cost: ~$2k legal + 5%+ position in target (real capital, $5M+ for $100M-cap target). Scale-to-attack-multiple: if attacker is correlated short on the target (small position pre-attack), the rally caused by activist-filing alert lets them cover at better price. Cost-to-alpha: real capital is real, but maybe 2–4:1 ratio.
- **A2 — Joint-filer cluster spam.** Multiple shell CIKs all in the same fund family file co-13Ds on the same day — looks like 4 distinct activist filers, but is one beneficial owner. Spec's "joint-filer 13Ds counted once" is a SAFEGUARD but the implementation hinges on parsing the 13D's joint-filer schedule, which is messy HTML.
- **A3 — 13G→13D conversion gaming.** Attacker has an existing 13G filing on a ticker; doesn't sell down (so passes continuity check); files fresh 13D with Item 4 = "engagement with management." Cost: $0 (already had the position). Profit: alert-driven retail flow. The conversion-trigger fires standalone, has high confidence per spec.
- **A4 — Activist-history fabrication.** Attacker creates a CIK 12 months ago, files small/non-meaningful 13Ds on micro-caps to build "activist history," then uses that history to rate as "known activist" (≥2 prior campaigns). Cost: 12 months of waiting + ~$3M aggregate in 2 prior 13D positions. ROI on later high-value spoof: unclear but possible if attacker is patient.

**Defender vs attacker cost:**
- A1: defense is to require Item 4 to specify *actionable* intent (specific candidate names for board, specific deadline for response) rather than soft engagement language. ~100 LOC of regex-tuning. Moderate cost; doesn't fully close gap. Attacker can write specific verbiage cheaply.
- A2: defense is the spec's name-similarity match — extend with a "common 13D filing date" rule (multiple CIKs co-filing same day = treat as one). ~50 LOC. Cheap.
- A3: defense is to require 13G→13D conversion to be *paired with a real concurrent action*: a press release, board nomination filing, or a tweet from a known activist's confirmed account. ~150 LOC + an activist-account whitelist.
- A4: defense is to weight the activist-history score by *outcome* (how many of the prior campaigns reached vote / settlement / board change?). Requires manual tagging of historical campaigns. ~500 LOC + ongoing curation. Expensive but necessary for high-value standalone-trigger.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Co-filing same-day deduplication** (multiple CIKs filing 13D on same target same day count as one filer).
2. **Item 4 must contain at least one of:** named director nominee, specific tender/proxy threat, or named transaction-counterparty. Soft "engagement" verbiage downgrades to xref-only.
3. **13G→13D conversion alert downgrades to xref-only unless** paired with one of: press release in same 24h, options flow ≥3σ, or known-activist-account tweet within ±48h.
4. **Activist-history weighting** discounts campaigns that did NOT reach a settlement or vote outcome (i.e., raw count of 13Ds is insufficient — outcome-weighted counts).
5. **Maintain whitelist of confirmed activist filer-CIKs** (Elliott, Starboard, Engaged, etc.); only those qualify for standalone-trigger. Newcomers downgrade to xref-only.

---

## 9. SEC EDGAR Full-Text Mention Velocity (cross-form) — VERDICT: STRENGTHEN

**Composite score (P2):** 3.80

**Attack vectors:**
- **A1 — Multi-form spam by issuer.** Issuer files multiple low-substance forms (Form 3 cosmetic restatements, NT-10-Q lateness, Form 144 announcements never followed up) within a single week. Form-type diversity threshold is "≥4 distinct form codes in week" — reachable with no real fundamental activity. Cost: ~$0 for the issuer's own filings (small filing fees). Effect: bot fires "+1 confirmation" toward 2-source rule on any unrelated tweet/breakout. Combined with another attack (sock-puppet tweet), creates 2-source standalone alert.
- **A2 — Routine-filing inflation.** Many issuers file 4s, 8-Ks, 10-Qs on a known cadence. An attacker who knows the cadence can time a coordinated tweet right after a normal 8-K + 4 + 10-Q week — bot's velocity z-score elevates, treats as confirmation.

**Defender vs attacker cost:**
- A1 defense: weight form types by substance — Form 3, 144, NT-10-Q are ~0 weight; Form 4 (with `P`), 8-K (with material items), 10-K, 10-Q, 13D, 13G are full weight. ~80 LOC. Cheap.
- A2 defense: per-issuer cadence normalization. Spec already has this ("divide raw count by issuer's trailing-12-month average filings/month") — but normalization is not defense against a specific *week's* coordinated attack. Need additional check: form-type *novelty* (forms not filed in prior 90 days carry more weight).

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Form-type substance weighting** (table maintained in config — Form 4 P-code = 5x; 8-K w/ Item 1.01/2.01/5.02 = 3x; 13D = 5x; 4 A-code/144/NT-10-Q = 0x).
2. **Form-type novelty weighting** (form not filed in trailing 90d carries 2x weight).
3. **Effective standalone-eligibility ban** — feature can ONLY contribute to xref boost; NEVER fire as second leg in 2-source rule for tweet-driven primary alerts (spec says it doesn't, but explicit codification matters because future maintainers can drift).

---

## 10. Wikipedia Pageview Spike — VERDICT: STRENGTHEN

**Composite score (P2):** 3.70

**Attack vectors:**
- **A1 — Pageview brigade.** A pump group with 5,000–10,000 active members coordinates a "click campaign" via a Discord/Telegram link to the company's Wikipedia article over a 1-hour window. Each click is an independent residential IP (the `all-access/user` filter is bot-imperfect; real human clickers pass). Cost: $0 if community-coordinated; the bot fires +1 confirmation source. Achieves z ≥ 2.5 at hourly cadence on most articles for $0.
- **A2 — Wikipedia article edit-and-revert spam.** Edit-war on the article inflates pageviews via the watchlist subscriber system. Cost: $0; effect: pageview spike.
- **A3 — Sock-puppet click farm.** Cheap residential-IP rotation services (e.g., PacketStream, Bright Data) cost ~$5/GB and can simulate 1,000+ pageviews/hour on a target article. Cost: ~$50/day if focused on a single target. Effect: sustained Wikipedia attention z above threshold.

**Defender vs attacker cost:**
- A1/A3 defense: require corroboration with at least ONE other attention proxy (Google Trends, options volume, news-mention count). Spec already has this ("when paired with Google Trends second source"). MUST be enforced — not just optional pairing, mandatory.
- A2 defense: filter pageview events by user-agent / referrer if Wikimedia API exposes any of that. (It doesn't expose much — the API just gives counts.) Defense is structurally weak.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **MANDATORY co-confirmation with a second uncorrelated attention source** (Google Trends in same hour + same direction). If Google Trends shows no spike, Wikipedia spike is null-and-void.
2. **Sustained-spike requirement** — z ≥ 2.5 must hold for ≥3 consecutive hours, not single-hour. Attacker's click brigade rarely sustains 3h.
3. **Cap on contribution to alert score** — Wikipedia is at most +0.05 (5% of score) regardless of magnitude. Capping limits manipulation upside.

---

## 11. Reg SHO Threshold List Entry/Exit Event — VERDICT: KEEP

**Composite score (P2):** 3.50

**Attack vectors:**
- **A1 — Coordinated borrow-fail.** Attacker enters a heavy short on a target, deliberately fails to deliver shares for 5 settlement days, then exits the FTD at day 6. Spec requires entry on day 5 — alert fires. Cost: punitive borrow-rate (15–30% APR for typical FTD-prone tickers) + buy-in risk (broker may force-close). Cost is effectively the attacker's borrow rate × position size × 5 days. For $1M position at 25% APR over 5 days: ~$3,400. Profit: alert-induced rally → cover at higher; loss on the short itself. Probably net negative for attacker.
- **A2 — Threshold-list parsing exploit.** Spec parses NASDAQ/NYSE/Cboe lists. If parser is fragile against format changes (a real ticker formatted weirdly, e.g., "BRK.B" appearing as "BRK B" or "BRK-B"), attacker can target a slightly-malformed ticker that's on the list to fire false alerts.

**Defender vs attacker cost:**
- A1: defense is the spec's market-cap floor (≥$1B for standalone trigger). Large-caps cannot easily be moved into FTD threshold by retail-scale attackers — only institutional positioning qualifies. Per spec, micro-caps are confirmatory only. Verdict: spec already largely defends.
- A2: defense is robust ticker normalization. ~50 LOC. Cheap.

**Verdict: KEEP**

**No additional hardening beyond spec.** The spec's $1B market-cap floor neutralizes the dominant manipulation vector — small-cap forced-close gaming. The features' regulatory plumbing is real and the attack costs are correctly scoped to "real institutional borrow capacity," which is itself a real fundamental signal.

---

## 12. VIX Term-Structure Flip — VERDICT: KILL

**Composite score (P2):** 3.50

**Attack vectors:**
- **A1 — VX-futures settlement gaming at 16:15 ET.** VIX futures are CBOE-listed derivatives. While settlement isn't trivially manipulable by a non-MM, it CAN be moved by ~$50–100M of focused volume in the front month. The spec's "magnitude filter |Δslope_today| ≥ 1σ" can be triggered by a single $50M absorption at the close. Cost-to-alpha: positive for institutional-scale attackers but the bot's downstream alert is index-level (S&P direction, 30bps mean 5d return) — the actual retail-flow value of an index alert is small.
- **A2 — Yfinance fallback (^VIX9D / ^VIX3M) spoofing via short-dated options.** Both ^VIX9D and ^VIX3M are CBOE-derived from S&P option chain. Even harder to manipulate than VX-futures directly.

**However, the more important problem is signal quality:**
- The spec itself says "30bps mean 5d excess return is modest" and "<10×/year" frequency.
- An index-level alert that fires <10×/year cannot have meaningful coverage at the bot's alert-budget; it's too rare to warrant a feature slot.
- The signal is *also* highly correlated with Feature 4 (HYG/LQD divergence) and Feature 3 (FOMC drift) — see spec's own "Anti-stacking warnings" — meaning the signal is partly redundant.

**Defender vs attacker cost:**
- Manipulation cost is high ($50–100M scale). Cost-to-alpha is unfavorable for the attacker.
- BUT: signal value is also low. The reasonable verdict is not "manipulation risk" but "signal-redundancy + low-frequency makes the slot uneconomic regardless of manipulation."

**Verdict: KILL**

**Reason (≤2 sentences):** Manipulation is theoretically possible at $50M+ scale, but more importantly the feature's claimed signal (~30bps mean 5d return on <10 events/year) is too thin to defend a feature slot when Features 3 and 4 already cover the macro/regime axis with similar information. Killing is on signal-value grounds; the manipulation surface is a bonus reason.

---

## 13. Influencer Cluster-Convergence — VERDICT: KILL

**Composite score (P2):** 3.40

**Attack vectors:**
- **A1 — Sybil cohort, 90+ days aged.** Spec requires "median author age ≥ 90 days AND median per-author tweet count > 50." An attacker provisioning 30 sock-puppet accounts in advance can age them passively (each posts 1–2 generic tweets/day for 90 days about market commentary) for ~$5/account-month for residential VPN access. After 3 months: 30 accounts, 90+ days, 50+ tweets each, low cosine similarity to each other (carefully diversified content). Cost: ~$450 for the prep cohort. Unique-attack cost: $0 — fire when needed by posting same ticker-mention from 4 accounts simultaneously in 4-hour window. Cohort is reusable across many target tickers.
- **A2 — Reply-chain evasion.** Spec uses "two authors are 'independent' if neither retweets the other in last 30d AND cosine similarity of their last-100-mention ticker history is < 0.6 AND not in same reply chain." Attacker's sybil cohort never retweets each other and posts independently across many tickers — easy to engineer cosine similarity < 0.6.
- **A3 — Cohort reuse across multiple alerts.** Same prep cohort can fire on N tickers per quarter; amortize the $450 prep cost over 30+ alerts → marginal cost per spoofed alert is ~$15.
- **A4 — TweetShift channel infiltration.** TweetShift maintains a curated cohort of analysts. The attack vector here is to *be added to that cohort* (gain credibility via real/aged content), then post the spoofed cluster ticker. Cost is the time to gain entry to the cohort (~6–12 months); ROI is permanent ability to inject signals.

**Defender vs attacker cost:**
- A1/A2/A3: defense requires real human-vs-bot detection (engagement-graph analysis, content originality detection, IP / device fingerprinting) — entire industry of social-fraud detection that the bot would need to license or rebuild. ~10,000+ LOC + ongoing model retraining. Defender cost is ~unbounded.
- A4: defense is to require multiple TweetShift cohorts to converge, not just N=4 within one cohort. Reduces attack surface but doesn't eliminate.

**Verdict: KILL** (or downgrade to xref-only with confidence cap)

**Reason (≤2 sentences):** The 90-day cohort prep + reusability makes spoofing a cluster-convergence signal cost ~$15/spoofed alert with arbitrary scaling, while defense requires industrial-grade social-fraud detection that is outside the scope of this project. The TweetShift cohort dependency is *also* an attack surface (infiltration over 6–12 months for permanent spoof capability), and the attack-defense ratio is heavily attacker-favored.

**Salvage option if not killed:** restrict to existing TweetShift-curated cohort with manual-vouching, reduce contribution to a +0.05 confidence multiplier (5% cap), and require corroboration by options-flow z-score or breakout pattern. At that point the feature is essentially unused.

---

## 14. PDUFA / AdCom Proximity Tag — VERDICT: STRENGTHEN

**Composite score (P2):** 3.30

**Attack vectors:**
- **A1 — 10-Q PDUFA date claim manipulation.** Issuer's 10-Q can claim a PDUFA date that doesn't appear in FDA calendar (because FDA hasn't pre-announced). Bot's cross-source check (FDA calendar + openFDA + 10-Q) treats this as "uncertain" — but the gate's behavior under "uncertain" is critical: if uncertain triggers suppression, attacker can suppress legitimate alerts by claiming a phantom PDUFA. If uncertain triggers an attention boost, attacker can manufacture a phantom event.
- **A2 — Sponsor-to-ticker mapping ambiguity.** Many drugs have complex licensing relationships (sponsor = subsidiary of public parent; partnership with another biotech). Bot's mapping to ticker can be ambiguous; attacker (the issuer) can disclose ambiguous language to confuse the mapping.
- **A3 — AdCom briefing-doc race.** Briefing docs sometimes appear at irregular hours. The spec mentions "race vs social-media leakage." Attacker (insider) leaks briefing-doc content via social media before the bot's hourly poll picks it up — attacker positioned, retail follows the eventual public release.

**Defender vs attacker cost:**
- A1: defense is to weight the 3 sources hierarchically — FDA calendar is ground truth, openFDA is corroboration, 10-Q is *informational only*. ~30 LOC. Cheap.
- A2: defense is manual mapping curation + a "downgrade to context-only when sponsor is < 90% confident" rule. ~100 LOC + curation effort.
- A3: defense is impossible without sub-hour polling cadence. Hourly is the spec's ceiling per FDA-page rate-limit. The attacker's social-media leak window is structural.

**Verdict: STRENGTHEN**

**Minimum hardening:**
1. **Hierarchical source-trust** (FDA calendar > openFDA > 10-Q). 10-Q-only PDUFA dates yield context-only label, never trigger gate behavior.
2. **Sponsor-to-ticker mapping must include a confidence score**; <90% confidence downgrades to context.
3. **PDUFA window suppression must be a soft modifier (0.7×), not hard-suppress.** A hard-suppress is gameable (attacker manufactures phantom PDUFA to suppress). A soft modifier degrades but doesn't kill alerts.
4. **AdCom briefing-doc detection is best-effort only**; do not promote it to standalone-trigger eligibility.

---

# Cross-Feature Attack Patterns

These are attacks that compose two or more features for multiplicative score boost — the framework's own Section 3 stacking notes inadvertently document the exact pairs an attacker should target.

## Attack X1 — "Multi-feature takeout setup spoof" (Form 4 cluster + S-4/425)

**Pair targeted:** Feature 1 + Feature 2, the framework's own called-out "very-high-conviction takeout setup."

**Sequence:**
1. Day T-14: Attacker is short the target (or accumulates a mid-sized long for the pump).
2. Day T-10: 3 friendly directors at acquirer-shell-CIK file Form 4 P-code buys totaling $300k (cluster threshold met).
3. Day T-3: Attacker files 425 from a different acquirer-shell-CIK with deal-language but referencing target as "potential strategic alternative."
4. Day T: Bot fires high-conviction "takeout" alert; retail floods in.
5. Day T+1: Attacker exits position into retail flow.

**Required attacker effort:** $300k Form 4 P-code real money (recoverable on dump) + $2k legal + 2 controlled CIKs.
**Score boost expected:** Form 4 cluster alone fires standalone-trigger (high score). S-4/425 then fires conditional standalone (paired with Form 4 cluster within 14d satisfies its 2-source rule). Bot publishes BOTH alerts inside same 14-day window — the second one explicitly cross-references the first ("smart money + M&A stack"), triggering the framework's own "Pair stacks worth flagging" amplification.
**Countered by:** Require co-filer to be a *real prior 10-K-filing entity* on 425; require Form 4 cluster's beneficial-owner check (already in Feature 1's hardening) to be enforced; require a third-party news source (Bloomberg / Reuters) corroboration before paired-stack score boost.

## Attack X2 — "13D + Reg SHO same-week stack"

**Pair targeted:** Feature 8 + Feature 11, the framework's "squeeze-pressure stack."

**Sequence:**
1. Attacker accumulates a real 5%+ position in a $1.2B-cap target (above the spec's market-cap floor for standalone Reg SHO).
2. Files 13D with "engagement" verbiage on day T-5.
3. On days T-4 to T, attacker (or counterparty) deliberately fails to deliver a small but consistent FTD on the target — pushing it onto Reg SHO threshold list at day T.
4. Bot fires:
   - 13D activist alert at T-5 (xref boost without standalone unless filer is known activist; if filer has 2 prior 13Ds via Attack X4 below, fires standalone).
   - Reg SHO entry alert at T (standalone, $1B cap).
5. Both alerts fire within 5 days — bot's xref logic stacks the two for high-conviction "squeeze + activist" thesis.
6. Attacker dumps into retail flow at T+1.

**Required attacker effort:** ~$60M of real position capital ($1.2B × 5%). 13D filing + intentional FTD over 5 days. Borrow cost on FTD position: ~$50k. Total cost: ~$50k cash + $60M working capital tied up.
**Profit:** Modest — squeeze rally on $1.2B-cap from retail flow is maybe 2–4% over 1–2 days; on $60M position that's $1.2–2.4M before slippage. Cost-to-alpha: ~30:1 favorable. Real attack.
**Countered by:** Require 13D's Item 4 to contain *specific* nomination/strategic-alternative language (not soft "engagement"); cap activist-stack weighting when filer is non-whitelisted; raise Reg SHO market-cap floor to $3B for standalone-trigger eligibility.

## Attack X3 — "FinBERT-pumped breakout"

**Pair targeted:** Feature 5 + Feature 7.

**Sequence:**
1. Pump group + paid PR-wire combination targeting a $500–800M small-mid cap.
2. T-1: GlobeNewswire press-release placed for $400 with adversarially-tuned positive-FinBERT language ("Company X exceeds Q4 guidance, FDA breakthrough designation, settles patent for $XXM").
3. FinBERT confirmer fires — first leg of 2-source.
4. T-1 to T 15:55–15:59 ET: Pump group prints buys at the close, lifting volume z above 2.0× and close above 20-day high — Feature 5 breakout fires standalone with entry/stop/target.
5. T+1 morning: pump group dumps; bot's published levels become exit liquidity for the attacker.

**Required attacker effort:** $400 PR-wire + $200k–$500k coordinated pump capital (recoverable on dump).
**Profit:** $50k–$200k from retail follow-through over 1–2 days.
**Countered by:** Require corroboration with first-class news source (Bloomberg/Reuters) for FinBERT trigger; raise Feature 5's market-cap floor to $500M; replace volume-z-score with dollar-volume z-score (limits low-float gameability); stop publishing stop-loss in alert text. **THIS IS WHY FEATURE 7 IS RECOMMENDED FOR KILL** — it's the cheapest leg of every cross-feature attack.

## Attack X4 — "Aged sock-puppet activist constellation"

**Pair targeted:** Features 8 + 13 + (potentially 1).

**Sequence (long-game, 12+ months prep):**
1. T-12mo: Attacker creates a CIK posing as a small activist fund. Files 2 nuisance 13Ds on micro-caps with cheap engagement language. Aged history accumulates.
2. T-12mo through T-3mo: Sybil sock-puppet TweetShift cohort aged in parallel (Feature 13 attack vector).
3. T-1: New 13D filed on target by aged-activist CIK (now passes "≥2 prior campaigns" gate and qualifies as known activist for Feature 8 standalone).
4. T: 4+ aged sock-puppet accounts post about the ticker in 4-hour window (Feature 13 cluster convergence fires).
5. T+1: Bot has fired multiple confirming alerts; retail floods.

**Required attacker effort:** ~12 months prep + $5–10M in 13D positions across the prep period (real capital but reusable across multiple target tickers). $450 sock-puppet aging cost.
**Profit:** Per-target alert: $50k–$200k. Reusable across ~4 targets/year for 5 years before pattern is detected = $1–4M total ROI on $5M capital tie-up = modest but real.
**Countered by:** Outcome-weighted activist-history scoring (count only campaigns reaching settlement/vote/board change); manual whitelist of confirmed activist firms; **KILL Feature 13** entirely (recommended).

## Attack X5 — "Wikipedia + TweetShift + News brigade in same hour"

**Pair targeted:** Feature 7 + 10 + 13.

**Sequence:**
1. Pump group coordinates: simultaneous Wikipedia article click campaign + 4-account TweetShift mention burst + paid PR-wire story.
2. Bot's xref aggregator: Wikipedia attention (+0.05) + TweetShift cluster (Feature 13 cluster signal) + FinBERT (Feature 7) → multiple concurrent SourceTypes — composite score multiplied by 3 SourceType contributions.
3. The composite scoring (`0.5·signal_quality + 0.3·edge_durability + 0.2·feasibility`) summing across feature contributions yields a much higher score than any one signal alone.

**Required attacker effort:** $400 PR-wire + $0 click brigade (community) + $0 sock-puppet posting = ~$400 total per attack.
**Profit:** Substantial if the bot has many followers acting on alerts.
**Countered by:** Correlation penalty (see systemic recommendation below). Killing Features 7 and 13 closes 2/3 of this attack's legs.

## Attack X6 — "Cooldown-race exploit" (cross-cutting across all Phase-2 instant-trigger features)

**Pair targeted:** ANY new instant-trigger feature wired into the same `db.py:672` `check_alert_cooldown` path that the audit confirmed has a parallel-read race for `kpak82` (26-min through a 6h cooldown).

**Sequence:**
1. Attacker positions and fires a coordinated burst of two near-simultaneous spoofed signals (e.g., two spoofed Form 4 P-codes in same 60-sec window from same beneficial owner across 2 controlled CIKs).
2. Bot's parallel-read race lets BOTH alerts pass cooldown.
3. Two distinct alerts fired on same ticker within minutes — increases retail conviction artifically.

**Required attacker effort:** Trivial — exploit the audit-known bug.
**Counter:** Implement the audit's M3 recommendation: replace ticker-level cooldown with per-analyst/per-source precision-weighted cooldown using `source_performance`. ~80 LOC. The fix should be a *precondition* of any new instant-trigger feature in this Phase-2 batch.

---

# Systemic Recommendation

**Yes — the overall composite scoring approach is attackable by correlated noise across features.**

Each feature in the basket provides a SourceType contribution to xref scoring. The scoring assumes approximate independence between SourceTypes — but several attack vectors above show that independence is exactly what an adversary attacks. Single-feature hardening cannot defend against an attacker who coordinates a cheap noise-injection across 2–3 features simultaneously.

**Recommended systemic safeguard — "correlation-aware decay penalty":**

For each ticker-window (defined as a 24h window per ticker), compute:
```
penalty = max(0, n_active_sources - 2) × suspicious_correlation_factor
```

where:
- `n_active_sources` = count of distinct SourceTypes contributing to score in the window.
- `suspicious_correlation_factor` is computed from cohort independence:
  - All sources point in the same direction in <12h: `+0.30`
  - At least one source is from a "low-trust" tier (FinBERT, Wikipedia, TweetShift cluster, news velocity): `+0.20` per low-trust source after the first.
  - At least one source has fired suspiciously soon after its respective "creation" event (e.g., 13D from CIK <90 days old, sock-puppet account in TweetShift cohort with <90d age): `+0.40` per such source.
- Final score = base_score × (1 − penalty), capped at `[0.20, 1.00]`.

This is ~150 LOC and lives once at the xref-aggregation layer (`cross_reference.py:333`), benefiting every feature in the basket without per-feature integration.

**Why this works:** A real high-conviction signal involves 2–3 *fundamentally diverse* sources (e.g., Form 4 cluster + actual options flow + first-class news) over a *natural cadence* (signals don't all arrive in same hour). An attacker's economic constraint forces them to either (a) attack 1 feature deeply (defended by per-feature hardening), or (b) attack many features cheaply but simultaneously (defended by correlation penalty). Both dimensions need defense; the systemic safeguard handles dimension (b) cheaply.

**Combined with the Phase-2 hardening recommendations above and the audit's mandatory cooldown-race fix, the system's adversarial posture moves from "naive" to "competent" — not bulletproof, but the cost-to-alpha ratio for any spoofing attack rises 5–10x, which is the practical bar.**

---

# Verdict Counts and Final Summary

| Verdict | Count | Features |
|---|---|---|
| KEEP | 3 | 1 (Form 4 cluster, with one tweak), 4 (Credit-equity divergence), 11 (Reg SHO threshold) |
| STRENGTHEN | 8 | 2 (S-4/425 M&A), 3 (Pre-FOMC drift), 5 (Breakout), 6 (Earnings gate), 8 (13D activist), 9 (SEC velocity), 10 (Wikipedia attention), 14 (PDUFA proximity) |
| KILL | 3 | 7 (FinBERT/lexicon), 12 (VIX term-structure flip), 13 (Influencer cluster-convergence) |

**Killed features rationale recap:**
- **Feature 7** is killed because adversarial-text inputs are too cheap (PR-wire at $300, BERT adversarial tokenization at $0). Defender's cost grows unbounded; salvage path collapses Feature 7 to lexicon-only confirmer with no real FinBERT contribution.
- **Feature 12** is killed primarily on signal-redundancy / low-frequency grounds, with manipulation surface as secondary; Features 3 and 4 cover the macro-regime axis adequately.
- **Feature 13** is killed because a 90-day pre-aged sock-puppet cohort costs ~$15/spoofed alert with arbitrary scaling, while defense requires industrial-grade social-fraud detection outside this project's scope.

**Highest-priority pre-Phase-3 work:**
1. Fix the audit-known cooldown race in `db.py:672` BEFORE shipping ANY new Phase-2 instant-trigger feature. (The audit's M3 recommendation; ~80 LOC.)
2. Add the systemic correlation-aware decay penalty at `cross_reference.py:333`. (~150 LOC; defends every feature simultaneously.)
3. Per-feature hardening per the STRENGTHEN sections above.
