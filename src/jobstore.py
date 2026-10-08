"""Keeps the FULL details of every job we score, so the apply step can draft
from the real posting rather than just its title.

The Google Sheet holds a summary row (title, company, score, url) — a job
description is far too long for a spreadsheet cell to stay readable. But a
cover letter written from a title alone is generic and useless, so every run
also stashes the complete Job record here, keyed by URL.

Every job that got a score is stored, not just the good ones: they were all
paid for, and the web UI browses them so the user can look past the shortlist.

Pure stdlib, same idea as dedupe.py: a small JSON file in data/ (gitignored).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .models import Job

STORE_PATH = PROJECT_ROOT / "data" / "jobs.json"

# Roughly two weeks of daily runs now that every scored job is kept (a run adds
# up to max_jobs_per_source per board). Postings expire off the boards long
# before this matters.
MAX_JOBS = 3000
# Descriptions can be enormous on some boards. This is plenty for drafting.
MAX_DESCRIPTION_CHARS = 12000

# Statuses that mean the user has engaged with a job. Those are never evicted
# to make room for a fresh batch of long shots.
_ENGAGED_EXCLUDED = {"", "new"}


def _key(url: str) -> str:
    return (url or "").strip().lower()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "source": job.source,
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "description": (job.description or "")[:MAX_DESCRIPTION_CHARS],
        "location": job.location,
        "tags": list(job.tags or []),
        "salary": job.salary,
        "date_posted": job.date_posted,
        "score": job.score,
        "recommendation": job.recommendation,
        "reasons": job.reasons,
    }


def job_from_dict(data: dict[str, Any]) -> Job:
    """Rebuild a Job from a stored record (unknown keys are ignored)."""
    return Job(
        source=str(data.get("source", "")),
        title=str(data.get("title", "")),
        company=str(data.get("company", "")),
        url=str(data.get("url", "")),
        description=str(data.get("description", "")),
        location=str(data.get("location", "")),
        tags=list(data.get("tags") or []),
        salary=str(data.get("salary", "")),
        date_posted=str(data.get("date_posted", "")),
        score=data.get("score"),
        recommendation=str(data.get("recommendation", "")),
        reasons=str(data.get("reasons", "")),
    )


# The store is read on every draft and on every matches refresh, and it is now
# large enough that re-parsing it each time is noticeable. Cache it against the
# file's mtime+size so a write from another process (the CLI) is still picked up.
_CACHE: tuple[str, float, int, dict[str, dict[str, Any]]] | None = None


def load_store(path: Path = STORE_PATH) -> dict[str, dict[str, Any]]:
    global _CACHE
    try:
        stat = path.stat()
    except OSError:
        return {}

    cached = _CACHE
    if (cached is not None and cached[0] == str(path)
            and cached[1] == stat.st_mtime and cached[2] == stat.st_size):
        return cached[3]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        jobs = data.get("jobs", {})
        jobs = jobs if isinstance(jobs, dict) else {}
    except (json.JSONDecodeError, OSError):
        # A corrupt cache must never break a run — start fresh.
        return {}

    _CACHE = (str(path), stat.st_mtime, stat.st_size, jobs)
    return jobs


def _evict_rank(record: dict[str, Any]) -> tuple[int, int, str]:
    """Sort key for trimming: the smallest goes first.

    Anything the user engaged with outranks everything else, then higher scores,
    then newer finds. Plain insertion order would throw away an 92-point match
    from last week to make room for this morning's long shots.
    """
    status = str(record.get("status") or "New").strip().lower()
    engaged = 0 if status in _ENGAGED_EXCLUDED else 1
    score = record.get("score")
    score = score if isinstance(score, int) else -1
    return (engaged, score, str(record.get("date_found") or ""))


def save_jobs(jobs: list[Job], path: Path = STORE_PATH, *,
              date_found: str | None = None) -> int:
    """Merge these jobs into the store (newest wins) and write it out.

    Returns the number of records written. `date_found` is stamped once per URL
    and preserved on later saves, so a job keeps the date we first saw it.
    """
    global _CACHE
    store = dict(load_store(path))
    stamp = date_found or _today()

    written = 0
    for job in jobs:
        key = _key(job.url)
        if not key:
            continue
        previous = store.get(key) or {}
        record = _job_to_dict(job)
        record["date_found"] = previous.get("date_found") or stamp
        record["status"] = previous.get("status") or "New"
        store[key] = record
        written += 1

    if len(store) > MAX_JOBS:
        ranked = sorted(store.items(), key=lambda kv: _evict_rank(kv[1]))
        for old_key, _ in ranked[: len(store) - MAX_JOBS]:
            store.pop(old_key, None)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"jobs": store}, f, indent=2, ensure_ascii=False)
    _CACHE = None
    return written


def set_status(url: str, status: str, path: Path = STORE_PATH) -> bool:
    """Record the stage a job has reached, so eviction keeps it. Returns True
    if the job was in the store."""
    global _CACHE
    key = _key(url)
    if not key:
        return False
    store = dict(load_store(path))
    record = store.get(key)
    if record is None:
        return False
    record = dict(record)
    record["status"] = status
    store[key] = record

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"jobs": store}, f, indent=2, ensure_ascii=False)
    _CACHE = None
    return True


def get_job(url: str, path: Path = STORE_PATH) -> Job | None:
    """Look up the full record for a job by URL, or None if we don't have it."""
    key = _key(url)
    if not key:
        return None
    record = load_store(path).get(key)
    return job_from_dict(record) if record else None
