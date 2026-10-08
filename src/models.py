"""The normalized Job record.

Every source (RemoteOK, Arbeitnow, Remotive, We Work Remotely, Apify) converts
its own raw data into this single shape, so the rest of the program only ever
deals with one kind of object. Pure stdlib — safe to import without any
third-party packages installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass
class Job:
    # Where it came from and the core facts.
    source: str
    title: str
    company: str
    url: str
    description: str = ""
    location: str = ""
    tags: list[str] = field(default_factory=list)
    salary: str = ""
    date_posted: str = ""

    # Filled in later by the scoring step.
    score: Optional[int] = None
    recommendation: str = ""   # e.g. "strong", "maybe", "skip"
    reasons: str = ""

    def dedupe_key(self) -> str:
        """A stable identifier so the same job isn't scored/logged twice.

        The URL is the best key; if it's missing we fall back to a
        source+company+title combination.
        """
        url = (self.url or "").strip().lower()
        if url:
            return url
        return f"{self.source}|{self.company}|{self.title}".strip().lower()

    def content_key(self) -> str:
        """A second key that catches the SAME role posted under several URLs.

        Aggregators re-post one opening once per country (e.g. the same
        "Customer Success Manager at Jobgether" on es./it./fr./ie. LinkedIn,
        each with its own job id), so the URL key can't collapse them and the
        job shows up a dozen times. Matching on company + title does.

        Returns "" when either field is missing — too weak to dedupe on.
        """
        company = _NON_WORD.sub(" ", (self.company or "").lower()).strip()
        title = _NON_WORD.sub(" ", (self.title or "").lower()).strip()
        if not company or not title:
            return ""
        return f"role|{company}|{title}"

    def to_compact_text(self, max_description_chars: int = 1500) -> str:
        """A short text blob describing the job, for sending to the model.

        Imported lazily here to keep this module free of third-party deps.
        """
        from .textutil import strip_html, truncate

        parts = [
            f"Title: {self.title}",
            f"Company: {self.company}",
        ]
        if self.location:
            parts.append(f"Location: {self.location}")
        if self.salary:
            parts.append(f"Salary: {self.salary}")
        if self.tags:
            parts.append("Tags: " + ", ".join(self.tags))
        desc = truncate(strip_html(self.description), max_description_chars)
        if desc:
            parts.append("Description:\n" + desc)
        return "\n".join(parts)
