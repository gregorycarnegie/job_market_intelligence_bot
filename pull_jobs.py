import csv
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

CSV_FILE = "jobs.csv"
RESUME_FILE = "resume.json"
FEED_STATE_FILE = "feed_state.json"
ALERTS_STATE_FILE = "alerts_state.json"
SEEN_JOBS_STATE_FILE = "seen_jobs_state.json"
MATCHES_FILE = "matches.json"
COMPANY_BOARDS_FILE = "company_boards.json"
JOB_SEARCH_CONFIG_FILE = "job_search_config.json"
APPLICATIONS_FILE = "applications.json"
DAILY_DIGEST_FILE = "daily_digest.json"
APPLICATION_BRIEFS_FILE = "application_briefs.json"
BORDERLINE_MATCHES_FILE = "borderline_matches.json"
FEEDBACK_METRICS_FILE = "feedback_metrics.json"
CSV_HEADERS = ["time", "title", "description", "link"]
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
MIN_MATCH_SCORE = 28
MAX_ALERTED_LINKS = 5000
MAX_REVIEWED_FINGERPRINTS = 50000
MAX_APPLICATION_RECORDS = 5000
BOARD_PAGE_LIMIT = 100
GENERIC_HTML_MAX_START_URLS = 10
GENERIC_HTML_MAX_JOB_LINKS = 60
DEFAULT_DAILY_DIGEST_HOUR_UTC = 7
DEFAULT_DAILY_DIGEST_MAX_ITEMS = 8
DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS = 10
APPLICATION_STATUSES = {"new", "reviewed", "applied", "rejected", "interview"}
DEFAULT_DAILY_DIGEST_STATUSES = ["new", "reviewed", "applied", "interview"]
COMPANY_CONTROL_ORDER = {"none": 0, "whitelist": 1, "priority": 2}
BORDERLINE_MATCH_MARGIN = 6
APPLICATION_READY_SCORE = 45
OUTCOME_RELEVANT_STATUSES = {"applied", "interview", "rejected"}
DEFAULT_FEEDBACK_MIN_SAMPLES = 2
DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT = 10
DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT = 6
DEFAULT_FEEDBACK_KEYWORD_LIMIT = 4
DEFAULT_NEW_REVIEWED_RETENTION_DAYS = 120
DEFAULT_REJECTED_RETENTION_DAYS = 180
DEFAULT_APPLIED_RETENTION_DAYS = 540
DEFAULT_INTERVIEW_RETENTION_DAYS = 730
LOCATION_ALIASES = {
    "united kingdom": ["uk", "great britain", "britain"],
    "uk": ["united kingdom", "great britain", "britain"],
    "united states": ["us", "usa", "america"],
    "us": ["usa", "united states", "america"],
    "usa": ["us", "united states", "america"],
}
POSITIVE_TITLE_WEIGHTS = {
    "systems administrator": 32,
    "system administrator": 32,
    "it support engineer": 30,
    "it support analyst": 28,
    "desktop support": 28,
    "service desk": 26,
    "help desk": 24,
    "helpdesk": 24,
    "technical support": 22,
    "it technician": 24,
    "support engineer": 18,
    "support analyst": 18,
    "infrastructure engineer": 18,
    "endpoint engineer": 16,
    "microsoft 365": 14,
    "identity access": 18,
    "iam": 10,
}
NEGATIVE_TITLE_WEIGHTS = {
    "data engineer": 40,
    "data scientist": 45,
    "machine learning": 45,
    "ml engineer": 45,
    "ai engineer": 40,
    "software engineer": 18,
    "backend engineer": 20,
    "frontend engineer": 20,
    "full stack": 18,
    "product manager": 35,
    "marketing": 35,
    "sales": 35,
    "account executive": 35,
    "account manager": 22,
}
SENIORITY_PENALTIES = {
    "senior": 12,
    "lead": 10,
    "principal": 25,
    "staff": 20,
    "manager": 18,
    "head": 28,
    "director": 30,
    "architect": 18,
}
TRACKING_QUERY_PARAMS = {
    "ref",
    "source",
    "src",
    "campaign",
    "email",
    "mc_cid",
    "mc_eid",
    "fbclid",
    "gclid",
    "yclid",
}
CURRENCY_TO_GBP = {
    "gbp": 1.0,
    "usd": 0.79,
    "eur": 0.86,
}
CADENCE_TO_ANNUAL_MULTIPLIER = {
    "year": 1,
    "month": 12,
    "day": 230,
    "hour": 1840,
}
JOB_TITLE_HINT_RE = re.compile(
    r"\b("
    r"engineer|analyst|administrator|technician|support|desk|helpdesk|specialist|consultant|"
    r"developer|devops|infrastructure|sysadmin|operations|desktop|service|endpoint|cloud"
    r")\b",
    re.IGNORECASE,
)
DEFAULT_GENERIC_JOB_LINK_KEYWORDS = [
    "job",
    "jobs",
    "career",
    "careers",
    "vacancy",
    "vacancies",
    "opening",
    "openings",
    "position",
    "positions",
    "role",
    "roles",
    "opportunity",
    "opportunities",
]
DEFAULT_ROLE_PROFILE_CONFIGS = [
    {
        "name": "core_it_support",
        "display_name": "Core IT Support",
        "title_keywords": [
            "it support engineer",
            "it support analyst",
            "it technician",
            "service desk",
            "help desk",
            "helpdesk",
            "desktop support",
            "technical support",
        ],
        "description_keywords": [
            "user support",
            "ticket management",
            "vip support",
            "hardware support",
            "onboarding",
            "offboarding",
            "troubleshooting",
        ],
        "title_boost": 18,
        "description_boost": 5,
        "priority": 100,
    },
    {
        "name": "systems_administration",
        "display_name": "Systems Administration",
        "title_keywords": [
            "systems administrator",
            "system administrator",
            "sysadmin",
            "endpoint engineer",
            "microsoft 365 administrator",
            "identity administrator",
        ],
        "description_keywords": [
            "active directory",
            "azure ad",
            "microsoft entra",
            "windows",
            "linux",
            "sharepoint",
            "exchange",
            "identity and access management",
        ],
        "title_boost": 16,
        "description_boost": 4,
        "priority": 90,
    },
    {
        "name": "support_infrastructure",
        "display_name": "Support Infrastructure",
        "title_keywords": [
            "support engineer",
            "support analyst",
            "infrastructure engineer",
            "operations analyst",
            "technical operations",
        ],
        "description_keywords": [
            "microsoft 365",
            "network",
            "access control",
            "hardware upgrades",
            "vendor coordination",
            "documentation",
        ],
        "title_boost": 9,
        "description_boost": 3,
        "priority": 70,
    },
]
FEEDS = [
    {
        "name": "efc_technology_uk",
        "url": "https://www.efinancialcareers.com/jobs/technology/in-united-kingdom",
        "type": "efc_html",
        "context_terms": "technology finance fintech banking trading london united kingdom hybrid in-office",
        "min_interval_seconds": 1800,
    },
    {
        "name": "wwr_programming",
        "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "min_interval_seconds": 900,
    },
    {
        "name": "wwr_devops",
        "url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "min_interval_seconds": 900,
    },
    {
        "name": "wwr_management_finance",
        "url": "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
        "min_interval_seconds": 900,
    },
    {
        "name": "remotive_software_dev",
        "url": "https://remotive.com/remote-jobs/feed/software-development",
        "min_interval_seconds": 3600,
    },
    {
        "name": "remotive_devops",
        "url": "https://remotive.com/remote-jobs/feed/devops",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobscollider_software",
        "url": "https://jobscollider.com/remote-software-development-jobs.rss",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobscollider_devops",
        "url": "https://jobscollider.com/remote-devops-jobs.rss",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobscollider_finance_legal",
        "url": "https://jobscollider.com/remote-finance-legal-jobs.rss",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobicy_fintech_uk_europe",
        "url": (
            "https://jobicy.com/feed/job_feed"
            "?job_categories=engineering,technical-suppor,accounting-finance"
            "&search_keywords=fintech"
            "&search_region=uk,europe"
        ),
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobicy_payments_uk_europe",
        "url": (
            "https://jobicy.com/feed/job_feed"
            "?job_categories=engineering,technical-suppor,accounting-finance"
            "&search_keywords=payments"
            "&search_region=uk,europe"
        ),
        "min_interval_seconds": 3600,
    },
]
SUPPORTED_BOARD_PLATFORMS = {"greenhouse", "lever", "ashby", "workable", "generic_html"}
COMPANY_BOARD_REQUIRED_FIELDS = {
    "greenhouse": ("board_token",),
    "lever": ("site",),
    "ashby": ("job_board_name",),
    "workable": ("account_subdomain",),
    "generic_html": ("start_urls",),
}

PatternEntry = tuple[str, re.Pattern[str]]


def clean_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return " ".join(clean.split())


def normalize_text(text: str) -> str:
    return " ".join(clean_text(text).lower().split())


def strip_cdata(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("<![CDATA[") and stripped.endswith("]]>"):
        return stripped[9:-3]
    return stripped


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def compile_skill_pattern(skill: str) -> re.Pattern[str] | None:
    normalized_skill = normalize_text(skill)
    if not normalized_skill:
        return None
    escaped = re.escape(normalized_skill).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def contains_phrase(text: str, phrase: str) -> bool:
    pattern = compile_skill_pattern(phrase)
    return bool(pattern and pattern.search(text))


def build_pattern_entries(values: list[str]) -> list[PatternEntry]:
    entries: list[PatternEntry] = []
    seen = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        pattern = compile_skill_pattern(normalized)
        if pattern is None:
            continue
        entries.append((normalized, pattern))
        seen.add(normalized)
    return entries


def find_pattern_matches(text: str, entries: list[PatternEntry], limit: int = 0) -> list[str]:
    matches = [label for label, pattern in entries if pattern.search(text)]
    return matches[:limit] if limit else matches


def append_reason(reasons: list[str], message: str) -> None:
    clean_message = clean_text(message)
    if clean_message and clean_message not in reasons:
        reasons.append(clean_message)


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = normalize_text(str(value))
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def fresh_alert_state() -> dict[str, object]:
    return {
        "alerted_links": [],
        "pending_alerts": [],
        "last_run_utc": "",
        "last_delivery_utc": "",
        "last_delivery_error": "",
    }


def fresh_seen_jobs_state() -> dict[str, object]:
    return {
        "reviewed_fingerprints": [],
        "last_run_utc": "",
    }


def fresh_applications_state() -> dict[str, object]:
    return {
        "applications": [],
        "last_updated_utc": "",
        "last_digest_utc": "",
        "last_digest_date_utc": "",
        "last_digest_error": "",
        "last_feedback_utc": "",
        "last_cleanup_utc": "",
    }


def join_text_parts(*parts: object) -> str:
    cleaned_parts = [clean_text(str(part)) for part in parts if clean_text(str(part))]
    return " ".join(cleaned_parts)


def normalize_string_list(values: object, *, lower: bool = False) -> list[str]:
    raw_values = values if isinstance(values, list) else [values] if values else []
    normalized_values = []
    for value in raw_values:
        normalized = normalize_text(value) if lower else clean_text(str(value))
        if normalized:
            normalized_values.append(normalized)
    return dedupe_preserving_order(normalized_values)


def normalize_url_list(values: object) -> list[str]:
    urls = []
    for value in values if isinstance(values, list) else [values] if values else []:
        url = clean_text(str(value))
        if url.startswith(("http://", "https://")):
            urls.append(url)
    return dedupe_preserving_order(urls)


def normalize_link_for_fingerprint(link: str) -> str:
    raw = html.unescape((link or "").strip())
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw

    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key in TRACKING_QUERY_PARAMS or normalized_key.startswith("utm_"):
            continue
        query_pairs.append((key, value))

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(query_pairs, doseq=True),
            "",
        )
    )


