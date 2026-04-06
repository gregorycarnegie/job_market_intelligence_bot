from datetime import datetime, timezone
import sys
from time import time
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree

import jobbot.common as common
import jobbot.matching as matching
import jobbot.storage as storage
import jobbot.sources as source_module

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
STATE_DB_FILE = common.STATE_DB_FILE

CSV_HEADERS = common.CSV_HEADERS
FETCH_TIMEOUT_SECONDS = common.FETCH_TIMEOUT_SECONDS
USER_AGENT = common.USER_AGENT
MIN_MATCH_SCORE = common.MIN_MATCH_SCORE
MAX_ALERTED_LINKS = common.MAX_ALERTED_LINKS
MAX_REVIEWED_FINGERPRINTS = common.MAX_REVIEWED_FINGERPRINTS
MAX_APPLICATION_RECORDS = common.MAX_APPLICATION_RECORDS
BOARD_PAGE_LIMIT = common.BOARD_PAGE_LIMIT
GENERIC_HTML_MAX_START_URLS = common.GENERIC_HTML_MAX_START_URLS
GENERIC_HTML_MAX_JOB_LINKS = common.GENERIC_HTML_MAX_JOB_LINKS
DEFAULT_DAILY_DIGEST_HOUR_UTC = common.DEFAULT_DAILY_DIGEST_HOUR_UTC
DEFAULT_DAILY_DIGEST_MAX_ITEMS = common.DEFAULT_DAILY_DIGEST_MAX_ITEMS
DEFAULT_DAILY_DIGEST_PAGE_SIZE = common.DEFAULT_DAILY_DIGEST_PAGE_SIZE
DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS = common.DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS
APPLICATION_STATUSES = common.APPLICATION_STATUSES
DEFAULT_DAILY_DIGEST_STATUSES = common.DEFAULT_DAILY_DIGEST_STATUSES
COMPANY_CONTROL_ORDER = common.COMPANY_CONTROL_ORDER
BORDERLINE_MATCH_MARGIN = common.BORDERLINE_MATCH_MARGIN
APPLICATION_READY_SCORE = common.APPLICATION_READY_SCORE
OUTCOME_RELEVANT_STATUSES = common.OUTCOME_RELEVANT_STATUSES
DEFAULT_FEEDBACK_MIN_SAMPLES = common.DEFAULT_FEEDBACK_MIN_SAMPLES
DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT = common.DEFAULT_MAX_SOURCE_FEEDBACK_ADJUSTMENT
DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT = common.DEFAULT_MAX_KEYWORD_FEEDBACK_ADJUSTMENT
DEFAULT_FEEDBACK_KEYWORD_LIMIT = common.DEFAULT_FEEDBACK_KEYWORD_LIMIT
DEFAULT_NEW_REVIEWED_RETENTION_DAYS = common.DEFAULT_NEW_REVIEWED_RETENTION_DAYS
DEFAULT_REJECTED_RETENTION_DAYS = common.DEFAULT_REJECTED_RETENTION_DAYS
DEFAULT_APPLIED_RETENTION_DAYS = common.DEFAULT_APPLIED_RETENTION_DAYS
DEFAULT_INTERVIEW_RETENTION_DAYS = common.DEFAULT_INTERVIEW_RETENTION_DAYS
LOCATION_ALIASES = common.LOCATION_ALIASES
POSITIVE_TITLE_WEIGHTS = common.POSITIVE_TITLE_WEIGHTS
NEGATIVE_TITLE_WEIGHTS = common.NEGATIVE_TITLE_WEIGHTS
SENIORITY_PENALTIES = common.SENIORITY_PENALTIES
TRACKING_QUERY_PARAMS = common.TRACKING_QUERY_PARAMS
CURRENCY_TO_GBP = common.CURRENCY_TO_GBP
CADENCE_TO_ANNUAL_MULTIPLIER = common.CADENCE_TO_ANNUAL_MULTIPLIER
JOB_TITLE_HINT_RE = common.JOB_TITLE_HINT_RE
DEFAULT_GENERIC_JOB_LINK_KEYWORDS = common.DEFAULT_GENERIC_JOB_LINK_KEYWORDS
DEFAULT_ROLE_PROFILE_CONFIGS = common.DEFAULT_ROLE_PROFILE_CONFIGS
FEEDS = common.FEEDS
SUPPORTED_BOARD_PLATFORMS = common.SUPPORTED_BOARD_PLATFORMS
COMPANY_BOARD_REQUIRED_FIELDS = common.COMPANY_BOARD_REQUIRED_FIELDS
PatternEntry = common.PatternEntry

