"""Governing-authority registry (verify Fix 2).

A small registry of governing rules. Each entry is::

    {topic, source_file, quote, issuer, effective_date,
     published, signed, gazette,
     supersedes: [source_file, ...]}

``effective_date`` is the date the rule is in force from;
``published`` is its Gazette publication date and ``signed``
the date it was signed. These are distinct dates and must not
be conflated.

When a claim's source is superseded on a topic, the governing
passage takes precedence over the claim's own source: the pipeline
re-verifies the claim against the governing quote (after an
evidence check on the governing PDF). A governing ``CONTRADICTED``
verdict makes the claim ``CONTRADICTED``, and any correction must
quote the governing passage and name the governing source.
"""

# PED quote: IRDAI (Insurance Products) Regulations, 2024,
# Schedule III, Regulation 7 (same passage as ask.py _PED_QUOTE).
_PED_QUOTE = (
    "Waiting period for pre-existing diseases disclosed by the persons "
    "to be insured, shall be maximum up to 36 months of continuous "
    "coverage under the Health Insurance policy."
)

REGISTRY = [
    {
        "topic": "PED waiting period",
        "source_file": "irdai-insurance-products-regulations-2024.pdf",
        "quote": _PED_QUOTE,
        "value": "36 months",
        "extracted_value": "36 months",
        "issuer": "IRDAI",
        "effective_date": "2024-04-01",
        "published": "2024-03-22",
        "signed": "2024-03-20",
        "gazette": "Gazette No. 206",
        "supersedes": ["arogya-sanjeevani-hdfc-ergo.pdf"],
    },
]

# Alias: the registry under a second common name.
RULES = REGISTRY

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _format_iso_date(iso_date):
    """Format ``YYYY-MM-DD`` as e.g. ``1 April 2024``."""
    try:
        year, month, day = str(iso_date).split("-")
        return "%d %s %d" % (
            int(day), _MONTH_NAMES[int(month) - 1], int(year))
    except (ValueError, IndexError, AttributeError):
        return str(iso_date)


def effective_display(rule):
    """Human-readable in-force display for ``rule``.

    Accepts a registry entry (dict) or an ISO date string and
    returns e.g. ``"in force from 1 April 2024"`` for the PED
    rule (``effective_date`` 2024-04-01). This is the displayed
    date: it uses ``effective_date``, never ``published`` or
    ``signed``.
    """
    iso = rule.get("effective_date") if isinstance(rule, dict) else rule
    if not iso:
        return ""
    return "in force from %s" % _format_iso_date(iso)


# Aliases for discoverability.
display_effective_date = effective_display
in_force_display = effective_display

# Topic keywords used to decide whether a governing rule is on-topic
# for a claim. A superseded source may cover many topics; only a
# rule whose topic the claim actually touches takes precedence.
# Matching is language-independent (Fix 14): the cited quote is
# verbatim source text (always English) and is matched in addition
# to claim + question, and Devanagari spellings of the governed
# topic are recognised so a Hindi claim cannot bypass the check.
_TOPIC_KEYWORDS = {
    "PED waiting period": (
        "ped", "pre-existing", "pre existing", "preexisting",
        # Devanagari (Fix 14).
        "प्री-एग्ज़िस्टिंग", "पूर्व-मौजूदा", "पीईडी",
        "वेटिंग पीरियड", "प्रतीक्षा अवधि",
    ),
}

# Roman-Hindi (Hinglish) markers: their presence in claim/question
# means keyword topic detection may miss a governed topic, so for
# a superseded source detection is uncertain (fail closed).
_HINGLISH_MARKERS = (
    "hai", "kya", "mein", "aur", "nahi", "ke liye", "ka", "ki",
    "ke", "mahine", "bimari", "bimaari", "purani", "pehle",
    "maujooda", "maujud", "kitne", "baad", "lagti", "hoga",
)


