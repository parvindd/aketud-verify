"""Fail-closed answering pipeline (hackathon Step 3).

``answer(question, lang)`` runs:

1. a proposer (Muse Spark via the Meta Model API) drafts claims, each
   with ``source_file`` + ``quote``;
2. :func:`evidence.check_evidence` on every claim — deterministic,
   and never overridden by any model;
3. :func:`verifier.verify_claim` on every claim that passed evidence;
4. a final decision:

   - ``VERIFIED`` — every claim ``SUPPORTED`` (and at least one claim);
     when a governing rule applies, only a governing ``SUPPORTED``
     counts — governing ``INSUFFICIENT_EVIDENCE`` is a refusal and
     the superseded source's verdict is never used;
   - ``REFUSED`` — any claim with failed evidence or
     ``INSUFFICIENT_EVIDENCE`` (including a malformed draft, a proposer
     or verifier failure, or no claims at all). Every ``REFUSED``
     trace carries ``refusal_reason`` and a user-facing
     ``final_answer`` (never ``None``);
   - ``SUPERSEDED`` — a claim faithful to its own source
     (``SUPPORTED`` against that source) but contradicted only by a
     governing rule that supersedes that source: the decision is
     ``SUPERSEDED``, not ``CONTRADICTED``/``CORRECTED``. The trace
     keeps the verifier's verdict on the cited source unchanged in
     ``verdict``/``verifier_verdict`` and the governing verdict
     separately in ``governing_verdict``; only the final decision
     combines them;
   - ``CORRECTED`` — any claim ``CONTRADICTED`` by its own cited
     source with no refusal trigger: the correction uses only the
     verifier's reason and the source name, never the claim's own
     quote.

Fail closed: anything not proven ``SUPPORTED`` is never shown as
verified. A ``REFUSED`` result carries no verified answer text; its
``final_answer`` is the refusal message described above.

The proposer and verifier are injectable callables so tests run
offline with mocks. The default proposer reads ``META_API_KEY``,
``PROPOSER_MODEL`` and ``META_API_BASE_URL``. The default verifier
reads its own env (``VERIFIER_BASE_URL`` / ``VERIFIER_API_KEY`` /
``VERIFIER_MODEL``, Muse Spark Open on Modal) and falls back to
the Meta Model API verifier when ``VERIFIER_*`` are unset; the
trace then says ``verifier: muse-spark-1.3 (fallback)`` (Fix 27).
No real model is called unless the env is set and the defaults
are used. Every trace carries ``verifier`` (label), ``verifier_model``
and ``verifier_fallback``, mirrored per claim, plus the verifier
response ``usage``/latency when a live backend recorded them.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

try:
    from verify.authority import (REGISTRY, effective_display,
                                  governing_for, governing_title,
                                  source_title,
                                  topic_detection_uncertain)
    from verify.evidence import check_evidence, extract_text
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier, make_model_backend,
                                 verifier_label)
except ImportError:  # run as top-level modules (cd verify; unittest)
    from authority import (REGISTRY, effective_display, governing_for,
                           governing_title, source_title,
                           topic_detection_uncertain)
    from evidence import check_evidence, extract_text
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier, make_model_backend,
                          verifier_label)

VERIFIED = "VERIFIED"
REFUSED = "REFUSED"
CORRECTED = "CORRECTED"
SUPERSEDED = "SUPERSEDED"

REFUSAL_NO_API_KEY = "no API key"
REFUSAL_PROPOSER_ERROR = "proposer error"
REFUSAL_NO_CLAIMS = "no claims"
REFUSAL_EVIDENCE_NOT_FOUND = "evidence not found"
REFUSAL_VERIFIER_INSUFFICIENT = "verifier insufficient"
REFUSAL_GOVERNING_INSUFFICIENT = "governing insufficient"

REFUSAL_PREFIX = "I can't confirm this from the official documents I have."

_REFUSAL_DETAILS = {
    REFUSAL_NO_API_KEY: "No API key is configured.",
    REFUSAL_PROPOSER_ERROR: "The draft generator failed.",
    REFUSAL_NO_CLAIMS: "The draft contained no claims to verify.",
    REFUSAL_EVIDENCE_NOT_FOUND: (
        "The cited evidence was not found in the official documents."),
    REFUSAL_VERIFIER_INSUFFICIENT: (
        "The verifier could not confirm the claim from the cited passage."),
    REFUSAL_GOVERNING_INSUFFICIENT: (
        "The governing document could not confirm the claim."),
}


_LANG_ALIASES = {
    "en": "en", "english": "en", "hi": "hi", "hindi": "hi",
    "hinglish": "hinglish",
}

_REFUSAL_TEMPLATES = {
    "hi": (
        "मैं इसकी पुष्टि मेरे पास मौजूद आधिकारिक दस्तावेज़ों से "
        "नहीं कर सकता।",
        {
            REFUSAL_NO_API_KEY: "कोई API कुंजी कॉन्फ़िगर नहीं है।",
            REFUSAL_PROPOSER_ERROR: "ड्राफ़्ट जनरेटर विफल रहा।",
            REFUSAL_NO_CLAIMS: (
                "ड्राफ़्ट में सत्यापित करने के लिए कोई दावा नहीं था।"),
            REFUSAL_EVIDENCE_NOT_FOUND: (
                "उद्धृत साक्ष्य आधिकारिक दस्तावेज़ों में नहीं मिला।"),
            REFUSAL_VERIFIER_INSUFFICIENT: (
                "सत्यापनकर्ता उद्धृत अंश से दावे की पुष्टि नहीं "
                "कर सका।"),
            REFUSAL_GOVERNING_INSUFFICIENT: (
                "शासी दस्तावेज़ दावे की पुष्टि नहीं कर सका।"),
        },
    ),
    "hinglish": (
        "Main iski confirmation apne paas maujood official "
        "documents se nahi kar sakta.",
        {
            REFUSAL_NO_API_KEY: "Koi API key configured nahi hai.",
            REFUSAL_PROPOSER_ERROR: "Draft generator fail ho gaya.",
            REFUSAL_NO_CLAIMS: (
                "Draft mein verify karne ke liye koi claim nahi tha."),
            REFUSAL_EVIDENCE_NOT_FOUND: (
                "Cited evidence official documents mein nahi mila."),
            REFUSAL_VERIFIER_INSUFFICIENT: (
                "Verifier cited passage se claim confirm nahi "
                "kar saka."),
            REFUSAL_GOVERNING_INSUFFICIENT: (
                "Governing document claim confirm nahi kar saka."),
        },
    ),
}


def _contains_devanagari(text):
    return bool(text) and any(
        "\u0900" <= ch <= "\u097f" for ch in str(text))


def detect_lang(text):
    """Auto-detect: Devanagari text -> ``hi``, else ``en``."""
    return "hi" if _contains_devanagari(text) else "en"


def normalize_lang(lang=None, text=None):
    """Normalise ``lang`` to en|hi|hinglish (auto-detect if unset)."""
    if lang is None or (isinstance(lang, str)
                        and lang.strip().lower() in ("", "auto")):
        return detect_lang(text)
    return _LANG_ALIASES.get(str(lang).strip().lower(), "en")


# Alias for discoverability.
resolve_lang = normalize_lang

_VALUE_RE = re.compile(r"(\d+\s*(?:months?|days?|years?))", re.I)


def _extract_value(text):
    """Extract a duration value (e.g. '36 months') from ``text``."""
    if not text:
        return None
    match = _VALUE_RE.search(str(text))
    return " ".join(match.group(1).split()) if match else None


def _hindi_value(value):
    """Render a duration value in Hindi (e.g. 36 months -> 36 महीने)."""
    if not value:
        return value
    text = str(value)
    text = text.replace("months", "महीने").replace("month", "महीना")
    return text


def _is_ped_text(*texts):
    combined = " ".join(str(t) for t in texts if t).lower()
    return any(k in combined for k in (
        "ped", "pre-existing", "pre existing", "preexisting",
        "प्री-एग्ज़िस्टिंग", "पूर्व-मौजूदा", "पीईडी"))


def _build_verified(entries, lang="en"):
    """Fixed-template verified answer (Fix 15).

    English keeps claim + source. Hindi/Hinglish PED answers use a
    fixed template (never model text for the final sentence);
    English insurance terms are Devanagari in Hindi and Roman in
    Hinglish, while the citation stays in English.
    """
    if lang not in ("hi", "hinglish"):
        return " ".join(
            "%s (Source: %s)" % (e["claim"], e["source_file"])
            for e in entries)
    parts = []
    for e in entries:
        value = (_extract_value(e.get("quote"))
                 or _extract_value(e.get("claim")))
        if value and _is_ped_text(e.get("claim"), e.get("quote")):
            if lang == "hi":
                parts.append(
                    "प्री-एग्ज़िस्टिंग डिज़ीज़ के लिए वेटिंग पीरियड "
                    "अधिकतम %s है। (Source: %s)"
                    % (_hindi_value(value), e["source_file"]))
            else:
                parts.append(
                    "Pre-existing disease ke liye waiting period "
                    "maximum %s hai. (Source: %s)"
                    % (value, e["source_file"]))
        elif lang == "hi":
            parts.append(
                "सत्यापित: %s (Source: %s)"
                % (e["claim"], e["source_file"]))
        else:
            parts.append(
                "Verified: %s (Source: %s)"
                % (e["claim"], e["source_file"]))
    return " ".join(parts)


def _build_superseded(records, lang="en"):
    parts = []
    for rec in records:
        if lang == "hi":
            sentence = (
                "वर्तमान नियम: प्री-एग्ज़िस्टिंग डिज़ीज़ के लिए "
                "वेटिंग पीरियड अधिकतम %s है (%s)। %s में अभी भी "
                "%s कहा गया है, लेकिन आईआरडीएआई का 2024 नियम इसे "
                "ओवरराइड करता है."
                % (_hindi_value(rec["governing_value"]),
                   rec["governing_title"],
                   rec["cited_title"], _hindi_value(rec["cited_value"])))
        elif lang == "hinglish":
            sentence = (
                "Ab ka rule: Pre-existing disease ke liye waiting "
                "period maximum %s hai (%s). %s mein abhi bhi %s "
                "hai, lekin IRDAI ka 2024 regulation ise override "
                "karta hai."
                % (rec["governing_value"], rec["governing_title"],
                   rec["cited_title"], rec["cited_value"]))
        else:
            sentence = (
                "Current rule: maximum %s (%s). %s still says %s, "
                "but the 2024 regulation overrides it."
                % (rec["governing_value"], rec["governing_title"],
                   rec["cited_title"], rec["cited_value"]))
        parts.append(sentence + "\n" + rec["governing_quote"])
    return "\n".join(parts)


def _build_corrected(records, lang="en"):
    parts = []
    for rec in records:
        if rec.get("governing_quote"):
            if lang == "hi":
                parts.append(
                    "वेटिंग पीरियड के लिए शासी स्रोत (%s) के अनुसार "
                    "अधिकतम %s है।\n%s" % (
                        rec["governing_title"],
                        _hindi_value(rec["governing_value"]),
                        rec["governing_quote"]))
            elif lang == "hinglish":
                parts.append(
                    "Waiting period ke liye governing source (%s) "
                    "ke anusar maximum %s hai.\n%s" % (
                        rec["governing_title"],
                        rec["governing_value"],
                        rec["governing_quote"]))
            else:
                parts.append(
                    "The governing source (%s) says the maximum is %s."
                    "\n%s" % (rec["governing_title"],
                              rec["governing_value"],
                              rec["governing_quote"]))
        elif rec.get("value"):
            if lang == "hi":
                parts.append(
                    "उद्धृत स्रोत (%s) के अनुसार अधिकतम %s है।\n%s"
                    % (rec["cited_title"], _hindi_value(rec["value"]),
                       rec["quote"]))
            elif lang == "hinglish":
                parts.append(
                    "Cited source (%s) ke anusar maximum %s hai.\n%s"
                    % (rec["cited_title"], rec["value"], rec["quote"]))
            else:
                parts.append(
                    "The cited source (%s) says the maximum is %s.\n%s"
                    % (rec["cited_title"], rec["value"], rec["quote"]))
        else:
            if lang == "hi":
                parts.append(
                    "उद्धृत स्रोत (%s) कहता है:\n%s"
                    % (rec["cited_title"], rec["quote"]))
            elif lang == "hinglish":
                parts.append(
                    "Cited source (%s) kehta hai:\n%s"
                    % (rec["cited_title"], rec["quote"]))
            else:
                parts.append(
                    "The cited source (%s) says:\n%s"
                    % (rec["cited_title"], rec["quote"]))
    return "\n".join(parts)


def _refuse(trace, reason, detail=None, exc=None):
    """Finalise ``trace`` as REFUSED with a reason and message."""
    trace["decision"] = REFUSED
    trace["refusal_reason"] = reason
    lang = normalize_lang(trace.get("lang"), trace.get("question"))
    trace["lang"] = lang
    if lang in _REFUSAL_TEMPLATES:
        prefix, details = _REFUSAL_TEMPLATES[lang]
        # Fixed template in the user's language (Fix 15), not the
        # English detail that may have been passed in.
        detail_text = details.get(
            reason, "दावे की पुष्टि नहीं हो सकी।"
            if lang == "hi" else "Claim confirm nahi ho saka.")
    else:
        prefix = REFUSAL_PREFIX
        detail_text = detail or _REFUSAL_DETAILS.get(
            reason, "The claim could not be verified.")
    detail_text = " ".join(str(detail_text).split())
    trace["refusal_detail"] = detail_text
    if exc is not None:
        trace["exception_type"] = type(exc).__name__
        trace["error_type"] = type(exc).__name__
        trace["exception"] = str(exc)
    trace["correction"] = None
    trace["final_answer"] = prefix + " " + detail_text
    return trace

_PROPOSER_PROMPT = (
    "Draft an answer to the question using only the source passages "
    "below. Quote only from these passages: every quote must be copied "
    "verbatim from a passage below, with its source_file. Do not quote "
    "from file names alone or from memory. Reply with strict JSON "
    "only: {{\"claims\": [{{\"claim\": "
    "\"<one factual claim>\", \"source_file\": \"<file name>\", "
    "\"quote\": \"<verbatim passage from that file>\"}}]}}. Every "
    "claim must carry a verbatim quote. If the passages do not support "
    "an answer, return {{\"claims\": []}}.\n\n"
    "Source passages:\n{passages}\n\n"
    "Language: {lang}\nQuestion: {question}"
)

_SOURCES_HINT = (
    "irdai-insurance-products-regulations-2024.pdf, "
    "master-circular-health-2024.pdf, arogya-sanjeevani-hdfc-ergo.pdf"
)

_PRODUCTS = "irdai-insurance-products-regulations-2024.pdf"
_MASTER = "master-circular-health-2024.pdf"
_AROGYA = "arogya-sanjeevani-hdfc-ergo.pdf"

# Candidate passages copied from the quotes ask.py already uses,
# plus authority entries (merged in retrieve()). Each entry:
# (source_file, quote, keywords).
_PASSAGES = (
    (_PRODUCTS,
     "Waiting period for pre-existing diseases disclosed by the persons "
     "to be insured, shall be maximum up to 36 months of continuous "
     "coverage under the Health Insurance policy. Insurers may endeavor "
     "to have lesser pre-existing disease waiting period and specific "
     "waiting period in the health insurance products. Provided that "
     "the above waiting period norm of pre-existing disease shall not "
     "be applicable for Overseas Travel Policies.",
     ("ped", "pre-existing", "pre existing", "waiting period")),
    (_MASTER,
     "No policy and claim of health insurance shall be contestable on "
     "any grounds of non-disclosure and/or misrepresentation except "
     "for established fraud, after the completion of the Moratorium "
     "Period, i.e. 60 months of continuous coverage",
     ("moratorium", "contest", "fraud", "60 months")),
    (_AROGYA,
     "Expenses related to the treatment of any illness within 30 days "
     "from the first policy commencement date shall be excluded except "
     "claims arising due to an accident, provided the same are covered.",
     ("30 days", "illness", "accident", "waiting period")),
    (_AROGYA,
     "Expenses for cosmetic or plastic surgery or any treatment to "
     "change appearance unless for reconstruction following an "
     "Accident, Burn(s) or Cancer or as part of medically necessary "
     "treatment to remove a direct and immediate health risk to the "
     "insured. For this to be considered a medical necessity, it must "
     "be certified by the attending Medical Practitioner.",
     ("cosmetic", "plastic surgery", "appearance")),
    (_MASTER,
     "CIS is to be provided with every policy \u2026 sub-limits (a "
     "pre-defined limit above which insurance company will not pay)",
     ("room", "sub-limit", "sub limit", "eligible limit", "cis")),
    (_AROGYA,
     "Expenses related to the treatment of a pre-existing Disease (PED) "
     "and its direct complications shall be excluded until the expiry "
     "of 48 months of continuous coverage after the date of inception "
     "of the first policy with us.",
     ("ped", "pre-existing", "pre existing", "waiting period")),
)


def _all_passages():
    passages = [
        {"source_file": src, "quote": quote, "_keywords": keywords}
        for src, quote, keywords in _PASSAGES
    ]
    seen = {(p["source_file"], p["quote"]) for p in passages}
    for rule in REGISTRY:
        key = (rule["source_file"], rule["quote"])
        if key in seen:
            continue
        seen.add(key)
        passages.append({
            "source_file": rule["source_file"], "quote": rule["quote"],
            "topic": rule["topic"],
            "_keywords": tuple(rule["topic"].lower().split()),
        })
    return passages


def retrieve(question):
    """Return candidate passages for ``question``.

    Each passage is ``{"source_file": ..., "quote": ...}`` (authority
    entries also carry ``topic``). Passages whose keywords appear in
    the question come first; if none match, all passages are returned
    so the proposer is always grounded in source text.
    """
    passages = _all_passages()
    if question is None or not str(question).strip():
        return [{k: v for k, v in p.items() if not k.startswith("_")}
                for p in passages]
    lowered = str(question).lower()
    scored = []
    for idx, passage in enumerate(passages):
        score = sum(1 for k in passage["_keywords"] if k in lowered)
        scored.append((-score, idx, passage))
    scored.sort(key=lambda t: (t[0], t[1]))
    matched = [p for neg, _, p in scored if neg < 0]
    chosen = matched if matched else passages
    return [{k: v for k, v in p.items() if not k.startswith("_")}
            for p in chosen]


def _format_passages(passages):
    return "\n".join(
        "- [%s] %s" % (p["source_file"], p["quote"]) for p in passages)


def make_model_proposer(model=None, *, timeout=60):
    """Build a Meta Model API proposer from the environment.

    Reads ``META_API_KEY``, ``PROPOSER_MODEL`` and
    ``META_API_BASE_URL``; raises ``RuntimeError`` if unset. Not
    called by offline tests.
    """
    api_key = os.environ.get("META_API_KEY")
    model_id = model or os.environ.get("PROPOSER_MODEL")
    base_url = os.environ.get("META_API_BASE_URL")
    if not api_key or not model_id or not base_url:
        raise RuntimeError(
            "META_API_KEY, PROPOSER_MODEL and META_API_BASE_URL must "
            "be set to use the model proposer.")

    def proposer(question, lang):
        import requests  # allowed dependency; imported lazily

        passages = retrieve(question)
        prompt = (_PROPOSER_PROMPT + "\nSources: " + _SOURCES_HINT).format(
            lang=lang, question=question,
            passages=_format_passages(passages))
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
        return resp.json()["choices"][0]["message"]["content"]

    return proposer


def _normalise_draft(draft):
    """Return a list of claim dicts, or None if the draft is malformed."""
    if isinstance(draft, str):
        try:
            draft = json.loads(draft)
        except (ValueError, TypeError):
            return None
    if not isinstance(draft, dict):
        return None
    claims = draft.get("claims")
    if not isinstance(claims, list):
        return None
    normalised = []
    for item in claims:
        if not isinstance(item, dict):
            return None
        claim = item.get("claim", item.get("text"))
        source_file = item.get("source_file", item.get("source"))
        quote = item.get("quote")
        if not all(isinstance(v, str) and v.strip()
                   for v in (claim, source_file, quote)):
            return None
        normalised.append({"claim": claim, "source_file": source_file,
                           "quote": quote})
    return normalised


def answer(question, lang=None, *, proposer=None, verifier=None,
           raw_dir=None):
    """Answer ``question`` fail-closed; return the full trace.

    ``proposer`` is ``(question, lang) -> draft`` (dict or JSON str);
    ``verifier`` is a :class:`Verifier` or a backend callable. Both
    default to the env-configured Meta Model API versions. The trace
    is ``{question, lang, draft, claims, decision, final_answer,
    correction}`` where each claim entry carries its evidence result
    and verdict.
    """
    lang = normalize_lang(lang, question)
    try:
        _default_verifier_label = verifier_label()
    except Exception:
        _default_verifier_label = "verifier: (not configured)"
    trace = {"question": question, "lang": lang, "draft": None,
             "claims": [], "decision": REFUSED, "final_answer": None,
             "correction": None, "refusal_reason": None,
             "refusal_detail": None, "exception_type": None,
             "error_type": None,
             "verifier": _default_verifier_label,
             "verifier_model": None, "verifier_fallback": None,
             "verifier_usage": None, "verifier_latency_s": None}
    if question is None or not str(question).strip():
        return _refuse(trace, REFUSAL_NO_CLAIMS)
    if proposer is None:
        try:
            proposer = make_model_proposer()
        except Exception as exc:
            return _refuse(trace, REFUSAL_NO_API_KEY, exc=exc)
    if verifier is None:
        try:
            verifier = Verifier(make_model_backend())
        except Exception as exc:
            trace["exception_type"] = type(exc).__name__
            trace["error_type"] = type(exc).__name__
            trace["exception"] = str(exc)
            verifier = Verifier(None)
    elif not isinstance(verifier, Verifier):
        verifier = Verifier(verifier)
    # Which model verified (Fix 27): label/model/fallback in trace.
    trace["verifier"] = verifier.label
    trace["verifier_model"] = verifier.model
    trace["verifier_fallback"] = verifier.fallback

    try:
        draft = proposer(question, lang)
    except Exception as exc:
        return _refuse(trace, REFUSAL_PROPOSER_ERROR, exc=exc)
    trace["draft"] = draft
    claims = _normalise_draft(draft)
    if not claims:  # malformed draft or no claims: fail closed
        return _refuse(trace, REFUSAL_NO_CLAIMS)

    has_refusal = False
    refusal_reason = None
    refusal_detail = None

    def _note_refusal(reason, detail=None):
        nonlocal has_refusal, refusal_reason, refusal_detail
        has_refusal = True
        if refusal_reason is None:
            refusal_reason = reason
            refusal_detail = detail
    has_contradicted = False
    has_superseded = False
    corrected_records = []
    superseded_records = []
    # Fix 28: collect every verifier call (cited + governing) first,
    # run them in parallel on a small pool, then replay the results
    # in the original claim/rule order below. Trace order, verdict
    # precedence and refusal order are unchanged.
    jobs = []
    prepared = []
    for item in claims:
        entry = {"claim": item["claim"],
                 "source_file": item["source_file"],
                 "quote": item["quote"],
                 "evidence": None, "verdict": None, "reason": None,
                 "verifier_verdict": None, "verifier_reason": None,
                 "verifier": trace["verifier"],
                 "verifier_model": trace["verifier_model"],
                 "verifier_fallback": trace["verifier_fallback"],
                 "verifier_usage": None, "verifier_latency_s": None,
                 "governing_verifier_usage": None,
                 "governing_verifier_latency_s": None,
                 "governing_verdict": None, "governing_reason": None,
                 "cited_value": _extract_value(item["quote"])
                 or _extract_value(item["claim"]),
                 "cited_title": source_title(item["source_file"]),
                 "governing_value": None}
        work = {"item": item, "entry": entry, "cited_job": None,
                "governing": [], "governing_rules": [],
                "governing_uncertain": False}
        prepared.append(work)
        evidence = check_evidence(item["source_file"], item["quote"],
                                  raw_dir=raw_dir)
        entry["evidence"] = evidence
        if not (evidence["exists"] and evidence["found"]):
            # Deterministic gate: the verifier is never consulted on
            # failed evidence, and cannot override this.
            entry["reason"] = (
                "Evidence check failed (exists=%s, found=%s); claim "
                "not verified." % (evidence["exists"], evidence["found"]))
            entry["refusal_reason"] = REFUSAL_EVIDENCE_NOT_FOUND
            continue
        source_text = extract_text(item["source_file"], raw_dir=raw_dir)
        work["cited_job"] = len(jobs)
        jobs.append((item["claim"], item["quote"], source_text))
        governing_rules = governing_for(
            item["source_file"],
            text=item["claim"] + " " + str(question),
            quote=item["quote"])
        work["governing_rules"] = governing_rules
        if not governing_rules and topic_detection_uncertain(
                item["source_file"], claim=item["claim"],
                question=str(question), quote=item["quote"],
                lang=lang):
            work["governing_uncertain"] = True
        for rule in governing_rules:
            gov = {"rule": rule, "job": None,
                   "evidence": check_evidence(
                       rule["source_file"], rule["quote"],
                       raw_dir=raw_dir)}
            work["governing"].append(gov)
            if gov["evidence"]["exists"] and gov["evidence"]["found"]:
                gov_text = extract_text(rule["source_file"],
                                        raw_dir=raw_dir)
                gov["job"] = len(jobs)
                jobs.append((item["claim"], rule["quote"], gov_text))

    def _run_job(job):
        result = verifier.verify(job[0], job[1], job[2])
        return (result, verifier.last_usage,
                verifier.last_latency_s,
                verifier.last_response_model)

    if len(jobs) > 1:
        with ThreadPoolExecutor(
                max_workers=min(4, len(jobs))) as pool:
            job_results = list(pool.map(_run_job, jobs))
    else:
        job_results = [_run_job(job) for job in jobs]

    for work in prepared:
        item = work["item"]
        entry = work["entry"]
        if work["cited_job"] is None:
            _note_refusal(REFUSAL_EVIDENCE_NOT_FOUND)
            trace["claims"].append(entry)
            continue
        (result, _usage, _latency, _rmodel) = job_results[
            work["cited_job"]]
        verifier.last_usage = _usage
        verifier.last_latency_s = _latency
        verifier.last_response_model = _rmodel
        # Verifier verdict on the cited source: stored unchanged.
        # Governing verdicts go in governing_verdict/governing_reason
        # and are never written over this.
        entry["verdict"] = result["verdict"]
        entry["verifier_verdict"] = result["verdict"]
        entry["reason"] = result["reason"]
        entry["verifier_reason"] = result["reason"]
        entry["verifier_usage"] = verifier.last_usage
        entry["verifier_latency_s"] = verifier.last_latency_s
        entry["verifier_response_model"] = verifier.last_response_model
        # Fix 34: raw verifier text when its output was malformed.
        entry["verifier_raw_output"] = result.get("raw_output")
        trace["verifier_usage"] = verifier.last_usage
        trace["verifier_latency_s"] = verifier.last_latency_s
        # Authority precedence: a superseded source does not govern.
        # Re-verify against the governing passage (evidence first).
        # When a governing rule applies, the claim is VERIFIED only
        # if the governing verdict is SUPPORTED; governing
        # INSUFFICIENT_EVIDENCE (including malformed/failed verifier
        # output, which fails closed to INSUFFICIENT_EVIDENCE) is a
        # refusal, and the superseded source's verdict is never used.
        # Language-independent topic matching (Fix 14): the cited
        # quote (verbatim English source text) is matched in
        # addition to claim + question, so a Hindi/Hinglish claim
        # citing a superseded source cannot bypass this check.
        governing_rules = work["governing_rules"]
        governing_uncertain = work["governing_uncertain"]
        if governing_uncertain:
            # Fail closed: superseded source, topic uncertain.
            entry["governing_verdict"] = INSUFFICIENT_EVIDENCE
            entry["governing_reason"] = (
                "Topic detection uncertain for a superseded "
                "source; failing closed.")
            entry["refusal_reason"] = REFUSAL_GOVERNING_INSUFFICIENT
            _note_refusal(REFUSAL_GOVERNING_INSUFFICIENT)
        governing_contradicted = False
        governing_failed = False
        governing_supported = False
        governing_superseded = False
        for gov in work["governing"]:
            rule = gov["rule"]
            gov_evidence = gov["evidence"]
            entry["governing_evidence"] = gov_evidence
            entry["governing_source"] = rule["source_file"]
            entry["governing_quote"] = rule["quote"]
            entry["governing_title"] = governing_title(
                rule["source_file"])
            entry["governing_effective_date"] = rule.get(
                "effective_date")
            entry["governing_effective_display"] = (
                effective_display(rule))
            entry["governing_published"] = rule.get("published")
            entry["governing_signed"] = rule.get("signed")
            entry["governing_value"] = (
                rule.get("value") or rule.get("extracted_value")
                or _extract_value(rule["quote"]))
            if not (gov_evidence["exists"] and gov_evidence["found"]):
                entry["governing_reason"] = (
                    "Governing evidence check failed for %s "
                    "(exists=%s, found=%s); claim not verified."
                    % (rule["source_file"], gov_evidence["exists"],
                       gov_evidence["found"]))
                entry["refusal_reason"] = (
                    REFUSAL_GOVERNING_INSUFFICIENT)
                _note_refusal(REFUSAL_GOVERNING_INSUFFICIENT)
                governing_failed = True
                break
            (gov_result, _g_usage, _g_latency,
             _g_rmodel) = job_results[gov["job"]]
            verifier.last_usage = _g_usage
            verifier.last_latency_s = _g_latency
            verifier.last_response_model = _g_rmodel
            entry["governing_verdict"] = gov_result["verdict"]
            entry["governing_reason"] = gov_result["reason"]
            entry["governing_verifier_usage"] = _g_usage
            entry["governing_verifier_latency_s"] = _g_latency
            entry["governing_verifier_response_model"] = _g_rmodel
            entry["governing_verifier_raw_output"] = gov_result.get(
                "raw_output")
            trace["verifier_usage"] = _g_usage
            trace["verifier_latency_s"] = _g_latency
            if gov_result["verdict"] == CONTRADICTED:
                if result["verdict"] == SUPPORTED:
                    # Faithful to its own source; only the governing
                    # rule catches it: decision SUPERSEDED. The cited
                    # verdict above stays SUPPORTED.
                    governing_superseded = True
                    has_superseded = True
                    superseded_records.append({
                        "governing_value": entry["governing_value"],
                        "governing_title": governing_title(
                            rule["source_file"]),
                        "governing_quote": rule["quote"],
                        "cited_title": source_title(
                            item["source_file"]),
                        "cited_value": entry["cited_value"],
                    })
                else:
                    governing_contradicted = True
                    has_contradicted = True
                    corrected_records.append({
                        "governing_value": entry["governing_value"],
                        "governing_title": governing_title(
                            rule["source_file"]),
                        "governing_quote": rule["quote"],
                        "cited_title": source_title(
                            item["source_file"]),
                        "quote": item["quote"],
                        "value": _extract_value(item["quote"]),
                    })
                break
            elif gov_result["verdict"] == SUPPORTED:
                governing_supported = True
            else:
                entry["refusal_reason"] = (
                    REFUSAL_GOVERNING_INSUFFICIENT)
                _note_refusal(REFUSAL_GOVERNING_INSUFFICIENT)
                governing_failed = True
                break
        if governing_rules:
            if not (governing_supported or governing_contradicted
                    or governing_failed or governing_superseded):
                entry["refusal_reason"] = (
                    REFUSAL_GOVERNING_INSUFFICIENT)
                _note_refusal(REFUSAL_GOVERNING_INSUFFICIENT)
        elif governing_uncertain:
            pass  # refusal already noted above; never VERIFY
        elif result["verdict"] == CONTRADICTED:
            has_contradicted = True
            corrected_records.append({
                "cited_title": source_title(item["source_file"]),
                "quote": item["quote"],
                "value": _extract_value(item["quote"]),
            })
        elif result["verdict"] != SUPPORTED:
            entry["refusal_reason"] = REFUSAL_VERIFIER_INSUFFICIENT
            _note_refusal(REFUSAL_VERIFIER_INSUFFICIENT)
        trace["claims"].append(entry)

    if has_refusal:
        return _refuse(
            trace, refusal_reason or REFUSAL_VERIFIER_INSUFFICIENT,
            detail=refusal_detail)
    elif has_superseded:
        trace["decision"] = SUPERSEDED
        parts = [_build_superseded(superseded_records, lang)]
        if corrected_records:
            parts.append(_build_corrected(corrected_records, lang))
        trace["correction"] = "\n".join(p for p in parts if p)
        trace["final_answer"] = trace["correction"]
    elif has_contradicted:
        trace["decision"] = CORRECTED
        trace["correction"] = _build_corrected(corrected_records, lang)
        trace["final_answer"] = trace["correction"]
    else:
        trace["decision"] = VERIFIED
        trace["final_answer"] = _build_verified(trace["claims"], lang)
    return trace
