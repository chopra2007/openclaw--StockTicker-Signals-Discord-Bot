"""Shared command selection; no provider/configuration/delivery dependencies."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .research_contracts import OptionsResearch

_OPT_PT = ZoneInfo('America/Los_Angeles')
_OPT_OTM_MAX = .30
_OPT_ITM_MAX = .10


def _is_directional(strike: float, spot: float, side: str) -> bool:
    """A contract is a directional bet (vs a far-OTM lottery ticket or a deep-ITM
    hedge/stock-replacement) when its strike sits within 30% OTM / 10% ITM of
    spot. OTM/ITM flips by side: a CALL is OTM above spot, a PUT is OTM below
    spot. No spot (can't classify) -> keep it."""
    if not spot:
        return True
    otm = (strike > spot) if side == "CALL" else (strike < spot)
    dist = abs(strike - spot) / spot
    return dist <= (_OPT_OTM_MAX if otm else _OPT_ITM_MAX)


def _current_day_pool(hits: list) -> list:
    """Keep only contracts that last traded on the MOST RECENT session present
    (today during market hours, the prior session otherwise), so a stale
    high-ratio strike can't surface. Undated input is returned unchanged."""
    dated = [h for h in hits if h.last_trade_ts]
    if not dated:
        return list(hits)
    latest_day = max(
        datetime.fromtimestamp(h.last_trade_ts, _OPT_PT).date() for h in dated
    )
    return [h for h in dated
            if datetime.fromtimestamp(h.last_trade_ts, _OPT_PT).date() == latest_day]



def select_options(result, hits) -> OptionsResearch:
    pool = _current_day_pool([hit for hit in hits if _is_directional(hit.strike, hit.spot, hit.side)])
    top = max(pool, key=lambda hit: hit.vol_oi_ratio, default=None)
    calls = [hit.vol_oi_ratio for hit in pool if hit.side == 'CALL']
    puts = [hit.vol_oi_ratio for hit in pool if hit.side == 'PUT']
    ratio = result.total_put_vol / result.total_call_vol if result.total_call_vol > 0 else None
    return OptionsResearch(result, tuple(pool), top, max(calls, default=None), max(puts, default=None), ratio)
