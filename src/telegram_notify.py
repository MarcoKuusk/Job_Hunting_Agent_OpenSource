"""Optional Telegram run summary.

Sends a short message listing the top matches after a search. If Telegram isn't
configured or is disabled, this quietly does nothing — it never raises in a way
that would stop a search run.
"""

from __future__ import annotations

from .config import scrub
from .models import Job

API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"


def _format_summary(jobs: list[Job], total_matches: int, top_n: int) -> str:
    if not jobs:
        return "Job search ran: no new matches this time."
    lines = [f"🧭 Job search: {total_matches} new match(es). Top {min(top_n, len(jobs))}:"]
    for job in jobs[:top_n]:
        score = job.score if job.score is not None else "?"
        lines.append(f"• [{score}] {job.title} — {job.company}\n{job.url}")
    return "\n".join(lines)


def send_summary(config, jobs: list[Job], total_matches: int) -> bool:
    """Send a summary to Telegram. Returns True if a message was sent."""
    tg = config.telegram()
    if not tg.get("enabled"):
        return False

    token = config.telegram_token
    chat_id = config.telegram_chat_id
    if not token or not chat_id:
        return False

    top_n = int(tg.get("notify_top_n", 5))
    text = _format_summary(jobs, total_matches, top_n)

    try:
        import requests

        resp = requests.post(
            API_TEMPLATE.format(token=token),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — notifications are best-effort
        print("Telegram notification failed: " + scrub(str(exc)))
        return False
