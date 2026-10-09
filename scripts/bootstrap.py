"""Prepare a private local installation, then optionally launch the web UI.

This file deliberately uses only the Python standard library so it can run
before the project's dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
STAMP = VENV / ".job-finder-requirements"
MIN_PYTHON = (3, 11)


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _requirements_fingerprint() -> str:
    requirements = (ROOT / "requirements.txt").read_bytes()
    version = f"{sys.version_info.major}.{sys.version_info.minor}".encode()
    return hashlib.sha256(requirements + b"\0" + version).hexdigest()


def _copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    print(f"Created {destination.relative_to(ROOT)}")


def prepare() -> Path:
    if sys.version_info < MIN_PYTHON:
        needed = ".".join(map(str, MIN_PYTHON))
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise RuntimeError(
            f"Job Finder needs Python {needed} or newer; this is Python {current}."
        )

    python = _venv_python()
    if not python.exists():
        print("Creating Job Finder's private Python environment?")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)

    fingerprint = _requirements_fingerprint()
    installed = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
    if installed != fingerprint:
        print("Installing or updating Job Finder? this can take a few minutes.")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(ROOT / "requirements.txt")],
            check=True,
        )
        STAMP.write_text(fingerprint + "\n", encoding="utf-8")

    _copy_if_missing(ROOT / ".env.example", ROOT / ".env")
    _copy_if_missing(
        ROOT / "config" / "profile.example.yaml", ROOT / "config" / "profile.yaml"
    )
    _copy_if_missing(
        ROOT / "config" / "search.example.yaml", ROOT / "config" / "search.yaml"
    )
    for name in ("credentials", "data", "output"):
        (ROOT / name).mkdir(exist_ok=True)
    return python


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Job Finder for local use.")
    parser.add_argument("--launch", action="store_true", help="open Job Finder after setup")
    args = parser.parse_args()

    try:
        python = prepare()
        if args.launch:
            print("Starting Job Finder?")
            return subprocess.run([str(python), str(ROOT / "scripts" / "run_ui.py")]).returncode
        print("Job Finder is ready. Run Start Job Finder to open it.")
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print()
        print("Setup could not finish:", exc)
        print("See README.md ? Troubleshooting, or copy this message when asking for help.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
