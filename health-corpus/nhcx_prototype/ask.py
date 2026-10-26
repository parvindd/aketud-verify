# MIT License
# Copyright (c) 2026 Parvind — deterministic demo lookup (synthetic use only).
"""Deterministic, no-API Ask path for the six frozen demo questions.

This is a lookup, not a language model. A question is answered only
when, after normalisation, it matches one of the frozen wordings in
``DEMO_QUESTIONS.md`` exactly. Near-misses, fragments, and questions
touching two frozen topics are refused as ambiguous; anything else is
refused as unsupported. Nothing is inferred from resemblance.

Before an answer is returned, its cited PDF must exist in
``health-corpus/raw/`` and every evidence probe for that question must
be found in the text extracted from that PDF (``pdftotext -raw``, the
same extraction the corpus builders use, compared with all whitespace
removed because PDF text extraction drops some spaces at line and
page breaks). If the source or the passage is unavailable, the result
is ``needs_review`` and no answer or citation is returned.

Statuses: ``answered``, ``refused``, ``needs_review``. Questions 5 and
6 are the frozen health-flow scenarios; their answers are flags only,
never a coverage decision and never an amount.

Separate from ``health_readiness`` and ``nhcx_packager``: this module
imports nothing from them.
"""
import re
import subprocess
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

DISCLAIMER = (
    "Deterministic lookup over the frozen demo questions — not a "
    "connected language model. Flags and citations only; not a "
    "coverage decision. The insurer decides admissibility."
)

_RAW_DIR = Path(__file__).resolve().parents[1] / "raw"

_PRODUCTS = "irdai-insurance-products-regulations-2024.pdf"
_MASTER = "master-circular-health-2024.pdf"
_AROGYA = "arogya-sanjeevani-hdfc-ergo.pdf"

_PRODUCTS_TITLE = "IRDAI (Insurance Products) Regulations, 2024"
_MASTER_TITLE = "Master Circular on Health Insurance Business, 29 May 2024"
_AROGYA_TITLE = "Arogya Sanjeevani prospectus (HDFC ERGO specimen)"

_PED_QUOTE = (
    "Waiting period for pre-existing diseases disclosed by the persons "
    "to be insured, shall be maximum up to 36 months of continuous "
    "coverage under the Health Insurance policy."
)
_PED_PROBES = (
    _PED_QUOTE,
    "Provided that the above waiting period norm of pre-existing "
    "disease shall not be applicable for Overseas Travel Policies.",
)


@dataclass(frozen=True)
class _Frozen:
    qid: str
    variants: tuple
    keywords: tuple
    answer: str
    source_title: str
    source_file: str
    citation: str
    quote: str
    probes: tuple


