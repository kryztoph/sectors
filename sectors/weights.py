"""Dated S&P 500 index allocations published by State Street (not SPY fund weights)."""
from __future__ import annotations

import json
import math
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen

SOURCE = "https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy"
NAMES = {"XLC": "Communication Services", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLE": "Energy", "XLF": "Financials", "XLV": "Health Care", "XLI": "Industrials", "XLB": "Materials", "XLRE": "Real Estate", "XLK": "Information Technology", "XLU": "Utilities"}


class _AllocationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.allocation: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("id") == "index-sector-breakdown":
            self.allocation = attrs.get("value")


def parse_sector_weights(document: str) -> dict[str, object]:
    parser = _AllocationParser()
    parser.feed(document)
    if parser.allocation is None:
        raise ValueError("State Street index-sector-breakdown missing")
    data = json.loads(parser.allocation)
    if not isinstance(data, dict) or not isinstance(data.get("attrArray"), list):
        raise ValueError("invalid index sector payload")
    as_of = datetime.strptime(data["asOfDateSimple"], "%b %d %Y").date().isoformat()
    allocations: dict[str, float] = {}
    for item in data["attrArray"]:
        if not isinstance(item, dict):
            raise ValueError("invalid sector allocation entry")
        name = item["name"]["value"]
        if name not in NAMES.values() or name in allocations:
            raise ValueError("unknown or duplicate sector allocation")
        allocations[name] = float(item["weight"]["originalValue"]) / 100
    weights = {symbol: allocations[name] for symbol, name in NAMES.items()}
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in weights.values()) or not 0.99 <= sum(weights.values()) <= 1.01:
        raise ValueError("invalid or incomplete index sector allocation")
    return {"status": "available", "as_of": as_of, "source": SOURCE, "basis": "S&P 500 index sector breakdown", "weights": weights}


def fetch_sector_weights() -> dict[str, object]:
    try:
        request = Request(SOURCE, headers={"User-Agent": "Mozilla/5.0 sectors-research"})
        with urlopen(request, timeout=20) as response:
            return parse_sector_weights(response.read().decode("utf-8"))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        return {"status": "unavailable", "source": SOURCE, "reason": str(exc)}
