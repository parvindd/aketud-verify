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
import os
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

# Honest provenance labels (Fix 30).
EXTRACTED_BY_MODEL = "Muse Spark"
EXTRACTED_BY_KEYWORD = "keyword safety net"
RULE_ONLY = "rule only (no model)"

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


_KIND_RULE = {
    "revival_guaranteed": 1,
    "payment_link": 1,
    "policy_status": 1,
    "revival_deadline": 2,
    "revival_fee": 3,
    "irdai_calling": 4,
}

_CANONICAL_CLAIMS = {
    "irdai_calling": (
        "Caller claims IRDAI is calling about a bonus/policy"),
    "revival_deadline": (
        "Caller claims the policy must be revived today or it "
        "will lapse forever"),
    "revival_guaranteed": "Caller claims revival is guaranteed",
    "revival_fee": "Caller claims a revival fee must be paid",
    "payment_link": "Caller asks for payment through a link",
    "policy_status": "Caller claims a specific policy status",
}


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
            "extracted_by": EXTRACTED_BY_KEYWORD,
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
            "guaranteed", "guarantee", "pakka", "गारंटी", "पक्का",
            "गारंटीड")):
        return "revival_guaranteed"
    if any(k in lowered for k in (
            "fee", "charge", "shulk", "शुल्क", "फीस", "फी", "चार्ज")):
        return "revival_fee"
    if "link" in lowered or "लिंक" in lowered:
        return "payment_link"
    if "irdai" in lowered or "bonus" in lowered or "बोनस" in lowered \
            or "आईआरडीएआई" in lowered or "इरडा" in lowered:
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
     ("guaranteed", "guarantee", "pakka", "pakki", "गारंटी", "पक्का",
      "गारंटीड")),
    ("revival_fee", 3, None,
     ("fee", "charge", "charges", "shulk", "शुल्क", "फीस", "फी",
      "चार्ज")),
    ("irdai_calling", 4, None,
     ("irdai", "bonus", "बोनस", "आईआरडीएआई", "इरडा", "पेंडिंग")),
    ("revival_deadline", 2, None,
     ("aaj hi", "today", "turant", "आज ही", "तुरंत", "तुरन्त",
      "रिवाइवल", "लैप्स")),
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
            "fee", "charge", "charges", "shulk", "शुल्क", "फीस",
            "फी", "चार्ज")):
        amount = _AMOUNT_RE.search(sentence)
        suffix = " (%s)" % amount.group(0) if amount else ""
        out.append(("revival_fee",
                    "Caller claims a revival fee must be paid%s" % suffix,
                    3, None))
    elif ("link" in lowered or "लिंक" in lowered):
        out.append(("payment_link",
                    "Caller asks for payment through a link", 1, None))
    if "irdai" in lowered or "bonus" in lowered or "बोनस" in lowered \
            or "आईआरडीएआई" in lowered or "इरडा" in lowered \
            or "पेंडिंग" in lowered:
        out.append(("irdai_calling",
                    "Caller claims IRDAI is calling about a bonus/policy",
                    4, None))
    if any(k in lowered for k in (
            "aaj hi", "today", "turant", "आज ही", "तुरंत", "तुरन्त",
            "रिवाइवल", "लैप्स")):
        scope = ("linked products only" if product == "linked"
                 else "non-linked products only")
        out.append(("revival_deadline",
                    "Caller claims the policy must be revived today or "
                    "it will lapse forever", 2, scope))
    if any(k in lowered for k in (
            "guaranteed", "guarantee", "pakka", "pakki",
            "गारंटी", "पक्का", "पक्की", "गारंटीड")):
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
                "extracted_by": EXTRACTED_BY_KEYWORD,
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
        return " ".join((plain.strip(), "(%s)" % citation))
    return plain.strip()


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
        kind = item.get("kind") or _infer_kind(claim)
        rule = item.get("rule")
        if not isinstance(rule, int):
            rule = _KIND_RULE.get(kind)
        entry = _rule_entry(rule, scope=item.get("scope")) \
            if isinstance(rule, int) else None
        source_file = item.get("source_file", item.get("source"))
        if not (isinstance(source_file, str) and source_file.strip()):
            source_file = (entry or {}).get("source_file")
        quote = item.get("quote")
        if not (isinstance(quote, str) and quote.strip()):
            quote = (entry or {}).get("quote")
        if not (isinstance(claim, str) and claim.strip()):
            claim = _CANONICAL_CLAIMS.get(kind)
        if not all(isinstance(v, str) and v.strip()
                   for v in (claim, source_file, quote)):
            continue
        out.append({
            "claim": claim, "kind": kind,
            "rule": rule, "source_file": source_file, "quote": quote,
            "citation": (item.get("citation")
                         or (entry or {}).get("citation", "")),
            "scope": (item.get("scope")
                      or (entry or {}).get("scope", "")),
            "extracted_by": (item.get("extracted_by")
                             or item.get("extraction_source") or ""),
        })
    return out


