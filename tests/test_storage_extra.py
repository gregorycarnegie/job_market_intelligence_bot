import os
import tempfile
import unittest
from pathlib import Path

from jobbot import storage as jobbot_storage


class StorageTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original_cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.addCleanup(os.chdir, self.original_cwd)
        self.db = "test_state.sqlite3"


class ReviewedFingerprintCountTestCase(StorageTestBase):
    def test_zero_when_empty(self) -> None:
        self.assertEqual(jobbot_storage.reviewed_fingerprint_count(self.db), 0)

    def test_counts_after_append(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp1", "fp2"], max_items=100)
        self.assertEqual(jobbot_storage.reviewed_fingerprint_count(self.db), 2)


class AppendReviewedFingerprintsTestCase(StorageTestBase):
    def test_overflow_prunes_oldest(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp1", "fp2", "fp3"], max_items=100)
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp4", "fp5"], max_items=4)
        count = jobbot_storage.reviewed_fingerprint_count(self.db)
        self.assertEqual(count, 4)

    def test_skips_empty_list(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, [], max_items=100)
        self.assertEqual(jobbot_storage.reviewed_fingerprint_count(self.db), 0)

    def test_deduplicates_within_batch(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp1", "fp1", "fp2"], max_items=100)
        self.assertEqual(jobbot_storage.reviewed_fingerprint_count(self.db), 2)


class HasAnyReviewedFingerprintTestCase(StorageTestBase):
    def test_returns_false_for_empty_list(self) -> None:
        self.assertFalse(jobbot_storage.has_any_reviewed_fingerprint(self.db, []))

    def test_finds_existing_fingerprint(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp-abc"], max_items=100)
        self.assertTrue(jobbot_storage.has_any_reviewed_fingerprint(self.db, ["missing", "fp-abc"]))

    def test_returns_false_for_missing_fingerprint(self) -> None:
        jobbot_storage.append_reviewed_fingerprints(self.db, ["fp-abc"], max_items=100)
        self.assertFalse(jobbot_storage.has_any_reviewed_fingerprint(self.db, ["fp-xyz"]))


class FeedStateTestCase(StorageTestBase):
    def test_save_and_load(self) -> None:
        state = {"my_feed": {"last_checked_at": 1234567890.0}}
        jobbot_storage.save_feed_state(self.db, state)
        loaded = jobbot_storage.load_feed_state(self.db)
        self.assertIn("my_feed", loaded)
        self.assertAlmostEqual(loaded["my_feed"]["last_checked_at"], 1234567890.0)

    def test_empty_state(self) -> None:
        self.assertEqual(jobbot_storage.load_feed_state(self.db), {})


class AlertStateTestCase(StorageTestBase):
    def test_save_and_load_alert_state(self) -> None:
        state = {
            "alerted_links": ["https://example.com/job/1"],
            "pending_alerts": [
                {
                    "link": "https://example.com/job/2",
                    "title": "IT Support",
                    "score": 55,
                    "time": "2026-04-04T10:00:00Z",
                    "reasons": ["match"],
                    "source": "board",
                    "company": "Acme",
                    "shortlisted": False,
                    "company_control": "none",
                    "role_profile": "",
                }
            ],
            "last_run_utc": "2026-04-04T10:00:00Z",
            "last_delivery_utc": "2026-04-04T09:00:00Z",
            "last_delivery_error": "",
        }
        jobbot_storage.save_alert_state(self.db, state)
        loaded = jobbot_storage.load_alert_state(self.db)
        self.assertIn("https://example.com/job/1", loaded["alerted_links"])
        self.assertEqual(len(loaded["pending_alerts"]), 1)
        self.assertEqual(loaded["last_run_utc"], "2026-04-04T10:00:00Z")

    def test_load_empty_alert_state(self) -> None:
        loaded = jobbot_storage.load_alert_state(self.db)
        self.assertEqual(loaded["alerted_links"], [])
        self.assertEqual(loaded["pending_alerts"], [])


class TelegramUpdateOffsetTestCase(StorageTestBase):
    def test_default_offset_is_zero(self) -> None:
        self.assertEqual(jobbot_storage.load_telegram_update_offset(self.db), 0)

    def test_save_and_load_offset(self) -> None:
        jobbot_storage.save_telegram_update_offset(self.db, 42)
        self.assertEqual(jobbot_storage.load_telegram_update_offset(self.db), 42)

    def test_negative_offset_clamped_to_zero(self) -> None:
        jobbot_storage.save_telegram_update_offset(self.db, -5)
        self.assertEqual(jobbot_storage.load_telegram_update_offset(self.db), 0)


class TelegramDigestSessionTestCase(StorageTestBase):
    def test_save_and_load_session(self) -> None:
        pages = ["Page 1 content", "Page 2 content"]
        jobbot_storage.save_telegram_digest_session(self.db, "session-abc", "2026-04-04T10:00:00Z", pages)
        loaded = jobbot_storage.load_telegram_digest_session(self.db, "session-abc")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["session_id"], "session-abc")
        self.assertEqual(len(loaded["pages"]), 2)

    def test_load_nonexistent_session_returns_none(self) -> None:
        self.assertIsNone(jobbot_storage.load_telegram_digest_session(self.db, "nonexistent"))

    def test_overflow_prunes_oldest_sessions(self) -> None:
        for i in range(5):
            jobbot_storage.save_telegram_digest_session(
                self.db, f"session-{i}", f"2026-04-0{i + 1}T00:00:00Z", [f"Page {i}"], keep_latest=3
            )
        # Sessions 0-1 should have been pruned; only the 3 newest should remain
        still_present = sum(
            1 for i in range(5)
            if jobbot_storage.load_telegram_digest_session(self.db, f"session-{i}") is not None
        )
        self.assertLessEqual(still_present, 3)


class FindApplicationByLinkOrFingerprintsTestCase(StorageTestBase):
    def _save_app(self, link: str, fingerprints: list[str]) -> None:
        application = {
            "title": "IT Support",
            "description": "A role",
            "link": link,
            "links": [link],
            "source": "board",
            "sources": ["board"],
            "status": "new",
            "company": "Acme",
            "shortlisted": False,
            "company_control": "none",
            "role_profile": "",
            "score": 50,
            "best_score": 50,
            "reasons": [],
            "why_this_fits": [],
            "resume_bullet_suggestions": [],
            "intro_message": "",
            "application_ready": False,
            "notes": "",
            "feedback_keywords": [],
            "fingerprints": fingerprints,
            "match_count": 1,
            "first_seen_utc": "2026-04-04T10:00:00Z",
            "last_seen_utc": "2026-04-04T10:00:00Z",
            "status_observed_utc": "",
            "applied_at_utc": "",
            "interviewed_at_utc": "",
            "rejected_at_utc": "",
        }
        jobbot_storage.save_application_record(self.db, application)

    def test_finds_by_link(self) -> None:
        self._save_app("https://example.com/job/1", ["fp1"])
        found_link, found = jobbot_storage.find_application_by_link_or_fingerprints(
            self.db, "https://example.com/job/1", []
        )
        self.assertIsNotNone(found)
        self.assertEqual(found_link, "https://example.com/job/1")

    def test_finds_by_fingerprint(self) -> None:
        self._save_app("https://example.com/job/2", ["fp-unique"])
        _found_link, found = jobbot_storage.find_application_by_link_or_fingerprints(
            self.db, "https://example.com/job/DIFFERENT", ["fp-unique"]
        )
        self.assertIsNotNone(found)

    def test_returns_none_for_missing(self) -> None:
        found_link, found = jobbot_storage.find_application_by_link_or_fingerprints(
            self.db, "https://example.com/missing", ["fp-missing"]
        )
        self.assertIsNone(found_link)
        self.assertIsNone(found)


class LoadLatestJobBatchTestCase(StorageTestBase):
    def test_returns_none_when_empty(self) -> None:
        ts, batch = jobbot_storage.load_latest_job_batch(self.db)
        self.assertIsNone(ts)
        self.assertEqual(batch, [])

    def test_returns_only_latest_timestamp_batch(self) -> None:
        rows = [
            {"time": "2026-04-03T10:00:00Z", "title": "Old", "description": "desc", "link": "https://example.com/1"},
            {"time": "2026-04-04T10:00:00Z", "title": "New A", "description": "desc", "link": "https://example.com/2"},
            {"time": "2026-04-04T10:00:00Z", "title": "New B", "description": "desc", "link": "https://example.com/3"},
        ]
        jobbot_storage.append_jobs(self.db, rows)
        ts, batch = jobbot_storage.load_latest_job_batch(self.db)
        self.assertEqual(ts, "2026-04-04T10:00:00Z")
        self.assertEqual(len(batch), 2)
        titles = {item["title"] for item in batch}
        self.assertIn("New A", titles)
        self.assertIn("New B", titles)


class ExportJobsToCsvTestCase(StorageTestBase):
    def test_creates_csv_with_headers(self) -> None:
        csv_file = "jobs.csv"
        jobbot_storage.export_jobs_to_csv(self.db, csv_file)
        content = Path(csv_file).read_text(encoding="utf-8")
        self.assertIn("title", content)
        self.assertIn("link", content)

    def test_exports_job_rows(self) -> None:
        jobbot_storage.append_jobs(
            self.db,
            [{"time": "2026-04-04T10:00:00Z", "title": "IT Support", "description": "desc", "link": "https://example.com/1"}],
        )
        csv_file = "jobs_export.csv"
        jobbot_storage.export_jobs_to_csv(self.db, csv_file)
        content = Path(csv_file).read_text(encoding="utf-8")
        self.assertIn("IT Support", content)


class SubdirDbTestCase(unittest.TestCase):
    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "subdir" / "nested.sqlite3")
            count = jobbot_storage.reviewed_fingerprint_count(db_path)
            self.assertEqual(count, 0)
            self.assertTrue(Path(db_path).exists())


if __name__ == "__main__":
    unittest.main()
