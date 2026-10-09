# Job Hunting Agent

Job Hunting Agent finds remote jobs, scores how well they match you, saves
them on your computer, optionally syncs them to Google Sheets, and prepares a
cover letter and tailored CV when you pick a job.

It runs on your own computer. It never submits an application or sends a
message for you. You review everything and apply yourself.

## What you need

- A Windows, macOS, or Linux computer with internet access.
- [Python 3.11 or newer](https://www.python.org/downloads/).
- An [Anthropic API key](https://platform.claude.com/settings/keys) for scoring
  jobs and writing application documents.

Anthropic charges for API use. The four built-in public job boards are free.
LinkedIn and Upwork are optional and use paid Apify actors. The app shows which
sources cost money before you enable them.

## Easiest setup on Windows

1. On this GitHub page, select **Code → Download ZIP**.
2. Open the downloaded ZIP and select **Extract all**. Do not run the app from
   inside the ZIP.
3. Install [Python](https://www.python.org/downloads/) if needed. During the
   Windows installer, tick **Add python.exe to PATH**.
4. In the extracted folder, double-click **Start Job Finder.bat**.
5. Leave the black window open. The first start creates a private Python
   environment and installs the required packages, so it can take a few
   minutes. Your browser opens automatically when it is ready.
6. Open **Settings** and complete the four numbered steps:
   - save your Anthropic API key;
   - fill in your profile and upload your CV;
   - add search keywords and choose job boards;
   - optionally connect Google Sheets, Apify, or Telegram.
7. Select **Test live connections**. When Claude is green, open **Jobs** and
   select **Find jobs now**. Results are saved on your computer automatically.

After the first setup, start the app by double-clicking **Start Job Finder.bat**.
The launcher checks for dependency updates automatically and never overwrites
your keys, profile, CV, or results.

> Windows may show a security warning for a downloaded `.bat` file. Only run a
> copy downloaded from this repository. Select **More info → Run anyway** if
> Windows SmartScreen appears.

## macOS and Linux

Download and extract the ZIP, or clone the repository, then open a terminal in
its folder and run:

```bash
chmod +x start-job-finder.sh
./start-job-finder.sh
```

The script creates `.venv`, installs dependencies, creates private local config
files, starts the app, and opens `http://127.0.0.1:5000`.

To clone instead of downloading the ZIP:

```bash
git clone https://github.com/MarcoKuusk/Job_Hunting_Agent_OpenSource.git
cd Job_Hunting_Agent_OpenSource
./start-job-finder.sh
```

## Optional: connect Google Sheets

Job Finder works without Google: results appear in the local Jobs page.
Connect Google only if you also want a spreadsheet dashboard. The same
checklist appears in Settings.

1. Create a spreadsheet at [Google Sheets](https://sheets.google.com/). Copy the
   text between `/d/` and `/edit` in its URL; that is the **Sheet ID**.
2. Open [Google Cloud Console](https://console.cloud.google.com/), create or
   select a project, and enable both **Google Sheets API** and **Google Drive
   API**.
3. Open **APIs & Services → Credentials → Create credentials → Service
   account** and create the account.
4. Open that service account, then select **Keys → Add key → Create new key →
   JSON**. Google downloads a JSON file.
5. In Job Finder Settings, choose **Choose Google JSON file…** and select the
   downloaded file.
6. Job Finder displays the service-account email. Return to your spreadsheet,
   select **Share**, add that email, and grant **Editor** access.
7. Paste the Sheet ID into Job Finder and select **Save connection details**.
8. Select **Test live connections**. A 403 error almost always means the Sheet
   was not shared with the service-account email as Editor.

The JSON file is copied to the ignored `credentials/` folder. Never publish or
send that file to anyone. You can skip this whole section and use local storage.

## Everyday use

1. Double-click **Start Job Finder.bat** on Windows, or run
   `./start-job-finder.sh` on macOS/Linux.
2. On **Jobs**, select **Find jobs now**.
3. Filter the results and choose a job. Job Finder prepares a cover letter and
   tailored CV for you to review and download.
4. Select **Open application page** only when you are ready. Job Finder opens
   the employer's page but never fills or submits it.
5. Close the black terminal window when finished; that stops the local app.

A **Practice run** avoids saving results, but it can still call enabled paid
services. To minimize cost, set a small job limit or use only the free boards.

## Optional LinkedIn, Upwork, and Telegram

The LinkedIn integration has been tested with Apify's
[LinkedIn Jobs Scraper](https://apify.com/cheap_scraper/linkedin-job-scraper)
(`cheap_scraper/linkedin-job-scraper`). It is a community-maintained paid actor,
so review its current pricing before enabling LinkedIn. Add your Apify token in
Settings, then enable LinkedIn under **Where to search**.

For Upwork, select a compatible actor from the
[Apify Store](https://apify.com/store), put its `username/actor-name` ID in
`config/search.yaml`, and enable Upwork. Different actors may require changes
to `build_input()` in `src/sources/apify_source.py`.

Telegram notifications are optional. Create a bot with **@BotFather**, get your
chat ID from **@userinfobot**, enter both values in Settings, and set
`telegram.enabled: true` in `config/search.yaml`.

## Where your data goes

- Keys and IDs are stored locally in the ignored `.env` file. The Settings page
  only reports whether each value is saved; it never sends saved values back to
  the browser.
- Your profile is stored in ignored files under `config/`.
- Your CV and generated documents stay in the ignored `data/` and `output/`
  folders.
- Scoring and drafting send the relevant profile, CV, and job text to Anthropic.
- Enabled searches contact their job boards and, when selected, Apify.
- Job matches are saved locally. If configured, they are also synced to your Google Sheet.
- The web app binds only to `127.0.0.1`; it is not exposed to your network or
  the internet.

See [SECURITY.md](SECURITY.md) for more detail.

## Troubleshooting

### The black window says Python is missing or too old

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/).
On Windows, tick **Add python.exe to PATH**, finish the installer, close the old
black window, and double-click the launcher again.

### Package installation fails

Check your internet connection and run the launcher again. It safely resumes
setup. On a work-managed computer, application-control or proxy rules may block
Python packages; copy the complete error from the black window for your system
administrator.

### The browser does not open

Keep the black window open and visit <http://127.0.0.1:5000> manually. If it
still does not load, close every Job Finder window, wait a few seconds, and
start it again.

### Google returns 403 or “permission denied”

Open the service-account JSON or upload it again to see its email, then share
your spreadsheet with that exact email as **Editor**. Confirm that the Google
Sheets and Google Drive APIs are enabled in the same Cloud project.

### No jobs appear

In Settings, add at least one broad keyword, save, and confirm at least one free
source is enabled. Try a small search with RemoteOK, Arbeitnow, Remotive, and We
Work Remotely before enabling paid sources.

### Claude reports that a model is unavailable

Your Anthropic account may not have access to the configured model. Change
`scoring.scoring_model` and `documents.drafting_model` in
`config/search.yaml` to model IDs available to your account, then restart the
app.

### Start over without deleting personal data

Close Job Finder and delete only the `.venv` folder. The next launch rebuilds
it. Do not delete `.env`, `config/profile.yaml`, `config/search.yaml`, `data/`,
`credentials/`, or `output/` unless you intentionally want to remove that data.

## Advanced manual setup

The one-click launcher is recommended. For a manual installation:

```bash
git clone https://github.com/MarcoKuusk/Job_Hunting_Agent_OpenSource.git
cd Job_Hunting_Agent_OpenSource
python -m venv .venv
```

Activate the environment with the command for your shell:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bat
:: Windows Command Prompt
.venv\Scripts\activate.bat
```

```bash
# macOS/Linux
source .venv/bin/activate
```

Then run:

```bash
pip install -r requirements.txt
python scripts/bootstrap.py
python scripts/run_ui.py
```

The command-line tools use the same configuration:

```bash
python scripts/check_setup.py
python scripts/run_search.py --no-score
python scripts/run_search.py --dry-run --limit 5
python scripts/run_search.py
python scripts/run_apply_assistant.py
```

`--no-score` skips Claude scoring. `--dry-run` prevents writes but does not
prevent API charges. `--limit 5` restricts scoring to five new jobs.

## Project layout

```text
Start Job Finder.bat       one-click Windows setup and launcher
start-job-finder.sh        one-command macOS/Linux setup and launcher
config/*.example.yaml      public configuration templates
config/*.yaml              your private settings (gitignored)
credentials/               Google service-account JSON (gitignored)
data/                      your CV and local job cache (gitignored)
output/                    generated application documents (gitignored)
scripts/bootstrap.py       dependency and first-run setup
scripts/check_setup.py     detailed connection checks
src/                       search, scoring, storage, and document logic
webapp/                    local browser interface
tests/                     offline tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before committing, run:

```bash
python scripts/check_public_release.py
python -m unittest discover -s tests
```

## License

MIT; see [LICENSE](LICENSE).
