"""Heuristics for turning a rendered reservation page into a status.

None of this was validated against the live sites (this tool was built in a
sandbox with no general internet egress — see README "Known limitations").
Treat the keyword lists and calendar fingerprints as a first draft: run
`check_availability.py --only <tent-id> --headed --keep-open` against a real
site and adjust `classify.py` based on what you actually see.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    AVAILABLE = "available"  # positive signal the target date is bookable
    LIKELY_FULL = "likely_full"  # positive signal the target date/tent is full
    FORM_ONLY = "form_only"  # a request form exists but no live per-date signal was found
    BLOCKED = "blocked"  # bot protection / CAPTCHA likely stopped us
    ERROR = "error"  # navigation/timeout/other failure
    NEEDS_REVIEW = "needs_review"  # no heuristic matched confidently either way


# German phrases that show up on a tent/restaurant site when reservations for
# a date (or the whole season) are closed out. Case-insensitive substring match
# against the page's visible text.
FULL_KEYWORDS = [
    "ausgebucht",
    "restlos ausgebucht",
    "vollständig ausgebucht",
    "keine reservierung mehr möglich",
    "keine reservierungen mehr möglich",
    "keine reservierungen mehr",
    "reservierung nicht mehr möglich",
    "reservierung geschlossen",
    "reservierungen geschlossen",
    "leider ausgebucht",
    "keine plätze mehr frei",
    "keine freien plätze",
    "keine freien tische",
    "warteliste",
    "fully booked",
    "sold out",
    "no availability",
]

# Phrases suggesting reservations are open / a request can be made. This is a
# weak signal on its own (most of these sites always show a "reserve" button
# even when full) -- it mainly helps distinguish FORM_ONLY from NEEDS_REVIEW.
OPEN_KEYWORDS = [
    "jetzt reservieren",
    "reservierung anfragen",
    "tisch reservieren",
    "tisch anfragen",
    "online reservieren",
    "reservierungsanfrage",
    "reservierungsformular",
    "jetzt anfragen",
    "verfügbar",
    "plätze frei",
    "book a table",
    "make a reservation",
]

BLOCKED_KEYWORDS = [
    "captcha",
    "cloudflare",
    "checking your browser",
    "access denied",
    "are you human",
    "attention required",
    "please verify you are a human",
    "unusual traffic",
]

# CSS/JS fingerprints of common date-picker / calendar widgets, used to decide
# whether a page likely has a real per-date calendar worth trying to click
# through (vs. a plain contact form).
CALENDAR_FINGERPRINTS = [
    "flatpickr",
    "daterangepicker",
    "air-datepicker",
    "ui-datepicker",  # jQuery UI
    "vc-date-picker",  # v-calendar
    "fc-daygrid",  # FullCalendar
    "react-datepicker",
    "mx-datepicker",  # element-plus / mint-ui
    'type="date"',
    "type='date'",
]


@dataclass
class ClassificationResult:
    status: Status
    evidence: str | None = None  # the matched keyword/snippet, for the report


def _find_first_match(haystack: str, needles: list[str]) -> str | None:
    lower = haystack.lower()
    for needle in needles:
        if needle in lower:
            return needle
    return None


def date_format_variants(target_date: dt.date) -> list[str]:
    """Common German/ISO date string formats a page might render the target date in."""
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
    ]


def has_calendar_widget(html: str) -> bool:
    lower = html.lower()
    return any(fp.lower() in lower for fp in CALENDAR_FINGERPRINTS)


def mentions_target_date(html: str, target_date: dt.date) -> bool:
    variants = date_format_variants(target_date)
    return any(v in html for v in variants)


def classify_page(
    *,
    visible_text: str,
    html: str,
    target_date: dt.date,
    http_status: int | None,
    navigation_error: str | None,
) -> ClassificationResult:
    """Best-effort classification from a fully-rendered page.

    This is intentionally conservative: it only claims AVAILABLE/LIKELY_FULL
    when a fairly specific keyword hit, and falls back to FORM_ONLY /
    NEEDS_REVIEW otherwise so a human double-checks before trusting it.
    """
    if navigation_error:
        return ClassificationResult(Status.ERROR, evidence=navigation_error)

    if http_status is not None and http_status >= 400:
        return ClassificationResult(Status.ERROR, evidence=f"HTTP {http_status}")

    blocked = _find_first_match(visible_text, BLOCKED_KEYWORDS)
    if blocked:
        return ClassificationResult(Status.BLOCKED, evidence=blocked)

    full_hit = _find_first_match(visible_text, FULL_KEYWORDS)
    if full_hit:
        return ClassificationResult(Status.LIKELY_FULL, evidence=full_hit)

    date_mentioned = mentions_target_date(html, target_date)
    open_hit = _find_first_match(visible_text, OPEN_KEYWORDS)

    if date_mentioned and open_hit:
        return ClassificationResult(
            Status.AVAILABLE,
            evidence=f"target date found on page + '{open_hit}'",
        )

    if has_calendar_widget(html):
        return ClassificationResult(
            Status.NEEDS_REVIEW,
            evidence="calendar widget detected but date-specific availability "
            "could not be read automatically -- open the screenshot/page manually",
        )

    if open_hit:
        return ClassificationResult(Status.FORM_ONLY, evidence=open_hit)

    return ClassificationResult(Status.NEEDS_REVIEW, evidence=None)
