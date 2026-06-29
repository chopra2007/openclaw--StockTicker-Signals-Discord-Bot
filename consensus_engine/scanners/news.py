"""News Cascade — 5-tier news source for catalyst detection.

All enabled tiers race concurrently; the first passed=True wins and the
others are cancelled. Brave self-gates on `news_cascade.brave_daily_budget`
so concurrent firing does not exhaust the free quota.

Tiers (configurable via news_cascade.tiers):
  - recent_earnings (synthesizes from most recent print)
  - finnhub /company-news
  - google_rss
  - brave search
  - searxng (self-hosted)
"""

import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.models import CatalystResult, TickerSignal, SourceType, Sentiment
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.utils.burst_retry import classify_retry, parse_retry_after, RetryClass
from consensus_engine.utils.circuit_breaker import circuit_breaker
from consensus_engine.scanners.searxng import search_searxng

log = logging.getLogger("consensus_engine.scanner.news")


async def _report_news_failure(source: str, *, status: int | None = None,
                               body: str | None = None, headers=None,
                               exc: Exception | None = None) -> None:
    """C3 + C5: report a news-tier failure to the single backoff authority
    (rate_limiter) AND feed the circuit breaker (which fires the throttled
    dead-source ops alert). C3: only OVERRIDE the normal exponential backoff
    when a server gave a real Retry-After on a QUOTA failure. C5: the breaker
    only gates/persists/alerts when its flags are on, so this is behavior-
    neutral until those flags flip."""
    parsed = None
    if cfg.get("retry.use_classifier", False):
        cls = classify_retry(http_status=status, body=body, exc=exc)
        if cls is RetryClass.QUOTA_BLOCKED:
            text = body or ""
            if headers is not None and hasattr(headers, "get"):
                ra = headers.get("Retry-After")
                if ra:
                    text = f"{text} Retry-After: {ra}"
            parsed = parse_retry_after(text)
    if parsed:
        rate_limiter.report_failure(source, retry_after=min(parsed, 600.0))
        log.info("news %s QUOTA_BLOCKED — Retry-After %.0fs", source, min(parsed, 600.0))
    else:
        rate_limiter.report_failure(source)
    await circuit_breaker.note_failure(source, status=status, body=body, exc=exc)


async def _report_news_success(source: str) -> None:
    """C5: a successful fetch resets rate_limiter backoff and closes the breaker."""
    rate_limiter.report_success(source)
    await circuit_breaker.note_success(source)

_CATALYST_PATTERNS = [
    (["short squeeze", "squeeze", "short interest"], "Short Squeeze"),
    (["acquisition", "merger", "acquire", "buyout", "m&a"], "M&A"),
    (["upgrade", "price target raised", "outperform"], "Analyst Upgrade"),
    (["downgrade", "price target cut", "underperform"], "Analyst Downgrade"),
    (["earnings beat", "beat estimates", "revenue beat", "eps beat"], "Earnings Beat"),
    (["earnings miss", "missed estimates", "revenue miss", "eps miss"], "Earnings Miss"),
    (["fda approv", "fda clear", "drug approv"], "FDA Approval"),
    (["fda reject", "fda deny", "clinical fail"], "FDA Rejection"),
    (["government contract", "defense contract", "military contract"], "Government Contract"),
    (["partnership", "collaboration", "joint venture", "deal with"], "Partnership"),
    (["ipo", "public offering", "going public"], "IPO"),
    (["stock split", "reverse split"], "Stock Split"),
    (["dividend", "special dividend", "dividend increase"], "Dividend"),
    (["insider buy", "insider purchas"], "Insider Buying"),
    (["insider sell", "insider sold"], "Insider Selling"),
    (["sec filing", "13f", "13d", "sec investigat"], "SEC Filing"),
    (["patent", "intellectual property"], "Patent"),
    (["product launch", "new product", "announced", "unveil"], "Product Launch"),
    (["revenue guidance", "raised guidance", "lowered guidance"], "Guidance Update"),
    (["breaking", "just announced", "just reported"], "Breaking News"),
]


def _classify_catalyst(text: str) -> Optional[str]:
    """Classify catalyst type from text."""
    lower = text.lower()
    for patterns, label in _CATALYST_PATTERNS:
        if any(p in lower for p in patterns):
            return label
    return None


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else "unknown"


def _is_trusted_source(url: str) -> bool:
    """Check if URL is from a trusted news source."""
    trusted = cfg.get("news.trusted_sources", [])
    url_lower = url.lower()
    return any(source in url_lower for source in trusted)


async def _get_search_query(ticker: str) -> str:
    """Build a better search query using company name if available."""
    meta = await db.get_ticker_metadata(ticker, max_age_days=30)
    if meta and meta.get("name"):
        return f'"{meta["name"]}" OR "${ticker}" stock'
    return f"${ticker} stock"