def _contains_devanagari(text):
    return bool(text) and any(
        "\u0900" <= ch <= "\u097f" for ch in str(text))


def contains_devanagari(text):
    """True if ``text`` contains any Devanagari character."""
    return _contains_devanagari(text)


def _contains_hinglish_marker(text):
    if not text:
        return False
    lowered = " %s " % str(text).lower()
    return any(" %s " % marker in lowered
               or " %s" % marker in lowered
               for marker in _HINGLISH_MARKERS)

# Human-readable titles for known sources.
_TITLES = {
    "irdai-insurance-products-regulations-2024.pdf": (
        "IRDAI (Insurance Products) Regulations, 2024, "
        "Schedule III, Regulation 7"
    ),
    "arogya-sanjeevani-hdfc-ergo.pdf": (
        "Arogya Sanjeevani prospectus (HDFC ERGO specimen)"
    ),
    "master-circular-health-2024.pdf": (
        "Master Circular on Health Insurance Business, 29 May 2024"
    ),
}


def governing_title(source_file):
    """Return a human-readable title for a governing source, if known."""
    return _TITLES.get(source_file, source_file)


def source_title(source_file):
    """Return a human-readable title for any known source."""
    return _TITLES.get(source_file, source_file)


# Aliases for discoverability.
cited_title = source_title
title_for = source_title


def topic_matches(rule, text=None, quote=None):
    """True if ``text``/``quote`` touches ``rule``'s topic.

    The cited ``quote`` is verbatim source text (always English),
    so it is matched in addition to claim + question: a governed
    topic in the quote triggers the governing check regardless of
    the claim's language (Fix 14). Unknown topic -> True.
    """
    keywords = _TOPIC_KEYWORDS.get(rule.get("topic"))
    if not keywords:
        return True
    combined = " ".join(
        str(p) for p in (text, quote) if p)
    if not combined:
        return False
    lowered = combined.lower()
    return any(k.lower() in lowered for k in keywords)


def governing_for(source_file, text=None, quote=None):
    """Return governing rules that supersede ``source_file``.

    If ``text`` (claim and/or question) and/or ``quote`` (the
    cited verbatim quote) is given, only rules whose topic that
    combined text touches are returned.
    """
    out = []
    for rule in REGISTRY:
        if source_file not in rule.get("supersedes", []):
            continue
        if (text is not None or quote is not None) and not topic_matches(
                rule, text, quote=quote):
            continue
        out.append(rule)
    return out


def is_superseded_source(source_file):
    """True if any rule supersedes ``source_file`` (any topic)."""
    return bool(governing_for(source_file))


def topic_detection_uncertain(source_file, claim=None, question=None,
                              quote=None, lang=None):
    """True when a superseded source's topic cannot be ruled out.

    Uncertain when no governing rule matched on claim+question+
    quote, yet the claim/question is in Hindi/Hinglish (``lang``
    is hi/hinglish, Devanagari is present, or Roman-Hindi markers
    are present) or no text was supplied at all. Pure-English
    claim/question/quote with no topic keyword is a certain
    non-match. Callers must fail closed (never VERIFY) when this
    is True for a superseded source (Fix 14).
    """
    if not is_superseded_source(source_file):
        return False
    if governing_for(source_file, text=" ".join(
            str(p) for p in (claim, question) if p), quote=quote):
        return False
    combined_claim_question = " ".join(
        str(p) for p in (claim, question) if p)
    if not combined_claim_question and not quote:
        return True
    if lang and str(lang).lower() in ("hi", "hinglish", "hindi"):
        return True
    if _contains_devanagari(combined_claim_question):
        return True
    if _contains_hinglish_marker(combined_claim_question):
        return True
    return False


# Aliases for discoverability.
find_governing = governing_for
governing_rules = governing_for


def is_superseded(source_file, text=None):
    """True if ``source_file`` is superseded (optionally on-topic)."""
    return bool(governing_for(source_file, text))
