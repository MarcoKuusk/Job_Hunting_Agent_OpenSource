"""Pre-flight check: verifies everything the agent needs is in place.

Run this after you've installed dependencies and filled in .env:

    python scripts/check_setup.py

It checks dependencies, your .env credentials, config files, your CV, and live
connections to Claude, Google Sheets, Apify, and Telegram. Secrets are always
masked — this script never prints a real key or token.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Render Unicode (dashes, emoji) correctly on Windows consoles instead of
# garbling or crashing on the default code page.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Make the project root importable when run as `python scripts/check_setup.py`.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Tally of failures in REQUIRED checks (used for the exit code).
_failures = 0


def line(status: str, label: str, detail: str = "") -> None:
    tag = {"PASS": "[ PASS ]", "FAIL": "[ FAIL ]",
           "WARN": "[ WARN ]", "SKIP": "[ SKIP ]", "INFO": "[ INFO ]"}[status]
    print(f"{tag} {label}" + (f" — {detail}" if detail else ""))


def fail(label: str, detail: str = "") -> None:
    global _failures
    _failures += 1
    line("FAIL", label, detail)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check_python() -> None:
    section("Python")
    v = sys.version_info
    line("INFO", "Python version", f"{v.major}.{v.minor}.{v.micro}")


def check_dependencies() -> bool:
    section("Dependencies")
    # (import name, pip name)
    from src.config import scrub

    deps = [
        ("anthropic", "anthropic"),
        ("requests", "requests"),
        ("feedparser", "feedparser"),
        ("yaml", "PyYAML"),
        ("dotenv", "python-dotenv"),
        ("gspread", "gspread"),
        ("google.auth", "google-auth"),
        ("pypdf", "pypdf"),
        ("docx", "python-docx"),
    ]
    all_ok = True
    for import_name, pip_name in deps:
        try:
            importlib.import_module(import_name)
            line("PASS", pip_name)
        except ImportError:
            all_ok = False
            fail(pip_name, "not installed — run: pip install -r requirements.txt")
        except Exception as exc:  # installed but failed to load (e.g. blocked DLL)
            all_ok = False
            fail(pip_name, "installed but failed to load: " + scrub(str(exc)))
    return all_ok


def check_env_and_config():
    section("Credentials (.env) and config")
    from src.config import PROJECT_ROOT, load_config, mask, scrub

    if not (PROJECT_ROOT / ".env").exists():
        fail(".env file", "missing — copy .env.example to .env and fill it in")
    else:
        line("PASS", ".env file", "found")

    try:
        config = load_config()
    except Exception as exc:
        fail("config files", scrub(str(exc)))
        return None

    line("PASS", "config/profile.yaml + config/search.yaml", "parsed")

    # Required secrets (masked).
    required = {
        "ANTHROPIC_API_KEY": config.anthropic_key,
        "GOOGLE_SHEET_ID": config.google_sheet_id,
    }
    for name, value in required.items():
        if value:
            shown = mask(value) if name == "ANTHROPIC_API_KEY" else value
            line("PASS", name, shown)
        else:
            fail(name, "not set in .env")

    # Apify / Telegram are required only if those features are on.
    enabled = config.enabled_sources()
    if enabled.get("linkedin") or enabled.get("upwork"):
        if config.apify_token:
            line("PASS", "APIFY_API_TOKEN", mask(config.apify_token))
        else:
            fail("APIFY_API_TOKEN", "LinkedIn/Upwork enabled but token not set")
    else:
        line("SKIP", "APIFY_API_TOKEN", "LinkedIn/Upwork sources are off")

    if config.telegram().get("enabled"):
        if config.telegram_token and config.telegram_chat_id:
            line("PASS", "Telegram token + chat id", mask(config.telegram_token))
        else:
            fail("Telegram", "enabled but TELEGRAM_BOT_TOKEN/CHAT_ID not set")
    else:
        line("SKIP", "Telegram", "disabled in search.yaml")

    return config


def check_cv(config) -> None:
    section("Résumé")
    from src.config import scrub

    try:
        from src.cv import load_cv_text

        text = load_cv_text(config.cv_path)
        line("PASS", "CV readable", f"{config.cv_path.name}, {len(text)} characters")
    except Exception as exc:
        fail("CV", scrub(str(exc)))


def check_anthropic(config) -> None:
    section("Claude API")
    from src.config import scrub

    if not config.anthropic_key:
        line("SKIP", "Claude", "no API key to test")
        return
    try:
        import anthropic

        client = anthropic.Anthropic()
        model = config.scoring_model()
        # Retrieving model metadata validates the key and the model id without
        # spending any tokens.
        client.models.retrieve(model)
        line("PASS", "Claude API key + model", model)
    except Exception as exc:
        fail("Claude API", scrub(str(exc)))


def _service_account_email(config) -> str:
    """Read the (non-secret) client_email from the service-account JSON."""
    import json

    try:
        with open(config.google_service_account_path, "r", encoding="utf-8") as f:
            return json.load(f).get("client_email", "(the client_email in your JSON)")
    except Exception:
        return "(the client_email in your JSON)"


def check_sheets(config) -> None:
    section("Google Sheets")
    from src.config import scrub

    try:
        from src.sheets import open_worksheet

        ws = open_worksheet(config)
        title = ws.spreadsheet.title
        line("PASS", "Google Sheet", f'opened "{title}"')
    except PermissionError:
        # gspread raises a bare PermissionError (no message) on a 403.
        email = _service_account_email(config)
        fail("Google Sheets",
             f"403 permission denied. Share the sheet with this service-account "
             f"email as Editor: {email}  (and confirm the Google Sheets API + "
             f"Google Drive API are enabled in the Cloud project).")
    except Exception as exc:
        detail = scrub(str(exc)) or type(exc).__name__
        hint = ""
        upper = detail.upper()
        if "SERVICE_DISABLED" in upper or "HAS NOT BEEN USED" in upper:
            hint = " — enable the Google Sheets API AND Google Drive API in the Cloud project"
        elif "PERMISSION" in upper or "403" in detail:
            hint = f" — share the sheet with {_service_account_email(config)} (Editor)"
        elif "NOT FOUND" in upper or "404" in detail:
            hint = " — check GOOGLE_SHEET_ID in .env matches your sheet's URL"
        fail("Google Sheets", detail + hint)


def check_apify(config) -> None:
    section("Apify")
    from src.config import scrub

    enabled = config.enabled_sources()
    if not (enabled.get("linkedin") or enabled.get("upwork")):
        line("SKIP", "Apify", "LinkedIn/Upwork sources are off")
        return
    if not config.apify_token:
        line("SKIP", "Apify", "no token to test")
        return
    try:
        import requests

        resp = requests.get(
            "https://api.apify.com/v2/users/me",
            params={"token": config.apify_token},
            timeout=15,
        )
        resp.raise_for_status()
        line("PASS", "Apify token", "valid")
    except Exception as exc:
        fail("Apify", scrub(str(exc)))

    # Warn if enabled but no actor configured yet (that's Step 5).
    apify = config.apify()
    if enabled.get("linkedin") and not apify.get("linkedin_actor"):
        line("WARN", "LinkedIn actor", "no actor id set in search.yaml (Step 5)")
    if enabled.get("upwork") and not apify.get("upwork_actor"):
        line("WARN", "Upwork actor", "no actor id set in search.yaml (Step 5)")


def check_telegram(config) -> None:
    section("Telegram")
    from src.config import scrub

    if not config.telegram().get("enabled"):
        line("SKIP", "Telegram", "disabled in search.yaml")
        return
    if not config.telegram_token:
        line("SKIP", "Telegram", "no token to test")
        return
    try:
        import requests

        resp = requests.get(
            f"https://api.telegram.org/bot{config.telegram_token}/getMe",
            timeout=15,
        )
        resp.raise_for_status()
        bot = resp.json().get("result", {}).get("username", "")
        line("PASS", "Telegram bot", f"@{bot}" if bot else "valid")
    except Exception as exc:
        fail("Telegram", scrub(str(exc)))


def main() -> int:
    print("Job Hunting Agent — setup check\n" + "=" * 40)
    check_python()
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\nInstall dependencies first, then re-run this check:")
        print("    pip install -r requirements.txt")
        return 1

    config = check_env_and_config()
    if config is not None:
        check_cv(config)
        check_anthropic(config)
        check_sheets(config)
        check_apify(config)
        check_telegram(config)

    print("\n" + "=" * 40)
    if _failures:
        print(f"{_failures} check(s) failed. Fix the items marked [ FAIL ] above.")
        return 1
    print("All required checks passed. You're ready to run a search. 🎉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
