"""Fail-closed answering pipeline (hackathon Step 3).

``answer(question, lang)`` runs:

1. a proposer (Muse Spark via the Meta Model API) drafts claims, each
   with ``source_file`` + ``quote``;
2. :func:`evidence.check_evidence` on every claim — deterministic,
   and never overridden by any model;
3. :func:`verifier.verify_claim` on every claim that passed evidence;
4. a final decision:

   - ``VERIFIED`` — every claim ``SUPPORTED`` (and at least one claim);
   - ``REFUSED`` — any claim with failed evidence or
     ``INSUFFICIENT_EVIDENCE`` (including a malformed draft, a proposer
     or verifier failure, or no claims at all);
   - ``CORRECTED`` — any claim ``CONTRADICTED`` with no refusal
     trigger: the trace shows what the source actually says instead.

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
    from verify.authority import governing_for, governing_title
    from verify.evidence import check_evidence, extract_text
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier, make_model_backend)
except ImportError:  # run as top-level modules (cd verify; unittest)
    from authority import governing_for, governing_title
    from evidence import check_evidence, extract_text
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier, make_model_backend)

VERIFIED = "VERIFIED"
REFUSED = "REFUSED"
CORRECTED = "CORRECTED"

_PROPOSER_PROMPT = (
    "Draft an answer to the question using only the listed source "
    "documents. Reply with strict JSON only: {{\"claims\": [{{\"claim\": "
    "\"<one factual claim>\", \"source_file\": \"<file name>\", "
    "\"quote\": \"<verbatim passage from that file>\"}}]}}. Every "
    "claim must carry a verbatim quote. If the sources do not support "
    "an answer, return {{\"claims\": []}}.\n\n"
    "Language: {lang}\nQuestion: {question}"
)

_SOURCES_HINT = (
    "irdai-insurance-products-regulations-2024.pdf, "
    "master-circular-health-2024.pdf, arogya-sanjeevani-hdfc-ergo.pdf"
)


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

        prompt = (_PROPOSER_PROMPT + "\nSources: " + _SOURCES_HINT).format(
            lang=lang, question=question)
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
    corrections = []
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
        governing_contradicted = False
        governing_failed = False
        for rule in governing_for(
                item["source_file"],
                text=item["claim"] + " " + str(question)):
            gov_evidence = check_evidence(
                rule["source_file"], rule["quote"], raw_dir=raw_dir)
            entry["governing_evidence"] = gov_evidence
            entry["governing_source"] = rule["source_file"]
            entry["governing_quote"] = rule["quote"]
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
        if governing_contradicted or governing_failed:
            pass
        elif result["verdict"] == CONTRADICTED:
            has_contradicted = True
            corrections.append(
                "Claim %r is contradicted. %s Source %s actually "
                "says: %r" % (item["claim"], result["reason"],
                              item["source_file"], item["quote"]))
        elif result["verdict"] != SUPPORTED:
            has_refusal = True
        trace["claims"].append(entry)

    if has_refusal:
        trace["decision"] = REFUSED
    elif has_contradicted:
        trace["decision"] = CORRECTED
        trace["correction"] = " ".join(corrections)
        trace["final_answer"] = trace["correction"]
    else:
        trace["decision"] = VERIFIED
        trace["final_answer"] = " ".join(
            c["claim"] for c in trace["claims"])
    return trace