def looks_like_job_title(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(normalized and JOB_TITLE_HINT_RE.search(normalized))


def normalize_company_name(company: str) -> str:
    normalized = normalize_text(company)
    normalized = re.sub(
        r"\b(ltd|limited|plc|inc|llc|gmbh|corp|corporation|company|co)\b",
        " ",
        normalized,
    )
    return " ".join(normalized.split())


def split_title_and_company(title: str) -> tuple[str, str]:
    clean_title = clean_text(title)
    if not clean_title:
        return "", ""

    separators = [
        ("at", r"\s+at\s+"),
        ("@", r"\s+@\s+"),
        ("pipe", r"\s+\|\s+"),
        ("dash", r"\s+[-–—]\s+"),
        ("colon", r":\s+"),
    ]

    for label, pattern in separators:
        parts = re.split(pattern, clean_title, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            continue
        left = clean_text(parts[0])
        right = clean_text(parts[1])
        if not left or not right:
            continue

        left_is_role = looks_like_job_title(left)
        right_is_role = looks_like_job_title(right)

        if left_is_role and not right_is_role:
            return left, right
        if right_is_role and not left_is_role:
            return right, left
        if label in {"at", "@"} and left_is_role:
            return left, right

    return clean_title, ""


def build_review_fingerprints(title: str, description: str, link: str) -> list[str]:
    fingerprints = []
    normalized_link = normalize_link_for_fingerprint(link)
    if normalized_link:
        fingerprints.append(f"link:{normalized_link}")

    role_title, company = split_title_and_company(title)
    normalized_role_title = normalize_text(role_title or title)
    normalized_company = normalize_company_name(company)
    if normalized_role_title and normalized_company:
        fingerprints.append(f"role_company:{normalized_role_title}|{normalized_company}")

    if not fingerprints:
        fallback_text = normalize_text(f"{title} {description}")[:180]
        if fallback_text:
            fingerprints.append(f"text:{fallback_text}")

    return dedupe_preserving_order(fingerprints)


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
    text = strip_html_noise(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = clean_text(text)
    return text[:limit]


def extract_jsonld_objects(html_text: str) -> list[object]:
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
    normalized_url = normalize_text(url)
    normalized_text = normalize_text(anchor_text)
    score = 0

    for pattern in board.get("job_link_regexes", []):
        try:
            if re.search(pattern, url, re.IGNORECASE):
                score += 4
                break
        except re.error:
            continue

    keywords = board.get("job_link_keywords", []) or DEFAULT_GENERIC_JOB_LINK_KEYWORDS
    if any(keyword in normalized_url for keyword in keywords):
        score += 2
    if any(keyword in normalized_text for keyword in keywords):
        score += 1
    if looks_like_job_title(anchor_text):
        score += 3

    slug = clean_text(urlsplit(url).path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " "))
    if looks_like_job_title(slug):
        score += 2

    return score >= 3


def fallback_generic_job_item(html_text: str, url: str, display_name: str) -> dict[str, str] | None:
    title = extract_page_title(html_text)
    if not looks_like_job_title(title):
        return None

    description = join_text_parts(
        extract_meta_content(html_text, "property", "og:description"),
        extract_meta_content(html_text, "name", "description"),
        extract_plain_text_from_html(html_text),
        display_name,
    )
    return {
        "title": title,
        "description": description,
        "link": clean_text(url),
    }


def fetch_generic_html_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    display_name = get_source_display_name(board)
    allowed_domains = board.get("allowed_domains", [])
    candidate_links = []
    items_by_link: dict[str, dict[str, str]] = {}

    for start_url in board["start_urls"][:GENERIC_HTML_MAX_START_URLS]:
        html_text = fetch_feed(start_url)

        for node in extract_jobposting_nodes(html_text):
            item = jobposting_node_to_item(node, display_name, start_url)
            if item and item["link"]:
                items_by_link[normalize_link_for_fingerprint(item["link"])] = item

        for url, anchor_text in extract_anchor_links(html_text, start_url):
            if not url_matches_allowed_domains(url, allowed_domains):
                continue
            if looks_like_generic_job_link(url, anchor_text, board):
                candidate_links.append(url)

    candidate_links = dedupe_preserving_order(candidate_links)[: safe_int(board.get("max_job_pages"), GENERIC_HTML_MAX_JOB_LINKS)]

    for url in candidate_links:
        if normalize_link_for_fingerprint(url) in items_by_link:
            continue
        html_text = fetch_feed(url)
        nodes = extract_jobposting_nodes(html_text)
        item = None
        for node in nodes:
            candidate_item = jobposting_node_to_item(node, display_name, url)
            if candidate_item and normalize_link_for_fingerprint(candidate_item["link"]) == normalize_link_for_fingerprint(url):
                item = candidate_item
                break
            if candidate_item and item is None:
                item = candidate_item
        if item is None:
            item = fallback_generic_job_item(html_text, url, display_name)
        if item and item["link"]:
            items_by_link[normalize_link_for_fingerprint(item["link"])] = item

    return list(items_by_link.values())


def sanitize_xml(xml_raw: str) -> str:
    xml_text = xml_raw.lstrip("\ufeff")
    xml_text = re.sub(r"&(?!#?[a-zA-Z0-9]+;)", "&amp;", xml_text)
    xml_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", xml_text)

    declared_prefixes = set(re.findall(r"\bxmlns:([A-Za-z_][\w.-]*)=", xml_text))
    used_prefixes = set(re.findall(r"</?([A-Za-z_][\w.-]*):[A-Za-z_][\w.-]*", xml_text))
    missing_prefixes = used_prefixes - declared_prefixes

    for prefix in sorted(missing_prefixes):
        xml_text = re.sub(rf"(<\/?){prefix}:", rf"\1{prefix}_", xml_text)
        xml_text = re.sub(rf"(\s){prefix}:", rf"\1{prefix}_", xml_text)

    return xml_text


def local_name(tag: str) -> str:
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    return tag.replace(":", "_").lower()


def extract_link(item: ElementTree.Element) -> str:
    accepted_names = {"link", "url", "apply_url", "apply-url"}
    for child in item.iter():
        if local_name(child.tag) not in accepted_names:
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        text = clean_text(child.text or "")
        if text:
            return text
    return ""


def extract_description(item: ElementTree.Element) -> str:
    preferred_names = {"description", "summary", "content", "content_encoded", "encoded"}
    for child in item.iter():
        if local_name(child.tag) not in preferred_names:
            continue
        text = child.text or ElementTree.tostring(child, encoding="unicode", method="xml")
        cleaned = strip_cdata(text)
        if cleaned.strip():
            return cleaned
    return ""


def parse_structured_feed(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items = []

    for item in root.iter():
        if local_name(item.tag) not in {"item", "entry", "job"}:
            continue
        title = ""
        for child in item:
            if local_name(child.tag) == "title":
                title = child.text or ""
                break

        link = extract_link(item)
        description = extract_description(item)
        if title or link or description:
            items.append(
                {
                    "title": title,
                    "description": description,
                    "link": link,
                }
            )

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
        description = " ".join(
            part
            for part in [clean_text(slug), str(source.get("context_terms", ""))]
            if part
        )

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


def expand_location_terms(values: list[str]) -> list[str]:
    expanded = set()
    for value in values:
        if not value:
            continue
        expanded.add(value)
        for alias in LOCATION_ALIASES.get(value, []):
            expanded.add(alias)
    return sorted(expanded)


def build_resume_evidence_entries(resume: dict[str, object]) -> list[dict[str, str]]:
    entries = []

    summary = clean_text(str(resume.get("summary", "")))
    if summary:
        entries.append(
            {
                "label": "Resume summary",
                "role": "",
                "organization": "",
                "text": summary,
                "normalized_text": normalize_text(summary),
            }
        )

    for experience in resume.get("experience", []):
        if not isinstance(experience, dict):
            continue
        role = clean_text(str(experience.get("role", "")))
        organization = clean_text(str(experience.get("organization", "")))
        label = join_text_parts(role, f"at {organization}" if organization else "")
        highlights = experience.get("highlights", [])
        if not isinstance(highlights, list):
            continue
        for highlight in highlights:
            text = clean_text(str(highlight))
            if not text:
                continue
            entries.append(
                {
                    "label": label or "Experience",
                    "role": role,
                    "organization": organization,
                    "text": text,
                    "normalized_text": normalize_text(join_text_parts(role, organization, text)),
                }
            )

    return entries


def load_resume_profile() -> dict[str, object]:
    with open(RESUME_FILE, encoding="utf-8") as f:
        resume = json.load(f)

    personal_info = resume.get("personal_info", {})
    technical_skills = resume.get("technical_skills", {})
    prefs = personal_info.get("preferences", {})
    loc = personal_info.get("location", {})

    raw_skills = technical_skills.get("skills", [])
    raw_competencies = technical_skills.get("competencies", [])
    raw_target_roles = list(personal_info.get("target_roles", []))
    current_title = personal_info.get("title", "")
    candidate_name = clean_text(str(personal_info.get("name", "")))
    resume_summary = clean_text(str(resume.get("summary", "")))
    if current_title:
        raw_target_roles.append(current_title)

    preferred_locations = [
        normalize_text(value)
        for value in [
            loc.get("city", ""),
            loc.get("country", ""),
            *prefs.get("preferred_locations", []),
        ]
        if normalize_text(value)
    ]

    return {
        "resume": resume,
        "candidate_name": candidate_name,
        "candidate_title": clean_text(str(current_title)),
        "resume_summary": resume_summary,
        "prefs": prefs,
        "preferred_locations": expand_location_terms(preferred_locations),
        "target_role_entries": build_pattern_entries(raw_target_roles),
        "skill_entries": build_pattern_entries(raw_skills),
        "competency_entries": build_pattern_entries(raw_competencies),
        "experience_entries": build_resume_evidence_entries(resume),
    }


def normalize_company_board(raw_board: dict[str, object]) -> dict[str, object] | None:
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

    if platform == "greenhouse":
        normalized_board["board_token"] = clean_text(str(raw_board.get("board_token", ""))).strip("/")
    elif platform == "lever":
        normalized_board["site"] = clean_text(str(raw_board.get("site", ""))).strip("/")
        normalized_board["instance"] = normalize_text(str(raw_board.get("instance", "global"))) or "global"
    elif platform == "ashby":
        normalized_board["job_board_name"] = clean_text(str(raw_board.get("job_board_name", ""))).strip("/")
    elif platform == "workable":
        normalized_board["account_subdomain"] = clean_text(
            str(raw_board.get("account_subdomain", "") or raw_board.get("subdomain", ""))
        ).strip("/")
        normalized_board["mode"] = normalize_text(str(raw_board.get("mode", "public"))) or "public"
        normalized_board["api_token_env"] = clean_text(str(raw_board.get("api_token_env", "")))
    elif platform == "generic_html":
        normalized_board["start_urls"] = normalize_url_list(raw_board.get("start_urls", []))
        raw_allowed_domains = raw_board.get("allowed_domains", [])
        normalized_board["allowed_domains"] = normalize_string_list(raw_allowed_domains, lower=True)
        if not normalized_board["allowed_domains"]:
            normalized_board["allowed_domains"] = dedupe_preserving_order(
                [
                    urlsplit(url).netloc.lower()
                    for url in normalized_board["start_urls"]
                    if urlsplit(url).netloc
                ]
            )
        normalized_board["job_link_keywords"] = normalize_string_list(
            raw_board.get("job_link_keywords", []),
            lower=True,
        )
        normalized_board["job_link_regexes"] = normalize_string_list(raw_board.get("job_link_regexes", []))
        normalized_board["max_job_pages"] = max(
            1,
            min(200, safe_int(raw_board.get("max_job_pages", GENERIC_HTML_MAX_JOB_LINKS), GENERIC_HTML_MAX_JOB_LINKS)),
        )

    missing_fields = [
        field
        for field in COMPANY_BOARD_REQUIRED_FIELDS[platform]
        if not normalized_board.get(field)
    ]
    if missing_fields:
        return None

    return normalized_board


def load_company_boards() -> list[dict[str, object]]:
    boards_path = Path(COMPANY_BOARDS_FILE)
    if not boards_path.exists():
        return []

    try:
        with open(boards_path, encoding="utf-8") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: skipping {COMPANY_BOARDS_FILE} — {exc}", file=sys.stderr)
        return []

    if not isinstance(raw_data, list):
        print(f"Warning: {COMPANY_BOARDS_FILE} must contain a JSON list.", file=sys.stderr)
        return []

    normalized_boards = []
    seen_names = set()
    for index, raw_board in enumerate(raw_data):
        if not isinstance(raw_board, dict):
            print(f"Warning: skipping board #{index + 1} in {COMPANY_BOARDS_FILE} — expected an object.", file=sys.stderr)
            continue
        normalized_board = normalize_company_board(raw_board)
        if normalized_board is None:
            print(
                f"Warning: skipping board #{index + 1} in {COMPANY_BOARDS_FILE} — invalid or missing required fields.",
                file=sys.stderr,
            )
            continue
        if normalized_board["name"] in seen_names:
            print(f"Warning: skipping duplicate board name {normalized_board['name']!r}.", file=sys.stderr)
            continue
        normalized_boards.append(normalized_board)
        seen_names.add(str(normalized_board["name"]))

    return normalized_boards


def normalize_company_control_values(values: object) -> list[str]:
    normalized_values = []
    for value in values if isinstance(values, list) else [values] if values else []:
        normalized_company = normalize_company_name(clean_text(str(value)))
        if normalized_company:
            normalized_values.append(normalized_company)
    return dedupe_preserving_order(normalized_values)


def normalize_role_profile(raw_profile: dict[str, object], index: int) -> dict[str, object] | None:
    name = normalize_text(str(raw_profile.get("name", ""))) or f"role_profile_{index}"
    display_name = clean_text(str(raw_profile.get("display_name", ""))) or name.replace("_", " ").title()
    title_keywords = raw_profile.get("title_keywords")
    description_keywords = raw_profile.get("description_keywords")
    shared_keywords = raw_profile.get("keywords")
    title_entries = build_pattern_entries(
        title_keywords if isinstance(title_keywords, list) and title_keywords else shared_keywords or []
    )
    description_entries = build_pattern_entries(
        description_keywords if isinstance(description_keywords, list) and description_keywords else shared_keywords or []
    )
    if not title_entries and not description_entries:
        return None

    return {
        "name": name,
        "display_name": display_name,
        "title_entries": title_entries,
        "description_entries": description_entries,
        "title_boost": safe_int(raw_profile.get("title_boost", 0), 0),
        "description_boost": safe_int(raw_profile.get("description_boost", 0), 0),
        "priority": safe_int(raw_profile.get("priority", 0), 0),
    }


def normalize_role_profiles(raw_profiles: object) -> list[dict[str, object]]:
    profiles_source = raw_profiles if isinstance(raw_profiles, list) and raw_profiles else DEFAULT_ROLE_PROFILE_CONFIGS
    normalized_profiles = []
    seen_names = set()

    for index, raw_profile in enumerate(profiles_source):
        if not isinstance(raw_profile, dict):
            continue
        normalized = normalize_role_profile(raw_profile, index)
        if normalized is None:
            continue
        if normalized["name"] in seen_names:
            continue
        normalized_profiles.append(normalized)
        seen_names.add(str(normalized["name"]))

    return normalized_profiles


def load_job_search_config() -> dict[str, object]:
    raw_data: dict[str, object] = {}
    config_path = Path(JOB_SEARCH_CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw_data = loaded
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: skipping {JOB_SEARCH_CONFIG_FILE} — {exc}", file=sys.stderr)

    whitelist = normalize_company_control_values(raw_data.get("company_whitelist", []))
    blacklist = normalize_company_control_values(raw_data.get("company_blacklist", []))
    priority_companies = normalize_company_control_values(raw_data.get("priority_companies", []))
    daily_digest = raw_data.get("daily_digest", {}) if isinstance(raw_data.get("daily_digest"), dict) else {}
    feedback = raw_data.get("feedback", {}) if isinstance(raw_data.get("feedback"), dict) else {}
    digest_statuses = [
        status
        for status in normalize_string_list(daily_digest.get("include_statuses", DEFAULT_DAILY_DIGEST_STATUSES), lower=True)
        if status in APPLICATION_STATUSES
    ]

    return {
        "company_whitelist": whitelist,
        "company_blacklist": blacklist,
        "priority_companies": priority_companies,
        "company_whitelist_entries": build_pattern_entries(whitelist),
        "company_blacklist_entries": build_pattern_entries(blacklist),
        "priority_company_entries": build_pattern_entries(priority_companies),
        "role_profiles": normalize_role_profiles(raw_data.get("role_profiles")),
        "daily_digest": {
            "enabled": parse_bool(daily_digest.get("enabled", True), True),
            "hour_utc": max(0, min(23, safe_int(daily_digest.get("hour_utc", DEFAULT_DAILY_DIGEST_HOUR_UTC), DEFAULT_DAILY_DIGEST_HOUR_UTC))),
            "max_items": max(1, min(20, safe_int(daily_digest.get("max_items", DEFAULT_DAILY_DIGEST_MAX_ITEMS), DEFAULT_DAILY_DIGEST_MAX_ITEMS))),
            "include_statuses": digest_statuses or list(DEFAULT_DAILY_DIGEST_STATUSES),
        },
        "feedback": {
            "enabled": parse_bool(feedback.get("enabled", True), True),
            "min_samples": max(1, min(20, safe_int(feedback.get("min_samples", DEFAULT_FEEDBACK_MIN_SAMPLES), DEFAULT_FEEDBACK_MIN_SAMPLES))),
            "max_source_adjustment": max(
                1,
                min(
                    20,
                    safe_int(
                        feedback.get("max_source_adjustment", DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT),
                        DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT,
                    ),
                ),
            ),
            "max_keyword_adjustment": max(
                1,
                min(
                    20,
                    safe_int(
                        feedback.get("max_keyword_adjustment", DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT),
                        DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT,
                    ),
                ),
            ),
            "keyword_limit": max(
                1,
                min(8, safe_int(feedback.get("keyword_limit", DEFAULT_FEEDBACK_KEYWORD_LIMIT), DEFAULT_FEEDBACK_KEYWORD_LIMIT)),
            ),
            "new_reviewed_retention_days": max(
                30,
                min(
                    3650,
                    safe_int(
                        feedback.get("new_reviewed_retention_days", DEFAULT_NEW_REVIEWED_RETENTION_DAYS),
                        DEFAULT_NEW_REVIEWED_RETENTION_DAYS,
                    ),
                ),
            ),
            "rejected_retention_days": max(
                30,
                min(
                    3650,
                    safe_int(
                        feedback.get("rejected_retention_days", DEFAULT_REJECTED_RETENTION_DAYS),
                        DEFAULT_REJECTED_RETENTION_DAYS,
                    ),
                ),
            ),
            "applied_retention_days": max(
                30,
                min(
                    3650,
                    safe_int(
                        feedback.get("applied_retention_days", DEFAULT_APPLIED_RETENTION_DAYS),
                        DEFAULT_APPLIED_RETENTION_DAYS,
                    ),
                ),
            ),
            "interview_retention_days": max(
                30,
                min(
                    3650,
                    safe_int(
                        feedback.get("interview_retention_days", DEFAULT_INTERVIEW_RETENTION_DAYS),
                        DEFAULT_INTERVIEW_RETENTION_DAYS,
                    ),
                ),
            ),
        },
    }


def atomic_write_json(path: Path, payload: object) -> None:
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def load_feed_state() -> dict[str, dict[str, float]]:
    state_path = Path(FEED_STATE_FILE)
    if not state_path.exists():
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_feed_state(feed_state: dict[str, dict[str, float]]) -> None:
    atomic_write_json(Path(FEED_STATE_FILE), feed_state)


def is_feed_due(feed: dict[str, str | int], feed_state: dict[str, dict[str, float]], now_ts: float) -> bool:
    last_checked_at = feed_state.get(feed["name"], {}).get("last_checked_at", 0)
    return now_ts - last_checked_at >= int(feed["min_interval_seconds"])


def get_source_display_name(source: dict[str, object]) -> str:
    return clean_text(str(source.get("display_name", "") or source.get("name", "")))


def extract_csv_link(row: dict[str, object]) -> str:
    link_parts = [str(row.get("link", ""))]
    if row.get(None):
        link_parts.extend(str(part) for part in row[None])
    return ",".join(part for part in link_parts if part)


def load_existing_jobs() -> list[dict[str, str]]:
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        return []

    jobs = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            link = extract_csv_link(row)
            if link:
                jobs.append(
                    {
                        "time": str(row.get("time", "")),
                        "title": str(row.get("title", "")),
                        "description": str(row.get("description", "")),
                        "link": link,
                    }
                )
    return jobs


def append_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


def dedupe_preserving_order(values: list[str]) -> list[str]:
    unique_values = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        unique_values.append(value)
        seen.add(value)
    return unique_values


def load_seen_jobs_state() -> dict[str, object]:
    state_path = Path(SEEN_JOBS_STATE_FILE)
    if not state_path.exists():
        return fresh_seen_jobs_state()

    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return fresh_seen_jobs_state()

    if not isinstance(data, dict):
        return fresh_seen_jobs_state()

    reviewed_fingerprints = [
        clean_text(str(fingerprint))
        for fingerprint in data.get("reviewed_fingerprints", [])
        if clean_text(str(fingerprint))
    ]

    return {
        "reviewed_fingerprints": dedupe_preserving_order(reviewed_fingerprints)[-MAX_REVIEWED_FINGERPRINTS:],
        "last_run_utc": clean_text(str(data.get("last_run_utc", ""))),
    }


def save_seen_jobs_state(seen_jobs_state: dict[str, object]) -> None:
    atomic_write_json(Path(SEEN_JOBS_STATE_FILE), seen_jobs_state)


def record_reviewed_fingerprints(
    seen_jobs_state: dict[str, object],
    reviewed_fingerprints: set[str],
    fingerprints: list[str],
) -> None:
    for fingerprint in fingerprints:
        if not fingerprint or fingerprint in reviewed_fingerprints:
            continue
        seen_jobs_state["reviewed_fingerprints"].append(fingerprint)
        reviewed_fingerprints.add(fingerprint)


def prune_reviewed_fingerprints(
    seen_jobs_state: dict[str, object],
    reviewed_fingerprints: set[str],
) -> None:
    fingerprints = list(seen_jobs_state["reviewed_fingerprints"])[-MAX_REVIEWED_FINGERPRINTS:]
    seen_jobs_state["reviewed_fingerprints"] = fingerprints
    reviewed_fingerprints.clear()
    reviewed_fingerprints.update(fingerprints)


def normalize_pending_alert(payload: dict[str, object]) -> dict[str, object] | None:
    link = clean_text(str(payload.get("link", "")))
    title = clean_text(str(payload.get("title", "")))
    if not link or not title:
        return None

    raw_reasons = payload.get("reasons", [])
    reasons = []
    if isinstance(raw_reasons, list):
        reasons = [clean_text(str(reason)) for reason in raw_reasons if clean_text(str(reason))]

    return {
        "time": clean_text(str(payload.get("time", ""))),
        "title": title,
        "link": link,
        "score": safe_int(payload.get("score", 0) or 0),
        "reasons": reasons[:6],
        "source": clean_text(str(payload.get("source", ""))),
        "company": clean_text(str(payload.get("company", ""))),
        "shortlisted": parse_bool(payload.get("shortlisted", False), False),
        "company_control": clean_text(str(payload.get("company_control", ""))),
        "role_profile": clean_text(str(payload.get("role_profile", ""))),
    }


def load_alert_state() -> dict[str, object]:
    state_path = Path(ALERTS_STATE_FILE)
    if not state_path.exists():
        return fresh_alert_state()

    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return fresh_alert_state()

    if not isinstance(data, dict):
        return fresh_alert_state()

    pending_alerts = []
    seen_pending_links = set()
    for payload in data.get("pending_alerts", []):
        if not isinstance(payload, dict):
            continue
        normalized = normalize_pending_alert(payload)
        if normalized is None or normalized["link"] in seen_pending_links:
            continue
        pending_alerts.append(normalized)
        seen_pending_links.add(normalized["link"])

    alerted_links = [
        clean_text(str(link))
        for link in data.get("alerted_links", [])
        if clean_text(str(link))
    ]

    return {
        "alerted_links": dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:],
        "pending_alerts": pending_alerts,
        "last_run_utc": clean_text(str(data.get("last_run_utc", ""))),
        "last_delivery_utc": clean_text(str(data.get("last_delivery_utc", ""))),
        "last_delivery_error": clean_text(str(data.get("last_delivery_error", ""))),
    }


def save_alert_state(alert_state: dict[str, object]) -> None:
    atomic_write_json(Path(ALERTS_STATE_FILE), alert_state)


def save_matches_snapshot(run_time_utc: str, matches: list[dict[str, object]]) -> None:
    snapshot = {
        "generated_at": run_time_utc,
        "match_count": len(matches),
        "matches": matches,
    }
    atomic_write_json(Path(MATCHES_FILE), snapshot)


def normalize_company_control(value: object) -> str:
    normalized = normalize_text(str(value))
    return normalized if normalized in COMPANY_CONTROL_ORDER else "none"


def stronger_company_control(left: str, right: str) -> str:
    return left if COMPANY_CONTROL_ORDER.get(left, 0) >= COMPANY_CONTROL_ORDER.get(right, 0) else right


def normalize_application_status(value: object) -> str:
    normalized = normalize_text(str(value))
    return normalized if normalized in APPLICATION_STATUSES else "new"


def normalize_application_record(payload: dict[str, object]) -> dict[str, object] | None:
    title = clean_text(str(payload.get("title", "")))
    link = clean_text(str(payload.get("link", "")))
    description = clean_text(str(payload.get("description", "")))[:1500]
    company = clean_text(str(payload.get("company", "")))
    if not company and title:
        _, company = split_title_and_company(title)
    source = clean_text(str(payload.get("source", "")))

    raw_fingerprints = payload.get("fingerprints", [])
    if not isinstance(raw_fingerprints, list):
        raw_fingerprints = [raw_fingerprints] if raw_fingerprints else []
    fingerprints = [
        clean_text(str(fingerprint))
        for fingerprint in raw_fingerprints
        if clean_text(str(fingerprint))
    ]
    if not fingerprints and (title or link):
        fingerprints = build_review_fingerprints(title, description, link)

    raw_links = payload.get("links", [])
    if not isinstance(raw_links, list):
        raw_links = [raw_links] if raw_links else []
    links = [clean_text(str(item)) for item in raw_links if clean_text(str(item))]
    if link:
        links.insert(0, link)

    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = [raw_sources] if raw_sources else []
    sources = [clean_text(str(item)) for item in raw_sources if clean_text(str(item))]
    if source:
        sources.insert(0, source)

    if not title or not links or not fingerprints:
        return None

    raw_reasons = payload.get("reasons", [])
    if not isinstance(raw_reasons, list):
        raw_reasons = [raw_reasons] if raw_reasons else []
    reasons = [
        clean_text(str(reason))
        for reason in raw_reasons
        if clean_text(str(reason))
    ]

    raw_fit_notes = payload.get("why_this_fits", [])
    if not isinstance(raw_fit_notes, list):
        raw_fit_notes = [raw_fit_notes] if raw_fit_notes else []
    why_this_fits = [ensure_sentence(note) for note in raw_fit_notes if clean_text(str(note))]

    raw_resume_bullets = payload.get("resume_bullet_suggestions", [])
    if not isinstance(raw_resume_bullets, list):
        raw_resume_bullets = [raw_resume_bullets] if raw_resume_bullets else []
    resume_bullet_suggestions = [
        ensure_sentence(bullet)
        for bullet in raw_resume_bullets
        if clean_text(str(bullet))
    ]

    raw_feedback_keywords = payload.get("feedback_keywords", [])
    if not isinstance(raw_feedback_keywords, list):
        raw_feedback_keywords = [raw_feedback_keywords] if raw_feedback_keywords else []
    feedback_keywords = [
        normalize_text(str(keyword))
        for keyword in raw_feedback_keywords
        if normalize_text(str(keyword))
    ]

    score = safe_int(payload.get("score", 0), 0)
    best_score = max(score, safe_int(payload.get("best_score", score), score))
    company_control = normalize_company_control(payload.get("company_control", "none"))
    shortlisted = parse_bool(payload.get("shortlisted", company_control == "priority"), company_control == "priority")
    application_ready = parse_bool(
        payload.get("application_ready", shortlisted or best_score >= APPLICATION_READY_SCORE),
        shortlisted or best_score >= APPLICATION_READY_SCORE,
    )

    return {
        "title": title,
        "description": description,
        "company": company,
        "link": links[0],
        "links": dedupe_preserving_order(links),
        "source": sources[0] if sources else "",
        "sources": dedupe_preserving_order(sources),
        "status": normalize_application_status(payload.get("status", "new")),
        "shortlisted": shortlisted,
        "company_control": "priority" if shortlisted else company_control,
        "role_profile": clean_text(str(payload.get("role_profile", ""))),
        "score": score,
        "best_score": best_score,
        "reasons": reasons[:6],
        "why_this_fits": dedupe_preserving_order(why_this_fits)[:3],
        "resume_bullet_suggestions": dedupe_preserving_order(resume_bullet_suggestions)[:3],
        "intro_message": clean_text(str(payload.get("intro_message", ""))),
        "application_ready": application_ready,
        "notes": clean_text(str(payload.get("notes", ""))),
        "feedback_keywords": dedupe_preserving_order(feedback_keywords)[:8],
        "status_observed_utc": clean_text(str(payload.get("status_observed_utc", ""))),
        "applied_at_utc": clean_text(str(payload.get("applied_at_utc", ""))),
        "interviewed_at_utc": clean_text(str(payload.get("interviewed_at_utc", ""))),
        "rejected_at_utc": clean_text(str(payload.get("rejected_at_utc", ""))),
        "first_seen_utc": clean_text(str(payload.get("first_seen_utc", ""))),
        "last_seen_utc": clean_text(str(payload.get("last_seen_utc", ""))),
        "match_count": max(1, safe_int(payload.get("match_count", 1), 1)),
        "fingerprints": dedupe_preserving_order(fingerprints),
    }


def load_applications_state() -> dict[str, object]:
    state_path = Path(APPLICATIONS_FILE)
    if not state_path.exists():
        return fresh_applications_state()

    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return fresh_applications_state()

    if not isinstance(data, dict):
        return fresh_applications_state()

    applications = []
    seen_keys = set()
    for payload in data.get("applications", []):
        if not isinstance(payload, dict):
            continue
        normalized = normalize_application_record(payload)
        if normalized is None:
            continue
        dedupe_key = normalized["link"]
        if dedupe_key in seen_keys:
            continue
        applications.append(normalized)
        seen_keys.add(dedupe_key)

    return {
        "applications": applications[-MAX_APPLICATION_RECORDS:],
        "last_updated_utc": clean_text(str(data.get("last_updated_utc", ""))),
        "last_digest_utc": clean_text(str(data.get("last_digest_utc", ""))),
        "last_digest_date_utc": clean_text(str(data.get("last_digest_date_utc", ""))),
        "last_digest_error": clean_text(str(data.get("last_digest_error", ""))),
        "last_feedback_utc": clean_text(str(data.get("last_feedback_utc", ""))),
        "last_cleanup_utc": clean_text(str(data.get("last_cleanup_utc", ""))),
    }


def save_applications_state(applications_state: dict[str, object]) -> None:
    atomic_write_json(Path(APPLICATIONS_FILE), applications_state)


def evaluate_location_fit(
    normalized_full_text: str,
    preferred_locations: list[str],
    prefs: dict,
    lockouts: list[str],
) -> tuple[bool, str]:
    location_context = normalized_full_text[:1000]
    is_remote = any(
        re.search(rf"\b{word}\b", location_context)
        for word in ["remote", "anywhere", "wfh"]
    )
    is_hybrid = "hybrid" in location_context
    is_onsite = any(
        term in location_context
        for term in [
            "in office",
            "in-office",
            "onsite",
            "on site",
            "on-site",
            "office based",
            "office-based",
        ]
    )
    is_local = any(term in location_context for term in preferred_locations)
    is_locked_out = any(lock in location_context for lock in lockouts)

    if prefs.get("relocation", False):
        return True, "location fit: relocation allowed"

    if prefs.get("remote") and is_remote and not is_locked_out:
        return True, "location fit: remote compatible"
    if prefs.get("hybrid") and is_local and (is_hybrid or not is_remote):
        return True, "location fit: local/hybrid compatible"
    if prefs.get("onsite") and is_local and (is_onsite or not is_remote):
        return True, "location fit: local/onsite compatible"
    if is_locked_out:
        return False, "location reject: explicit geographic lockout"
    return False, "location reject: not aligned with preferences"


def normalize_currency_token(token: str) -> str:
    normalized = token.strip().lower()
    if normalized in {"£", "gbp", "pound", "pounds"}:
        return "gbp"
    if normalized in {"$", "usd", "us$", "dollar", "dollars"}:
        return "usd"
    if normalized in {"€", "eur", "euro", "euros"}:
        return "eur"
    return ""


def detect_salary_cadence(context: str) -> str:
    normalized = normalize_text(context)
    if re.search(r"\b(per|a)\s+hour\b|/hour\b|\bhourly\b", normalized):
        return "hour"
    if re.search(r"\b(per|a)\s+day\b|/day\b|\bdaily\b|\bday rate\b|\bday-rate\b", normalized):
        return "day"
    if re.search(r"\b(per|a)\s+month\b|/month\b|\bmonthly\b", normalized):
        return "month"
    return "year"


def parse_salary_amount(raw_amount: str, has_k_suffix: str | None) -> float:
    amount = float(raw_amount.replace(",", ""))
    if has_k_suffix:
        amount *= 1000
    return amount


def annualize_salary_to_gbp(amount: float, currency: str, cadence: str) -> int:
    rate = CURRENCY_TO_GBP[currency]
    multiplier = CADENCE_TO_ANNUAL_MULTIPLIER[cadence]
    return int(round(amount * rate * multiplier))


def build_salary_info(
    minimum_amount: float,
    maximum_amount: float,
    currency: str,
    cadence: str,
) -> dict[str, object]:
    low = annualize_salary_to_gbp(minimum_amount, currency, cadence)
    high = annualize_salary_to_gbp(maximum_amount, currency, cadence)
    return {
        "min_gbp": min(low, high),
        "max_gbp": max(low, high),
        "currency": currency,
        "cadence": cadence,
    }


def extract_salary_range_gbp(text: str) -> dict[str, object] | None:
    normalized = clean_text(text).lower().replace(",", "")
    range_patterns = [
        re.compile(
            r"(?P<currency>£|gbp|us\$|usd|\$|eur|€)\s*"
            r"(?P<minimum>\d+(?:\.\d+)?)\s*(?P<minimum_k>k)?\s*"
            r"(?:-|–|—|to)\s*"
            r"(?:(?:£|gbp|us\$|usd|\$|eur|€)\s*)?"
            r"(?P<maximum>\d+(?:\.\d+)?)\s*(?P<maximum_k>k)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<minimum>\d+(?:\.\d+)?)\s*(?P<minimum_k>k)?\s*"
            r"(?:-|–|—|to)\s*"
            r"(?P<maximum>\d+(?:\.\d+)?)\s*(?P<maximum_k>k)?\s*"
            r"(?P<currency>gbp|usd|eur|pounds?|dollars?|euros?)",
            re.IGNORECASE,
        ),
    ]
    single_patterns = [
        re.compile(
            r"(?P<currency>£|gbp|us\$|usd|\$|eur|€)\s*"
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<amount_k>k)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<amount_k>k)?\s*"
            r"(?P<currency>gbp|usd|eur|pounds?|dollars?|euros?)",
            re.IGNORECASE,
        ),
    ]

    for pattern in range_patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        currency = normalize_currency_token(match.group("currency"))
        if currency not in CURRENCY_TO_GBP:
            continue
        cadence = detect_salary_cadence(normalized[match.start(): match.end() + 32])
        minimum_amount = parse_salary_amount(match.group("minimum"), match.group("minimum_k"))
        maximum_amount = parse_salary_amount(match.group("maximum"), match.group("maximum_k"))
        if cadence == "year" and max(minimum_amount, maximum_amount) < 1000:
            continue
        return build_salary_info(minimum_amount, maximum_amount, currency, cadence)

    for pattern in single_patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        currency = normalize_currency_token(match.group("currency"))
        if currency not in CURRENCY_TO_GBP:
            continue
        cadence = detect_salary_cadence(normalized[match.start(): match.end() + 32])
        amount = parse_salary_amount(match.group("amount"), match.group("amount_k"))
        if cadence == "year" and amount < 1000:
            continue
        return build_salary_info(amount, amount, currency, cadence)

    return None


def format_salary_info_for_reason(salary_info: dict[str, object]) -> str:
    base = f"estimated GBP {salary_info['min_gbp']:,}-{salary_info['max_gbp']:,}"
    suffix = []
    if salary_info["currency"] != "gbp":
        suffix.append(str(salary_info["currency"]).upper())
    if salary_info["cadence"] != "year":
        suffix.append(str(salary_info["cadence"]))
    if suffix:
        return f"{base} from {' '.join(suffix)}"
    return base


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


def fetch_greenhouse_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    payload = fetch_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board['board_token']}/jobs?content=true"
    )
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
        location = clean_text(str(job.get("location", {}).get("name", ""))) if isinstance(job.get("location"), dict) else ""
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
        payload = fetch_json(
            f"{base_url}/v0/postings/{board['site']}?mode=json&limit={BOARD_PAGE_LIMIT}&skip={skip}"
        )
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
                    str(job.get("url", "") or job.get("shortlink", "") or job.get("application_url", ""))
                ),
            }
        )

    return items


