"""Check tracked files for private paths and common secret formats.

Reports filenames and line numbers only; never prints matching values.
This complements, but cannot replace, human review and a dedicated scanner.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}",
    "Apify token": r"apify_api_[A-Za-z0-9_-]{20,}",
    "GitHub token": r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "Google key": r"AIza[A-Za-z0-9_-]{30,}",
    "AWS access key": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "Telegram token": r"\b\d{6,}:[A-Za-z0-9_-]{25,}",
    # Unix forms require a path boundary, so a public URL ending in
    # /v2/users/me is not confused with a local home directory.
    "private home path": r"(?i)(?:[A-Z]:[\\/]Users[\\/]|(?<![A-Za-z0-9:/])/(?:Users|home)/)[\w.-]+",
}

def inspect_file(name, content):
    findings = []
    path = Path(name)
    if (name in {"config/profile.yaml", "config/search.yaml"}
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".pdf", ".docx"}
        or any(part in {".claude", ".codex", ".aws"} for part in path.parts)
        or (path.parts[0] in {"data", "output", "credentials"} and path.name != ".gitkeep")):
        findings.append(f"{name}: private or generated file must not be tracked")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(f"{name}: binary file requires manual review")
        return findings
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            if re.search(pattern, line):
                findings.append(f"{name}:{number}: possible {label}")
    return findings

def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    findings = []
    for name in filter(None, names):
        # Inspect index too: an earlier staged secret may still be present.
        path = ROOT / name
        if path.is_file():
            findings.extend(inspect_file(name, path.read_bytes()))
        staged = subprocess.run(["git", "show", f":{name}"], cwd=ROOT, capture_output=True)
        if staged.returncode == 0:
            findings.extend(inspect_file(name, staged.stdout))
    findings = sorted(set(findings))
    print("\n".join(findings) if findings else "Public release check passed (tracked working tree and index).")
    return bool(findings)

if __name__ == "__main__":
    sys.exit(main())