_CALL_PROPOSER_PROMPT = (
    "You extract the CALLER's claims from a call transcript. The "
    "transcript may be in Hindi (Devanagari), Hinglish (Roman Hindi) "
    "or English. Do not answer any question; extract only what the "
    "caller claims. Map each claim to one registered rule kind: "
    "revival_guaranteed (rule 1, revival guaranteed/pakka), "
    "revival_deadline (rule 2, revive today or lapse forever), "
    "revival_fee (rule 3, a revival fee/charge must be paid), "
    "irdai_calling (rule 4, IRDAI calling/selling/announcing a "
    "bonus), payment_link (rule 1, pay through a link sent by the "
    "caller), policy_status (rule 1, a specific policy status). "
    "Reply with strict JSON only: {{\"claims\": [{{\"kind\": "
    "\"<kind>\", \"rule\": <rule number>, \"claim\": \"<one "
    "caller claim, in English>\"}}]}}. If the caller makes none of "
    "these claims, return {{\"claims\": []}}.\n\n"
    "Language: {lang}\nTranscript: {transcript}"
)


def _expand_model_claims(parsed, transcript):
    """Map parsed model output onto the registered rules (Fix 30)."""
    if isinstance(parsed, str):
        import json as _json
        try:
            parsed = _json.loads(parsed)
        except (ValueError, TypeError):
            return {"claims": []}
    if not isinstance(parsed, dict):
        return {"claims": []}
    items = parsed.get("claims")
    if not isinstance(items, list):
        return {"claims": []}
    product = detect_product_type(transcript)
    amount = _AMOUNT_RE.search(str(transcript or ""))
    out, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or _infer_kind(
            item.get("claim", item.get("text")))
        rule = item.get("rule")
        if not isinstance(rule, int):
            rule = _KIND_RULE.get(kind)
        if kind not in _KIND_RULE or not isinstance(rule, int):
            continue
        if kind in seen:
            continue
        seen.add(kind)
        scope = item.get("scope")
        if kind == "revival_deadline" and not scope:
            scope = ("linked products only" if product == "linked"
                     else "non-linked products only")
        entry = _rule_entry(rule, scope=scope)
        if entry is None:
            continue
        claim = item.get("claim", item.get("text"))
        if not (isinstance(claim, str) and claim.strip()):
            claim = _CANONICAL_CLAIMS[kind]
        if kind == "revival_fee" and amount \
                and amount.group(0) not in claim:
            claim = "%s (%s)" % (
                _CANONICAL_CLAIMS[kind], amount.group(0))
        out.append({
            "claim": claim, "kind": kind, "rule": rule,
            "source_file": entry["source_file"],
            "quote": entry["quote"],
            "citation": entry.get("citation", ""),
            "scope": entry.get("scope", ""),
            "extracted_by": EXTRACTED_BY_MODEL,
        })
    return {"claims": out}


