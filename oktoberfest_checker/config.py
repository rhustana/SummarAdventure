"""Loading and representing the list of tents to check."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Tent:
    id: str
    name: str
    url: str
    notes: str | None = None


def load_tents(path: Path, only: list[str] | None = None) -> list[Tent]:
    """Load tent definitions from a JSON config file.

    `only`, if given, restricts the result to tent ids in that list (used by
    --only for iterating on a handful of tents at a time).
    """
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    tents = [Tent(**entry) for entry in raw]

    if only:
        wanted = set(only)
        tents = [t for t in tents if t.id in wanted]
        missing = wanted - {t.id for t in tents}
        if missing:
            raise ValueError(f"Unknown tent id(s): {', '.join(sorted(missing))}")

    return tents
