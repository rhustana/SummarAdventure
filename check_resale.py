#!/usr/bin/env python3
"""CLI: check the Oktoberfest resale site for new table listings on a given
date, and push an ntfy.sh notification for any listing not seen before.

Examples:
    python check_resale.py                          # normal run
    python check_resale.py --headed                 # watch it work
    python check_resale.py --dump                    # debug: save every
                                                       # price-bearing block
                                                       # found on the page,
                                                       # no notifications sent
    python check_resale.py --card-selector ".ticket-card"   # precise mode,
                                                              # once you know
                                                              # the real markup
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from resale_checker.browser import fetch_candidates
from resale_checker.extract import find_listings_for_date
from resale_checker.notify import send_ntfy
from resale_checker.state import load_seen, mark_seen, save_seen

DEFAULT_URL = "https://www.oktoberfest-booking.com/de#ticket-shop"
DEFAULT_TARGET_DATE = dt.date(2026, 9, 26)  # Saturday
DEFAULT_STATE_FILE = Path(__file__).parent / "state" / "resale_seen.json"
META_KEY = "_meta"
ERROR_RENOTIFY_AFTER = dt.timedelta(hours=12)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=DEFAULT_URL, help="Resale site URL to check")
    p.add_argument(
        "--date",
        type=lambda s: dt.date.fromisoformat(s),
        default=DEFAULT_TARGET_DATE,
        help=f"Target date, YYYY-MM-DD (default: {DEFAULT_TARGET_DATE.isoformat()})",
    )
    p.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    p.add_argument(
        "--topic",
        default=os.environ.get("NTFY_TOPIC"),
        help="ntfy.sh topic to notify (default: $NTFY_TOPIC env var)",
    )
    p.add_argument("--card-selector", default=None, help="CSS selector for listing cards, once known (see README)")
    p.add_argument("--timeout", type=int, default=30_000, help="Navigation timeout in ms")
    p.add_argument("--headed", action="store_true", help="Run with a visible browser window")
    p.add_argument(
        "--dump",
        action="store_true",
        help="Debug mode: save every price-bearing candidate block + a screenshot to debug/, "
        "send no notifications, and don't touch state",
    )
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    if not args.dump and not args.topic:
        print(
            "No ntfy topic set. Pass --topic or set the NTFY_TOPIC environment variable.",
            file=sys.stderr,
        )
        return 1

    screenshot_path = None
    if args.dump:
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)
        screenshot_path = str(debug_dir / "resale_page.png")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        try:
            result = await fetch_candidates(
                browser,
                args.url,
                card_selector=args.card_selector,
                screenshot_path=screenshot_path,
                timeout_ms=args.timeout,
            )
        finally:
            await browser.close()

    if args.dump:
        debug_dir = Path("debug")
        candidates_path = debug_dir / "candidates.json"
        candidates_path.write_text(
            json.dumps(result.candidates, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Found {len(result.candidates)} price-bearing block(s).")
        print(f"Candidates: {candidates_path}")
        if result.screenshot_path:
            print(f"Screenshot: {result.screenshot_path}")
        if result.error:
            print(f"Page load error: {result.error}", file=sys.stderr)
        return 0

    seen = load_seen(args.state_file)
    meta = seen.get(META_KEY, {})
    is_baseline_run = not any(k for k in seen if k != META_KEY)

    if result.error:
        print(f"Page load error: {result.error}", file=sys.stderr)
        last_notified = meta.get("last_error_notified_at")
        should_notify = True
        if last_notified:
            elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last_notified)
            should_notify = elapsed > ERROR_RENOTIFY_AFTER
        if should_notify:
            try:
                send_ntfy(
                    args.topic,
                    title="Oktoberfest resale checker: monitoring broken",
                    message=f"Couldn't load the resale site: {result.error}",
                    priority="high",
                    tags="warning",
                )
                meta["last_error_notified_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                seen[META_KEY] = meta
                save_seen(args.state_file, seen)
            except RuntimeError as e:
                print(str(e), file=sys.stderr)
        return 1

    listings = find_listings_for_date(result.candidates, args.date, result.page_url)
    new_listings = [l for l in listings if l.id not in seen]

    print(f"Checked {args.url} for {args.date.isoformat()}: {len(listings)} matching listing(s), {len(new_listings)} new.")

    if is_baseline_run and listings:
        print("First run (no prior state) -- recording existing listings as a baseline without notifying.")

    for listing in new_listings:
        if not is_baseline_run:
            snippet = listing.text[:200].replace("\n", " ")
            try:
                send_ntfy(
                    args.topic,
                    title=f"New Oktoberfest table listing for {args.date.strftime('%b %d, %Y')}",
                    message=snippet,
                    url=listing.url,
                    priority="high",
                    tags="beer,tada",
                )
                print(f"  notified: {snippet}")
            except RuntimeError as e:
                print(f"  FAILED to notify for listing {listing.id}: {e}", file=sys.stderr)
                continue  # don't mark as seen if we couldn't notify -- retry next run
        mark_seen(seen, listing.id, listing.text, listing.url)

    seen.pop(META_KEY, None)  # clear any prior error-throttle now that we're healthy

    save_seen(args.state_file, seen)
    return 0


def main() -> None:
    args = parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
