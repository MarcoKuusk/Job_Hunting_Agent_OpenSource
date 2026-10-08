"""Offline tests for the "pick a job and everything is written for you" path
and for the dashboard layout. Like the other tests, these import only
stdlib-safe modules and never touch the network, Claude, or Google Sheets.

    python -m unittest discover -s tests
"""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import jobstore, sheets
from src.documents import _slug, _strip_code_fence
from src.jsonsafe import finite_only
from src.models import Job


def _reject_constant(name):
    """Stand in for a browser: JSON.parse has no NaN/Infinity literals."""
    raise ValueError(f"browsers reject the bare token {name}")


def _job(**kwargs) -> Job:
    base = dict(source="remotive", title="SEO Editor", company="Acme",
                url="https://example.com/jobs/1", description="Write copy.",
                location="EU remote")
    base.update(kwargs)
    return Job(**base)


class JobStoreTests(unittest.TestCase):
    """The store is what lets the apply step draft from the real posting
    rather than from the one-line summary in the spreadsheet."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "jobs.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_keeps_the_description(self):
        jobstore.save_jobs([_job(score=88, reasons="Strong SEO overlap")],
                           path=self.path)
        got = jobstore.get_job("https://example.com/jobs/1", path=self.path)
        self.assertIsNotNone(got)
        self.assertEqual(got.description, "Write copy.")
        self.assertEqual(got.company, "Acme")
        self.assertEqual(got.score, 88)

    def test_lookup_ignores_url_case_and_padding(self):
        jobstore.save_jobs([_job()], path=self.path)
        got = jobstore.get_job("  HTTPS://EXAMPLE.COM/jobs/1 ", path=self.path)
        self.assertIsNotNone(got)

    def test_unknown_and_empty_urls_return_none(self):
        jobstore.save_jobs([_job()], path=self.path)
        self.assertIsNone(jobstore.get_job("https://example.com/other",
                                           path=self.path))
        self.assertIsNone(jobstore.get_job("", path=self.path))

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(jobstore.load_store(path=self.path), {})
        self.assertIsNone(jobstore.get_job("https://example.com/jobs/1",
                                           path=self.path))

    def test_corrupt_file_starts_fresh(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(jobstore.load_store(path=self.path), {})

    def test_later_runs_merge_rather_than_replace(self):
        jobstore.save_jobs([_job()], path=self.path)
        jobstore.save_jobs([_job(url="https://example.com/jobs/2",
                                 title="Copywriter")], path=self.path)
        self.assertEqual(len(jobstore.load_store(path=self.path)), 2)

    def test_huge_descriptions_are_truncated(self):
        jobstore.save_jobs([_job(description="x" * 50000)], path=self.path)
        got = jobstore.get_job("https://example.com/jobs/1", path=self.path)
        self.assertEqual(len(got.description), jobstore.MAX_DESCRIPTION_CHARS)


class DocumentHelperTests(unittest.TestCase):
    def test_strips_a_wrapping_code_fence(self):
        text = "```markdown\n# Jane Doe\n## Skills\n```"
        self.assertEqual(_strip_code_fence(text), "# Jane Doe\n## Skills")

    def test_leaves_plain_text_alone(self):
        self.assertEqual(_strip_code_fence("  # Jane Doe  "), "# Jane Doe")

    def test_slug_is_filename_safe(self):
        self.assertEqual(_slug("Acme, Inc. / Spain"), "acme-inc-spain")
        self.assertEqual(_slug(""), "job")


class CatalogTests(unittest.TestCase):
    """Every job we paid to score is kept, not just the good ones, so the
    dashboard can offer more than the shortlist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "jobs.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_sub_threshold_and_failed_scores_are_kept(self):
        jobstore.save_jobs(
            [_job(url="https://x/low", score=12),
             _job(url="https://x/failed", score=None,
                  reasons="Scoring failed: timeout")],
            path=self.path)
        store = jobstore.load_store(self.path)
        self.assertEqual(store["https://x/low"]["score"], 12)
        self.assertIsNone(store["https://x/failed"]["score"])

    def test_date_found_is_stamped_once_and_preserved(self):
        jobstore.save_jobs([_job(score=50)], path=self.path,
                           date_found="2026-01-01")
        jobstore.save_jobs([_job(score=90)], path=self.path,
                           date_found="2026-09-21")
        record = jobstore.load_store(self.path)[_job().url]
        # The date we FIRST saw it, but this run's score.
        self.assertEqual(record["date_found"], "2026-01-01")
        self.assertEqual(record["score"], 90)

    def test_a_status_survives_a_later_save_of_the_same_job(self):
        jobstore.save_jobs([_job(score=50)], path=self.path)
        jobstore.set_status(_job().url, "Applied", path=self.path)
        jobstore.save_jobs([_job(score=50)], path=self.path)
        self.assertEqual(
            jobstore.load_store(self.path)[_job().url]["status"], "Applied")

    def test_eviction_drops_junk_before_jobs_she_cares_about(self):
        """Plain insertion order would throw away a 95-point match from last
        week to make room for this morning's long shots."""
        original = jobstore.MAX_JOBS
        jobstore.MAX_JOBS = 3
        try:
            jobstore.save_jobs(
                [_job(url="https://x/unscored", score=None),
                 _job(url="https://x/weak", score=5),
                 _job(url="https://x/great", score=95),
                 _job(url="https://x/applied", score=10)],
                path=self.path, date_found="2026-01-01")
            jobstore.set_status("https://x/applied", "Applied", path=self.path)
            jobstore.save_jobs([_job(url="https://x/fresh", score=70)],
                               path=self.path, date_found="2026-09-21")
        finally:
            jobstore.MAX_JOBS = original

        kept = set(jobstore.load_store(self.path))
        self.assertEqual(len(kept), 3)
        self.assertIn("https://x/applied", kept)   # the user engaged with it
        self.assertIn("https://x/great", kept)     # best score
        self.assertNotIn("https://x/unscored", kept)
        self.assertNotIn("https://x/weak", kept)