clean_text = common.clean_text
normalize_text = common.normalize_text
strip_cdata = common.strip_cdata
strip_tags = common.strip_tags
compile_skill_pattern = common.compile_skill_pattern
contains_phrase = common.contains_phrase
build_pattern_entries = common.build_pattern_entries
find_pattern_matches = common.find_pattern_matches
append_reason = common.append_reason
safe_int = common.safe_int
parse_bool = common.parse_bool
dedupe_preserving_order = common.dedupe_preserving_order
fresh_alert_state = common.fresh_alert_state
fresh_seen_jobs_state = common.fresh_seen_jobs_state
fresh_applications_state = common.fresh_applications_state
join_text_parts = common.join_text_parts
normalize_string_list = common.normalize_string_list
normalize_url_list = common.normalize_url_list
normalize_link_for_fingerprint = common.normalize_link_for_fingerprint
looks_like_job_title = common.looks_like_job_title
normalize_company_name = common.normalize_company_name
split_title_and_company = common.split_title_and_company
build_review_fingerprints = common.build_review_fingerprints
expand_location_terms = common.expand_location_terms
build_resume_evidence_entries = common.build_resume_evidence_entries
normalize_company_control_values = common.normalize_company_control_values
normalize_role_profile = common.normalize_role_profile
normalize_role_profiles = common.normalize_role_profiles
atomic_write_json = common.atomic_write_json
is_feed_due = common.is_feed_due
get_source_display_name = common.get_source_display_name
normalize_pending_alert = common.normalize_pending_alert
normalize_company_control = common.normalize_company_control
stronger_company_control = common.stronger_company_control
normalize_application_status = common.normalize_application_status
ensure_sentence = common.ensure_sentence
truncate_text = common.truncate_text
build_focus_phrases = common.build_focus_phrases
parse_iso_utc = common.parse_iso_utc
latest_application_timestamp = common.latest_application_timestamp

fetch_feed = source_module.fetch_feed
fetch_json = source_module.fetch_json
strip_html_noise = source_module.strip_html_noise
extract_meta_content = source_module.extract_meta_content
extract_page_title = source_module.extract_page_title
extract_plain_text_from_html = source_module.extract_plain_text_from_html
extract_jsonld_objects = source_module.extract_jsonld_objects
iter_json_nodes = source_module.iter_json_nodes
node_has_type = source_module.node_has_type
extract_jobposting_nodes = source_module.extract_jobposting_nodes
format_jsonld_address = source_module.format_jsonld_address
extract_jsonld_location_text = source_module.extract_jsonld_location_text
normalize_salary_unit_text = source_module.normalize_salary_unit_text
format_provider_salary_text = source_module.format_provider_salary_text
extract_jsonld_salary_text = source_module.extract_jsonld_salary_text
jobposting_node_to_item = source_module.jobposting_node_to_item
extract_anchor_links = source_module.extract_anchor_links
url_matches_allowed_domains = source_module.url_matches_allowed_domains
looks_like_generic_job_link = source_module.looks_like_generic_job_link
fallback_generic_job_item = source_module.fallback_generic_job_item
sanitize_xml = source_module.sanitize_xml
local_name = source_module.local_name
extract_link = source_module.extract_link
extract_description = source_module.extract_description
parse_structured_feed = source_module.parse_structured_feed
extract_tag_text = source_module.extract_tag_text
parse_fallback_feed = source_module.parse_fallback_feed
parse_feed_items = source_module.parse_feed_items
parse_efinancialcareers_html = source_module.parse_efinancialcareers_html
parse_source_items = source_module.parse_source_items
normalize_company_board = source_module.normalize_company_board
fetch_greenhouse_board_jobs = source_module.fetch_greenhouse_board_jobs
fetch_lever_board_jobs = source_module.fetch_lever_board_jobs
fetch_ashby_board_jobs = source_module.fetch_ashby_board_jobs
fetch_workable_board_jobs = source_module.fetch_workable_board_jobs

