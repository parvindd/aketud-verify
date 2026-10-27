"""Deterministic evidence check (hackathon Step 1).

``check_evidence(source_file, quote)`` verifies, without any model,
that ``source_file`` exists under ``health-corpus/raw/`` and that
``quote`` is found verbatim in the text extracted from that PDF.

Extraction and matching copy the helpers in
``health-corpus/nhcx_prototype/ask.py`` (``pdftotext -raw`` compared
with all whitespace removed, because PDF extraction drops some spaces
at line and page breaks). ``ask.py`` is a baseline file and is not
edited or imported from here; the helper is copied so this module
stays self-contained.

This check is deterministic and cannot be overridden by any model:
a quote not found verbatim gives ``found=False``.
"""
import hashlib
import re
import subprocess
from pathlib import Path

_RAW_DIR = Path(__file__).resolve().parents[1] / "health-corpus" / "raw"
_RAW_DIRS = (
    _RAW_DIR,
    Path(__file__).resolve().parents[1] / "life-corpus" / "raw",
)


def _raw_dirs(raw_dir=None):
    if raw_dir is not None:
        return (Path(raw_dir),)
    return _RAW_DIRS


def _resolve(source_file, raw_dir=None):
    if not source_file:
        return None
    for directory in _raw_dirs(raw_dir):
        candidate = directory / str(source_file)
        if candidate.is_file():
            return candidate
    # Return the first candidate so exists=False reporting is stable.
    return _raw_dirs(raw_dir)[0] / str(source_file)


def _squash(text):
    # Copied from ask.py: whitespace-stripped comparison form.
    # Curly quotes are normalised so a straight-quoted citation
    # matches PDF text extracted with typographic quotes.
    normalised = str(text).replace("\u201c", '"').replace(
        "\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return re.sub(r"\s+", "", normalised).lower()


def _pdf_text(pdf_path):
    """Extract PDF text, or return None when extraction is unavailable."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-raw", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def extract_text(source_file, *, raw_dir=None):
    """Return extracted text for ``source_file``, or None if unavailable."""
    pdf_path = _resolve(source_file, raw_dir)
    if pdf_path is None or not pdf_path.is_file():
        return None
    return _pdf_text(pdf_path)


def check_evidence(source_file, quote, *, raw_dir=None):
    """Check that ``quote`` appears verbatim in ``source_file``.

    Returns ``{"exists": bool, "found": bool, "page_text_hash": str|None}``
    where ``page_text_hash`` is the SHA-256 hex digest of the extracted
    page text (``None`` when no text could be extracted). Fails closed:
    a missing file, failed extraction, or empty quote gives
    ``found=False``.
    """
    pdf_path = _resolve(source_file, raw_dir)
    exists = bool(pdf_path is not None and pdf_path.is_file())
    if not exists:
        return {"exists": False, "found": False, "page_text_hash": None}
    text = _pdf_text(pdf_path)
    if text is None:
        return {"exists": True, "found": False, "page_text_hash": None}
    page_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if quote is None or not str(quote).strip():
        return {"exists": True, "found": False,
                "page_text_hash": page_text_hash}
    found = _squash(quote) in _squash(text)
    return {"exists": True, "found": found,
            "page_text_hash": page_text_hash}
