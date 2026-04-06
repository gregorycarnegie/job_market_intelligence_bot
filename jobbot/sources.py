import html
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from jobbot.common import (
    BOARD_PAGE_LIMIT,
    COMPANY_BOARD_REQUIRED_FIELDS,
    DEFAULT_GENERIC_JOB_LINK_KEYWORDS,
    FETCH_TIMEOUT_SECONDS,
    GENERIC_HTML_MAX_JOB_LINKS,
    GENERIC_HTML_MAX_START_URLS,
    SUPPORTED_BOARD_PLATFORMS,
    USER_AGENT,
    clean_text,
    dedupe_preserving_order,
    join_text_parts,
    normalize_string_list,
    normalize_text,
    normalize_url_list,
    safe_int,
    strip_cdata,
    strip_tags,
)

logger = logging.getLogger(__name__)


def fetch_feed(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_json(url: str, headers: dict[str, str] | None = None) -> object:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    if headers:
        request_headers.update(headers)

    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
    return json.loads(body)


def strip_html_noise(html_text: str) -> str:
    """
    Remove noisy HTML elements (script, style, noscript) from text.

    Args:
        html_text (str): The raw HTML string.

    Returns:
        str: The HTML with noisy elements removed.
    """
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def extract_meta_content(html_text: str, attr_name: str, attr_value: str) -> str:
    pattern = re.compile(
        rf"<meta\b[^>]*{attr_name}=[\"']{re.escape(attr_value)}[\"'][^>]*content=[\"'](.*?)[\"'][^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html_text)
    if match:
        return clean_text(match.group(1))

    reverse_pattern = re.compile(
        rf"<meta\b[^>]*content=[\"'](.*?)[\"'][^>]*{attr_name}=[\"']{re.escape(attr_value)}[\"'][^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    reverse_match = reverse_pattern.search(html_text)
    return clean_text(reverse_match.group(1)) if reverse_match else ""


def extract_page_title(html_text: str) -> str:
    """
    Attempt to extract the page title using best-effort metadata tags (OpenGraph, Twitter)
    before falling back to <title> or <h1>.

    Args:
        html_text (str): The raw HTML document.

    Returns:
        str: The extracted page title, or an empty string if none is found.
    """
    for extractor in (
        lambda text: extract_meta_content(text, "property", "og:title"),
        lambda text: extract_meta_content(text, "name", "twitter:title"),
    ):
        value = extractor(html_text)
        if value:
            return value

    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if title_match:
        return clean_text(title_match.group(1))

    h1_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.IGNORECASE | re.DOTALL)
    if h1_match:
        return clean_text(h1_match.group(1))

    return ""


def extract_plain_text_from_html(html_text: str, limit: int = 3000) -> str:
    """
    Extract readable plain text from raw HTML by removing noise and tags.

    Args:
        html_text (str): The raw HTML string.
        limit (int): The maximum length of the returned string.

    Returns:
        str: The truncated plain text.
    """
    text = strip_html_noise(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = clean_text(text)
    return text[:limit]


def extract_jsonld_objects(html_text: str) -> list[object]:
    """
    Extract and parse all JSON-LD <script> block objects found in the given HTML.

    Args:
        html_text (str): The HTML to scan.

    Returns:
        list[object]: A list of deserialized JSON objects.
    """
    pattern = re.compile(
        r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    objects = []
    for match in pattern.finditer(html_text):
        raw_content = match.group(1).strip()
        if not raw_content:
            continue
        candidate = re.sub(r"^\s*<!--|-->\s*$", "", raw_content).strip()
        for payload in (candidate, html.unescape(candidate)):
            try:
                objects.append(json.loads(payload))
                break
            except json.JSONDecodeError:
                continue
    return objects


def iter_json_nodes(payload: object):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from iter_json_nodes(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_json_nodes(item)


def node_has_type(node: dict[str, object], target_type: str) -> bool:
    raw_type = node.get("@type")
    if isinstance(raw_type, list):
        return any(clean_text(str(item)).lower() == target_type.lower() for item in raw_type)
    return clean_text(str(raw_type)).lower() == target_type.lower()


def extract_jobposting_nodes(html_text: str) -> list[dict[str, object]]:
    nodes = []
    for payload in extract_jsonld_objects(html_text):
        for node in iter_json_nodes(payload):
            if isinstance(node, dict) and node_has_type(node, "JobPosting"):
                nodes.append(node)
    return nodes


def format_jsonld_address(address: object) -> str:
    if not isinstance(address, dict):
        return ""
    return join_text_parts(
        address.get("streetAddress", ""),
        address.get("addressLocality", ""),
        address.get("addressRegion", ""),
        address.get("postalCode", ""),
        address.get("addressCountry", ""),
    )


def extract_jsonld_location_text(node: dict[str, object]) -> str:
    locations = []
    if clean_text(str(node.get("jobLocationType", ""))).lower() == "telecommute":
        locations.append("remote")

    raw_locations = node.get("jobLocation")
    for location in raw_locations if isinstance(raw_locations, list) else [raw_locations]:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        locations.append(join_text_parts(location.get("name", ""), format_jsonld_address(address)))

    applicant_requirements = node.get("applicantLocationRequirements")
    for requirement in applicant_requirements if isinstance(applicant_requirements, list) else [applicant_requirements]:
        if not isinstance(requirement, dict):
            continue
        locations.append(format_jsonld_address(requirement.get("address")))

    return " ".join(value for value in dedupe_preserving_order(locations) if value)


def normalize_salary_unit_text(unit_text: object) -> str:
    normalized = normalize_text(str(unit_text)).replace(" ", "")
    mapping = {
        "year": "year",
        "1year": "year",
        "annual": "year",
        "month": "month",
        "1month": "month",
        "day": "day",
        "1day": "day",
        "hour": "hour",
        "1hour": "hour",
    }
    return mapping.get(normalized, "year")


def format_provider_salary_text(
    minimum_value: object,
    maximum_value: object,
    currency: object,
    cadence: str,
) -> str:
    minimum = safe_int(minimum_value, 0)
    maximum = safe_int(maximum_value, 0)
    currency_text = clean_text(str(currency)).upper()
    cadence_text = clean_text(cadence).lower()
    if minimum and maximum and minimum != maximum:
        return join_text_parts(f"{currency_text} {minimum:,}-{maximum:,}", cadence_text)
    if minimum:
        return join_text_parts(f"{currency_text} {minimum:,}", cadence_text)
    if maximum:
        return join_text_parts(f"{currency_text} {maximum:,}", cadence_text)
    return ""


def extract_jsonld_salary_text(node: dict[str, object]) -> str:
    base_salary = node.get("baseSalary")
    candidates = base_salary if isinstance(base_salary, list) else [base_salary]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        currency = candidate.get("currency") or candidate.get("currencyCode")
        value = candidate.get("value")
        if isinstance(value, list):
            value = value[0] if value else None

        if isinstance(value, dict):
            minimum = value.get("minValue") or value.get("value")
            maximum = value.get("maxValue") or value.get("value")
            cadence = normalize_salary_unit_text(value.get("unitText"))
        else:
            minimum = candidate.get("minValue") or candidate.get("value")
            maximum = candidate.get("maxValue") or candidate.get("value")
            cadence = normalize_salary_unit_text(candidate.get("unitText"))

        salary_text = format_provider_salary_text(minimum, maximum, currency, cadence)
        if salary_text:
            return salary_text
    return ""


def jobposting_node_to_item(
    node: dict[str, object],
    display_name: str,
    fallback_url: str = "",
) -> dict[str, str] | None:
    """
    Convert a JSON-LD 'JobPosting' node into a standardized item dictionary.

    Args:
        node (dict[str, object]): The JSON-LD node.
        display_name (str): The name of the source or board to append to the description.
        fallback_url (str): The URL to use if the node doesn't contain one.

    Returns:
        dict | None: The normalized job item, or None if the title/link is missing.
    """
    title = clean_text(str(node.get("title", "") or node.get("name", "")))
    link = clean_text(str(node.get("url", "") or fallback_url))
    if not title or not link:
        return None

    company_name = ""
    hiring_organization = node.get("hiringOrganization")
    if isinstance(hiring_organization, dict):
        company_name = clean_text(str(hiring_organization.get("name", "")))

    description = join_text_parts(
        node.get("description", ""),
        extract_jsonld_location_text(node),
        node.get("employmentType", ""),
        company_name,
        extract_jsonld_salary_text(node),
        display_name,
    )
    return {
        "title": title,
        "description": description,
        "link": link,
    }


def extract_anchor_links(html_text: str, base_url: str) -> list[tuple[str, str]]:
    """
    Extract all <a> tags from an HTML string, resolving them against a base URL.

    Args:
        html_text (str): The HTML text.
        base_url (str): The base URL for resolving relative links.

    Returns:
        list[tuple[str, str]]: A list of (absolute_url, anchor_text) tuples.
    """
    pattern = re.compile(
        r"<a\b[^>]*href=(?P<quote>[\"'])(?P<href>.*?)(?P=quote)[^>]*>(?P<text>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    links = []
    for match in pattern.finditer(html_text):
        href = clean_text(match.group("href"))
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute_url = urljoin(base_url, href)
        links.append((absolute_url, clean_text(strip_tags(match.group("text")))))
    return links


def url_matches_allowed_domains(url: str, allowed_domains: list[str]) -> bool:
    try:
        netloc = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    if not netloc:
        return False
    if not allowed_domains:
        return True
    return any(netloc == domain or netloc.endswith(f".{domain}") for domain in allowed_domains)


def looks_like_generic_job_link(
    url: str,
    anchor_text: str,
    board: dict[str, object],
) -> bool:
    if not url_matches_allowed_domains(url, board["allowed_domains"]):
        return False

    normalized_url = normalize_text(url)
    normalized_anchor = normalize_text(anchor_text)
    patterns = board.get("_job_link_patterns") or [re.compile(p, re.IGNORECASE) for p in board["job_link_regexes"]]
    if any(pattern.search(url) for pattern in patterns):
        return True

    keywords = list(board["job_link_keywords"]) or list(DEFAULT_GENERIC_JOB_LINK_KEYWORDS)
    return bool(any(keyword in normalized_url or keyword in normalized_anchor for keyword in keywords))


def fallback_generic_job_item(html_text: str, url: str, display_name: str) -> dict[str, str] | None:
    title = extract_page_title(html_text)
    if not title:
        return None

    plain_text = extract_plain_text_from_html(html_text)
    description = join_text_parts(plain_text, display_name)
    if len(description) < 24:
        return None

    return {
        "title": title,
        "description": description,
        "link": url,
    }


def fetch_generic_html_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    candidate_links = []
    for start_url in board["start_urls"][:GENERIC_HTML_MAX_START_URLS]:
        html_text = fetch_feed(start_url)
        for absolute_url, anchor_text in extract_anchor_links(html_text, start_url):
            if looks_like_generic_job_link(absolute_url, anchor_text, board):
                candidate_links.append(absolute_url)

    items = []
    seen_links = set()
    candidate_links = dedupe_preserving_order(candidate_links)[
        : safe_int(board.get("max_job_pages"), GENERIC_HTML_MAX_JOB_LINKS)
    ]

    for candidate_link in candidate_links:
        html_text = fetch_feed(candidate_link)
        jsonld_items = [
            item
            for item in (
                jobposting_node_to_item(node, str(board.get("display_name", "")), candidate_link)
                for node in extract_jobposting_nodes(html_text)
            )
            if item is not None
        ]

        if jsonld_items:
            for item in jsonld_items:
                link = clean_text(item["link"])
                if link and link not in seen_links:
                    items.append(item)
                    seen_links.add(link)
            continue

        fallback_item = fallback_generic_job_item(html_text, candidate_link, str(board.get("display_name", "")))
        if fallback_item is not None:
            items.append(fallback_item)
            seen_links.add(fallback_item["link"])

    return items


def sanitize_xml(xml_raw: str) -> str:
    cleaned = xml_raw
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = re.sub(r"&(?!#?[a-z0-9]+;)", "&amp;", cleaned, flags=re.IGNORECASE)
    return cleaned


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def extract_link(item: ElementTree.Element) -> str:
    for child in item:
        tag = local_name(child.tag)
        if tag != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text:
            return child.text.strip()
    return ""


def extract_description(item: ElementTree.Element) -> str:
    desc_tags = {"description", "summary", "encoded", "content"}
    for child in item:
        if local_name(child.tag) in desc_tags:
            return strip_cdata("".join(child.itertext()) or (child.text or ""))
    return ""


def parse_structured_feed(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items = []
    seen_links = set()

    for item in root.iter():
        tag = local_name(item.tag)
        if tag not in {"item", "entry", "job"}:
            continue

        title = ""
        link = extract_link(item)
        description = extract_description(item)

        for child in item:
            if local_name(child.tag) == "title" and (child.text or "").strip():
                title = strip_cdata(child.text or "")
                break

        if not title and not link and not description:
            continue
        if link and link in seen_links:
            continue

        items.append(
            {
                "title": clean_text(title),
                "description": clean_text(description),
                "link": clean_text(link),
            }
        )
        seen_links.add(link)

    return items


def extract_tag_text(block: str, tag_names: list[str]) -> str:
    for tag_name in tag_names:
        pattern = re.compile(
            rf"<{tag_name}\b[^>]*>(.*?)</{tag_name}>",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(block)
        if match:
            return strip_cdata(match.group(1))
    return ""


def parse_fallback_feed(xml_text: str) -> list[dict[str, str]]:
    items = []
    blocks = re.findall(r"<(item|entry|job)\b[^>]*>(.*?)</\1>", xml_text, re.IGNORECASE | re.DOTALL)

    for _, block in blocks:
        title = extract_tag_text(block, ["title"])
        description = extract_tag_text(
            block,
            ["description", "summary", "content:encoded", "content_encoded", "content"],
        )

        link = ""
        href_match = re.search(r"<link\b[^>]*href=[\"']([^\"']+)[\"'][^>]*?/?>", block, re.IGNORECASE)
        if href_match:
            link = href_match.group(1).strip()
        else:
            link = extract_tag_text(block, ["link", "url", "apply-url", "apply_url"])

        if title or link or description:
            items.append(
                {
                    "title": title,
                    "description": description,
                    "link": link,
                }
            )

    return items


def parse_feed_items(xml_raw: str) -> list[dict[str, str]]:
    try:
        return parse_structured_feed(xml_raw)
    except ElementTree.ParseError:
        sanitized = sanitize_xml(xml_raw)
        try:
            return parse_structured_feed(sanitized)
        except ElementTree.ParseError:
            items = parse_fallback_feed(sanitized)
            if items:
                return items
            raise


def parse_efinancialcareers_html(html_text: str, source: dict[str, str | int]) -> list[dict[str, str]]:
    pattern = re.compile(
        r"""href=["'](?P<link>(?:https://www\.efinancialcareers\.com)?/(?:jobs-[^"'?#]+?id\d+))["'][^>]*>(?P<title>.*?)</a>""",
        re.IGNORECASE | re.DOTALL,
    )
    items = []
    seen_links = set()

    for match in pattern.finditer(html_text):
        link = html.unescape(match.group("link")).strip()
        if link.startswith("/"):
            link = f"https://www.efinancialcareers.com{link}"
        if link in seen_links:
            continue

        raw_title = html.unescape(match.group("title"))
        title = clean_text(strip_tags(raw_title))
        if not title or title.lower() in {"apply now", "save"} or len(title) < 4:
            continue

        slug = link.rsplit("/", 1)[-1]
        slug = re.sub(r"\.id\d+.*$", "", slug)
        slug = slug.replace("jobs-", "").replace("_", " ").replace("-", " ")
        description = " ".join(part for part in [clean_text(slug), str(source.get("context_terms", ""))] if part)

        items.append(
            {
                "title": title,
                "description": description,
                "link": link,
            }
        )
        seen_links.add(link)

    return items


def parse_source_items(source: dict[str, str | int], raw_text: str) -> list[dict[str, str]]:
    if source.get("type") == "efc_html":
        return parse_efinancialcareers_html(raw_text, source)
    return parse_feed_items(raw_text)


def _normalize_greenhouse(raw_board: dict[str, object], normalized: dict[str, object]) -> None:
    normalized["board_token"] = clean_text(str(raw_board.get("board_token", ""))).strip("/")


def _normalize_lever(raw_board: dict[str, object], normalized: dict[str, object]) -> None:
    normalized["site"] = clean_text(str(raw_board.get("site", ""))).strip("/")
    normalized["instance"] = normalize_text(str(raw_board.get("instance", "global"))) or "global"


def _normalize_ashby(raw_board: dict[str, object], normalized: dict[str, object]) -> None:
    normalized["job_board_name"] = clean_text(str(raw_board.get("job_board_name", ""))).strip("/")


def _normalize_workable(raw_board: dict[str, object], normalized: dict[str, object]) -> None:
    normalized["account_subdomain"] = clean_text(
        str(raw_board.get("account_subdomain", "") or raw_board.get("subdomain", ""))
    ).strip("/")
    normalized["mode"] = normalize_text(str(raw_board.get("mode", "public"))) or "public"
    normalized["api_token_env"] = clean_text(str(raw_board.get("api_token_env", "")))


def _normalize_generic_html(raw_board: dict[str, object], normalized: dict[str, object]) -> None:
    normalized["start_urls"] = normalize_url_list(raw_board.get("start_urls", []))
    raw_allowed_domains = raw_board.get("allowed_domains", [])
    normalized["allowed_domains"] = normalize_string_list(raw_allowed_domains, lower=True)
    if not normalized["allowed_domains"]:
        normalized["allowed_domains"] = dedupe_preserving_order(
            [urlsplit(url).netloc.lower() for url in normalized["start_urls"] if urlsplit(url).netloc]
        )
    normalized["job_link_keywords"] = normalize_string_list(
        raw_board.get("job_link_keywords", []),
        lower=True,
    )
    normalized["job_link_regexes"] = normalize_string_list(raw_board.get("job_link_regexes", []))
    normalized["_job_link_patterns"] = [
        re.compile(pattern, re.IGNORECASE) for pattern in normalized["job_link_regexes"]
    ]
    normalized["max_job_pages"] = max(
        1,
        min(200, safe_int(raw_board.get("max_job_pages", GENERIC_HTML_MAX_JOB_LINKS), GENERIC_HTML_MAX_JOB_LINKS)),
    )


BOARD_NORMALIZERS = {
    "greenhouse": _normalize_greenhouse,
    "lever": _normalize_lever,
    "ashby": _normalize_ashby,
    "workable": _normalize_workable,
    "generic_html": _normalize_generic_html,
}


def normalize_company_board(raw_board: dict[str, object]) -> dict[str, object] | None:
    """
    Normalize a raw company board dictionary into a standardized format.

    Args:
        raw_board: A raw dictionary parsed from a board config file.

    Returns:
        A normalized dictionary, or None if validation fails.
    """
    name = clean_text(str(raw_board.get("name", "")))
    platform = normalize_text(str(raw_board.get("platform", ""))).replace(" ", "_")
    if not name or platform not in SUPPORTED_BOARD_PLATFORMS:
        return None

    normalized_board = {
        "name": name,
        "platform": platform,
        "display_name": clean_text(str(raw_board.get("display_name", "") or raw_board.get("company_name", "") or name)),
        "min_interval_seconds": max(300, safe_int(raw_board.get("min_interval_seconds", 1800), 1800)),
    }

    normalizer = BOARD_NORMALIZERS.get(platform)
    if normalizer:
        normalizer(raw_board, normalized_board)

    missing_fields = [field for field in COMPANY_BOARD_REQUIRED_FIELDS[platform] if not normalized_board.get(field)]
    if missing_fields:
        return None

    return normalized_board


def load_company_boards(company_boards_file: str) -> list[dict[str, object]]:
    boards_path = Path(company_boards_file)
    if not boards_path.exists():
        return []

    try:
        with open(boards_path, encoding="utf-8") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"skipping {company_boards_file} — {exc}")
        return []

    if not isinstance(raw_data, list):
        logger.warning(f"file {company_boards_file} must contain a JSON list.")
        return []

    normalized_boards = []
    seen_names = set()
    for index, raw_board in enumerate(raw_data):
        if not isinstance(raw_board, dict):
            logger.warning(f"skipping board #{index + 1} in {company_boards_file} — expected an object.")
            continue
        normalized_board = normalize_company_board(raw_board)
        if normalized_board is None:
            logger.warning(
                f"skipping board #{index + 1} in {company_boards_file} — invalid or missing required fields."
            )
            continue
        if normalized_board["name"] in seen_names:
            logger.warning(f"skipping duplicate board name {normalized_board['name']!r}.")
            continue
        normalized_boards.append(normalized_board)
        seen_names.add(str(normalized_board["name"]))

    return normalized_boards


def fetch_greenhouse_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board['board_token']}/jobs?content=true")
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    items = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        departments = ", ".join(
            clean_text(str(department.get("name", "")))
            for department in job.get("departments", [])
            if isinstance(department, dict) and clean_text(str(department.get("name", "")))
        )
        offices = ", ".join(
            join_text_parts(office.get("name", ""), office.get("location", ""))
            for office in job.get("offices", [])
            if isinstance(office, dict)
        )
        location = (
            clean_text(str(job.get("location", {}).get("name", ""))) if isinstance(job.get("location"), dict) else ""
        )
        items.append(
            {
                "title": clean_text(str(job.get("title", ""))),
                "description": join_text_parts(
                    job.get("content", ""),
                    location,
                    departments,
                    offices,
                    board.get("display_name", ""),
                ),
                "link": clean_text(str(job.get("absolute_url", ""))),
            }
        )

    return items


def fetch_lever_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    instance = normalize_text(str(board.get("instance", "global"))) or "global"
    base_url = "https://api.eu.lever.co" if instance == "eu" else "https://api.lever.co"
    items = []
    skip = 0

    while True:
        payload = fetch_json(f"{base_url}/v0/postings/{board['site']}?mode=json&limit={BOARD_PAGE_LIMIT}&skip={skip}")
        jobs = payload if isinstance(payload, list) else []
        if not jobs:
            break

        for job in jobs:
            if not isinstance(job, dict):
                continue
            categories = job.get("categories", {}) if isinstance(job.get("categories"), dict) else {}
            salary_range = job.get("salaryRange", {}) if isinstance(job.get("salaryRange"), dict) else {}
            items.append(
                {
                    "title": clean_text(str(job.get("text", ""))),
                    "description": join_text_parts(
                        job.get("descriptionPlain", ""),
                        job.get("descriptionBodyPlain", ""),
                        job.get("additionalPlain", ""),
                        categories.get("location", ""),
                        categories.get("team", ""),
                        categories.get("department", ""),
                        categories.get("commitment", ""),
                        job.get("workplaceType", ""),
                        format_provider_salary_text(
                            salary_range.get("min"),
                            salary_range.get("max"),
                            salary_range.get("currency"),
                            str(salary_range.get("interval", "year")).replace("_", " "),
                        ),
                        job.get("salaryDescriptionPlain", ""),
                        board.get("display_name", ""),
                    ),
                    "link": clean_text(str(job.get("hostedUrl", "") or job.get("applyUrl", ""))),
                }
            )

        if len(jobs) < BOARD_PAGE_LIMIT:
            break
        skip += BOARD_PAGE_LIMIT

    return items


def fetch_ashby_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    payload = fetch_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{board['job_board_name']}?includeCompensation=true"
    )
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    items = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("isListed") is False:
            continue
        compensation = job.get("compensation", {}) if isinstance(job.get("compensation"), dict) else {}
        items.append(
            {
                "title": clean_text(str(job.get("title", ""))),
                "description": join_text_parts(
                    job.get("descriptionPlain", ""),
                    job.get("location", ""),
                    job.get("department", ""),
                    job.get("team", ""),
                    job.get("employmentType", ""),
                    job.get("workplaceType", ""),
                    compensation.get("scrapeableCompensationSalarySummary", ""),
                    compensation.get("compensationTierSummary", ""),
                    board.get("display_name", ""),
                ),
                "link": clean_text(str(job.get("jobUrl", "") or job.get("applyUrl", ""))),
            }
        )

    return items


def fetch_workable_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    subdomain = str(board["account_subdomain"])
    mode = normalize_text(str(board.get("mode", "public"))) or "public"

    if mode == "spi":
        token_env = clean_text(str(board.get("api_token_env", "")))
        token = os.environ.get(token_env, "").strip() if token_env else ""
        if not token:
            raise ValueError(f"Workable board {board['name']} requires env var {token_env or 'api_token_env'}")
        payload = fetch_json(
            f"https://{subdomain}.workable.com/spi/v3/jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
    else:
        payload = fetch_json(f"https://www.workable.com/api/accounts/{subdomain}?details=true")

    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    items = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        location = job.get("location", {}) if isinstance(job.get("location"), dict) else {}
        salary = job.get("salary", {}) if isinstance(job.get("salary"), dict) else {}
        items.append(
            {
                "title": clean_text(str(job.get("title", "") or job.get("full_title", ""))),
                "description": join_text_parts(
                    job.get("description", ""),
                    job.get("description_plain", ""),
                    location.get("location_str", ""),
                    location.get("country", ""),
                    location.get("city", ""),
                    location.get("workplace_type", ""),
                    job.get("department", ""),
                    format_provider_salary_text(
                        salary.get("salary_from"),
                        salary.get("salary_to"),
                        salary.get("salary_currency"),
                        "year",
                    ),
                    board.get("display_name", ""),
                ),
                "link": clean_text(
                    str(job.get("application_url", "") or job.get("url", "") or job.get("shortlink", ""))
                ),
            }
        )

    return items


def fetch_company_board_items(board: dict[str, object]) -> list[dict[str, str]]:
    """
    Fetch job openings for a specific company board using the required backend handler.

    Args:
        board: A single company board dictionary containing normalized configuration.

    Returns:
        A list of dictionaries representing the fetched job items.
    """
    platform = str(board.get("platform", ""))

    handlers = {
        "greenhouse": fetch_greenhouse_board_jobs,
        "lever": fetch_lever_board_jobs,
        "ashby": fetch_ashby_board_jobs,
        "workable": fetch_workable_board_jobs,
        "generic_html": fetch_generic_html_board_jobs,
    }

    handler = handlers.get(platform)
    if handler:
        return handler(board)
    return []
    raise ValueError(f"Unsupported board platform: {platform}")
