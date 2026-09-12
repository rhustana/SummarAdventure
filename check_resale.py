#!/usr/bin/env python3
"""Watch the Oktoberfest resale shop for new table offers on a target date.

Reads the shop, parses every offer, keeps the ones matching the target date,
and pushes a notification for any offer it has not already reported. It never
books, reserves, or pays for anything -- it only reads the page and messages
you.

Default target date: Saturday, 26 September 2026.

    python check_resale.py --date 2026-09-26 --notify-via ntfy --topic <topic>
    python check_resale.py --notify-via stdout        # dry run, no push
    python check_resale.py --self-test                # parser regression test
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from collections import Counter
from pathlib import Path

from resale_checker.notify import send_ntfy
from resale_checker.parse import offer_to_dict, offers_for_date, parse_offers
from resale_checker.state import load_seen, mark_seen, save_seen

DEFAULT_URL = "https://www.oktoberfest-booking.com/de#ticket-shop"
DEFAULT_TARGET_DATE = dt.date(2026, 9, 26)
DEFAULT_STATE_FILE = Path(__file__).parent / "state" / "resale_seen.json"
FIXTURE = Path(__file__).parent / "tests" / "fixture_shop.txt"

META_KEY = "_meta"
ERROR_RENOTIFY_AFTER = dt.timedelta(hours=12)

# If the page loads fine but yields no offers for ANY date, the site changed
# shape and this watcher has gone blind. That is the failure mode that made
# the previous version look healthy for weeks while recording nothing usable,
# so it gets an alarm of its own.
BLIND_THRESHOLD = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument(
        "--date",
        type=lambda s: dt.date.fromisoformat(s),
        default=DEFAULT_TARGET_DATE,
        help=f"Target date, YYYY-MM-DD (default {DEFAULT_TARGET_DATE.isoformat()})",
    )
    p.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    p.add_argument(
        "--notify-via",
        choices=["ntfy", "stdout"],
        default="ntfy",
        help="ntfy: push to an ntfy.sh topic. stdout: print instead (dry run).",
    )
    p.add_argument("--topic", default=os.environ.get("NTFY_TOPIC"), help="ntfy.sh topic (or $NTFY_TOPIC)")
    p.add_argument("--timeout", type=int, default=45_000)
    p.add_argument("--headed", action="store_true")
    p.add_argument("--screenshot", default=None, help="Save a full-page screenshot here")
    p.add_argument(
        "--show-all",
        action="store_true",
        help="Also print every offer found for every date (useful when checking it works)",
    )
    p.add_argument("--self-test", action="store_true", help="Run the parser against the committed fixture and exit")
    return p.parse_args()


def self_test() -> int:
    if not FIXTURE.exists():
        print(f"fixture missing: {FIXTURE}", file=sys.stderr)
        return 1
    offers = parse_offers(FIXTURE.read_text(encoding="utf-8"))
    print(f"parsed {len(offers)} offers from fixture")
    for o in offers:
        print(f"  {o.date}  {o.summary()}")

    failures = []
    if len(offers) != 8:
        failures.append(f"expected 8 offers, got {len(offers)}")

    first = offers[0] if offers else None
    if not first or first.tent != "Fischer Vroni Festzelt":
        failures.append(f"first tent wrong: {first.tent if first else None}")
    if not first or first.total != "531,90":
        # Guards the subtle bit: the total must come from Summe, not from the
        # "20 x Bier ... € 300,00" line item above it.
        failures.append(f"first total wrong: {first.total if first else None} (want 531,90)")
    if not first or first.persons != 10 or first.tables != 1:
        failures.append("first persons/tables wrong")
    if not first or first.time != "11:00-16:00":
        failures.append(f"first time wrong: {first.time if first else None}")

    if any(o.tent in {"Infos zum Zelt", "Details anzeigen"} for o in offers):
        failures.append("decoration text leaked into a tent name")

    ids = [o.id for o in offers]
    if len(set(ids)) != len(ids):
        failures.append("ids collided across distinct offers")

    if failures:
        print("\nSELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\nself-test OK")
    return 0


def make_notifier(args: argparse.Namespace):
    if args.notify_via == "ntfy":
        def notifier(*, title, message, url=None, priority="default", tags=None):
            send_ntfy(args.topic, title=title, message=message, url=url, priority=priority, tags=tags)
        return notifier

    def notifier(*, title, message, url=None, priority="default", tags=None):
        print("NOTIFY: " + json.dumps(
            {"title": title, "message": message, "url": url}, ensure_ascii=False))
    return notifier


def _maybe_alarm(notify, seen: dict, state_file: Path, *, title: str, message: str) -> None:
    """Send a health alarm at most once per ERROR_RENOTIFY_AFTER."""
    meta = seen.get(META_KEY, {})
    last = meta.get("last_error_notified_at")
    if last:
        elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)
        if elapsed <= ERROR_RENOTIFY_AFTER:
            return
    try:
        notify(title=title, message=message, priority="high", tags="warning")
        meta["last_error_notified_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        seen[META_KEY] = meta
        save_seen(state_file, seen)
    except RuntimeError as e:
        print(f"failed to send health alarm: {e}", file=sys.stderr)


async def run(args: argparse.Namespace) -> int:
    if args.notify_via == "ntfy" and not args.topic:
        print("No ntfy topic set: pass --topic or set NTFY_TOPIC.", file=sys.stderr)
        return 1

    notify = make_notifier(args)
    seen = load_seen(args.state_file)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not args.headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            from resale_checker.browser import fetch_body_text
            result = await fetch_body_text(
                browser, args.url, timeout_ms=args.timeout, screenshot_path=args.screenshot
            )
        finally:
            await browser.close()

    if result.error:
        print(f"Page load error: {result.error}", file=sys.stderr)
        _maybe_alarm(
            notify, seen, args.state_file,
            title="Oktoberfest watcher: can't read the site",
            message=f"{result.error} -- the watcher is blind until this is fixed.",
        )
        return 1

    all_offers = parse_offers(result.body_text)
    matching = offers_for_date(all_offers, args.date)

    by_date = Counter(o.date for o in all_offers)
    print(f"Checked {result.page_url}")
    print(f"  offers on page (all dates): {len(all_offers)}")
    print(f"  dates present: {dict(sorted(by_date.items()))}")
    print(f"  offers for {args.date.isoformat()}: {len(matching)}")

    if args.show_all:
        print("\n  --- every offer on the page ---")
        for o in sorted(all_offers, key=lambda x: (x.date, x.tent)):
            print(f"    {o.date}  {o.summary()}")

    # Blind-watcher guard: page rendered, but nothing parsed at all.
    if len(all_offers) <= BLIND_THRESHOLD:
        print("No offers parsed for ANY date -- the page shape probably changed.", file=sys.stderr)
        _maybe_alarm(
            notify, seen, args.state_file,
            title="Oktoberfest watcher: parsing broke",
            message="The site loaded but no offers could be parsed. The layout likely changed; "
                    "the watcher can't see new tables until it's updated.",
        )
        return 1

    is_baseline = not any(k for k in seen if k != META_KEY)
    new_offers = [o for o in matching if o.id not in seen]

    if is_baseline:
        # First healthy run: record what's already listed so the very first
        # check doesn't fire an alert for offers that were there all along.
        if matching:
            print(f"  baseline run: recording {len(matching)} existing offer(s) without notifying")
        for o in matching:
            mark_seen(seen, o.id, o.summary(), result.page_url)
    else:
        print(f"  new since last check: {len(new_offers)}")
        for o in new_offers:
            try:
                notify(
                    title=f"🍻 Table for {args.date.strftime('%a %d %b %Y')}: {o.tent}",
                    message=f"{o.summary()}\n\nBook fast — resale tables go quickly.",
                    url=result.page_url,
                    priority="urgent",
                    tags="beer,tada",
                )
                print(f"    NOTIFIED: {o.summary()}")
            except RuntimeError as e:
                # Don't mark as seen -- retry on the next run rather than
                # silently swallowing the one alert that mattered.
                print(f"    FAILED to notify ({e}); will retry next run", file=sys.stderr)
                continue
            mark_seen(seen, o.id, o.summary(), result.page_url)

    # Drop offers that are no longer listed, so a table that disappears and
    # relists later alerts again.
    live_ids = {o.id for o in matching}
    for stale in [k for k in seen if k != META_KEY and k not in live_ids]:
        del seen[stale]

    seen.pop(META_KEY, None)  # healthy run clears any error throttle
    save_seen(args.state_file, seen)
    return 0


def main() -> None:
    args = parse_args()
    if args.self_test:
        sys.exit(self_test())
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
