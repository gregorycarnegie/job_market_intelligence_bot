# job_market_intelligence_bot

[![CI](https://github.com/gregorycarnegie/job_market_intelligence_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/gregorycarnegie/job_market_intelligence_bot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)

Automated Search for Job Listings in RSS Feeds with self-hosted OpenClaw running on VPS. Offloading all the heavy complex logic to Python (running on OS, without wasting OpenClaw credits) and sharing bare minimum information with OpenClaw, only what's absolutely necessary for its decision making process.

## 📽️ Step By Step OpenClaw Video Tutorial

[![Step By Step OpenClaw Video Tutorial](https://github.com/user-attachments/assets/e1322230-b694-4b4c-a2cf-f2b5abc383d4)](https://youtu.be/ehfTs0wdW5g)

Watch Full Video Here: <https://youtu.be/ehfTs0wdW5g>

## 👀 Overview

This repository contains several files, part of the job market intelligence mechanism:

- `resume.json`: stores skills, preferences, and experience information that the Python scripts and OpenClaw rely on.
  OpenClaw will read the entire file once, while `pull_jobs.py` will pull special fields from this file in every execution (once every 60 seconds).
  OpenClaw will use AI credits to read the file and store it in memory, Python file will not use AI credits as it runs on the system level with Bash.
- `pull_jobs.py`: thin entrypoint/orchestrator for the job bot. It wires together feed polling, scoring, state updates, snapshots, and direct Telegram delivery.
- `telegram_callback_worker.py`: dedicated Telegram inline-button worker that long-polls `callback_query` updates and edits the current digest page in place.
- `jobbot/common.py`: shared constants, text helpers, resume/config loading, and JSON/CSV state helpers.
- `jobbot_state.sqlite3`: primary runtime database for matched jobs, review history, alerts, applications, and feed polling state.
- `jobbot/sources.py`: feed and careers-page ingestion for RSS, Greenhouse, Lever, Ashby, Workable, and generic HTML careers pages.
- `jobbot/matching.py`: scoring, application tracking, alerts, daily digest generation, and feedback learning.
- `pull_desc.py`: fetches listings **only** from the most recent matched batch in the runtime store, then stages them into `desc.json` (a file that's being generated in the first run, and **replaced continuously** - always storing **the most recent listings** and disposing of the rest). `desc.json` is the only file that OpenClaw is exposed to.
- `exec_loop.sh`: a bash script that keeps `telegram_callback_worker.py` running in the background while `pull_jobs.py` and `pull_desc.py` continue on the 60-second cadence. Meant to run with Nohup on the system level of the VPS (see instructions below).
- `.env.example`: a template for optional direct Telegram delivery using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- `company_boards.json.example`: optional company-board config for Greenhouse, Lever, Ashby, and Workable sources.
- `job_search_config.json.example`: optional search-operations config for company whitelist / blacklist, shortlist employers, daily digest settings, and role-profile weights.
- `seen_jobs_state.json`: runtime state that remembers already reviewed items, including non-matches, so the same old feed entries are not rescored on every loop.
- `application_briefs.json`: runtime snapshot of application-ready jobs with generated fit notes, resume bullet suggestions, and intro-message drafts.
- `borderline_matches.json`: runtime snapshot of near-threshold jobs that are worth optional AI review instead of sending the entire feed to OpenClaw.
- `feedback_metrics.json`: runtime snapshot of outcome tracking, learned source/keyword adjustments, and cleanup activity.

![Screenshot of Finished Project - job alerts scheduled and coming in on WhatsApp](https://github.com/user-attachments/assets/e19573a1-a861-467b-8fc5-5657afaa1d19)

## 🗂️ Runtime State Files

All persistent state lives in `jobbot_state.sqlite3` (the authoritative store). The JSON files below are **read-only snapshots** written by `pull_jobs.py` after each run for human inspection or optional AI handoff. Deleting any JSON snapshot is safe — it will be regenerated on the next run. The SQLite database should not be deleted unless you want to reset all history.

| File | Purpose | Safe to delete? |
| --- | --- | --- |
| `jobbot_state.sqlite3` | Primary database: matched jobs, review history, alerts, applications, feed state, Telegram sessions. | No — this is the source of truth |
| `matches.json` | Latest-run snapshot of all scored matches above the threshold. Replaced on every run. | Yes |
| `desc.json` | Most recent matched batch staged for OpenClaw review. Replaced on every run. | Yes |
| `seen_jobs_state.json` | Legacy flat-file mirror of reviewed fingerprints. Kept for backwards compatibility; SQLite is authoritative. | Yes |
| `alerts_state.json` | Legacy flat-file mirror of alert queue and delivery history. SQLite is authoritative. | Yes |
| `applications.json` | Legacy flat-file mirror of application records. SQLite is authoritative. | Yes |
| `feed_state.json` | Legacy flat-file mirror of per-feed poll timestamps. SQLite is authoritative. | Yes |
| `daily_digest.json` | Latest daily digest snapshot sent to Telegram. Replaced each digest cycle. | Yes |
| `application_briefs.json` | Application-ready jobs with generated fit notes, resume bullets, and intro drafts. Replaced on each run. | Yes |
| `borderline_matches.json` | Near-threshold jobs for optional AI review. Replaced on each run. | Yes |
| `feedback_metrics.json` | Outcome tracking and learned source/keyword score adjustments. Replaced on each run. | Yes |

## 🧰 Requirements

- A VPS or always-on Linux host.
- OpenClaw only if you want the optional AI review / relay layer.
- Basic familiarity with Linux terminal (no need to be an expert).
- SSH access to your VPS (set up a root password in advance).
- Python 3 installed on the server (automatic if you use the One Click Deploy image - instructions below).
  Python 3.10 or newer is recommended.
- [Git](https://git-scm.com/) installed on local machine.

## 📚 Instructions

Please follow these instructions, and if you get stuck - check out the video tutorial where I demonstrate it step by step.

### 1. Adjust resume.json 📜

Adjust resume.json to your own information. This will give OpenClaw plenty of background about your skills, experience and requirements.

Special fields to update (do not remove! they are used in the python scripts):

- `location` - city, country
- `target_roles`
- `preferences` - remote, hybrid, preferred locations, minimum salary, relocation
- `education`
- `technical_skills` - skills

You can remove or add any other fields, the more context you provide to OpenClaw - the better it can match jobs to you.

### 2. Deploy OpenClaw VPS 🚀

To ensure your AI agent is running 24/7 we must deploy it just like deploying a website.

If our website is running and fully operational even when our computer is off - then so should our OpenClaw agent.

For this, we will deploy a self-hosted OpenClaw instance, running on a virtual private server.

I used Hostinger's **One Click Deploy** Docker image, you can find it here:

<https://www.hostinger.com/phyton>

Use my code **PYTHON** for 10% discount on yearly/bi-yearly plans

### 3. Connect OpenClaw to WhatsApp 📨

In your OpenClaw interface navigate to "Channels" tab and connect your WhatsApp account by scanning the QR code.

Once WhatsApp is connected, try sending a message to yourself (your own phone number) and if OpenClaw replies - everything worked.

### 4. Find the Location of Your OpenClaw Workspace

First, we must find the location of our OpenClaw workspace. For this, send the following prompt:

```text
Save this python file as gregs_test.py: `print("yo yo yo")`
```

And then in your terminal, type (just replace `@72.60.178.132` with the address of your server):

```bash
ssh root@72.60.178.132
find / -name "gregs_test.py"
```

This will show you the exact location of your file - which would be the workspace we're looking for. In my case:

```bash
/docker/<docker_container_name>/data/.openclaw/workspace/gregs_test.py
```

Navigate there with cd:

```bash
cd /docker/<docker_container_name>/data/.openclaw/workspace
```

### 5. Copy Repository Files to VPS 📂

Find the root address of your server (you'll need to set up a password for it first), and follow these instructions:

- clone my repository to your system:

```bash
git clone https://github.com/MariyaSha/job_market_intelligence_bot.git
cd job_market_intelligence_bot
```

- copy files from your local directory into your remote server:

```bash
scp pull_jobs.py pull_desc.py telegram_callback_worker.py exec_loop.sh resume.json .env root@72.60.178.132:/docker/<docker_container_name>/data/.openclaw/workspace/automations/job_finder/
scp -r jobbot root@72.60.178.132:/docker/<docker_container_name>/data/.openclaw/workspace/automations/job_finder/
```

### 6. Run exec_loop.sh ➿

Give yourself permissions to execute the loop. It will keep the Telegram callback worker alive in the background while running the two main Python scripts once every 60 seconds.

We do so using Nohup (No hangup) which ensures the script is running non-stop.

```bash
chmod 700 exec_loop.sh
nohup ./exec_loop.sh > output.log 2>&1 &
```

You can then verify that everything works by looking at the log file that our previous command generated:

```bash
cat output.log
```

![Screenshot of initial output.log output - expected to find several jobs matching your skills](https://github.com/user-attachments/assets/2d2b2261-f5f1-47e6-998d-4b02f1b47657)

As well as verifying that data is being collected properly from both our Python files:

```bash
cat jobs.csv
cat desc.json
```

If both files contain data - everything works great!

### 6.5 Recommended: Direct Telegram Alerts

The repo can now send Telegram alerts directly from Python, which is cheaper and more reliable than using OpenClaw for the hot alert path.

Create a `.env` file from `.env.example` and fill in your bot token and chat ID:

```bash
cp .env.example .env
```

Generated runtime files:

- `jobbot_state.sqlite3` stores the operational runtime state. The JSON and CSV files below remain exported views and snapshots for inspection and compatibility.
- `alerts_state.json` stores which links were already alerted and which alerts are still queued for retry.
- `matches.json` stores the latest scored match batch with reasons and scores.
- `seen_jobs_state.json` stores review fingerprints so already-seen non-matches and cross-source duplicates can be skipped.
- `applications.json` stores the persistent application tracker with statuses like `new`, `reviewed`, `applied`, `rejected`, and `interview`.
- `daily_digest.json` stores the current ranked daily digest snapshot based on score, freshness, and employer priority. When Telegram delivery is enabled, the digest is sent as an interactive paged message with Telegram inline `Prev` / `Next` buttons, and the worker edits the same message in place as users navigate.
- `application_briefs.json` stores the top application-ready jobs with generated "why this fits" notes, resume bullet suggestions, and intro-message drafts.
- `borderline_matches.json` stores near-threshold candidates for optional AI review.
- `feedback_metrics.json` stores outcome summaries, source/keyword performance, recommended score adjustments, and cleanup information.

If `.env` is missing, the bot will still discover matches and queue them in `alerts_state.json`, but it will not send Telegram messages until credentials are present.

### 6.6 Optional: Add Company Career Boards

If you want to go beyond generic RSS feeds, copy `company_boards.json.example` to `company_boards.json` and add the employers you want to monitor.

Supported platforms:

- Greenhouse using the public Job Board API.
- Lever using the public Postings API.
- Ashby using the public Job Postings API.
- Workable using the public account jobs endpoint by default.
- Generic company careers pages using configurable HTML scraping plus JSON-LD job extraction.

The bot will merge those board jobs into the same scoring, dedupe, review-history, and Telegram pipeline as the RSS feeds.

For `generic_html` entries:

- `start_urls` are the careers pages to fetch.
- `allowed_domains` limits which discovered links are followed.
- `job_link_keywords` and `job_link_regexes` help identify job-detail links.
- `max_job_pages` caps how many discovered job pages are fetched per run.

### 6.7 Optional: Add Search Controls, Shortlists, and Digest Settings

If you want more control over which companies are prioritized and how daily review works, copy `job_search_config.json.example` to `job_search_config.json` and edit it.

Supported controls:

- `company_whitelist`: adds a score boost for preferred employers.
- `company_blacklist`: hard-rejects employers you never want to see.
- `priority_companies`: marks high-priority employers as shortlisted and boosts them harder than a normal whitelist.
- `daily_digest`: controls whether a once-per-day digest is sent to Telegram, when it is sent, how many tracked jobs it includes, and how many jobs appear in each Telegram page via `page_size`.
  Inline-button page changes are processed by `telegram_callback_worker.py` using Telegram long polling, so page turns should feel near-instant as long as the worker is running.
- `feedback`: controls how aggressively the bot learns from `applied` / `interview` / `rejected` outcomes and how long old application records are retained.
- `role_profiles`: lets you bias scoring so core IT support and sysadmin roles outrank adjacent engineering roles.

`applications.json` is intended to be editable:

- Change `status` as you move a job from `new` to `reviewed`, `applied`, `rejected`, or `interview`.
- Add your own notes in the `notes` field.
- The bot will observe those status changes and backfill fields like `status_observed_utc`, `applied_at_utc`, `interviewed_at_utc`, and `rejected_at_utc` on later runs.
- Leave the rest of the fields to Python; they will be refreshed automatically as the same job reappears across feeds or boards.

The tailoring layer is now generated in Python:

- `why_this_fits` gives a fast explanation for why the job lines up with your target path.
- `resume_bullet_suggestions` reuses the most relevant existing highlights from your resume for that specific role.
- `intro_message` gives you a short application-ready note you can refine before sending.

The feedback layer is also generated in Python:

- `feedback_keywords` captures the matched role/skill phrases that the bot used when scoring the job.
- `feedback_metrics.json` summarizes which sources and matched keywords are actually leading to interviews or rejections.
- Those metrics are then folded back into scoring so the bot gradually prefers sources and themes that are working for you.
- Old application records are pruned automatically based on the `feedback` retention settings in `job_search_config.json`.

### 6.8 Run the Unit Tests

The repo now includes a stdlib `unittest` suite covering the most regression-prone logic in the `jobbot` package and `pull_desc.py`.

Run the full suite from the repo root:

```bash
python3 -m unittest discover -s tests -v
```

What is covered right now:

- scoring and generated application materials
- blacklist / shortlist behavior
- application-state upserts and dedupe
- feedback learning and stale-record pruning
- end-to-end `pull_jobs.main()` orchestration with temp runtime files
- failed-feed handling that leaves `feed_state.json` unchanged
- generic HTML careers-page parsing
- latest-batch staging in `pull_desc.py`

The current code layout is intentionally split so that:

- `pull_jobs.py` stays small and readable as the runtime entrypoint
- source-specific parsing changes live in `jobbot/sources.py`
- scoring and application-ops changes live in `jobbot/matching.py`
- shared state/config/text helpers live in `jobbot/common.py`

### 7. Manually Set Up Cron Jobs in OpenClaw UI ⏰

OpenClaw is now optional.

If you still want OpenClaw as a secondary relay for `desc.json`, navigate to the "Cron Jobs" tab and set up a manual task named `job_alerts` that runs every 1 minute.

Use the prompt from `openclaw_job_alerts_prompt.txt` as the full task description.

This stricter prompt matters: if you use a vague description, OpenClaw may send status updates like "no new matches" instead of staying silent when there is nothing to alert on.

It relies on the batch `time` already stored in `desc.json`. The OpenClaw prompt does not use `alerts_state.json`; that file is for the direct Python-to-Telegram alert path.

`pull_desc.py` continuously replaces `desc.json` with only the latest matched batch, so slower cron intervals can miss intermediate batches.

If you want to use OpenClaw for higher-value work only, point it at the small generated files instead of the raw feed:

- `borderline_matches.json` for borderline-fit review.
- `application_briefs.json` for resume tailoring, "why this fits" refinement, and message drafting.

That keeps AI usage focused on a small number of high-value jobs instead of spending credits on every feed poll.

### 8. Enjoy! 🙂

Wait for Alerts to Come in Constantly! Good luck on your job search! 🙏
