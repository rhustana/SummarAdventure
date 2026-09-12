#!/usr/bin/env python3
"""One-off reconnaissance of the resale site's real markup.

Why this exists: the listing extractor in `resale_checker/extract.py` was
written blind (no environment that could author it could also reach the
site) and calibrated only indirectly. It anchors on *prices* and climbs to
an ancestor with a link -- which on this site lands on per-tent header
cards ("Infos zum Zelt / Hacker Festzelt", href
`/de/<tent>-tischreservierung`) rather than on a bookable offer for a
specific date. `state/resale_seen.json` shows exactly that failure.

This script anchors on the *target date* instead, which is the right
anchor for a date-specific watch, and dumps enough real structure to write
a precise extractor:

  1. Whether a consent/cookie gate or bot-block is being served (the
     "321-char body" failure seen in earlier runs was never diagnosed).
  2. The full rendered body text, so the shop's actual content is visible.
  3. Every element whose *own* text contains a target-date variant, with
     its ancestor chain and the outerHTML of a plausible card container.
  4. Repeated class signatures -- the strongest hint at a real card
     container selector.

Everything goes to stdout so it can be read back out of the GitHub Actions
job log. Read-only: it never books, submits, or writes state.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys

from playwright.async_api import async_playwright

DEFAULT_URL = "https://www.oktoberfest-booking.com/de#ticket-shop"
DEFAULT_TARGET_DATE = dt.date(2026, 9, 26)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Text on the buttons German cookie-consent management platforms use.
CONSENT_LABELS = [
    "Alle akzeptieren",
    "Alle Cookies akzeptieren",
    "Akzeptieren",
    "Alle zulassen",
    "Zustimmen",
    "Einverstanden",
    "Ich stimme zu",
    "Verstanden",
    "OK",
    "Accept all",
    "Accept",
]

# A body this short means we got a gate/placeholder, not the shop.
MIN_PLAUSIBLE_BODY = 2000


def date_variants(d: dt.date) -> list[str]:
    de_months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    return [
        d.strftime("%d.%m.%Y"),          # 26.09.2026
        d.strftime("%d.%m.%y"),          # 26.09.26
        f"{d.day}.{d.month}.{d.year}",   # 26.9.2026
        f"{d.day}. {de_months[d.month - 1]}",   # 26. September
        f"{d.day:02d}.{d.month:02d}.",   # 26.09.
        d.strftime("%Y-%m-%d"),          # 2026-09-26
    ]


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n=== {title}\n{'=' * 78}", flush=True)


async def dismiss_consent(page) -> str | None:
    """Best-effort click through a cookie/consent gate. Returns what it clicked."""
    for label in CONSENT_LABELS:
        for frame in page.frames:
            try:
                btn = frame.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    return f"{label} (frame: {frame.url[:80]})"
            except Exception:
                continue
    return None


# Dumps, for each element whose OWN text nodes contain a date variant, the
# ancestor chain and the outerHTML of the nearest ancestor that looks like a
# self-contained card (has a price AND an action). Anchoring on the date is
# the whole point -- a date-specific watch should start from the date.
_DATE_ANCHORED_JS = r"""
(variants) => {
  const hasVariant = (s) => variants.some(v => s.includes(v));
  const priceRe = /€|EUR/;

  const ownText = (el) => Array.from(el.childNodes)
    .filter(n => n.nodeType === 3)
    .map(n => n.textContent)
    .join('')
    .trim();

  const describe = (el) => ({
    tag: el.tagName,
    cls: (el.className || '').toString().slice(0, 200),
    id: el.id || null,
    // Livewire/Alpine components announce themselves with these.
    wire: el.getAttribute ? (el.getAttribute('wire:id') || el.getAttribute('wire:key') || null) : null,
    textLen: (el.textContent || '').trim().length,
  });

  const out = [];
  const all = Array.from(document.querySelectorAll('body *'));

  for (const el of all) {
    const own = ownText(el);
    if (!own || !hasVariant(own)) continue;

    const chain = [];
    let node = el;
    for (let i = 0; i < 12 && node && node !== document.body; i++) {
      chain.push(describe(node));
      node = node.parentElement;
    }

    // Climb to the smallest ancestor that carries both a price and an
    // action -- i.e. something that plausibly IS one bookable offer.
    let card = el;
    let cardDepth = -1;
    for (let i = 0; i < 12 && card && card !== document.body; i++) {
      const t = card.textContent || '';
      const acts = card.querySelectorAll('a[href], button');
      if (priceRe.test(t) && acts.length > 0 && t.trim().length > 40) {
        cardDepth = i;
        break;
      }
      card = card.parentElement;
    }

    out.push({
      anchorOwnText: own.slice(0, 300),
      anchor: describe(el),
      chain,
      cardDepth,
      cardDesc: cardDepth >= 0 ? describe(card) : null,
      cardText: cardDepth >= 0 ? (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 600) : null,
      cardHtml: cardDepth >= 0 ? card.outerHTML.slice(0, 2500) : null,
      cardHref: cardDepth >= 0 ? (card.tagName === 'A' ? card.href : (card.querySelector('a[href]')?.href || null)) : null,
    });

    if (out.length >= 25) break;
  }
  return out;
}
"""

# Class signatures that repeat many times are almost always the list-item
# container of a rendered collection -- the card selector we actually want.
_REPEATED_CLASS_JS = r"""
() => {
  const counts = {};
  for (const el of document.querySelectorAll('body *')) {
    const cls = (el.className || '').toString().trim();
    if (!cls || cls.length > 160) continue;
    counts[cls] = (counts[cls] || 0) + 1;
  }
  return Object.entries(counts)
    .filter(([, n]) => n >= 3)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 40)
    .map(([cls, n]) => ({ cls, n }));
}
"""


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--date", type=lambda s: dt.date.fromisoformat(s), default=DEFAULT_TARGET_DATE)
    ap.add_argument("--body-chars", type=int, default=18000, help="How much rendered body text to print")
    ap.add_argument("--timeout", type=int, default=45_000)
    args = ap.parse_args()

    variants = date_variants(args.date)
    print(f"Target date: {args.date.isoformat()}")
    print(f"Date variants searched: {variants}")
    print(f"URL: {args.url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1200},
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )
        # Cheap but effective against naive headless detection.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()

        body = ""
        try:
            resp = await page.goto(args.url, timeout=args.timeout, wait_until="domcontentloaded")
            section("RESPONSE")
            print(f"status: {resp.status if resp else 'n/a'}")
            print(f"final url: {page.url}")
            print(f"title: {await page.title()}")

            try:
                await page.wait_for_load_state("networkidle", timeout=args.timeout)
            except Exception:
                print("(networkidle never reached -- continuing)")
            await page.wait_for_timeout(3000)

            clicked = await dismiss_consent(page)
            section("CONSENT GATE")
            print(f"clicked: {clicked!r}")

            body = await page.locator("body").inner_text()

            # Earlier runs intermittently got a ~321-char body. If that
            # happens, scroll (lazy-render) and retry before giving up, and
            # show what was actually served.
            if len(body) < MIN_PLAUSIBLE_BODY:
                print(f"\n!! Body only {len(body)} chars -- retrying after scroll")
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(4000)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(2000)
                body = await page.locator("body").inner_text()
                if len(body) < MIN_PLAUSIBLE_BODY:
                    section("SHORT-BODY DIAGNOSTIC (what the server actually served)")
                    print(repr(body))
                    html = await page.content()
                    print(f"\nraw HTML length: {len(html)}")
                    print(html[:6000])

            # The shop is a #ticket-shop anchor -- scroll it into view so any
            # lazy-loaded offers actually render.
            try:
                target = page.locator("#ticket-shop")
                if await target.count() > 0:
                    await target.first.scroll_into_view_if_needed(timeout=5000)
                    await page.wait_for_timeout(3000)
                    body = await page.locator("body").inner_text()
                    print("\n(scrolled #ticket-shop into view and re-read body)")
            except Exception as e:
                print(f"(#ticket-shop scroll failed: {e})")

            section("BODY TEXT STATS")
            print(f"body text length: {len(body)}")
            for v in variants:
                print(f"  occurrences of {v!r}: {body.count(v)}")
            print(f"  occurrences of '€': {body.count('€')}")
            print(f"  occurrences of 'Details anzeigen': {body.count('Details anzeigen')}")
            print(f"  occurrences of 'ausverkauft': {body.lower().count('ausverkauft')}")
            print(f"  occurrences of 'Anfrage': {body.count('Anfrage')}")

            section("DATE-ANCHORED ELEMENTS")
            try:
                anchored = await page.evaluate(_DATE_ANCHORED_JS, variants)
                print(f"matches: {len(anchored)}")
                for i, a in enumerate(anchored):
                    print(f"\n----- match {i} -----")
                    print(json.dumps(a, indent=2, ensure_ascii=False)[:5000])
            except Exception as e:
                print(f"date-anchored evaluate failed: {e}")

            section("REPEATED CLASS SIGNATURES (candidate card selectors)")
            try:
                rep = await page.evaluate(_REPEATED_CLASS_JS)
                for r in rep:
                    print(f"{r['n']:4d}x  {r['cls']}")
            except Exception as e:
                print(f"repeated-class evaluate failed: {e}")

            section(f"RENDERED BODY TEXT (first {args.body_chars} chars)")
            # Collapse runs of blank lines; this site is whitespace-heavy.
            cleaned = re.sub(r"\n{3,}", "\n\n", body)
            print(cleaned[: args.body_chars])

        except Exception as e:
            section("FATAL")
            print(f"{type(e).__name__}: {e}")
            return 1
        finally:
            await context.close()
            await browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
