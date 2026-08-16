from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from .analytics import build_snapshot
from .backfill import backfill_weekly_snapshots
from .charts import write_sector_charts
from .cotpy import write_cotpy_charts
from .config import init_project, load_references, load_universe, read_json, validate_universe, write_json
from .market_data import get_market_data_provider, provider_names
from .model import utc_timestamp
from .report import write_brief, write_brief_html
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
    references = load_references(ROOT)
    symbols = list(dict.fromkeys(reference.symbol for reference in references + sectors))
    provider = get_market_data_provider(args.provider)
    history = provider.fetch_history(symbols, period=args.period)
    snapshot = build_snapshot(benchmark, sectors, history, provider=provider.name, references=references)
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
    if output.suffix == ".md":
        html_output = output.with_suffix(".html")
        write_brief_html(html_output, snapshot)
        print(html_output)
        if args.output is None:
            latest_md = ROOT / "reports" / "latest-brief.md"
            latest_html = ROOT / "reports" / "latest-brief.html"
            write_brief(latest_md, snapshot)
            write_brief_html(latest_html, snapshot)
            print(latest_md)
            print(latest_html)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    snapshot = _latest_snapshot(ROOT)
    latest_report = sorted((ROOT / "reports").glob("*.md"))[-1:] if (ROOT / "reports").exists() else []
    tracker = ROOT / "reports" / "sector_rotation_tracker.html"
    charts = ROOT / "reports" / "sector_charts.html"
    status = {
        "root": str(ROOT),
        "latest_snapshot": str(snapshot) if snapshot else None,
        "latest_report": str(latest_report[0]) if latest_report else None,
        "tracker": str(tracker) if tracker.exists() else None,
        "charts": str(charts) if charts.exists() else None,
        "providers": provider_names(),
    }
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def cmd_tracker(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else None
    written = write_tracker(ROOT, output=output, trail_length=args.trail_length)
    print(written)
    if args.publish and output is None:
        return _publish_to_reports_repo()
    return 0


def cmd_charts(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    output = Path(args.output) if args.output else None
    chart_dir = Path(args.chart_dir) if args.chart_dir else None
    written = write_sector_charts(
        ROOT,
        snapshot_path=snapshot,
        output=output,
        chart_dir=chart_dir,
        lookback=args.lookback,
    )
    for path in written:
        print(path)
    return 0


def cmd_cotpy(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else None
    chart_dir = Path(args.chart_dir) if args.chart_dir else None
    written = write_cotpy_charts(
        ROOT,
        provider_name=args.provider,
        period=args.period,
        output=output,
        chart_dir=chart_dir,
        lookback=args.lookback,
    )
    for path in written:
        print(path)
    if args.publish and output is None:
        return _publish_to_reports_repo()
    return 0


def cmd_backfill_weekly(args: argparse.Namespace) -> int:
    written = backfill_weekly_snapshots(
        ROOT,
        weeks=args.weeks,
        provider_name=args.provider,
        period=args.period,
        overwrite=args.overwrite,
        refresh_tracker=not args.no_tracker,
    )
    for path in written:
        print(path)
    if not written:
        print("no new weekly snapshots written")
    if not args.no_tracker and args.publish:
        return _publish_to_reports_repo()
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
    tracker_parser.add_argument(
        "--publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publish the default tracker directly to the csfox GitHub repo after writing it",
    )
    tracker_parser.set_defaults(func=cmd_tracker)

    charts_parser = subparsers.add_parser("charts")
    charts_parser.add_argument("--snapshot", help="Snapshot JSON path; defaults to latest")
    charts_parser.add_argument("--output", help="Index HTML output path; defaults to reports/sector_charts.html")
    charts_parser.add_argument("--chart-dir", help="Per-sector chart directory; defaults to reports/charts")
    charts_parser.add_argument("--lookback", type=int, default=126, help="Number of recent bars to draw")
    charts_parser.set_defaults(func=cmd_charts)

    cotpy_parser = subparsers.add_parser("cotpy")
    cotpy_parser.add_argument("--provider", default="yfinance", choices=provider_names())
    cotpy_parser.add_argument("--period", default="2y")
    cotpy_parser.add_argument("--output", help="Index HTML output path; defaults to reports/cotpy/index.html")
    cotpy_parser.add_argument("--chart-dir", help="Commodity chart directory; defaults to reports/cotpy/charts")
    cotpy_parser.add_argument("--lookback", type=int, default=104, help="Number of weekly bars to draw")
    cotpy_parser.add_argument(
        "--publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publish the default cotpy report directly to the csfox GitHub repo after writing it",
    )
    cotpy_parser.set_defaults(func=cmd_cotpy)

    backfill_parser = subparsers.add_parser("backfill-weekly")
    backfill_parser.add_argument("--weeks", type=int, default=8, help="Number of prior complete weekly closes")
    backfill_parser.add_argument("--provider", default="yfinance", choices=provider_names())
    backfill_parser.add_argument("--period", default="1y")
    backfill_parser.add_argument("--overwrite", action="store_true", help="Replace existing backfill files")
    backfill_parser.add_argument("--no-tracker", action="store_true", help="Do not refresh tracker after writing snapshots")
    backfill_parser.add_argument(
        "--publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publish directly to the csfox GitHub repo after refreshing the tracker",
    )
    backfill_parser.set_defaults(func=cmd_backfill_weekly)
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


def _publish_to_reports_repo() -> int:
    publish_setting = os.environ.get("SECTORS_PUBLISH_REPORTS", os.environ.get("SECTORS_PUBLISH_CSFOX", "1"))
    if publish_setting != "1":
        print("sector reports publish skipped")
        return 0
    script = ROOT / "scripts" / "publish_to_reports_repo.sh"
    if not script.exists():
        print(f"ERROR: missing publish script: {script}")
        return 1
    completed = subprocess.run([str(script)], cwd=ROOT, check=False)
    return completed.returncode
