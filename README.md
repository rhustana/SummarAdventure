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

Watches the official resale marketplace
(`https://www.oktoberfest-booking.com/de#ticket-shop`) every 10 minutes for
table offers on a target date, and pushes a notification to your phone the
moment a **new** one appears. It never re-notifies about an offer it has
already reported, and it never books, reserves, or pays for anything — it
only reads the page and messages you.

Default target date: **Saturday, 26 September 2026**.

## Setup (one time, ~2 minutes)

Notifications go through [ntfy.sh](https://ntfy.sh) — free, instant, no
account required.

1. Install the **ntfy** app (iOS App Store / Google Play / F-Droid).
2. Tap **+** to subscribe to a topic. Invent a long, unguessable name —
   anyone who knows a topic name can read and post to it. Something like
   `wiesn-tisch-a7f3k9q2x` rather than `oktoberfest`.
3. In this repo: **Settings → Secrets and variables → Actions → New
   repository secret**. Name it `NTFY_TOPIC`, value is the topic name only
   (not the full URL).

That's it. The watcher is already scheduled and will start checking on its
own.

To confirm it works end to end, go to **Actions → Check Oktoberfest resale
listings → Run workflow**, set **show_all** to `true`, and check the log:
you should see a list of every offer currently on the site, grouped by date.

## What to expect

- **The first run records a baseline.** Whatever is already listed for your
  date is recorded silently, so you don't get an alert for offers that were
  already there. Only offers appearing *after* that trigger a push.
- Alerts fire at **urgent** priority so they break through Do Not Disturb.
- If an offer disappears and later relists, you get alerted again — the
  watcher forgets offers that are no longer on the page.

## How it works

`resale_checker/parse.py` reads the shop's **rendered text**, not its DOM.
Each offer renders in a strictly regular shape:

```
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
Details anzeigen
```

The parser anchors on the `Weekday, DD.MM.YYYY` line and reads the fields
that follow. Two details matter: the price it records is the one after
`Summe` (the line items above it are the cost breakdown, not the total), and
an offer's identity is a hash of tent + date + slot + time + seats + total,
so re-rendering the page doesn't make an existing offer look new.

This replaced a DOM-walking extractor that anchored on prices and climbed to
the nearest ancestor with a link. On this site that lands on the per-tent
header card (`Infos zum Zelt / Hacker Festzelt`, href
`/de/<tent>-tischreservierung`) rather than on a bookable offer — so the old
watcher recorded tent pages, and could never have fired on an actual table.
Text parsing is also immune to the Tailwind/Livewire class churn that made
the DOM approach so fragile.

`python check_resale.py --self-test` runs the parser against
`tests/fixture_shop.txt`, captured from the live site. The workflow runs it
before every check, so a parser regression fails loudly instead of silently
returning zero offers.

## Running it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Dry run: print every offer found, notify nobody
python check_resale.py --notify-via stdout --show-all

# Watch it work in a real browser window
python check_resale.py --notify-via stdout --headed

# Dump the site's raw rendered markup (for when the layout changes)
python recon_resale.py --date 2026-09-26
```

## Limits worth knowing

- **Scheduled GitHub Actions runs are best-effort.** GitHub delays cron
  workflows under load, sometimes well past the nominal interval. The
  10-minute schedule is a target, not a guarantee.
- **The site sells its own alert, and it beats this one.** The page
  advertises a *Reservierungsalarm* at €9.99/year for email (€29.99 for
  WhatsApp) that notifies you **ten minutes before new offers are published**
  («Lass Dich zehn Minuten vor Veröffentlichung neuer Tischangebote […]
  benachrichtigen»). This watcher can only ever see an offer *after* it goes
  live. For a prime Saturday that head start is likely decisive — treat this
  repo as a free backstop, not a replacement.
- An offer that matches an existing one on tent, date, slot, time, seats
  *and* total collapses into a single alert. Such offers are interchangeable
  to a buyer, and this is far safer than keying on raw text, which treated
  any wording change as a brand-new listing.
- The watcher only reads the public shop page. Actually buying still means
  logging in and completing checkout yourself, quickly.
- `state/resale_seen.json` is written by automation. It's committed only
  when it actually changes, so quiet periods produce no commits — don't
  hand-edit it while the watcher is running.

## If it stops working

Two failure modes raise a push alarm on their own, throttled to at most one
every 12 hours:

- **Can't read the site** — blocked, down, or served a stub page.
- **Parsing broke** — the page loaded but no offers could be parsed for any
  date, which means the layout changed.

That second alarm is the important one. The previous version had no such
check, so it reported success every hour for weeks while recording nothing
usable. When it fires, run the workflow with **dump** set to `true` and read
the log — it prints the site's current rendered markup, which is what
`resale_checker/parse.py` needs to be updated against.

## Before it runs automatically

GitHub fires `schedule` triggers **only from the repository's default
branch**. This work lives on `claude/oktoberfest-table-monitor-9m8v4f`,
while the default branch is `claude/oktoberfest-tent-reservations-6lo0jq` —
so until these changes are merged into the default branch, the 10-minute
cron never fires and only manual **Run workflow** dispatches happen.

Two things are needed to go live:

1. Add the `NTFY_TOPIC` secret (see Setup above). Without it, scheduled runs
   skip with a warning rather than checking — deliberately, so no offer is
   marked "already seen" while alerts can't be delivered.
2. Merge this branch into the default branch.
