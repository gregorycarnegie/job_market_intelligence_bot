import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

from jobbot import sources


class FormatJsonldAddressTestCase(unittest.TestCase):
    def test_formats_full_address(self) -> None:
        address = {
            "streetAddress": "1 Main St",
            "addressLocality": "London",
            "addressCountry": "GB",
        }
        result = sources.format_jsonld_address(address)
        self.assertIn("London", result)
        self.assertIn("GB", result)

    def test_returns_empty_for_non_dict(self) -> None:
        self.assertEqual(sources.format_jsonld_address("London"), "")

    def test_returns_empty_for_empty_dict(self) -> None:
        self.assertEqual(sources.format_jsonld_address({}), "")


class ExtractJsonldLocationTextTestCase(unittest.TestCase):
    def test_remote_job_location_type(self) -> None:
        node = {"jobLocationType": "TELECOMMUTE"}
        result = sources.extract_jsonld_location_text(node)
        self.assertIn("remote", result)

    def test_extracts_place_location(self) -> None:
        node = {
            "jobLocation": {
                "@type": "Place",
                "address": {"addressLocality": "London", "addressCountry": "GB"},
            }
        }
        result = sources.extract_jsonld_location_text(node)
        self.assertIn("London", result)

    def test_handles_list_of_locations(self) -> None:
        node = {
            "jobLocation": [
                {"@type": "Place", "address": {"addressLocality": "London"}},
                {"@type": "Place", "address": {"addressLocality": "Manchester"}},
            ]
        }
        result = sources.extract_jsonld_location_text(node)
        self.assertIn("London", result)
        self.assertIn("Manchester", result)

    def test_applicant_location_requirements(self) -> None:
        node = {
            "applicantLocationRequirements": {
                "@type": "Country",
                "address": {"addressCountry": "GB"},
            }
        }
        result = sources.extract_jsonld_location_text(node)
        self.assertIn("GB", result)

    def test_empty_node(self) -> None:
        self.assertEqual(sources.extract_jsonld_location_text({}), "")


class NormalizeSalaryUnitTextTestCase(unittest.TestCase):
    def test_year(self) -> None:
        self.assertEqual(sources.normalize_salary_unit_text("year"), "year")

    def test_annual(self) -> None:
        self.assertEqual(sources.normalize_salary_unit_text("annual"), "year")

    def test_month(self) -> None:
        self.assertEqual(sources.normalize_salary_unit_text("month"), "month")

    def test_hour(self) -> None:
        self.assertEqual(sources.normalize_salary_unit_text("hour"), "hour")

    def test_unknown_defaults_to_year(self) -> None:
        self.assertEqual(sources.normalize_salary_unit_text("biweekly"), "year")


class FormatProviderSalaryTextTestCase(unittest.TestCase):
    def test_range(self) -> None:
        result = sources.format_provider_salary_text(40000, 60000, "GBP", "year")
        self.assertIn("40,000", result)
        self.assertIn("60,000", result)

    def test_minimum_only(self) -> None:
        result = sources.format_provider_salary_text(50000, 0, "GBP", "year")
        self.assertIn("50,000", result)

    def test_maximum_only(self) -> None:
        result = sources.format_provider_salary_text(0, 55000, "USD", "year")
        self.assertIn("55,000", result)

    def test_all_zero_returns_empty(self) -> None:
        self.assertEqual(sources.format_provider_salary_text(0, 0, "GBP", "year"), "")

    def test_equal_min_max(self) -> None:
        result = sources.format_provider_salary_text(50000, 50000, "GBP", "year")
        self.assertIn("50,000", result)


class ExtractJsonldSalaryTextTestCase(unittest.TestCase):
    def test_extracts_salary_with_value_dict(self) -> None:
        node = {
            "baseSalary": {
                "currency": "GBP",
                "value": {
                    "minValue": 40000,
                    "maxValue": 60000,
                    "unitText": "year",
                },
            }
        }
        result = sources.extract_jsonld_salary_text(node)
        self.assertIn("GBP", result)
        self.assertIn("40,000", result)

    def test_extracts_salary_with_flat_fields(self) -> None:
        node = {
            "baseSalary": {
                "currency": "USD",
                "minValue": 80000,
                "maxValue": 100000,
                "unitText": "year",
            }
        }
        result = sources.extract_jsonld_salary_text(node)
        self.assertIn("USD", result)

    def test_returns_empty_when_no_base_salary(self) -> None:
        self.assertEqual(sources.extract_jsonld_salary_text({}), "")

    def test_handles_list_base_salary(self) -> None:
        node = {
            "baseSalary": [
                {"currency": "GBP", "value": {"minValue": 50000, "maxValue": 70000, "unitText": "year"}},
            ]
        }
        result = sources.extract_jsonld_salary_text(node)
        self.assertIn("50,000", result)


