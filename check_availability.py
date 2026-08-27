#!/usr/bin/env python3
"""CLI: check Oktoberfest tent websites for table-reservation availability
on a given date and produce a consolidated HTML report.

Examples:
    python check_availability.py
    python check_availability.py --date 2026-09-26
    python check_availability.py --only hofbraeu-festzelt,schottenhamel --headed
    python check_availability.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import webbrowser
from pathlib import Path

from playwright.async_api import async_playwright

from oktoberfest_checker.checker import check_all
from oktoberfest_checker.config import load_tents

DEFAULT_TARGET_DATE = dt.date(2026, 9, 26)  # Saturday
DEFAULT_TENTS_FILE = Path(__file__).parent / "config" / "tents.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--date",
        type=lambda s: dt.date.fromisoformat(s),
        default=DEFAULT_TARGET_DATE,
        help=f"Target date, YYYY-MM-DD (default: {DEFAULT_TARGET_DATE.isoformat()})",
    )
    p.add_argument("--tents-file", type=Path, default=DEFAULT_TENTS_FILE, help="Path to tents JSON config")
    p.add_argument("--only", type=str, default=None, help="Comma-separated tent ids to check (for iterating on a few at a time)")
    p.add_argument("--list", action="store_true", help="List configured tent ids and exit")
    p.add_argument("--output-dir", type=Path, default=None, help="Where to write the report + screenshots (default: reports/<timestamp>/)")
    p.add_argument("--concurrency", type=int, default=4, help="Max tents to check in parallel (default: 4)")
    p.add_argument("--timeout", type=int, default=30_000, help="Per-page navigation timeout in ms (default: 30000)")
    p.add_argument("--retries", type=int, default=1, help="Retries per tent on navigation failure (default: 1)")
    p.add_argument("--headed", action="store_true", help="Run with a visible browser window instead of headless")
    p.add_argument("--no-open", action="store_true", help="Don't auto-open the report in a browser when done")
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    tents = load_tents(args.tents_file, only=args.only.split(",") if args.only else None)

    if args.list:
        for t in tents:
            print(f"{t.id}\t{t.name}\t{t.url}")
        return 0

    if not tents:
        print("No tents to check.", file=sys.stderr)
        return 1

    output_dir = args.output_dir or Path("reports") / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot_dir = output_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    print(f"Checking {len(tents)} tent(s) for {args.date.strftime('%A, %B %d, %Y')}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        try:
            results = await check_all(
                browser,
                tents,
                args.date,
                screenshot_dir=screenshot_dir,
                concurrency=args.concurrency,
                timeout_ms=args.timeout,
                retries=args.retries,
            )
        finally:
            await browser.close()

    # Import here to avoid pulling report.py's deps into --list-only usage.
    from oktoberfest_checker.report import render_report

    report_path = output_dir / "report.html"
    render_report(results, args.date, report_path)

    for r in results:
        print(f"  [{r.status.value:>12}] {r.tent.name}" + (f" -- {r.evidence}" if r.evidence else ""))

    print(f"\nReport written to {report_path}")
    if not args.no_open:
        webbrowser.open(report_path.resolve().as_uri())

    return 0


def main() -> None:
    args = parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
