import concurrent.futures
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from time import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree

import jobbot.common as common
import jobbot.matching as matching
import jobbot.sources as source_module
import jobbot.storage as storage
from jobbot.common import (
    BORDERLINE_MATCH_MARGIN,
    DEFAULT_APPLICATION_BRIEFS_MAX_ITEMS,
    FEEDS,
    MAX_REVIEWED_FINGERPRINTS,
    MIN_MATCH_SCORE,
    STATE_DB_FILE,
    build_review_fingerprints,
    clean_text,
    get_source_display_name,
    is_feed_due,
)
from jobbot.logging_config import setup_logging
from jobbot.matching import (
    build_daily_digest_snapshot,
    build_feedback_metrics,
    deliver_pending_alerts,
    maybe_send_daily_digest,
    prune_applications_state,
    queue_pending_alerts,
    score_job,
    seed_applications_from_existing_jobs,
    sync_application_outcomes,
    upsert_application_record_in_storage,
)
from jobbot.models import AlertState, ApplicationsState, FeedState, ResumeProfile, SearchConfig, SeenJobsState
from jobbot.sources import create_source


def _load_dotenv(path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ (stdlib only)."""
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()
setup_logging()
logger = logging.getLogger(__name__)

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


def load_resume_profile() -> ResumeProfile:
    return common.load_resume_profile(RESUME_FILE)


def load_job_search_config() -> SearchConfig:
    return common.load_job_search_config(JOB_SEARCH_CONFIG_FILE)


def load_feed_state() -> dict[str, dict[str, float]]:
    return common.load_feed_state(FEED_STATE_FILE)


def save_feed_state(feed_state: FeedState) -> None:
    common.save_feed_state(FEED_STATE_FILE, feed_state)


def load_existing_jobs() -> list[dict[str, str]]:
    return common.load_existing_jobs(CSV_FILE)


def append_rows(rows: list[dict[str, str]]) -> None:
    common.append_rows(CSV_FILE, rows)


def load_seen_jobs_state() -> SeenJobsState:
    return common.load_seen_jobs_state(SEEN_JOBS_STATE_FILE)


def save_seen_jobs_state(seen_jobs_state: SeenJobsState) -> None:
    common.save_seen_jobs_state(SEEN_JOBS_STATE_FILE, seen_jobs_state)


def load_alert_state() -> AlertState:
    return common.load_alert_state(ALERTS_STATE_FILE)


def save_alert_state(alert_state: AlertState) -> None:
    common.save_alert_state(ALERTS_STATE_FILE, alert_state)


def save_matches_snapshot(run_time_utc: str, matches: list[dict[str, object]]) -> None:
    common.save_matches_snapshot(MATCHES_FILE, run_time_utc, matches)


def load_company_boards() -> list[dict[str, object]]:
    return source_module.load_company_boards(COMPANY_BOARDS_FILE)


def load_applications_state() -> ApplicationsState:
    return matching.load_applications_state(APPLICATIONS_FILE)


def save_applications_state(applications_state: ApplicationsState) -> None:
    matching.save_applications_state(APPLICATIONS_FILE, applications_state)


def save_feedback_metrics_snapshot(snapshot: dict[str, object]) -> None:
    matching.save_feedback_metrics_snapshot(FEEDBACK_METRICS_FILE, snapshot)


def save_daily_digest_snapshot(snapshot: dict[str, object]) -> None:
    matching.save_daily_digest_snapshot(DAILY_DIGEST_FILE, snapshot)


def build_application_briefs_snapshot(
    current_run_ts: str,
    applications_state: ApplicationsState,
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
    feedback_profile = build_feedback_metrics(
        current_run_ts, applications_state, search_config, initial_cleanup_summary
    )
    save_applications_state(applications_state)

    for job in existing_jobs:
        storage.append_reviewed_fingerprints(
            STATE_DB_FILE,
            build_review_fingerprints(job["title"], job["description"], job["link"]),
            MAX_REVIEWED_FINGERPRINTS,
        )

    preferred_locations = cast(list[str], profile["preferred_locations"])
    regions = ["us", "usa", "united states", "uk", "united kingdom", "canada", "europe", "americas"]
    lockouts = [f"{region} only" for region in regions if region not in preferred_locations]
    lockouts += [f"remote {region}" for region in regions if region not in preferred_locations]

    all_sources: list[dict[str, Any]] = [*FEEDS, *company_boards]
    due_sources = []
    checked_at = time()
    for source in all_sources:
        if is_feed_due(source, feed_state, checked_at):
            due_sources.append(source)

    if not due_sources:
        logger.info("Jobs: No feeds are due for check at this time.")
    else:

        def fetch_task(src: dict[str, Any]) -> tuple[dict[str, Any], list[Any] | None, Exception | None]:
            try:
                inst = create_source(src)
                return src, inst.fetch(), None
            except (ElementTree.ParseError, HTTPError, URLError, OSError, ValueError) as exc:
                return src, None, exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_source = {executor.submit(fetch_task, s): s for s in due_sources}
            for future in concurrent.futures.as_completed(future_to_source):
                source, items, exc = future.result()
                source_label = get_source_display_name(source)
                source_name = cast(str, source["name"])

                if exc:
                    source_ref = source.get("url") or source.get("platform") or source_name
                    logger.warning("skipping %s — %s", source_ref, exc)

                    # Update failure count
                    state = feed_state.get(source_name, {"last_checked_at": 0.0, "consecutive_failures": 0})
                    failures = cast(int, state.get("consecutive_failures", 0)) + 1
                    feed_state[source_name] = {
                        "last_checked_at": state.get("last_checked_at", 0.0),
                        "consecutive_failures": failures,
                    }

                    if failures == 10:
                        logger.error("Source %s failed 10 times consecutively. Alerting.", source_label)
                        match_details.append(
                            {
                                "time": current_run_ts,
                                "title": f"⚠️ Source Failure: {source_label}",
                                "description": f"The job source '{source_label}' has failed 10 times in a row. "
                                "Please check the source URL and integration settings.",
                                "link": str(source.get("url", "https://github.com/jobbot")),
                                "source": "System Monitor",
                                "qualified": True,
                                "score": 100,
                            }
                        )
                    continue

                # Success
                feed_state[source_name] = {
                    "last_checked_at": checked_at,
                    "consecutive_failures": 0,
                }

                if items is None:
                    continue

                new_rows = []
                for item in items:
                    link = clean_text(item.link)
                    fingerprints = build_review_fingerprints(item.title, item.description, link)
                    if (
                        not link
                        or link in existing_links
                        or storage.has_any_reviewed_fingerprint(STATE_DB_FILE, fingerprints)
                    ):
                        continue

                    eval = cast(
                        dict[str, Any],
                        score_job(
                            item,
                            source_label,
                            profile,
                            search_config,
                            feedback_profile,
                            current_run_ts,
                            lockouts,
                        ),
                    )
                    storage.append_reviewed_fingerprints(STATE_DB_FILE, fingerprints, MAX_REVIEWED_FINGERPRINTS)
                    reviewed_count += 1
                    if not eval["qualified"]:
                        candidate = cast(dict[str, object] | None, eval.get("candidate"))
                        if candidate and cast(int, eval["score"]) >= max(0, MIN_MATCH_SCORE - BORDERLINE_MATCH_MARGIN):
                            borderline_details.append(candidate)
                        continue

                    match = cast(dict[str, Any], eval["match"])
                    new_rows.append(
                        {
                            "time": match["time"],
                            "title": match["title"],
                            "company": match.get("company", ""),
                            "location": clean_text(item.location),
                            "salary": clean_text(item.salary),
                            "source": source_label,
                            "employment_type": clean_text(item.employment_type),
                            "date_posted": clean_text(item.date_posted),
                            "description": match["description"],
                            "link": match["link"],
                        }
                    )
                    match_details.append(cast(dict[str, object], match))
                    if upsert_application_record_in_storage(cast(dict[str, object], match), current_run_ts):
                        applications_created += 1
                    existing_links.add(link)
                    new_hits += 1

                append_rows(new_rows)

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
    save_feedback_metrics_snapshot(cast(dict[str, object], feedback_profile["snapshot"]))
    save_applications_state(applications_state)

    if (
        new_hits > 0
        or sent_count > 0
        or queued_count > 0
        or applications_created > 0
        or seeded_applications > 0
        or digest_sent
        or cast(int, cleanup_summary["removed_count"]) > 0
    ):
        logger.info(
            "Jobs: found %d new matches, reviewed %d new items, tracked %d applications, "
            "seeded %d, pruned %d stale applications, queued %d alerts, sent %d, "
            "pending %d, digest %s.",
            new_hits,
            reviewed_count,
            applications_created,
            seeded_applications,
            cast(int, cleanup_summary["removed_count"]),
            queued_count,
            sent_count,
            len(alert_state["pending_alerts"]),
            "sent" if digest_sent else "not sent",
        )
    else:
        logger.info("Jobs: No new matches found in this sweep.")

    if delivery_error:
        logger.error("Jobs: %s", delivery_error)
    if digest_error:
        logger.error("Jobs: %s", digest_error)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