class JobpostingNodeToItemTestCase(unittest.TestCase):
    def test_converts_valid_node(self) -> None:
        node = {
            "@type": "JobPosting",
            "title": "IT Support Engineer",
            "url": "https://example.com/jobs/1",
            "description": "A great role",
            "hiringOrganization": {"@type": "Organization", "name": "Acme"},
        }
        item = sources.jobposting_node_to_item(node, "Acme")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.title, "IT Support Engineer")
        self.assertEqual(item.link, "https://example.com/jobs/1")
        self.assertIn("Acme", item.description)

    def test_returns_none_when_missing_title(self) -> None:
        node = {"url": "https://example.com/jobs/1"}
        self.assertIsNone(sources.jobposting_node_to_item(node, "Acme"))

    def test_returns_none_when_missing_link(self) -> None:
        node = {"title": "Engineer"}
        self.assertIsNone(sources.jobposting_node_to_item(node, "Acme"))

    def test_uses_fallback_url(self) -> None:
        node = {"title": "Engineer", "name": "Engineer"}
        item = sources.jobposting_node_to_item(node, "Acme", fallback_url="https://example.com/fallback")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.link, "https://example.com/fallback")

    def test_uses_name_field_as_title(self) -> None:
        node = {"name": "IT Technician", "url": "https://example.com/jobs/2"}
        item = sources.jobposting_node_to_item(node, "Acme")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.title, "IT Technician")


class ExtractAnchorLinksTestCase(unittest.TestCase):
    def test_extracts_absolute_links(self) -> None:
        html = '<a href="https://example.com/jobs/1">Job 1</a>'
        links = sources.extract_anchor_links(html, "https://example.com")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][0], "https://example.com/jobs/1")
        self.assertEqual(links[0][1], "Job 1")

    def test_resolves_relative_links(self) -> None:
        html = '<a href="/jobs/2">Job 2</a>'
        links = sources.extract_anchor_links(html, "https://example.com")
        self.assertEqual(links[0][0], "https://example.com/jobs/2")

    def test_skips_hash_links(self) -> None:
        html = '<a href="#section">Skip</a>'
        links = sources.extract_anchor_links(html, "https://example.com")
        self.assertEqual(links, [])

    def test_skips_mailto_links(self) -> None:
        html = '<a href="mailto:hr@example.com">Email</a>'
        links = sources.extract_anchor_links(html, "https://example.com")
        self.assertEqual(links, [])

    def test_skips_javascript_links(self) -> None:
        html = '<a href="javascript:void(0)">Click</a>'
        links = sources.extract_anchor_links(html, "https://example.com")
        self.assertEqual(links, [])


class UrlMatchesAllowedDomainsTestCase(unittest.TestCase):
    def test_matches_exact_domain(self) -> None:
        self.assertTrue(
            sources.url_matches_allowed_domains("https://example.com/jobs/1", ["example.com"])
        )

    def test_matches_subdomain(self) -> None:
        self.assertTrue(
            sources.url_matches_allowed_domains("https://boards.example.com/jobs/1", ["example.com"])
        )

    def test_rejects_unrelated_domain(self) -> None:
        self.assertFalse(
            sources.url_matches_allowed_domains("https://evil.com/jobs/1", ["example.com"])
        )

    def test_empty_allowed_domains_allows_all(self) -> None:
        self.assertTrue(
            sources.url_matches_allowed_domains("https://anything.com/jobs/1", [])
        )

    def test_invalid_url_returns_false(self) -> None:
        self.assertFalse(sources.url_matches_allowed_domains("not-a-url", ["example.com"]))


class FallbackGenericJobItemTestCase(unittest.TestCase):
    def test_returns_item_with_title_and_description(self) -> None:
        html = "<title>Software Engineer</title><p>" + "X" * 50 + "</p>"
        item = sources.fallback_generic_job_item(html, "https://example.com/job", "Acme")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.title, "Software Engineer")
        self.assertEqual(item.link, "https://example.com/job")

    def test_returns_none_when_no_title(self) -> None:
        html = "<p>No title here</p>"
        self.assertIsNone(sources.fallback_generic_job_item(html, "https://example.com/job", "Acme"))

    def test_returns_none_when_description_too_short(self) -> None:
        html = "<title>Role</title><p>short</p>"
        self.assertIsNone(sources.fallback_generic_job_item(html, "https://example.com/job", "Acme"))


