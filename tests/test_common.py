import unittest
from datetime import timezone

from jobbot.common import (
    append_reason,
    build_focus_phrases,
    build_pattern_entries,
    build_review_fingerprints,
    compile_skill_pattern,
    contains_phrase,
    dedupe_preserving_order,
    ensure_sentence,
    expand_location_terms,
    find_pattern_matches,
    join_text_parts,
    latest_application_timestamp,
    normalize_company_name,
    normalize_link_for_fingerprint,
    normalize_string_list,
    normalize_url_list,
    parse_bool,
    parse_iso_utc,
    safe_int,
    split_title_and_company,
    strip_cdata,
    truncate_text,
)


class StripCdataTestCase(unittest.TestCase):
    def test_strips_cdata_wrapper(self) -> None:
        self.assertEqual(strip_cdata("<![CDATA[hello world]]>"), "hello world")

    def test_returns_plain_text_unchanged(self) -> None:
        self.assertEqual(strip_cdata("  plain text  "), "plain text")

    def test_empty_cdata(self) -> None:
        self.assertEqual(strip_cdata("<![CDATA[]]>"), "")


class CompileSkillPatternTestCase(unittest.TestCase):
    def test_returns_none_for_empty_string(self) -> None:
        self.assertIsNone(compile_skill_pattern(""))

    def test_returns_none_for_whitespace(self) -> None:
        self.assertIsNone(compile_skill_pattern("   "))

    def test_compiled_pattern_matches_whole_word(self) -> None:
        pattern = compile_skill_pattern("python")
        self.assertIsNotNone(pattern)
        assert pattern is not None
        self.assertIsNotNone(pattern.search("knows python well"))
        self.assertIsNone(pattern.search("pythonic"))

    def test_compiled_pattern_handles_spaces_as_flexible_whitespace(self) -> None:
        pattern = compile_skill_pattern("active directory")
        self.assertIsNotNone(pattern)
        assert pattern is not None
        self.assertIsNotNone(pattern.search("uses Active  Directory"))


class ParseBoolTestCase(unittest.TestCase):
    def test_true_bool_passthrough(self) -> None:
        self.assertTrue(parse_bool(True))

    def test_false_bool_passthrough(self) -> None:
        self.assertFalse(parse_bool(False))

    def test_int_nonzero_is_true(self) -> None:
        self.assertTrue(parse_bool(1))

    def test_int_zero_is_false(self) -> None:
        self.assertFalse(parse_bool(0))

    def test_float_truthy(self) -> None:
        self.assertTrue(parse_bool(0.5))

    def test_string_true_values(self) -> None:
        for val in ("true", "True", "1", "yes", "on"):
            self.assertTrue(parse_bool(val), f"expected True for {val!r}")

    def test_string_false_values(self) -> None:
        for val in ("false", "False", "0", "no", "off"):
            self.assertFalse(parse_bool(val), f"expected False for {val!r}")

    def test_ambiguous_returns_default(self) -> None:
        self.assertFalse(parse_bool("maybe"))
        self.assertTrue(parse_bool("maybe", default=True))


class SafeIntTestCase(unittest.TestCase):
    def test_converts_string_int(self) -> None:
        self.assertEqual(safe_int("42"), 42)

    def test_returns_default_for_none(self) -> None:
        self.assertEqual(safe_int(None, 7), 7)

    def test_returns_default_for_non_numeric_string(self) -> None:
        self.assertEqual(safe_int("abc", 5), 5)

    def test_returns_default_for_empty_string(self) -> None:
        self.assertEqual(safe_int("", 3), 3)


class NormalizeCompanyNameTestCase(unittest.TestCase):
    def test_strips_ltd(self) -> None:
        self.assertEqual(normalize_company_name("Acme Ltd"), "acme")

    def test_strips_limited(self) -> None:
        self.assertEqual(normalize_company_name("Widgets Limited"), "widgets")

    def test_strips_inc(self) -> None:
        self.assertEqual(normalize_company_name("BigCorp Inc"), "bigcorp")

    def test_passes_through_plain_name(self) -> None:
        self.assertEqual(normalize_company_name("Monzo"), "monzo")

    def test_empty_string(self) -> None:
        self.assertEqual(normalize_company_name(""), "")


