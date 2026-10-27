"""Fake revival-call check (Case D, verify Fix 18).

``check_call(transcript)`` extracts the CALLER'S claims from a call
transcript (not an answer to a question), maps each claim to a
verified rule in :data:`verify.authority.REGISTRY` with its exact
quote, and runs each claim through the same deterministic evidence
check and verifier as the answering pipeline.

Per-claim verdicts are exactly one of::

    SUPPORTED BY RULES
    CONTRADICTS RULES
    CANNOT BE CONFIRMED (ask insurer)

Only text marked verified in ``life-corpus/CASE_D_RULES.md`` is
encoded. Fee claims need a known product type: for linked (ULIP)
products rule 3 says no interest or fee on due premiums; for an
unknown product type the verdict is always CANNOT BE CONFIRMED,
and no "no fee" claim is ever made for non-linked policies (rule 1
allows charges or a late fee per the policy terms there).

This module never states whether a policy exists. The final block
always ends with safety advice, labelled as advice (not a rule),
directing the user to the insurer's official channels or Bima
Bharosa.
"""
import re

try:
    from verify.authority import REGISTRY, governing_title, rule_plain
    from verify.evidence import check_evidence, extract_text
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier)
except ImportError:  # run as top-level modules (cd verify)
    from authority import REGISTRY, governing_title, rule_plain
    from evidence import check_evidence, extract_text
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier)

SUPPORTED_BY_RULES = "SUPPORTED BY RULES"
CONTRADICTS_RULES = "CONTRADICTS RULES"
CANNOT_BE_CONFIRMED = "CANNOT BE CONFIRMED (ask insurer)"

SAFETY_ADVICE = (
    "We cannot see your policy. Check its status only with your "
    "insurer's official website/app/branch or Bima Bharosa. Do not "
    "pay through links sent by callers."
)

SAFETY_ADVICE_BY_LANG = {
    "en": SAFETY_ADVICE,
    "hinglish": (
        "Hum aapki policy nahi dekh sakte. Uski status sirf apne "
        "insurer ke official website/app/branch ya Bima Bharosa se "
        "check karein. Caller ke bheje hue link se payment na "
        "karein."),
    "hi": (
        "हम आपकी पॉलिसी नहीं देख सकते। इसका स्टेटस सिर्फ़ अपने "
        "इंश्योरर की ऑफ़िशियल वेबसाइट/ऐप/ब्रांच या बीमा भरोसा से "
        "चेक करें। कॉलर के भेजे हुए लिंक से पेमेंट न करें।"),
}

_VERDICT_LABELS = {
    "en": {
        SUPPORTED_BY_RULES: SUPPORTED_BY_RULES,
        CONTRADICTS_RULES: CONTRADICTS_RULES,
        CANNOT_BE_CONFIRMED: CANNOT_BE_CONFIRMED,
    },
    "hinglish": {
        SUPPORTED_BY_RULES: "Rules se supported",
        CONTRADICTS_RULES: "Rules ke khilaf",
        CANNOT_BE_CONFIRMED: "Confirm nahi ho sakta (insurer se poochhein)",
    },
    "hi": {
        SUPPORTED_BY_RULES: "नियमों द्वारा समर्थित",
        CONTRADICTS_RULES: "नियमों के विपरीत",
        CANNOT_BE_CONFIRMED: "पुष्टि नहीं हो सकती (इंश्योरर से पूछें)",
    },
}

_SAFETY_LABEL = {"en": "Safety advice", "hinglish": "Safety advice",
                 "hi": "सुरक्षा सलाह"}


def verdict_label(verdict, lang="en"):
    return _VERDICT_LABELS.get(lang, _VERDICT_LABELS["en"]).get(
        verdict, verdict)


def safety_advice_for(lang="en"):
    return SAFETY_ADVICE_BY_LANG.get(lang, SAFETY_ADVICE)

_DISPLAY = {
    SUPPORTED: SUPPORTED_BY_RULES,
    CONTRADICTED: CONTRADICTS_RULES,
}


def _rule_entries(rule):
    return [r for r in REGISTRY if r.get("rule") == rule]


def _rule_entry(rule, scope=None):
    entries = _rule_entries(rule)
    if scope:
        for entry in entries:
            if entry.get("scope") == scope:
                return entry
    return entries[0] if entries else None