normalize_application_record = matching.normalize_application_record
evaluate_location_fit = matching.evaluate_location_fit
normalize_currency_token = matching.normalize_currency_token
detect_salary_cadence = matching.detect_salary_cadence
parse_salary_amount = matching.parse_salary_amount
annualize_salary_to_gbp = matching.annualize_salary_to_gbp
build_salary_info = matching.build_salary_info
extract_salary_range_gbp = matching.extract_salary_range_gbp
format_salary_info_for_reason = matching.format_salary_info_for_reason
apply_weight_map = matching.apply_weight_map
evaluate_company_preferences = matching.evaluate_company_preferences
evaluate_role_profile = matching.evaluate_role_profile
select_resume_evidence = matching.select_resume_evidence
build_why_this_fits_notes = matching.build_why_this_fits_notes
build_resume_bullet_suggestions = matching.build_resume_bullet_suggestions
build_intro_message = matching.build_intro_message
build_application_materials = matching.build_application_materials
apply_feedback_adjustments = matching.apply_feedback_adjustments
score_job = matching.score_job
queue_pending_alerts = matching.queue_pending_alerts
load_telegram_settings = matching.load_telegram_settings
format_alert_message = matching.format_alert_message
send_telegram_message = matching.send_telegram_message
deliver_pending_alerts = matching.deliver_pending_alerts
process_telegram_callback_updates = matching.process_telegram_callback_updates
sync_application_outcomes = matching.sync_application_outcomes
prune_applications_state = matching.prune_applications_state
fresh_feedback_counts = matching.fresh_feedback_counts
increment_feedback_counts = matching.increment_feedback_counts
compute_feedback_adjustment = matching.compute_feedback_adjustment
build_feedback_metrics = matching.build_feedback_metrics
find_application_record = matching.find_application_record
upsert_application_record = matching.upsert_application_record
upsert_application_record_in_storage = matching.upsert_application_record_in_storage
seed_applications_from_existing_jobs = matching.seed_applications_from_existing_jobs
rank_application_for_digest = matching.rank_application_for_digest
build_daily_digest_snapshot = matching.build_daily_digest_snapshot
format_daily_digest_message = matching.format_daily_digest_message
maybe_send_daily_digest = matching.maybe_send_daily_digest
def load_resume_profile() -> dict[str, object]:
    return common.load_resume_profile(RESUME_FILE)


def load_job_search_config() -> dict[str, object]:
    return common.load_job_search_config(JOB_SEARCH_CONFIG_FILE)


def load_feed_state() -> dict[str, dict[str, float]]:
    return common.load_feed_state(FEED_STATE_FILE)


def save_feed_state(feed_state: dict[str, dict[str, float]]) -> None:
    common.save_feed_state(FEED_STATE_FILE, feed_state)


def load_existing_jobs() -> list[dict[str, str]]:
    return common.load_existing_jobs(CSV_FILE)


def append_rows(rows: list[dict[str, str]]) -> None:
    common.append_rows(CSV_FILE, rows)


def load_seen_jobs_state() -> dict[str, object]:
    return common.load_seen_jobs_state(SEEN_JOBS_STATE_FILE)


def save_seen_jobs_state(seen_jobs_state: dict[str, object]) -> None:
    common.save_seen_jobs_state(SEEN_JOBS_STATE_FILE, seen_jobs_state)


def load_alert_state() -> dict[str, object]:
    return common.load_alert_state(ALERTS_STATE_FILE)


def save_alert_state(alert_state: dict[str, object]) -> None:
    common.save_alert_state(ALERTS_STATE_FILE, alert_state)


def save_matches_snapshot(run_time_utc: str, matches: list[dict[str, object]]) -> None:
    common.save_matches_snapshot(MATCHES_FILE, run_time_utc, matches)


