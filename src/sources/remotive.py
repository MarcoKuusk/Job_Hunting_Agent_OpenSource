"""Remotive — https://remotive.com/api/remote-jobs

JSON with a top-level "jobs" array. Supports ?search=TERM. Remotive asks
callers to fetch at most a few times per day (data is delayed ~24h), so we
issue one request per search term. Each job has: title, company_name,
category, job_type, candidate_required_location, salary, description (HTML),
url, tags, publication_date.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Job
from .base import JobSource, http_get

API_URL = "https://remotive.com/api/remote-jobs"


def normalize(item: dict[str, Any]) -> Optional[Job]:
    title = (item.get("title") or "").strip()
    company = (item.get("company_name") or "").strip()
    if not title and not company:
        return None

    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    return Job(
        source="remotive",
        title=title,
        company=company,
        url=(item.get("url") or "").strip(),
        description=item.get("description") or "",
        location=(item.get("candidate_required_location") or "Remote").strip(),
        tags=[str(t) for t in tags],
        salary=(item.get("salary") or "").strip(),
        date_posted=str(item.get("publication_date") or ""),
    )


class RemotiveSource(JobSource):
    name = "remotive"

    def __init__(self, config, search_terms: list[str] | None = None) -> None:
        super().__init__(config)
        self.search_terms = [t for t in (search_terms or []) if t]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        # One request per term, or a single unfiltered request if no terms.
        queries: list[dict[str, Any] | None] = (
            [{"search": t} for t in self.search_terms] if self.search_terms
            else [None]
        )
        for params in queries:
            resp = http_get(API_URL, params=params)
            data = resp.json()
            items = data.get("jobs", []) if isinstance(data, dict) else []
            for item in items:
                if isinstance(item, dict):
                    job = normalize(item)
                    if job:
                        jobs.append(job)
        return jobs
