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
    page_text: str | None = None
    button_labels: list[str] | None = None
    sample_offer_row: dict | None = None


async def fetch_candidates(
    browser: Browser,
    url: str,
    *,
    card_selector: str | None = None,
    screenshot_path: str | None = None,
    timeout_ms: int = 30_000,
    capture_diagnostics: bool = False,
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
    page_text: str | None = None
    button_labels: list[str] | None = None
    sample_offer_row: dict | None = None

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

        if capture_diagnostics:
            page_text = await page.locator("body").inner_text()
            button_labels = await page.eval_on_selector_all(
                "button",
                "els => els.slice(0, 60).map(e => (e.innerText || '').trim().slice(0, 60)).filter(Boolean)",
            )
            sample_offer_row = await page.evaluate(
                r"""
                () => {
                  const priceRe = /€\s?\d/;
                  const all = Array.from(document.querySelectorAll('body *'));
                  const priceEl = all.find(el => {
                    const own = Array.from(el.childNodes)
                      .filter(n => n.nodeType === 3)
                      .map(n => n.textContent).join('');
                    return priceRe.test(own) && own.trim().length < 30;
                  });
                  if (!priceEl) return { found: false };
                  const chain = [];
                  let node = priceEl;
                  for (let i = 0; i < 8 && node; i++) {
                    chain.push({ tag: node.tagName, className: (node.className || '').toString(), id: node.id || null });
                    node = node.parentElement;
                  }
                  let ancestor = priceEl;
                  for (let i = 0; i < 8; i++) {
                    const t = ancestor.textContent || '';
                    if (t.includes('Details anzeigen') || t.includes('Summe')) break;
                    if (!ancestor.parentElement) break;
                    ancestor = ancestor.parentElement;
                  }
                  return {
                    found: true,
                    priceElTag: priceEl.tagName,
                    priceElText: (priceEl.textContent || '').trim(),
                    chain,
                    ancestorClassName: (ancestor.className || '').toString(),
                    ancestorHref: ancestor.tagName === 'A' ? ancestor.href : (ancestor.querySelector('a[href]')?.href || null),
                    ancestorHtml: ancestor.outerHTML.slice(0, 6000),
                  };
                }
                """
            )

    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        await context.close()

    return FetchResult(
        page_url=page_url,
        candidates=candidates,
        screenshot_path=screenshot_path if screenshot_path and error is None else None,
        error=error,
        page_text=page_text,
        button_labels=button_labels,
        sample_offer_row=sample_offer_row,
    )
