"""The 6 technical filters as a pure function (no config, DB or network imports).

Shared by the bot (analysis/technical.py) and the member dashboard's isolated compute.
"""
from consensus_engine.models import TechnicalFilter
from consensus_engine.analysis import indicators


def run_filters(quote: dict, candles: dict, direction: str, filter_cfg: dict) -> list[TechnicalFilter]:
    """Run all 6 technical filters.

    quote: Finnhub quote {c, o, h, l, pc, dp, t}
    candles: yfinance history {o[], h[], l[], c[], v[], t[]}
    direction: "long" or "short" — flips filter logic for bearish signals
    filter_cfg: the `technical.filters` settings block (explicit; no config import)
    """
    is_short = direction == "short"
    results = []

    current_price = quote.get("c", 0)
    prev_close = quote.get("pc", 0)
    closes = candles.get("c", [])
    highs = candles.get("h", [])
    lows = candles.get("l", [])
    volumes = candles.get("v", [])

    # 1. Relative Volume (RVOL)
    rvol_threshold = filter_cfg.get("rvol_threshold", 2.0)
    rvol_lookback = filter_cfg.get("rvol_lookback_days", 20)
    if volumes and len(volumes) >= rvol_lookback:
        avg_vol = sum(volumes[-rvol_lookback:]) / rvol_lookback
        current_vol = volumes[-1] if volumes else 0
        rvol_val = indicators.relative_volume(current_vol, avg_vol)
        results.append(TechnicalFilter(
            name="RVOL",
            value=round(rvol_val, 2),
            threshold=f"> {rvol_threshold}x",
            passed=rvol_val >= rvol_threshold,
        ))
    else:
        results.append(TechnicalFilter(
            name="RVOL", value=0, threshold=f"> {rvol_threshold}x", passed=False,
        ))

    # 2. Price vs VWAP (above for long, below for short)
    if filter_cfg.get("vwap_enabled", True) and closes and volumes:
        vwap_val = indicators.vwap(closes[-20:], volumes[-20:])
        if vwap_val and current_price:
            if is_short:
                vwap_passed = current_price < vwap_val
                vwap_threshold = f"< {round(vwap_val, 2)} (VWAP)"
            else:
                vwap_passed = current_price > vwap_val
                vwap_threshold = f"> {round(vwap_val, 2)} (VWAP)"
            results.append(TechnicalFilter(
                name="VWAP",
                value=round(current_price, 2),
                threshold=vwap_threshold,
                passed=vwap_passed,
            ))
        else:
            results.append(TechnicalFilter(
                name="VWAP", value=0, threshold="above VWAP", passed=False,
            ))

    # 3. RSI (long: 40-75 range, short: 60-85 overbought range)
    rsi_period = filter_cfg.get("rsi_period", 14)
    if is_short:
        rsi_lower = filter_cfg.get("rsi_lower_short", 60)
        rsi_upper = filter_cfg.get("rsi_upper_short", 85)
    else:
        rsi_lower = filter_cfg.get("rsi_lower", 40)
        rsi_upper = filter_cfg.get("rsi_upper", 75)
    if closes and len(closes) >= rsi_period + 1:
        rsi_val = indicators.rsi(closes, rsi_period)
        if rsi_val is not None:
            results.append(TechnicalFilter(
                name="RSI",
                value=round(rsi_val, 1),
                threshold=f"{rsi_lower}-{rsi_upper}",
                passed=rsi_lower <= rsi_val <= rsi_upper,
            ))
        else:
            results.append(TechnicalFilter(
                name="RSI", value=0, threshold=f"{rsi_lower}-{rsi_upper}", passed=False,
            ))
    else:
        results.append(TechnicalFilter(
            name="RSI", value=0, threshold=f"{rsi_lower}-{rsi_upper}", passed=False,
        ))

    # 4. EMA Crossover (long: fast > slow, short: fast < slow / death cross)
    ema_fast = filter_cfg.get("ema_fast", 9)
    ema_slow = filter_cfg.get("ema_slow", 21)
    if closes and len(closes) >= ema_slow:
        crossover = indicators.ema_crossover(closes, ema_fast, ema_slow)
        fast_vals = indicators.ema(closes, ema_fast)
        slow_vals = indicators.ema(closes, ema_slow)
        diff = round(fast_vals[-1] - slow_vals[-1], 2) if fast_vals and slow_vals else 0
        if is_short:
            ema_passed = diff < 0  # death cross: fast < slow
            ema_threshold = f"{ema_fast}EMA < {ema_slow}EMA"
        else:
            ema_passed = crossover is True
            ema_threshold = f"{ema_fast}EMA > {ema_slow}EMA"
        results.append(TechnicalFilter(
            name="EMA Cross",
            value=diff,
            threshold=ema_threshold,
            passed=ema_passed,
        ))
    else:
        results.append(TechnicalFilter(
            name="EMA Cross", value=0, threshold=f"{ema_fast}EMA > {ema_slow}EMA", passed=False,
        ))

    # 5. Price Change % (long: >= +min_pct, short: <= -min_pct)
    min_pct = filter_cfg.get("price_change_min_pct", 2.0)
    if current_price and prev_close:
        pct = indicators.price_change_pct(current_price, prev_close)
        if is_short:
            pct_passed = pct <= -min_pct
            pct_threshold = f"< -{min_pct}%"
        else:
            pct_passed = pct >= min_pct
            pct_threshold = f"> +{min_pct}%"
        results.append(TechnicalFilter(
            name="Price Change",
            value=round(pct, 2),
            threshold=pct_threshold,
            passed=pct_passed,
        ))
    else:
        results.append(TechnicalFilter(
            name="Price Change", value=0, threshold=f"> +{min_pct}%", passed=False,
        ))

    # 6. ATR Breakout
    atr_period = filter_cfg.get("atr_period", 14)
    atr_mult = filter_cfg.get("atr_multiplier", 1.5)
    if highs and lows and closes and len(highs) >= atr_period + 1:
        atr_val = indicators.atr(highs, lows, closes, atr_period)
        if atr_val and prev_close and current_price:
            price_move = abs(current_price - prev_close)
            breakout_ratio = round(price_move / atr_val, 2) if atr_val > 0 else 0
            results.append(TechnicalFilter(
                name="ATR Breakout",
                value=breakout_ratio,
                threshold=f"> {atr_mult}x ATR",
                passed=price_move >= atr_val * atr_mult,
            ))
        else:
            results.append(TechnicalFilter(
                name="ATR Breakout", value=0, threshold=f"> {atr_mult}x ATR", passed=False,
            ))
    else:
        results.append(TechnicalFilter(
            name="ATR Breakout", value=0, threshold=f"> {atr_mult}x ATR", passed=False,
        ))

    return results