# The rest of the suite runs with no dependencies installed at all. These two
# helpers live in the Flask app, so skip rather than fail when it can't import.
try:
    from webapp.app import _as_score, _counts
except Exception:  # noqa: BLE001
    _as_score = _counts = None


@unittest.skipIf(_as_score is None, "Flask is not installed")
class MatchesApiTests(unittest.TestCase):
    """The score the dashboard renders. Sheet cells arrive as text, and one
    unparseable cell must not take the whole list down with it."""

    def test_scores_parse_or_become_none_never_a_crash(self):
        self.assertEqual(_as_score("87"), 87)
        self.assertEqual(_as_score("  42 "), 42)
        self.assertEqual(_as_score("88.6"), 88)
        self.assertEqual(_as_score("0"), 0)
        for empty in ("", None, "not a number"):
            self.assertIsNone(_as_score(empty))

    def test_non_finite_words_are_rejected(self):
        """float() accepts these, which is how a company named Infinity once
        blanked the entire matches list."""
        for word in ("Infinity", "-Infinity", "NaN", "inf"):
            self.assertIsNone(_as_score(word), word)

    def test_counts_bucket_every_row_exactly_once(self):
        rows = [{"Score": 90, "Status": "New"},      # great
                {"Score": 62, "Status": "Applied"},  # worth a look
                {"Score": 30, "Status": "New"},      # long shot
                {"Score": None, "Status": ""}]       # long shot (no score)
        counts = _counts(rows, 70)
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["great"], 1)
        self.assertEqual(counts["worth_a_look"], 1)
        self.assertEqual(counts["long_shot"], 2)
        self.assertEqual(counts["applied"], 1)
        self.assertEqual(
            counts["great"] + counts["worth_a_look"] + counts["long_shot"],
            counts["total"])


