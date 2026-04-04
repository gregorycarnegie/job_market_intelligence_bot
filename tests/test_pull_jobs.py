import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pull_jobs


REPO_ROOT = Path(__file__).resolve().parents[1]
RESUME_PATH = REPO_ROOT / "resume.json"


class PullJobsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original_cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.addCleanup(os.chdir, self.original_cwd)

        self.original_resume_file = pull_jobs.RESUME_FILE
        self.original_job_search_config_file = pull_jobs.JOB_SEARCH_CONFIG_FILE
        self.addCleanup(self._restore_paths)

        pull_jobs.RESUME_FILE = str(RESUME_PATH)
        pull_jobs.JOB_SEARCH_CONFIG_FILE = "job_search_config.json"

        self.profile = pull_jobs.load_resume_profile()

    def _restore_paths(self) -> None:
        pull_jobs.RESUME_FILE = self.original_resume_file
        pull_jobs.JOB_SEARCH_CONFIG_FILE = self.original_job_search_config_file

    def write_search_config(self, payload: dict) -> dict[str, object]:
        Path("job_search_config.json").write_text(json.dumps(payload), encoding="utf-8")
        return pull_jobs.load_job_search_config()

    def test_score_job_generates_application_materials(self) -> None:
        search_config = self.write_search_config(
            {
                "priority_companies": ["Monzo"],
                "feedback": {"enabled": False},
            }
        )
        lockouts = ["remote us", "us only"]
        item = {
            "title": "IT Support Engineer at Monzo",
            "description": (
                "London hybrid role covering Active Directory, Azure AD, Microsoft 365, "
                "user onboarding, troubleshooting, and hardware support."
            ),
            "link": "https://example.com/jobs/monzo-it-support",
        }

        evaluation = pull_jobs.score_job(
            item,
            "example_board",
            self.profile,
            search_config,
            {"enabled": False, "source_adjustments": {}, "keyword_adjustments": {}, "keyword_limit": 4, "max_keyword_adjustment": 6},
            "2026-04-04T10:00:00Z",
            lockouts,
        )

        self.assertTrue(evaluation["qualified"], evaluation)
        match = evaluation["match"]
        self.assertTrue(match["shortlisted"])
        self.assertEqual(match["company_control"], "priority")
        self.assertTrue(match["why_this_fits"])
        self.assertTrue(match["resume_bullet_suggestions"])
        self.assertTrue(match["intro_message"])
        self.assertTrue(match["feedback_keywords"])
        self.assertTrue(match["application_ready"])

    def test_score_job_rejects_blacklisted_company(self) -> None:
        search_config = self.write_search_config(
            {
                "company_blacklist": ["Example Recruiter"],
                "feedback": {"enabled": False},
            }
        )
        item = {
            "title": "IT Support Engineer at Example Recruiter",
            "description": "London onsite support role with Windows troubleshooting and Microsoft 365.",
            "link": "https://example.com/jobs/recruiter-it-support",
        }

        evaluation = pull_jobs.score_job(
            item,
            "example_board",
            self.profile,
            search_config,
            {"enabled": False, "source_adjustments": {}, "keyword_adjustments": {}, "keyword_limit": 4, "max_keyword_adjustment": 6},
            "2026-04-04T10:00:00Z",
            ["remote us", "us only"],
        )

        self.assertFalse(evaluation["qualified"], evaluation)
        self.assertIn("blacklisted employer", " ".join(evaluation["reasons"]))

    def test_upsert_application_record_merges_duplicate_matches(self) -> None:
        state = pull_jobs.fresh_applications_state()
        first_payload = {
            "title": "IT Support Engineer at Monzo",
            "description": "London hybrid Active Directory and Microsoft 365 support role.",
            "link": "https://example.com/jobs/monzo-it-support",
            "source": "good_board",
            "company": "Monzo",
            "score": 58,
            "best_score": 58,
            "status": "new",
            "why_this_fits": ["Direct IT support overlap."],
            "resume_bullet_suggestions": ["Managed onboarding and offboarding in Active Directory."],
            "intro_message": "Hi Monzo team, ...",
            "feedback_keywords": ["active directory", "microsoft 365"],
        }
        created = pull_jobs.upsert_application_record(state, first_payload, "2026-04-04T10:00:00Z")
        self.assertTrue(created)
        self.assertEqual(len(state["applications"]), 1)

        state["applications"][0]["status"] = "reviewed"
        state["applications"][0]["notes"] = "Manual note"

        second_payload = {
            **first_payload,
            "link": "https://boards.example.com/monzo/it-support",
            "score": 64,
            "best_score": 64,
            "resume_bullet_suggestions": ["Supported 600 to 700 users across Microsoft 365 and hardware."],
            "feedback_keywords": ["hardware support"],
        }
        created = pull_jobs.upsert_application_record(state, second_payload, "2026-04-04T11:00:00Z")
        self.assertFalse(created)
        self.assertEqual(len(state["applications"]), 1)

        application = state["applications"][0]
        self.assertEqual(application["status"], "reviewed")
        self.assertEqual(application["notes"], "Manual note")
        self.assertEqual(application["best_score"], 64)
        self.assertEqual(len(application["links"]), 2)
        self.assertGreaterEqual(application["match_count"], 2)
        self.assertIn("hardware support", application["feedback_keywords"])

    def test_feedback_metrics_and_scoring_adjustments(self) -> None:
        search_config = self.write_search_config(
            {
                "feedback": {
                    "enabled": True,
                    "min_samples": 1,
                    "max_source_adjustment": 10,
                    "max_keyword_adjustment": 6,
                    "keyword_limit": 4,
                    "new_reviewed_retention_days": 30,
                    "rejected_retention_days": 30,
                    "applied_retention_days": 365,
                    "interview_retention_days": 365,
                }
            }
        )
        applications_state = pull_jobs.fresh_applications_state()
        applications_state["applications"] = [
            pull_jobs.normalize_application_record(
                {
                    "title": "IT Support Engineer at Good Co",
                    "description": "London hybrid Active Directory and Microsoft 365 support role",
                    "link": "https://example.com/good",
                    "source": "good_board",
                    "sources": ["good_board"],
                    "status": "interview",
                    "score": 60,
                    "best_score": 60,
                    "feedback_keywords": ["active directory", "microsoft 365"],
                    "first_seen_utc": "2026-03-01T09:00:00Z",
                    "last_seen_utc": "2026-03-20T09:00:00Z",
                }
            ),
            pull_jobs.normalize_application_record(
                {
                    "title": "Data Engineer at Bad Co",
                    "description": "London data engineering role",
                    "link": "https://example.com/bad",
                    "source": "bad_board",
                    "sources": ["bad_board"],
                    "status": "rejected",
                    "score": 20,
                    "best_score": 20,
                    "feedback_keywords": ["data engineer"],
                    "first_seen_utc": "2026-03-01T09:00:00Z",
                    "last_seen_utc": "2026-03-15T09:00:00Z",
                }
            ),
            pull_jobs.normalize_application_record(
                {
                    "title": "Old Rejected Role at Old Co",
                    "description": "Old stale rejected role",
                    "link": "https://example.com/old",
                    "source": "old_board",
                    "sources": ["old_board"],
                    "status": "rejected",
                    "score": 10,
                    "best_score": 10,
                    "feedback_keywords": ["old keyword"],
                    "first_seen_utc": "2025-01-01T09:00:00Z",
                    "last_seen_utc": "2025-01-15T09:00:00Z",
                    "rejected_at_utc": "2025-01-15T09:00:00Z",
                }
            ),
        ]
        applications_state["applications"] = [app for app in applications_state["applications"] if app]

        pull_jobs.sync_application_outcomes(applications_state, "2026-04-04T10:00:00Z")
        cleanup = pull_jobs.prune_applications_state(applications_state, search_config, "2026-04-04T10:00:00Z")
        self.assertEqual(cleanup["removed_count"], 1, cleanup)

        feedback = pull_jobs.build_feedback_metrics(
            "2026-04-04T10:00:00Z",
            applications_state,
            search_config,
            cleanup,
        )
        self.assertGreater(feedback["source_adjustments"].get("good_board", 0), 0)
        self.assertLess(feedback["source_adjustments"].get("bad_board", 0), 0)
        self.assertGreater(feedback["keyword_adjustments"].get("active directory", 0), 0)
        self.assertLess(feedback["keyword_adjustments"].get("data engineer", 0), 0)

        item = {
            "title": "IT Support Engineer at Future Co",
            "description": "London hybrid role with Active Directory, Microsoft 365, troubleshooting and onboarding.",
            "link": "https://example.com/future-good",
        }
        good_eval = pull_jobs.score_job(
            item,
            "good_board",
            self.profile,
            search_config,
            feedback,
            "2026-04-04T10:05:00Z",
            ["remote us", "us only"],
        )
        bad_eval = pull_jobs.score_job(
            item,
            "bad_board",
            self.profile,
            search_config,
            feedback,
            "2026-04-04T10:05:00Z",
            ["remote us", "us only"],
        )
        self.assertGreater(good_eval["score"], bad_eval["score"])
        self.assertIn("feedback", " ".join(good_eval["reasons"]).lower())

    def test_fetch_generic_html_board_jobs_parses_jsonld_job(self) -> None:
        board = {
            "name": "example_generic_html",
            "display_name": "Example Co",
            "platform": "generic_html",
            "start_urls": ["https://example.com/careers"],
            "allowed_domains": ["example.com"],
            "job_link_keywords": ["jobs", "careers", "role"],
            "job_link_regexes": ["/careers/.+"],
            "max_job_pages": 10,
        }
        list_page = """
        <html><body>
          <a href="/careers/it-support-engineer">IT Support Engineer</a>
        </body></html>
        """
        detail_page = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "IT Support Engineer",
            "url": "https://example.com/careers/it-support-engineer",
            "description": "London hybrid support role with Active Directory and Microsoft 365",
            "hiringOrganization": {"@type": "Organization", "name": "Example Co"}
          }
          </script>
        </head><body></body></html>
        """

        def fake_fetch(url: str) -> str:
            if url.endswith("/careers"):
                return list_page
            if url.endswith("/careers/it-support-engineer"):
                return detail_page
            raise AssertionError(f"Unexpected URL {url}")

        with mock.patch.object(pull_jobs, "fetch_feed", side_effect=fake_fetch):
            items = pull_jobs.fetch_generic_html_board_jobs(board)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "IT Support Engineer")
        self.assertIn("Example Co", items[0]["description"])
        self.assertEqual(items[0]["link"], "https://example.com/careers/it-support-engineer")

    def test_main_end_to_end_writes_expected_runtime_files(self) -> None:
        self.write_search_config(
            {
                "priority_companies": ["Monzo"],
                "daily_digest": {"enabled": False},
                "feedback": {"enabled": False},
            }
        )
        feed_xml = """
        <rss><channel>
          <item>
            <title>IT Support Engineer at Monzo</title>
            <description>
              London hybrid support role with Active Directory, Azure AD, Microsoft 365,
              onboarding, troubleshooting, and hardware support.
            </description>
            <link>https://example.com/jobs/monzo-it-support</link>
          </item>
        </channel></rss>
        """
        test_feeds = [
            {
                "name": "test_feed",
                "url": "https://example.com/feed.xml",
                "min_interval_seconds": 0,
            }
        ]

        with (
            mock.patch.object(pull_jobs, "FEEDS", test_feeds),
            mock.patch.object(pull_jobs, "fetch_feed", return_value=feed_xml),
            mock.patch("jobbot.matching.load_telegram_settings", return_value=("", "", "")),
        ):
            result = pull_jobs.main()

        self.assertEqual(result, 0)

        with open("jobs.csv", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "IT Support Engineer at Monzo")

        matches = json.loads(Path("matches.json").read_text(encoding="utf-8"))
        self.assertEqual(matches["match_count"], 1)
        self.assertEqual(matches["matches"][0]["company"], "Monzo")
        self.assertTrue(matches["matches"][0]["application_ready"])

        alert_state = json.loads(Path("alerts_state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(alert_state["pending_alerts"]), 1)
        self.assertIn("Telegram credentials not configured", alert_state["last_delivery_error"])

        seen_state = json.loads(Path("seen_jobs_state.json").read_text(encoding="utf-8"))
        self.assertTrue(seen_state["reviewed_fingerprints"])
        self.assertTrue(seen_state["last_run_utc"])

        applications_state = json.loads(Path("applications.json").read_text(encoding="utf-8"))
        self.assertEqual(len(applications_state["applications"]), 1)
        self.assertEqual(applications_state["applications"][0]["company"], "Monzo")
        self.assertEqual(applications_state["applications"][0]["status"], "new")

        feed_state = json.loads(Path("feed_state.json").read_text(encoding="utf-8"))
        self.assertIn("test_feed", feed_state)
        self.assertIn("last_checked_at", feed_state["test_feed"])

        digest = json.loads(Path("daily_digest.json").read_text(encoding="utf-8"))
        self.assertEqual(digest["item_count"], 1)

        briefs = json.loads(Path("application_briefs.json").read_text(encoding="utf-8"))
        self.assertEqual(briefs["brief_count"], 1)
        self.assertEqual(briefs["items"][0]["company"], "Monzo")

        borderline = json.loads(Path("borderline_matches.json").read_text(encoding="utf-8"))
        self.assertEqual(borderline["candidate_count"], 0)

        feedback_metrics = json.loads(Path("feedback_metrics.json").read_text(encoding="utf-8"))
        self.assertTrue(feedback_metrics["feedback_enabled"] is False)
        self.assertEqual(feedback_metrics["status_counts"]["new"], 1)
        self.assertEqual(feedback_metrics["outcome_sample_count"], 0)

    def test_main_does_not_mark_feed_checked_when_fetch_fails(self) -> None:
        self.write_search_config(
            {
                "daily_digest": {"enabled": False},
                "feedback": {"enabled": False},
            }
        )
        test_feeds = [
            {
                "name": "failing_feed",
                "url": "https://example.com/feed.xml",
                "min_interval_seconds": 0,
            }
        ]

        with (
            mock.patch.object(pull_jobs, "FEEDS", test_feeds),
            mock.patch.object(pull_jobs, "fetch_feed", side_effect=OSError("boom")),
            mock.patch("jobbot.matching.load_telegram_settings", return_value=("", "", "")),
        ):
            result = pull_jobs.main()

        self.assertEqual(result, 0)
        feed_state = json.loads(Path("feed_state.json").read_text(encoding="utf-8"))
        self.assertEqual(feed_state, {})

        matches = json.loads(Path("matches.json").read_text(encoding="utf-8"))
        self.assertEqual(matches["match_count"], 0)

        applications_state = json.loads(Path("applications.json").read_text(encoding="utf-8"))
        self.assertEqual(applications_state["applications"], [])

        alert_state = json.loads(Path("alerts_state.json").read_text(encoding="utf-8"))
        self.assertEqual(alert_state["pending_alerts"], [])


if __name__ == "__main__":
    unittest.main()
