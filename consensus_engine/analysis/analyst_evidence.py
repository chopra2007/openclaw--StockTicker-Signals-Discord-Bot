"""Shared source checks for analyst bias; never choose the model's direction.

Recognize directional language beyond buy/sell, while keeping ambiguous options,
negated setups and ungrounded image readings out of group cards.
"""
import math
import re

OPTION_RE = re.compile(r"\b(?:calls?|puts?|\d+(?:\.\d+)?\s*[cp])\b", re.I)
OPTION_SIDE_RE = re.compile(
    r"\b(?:buy|buying|bought|long|sell|selling|sold|short|write|writing|wrote)\b", re.I,
)
_LONG = re.compile(
    r"\b(?:long(?![- ]term\b)|buy|buying|bought|bullish|add|adding|added|breakout|broke|"
    r"reclaim|reclaimed|reclaiming|upside|bounce|bouncing|above|purchased?|"
    r"overweight|outperform|upgraded?|upgrades|cup and handle|"
    r"break(?:s|ing)? out|top (?:\w+ ){0,2}pick|"
    r"beat(?:s|ing)? (?:\w+ ){0,3}(?:estimates?|earnings|consensus)|"
    r"exceed(?:s|ed|ing)?|surpass(?:es|ed|ing)?|"
    r"rais(?:e|es|ed|ing) (?:\w+ ){0,2}(?:guidance|estimates?|target)|"
    r"winding up for a move|to \$?\d+(?:\.\d+)? (?:coming|again|soon)|"
    r"(?:run|rally|rallied|ripping|rip|push) (?:to|higher)|"
    r"(?:up|gained|rallied) (?:about |more than |over )?\d+(?:\.\d+)?%)(?!\w)", re.I,
)
_SHORT = re.compile(
    r"\b(?:short(?![- ]term\b)|sell|selling|sold|bearish|fade|fading|breakdown|"
    r"lost support|downside|below|reject|rejected|rejecting|"
    r"underweight|underperform|downgrad(?:e|ed|es)|break(?:s|ing)? down|"
    r"miss(?:es|ed|ing)? (?:\w+ ){0,3}(?:estimates?|earnings|consensus)|"
    r"cut(?:s|ting)? (?:\w+ ){0,2}(?:guidance|estimates?|target)|"
    r"(?:down|fell|lost) (?:about |more than |over )?\d+(?:\.\d+)?%)(?!\w)", re.I,
)
_NEGATED = re.compile(r"\b(?:no|not|never|failed|without|isn't|isn’t)\s+(?:(?:longer|a|the|looking|really|very|yet|necessarily)\s+){0,3}$", re.I)
_FAILED_AFTER = re.compile(r"^\s*(?:has |had |is |was )?(?:failed|failure|did not|didn't|didn’t|never happened)\b", re.I)
_OPTION_ACTOR = re.compile(r"\b(calls?|puts?)\s+(buyers?|sellers?)\b", re.I)
_NUMBER = r"\$?(-?\d[\d,]*(?:\.\d+)?)\s*([bmk%]?)"
_METRIC = re.compile(
    r"\b(?:revenue|sales|eps|deliver(?:ed|ies)|gross margin)\b[^\n;]{0,24}?" + _NUMBER +
    r"[^\n;]{0,35}?\b(?:vs\.?|versus|compared to|beats?|beating|miss(?:es|ed)?)\s*(?:(?:consensus|est\.?|estimate[ds]?|expected)(?: of)?\s*)?" +
    _NUMBER + r"(?:\s*(?:est\.?|estimate[ds]?|expected|consensus))?", re.I,
)


def _metric_bias(text: str) -> str | None:
    signs = set()
    scale = {"b": 1e9, "m": 1e6, "k": 1e3, "%": 1, "": 1}
    for match in _METRIC.finditer(text):
        actual, unit, expected, expected_unit = match.groups()
        # Omitted units inherit the explicitly stated unit; never mix % and money.
        unit, expected_unit = unit.lower(), expected_unit.lower()
        if unit and expected_unit and (unit == "%") != (expected_unit == "%"):
            continue
        unit, expected_unit = unit or expected_unit, expected_unit or unit
        left = float(actual.replace(",", "")) * scale[unit]
        right = float(expected.replace(",", "")) * scale[expected_unit]
        if left != right:
            signs.add("long" if left > right else "short")
    return next(iter(signs)) if len(signs) == 1 else None


def _option_bias(text: str) -> str | None:
    if re.search(r"\b(?:spread|straddle|strangle|rolled?|rolling|closing)\b", text, re.I):
        return None
    signs = set()
    for contract_match in OPTION_RE.finditer(text):
        before = text[:contract_match.start()]
        start = max((m.end() for m in re.finditer(r"[\n;!?]|\.(?!\d)", before)), default=0)
        actions = list(OPTION_SIDE_RE.finditer(text, start, contract_match.start()))
        if not actions:
            continue
        action = actions[-1]
        if contract_match.start() - action.end() > 60 or _NEGATED.search(text[max(start, action.start() - 30):action.start()]):
            continue
        bridge = text[action.end():contract_match.start()]
        if re.search(r"\bshares?\b", bridge, re.I):
            continue
        contract = contract_match.group()
        buy = action.group().lower() in {"buy", "buying", "bought", "long"}
        call = contract.lower().endswith("c") or contract.lower().startswith("call")
        signs.add("long" if buy == call else "short")
    for match in _OPTION_ACTOR.finditer(text):
        if _NEGATED.search(text[max(0, match.start() - 30):match.start()]):
            continue
        call = match[1].lower().startswith("call")
        buy = match[2].lower().startswith("buyer")
        signs.add("long" if buy == call else "short")
    return next(iter(signs)) if len(signs) == 1 else None


