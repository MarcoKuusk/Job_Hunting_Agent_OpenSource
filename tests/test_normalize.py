"""Offline tests for the pure logic: field mapping, title parsing, HTML
stripping, and dedupe. These import only stdlib-safe modules, so they run with
NO third-party dependencies installed:

    python -m unittest discover -s tests

(The source modules import requests/feedparser/anthropic lazily inside their
fetch/score functions, so importing them here is safe.)
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dedupe import filter_new, mark_seen
from src.models import Job
from src.textutil import strip_html, truncate
from src.sources import remoteok, arbeitnow, remotive, weworkremotely, apify_source


class TextUtilTests(unittest.TestCase):
    def test_strip_html_basic(self):
        html = "<p>Hello <b>world</b></p><script>ignore()</script>"
        out = strip_html(html)
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertNotIn("ignore", out)
        self.assertNotIn("<", out)

    def test_strip_html_entities(self):
        self.assertEqual(strip_html("Tom &amp; Jerry"), "Tom & Jerry")

    def test_strip_html_empty(self):
        self.assertEqual(strip_html(None), "")
        self.assertEqual(strip_html(""), "")

    def test_truncate(self):
        self.assertEqual(truncate("short", 100), "short")
        self.assertTrue(truncate("x" * 50, 10).startswith("xxxxxxxxxx"))
        self.assertIn("truncated", truncate("x" * 50, 10))


class JobModelTests(unittest.TestCase):
    def test_dedupe_key_prefers_url(self):
        j = Job(source="s", title="T", company="C", url="https://X/Job?id=1")
        self.assertEqual(j.dedupe_key(), "https://x/job?id=1")

    def test_dedupe_key_fallback(self):
        j = Job(source="S", title="T", company="C", url="")
        self.assertEqual(j.dedupe_key(), "s|c|t")

    def test_content_key_ignores_url_and_punctuation(self):
        a = Job(source="linkedin", title="Customer Success Manager",
                company="Jobgether", url="https://es.linkedin.com/jobs/view/1")
        b = Job(source="linkedin", title="customer  success   manager!",
                company="Jobgether", url="https://it.linkedin.com/jobs/view/2")
        self.assertNotEqual(a.dedupe_key(), b.dedupe_key())
        self.assertEqual(a.content_key(), b.content_key())

    def test_content_key_empty_without_company_or_title(self):
        self.assertEqual(Job(source="s", title="T", company="", url="u").content_key(), "")
        self.assertEqual(Job(source="s", title="", company="C", url="u").content_key(), "")

    def test_compact_text_strips_html(self):
        j = Job(source="s", title="Dev", company="Acme", url="https://x",
                description="<p>Build <b>things</b></p>", tags=["python"])
        text = j.to_compact_text()
        self.assertIn("Dev", text)
        self.assertIn("Acme", text)
        self.assertIn("python", text)
        self.assertNotIn("<p>", text)


class DedupeTests(unittest.TestCase):
    @staticmethod
    def _same_role(*urls):
        return [Job(source="linkedin", title="Customer Success Manager",
                    company="Jobgether", url=u) for u in urls]

    def test_collapses_one_role_reposted_under_many_urls(self):
        jobs = self._same_role("https://es.linkedin.com/1",
                               "https://it.linkedin.com/2",
                               "https://fr.linkedin.com/3")
        self.assertEqual(len(filter_new(jobs, set())), 1)

    def test_marked_role_stays_filtered_on_the_next_run(self):
        seen = set()
        first = filter_new(self._same_role("https://es.linkedin.com/1"), seen)
        mark_seen(seen, first)
        # A different URL for the same opening must not come back as new.
        again = filter_new(self._same_role("https://it.linkedin.com/2"), seen)
        self.assertEqual(again, [])

    def test_different_roles_at_one_company_both_kept(self):
        jobs = [
            Job(source="s", title="Customer Support Agent", company="Acme", url="https://a/1"),
            Job(source="s", title="SEO Copywriter", company="Acme", url="https://a/2"),
        ]
        self.assertEqual(len(filter_new(jobs, set())), 2)

    def test_no_company_falls_back_to_url_only(self):
        jobs = [
            Job(source="s", title="Support", company="", url="https://a/1"),
            Job(source="s", title="Support", company="", url="https://a/2"),
        ]
        self.assertEqual(len(filter_new(jobs, set())), 2)


class RemoteOKTests(unittest.TestCase):
    def test_skips_legal_metadata_element(self):
        self.assertIsNone(remoteok.normalize({"legal": "Use at your own risk"}))

    def test_normalize_job(self):
        job = remoteok.normalize({
            "position": "Backend Engineer",
            "company": "Acme",
            "url": "https://remoteok.com/x",
            "tags": ["python", "django"],
            "description": "<p>Great role</p>",
            "salary_min": 60000, "salary_max": 90000,
        })
        self.assertIsNotNone(job)
        self.assertEqual(job.source, "remoteok")
        self.assertEqual(job.title, "Backend Engineer")
        self.assertEqual(job.company, "Acme")
        self.assertIn("python", job.tags)
        self.assertIn("60000", job.salary)


class ArbeitnowTests(unittest.TestCase):
    def test_normalize_remote_flag(self):
        job = arbeitnow.normalize({
            "title": "Data Engineer",
            "company_name": "BetaCorp",
            "url": "https://arbeitnow.com/x",
            "location": "Berlin",
            "remote": True,
            "tags": ["sql"],
        })
        self.assertEqual(job.company, "BetaCorp")
        self.assertIn("remote", job.location.lower())

    def test_empty_item_returns_none(self):
        self.assertIsNone(arbeitnow.normalize({}))


class RemotiveTests(unittest.TestCase):
    def test_normalize_uses_jobs_fields(self):
        job = remotive.normalize({
            "title": "Frontend Dev",
            "company_name": "Gamma",
            "url": "https://remotive.com/x",
            "candidate_required_location": "Europe",
            "salary": "$70k",
        })
        self.assertEqual(job.title, "Frontend Dev")
        self.assertEqual(job.location, "Europe")
        self.assertEqual(job.salary, "$70k")


class WeWorkRemotelyTests(unittest.TestCase):
    def test_split_title_company_position(self):
        company, position = weworkremotely.split_title("Hospitable: Chief Financial Officer (Remote)")
        self.assertEqual(company, "Hospitable")
        self.assertEqual(position, "Chief Financial Officer (Remote)")

    def test_split_title_no_colon(self):
        company, position = weworkremotely.split_title("Software Engineer")
        self.assertEqual(company, "")
        self.assertEqual(position, "Software Engineer")

    def test_normalize_entry(self):
        entry = {
            "title": "Toptal: AI Engineer",
            "link": "https://weworkremotely.com/x",
            "summary": "<p>Join us</p>",
            "region": "Anywhere in the World",
            "tags": [{"term": "AI"}],
        }
        job = weworkremotely.normalize(entry)
        self.assertEqual(job.company, "Toptal")
        self.assertEqual(job.title, "AI Engineer")
        self.assertIn("AI", job.tags)


class ApifyTests(unittest.TestCase):
    def test_build_input_linkedin(self):
        # Reconciled to cheap_scraper/linkedin-job-scraper's Input schema.
        inp = apify_source.build_input("linkedin", ["cybersecurity", "GRC"], 150)
        self.assertEqual(inp["keyword"], ["cybersecurity", "GRC"])
        self.assertEqual(inp["maxItems"], 150)
        self.assertTrue(inp["saveOnlyUniqueItems"])

    def test_build_input_upwork(self):
        inp = apify_source.build_input("upwork", ["react"], 10)
        self.assertEqual(inp["searchQuery"], "react")
        self.assertEqual(inp["maxItems"], 10)

    def test_normalize_tolerates_field_variants(self):
        job = apify_source.normalize(
            {"jobTitle": "ML Engineer", "companyName": "Delta",
             "jobUrl": "https://x", "descriptionText": "Do ML"},
            "linkedin",
        )
        self.assertEqual(job.title, "ML Engineer")
        self.assertEqual(job.company, "Delta")
        self.assertEqual(job.url, "https://x")


class NoEmDashTests(unittest.TestCase):
    def test_removes_spaced_em_dash(self):
        from src.documents import _no_em_dash
        out = _no_em_dash("I lead GRC programs — and I enjoy it.")
        self.assertNotIn("—", out)
        self.assertIn("programs, and", out)

    def test_removes_unspaced_em_dash(self):
        from src.documents import _no_em_dash
        out = _no_em_dash("GRC—ISO 27001—NIST")
        self.assertNotIn("—", out)

    def test_leaves_clean_text_unchanged(self):
        from src.documents import _no_em_dash
        self.assertEqual(_no_em_dash("Clean, plain text."), "Clean, plain text.")


if __name__ == "__main__":
    unittest.main()
