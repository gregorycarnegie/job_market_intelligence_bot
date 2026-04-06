import html
import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobbot import storage

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "time", "title", "company", "location", "salary",
    "source", "employment_type", "date_posted", "description", "link",
]
STATE_DB_FILE = "jobbot_state.sqlite3"
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
MIN_MATCH_SCORE = 28
MAX_ALERTED_LINKS = 5000
MAX_REVIEWED_FINGERPRINTS = 50000
MAX_APPLICATION_RECORDS = 5000
BOARD_PAGE_LIMIT = 100
GENERIC_HTML_MAX_START_URLS = 10
GENERIC_HTML_MAX_JOB_LINKS = 60
DEFAULT_DAILY_DIGEST_HOUR_UTC = 7
DEFAULT_DAILY_DIGEST_MAX_ITEMS = 8
DEFAULT_DAILY_DIGEST_PAGE_SIZE = 4
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


def fetch_live_currency_rates() -> None:
    """Fetch live GBP exchange rates from Frankfurter (ECB data) and update CURRENCY_TO_GBP in-place.
    Falls back silently to the hardcoded rates on any error."""
    try:
        req = urllib.request.Request(
            "https://api.frankfurter.dev/v1/latest?from=GBP&to=USD,EUR",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        rates = data.get("rates", {})
        if "USD" in rates:
            CURRENCY_TO_GBP["usd"] = round(1.0 / rates["USD"], 6)
        if "EUR" in rates:
            CURRENCY_TO_GBP["eur"] = round(1.0 / rates["EUR"], 6)
        logger.info(
            f"Rates: 1 GBP = {rates.get('USD', '?')} USD, {rates.get('EUR', '?')} EUR (date: {data.get('date', '?')})"
        )
    except Exception as exc:
        logger.warning(f"could not fetch live currency rates, using defaults — {exc}")


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
        "name": "wwr_all",
        "url": "https://weworkremotely.com/remote-jobs.rss",
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
        "name": "remotefirstjobs_all",
        "url": "https://remotefirstjobs.com/rss/jobs.rss",
        "min_interval_seconds": 3600,
    },
    {
        "name": "python_org_jobs",
        "url": "https://www.python.org/jobs/feed/rss/",
        "context_terms": "london uk united kingdom hybrid office",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobs_ac_uk_tech_london",
        "url": "https://www.jobs.ac.uk/jobs/london?format=rss",
        # Universities hire a massive amount of IT/Tech staff in London, usually hybrid/office.
        "context_terms": "tech support developer engineer hybrid in-office",
        "min_interval_seconds": 3600,
    },
    {
        "name": "google_alerts_corporate",
        "url": "https://www.google.com/alerts/feeds/09910730576829865385/10714127524543454759",
        "min_interval_seconds": 3600,
    },
    {
        "name": "google_alerts_core_it_support",
        "url": "https://www.google.com/alerts/feeds/09910730576829865385/13401058173831861136",
        "min_interval_seconds": 3600,
    },
    {
        "name": "google_alerts_infrastructure",
        "url": "https://www.google.com/alerts/feeds/09910730576829865385/15611871513157400765",
        "min_interval_seconds": 3600,
    },
    {
        "name": "google_alerts_dev_adjacent",
        "url": "https://www.google.com/alerts/feeds/09910730576829865385/17528292640163305738",
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobicy_fintech_uk",
        "url": (
            "https://jobicy.com/feed/job_feed"
            "?job_categories=engineering,technical-support,accounting-finance"
            "&search_keywords=fintech"
            "&search_region=uk"
        ),
        "min_interval_seconds": 3600,
    },
    {
        "name": "jobicy_payments_uk",
        "url": (
            "https://jobicy.com/feed/job_feed"
            "?job_categories=engineering,technical-support,accounting-finance"
            "&search_keywords=payments"
            "&search_region=uk"
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
    """
    Remove HTML tags and extra whitespace from text.

    Args:
        text (str): The raw text to clean.

    Returns:
        str: The cleaned string.
    """
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return " ".join(clean.split())


def normalize_text(text: str) -> str:
    """
    Clean text and convert it to lowercase for consistent matching.

    Args:
        text (str): The raw text to normalize.

    Returns:
        str: The cleaned, lowercase string.
    """
    return " ".join(clean_text(text).lower().split())


def strip_cdata(text: str) -> str:
    """
    Remove CDATA wrappers from XML/RSS strings.

    Args:
        text (str): The text potentially containing CDATA.

    Returns:
        str: The plain text without CDATA tags.
    """
    stripped = text.strip()
    if stripped.startswith("<![CDATA[") and stripped.endswith("]]>"):
        return stripped[9:-3]
    return stripped


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def compile_skill_pattern(skill: str) -> re.Pattern[str] | None:
    """
    Create a compiled regex pattern for matching a specific skill as a whole word.

    Args:
        skill (str): The skill text to match.

    Returns:
        re.Pattern | None: The compiled regex, or None if the input is empty.
    """
    normalized_skill = normalize_text(skill)
    if not normalized_skill:
        return None
    escaped = re.escape(normalized_skill).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def contains_phrase(text: str, phrase: str) -> bool:
    pattern = compile_skill_pattern(phrase)
    return bool(pattern and pattern.search(text))


def build_pattern_entries(values: list[str]) -> list[PatternEntry]:
    """
    Convert a list of string skills/roles into a list of pre-compiled regex PatternEntries.

    Args:
        values (list[str]): The strings to convert.

    Returns:
        list[PatternEntry]: A list of tuples containing the normalized string and its regex pattern.
    """
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
    """
    Safely convert an object to an integer, falling back to a default on failure.

    Args:
        value (object): The item to convert.
        default (int): Default to return if conversion fails.

    Returns:
        int: The parsed integer or the default.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value: object, default: bool = False) -> bool:
    """
    Parse a boolean from various string or numeric representations.

    Args:
        value (object): The value to parse (e.g., '1', 'true', 'no').
        default (bool): The default if parsing is ambiguous.

    Returns:
        bool: The evaluated boolean state.
    """
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


def dedupe_preserving_order(values: list[str]) -> list[str]:
    """
    Remove duplicates from a list of strings while preserving the original insertion order.

    Args:
        values (list[str]): The incoming strings.

    Returns:
        list[str]: The deduped list.
    """
    unique_values = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        unique_values.append(value)
        seen.add(value)
    return unique_values


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
    seen: set[str] = set()
    for value in raw_values:
        normalized = normalize_text(value) if lower else clean_text(str(value))
        if normalized and normalized not in seen:
            normalized_values.append(normalized)
            seen.add(normalized)
    return normalized_values


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
    """
    Filter out common corporate suffixes (Ltd, Inc, LLC, etc.) to standardize company names.

    Args:
        company (str): The raw company name.

    Returns:
        str: The normalized company name.
    """
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
        ("dash", r"\s+[-–—]\s+"),  # noqa: RUF001
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
    """
    Generate unique fingerprints for a job listing to avoid duplicate reviews.
    Utilizes link, role/company pair, and text as fallback markers.

    Args:
        title (str): The job title.
        description (str): Full text description.
        link (str): The job link.

    Returns:
        list[str]: The unique fingerprints representing this job.
    """
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


def load_resume_profile(resume_file: str) -> dict[str, object]:
    with open(resume_file, encoding="utf-8") as f:
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
        description_keywords
        if isinstance(description_keywords, list) and description_keywords
        else shared_keywords or []
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


def _clamp_int(value: object, min_val: int, max_val: int, default: int) -> int:
    return max(min_val, min(max_val, safe_int(value, default)))


def load_job_search_config(config_file: str) -> dict[str, object]:
    raw_data: dict[str, object] = {}
    config_path = Path(config_file)
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw_data = loaded
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"skipping {config_file} — {exc}")

    whitelist = normalize_company_control_values(raw_data.get("company_whitelist", []))
    blacklist = normalize_company_control_values(raw_data.get("company_blacklist", []))
    priority_companies = normalize_company_control_values(raw_data.get("priority_companies", []))
    daily_digest = raw_data.get("daily_digest", {}) if isinstance(raw_data.get("daily_digest"), dict) else {}
    feedback = raw_data.get("feedback", {}) if isinstance(raw_data.get("feedback"), dict) else {}
    digest_statuses = [
        status
        for status in normalize_string_list(
            daily_digest.get("include_statuses", DEFAULT_DAILY_DIGEST_STATUSES), lower=True
        )
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
            "hour_utc": _clamp_int(
                daily_digest.get("hour_utc", DEFAULT_DAILY_DIGEST_HOUR_UTC), 0, 23, DEFAULT_DAILY_DIGEST_HOUR_UTC
            ),
            "max_items": _clamp_int(
                daily_digest.get("max_items", DEFAULT_DAILY_DIGEST_MAX_ITEMS), 1, 20, DEFAULT_DAILY_DIGEST_MAX_ITEMS
            ),
            "page_size": _clamp_int(
                daily_digest.get("page_size", DEFAULT_DAILY_DIGEST_PAGE_SIZE),
                1,
                10,
                DEFAULT_DAILY_DIGEST_PAGE_SIZE,
            ),
            "include_statuses": digest_statuses or list(DEFAULT_DAILY_DIGEST_STATUSES),
        },
        "feedback": {
            "enabled": parse_bool(feedback.get("enabled", True), True),
            "min_samples": _clamp_int(
                feedback.get("min_samples", DEFAULT_FEEDBACK_MIN_SAMPLES), 1, 20, DEFAULT_FEEDBACK_MIN_SAMPLES
            ),
            "max_source_adjustment": _clamp_int(
                feedback.get("max_source_adjustment", DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT),
                1,
                20,
                DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT,
            ),
            "max_keyword_adjustment": _clamp_int(
                feedback.get("max_keyword_adjustment", DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT),
                1,
                20,
                DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT,
            ),
            "keyword_limit": _clamp_int(
                feedback.get("keyword_limit", DEFAULT_FEEDBACK_KEYWORD_LIMIT), 1, 8, DEFAULT_FEEDBACK_KEYWORD_LIMIT
            ),
            "new_reviewed_retention_days": _clamp_int(
                feedback.get("new_reviewed_retention_days", DEFAULT_NEW_REVIEWED_RETENTION_DAYS),
                30,
                3650,
                DEFAULT_NEW_REVIEWED_RETENTION_DAYS,
            ),
            "rejected_retention_days": _clamp_int(
                feedback.get("rejected_retention_days", DEFAULT_REJECTED_RETENTION_DAYS),
                30,
                3650,
                DEFAULT_REJECTED_RETENTION_DAYS,
            ),
            "applied_retention_days": _clamp_int(
                feedback.get("applied_retention_days", DEFAULT_APPLIED_RETENTION_DAYS),
                30,
                3650,
                DEFAULT_APPLIED_RETENTION_DAYS,
            ),
            "interview_retention_days": _clamp_int(
                feedback.get("interview_retention_days", DEFAULT_INTERVIEW_RETENTION_DAYS),
                30,
                3650,
                DEFAULT_INTERVIEW_RETENTION_DAYS,
            ),
        },
    }


def atomic_write_json(path: Path, payload: object) -> None:
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def load_feed_state(feed_state_file: str) -> dict[str, dict[str, float]]:
    return storage.load_feed_state(STATE_DB_FILE)


def save_feed_state(feed_state_file: str, feed_state: dict[str, dict[str, float]]) -> None:
    storage.save_feed_state(STATE_DB_FILE, feed_state)
    atomic_write_json(Path(feed_state_file), feed_state)


def is_feed_due(feed: dict[str, str | int], feed_state: dict[str, dict[str, float]], now_ts: float) -> bool:
    last_checked_at = feed_state.get(feed["name"], {}).get("last_checked_at", 0)
    return now_ts - last_checked_at >= int(feed["min_interval_seconds"])


def get_source_display_name(source: dict[str, object]) -> str:
    return clean_text(str(source.get("display_name", "") or source.get("name", "")))


def load_existing_jobs(csv_file: str) -> list[dict[str, str]]:
    jobs = storage.load_jobs(STATE_DB_FILE)
    storage.export_jobs_to_csv(STATE_DB_FILE, csv_file)
    return jobs


def append_rows(csv_file: str, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    storage.append_jobs(STATE_DB_FILE, rows)
    storage.export_jobs_to_csv(STATE_DB_FILE, csv_file)


def load_seen_jobs_state(seen_jobs_state_file: str) -> dict[str, object]:
    state = storage.load_seen_jobs_state(STATE_DB_FILE)
    state["reviewed_fingerprints"] = dedupe_preserving_order(
        [clean_text(str(fingerprint)) for fingerprint in state["reviewed_fingerprints"] if clean_text(str(fingerprint))]
    )[-MAX_REVIEWED_FINGERPRINTS:]
    return state


def save_seen_jobs_state(seen_jobs_state_file: str, seen_jobs_state: dict[str, object]) -> None:
    storage.save_seen_jobs_state(STATE_DB_FILE, seen_jobs_state)
    atomic_write_json(Path(seen_jobs_state_file), seen_jobs_state)


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


def load_alert_state(alerts_state_file: str) -> dict[str, object]:
    state = storage.load_alert_state(STATE_DB_FILE)
    pending_alerts = []
    seen_pending_links = set()
    for payload in state.get("pending_alerts", []):
        if not isinstance(payload, dict):
            continue
        normalized = normalize_pending_alert(payload)
        if normalized is None or normalized["link"] in seen_pending_links:
            continue
        pending_alerts.append(normalized)
        seen_pending_links.add(normalized["link"])

    alerted_links = [clean_text(str(link)) for link in state.get("alerted_links", []) if clean_text(str(link))]

    return {
        "alerted_links": dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:],
        "pending_alerts": pending_alerts,
        "last_run_utc": clean_text(str(state.get("last_run_utc", ""))),
        "last_delivery_utc": clean_text(str(state.get("last_delivery_utc", ""))),
        "last_delivery_error": clean_text(str(state.get("last_delivery_error", ""))),
    }


def save_alert_state(alerts_state_file: str, alert_state: dict[str, object]) -> None:
    storage.save_alert_state(STATE_DB_FILE, alert_state)
    atomic_write_json(Path(alerts_state_file), alert_state)


def save_matches_snapshot(matches_file: str, run_time_utc: str, matches: list[dict[str, object]]) -> None:
    snapshot = {
        "generated_at": run_time_utc,
        "match_count": len(matches),
        "matches": matches,
    }
    atomic_write_json(Path(matches_file), snapshot)


def normalize_company_control(value: object) -> str:
    normalized = normalize_text(str(value))
    return normalized if normalized in COMPANY_CONTROL_ORDER else "none"


def stronger_company_control(left: str, right: str) -> str:
    return left if COMPANY_CONTROL_ORDER.get(left, 0) >= COMPANY_CONTROL_ORDER.get(right, 0) else right


def normalize_application_status(value: object) -> str:
    normalized = normalize_text(str(value))
    return normalized if normalized in APPLICATION_STATUSES else "new"


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