def direction_context(text: str, span: tuple[int, int] | None, ticker: str) -> str:
    """Expand a quote within its source clause, retaining negation on either side."""
    if span is None:
        return text
    start, end = span
    separators = list(re.finditer(r"[\n;!?]|\.(?!\d)", text))
    left = max((m.end() for m in separators if m.end() <= start), default=0)
    right = min((m.start() for m in separators if m.start() >= end), default=len(text))
    matches = list(re.finditer(r"\$([A-Za-z]{1,10})\b", text))
    prior_other = [m for m in matches if left <= m.start() < start and m[1].upper() != ticker.upper()]
    own_anchor = [m for m in matches if left <= m.start() < end and m[1].upper() == ticker.upper()]
    if prior_other and own_anchor:
        left = own_anchor[-1].start()
    right = min(right, min((m.start() for m in matches if m.start() >= end and m[1].upper() != ticker.upper()), default=right))
    return text[left:right]


def ticker_text_context(text: str, ticker: str) -> str:
    matches = list(re.finditer(rf"(?<![A-Za-z0-9])\$?{re.escape(ticker)}(?![A-Za-z0-9])", text, re.I))
    if matches:
        return "\n".join(direction_context(text, m.span(), ticker) for m in matches)
    named = {symbol.upper() for symbol in re.findall(r"\$([A-Za-z]{1,10})\b", text)}
    return text if not named or named == {ticker.upper()} else ""


def shared_ticker_subject(text: str, span: tuple[int, int], ticker: str) -> bool:
    """A quote cannot detach the last symbol of a coordinated subject."""
    boundaries = list(re.finditer(r"[\n;!?]|\.(?!\d)", text[:span[0]]))
    left = boundaries[-1].end() if boundaries else 0
    anchors = list(re.compile(r"\$([A-Za-z]{1,10})\b").finditer(text, left, span[1]))
    own = [i for i, anchor in enumerate(anchors) if anchor[1].upper() == ticker.upper()]
    if not own or own[-1] == 0:
        return False
    anchor, prior = anchors[own[-1]], anchors[own[-1] - 1]
    return prior[1].upper() != ticker.upper() and bool(re.fullmatch(
        r"[\s,/&+]*(?:(?:and|or|plus|with|versus|vs\.?)\s*)?",
        text[prior.end():anchor.start()], re.I,
    ))


def comparison_direction(text: str, *, numeric_only: bool = False) -> str | None:
    """Infer only specific event/setup evidence, never generic long/add words."""
    metric = _metric_bias(text)
    if _METRIC.search(text):
        return metric
    if numeric_only:
        return None
    specific = re.search(
        r"\b(?:top (?:\w+ ){0,2}pick|upgrad\w*|downgrad\w*|overweight|underweight|"
        r"outperform|underperform|(?:raised|cut) (?:\w+ ){0,2}guidance|"
        r"purchased?[^\n;]{0,60}\bshares?|breakout|breakdown|broke resistance|break(?:s|ing)? (?:out|down)|"
        r"winding up for a move|to \$?\d+(?:\.\d+)? (?:again|coming|soon)|"
        r"(?:through|above)\s+\d+[^\n;]{0,35}\bsee\s+\d+)\b", text, re.I,
    )
    if not specific or unsided_option(text):
        return None
    supported = [side for side in ("long", "short") if direction_is_supported(side, text)]
    return supported[0] if len(supported) == 1 else None


def direction_is_supported(direction: str, text: str) -> bool:
    if direction not in {"long", "short"}:
        return False
    if OPTION_RE.search(text):
        return _option_bias(text) == direction
    targets = re.search(r"\b(?:through|above)\s+\$?(\d+(?:\.\d+)?)\+?[^\n;]{0,35}\b(?:see|run to|target)\s+\$?(\d+(?:\.\d+)?)", text, re.I)
    if targets and float(targets[1]) != float(targets[2]):
        return direction == ("long" if float(targets[2]) > float(targets[1]) else "short")
    pattern = _LONG if direction == "long" else _SHORT
    for match in pattern.finditer(text):
        if (not _NEGATED.search(text[max(0, match.start() - 30):match.start()])
                and not _FAILED_AFTER.search(text[match.end():match.end() + 40])):
            return True
    return _metric_bias(text) == direction


def unsided_option(text: str) -> bool:
    return bool(OPTION_RE.search(text) and _option_bias(text) is None)


def safe_image_evidence(evidence: object, ticker: str, direction: str) -> dict | None:
    if not isinstance(evidence, dict) or direction not in {"long", "short"}:
        return None
    if str(evidence.get("ticker", "")).lstrip("$").upper() != ticker.upper():
        return None
    setup_direction = evidence.get("setup_direction")
    sentiment = {"long": "bullish", "short": "bearish"}.get(setup_direction, evidence.get("sentiment"))
    if sentiment != {"long": "bullish", "short": "bearish"}[direction]:
        return None
    if evidence.get("direction_basis") not in {"annotated_setup", "price_action", "fundamental_event"}:
        return None
    try:
        confidence = float(evidence.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence) or not .65 <= confidence <= 1:
        return None
    url = evidence.get("image_url")
    details = evidence.get("direction_evidence")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    if not isinstance(details, str) or not details.strip():
        return None
    return {"ticker": ticker.upper(), "sentiment": sentiment,
            "setup_direction": direction, "overall_sentiment": evidence.get("overall_sentiment", evidence.get("sentiment")),
            "confidence": confidence, "direction_basis": evidence["direction_basis"],
            "direction_evidence": details.strip()[:1500], "image_url": url}
