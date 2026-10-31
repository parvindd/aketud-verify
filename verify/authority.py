"""Governing-authority registry (verify Fix 2).

A small registry of governing rules. Each entry is::

    {topic, source_file, quote, issuer, effective_date,
     published, signed, gazette,
     supersedes: [source_file, ...]}

``effective_date`` is the date the rule is in force from;
``published`` is its Gazette publication date and ``signed``
the date it was signed. These are distinct dates and must not
be conflated.

Fix 36 — sale-date aware precedence: every rule carries
``applies_from`` (the date from which it governs newly sold
contracts) and, where the issuing regulation has one, a
``savings_quote`` / ``savings_source`` / ``savings_citation``: the
clause saying contracts entered into earlier are not invalidated
(IRDAI (Insurance Products) Regulations 2024, reg 9(3)). The
savings quote is evidence-checked against its PDF like any quote.

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

# Case D life rules: exact quotes from life-corpus/CASE_D_RULES.md
# (read from life-corpus/raw/ PDFs, 27 Oct 2026). Only the clean
# span is quoted for rule 4.
_LIFE_REGULATIONS = "irdai-insurance-products-regulations-2024.pdf"
_LIFE_MASTER = "mc-life-insurance-products-2024.pdf"
_ADVERTISEMENTS_2019 = "mc-insurance-advertisements-2019.pdf"

_RULE1_QUOTE = (
    '"Revival of a policy" means restoration of the policy, which '
    "was discontinued due to the non-payment of premium, by the "
    "insurer with all the benefits mentioned in the policy document, "
    "with or without rider benefits if any, upon the receipt of all "
    "the premiums due and other charges or late fee if any, during "
    "the revival period, as per the terms and conditions of the "
    "policy, upon being satisfied as to the continued insurability "
    "of the insured or policyholder on the basis of the information, "
    "documents and reports furnished by the policyholder, in "
    "accordance with Board approved underwriting policy."
)
_RULE2_LINKED_QUOTE = (
    '"Revival period" means the period of three consecutive '
    "complete years from the date of first unpaid premium."
)
_RULE2_NONLINKED_QUOTE = (
    '"Revival period" means the period of five consecutive '
    "complete years from the date of first unpaid premium."
)
_RULE3_QUOTE = (
    "shall collect all due and unpaid premiums without charging "
    "any interest or fee"
)
_RULE4_QUOTE = (
    "is not involved in activities like selling insurance policies, "
    "announcing bonus or investment of premiums. Public receiving "
    "such phone calls are requested to lodge a police complaint."
)

# Fix 36: savings clause, IRDAI (Insurance Products) Regulations,
# 2024, regulation 9 "Repeal and Savings", sub-regulation (3) — read
# from the PDF 31 Oct 2026. The regulations are in force from the
# later of Gazette publication (22 Mar 2024) and 1 April 2024
# (reg 1(2)), i.e. 2024-04-01.
_SAVINGS_QUOTE = (
    "Unless otherwise mentioned herein, nothing in these regulations "
    "shall be deemed to invalidate the insurance contracts entered "
    "into prior to these regulations coming into force."
)
_SAVINGS_CITATION = (
    "IRDAI (Insurance Products) Regulations, 2024, Regulation 9(3)")
_PRODUCTS_SAVINGS = {
    "applies_from": "2024-04-01",
    "savings_quote": _SAVINGS_QUOTE,
    "savings_source": "irdai-insurance-products-regulations-2024.pdf",
    "savings_citation": _SAVINGS_CITATION,
    "savings_ref": "Reg 9(3)",
}
_NO_SAVINGS = {"savings_quote": None, "savings_source": None,
               "savings_citation": None, "savings_ref": None}

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
        "short_ref": "Reg 7",
        **_PRODUCTS_SAVINGS,
    },
    {
        "rule": 1,
        "topic": "life revival by insurer underwriting",
        "source_file": _LIFE_REGULATIONS,
        "quote": _RULE1_QUOTE,
        "issuer": "IRDAI",
        "effective_date": "2024-04-01",
        "published": "2024-03-22",
        "signed": "2024-03-20",
        "gazette": "Gazette No. 206",
        "supersedes": [],
        **_PRODUCTS_SAVINGS,
        "scope": "life policies",
        "citation": (
            "IRDAI (Insurance Products) Regulations, 2024, "
            "Schedule I, 1.10"),
        "plain": (
            "Revival is done by the insurer, and only after the "
            "insurer is satisfied about continued insurability "
            "under its underwriting policy; revival is not "
            "guaranteed."),
        "plain_hi": (
            "रिवाइवल इंश्योरर करता है, और केवल तब जब इंश्योरर "
            "अपनी अंडरराइटिंग पॉलिसी के तहत कंटिन्यूड "
            "इंश्योरेबिलिटी से संतुष्ट हो; रिवाइवल की गारंटी "
            "नहीं है।"),
        "plain_hinglish": (
            "Revival insurer karta hai, aur sirf tab jab insurer "
            "apni underwriting policy ke under continued "
            "insurability se satisfied ho; revival guaranteed "
            "nahi hai."),
    },
    {
        "rule": 2,
        "topic": "life revival period linked",
        "source_file": _LIFE_REGULATIONS,
        "quote": _RULE2_LINKED_QUOTE,
        "value": "three years",
        "extracted_value": "three consecutive complete years",
        "issuer": "IRDAI",
        "effective_date": "2024-04-01",
        "published": "2024-03-22",
        "signed": "2024-03-20",
        "gazette": "Gazette No. 206",
        "supersedes": [],
        **_PRODUCTS_SAVINGS,
        "scope": "linked products only",
        "citation": (
            "IRDAI (Insurance Products) Regulations, 2024, "
            "Schedule I, 1.28"),
        "plain": (
            "Revival period is 3 years (linked) from the first "
            "unpaid premium."),
    },
    {
        "rule": 2,
        "topic": "life revival period non-linked",
        "source_file": _LIFE_REGULATIONS,
        "quote": _RULE2_NONLINKED_QUOTE,
        "value": "five years",
        "extracted_value": "five consecutive complete years",
        "issuer": "IRDAI",
        "effective_date": "2024-04-01",
        "published": "2024-03-22",
        "signed": "2024-03-20",
        "gazette": "Gazette No. 206",
        "supersedes": [],
        **_PRODUCTS_SAVINGS,
        "scope": "non-linked products only",
        "citation": (
            "IRDAI (Insurance Products) Regulations, 2024, "
            "Schedule I, 1.39"),
        "plain": (
            "Revival period is 5 years (non-linked) from the "
            "first unpaid premium."),
    },
    {
        "rule": 3,
        "topic": "linked revival no interest or fee",
        "source_file": _LIFE_MASTER,
        "quote": _RULE3_QUOTE,
        "issuer": "IRDAI",
        "effective_date": "2024-06-12",
        "published": "2024-06-12",
        "supersedes": [],
        "applies_from": "2024-06-12",
        **_NO_SAVINGS,
        "scope": "linked products only",
        "citation": (
            "Master Circular on Life Insurance Products, "
            "12 June 2024, Part C, para 40"),
        "plain": (
            "For linked products, the insurer collects all due "
            "and unpaid premiums without charging any interest "
            "or fee."),
        "plain_hi": (
            "लिंक्ड प्रोडक्ट्स के लिए, इंश्योरर सभी ड्यू और "
            "अनपेड प्रीमियम्स बिना किसी इंटरेस्ट या फ़ी के "
            "लेता है।"),
        "plain_hinglish": (
            "Linked products ke liye, insurer saare due aur "
            "unpaid premiums bina kisi interest ya fee ke leta "
            "hai."),
    },
    {
        "rule": 4,
        "topic": "IRDAI does not sell policies or announce bonus",
        "source_file": _ADVERTISEMENTS_2019,
        "quote": _RULE4_QUOTE,
        "issuer": "IRDAI",
        "effective_date": "2019-10-16",
        "published": "2019-10-16",
        "supersedes": [],
        "applies_from": "2019-10-16",
        **_NO_SAVINGS,
        "scope": "public notice on spurious calls (2019)",
        "citation": (
            "Master Circular on Insurance Advertisements, "
            "16 Oct 2019, para 15"),
        "status_note": (
            "2019 date; status after 2024 consolidation "
            "NOT confirmed"),
        "plain": (
            "IRDAI is not involved in selling insurance policies, "
            "announcing bonus or investment of premiums."),
        "plain_hi": (
            "आईआरडीएआई इंश्योरेंस पॉलिसीज़ बेचने, बोनस अनाउंस "
            "करने या प्रीमियम्स के इन्वेस्टमेंट में शामिल नहीं "
            "है।"),
        "plain_hinglish": (
            "IRDAI insurance policies bechne, bonus announce "
            "karne ya premiums ke investment mein shaamil nahi "
            "hai."),
    },
]

# Alias: the registry under a second common name.
RULES = REGISTRY


def rule_entry(rule, scope=None):
    entries = [r for r in REGISTRY if r.get("rule") == rule]
    if scope:
        for entry in entries:
            if entry.get("scope") == scope:
                return entry
    return entries[0] if entries else None


def revival_period_plain(product="unknown", lang="en"):
    """Plain revival-period statement; both periods if unknown."""
    if lang == "hi":
        if product == "linked":
            return ("रिवाइवल पीरियड पहले अनपेड प्रीमियम से "
                    "3 साल (लिंक्ड) है।")
        if product == "non-linked":
            return ("रिवाइवल पीरियड पहले अनपेड प्रीमियम से "
                    "5 साल (नॉन-लिंक्ड) है।")
        return ("रिवाइवल पीरियड पहले अनपेड प्रीमियम से "
                "5 साल (नॉन-लिंक्ड) या 3 साल (लिंक्ड) है।")
    if lang == "hinglish":
        if product == "linked":
            return ("Revival period pehle unpaid premium se "
                    "3 years (linked) hai.")
        if product == "non-linked":
            return ("Revival period pehle unpaid premium se "
                    "5 years (non-linked) hai.")
        return ("Revival period pehle unpaid premium se "
                "5 years (non-linked) ya 3 years (linked) hai.")
    if product == "linked":
        return ("Revival period is 3 years (linked) from the "
                "first unpaid premium.")
    if product == "non-linked":
        return ("Revival period is 5 years (non-linked) from "
                "the first unpaid premium.")
    return ("Revival period is 5 years (non-linked) or 3 years "
            "(linked) from the first unpaid premium.")


def rule_plain(entry, lang="en", product="unknown"):
    """Plain-language statement of ``entry``'s rule (Fix 21)."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("rule") == 2:
        if product == "unknown":
            return revival_period_plain("unknown", lang)
        return revival_period_plain(product, lang)
    if lang == "hi":
        return entry.get("plain_hi", entry.get("plain", ""))
    if lang == "hinglish":
        return entry.get("plain_hinglish", entry.get("plain", ""))
    return entry.get("plain", "")

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
    "mc-life-insurance-products-2024.pdf": (
        "Master Circular on Life Insurance Products, 12 June 2024"
    ),
    "mc-insurance-advertisements-2019.pdf": (
        "Master Circular on Insurance Advertisements, "
        "16 Oct 2019 (IRDAI/LIFE/CIR/MISC/189/10/2019)"
    ),
}


# Short names for a cited (superseded) source in final answers.
_SHORT_NAMES = {
    "arogya-sanjeevani-hdfc-ergo.pdf": {
        "en": "the specimen", "hi": "स्पेसिमेन",
        "hinglish": "specimen"},
}


def short_source_name(source_file, lang="en"):
    """Short name of a cited source (e.g. ``the specimen``)."""
    names = _SHORT_NAMES.get(source_file)
    if names:
        return names.get(lang, names["en"])
    return source_title(source_file)


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
