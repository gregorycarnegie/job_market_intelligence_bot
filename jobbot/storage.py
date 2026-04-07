import contextlib
import csv
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

CSV_HEADERS = [
    "time",
    "title",
    "company",
    "location",
    "salary",
    "source",
    "employment_type",
    "date_posted",
    "description",
    "link",
]


def _connect(db_file: str) -> sqlite3.Connection:
    """
    Establish a connection to the SQLite database, initializing it if necessary.

    Args:
        db_file: Path to the SQLite database file.

    Returns:
        A sqlite3.Connection object with row_factory set to sqlite3.Row.
    """
    db_path = Path(db_file)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _initialize_database(connection)
    return connection


def _initialize_database(connection: sqlite3.Connection) -> None:
    """
    Create necessary tables and apply any pending schema migrations.

    Args:
        connection: An active sqlite3.Connection.
    """
    connection.execute("CREATE TABLE IF NOT EXISTS migrations (id INTEGER PRIMARY KEY)")
    applied = {row["id"] for row in connection.execute("SELECT id FROM migrations").fetchall()}

    migrations = [
        # 1: Initial core tables and indexes
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_time ON jobs(time);

        CREATE TABLE IF NOT EXISTS feed_state (
            name TEXT PRIMARY KEY,
            last_checked_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_metadata (
            scope TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (scope, key)
        );

        CREATE TABLE IF NOT EXISTS reviewed_fingerprints (
            position INTEGER NOT NULL,
            fingerprint TEXT PRIMARY KEY
        );
        CREATE INDEX IF NOT EXISTS idx_reviewed_fingerprints_position ON reviewed_fingerprints(position);

        CREATE TABLE IF NOT EXISTS alerted_links (
            position INTEGER NOT NULL,
            link TEXT PRIMARY KEY
        );
        CREATE INDEX IF NOT EXISTS idx_alerted_links_position ON alerted_links(position);

        CREATE TABLE IF NOT EXISTS pending_alerts (
            position INTEGER NOT NULL,
            link TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pending_alerts_position ON pending_alerts(position);

        CREATE TABLE IF NOT EXISTS applications (
            position INTEGER NOT NULL,
            link TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_applications_position ON applications(position);

        CREATE TABLE IF NOT EXISTS application_links (
            link_value TEXT PRIMARY KEY,
            application_link TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_application_links_application_link
            ON application_links(application_link);

        CREATE TABLE IF NOT EXISTS application_fingerprints (
            fingerprint TEXT PRIMARY KEY,
            application_link TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_application_fingerprints_application_link
            ON application_fingerprints(application_link);

        CREATE TABLE IF NOT EXISTS telegram_digest_sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            pages_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_telegram_digest_sessions_created_at
            ON telegram_digest_sessions(created_at);
        """,
        # 2: Extended job metadata columns
        """
        ALTER TABLE jobs ADD COLUMN company TEXT DEFAULT '';
        ALTER TABLE jobs ADD COLUMN location TEXT DEFAULT '';
        ALTER TABLE jobs ADD COLUMN salary TEXT DEFAULT '';
        ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT '';
        ALTER TABLE jobs ADD COLUMN employment_type TEXT DEFAULT '';
        ALTER TABLE jobs ADD COLUMN date_posted TEXT DEFAULT '';
        """,
        # 3: Consecutive failure tracking for sources
        """
        ALTER TABLE feed_state ADD COLUMN consecutive_failures INTEGER DEFAULT 0;
        """,
    ]

    for i, sql in enumerate(migrations, start=1):
        if i in applied:
            continue

        try:
            connection.executescript(sql)
        except sqlite3.OperationalError as exc:
            # Handle cases where columns might already exist due to previous manual hacks
            if "duplicate column name" in str(exc).lower():
                pass
            else:
                raise
        connection.execute("INSERT INTO migrations (id) VALUES (?)", (i,))


def _load_scope_metadata(connection: sqlite3.Connection, scope: str) -> dict[str, str]:
    """
    Load key-value metadata for a specific scope from the state_metadata table.

    Args:
        connection: SQLite connection.
        scope: The metadata scope (e.g., 'alerts', 'seen_jobs').

    Returns:
        A dictionary of key-value pairs.
    """
    rows = connection.execute(
        "SELECT key, value FROM state_metadata WHERE scope = ?",
        (scope,),
    ).fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def _save_scope_metadata(connection: sqlite3.Connection, scope: str, metadata: dict[str, object]) -> None:
    """
    Save key-value metadata for a specific scope.

    Args:
        connection: SQLite connection.
        scope: The metadata scope.
        metadata: Dictionary of metadata to save.
    """
    connection.execute("DELETE FROM state_metadata WHERE scope = ?", (scope,))
    connection.executemany(
        "INSERT INTO state_metadata(scope, key, value) VALUES (?, ?, ?)",
        [(scope, key, str(value)) for key, value in metadata.items()],
    )


_POSITION_TABLES = {"reviewed_fingerprints", "applications"}


def _next_position(connection: sqlite3.Connection, table: str) -> int:
    """
    Calculate the next available position index for a table with a position column.

    Args:
        connection: SQLite connection.
        table: Table name.

    Returns:
        The next integer position.
    """
    if table not in _POSITION_TABLES:
        raise ValueError(f"Invalid table name: {table!r}")
    row = connection.execute(f"SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM {table}").fetchone()
    return int(row["next_position"]) if row is not None else 0


def _dedupe_values(values: Sequence[object]) -> list[str]:
    """
    Deduplicate a sequence of values while preserving order and removing empties.

    Args:
        values: Sequence of values to deduplicate.

    Returns:
        A list of unique non-empty strings.
    """
    cleaned = []
    seen = set()
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


def _delete_application_indexes(connection: sqlite3.Connection, application_link: str) -> None:
    """
    Remove link and fingerprint index entries for a specific application.

    Args:
        connection: SQLite connection.
        application_link: The primary link of the application record.
    """
    connection.execute("DELETE FROM application_links WHERE application_link = ?", (application_link,))
    connection.execute("DELETE FROM application_fingerprints WHERE application_link = ?", (application_link,))


def _index_application(connection: sqlite3.Connection, application: dict[str, object]) -> None:
    """
    Create link and fingerprint index entries for an application record.

    Args:
        connection: SQLite connection.
        application: Application record dictionary.
    """
    application_link = str(application.get("link", ""))
    if not application_link:
        return
    link_values = _dedupe_values([*cast(list[object], application.get("links", [])), application_link])
    fingerprint_values = _dedupe_values(cast(list[object], application.get("fingerprints", [])))
    connection.executemany(
        "INSERT OR REPLACE INTO application_links(link_value, application_link) VALUES (?, ?)",
        [(link_value, application_link) for link_value in link_values],
    )
    connection.executemany(
        "INSERT OR REPLACE INTO application_fingerprints(fingerprint, application_link) VALUES (?, ?)",
        [(fingerprint, application_link) for fingerprint in fingerprint_values],
    )


def load_jobs(db_file: str) -> list[dict[str, str]]:
    """
    Load all job records from the database.

    Args:
        db_file: Path to the database.

    Returns:
        List of job record dictionaries.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        rows = connection.execute(
            "SELECT time, title, description, link, company, location, salary,"
            " source, employment_type, date_posted FROM jobs ORDER BY id"
        ).fetchall()
    return [
        {
            "time": str(row["time"]),
            "title": str(row["title"]),
            "company": str(row["company"]),
            "location": str(row["location"]),
            "salary": str(row["salary"]),
            "source": str(row["source"]),
            "employment_type": str(row["employment_type"]),
            "date_posted": str(row["date_posted"]),
            "description": str(row["description"]),
            "link": str(row["link"]),
        }
        for row in rows
    ]


def load_latest_job_batch(db_file: str) -> tuple[str | None, list[dict[str, str]]]:
    """
    Identify the most recent crawl batch and return its jobs.

    Args:
        db_file: Path to the database.

    Returns:
        A tuple of (batch_timestamp_iso, list_of_jobs).
    """
    with contextlib.closing(_connect(db_file)) as connection:
        row = connection.execute("SELECT time FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None, []
        latest_ts = str(row["time"])
        batch_rows = connection.execute(
            "SELECT time, title, description, link, company,"
            " location, salary, source, employment_type, date_posted"
            " FROM jobs WHERE time = ? ORDER BY id",
            (latest_ts,),
        ).fetchall()

    return latest_ts, [
        {
            "time": str(batch_row["time"]),
            "title": str(batch_row["title"]),
            "company": str(batch_row["company"]),
            "location": str(batch_row["location"]),
            "salary": str(batch_row["salary"]),
            "source": str(batch_row["source"]),
            "employment_type": str(batch_row["employment_type"]),
            "date_posted": str(batch_row["date_posted"]),
            "description": str(batch_row["description"]),
            "link": str(batch_row["link"]),
        }
        for batch_row in batch_rows
    ]


def append_jobs(db_file: str, rows: list[dict[str, str]]) -> None:
    """
    Bulk insert new job records, ignoring existing links.

    Args:
        db_file: Path to the database.
        rows: List of job record dictionaries.
    """
    if not rows:
        return

    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.executemany(
            """
                INSERT OR IGNORE INTO jobs(
                    time, title, description, link, company,
                    location, salary, source, employment_type, date_posted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            [
                (
                    str(row.get("time", "")),
                    str(row.get("title", "")),
                    str(row.get("description", "")),
                    str(row.get("link", "")),
                    str(row.get("company", "")),
                    str(row.get("location", "")),
                    str(row.get("salary", "")),
                    str(row.get("source", "")),
                    str(row.get("employment_type", "")),
                    str(row.get("date_posted", "")),
                )
                for row in rows
                if str(row.get("link", ""))
            ],
        )


def export_jobs_to_csv(db_file: str, csv_file: str) -> None:
    """
    Export all job records from the database to a CSV file.

    Args:
        db_file: Path to the database.
        csv_file: Output CSV file path.
    """
    csv_path = Path(csv_file)
    rows = load_jobs(db_file)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def load_feed_state(db_file: str) -> dict[str, dict[str, Any]]:
    """
    Load the state of all job feeds (last checked timestamps and failure counts).

    Args:
        db_file: Path to the database.

    Returns:
        A dictionary mapping feed names to their state (last_checked_at, consecutive_failures).
    """
    with contextlib.closing(_connect(db_file)) as connection:
        rows = connection.execute(
            "SELECT name, last_checked_at, consecutive_failures FROM feed_state ORDER BY name"
        ).fetchall()
    return {
        str(row["name"]): {
            "last_checked_at": float(row["last_checked_at"]),
            "consecutive_failures": int(row["consecutive_failures"]),
        }
        for row in rows
    }


def save_feed_state(db_file: str, feed_state: dict[str, dict[str, Any]]) -> None:
    """
    Save the state of all job feeds.

    Args:
        db_file: Path to the database.
        feed_state: Dictionary of feed states.
    """
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute("DELETE FROM feed_state")
        connection.executemany(
            "INSERT INTO feed_state(name, last_checked_at, consecutive_failures) VALUES (?, ?, ?)",
            [
                (
                    name,
                    float(state.get("last_checked_at", 0)),
                    int(state.get("consecutive_failures", 0)),
                )
                for name, state in feed_state.items()
            ],
        )


def load_seen_jobs_state(db_file: str) -> dict[str, object]:
    """
    Load the state of seen jobs and reviewed fingerprints.

    Args:
        db_file: Path to the database.

    Returns:
        State dictionary including reviewed_fingerprints list and last_run_utc.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        fingerprints = [
            str(row["fingerprint"])
            for row in connection.execute("SELECT fingerprint FROM reviewed_fingerprints ORDER BY position").fetchall()
        ]
        metadata = _load_scope_metadata(connection, "seen_jobs")

    return {
        "reviewed_fingerprints": fingerprints,
        "last_run_utc": metadata.get("last_run_utc", ""),
    }


def reviewed_fingerprint_count(db_file: str) -> int:
    """
    Count the number of reviewed job fingerprints in the database.

    Args:
        db_file: Path to the database.

    Returns:
        The total count of reviewed fingerprints.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM reviewed_fingerprints").fetchone()
    return int(row["count"]) if row is not None else 0


def has_any_reviewed_fingerprint(db_file: str, fingerprints: list[str]) -> bool:
    """
    Check if any of the provided fingerprints have been previously reviewed.

    Args:
        db_file: Path to the database.
        fingerprints: List of fingerprints to check.

    Returns:
        True if at least one fingerprint is found in the database.
    """
    candidates = _dedupe_values(fingerprints)
    if not candidates:
        return False
    placeholders = ", ".join("?" for _ in candidates)
    with contextlib.closing(_connect(db_file)) as connection:
        row = connection.execute(
            f"SELECT 1 FROM reviewed_fingerprints WHERE fingerprint IN ({placeholders}) LIMIT 1",
            tuple(candidates),
        ).fetchone()
    return row is not None


def append_reviewed_fingerprints(db_file: str, fingerprints: list[str], max_items: int) -> None:
    """
    Append new fingerprints to the reviewed list, enforcing a maximum size.

    Args:
        db_file: Path to the database.
        fingerprints: New fingerprints to add.
        max_items: Maximum capacity for the reviewed fingerprints list.
    """
    candidates = _dedupe_values(fingerprints)
    if not candidates:
        return
    with contextlib.closing(_connect(db_file)) as connection, connection:
        position = _next_position(connection, "reviewed_fingerprints")
        for fingerprint in candidates:
            connection.execute(
                "INSERT OR IGNORE INTO reviewed_fingerprints(position, fingerprint) VALUES (?, ?)",
                (position, fingerprint),
            )
            position += 1

        row = connection.execute("SELECT COUNT(*) AS count FROM reviewed_fingerprints").fetchone()
        total_count = int(row["count"]) if row is not None else 0
        overflow = max(0, total_count - max_items)
        if overflow:
            connection.execute(
                """
                    DELETE FROM reviewed_fingerprints
                    WHERE fingerprint IN (
                        SELECT fingerprint
                        FROM reviewed_fingerprints
                        ORDER BY position ASC
                        LIMIT ?
                    )
                    """,
                (overflow,),
            )


def save_seen_jobs_state(db_file: str, seen_jobs_state: dict[str, object]) -> None:
    """
    Bulk save the seen jobs state, replacing existing data.

    Args:
        db_file: Path to the database.
        seen_jobs_state: State dictionary to save.
    """
    fingerprints = cast(list[object], seen_jobs_state.get("reviewed_fingerprints", []))
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute("DELETE FROM reviewed_fingerprints")
        connection.executemany(
            "INSERT INTO reviewed_fingerprints(position, fingerprint) VALUES (?, ?)",
            [(position, str(fingerprint)) for position, fingerprint in enumerate(fingerprints) if str(fingerprint)],
        )
        _save_scope_metadata(
            connection,
            "seen_jobs",
            {"last_run_utc": seen_jobs_state.get("last_run_utc", "")},
        )


def load_alert_state(db_file: str) -> dict[str, object]:
    """
    Load the alert history and pending notifications state.

    Args:
        db_file: Path to the database.

    Returns:
        State dictionary including alerted_links, pending_alerts, and metadata.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        alerted_links = [
            str(row["link"])
            for row in connection.execute("SELECT link FROM alerted_links ORDER BY position").fetchall()
        ]
        pending_alerts = []
        for row in connection.execute("SELECT payload_json FROM pending_alerts ORDER BY position").fetchall():
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                pending_alerts.append(payload)
        metadata = _load_scope_metadata(connection, "alerts")

    return {
        "alerted_links": alerted_links,
        "pending_alerts": pending_alerts,
        "last_run_utc": metadata.get("last_run_utc", ""),
        "last_delivery_utc": metadata.get("last_delivery_utc", ""),
        "last_delivery_error": metadata.get("last_delivery_error", ""),
    }


def save_alert_state(db_file: str, alert_state: dict[str, object]) -> None:
    """
    Bulk save the alert state, replacing existing data.

    Args:
        db_file: Path to the database.
        alert_state: State dictionary to save.
    """
    alerted_links = cast(list[object], alert_state.get("alerted_links", []))
    pending_alerts = cast(list[object], alert_state.get("pending_alerts", []))
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute("DELETE FROM alerted_links")
        connection.executemany(
            "INSERT INTO alerted_links(position, link) VALUES (?, ?)",
            [(position, str(link)) for position, link in enumerate(alerted_links) if str(link)],
        )
        connection.execute("DELETE FROM pending_alerts")
        connection.executemany(
            "INSERT INTO pending_alerts(position, link, payload_json) VALUES (?, ?, ?)",
            [
                (
                    position,
                    str(payload.get("link", "")),
                    json.dumps(payload, ensure_ascii=False),
                )
                for position, payload in enumerate(pending_alerts)
                if isinstance(payload, dict) and str(payload.get("link", ""))
            ],
        )
        _save_scope_metadata(
            connection,
            "alerts",
            {
                "last_run_utc": alert_state.get("last_run_utc", ""),
                "last_delivery_utc": alert_state.get("last_delivery_utc", ""),
                "last_delivery_error": alert_state.get("last_delivery_error", ""),
            },
        )


def load_applications_state(db_file: str) -> dict[str, object]:
    """
    Load all application records and associated metadata.

    Args:
        db_file: Path to the database.

    Returns:
        State dictionary including applications list and metadata.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        applications = []
        for row in connection.execute("SELECT payload_json FROM applications ORDER BY position").fetchall():
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                applications.append(payload)
        metadata = _load_scope_metadata(connection, "applications")

    return {
        "applications": applications,
        "last_updated_utc": metadata.get("last_updated_utc", ""),
        "last_digest_utc": metadata.get("last_digest_utc", ""),
        "last_digest_date_utc": metadata.get("last_digest_date_utc", ""),
        "last_digest_error": metadata.get("last_digest_error", ""),
        "last_feedback_utc": metadata.get("last_feedback_utc", ""),
        "last_cleanup_utc": metadata.get("last_cleanup_utc", ""),
    }


def find_application_by_link_or_fingerprints(
    db_file: str,
    link: str,
    fingerprints: list[str],
) -> tuple[str | None, dict[str, object] | None]:
    """
    Search for an existing application record using multiple identifiers.

    Args:
        db_file: Path to the database.
        link: A job link to search for.
        fingerprints: A list of content fingerprints to search for.

    Returns:
        A tuple of (primary_link, payload_dict) if found, else (None, None).
    """
    candidate_link = str(link)
    candidate_fingerprints = _dedupe_values(fingerprints)
    with contextlib.closing(_connect(db_file)) as connection:
        application_link = None
        if candidate_link:
            row = connection.execute(
                "SELECT application_link FROM application_links WHERE link_value = ?",
                (candidate_link,),
            ).fetchone()
            if row is not None:
                application_link = str(row["application_link"])
        if application_link is None and candidate_fingerprints:
            placeholders = ", ".join("?" for _ in candidate_fingerprints)
            row = connection.execute(
                f"SELECT application_link FROM application_fingerprints WHERE fingerprint IN ({placeholders}) LIMIT 1",
                tuple(candidate_fingerprints),
            ).fetchone()
            if row is not None:
                application_link = str(row["application_link"])
        if application_link is None:
            return None, None

        payload_row = connection.execute(
            "SELECT payload_json FROM applications WHERE link = ?",
            (application_link,),
        ).fetchone()
        if payload_row is None:
            return application_link, None
        try:
            payload = json.loads(str(payload_row["payload_json"]))
        except json.JSONDecodeError:
            return application_link, None
    return application_link, payload if isinstance(payload, dict) else None


def save_application_record(
    db_file: str,
    application: dict[str, object],
    previous_link: str | None = None,
) -> None:
    """
    Save or update a single application record and refresh its indexes.

    Args:
        db_file: Path to the database.
        application: The application record to save.
        previous_link: Optional old link if the primary link is being changed.
    """
    application_link = str(application.get("link", ""))
    if not application_link:
        return

    with contextlib.closing(_connect(db_file)) as connection, connection:
        row = None
        if previous_link:
            row = connection.execute(
                "SELECT position FROM applications WHERE link = ?",
                (previous_link,),
            ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT position FROM applications WHERE link = ?",
                (application_link,),
            ).fetchone()
        position = int(row["position"]) if row is not None else _next_position(connection, "applications")

        if previous_link:
            _delete_application_indexes(connection, previous_link)
            connection.execute("DELETE FROM applications WHERE link = ?", (previous_link,))
        if application_link != previous_link:
            _delete_application_indexes(connection, application_link)
            connection.execute("DELETE FROM applications WHERE link = ?", (application_link,))

        connection.execute(
            "INSERT INTO applications(position, link, payload_json) VALUES (?, ?, ?)",
            (position, application_link, json.dumps(application, ensure_ascii=False)),
        )
        _index_application(connection, application)


def save_applications_state(db_file: str, applications_state: dict[str, object]) -> None:
    """
    Bulk save the entire applications state and rebuild all indexes.

    Args:
        db_file: Path to the database.
        applications_state: State dictionary to save.
    """
    applications = cast(list[object], applications_state.get("applications", []))
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute("DELETE FROM applications")
        connection.execute("DELETE FROM application_links")
        connection.execute("DELETE FROM application_fingerprints")
        connection.executemany(
            "INSERT INTO applications(position, link, payload_json) VALUES (?, ?, ?)",
            [
                (
                    position,
                    str(application.get("link", "")),
                    json.dumps(application, ensure_ascii=False),
                )
                for position, application in enumerate(applications)
                if isinstance(application, dict) and str(application.get("link", ""))
            ],
        )
        for application in applications:
            if isinstance(application, dict) and str(application.get("link", "")):
                _index_application(connection, application)
        _save_scope_metadata(
            connection,
            "applications",
            {
                "last_updated_utc": applications_state.get("last_updated_utc", ""),
                "last_digest_utc": applications_state.get("last_digest_utc", ""),
                "last_digest_date_utc": applications_state.get("last_digest_date_utc", ""),
                "last_digest_error": applications_state.get("last_digest_error", ""),
                "last_feedback_utc": applications_state.get("last_feedback_utc", ""),
                "last_cleanup_utc": applications_state.get("last_cleanup_utc", ""),
            },
        )


def load_telegram_update_offset(db_file: str) -> int:
    """
    Load the Telegram update offset (for polling) from the database.

    Args:
        db_file: Path to the database.

    Returns:
        The last processed update ID.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        metadata = _load_scope_metadata(connection, "telegram")
    try:
        return max(0, int(metadata.get("update_offset", "0")))
    except ValueError:
        return 0


def save_telegram_update_offset(db_file: str, offset: int) -> None:
    """
    Save the Telegram update offset.

    Args:
        db_file: Path to the database.
        offset: The update ID to save.
    """
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO state_metadata(scope, key, value) VALUES ('telegram', 'update_offset', ?)",
            (str(max(0, int(offset))),),
        )


def save_telegram_digest_session(
    db_file: str,
    session_id: str,
    created_at: str,
    pages: list[str],
    keep_latest: int = 20,
) -> None:
    """
    Save a Telegram digest pagination session.

    Args:
        db_file: Path to the database.
        session_id: Unique session ID.
        created_at: Creation timestamp.
        pages: List of formatted message pages.
        keep_latest: Max number of history sessions to retain.
    """
    with contextlib.closing(_connect(db_file)) as connection, connection:
        connection.execute(
            """
                INSERT OR REPLACE INTO telegram_digest_sessions(session_id, created_at, pages_json)
                VALUES (?, ?, ?)
                """,
            (session_id, created_at, json.dumps(list(pages), ensure_ascii=False)),
        )
        if keep_latest > 0:
            row = connection.execute("SELECT COUNT(*) AS count FROM telegram_digest_sessions").fetchone()
            total_count = int(row["count"]) if row is not None else 0
            overflow = max(0, total_count - keep_latest)
            if overflow:
                connection.execute(
                    """
                        DELETE FROM telegram_digest_sessions
                        WHERE session_id IN (
                            SELECT session_id
                            FROM telegram_digest_sessions
                            ORDER BY created_at ASC, session_id ASC
                            LIMIT ?
                        )
                        """,
                    (overflow,),
                )


def load_telegram_digest_session(db_file: str, session_id: str) -> dict[str, object] | None:
    """
    Load a Telegram digest pagination session by its ID.

    Args:
        db_file: Path to the database.
        session_id: The session ID to look up.

    Returns:
        The session dictionary or None if not found or invalid.
    """
    with contextlib.closing(_connect(db_file)) as connection:
        row = connection.execute(
            """
            SELECT session_id, created_at, pages_json
            FROM telegram_digest_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        pages = json.loads(str(row["pages_json"]))
    except json.JSONDecodeError:
        return None
    if not isinstance(pages, list):
        return None
    page_texts = [str(page) for page in pages if str(page)]
    if not page_texts:
        return None
    return {
        "session_id": str(row["session_id"]),
        "created_at": str(row["created_at"]),
        "pages": page_texts,
    }