def _headline_relevant(headline: str, ticker: str, company_name: str = "") -> bool:
    """Check if a headline actually mentions the ticker or company."""
    upper = headline.upper()
    if ticker in upper:
        return True
    if company_name and company_name.lower() in headline.lower():
        return True
    return False


async def _get_company_name(ticker: str) -> str:
    """Get cached company name for relevance checking."""
    meta = await db.get_ticker_metadata(ticker, max_age_days=30)
    if meta and meta.get("name"):
        return meta["name"]
    return ""


def _build_catalyst(
    ticker: str,
    title: str,
    url: str,
    catalyst_type: str,
    body: str = "",
    *,
    eps_surprise_pct: float | None = None,
    eps_estimate: float | None = None,
    eps_period: str = "",
) -> CatalystResult:
    """Build a CatalystResult from a single news hit.

    `eps_*` are populated only by the earnings-recap tier (I12); every other
    caller leaves them at the defaults, so the magnitude bonus only ever sees
    a number when the catalyst really is an earnings print.
    """
    return CatalystResult(
        ticker=ticker,
        catalyst_summary=title[:200],
        catalyst_type=catalyst_type,
        news_sources=[_extract_domain(url)],
        source_urls=[url],
        confidence=0.8 if catalyst_type != "Market Movement" else 0.5,
        catalyst_body=(body or "")[:1000],
        eps_surprise_pct=eps_surprise_pct,
        eps_estimate=eps_estimate,
        eps_period=eps_period,
    )


def _format_money(amount) -> str:
    """Compact USD: 68132000000 → '$68.13B', 35080000000 → '$35.08B'."""
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return ""
    abs_n = abs(n)
    if abs_n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if abs_n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if abs_n >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"


async def _search_recent_earnings(ticker: str) -> Optional[CatalystResult]:
    """Highest-priority tier: synthesize a catalyst from the most recent print.

    Finnhub /calendar/earnings carries revenueActual + epsActual which the
    news headline summaries usually omit. Putting them in catalyst_body
    means the synth prompt sees the real Q numbers instead of having to
    guess from headline keywords.
    """
    from consensus_engine.scanners.earnings_calendar import fetch_recent_earnings_for_ticker

    try:
        recap = await fetch_recent_earnings_for_ticker(ticker)
    except Exception as e:
        log.debug("recent_earnings tier error for %s: %s", ticker, e)
        return None
    if not recap or not recap.get("period"):
        return None

    period = recap["period"]
    eps_a, eps_e = recap.get("eps_actual"), recap.get("eps_estimate")
    eps_surprise_pct = recap.get("eps_surprise_pct")
    rev_a, rev_yoy = recap.get("revenue_actual"), recap.get("revenue_yoy_pct")
    parts: list[str] = [f"{ticker} reported earnings for the quarter ending {period}."]
    if rev_a is not None:
        rev_str = f"Revenue {_format_money(rev_a)}"
        if rev_yoy is not None:
            rev_str += f" ({rev_yoy:+.1f}% YoY)"
        parts.append(rev_str + ".")
    if eps_a is not None:
        try:
            eps_str = f"EPS ${float(eps_a):.2f}"
        except (TypeError, ValueError):
            eps_str = f"EPS {eps_a}"
        if eps_e is not None:
            try:
                eps_str += f" vs est ${float(eps_e):.2f}"
            except (TypeError, ValueError):
                pass
        if eps_surprise_pct is not None:
            try:
                eps_str += f" ({float(eps_surprise_pct):+.1f}% surprise)"
            except (TypeError, ValueError):
                pass
        parts.append(eps_str + ".")

    body = " ".join(parts)
    log.info("Recent earnings catalyst for %s: %s", ticker, period)

    # I12: thread the numeric surprise % + estimate denominator + period date
    # onto the CatalystResult so the scorer (cross_reference.py) can apply the
    # magnitude bonus + denominator/freshness guards. Coerce to float; any
    # non-numeric value stays None so the bonus simply doesn't fire.
    def _as_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return _build_catalyst(
        ticker,
        title=f"{ticker} reported earnings for quarter ending {period}",
        url="https://finnhub.io/api/v1/stock/earnings",
        catalyst_type="Earnings Report",
        body=body,
        eps_surprise_pct=_as_float(eps_surprise_pct),
        eps_estimate=_as_float(eps_e),
        eps_period=str(period or ""),
    )


