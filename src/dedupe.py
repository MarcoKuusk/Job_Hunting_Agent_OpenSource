"""Remembers which jobs we've already seen, so we don't re-score or re-log the
same posting on every run. The cache is a JSON file in data/ (gitignored).
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import PROJECT_ROOT
from .models import Job

SEEN_PATH = PROJECT_ROOT / "data" / "seen.json"


def load_seen(path: Path = SEEN_PATH) -> set[str]:
    """Load the set of dedupe keys we've already processed."""
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("keys", []))
    except (json.JSONDecodeError, OSError):
        # A corrupt cache shouldn't stop a run — start fresh.
        return set()


def save_seen(seen: set[str], path: Path = SEEN_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"keys": sorted(seen)}, f, indent=2)


def filter_new(jobs: list[Job], seen: set[str]) -> list[Job]:
    """Return only the jobs whose dedupe key isn't already in `seen`.

    Checks two keys per job: the URL (the same posting seen again) and
    company+title (the same opening re-posted under a different URL — see
    `Job.content_key`). Also de-duplicates within this batch, since the same
    job can appear on more than one board.
    """
    new: list[Job] = []
    batch_keys: set[str] = set()
    for job in jobs:
        keys = [k for k in (job.dedupe_key(), job.content_key()) if k]
        if any(k in seen or k in batch_keys for k in keys):
            continue
        batch_keys.update(keys)
        new.append(job)
    return new


def mark_seen(seen: set[str], jobs: list[Job]) -> None:
    for job in jobs:
        seen.add(job.dedupe_key())
        content = job.content_key()
        if content:
            seen.add(content)
