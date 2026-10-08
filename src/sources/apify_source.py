"""LinkedIn & Upwork via Apify actors.

IMPORTANT — we deliberately go through Apify actors and NEVER do logged-in
scraping or browser automation against LinkedIn or Upwork ourselves, to stay
within their terms of service. Do not replace this with direct scraping.

Apify actors each define their own Input schema, so the field names below in
`build_input()` are EDUCATED GUESSES based on common actors. After you pick an
actor on apify.com, open its "Input" tab and make the keys here match exactly
(this is Step 5 of the README). The `normalize()` function already tolerates a
wide range of OUTPUT field names, so usually only `build_input()` needs edits.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Job
from .base import JobSource


def build_input(platform: str, search_terms: list[str],
                results_per_actor: int,
                apify_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the `run input` dict passed to the Apify actor.

    >>> EDIT THIS to match your chosen actor's Input tab. <<<
    Different actors name the same concept differently — the alternatives seen
    in the wild are listed in the comments next to each field. `apify_cfg` is
    the `apify:` block of config/search.yaml, so region / recency / work type
    can be tuned there without editing code.
    """
    terms = [t for t in search_terms if t]
    query = " ".join(terms)
    cfg = apify_cfg or {}

    if platform == "linkedin":
        # Reconciled to the cheap_scraper/linkedin-job-scraper input schema.
        # Its Input tab uses `keyword` (array) + `locations` (array) +
        # `maxItems` + `workType`. Region, work type and recency are read from
        # config/search.yaml (apify.locations / apify.work_type /
        # apify.published_at) so you can tune them without touching this file.
        # NOTE: this actor bills per result — `maxItems` is an upper bound, and
        # a narrower `published_at` (e.g. last 24h) is the cheapest way to run.
        run_input: dict[str, Any] = {
            "keyword": terms,                            # array of search terms
            "locations": cfg.get("locations") or ["Europe", "USA"],
            "maxItems": results_per_actor,
            "workType": cfg.get("work_type") or ["remote"],
            "saveOnlyUniqueItems": True,                 # dedupe by LinkedIn job id
        }
        # Recency filter: "r86400" = last 24h, "r604800" = last 7 days.
        published_at = cfg.get("published_at")
        if published_at:
            run_input["publishedAt"] = published_at
        return run_input

    if platform == "upwork":
        return {
            # Search text. Other actors: "query", "keywords", "search".
            "searchQuery": query,
            # How many results. Other actors: "limit", "rows", "maxResults".
            "maxItems": results_per_actor,
        }

    # Fallback for any other platform.
    return {"query": query, "maxItems": results_per_actor}


def _first(item: dict[str, Any], keys: list[str], default: str = "") -> str:
    """Return the first non-empty value among several possible keys."""
    for k in keys:
        v = item.get(k)
        if v:
            return str(v)
    return default


def normalize(item: dict[str, Any], platform: str) -> Optional[Job]:
    """Map an actor's output item to a Job, tolerating many field names."""
    title = _first(item, ["title", "jobTitle", "position", "name", "headline"])
    company = _first(item, [
        "company", "companyName", "company_name", "employer",
        "client", "clientName", "organization",
    ])
    if not title and not company:
        return None

    url = _first(item, [
        "url", "jobUrl", "job_url", "link", "applyUrl", "applyLink",
        "detailsUrl", "ciphertext",
    ])
    description = _first(item, [
        "description", "descriptionHtml", "descriptionText",
        "jobDescription", "snippet", "summary",
    ])
    location = _first(item, [
        "location", "jobLocation", "place", "country", "region",
    ], "Remote")
    salary = _first(item, [
        "salary", "salaryInfo", "budget", "payRate", "compensation", "rate",
    ])

    tags_raw = item.get("skills") or item.get("tags") or []
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

    return Job(
        source=platform,
        title=title,
        company=company,
        url=url,
        description=description,
        location=location,
        tags=tags,
        salary=salary,
        date_posted=_first(item, ["postedDate", "publishedAt", "datePosted", "postedAt"]),
    )


class ApifySource(JobSource):
    """Runs one Apify actor (for LinkedIn or Upwork) and normalizes results."""

    def __init__(self, config, platform: str, actor_id: str) -> None:
        super().__init__(config)
        self.platform = platform
        self.name = platform
        self.actor_id = actor_id

    def fetch(self) -> list[Job]:
        # We call Apify's REST API directly with `requests` rather than the
        # apify-client SDK. The SDK pulls in a native HTTP library (impit) whose
        # DLL is blocked by some Windows Application Control policies; plain
        # requests avoids that and needs no extra dependency. This still runs
        # the actor on Apify — no local scraping.
        import requests

        token = self.config.apify_token
        if not token:
            raise RuntimeError(
                "APIFY_API_TOKEN is not set in .env, but an Apify source is enabled."
            )
        if not self.actor_id:
            raise RuntimeError(
                f"No Apify actor id configured for '{self.platform}'. "
                f"Set it in config/search.yaml under apify."
            )

        apify_cfg = self.config.apify()
        search_terms = [t for t in (apify_cfg.get("search_terms") or []) if t]
        results = int(apify_cfg.get("results_per_actor", 25))
        run_input = build_input(self.platform, search_terms, results, apify_cfg)

        # In Apify REST URLs the actor id uses '~' instead of '/'.
        actor_path = self.actor_id.replace("/", "~")

        # Cost saver: if the last successful run finished recently enough, reuse
        # its dataset for free instead of paying for a fresh run. `0` (or
        # missing) disables reuse and always runs fresh.
        reuse_hours = float(apify_cfg.get("reuse_within_hours", 0) or 0)
        if reuse_hours > 0:
            items = self._reuse_last_run(requests, token, actor_path, reuse_hours)
            if items is not None:
                return self._items_to_jobs(items)

        # run-sync waits for the actor to finish and returns dataset items
        # directly. Apify caps synchronous runs at ~5 minutes.
        url = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
        resp = requests.post(
            url, params={"token": token}, json=run_input, timeout=300
        )
        resp.raise_for_status()
        return self._items_to_jobs(resp.json())

    def _reuse_last_run(self, requests, token: str, actor_path: str,
                        reuse_hours: float):
        """Return dataset items from the actor's last SUCCEEDED run if it
        finished within `reuse_hours`, else None (caller then runs fresh).

        Any error here just falls back to a fresh run — reuse is best-effort.
        """
        from datetime import datetime, timezone

        try:
            run = requests.get(
                f"https://api.apify.com/v2/acts/{actor_path}/runs/last",
                params={"token": token, "status": "SUCCEEDED"}, timeout=30,
            )
            if run.status_code != 200:
                return None
            data = (run.json() or {}).get("data") or {}
            finished = data.get("finishedAt")
            dataset_id = data.get("defaultDatasetId")
            if not finished or not dataset_id:
                return None
            # finishedAt looks like "2026-07-12T11:00:00.000Z".
            fin = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - fin).total_seconds() / 3600
            if age_hours > reuse_hours:
                return None
            ds = requests.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                params={"token": token, "clean": "true", "format": "json"},
                timeout=120,
            )
            if ds.status_code != 200:
                return None
            return ds.json()
        except Exception:  # noqa: BLE001 — never let reuse break the run
            return None

    def _items_to_jobs(self, items: Any) -> list[Job]:
        jobs: list[Job] = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                job = normalize(item, self.platform)
                if job:
                    jobs.append(job)
        return jobs
