import unittest

from jobbot import sources


class SourcesUtilsTestCase(unittest.TestCase):
    def test_strip_html_noise_removes_script_style_noscript(self) -> None:
        html = "<p>keep</p><script>bad()</script><style>.x{}</style><noscript>fallback</noscript>"
        result = sources.strip_html_noise(html)
        self.assertIn("<p>keep</p>", result)
        self.assertNotIn("bad()", result)
        self.assertNotIn(".x{}", result)
        self.assertNotIn("fallback", result)

    def test_extract_plain_text_from_html_strips_tags(self) -> None:
        html = "<p>Hello <b>World</b></p>"
        result = sources.extract_plain_text_from_html(html)
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("<p>", result)

    def test_extract_plain_text_from_html_respects_limit(self) -> None:
        html = "<p>" + "a" * 5000 + "</p>"
        result = sources.extract_plain_text_from_html(html, limit=100)
        self.assertLessEqual(len(result), 100)

    def test_extract_meta_content_finds_property(self) -> None:
        html = '<meta property="og:title" content="My Title" />'
        result = sources.extract_meta_content(html, "property", "og:title")
        self.assertEqual(result, "My Title")

    def test_extract_meta_content_finds_reversed_attribute_order(self) -> None:
        html = '<meta content="Rev Title" property="og:title" />'
        result = sources.extract_meta_content(html, "property", "og:title")
        self.assertEqual(result, "Rev Title")

    def test_extract_meta_content_returns_empty_when_missing(self) -> None:
        result = sources.extract_meta_content("<html></html>", "property", "og:title")
        self.assertEqual(result, "")

    def test_extract_page_title_uses_og_title(self) -> None:
        html = '<meta property="og:title" content="OG Title" />'
        self.assertEqual(sources.extract_page_title(html), "OG Title")

    def test_extract_page_title_falls_back_to_title_tag(self) -> None:
        html = "<title>Page Title</title>"
        self.assertEqual(sources.extract_page_title(html), "Page Title")

    def test_extract_page_title_falls_back_to_h1(self) -> None:
        html = "<h1>Heading</h1>"
        self.assertEqual(sources.extract_page_title(html), "Heading")

    def test_extract_page_title_returns_empty_when_none(self) -> None:
        self.assertEqual(sources.extract_page_title("<html></html>"), "")

    def test_iter_json_nodes_yields_dict_and_children(self) -> None:
        payload = {"key": "val", "child": {"nested": True}}
        nodes = list(sources.iter_json_nodes(payload))
        self.assertIn({"key": "val", "child": {"nested": True}}, nodes)
        self.assertIn({"nested": True}, nodes)

    def test_iter_json_nodes_handles_list(self) -> None:
        payload = [{"a": 1}, {"b": 2}]
        nodes = list(sources.iter_json_nodes(payload))
        self.assertIn({"a": 1}, nodes)
        self.assertIn({"b": 2}, nodes)

    def test_node_has_type_matches_string(self) -> None:
        self.assertTrue(sources.node_has_type({"@type": "JobPosting"}, "JobPosting"))
        self.assertFalse(sources.node_has_type({"@type": "Organization"}, "JobPosting"))

    def test_node_has_type_matches_list(self) -> None:
        self.assertTrue(sources.node_has_type({"@type": ["JobPosting", "Thing"]}, "JobPosting"))

    def test_extract_jsonld_objects_parses_script_block(self) -> None:
        html = '<script type="application/ld+json">{"@type": "JobPosting"}</script>'
        objects = sources.extract_jsonld_objects(html)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["@type"], "JobPosting")  # type: ignore[index]

    def test_extract_jsonld_objects_skips_invalid_json(self) -> None:
        html = '<script type="application/ld+json">not json</script>'
        objects = sources.extract_jsonld_objects(html)
        self.assertEqual(objects, [])


if __name__ == "__main__":
    unittest.main()
