"""Push notifications via ntfy.sh (no account needed -- see README)."""

from __future__ import annotations

import urllib.error
import urllib.request


def send_ntfy(
    topic: str,
    *,
    title: str,
    message: str,
    url: str | None = None,
    priority: str = "default",
    tags: str | None = None,
) -> None:
    endpoint = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if url:
        headers["Click"] = url
    if tags:
        headers["Tags"] = tags

    req = urllib.request.Request(
        endpoint,
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to send ntfy notification: {e}") from e