def fetch_company_board_items(board: dict[str, object]) -> list[dict[str, str]]:
    platform = str(board["platform"])
    if platform == "greenhouse":
        return fetch_greenhouse_board_jobs(board)
    if platform == "lever":
        return fetch_lever_board_jobs(board)
    if platform == "ashby":
        return fetch_ashby_board_jobs(board)
    if platform == "workable":
        return fetch_workable_board_jobs(board)
    if platform == "generic_html":
        return fetch_generic_html_board_jobs(board)
    raise ValueError(f"Unsupported board platform: {platform}")


def apply_weight_map(text: str, weights: dict[str, int], reasons: list[str], prefix: str) -> int:
    matched_phrases = [phrase for phrase in weights if contains_phrase(text, phrase)]
    if not matched_phrases:
        return 0

    append_reason(reasons, f"{prefix}: {', '.join(matched_phrases[:3])}")
    return sum(weights[phrase] for phrase in matched_phrases)


def evaluate_company_preferences(company_name: str, search_config: dict[str, object]) -> dict[str, object]:
    normalized_company = normalize_company_name(company_name)
    if not normalized_company:
        return {
            "qualified": True,
            "score_delta": 0,
            "reason": "",
            "control": "none",
            "shortlisted": False,
        }

    blacklist_match = find_pattern_matches(normalized_company, search_config["company_blacklist_entries"], limit=1)
    if blacklist_match:
        return {
            "qualified": False,
            "score_delta": 0,
            "reason": f"company reject: blacklisted employer {blacklist_match[0]}",
            "control": "blacklist",
            "shortlisted": False,
        }

    priority_match = find_pattern_matches(normalized_company, search_config["priority_company_entries"], limit=1)
    if priority_match:
        return {
            "qualified": True,
            "score_delta": 14,
            "reason": f"company shortlist: {priority_match[0]}",
            "control": "priority",
            "shortlisted": True,
        }

    whitelist_match = find_pattern_matches(normalized_company, search_config["company_whitelist_entries"], limit=1)
    if whitelist_match:
        return {
            "qualified": True,
            "score_delta": 8,
            "reason": f"company whitelist: {whitelist_match[0]}",
            "control": "whitelist",
            "shortlisted": False,
        }

    return {
        "qualified": True,
        "score_delta": 0,
        "reason": "",
        "control": "none",
        "shortlisted": False,
    }


