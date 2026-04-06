import os
import unittest
import unittest.mock as mock

from jobbot import sources


class AdzunaSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"country": "gb", "what": "python developer", "where": "london", "display_name": "Adzuna", **kwargs}

    def _one_job(self):
        return {
            "redirect_url": "https://www.adzuna.co.uk/jobs/details/1",
            "title": "Python Developer",
            "company": {"display_name": "Acme Ltd"},
            "location": {"display_name": "London"},
            "salary_min": 60000,
            "salary_max": 80000,
            "description": "Great role",
            "contract_type": "permanent",
            "contract_time": "full_time",
            "created": "2026-04-01",
        }

    def test_raises_when_credentials_missing(self):
        src = sources.AdzunaSource(self._config())
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ADZUNA_APP_ID", None)
            os.environ.pop("ADZUNA_APP_KEY", None)
            with self.assertRaises(ValueError):
                src.fetch()

    def test_returns_items_from_single_page(self):
        src = sources.AdzunaSource(self._config())
        payload = {"results": [self._one_job()]}
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id123", "ADZUNA_APP_KEY": "key456"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Python Developer")
        self.assertEqual(items[0].location, "London")
        self.assertIn("GBP", items[0].salary)

    def test_stops_when_results_empty(self):
        src = sources.AdzunaSource(self._config())
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value={"results": []}):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_stops_when_payload_not_dict(self):
        src = sources.AdzunaSource(self._config())
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value=None):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.AdzunaSource(self._config())
        job = self._one_job()
        payload = {"results": [job, job]}
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_job_with_missing_title_or_link(self):
        src = sources.AdzunaSource(self._config())
        payload = {"results": [{"redirect_url": "", "title": ""}]}
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_non_dict_job_entry(self):
        src = sources.AdzunaSource(self._config())
        payload = {"results": ["not-a-dict"]}
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_paginates_when_page_is_full(self):
        src = sources.AdzunaSource(self._config())
        full_page = [
            {
                "redirect_url": f"https://adzuna.co.uk/jobs/{i}",
                "title": f"Job {i}",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "London"},
                "salary_min": 0,
                "salary_max": 0,
                "description": "",
                "contract_type": "",
                "contract_time": "",
                "created": "",
            }
            for i in range(50)
        ]
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if len(calls) == 1:
                return {"results": full_page}
            return {"results": []}

        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", side_effect=fake_fetch):
                items = src.fetch()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(items), 50)

    def test_uses_usd_currency_for_non_gb_country(self):
        src = sources.AdzunaSource(self._config(country="us"))
        job = {**self._one_job(), "salary_min": 100000, "salary_max": 120000}
        payload = {"results": [job]}
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertIn("USD", items[0].salary)


class ReedSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"keywords": "python", "location": "london", "display_name": "Reed", **kwargs}

    def _one_job(self):
        return {
            "jobUrl": "https://www.reed.co.uk/jobs/1",
            "jobTitle": "Python Developer",
            "employerName": "Acme Ltd",
            "locationName": "London",
            "minimumSalary": 50000,
            "maximumSalary": 70000,
            "currency": "GBP",
            "jobDescription": "A great role",
            "date": "2026-04-01",
        }

    def test_raises_when_api_key_missing(self):
        src = sources.ReedSource(self._config())
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REED_APP_KEY", None)
            with self.assertRaises(ValueError):
                src.fetch()

    def test_returns_items(self):
        src = sources.ReedSource(self._config())
        payload = {"results": [self._one_job()]}
        with mock.patch.dict(os.environ, {"REED_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Python Developer")
        self.assertIn("GBP", items[0].salary)

    def test_handles_non_dict_payload(self):
        src = sources.ReedSource(self._config())
        with mock.patch.dict(os.environ, {"REED_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json", return_value="not-a-dict"):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.ReedSource(self._config())
        job = self._one_job()
        payload = {"results": [job, job]}
        with mock.patch.dict(os.environ, {"REED_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_non_dict_job_entry(self):
        src = sources.ReedSource(self._config())
        payload = {"results": ["not-a-dict"]}
        with mock.patch.dict(os.environ, {"REED_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_job_with_no_link_or_title(self):
        src = sources.ReedSource(self._config())
        payload = {"results": [{"jobUrl": "", "jobTitle": ""}]}
        with mock.patch.dict(os.environ, {"REED_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_passes_auth_header(self):
        src = sources.ReedSource(self._config())
        captured_headers = []

        def fake_fetch(url, headers=None):
            captured_headers.append(headers)
            return {"results": []}

        with mock.patch.dict(os.environ, {"REED_APP_KEY": "mykey"}):
            with mock.patch.object(sources, "fetch_json", side_effect=fake_fetch):
                src.fetch()
        self.assertIsNotNone(captured_headers[0])
        self.assertIn("Authorization", captured_headers[0])
        self.assertTrue(captured_headers[0]["Authorization"].startswith("Basic "))


class JoobleSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"keywords": "python", "location": "london", "display_name": "Jooble", **kwargs}

    def _one_job(self):
        return {
            "link": "https://jooble.org/job/1",
            "title": "Python Developer",
            "company": "Acme Ltd",
            "location": "London",
            "salary": "£50k-70k",
            "snippet": "A great role",
            "type": "Full-time",
            "updated": "2026-04-01",
        }

    def test_raises_when_api_key_missing(self):
        src = sources.JoobleSource(self._config())
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("JOOBLE_APP_KEY", None)
            with self.assertRaises(ValueError):
                src.fetch()

    def test_returns_items(self):
        src = sources.JoobleSource(self._config())
        payload = {"jobs": [self._one_job()]}
        with mock.patch.dict(os.environ, {"JOOBLE_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json_post", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Python Developer")
        self.assertEqual(items[0].salary, "£50k-70k")

    def test_handles_non_dict_payload(self):
        src = sources.JoobleSource(self._config())
        with mock.patch.dict(os.environ, {"JOOBLE_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json_post", return_value=None):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.JoobleSource(self._config())
        job = self._one_job()
        payload = {"jobs": [job, job]}
        with mock.patch.dict(os.environ, {"JOOBLE_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json_post", return_value=payload):
                items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_non_dict_job(self):
        src = sources.JoobleSource(self._config())
        payload = {"jobs": ["not-a-dict"]}
        with mock.patch.dict(os.environ, {"JOOBLE_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json_post", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_job_with_no_link_or_title(self):
        src = sources.JoobleSource(self._config())
        payload = {"jobs": [{"link": "", "title": ""}]}
        with mock.patch.dict(os.environ, {"JOOBLE_APP_KEY": "testkey"}):
            with mock.patch.object(sources, "fetch_json_post", return_value=payload):
                items = src.fetch()
        self.assertEqual(items, [])


class TheMuseSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"category": "IT & Data", "display_name": "The Muse", **kwargs}

    def _one_job(self):
        return {
            "name": "Data Engineer",
            "refs": {"landing_page": "https://www.themuse.com/jobs/acme/data-engineer"},
            "company": {"name": "Acme Ltd"},
            "locations": [{"name": "New York"}],
            "levels": [{"name": "Mid Level"}],
            "contents": "A great data role",
            "publication_date": "2026-04-01",
        }

    def test_returns_items_from_single_page(self):
        src = sources.TheMuseSource(self._config())
        payload = {"results": [self._one_job()]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Data Engineer")
        self.assertEqual(items[0].location, "New York")

    def test_stops_when_results_empty(self):
        src = sources.TheMuseSource(self._config())
        with mock.patch.object(sources, "fetch_json", return_value={"results": []}):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_stops_when_payload_not_dict(self):
        src = sources.TheMuseSource(self._config())
        with mock.patch.object(sources, "fetch_json", return_value=None):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.TheMuseSource(self._config())
        job = self._one_job()
        payload = {"results": [job, job]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_non_dict_job(self):
        src = sources.TheMuseSource(self._config())
        payload = {"results": ["not-a-dict"]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_job_with_no_link_or_title(self):
        src = sources.TheMuseSource(self._config())
        payload = {"results": [{"name": "", "refs": {"landing_page": ""}}]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_uses_location_param_when_set(self):
        src = sources.TheMuseSource(self._config(location="New York"))
        captured_urls = []

        def fake_fetch(url):
            captured_urls.append(url)
            return {"results": []}

        with mock.patch.object(sources, "fetch_json", side_effect=fake_fetch):
            src.fetch()
        self.assertTrue(any("location" in url for url in captured_urls))

    def test_multiple_locations_joined(self):
        src = sources.TheMuseSource(self._config())
        job = {**self._one_job(), "locations": [{"name": "New York"}, {"name": "Remote"}]}
        with mock.patch.object(sources, "fetch_json", return_value={"results": [job]}):
            items = src.fetch()
        self.assertIn("New York", items[0].location)
        self.assertIn("Remote", items[0].location)

    def test_non_dict_refs_skips_job(self):
        src = sources.TheMuseSource(self._config())
        job = {**self._one_job(), "refs": "not-a-dict"}
        payload = {"results": [job]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])


class ArbeitnowSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"display_name": "Arbeitnow", **kwargs}

    def _one_job(self, remote=False, visa=False):
        return {
            "url": "https://www.arbeitnow.com/jobs/acme/1",
            "title": "Backend Developer",
            "company_name": "Acme Ltd",
            "location": "Berlin",
            "description": "A great backend role",
            "tags": ["python", "django"],
            "job_types": ["full-time"],
            "remote": remote,
            "visa_sponsorship": visa,
        }

    def test_returns_items(self):
        src = sources.ArbeitnowSource(self._config())
        payload = {"data": [self._one_job()]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Backend Developer")
        self.assertEqual(items[0].employment_type, "full-time")

    def test_remote_flag_included_in_description(self):
        src = sources.ArbeitnowSource(self._config())
        payload = {"data": [self._one_job(remote=True)]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertIn("remote", items[0].description)

    def test_visa_flag_included_in_description(self):
        src = sources.ArbeitnowSource(self._config())
        payload = {"data": [self._one_job(visa=True)]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertIn("visa sponsorship", items[0].description)

    def test_stops_when_data_empty(self):
        src = sources.ArbeitnowSource(self._config())
        with mock.patch.object(sources, "fetch_json", return_value={"data": []}):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_stops_when_payload_not_dict(self):
        src = sources.ArbeitnowSource(self._config())
        with mock.patch.object(sources, "fetch_json", return_value=None):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.ArbeitnowSource(self._config())
        job = self._one_job()
        payload = {"data": [job, job]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_non_dict_job(self):
        src = sources.ArbeitnowSource(self._config())
        payload = {"data": ["not-a-dict"]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_job_missing_link_or_title(self):
        src = sources.ArbeitnowSource(self._config())
        payload = {"data": [{"url": "", "title": ""}]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_paginates(self):
        src = sources.ArbeitnowSource(self._config())
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if len(calls) == 1:
                return {"data": [self._one_job()]}
            return {"data": []}

        with mock.patch.object(sources, "fetch_json", side_effect=fake_fetch):
            items = src.fetch()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(items), 1)


class RemotiveSourceTestCase(unittest.TestCase):
    def _config(self, **kwargs):
        return {"category": "software-dev", "display_name": "Remotive", **kwargs}

    def _one_job(self):
        return {
            "url": "https://remotive.com/remote-jobs/software-dev/1",
            "title": "Remote Python Engineer",
            "company_name": "Startup Inc",
            "candidate_required_location": "Worldwide",
            "salary": "$80k-100k",
            "description": "An amazing remote role",
            "job_type": "full_time",
            "publication_date": "2026-04-01",
            "tags": ["python", "remote"],
        }

    def test_returns_items(self):
        src = sources.RemotiveSource(self._config())
        payload = {"jobs": [self._one_job()]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Remote Python Engineer")
        self.assertEqual(items[0].salary, "$80k-100k")

    def test_handles_non_dict_payload(self):
        src = sources.RemotiveSource(self._config())
        with mock.patch.object(sources, "fetch_json", return_value=None):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_deduplicates_by_link(self):
        src = sources.RemotiveSource(self._config())
        job = self._one_job()
        payload = {"jobs": [job, job]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)

    def test_skips_non_dict_job(self):
        src = sources.RemotiveSource(self._config())
        payload = {"jobs": ["not-a-dict"]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_skips_job_with_no_link_or_title(self):
        src = sources.RemotiveSource(self._config())
        payload = {"jobs": [{"url": "", "title": ""}]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(items, [])

    def test_tags_string_included_in_description(self):
        src = sources.RemotiveSource(self._config())
        job = {**self._one_job(), "tags": "python, remote"}
        payload = {"jobs": [job]}
        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = src.fetch()
        self.assertEqual(len(items), 1)
        self.assertIn("python, remote", items[0].description)


class CreateSourceTestCase(unittest.TestCase):
    def test_greenhouse(self):
        src = sources.create_source({"platform": "greenhouse", "board_token": "acme"})
        self.assertIsInstance(src, sources.GreenhouseSource)

    def test_lever(self):
        src = sources.create_source({"platform": "lever", "site": "acme"})
        self.assertIsInstance(src, sources.LeverSource)

    def test_ashby(self):
        src = sources.create_source({"platform": "ashby", "job_board_name": "acme"})
        self.assertIsInstance(src, sources.AshbySource)

    def test_workable(self):
        src = sources.create_source({"platform": "workable", "account_subdomain": "acme"})
        self.assertIsInstance(src, sources.WorkableSource)

    def test_generic_html(self):
        src = sources.create_source({"platform": "generic_html", "start_urls": ["https://example.com"]})
        self.assertIsInstance(src, sources.GenericHtmlSource)

    def test_efc_html_type(self):
        src = sources.create_source({"type": "efc_html", "url": "https://example.com"})
        self.assertIsInstance(src, sources.EfcHtmlSource)

    def test_adzuna_type(self):
        src = sources.create_source({"type": "adzuna"})
        self.assertIsInstance(src, sources.AdzunaSource)

    def test_reed_type(self):
        src = sources.create_source({"type": "reed"})
        self.assertIsInstance(src, sources.ReedSource)

    def test_jooble_type(self):
        src = sources.create_source({"type": "jooble"})
        self.assertIsInstance(src, sources.JoobleSource)

    def test_themuse_type(self):
        src = sources.create_source({"type": "themuse"})
        self.assertIsInstance(src, sources.TheMuseSource)

    def test_arbeitnow_type(self):
        src = sources.create_source({"type": "arbeitnow"})
        self.assertIsInstance(src, sources.ArbeitnowSource)

    def test_remotive_type(self):
        src = sources.create_source({"type": "remotive"})
        self.assertIsInstance(src, sources.RemotiveSource)

    def test_default_returns_rss(self):
        src = sources.create_source({"url": "https://example.com/feed.rss"})
        self.assertIsInstance(src, sources.RssSource)


class FetchCompanyBoardItemsDispatchTestCase(unittest.TestCase):
    def test_dispatches_lever(self):
        board = {"platform": "lever", "site": "acme", "display_name": "Acme", "instance": "global"}
        with mock.patch.object(sources, "fetch_lever_board_jobs", return_value=[]) as m:
            sources.fetch_company_board_items(board)
            m.assert_called_once_with(board)

    def test_dispatches_ashby(self):
        board = {"platform": "ashby", "job_board_name": "acme", "display_name": "Acme"}
        with mock.patch.object(sources, "fetch_ashby_board_jobs", return_value=[]) as m:
            sources.fetch_company_board_items(board)
            m.assert_called_once_with(board)

    def test_dispatches_workable(self):
        board = {"platform": "workable", "account_subdomain": "acme", "display_name": "Acme", "mode": "public"}
        with mock.patch.object(sources, "fetch_workable_board_jobs", return_value=[]) as m:
            sources.fetch_company_board_items(board)
            m.assert_called_once_with(board)

    def test_dispatches_generic_html(self):
        board = {
            "platform": "generic_html",
            "start_urls": ["https://example.com"],
            "allowed_domains": ["example.com"],
            "job_link_keywords": [],
            "job_link_regexes": [],
            "_job_link_patterns": [],
            "max_job_pages": 10,
            "display_name": "Example",
        }
        with mock.patch.object(sources.GenericHtmlSource, "fetch", return_value=[]):
            result = sources.fetch_company_board_items(board)
        self.assertEqual(result, [])


class ParseSourceItemsTestCase(unittest.TestCase):
    def test_efc_html_type(self):
        source_config = {"type": "efc_html", "display_name": "EFC", "url": "https://example.com"}
        html = """<a href="https://www.efinancialcareers.com/jobs-IT-Support.id123">IT Support Analyst</a>"""
        items = sources.parse_source_items(source_config, html)
        self.assertIsInstance(items, list)

    def test_default_rss_type(self):
        source_config = {"type": "rss", "display_name": "Feed"}
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Test Job</title>
            <link>https://example.com/job/1</link>
          </item>
        </channel></rss>"""
        items = sources.parse_source_items(source_config, xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Test Job")


if __name__ == "__main__":
    unittest.main()
