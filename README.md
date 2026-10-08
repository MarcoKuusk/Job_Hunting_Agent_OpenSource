# Job Hunting Agent

A personal job-search assistant. It:

1. **Searches** remote job boards — RemoteOK, Arbeitnow, Remotive, We Work
   Remotely (free APIs/RSS), plus **LinkedIn and Upwork via Apify actors**.
2. **Scores** each job against your CV and profile using Claude (Anthropic).
3. **Logs** good matches to a Google Sheet, and keeps a **Dashboard** tab there
   (counters, best matches still to review, charts) that updates by itself.
4. **Helps you apply**: pick a job and it writes a tailored cover letter *and* a
   version of your CV rewritten for that posting, both downloadable as Word files.

> **It never applies for you.** The assistant only prepares drafts and, after
> you explicitly type `approve`, opens a job's application page in your browser
> so *you* can review and submit it yourself. It never submits a form or sends
> an email on its own.

---

## The easy way — the web UI

After the one-time setup (Section 1 below), you can do everything from a local
web page instead of the command line. **Just double-click `Start Job Finder.bat`**
in the project folder — it starts the app and opens your browser. (Tip: right-click
it → *Send to → Desktop (create shortcut)* to get a desktop icon. Closing the
black window stops the app.)

Or from a terminal:

```bash
python scripts/run_ui.py
```

It opens `http://127.0.0.1:5000` in your browser — **local only, nothing is
exposed to the internet** — with three tabs:

1. **Profile** — edit your background, skills, keywords, and match threshold; see
   your setup status; save with one button.
2. **Find jobs** — run a search (with a cost estimate) and see the matches from
   your Google Sheet.
3. **Apply** — pick a match and that's it: the cover letter and a CV tailored to
   that job are written straight away, ready to read, edit and download as Word
   files. Then you open the job's page and apply yourself. (It never submits —
   same rule as everywhere else.)

The command-line scripts below do exactly the same things if you prefer them.

---

## Repo layout

```
config/profile.example.yaml   public profile template
config/search.example.yaml    public search template
config/profile.yaml           your private background (gitignored)
config/search.yaml            your private search settings (gitignored)
data/                 put your résumé here (gitignored)
credentials/          Google service-account JSON goes here (gitignored)
output/               generated cover letters / tailored CVs (gitignored)
src/                  all the logic
scripts/              the commands you run:
    run_ui.py             launch the web UI (easiest — see below)
    check_setup.py        verify everything is configured
    run_search.py         run a search
    run_apply_assistant.py prepare an application
webapp/               the local web UI (Flask)
tests/                offline tests (no network/keys needed)
```

---

## Quick start

```bash
# 1. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell/CMD)
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# 2. Set up credentials  ->  see "Section 1" below
copy .env.example .env          # Windows   (cp on macOS/Linux)
#   ...then edit .env with your keys

# 3. Verify everything
python scripts/check_setup.py

# 4. Save your profile in the UI, or copy and edit the templates:
copy config\profile.example.yaml config\profile.yaml
copy config\search.example.yaml config\search.yaml
# macOS/Linux: use cp instead of copy, and / instead of \

# 5. Run a cheap test search
python scripts/run_search.py --dry-run --limit 5

# 6. Run for real
python scripts/run_search.py

# 7. Prepare an application
python scripts/run_apply_assistant.py
```

---

## Section 1 — Credentials & the `.env` file

All secrets live in a file called `.env` in the project root. It is **gitignored**
and must never be committed or shared. Create it by copying the template:

```bash
copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux
```

Then open `.env` in a text editor and fill in each value. Here's what each one
is and where to get it:

### 1a. `ANTHROPIC_API_KEY` (required)
Powers the scoring and the cover-letter drafting.
1. Go to <https://platform.claude.com> and sign in.
2. **API keys → Create key**.
3. Copy the key (starts with `sk-ant-`) and paste it after `ANTHROPIC_API_KEY=`.
> Claude usage costs money per request. Scoring uses the cheap `claude-haiku-4-5`
> model; you can set a `max_jobs_per_source` cap in `config/search.yaml`.

### 1b. Google Sheets — `GOOGLE_SERVICE_ACCOUNT_FILE` + `GOOGLE_SHEET_ID` (required)
Matches are written to a Google Sheet via a "service account" (a robot Google
account).
1. Create a sheet at <https://sheets.google.com> — name it anything. Copy its ID
   from the URL: `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`.
   Paste it after `GOOGLE_SHEET_ID=`.
2. Go to <https://console.cloud.google.com> → create (or pick) a project.
3. **APIs & Services → Library** → enable **Google Sheets API** *and*
   **Google Drive API**.
4. **APIs & Services → Credentials → Create credentials → Service account.**
   Give it a name and create it.