def detect_product_type(transcript):
    """Return ``linked``, ``non-linked`` or ``unknown``."""
    lowered = str(transcript or "").lower()
    if any(k in lowered for k in (
            "non-linked", "non linked", "nonlinked", "endowment",
            "money back", "money-back", "traditional plan")):
        return "non-linked"
    if any(k in lowered for k in (
            "ulip", "unit linked", "unit-linked", "linked plan",
            "linked product", "linked policy")):
        return "linked"
    return "unknown"


_AMOUNT_RE = re.compile(
    r"(?:₹|rs\.?|rupees?)\s*[\d,]+|[\d,]+\s*(?:rupees?|rs\.?)", re.I)


def extract_caller_claims(transcript):
    """Deterministically extract caller claims from ``transcript``.

    This is the default (offline) proposer for call-check mode: it
    recognises the known fake-call patterns in English/Hinglish and
    maps each to its verified rule and exact quote. It extracts what
    the caller claims; it does not answer any question.
    """
    text = str(transcript or "")
    lowered = text.lower()
    product = detect_product_type(text)
    claims = []

    def add(kind, claim, rule, scope=None):
        entry = _rule_entry(rule, scope=scope)
        if entry is None:
            return
        claims.append({
            "claim": claim, "kind": kind, "rule": rule,
            "source_file": entry["source_file"],
            "quote": entry["quote"],
            "citation": entry.get("citation", ""),
            "scope": entry.get("scope", ""),
        })

    # Rule 4: IRDAI calling / selling / announcing a bonus.
    if "irdai" in lowered and any(k in lowered for k in (
            "call", "bonus", "sell", "policy", "investment",
            "कॉल", "बोनस", "बुला")):
        add("irdai_calling",
            "Caller claims IRDAI is calling about a bonus/policy",
            4)
    elif "bonus" in lowered or "बोनस" in lowered:
        add("irdai_calling",
            "Caller claims a bonus is being announced on the call", 4)

    # Rule 2: revive today or lapse forever / immediate deadline.
    deadline = any(k in lowered for k in (
        "revive today", "aaj hi revive", "aaj revive", "today or",
        "lapse forever", "forever lapse", "hamesha ke liye",
        "khatam ho jayegi", "khatam ho jayega", "last chance",
        "turant revive", "abhi revive", "revive now",
        "इसी समय", "आज ही"))
    revival = any(k in lowered for k in (
        "reviv", "lapse", "पुनः", "चालू"))
    if deadline and revival:
        scope = ("linked products only" if product == "linked"
                 else "non-linked products only")
        add("revival_deadline",
            "Caller claims the policy must be revived today or it "
            "will lapse forever", 2, scope=scope)

    # Rule 1: revival guaranteed / pakka (contradicts underwriting).
    if any(k in lowered for k in (
            "guaranteed", "guarantee", "pakka", "pakki",
            "गारंटी", "पक्का", "पक्की")):
        add("revival_guaranteed",
            "Caller claims revival is guaranteed", 1)

    # Rule 3 / fee: caller demands a revival fee or charge.
    fee_words = any(k in lowered for k in (
        "fee", "charge", "shulk", "शुल्क", "फीस"))
    if fee_words and (revival or _AMOUNT_RE.search(text)):
        amount = _AMOUNT_RE.search(text)
        suffix = " (%s)" % amount.group(0) if amount else ""
        add("revival_fee",
            "Caller claims a revival fee must be paid%s" % suffix, 3)
    elif any(k in lowered for k in ("link", "लिंक")) and any(
            k in lowered for k in ("pay", "payment", "भेज", "pay kar")):
        add("payment_link",
            "Caller asks for payment through a link", 1)

    # Policy existence/status: never confirmable here.
    if any(k in lowered for k in (
            "your policy is lapsed", "your policy has lapsed",
            "policy lapsed", "policy is active", "policy exists",
            "aapki policy lapse", "policy band ho")) and not claims:
        add("policy_status",
            "Caller claims a specific policy status", 1)
    return claims


def _infer_kind(claim_text):
    lowered = str(claim_text or "").lower()
    if any(k in lowered for k in (
            "guaranteed", "guarantee", "pakka", "गारंटी", "पक्का")):
        return "revival_guaranteed"
    if any(k in lowered for k in (
            "fee", "charge", "shulk", "शुल्क", "फीस")):
        return "revival_fee"
    if "link" in lowered or "लिंक" in lowered:
        return "payment_link"
    if "irdai" in lowered or "bonus" in lowered or "बोनस" in lowered:
        return "irdai_calling"
    if any(k in lowered for k in ("today", "forever", "aaj", "turant")):
        return "revival_deadline"
    if any(k in lowered for k in ("policy status", "lapsed", "exists")):
        return "policy_status"
    return ""


