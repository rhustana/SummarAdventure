"""Persisted 'have we already notified about this listing' tracking.

Stored as plain JSON so it can be committed back to the repo by the GitHub
Actions workflow between runs (Actions runners have no persistent disk of
their own).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def load_seen(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(path: Path, seen: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def mark_seen(seen: dict[str, dict], listing_id: str, text: str, url: str | None) -> None:
    seen[listing_id] = {
        "first_seen": dt.datetime.now(dt.timezone.utc).isoformat(),
        "text": text[:300],
        "url": url,
    }
