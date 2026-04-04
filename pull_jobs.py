import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

CSV_FILE = "jobs.csv"
RESUME_FILE = "resume.json"
FEED_STATE_FILE = "feed_state.json"
CSV_HEADERS = ["time", "title", "description", "link"]
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = "job-market-intelligence-bot/0.1"
LOCATION_ALIASES = {
    "united kingdom": ["uk", "great britain", "britain"],
    "uk": ["united kingdom", "great britain", "britain"],
    "united states": ["us", "usa", "america"],
    "us": ["usa", "united states", "america"],
    "usa": ["us", "united states", "america"],
}
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
        "url": "https://remotive.com/remote-jobs/software-dev/feed",
        "min_interval_seconds": 3600,
    },
    {
        "name": "remotive_devops",
        "url": "https://remotive.com/remote-jobs/devops/feed",
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


def has_skill_match(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def fetch_feed(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


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


def load_resume() -> tuple[list[re.Pattern[str]], list[re.Pattern[str]], dict, list[str]]:
    with open(RESUME_FILE, encoding="utf-8") as f:
        resume = json.load(f)

    raw_skills = resume["technical_skills"]["skills"]
    skill_patterns = [
        pattern
        for pattern in (compile_skill_pattern(skill) for skill in raw_skills)
        if pattern is not None
    ]
    raw_target_roles = resume["personal_info"].get("target_roles", [])
    target_role_patterns = [
        pattern
        for pattern in (compile_skill_pattern(role) for role in raw_target_roles)
        if pattern is not None
    ]
    prefs = resume["personal_info"]["preferences"]
    loc = resume["personal_info"]["location"]
    preferred_locations = [
        normalize_text(value)
        for value in [
            loc.get("city", ""),
            loc.get("country", ""),
            *prefs.get("preferred_locations", []),
        ]
        if normalize_text(value)
    ]
    return skill_patterns, target_role_patterns, prefs, expand_location_terms(preferred_locations)


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
    state_path = Path(FEED_STATE_FILE)
    temp_path = state_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(feed_state, f, indent=2)
    temp_path.replace(state_path)


def is_feed_due(feed: dict[str, str | int], feed_state: dict[str, dict[str, float]], now_ts: float) -> bool:
    last_checked_at = feed_state.get(feed["name"], {}).get("last_checked_at", 0)
    return now_ts - last_checked_at >= int(feed["min_interval_seconds"])


def load_existing_links() -> set[str]:
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        return set()

    links = set()
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            link_parts = [row.get("link", "")]
            if row.get(None):
                link_parts.extend(row[None])
            link = ",".join(part for part in link_parts if part)
            if link:
                links.add(link)
    return links


def append_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


def main() -> int:
    current_run_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_hits = 0

    skill_patterns, target_role_patterns, prefs, preferred_locations = load_resume()
    existing_links = load_existing_links()
    feed_state = load_feed_state()

    regions = ["us", "usa", "united states", "uk", "united kingdom", "canada", "europe", "americas"]
    lockouts = [f"{region} only" for region in regions if region not in preferred_locations]
    lockouts += [f"remote {region}" for region in regions if region not in preferred_locations]

    for feed in FEEDS:
        checked_at = time()
        if not is_feed_due(feed, feed_state, checked_at):
            continue

        feed_state[feed["name"]] = {"last_checked_at": checked_at}
        try:
            xml_raw = fetch_feed(str(feed["url"]))
            items = parse_source_items(feed, xml_raw)
            new_rows = []

            for item in items:
                link = clean_text(item["link"])
                if not link or link in existing_links:
                    continue

                raw_title = item["title"]
                raw_desc = item["description"]
                normalized_full_text = normalize_text(f"{raw_title} {raw_desc}")
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

                location_ok = False
                if prefs.get("relocation", False):
                    location_ok = True
                else:
                    if prefs.get("remote") and is_remote and not is_locked_out:
                        location_ok = True
                    if prefs.get("hybrid") and is_local and (is_hybrid or not is_remote):
                        location_ok = True
                    if prefs.get("onsite") and is_local and (is_onsite or not is_remote):
                        location_ok = True

                has_relevant_match = (
                    has_skill_match(normalized_full_text, skill_patterns)
                    or has_skill_match(normalized_full_text, target_role_patterns)
                )

                if not location_ok or not has_relevant_match:
                    continue

                new_rows.append(
                    {
                        "time": current_run_ts,
                        "title": clean_text(raw_title),
                        "description": clean_text(raw_desc)[:1500],
                        "link": link,
                    }
                )
                existing_links.add(link)
                new_hits += 1

            append_rows(new_rows)

        except (ElementTree.ParseError, HTTPError, URLError, OSError, ValueError) as e:
            print(f"Warning: skipping {feed['url']} — {e}", file=sys.stderr)
            continue

    save_feed_state(feed_state)

    if new_hits > 0:
        print(f"Jobs: Found and added {new_hits} new technical listings.")
    else:
        print("Jobs: No new matches found in this sweep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