def load_company_boards() -> list[dict[str, object]]:
    return source_module.load_company_boards(COMPANY_BOARDS_FILE)


def _call_with_bound_fetch(callback, *args):
    original_fetch_feed = source_module.fetch_feed
    source_module.fetch_feed = fetch_feed
    try:
        return callback(*args)
    finally:
        source_module.fetch_feed = original_fetch_feed


def fetch_generic_html_board_jobs(board: dict[str, object]) -> list[dict[str, str]]:
    return _call_with_bound_fetch(source_module.fetch_generic_html_board_jobs, board)


def fetch_company_board_items(board: dict[str, object]) -> list[dict[str, str]]:
    return _call_with_bound_fetch(source_module.fetch_company_board_items, board)


def load_applications_state() -> dict[str, object]:
    return matching.load_applications_state(APPLICATIONS_FILE)


def save_applications_state(applications_state: dict[str, object]) -> None:
    matching.save_applications_state(APPLICATIONS_FILE, applications_state)


def save_feedback_metrics_snapshot(snapshot: dict[str, object]) -> None:
    matching.save_feedback_metrics_snapshot(FEEDBACK_METRICS_FILE, snapshot)


def save_daily_digest_snapshot(snapshot: dict[str, object]) -> None:
    matching.save_daily_digest_snapshot(DAILY_DIGEST_FILE, snapshot)


def build_application_briefs_snapshot(
    current_run_ts: str,
    applications_state: dict[str, object],
    max_items: int = DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS,
) -> dict[str, object]:
    return matching.build_application_briefs_snapshot(current_run_ts, applications_state, max_items)


def save_application_briefs_snapshot(snapshot: dict[str, object]) -> None:
    matching.save_application_briefs_snapshot(APPLICATION_BRIEFS_FILE, snapshot)


def save_borderline_matches_snapshot(
    current_run_ts: str,
    candidates: list[dict[str, object]],
    max_items: int = DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS,
) -> None:
    matching.save_borderline_matches_snapshot(BORDERLINE_MATCHES_FILE, current_run_ts, candidates, max_items)


def main() -> int:
    current_run_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_hits = 0
    match_details: list[dict[str, object]] = []
    borderline_details: list[dict[str, object]] = []
    reviewed_count = 0
    applications_created = 0

    common.fetch_live_currency_rates()
    profile = load_resume_profile()
    search_config = load_job_search_config()
    existing_jobs = load_existing_jobs()
    existing_links = {job["link"] for job in existing_jobs}
    feed_state = load_feed_state()
    alert_state = load_alert_state()
    applications_state = load_applications_state()
    company_boards = load_company_boards()
    seeded_applications = seed_applications_from_existing_jobs(applications_state, existing_jobs)
    sync_application_outcomes(applications_state, current_run_ts)
    initial_cleanup_summary = prune_applications_state(applications_state, search_config, current_run_ts)
    feedback_profile = build_feedback_metrics(current_run_ts, applications_state, search_config, initial_cleanup_summary)
    save_applications_state(applications_state)

    for job in existing_jobs:
        storage.append_reviewed_fingerprints(
            STATE_DB_FILE,
            build_review_fingerprints(job["title"], job["description"], job["link"]),
            MAX_REVIEWED_FINGERPRINTS,
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
                if not link or link in existing_links or storage.has_any_reviewed_fingerprint(STATE_DB_FILE, fingerprints):
                    continue

                evaluation = score_job(item, source_label, profile, search_config, feedback_profile, current_run_ts, lockouts)
                storage.append_reviewed_fingerprints(STATE_DB_FILE, fingerprints, MAX_REVIEWED_FINGERPRINTS)
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
                if upsert_application_record_in_storage(match, current_run_ts):
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
    seen_jobs_state = load_seen_jobs_state()
    seen_jobs_state["last_run_utc"] = current_run_ts
    save_seen_jobs_state(seen_jobs_state)
    applications_state = load_applications_state()
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

    if (
        new_hits > 0
        or sent_count > 0
        or queued_count > 0
        or applications_created > 0
        or seeded_applications > 0
        or digest_sent
        or cleanup_summary["removed_count"] > 0
    ):
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
