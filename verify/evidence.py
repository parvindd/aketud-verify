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


def _squash(text):
    # Copied from ask.py: whitespace-stripped comparison form.
    return re.sub(r"\s+", "", str(text)).lower()


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
    if raw_dir is None:
        raw_dir = _RAW_DIR
    pdf_path = Path(raw_dir) / str(source_file)
    if not pdf_path.is_file():
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
    if raw_dir is None:
        raw_dir = _RAW_DIR
    pdf_path = Path(raw_dir) / str(source_file) if source_file else None
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