class SanitizeXmlTestCase(unittest.TestCase):
    def test_replaces_nbsp(self) -> None:
        self.assertIn(" ", sources.sanitize_xml("hello&nbsp;world"))

    def test_escapes_bare_ampersand(self) -> None:
        result = sources.sanitize_xml("fish & chips")
        self.assertIn("&amp;", result)

    def test_preserves_valid_entities(self) -> None:
        result = sources.sanitize_xml("&amp; &lt; &gt;")
        self.assertIn("&amp;", result)
        self.assertIn("&lt;", result)


class LocalNameTestCase(unittest.TestCase):
    def test_strips_namespace(self) -> None:
        self.assertEqual(sources.local_name("{http://www.w3.org/2005/Atom}entry"), "entry")

    def test_no_namespace_passthrough(self) -> None:
        self.assertEqual(sources.local_name("item"), "item")


class ParseStructuredFeedTestCase(unittest.TestCase):
    def test_parses_rss_feed(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>IT Support Engineer</title>
            <link>https://example.com/job/1</link>
            <description>A great role</description>
          </item>
        </channel></rss>"""
        items = sources.parse_structured_feed(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Support Engineer")
        self.assertEqual(items[0].link, "https://example.com/job/1")

    def test_deduplicates_by_link(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item><title>Job A</title><link>https://example.com/job/1</link></item>
          <item><title>Job A copy</title><link>https://example.com/job/1</link></item>
        </channel></rss>"""
        items = sources.parse_structured_feed(xml)
        self.assertEqual(len(items), 1)

    def test_parses_atom_feed(self) -> None:
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Analyst Role</title>
            <link href="https://example.com/analyst"/>
            <summary>Great opportunity</summary>
          </entry>
        </feed>"""
        items = sources.parse_structured_feed(xml)
        self.assertEqual(len(items), 1)
        self.assertIn("Analyst", items[0].title)


class ParseFallbackFeedTestCase(unittest.TestCase):
    def test_parses_basic_items(self) -> None:
        xml = """
        <rss><channel>
          <item>
            <title>Support Role</title>
            <link>https://example.com/support</link>
            <description>Good job</description>
          </item>
        </channel></rss>"""
        items = sources.parse_fallback_feed(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Support Role")

    def test_parses_link_with_href_attribute(self) -> None:
        xml = """
        <feed>
          <entry>
            <title>Role</title>
            <link href="https://example.com/role"/>
          </entry>
        </feed>"""
        items = sources.parse_fallback_feed(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].link, "https://example.com/role")


class ParseFeedItemsTestCase(unittest.TestCase):
    def test_parses_valid_xml(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>IT Support</title>
            <link>https://example.com/it</link>
          </item>
        </channel></rss>"""
        items = sources.parse_feed_items(xml)
        self.assertEqual(len(items), 1)

    def test_falls_back_on_parse_error(self) -> None:
        malformed = """
        <rss><channel>
          <item>
            <title>IT Support</title>
            <link>https://example.com/it</link>
          </item>
        </channel></rss>"""
        items = sources.parse_feed_items(malformed)
        self.assertIsInstance(items, list)

    def test_raises_when_totally_unparseable(self) -> None:
        with self.assertRaises(ElementTree.ParseError):
            sources.parse_feed_items("<<<not xml at all>>>")


class ParseEfinancialcareersHtmlTestCase(unittest.TestCase):
    def test_extracts_job_links(self) -> None:
        html = """
        <a href="https://www.efinancialcareers.com/jobs-IT-Support.id123456">
          IT Support Analyst
        </a>
        """
        items = sources.parse_efinancialcareers_html(html, {"context_terms": "london finance"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Support Analyst")
        self.assertIn("efinancialcareers.com", items[0].link)

    def test_skips_short_titles(self) -> None:
        html = """<a href="/jobs-it.id999">IT</a>"""
        items = sources.parse_efinancialcareers_html(html, {})
        self.assertEqual(items, [])

    def test_skips_action_titles(self) -> None:
        html = """<a href="/jobs-apply.id888">Apply Now</a>"""
        items = sources.parse_efinancialcareers_html(html, {})
        self.assertEqual(items, [])

    def test_deduplicates_links(self) -> None:
        html = """
        <a href="/jobs-IT-Support.id123">IT Support Analyst</a>
        <a href="/jobs-IT-Support.id123">IT Support Analyst copy</a>
        """
        items = sources.parse_efinancialcareers_html(html, {})
        self.assertLessEqual(len(items), 1)


class NormalizeCompanyBoardTestCase(unittest.TestCase):
    def test_normalizes_greenhouse_board(self) -> None:
        raw = {"name": "Monzo", "platform": "greenhouse", "board_token": "monzo"}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertEqual(board["name"], "Monzo")
        self.assertEqual(board["platform"], "greenhouse")
        self.assertEqual(board["board_token"], "monzo")

    def test_normalizes_lever_board(self) -> None:
        raw = {"name": "Acme", "platform": "lever", "site": "acme-corp"}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertEqual(board["site"], "acme-corp")

    def test_normalizes_ashby_board(self) -> None:
        raw = {"name": "Startup", "platform": "ashby", "job_board_name": "startup"}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertEqual(board["job_board_name"], "startup")

    def test_normalizes_workable_board(self) -> None:
        raw = {"name": "Corp", "platform": "workable", "account_subdomain": "corp"}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertEqual(board["account_subdomain"], "corp")

    def test_normalizes_generic_html_board(self) -> None:
        raw = {
            "name": "Blog",
            "platform": "generic_html",
            "start_urls": ["https://blog.example.com/jobs"],
        }
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertIn("blog.example.com", cast(list[str], board["allowed_domains"]))

    def test_returns_none_for_missing_name(self) -> None:
        raw = {"platform": "greenhouse", "board_token": "acme"}
        self.assertIsNone(sources.normalize_company_board(raw))

    def test_returns_none_for_unsupported_platform(self) -> None:
        raw = {"name": "Acme", "platform": "unknown_platform"}
        self.assertIsNone(sources.normalize_company_board(raw))

    def test_returns_none_for_missing_required_fields(self) -> None:
        raw = {"name": "Acme", "platform": "greenhouse"}
        self.assertIsNone(sources.normalize_company_board(raw))

    def test_min_interval_clamped_to_minimum(self) -> None:
        raw = {"name": "Acme", "platform": "greenhouse", "board_token": "acme", "min_interval_seconds": 10}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertGreaterEqual(cast(int, board["min_interval_seconds"]), 300)

    def test_display_name_falls_back_to_name(self) -> None:
        raw = {"name": "Acme Corp", "platform": "greenhouse", "board_token": "acme"}
        board = sources.normalize_company_board(raw)
        self.assertIsNotNone(board)
        assert board is not None
        self.assertEqual(board["display_name"], "Acme Corp")


class LoadCompanyBoardsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def _write(self, filename: str, data: object) -> str:
        path = str(Path(self.tempdir.name) / filename)
        Path(path).write_text(
            data if isinstance(data, str) else __import__("json").dumps(data),
            encoding="utf-8",
        )
        return path

    def test_loads_valid_boards(self) -> None:
        path = self._write(
            "boards.json",
            [{"name": "Monzo", "platform": "greenhouse", "board_token": "monzo"}],
        )
        boards = sources.load_company_boards(path)
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0]["name"], "Monzo")

    def test_returns_empty_for_missing_file(self) -> None:
        self.assertEqual(sources.load_company_boards("/nonexistent/path.json"), [])

    def test_returns_empty_for_invalid_json(self) -> None:
        path = self._write("bad.json", "not json at all {{{")
        self.assertEqual(sources.load_company_boards(path), [])

    def test_returns_empty_for_non_list_json(self) -> None:
        path = self._write("bad.json", {"key": "value"})
        self.assertEqual(sources.load_company_boards(path), [])

    def test_skips_invalid_boards_and_keeps_valid(self) -> None:
        path = self._write(
            "mixed.json",
            [
                {"name": "Monzo", "platform": "greenhouse", "board_token": "monzo"},
                {"platform": "greenhouse"},
                "not a dict",
            ],
        )
        boards = sources.load_company_boards(path)
        self.assertEqual(len(boards), 1)

    def test_skips_duplicate_names(self) -> None:
        path = self._write(
            "dupes.json",
            [
                {"name": "Monzo", "platform": "greenhouse", "board_token": "monzo"},
                {"name": "Monzo", "platform": "greenhouse", "board_token": "monzo2"},
            ],
        )
        boards = sources.load_company_boards(path)
        self.assertEqual(len(boards), 1)


class FetchGreenhouseBoardJobsTestCase(unittest.TestCase):
    def test_parses_jobs_payload(self) -> None:
        board = {"board_token": "acme", "display_name": "Acme"}
        payload = {
            "jobs": [
                {
                    "title": "IT Support Engineer",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    "content": "A great role",
                    "location": {"name": "London"},
                    "departments": [{"name": "IT"}],
                    "offices": [{"name": "HQ", "location": "London"}],
                }
            ]
        }
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = sources.fetch_greenhouse_board_jobs(board)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Support Engineer")
        self.assertIn("London", items[0].description)


class FetchLeverBoardJobsTestCase(unittest.TestCase):
    def test_parses_single_page(self) -> None:
        board = {"site": "acme", "display_name": "Acme", "instance": "global"}
        jobs = [
            {
                "text": "IT Support",
                "hostedUrl": "https://jobs.lever.co/acme/1",
                "descriptionPlain": "A great role",
                "categories": {"location": "London", "team": "IT"},
                "salaryRange": {},
            }
        ]
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_json", return_value=jobs):
            items = sources.fetch_lever_board_jobs(board)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Support")
        self.assertIn("London", items[0].description)

    def test_uses_eu_base_url_for_eu_instance(self) -> None:
        board = {"site": "acme", "display_name": "Acme", "instance": "eu"}
        import unittest.mock as mock

        urls_called = []

        def fake_fetch_json(url: str, headers=None):
            urls_called.append(url)
            return []

        with mock.patch.object(sources, "fetch_json", side_effect=fake_fetch_json):
            sources.fetch_lever_board_jobs(board)

        self.assertTrue(any("eu.lever.co" in url for url in urls_called))


class FetchAshbyBoardJobsTestCase(unittest.TestCase):
    def test_parses_jobs(self) -> None:
        board = {"job_board_name": "startup", "display_name": "Startup"}
        payload = {
            "jobs": [
                {
                    "title": "IT Technician",
                    "jobUrl": "https://jobs.ashbyhq.com/startup/1",
                    "location": "London",
                    "isListed": True,
                    "compensation": {"scrapeableCompensationSalarySummary": "£40k-60k"},
                }
            ]
        }
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = sources.fetch_ashby_board_jobs(board)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Technician")

    def test_skips_unlisted_jobs(self) -> None:
        board = {"job_board_name": "startup", "display_name": "Startup"}
        payload = {
            "jobs": [{"title": "Secret Role", "jobUrl": "https://jobs.ashbyhq.com/startup/2", "isListed": False}]
        }
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = sources.fetch_ashby_board_jobs(board)

        self.assertEqual(items, [])


class FetchWorkableBoardJobsTestCase(unittest.TestCase):
    def test_parses_public_mode(self) -> None:
        board = {"account_subdomain": "acme", "display_name": "Acme", "mode": "public", "name": "acme"}
        payload = {
            "jobs": [
                {
                    "title": "IT Support",
                    "application_url": "https://acme.workable.com/j/1",
                    "location": {"location_str": "London", "country": "UK"},
                    "salary": {},
                }
            ]
        }
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_json", return_value=payload):
            items = sources.fetch_workable_board_jobs(board)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "IT Support")

    def test_raises_when_spi_token_missing(self) -> None:
        board = {
            "account_subdomain": "acme",
            "display_name": "Acme",
            "mode": "spi",
            "api_token_env": "MISSING_VAR",
            "name": "acme",
        }
        with self.assertRaises(ValueError):
            sources.fetch_workable_board_jobs(board)


class FetchCompanyBoardItemsTestCase(unittest.TestCase):
    def test_dispatches_to_greenhouse(self) -> None:
        board = {"platform": "greenhouse", "board_token": "acme", "display_name": "Acme"}
        import unittest.mock as mock

        with mock.patch.object(sources, "fetch_greenhouse_board_jobs", return_value=[]) as mock_handler:
            sources.fetch_company_board_items(board)
            mock_handler.assert_called_once_with(board)

    def test_returns_empty_for_unknown_platform(self) -> None:
        board = {"platform": "unknown"}
        self.assertEqual(sources.fetch_company_board_items(board), [])


if __name__ == "__main__":
    unittest.main()