def evaluate_role_profile(
    normalized_title: str,
    normalized_desc: str,
    search_config: dict[str, object],
) -> dict[str, object] | None:
    best_match = None
    best_sort_key = None

    for profile in search_config["role_profiles"]:
        title_matches = find_pattern_matches(normalized_title, profile["title_entries"], limit=3)
        description_matches = [
            match
            for match in find_pattern_matches(normalized_desc, profile["description_entries"], limit=3)
            if match not in title_matches
        ]
        if not title_matches and not description_matches:
            continue

        score_delta = len(title_matches) * int(profile["title_boost"]) + len(description_matches) * int(
            profile["description_boost"]
        )
        sort_key = (score_delta, int(profile["priority"]), len(title_matches), len(description_matches))
        if best_sort_key is None or sort_key > best_sort_key:
            best_sort_key = sort_key
            best_match = {
                "name": str(profile["name"]),
                "display_name": str(profile["display_name"]),
                "score_delta": score_delta,
                "title_matches": title_matches,
                "description_matches": description_matches,
            }

    return best_match


def ensure_sentence(text: object) -> str:
    cleaned = clean_text(str(text)).strip()
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."


def truncate_text(text: object, limit: int = 180) -> str:
    cleaned = clean_text(str(text))
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[: max(0, limit - 3)].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{truncated}..." if truncated else cleaned[:limit]


