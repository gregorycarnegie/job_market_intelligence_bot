import json
import os
import tempfile
import unittest
from pathlib import Path

import pull_desc


class PullDescTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original_cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.addCleanup(os.chdir, self.original_cwd)

        self.original_csv_file = pull_desc.CSV_FILE
        self.original_json_file = pull_desc.JSON_FILE
        self.addCleanup(self._restore_paths)

        pull_desc.CSV_FILE = "jobs.csv"
        pull_desc.JSON_FILE = "desc.json"

    def _restore_paths(self) -> None:
        pull_desc.CSV_FILE = self.original_csv_file
        pull_desc.JSON_FILE = self.original_json_file

    def seed_jobs(self, rows: list[dict[str, str]]) -> None:
        pull_desc.storage.append_jobs(pull_desc.STATE_DB_FILE, rows)
        pull_desc.storage.export_jobs_to_csv(pull_desc.STATE_DB_FILE, pull_desc.CSV_FILE)

    def test_load_latest_csv_batch_returns_only_latest_timestamp(self) -> None:
        self.seed_jobs(
            [
                {
                    "time": "2026-04-04T09:00:00Z",
                    "title": "Old role",
                    "description": "Old description",
                    "link": "https://example.com/old",
                },
                {
                    "time": "2026-04-04T10:00:00Z",
                    "title": "New role 1",
                    "description": "New description 1",
                    "link": "https://example.com/new-1",
                },
                {
                    "time": "2026-04-04T10:00:00Z",
                    "title": "New role 2",
                    "description": "New description 2",
                    "link": "https://example.com/new-2",
                },
            ]
        )

        latest_ts, batch = pull_desc.load_latest_csv_batch()
        self.assertEqual(latest_ts, "2026-04-04T10:00:00Z")
        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0]["title"], "New role 1")
        self.assertEqual(batch[1]["title"], "New role 2")

    def test_main_creates_empty_desc_when_csv_missing(self) -> None:
        result = pull_desc.main()
        self.assertEqual(result, 0)
        payload = json.loads(Path("desc.json").read_text(encoding="utf-8"))
        self.assertEqual(payload, [])

    def test_load_latest_csv_batch_reads_from_sqlite(self) -> None:
        self.seed_jobs(
            [
                {
                    "time": "2026-04-04T09:00:00Z",
                    "title": "Old role",
                    "description": "Old description",
                    "link": "https://example.com/old",
                },
                {
                    "time": "2026-04-04T10:00:00Z",
                    "title": "New role",
                    "description": "New description",
                    "link": "https://example.com/new",
                },
            ]
        )

        latest_ts, batch = pull_desc.load_latest_csv_batch()
        self.assertEqual(latest_ts, "2026-04-04T10:00:00Z")
        Path("jobs.csv").write_text("time,title,description,link\n", encoding="utf-8")
        latest_ts, batch = pull_desc.load_latest_csv_batch()
        self.assertEqual(latest_ts, "2026-04-04T10:00:00Z")
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["title"], "New role")


if __name__ == "__main__":
    unittest.main()
