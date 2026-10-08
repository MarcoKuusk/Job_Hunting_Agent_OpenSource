"""Reads your résumé into plain text for the model to compare jobs against.

Supports PDF (pypdf), Word .docx (python-docx), and plain .txt/.md. Heavy
libraries are imported lazily, per file type.
"""

from __future__ import annotations

from pathlib import Path


def load_cv_text(path: Path | str) -> str:
    """Extract plain text from a résumé file. Raises a clear error if missing
    or if the file type isn't supported."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Résumé not found at {path}. Put your CV in the data/ folder and "
            f"set 'cv_path' in config/profile.yaml."
        )

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    raise ValueError(
        f"Unsupported résumé type '{suffix}'. Use a .pdf, .docx, .txt, or .md file."
    )


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError(
            f"Could not extract any text from {path}. If it's a scanned image "
            f"PDF, save a text-based version or paste your CV into a .txt file."
        )
    return text


def _read_docx(path: Path) -> str:
    import docx  # python-docx

    document = docx.Document(str(path))
    text = "\n".join(p.text for p in document.paragraphs).strip()
    if not text:
        raise ValueError(f"Could not extract any text from {path}.")
    return text
