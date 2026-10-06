"""Trade plan from real chart and options levels, each with a plain reason.

Owner report 2026-10-06: the NVDA plan had evenly spaced targets ($244.79, $250.34, $255.90: fixed
steps, no chart level behind them) and no reasoning. Every level here comes from the data (a swing
high or low, the most-traded price, a moving average, the 52-week range, the strike with the most
open option contracts, the options-implied range) and carries the reason a member reads next to it.
Pure functions: candles are the collector's daily dicts (date, open, high, low, close, volume).
"""
from dataclasses import dataclass, field
from datetime import date
import math


@dataclass
class Level:
    price: float
    weight: float
    reasons: list = field(default_factory=list)

    def why(self, limit=2):
        return ' + '.join(self.reasons[:limit])


def _day(iso):
    return date.fromisoformat(iso).strftime('%b %-d')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def atr(candles, period=14):
    if len(candles) < period + 1: return None
    ranges = [max(c['high'], p['close']) - min(c['low'], p['close']) for p, c in zip(candles[-period - 1:], candles[-period:])]
    return sum(ranges) / period


def profile(candles, bins=48):
    """Volume at price: each day's volume spread evenly over its high-low range. Returns
    (most-traded price, value-area low, value-area high), the value area holding 70% of the volume."""
    rows = [c for c in candles if _finite(c.get('volume')) and c['volume'] > 0 and c['high'] >= c['low']]
    if len(rows) < 10: return None
    low, high = min(c['low'] for c in rows), max(c['high'] for c in rows)
    if high <= low: return None
    step = (high - low) / bins
    volume = [0.0] * bins
    for c in rows:
        first, last = int((c['low'] - low) / step), min(bins - 1, int((c['high'] - low) / step))
        first = min(first, last)
        for index in range(first, last + 1): volume[index] += c['volume'] / (last - first + 1)
    poc = max(range(bins), key=volume.__getitem__)
    lo = hi = poc
    inside, total = volume[poc], sum(volume)
    while inside < 0.7 * total:
        down = volume[lo - 1] if lo > 0 else -1
        up = volume[hi + 1] if hi < bins - 1 else -1
        if up >= down: hi += 1; inside += up
        else: lo -= 1; inside += down
    centre = lambda index: low + (index + 0.5) * step
    return centre(poc), low + lo * step, low + (hi + 1) * step


def walls(frames, spot):
    """The strikes holding the most open option contracts: calls above the price, puts below it.
    frames: (calls, puts) DataFrames for the expirations of the next ~5 weeks."""
    out = []
    for side, pick in (('call', lambda k: spot < k <= spot * 1.25), ('put', lambda k: spot * 0.75 <= k < spot)):
        totals = {}
        for frame in frames[side]:
            if frame is None or frame.empty: continue
            for strike, oi in zip(frame['strike'], frame['openInterest']):
                if _finite(strike) and _finite(oi) and pick(strike): totals[float(strike)] = totals.get(float(strike), 0) + oi
        for rank, (strike, oi) in enumerate(sorted(totals.items(), key=lambda kv: -kv[1])[:2]):
            if oi > 0: out.append({'side': side, 'strike': int(strike) if strike == int(strike) else round(strike, 2), 'open_interest': int(oi), 'rank': rank})
    return out


def implied_range(frames, spot, days_wanted, today):
    """Options-implied move to the listed expiration nearest `days_wanted` calendar days away:
    price x at-the-money implied volatility x sqrt(days / 365), the usual one-standard-deviation range."""
    best = None
    for expiry in frames['expirations']:
        days = (date.fromisoformat(expiry) - today).days
        if days >= 2 and (best is None or abs(days - days_wanted) < abs(best[1] - days_wanted)): best = (expiry, days)
    if best is None: return None
    expiry, days = best
    vols = []
    for side in ('call', 'put'):
        for frame in frames[side]:
            if frame is None or frame.empty: continue
            rows = frame[frame['expiry'] == expiry]
            if rows.empty: continue
            nearest = rows.iloc[(rows['strike'] - spot).abs().argsort()[:1]]
            iv = float(nearest['impliedVolatility'].iloc[0])
            if _finite(iv) and 0.01 < iv < 5: vols.append(iv)
    if not vols: return None
    iv = sum(vols) / len(vols)
    move = spot * iv * math.sqrt(days / 365)
    return {'expiry': expiry, 'until': _day(expiry), 'days': days, 'implied_volatility_pct': round(iv * 100, 1),
            'low': round(spot - move, 2), 'high': round(spot + move, 2), 'move_pct': round(move / spot * 100, 1)}