class SplitTitleAndCompanyTestCase(unittest.TestCase):
    def test_splits_on_at(self) -> None:
        role, company = split_title_and_company("IT Support Engineer at Monzo")
        self.assertEqual(role, "IT Support Engineer")
        self.assertEqual(company, "Monzo")

    def test_splits_on_pipe(self) -> None:
        role, company = split_title_and_company("Help Desk Technician | Acme Corp")
        self.assertEqual(role, "Help Desk Technician")
        self.assertEqual(company, "Acme Corp")

    def test_splits_on_dash(self) -> None:
        role, company = split_title_and_company("Systems Administrator - Contoso")
        self.assertEqual(role, "Systems Administrator")
        self.assertEqual(company, "Contoso")

    def test_no_separator_returns_full_title_and_empty_company(self) -> None:
        role, company = split_title_and_company("IT Support Engineer")
        self.assertEqual(role, "IT Support Engineer")
        self.assertEqual(company, "")

    def test_empty_string(self) -> None:
        role, company = split_title_and_company("")
        self.assertEqual(role, "")
        self.assertEqual(company, "")


class NormalizeLinkForFingerprintTestCase(unittest.TestCase):
    def test_strips_tracking_params(self) -> None:
        url = "https://example.com/jobs/123?ref=linkedin&utm_source=email"
        result = normalize_link_for_fingerprint(url)
        self.assertNotIn("ref=", result)
        self.assertNotIn("utm_source=", result)
        self.assertIn("/jobs/123", result)

    def test_strips_trailing_slash_from_path(self) -> None:
        result = normalize_link_for_fingerprint("https://example.com/jobs/")
        self.assertNotIn("/jobs/", result)
        self.assertIn("/jobs", result)

    def test_lowercases_scheme_and_host(self) -> None:
        result = normalize_link_for_fingerprint("HTTPS://Example.COM/jobs/1")
        self.assertTrue(result.startswith("https://example.com/"))

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(normalize_link_for_fingerprint(""), "")

    def test_no_scheme_returns_raw(self) -> None:
        raw = "not-a-url"
        self.assertEqual(normalize_link_for_fingerprint(raw), raw)

    def test_preserves_non_tracking_params(self) -> None:
        result = normalize_link_for_fingerprint("https://example.com/jobs?page=2")
        self.assertIn("page=2", result)


class BuildReviewFingerprintsTestCase(unittest.TestCase):
    def test_includes_link_fingerprint(self) -> None:
        fps = build_review_fingerprints("IT Support Engineer at Monzo", "", "https://example.com/jobs/1")
        self.assertTrue(any(fp.startswith("link:") for fp in fps))

    def test_includes_role_company_fingerprint(self) -> None:
        fps = build_review_fingerprints("IT Support Engineer at Monzo", "", "https://example.com/jobs/1")
        self.assertTrue(any(fp.startswith("role_company:") for fp in fps))

    def test_falls_back_to_text_when_no_link_and_no_company(self) -> None:
        fps = build_review_fingerprints("Miscellaneous role", "Some description here", "")
        self.assertTrue(any(fp.startswith("text:") for fp in fps))

    def test_empty_inputs_return_empty(self) -> None:
        fps = build_review_fingerprints("", "", "")
        self.assertEqual(fps, [])


class EnsureSentenceTestCase(unittest.TestCase):
    def test_adds_period_when_missing(self) -> None:
        self.assertEqual(ensure_sentence("good experience"), "good experience.")

    def test_leaves_period_alone(self) -> None:
        self.assertEqual(ensure_sentence("good experience."), "good experience.")

    def test_leaves_exclamation_alone(self) -> None:
        self.assertEqual(ensure_sentence("great!"), "great!")

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(ensure_sentence(""), "")


class TruncateTextTestCase(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        self.assertEqual(truncate_text("short", 50), "short")

    def test_long_text_is_truncated(self) -> None:
        result = truncate_text("word " * 60, 50)
        self.assertLessEqual(len(result), 53)
        self.assertTrue(result.endswith("..."))

    def test_truncate_at_word_boundary(self) -> None:
        result = truncate_text("alpha beta gamma delta", 14)
        self.assertNotIn("elta", result)


class ParseIsoUtcTestCase(unittest.TestCase):
    def test_parses_z_suffix(self) -> None:
        result = parse_iso_utc("2026-04-04T10:00:00Z")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.year, 2026)

    def test_parses_plus_offset(self) -> None:
        result = parse_iso_utc("2026-04-04T10:00:00+00:00")
        self.assertIsNotNone(result)

    def test_returns_none_for_empty(self) -> None:
        self.assertIsNone(parse_iso_utc(""))

    def test_returns_none_for_invalid(self) -> None:
        self.assertIsNone(parse_iso_utc("not-a-date"))


class LatestApplicationTimestampTestCase(unittest.TestCase):
    def test_returns_most_recent_timestamp(self) -> None:
        application = {
            "first_seen_utc": "2026-01-01T00:00:00Z",
            "last_seen_utc": "2026-03-01T00:00:00Z",
            "rejected_at_utc": "2026-04-01T00:00:00Z",
        }
        result = latest_application_timestamp(application)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.month, 4)

    def test_returns_none_for_empty(self) -> None:
        self.assertIsNone(latest_application_timestamp({}))


