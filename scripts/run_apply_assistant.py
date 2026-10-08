"""Application assistant: pick a logged job, draft documents, then — only after
you explicitly approve — open its application page in your browser.

============================  SAFETY CONTRACT  ============================
This tool helps you PREPARE applications. It must NEVER:
  * submit an application form,
  * send an email or message on your behalf,
  * open the application page without you typing "approve" first.

The human-approval gate below (look for "HUMAN APPROVAL GATE") is mandatory.
Do not remove or weaken it. The only outward action this script can take is
`webbrowser.open(url)` AFTER you approve — which just opens the page so YOU can
review and submit it yourself.
==========================================================================
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.config import load_config, scrub
    from src.models import Job

    try:
        config = load_config()
    except Exception as exc:
        print("Could not load configuration: " + scrub(str(exc)))
        return 1

    # --- Load the jobs you've logged ---
    try:
        from src.sheets import read_logged_jobs

        rows = read_logged_jobs(config)
    except Exception as exc:
        print("Could not read your Google Sheet: " + scrub(str(exc)))
        return 1

    if not rows:
        print("No jobs logged yet. Run scripts/run_search.py first.")
        return 0

    # Prefer jobs still marked "New"; fall back to showing everything.
    candidates = [r for r in rows if str(r.get("Status", "")).strip().lower() == "new"]
    if not candidates:
        candidates = rows
        print("(No 'New' jobs — showing all logged jobs.)")

    # Sort by score, highest first.
    def _score(r):
        try:
            return int(r.get("Score") or 0)
        except (TypeError, ValueError):
            return 0

    candidates.sort(key=_score, reverse=True)

    print("\nLogged jobs:\n" + "-" * 60)
    for i, r in enumerate(candidates, 1):
        print(f"{i:>3}. [{r.get('Score', '?')}] {r.get('Title', '')} — "
              f"{r.get('Company', '')}  ({r.get('Status', '')})")
    print("-" * 60)

    # --- Pick one ---
    choice = input("\nEnter a number to prepare an application (or 'q' to quit): ").strip()
    if choice.lower() in ("q", "quit", "exit", ""):
        print("Cancelled.")
        return 0
    try:
        idx = int(choice)
        row = candidates[idx - 1]
    except (ValueError, IndexError):
        print("That wasn't a valid number from the list.")
        return 1

    # Prefer the full posting cached during the search (it still has the job
    # description); fall back to the sheet row, which is only a summary.
    from src.jobstore import get_job

    job = get_job(str(row.get("URL", "")))
    if job is None:
        job = Job(
            source=str(row.get("Source", "")),
            title=str(row.get("Title", "")),
            company=str(row.get("Company", "")),
            url=str(row.get("URL", "")),
            location=str(row.get("Location", "")),
            reasons=str(row.get("Reasons", "")),
        )

    print(f"\nSelected: {job.title} — {job.company}")
    print(f"URL: {job.url}")

    # --- Draft documents ---
    try:
        from src.cv import load_cv_text
        from src.documents import draft_for_job

        cv_text = load_cv_text(config.cv_path)
        print("\nWriting your cover letter and tailoring your CV with Claude … (a moment)")
        paths = draft_for_job(job, cv_text, config.profile, config.drafting_model())
    except Exception as exc:
        print("Drafting failed: " + scrub(str(exc)))
        return 1

    print("\nDrafts saved (review and edit them — they are starting points):")
    for label, key in (("Cover letter (Word)", "cover_letter_docx"),
                       ("Tailored CV (Word)", "tailored_cv_docx"),
                       ("Cover letter (text)", "cover_letter"),
                       ("Tailored CV (text)", "tailored_cv"),
                       ("What changed", "cv_notes")):
        if key in paths:
            print(f"  {label + ':':<22}{paths[key]}")

    # =================  HUMAN APPROVAL GATE  =================
    # Nothing outward-facing happens above this point. The browser only opens
    # if you type exactly "approve". Do not weaken this check.
    if not job.url:
        print("\nThis job has no application URL on file; nothing to open.")
        return 0

    print("\nWhen you're ready, I can open the application page in your browser")
    print("so YOU can review and submit it yourself. I will not submit anything.")
    approval = input('Type "approve" to open the page (anything else cancels): ').strip().lower()
    if approval != "approve":
        print("Not approved — the page was not opened. Your drafts are saved.")
        return 0

    webbrowser.open(job.url)
    print("Opened the application page. Review your drafts and submit it yourself.")
    # =========================================================

    # Optional, user-confirmed bookkeeping only. This does NOT apply anything.
    mark = input('If YOU have submitted it, type "yes" to mark it Applied in the '
                 'sheet (anything else leaves it unchanged): ').strip().lower()
    if mark == "yes":
        try:
            from src.sheets import update_status

            if update_status(config, job.url, "Applied"):
                print("Marked as Applied in your sheet.")
            else:
                print("Could not find that row to update (left unchanged).")
        except Exception as exc:
            print("Could not update the sheet: " + scrub(str(exc)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
