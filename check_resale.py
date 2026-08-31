#!/usr/bin/env python3
"""CLI: check the Oktoberfest resale site for new table listings on a given
date, and notify about any listing not seen before.

Three notification channels (--notify-via):
  file    (default) -- appends each new listing to a JSON queue file
                        (--queue-file, default state/pending_notifications.json)
                        instead of sending anything itself. Used by the
                        GitHub Actions workflow, which has real internet
                        access to this site but can't push to a phone; a
                        separate Claude Code Remote Routine (which can push,
                        but can't reach this site -- see README) reads and
                        clears that queue on its own schedule.
  stdout  -- prints one "NOTIFY_JSON: {...}" line per new listing instead.
             Handy for interactive/manual runs.
  ntfy    -- posts directly to an ntfy.sh topic (--topic / $NTFY_TOPIC).
             The original flow before switching to Claude-app push; kept as
             a fallback.

Examples:
    python check_resale.py                          # normal run (stdout)
    python check_resale.py --headed                 # watch it work
    python check_resale.py --notify-via ntfy --topic my-topic
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
DEFAULT_QUEUE_FILE = Path(__file__).parent / "state" / "pending_notifications.json"
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
        "--notify-via",
        choices=["file", "stdout", "ntfy"],
        default="file",
        help="file: queue new listings in --queue-file for a Claude Routine to relay + clear (default). "
        "stdout: print NOTIFY_JSON lines instead. ntfy: post directly to an ntfy.sh topic.",
    )
    p.add_argument("--queue-file", type=Path, default=DEFAULT_QUEUE_FILE, help="JSON queue file for --notify-via file")
    p.add_argument(
        "--topic",
        default=os.environ.get("NTFY_TOPIC"),
        help="ntfy.sh topic to notify, only used with --notify-via ntfy (default: $NTFY_TOPIC env var)",
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


def _append_to_queue(queue_file: Path, entry: dict) -> None:
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    if queue_file.exists():
        queue = json.loads(queue_file.read_text(encoding="utf-8"))
    else:
        queue = []
    queue.append(entry)
    queue_file.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_notifier(args: argparse.Namespace):
    """Returns notify(*, title, message, url=None, priority="default", tags=None).

    Raises RuntimeError on failure to send (file/stdout modes never fail).
    """
    if args.notify_via == "ntfy":
        def notifier(*, title: str, message: str, url: str | None = None, priority: str = "default", tags: str | None = None):
            send_ntfy(args.topic, title=title, message=message, url=url, priority=priority, tags=tags)
        return notifier

    if args.notify_via == "file":
        def notifier(*, title: str, message: str, url: str | None = None, priority: str = "default", tags: str | None = None):
            _append_to_queue(
                args.queue_file,
                {
                    "title": title,
                    "message": message,
                    "url": url,
                    "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
        return notifier

    def notifier(*, title: str, message: str, url: str | None = None, priority: str = "default", tags: str | None = None):
        print("NOTIFY_JSON: " + json.dumps({"title": title, "message": message, "url": url}, ensure_ascii=False))

    return notifier


async def run(args: argparse.Namespace) -> int:
    if not args.dump and args.notify_via == "ntfy" and not args.topic:
        print(
            "No ntfy topic set. Pass --topic or set the NTFY_TOPIC environment variable.",
            file=sys.stderr,
        )
        return 1

    notify = make_notifier(args)

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
                capture_diagnostics=args.dump,
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

        if result.page_text is not None:
            print(f"Full body text length: {len(result.page_text)}")
            euro_positions = [i for i, ch in enumerate(result.page_text) if ch == "€"]
            print(f"'€' occurrences on page: {len(euro_positions)}")
            for i in euro_positions[:20]:
                snippet = result.page_text[max(0, i - 60): i + 20].replace("\n", " | ")
                print(f"  euro context: {snippet!r}")
        if result.button_labels:
            print(f"Button labels (first {len(result.button_labels)}): {result.button_labels}")
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
                notify(
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
                notify(
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