def trend(candles, spot):
    closes = [c['close'] for c in candles]
    year = candles[-252:]
    change = lambda n: round((spot / closes[-n - 1] - 1) * 100, 1) if len(closes) > n else None
    sma = lambda n: round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None
    high, low = max(c['high'] for c in year), min(c['low'] for c in year)
    return {'change_1m_pct': change(21), 'change_3m_pct': change(63), 'change_1y_pct': change(min(251, len(closes) - 1)),
            'sma20': sma(20), 'sma50': sma(50), 'sma200': sma(200), 'high_52w': round(high, 2), 'low_52w': round(low, 2),
            'from_52w_high_pct': round((spot / high - 1) * 100, 1)}


def levels(candles, spot, average_range, option_walls, ranges):
    """Every level within 25% of the price, merged where they sit close together; a merged level
    is stronger (its weight adds up) and keeps the reasons of its parts, strongest first."""
    raw = []
    def add(price, weight, reason, swing=None):
        if _finite(price) and price > 0 and abs(price / spot - 1) <= 0.25:
            raw.append((float(price), weight, reason, swing))
    recent, k = candles[-126:], 3
    for i in range(k, len(recent) - k):
        window = recent[i - k:i + k + 1]
        c = recent[i]
        if c['high'] == max(x['high'] for x in window): add(c['high'], 2.0, None, ('high', c['date']))
        if c['low'] == min(x['low'] for x in window): add(c['low'], 2.0, None, ('low', c['date']))
    shape = profile(candles[-63:])
    if shape:
        add(shape[0], 3.0, 'most-traded price of the last 3 months')
        add(shape[1], 1.5, 'bottom of the 3-month high-volume zone')
        add(shape[2], 1.5, 'top of the 3-month high-volume zone')
    closes = [c['close'] for c in candles]
    for n, weight in ((20, 1.0), (50, 2.0), (200, 2.0)):
        if len(closes) >= n: add(sum(closes[-n:]) / n, weight, f'{n}-day average')
    year = candles[-252:]
    add(max(c['high'] for c in year), 2.5, '52-week high')
    add(min(c['low'] for c in year), 2.5, '52-week low')
    for wall in option_walls:
        noun = 'call' if wall['side'] == 'call' else 'put'
        add(wall['strike'], 2.5 if wall['rank'] == 0 else 1.5,
            f'{wall["open_interest"]:,} open {noun} contracts' + (f', the largest {noun} position' if wall['rank'] == 0 else ''))
    for window in (ranges.get('week'), ranges.get('month')):
        if window:
            when = _day(window['expiry'])
            add(window['high'], 1.5, f'top of the options-implied range to {when}')
            add(window['low'], 1.5, f'bottom of the options-implied range to {when}')
    step = 50 if spot >= 500 else 10 if spot >= 100 else 5 if spot >= 40 else 1 if spot >= 10 else 0.5
    for multiple in range(math.floor(spot * 0.85 / step), math.ceil(spot * 1.15 / step) + 1):
        add(multiple * step, 0.5, 'round number')
    # Strongest first; a level joins the nearest stronger one within the gap, never chaining onwards.
    gap = max(spot * 0.004, 0.25 * (average_range or 0))
    groups = []
    for row in sorted(raw, key=lambda row: -row[1]):
        home = min((g for g in groups if abs(g[0][0] - row[0]) <= gap), key=lambda g: abs(g[0][0] - row[0]), default=None)
        if home is None: groups.append([row])
        else: home.append(row)
    out = []
    for group in groups:
        price = group[0][0]
        parts = {}
        for _, weight, reason, swing in group:
            if swing:
                kind, day = swing
                key = 'swing ' + kind
                parts.setdefault(key, [0, []])
                parts[key][0] += weight
                parts[key][1].append(day)
            elif reason not in parts:
                parts[reason] = [weight, []]
        reasons = []
        for key, (weight, days) in sorted(parts.items(), key=lambda kv: -kv[1][0]):
            if days:
                days = sorted(set(days))
                names = [_day(d) for d in days]
                listed = names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]
                former = (key == 'swing high' and price < spot) or (key == 'swing low' and price > spot)
                noun = key + ('s' if len(days) > 1 else '')
                tail = (', old ceilings' if len(days) > 1 else ', an old ceiling') if key == 'swing high' else (', old floors' if len(days) > 1 else ', an old floor')
                reasons.append(f'{noun} on {listed}' + (tail if former else ''))
            else:
                reasons.append(key)
        out.append(Level(price, sum(row[1] for row in group), reasons))
    out.sort(key=lambda level: level.price)
    return out