# --- Deterministic keyword pass (Fix 20) ---------------------------
# Flags every rule-checkable sentence the proposer did not extract.
_KEYWORD_GROUPS = (
    ("revival_guaranteed", 1, None,
     ("guaranteed", "guarantee", "pakka", "pakki", "गारंटी", "पक्का")),
    ("revival_fee", 3, None,
     ("fee", "charge", "charges", "shulk", "शुल्क", "फीस")),
    ("irdai_calling", 4, None,
     ("irdai", "bonus", "बोनस", "आईआरडीएआई")),
    ("revival_deadline", 2, None,
     ("aaj hi", "today", "turant", "आज ही", "तुरंत", "तुरन्त")),
    ("payment_link", 1, None, ("link", "लिंक")),
)

_SENTENCE_RE = re.compile(r"[^.!?।\n]+[.!?।]?")


def split_sentences(text):
    return [s.strip() for s in _SENTENCE_RE.findall(str(text or ""))
            if s.strip()]


def _classify_sentence(sentence, product):
    cands = _classify_sentence_all(sentence, product)
    return cands[0] if cands else None


def _classify_sentence_all(sentence, product):
    lowered = sentence.lower()
    out = []
    if any(k in lowered for k in (
            "fee", "charge", "charges", "shulk", "शुल्क", "फीस")):
        amount = _AMOUNT_RE.search(sentence)
        suffix = " (%s)" % amount.group(0) if amount else ""
        out.append(("revival_fee",
                    "Caller claims a revival fee must be paid%s" % suffix,
                    3, None))
    elif ("link" in lowered or "लिंक" in lowered):
        out.append(("payment_link",
                    "Caller asks for payment through a link", 1, None))
    if "irdai" in lowered or "bonus" in lowered or "बोनस" in lowered \
            or "आईआरडीएआई" in lowered:
        out.append(("irdai_calling",
                    "Caller claims IRDAI is calling about a bonus/policy",
                    4, None))
    if any(k in lowered for k in (
            "aaj hi", "today", "turant", "आज ही", "तुरंत", "तुरन्त")):
        scope = ("linked products only" if product == "linked"
                 else "non-linked products only")
        out.append(("revival_deadline",
                    "Caller claims the policy must be revived today or "
                    "it will lapse forever", 2, scope))
    if any(k in lowered for k in (
            "guaranteed", "guarantee", "pakka", "pakki",
            "गारंटी", "पक्का", "पक्की")):
        out.append(("revival_guaranteed",
                    "Caller claims revival is guaranteed", 1, None))
    return out


def keyword_flagged_claims(transcript, existing_claims):
    """Claims for flagged sentences not already extracted."""
    product = detect_product_type(transcript)
    existing_kinds = set()
    for item in existing_claims or []:
        kind = item.get("kind") or _infer_kind(item.get("claim"))
        if kind:
            existing_kinds.add(kind)
    out = []
    for sentence in split_sentences(transcript):
        for kind, claim, rule, scope in _classify_sentence_all(
                sentence, product):
            if kind in existing_kinds:
                continue
            entry = _rule_entry(rule, scope=scope)
            if entry is None:
                continue
            existing_kinds.add(kind)
            out.append({
                "claim": claim, "kind": kind, "rule": rule,
                "source_file": entry["source_file"],
                "quote": entry["quote"],
                "citation": entry.get("citation", ""),
                "scope": entry.get("scope", ""),
                "sentence": sentence,
            })
    return out


