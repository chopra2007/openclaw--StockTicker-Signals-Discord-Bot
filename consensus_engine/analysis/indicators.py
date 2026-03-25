"""Technical indicator calculations.

Pure functions operating on OHLCV price data.
All functions accept lists of floats and return computed values.
"""

from typing import Optional


def ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average.

    Returns a list the same length as prices, with None-equivalent (0.0)
    for the first (period-1) values.
    """
    if len(prices) < period:
        return [0.0] * len(prices)

    result = [0.0] * len(prices)
    multiplier = 2.0 / (period + 1)

    # SMA for the initial seed
    sma = sum(prices[:period]) / period
    result[period - 1] = sma

    for i in range(period, len(prices)):
        result[i] = (prices[i] - result[i - 1]) * multiplier + result[i - 1]

    return result


def sma(prices: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    if len(prices) < period:
        return [0.0] * len(prices)
    result = [0.0] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i - period + 1:i + 1]) / period
    return result


def rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index (latest value only).

    Uses the Wilder smoothing method (exponential).
    Returns None if insufficient data.
    """
    if len(prices) < period + 1:
        return None

    # Calculate price changes
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Initial average gain/loss
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder smoothing for remaining periods
    for i in range(period, len(deltas)):
        change = deltas[i]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> Optional[float]:
    """Average True Range (latest value only).

    Returns None if insufficient data.
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Initial ATR is SMA of first 'period' true ranges
    current_atr = sum(true_ranges[:period]) / period

    # Wilder smoothing for remaining
    for i in range(period, len(true_ranges)):
        current_atr = (current_atr * (period - 1) + true_ranges[i]) / period

    return current_atr


def vwap(prices: list[float], volumes: list[int]) -> Optional[float]:
    """Volume Weighted Average Price.

    Computes VWAP over the provided period (typically intraday).
    Returns None if no volume data.
    """
    if not prices or not volumes or len(prices) != len(volumes):
        return None

    total_pv = sum(p * v for p, v in zip(prices, volumes))
    total_v = sum(volumes)

    if total_v == 0:
        return None
    return total_pv / total_v


def relative_volume(current_volume: int, avg_volume: float) -> float:
    """Relative Volume (RVOL).

    current_volume / average_volume. Returns 0 if average is 0.
    """
    if avg_volume <= 0:
        return 0.0
    return current_volume / avg_volume


def ema_crossover(prices: list[float], fast_period: int = 9,
                  slow_period: int = 21) -> Optional[bool]:
    """Check if fast EMA is above slow EMA (bullish crossover).

    Returns True if fast EMA > slow EMA, False if not, None if insufficient data.
    """
    if len(prices) < slow_period:
        return None

    fast = ema(prices, fast_period)
    slow = ema(prices, slow_period)

    # Use the latest values
    fast_val = fast[-1]
    slow_val = slow[-1]

    if fast_val == 0 or slow_val == 0:
        return None

    return fast_val > slow_val


def price_change_pct(current: float, previous: float) -> float:
    """Calculate percentage price change."""
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100.0
