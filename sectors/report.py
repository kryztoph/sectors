from __future__ import annotations

from pathlib import Path
from typing import Any


def build_brief(snapshot: dict[str, Any]) -> str:
    metrics = list(snapshot.get("metrics", []))
    leaders = metrics[:3]
    laggards = metrics[-3:]
    lines = [
        "# Sector Rotation Brief",
        "",
        f"Created: {snapshot.get('created_at', 'unknown')}",
        f"As of: {snapshot.get('as_of', 'unknown')}",
        f"Provider: {snapshot.get('provider', 'unknown')}",
        "",
        "## Summary",
        "",
    ]
    if leaders:
        lines.append("- Leaders: " + ", ".join(_label(row) for row in leaders))
    if laggards:
        lines.append("- Laggards: " + ", ".join(_label(row) for row in laggards))
    lines.extend(["", "## Rankings", ""])
    lines.append("| Rank | Sector | Symbol | Signal | Score | Rel 5d | Rel 21d | Rel 63d | Trend |")
    lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
    for row in metrics:
        rel = row.get("relative_returns") or {}
        lines.append(
            "| {rank} | {name} | {symbol} | {signal} | {score:.2f} | {rel5} | {rel21} | {rel63} | {trend} |".format(
                rank=row.get("rank", ""),
                name=row.get("name", ""),
                symbol=row.get("symbol", ""),
                signal=row.get("signal", ""),
                score=float(row.get("score") or 0.0),
                rel5=_pct(rel.get("5d")),
                rel21=_pct(rel.get("21d")),
                rel63=_pct(rel.get("63d")),
                trend=row.get("trend", ""),
            )
        )
    lines.extend(["", "## Notes", ""])
    lines.append("- Relative returns are sector ETF returns minus SPY returns over the same window.")
    lines.append("- Scores are cross-sectional ranks; they are useful for rotation monitoring, not trade execution.")
    return "\n".join(lines) + "\n"


def write_brief(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_brief(snapshot), encoding="utf-8")


def _label(row: dict[str, Any]) -> str:
    return f"{row.get('symbol', '')} {row.get('signal', '')}".strip()


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"