async def _search_finnhub_news(ticker: str) -> Optional[CatalystResult]:
    """Search Finnhub company news endpoint."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return None
    if not circuit_breaker.allow("finnhub_news"):  # C5 dead-source gate
        return None
    if not await rate_limiter.acquire("finnhub_news"):
        return None

    days_back = cfg.get("news_cascade.finnhub_news_days_back", 2)
    from datetime import datetime, timedelta
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        session = await get_session()
        url = "https://finnhub.io/api/v1/company-news"
        params = {"symbol": ticker, "from": from_date, "to": to_date, "token": api_key}
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                await _report_news_failure("finnhub_news", status=resp.status, headers=resp.headers)
                return None
            articles = await resp.json()
            await _report_news_success("finnhub_news")

        if not isinstance(articles, list):
            return None

        for article in articles[:10]:
            headline = article.get("headline", "")
            source = article.get("source", "")
            article_url = article.get("url", "")
            summary = article.get("summary", "")
            full_text = f"{headline} {summary} {source}"
            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(article_url):
                log.info("Finnhub news catalyst for %s: %s (%s)", ticker, catalyst_type, source)
                return _build_catalyst(ticker, headline, article_url, catalyst_type, body=summary)

        return None
    except Exception as e:
        log.warning("Finnhub news error for %s: %s", ticker, e)
        await _report_news_failure("finnhub_news", exc=e)
        return None


async def _search_google_news_rss(ticker: str) -> Optional[CatalystResult]:
    """Search Google News via RSS feed (free, no auth)."""
    if not circuit_breaker.allow("google_news_rss"):  # C5 dead-source gate
        return None
    if not await rate_limiter.acquire("google_news_rss"):
        return None

    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)
    query = search_query.replace('"', '').replace(' ', '+')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        session = await get_session()
        async with session.get(
            rss_url,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            if resp.status != 200:
                await _report_news_failure("google_news_rss", status=resp.status, headers=resp.headers)
                return None
            xml_text = await resp.text()
            await _report_news_success("google_news_rss")

        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            source_el = item.find("source")
            source_name = source_el.text if source_el is not None else ""

            if not _headline_relevant(title, ticker, company_name):
                continue

            catalyst_type = _classify_catalyst(title)
            is_trusted = _is_trusted_source(link) or any(
                s.lower() in source_name.lower()
                for s in cfg.get("news.trusted_sources", [])
            )

            if catalyst_type and is_trusted:
                log.info("Google RSS catalyst for %s: %s (%s)", ticker, catalyst_type, source_name)
                return _build_catalyst(ticker, title, link, catalyst_type)

        return None
    except Exception as e:
        log.warning("Google News RSS error for %s: %s", ticker, e)
        await _report_news_failure("google_news_rss", exc=e)
        return None


_BRAVE_COUNTER_PATH = Path(".omc/state/news_cascade_brave_counter.json")


def _brave_counter_today() -> int:
    """Return today's Brave call count from the on-disk counter (0 if absent
    or the stored day is stale)."""
    try:
        raw = _BRAVE_COUNTER_PATH.read_text()
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("day_utc") != today:
        return 0
    try:
        return int(data.get("count", 0))
    except (TypeError, ValueError):
        return 0


def _bump_brave_counter() -> None:
    """Increment today's Brave call counter. Resets if the day rolled over."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = _brave_counter_today() + 1
    try:
        _BRAVE_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BRAVE_COUNTER_PATH.write_text(
            json.dumps({"day_utc": today, "count": n})
        )
    except OSError as e:
        log.warning("Failed to write Brave counter: %s", e)


def _brave_budget_ok() -> bool:
    """True if today's Brave-tier usage is below `news_cascade.brave_daily_budget`."""
    cap = int(cfg.get("news_cascade.brave_daily_budget", 50))
    return _brave_counter_today() < cap


# Circuit breaker: tripped on an HTTP 402 (Brave monthly quota exhausted) so the
# tier stops issuing doomed requests for the rest of the process lifetime. The
# monthly cap clears at the billing boundary, so a process restart resets it.
_brave_quota_exhausted = False


async def _search_brave(ticker: str) -> Optional[CatalystResult]:
    """Search Brave for news. Gated by news_cascade.brave_daily_budget so
    parallel cascade firing doesn't blow the free tier quota."""
    global _brave_quota_exhausted
    if _brave_quota_exhausted:
        return None
    api_key = cfg.get_api_key("brave_search")
    if not api_key:
        return None
    if not _brave_budget_ok():
        cap = cfg.get("news_cascade.brave_daily_budget", 50)
        log.info("news_cascade: Brave daily cap (%d) reached, skipping tier", cap)
        return None
    if not circuit_breaker.allow("brave_search"):  # C5 dead-source gate
        return None
    if not await rate_limiter.acquire("brave_search"):
        return None

    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)

    try:
        session = await get_session()
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
        params = {
            "q": f"{search_query} news today",
            "count": cfg.get("news.max_search_results", 10),
            "freshness": "pd",
        }
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                if resp.status == 402:
                    _brave_quota_exhausted = True
                    log.warning("Brave monthly quota exhausted (HTTP 402) — "
                                "circuit open until restart")
                await _report_news_failure("brave_search", status=resp.status, headers=resp.headers)
                return None
            data = await resp.json()
            await _report_news_success("brave_search")
            _bump_brave_counter()

        for r in data.get("web", {}).get("results", []):
            title = r.get("title", "")
            result_url = r.get("url", "")
            description = r.get("description", "")
            full_text = f"{title} {description}"

            if not _headline_relevant(full_text, ticker, company_name):
                continue

            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(result_url):
                log.info("Brave catalyst for %s: %s", ticker, catalyst_type)
                return _build_catalyst(ticker, title, result_url, catalyst_type, body=description)

        return None
    except Exception as e:
        log.warning("Brave search error for %s: %s", ticker, e)
        await _report_news_failure("brave_search", exc=e)
        return None


