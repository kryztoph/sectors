"""Opt-in, evidence-backed long setup review. No broker or execution interface."""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "candidate-review-v1"
READY = "READY FOR REVIEW"
WATCH = "WATCH FOR TRIGGER"
REJECTED = "REJECTED"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a price")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("missing or invalid number") from exc
    if not result.is_finite() or result <= 0 or not math.isfinite(float(result)) or float(result) == 0:
        raise ValueError("numbers must be finite and positive")
    return result


def position_size(entry: Any, stop: Any, target: Any) -> dict[str, Any]:
    """Decimal arithmetic keeps the inclusive 3%, $60, $2000, 2R edges exact."""
    entry, stop, target = map(number, (entry, stop, target))
    risk = entry - stop
    if not stop < entry < target:
        raise ValueError("require 0 < stop < entry < target")
    if risk > entry * Decimal("0.03"):
        raise ValueError("stop exceeds 3% below entry")
    if target - entry < 2 * risk:
        raise ValueError("target is below 2R")
    shares = int(min(Decimal(2000) / entry, Decimal(60) / risk).to_integral_value(rounding=ROUND_FLOOR))
    if shares <= 0:
        raise ValueError("capital/risk budget cannot fund one whole share")
    return {"entry": str(entry), "stop": str(stop), "target": str(target), "shares": shares,
            "capital": str(shares * entry), "planned_loss": str(shares * risk),
            "reward_risk": str((target - entry) / risk), "stop_fraction": str(risk / entry)}


def timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps require a timezone")
    return parsed.astimezone(UTC)


def evidence(item: Any, symbol: str, time_key: str, now: datetime) -> None:
    if not isinstance(item, dict) or item.get("verified") is not True:
        raise ValueError("missing verified source evidence")
    if item.get("symbol") != symbol or not isinstance(item.get("source"), str) or not item["source"].strip():
        raise ValueError("source and matching symbol are required")
    age = now - timestamp(item.get(time_key))
    if age < timedelta(0) or age > timedelta(hours=24):
        raise ValueError(f"stale or future {time_key}; maximum evidence age is 24 hours")


def missing_session(start: date, end: date, closures: set[date]) -> bool:
    day = start + timedelta(days=1)
    while day < end:
        if day.weekday() < 5 and day not in closures:
            return True
        day += timedelta(days=1)
    return False


def validate_history(item: Any, symbol: str, now: datetime, minimum: int = 64) -> list[dict[str, Any]]:
    evidence(item, symbol, "retrieved_at", now)
    if item.get("price_basis") != "raw" or item.get("interval") != "1d" or item.get("currency") != "USD":
        raise ValueError("require raw, unadjusted USD daily OHLCV for comparable levels")
    rows = item.get("bars")
    if not isinstance(rows, list) or len(rows) < minimum:
        raise ValueError(f"at least {minimum} verified daily OHLCV bars required")
    declared_closures = item.get("non_trading_dates", [])
    if not isinstance(declared_closures, list):
        raise ValueError("non_trading_dates must be an explicit sourced list of exchange closures")
    closures = {date.fromisoformat(day) for day in declared_closures}
    previous = None
    for bar in rows:
        if not isinstance(bar, dict):
            raise ValueError("each OHLCV bar must be an object")
        day = date.fromisoformat(bar["date"])
        if day > now.date() or day > timestamp(item["retrieved_at"]).date() or day.weekday() > 4 or day in closures:
            raise ValueError("future or non-session daily bar")
        session_end = datetime.combine(day, time(16), ZoneInfo("America/New_York"))
        if session_end > min(now, timestamp(item["retrieved_at"])):
            raise ValueError("daily bar is not yet complete; require evidence after 4 PM ET")
        if previous is not None and (day <= previous or (day - previous).days > 7 or missing_session(previous, day, closures)):
            raise ValueError("history must have unique increasing dates without missing sessions or gaps over 7 calendar days")
        o, h, l, c, v = [number(bar.get(k)) for k in ("open", "high", "low", "close", "volume")]
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent OHLC range")
        if v != v.to_integral_value():
            raise ValueError("volume must be whole shares")
        previous = day
    if not 0 <= (now.date() - previous).days <= 4:
        raise ValueError("stale price history; latest daily bar exceeds 4 calendar days")
    local = now.astimezone(ZoneInfo("America/New_York"))
    expected = local.date() if local.time() >= time(16) else local.date() - timedelta(days=1)
    while expected.weekday() > 4 or expected in closures:
        expected -= timedelta(days=1)
    if previous != expected:
        raise ValueError("stale price history; latest completed session is missing")
    return rows


