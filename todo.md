# TODO

## Immediate Buildout

- [x] Add a tracked roadmap inside the repo.
- [x] Move alert-state persistence into Python with a real `alerts_state.json`.
- [x] Add direct Telegram delivery from Python using only the standard library.
- [x] Queue unsent alerts and retry them on the next loop instead of dropping them.
- [x] Add weighted job scoring with explainable reasons instead of pure binary matching.
- [x] Persist a scored latest-run snapshot to `matches.json` for inspection.
- [x] Add `.env` support in `exec_loop.sh` plus an `.env.example` template.
- [x] Persist a separate seen-feed history for non-matching jobs so old feed items are not rescored forever.
- [x] Parse salary more deeply across currencies, ranges, and day-rate contracts.
- [x] Canonicalize duplicates across sources beyond raw link equality.

## Source Expansion

- [x] Add Greenhouse ingestion.
- [x] Add Lever ingestion.
- [x] Add Ashby ingestion.
- [x] Add Workable ingestion.
- [x] Add configurable direct company careers-page scraping for target employers.

## Application Machine

- [x] Add `applications.csv` or `applications.json` with statuses like `new`, `reviewed`, `applied`, `rejected`, `interview`.
- [x] Add a daily top-matches digest ranked by score and freshness.
- [x] Add company whitelist and blacklist controls.
- [x] Add a shortlist workflow for high-priority employers.
- [x] Add a per-role scoring profile so support/sysadmin roles outrank adjacent engineering roles.

## AI Layer

- [x] Keep OpenClaw optional and move it off the critical alert path.
- [x] Use AI only for borderline-fit review, resume tailoring, and message drafting.
- [x] Add generated “why this fits” notes for top matches.
- [x] Add resume bullet suggestions per shortlisted job.
- [x] Add cover-letter or intro-message drafting for application-ready jobs.

## Feedback Loop

- [x] Record outcomes from applications and interviews.
- [x] Reweight sources and keywords based on interview hit rate.
- [x] Add periodic cleanup and pruning for long-lived state files.

## Architecture

- [x] Introduce a `JobLead` dataclass with structured fields (`title`, `link`, `source`, `company`, `location`, `salary`, `description`, `employment_type`, `date_posted`) to replace the current flat `dict[str, str]` with a concatenated `description` blob.
- [x] Replace current `fetch_company_board_items` dispatch dict with an abstract `Source` base class (`fetch() -> list[JobLead]`) so every source type (RSS, API, email, HN) is a uniform, pluggable unit.
- [x] Migrate all existing source handlers (Greenhouse, Lever, Ashby, Workable, generic HTML, RSS feeds) to the new `Source` interface and `JobLead` output before adding new sources.
- [x] Update `matching.py` and `storage.py` to consume `JobLead` fields directly instead of pattern-matching against the flat description string.

## Free Job API Sources

- [ ] Add Reed.co.uk API ingestion (UK/London specialist, clean salary bands, direct apply URLs — register at reed.co.uk/developers).
- [ ] Add Adzuna API ingestion (UK aggregator, salary trends, company data — register at developer.adzuna.com).
- [ ] Add Jooble API ingestion (global aggregator with heavy ATS coverage — key via RapidAPI or jooble.org developer portal).
- [ ] Add The Muse API ingestion (tech/modern companies, filter by category and level — themuse.com/developers/api/v2, no key needed up to 500 req/hr).
- [ ] Add Arbeitnow API ingestion (tech-heavy, EU/remote, visa sponsorship flags — no API key needed, hit arbeitnow.com/api/job-board-api).
- [ ] Switch Remotive source from RSS to JSON API (no key needed — remotive.com/api/remote-jobs?category=software-dev).

## Free Job Sources (Non-API)

- [ ] Add email inbox parsing via IMAP (dedicated Gmail account for job alerts from LinkedIn, Indeed, Otta — use imaplib + BeautifulSoup to extract jobs from alert emails).
- [ ] Add Hacker News "Who is Hiring" ingestion (monthly thread on first weekday — parse via Hacker News Firebase API at hacker-news.firebaseio.com/v0/, filter for London/UK/hybrid keywords).
- [ ] Add Discord job channel monitoring (join UK tech community servers, listen to #jobs channels via discord.py — requires permission from server admins).
- [ ] Add Slack job channel monitoring (join Tech London Slack and similar, monitor #jobs/#careers channels via Slack API).
