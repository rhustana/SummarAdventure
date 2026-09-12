"""Parse bookable resale offers out of the shop's rendered text.

Why text and not CSS selectors: the old extractor walked the DOM, anchoring
on a price and climbing to the nearest ancestor holding a link. On this site
that reliably lands on the per-tent header card ("Infos zum Zelt / Hacker
Festzelt", href `/de/<tent>-tischreservierung`) rather than on a bookable
offer -- which is why `state/resale_seen.json` was full of tent pages and
the watcher could never have fired on a real table.

The rendered text, by contrast, is strictly regular (confirmed against the
live site). One offer reads:

    Infos zum Zelt
    Fischer Vroni Festzelt
    Montag, 28.09.2026
    Mittag
    11:00-16:00 Uhr
    10 Personen
    1 Tisch(e)
    Inkludierte Leistungen
    20 x Bier (á € 15,00)
    € 300,00
    ...
    Summe
    € 531,90
    € 531,90
    Details anzeigen

Anchoring on the weekday+date line and reading the fields that follow is
both simpler and immune to the Tailwind/Livewire class churn that broke the
DOM approach.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, asdict

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# "Samstag, 26.09.2026" -- the anchor for one offer.
DATE_LINE_RE = re.compile(
    r"^(" + "|".join(WEEKDAYS) + r")\s*,\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$"
)

TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*Uhr\s*$")
PERSONS_RE = re.compile(r"^(\d+)\s*Personen?\s*$")
TABLES_RE = re.compile(r"^(\d+)\s*Tisch(?:\(e\)|e)?\s*$")
# Prices render with a non-breaking space after the euro sign.
PRICE_RE = re.compile(r"^€\s*([\d.]+,\d{2})\s*$")

SLOTS = {"Mittag", "Nachmittag", "Abend", "Vormittag"}

# An offer block ends at whichever of these comes first.
BLOCK_END = {"Details anzeigen"}

# Lines that decorate a card but carry no data.
NOISE = {"Infos zum Zelt", "Inkludierte Leistungen", "...", "Details anzeigen"}


@dataclass
class Offer:
    tent: str
    date: str            # ISO, YYYY-MM-DD
    weekday: str
    slot: str | None     # Mittag / Nachmittag / Abend
    time: str | None     # "11:00-16:00"
    persons: int | None
    tables: int | None
    total: str | None    # "531,90"
    id: str

    def summary(self) -> str:
        bits = [self.tent]
        if self.slot:
            bits.append(self.slot)
        if self.time:
            bits.append(self.time)
        if self.persons:
            bits.append(f"{self.persons} Pers.")
        if self.tables:
            bits.append(f"{self.tables} Tisch(e)")
        if self.total:
            bits.append(f"€ {self.total}")
        return " · ".join(bits)


def _parse_price_to_float(total: str | None) -> float | None:
    """'1.476,00' -> 1476.0 (German formatting)."""
    if not total:
        return None
    try:
        return float(total.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _make_id(tent: str, date: str, slot: str | None, time: str | None,
             persons: int | None, tables: int | None, total: str | None) -> str:
    """Stable across runs: identical fields mean the same offer.

    Two genuinely distinct listings that match on every single field are
    indistinguishable here and collapse into one alert. That is an accepted
    trade-off -- such offers are interchangeable to a buyer -- and it is far
    safer than the old text-hash id, which treated any whitespace or wording
    change as a brand-new listing.
    """
    raw = "|".join([tent, date, slot or "", time or "", str(persons or ""), str(tables or ""), total or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_offers(body_text: str) -> list[Offer]:
    """Extract every offer on the page, in document order."""
    lines = [ln.strip() for ln in body_text.splitlines()]
    lines = [ln for ln in lines if ln]

    offers: list[Offer] = []

    for i, line in enumerate(lines):
        m = DATE_LINE_RE.match(line)
        if not m:
            continue

        weekday, day, month, year = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            date = dt.date(year, month, day)
        except ValueError:
            continue

        # The tent name is the nearest preceding line that isn't decoration
        # and isn't itself another offer's field.
        tent = None
        for j in range(i - 1, max(-1, i - 5), -1):
            cand = lines[j]
            if cand in NOISE or cand in SLOTS:
                continue
            if DATE_LINE_RE.match(cand) or PRICE_RE.match(cand):
                break
            tent = cand
            break
        if not tent:
            continue

        slot = time = total = None
        persons = tables = None
        seen_summe = False

        # Read forward to the end of this offer block.
        for k in range(i + 1, min(len(lines), i + 60)):
            cur = lines[k]

            if DATE_LINE_RE.match(cur):
                break  # next offer started

            if cur in BLOCK_END:
                break

            if cur in SLOTS and slot is None:
                slot = cur
                continue

            tm = TIME_RE.match(cur)
            if tm and time is None:
                time = f"{tm.group(1)}-{tm.group(2)}"
                continue

            pm = PERSONS_RE.match(cur)
            if pm and persons is None:
                persons = int(pm.group(1))
                continue

            tb = TABLES_RE.match(cur)
            if tb and tables is None:
                tables = int(tb.group(1))
                continue

            # The total is the first price AFTER the "Summe" label -- prices
            # before it are line items in the cost breakdown.
            if cur == "Summe":
                seen_summe = True
                continue
            if seen_summe and total is None:
                pr = PRICE_RE.match(cur)
                if pr:
                    total = pr.group(1)
                    continue

        iso = date.isoformat()
        offers.append(
            Offer(
                tent=tent,
                date=iso,
                weekday=weekday,
                slot=slot,
                time=time,
                persons=persons,
                tables=tables,
                total=total,
                id=_make_id(tent, iso, slot, time, persons, tables, total),
            )
        )

    return offers


def offers_for_date(offers: list[Offer], target: dt.date) -> list[Offer]:
    iso = target.isoformat()
    seen: dict[str, Offer] = {}
    for o in offers:
        if o.date == iso:
            seen.setdefault(o.id, o)
    return list(seen.values())


def offer_to_dict(o: Offer) -> dict:
    d = asdict(o)
    d["total_eur"] = _parse_price_to_float(o.total)
    return d