def build_focus_phrases(*sources: object) -> list[str]:
    phrases = []
    for source in sources:
        values = source if isinstance(source, list) else [source] if source else []
        for value in values:
            normalized = normalize_text(str(value))
            if normalized:
                phrases.append(normalized)
    return dedupe_preserving_order(phrases)


def select_resume_evidence(profile: dict[str, object], focus_phrases: list[str], limit: int = 3) -> list[dict[str, object]]:
    experience_entries = list(profile.get("experience_entries", []))
    if not experience_entries:
        return []

    focus_entries = build_pattern_entries(focus_phrases)
    ranked_entries = []
    fallback_entries = []

    for index, entry in enumerate(experience_entries):
        if not isinstance(entry, dict):
            continue
        entry_text = clean_text(str(entry.get("text", "")))
        if not entry_text:
            continue

        matches = find_pattern_matches(str(entry.get("normalized_text", "")), focus_entries, limit=4) if focus_entries else []
        candidate = {
            "label": clean_text(str(entry.get("label", ""))) or "Experience",
            "role": clean_text(str(entry.get("role", ""))),
            "organization": clean_text(str(entry.get("organization", ""))),
            "text": entry_text,
            "matches": matches,
        }
        if matches:
            rank = len(matches) * 6 + (1 if candidate["organization"] else 0) + (1 if candidate["label"] != "Resume summary" else 0)
            ranked_entries.append((rank, -index, candidate))
        elif candidate["label"] != "Resume summary":
            fallback_entries.append(candidate)

    if ranked_entries:
        ranked_entries.sort(reverse=True)
        return [candidate for _, _, candidate in ranked_entries[:limit]]

    return fallback_entries[:limit]


def build_why_this_fits_notes(
    company_name: str,
    company_preferences: dict[str, object],
    role_profile_match: dict[str, object],
    title_alignment_matches: list[str],
    skill_focus_phrases: list[str],
    evidence_entries: list[dict[str, object]],
) -> list[str]:
    notes = []

    if company_preferences["control"] == "priority" and company_name:
        notes.append(ensure_sentence(f"{company_name} is on your priority-employer shortlist, so this role deserves fast review"))

    if role_profile_match.get("display_name"):
        if title_alignment_matches:
            notes.append(
                ensure_sentence(
                    f"The role sits in your {role_profile_match['display_name']} lane and overlaps with target titles like {', '.join(title_alignment_matches[:3])}"
                )
            )
        else:
            notes.append(ensure_sentence(f"The role sits in your {role_profile_match['display_name']} lane"))
    elif title_alignment_matches:
        notes.append(ensure_sentence(f"The title overlaps directly with your target role focus: {', '.join(title_alignment_matches[:3])}"))

    if skill_focus_phrases:
        notes.append(
            ensure_sentence(
                f"The job text overlaps with your hands-on stack in {', '.join(skill_focus_phrases[:4])}"
            )
        )

    if evidence_entries:
        top_evidence = evidence_entries[0]
        notes.append(
            ensure_sentence(
                f"You already have direct evidence from {top_evidence['label']}: {truncate_text(top_evidence['text'], 170)}"
            )
        )

    return dedupe_preserving_order([note for note in notes if note])[:3]


def build_resume_bullet_suggestions(evidence_entries: list[dict[str, object]]) -> list[str]:
    suggestions = []
    for entry in evidence_entries:
        bullet = ensure_sentence(truncate_text(entry.get("text", ""), 220))
        if bullet:
            suggestions.append(bullet)
    return dedupe_preserving_order(suggestions)[:3]


def build_intro_message(
    profile: dict[str, object],
    role_title: str,
    company_name: str,
    skill_focus_phrases: list[str],
    evidence_entries: list[dict[str, object]],
) -> str:
    candidate_name = clean_text(str(profile.get("candidate_name", "")))
    candidate_title = clean_text(str(profile.get("candidate_title", ""))) or "IT support professional"
    greeting = f"Hi {company_name} team," if company_name else "Hi hiring team,"
    intro_subject = f"I'm {candidate_name}, currently working as {candidate_title}" if candidate_name else f"I'm a {candidate_title}"
    skill_clause = ", ".join(skill_focus_phrases[:3]) if skill_focus_phrases else "IT support, Microsoft 365, and identity/access administration"
    role_name = role_title or "this role"
    evidence_clause = ""
    if evidence_entries:
        evidence_clause = truncate_text(evidence_entries[0]["text"], 120).rstrip(".")

    lines = [
        f"{greeting} {intro_subject} with hands-on experience in {skill_clause}.",
        f"I'm interested in the {role_name} role because it lines up closely with the support and systems work I already do.",
    ]
    if evidence_clause:
        lines.append(f"A relevant example from my recent work is: {evidence_clause}.")
    lines.append("I'd welcome the chance to discuss how I could contribute.")
    return " ".join(lines)


def build_application_materials(
    profile: dict[str, object],
    role_title: str,
    company_name: str,
    score: int,
    company_preferences: dict[str, object],
    role_profile_match: dict[str, object],
    title_alignment_matches: list[str],
    skill_focus_phrases: list[str],
) -> dict[str, object]:
    evidence_entries = select_resume_evidence(profile, build_focus_phrases(title_alignment_matches, skill_focus_phrases), limit=3)
    why_this_fits = build_why_this_fits_notes(
        company_name,
        company_preferences,
        role_profile_match,
        title_alignment_matches,
        skill_focus_phrases,
        evidence_entries,
    )
    return {
        "why_this_fits": why_this_fits,
        "resume_bullet_suggestions": build_resume_bullet_suggestions(evidence_entries),
        "intro_message": build_intro_message(profile, role_title, company_name, skill_focus_phrases, evidence_entries),
        "application_ready": bool(company_preferences.get("shortlisted") or score >= APPLICATION_READY_SCORE),
    }


def apply_feedback_adjustments(
    score: int,
    reasons: list[str],
    source_label: str,
    feedback_keywords: list[str],
    feedback_profile: dict[str, object],
) -> int:
    if not feedback_profile.get("enabled", False):
        return score

    score_delta = 0
    source_key = normalize_text(source_label)
    source_adjustment = safe_int(feedback_profile["source_adjustments"].get(source_key, 0), 0)
    if source_adjustment:
        score_delta += source_adjustment
        append_reason(
            reasons,
            f"feedback source {'boost' if source_adjustment > 0 else 'penalty'}: {clean_text(source_label)} ({source_adjustment:+d})",
        )

    keyword_adjustments = []
    for keyword in dedupe_preserving_order(feedback_keywords):
        adjustment = safe_int(feedback_profile["keyword_adjustments"].get(keyword, 0), 0)
        if adjustment:
            keyword_adjustments.append((keyword, adjustment))

    keyword_adjustments.sort(key=lambda item: (abs(item[1]), item[1], item[0]), reverse=True)
    selected_adjustments = keyword_adjustments[: int(feedback_profile["keyword_limit"])]
    if selected_adjustments:
        total_keyword_delta = sum(item[1] for item in selected_adjustments)
        max_keyword_delta = int(feedback_profile["max_keyword_adjustment"])
        total_keyword_delta = max(-max_keyword_delta, min(max_keyword_delta, total_keyword_delta))
        if total_keyword_delta:
            score_delta += total_keyword_delta
            adjustment_text = ", ".join(f"{keyword} ({adjustment:+d})" for keyword, adjustment in selected_adjustments[:3])
            append_reason(
                reasons,
                f"feedback keywords {'boost' if total_keyword_delta > 0 else 'penalty'}: {adjustment_text}",
            )

    return score + score_delta


