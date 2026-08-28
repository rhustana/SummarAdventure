"""Playwright page-fetch for the resale site."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Browser

from .extract import candidate_extraction_script

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    page_url: str
    candidates: list[dict]
    screenshot_path: str | None
    error: str | None


async def fetch_candidates(
    browser: Browser,
    url: str,
    *,
    card_selector: str | None = None,
    screenshot_path: str | None = None,
    timeout_ms: int = 30_000,
) -> FetchResult:
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1400, "height": 1000},
        locale="de-DE",
    )
    page = await context.new_page()

    error: str | None = None
    candidates: list[dict] = []
    page_url = url

    try:
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass  # some sites never go idle -- best effort
        await page.wait_for_timeout(2000)  # let client-side rendering settle

        page_url = page.url

        if card_selector:
            # Precise mode once the real markup is known: each match IS a
            # listing card, no price/date filtering needed at this stage.
            elements = await page.query_selector_all(card_selector)
            for el in elements:
                text = (await el.inner_text()).strip()
                html = await el.evaluate("e => e.outerHTML.slice(0, 2000)")
                href = await el.evaluate(
                    "e => (e.tagName === 'A' ? e : e.querySelector('a[href]'))?.href || null"
                )
                candidates.append({"text": text, "html": html, "href": href})
        else:
            js_body, price_source = candidate_extraction_script()
            candidates = await page.evaluate(js_body, price_source)

        if screenshot_path:
            await page.screenshot(path=screenshot_path, full_page=True)

    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        await context.close()

    return FetchResult(
        page_url=page_url,
        candidates=candidates,
        screenshot_path=screenshot_path if screenshot_path and error is None else None,
        error=error,
    )