def make_call_proposer(model=None, *, timeout=60):
    """Build the live Muse Spark call-claim proposer (Fix 30).

    Reads ``META_API_KEY``, ``PROPOSER_MODEL`` and
    ``META_API_BASE_URL`` (Muse Spark, same env as the pipeline
    proposer); raises ``RuntimeError`` if unset. Not called by
    offline tests, which inject fake proposers. The returned
    callable is ``(transcript, lang) -> {"claims": [...]}`` with
    every claim mapped onto a registered rule's exact
    source/quote, and carries ``model`` / ``extracted_by``.
    """
    api_key = os.environ.get("META_API_KEY")
    model_id = model or os.environ.get("PROPOSER_MODEL") \
        or "muse-spark-1.3"
    base_url = os.environ.get("META_API_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError(
            "META_API_KEY, PROPOSER_MODEL and META_API_BASE_URL must "
            "be set to use the Muse Spark call proposer.")

    def proposer(transcript, lang):
        import requests  # allowed dependency; imported lazily

        prompt = _CALL_PROPOSER_PROMPT.format(
            lang=lang, transcript=transcript)
        resp = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={"model": model_id,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0},
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _expand_model_claims(content, transcript)

    proposer.model = model_id
    proposer.extracted_by = EXTRACTED_BY_MODEL
    proposer.label = EXTRACTED_BY_MODEL
    proposer.is_model = True
    return proposer


# Aliases for discoverability.
make_model_call_proposer = make_call_proposer
make_callcheck_proposer = make_call_proposer


_LOCALISED_CLAIMS = {
    "hinglish": {
        "irdai_calling": (
            "Caller ka daava: IRDAI bonus ke baare mein call kar "
            "raha hai"),
        "revival_deadline": (
            "Caller ka daava: policy aaj hi revive karni hai, "
            "warna hamesha ke liye lapse ho jayegi"),
        "revival_guaranteed": (
            "Caller ka daava: revival guaranteed hai"),
        "revival_fee": "Caller ka daava: revival fee pay karni hai",
        "payment_link": (
            "Caller ka daava: payment is link se karni hai"),
        "policy_status": (
            "Caller ka daava: aapki policy ki status tay hai"),
    },
    "hi": {
        "irdai_calling": (
            "कॉलर का दावा: आईआरडीएआई बोनस के बारे में कॉल कर "
            "रहा है"),
        "revival_deadline": (
            "कॉलर का दावा: पॉलिसी आज ही रिवाइव करनी है, वरना "
            "हमेशा के लिए लैप्स हो जाएगी"),
        "revival_guaranteed": "कॉलर का दावा: रिवाइवल की गारंटी है",
        "revival_fee": "कॉलर का दावा: रिवाइवल फ़ी देनी है",
        "payment_link": "कॉलर का दावा: पेमेंट इस लिंक से करनी है",
        "policy_status": "कॉलर का दावा: आपकी पॉलिसी की स्थिति तय है",
    },
}


def claim_label(claim, lang="en"):
    """Claim text for the final block, in the chosen language.

    English keeps the extracted claim verbatim; Hinglish/Hindi use
    a fixed localised label per claim kind (fee amounts preserved).
    Unknown kinds/languages fall back to the extracted claim.
    """
    if isinstance(claim, dict):
        text = str(claim.get("claim") or "")
        kind = claim.get("kind") or _infer_kind(text)
    else:
        text = str(claim or "")
        kind = _infer_kind(text)
    templates = _LOCALISED_CLAIMS.get(lang)
    if not templates:
        return text
    label = templates.get(kind)
    if not label:
        return text
    if kind == "revival_fee":
        amount = _AMOUNT_RE.search(text)
        if amount and amount.group(0) not in label:
            label = "%s (%s)" % (label, amount.group(0))
    return label


