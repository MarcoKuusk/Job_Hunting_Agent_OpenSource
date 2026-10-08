"""RemoteOK — https://remoteok.com/api

Returns a JSON array. The FIRST element is a legal/metadata object, not a job,
so we skip it. Requires a User-Agent header (handled by base.http_get).
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Job
from .base import JobSource, http_get

API_URL = "https://remoteok.com/api"


def normalize(item: dict[str, Any]) -> Optional[Job]:
    """Turn one RemoteOK item into a Job (or None if it's not a job)."""
    # The metadata element has a "legal" key and no position/company.
    if "legal" in item:
        return None
    title = (item.get("position") or item.get("title") or "").strip()
    company = (item.get("company") or "").strip()
    if not title and not company:
        return None

    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    salary = ""
    smin, smax = item.get("salary_min"), item.get("salary_max")
    if smin or smax:
        salary = f"{smin or '?'}–{smax or '?'}"

    return Job(
        source="remoteok",
        title=title,
        company=company,
        url=(item.get("url") or item.get("apply_url") or "").strip(),
        description=item.get("description") or "",
        location=(item.get("location") or "Remote").strip(),
        tags=[str(t) for t in tags],
        salary=salary,
        date_posted=str(item.get("date") or ""),
    )


class RemoteOKSource(JobSource):
    name = "remoteok"

    def fetch(self) -> list[Job]:
        resp = http_get(API_URL)
        data = resp.json()
        jobs: list[Job] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            job = normalize(item)
            if job:
                jobs.append(job)
        return jobs