5. Open the service account → **Keys → Add key → Create new key → JSON**.
   A `.json` file downloads.
6. Move that file into the `credentials/` folder. Point `.env` at it:
   `GOOGLE_SERVICE_ACCOUNT_FILE=credentials/your-file.json`.
7. **Crucial:** open the JSON and copy the `client_email` value (looks like
   `…@….iam.gserviceaccount.com`). Back in your Google Sheet, click **Share**
   and share it with that email as **Editor**. (Otherwise you'll get a
   permission error.)

### 1c. `APIFY_API_TOKEN` (for LinkedIn + Upwork)
1. Sign up at <https://console.apify.com>.
2. **Settings → Integrations → API token** (or **API & Integrations**). Copy it.
3. Paste after `APIFY_API_TOKEN=`.
> You also pick the actors and set their IDs in `config/search.yaml` — that's
> Step 5 below. LinkedIn/Upwork stay off until you do.

### 1d. Telegram — `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
Sends you a summary after each run.
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts. It gives a
   token like `123456789:AA...`. Paste after `TELEGRAM_BOT_TOKEN=`.
2. Message **@userinfobot** in Telegram; it replies with your numeric **Id**.
   Paste after `TELEGRAM_CHAT_ID=`.
3. Send your new bot any message once (so it's allowed to message you back).

When you've filled everything in, run `python scripts/check_setup.py` — it
verifies each credential and tells you exactly what (if anything) is wrong,
without ever printing your secrets.

---

## Section 2 — Your profile and search settings

- **`config/profile.yaml`** — who you are: name, summary, target roles, skills,
  requirements, things to avoid, and the path to your résumé. Drop your résumé
  (PDF, DOCX, or TXT) into `data/` and set `cv_path` to point at it.
- **`config/search.yaml`** — which sources are on, your keywords, the minimum
  score to log a job (`min_score`), the models, and the Apify settings.

Personal settings files are gitignored. A fresh checkout reads the blank profile
and generic search defaults from `config/*.example.yaml`; saving Settings in
the UI creates the private files automatically. For command-line setup, copy
the examples to `config/profile.yaml` and `config/search.yaml` and edit them.
Set your target roles, keywords, locations and resume before running a search.
Paid Apify sources and Telegram are disabled until you configure them.

---

## Section 3 — Running a search

```bash
python scripts/run_search.py --dry-run --limit 5   # cheap test, writes nothing
python scripts/run_search.py --no-score            # just fetch & count, no Claude
python scripts/run_search.py                        # full run, logs to your sheet
```

Each run fetches jobs, filters by your keywords, drops jobs seen on previous
runs (remembered in `data/seen.json`), scores the rest with Claude, and writes
jobs scoring at/above `min_score` to your sheet.

---

## Section 4 — Preparing an application (human-approved)

```bash
python scripts/run_apply_assistant.py
```

It lists logged jobs, lets you pick one, writes a cover letter, a tailored CV,
and a short "what I changed" note into `output/` (Markdown plus Word), and
**only after you type `approve`** opens the job's application page in your
browser. It never submits anything for you.

---

## Section 5 — LinkedIn / Upwork via Apify

1. On <https://apify.com>, find a LinkedIn-jobs actor and an Upwork actor (the
   "Store"). Note each actor's ID (`username/actor-name`).
2. In `config/search.yaml`, set `apify.linkedin_actor` / `apify.upwork_actor`
   and flip `sources.linkedin` / `sources.upwork` to `true`.
3. Open each actor's **Input** tab on Apify and compare the field names to
   `build_input()` in `src/sources/apify_source.py`. Adjust the keys there so
   they match your actor exactly. The output normalizer already handles many
   field-name variants.

---

## Section 6 — Run it daily (optional)

**Windows Task Scheduler:** create a Basic Task → Daily → *Start a program*:
- Program: the full path to `.venv\Scripts\python.exe`
- Arguments: `scripts\run_search.py`
- Start in: the project folder

**macOS/Linux cron** (example, 8am daily):
```
0 8 * * * cd /path/to/Job_Hunting_Agent && .venv/bin/python scripts/run_search.py
```

---

## Safety notes

- `.env`, personal config files, `credentials/`, your résumé, and `output/` are all gitignored.
  `check_setup.py` and the search never print secret values.
- The apply assistant always requires a typed `approve` and never submits an
  application or sends a message on your behalf.
- LinkedIn and Upwork are accessed **only** through Apify actors — there is no
  logged-in scraping or browser automation against those sites.

## Contributing and privacy

See CONTRIBUTING.md and SECURITY.md. Run `python scripts/check_public_release.py`
before committing. The release repository starts with fresh history; no private
configuration, resumes, generated output, or original Git metadata is included.

## License

MIT; see LICENSE.
