"""Playwright helpers: load a page, grab its text/html/screenshot safely."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Browser, TimeoutError as PlaywrightTimeoutError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class PageSnapshot:
    url: str
    final_url: str | None
    http_status: int | None
    visible_text: str
    html: str
    screenshot_path: str | None
    navigation_error: str | None


async def snapshot_page(
    browser: Browser,
    url: str,
    *,
    screenshot_path: str | None,
    timeout_ms: int = 30_000,
) -> PageSnapshot:
    """Navigate to `url` and capture text/html/screenshot for classification.

    Any failure (timeout, DNS error, etc.) is captured into
    `navigation_error` rather than raised, so one bad tent doesn't abort the
    whole batch.
    """
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1400, "height": 1000},
        locale="de-DE",
    )
    page = await context.new_page()

    navigation_error: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    visible_text = ""
    html = ""

    try:
        response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        http_status = response.status if response else None
        final_url = page.url

        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass  # some sites never go idle (polling widgets); best effort only

        # Give client-side calendars/widgets a moment to render.
        await page.wait_for_timeout(1500)

        visible_text = await page.inner_text("body")
        html = await page.content()

        if screenshot_path:
            await page.screenshot(path=screenshot_path, full_page=True)

    except PlaywrightTimeoutError as e:
        navigation_error = f"Timed out loading page: {e}"
    except Exception as e:  # noqa: BLE001 -- one tent's failure must not sink the batch
        navigation_error = f"{type(e).__name__}: {e}"
    finally:
        await context.close()

    return PageSnapshot(
        url=url,
        final_url=final_url,
        http_status=http_status,
        visible_text=visible_text,
        html=html,
        screenshot_path=screenshot_path if screenshot_path and navigation_error is None else None,
        navigation_error=navigation_error,
    )