def check_call(transcript, lang=None, *, proposer=None, verifier=None,
               raw_dir=None, progress=None):
    """Check a fake-call ``transcript``; return the call trace.

    ``progress`` (Fix 39) is an optional ``(stage, detail)`` callback
    called as each stage starts: ``extract``, ``evidence``, ``verify``
    (per claim sent to the verifier), ``decision``. It only reports.

    ``proposer`` is ``(transcript, lang) -> draft`` extracting the
    caller's claims (injectable for offline tests); the default is
    :func:`extract_caller_claims`. ``verifier`` is a
    :class:`Verifier` or backend callable; with none, a deterministic
    verdict from the mapped rule's verified meaning is used. Every
    claim runs the deterministic evidence check first; the verifier
    is never consulted on failed evidence.

    Fix 30: the deterministic keyword pass runs AFTER the (model)
    proposer as a safety net. Each claim is labelled honestly:
    ``extracted_by`` is ``Muse Spark`` for proposer claims and
    ``keyword safety net`` for keyword/default claims, and
    ``verified_by`` is the verifier model or ``rule only
    (no model)``. The deterministic gate is final: a model
    ``SUPPORTED`` can never override a rule ``CONTRADICTED``, and
    fee claims with an unknown/non-linked product stay
    ``CANNOT BE CONFIRMED`` regardless of model output.
    """
    try:
        from verify.pipeline import emit_progress, normalize_lang
    except ImportError:
        from pipeline import emit_progress, normalize_lang
    lang = normalize_lang(lang, transcript)
    product = detect_product_type(transcript)
    trace = {"transcript": transcript, "question": transcript,
             "lang": lang, "product_type": product, "claims": [],
             "safety_advice": safety_advice_for(lang)}

    emit_progress(progress, "extract",
                  None if proposer is not None else EXTRACTED_BY_KEYWORD)
    if proposer is not None:
        proposer_label = (
            getattr(proposer, "extracted_by", None)
            or getattr(proposer, "label", None)
            or EXTRACTED_BY_MODEL)
        try:
            extracted = _normalise_proposer_claims(
                proposer(transcript, lang))
        except Exception:
            extracted = []
        for _c in extracted:
            if not _c.get("extracted_by"):
                _c["extracted_by"] = proposer_label
            _c["extraction_source"] = _c["extracted_by"]
    else:
        proposer_label = EXTRACTED_BY_KEYWORD
        extracted = extract_caller_claims(transcript)
        for _c in extracted:
            _c.setdefault("extracted_by", EXTRACTED_BY_KEYWORD)
            _c["extraction_source"] = _c["extracted_by"]
    # Fix 20/30: deterministic keyword pass AFTER model extraction,
    # as a safety net — no missed claims.
    extracted = list(extracted) + keyword_flagged_claims(
        transcript, extracted)
    for _c in extracted:
        _c.setdefault("extracted_by", EXTRACTED_BY_KEYWORD)
        _c.setdefault("extraction_source", _c["extracted_by"])

    if verifier is None:
        backend = None
    elif isinstance(verifier, Verifier):
        backend = verifier
    else:
        backend = Verifier(verifier)
    # Which model verified (Fix 27); no model in offline rule mode.
    if backend is not None:
        trace["verifier"] = backend.label
        trace["verifier_model"] = backend.model
        trace["verifier_fallback"] = backend.fallback
        if backend.model:
            configured_verified_by = "%s%s" % (
                backend.model,
                " (fallback)" if backend.fallback else "")
        else:
            configured_verified_by = str(
                backend.label).removeprefix("verifier: ") \
                or RULE_ONLY
    else:
        trace["verifier"] = "verifier: (deterministic rules, no model)"
        trace["verifier_model"] = None
        trace["verifier_fallback"] = None
        configured_verified_by = RULE_ONLY
    trace["verified_by"] = configured_verified_by
    trace["proposer"] = proposer_label
    trace["proposer_model"] = (
        getattr(proposer, "model", None) if proposer is not None
        else None)
    trace["proposer_label"] = proposer_label

    emit_progress(progress, "evidence", "%d claim(s)" % len(extracted))
    for item_no, item in enumerate(extracted, 1):
        entry = dict(item)
        entry.setdefault("kind", _infer_kind(entry.get("claim")))
        if not entry.get("extracted_by"):
            entry["extracted_by"] = EXTRACTED_BY_KEYWORD
        entry.setdefault("extraction_source", entry["extracted_by"])
        kind = entry["kind"]
        evidence = check_evidence(entry["source_file"], entry["quote"],
                                  raw_dir=raw_dir)
        entry["evidence"] = evidence
        entry["verifier_verdict"] = None
        entry["verifier_reason"] = None
        entry["verifier"] = trace["verifier"]
        entry["verifier_model"] = trace["verifier_model"]
        entry["verifier_fallback"] = trace["verifier_fallback"]
        entry["verified_by"] = RULE_ONLY
        entry["verification_source"] = RULE_ONLY
        entry["rule_verdict"] = _semantic_verdict(entry)["verdict"]

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
            emit_progress(progress, "verify", "claim %d of %d"
                          % (item_no, len(extracted)))
            result = backend.verify(
                entry["claim"], entry["quote"], source_text)
        else:
            result = _semantic_verdict(entry)
        entry["verifier_verdict"] = result["verdict"]
        entry["verifier_reason"] = result["reason"]
        # Fix 34: raw verifier text when its output was malformed.
        entry["verifier_raw_output"] = result.get("raw_output")
        entry["verifier"] = trace["verifier"]
        entry["verifier_model"] = trace["verifier_model"]
        entry["verifier_fallback"] = trace["verifier_fallback"]
        entry["verifier_usage"] = (
            backend.last_usage if backend is not None else None)
        entry["verifier_latency_s"] = (
            backend.last_latency_s if backend is not None else None)
        if backend is not None:
            entry["verified_by"] = configured_verified_by
            entry["verification_source"] = configured_verified_by
        entry["reason"] = _specific_reason(entry, product, lang)
        # Deterministic rule/evidence gate (Fix 30): a model verdict
        # can never turn a rule CONTRADICTS into SUPPORTED.
        if entry["rule_verdict"] == CONTRADICTED:
            entry["verdict"] = CONTRADICTS_RULES
        else:
            entry["verdict"] = _DISPLAY.get(
                result["verdict"], CANNOT_BE_CONFIRMED)
        trace["claims"].append(entry)

    emit_progress(progress, "decision")
    for _c in trace["claims"]:
        _c["verdict_label"] = verdict_label(_c.get("verdict", ""), lang)
        _c["claim_label"] = claim_label(_c, lang)
    lines = []
    if not trace["claims"]:
        lines.append("No caller claims could be checked: %s"
                     % verdict_label(CANNOT_BE_CONFIRMED, lang))
    for idx, claim in enumerate(trace["claims"], 1):
        lines.append("Claim %d: %s — %s" % (
            idx, claim.get("verdict_label", claim["verdict"]),
            claim.get("claim_label", claim["claim"])))
        lines.append("  %s" % (claim.get("reason") or ""))
    trace["final_block"] = "\n".join(lines + [
        "%s: %s" % (_SAFETY_LABEL.get(lang, "Safety advice"),
                    safety_advice_for(lang))])
    trace["final_answer"] = trace["final_block"]
    return trace


