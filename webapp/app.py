"""Flask backend for the Job Hunting Agent's local web UI.

Local-only (binds to 127.0.0.1) — nothing is exposed to the internet. Every
route reuses the existing src/ modules, so the UI and the CLI behave identically.

SAFETY: The "Apply" flow only DRAFTS documents and OPENS the job's page in the
browser. It never submits a form or sends an email — same guarantee as the CLI
apply assistant. Do not add an auto-submit route.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

# Make the project root importable whether launched via run_ui.py or directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from flask import Flask, jsonify, render_template, request, send_file
from flask.json.provider import DefaultJSONProvider

from src.config import PROJECT_ROOT, load_config, scrub
from src.models import Job

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB cap on CV uploads


class _BrowserSafeJSON(DefaultJSONProvider):
    """Emit JSON a browser will actually accept.

    Python writes bare NaN/Infinity tokens for non-finite floats and reads
    them back happily, but JSON.parse rejects the entire document. One such
    value (a company named "Infinity", say) would otherwise blank out the
    whole matches list. See src/jsonsafe.py.
    """

    def dumps(self, obj, **kwargs):
        from src.jsonsafe import finite_only

        return super().dumps(finite_only(obj), **kwargs)


app.json = _BrowserSafeJSON(app)

PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
SEARCH_PATH = PROJECT_ROOT / "config" / "search.yaml"
ENV_PATH = PROJECT_ROOT / ".env"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
CV_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
CONNECTION_FIELDS = {
    "anthropic_key": "ANTHROPIC_API_KEY",
    "google_sheet_id": "GOOGLE_SHEET_ID",
    "apify_token": "APIFY_API_TOKEN",
    "telegram_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
}

# Shared state for the background search run (single-user local app).
SEARCH_STATE: dict = {"running": False, "log": [], "result": None, "error": None}
SEARCH_LOCK = threading.Lock()

# Drafting starts by itself the moment a job is picked, so the same job can
# easily be opened twice in one sitting. Remember what we wrote (per job URL,
# for this session only) and hand the same documents back instead of paying
# Claude to write them again. "Write them again" in the UI forces a rewrite.
DRAFT_CACHE: dict[str, dict] = {}
DRAFT_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _load_yaml(path: Path) -> dict:
    from src.config import _load_yaml as load_settings
    return load_settings(path)


def _save_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True,
                       default_flow_style=False)


def _lines_to_list(text) -> list[str]:
    """Turn a textarea value (one item per line) into a clean list."""
    if isinstance(text, list):
        return [str(t).strip() for t in text if str(t).strip()]
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]

def _save_env_values(values: dict[str, str], clear: set[str] | None = None) -> None:
    """Update selected .env values without ever returning or printing them."""
    clear = clear or set()
    allowed = set(CONNECTION_FIELDS.values()) | {"GOOGLE_SERVICE_ACCOUNT_FILE"}
    updates = {key: str(value).strip() for key, value in values.items() if key in allowed}
    for key, value in updates.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} cannot contain a line break")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    found: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in clear:
            output.append(f"{key}=")
            found.add(key)
        elif key in updates and updates[key]:
            output.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if value and key not in found:
            output.append(f"{key}={value}")
    for key in clear - found:
        if key in allowed:
            output.append(f"{key}=")

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=ENV_PATH.parent,
        prefix=".env.", suffix=".tmp", delete=False,
    ) as handle:
        handle.write("\n".join(output).rstrip() + "\n")
        temporary = Path(handle.name)
    temporary.replace(ENV_PATH)
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    for key, value in updates.items():
        if value:
            os.environ[key] = value
    for key in clear:
        os.environ.pop(key, None)


def _connection_status() -> dict:
    cfg = load_config()
    credentials_exist = cfg.google_service_account_path.exists()
    service_email = ""
    if credentials_exist:
        try:
            service_email = str(json.loads(
                cfg.google_service_account_path.read_text(encoding="utf-8")
            ).get("client_email", ""))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    return {
        "anthropic_key": bool(cfg.anthropic_key),
        "google_sheet_id": bool(cfg.google_sheet_id),
        "google_credentials": credentials_exist,
        "google_credentials_name": cfg.google_service_account_path.name if credentials_exist else "",
        "google_service_email": service_email,
        "apify_token": bool(cfg.apify_token),
        "telegram_token": bool(cfg.telegram_token),
        "telegram_chat_id": bool(cfg.telegram_chat_id),
    }

# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# What this backend can do. The page checks this on load: templates and static
# files are read from disk on every request, so a browser can easily end up
# running today's page against a server process started before the code
# changed. Without this check that mismatch shows up as inexplicable errors.
API_FEATURES = ["auto-draft", "tailored-cv", "downloads", "dashboard",
                "dashboard-v2", "guided-setup"]


@app.route("/api/version", methods=["GET"])
def version():
    import os
    return jsonify({"ok": True, "features": API_FEATURES, "pid": os.getpid()})


@app.before_request
def _reject_cross_site_mutations():
    """Do not let an unrelated website change this localhost-only app."""
    if request.method in {"GET", "HEAD", "OPTIONS"} or not request.path.startswith("/api/"):
        return None
    origin = request.headers.get("Origin")
    if not origin:
        return None
    parsed = urlsplit(origin)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return jsonify({"ok": False, "error": "Cross-site request blocked."}), 403
    return None


@app.after_request
def _no_store(response):
    """Never let a browser reuse an API answer. These are live views of a
    spreadsheet and of a background run, and a cached copy is always wrong."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

