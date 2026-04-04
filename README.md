# job_market_intelligence_bot

Automated Search for Job Listings in RSS Feeds with self-hosted OpenClaw running on VPS. Offloading all the heavy complex logic to Python (running on OS, without wasting OpenClaw credits) and sharing bare minimum information with OpenClaw, only what's absolutely necessary for its decision making process.

## 📽️ Step By Step OpenClaw Video Tutorial

<a href="https://youtu.be/ehfTs0wdW5g">
<img width="600px" src="https://github.com/user-attachments/assets/e1322230-b694-4b4c-a2cf-f2b5abc383d4">
</a>
<br>
Watch Full Video Here: https://youtu.be/ehfTs0wdW5g

## 👀 Overview

This repository contains several files, part of the job market intelligence mechanism:

- `resume.json`: stores skills, preferences, and experience information that the Python scripts and OpenClaw rely on.
  OpenClaw will read the entire file once, while `pull_jobs.py` will pull special fields from this file in every execution (once every 60 seconds).
  OpenClaw will use AI credits to read the file and store it in memory, Python file will not use AI credits as it runs on the system level with Bash.
- `pull_jobs.py`: fetches listings from several RSS jobs feeds (meant for computer reading), scores them against `resume.json`, stores matched listings in `jobs.csv`, writes the latest scored batch to `matches.json`, keeps delivery state in `alerts_state.json`, and can send Telegram alerts directly without OpenClaw.
- `pull_desc.py`: fetches listings **only** from the most recent timestamp of `jobs.csv`, stores them in `desc.json` (a file that's being generated in the first run, and **replaced continuously** - always storing **the most recent listings** and disposing of the rest). `desc.json` is the only file that OpenClaw is exposed to.
- `exec_loop.sh`: a bash script that runs both Python files, one after the other, every 60 seconds. Meant to run with Nohup on the system level of the VPS (see instructions below).
- `.env.example`: a template for optional direct Telegram delivery using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- `company_boards.json.example`: optional company-board config for Greenhouse, Lever, Ashby, and Workable sources.
- `job_search_config.json.example`: optional search-operations config for company whitelist / blacklist, shortlist employers, daily digest settings, and role-profile weights.
- `seen_jobs_state.json`: runtime state that remembers already reviewed items, including non-matches, so the same old feed entries are not rescored on every loop.
- `application_briefs.json`: runtime snapshot of application-ready jobs with generated fit notes, resume bullet suggestions, and intro-message drafts.
- `borderline_matches.json`: runtime snapshot of near-threshold jobs that are worth optional AI review instead of sending the entire feed to OpenClaw.
- `feedback_metrics.json`: runtime snapshot of outcome tracking, learned source/keyword adjustments, and cleanup activity.

<br>
<img width="1920" alt="Screenshot of Finished Project - job alerts scheduled and coming in on WhatsApp" src="https://github.com/user-attachments/assets/e19573a1-a861-467b-8fc5-5657afaa1d19" />
<br>
<br>

## 🧰 Requirements

- A VPS or always-on Linux host.
- OpenClaw only if you want the optional AI review / relay layer.
- Basic familiarity with Linux terminal (no need to be an expert).
- SSH access to your VPS (set up a root password in advance).
- Python 3 installed on the server (automatic if you use the One Click Deploy image - instructions below).
  Python 3.10 or newer is recommended.
- <a href="https://git-scm.com/">Git</a> installed on local machine.

## 📚 Instructions

Please follow these instructions, and if you get stuck - check out the video tutorial where I demonstrate it step by step.

### 1. Adjust resume.json 📜

Adjust resume.json to your own information. This will give OpenClaw plenty of background about your skills, experience and requirements.
<br>
Special fields to update (do not remove! they are used in the python scripts):

- `location` - city, country
- `target_roles`
- `preferences` - remote, hybrid, preferred locations, minimum salary, relocation
- `education`
- `technical_skills` - skills
<br>

You can remove or add any other fields, the more context you provide to OpenClaw - the better it can match jobs to you.

### 2. Deploy OpenClaw VPS 🚀

To ensure your AI agent is running 24/7 we must deploy it just like deploying a website.
<br>
If our website is running and fully operational even when our computer is off - then so should our OpenClaw agent.
<br>
For this, we will deploy a self-hosted OpenClaw instance, running on a virtual private server.
<br>
I used Hostinger's **One Click Deploy** Docker image, you can find it here:
<br>
<https://www.hostinger.com/phyton>
<br>
Use my code **PYTHON** for 10% discount on yearly/bi-yearly plans

### 3. Connect OpenClaw to WhatsApp 📨

In your OpenClaw interface navigate to "Channels" tab and connect your WhatsApp account by scanning the QR code.
<br>
Once WhatsApp is connected, try sending a message to yourself (your own phone number) and if OpenClaw replies - everything worked.

### 4. Find the Location of Your OpenClaw Workspace

First, we must find the location of our OpenClaw workspace. For this, send the following prompt:

```text
Save this python file as mariyas_test.py: `print("yo yo yo")`
```

And then in your terminal, type (just replace `@72.60.178.132` with the address of your server):

```bash
ssh root@72.60.178.132
find / -name "mariyas_test.py"
```

This will show you the exact location of your file - which would be the workspace we're looking for. In my case:

```bash
/docker/openclaw-laek/data/.openclaw/workspace/mariyas_test.py
```

Navigate there with cd:

```bash
cd /docker/openclaw-laek/data/.openclaw/workspace
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
scp pull_jobs.py pull_desc.py exec_loop.sh resume.json .env.example company_boards.json.example job_search_config.json.example root@72.60.178.132:/docker/openclaw-cevb/data/.openclaw/workspace/
```

### 6. Run exec_loop.sh ➿

Give yourself permissions to execute the loop (running both python scripts on the OS of your container once in every 60 seconds)
<br>
We do so using Nohup (No hangup) which ensures the script is running non-stop.

```bash
chmod 700 exec_loop.sh
nohup ./exec_loop.sh > output.log 2>&1 &
```

You can then verify that everything works by looking at the log file that our previous command generated:

```bash
cat output.log
```

<br>
<img width="1920" alt="Screenshot of initial output.log output - expected to find several jobs matching your skills" src="https://github.com/user-attachments/assets/2d2b2261-f5f1-47e6-998d-4b02f1b47657" />
<br>
<br>
As well as verifying that data is being collected properly from both our Python files:
```
cat jobs.csv
cat desc.json
```

If both files contain data - everything works great!

### 6.5 Recommended: Direct Telegram Alerts

The repo can now send Telegram alerts directly from Python, which is cheaper and more reliable than using OpenClaw for the hot alert path.
<br>
Create a `.env` file from `.env.example` and fill in your bot token and chat ID:

```bash
cp .env.example .env
```

Generated runtime files:

- `alerts_state.json` stores which links were already alerted and which alerts are still queued for retry.
- `matches.json` stores the latest scored match batch with reasons and scores.
- `seen_jobs_state.json` stores review fingerprints so already-seen non-matches and cross-source duplicates can be skipped.
- `applications.json` stores the persistent application tracker with statuses like `new`, `reviewed`, `applied`, `rejected`, and `interview`.
- `daily_digest.json` stores the current ranked daily digest snapshot based on score, freshness, and employer priority.
- `application_briefs.json` stores the top application-ready jobs with generated “why this fits” notes, resume bullet suggestions, and intro-message drafts.
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
- `daily_digest`: controls whether a once-per-day digest is sent to Telegram, when it is sent, and how many tracked jobs it includes.
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

The repo now includes a stdlib `unittest` suite covering the most regression-prone logic in `pull_jobs.py` and `pull_desc.py`.

Run the full suite from the repo root:

```bash
python3 -m unittest discover -s tests -v
```

What is covered right now:

- scoring and generated application materials
- blacklist / shortlist behavior
- application-state upserts and dedupe
- feedback learning and stale-record pruning
- generic HTML careers-page parsing
- latest-batch staging in `pull_desc.py`

### 7. Manually Set Up Cron Jobs in OpenClaw UI ⏰

OpenClaw is now optional.
<br>
If you still want OpenClaw as a secondary relay or AI review layer, navigate to the "Cron Jobs" tab and set up a manual task named: "job_alerts" that runs every 5 minutes (or any other interval you’d like)
<br>
Use the prompt from `openclaw_job_alerts_prompt.txt` as the full task description.
<br>
This stricter prompt matters: if you use a vague description, OpenClaw may send status updates like "no new matches" instead of staying silent when there is nothing to alert on.
<br>
It relies on the batch `time` already stored in `desc.json`. The OpenClaw prompt does not use `alerts_state.json`; that file is for the direct Python-to-Telegram alert path.

If you want to use OpenClaw for higher-value work only, point it at the small generated files instead of the raw feed:

- `borderline_matches.json` for borderline-fit review.
- `application_briefs.json` for resume tailoring, “why this fits” refinement, and message drafting.

That keeps AI usage focused on a small number of high-value jobs instead of spending credits on every feed poll.

### 8. Enjoy! 🙂

Wait for Alerts to Come in Constantly! Good luck on your job search! 🙏
