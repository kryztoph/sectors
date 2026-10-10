from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Instrument


DEFAULT_UNIVERSE: dict[str, Any] = {
    "benchmark": {"symbol": "SPY", "name": "S&P 500 ETF"},
    "references": [
        {"symbol": "SPY", "name": "S&P 500 ETF"},
        {"symbol": "RSP", "name": "Invesco S&P 500 Equal Weight ETF"},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust"},
    ],
    "assets": [
        {"symbol": "CL=F", "name": "WTI crude oil (continuous futures)"},
        {"symbol": "ZN=F", "name": "10-year Treasury note (continuous futures price)"},
        {"symbol": "BTC-USD", "name": "Bitcoin (USD spot)"},
    ],
    "sectors": [
        {"symbol": "XLC", "name": "Communication Services"},
        {"symbol": "XLY", "name": "Consumer Discretionary"},
        {"symbol": "XLP", "name": "Consumer Staples"},
        {"symbol": "XLE", "name": "Energy"},
        {"symbol": "XLF", "name": "Financials"},
        {"symbol": "XLV", "name": "Health Care"},
        {"symbol": "XLI", "name": "Industrials"},
        {"symbol": "XLB", "name": "Materials"},
        {"symbol": "XLRE", "name": "Real Estate"},
        {"symbol": "XLK", "name": "Technology"},
        {"symbol": "XLU", "name": "Utilities"},
    ],
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def init_project(root: Path) -> list[Path]:
    created: list[Path] = []
    for directory in [
        root / "config",
        root / "state" / "raw",
        root / "state" / "snapshots",
        root / "reports",
    ]:
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)

    universe_path = root / "config" / "universe.json"
    if not universe_path.exists():
        write_json(universe_path, DEFAULT_UNIVERSE)
        created.append(universe_path)
    return created


def validate_universe(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    benchmark = data.get("benchmark")
    if not isinstance(benchmark, dict):
        errors.append("benchmark must be an object")
    else:
        errors.extend(_validate_instrument(benchmark, "benchmark"))

    sectors = data.get("sectors")
    if not isinstance(sectors, list):
        errors.append("sectors must be a list")
    elif len(sectors) != 11:
        errors.append("sectors must contain exactly 11 entries")
    else:
        seen: set[str] = set()
        for index, sector in enumerate(sectors):
            if not isinstance(sector, dict):
                errors.append(f"sectors[{index}] must be an object")
                continue
            errors.extend(_validate_instrument(sector, f"sectors[{index}]"))
            symbol = sector.get("symbol")
            if isinstance(symbol, str):
                if symbol in seen:
                    errors.append(f"duplicate sector symbol: {symbol}")
                seen.add(symbol)

    references = data.get("references")
    if not isinstance(references, list):
        errors.append("references must be a list")
    else:
        seen: set[str] = set()
        for index, reference in enumerate(references):
            if not isinstance(reference, dict):
                errors.append(f"references[{index}] must be an object")
                continue
            errors.extend(_validate_instrument(reference, f"references[{index}]"))
            symbol = reference.get("symbol")
            if isinstance(symbol, str):
                if symbol in seen:
                    errors.append(f"duplicate reference symbol: {symbol}")
                seen.add(symbol)
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        errors.append("assets must be a list")
    else:
        seen_assets: set[str] = set()
        reserved = {
            item.get("symbol")
            for group in (sectors, references)
            if isinstance(group, list)
            for item in group
            if isinstance(item, dict) and isinstance(item.get("symbol"), str)
        }
        if isinstance(benchmark, dict) and isinstance(benchmark.get("symbol"), str):
            reserved.add(benchmark["symbol"])
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                errors.append(f"assets[{index}] must be an object")
                continue
            errors.extend(_validate_instrument(asset, f"assets[{index}]"))
            symbol = asset.get("symbol")
            if isinstance(symbol, str) and (symbol in seen_assets or symbol in reserved):
                errors.append(f"duplicate or reserved asset symbol: {symbol}")
            if isinstance(symbol, str):
                seen_assets.add(symbol)
    return errors


def load_universe(root: Path) -> tuple[Instrument, list[Instrument]]:
    data = read_json(root / "config" / "universe.json")
    errors = validate_universe(data)
    if errors:
        raise ValueError("; ".join(errors))
    benchmark = Instrument(
        symbol=data["benchmark"]["symbol"],
        name=data["benchmark"]["name"],
    )
    sectors = [
        Instrument(symbol=item["symbol"], name=item["name"])
        for item in data["sectors"]
    ]
    return benchmark, sectors


def load_assets(root: Path) -> list[Instrument]:
    data = read_json(root / "config" / "universe.json")
    errors = validate_universe(data)
    if errors:
        raise ValueError("; ".join(errors))
    return [Instrument(symbol=item["symbol"], name=item["name"]) for item in data.get("assets", [])]


def load_references(root: Path) -> list[Instrument]:
    data = read_json(root / "config" / "universe.json")
    errors = validate_universe(data)
    if errors:
        raise ValueError("; ".join(errors))
    return [
        Instrument(symbol=item["symbol"], name=item["name"])
        for item in data["references"]
    ]


def _validate_instrument(item: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    symbol = item.get("symbol")
    name = item.get("name")
    if not isinstance(symbol, str) or not symbol or symbol.upper() != symbol:
        errors.append(f"{label}.symbol must be a non-empty uppercase string")
    if not isinstance(name, str) or not name:
        errors.append(f"{label}.name must be a non-empty string")
    return errors