def _money(value):
    return f'${value:,.2f}'


def plan(all_levels, spot, average_range, direction):
    """Long for BULLISH, short for BEARISH, none for NEUTRAL. Entry at the nearest real support
    (resistance when short), stop just past it, targets at the next real levels in the trade's way."""
    if direction not in ('BULLISH', 'BEARISH') or not average_range: return None
    long = direction == 'BULLISH'
    sign = 1 if long else -1
    a = average_range
    near = sorted((l for l in all_levels if (l.price < spot * 0.998 if long else l.price > spot * 1.002)), key=lambda l: -sign * l.price)
    far = sorted((l for l in all_levels if (l.price > spot * 1.002 if long else l.price < spot * 0.998)), key=lambda l: sign * l.price)
    side_word = 'support' if long else 'resistance'
    reach = [l for l in near if abs(spot - l.price) <= 2.5 * a]
    anchor = next((l for l in reach if l.weight >= 2), reach[0] if reach else None)
    if anchor is None:
        zone = (spot - sign * 0.5 * a, spot)
        entry_why = f'No chart level within 2.5 typical daily moves, so the zone is half a typical daily move ({_money(0.5 * a)}) from the current price.'
        base = zone[0]
    elif abs(spot - anchor.price) <= a:
        zone = (anchor.price, spot)
        entry_why = f'From the {_money(anchor.price)} {side_word} ({anchor.why()}) to the current price.'
        base = anchor.price
    else:
        zone = (anchor.price, anchor.price + sign * 0.35 * a)
        entry_why = (f'A pullback to the {_money(anchor.price)} {side_word} ({anchor.why()}). The price is '
                     f'{abs(spot - anchor.price) / a:.1f} typical daily moves away from it now, so chasing adds risk.')
        base = anchor.price
    # Stop: just past the level the entry leans on; past the next one too when it sits within a day's move.
    nearby = [l for l in near if 0.15 * a < sign * (base - l.price) <= 1.5 * a]
    backup = max(nearby, key=lambda l: l.weight, default=None)
    if backup and backup.weight >= max(4, anchor.weight if anchor else 0):
        stop = backup.price - sign * 0.25 * a
        stop_why = (f'Past the stronger {side_word} at {_money(backup.price)} ({backup.why()}) plus a quarter of a typical daily move. '
                    f'A close beyond it means both levels failed.')
    else:
        stop = base - sign * 0.5 * a
        stop_why = (f'Half a typical daily move ({_money(0.5 * a)}) past the {_money(base)} entry level. '
                    f'A close beyond it means the {side_word} failed.')
    entry = sum(zone) / 2
    risk = abs(entry - stop)
    picked, edge = [], max(zone) if long else min(zone)
    for level in (l for l in far if l.weight >= 1.5):
        before = picked[-2].price if len(picked) > 1 else edge
        if picked and sign * (level.price - picked[-1].price) < 0.6 * a:
            # Too close to the last pick to be a separate target: keep whichever is stronger.
            if level.weight > picked[-1].weight and sign * (level.price - before) >= 0.6 * a: picked[-1] = level
        elif sign * (level.price - (picked[-1].price if picked else edge)) >= 0.6 * a:
            if len(picked) == 3: break
            picked.append(level)
    targets = [{'price': round(level.price, 2), 'why': level.why()} for level in picked]
    multiple = 2
    while len(targets) < 3 and risk > 0 and multiple < 20:
        last = targets[-1]['price'] if targets else edge
        price = entry + sign * multiple * risk
        if sign * (price - last) >= 0.6 * a:
            targets.append({'price': round(price, 2), 'why': f'no chart level further out; {multiple} times the risk from entry to stop'})
        multiple += 1
    low, high = sorted(zone)
    return {'side': 'long' if long else 'short', 'entry_low': round(low, 2), 'entry_high': round(high, 2), 'entry_why': entry_why,
            'stop': round(stop, 2), 'stop_why': stop_why, 'targets': targets,
            'reward_to_risk': round(abs(targets[0]['price'] - entry) / risk, 1) if risk else None}


def key_levels(all_levels, spot, count=3):
    """The strongest nearby levels on each side, for the write-up and for a neutral signal."""
    strong = sorted((l for l in all_levels if l.weight >= 2), key=lambda l: abs(l.price - spot))
    below = [l for l in strong if l.price < spot][:count]
    above = [l for l in strong if l.price > spot][:count]
    row = lambda kind, l: {'kind': kind, 'price': round(l.price, 2), 'why': l.why()}
    return [row('support', l) for l in below] + [row('resistance', l) for l in above]
