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
