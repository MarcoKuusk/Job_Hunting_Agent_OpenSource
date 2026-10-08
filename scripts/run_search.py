"""Run a job search: fetch, score, log matches.

Examples:
    python scripts/run_search.py                # full run (writes to your sheet)
    python scripts/run_search.py --dry-run      # do everything EXCEPT writing
    python scripts/run_search.py --no-score     # just fetch & count (no Claude)
    python scripts/run_search.py --limit 5      # only score the first 5 (cheap test)

A good first test is:   python scripts/run_search.py --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a job search.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Do everything except writing to the sheet/cache/Telegram.")
    parser.add_argument("--no-score", action="store_true",
                        help="Fetch and filter only; skip Claude scoring.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only score the first N new jobs (cheap test).")
    args = parser.parse_args()

    from src.config import load_config, scrub
    from src.pipeline import run_search

    try:
        config = load_config()
    except Exception as exc:
        print("Could not load configuration: " + scrub(str(exc)))
        return 1

    print("Fetching jobs from enabled sources …")
    try:
        result = run_search(
            config,
            dry_run=args.dry_run,
            no_score=args.no_score,
            limit=args.limit,
        )
    except Exception as exc:
        print("Search failed: " + scrub(str(exc)))
        return 1

    # --- Summary ---
    print("\n" + "=" * 50)
    print("Run summary")
    print("=" * 50)
    print(f"Fetched (raw):        {result.fetched}")
    print(f"After keyword filter: {result.after_filter}")
    print(f"New (not seen before):{result.new_jobs}")
    if not result.scored_disabled:
        print(f"Scored:               {result.scored}")
        print(f"Matches (>= {result.min_score}):      {len(result.matches)}")
        print(f"Below the threshold:  {result.below_threshold}")
        if result.unscored:
            print(f"Scoring failed:       {result.unscored}")
        if not result.dry_run:
            print(f"Saved to the app:     {result.saved}")
            print(f"Written to sheet:     {result.logged}")

    if result.errors:
        print("\nSource issues:")
        for err in result.errors:
            print("  - " + err)

    if result.matches:
        print("\nTop matches:")
        for job in result.matches[:10]:
            print(f"  [{job.score}] {job.title} — {job.company}")
            print(f"        {job.url}")
            if job.reasons:
                print(f"        {job.reasons}")

    if result.dry_run:
        print("\n(Dry run — nothing was saved.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