class SheetLayoutTests(unittest.TestCase):
    def test_new_columns_are_only_appended(self):
        """Old sheets keep working because a column is never inserted in the
        middle: the first ten headers must stay exactly where they were."""
        original = ["Date found", "Source", "Title", "Company", "Location",
                    "Score", "Recommendation", "Reasons", "URL", "Status"]
        self.assertEqual(sheets.HEADERS[: len(original)], original)

    def test_status_column_letter_matches_the_dashboard_formulas(self):
        """The Dashboard counts statuses with COUNTIF over column J, so Status
        has to actually be the tenth column."""
        self.assertEqual(sheets.HEADERS.index("Status"), 9)   # J
        self.assertEqual(sheets.HEADERS.index("Score"), 5)    # F
        self.assertEqual(sheets.HEADERS.index("URL"), 8)      # I
        self.assertEqual(sheets.HEADERS.index("Source"), 1)   # B

    def test_dashboard_blocks_leave_the_query_spill_area_empty(self):
        """A9 spills up to ten rows into A9:D18. Writing anything else into
        that area (even a blank) would break the formula."""
        blocks = {b["range"]: b["values"] for b in sheets._dashboard_blocks("Sheet1")}
        self.assertEqual(sorted(blocks), ["A1:F8", "A20:F38", "A9"])
        self.assertEqual(len(blocks["A9"]), 1)
        self.assertEqual(len(blocks["A9"][0]), 1)
        self.assertEqual(len(blocks["A1:F8"]), 8)

    def test_dashboard_rows_line_up_with_the_charts(self):
        """The charts point at fixed rows, so the source and status tables
        have to start exactly where _chart_requests expects them."""
        rows = {b["range"]: b["values"] for b in sheets._dashboard_blocks("Sheet1")}
        bottom = rows["A20:F38"]          # starts at row 20, i.e. index 19
        self.assertEqual(bottom[1][0], "Job board")            # row 21
        self.assertEqual(bottom[2][0], sheets.SOURCE_NAMES[0])  # row 22
        self.assertEqual(bottom[11][0], "Stage")               # row 31
        self.assertEqual(bottom[12][0], sheets.STATUSES[0])    # row 32
        self.assertEqual(len(bottom), 19)

    def test_dashboard_quotes_a_sheet_title_with_spaces(self):
        blocks = sheets._dashboard_blocks("Job list")
        self.assertIn("'Job list'!", blocks[0]["values"][4][0])

    def test_every_dashboard_row_is_six_cells_wide(self):
        for block in sheets._dashboard_blocks("Sheet1"):
            if block["range"] == "A9":
                continue
            for row in block["values"]:
                self.assertEqual(len(row), 6)

    def test_job_row_matches_the_header_width(self):
        row = sheets._job_to_row(_job(score=90, recommendation="strong",
                                      reasons="Good fit"), "2026-09-08")
        self.assertEqual(len(row), len(sheets.HEADERS))
        self.assertEqual(row[sheets.HEADERS.index("Status")], "New")
        self.assertEqual(row[sheets.HEADERS.index("Score")], 90)

    def test_unscored_job_writes_a_blank_score_not_none(self):
        row = sheets._job_to_row(_job(), "2026-09-08")
        self.assertEqual(row[sheets.HEADERS.index("Score")], "")


class BrowserSafeJsonTests(unittest.TestCase):
    """A browser's JSON.parse rejects NaN/Infinity and throws away the WHOLE
    response. Python's json accepts them, so these tests parse strictly, the
    way the web UI does.

    This is the bug that blanked the matches list: gspread turned a company
    genuinely named "Infinity" into float('inf').
    """

    @staticmethod
    def _parse_like_a_browser(text: str):
        return json.loads(text, parse_constant=_reject_constant)

    def test_python_would_otherwise_emit_a_token_browsers_reject(self):
        """Guards the assumption behind the fix."""
        raw = json.dumps({"Company": float("inf")})
        self.assertIn("Infinity", raw)
        with self.assertRaises(ValueError):
            self._parse_like_a_browser(raw)

    def test_non_finite_floats_become_text(self):
        cleaned = finite_only({"Company": float("inf"), "Score": float("nan"),
                               "Low": float("-inf")})
        self.assertEqual(cleaned, {"Company": "Infinity", "Score": "NaN",
                                   "Low": "-Infinity"})

    def test_cleaned_payload_parses_strictly(self):
        rows = [{"Company": float("inf"), "Title": "SEO Editor", "Score": 85},
                {"Company": "Acme", "Title": "Copywriter", "Score": float("nan")}]
        text = json.dumps(finite_only({"ok": True, "rows": rows}))
        parsed = self._parse_like_a_browser(text)
        self.assertEqual(parsed["rows"][0]["Company"], "Infinity")
        self.assertEqual(parsed["rows"][1]["Score"], "NaN")

    def test_ordinary_values_are_untouched(self):
        payload = {"ok": True, "n": 3, "x": 1.5, "s": "Infinity Ltd",
                   "list": [1, "two", None], "nested": {"a": [0.5]}}
        self.assertEqual(finite_only(payload), payload)

    def test_nested_containers_are_cleaned(self):
        cleaned = finite_only({"rows": [{"vals": (float("inf"), 2)}]})
        self.assertEqual(cleaned, {"rows": [{"vals": ["Infinity", 2]}]})

    def test_original_object_is_not_modified(self):
        original = {"Company": float("inf")}
        finite_only(original)
        self.assertTrue(math.isinf(original["Company"]))


if __name__ == "__main__":
    unittest.main()
