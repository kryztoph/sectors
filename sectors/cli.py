from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analytics import build_snapshot
from .config import init_project, load_universe, read_json, validate_universe, write_json
from .market_data import get_market_data_provider, provider_names
from .model import utc_timestamp
from .report import write_brief
from .tracker import write_tracker


ROOT = Path.cwd()


def cmd_init(args: argparse.Namespace) -> int:
    created = init_project(ROOT)
    for path in created:
        print(path)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    universe_path = ROOT / "config" / "universe.json"
    if not universe_path.exists():
        print("ERROR: missing config/universe.json; run init")
        return 1
    errors = validate_universe(read_json(universe_path))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("validation ok")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    benchmark, sectors = load_universe(ROOT)
    symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
    provider = get_market_data_provider(args.provider)
    history = provider.fetch_history(symbols, period=args.period)
    snapshot = build_snapshot(benchmark, sectors, history, provider=provider.name)
    output = Path(args.output) if args.output else ROOT / "state" / "snapshots" / f"{snapshot['created_at']}.json"
    write_json(output, snapshot)
    if args.promote_latest:
        write_json(ROOT / "state" / "snapshots" / "latest.json", snapshot)
    print(output)
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    snapshot_path = Path(args.snapshot) if args.snapshot else _latest_snapshot(ROOT)
    if snapshot_path is None:
        print("ERROR: no snapshot found; run snapshot first")
        return 1
    snapshot = read_json(snapshot_path)
    output = Path(args.output) if args.output else ROOT / "reports" / f"{utc_timestamp()}-brief.md"
    write_brief(output, snapshot)
    print(output)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    snapshot = _latest_snapshot(ROOT)
    latest_report = sorted((ROOT / "reports").glob("*.md"))[-1:] if (ROOT / "reports").exists() else []
    tracker = ROOT / "reports" / "sector_rotation_tracker.html"
    status = {
        "root": str(ROOT),
        "latest_snapshot": str(snapshot) if snapshot else None,
        "latest_report": str(latest_report[0]) if latest_report else None,
        "tracker": str(tracker) if tracker.exists() else None,
        "providers": provider_names(),
    }
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def cmd_tracker(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else None
    written = write_tracker(ROOT, output=output, trail_length=args.trail_length)
    print(written)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sectors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(func=cmd_init)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.set_defaults(func=cmd_validate)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--provider", default="yfinance", choices=provider_names())
    snapshot_parser.add_argument("--period", default="1y")
    snapshot_parser.add_argument("--output", help="Snapshot output path")
    snapshot_parser.add_argument(
        "--promote-latest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Update state/snapshots/latest.json",
    )
    snapshot_parser.set_defaults(func=cmd_snapshot)

    brief_parser = subparsers.add_parser("brief")
    brief_parser.add_argument("--snapshot", help="Snapshot JSON path; defaults to latest")
    brief_parser.add_argument("--output", help="Markdown report output path")
    brief_parser.set_defaults(func=cmd_brief)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=cmd_status)

    tracker_parser = subparsers.add_parser("tracker")
    tracker_parser.add_argument("--output", help="HTML output path; defaults to reports/sector_rotation_tracker.html")
    tracker_parser.add_argument("--trail-length", type=int, default=12, help="Number of recent snapshots to draw as trails")
    tracker_parser.set_defaults(func=cmd_tracker)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _latest_snapshot(root: Path) -> Path | None:
    latest = root / "state" / "snapshots" / "latest.json"
    if latest.exists():
        return latest
    snapshots = sorted(path for path in (root / "state" / "snapshots").glob("*.json") if path.name != "latest.json")
    return snapshots[-1] if snapshots else None
