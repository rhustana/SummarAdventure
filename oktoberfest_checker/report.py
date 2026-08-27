"""Renders a list of TentResult into a static HTML report."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .checker import TentResult
from .classify import Status

STATUS_META = {
    Status.AVAILABLE: ("Available", "#1a7f37", "#eafbf1"),
    Status.LIKELY_FULL: ("Likely full", "#8a1f1f", "#fdecec"),
    Status.FORM_ONLY: ("Request-only form", "#8a6d1f", "#fdf6e3"),
    Status.NEEDS_REVIEW: ("Needs manual review", "#555", "#f1f1f1"),
    Status.BLOCKED: ("Blocked by site", "#8a1f1f", "#fdecec"),
    Status.ERROR: ("Error checking", "#8a1f1f", "#fdecec"),
}

STATUS_ORDER = [
    Status.AVAILABLE,
    Status.NEEDS_REVIEW,
    Status.FORM_ONLY,
    Status.LIKELY_FULL,
    Status.BLOCKED,
    Status.ERROR,
]


def _card(result: TentResult, screenshot_rel: str | None) -> str:
    label, fg, bg = STATUS_META[result.status]
    tent = result.tent
    evidence = html.escape(result.evidence) if result.evidence else "no specific signal found"
    notes = f'<p class="notes">Note: {html.escape(tent.notes)}</p>' if tent.notes else ""
    img = (
        f'<a href="{html.escape(screenshot_rel)}" target="_blank">'
        f'<img src="{html.escape(screenshot_rel)}" loading="lazy" alt="Screenshot of {html.escape(tent.name)}"></a>'
        if screenshot_rel
        else '<div class="no-shot">no screenshot</div>'
    )
    return f"""
    <div class="card">
      <div class="card-shot">{img}</div>
      <div class="card-body">
        <div class="card-head">
          <h3>{html.escape(tent.name)}</h3>
          <span class="badge" style="color:{fg};background:{bg}">{label}</span>
        </div>
        <p class="url"><a href="{html.escape(tent.url)}" target="_blank">{html.escape(tent.url)}</a></p>
        <p class="evidence">{evidence}</p>
        {notes}
      </div>
    </div>
    """


def render_report(
    results: list[TentResult],
    target_date: dt.date,
    output_path: Path,
    screenshot_dir_name: str = "screenshots",
) -> None:
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    by_status: dict[Status, list[TentResult]] = {s: [] for s in STATUS_ORDER}
    for r in results:
        by_status[r.status].append(r)

    sections = []
    for status in STATUS_ORDER:
        group = by_status[status]
        if not group:
            continue
        label = STATUS_META[status][0]
        cards = "\n".join(
            _card(
                r,
                f"{screenshot_dir_name}/{Path(r.screenshot_path).name}" if r.screenshot_path else None,
            )
            for r in sorted(group, key=lambda r: r.tent.name)
        )
        sections.append(f'<section><h2>{html.escape(label)} ({len(group)})</h2><div class="grid">{cards}</div></section>')

    body = "\n".join(sections)

    out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Oktoberfest tent availability -- {target_date.isoformat()}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 2rem;
         background: #fafafa; color: #1a1a1a; }}
  header {{ margin-bottom: 2rem; }}
  header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
  header p {{ margin: 0.15rem 0; color: #555; }}
  section {{ margin-bottom: 2.5rem; }}
  section h2 {{ font-size: 1.1rem; border-bottom: 2px solid #ddd; padding-bottom: 0.4rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; margin-top: 1rem; }}
  .card {{ background: white; border: 1px solid #e2e2e2; border-radius: 10px; overflow: hidden;
          display: flex; flex-direction: column; }}
  .card-shot img {{ width: 100%; display: block; aspect-ratio: 16/10; object-fit: cover; object-position: top; }}
  .no-shot {{ aspect-ratio: 16/10; display:flex; align-items:center; justify-content:center; color:#999; background:#f2f2f2; font-size: 0.85rem; }}
  .card-body {{ padding: 0.85rem 1rem 1rem; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: start; gap: 0.5rem; }}
  .card-head h3 {{ margin: 0; font-size: 1rem; }}
  .badge {{ font-size: 0.72rem; font-weight: 600; padding: 0.2rem 0.55rem; border-radius: 999px; white-space: nowrap; }}
  .url {{ font-size: 0.78rem; margin: 0.4rem 0; word-break: break-all; }}
  .url a {{ color: #555; }}
  .evidence {{ font-size: 0.85rem; color: #333; margin: 0.4rem 0 0; }}
  .notes {{ font-size: 0.78rem; color: #a06a00; margin: 0.4rem 0 0; }}
  footer {{ color: #888; font-size: 0.8rem; margin-top: 3rem; }}
</style>
</head>
<body>
<header>
  <h1>Oktoberfest tent table availability</h1>
  <p>Target date: <strong>{target_date.strftime("%A, %B %d, %Y")}</strong></p>
  <p>Generated {generated_at}</p>
  <p style="max-width:60ch">These statuses come from automated keyword/heuristic checks of each
  site's rendered page -- not a guaranteed real-time booking API. Treat "Available" and
  "Likely full" as leads to verify yourself, and open the screenshot before relying on either.</p>
</header>
{body}
<footer>Generated by the Oktoberfest tent checker tool.</footer>
</body>
</html>
"""
    output_path.write_text(out, encoding="utf-8")