_KNOWN_DISPLAY_JOINS = (
    (re.compile(r"\btolodge\b", re.I), "to lodge"),
    (re.compile(r"\blinkse\b", re.I), "link se"),
    (re.compile(r"\bwithall\b", re.I), "with all"),
    (re.compile(r"\bmonthsof\b", re.I), "months of"),
    (re.compile(r"\bScheduleI\b"), "Schedule I"),
)


def normalise_display_text(text):
    """Normalise joined text for display only (Fix 26, Fix 29).

    Inserts a space where text was joined without one: after a
    comma before a letter, after a full stop before a capital
    (``karein.Caller`` -> ``karein. Caller``), between a lowercase
    and an uppercase letter (``ScheduleI`` -> ``Schedule I``),
    between a letter and a digit (either way), and for known
    joined phrases (``tolodge`` -> ``to lodge``, ``linkse`` ->
    ``link se``, ``withall`` -> ``with all``, ``monthsof`` ->
    ``months of``). Evidence matching and the stored trace are
    unchanged; this is applied only when rendering
    quotes/citations for display.
    """
    out = str(text or "")
    for pattern, replacement in _KNOWN_DISPLAY_JOINS:
        out = pattern.sub(replacement, out)
    out = re.sub(r",(?=[A-Za-z])", ", ", out)
    out = re.sub(r"(?<=[a-z])\.(?=[A-Z])", ". ", out)
    out = re.sub(r"([a-z])([A-Z])", r"\1 \2", out)
    out = re.sub(r"([A-Za-z])(\d)", r"\1 \2", out)
    out = re.sub(r"(\d)([A-Za-z])", r"\1 \2", out)
    return out