class DedupePreservingOrderTestCase(unittest.TestCase):
    def test_removes_duplicates(self) -> None:
        self.assertEqual(dedupe_preserving_order(["a", "b", "a", "c"]), ["a", "b", "c"])

    def test_preserves_order(self) -> None:
        self.assertEqual(dedupe_preserving_order(["c", "a", "b"]), ["c", "a", "b"])

    def test_skips_empty_strings(self) -> None:
        self.assertEqual(dedupe_preserving_order(["a", "", "b"]), ["a", "b"])


class NormalizeStringListTestCase(unittest.TestCase):
    def test_dedupes_and_normalizes(self) -> None:
        result = normalize_string_list(["Hello", "hello", "World"], lower=True)
        self.assertIn("hello", result)
        self.assertIn("world", result)
        self.assertEqual(len(result), 2)

    def test_handles_non_list_input(self) -> None:
        result = normalize_string_list("single", lower=False)
        self.assertEqual(result, ["single"])

    def test_handles_none(self) -> None:
        self.assertEqual(normalize_string_list(None), [])


class NormalizeUrlListTestCase(unittest.TestCase):
    def test_filters_non_http(self) -> None:
        result = normalize_url_list(["https://example.com", "not-a-url", "http://foo.com"])
        self.assertIn("https://example.com", result)
        self.assertIn("http://foo.com", result)
        self.assertNotIn("not-a-url", result)

    def test_dedupes(self) -> None:
        result = normalize_url_list(["https://example.com", "https://example.com"])
        self.assertEqual(len(result), 1)


class AppendReasonTestCase(unittest.TestCase):
    def test_adds_new_reason(self) -> None:
        reasons: list[str] = []
        append_reason(reasons, "matched python")
        self.assertIn("matched python", reasons)

    def test_does_not_add_duplicate(self) -> None:
        reasons = ["matched python"]
        append_reason(reasons, "matched python")
        self.assertEqual(len(reasons), 1)

    def test_ignores_empty_string(self) -> None:
        reasons: list[str] = []
        append_reason(reasons, "")
        self.assertEqual(reasons, [])


class FindPatternMatchesTestCase(unittest.TestCase):
    def test_finds_matches(self) -> None:
        entries = build_pattern_entries(["python", "java"])
        matches = find_pattern_matches("knows python and java", entries)
        self.assertIn("python", matches)
        self.assertIn("java", matches)

    def test_respects_limit(self) -> None:
        entries = build_pattern_entries(["python", "java", "go"])
        matches = find_pattern_matches("knows python and java and go", entries, limit=2)
        self.assertEqual(len(matches), 2)


class BuildFocusPhrasesTestCase(unittest.TestCase):
    def test_combines_sources(self) -> None:
        result = build_focus_phrases(["python", "java"], "go")
        self.assertIn("python", result)
        self.assertIn("java", result)
        self.assertIn("go", result)

    def test_dedupes(self) -> None:
        result = build_focus_phrases(["python"], ["python"])
        self.assertEqual(result.count("python"), 1)

    def test_empty_sources(self) -> None:
        self.assertEqual(build_focus_phrases([], None, ""), [])


class ExpandLocationTermsTestCase(unittest.TestCase):
    def test_expands_uk_aliases(self) -> None:
        result = expand_location_terms(["uk"])
        self.assertIn("united kingdom", result)
        self.assertIn("great britain", result)

    def test_passes_through_unknown_location(self) -> None:
        result = expand_location_terms(["london"])
        self.assertIn("london", result)

    def test_skips_empty_strings(self) -> None:
        result = expand_location_terms(["", "london"])
        self.assertNotIn("", result)


class ContainsPhraseTestCase(unittest.TestCase):
    def test_finds_whole_word_match(self) -> None:
        self.assertTrue(contains_phrase("has python skills", "python"))

    def test_does_not_match_partial_word(self) -> None:
        self.assertFalse(contains_phrase("pythonic code", "python"))

    def test_empty_phrase_returns_false(self) -> None:
        self.assertFalse(contains_phrase("some text", ""))


class JoinTextPartsTestCase(unittest.TestCase):
    def test_joins_non_empty_parts(self) -> None:
        self.assertEqual(join_text_parts("hello", "", "world"), "hello world")

    def test_all_empty_returns_empty(self) -> None:
        self.assertEqual(join_text_parts("", ""), "")


if __name__ == "__main__":
    unittest.main()
