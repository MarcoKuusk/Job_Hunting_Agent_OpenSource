"""Orchestrates one end-to-end search run.

    fetch from each enabled source
      -> filter by your keywords / exclude list
      -> drop jobs seen on previous runs
      -> score each with Claude
      -> (unless dry run) save every scored job locally and optionally sync Google,
         remember them, notify Telegram about the ones at/above min_score

min_score is not a gate: every job we paid to score is kept, and the threshold
only decides what counts as a "good match" (the Telegram summary, the sheet's
Dashboard, and the web UI's default filter).

Designed so that one failing source or one failing score doesn't abort the
whole run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .config import Config, scrub
from .cv import load_cv_text
from .dedupe import filter_new, load_seen, mark_seen, save_seen
from .models import Job
from .scoring import profile_to_text, score_job
from .sources.base import has_excluded, matches_keywords
from .sources.registry import build_sources

# How many jobs to score concurrently (see the scoring step in run_search).
SCORING_WORKERS = 6


@dataclass
class RunResult:
    fetched: int = 0
    after_filter: int = 0
    new_jobs: int = 0
    scored: int = 0
    matches: list[Job] = field(default_factory=list)   # at/above min_score
    below_threshold: int = 0   # scored, but under min_score (still saved)
    unscored: int = 0          # scoring failed; counted, not saved
    saved: int = 0             # records written to the local job store
    logged: int = 0            # rows appended to the Google Sheet
    min_score: int = 0         # the threshold this run used
    per_source: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
    scored_disabled: bool = False


# Boards occasionally emit rows that aren't real postings (a stray heading, an
# empty placeholder). They cost a scoring call and can never be applied to, so
# drop them before scoring.
def _is_postable(job: Job) -> bool:
    return bool(job.url) and len(job.title.strip()) >= 3


def _keep(job: Job, keywords: list[str], exclude: list[str]) -> bool:
    if not _is_postable(job):
        return False
    haystack = " ".join([job.title, job.company, job.location,
                         " ".join(job.tags), job.description])
    if has_excluded(haystack, exclude):
        return False
    return matches_keywords(haystack, keywords)


def run_search(config: Config, *, dry_run: bool = False, no_score: bool = False,
               limit: int | None = None,
               progress: Callable[[str], None] = print) -> RunResult:
    result = RunResult(dry_run=dry_run, scored_disabled=no_score)

    # 1) Fetch from each enabled source (isolate failures per source).
    sources = build_sources(config)
    if not sources:
        progress("No sources are enabled in config/search.yaml.")
    cap = config.max_jobs_per_source()
    all_jobs: list[Job] = []
    for source in sources:
        try:
            jobs = source.fetch()
            result.per_source[source.name] = len(jobs)
            all_jobs.extend(jobs)
            progress(f"  {source.name}: {len(jobs)} job(s)")
        except Exception as exc:  # noqa: BLE001
            msg = f"{source.name} failed: {scrub(str(exc))}"
            result.errors.append(msg)
            result.per_source[source.name] = 0
            progress("  " + msg)
    result.fetched = len(all_jobs)

    # 2) Keyword / exclude filtering (uses YOUR config values, unchanged).
    keywords = config.keywords()
    exclude = config.exclude_keywords()
    filtered = [j for j in all_jobs if _keep(j, keywords, exclude)]
    result.after_filter = len(filtered)

    # 3) Drop jobs seen on previous runs (and de-dupe within this batch).
    seen = load_seen()
    new_jobs = filter_new(filtered, seen)

    # Cap per source only AFTER keyword filtering AND dedupe, so the scoring
    # budget is spent on keyword-relevant jobs we haven't scored before.
    # (Capping the raw fetch keeps whatever the board listed first — usually
    # noise. Capping before dedupe fills the budget with already-seen postings,
    # which after a few runs leaves nothing new and returns zero matches.)
    if cap:
        capped: list[Job] = []
        kept_per_source: dict[str, int] = {}
        for j in new_jobs:
            n = kept_per_source.get(j.source, 0)
            if n < cap:
                capped.append(j)
                kept_per_source[j.source] = n + 1
        new_jobs = capped
    result.new_jobs = len(new_jobs)

    if limit is not None and limit >= 0:
        new_jobs = new_jobs[:limit]

    if no_score:
        progress(f"Scoring skipped (--no-score). {len(new_jobs)} new job(s) found.")
        return result

    # 4) Score each new job with Claude.
    from .scoring import build_client

    client = build_client()
    cv_text = load_cv_text(config.cv_path)
    profile_text = profile_to_text(config.profile)
    model = config.scoring_model()
    min_score = config.min_score()

    progress(f"Scoring {len(new_jobs)} job(s) with {model} …")
    # Score a few at a time — one run can be 200+ jobs and sequential calls make
    # the user wait ~15 minutes. score_job() never raises (it records the error
    # on the job), so a failure can't break the pool. Kept small to stay well
    # inside the API rate limits.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workers = min(SCORING_WORKERS, len(new_jobs)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(score_job, job, cv_text, profile_text, model, client=client)
            for job in new_jobs
        ]
        for future in as_completed(futures):
            future.result()
            result.scored += 1
            if result.scored % 10 == 0:
                progress(f"  scored {result.scored}/{len(new_jobs)}")

    # Everything that came back with a score, best first. Scoring failures
    # (score is None) are counted but not persisted: a blank-score row is
    # nothing the user can act on.
    loggable = [j for j in new_jobs if j.score is not None]
    loggable.sort(key=lambda j: j.score or 0, reverse=True)
    result.unscored = len(new_jobs) - len(loggable)

    matches = [j for j in loggable if (j.score or 0) >= min_score]
    result.matches = matches
    result.below_threshold = len(loggable) - len(matches)
    result.min_score = min_score

    # 5) Persist results (skipped on a dry run). The local store is the primary
    # database; Google Sheets is an optional sync for people who configure it.
    if not dry_run:
        from .jobstore import save_jobs

        date_found = datetime.now().strftime("%Y-%m-%d")
        if loggable:
            result.saved = save_jobs(loggable, date_found=date_found)
            progress(f"Saved {result.saved} job(s) on this computer.")

        if config.google_sheets_ready():
            from .sheets import append_jobs, build_dashboard

            if loggable:
                try:
                    result.logged = append_jobs(config, loggable, date_found)
                except Exception as exc:  # noqa: BLE001
                    result.errors.append("sheet write failed: " + scrub(str(exc)))
                    progress("  Google sync failed — your jobs are still saved locally.")
            try:
                progress("Updating your Google dashboard …")
                build_dashboard(config)
            except Exception as exc:  # noqa: BLE001
                result.errors.append("dashboard update failed: " + scrub(str(exc)))
        else:
            progress("Google Sheets is not connected; using local storage only.")
        # Remember everything we scored so we don't re-score it next time.
        mark_seen(seen, new_jobs)
        save_seen(seen)

        from .telegram_notify import send_summary

        send_summary(config, matches, len(matches))
    else:
        progress("Dry run: nothing saved locally, synced to Google, or sent to Telegram.")

    return result