def _specific_reason(entry, product="unknown", lang="en"):
    """Plain rule statement + citation from authority (Fix 21)."""
    kind = entry.get("kind") or _infer_kind(entry.get("claim"))
    rule = entry.get("rule")
    reg = _rule_entry(rule, scope=entry.get("scope")) \
        if isinstance(rule, int) else None
    if reg is None and isinstance(rule, int):
        reg = _rule_entry(rule)
    citation = entry.get("citation") or (reg or {}).get("citation", "")
    if kind == "payment_link":
        if lang == "hi":
            return ("कॉलर के भेजे लिंक से पेमेंट की कोई सत्यापित "
                    "नियम पुष्टि नहीं करता।")
        if lang == "hinglish":
            return ("Caller ke bheje link se payment ki koi "
                    "verified rule confirmation nahi karta.")
        return ("No verified rule confirms paying through a link "
                "sent by a caller.")
    if kind == "policy_status":
        if lang == "hi":
            return "पॉलिसी का अस्तित्व/स्टेटस केवल इंश्योरर जानता है।"
        if lang == "hinglish":
            return "Policy ka existence/status sirf insurer jaanta hai."
        return ("Policy existence/status is known only to the "
                "insurer.")
    plain = rule_plain(reg, lang=lang, product=product) if reg else ""
    if kind == "revival_deadline" and product == "unknown":
        citation = (
            "IRDAI (Insurance Products) Regulations, 2024, "
            "Schedule I, 1.39 (non-linked) and 1.28 (linked)")
    if not plain:
        plain = "The mapped rule does not establish this claim."
    if kind == "revival_fee" and product != "linked":
        if lang == "hi":
            plain = ("%s यह नो-फ़ी नियम केवल लिंक्ड प्रोडक्ट्स पर "
                     "लागू है; प्रोडक्ट टाइप %s है, इसलिए इस फ़ी "
                     "दावे की नियमों से पुष्टि नहीं हो सकती।"
                     % (plain, product))
        elif lang == "hinglish":
            plain = ("%s Yeh no-fee rule sirf linked products par "
                     "hai; product type %s hai, isliye is fee claim "
                     "ki rules se confirmation nahi ho sakti."
                     % (plain, product))
        else:
            plain = ("%s This no-fee rule covers linked products "
                     "only; product type is %s, so this fee claim "
                     "cannot be confirmed from the rules."
                     % (plain, product))
    if citation:
        return "%s (%s)" % (plain, citation)
    return plain


def _semantic_verdict(entry):
    """Offline verdict from the mapped rule's verified meaning."""
    kind = entry.get("kind") or _infer_kind(entry.get("claim"))
    if kind in ("revival_deadline", "irdai_calling",
                "revival_guaranteed"):
        return {"verdict": CONTRADICTED,
                "reason": "The mapped rule states the opposite."}
    if kind == "revival_fee":
        return {"verdict": CONTRADICTED,
                "reason": "Linked revival collects due premiums "
                          "without interest or fee."}
    return {"verdict": INSUFFICIENT_EVIDENCE,
            "reason": "The mapped rule does not establish this claim."}


def _normalise_proposer_claims(draft):
    if isinstance(draft, str):
        import json
        try:
            draft = json.loads(draft)
        except (ValueError, TypeError):
            return []
    if not isinstance(draft, dict):
        return []
    items = draft.get("claims")
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim", item.get("text"))
        source_file = item.get("source_file", item.get("source"))
        quote = item.get("quote")
        if not all(isinstance(v, str) and v.strip()
                   for v in (claim, source_file, quote)):
            continue
        rule = item.get("rule")
        entry = _rule_entry(rule) if isinstance(rule, int) else None
        out.append({
            "claim": claim, "kind": item.get("kind", ""),
            "rule": rule, "source_file": source_file, "quote": quote,
            "citation": (item.get("citation")
                         or (entry or {}).get("citation", "")),
            "scope": (item.get("scope")
                      or (entry or {}).get("scope", "")),
        })
    return out