def score_job(
    item: dict[str, str],
    source_label: str,
    profile: dict[str, object],
    search_config: dict[str, object],
    feedback_profile: dict[str, object],
    current_run_ts: str,
    lockouts: list[str],
) -> dict[str, object]:
    raw_title = clean_text(item["title"])
    raw_desc = clean_text(item["description"])
    role_title, company = split_title_and_company(raw_title)
    normalized_title = normalize_text(role_title or raw_title)
    normalized_desc = normalize_text(raw_desc)
    normalized_full_text = normalize_text(f"{raw_title} {raw_desc}")
    reasons: list[str] = []

    prefs = profile["prefs"]
    preferred_locations = profile["preferred_locations"]
    target_role_entries = profile["target_role_entries"]
    skill_entries = profile["skill_entries"]
    competency_entries = profile["competency_entries"]

    location_ok, location_reason = evaluate_location_fit(
        normalized_full_text,
        preferred_locations,
        prefs,
        lockouts,
    )
    append_reason(reasons, location_reason)
    if not location_ok:
        return {
            "qualified": False,
            "score": 0,
            "reasons": reasons,
        }

    score = 0
    company_name = company or source_label

    company_preferences = evaluate_company_preferences(company_name, search_config)
    if company_preferences["reason"]:
        append_reason(reasons, str(company_preferences["reason"]))
    if not company_preferences["qualified"]:
        return {
            "qualified": False,
            "score": 0,
            "reasons": reasons,
        }
    score += int(company_preferences["score_delta"])

    target_title_matches = find_pattern_matches(normalized_title, target_role_entries, limit=3)
    if target_title_matches:
        score += min(48, 34 + 7 * (len(target_title_matches) - 1))
        append_reason(reasons, f"target role in title: {', '.join(target_title_matches)}")

    target_desc_matches = [
        match
        for match in find_pattern_matches(normalized_desc, target_role_entries, limit=3)
        if match not in target_title_matches
    ]
    if target_desc_matches:
        score += min(18, 9 * len(target_desc_matches))
        append_reason(reasons, f"target role in description: {', '.join(target_desc_matches)}")

    skill_title_matches = find_pattern_matches(normalized_title, skill_entries, limit=4)
    if skill_title_matches:
        score += min(18, 6 * len(skill_title_matches))
        append_reason(reasons, f"skills in title: {', '.join(skill_title_matches)}")

    skill_desc_matches = [
        match
        for match in find_pattern_matches(normalized_desc, skill_entries, limit=5)
        if match not in skill_title_matches
    ]
    if skill_desc_matches:
        score += min(20, 4 * len(skill_desc_matches))
        append_reason(reasons, f"skills in description: {', '.join(skill_desc_matches)}")

    competency_matches = find_pattern_matches(normalized_full_text, competency_entries, limit=4)
    if competency_matches:
        score += min(12, 3 * len(competency_matches))
        append_reason(reasons, f"competencies matched: {', '.join(competency_matches)}")

    score += apply_weight_map(normalized_title, POSITIVE_TITLE_WEIGHTS, reasons, "title boost")
    score -= apply_weight_map(normalized_title, NEGATIVE_TITLE_WEIGHTS, reasons, "title penalty")
    score -= apply_weight_map(normalized_title, SENIORITY_PENALTIES, reasons, "seniority penalty")

    role_profile_match = evaluate_role_profile(normalized_title, normalized_desc, search_config)
    if role_profile_match:
        score += int(role_profile_match["score_delta"])
        role_profile_reason_parts = []
        if role_profile_match["title_matches"]:
            role_profile_reason_parts.append(f"title: {', '.join(role_profile_match['title_matches'])}")
        if role_profile_match["description_matches"]:
            role_profile_reason_parts.append(f"description: {', '.join(role_profile_match['description_matches'])}")
        append_reason(
            reasons,
            f"role profile {role_profile_match['display_name']}: {'; '.join(role_profile_reason_parts)}",
        )
    else:
        role_profile_match = {
            "name": "",
            "display_name": "",
            "score_delta": 0,
            "title_matches": [],
            "description_matches": [],
        }

    salary_range = extract_salary_range_gbp(f"{raw_title} {raw_desc}")
    minimum_salary_gbp = int(prefs.get("minimum_salary_gbp", 0) or 0)
    if salary_range and minimum_salary_gbp:
        salary_min = safe_int(salary_range["min_gbp"])
        salary_max = safe_int(salary_range["max_gbp"])
        salary_reason = format_salary_info_for_reason(salary_range)
        if salary_max < minimum_salary_gbp:
            score -= 18
            append_reason(reasons, f"salary penalty: {salary_reason} is below preference")
        elif salary_min >= minimum_salary_gbp:
            score += 4
            append_reason(reasons, f"salary fit: {salary_reason}")

    title_alignment_matches = dedupe_preserving_order(target_title_matches + role_profile_match["title_matches"])
    skill_focus_phrases = build_focus_phrases(
        skill_title_matches,
        skill_desc_matches,
        competency_matches,
        role_profile_match["description_matches"],
    )
    feedback_keywords = dedupe_preserving_order(build_focus_phrases(title_alignment_matches, skill_focus_phrases))[:8]
    score = apply_feedback_adjustments(
        score,
        reasons,
        source_label,
        feedback_keywords,
        feedback_profile,
    )
    application_materials = build_application_materials(
        profile,
        role_title or raw_title,
        company_name,
        score,
        company_preferences,
        role_profile_match,
        title_alignment_matches,
        skill_focus_phrases,
    )

    candidate = {
        "time": current_run_ts,
        "title": raw_title,
        "description": raw_desc[:1500],
        "link": clean_text(item["link"]),
        "source": source_label,
        "company": company_name,
        "score": score,
        "reasons": reasons[:6],
        "shortlisted": bool(company_preferences["shortlisted"]),
        "company_control": str(company_preferences["control"]),
        "role_profile": str(role_profile_match["display_name"] or role_profile_match["name"]),
        "why_this_fits": application_materials["why_this_fits"],
        "resume_bullet_suggestions": application_materials["resume_bullet_suggestions"],
        "intro_message": application_materials["intro_message"],
        "application_ready": bool(application_materials["application_ready"]),
        "feedback_keywords": feedback_keywords,
    }

    return {
        "qualified": score >= MIN_MATCH_SCORE,
        "score": score,
        "reasons": reasons[:6],
        "candidate": candidate,
        "match": candidate if score >= MIN_MATCH_SCORE else None,
    }


def queue_pending_alerts(alert_state: dict[str, object], matches: list[dict[str, object]]) -> int:
    pending_alerts = alert_state["pending_alerts"]
    pending_links = {str(alert["link"]) for alert in pending_alerts}
    alerted_links = set(str(link) for link in alert_state["alerted_links"])
    queued = 0

    for match in matches:
        link = str(match["link"])
        if link in pending_links or link in alerted_links:
            continue
        pending_alerts.append(
            {
                "time": match["time"],
                "title": match["title"],
                "link": link,
                "score": match["score"],
                "reasons": match["reasons"],
                "source": match["source"],
                "company": match.get("company", ""),
                "shortlisted": bool(match.get("shortlisted", False)),
                "company_control": clean_text(str(match.get("company_control", ""))),
                "role_profile": clean_text(str(match.get("role_profile", ""))),
            }
        )
        pending_links.add(link)
        queued += 1

    return queued


def load_telegram_settings() -> tuple[str, str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    thread_id = os.environ.get("TELEGRAM_THREAD_ID", "").strip()
    return token, chat_id, thread_id


def format_alert_message(alert: dict[str, object]) -> str:
    lines = [f"Job Match ({alert['score']}): {alert['title']}"]
    if alert.get("company"):
        lines.append(f"Company: {alert['company']}")
    if alert.get("shortlisted"):
        lines.append("Priority: shortlisted employer")
    elif alert.get("company_control") == "whitelist":
        lines.append("Priority: company whitelist")
    if alert.get("role_profile"):
        lines.append(f"Role Profile: {alert['role_profile']}")
    if alert.get("source"):
        lines.append(f"Source: {alert['source']}")
    if alert.get("reasons"):
        reasons = "; ".join(str(reason) for reason in alert["reasons"][:2])
        lines.append(f"Why: {reasons}")
    lines.append(str(alert["link"]))
    return "\n".join(lines)


def send_telegram_message(message: str, token: str, chat_id: str, thread_id: str) -> tuple[bool, str]:
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "true",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode(payload).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return False, clean_text(str(exc))

    try:
        payload_json = json.loads(body)
    except json.JSONDecodeError:
        return False, "Telegram API returned invalid JSON"

    if payload_json.get("ok") is True:
        return True, ""
    return False, clean_text(str(payload_json.get("description", "Telegram API error")))


def deliver_pending_alerts(alert_state: dict[str, object], current_run_ts: str) -> tuple[int, str]:
    pending_alerts = list(alert_state["pending_alerts"])
    if not pending_alerts:
        alert_state["last_delivery_error"] = ""
        return 0, ""

    token, chat_id, thread_id = load_telegram_settings()
    if not token or not chat_id:
        message = "Telegram credentials not configured; alerts left queued in alerts_state.json."
        alert_state["last_delivery_error"] = message
        return 0, message

    alerted_links = list(alert_state["alerted_links"])
    alerted_link_set = set(alerted_links)
    sent_count = 0

    for index, alert in enumerate(pending_alerts):
        link = str(alert["link"])
        if link in alerted_link_set:
            continue

        ok, error = send_telegram_message(format_alert_message(alert), token, chat_id, thread_id)
        if not ok:
            alert_state["pending_alerts"] = pending_alerts[index:]
            alert_state["alerted_links"] = dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:]
            alert_state["last_delivery_error"] = error
            return sent_count, error

        alerted_links.append(link)
        alerted_link_set.add(link)
        sent_count += 1

    alert_state["pending_alerts"] = []
    alert_state["alerted_links"] = dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:]
    alert_state["last_delivery_utc"] = current_run_ts
    alert_state["last_delivery_error"] = ""
    return sent_count, ""


def parse_iso_utc(value: object) -> datetime | None:
    cleaned = clean_text(str(value))
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_application_timestamp(application: dict[str, object]) -> datetime | None:
    timestamps = [
        parse_iso_utc(application.get("rejected_at_utc", "")),
        parse_iso_utc(application.get("interviewed_at_utc", "")),
        parse_iso_utc(application.get("applied_at_utc", "")),
        parse_iso_utc(application.get("last_seen_utc", "")),
        parse_iso_utc(application.get("status_observed_utc", "")),
        parse_iso_utc(application.get("first_seen_utc", "")),
    ]
    candidates = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(candidates) if candidates else None


def sync_application_outcomes(applications_state: dict[str, object], observed_at_utc: str) -> None:
    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        application["status"] = status
        fallback_observed_utc = clean_text(str(application.get("last_seen_utc", ""))) or clean_text(
            str(application.get("first_seen_utc", ""))
        ) or observed_at_utc
        if not clean_text(str(application.get("status_observed_utc", ""))):
            application["status_observed_utc"] = fallback_observed_utc

        if status in {"applied", "interview", "rejected"} and not clean_text(str(application.get("applied_at_utc", ""))):
            application["applied_at_utc"] = fallback_observed_utc
        if status == "interview" and not clean_text(str(application.get("interviewed_at_utc", ""))):
            application["interviewed_at_utc"] = fallback_observed_utc
        if status == "rejected" and not clean_text(str(application.get("rejected_at_utc", ""))):
            application["rejected_at_utc"] = fallback_observed_utc


