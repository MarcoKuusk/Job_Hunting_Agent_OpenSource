"""Configuration loading and secret-safe helpers.

Loads secrets from .env and settings from config/profile.yaml and
config/search.yaml. Also provides `mask()` / `scrub()` so that nothing in this
program ever prints a real API key or token to the screen or a log.

Third-party imports (dotenv, yaml) happen inside functions so this module can
be imported even before dependencies are installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Every environment variable that holds a secret. Used by scrub() to make sure
# none of these values ever leak into printed output or error messages.
SECRET_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "APIFY_API_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)


def mask(secret: str | None) -> str:
    """Show just enough of a secret to recognise it, hiding the rest."""
    if not secret:
        return "(not set)"
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}…{secret[-2:]}"


def scrub(text: str) -> str:
    """Replace any real secret value found in `text` with [REDACTED].

    Use this on anything (error messages, API responses) before showing it to
    the user, so a stray exception can't print a key.
    """
    if not text:
        return text
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 6 and value in text:
            text = text.replace(value, "[REDACTED]")
    return text


def load_env() -> None:
    """Load the .env file into the process environment (if present)."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        # A fresh checkout uses public defaults until local settings are saved.
        path = path.with_name(f"{path.stem}.example{path.suffix}")
        if not path.exists():
            return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


@dataclass
class Config:
    profile: dict[str, Any]
    search: dict[str, Any]

    # --- convenience accessors for secrets (read from the environment) ---
    @property
    def anthropic_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def apify_token(self) -> str:
        return os.environ.get("APIFY_API_TOKEN", "")

    @property
    def telegram_token(self) -> str:
        return os.environ.get("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.environ.get("TELEGRAM_CHAT_ID", "")

    @property
    def google_sheet_id(self) -> str:
        return os.environ.get("GOOGLE_SHEET_ID", "")

    @property
    def google_service_account_path(self) -> Path:
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        if not raw:
            return PROJECT_ROOT / "credentials" / "service_account.json"
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def cv_path(self) -> Path:
        raw = (self.profile.get("cv_path") or "data/resume.pdf").strip()
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p

    # --- nested settings helpers ---
    def scoring(self) -> dict[str, Any]:
        return self.search.get("scoring", {}) or {}

    def min_score(self) -> int:
        return int(self.scoring().get("min_score", 70))

    def scoring_model(self) -> str:
        return self.scoring().get("scoring_model", "claude-haiku-4-5")

    def max_jobs_per_source(self) -> int:
        return int(self.scoring().get("max_jobs_per_source", 50))

    def drafting_model(self) -> str:
        return (self.search.get("documents", {}) or {}).get(
            "drafting_model", "claude-opus-4-8"
        )

    def enabled_sources(self) -> dict[str, bool]:
        return self.search.get("sources", {}) or {}

    def keywords(self) -> list[str]:
        return [k for k in (self.search.get("keywords") or []) if k]

    def exclude_keywords(self) -> list[str]:
        return [k for k in (self.search.get("exclude_keywords") or []) if k]

    def apify(self) -> dict[str, Any]:
        return self.search.get("apify", {}) or {}

    def telegram(self) -> dict[str, Any]:
        return self.search.get("telegram", {}) or {}


def load_config() -> Config:
    """Load .env + the two YAML files and return a Config object."""
    load_env()
    profile = _load_yaml(PROJECT_ROOT / "config" / "profile.yaml")
    search = _load_yaml(PROJECT_ROOT / "config" / "search.yaml")
    return Config(profile=profile, search=search)
