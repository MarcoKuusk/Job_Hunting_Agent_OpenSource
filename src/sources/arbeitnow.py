"""Arbeitnow — https://www.arbeitnow.com/api/job-board-api

JSON with a top-level "data" array. Paginated via ?page=N. Each job has:
title, company_name, description (HTML), tags, job_types, location, remote
(bool), url, slug, created_at (unix timestamp).
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Job
from .base import JobSource, http_get

API_URL = "https://www.arbeitnow.com/api/job-board-api"


def normalize(item: dict[str, Any]) -> Optional[Job]:
    title = (item.get("title") or "").strip()
    company = (item.get("company_name") or "").strip()
    if not title and not company:
        return None

    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    location = (item.get("location") or "").strip()
    if item.get("remote"):
        location = (location + " (remote)").strip() if location else "Remote"

    return Job(
        source="arbeitnow",
        title=title,
        company=company,
        url=(item.get("url") or "").strip(),
        description=item.get("description") or "",
        location=location,
        tags=[str(t) for t in tags],
        date_posted=str(item.get("created_at") or ""),
    )


class ArbeitnowSource(JobSource):
    name = "arbeitnow"

    def __init__(self, config, max_pages: int = 2) -> None:
        super().__init__(config)
        self.max_pages = max_pages

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, self.max_pages + 1):
            resp = http_get(API_URL, params={"page": page})
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            if not items:
                break
            for item in items:
                if isinstance(item, dict):
                    job = normalize(item)
                    if job:
                        jobs.append(job)
        return jobs