def prune_applications_state(
    applications_state: dict[str, object],
    search_config: dict[str, object],
    current_run_ts: str,
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    feedback_settings = search_config["feedback"]
    before_count = len(applications_state["applications"])
    removed_by_status: dict[str, int] = {}
    retained = []

    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        if status in {"new", "reviewed"}:
            retention_days = int(feedback_settings["new_reviewed_retention_days"])
        elif status == "rejected":
            retention_days = int(feedback_settings["rejected_retention_days"])
        elif status == "interview":
            retention_days = int(feedback_settings["interview_retention_days"])
        else:
            retention_days = int(feedback_settings["applied_retention_days"])

        if parse_bool(application.get("shortlisted", False), False):
            retention_days *= 2

        reference_dt = latest_application_timestamp(application)
        if reference_dt is None:
            retained.append(application)
            continue

        age_days = max(0, int((current_dt - reference_dt).days))
        if age_days > retention_days:
            removed_by_status[status] = removed_by_status.get(status, 0) + 1
            continue
        retained.append(application)

    applications_state["applications"] = retained[-MAX_APPLICATION_RECORDS:]
    applications_state["last_cleanup_utc"] = current_run_ts
    return {
        "before_count": before_count,
        "after_count": len(applications_state["applications"]),
        "removed_count": before_count - len(applications_state["applications"]),
        "removed_by_status": removed_by_status,
        "retention_days": {
            "new_reviewed": int(feedback_settings["new_reviewed_retention_days"]),
            "rejected": int(feedback_settings["rejected_retention_days"]),
            "applied": int(feedback_settings["applied_retention_days"]),
            "interview": int(feedback_settings["interview_retention_days"]),
        },
    }


def fresh_feedback_counts() -> dict[str, int]:
    return {
        "total": 0,
        "applied": 0,
        "interview": 0,
        "rejected": 0,
    }


def increment_feedback_counts(counter: dict[str, int], status: str) -> None:
    if status not in OUTCOME_RELEVANT_STATUSES:
        return
    counter["total"] += 1
    counter[status] += 1


def compute_feedback_adjustment(counts: dict[str, int], max_adjustment: int, min_samples: int) -> int:
    total = int(counts.get("total", 0))
    if total < min_samples:
        return 0

    interview_rate = counts.get("interview", 0) / total
    applied_rate = counts.get("applied", 0) / total
    rejected_rate = counts.get("rejected", 0) / total
    raw_score = interview_rate + (applied_rate * 0.2) - (rejected_rate * 0.7)
    return max(-max_adjustment, min(max_adjustment, int(round(raw_score * max_adjustment))))


def build_feedback_metrics(
    current_run_ts: str,
    applications_state: dict[str, object],
    search_config: dict[str, object],
    cleanup_summary: dict[str, object],
) -> dict[str, object]:
    feedback_settings = search_config["feedback"]
    status_counts = {status: 0 for status in sorted(APPLICATION_STATUSES)}
    outcome_sample_count = 0
    source_counters: dict[str, dict[str, int]] = {}
    keyword_counters: dict[str, dict[str, int]] = {}
    source_labels: dict[str, str] = {}

    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        status_counts[status] += 1
        if status not in OUTCOME_RELEVANT_STATUSES:
            continue
        outcome_sample_count += 1

        source_values = [
            normalize_text(value)
            for value in application.get("sources", [])
            if normalize_text(value)
        ]
        if not source_values and normalize_text(application.get("source", "")):
            source_values = [normalize_text(application.get("source", ""))]

        for source_key in dedupe_preserving_order(source_values):
            source_counters.setdefault(source_key, fresh_feedback_counts())
            increment_feedback_counts(source_counters[source_key], status)
            source_labels.setdefault(source_key, clean_text(str(application.get("source", ""))) or source_key)

        keyword_values = [
            normalize_text(value)
            for value in application.get("feedback_keywords", [])
            if normalize_text(value)
        ]
        for keyword in dedupe_preserving_order(keyword_values):
            keyword_counters.setdefault(keyword, fresh_feedback_counts())
            increment_feedback_counts(keyword_counters[keyword], status)

    def build_metric_rows(
        counters: dict[str, dict[str, int]],
        max_adjustment: int,
        label_resolver,
    ) -> list[dict[str, object]]:
        rows = []
        for key, counts in counters.items():
            adjustment = compute_feedback_adjustment(
                counts,
                max_adjustment=max_adjustment,
                min_samples=int(feedback_settings["min_samples"]),
            )
            total = int(counts["total"])
            interview_rate = round((counts["interview"] / total) if total else 0.0, 3)
            rejected_rate = round((counts["rejected"] / total) if total else 0.0, 3)
            rows.append(
                {
                    "key": key,
                    "label": label_resolver(key),
                    "total": total,
                    "applied": int(counts["applied"]),
                    "interview": int(counts["interview"]),
                    "rejected": int(counts["rejected"]),
                    "interview_rate": interview_rate,
                    "rejected_rate": rejected_rate,
                    "recommended_adjustment": adjustment,
                }
            )
        rows.sort(
            key=lambda row: (
                int(row["recommended_adjustment"]),
                int(row["interview"]),
                -int(row["rejected"]),
                int(row["total"]),
                clean_text(str(row["label"])),
            ),
            reverse=True,
        )
        return rows

    source_metrics = build_metric_rows(
        source_counters,
        max_adjustment=int(feedback_settings["max_source_adjustment"]),
        label_resolver=lambda key: source_labels.get(key, key),
    )
    keyword_metrics = build_metric_rows(
        keyword_counters,
        max_adjustment=int(feedback_settings["max_keyword_adjustment"]),
        label_resolver=lambda key: key,
    )

    snapshot = {
        "generated_at": current_run_ts,
        "feedback_enabled": bool(feedback_settings["enabled"]),
        "status_counts": status_counts,
        "outcome_sample_count": outcome_sample_count,
        "top_positive_sources": [row for row in source_metrics if int(row["recommended_adjustment"]) > 0][:5],
        "top_negative_sources": [row for row in source_metrics if int(row["recommended_adjustment"]) < 0][:5],
        "top_positive_keywords": [row for row in keyword_metrics if int(row["recommended_adjustment"]) > 0][:8],
        "top_negative_keywords": [row for row in keyword_metrics if int(row["recommended_adjustment"]) < 0][:8],
        "source_metrics": source_metrics[:25],
        "keyword_metrics": keyword_metrics[:40],
        "cleanup": cleanup_summary,
    }

    return {
        "snapshot": snapshot,
        "enabled": bool(feedback_settings["enabled"]),
        "keyword_limit": int(feedback_settings["keyword_limit"]),
        "max_keyword_adjustment": int(feedback_settings["max_keyword_adjustment"]),
        "source_adjustments": {
            row["key"]: int(row["recommended_adjustment"])
            for row in source_metrics
            if int(row["recommended_adjustment"]) != 0
        },
        "keyword_adjustments": {
            row["key"]: int(row["recommended_adjustment"])
            for row in keyword_metrics
            if int(row["recommended_adjustment"]) != 0
        },
    }


def save_feedback_metrics_snapshot(snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(FEEDBACK_METRICS_FILE), snapshot)


def find_application_record(
    applications: list[dict[str, object]],
    fingerprints: list[str],
    link: str,
) -> dict[str, object] | None:
    fingerprint_set = set(fingerprints)
    for application in applications:
        existing_links = set(str(item) for item in application.get("links", []))
        if link and link in existing_links:
            return application
        existing_fingerprints = set(str(item) for item in application.get("fingerprints", []))
        if fingerprint_set and existing_fingerprints.intersection(fingerprint_set):
            return application
    return None


def upsert_application_record(
    applications_state: dict[str, object],
    payload: dict[str, object],
    seen_at_utc: str,
) -> bool:
    application = normalize_application_record(
        {
            **payload,
            "first_seen_utc": clean_text(str(payload.get("first_seen_utc", ""))) or seen_at_utc,
            "last_seen_utc": seen_at_utc,
        }
    )
    if application is None:
        return False

    existing = find_application_record(
        applications_state["applications"],
        application["fingerprints"],
        application["link"],
    )
    if existing is None:
        applications_state["applications"].append(application)
        applications_state["applications"] = applications_state["applications"][-MAX_APPLICATION_RECORDS:]
        return True

    existing["title"] = application["title"] or existing["title"]
    if application["description"] and len(application["description"]) >= len(str(existing.get("description", ""))):
        existing["description"] = application["description"]
    existing["company"] = application["company"] or existing["company"]
    existing["link"] = application["link"] or existing["link"]
    existing["links"] = dedupe_preserving_order(application["links"] + list(existing.get("links", [])))
    existing["source"] = application["source"] or existing["source"]
    existing["sources"] = dedupe_preserving_order(application["sources"] + list(existing.get("sources", [])))
    existing["status"] = normalize_application_status(existing.get("status", application["status"]))
    existing["shortlisted"] = bool(existing.get("shortlisted", False) or application["shortlisted"])
    existing["company_control"] = stronger_company_control(
        normalize_company_control(existing.get("company_control", "none")),
        normalize_company_control(application["company_control"]),
    )
    if existing["shortlisted"]:
        existing["company_control"] = "priority"
    existing["role_profile"] = application["role_profile"] or clean_text(str(existing.get("role_profile", "")))
    existing["score"] = max(safe_int(existing.get("score", 0), 0), application["score"])
    existing["best_score"] = max(safe_int(existing.get("best_score", 0), 0), application["best_score"], existing["score"])
    existing["reasons"] = dedupe_preserving_order(application["reasons"] + list(existing.get("reasons", [])))[:6]
    existing["why_this_fits"] = dedupe_preserving_order(
        application["why_this_fits"] + list(existing.get("why_this_fits", []))
    )[:3]
    existing["resume_bullet_suggestions"] = dedupe_preserving_order(
        application["resume_bullet_suggestions"] + list(existing.get("resume_bullet_suggestions", []))
    )[:3]
    existing["intro_message"] = application["intro_message"] or clean_text(str(existing.get("intro_message", "")))
    existing["application_ready"] = bool(
        parse_bool(existing.get("application_ready", False), False) or application["application_ready"]
    )
    existing["feedback_keywords"] = dedupe_preserving_order(
        application["feedback_keywords"] + list(existing.get("feedback_keywords", []))
    )[:8]
    existing["status_observed_utc"] = clean_text(str(existing.get("status_observed_utc", ""))) or clean_text(
        str(application.get("status_observed_utc", ""))
    )
    existing["applied_at_utc"] = clean_text(str(existing.get("applied_at_utc", ""))) or clean_text(
        str(application.get("applied_at_utc", ""))
    )
    existing["interviewed_at_utc"] = clean_text(str(existing.get("interviewed_at_utc", ""))) or clean_text(
        str(application.get("interviewed_at_utc", ""))
    )
    existing["rejected_at_utc"] = clean_text(str(existing.get("rejected_at_utc", ""))) or clean_text(
        str(application.get("rejected_at_utc", ""))
    )
    existing["notes"] = clean_text(str(existing.get("notes", "")))
    existing["first_seen_utc"] = clean_text(str(existing.get("first_seen_utc", ""))) or seen_at_utc
    existing["last_seen_utc"] = seen_at_utc
    existing["match_count"] = max(1, safe_int(existing.get("match_count", 1), 1) + 1)
    existing["fingerprints"] = dedupe_preserving_order(
        list(existing.get("fingerprints", [])) + application["fingerprints"]
    )
    return False


def seed_applications_from_existing_jobs(
    applications_state: dict[str, object],
    existing_jobs: list[dict[str, str]],
) -> int:
    if applications_state["applications"] or not existing_jobs:
        return 0

    created = 0
    for job in existing_jobs:
        if upsert_application_record(
            applications_state,
            {
                "title": job["title"],
                "description": job["description"],
                "link": job["link"],
                "company": split_title_and_company(job["title"])[1],
                "status": "new",
                "score": 0,
                "best_score": 0,
                "reasons": [],
            },
            job["time"] or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ):
            created += 1

    return created


def rank_application_for_digest(application: dict[str, object], current_dt: datetime) -> tuple[int, float]:
    last_seen_dt = parse_iso_utc(application.get("last_seen_utc", "")) or parse_iso_utc(application.get("first_seen_utc", ""))
    age_hours = 9999.0
    freshness_bonus = 0.0
    if last_seen_dt is not None:
        age_hours = max(0.0, (current_dt - last_seen_dt).total_seconds() / 3600)
        freshness_bonus = max(0.0, 72.0 - age_hours) / 6.0

    company_control = normalize_company_control(application.get("company_control", "none"))
    status = normalize_application_status(application.get("status", "new"))
    status_bonus = {
        "new": 8,
        "reviewed": 4,
        "applied": 1,
        "interview": 2,
        "rejected": -50,
    }.get(status, 0)
    company_bonus = 16 if parse_bool(application.get("shortlisted", False), False) else 8 if company_control == "whitelist" else 0
    rank = int(
        round(
            max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0))
            + freshness_bonus
            + company_bonus
            + status_bonus
        )
    )
    return rank, age_hours


