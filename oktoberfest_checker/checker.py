"""Runs the availability check across all configured tents."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser

from .browser import snapshot_page
from .classify import ClassificationResult, Status, classify_page
from .config import Tent


@dataclass
class TentResult:
    tent: Tent
    status: Status
    evidence: str | None
    final_url: str | None
    screenshot_path: str | None
    checked_at: dt.datetime


async def _check_one(
    browser: Browser,
    tent: Tent,
    target_date: dt.date,
    screenshot_dir: Path | None,
    timeout_ms: int,
    retries: int,
) -> TentResult:
    screenshot_path = (
        str(screenshot_dir / f"{tent.id}.png") if screenshot_dir else None
    )

    last_snapshot = None
    for attempt in range(retries + 1):
        last_snapshot = await snapshot_page(
            browser, tent.url, screenshot_path=screenshot_path, timeout_ms=timeout_ms
        )
        if not last_snapshot.navigation_error:
            break
        if attempt < retries:
            await asyncio.sleep(2 * (attempt + 1))

    result: ClassificationResult = classify_page(
        visible_text=last_snapshot.visible_text,
        html=last_snapshot.html,
        target_date=target_date,
        http_status=last_snapshot.http_status,
        navigation_error=last_snapshot.navigation_error,
    )

    return TentResult(
        tent=tent,
        status=result.status,
        evidence=result.evidence,
        final_url=last_snapshot.final_url,
        screenshot_path=last_snapshot.screenshot_path,
        checked_at=dt.datetime.now(dt.timezone.utc),
    )


async def check_all(
    browser: Browser,
    tents: list[Tent],
    target_date: dt.date,
    *,
    screenshot_dir: Path | None,
    concurrency: int = 4,
    timeout_ms: int = 30_000,
    retries: int = 1,
) -> list[TentResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bound_check(tent: Tent) -> TentResult:
        async with semaphore:
            return await _check_one(
                browser, tent, target_date, screenshot_dir, timeout_ms, retries
            )

    return await asyncio.gather(*(bound_check(t) for t in tents))
