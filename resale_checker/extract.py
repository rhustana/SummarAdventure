"""Heuristic extraction of resale listings from the rendered page.

This was written without ever being able to load the real site (see
README "Known limitations") -- it finds the smallest DOM elements that
contain a price and treats each as a "listing card". This is a reasonable
generic starting point but WILL need a calibration pass against the real
page: run `check_resale.py --dump` to save every price-bearing candidate
plus a screenshot, inspect them, and either tighten `PRICE_RE`/`is_target_date`
below or pass `--card-selector` with an exact CSS selector for listing cards.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass

PRICE_RE = re.compile(r"(\d+[.,]?\d*)\s?€|€\s?(\d+[.,]?\d*)")

# JS run in-page via Playwright's page.evaluate(). First finds the smallest
# elements whose own text contains a price but whose children don't (i.e.
# the price's tightest containing element) -- these anchor one candidate
# "listing" each. Since a real card's price, date, and buy-link are often
# in separate sibling elements rather than all in one node, each anchor
# then climbs its ancestor chain until it reaches an element that also
# contains a date-shaped string and a link, so the returned text/href
# actually cover the whole card and not just the price fragment. Multiple
# price anchors that climb to the same ancestor collapse into one candidate.
_CANDIDATE_JS = r"""
(priceSource) => {
  const priceRe = new RegExp(priceSource);
  const dateRe = /\d{1,2}[.\/]\d{1,2}[.\/]\d{2,4}|\d{1,2}\.\s?(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)/i;
  const MAX_CLIMB = 6;

  const all = Array.from(document.querySelectorAll('body *'));
  const priceLeaves = [];
  for (const el of all) {
    const text = (el.textContent || '').trim();
    if (!text || text.length > 800) continue;
    if (!priceRe.test(text)) continue;
    const childHasPrice = Array.from(el.children).some(
      c => priceRe.test((c.textContent || ''))
    );
    if (childHasPrice) continue;
    priceLeaves.push(el);
  }

  const seenCards = new Set();
  const out = [];
  for (const leaf of priceLeaves) {
    let card = leaf;
    for (let depth = 0; depth < MAX_CLIMB; depth++) {
      const text = (card.textContent || '').trim();
      const hasDate = dateRe.test(text);
      // Some sites (this one included) drive their buy/details action off a
      // JS click handler on a <button>, not a real <a href> -- accept either
      // as "actionable" so the climb doesn't overshoot the real card looking
      // for a link that will never exist at this level.
      const hasLink = !!card.querySelector('a[href], button');
      if (hasDate && hasLink) break;
      if (!card.parentElement || card.parentElement === document.body) break;
      card = card.parentElement;
    }

    if (seenCards.has(card)) continue;
    seenCards.add(card);

    const link = card.tagName === 'A' ? card : card.querySelector('a[href]');
    out.push({
      // Generous slices: a real card's price/date/details text can sit well
      // past a smaller cutoff behind large blocks of whitespace and
      // decorative icon markup (verified against the real site).
      text: (card.textContent || '').trim().slice(0, 4000),
      html: card.outerHTML.slice(0, 4000),
      href: link ? link.href : null,
      tag: card.tagName,
      className: (card.className || '').toString(),
    });
  }
  return out;
}
"""


def candidate_extraction_script() -> tuple[str, str]:
    """Returns (js_function_body, price_regex_source) for page.evaluate()."""
    return _CANDIDATE_JS, PRICE_RE.pattern


def date_format_variants(target_date: dt.date) -> list[str]:
    de_months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    return [
        target_date.strftime("%Y-%m-%d"),
        target_date.strftime("%d.%m.%Y"),
        target_date.strftime("%d.%m.%y"),
        f"{target_date.day}. {de_months[target_date.month - 1]} {target_date.year}",
        f"{target_date.day}.{target_date.month}.{target_date.year}",
        f"{target_date.day:02d}.{target_date.month:02d}",  # bare DD.MM, common in compact listings
    ]


@dataclass
class Listing:
    id: str
    text: str
    url: str | None
    matched_date_variant: str

    @staticmethod
    def from_candidate(candidate: dict, matched_variant: str, page_url: str) -> "Listing":
        href = candidate.get("href")
        if href:
            listing_id = hashlib.sha256(href.encode("utf-8")).hexdigest()[:16]
        else:
            # No stable link on the card -- fall back to a hash of its text.
            # NOTE: if a listing's price/wording changes slightly between
            # runs this will look like a "new" listing. Prefer --card-selector
            # + a real id/href once you've seen the actual markup.
            listing_id = hashlib.sha256(candidate["text"].encode("utf-8")).hexdigest()[:16]
        return Listing(
            id=listing_id,
            text=candidate["text"],
            url=href or page_url,
            matched_date_variant=matched_variant,
        )


def find_listings_for_date(
    candidates: list[dict], target_date: dt.date, page_url: str
) -> list[Listing]:
    variants = date_format_variants(target_date)
    listings = []
    for c in candidates:
        text = c["text"]
        hit = next((v for v in variants if v in text), None)
        if hit:
            listings.append(Listing.from_candidate(c, hit, page_url))
    return listings