def indicators(rows: list[dict[str, Any]], entry: Decimal) -> dict[str, Any]:
    closes = [float(number(b["close"])) for b in rows]
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    gain, loss = mean(gains[:14]), mean(losses[:14])
    for g, l in zip(gains[14:], losses[14:]):
        gain, loss = (gain * 13 + g) / 14, (loss * 13 + l) / 14
    rsi = 50.0 if gain == loss == 0 else (100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    ranges = [max(float(number(b["high"])) - float(number(b["low"])),
                  abs(float(number(b["high"])) - closes[i - 1]),
                  abs(float(number(b["low"])) - closes[i - 1])) for i, b in enumerate(rows) if i]
    atr = mean(ranges[:14])
    for tr in ranges[14:]:
        atr = (atr * 13 + tr) / 14
    # Two bars on either side confirm a pivot; the latest unconfirmed bar is excluded.
    window = rows[-64:]
    lows, highs = [], []
    for i in range(2, len(window) - 2):
        group = window[i - 2:i + 3]
        low, high = number(window[i]["low"]), number(window[i]["high"])
        if low == min(number(b["low"]) for b in group) and low < entry:
            lows.append((low, window[i]["date"]))
        if high == max(number(b["high"]) for b in group) and high > entry:
            highs.append((high, window[i]["date"]))
    volumes = [float(number(b["volume"])) for b in rows[-20:]]
    return {"ma20": mean(closes[-20:]), "ma50": mean(closes[-50:]), "rsi14": rsi, "atr14": atr,
            "average_volume20": mean(volumes),
            "average_dollar_volume20": mean(float(number(b["close"])) * float(number(b["volume"])) for b in rows[-20:]),
            "relative_volume": volumes[-1] / mean(volumes),
            "support": str(max(lows)[0]) if lows else None, "support_date": max(lows)[1] if lows else None,
            "resistance": str(min(highs)[0]) if highs else None, "resistance_date": min(highs)[1] if highs else None}


def analyze_candidate(candidate: dict[str, Any], now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {"symbol": candidate.get("symbol"), "classification": REJECTED,
                              "setup_id": None, "reasons": [], "kind": "hypothetical", "algorithm": VERSION}
    try:
        symbol = candidate["symbol"]
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
            raise ValueError("invalid stock/ETF symbol")
        if candidate.get("asset_type") not in {"stock", "etf"} or candidate.get("side") != "long":
            raise ValueError("only explicitly identified long stocks and ETFs are eligible")
        thesis = date.fromisoformat(candidate["setup_date"])
        market_date = now.astimezone(ZoneInfo("America/New_York")).date()
        if thesis > market_date:
            raise ValueError("setup date is in the future")
        size = position_size(candidate.get("entry"), candidate.get("stop"), candidate.get("target"))
        result["position"] = size
        identity = {k: size[k] for k in ("entry", "stop", "target")}
        identity.update(symbol=symbol, setup_date=thesis.isoformat(), asset_type=candidate["asset_type"], algorithm=VERSION)
        # Normalize Decimal spelling so 100 and 100.0 identify the same setup.
        for key in ("entry", "stop", "target"):
            identity[key] = format(Decimal(identity[key]).normalize(), "f")
        result["setup_id"] = "setup-" + digest(identity)[:24]
        rows = validate_history(candidate.get("history"), symbol, now)
        quote, events = candidate.get("quote"), candidate.get("events")
        evidence(quote, symbol, "as_of", now)
        if quote.get("price_basis") != "raw" or quote.get("currency") != "USD":
            raise ValueError("require a raw USD quote")
        price = number(quote.get("price"))
        latest_close_time = datetime.combine(date.fromisoformat(rows[-1]["date"]), time(16), ZoneInfo("America/New_York"))
        if timestamp(quote["as_of"]) < latest_close_time:
            raise ValueError("quote predates the latest history bar")
        evidence(events, symbol, "checked_at", now)
        result["provenance"] = {"history": {k: v for k, v in candidate["history"].items() if k != "bars"},
                                "history_sha256": digest(rows), "quote": quote, "events": events,
                                "bar_count": len(rows), "last_bar": rows[-1]["date"]}
        if events.get("status") != "clear" or events.get("coverage_days", 0) < 7 or events.get("risks"):
            raise ValueError("event risk is unknown, present, or coverage is less than 7 days")
        next_event = events.get("next_event")
        if next_event and date.fromisoformat(next_event) <= market_date + timedelta(days=7):
            raise ValueError("event within the next 7 days or event review is outdated")
        entry, stop, target = map(Decimal, (size["entry"], size["stop"], size["target"]))
        tech = indicators(rows, entry)
        if any(isinstance(value, float) and not math.isfinite(value) for value in tech.values()):
            raise ValueError("nonfinite derived indicator; source values exceed numerical range")
        result["technicals"] = tech
        if tech["support"] is None or tech["resistance"] is None or tech["atr14"] <= 0:
            raise ValueError("confirmed chart support, resistance and positive ATR are required")
        atr = Decimal(str(tech["atr14"]))
        support, resistance = Decimal(tech["support"]), Decimal(tech["resistance"])
        if not support - atr / 2 <= stop < support or entry - stop < atr / 2:
            raise ValueError("stop must be below confirmed support within 0.5 ATR and at least 0.5 ATR from entry")
        if not resistance - atr / 2 <= target <= resistance:
            raise ValueError("target must be supported by nearest confirmed resistance (within 0.5 ATR below it)")
        if tech["average_volume20"] < 100_000 or tech["average_dollar_volume20"] < 1_000_000:
            raise ValueError("insufficient liquidity: require 100k average shares and $1m average daily dollar volume")
        reasons = []
        if not float(number(rows[-1]["close"])) >= tech["ma20"] > tech["ma50"]:
            reasons.append("price/MA20/MA50 trend not confirmed")
        if not 40 <= tech["rsi14"] <= 70:
            reasons.append("RSI14 outside 40–70 review range")
        if tech["relative_volume"] < 1:
            reasons.append("latest daily volume below its 20-day average")
        if not entry <= price <= entry * Decimal("1.005"):
            reasons.append("quote has not reached entry or exceeds the 0.5% review band; do not chase")
        result["classification"] = WATCH if reasons else READY
        result["reasons"] = reasons or ["all evidence, risk and technical gates passed; human review required"]
    except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation) as exc:
        result["reasons"] = [str(exc)]
    return result


def connect(root: Path, replay: bool = False) -> sqlite3.Connection:
    path = root / "state" / ("candidates-replay.sqlite3" if replay else "candidates.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS setups (id TEXT PRIMARY KEY, payload TEXT NOT NULL, activated_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS bars (setup_id TEXT, day TEXT, payload TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(setup_id, day))")
    db.execute("CREATE TABLE IF NOT EXISTS outcomes (id TEXT PRIMARY KEY, checked_at TEXT, payload TEXT NOT NULL)")
    return db


def hypothetical_outcome(setup: dict[str, Any], activated_at: str, bars: list[dict[str, Any]],
                         non_trading_dates: list[str] | None = None) -> dict[str, Any]:
    """Conservative daily-bar simulation; ambiguous ordering/gaps never earn R."""
    entry, stop, target = [Decimal(setup["position"][k]) for k in ("entry", "stop", "target")]
    result: dict[str, Any] = {"setup_id": setup["setup_id"], "kind": "hypothetical", "broker_fill": False,
                              "symbol": setup["symbol"], "activated_at": activated_at, "position": setup["position"],
                              "status": "AWAITING ENTRY", "entry_date": None, "exit_date": None, "r_multiple": None}
    activation_day = timestamp(activated_at).astimezone(ZoneInfo("America/New_York")).date()
    previous = activation_day
    closures = {date.fromisoformat(day) for day in non_trading_dates or []}
    for bar in bars:
        day = date.fromisoformat(bar["date"])
        if day <= activation_day:
            continue  # Never infer a fill before/within the review's daily bar.
        o, h, l = [number(bar[k]) for k in ("open", "high", "low")]
        if day in closures:
            raise ValueError("declared closure conflicts with previously recorded daily bar")
        if (day - previous).days > 7 or missing_session(previous, day, closures):
            result.update(status="UNRESOLVED", reason="missing daily bars; path cannot be reconstructed")
            return result
        previous = day
        if result["entry_date"] is None:
            if o > entry:
                result.update(status="UNRESOLVED", reason="gap above entry; hypothetical fill unknown")
                return result
            if not l <= entry <= h:
                continue
            result.update(entry_date=bar["date"], status="OPEN")
            if l <= stop or h >= target:
                result.update(status="UNRESOLVED", reason="entry and exit touched on same daily bar; order unknown")
                return result
            continue
        if l <= stop and h >= target:
            result.update(status="UNRESOLVED", reason="stop and target touched on same daily bar; order unknown")
            return result
        if o < stop or o > target:
            result.update(status="UNRESOLVED", reason="gap through exit; realized price unknown")
            return result
        if l <= stop or h >= target:
            hit_stop = l <= stop
            result.update(status="STOP" if hit_stop else "TARGET", exit_date=bar["date"],
                          r_multiple="-1" if hit_stop else str((target - entry) / (entry - stop)))
            return result
    return result


def _archive(root: Path, packet: dict[str, Any]) -> str:
    key = digest(packet)
    path = root / "state" / "snapshots" / "candidates" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(packet, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return key


def review_packet(root: Path, packet: dict[str, Any], now: datetime, *, replay: bool = False) -> dict[str, Any]:
    candidates = packet.get("candidates")
    if not isinstance(candidates, list) or not candidates or not all(isinstance(c, dict) for c in candidates):
        raise ValueError("input must contain a nonempty candidates array of sourced candidate objects")
    results = [analyze_candidate(c, now) for c in candidates]
    ids = [r["setup_id"] for r in results if r["setup_id"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate setup identities in input")
    key = _archive(root, packet)
    db = connect(root, replay)
    try:
        with db:
            for result in results:
                if result["classification"] == READY:
                    inserted = db.execute("INSERT OR IGNORE INTO setups VALUES (?, ?, ?)",
                                          (result["setup_id"], json.dumps(result, sort_keys=True), now.isoformat())).rowcount
                    if inserted:
                        initial = hypothetical_outcome(result, now.isoformat(), [])
                        initial.update(checked_at=now.isoformat(), input_sha256=key)
                        db.execute("INSERT INTO outcomes VALUES (?, ?, ?)",
                                   (result["setup_id"], now.isoformat(), json.dumps(initial, sort_keys=True)))
        outcomes = [json.loads(row[0]) for row in db.execute("SELECT payload FROM outcomes ORDER BY id")]
    finally:
        db.close()
    report = {"algorithm": VERSION, "as_of": now.isoformat(), "input_sha256": key,
              "evaluation_mode": "historical replay" if replay else "current review",
              "data_policy": "Source-verified attestations and validated OHLCV; no independent vendor authentication. Quotes may be delayed.",
              "risk_policy": "$2000 capital / $60 planned loss / 3% maximum stop / 2R minimum; long stocks/ETFs, whole shares. Gaps can exceed planned loss.",
              "candidates": results, "outcomes": outcomes,
              "outcome_policy": "Hypothetical scenarios only, never broker fills. Daily entry/exit ambiguity and gaps remain unresolved."}
    write_candidate_reports(root, report)
    return report


def update_outcomes(root: Path, packet: dict[str, Any], now: datetime, *, replay: bool = False) -> dict[str, Any]:
    histories = packet.get("histories")
    if not isinstance(histories, dict) or not histories:
        raise ValueError("outcome input requires a nonempty histories object keyed by symbol")
    validated = {symbol: validate_history(item, symbol, now, minimum=1) for symbol, item in histories.items()}
    key = _archive(root, packet)
    db = connect(root, replay)
    output = []
    try:
        with db:
            for setup_id, payload, activated in db.execute("SELECT id, payload, activated_at FROM setups ORDER BY id").fetchall():
                setup = json.loads(payload)
                symbol = setup["symbol"]
                if symbol not in validated:
                    continue
                old = db.execute("SELECT checked_at FROM outcomes WHERE id=?", (setup_id,)).fetchone()
                if old and timestamp(old[0]) > now:
                    raise ValueError("outcome update cannot move backward in time")
                activation_day = timestamp(activated).astimezone(ZoneInfo("America/New_York")).date().isoformat()
                source_evidence = {k: v for k, v in histories[symbol].items() if k != "bars"}
                source_evidence["input_sha256"] = key
                for bar in validated[symbol]:
                    if bar["date"] <= activation_day:
                        continue
                    encoded = json.dumps(bar, sort_keys=True)
                    existing = db.execute("SELECT payload FROM bars WHERE setup_id=? AND day=?", (setup_id, bar["date"])).fetchone()
                    if existing and existing[0] != encoded:
                        raise ValueError("historical bar correction conflicts with recorded evidence; manual review required")
                    db.execute("INSERT OR IGNORE INTO bars VALUES (?, ?, ?, ?)",
                               (setup_id, bar["date"], encoded, json.dumps(source_evidence, sort_keys=True)))
                rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM bars WHERE setup_id=? ORDER BY day", (setup_id,))]
                outcome = hypothetical_outcome(setup, activated, rows, histories[symbol].get("non_trading_dates", []))
                inputs = [json.loads(row[0]) for row in db.execute("SELECT DISTINCT evidence FROM bars WHERE setup_id=? ORDER BY evidence", (setup_id,))]
                outcome.update(input_sha256=key, checked_at=now.isoformat(), source=histories[symbol]["source"],
                               history_sha256=digest(rows), evidence_inputs=inputs)
                db.execute("INSERT OR REPLACE INTO outcomes VALUES (?, ?, ?)", (setup_id, now.isoformat(), json.dumps(outcome, sort_keys=True)))
                output.append(outcome)
    finally:
        db.close()
    report = {"algorithm": VERSION, "as_of": now.isoformat(), "input_sha256": key, "outcomes": output}
    # Preserve the latest reviews while refreshing their hypothetical outcomes.
    latest = root / "reports" / "candidates" / ("replay/latest.json" if replay else "latest.json")
    if latest.exists():
        current = json.loads(latest.read_text())
        db = connect(root, replay)
        try:
            current["outcomes"] = [json.loads(row[0]) for row in db.execute("SELECT payload FROM outcomes ORDER BY id")]
        finally:
            db.close()
        current["outcomes_as_of"] = now.isoformat()
        write_candidate_reports(root, current)
    return report


def write_candidate_reports(root: Path, report: dict[str, Any]) -> None:
    directory = root / "reports" / "candidates"
    if report["evaluation_mode"] == "historical replay":
        directory = directory / "replay"
    directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    lines = ["# Candidate review", "", f"As of: {report['as_of']} ({report['evaluation_mode']})", "", report["risk_policy"], "",
             report["data_policy"], "", report["outcome_policy"], "", f"Input SHA256: {report['input_sha256']}", ""]
    for result in report["candidates"]:
        symbol = html.escape(str(result["symbol"]))
        lines.extend([f"## {symbol}: {result['classification']}", ""])
        if "position" in result:
            p = result["position"]
            lines.extend([f"Entry ${p['entry']} · Stop ${p['stop']} · Target ${p['target']} · {p['shares']} shares · Planned loss ${p['planned_loss']}", ""])
        # Escape fence delimiters and HTML from untrusted source descriptions.
        detail = json.dumps(result, indent=2, sort_keys=True, allow_nan=False).replace("<", "\\u003c").replace("`", "\\u0060")
        lines.extend(["```json", detail, "```", ""])
    lines.extend(["## Hypothetical outcomes", "", "```json", json.dumps(report["outcomes"], indent=2, sort_keys=True), "```", ""])
    markdown = "\n".join(lines)
    rendered = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<title>Candidate review</title><body><main><h1>Candidate review</h1>'
                '<p><a href="latest.json">JSON evidence</a> · <a href="latest.md">Markdown</a></p>'
                f'<pre style="white-space:pre-wrap">{html.escape(markdown)}</pre></main></body></html>\n')
    # Fixed filenames keep repeated runs idempotent. Temporary files prevent partial individual reports.
    for name, content in (("latest.json", encoded), ("latest.md", markdown), ("latest.html", rendered)):
        temporary = directory / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(directory / name)