def check_call(transcript, lang=None, *, proposer=None, verifier=None,
               raw_dir=None):
    """Check a fake-call ``transcript``; return the call trace.

    ``proposer`` is ``(transcript, lang) -> draft`` extracting the
    caller's claims (injectable for offline tests); the default is
    :func:`extract_caller_claims`. ``verifier`` is a
    :class:`Verifier` or backend callable; with none, a deterministic
    verdict from the mapped rule's verified meaning is used. Every
    claim runs the deterministic evidence check first; the verifier
    is never consulted on failed evidence.
    """
    try:
        from verify.pipeline import normalize_lang
    except ImportError:
        from pipeline import normalize_lang
    lang = normalize_lang(lang, transcript)
    product = detect_product_type(transcript)
    trace = {"transcript": transcript, "question": transcript,
             "lang": lang, "product_type": product, "claims": [],
             "safety_advice": safety_advice_for(lang)}

    if proposer is not None:
        try:
            extracted = _normalise_proposer_claims(
                proposer(transcript, lang))
        except Exception:
            extracted = []
    else:
        extracted = extract_caller_claims(transcript)
    # Fix 20: deterministic keyword pass — no missed claims.
    extracted = list(extracted) + keyword_flagged_claims(
        transcript, extracted)

    if verifier is None:
        backend = None
    elif isinstance(verifier, Verifier):
        backend = verifier
    else:
        backend = Verifier(verifier)

    for item in extracted:
        entry = dict(item)
        entry.setdefault("kind", _infer_kind(entry.get("claim")))
        kind = entry["kind"]
        evidence = check_evidence(entry["source_file"], entry["quote"],
                                  raw_dir=raw_dir)
        entry["evidence"] = evidence
        entry["verifier_verdict"] = None
        entry["verifier_reason"] = None

        # Scope guardrails (fail closed, before any verdict display).
        if kind == "payment_link":
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = _specific_reason(entry, product, lang)
            trace["claims"].append(entry)
            continue
        if kind == "policy_status":
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = _specific_reason(entry, product, lang)
            trace["claims"].append(entry)
            continue
        if kind == "revival_fee" and product != "linked":
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = _specific_reason(entry, product, lang)
            trace["claims"].append(entry)
            continue
        if not (evidence["exists"] and evidence["found"]):
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = (
                "%s Evidence check failed (exists=%s, found=%s)."
                % (_specific_reason(entry, product, lang),
                   evidence["exists"], evidence["found"]))
            trace["claims"].append(entry)
            continue
        source_text = extract_text(entry["source_file"], raw_dir=raw_dir)
        if backend is not None:
            result = backend.verify(
                entry["claim"], entry["quote"], source_text)
        else:
            result = _semantic_verdict(entry)
        entry["verifier_verdict"] = result["verdict"]
        entry["verifier_reason"] = result["reason"]
        entry["reason"] = _specific_reason(entry, product, lang)
        entry["verdict"] = _DISPLAY.get(
            result["verdict"], CANNOT_BE_CONFIRMED)
        trace["claims"].append(entry)

    for _c in trace["claims"]:
        _c["verdict_label"] = verdict_label(_c.get("verdict", ""), lang)
    lines = []
    if not trace["claims"]:
        lines.append("No caller claims could be checked: %s"
                     % verdict_label(CANNOT_BE_CONFIRMED, lang))
    for idx, claim in enumerate(trace["claims"], 1):
        lines.append("Claim %d: %s — %s" % (
            idx, claim.get("verdict_label", claim["verdict"]),
            claim["claim"]))
        lines.append("  %s" % (claim.get("reason") or ""))
    trace["final_block"] = "\n".join(lines + [
        "%s: %s" % (_SAFETY_LABEL.get(lang, "Safety advice"),
                    safety_advice_for(lang))])
    trace["final_answer"] = trace["final_block"]
    return trace


def format_call_trace(trace, *, color=False):
    """Render a call-check trace for the demo CLI."""
    lines = ["Stage 1 — Call transcript",
             "--------------------------------",
             str(trace.get("transcript") or ""), "",
             "Stage 2 — Caller claims (proposer, not an answer)",
             "---------------------------------------------------"]
    claims = trace.get("claims") or []
    if not claims:
        lines.append("(no caller claims extracted)")
    for idx, claim in enumerate(claims, 1):
        lines.append("%d. %s — rule %s (%s) — %s" % (
            idx, claim.get("claim", ""), claim.get("rule", "?"),
            claim.get("citation", ""), claim.get("source_file", "")))
        lines.append("   Quote: %s" % claim.get("quote", ""))
    lines += ["", "Stage 3 — Evidence check + verifier (per claim)",
              "-----------------------------------------------"]
    if not claims:
        lines.append("(no claims to check)")
    for idx, claim in enumerate(claims, 1):
        evidence = claim.get("evidence") or {}
        found = bool(evidence.get("exists") and evidence.get("found"))
        lines.append("Claim %d: evidence %s (exists=%s, found=%s); "
                     "verifier %s" % (
                         idx, "FOUND" if found else "NOT FOUND",
                         evidence.get("exists"), evidence.get("found"),
                         claim.get("verifier_verdict") or "(not run)"))
    lines += ["", "Stage 4 — Per-claim verdicts",
              "----------------------------"]
    if not claims:
        lines.append(verdict_label(
            CANNOT_BE_CONFIRMED, trace.get("lang", "en")))
    for idx, claim in enumerate(claims, 1):
        lines.append("Claim %d: %s" % (
            idx, claim.get("verdict_label",
                           claim.get("verdict", ""))))
        lines.append("  %s" % (claim.get("reason") or ""))
    lines += ["", "Final block", "-----------",
              str(trace.get("final_block") or "")]
    return "\n".join(lines)
