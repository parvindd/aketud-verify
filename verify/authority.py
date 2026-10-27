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
_TOPIC_KEYWORDS = {
    "PED waiting period": (
        "ped", "pre-existing", "pre existing", "preexisting",
    ),
}

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


def topic_matches(rule, text):
    """True if ``text`` touches ``rule``'s topic (or topic unknown)."""
    keywords = _TOPIC_KEYWORDS.get(rule.get("topic"))
    if not keywords:
        return True
    if not text:
        return False
    lowered = str(text).lower()
    return any(k in lowered for k in keywords)


def governing_for(source_file, text=None):
    """Return governing rules that supersede ``source_file``.

    If ``text`` (claim and/or question) is given, only rules whose
    topic the text touches are returned.
    """
    out = []
    for rule in REGISTRY:
        if source_file not in rule.get("supersedes", []):
            continue
        if text is not None and not topic_matches(rule, text):
            continue
        out.append(rule)
    return out


# Aliases for discoverability.
find_governing = governing_for
governing_rules = governing_for


def is_superseded(source_file, text=None):
    """True if ``source_file`` is superseded (optionally on-topic)."""
    return bool(governing_for(source_file, text))
