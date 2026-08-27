# Oktoberfest tent table-availability checker

A personal tool that visits each Oktoberfest tent's reservation page, tries
to work out whether tables are still available/bookable for a given date,
and writes a consolidated HTML report. It **only reads pages** — it never
fills in or submits any reservation form, and does not purchase anything.

Default target date: **Saturday, September 26, 2026**.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# Check every configured tent for the default date, write + open a report
python check_availability.py

# A different date
python check_availability.py --date 2026-09-19

# Just a few tents, with a visible browser (handy while debugging one site)
python check_availability.py --only hofbraeu-festzelt,schottenhamel --headed

# See the configured tent ids without checking anything
python check_availability.py --list
```

Each run writes `reports/<timestamp>/report.html` plus a screenshot per tent
under `reports/<timestamp>/screenshots/`, and opens the report in your
default browser when done (`--no-open` to skip that).

Tents are configured in `config/tents.json` (id, name, url, optional notes).
Add, remove, or fix URLs there — no code changes needed for that.

## How classification works

`oktoberfest_checker/classify.py` renders each page with Playwright, then
buckets it into one of:

- **Available** — the target date's text and an "open for reservations"
  phrase were both found on the page.
- **Likely full** — a German "ausgebucht"/"no more tables"-style phrase was
  found.
- **Request-only form** — a reservation form exists, but no date-specific
  availability signal was found (many tents only take inquiry-style requests
  with no live calendar — you'll need to submit an inquiry to actually know).
- **Needs manual review** — nothing matched confidently, or a calendar
  widget was detected but its specific day cells couldn't be read
  automatically. Open the screenshot.
- **Blocked** — the page looks like it hit bot protection / a CAPTCHA.
- **Error** — the page failed to load (timeout, DNS, etc.).

**Every result includes a screenshot — check it before trusting the status.**
This is keyword/heuristic-based, not a real booking API, and will
occasionally misread a page.

## Known limitations (read before running)

This tool was built in a sandboxed environment with no general internet
egress, so **none of the 36 configured tent URLs could actually be loaded or
inspected while writing this** — the heuristics in `classify.py` are a
first draft based on common German phrasing and common calendar-widget
fingerprints, not on what these specific sites actually do. The
scraping/rendering pipeline itself (browser launch, page snapshot,
classification, HTML report) was validated against a local test page and
works correctly; what's untested is whether the *keyword lists* match what
each real site actually says.

Expect to need a first real run, then some iteration:

1. Run `python check_availability.py --only <tent-id> --headed` for a tent
   that came back `needs_review` or `error`.
2. Look at the browser window and/or the saved screenshot.
3. Adjust `FULL_KEYWORDS` / `OPEN_KEYWORDS` / `CALENDAR_FINGERPRINTS` in
   `oktoberfest_checker/classify.py`, or add a per-tent override if a site
   needs bespoke logic (e.g. clicking into a calendar widget).

Other things to know:

- **Most tents don't sell "tickets" for table seats.** Oktoberfest tent
  reservations are typically free inquiry forms (any deposit is paid later,
  once the tent confirms), and big tents often open/close their reservation
  windows for the whole season well before September. "Available" here
  generally means "the reservation form is open," not "instantly bookable."
- A few config entries have a `notes` field flagging a URL that's a
  homepage rather than a reservation page, looks stale (e.g. a
  `.../2023/` path), or was recovered from a malformed link in the original
  list — check `config/tents.json` for those and fix as needed.
- Some sites may block headless browsers outright; those will show up as
  `blocked` or `error`. Be respectful of each site's terms of service and
  rate limits — this is a personal-use checking tool, not a scraper meant
  to run continuously or aggressively.
