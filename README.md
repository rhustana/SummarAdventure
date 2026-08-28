# Oktoberfest tent table-availability checker

A personal tool that visits each Oktoberfest tent's reservation page, tries
to work out whether tables are still available/bookable for a given date,
and writes a consolidated HTML report. It **only reads pages** — it never
fills in or submits any reservation form, and does not purchase anything.

Default target date: **Saturday, September 26, 2026**.

## Running it without installing anything (recommended if you're not technical)

This repo includes a GitHub Actions workflow that runs the checker in the
cloud and gives you a webpage with the results. One-time setup, then you
just click a button whenever you want a fresh check.

**One-time setup (about 1 minute):**

1. On this repo's GitHub page, click **Settings** (top menu bar).
2. In the left sidebar, click **Pages**.
3. Under "Build and deployment" → "Source", choose **GitHub Actions**.

That's it — you won't need to touch settings again.

**Every time you want to check availability:**

1. Click the **Actions** tab (top menu bar).
2. In the left sidebar, click **Check Oktoberfest tent availability**.
3. Click the **Run workflow** button (top right of the list), optionally
   change the date, then click the green **Run workflow** button in the
   dropdown.
4. Wait a few minutes (it's visiting 36 websites one by one) — refresh the
   page and you'll see a run appear with a spinner, then a green checkmark
   once it's done.
5. Click into that run, then open the **deploy** step to find the report's
   web link (also always available at
   `https://<your-github-username>.github.io/SummarAdventure/`).
   If you see a red X on "deploy" instead — that only happens if step 3 of
   the one-time setup above wasn't done yet, or hasn't finished propagating
   yet (can take a minute the very first time). Either way, you can still
   get the results: scroll to the bottom of the run page to
   **Artifacts**, download **availability-report**, and unzip it — inside
   is `report.html`, open it by double-clicking.

## Running it on your own computer instead

If you'd rather run it locally (more reliable — it looks like an ordinary
home visitor to the tent sites, whereas GitHub's cloud servers might get
blocked by some sites' bot protection more easily):

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

---

# Resale listing watcher (second app)

A separate tool that checks one resale site
(`https://www.oktoberfest-booking.com/de#ticket-shop`) every hour for table
listings on a given date, and sends you a free push notification the moment
a **new** one appears. It never re-notifies you about a listing it already
told you about, and it never buys or reserves anything — it only reads the
page and messages you.

Default target date: **Saturday, September 26, 2026**.

## One-time setup (about 5 minutes)

**1. Get a private notification channel (no account needed):**

- On your phone, install the free **ntfy** app ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)), or just use [ntfy.sh](https://ntfy.sh) in a browser.
- Pick a **topic name** that's private to you — treat it like a secret
  password (anyone who knows it can see your notifications). A ready-made
  random one you can use: `oktoberfest-resale-f511e5e8928ae194`
- In the app (or on the website), **subscribe** to that exact topic name.
  That's it — no sign-up, no email.

**2. Tell the GitHub workflow your topic name:**

1. On this repo's GitHub page, click **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret**.
3. Name: `NTFY_TOPIC`. Value: the topic name you subscribed to above.
4. Click **Add secret**.

**3. Turn the checker on:**

1. Click the **Actions** tab.
2. In the left sidebar, click **Check Oktoberfest resale listings**.
3. If prompted, click **Enable workflow**.

That's it. From here it runs itself, once an hour, no clicking needed.
(You can also click **Run workflow** any time to check immediately.)

## What to expect

- The **first run** just records whatever's already listed for the target
  date as a baseline — you won't get notified for those, only for anything
  that shows up *after* that first run.
- After that, every hour it checks again, and you get a push notification
  only for listings it hasn't shown you before.
- Each notification includes the listing's price/description and a link —
  tapping it opens the resale site so you can act on it yourself. Nothing
  is ever booked or paid for automatically.

## Known limitations (read before relying on this)

Same caveat as the first app: this was built in a sandbox with no access to
the real site, so `resale_checker/extract.py`'s listing-detection logic
(find a price on the page, then walk up to the nearest containing block
that also has a date and a link) is an untested first draft, not tuned to
this specific site's actual markup.

**Please do a manual calibration pass before trusting it to run silently:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python check_resale.py --dump
```

This opens the page, saves every price-bearing block it found to
`debug/candidates.json`, and a full-page screenshot to
`debug/resale_page.png` — no notifications sent, no state touched. Check
that real listings are being captured as single, sensible blocks (not
merged together, not split apart, not missing their link). If they're not,
either:

- send me `debug/candidates.json` and a description of what a listing card
  actually looks like, so the extraction logic can be corrected, or
- if you can identify the CSS class/selector for a listing card yourself
  (e.g. via your browser's "Inspect Element"), pass it directly:
  `python check_resale.py --card-selector ".some-listing-class"` — this
  skips the heuristic entirely and is far more reliable once known. Add it
  to the `check_resale.py` step's arguments in
  `.github/workflows/check-resale.yml` once confirmed.

Other things to know:

- The dedup key prefers the listing's own link URL; if a card has no
  distinct link, it falls back to hashing the card's text, which means a
  listing whose price or wording changes slightly could look "new" again.
- The workflow commits `state/resale_seen.json` back to the repo after
  every run so it remembers what it's already told you about — don't edit
  that file by hand while the workflow is enabled.
- If the site becomes unreachable (blocked, down, redesigned), you'll get a
  one-time "monitoring broken" push (throttled to at most once per 12
  hours) instead of silent failure.
- ntfy's free tier is a public broker; your topic name is the only thing
  keeping others from seeing your notifications, so don't reuse a
  guessable one.
