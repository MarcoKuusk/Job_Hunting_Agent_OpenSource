"""Shared pieces for all job sources.

`JobSource` is the common interface; `http_get` is a small wrapper around
requests that sets a browser-like User-Agent (some boards, e.g. RemoteOK,
reject requests without one) and a sane timeout.
"""

from __future__ import annotations

from typing import Any

# A polite, browser-like User-Agent. RemoteOK in particular returns 403 to
# requests that don't send one.
USER_AGENT = (
    "Mozilla/5.0 (compatible; JobHuntingAgent/1.0; personal job search)"
)

DEFAULT_TIMEOUT = 45


class JobSource:
    """Base class. Subclasses set `name` and implement `fetch()`."""

    name: str = "base"

    def __init__(self, config) -> None:
        self.config = config

    def fetch(self) -> list:
        raise NotImplementedError


def http_get(url: str, *, params: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None,
             timeout: int = DEFAULT_TIMEOUT):
    """GET a URL with a default User-Agent. Imports requests lazily."""
    import requests

    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    resp = requests.get(url, params=params, headers=merged, timeout=timeout)
    resp.raise_for_status()
    return resp


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """True if `text` contains any of the keywords (case-insensitive).

    An empty keyword list means "no filter" -> everything matches.
    """
    if not keywords:
        return True
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords if k)


def has_excluded(text: str, exclude: list[str]) -> bool:
    """True if `text` contains any excluded term (case-insensitive)."""
    if not exclude:
        return False
    low = (text or "").lower()
    return any(k.lower() in low for k in exclude if k)
