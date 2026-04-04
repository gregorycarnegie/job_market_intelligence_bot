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
- `pull_jobs.py`: fetches listings from several RSS jobs feeds (meant for computer reading), filters them based on location and skills from `resume.json` and stores selected listings in `jobs.csv` (a file that's being generated in the first run, and **updated continuously** - storing the **entire history of listings**, old and new)
- `pull_desc.py`: fetches listings **only** from the most recent timestamp of `jobs.csv`, stores them in `desc.json` (a file that's being generated in the first run, and **replaced continuously** - always storing **the most recent listings** and disposing of the rest). `desc.json` is the only file that OpenClaw is exposed to.
- `exec_loop.sh`: a bash script that runs both Python files, one after the other, every 60 seconds. Meant to run with Nohup on the system level of the VPS (see instructions below).

<br>
<img width="1920" alt="Screenshot of Finished Project - job alerts scheduled and coming in on WhatsApp" src="https://github.com/user-attachments/assets/e19573a1-a861-467b-8fc5-5657afaa1d19" />
<br>
<br>

## 🧰 Requirements

- A self-hosted OpenClaw instance (running on VPS so it works even if you're computer is off).
- Basic familiarity with Linux terminal (no need to be an expert).
- SSH access to your VPS (set up a root password in advance).
- Python 3 installed on the server (automatic if you use the One Click Deploy image - instructions below).
- <a href="https://git-scm.com/">Git</a> installed on local machine.

## 📚 Instructions

Please follow these instructions, and if you get stuck - check out the video tutorial where I demonstrate it step by step.

### 1. Adjust resume.json 📜

Adjust resume.json to your own information. This will give OpenClaw plenty of background about your skills, experience and requirements.
<br>
Special fields to update (do not remove! they are used in the python scripts):

- `location` - city, country
- `target_roles`
- `preferences` - remote, hybrid, minimum_salary_usd, relocation
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
scp pull_jobs.py pull_desc.py exec_loop.sh resume.json root@72.60.178.132:/docker/openclaw-cevb/data/.openclaw/workspace/
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

If both files contain data - everything works great! and we can move on with the final instruction to OpenClaw.

### 7. Manually Set Up Cron Jobs in OpenClaw UI ⏰

Back in OpenClaw, navigate to the "Cron Jobs" tab and set up a manual task named: "job_alerts" that runs every 5 minutes (or any other interval you’d like)
<br>
Use the prompt from `openclaw_job_alerts_prompt.txt` as the full task description.
<br>
This stricter prompt matters: if you use a vague description, OpenClaw may send status updates like "no new matches" instead of staying silent when there is nothing to alert on.
<br>
It relies on the batch `time` already stored in `desc.json`; there is no separate alert-state file created by the Python scripts in this repository.

### 8. Enjoy! 🙂

Wait for Alerts to Come in Constantly! Good luck on your job search! 🙏
