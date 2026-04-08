# job_market_intelligence_bot

[![CI](https://github.com/gregorycarnegie/job_market_intelligence_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/gregorycarnegie/job_market_intelligence_bot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/shell-bash-89e051?logo=gnubash&logoColor=white)](https://www.gnu.org/software/bash/)

Job search automation for resume-based filtering, SQLite-backed state, optional direct Telegram alerts, and optional OpenClaw handoff.

The current repo is Python-first. OpenClaw is optional and only needs to read small generated files such as `desc.json`, `borderline_matches.json`, and `application_briefs.json`.

## Overview

The bot currently:

- polls a built-in set of feeds defined in `jobbot/common.py`
- supports optional company board ingestion from `company_boards.json`
- scores jobs against `resume.json`, location preferences, salary heuristics, and role profiles
- stores authoritative runtime state in `jobbot_state.sqlite3`
- exports CSV/JSON mirrors for inspection
- can send direct Telegram alerts plus a paged daily digest
- can stage the latest matched batch into `desc.json` for OpenClaw

Built-in source support includes:

- RSS and HTML feeds
- eFinancialCareers HTML
- Remotive
- The Muse
- Arbeitnow
- Adzuna, Reed, and Jooble APIs
- optional Greenhouse, Lever, Ashby, Workable, and generic HTML career boards

## Repo Layout

- `pull_jobs.py`: main runtime entrypoint; fetches, scores, stores, snapshots, and sends alerts
- `pull_desc.py`: exports only the latest matched batch into `desc.json`
- `telegram_callback_worker.py`: long-polls Telegram `callback_query` updates for digest pagination
- `exec_loop.sh`: keeps the callback worker alive and runs the main job loop every 60 seconds
- `jobbot/common.py`: shared constants, built-in feeds, config loading, text helpers
- `jobbot/sources.py`: source integrations and company-board loaders
- `jobbot/matching.py`: scoring, application tracking, Telegram delivery, digest generation, feedback logic
- `jobbot/storage.py`: SQLite schema, migrations, and persistence helpers
- `resume.json`: sample resume/profile data; replace this with your own details before running
- `.env.example`: optional Telegram and provider API credentials
- `openclaw_job_alerts_prompt.txt`: prompt text for optional OpenClaw cron usage

## Quick Start

### 1. Requirements

- Python 3.10+
- Linux or another always-on environment if you want continuous polling
- Telegram bot credentials only if you want direct Telegram delivery
- OpenClaw only if you want the optional AI review / relay layer

The runtime code uses the Python standard library. `uv`, `pytest`, `ruff`, `mypy`, and `pylint` are only needed for development and verification.

### 2. Clone the Repo

```bash
git clone https://github.com/gregorycarnegie/job_market_intelligence_bot.git
cd job_market_intelligence_bot
```

### 3. Replace the Sample Resume

Edit `resume.json` before running the bot. The important fields the current code reads are:

- `personal_info.name`
- `personal_info.title`
- `personal_info.location.city`
- `personal_info.location.country`
- `personal_info.target_roles`
- `personal_info.preferences.remote`
- `personal_info.preferences.hybrid`
- `personal_info.preferences.onsite`
- `personal_info.preferences.preferred_locations`
- `personal_info.preferences.minimum_salary_gbp`
- `technical_skills.skills`
- `technical_skills.competencies`
- `summary` and `experience` for extra matching evidence

### 4. Review the Built-In Feed List

The default feed list is hard-coded in `jobbot/common.py` as `FEEDS`.

Review that list before running the loop long-term:

- it is opinionated and currently UK / remote / IT-support focused
- it includes Adzuna, Reed, and Jooble entries that require API keys
- it includes Google Alerts feed URLs that you may want to replace with your own

If you do not want a built-in source, remove or edit that entry in `jobbot/common.py`.

### 5. Optional `.env` Setup

Create a `.env` file if you want Telegram delivery or API-backed providers:

```bash
cp .env.example .env
```

Supported keys in the shipped example:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_THREAD_ID` (optional, for forum topics)
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `REED_APP_KEY`
- `JOOBLE_APP_KEY`

If you leave provider keys blank while keeping those providers in `FEEDS`, those sources will be skipped and their failure counters will increase on each run.

### 6. Optional Local Config Files

The repo currently looks for `company_boards.json` and `job_search_config.json`, but example copies are not committed. Create them yourself only if you need them.

Minimal `company_boards.json` example:

```json
[
  {
    "name": "acme_greenhouse",
    "display_name": "Acme",
    "platform": "greenhouse",
    "board_token": "acme"
  },
  {
    "name": "acme_generic_html",
    "display_name": "Acme",
    "platform": "generic_html",
    "start_urls": ["https://example.com/careers"],
    "allowed_domains": ["example.com"],
    "job_link_keywords": ["jobs", "careers", "role"],
    "job_link_regexes": ["/careers/.+"],
    "max_job_pages": 20
  }
]
```

Supported `platform` values are:

- `greenhouse`
- `lever`
- `ashby`
- `workable`
- `generic_html`

Minimal `job_search_config.json` example:

```json
{
  "priority_companies": ["Monzo"],
  "company_blacklist": ["Example Corp"],
  "daily_digest": {
    "enabled": true,
    "hour_utc": 7,
    "max_items": 8,
    "page_size": 4
  },
  "feedback": {
    "enabled": true
  }
}
```

If `job_search_config.json` is missing, the code falls back to built-in defaults, including default role profiles.

### 7. Run Once

From the repo root:

```bash
python3 pull_jobs.py
python3 pull_desc.py
```

If you are using direct Telegram digest paging outside `exec_loop.sh`, run the callback worker separately:

```bash
python3 telegram_callback_worker.py
```

### 8. Run Continuously

`exec_loop.sh` does three things:

- loads `.env` if present
- keeps `telegram_callback_worker.py` alive
- runs `pull_jobs.py` and `pull_desc.py` every 60 seconds

Typical background start on Linux:

```bash
chmod 700 exec_loop.sh
nohup ./exec_loop.sh > output.log 2>&1 &
```

## Runtime Files

`jobbot_state.sqlite3` is the source of truth. Most JSON files are mirrors or derived snapshots written after each run.

| File                      | Purpose                                                                                           | Safe to delete? |
|---------------------------|---------------------------------------------------------------------------------------------------|-----------------|
| `jobbot_state.sqlite3`    | Authoritative runtime database for jobs, alerts, applications, feed state, and Telegram sessions. | No              |
| `jobs.csv`                | CSV export of jobs stored in SQLite.                                                              | Yes             |
| `matches.json`            | Latest-run snapshot of newly matched jobs.                                                        | Yes             |
| `desc.json`               | Latest matched batch exported for OpenClaw.                                                       | Yes             |
| `alerts_state.json`       | JSON mirror of alert queue and delivery metadata.                                                 | Yes             |
| `seen_jobs_state.json`    | JSON mirror of reviewed job fingerprints.                                                         | Yes             |
| `applications.json`       | JSON mirror of application records and digest metadata.                                           | Yes             |
| `feed_state.json`         | JSON mirror of source polling timestamps and failure counts.                                      | Yes             |
| `daily_digest.json`       | Latest digest snapshot.                                                                           | Yes             |
| `application_briefs.json` | Application-ready jobs with fit notes and draft material.                                         | Yes             |
| `borderline_matches.json` | Near-threshold jobs for optional AI review.                                                       | Yes             |
| `feedback_metrics.json`   | Current feedback snapshot and learned adjustments.                                                | Yes             |

Important detail: the JSON state files above are outputs, not the authoritative input path. The current code reads and writes runtime state through SQLite first, then exports JSON mirrors. Do not rely on hand-editing those JSON files and expecting the bot to load them back.

If you want a full reset, stop the loop and remove `jobbot_state.sqlite3`. The CSV/JSON files can be deleted as well and will be regenerated.

## OpenClaw

OpenClaw is optional.

Current repo behavior:

- `pull_desc.py` rewrites `desc.json` with only the latest matched batch
- `openclaw_job_alerts_prompt.txt` is the prompt file for an OpenClaw cron task
- `borderline_matches.json` and `application_briefs.json` are better handoff files for higher-value AI review than the full feed

Because `desc.json` only contains the newest batch, slower OpenClaw polling intervals can miss intermediate runs.

## Testing And Dev Tools

Run the current test suite with:

```bash
python3 -m unittest discover -s tests -v
```

If you want the full dev toolchain from `pyproject.toml`:

```bash
uv sync --extra dev
uv run pytest tests/
uv run ruff check .
uv run mypy .
uv run pylint jobbot
```
