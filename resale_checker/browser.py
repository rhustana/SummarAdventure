"""Render the resale shop and hand back its text.

Deliberately thin: all listing logic lives in `parse.py`, which works on the
rendered text rather than the DOM. The previous version of this module
returned DOM-climbed "candidate" blocks, which is what produced tent pages
instead of offers -- that path is gone.
"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Browser

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CONSENT_LABELS = [
    "Alle akzeptieren",
    "Alle Cookies akzeptieren",
    "Akzeptieren",
    "Alle zulassen",
    "Zustimmen",
    "Einverstanden",
    "Verstanden",
    "Accept all",
]

# Earlier runs intermittently got a ~321-char body where a full load gives
# tens of thousands. Treat anything this short as "not the shop".
MIN_PLAUSIBLE_BODY = 2000


@dataclass
class FetchResult:
    page_url: str
    body_text: str
    error: str | None
    consent_clicked: str | None = None


async def _dismiss_consent(page) -> str | None:
    for label in CONSENT_LABELS:
        for frame in page.frames:
            try:
                btn = frame.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    return label
            except Exception:
                continue
    return None


async def fetch_body_text(
    browser: Browser,
    url: str,
    *,
    timeout_ms: int = 45_000,
    screenshot_path: str | None = None,
) -> FetchResult:
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 1200},
        locale="de-DE",
        timezone_id="Europe/Berlin",
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    page = await context.new_page()

    error: str | None = None
    body = ""
    page_url = url
    consent: str | None = None

    try:
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        page_url = page.url
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass  # this site rarely goes fully idle -- best effort
        await page.wait_for_timeout(2500)

        consent = await _dismiss_consent(page)

        # Offers live under the #ticket-shop anchor; scrolling it into view
        # makes sure anything lazily rendered has actually rendered.
        try:
            shop = page.locator("#ticket-shop")
            if await shop.count() > 0:
                await shop.first.scroll_into_view_if_needed(timeout=5000)
                await page.wait_for_timeout(2500)
        except Exception:
            pass

        body = await page.locator("body").inner_text()

        if len(body) < MIN_PLAUSIBLE_BODY:
            # Scroll and retry once before declaring the load bad.
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(4000)
            body = await page.locator("body").inner_text()

        if len(body) < MIN_PLAUSIBLE_BODY:
            error = f"page loaded but body was only {len(body)} chars (bot gate or placeholder?)"

        if screenshot_path:
            await page.screenshot(path=screenshot_path, full_page=True)

    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        await context.close()

    return FetchResult(page_url=page_url, body_text=body, error=error, consent_clicked=consent)
