"""Drafts the whole application pack for ONE job: a cover letter, a tailored
version of the CV, and a short list of what was changed.

These are DRAFTS for you to review and edit. This module only writes files to
the output/ folder — it never sends an email and never submits anything.

Each document is saved twice: as Markdown (easy to read on screen) and as a
Word .docx (what you actually attach to an application).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT
from .models import Job
from .scoring import build_client, profile_to_text

OUTPUT_DIR = PROJECT_ROOT / "output"

COVER_LETTER_SYSTEM = (
    "You are helping a job seeker write a concise, specific, and genuine cover "
    "letter for a remote job. Use the candidate's real CV and profile. Match "
    "the letter to the job's actual requirements, highlight the most relevant "
    "experience, avoid clichés and filler, and keep it under ~300 words. "
    "Write in the first person as the candidate. Do not invent facts that "
    "aren't supported by the CV. Output the letter text only: no preamble, no "
    "commentary, no markdown headings. IMPORTANT: never use the em dash "
    "character (—) anywhere in the letter; use commas, periods, or parentheses "
    "instead."
)

TAILORED_CV_SYSTEM = (
    "You are an expert CV writer. Rewrite the candidate's existing CV so that "
    "it targets ONE specific job posting. This is a re-presentation of real "
    "experience, never an invention of new experience.\n\n"
    "Hard rules:\n"
    "* Every employer, job title, date, qualification and achievement must "
    "already appear in the source CV. Never add, inflate, or invent one, and "
    "never change dates or job titles.\n"
    "* You MAY reorder sections and bullets, reword bullets to mirror the "
    "posting's own language, lead with the most relevant experience, and cut "
    "or compress the least relevant detail.\n"
    "* Keep every contact detail (email, phone, city, LinkedIn) exactly as it "
    "appears in the source CV. If a detail is not in the CV, leave it out "
    "rather than inventing a placeholder.\n"
    "* Aim for one to two pages of content.\n\n"
    "Output the finished CV as Markdown only, with no commentary before or "
    "after it, using this structure:\n"
    "'# Candidate Name', then a single line of contact details separated by "
    "vertical bars, then '## Professional Summary' (2 to 4 sentences aimed at "
    "this job), '## Key Skills' (bulleted short phrases, the ones this posting "
    "asks for first), '## Experience' with one '### Job Title, Company "
    "(dates)' per role followed by achievement bullets, then '## Education' "
    "and '## Languages'. Keep any other section the source CV has "
    "(certifications, tools, volunteering) using the same '##' style.\n\n"
    "IMPORTANT: never use the em dash character (—) anywhere; use commas, "
    "hyphens, or parentheses instead."
)

CV_NOTES_SYSTEM = (
    "You are a practical career coach. The candidate has just been given an "
    "automatically tailored CV for a specific job. Write a SHORT briefing (150 "
    "words maximum) telling them what to check before they send it: which "
    "experience the tailored CV leads with and why, which keywords from the "
    "posting it mirrors, what it plays down, and any gap against the posting "
    "they should be ready to talk about at interview. Use short bullet points. "
    "Never suggest fabricating experience. IMPORTANT: never use the em dash "
    "character (—) anywhere; use commas, hyphens, or parentheses instead."
)


@dataclass
class DraftPack:
    """Everything produced for one job: the text and where it was saved."""

    cover_letter: str = ""
    tailored_cv: str = ""
    cv_notes: str = ""
    paths: dict[str, Path] = field(default_factory=dict)


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
    return (text[:max_len] or "job").strip("-")


def _no_em_dash(text: str) -> str:
    """Guarantee the drafts contain no em dash (—). The model is instructed to
    avoid it, but we also strip it deterministically as a safety net, since
    models often ignore such rules. Em dashes become commas; the result is
    tidied so we don't leave doubled commas or stray spaces."""
    if not text:
        return text
    text = text.replace(" — ", ", ").replace("—", ", ")
    text = re.sub(r",\s*,", ", ", text)      # collapse doubled commas
    text = re.sub(r"\s+,", ",", text)         # no space before a comma
    text = re.sub(r"[ \t]{2,}", " ", text)    # collapse runs of spaces
    return text


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap a whole document in a ``` code fence."""
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _draft(system: str, instruction: str, job: Job, cv_text: str,
           profile: dict, model: str, client, max_tokens: int = 2000) -> str:
    user_prompt = (
        "CANDIDATE PROFILE:\n"
        f"{profile_to_text(profile)}\n\n"
        "CANDIDATE CV:\n"
        f"{cv_text}\n\n"
        "JOB POSTING:\n"
        f"{job.to_compact_text(max_description_chars=6000)}\n\n"
        f"{instruction}"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _no_em_dash(_strip_code_fence(text))


# --------------------------------------------------------------------------
# Markdown -> Word
# --------------------------------------------------------------------------
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _add_runs(paragraph, text: str) -> None:
    """Add text to a paragraph, honouring **bold** spans."""
    pos = 0
    for match in _BOLD.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos:match.start()])
        paragraph.add_run(match.group(1)).bold = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _markdown_to_docx(markdown: str, path: Path) -> Path:
    """Render the small Markdown subset we generate (#/##/### headings, dash
    bullets, **bold**) into a Word document. python-docx is imported lazily,
    like every other heavy dependency in this project."""
    import docx

    document = docx.Document()
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line in ("---", "***", "___"):
            continue
        if line.startswith("### "):
            document.add_heading(line[4:].strip(), level=3)
        elif line.startswith("## "):
            document.add_heading(line[3:].strip(), level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:].strip(), level=1)
        elif line.startswith(("- ", "* ")):
            _add_runs(document.add_paragraph(style="List Bullet"), line[2:].strip())
        else:
            _add_runs(document.add_paragraph(), line)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def _write_pair(base_dir: Path, stem: str, header: str, body: str,
                as_docx: bool) -> dict[str, Path]:
    """Save one document as .md (always) and .docx (when it is something the
    user will attach to an application)."""
    md_path = base_dir / f"{stem}.md"
    # Filter the FULL file contents (header included) so nothing written to
    # disk ever contains an em dash.
    md_path.write_text(_no_em_dash(header + body) + "\n", encoding="utf-8")
    out = {"md": md_path}
    if as_docx:
        try:
            out["docx"] = _markdown_to_docx(_no_em_dash(body),
                                            base_dir / f"{stem}.docx")
        except Exception:  # noqa: BLE001
            # A missing python-docx must not throw away the draft we just paid
            # for; the Markdown copy is already safely on disk.
            pass
    return out


# --------------------------------------------------------------------------
# The public entry point
# --------------------------------------------------------------------------
def draft_pack(job: Job, cv_text: str, profile: dict, model: str,
               client=None) -> DraftPack:
    """Write the cover letter, the tailored CV and the review notes for one
    job, save them all to output/, and return the text plus the file paths.

    The three Claude calls are independent, so they run at the same time: the
    user is sitting in front of the UI waiting, and doing them one after
    another would roughly triple that wait.
    """
    client = client or build_client()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = {
        "cover_letter": (COVER_LETTER_SYSTEM, "Write the cover letter now.", 2000),
        "tailored_cv": (TAILORED_CV_SYSTEM, "Write the tailored CV now.", 4000),
        "cv_notes": (CV_NOTES_SYSTEM, "Write the review briefing now.", 1200),
    }
    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        futures = {
            name: pool.submit(_draft, system, instruction, job, cv_text,
                              profile, model, client, tokens)
            for name, (system, instruction, tokens) in wanted.items()
        }
        texts = {name: future.result() for name, future in futures.items()}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{_slug(job.company)}_{_slug(job.title)}"
    header = f"# {job.title} at {job.company}\n# {job.url}\n\n"

    cover = _write_pair(OUTPUT_DIR, f"{base}_cover_letter", header,
                        texts["cover_letter"], as_docx=True)
    # The CV gets no header comment: it is a finished document, not a note.
    cv = _write_pair(OUTPUT_DIR, f"{base}_tailored_cv", "",
                     texts["tailored_cv"], as_docx=True)
    notes = _write_pair(OUTPUT_DIR, f"{base}_cv_notes", header,
                        texts["cv_notes"], as_docx=False)

    paths = {
        "cover_letter": cover["md"],
        "tailored_cv": cv["md"],
        "cv_notes": notes["md"],
        # Kept under its old name so existing callers keep working.
        "cv_suggestions": notes["md"],
    }
    if "docx" in cover:
        paths["cover_letter_docx"] = cover["docx"]
    if "docx" in cv:
        paths["tailored_cv_docx"] = cv["docx"]

    return DraftPack(
        cover_letter=texts["cover_letter"],
        tailored_cv=texts["tailored_cv"],
        cv_notes=texts["cv_notes"],
        paths=paths,
    )


def draft_for_job(job: Job, cv_text: str, profile: dict, model: str,
                  client=None) -> dict[str, Path]:
    """Backwards-compatible wrapper: returns only the saved file paths."""
    return draft_pack(job, cv_text, profile, model, client=client).paths