_FROZEN = (
    _Frozen(
        qid="ped_maximum",
        variants=(
            "What is the maximum pre-existing disease waiting period "
            "under the 2024 product rules?",
        ),
        keywords=(
            "pre-existing disease waiting period", "ped waiting",
            "36 months", "2024 product rules",
        ),
        answer=(
            "Maximum up to 36 months of continuous coverage for "
            "pre-existing diseases disclosed by the persons to be "
            "insured. This is a cap, not a fixed period: insurers may "
            "have a lesser pre-existing disease waiting period, so a "
            "given policy does not necessarily have a 36-month waiting "
            "period. The norm does not apply to Overseas Travel "
            "Policies."
        ),
        source_title=_PRODUCTS_TITLE,
        source_file=_PRODUCTS,
        citation=(
            "IRDAI (Insurance Products) Regulations, 2024, Schedule "
            "III, Regulation 7 (Gazette of India, Extraordinary, Part "
            "III—Sec. 4, No. 206, 22 March 2024, p. 37)"
        ),
        quote=(
            _PED_QUOTE + " Insurers may endeavor to have lesser "
            "pre-existing disease waiting period and specific waiting "
            "period in the health insurance products. Provided that "
            "the above waiting period norm of pre-existing disease "
            "shall not be applicable for Overseas Travel Policies."
        ),
        probes=_PED_PROBES,
    ),
    _Frozen(
        qid="moratorium",
        variants=(
            "After how many months of continuous cover can a health "
            "claim not be contested except for established fraud?",
            "लगातार कवर के कितने महीनों के बाद स्वास्थ्य दावा सिद्ध "
            "धोखाधड़ी के अलावा चुनौती नहीं दिया जा सकता?",
            "Continuous cover ke kitne months baad health claim "
            "established fraud ke alawa contest nahi ho sakta?",
        ),
        keywords=(
            "moratorium", "contest", "fraud", "चुनौती", "धोखाधड़ी",
        ),
        answer=(
            "60 months of continuous coverage (the Moratorium "
            "Period). After its completion, no policy and claim of "
            "health insurance shall be contestable on grounds of "
            "non-disclosure and/or misrepresentation except for "
            "established fraud."
        ),
        source_title=_MASTER_TITLE,
        source_file=_MASTER,
        citation=(
            "Master Circular on Health Insurance Business, 29 May "
            "2024, para 13 (PDF p. 8 of 17)"
        ),
        quote=(
            "No policy and claim of health insurance shall be "
            "contestable on any grounds of non-disclosure and/or "
            "misrepresentation except for established fraud, after "
            "the completion of the Moratorium Period, i.e. 60 months "
            "of continuous coverage"
        ),
        probes=(
            "No policy and claim of health insurance shall be "
            "contestable on any grounds of non-disclosure and/or "
            "misrepresentation except for established fraud, after "
            "the completion of the Moratorium Period, i.e. 60 months "
            "of continuous coverage",
        ),
    ),
    _Frozen(
        qid="initial_waiting_period",
        variants=(
            "In the Arogya Sanjeevani specimen, is there a waiting "
            "period for illness, and does it apply to accidents?",
            "आरोग्य संजीवनी नमूने में बीमारी के लिए प्रतीक्षा अवधि है "
            "क्या, और क्या यह दुर्घटना पर लागू होती है?",
            "Arogya Sanjeevani specimen mein illness ke liye waiting "
            "period hai kya, aur kya yeh accident par lagti hai?",
        ),
        keywords=("30 days", "first thirty days", "waiting period for illness"),
        answer=(
            "In the Arogya Sanjeevani specimen (HDFC ERGO), expenses "
            "for treatment of any illness within 30 days from the "
            "first policy commencement date are excluded. The "
            "exclusion does not apply to claims arising due to an "
            "accident, provided the same are covered."
        ),
        source_title=_AROGYA_TITLE,
        source_file=_AROGYA,
        citation=(
            "Arogya Sanjeevani prospectus (HDFC ERGO specimen), "
            "§3.2, Code-Excl03 (p. 2)"
        ),
        quote=(
            "Expenses related to the treatment of any illness within "
            "30 days from the first policy commencement date shall be "
            "excluded except claims arising due to an accident, "
            "provided the same are covered."
        ),
        probes=(
            "Expenses related to the treatment of any illness within "
            "30 days from the first policy commencement date shall be "
            "excluded except claims arising due to an accident, "
            "provided the same are covered.",
        ),
    ),
    _Frozen(
        qid="cosmetic_exclusion",
        variants=(
            "Does the Arogya Sanjeevani specimen cover cosmetic "
            "surgery to change appearance?",
            "क्या आरोग्य संजीवनी नमूना दिखावा बदलने के लिए कॉस्मेटिक "
            "सर्जरी कवर करता है?",
            "Kya Arogya Sanjeevani specimen appearance badalne ke "
            "liye cosmetic surgery cover karta hai?",
        ),
        keywords=("cosmetic", "plastic surgery", "appearance", "कॉस्मेटिक"),
        answer=(
            "Not covered: expenses for cosmetic or plastic surgery "
            "or any treatment to change appearance are excluded, "
            "unless for reconstruction following an Accident, Burn(s) "
            "or Cancer, or as part of medically necessary treatment "
            "to remove a direct and immediate health risk to the "
            "insured. For this to be considered a medical necessity, "
            "it must be certified by the attending Medical "
            "Practitioner."
        ),
        source_title=_AROGYA_TITLE,
        source_file=_AROGYA,
        citation=(
            "Arogya Sanjeevani prospectus (HDFC ERGO specimen), "
            "§4.5, Code-Excl08 (pp. 2–3)"
        ),
        quote=(
            "Expenses for cosmetic or plastic surgery or any "
            "treatment to change appearance unless for "
            "reconstruction following an Accident, Burn(s) or Cancer "
            "or as part of medically necessary treatment to remove a "
            "direct and immediate health risk to the insured. For "
            "this to be considered a medical necessity, it must be "
            "certified by the attending Medical Practitioner."
        ),
        probes=(
            "Expenses for cosmetic or plastic surgery or any "
            "treatment to change appearance unless for "
            "reconstruction following an Accident, Burn(s) or",
            "Cancer or as part of medically necessary treatment to "
            "remove a direct and immediate health risk to the "
            "insured. For this to be considered a medical necessity, "
            "it must be certified by the attending Medical "
            "Practitioner.",
        ),
    ),
    _Frozen(
        qid="ped_flag",
        variants=(
            "Synthetic: policy started 8 months ago, admission for a "
            "declared PED.",
            "Policy started 8 months ago, admission for a declared "
            "PED.",
            "Synthetic: policy started 8 months ago, admission for a "
            "declared pre-existing disease.",
        ),
        keywords=("declared ped", "declared pre-existing", "8 months ago"),
        answer=(
            "Flag: PED waiting period not completed — the policy "
            "started 8 months ago and the admission is for a declared "
            "pre-existing disease. This is a readiness flag only, "
            "not a claim decision. The policy wording must also be "
            "checked: the 36-month figure is the regulatory maximum "
            "for disclosed PEDs, and the policy may specify less."
        ),
        source_title=_PRODUCTS_TITLE,
        source_file=_PRODUCTS,
        citation=(
            "IRDAI (Insurance Products) Regulations, 2024, Schedule "
            "III, Regulation 7 (Gazette of India, Extraordinary, Part "
            "III—Sec. 4, No. 206, 22 March 2024, p. 37), and the "
            "policy wording"
        ),
        quote=_PED_QUOTE,
        probes=_PED_PROBES,
    ),
    _Frozen(
        qid="room_rent_flag",
        variants=(
            "Synthetic: room category above the eligible limit.",
            "Room category above the eligible limit.",
        ),
        keywords=(
            "room category", "room-rent", "room rent", "eligible limit",
            "proportionate",
        ),
        answer=(
            "Flag: proportionate-deduction risk — the selected room "
            "category is above the eligible limit. This is a "
            "readiness flag only: no payable amount is computed and "
            "no claim outcome is stated. The applicable limit is the "
            "one disclosed in the policy wording / Customer "
            "Information Sheet."
        ),
        source_title=_MASTER_TITLE,
        source_file=_MASTER,
        citation=(
            "Master Circular on Health Insurance Business, 29 May "
            "2024, Chapter I, para 4 (Customer Information Sheet) "
            "(PDF p. 6 of 17)"
        ),
        quote=(
            "CIS is to be provided with every policy … sub-limits (a "
            "pre-defined limit above which insurance company will "
            "not pay)"
        ),
        probes=(
            "CIS is to be provided with every policy",
            "sub-limits (a pre-defined limit above which insurance "
            "company will not pay)",
        ),
    ),
)