async def _search_searxng(ticker: str) -> Optional[CatalystResult]:
    """Search SearXNG for news (self-hosted, unlimited)."""
    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)
    results = await search_searxng(f"{search_query} news")
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        full_text = f"{title} {content}"

        if not _headline_relevant(full_text, ticker, company_name):
            continue

        catalyst_type = _classify_catalyst(full_text)

        if catalyst_type and _is_trusted_source(url):
            log.info("SearXNG catalyst for %s: %s", ticker, catalyst_type)
            return _build_catalyst(ticker, title, url, catalyst_type, body=content)

    return None


async def _news_cascade_serial(
    ticker: str,
    tier_names: list[str],
    tier_funcs: dict,
) -> Optional[CatalystResult]:
    """Run cascade tiers serially in priority order; return on first hit.

    Used when `news_cascade.parallel: false` (the safer default). Preserves
    the tier priority ordering with no concurrent racing exposure.
    """
    for tier_name in tier_names:
        func = tier_funcs.get(tier_name)
        if not func:
            continue
        try:
            result = await func(ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("news_cascade serial tier '%s' error: %s", tier_name, exc)
            continue
        if result and getattr(result, "passed", False):
            log.info("News cascade hit at tier '%s' for %s", tier_name, ticker)
            return result
    log.debug("News cascade: no catalyst found for %s across all tiers", ticker)
    return None


async def news_cascade(ticker: str) -> Optional[CatalystResult]:
    """Run the configured tiers and return the first passed=True result.

    When `news_cascade.parallel: true`, all tiers race concurrently via
    asyncio.as_completed and pending tasks are cancelled on the first hit.

    When `news_cascade.parallel: false` (default — safer, no race exposure),
    tiers are awaited serially in priority order with short-circuit on hit.

    Both paths preserve the tier priority ordering for the hit case; parallel
    mode uses score-then-take-N dedup on concurrent results (idempotent URL set).
    """
    tiers = cfg.get(
        "news_cascade.tiers",
        ["recent_earnings", "finnhub", "google_rss", "brave", "searxng"],
    )

    tier_funcs = {
        "recent_earnings": _search_recent_earnings,
        "finnhub": _search_finnhub_news,
        "google_rss": _search_google_news_rss,
        "brave": _search_brave,
        "searxng": _search_searxng,
    }

    parallel = bool(cfg.get("news_cascade.parallel", False))
    if not parallel:
        return await _news_cascade_serial(ticker, tiers, tier_funcs)

    # Parallel path — all tiers race; first passed=True wins.
    tasks: list[asyncio.Task] = []
    task_to_tier: dict[asyncio.Task, str] = {}
    for tier_name in tiers:
        func = tier_funcs.get(tier_name)
        if not func:
            continue
        t = asyncio.create_task(func(ticker), name=f"news_cascade:{tier_name}")
        tasks.append(t)
        task_to_tier[t] = tier_name

    if not tasks:
        return None

    timeout_sec = float(cfg.get("news_cascade.parallel_timeout_sec", 12.0))
    hit: Optional[CatalystResult] = None
    hit_tier: Optional[str] = None
    try:
        for fut in asyncio.as_completed(tasks, timeout=timeout_sec):
            try:
                result = await fut
            except asyncio.CancelledError:
                continue
            except Exception as exc:  # noqa: BLE001 — keep racing on tier errors
                log.warning("news_cascade tier task error: %s", exc)
                continue
            if result and getattr(result, "passed", False):
                hit = result
                for done_t, name in task_to_tier.items():
                    if (done_t.done() and not done_t.cancelled()
                            and done_t.exception() is None
                            and done_t.result() is result):
                        hit_tier = name
                        break
                break
    except asyncio.TimeoutError:
        log.debug("news_cascade: timeout (%.1fs) for %s", timeout_sec, ticker)

    pending = [t for t in tasks if not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    if hit:
        log.info("News cascade hit at tier '%s' for %s", hit_tier or "?", ticker)
        return hit
    log.debug("News cascade: no catalyst found for %s across all tiers", ticker)
    return None
