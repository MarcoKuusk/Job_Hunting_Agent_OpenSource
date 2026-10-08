"""We Work Remotely — RSS feed (https://weworkremotely.com/remote-jobs.rss)

RSS, parsed with feedparser. Each <item> title is "Company: Position", so we
split on the first colon. Description is HTML.
"""

from __future__ import annotations

from typing import Optional

from ..models import Job
from .base import JobSource, USER_AGENT

FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


def split_title(raw_title: str) -> tuple[str, str]:
    """Split 'Company: Position' into (company, position).

    If there's no colon, the whole thing is treated as the position and the
    company is left blank.
    """
    raw_title = (raw_title or "").strip()
    if ":" in raw_title:
        company, _, position = raw_title.partition(":")
        return company.strip(), position.strip()
    return "", raw_title


def normalize(entry) -> Optional[Job]:
    """Turn one feedparser entry (or dict-like) into a Job."""
    raw_title = entry.get("title", "") if hasattr(entry, "get") else ""
    company, position = split_title(raw_title)
    if not position and not company:
        return None

    # feedparser exposes tags as objects with a `.term`; fall back gracefully.
    tags: list[str] = []
    for t in entry.get("tags", []) or []:
        term = t.get("term") if hasattr(t, "get") else getattr(t, "term", None)
        if term:
            tags.append(str(term))

    region = entry.get("region", "") if hasattr(entry, "get") else ""

    return Job(
        source="weworkremotely",
        title=position,
        company=company,
        url=(entry.get("link", "") or "").strip(),
        description=entry.get("summary", "") or entry.get("description", "") or "",
        location=(region or "Remote").strip(),
        tags=tags,
        date_posted=entry.get("published", "") or "",
    )


class WeWorkRemotelySource(JobSource):
    name = "weworkremotely"

    def fetch(self) -> list[Job]:
        import feedparser

        parsed = feedparser.parse(FEED_URL, request_headers={"User-Agent": USER_AGENT})
        jobs: list[Job] = []
        for entry in parsed.entries:
            job = normalize(entry)
            if job:
                jobs.append(job)
        return jobs