# --------------------------------------------------------------------------
# Guided connection setup. Secret values are accepted but never returned.
# The server is bound to localhost by scripts/run_ui.py.
# --------------------------------------------------------------------------
@app.route("/api/connections", methods=["GET"])
def get_connections():
    return jsonify({"ok": True, "configured": _connection_status()})


@app.route("/api/connections", methods=["POST"])
def save_connections():
    try:
        data = request.get_json(force=True) or {}
        updates = {}
        for field, env_name in CONNECTION_FIELDS.items():
            value = str(data.get(field, "") or "").strip()
            if value:
                updates[env_name] = value
        clear_fields = data.get("clear") or []
        clear = {CONNECTION_FIELDS[field] for field in clear_fields
                 if field in CONNECTION_FIELDS}
        _save_env_values(updates, clear)
        return jsonify({"ok": True, "configured": _connection_status()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


@app.route("/api/upload-google-credentials", methods=["POST"])
def upload_google_credentials():
    try:
        uploaded = request.files.get("credentials")
        if uploaded is None or not uploaded.filename:
            return jsonify({"ok": False,
                            "error": "Choose the JSON file downloaded from Google Cloud."}), 400
        raw = uploaded.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return jsonify({"ok": False,
                            "error": "The credential file is unexpectedly large."}), 400
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return jsonify({"ok": False, "error": "That is not a valid JSON file."}), 400
        required = ("type", "project_id", "private_key", "client_email")
        if payload.get("type") != "service_account" or any(not payload.get(k) for k in required):
            return jsonify({"ok": False, "error":
                "This is not a Google service-account JSON file. Download a JSON key for a service account."}), 400

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        destination = CREDENTIALS_DIR / "service_account.json"
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        _save_env_values({"GOOGLE_SERVICE_ACCOUNT_FILE":
                          destination.relative_to(PROJECT_ROOT).as_posix()})
        return jsonify({"ok": True, "filename": destination.name,
                        "configured": _connection_status()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400

# --------------------------------------------------------------------------
# Profile + search settings
# --------------------------------------------------------------------------
@app.route("/api/profile", methods=["GET"])
def get_profile():
    profile = _load_yaml(PROFILE_PATH)
    search = _load_yaml(SEARCH_PATH)
    req = profile.get("requirements", {}) or {}
    scoring = search.get("scoring", {}) or {}
    cv_value = str(profile.get("cv_path", "") or "").strip()
    cv_file = Path(cv_value) if cv_value else None
    if cv_file is not None and not cv_file.is_absolute():
        cv_file = PROJECT_ROOT / cv_file
    visible_cv_path = cv_value if cv_file is not None and cv_file.is_file() else ""
    return jsonify({
        "name": profile.get("name", ""),
        "location": profile.get("location", ""),
        "summary": profile.get("summary", ""),
        "target_roles": profile.get("target_roles", []),
        "skills": profile.get("skills", []),
        "avoid": profile.get("avoid", []),
        "remote_only": bool(req.get("remote_only", True)),
        "min_salary": req.get("min_salary", ""),
        "locations_allowed": req.get("locations_allowed", []),
        "cv_path": visible_cv_path,
        "keywords": search.get("keywords", []),
        "min_score": scoring.get("min_score", 70),
        "sources": search.get("sources", {}),
        "search_terms": (search.get("apify", {}) or {}).get("search_terms", []),
    })


@app.route("/api/profile", methods=["POST"])
def save_profile():
    try:
        data = request.get_json(force=True) or {}
        profile = _load_yaml(PROFILE_PATH)
        search = _load_yaml(SEARCH_PATH)

        # Profile fields
        profile["name"] = str(data.get("name", "")).strip()
        profile["location"] = str(data.get("location", "")).strip()
        profile["summary"] = str(data.get("summary", "")).strip()
        profile["target_roles"] = _lines_to_list(data.get("target_roles"))
        profile["skills"] = _lines_to_list(data.get("skills"))
        profile["avoid"] = _lines_to_list(data.get("avoid"))
        req = profile.get("requirements", {}) or {}
        req["remote_only"] = bool(data.get("remote_only", True))
        req["min_salary"] = str(data.get("min_salary", "")).strip()
        req["locations_allowed"] = _lines_to_list(data.get("locations_allowed"))
        profile["requirements"] = req
        if data.get("cv_path"):
            profile["cv_path"] = str(data["cv_path"]).strip()

        # Search settings
        search["keywords"] = _lines_to_list(data.get("keywords"))
        scoring = search.get("scoring", {}) or {}
        try:
            scoring["min_score"] = int(data.get("min_score", 70))
        except (TypeError, ValueError):
            scoring["min_score"] = 70
        search["scoring"] = scoring
        apify = search.get("apify", {}) or {}
        if data.get("search_terms") is not None:
            apify["search_terms"] = _lines_to_list(data.get("search_terms"))
        search["apify"] = apify
        # Source toggles
        sources = search.get("sources", {}) or {}
        for key, val in (data.get("sources") or {}).items():
            sources[key] = bool(val)
        search["sources"] = sources

        _save_yaml(PROFILE_PATH, profile)
        _save_yaml(SEARCH_PATH, search)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


# --------------------------------------------------------------------------
# CV upload — save the file into data/ and point the profile at it, so the
# user never has to type a file path. Only writes into data/ (git-ignored).
# --------------------------------------------------------------------------
@app.route("/api/upload-cv", methods=["POST"])
def upload_cv():
    try:
        from werkzeug.utils import secure_filename

        file = request.files.get("cv")
        if file is None or not file.filename:
            return jsonify({"ok": False, "error": "No file was selected."}), 400

        name = secure_filename(file.filename)
        ext = Path(name).suffix.lower()
        if ext not in CV_EXTENSIONS:
            return jsonify({"ok": False, "error":
                "Please upload a PDF, Word (.docx), or text (.txt/.md) file."}), 400

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = DATA_DIR / name
        file.save(str(dest))

        # Point the profile at the new CV (relative path, forward slashes).
        rel = dest.relative_to(PROJECT_ROOT).as_posix()
        profile = _load_yaml(PROFILE_PATH)
        profile["cv_path"] = rel
        _save_yaml(PROFILE_PATH, profile)

        return jsonify({"ok": True, "filename": name, "cv_path": rel})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


# --------------------------------------------------------------------------
# Setup status (fast presence checks) + live connection test
# --------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def status():
    cfg = load_config()
    enabled = cfg.enabled_sources()
    apify_needed = bool(enabled.get("linkedin") or enabled.get("upwork"))
    tg = cfg.telegram()
    google_id_ready = bool(cfg.google_sheet_id)
    google_file_ready = cfg.google_service_account_path.exists()
    google_partly_configured = google_id_ready or google_file_ready
    google_optional_detail = "optional — not connected"
    items = [
        {"name": "Claude API key", "ok": bool(cfg.anthropic_key),
         "detail": "configured" if cfg.anthropic_key else "not set"},
        {"name": "Google Sheet ID (optional)",
         "ok": google_id_ready if google_partly_configured else True,
         "detail": ("configured" if google_id_ready else
                    ("missing" if google_partly_configured else google_optional_detail))},
        {"name": "Google credentials (optional)",
         "ok": google_file_ready if google_partly_configured else True,
         "detail": (cfg.google_service_account_path.name if google_file_ready else
                    ("missing" if google_partly_configured else google_optional_detail))},
        {"name": "Profile", "ok": bool(cfg.profile.get("summary") and cfg.profile.get("target_roles")),
         "detail": "ready" if cfg.profile.get("summary") and cfg.profile.get("target_roles") else "add a summary and at least one target role"},
        {"name": "Search keywords", "ok": bool(cfg.keywords()),
         "detail": "ready" if cfg.keywords() else "add at least one keyword"},
        {"name": "Résumé / CV", "ok": cfg.cv_path.exists(),
         "detail": cfg.cv_path.name if cfg.cv_path.exists() else "upload your CV"},
    ]
    if apify_needed:
        items.append({"name": "Apify token", "ok": bool(cfg.apify_token),
                      "detail": "configured" if cfg.apify_token else "not set"})
    if tg.get("enabled"):
        ok = bool(cfg.telegram_token and cfg.telegram_chat_id)
        items.append({"name": "Telegram", "ok": ok,
                      "detail": "configured" if ok else "enabled but not set"})
    return jsonify({"items": items})


@app.route("/api/check", methods=["POST"])
def check_live():
    """Live connection test (Claude, Google Sheets). Redacted output."""
    cfg = load_config()
    results = []

    # Claude (Anthropic)
    try:
        import anthropic
        anthropic.Anthropic().models.retrieve(cfg.scoring_model())
        results.append({"name": "Claude", "ok": True, "detail": cfg.scoring_model()})
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "Claude", "ok": False, "detail": scrub(str(exc))})

    # Google Sheets (optional; local storage works without it).
    if not cfg.google_sheets_ready():
        results.append({"name": "Google Sheet", "ok": True,
                        "detail": "optional — not connected; jobs are saved locally"})
    else:
        try:
            from src.sheets import open_worksheet
            ws = open_worksheet(cfg)
            results.append({"name": "Google Sheet", "ok": True,
                            "detail": f'opened "{ws.spreadsheet.title}"'})
        except PermissionError:
            results.append({"name": "Google Sheet", "ok": False,
                            "detail": "403 — share the sheet with the service-account email (Editor)"})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": "Google Sheet", "ok": False, "detail": scrub(str(exc))})

    return jsonify({"results": results})


# --------------------------------------------------------------------------
# Search (background thread)
# --------------------------------------------------------------------------
def _run_search_thread(dry_run: bool, no_score: bool, limit):
    from src.pipeline import run_search

    def progress(msg: str):
        with SEARCH_LOCK:
            SEARCH_STATE["log"].append(msg)

    try:
        cfg = load_config()
        result = run_search(cfg, dry_run=dry_run, no_score=no_score,
                            limit=limit, progress=progress)
        summary = {
            "fetched": result.fetched,
            "after_filter": result.after_filter,
            "new_jobs": result.new_jobs,
            "scored": result.scored,
            "logged": result.logged,
            "saved": result.saved,
            "below_threshold": result.below_threshold,
            "unscored": result.unscored,
            "min_score": result.min_score,
            "dry_run": result.dry_run,
            "scored_disabled": result.scored_disabled,
            "per_source": result.per_source,
            "errors": result.errors,
            "matches": [
                {"score": j.score, "title": j.title, "company": j.company,
                 "url": j.url, "reasons": j.reasons,
                 "recommendation": j.recommendation, "location": j.location}
                for j in result.matches
            ],
        }
        with SEARCH_LOCK:
            SEARCH_STATE["result"] = summary
    except Exception as exc:  # noqa: BLE001
        with SEARCH_LOCK:
            SEARCH_STATE["error"] = scrub(str(exc))
    finally:
        with SEARCH_LOCK:
            SEARCH_STATE["running"] = False


@app.route("/api/search", methods=["POST"])
def start_search():
    with SEARCH_LOCK:
        if SEARCH_STATE["running"]:
            return jsonify({"started": False, "error": "A search is already running."}), 409
        data = request.get_json(force=True) or {}
        SEARCH_STATE.update({"running": True, "log": [], "result": None, "error": None})

    limit = data.get("limit")
    try:
        limit = int(limit) if limit not in (None, "", "0") else None
    except (TypeError, ValueError):
        limit = None

    t = threading.Thread(
        target=_run_search_thread,
        args=(bool(data.get("dry_run")), bool(data.get("no_score")), limit),
        daemon=True,
    )
    t.start()
    return jsonify({"started": True})


@app.route("/api/search/status", methods=["GET"])
def search_status():
    with SEARCH_LOCK:
        return jsonify({
            "running": SEARCH_STATE["running"],
            "log": list(SEARCH_STATE["log"]),
            "result": SEARCH_STATE["result"],
            "error": SEARCH_STATE["error"],
        })


# --------------------------------------------------------------------------
# Matches (local storage, enriched from Google Sheets when connected)
# --------------------------------------------------------------------------
# The dashboard shows the AI's reasoning on each card, so the full text goes
# out. The scoring prompt caps it at 1-3 sentences, so this stays small.
MATCH_FIELDS = ("Date found", "Source", "Title", "Company", "Location",
                "Recommendation", "Reasons", "Status", "Applied on", "URL")


def _local_job_rows() -> list[dict]:
    """Return browser rows from the local store used by every installation."""
    from src.jobstore import load_store

    rows = []
    for record in load_store().values():
        rows.append({
            "Date found": record.get("date_found", ""),
            "Source": record.get("source", ""),
            "Title": record.get("title", ""),
            "Company": record.get("company", ""),
            "Location": record.get("location", ""),
            "Score": record.get("score"),
            "Recommendation": record.get("recommendation", ""),
            "Reasons": record.get("reasons", ""),
            "Status": record.get("status", "New"),
            "Applied on": record.get("applied_on", ""),
            "URL": record.get("url", ""),
        })
    return rows


def _as_score(value):
    """Sheet cells arrive as text. Return an int, or None when there is none.

    Deliberately rejects the non-finite words: float() accepts "Infinity" and
    "NaN", which is the bug that once blanked the whole matches list.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number)


def _counts(rows: list[dict], min_score: int) -> dict:
    """Totals for the filter bar's chips, so the client never recomputes them."""
    worth = max(min_score - 15, 0)
    out = {"total": len(rows), "great": 0, "worth_a_look": 0,
           "long_shot": 0, "applied": 0}
    for row in rows:
        score = row.get("Score")
        if score is None or score < worth:
            out["long_shot"] += 1
        elif score >= min_score:
            out["great"] += 1
        else:
            out["worth_a_look"] += 1
        if "applied" in str(row.get("Status") or "").lower():
            out["applied"] += 1
    return out


@app.route("/api/matches", methods=["GET"])
def matches():
    try:
        cfg = load_config()
        min_score = cfg.min_score()
        rows = _local_job_rows()
        storage = "local"
        warning = ""

        # When Google sync is enabled, merge its editable summary fields over
        # local rows while retaining any jobs a failed sync did not upload.
        if cfg.google_sheets_ready():
            try:
                from src.sheets import read_logged_jobs

                sheet_rows = read_logged_jobs(cfg)
                by_url = {str(row.get("URL", "")).strip().lower(): row for row in rows}
                for row in sheet_rows:
                    key = str(row.get("URL", "")).strip().lower()
                    if key and key in by_url:
                        by_url[key].update(row)
                    elif key:
                        rows.append(row)
                storage = "local+google"
            except Exception as exc:  # noqa: BLE001
                warning = "Google sync could not be read; showing jobs saved on this computer."

        slim = []
        for row in rows:
            item = {key: row.get(key, "") for key in MATCH_FIELDS}
            item["Score"] = _as_score(row.get("Score"))
            slim.append(item)

        slim.sort(key=lambda r: (r["Score"] is None, -(r["Score"] or 0)))
        return jsonify({"ok": True, "rows": slim, "min_score": min_score,
                        "counts": _counts(slim, min_score), "storage": storage,
                        "warning": warning})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


# --------------------------------------------------------------------------
# Draft the application pack for one job.
#
# The UI calls this the moment a job is selected: picking a job is the only
# thing the user has to do, and the cover letter plus the tailored CV are
# written for them. This still only WRITES FILES — it never sends or submits
# anything.
# --------------------------------------------------------------------------
def _job_from_request(data: dict) -> Job:
    """Build the Job to draft from.

    The Google Sheet row only carries a summary (title, company, location), so
    we look the posting up in the local job store first: drafting against the
    real job description is the difference between a specific letter and a
    generic one. The sheet row fills any gap.
    """
    url = str(data.get("url", "")).strip()
    job = None
    if url:
        from src.jobstore import get_job

        job = get_job(url)
    if job is None:
        job = Job(source="", title="", company="", url=url)

    # The sheet is the more current source for these (the user may have edited
    # a cell), so prefer it wherever it has something to say.
    for field_name in ("source", "title", "company", "location"):
        value = str(data.get(field_name, "") or "").strip()
        if value:
            setattr(job, field_name, value)
    return job


def _download_name(path) -> str:
    return Path(path).name if path else ""


@app.route("/api/draft", methods=["POST"])
def draft():
    try:
        data = request.get_json(force=True) or {}
        url = str(data.get("url", "")).strip()
        force = bool(data.get("force"))

        if url and not force:
            with DRAFT_LOCK:
                cached = DRAFT_CACHE.get(url)
            if cached:
                return jsonify({**cached, "cached": True})

        cfg = load_config()
        job = _job_from_request(data)

        from src.cv import load_cv_text
        from src.documents import draft_pack

        cv_text = load_cv_text(cfg.cv_path)
        pack = draft_pack(job, cv_text, cfg.profile, cfg.drafting_model())
        paths = pack.paths
        payload = {
            "ok": True,
            "cached": False,
            "cover_letter": pack.cover_letter,
            "tailored_cv": pack.tailored_cv,
            "cv_notes": pack.cv_notes,
            # What the download buttons ask for (Word where we made one).
            "cover_file": _download_name(paths.get("cover_letter_docx")
                                         or paths.get("cover_letter")),
            "cv_file": _download_name(paths.get("tailored_cv_docx")
                                      or paths.get("tailored_cv")),
            "used_description": bool(job.description),
            "folder": str(OUTPUT_DIR),
        }
        if url:
            with DRAFT_LOCK:
                DRAFT_CACHE[url] = payload
        return jsonify(payload)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


@app.route("/api/download/<path:filename>", methods=["GET"])
def download(filename: str):
    """Hand back one of the files we just wrote into output/."""
    target = (OUTPUT_DIR / filename).resolve()
    if OUTPUT_DIR.resolve() not in target.parents or not target.is_file():
        return jsonify({"ok": False, "error": "No such file."}), 404
    return send_file(str(target), as_attachment=True, download_name=target.name)


# --------------------------------------------------------------------------
# The Google Sheet dashboard
# --------------------------------------------------------------------------
@app.route("/api/dashboard", methods=["GET"])
def dashboard_link():
    from src.sheets import sheet_url

    cfg = load_config()
    if not cfg.google_sheets_ready():
        return jsonify({"ok": False, "error": "Google Sheets is not connected."}), 400
    return jsonify({"ok": True, "url": sheet_url(cfg)})


@app.route("/api/dashboard/refresh", methods=["POST"])
def dashboard_refresh():
    try:
        from src.sheets import build_dashboard

        return jsonify({"ok": True, "url": build_dashboard(load_config())})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400


# --------------------------------------------------------------------------
# Open the application page (the human-approved "apply" action).
# This ONLY opens the page in the browser. It never submits anything.
# --------------------------------------------------------------------------
@app.route("/api/open", methods=["POST"])
def open_page():
    data = request.get_json(force=True) or {}
    url = str(data.get("url", "")).strip()
    if not url:
        return jsonify({"ok": False, "error": "No URL for this job."}), 400
    webbrowser.open(url)
    return jsonify({"ok": True})


@app.route("/api/mark-applied", methods=["POST"])
def mark_applied():
    try:
        data = request.get_json(force=True) or {}
        from src.jobstore import set_status

        url = str(data.get("url", ""))
        local_updated = set_status(url, "Applied")
        sheet_updated = False
        cfg = load_config()
        if cfg.google_sheets_ready():
            try:
                from src.sheets import update_status

                sheet_updated = update_status(cfg, url, "Applied")
            except Exception:
                pass
        return jsonify({"ok": True, "updated": local_updated or sheet_updated,
                        "sheet_updated": sheet_updated})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub(str(exc))}), 400