def build_daily_digest_snapshot(
    current_run_ts: str,
    applications_state: dict[str, object],
    search_config: dict[str, object],
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    digest_settings = search_config["daily_digest"]
    items = []

    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        if status not in digest_settings["include_statuses"]:
            continue

        rank, age_hours = rank_application_for_digest(application, current_dt)
        items.append(
            {
                "title": str(application["title"]),
                "company": clean_text(str(application.get("company", ""))) or clean_text(str(application.get("source", ""))),
                "link": str(application["link"]),
                "status": status,
                "score": max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0)),
                "rank": rank,
                "shortlisted": parse_bool(application.get("shortlisted", False), False),
                "company_control": normalize_company_control(application.get("company_control", "none")),
                "role_profile": clean_text(str(application.get("role_profile", ""))),
                "reasons": list(application.get("reasons", []))[:3],
                "first_seen_utc": clean_text(str(application.get("first_seen_utc", ""))),
                "last_seen_utc": clean_text(str(application.get("last_seen_utc", ""))),
                "age_hours": round(age_hours, 1),
            }
        )

    items.sort(
        key=lambda item: (
            int(item["shortlisted"]),
            COMPANY_CONTROL_ORDER.get(str(item["company_control"]), 0),
            int(item["rank"]),
            int(item["score"]),
            clean_text(str(item["last_seen_utc"])),
            clean_text(str(item["title"])),
        ),
        reverse=True,
    )

    limited_items = items[: int(digest_settings["max_items"])]
    return {
        "generated_at": current_run_ts,
        "digest_date_utc": current_dt.date().isoformat(),
        "item_count": len(limited_items),
        "items": limited_items,
        "include_statuses": list(digest_settings["include_statuses"]),
    }


def save_daily_digest_snapshot(snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(DAILY_DIGEST_FILE), snapshot)


def format_daily_digest_message(snapshot: dict[str, object]) -> str:
    lines = [f"Daily Job Digest: {snapshot['digest_date_utc']}"]
    for index, item in enumerate(snapshot["items"], start=1):
        badges = [f"score {item['score']}", str(item["status"])]
        if item["shortlisted"]:
            badges.insert(0, "shortlist")
        elif item["company_control"] == "whitelist":
            badges.insert(0, "whitelist")
        lines.append(f"{index}. {' | '.join(badges)}")
        lines.append(f"{item['title']} at {item['company']}")
        if item.get("reasons"):
            lines.append(f"Why: {item['reasons'][0]}")
        lines.append(str(item["link"]))
    return "\n".join(lines)


def maybe_send_daily_digest(
    applications_state: dict[str, object],
    snapshot: dict[str, object],
    current_run_ts: str,
    search_config: dict[str, object],
) -> tuple[bool, str]:
    digest_settings = search_config["daily_digest"]
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    digest_date = current_dt.date().isoformat()

    if not digest_settings["enabled"]:
        applications_state["last_digest_error"] = ""
        return False, ""
    if current_dt.hour < int(digest_settings["hour_utc"]):
        return False, ""
    if clean_text(str(applications_state.get("last_digest_date_utc", ""))) == digest_date:
        return False, ""
    if not snapshot["items"]:
        applications_state["last_digest_utc"] = current_run_ts
        applications_state["last_digest_date_utc"] = digest_date
        applications_state["last_digest_error"] = ""
        return False, ""

    token, chat_id, thread_id = load_telegram_settings()
    if not token or not chat_id:
        error = "Telegram credentials not configured; daily digest not sent."
        applications_state["last_digest_error"] = error
        return False, error

    ok, error = send_telegram_message(format_daily_digest_message(snapshot), token, chat_id, thread_id)
    if ok:
        applications_state["last_digest_utc"] = current_run_ts
        applications_state["last_digest_date_utc"] = digest_date
        applications_state["last_digest_error"] = ""
        return True, ""

    applications_state["last_digest_error"] = error
    return False, error


def build_application_briefs_snapshot(
    current_run_ts: str,
    applications_state: dict[str, object],
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    items = []

    for application in applications_state["applications"]:
        if not parse_bool(application.get("application_ready", False), False):
            continue
        status = normalize_application_status(application.get("status", "new"))
        if status == "rejected":
            continue
        rank, age_hours = rank_application_for_digest(application, current_dt)
        items.append(
            {
                "title": clean_text(str(application.get("title", ""))),
                "company": clean_text(str(application.get("company", ""))),
                "link": clean_text(str(application.get("link", ""))),
                "status": status,
                "score": max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0)),
                "rank": rank,
                "shortlisted": parse_bool(application.get("shortlisted", False), False),
                "company_control": normalize_company_control(application.get("company_control", "none")),
                "role_profile": clean_text(str(application.get("role_profile", ""))),
                "why_this_fits": list(application.get("why_this_fits", []))[:3],
                "resume_bullet_suggestions": list(application.get("resume_bullet_suggestions", []))[:3],
                "intro_message": clean_text(str(application.get("intro_message", ""))),
                "notes": clean_text(str(application.get("notes", ""))),
                "last_seen_utc": clean_text(str(application.get("last_seen_utc", ""))),
                "age_hours": round(age_hours, 1),
            }
        )

    items.sort(
        key=lambda item: (
            int(item["shortlisted"]),
            COMPANY_CONTROL_ORDER.get(str(item["company_control"]), 0),
            int(item["rank"]),
            int(item["score"]),
            clean_text(str(item["last_seen_utc"])),
        ),
        reverse=True,
    )
    limited_items = items[:DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS]
    return {
        "generated_at": current_run_ts,
        "brief_count": len(limited_items),
        "items": limited_items,
    }


def save_application_briefs_snapshot(snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(APPLICATION_BRIEFS_FILE), snapshot)


def save_borderline_matches_snapshot(current_run_ts: str, candidates: list[dict[str, object]]) -> None:
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            safe_int(item.get("score", 0), 0),
            int(parse_bool(item.get("shortlisted", False), False)),
            clean_text(str(item.get("title", ""))),
        ),
        reverse=True,
    )
    snapshot = {
        "generated_at": current_run_ts,
        "min_match_score": MIN_MATCH_SCORE,
        "review_band": {
            "min_score": max(0, MIN_MATCH_SCORE - BORDERLINE_MATCH_MARGIN),
            "max_score": MIN_MATCH_SCORE - 1,
        },
        "candidate_count": len(sorted_candidates[:DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS]),
        "candidates": sorted_candidates[:DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS],
    }
    atomic_write_json(Path(BORDERLINE_MATCHES_FILE), snapshot)


def main() -> int:
    current_run_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_hits = 0
    match_details: list[dict[str, object]] = []
    borderline_details: list[dict[str, object]] = []
    reviewed_count = 0
    applications_created = 0

    profile = load_resume_profile()
    search_config = load_job_search_config()
    existing_jobs = load_existing_jobs()
    existing_links = {job["link"] for job in existing_jobs}
    feed_state = load_feed_state()
    alert_state = load_alert_state()
    seen_jobs_state = load_seen_jobs_state()
    applications_state = load_applications_state()
    company_boards = load_company_boards()
    reviewed_fingerprints = set(str(fingerprint) for fingerprint in seen_jobs_state["reviewed_fingerprints"])
    seeded_applications = seed_applications_from_existing_jobs(applications_state, existing_jobs)
    sync_application_outcomes(applications_state, current_run_ts)
    initial_cleanup_summary = prune_applications_state(applications_state, search_config, current_run_ts)
    feedback_profile = build_feedback_metrics(current_run_ts, applications_state, search_config, initial_cleanup_summary)

    for job in existing_jobs:
        record_reviewed_fingerprints(
            seen_jobs_state,
            reviewed_fingerprints,
            build_review_fingerprints(job["title"], job["description"], job["link"]),
        )

    preferred_locations = profile["preferred_locations"]
    regions = ["us", "usa", "united states", "uk", "united kingdom", "canada", "europe", "americas"]
    lockouts = [f"{region} only" for region in regions if region not in preferred_locations]
    lockouts += [f"remote {region}" for region in regions if region not in preferred_locations]

    all_sources: list[dict[str, object]] = [*FEEDS, *company_boards]

    for source in all_sources:
        checked_at = time()
        if not is_feed_due(source, feed_state, checked_at):
            continue

        try:
            if source.get("platform"):
                items = fetch_company_board_items(source)
            else:
                xml_raw = fetch_feed(str(source["url"]))
                items = parse_source_items(source, xml_raw)
            new_rows = []
            source_label = get_source_display_name(source)

            for item in items:
                link = clean_text(item["link"])
                fingerprints = build_review_fingerprints(item["title"], item["description"], link)
                if not link or link in existing_links or any(
                    fingerprint in reviewed_fingerprints for fingerprint in fingerprints
                ):
                    continue

                evaluation = score_job(item, source_label, profile, search_config, feedback_profile, current_run_ts, lockouts)
                record_reviewed_fingerprints(seen_jobs_state, reviewed_fingerprints, fingerprints)
                reviewed_count += 1
                if not evaluation["qualified"]:
                    candidate = evaluation.get("candidate")
                    if candidate and evaluation["score"] >= max(0, MIN_MATCH_SCORE - BORDERLINE_MATCH_MARGIN):
                        borderline_details.append(candidate)
                    continue

                match = evaluation["match"]
                new_rows.append(
                    {
                        "time": match["time"],
                        "title": match["title"],
                        "description": match["description"],
                        "link": match["link"],
                    }
                )
                match_details.append(match)
                if upsert_application_record(applications_state, match, current_run_ts):
                    applications_created += 1
                existing_links.add(link)
                new_hits += 1

            append_rows(new_rows)
            feed_state[source["name"]] = {"last_checked_at": checked_at}

        except (ElementTree.ParseError, HTTPError, URLError, OSError, ValueError) as exc:
            source_ref = source.get("url") or source.get("platform") or source.get("name")
            print(f"Warning: skipping {source_ref} — {exc}", file=sys.stderr)
            continue

    save_feed_state(feed_state)
    save_matches_snapshot(current_run_ts, match_details)
    prune_reviewed_fingerprints(seen_jobs_state, reviewed_fingerprints)
    seen_jobs_state["last_run_utc"] = current_run_ts
    save_seen_jobs_state(seen_jobs_state)
    sync_application_outcomes(applications_state, current_run_ts)
    cleanup_summary = prune_applications_state(applications_state, search_config, current_run_ts)
    feedback_profile = build_feedback_metrics(current_run_ts, applications_state, search_config, cleanup_summary)
    applications_state["last_updated_utc"] = current_run_ts
    applications_state["last_feedback_utc"] = current_run_ts

    queued_count = queue_pending_alerts(alert_state, match_details)
    sent_count, delivery_error = deliver_pending_alerts(alert_state, current_run_ts)
    alert_state["last_run_utc"] = current_run_ts
    save_alert_state(alert_state)
    daily_digest_snapshot = build_daily_digest_snapshot(current_run_ts, applications_state, search_config)
    save_daily_digest_snapshot(daily_digest_snapshot)
    save_application_briefs_snapshot(build_application_briefs_snapshot(current_run_ts, applications_state))
    save_borderline_matches_snapshot(current_run_ts, borderline_details)
    digest_sent, digest_error = maybe_send_daily_digest(
        applications_state,
        daily_digest_snapshot,
        current_run_ts,
        search_config,
    )
    save_feedback_metrics_snapshot(feedback_profile["snapshot"])
    save_applications_state(applications_state)

    if new_hits > 0 or sent_count > 0 or queued_count > 0 or applications_created > 0 or seeded_applications > 0 or digest_sent or cleanup_summary["removed_count"] > 0:
        print(
            "Jobs: "
            f"found {new_hits} new matches, "
            f"reviewed {reviewed_count} new items, "
            f"tracked {applications_created} applications, "
            f"seeded {seeded_applications}, "
            f"pruned {cleanup_summary['removed_count']} stale applications, "
            f"queued {queued_count} alerts, "
            f"sent {sent_count}, "
            f"pending {len(alert_state['pending_alerts'])}, "
            f"digest {'sent' if digest_sent else 'not sent'}."
        )
    else:
        print("Jobs: No new matches found in this sweep.")

    if delivery_error:
        print(f"Jobs: {delivery_error}", file=sys.stderr)
    if digest_error:
        print(f"Jobs: {digest_error}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
