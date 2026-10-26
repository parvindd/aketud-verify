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
     or verifier failure, or no claims at all);
   - ``SUPERSEDED`` — a claim faithful to its own source
     (``SUPPORTED`` against that source) but contradicted only by a
     governing rule that supersedes that source: the claim verdict
     and the decision are ``SUPERSEDED``, not
     ``CONTRADICTED``/``CORRECTED``;
   - ``CORRECTED`` — any claim ``CONTRADICTED`` by its own cited
     source with no refusal trigger: the correction uses only the
     verifier's reason and the source name, never the claim's own
     quote.

Fail closed: anything not proven ``SUPPORTED`` is never shown as
verified, and a ``REFUSED`` result carries no answer text.

The proposer and verifier are injectable callables so tests run
offline with mocks. The default proposer/verifier read
``META_API_KEY`` and model ids (``PROPOSER_MODEL`` /
``VERIFIER_MODEL``, plus ``META_API_BASE_URL``) from the environment;
no secret or model id is hard-coded, and no real model is called
unless those are set and the defaults are used.
"""
import json
import os

try:
    from verify.authority import REGISTRY, governing_for, governing_title
    from verify.evidence import check_evidence, extract_text
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier, make_model_backend)
except ImportError:  # run as top-level modules (cd verify; unittest)
    from authority import REGISTRY, governing_for, governing_title
    from evidence import check_evidence, extract_text
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier, make_model_backend)

VERIFIED = "VERIFIED"
REFUSED = "REFUSED"
CORRECTED = "CORRECTED"
SUPERSEDED = "SUPERSEDED"

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


def answer(question, lang="en", *, proposer=None, verifier=None,
           raw_dir=None):
    """Answer ``question`` fail-closed; return the full trace.

    ``proposer`` is ``(question, lang) -> draft`` (dict or JSON str);
    ``verifier`` is a :class:`Verifier` or a backend callable. Both
    default to the env-configured Meta Model API versions. The trace
    is ``{question, lang, draft, claims, decision, final_answer,
    correction}`` where each claim entry carries its evidence result
    and verdict.
    """
    trace = {"question": question, "lang": lang, "draft": None,
             "claims": [], "decision": REFUSED, "final_answer": None,
             "correction": None}
    if question is None or not str(question).strip():
        trace["correction"] = None
        return trace
    if proposer is None:
        try:
            proposer = make_model_proposer()
        except Exception:
            return trace
    if verifier is None:
        try:
            verifier = Verifier(make_model_backend())
        except Exception:
            verifier = Verifier(None)
    elif not isinstance(verifier, Verifier):
        verifier = Verifier(verifier)

    try:
        draft = proposer(question, lang)
    except Exception:
        return trace
    trace["draft"] = draft
    claims = _normalise_draft(draft)
    if not claims:  # malformed draft or no claims: fail closed
        return trace

    has_refusal = False
    has_contradicted = False
    has_superseded = False
    corrections = []
    superseded_messages = []
    for item in claims:
        entry = {"claim": item["claim"],
                 "source_file": item["source_file"],
                 "quote": item["quote"],
                 "evidence": None, "verdict": None, "reason": None}
        evidence = check_evidence(item["source_file"], item["quote"],
                                  raw_dir=raw_dir)
        entry["evidence"] = evidence
        if not (evidence["exists"] and evidence["found"]):
            # Deterministic gate: the verifier is never consulted on
            # failed evidence, and cannot override this.
            entry["reason"] = (
                "Evidence check failed (exists=%s, found=%s); claim "
                "not verified." % (evidence["exists"], evidence["found"]))
            has_refusal = True
            trace["claims"].append(entry)
            continue
        source_text = extract_text(item["source_file"], raw_dir=raw_dir)
        result = verifier.verify(item["claim"], item["quote"], source_text)
        entry["verdict"] = result["verdict"]
        entry["reason"] = result["reason"]
        # Authority precedence: a superseded source does not govern.
        # Re-verify against the governing passage (evidence first).
        # When a governing rule applies, the claim is VERIFIED only
        # if the governing verdict is SUPPORTED; governing
        # INSUFFICIENT_EVIDENCE (including malformed/failed verifier
        # output, which fails closed to INSUFFICIENT_EVIDENCE) is a
        # refusal, and the superseded source's verdict is never used.
        governing_rules = governing_for(
            item["source_file"],
            text=item["claim"] + " " + str(question))
        governing_contradicted = False
        governing_failed = False
        governing_supported = False
        governing_superseded = False
        for rule in governing_rules:
            gov_evidence = check_evidence(
                rule["source_file"], rule["quote"], raw_dir=raw_dir)
            entry["governing_evidence"] = gov_evidence
            entry["governing_source"] = rule["source_file"]
            entry["governing_quote"] = rule["quote"]
            entry["governing_title"] = governing_title(
                rule["source_file"])
            entry["governing_effective_date"] = rule.get(
                "effective_date")
            if not (gov_evidence["exists"] and gov_evidence["found"]):
                entry["reason"] = (
                    "Governing evidence check failed for %s "
                    "(exists=%s, found=%s); claim not verified."
                    % (rule["source_file"], gov_evidence["exists"],
                       gov_evidence["found"]))
                has_refusal = True
                governing_failed = True
                break
            gov_text = extract_text(rule["source_file"], raw_dir=raw_dir)
            gov_result = verifier.verify(
                item["claim"], rule["quote"], gov_text)
            entry["governing_verdict"] = gov_result["verdict"]
            if gov_result["verdict"] == CONTRADICTED:
                if result["verdict"] == SUPPORTED:
                    # Faithful to its own source; only the governing
                    # rule catches it: SUPERSEDED, not CONTRADICTED.
                    governing_superseded = True
                    entry["verdict"] = SUPERSEDED
                    entry["reason"] = gov_result["reason"]
                    has_superseded = True
                    detail = str(gov_result["reason"]).strip()
                    detail = detail.rstrip(".")
                    superseded_messages.append(
                        "%s says %s, but %s (effective %s) caps/sets "
                        "%s. Current rule: %s."
                        % (item["source_file"], item["claim"],
                           governing_title(rule["source_file"]),
                           rule.get("effective_date", ""),
                           detail, rule["quote"]))
                else:
                    governing_contradicted = True
                    entry["verdict"] = CONTRADICTED
                    entry["reason"] = gov_result["reason"]
                    has_contradicted = True
                    corrections.append(
                        "Claim %r is contradicted. %s Governing source "
                        "%s (%s) supersedes %s on %s and actually says: %r"
                        % (item["claim"], gov_result["reason"],
                           rule["source_file"],
                           governing_title(rule["source_file"]),
                           item["source_file"], rule["topic"],
                           rule["quote"]))
                break
            elif gov_result["verdict"] == SUPPORTED:
                governing_supported = True
                entry["verdict"] = SUPPORTED
                entry["reason"] = gov_result["reason"]
            else:
                entry["verdict"] = gov_result["verdict"]
                entry["reason"] = gov_result["reason"]
                has_refusal = True
                governing_failed = True
                break
        if governing_rules:
            if not (governing_supported or governing_contradicted
                    or governing_failed or governing_superseded):
                has_refusal = True
        elif result["verdict"] == CONTRADICTED:
            has_contradicted = True
            # No governing rule: do not present the claim's own
            # quote as what the source says; use only the
            # verifier's reason and the source name.
            corrections.append(
                "Claim %r is contradicted. %s Source: %s."
                % (item["claim"], result["reason"],
                   item["source_file"]))
        elif result["verdict"] != SUPPORTED:
            has_refusal = True
        trace["claims"].append(entry)

    if has_refusal:
        trace["decision"] = REFUSED
    elif has_superseded:
        trace["decision"] = SUPERSEDED
        trace["correction"] = " ".join(
            superseded_messages + corrections)
        trace["final_answer"] = trace["correction"]
    elif has_contradicted:
        trace["decision"] = CORRECTED
        trace["correction"] = " ".join(corrections)
        trace["final_answer"] = trace["correction"]
    else:
        trace["decision"] = VERIFIED
        trace["final_answer"] = " ".join(
            c["claim"] for c in trace["claims"])
    return trace