normalize_display_text = normalise_display_text


def _verifier_display(trace, claim=None):
    """Which model verified ``claim`` (Fix 27), for Stage 3/4."""
    claim = claim or {}
    model = claim.get("verifier_model") or trace.get("verifier_model")
    fallback = claim.get("verifier_fallback")
    if fallback is None:
        fallback = trace.get("verifier_fallback")
    if model:
        return "%s%s" % (model, " (fallback)" if fallback else "")
    label = claim.get("verifier") or trace.get("verifier") or ""
    return str(label).removeprefix("verifier: ") or "(not configured)"


def _verified_by_display(trace, claim=None):
    """``verified by`` value for ``claim`` (Fix 30)."""
    claim = claim or {}
    if claim.get("verified_by"):
        return str(claim["verified_by"])
    if claim.get("verifier_model") or trace.get("verifier_model"):
        return _verifier_display(trace, claim)
    return RULE_ONLY


def _extracted_by_display(trace, claim=None):
    """``extracted by`` value for ``claim`` (Fix 30)."""
    claim = claim or {}
    return str(claim.get("extracted_by")
               or claim.get("extraction_source")
               or EXTRACTED_BY_KEYWORD)


def format_call_trace(trace, *, color=False, show_transcript=True):
    """Render a call-check trace for the demo CLI."""
    transcript_line = (str(trace.get("transcript") or "")
                       if show_transcript else "from Stage 0")
    lines = ["Stage 1 — Call transcript",
             "--------------------------------",
             transcript_line, "",
             "Stage 2 — Caller claims (proposer, not an answer)",
             "---------------------------------------------------"]
    claims = trace.get("claims") or []
    if not claims:
        lines.append("(no caller claims extracted)")
    for idx, claim in enumerate(claims, 1):
        lines.append("%d. %s — rule %s (%s) — %s" % (
            idx, claim.get("claim", ""), claim.get("rule", "?"),
            normalise_display_text(claim.get("citation", "")),
            claim.get("source_file", "")))
        lines.append("   Quote: %s" % normalise_display_text(
            claim.get("quote", "")))
        lines.append("   extracted by: %s"
                     % _extracted_by_display(trace, claim))
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
        lines.append("  Verifier: %s" % _verifier_display(trace, claim))
        lines.append("  verified by: %s"
                     % _verified_by_display(trace, claim))
        lines.append("  extracted by: %s"
                     % _extracted_by_display(trace, claim))
    lines += ["", "Stage 4 — Per-claim verdicts",
              "----------------------------"]
    if not claims:
        lines.append(verdict_label(
            CANNOT_BE_CONFIRMED, trace.get("lang", "en")))
    for idx, claim in enumerate(claims, 1):
        lines.append("Claim %d: %s" % (
            idx, claim.get("verdict_label",
                           claim.get("verdict", ""))))
        lines.append("  Verifier: %s" % _verifier_display(trace, claim))
        lines.append("  verified by: %s"
                     % _verified_by_display(trace, claim))
        lines.append("  extracted by: %s"
                     % _extracted_by_display(trace, claim))
        lines.append("  %s" % normalise_display_text(
            claim.get("reason") or ""))
    lines += ["", "Final block", "-----------",
              normalise_display_text(trace.get("final_block") or "")]
    return "\n".join(lines)