@dataclass(frozen=True)
class AskResult:
    status: str  # answered | refused | needs_review
    question_id: str | None
    answer: str | None
    source_title: str | None
    citation: str | None
    quote: str | None
    reason: str

    def to_dict(self):
        return asdict(self)


def _normalise(text):
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _squash(text):
    return re.sub(r"\s+", "", str(text)).lower()


_BY_VARIANT = {}
for _entry in _FROZEN:
    for _variant in _entry.variants:
        _BY_VARIANT[_normalise(_variant)] = _entry
_KEYWORDS = {
    e.qid: tuple(_normalise(k) for k in e.keywords) for e in _FROZEN
}


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


def _evidence_ok(entry, raw_dir):
    pdf_path = Path(raw_dir) / entry.source_file
    if not pdf_path.is_file():
        return False
    text = _pdf_text(pdf_path)
    if text is None:
        return False
    squashed = _squash(text)
    return all(_squash(probe) in squashed for probe in entry.probes)


def ask(question, *, raw_dir=None):
    """Answer one of the six frozen questions, or refuse.

    ``raw_dir`` overrides the corpus directory (used by tests to
    simulate missing evidence). Matching is exact after normalisation;
    resemblance alone never produces an answer.
    """
    if raw_dir is None:
        raw_dir = _RAW_DIR
    if question is None or not str(question).strip():
        return AskResult(
            "refused", None, None, None, None, None,
            "Refused (ambiguous): the question is empty, so it cannot "
            "be matched to a frozen question.",
        )
    entry = _BY_VARIANT.get(_normalise(question))
    if entry is None:
        normalised = _normalise(question)
        hits = [
            e.qid for e in _FROZEN
            if any(k in normalised for k in _KEYWORDS[e.qid])
        ]
        if len(hits) > 1:
            reason = (
                "Refused (ambiguous): the question touches more than "
                "one frozen topic (" + ", ".join(hits) + ") and does "
                "not match any single frozen question exactly."
            )
        elif hits:
            reason = (
                "Refused (ambiguous): the question resembles frozen "
                "question '" + hits[0] + "' but does not match its "
                "frozen wording exactly, so no answer is inferred."
            )
        else:
            reason = (
                "Refused (unsupported): the question does not match "
                "any of the six frozen demo questions."
            )
        return AskResult("refused", None, None, None, None, None, reason)
    if not _evidence_ok(entry, raw_dir):
        return AskResult(
            "needs_review", entry.qid, None, None, None, None,
            "Needs review: the cited source or required passage for "
            "frozen question '" + entry.qid + "' is unavailable, so "
            "no answer or citation is returned.",
        )
    return AskResult(
        "answered", entry.qid, entry.answer, entry.source_title,
        entry.citation, entry.quote,
        "Matched frozen question '" + entry.qid + "' exactly; cited "
        "passage verified in the source PDF.",
    )
