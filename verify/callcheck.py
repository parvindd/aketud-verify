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
    from verify.authority import REGISTRY, governing_title
    from verify.evidence import check_evidence, extract_text
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier)
except ImportError:  # run as top-level modules (cd verify)
    from authority import REGISTRY, governing_title
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

    # Rule 3 / fee: caller demands a revival fee or charge.
    fee_words = any(k in lowered for k in (
        "fee", "charge", "शुल्क", "फीस"))
    if fee_words and (revival or _AMOUNT_RE.search(text)):
        amount = _AMOUNT_RE.search(text)
        suffix = " (%s)" % amount.group(0) if amount else ""
        add("revival_fee",
            "Caller claims a revival fee must be paid%s" % suffix, 3)

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
    if any(k in lowered for k in ("fee", "charge", "शुल्क", "फीस")):
        return "revival_fee"
    if "irdai" in lowered or "bonus" in lowered:
        return "irdai_calling"
    if any(k in lowered for k in ("today", "forever", "aaj", "turant")):
        return "revival_deadline"
    if any(k in lowered for k in ("policy status", "lapsed", "exists")):
        return "policy_status"
    return ""


def _semantic_verdict(entry):
    """Offline verdict from the mapped rule's verified meaning."""
    kind = entry.get("kind") or _infer_kind(entry.get("claim"))
    if kind in ("revival_deadline", "irdai_calling"):
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
             "safety_advice": SAFETY_ADVICE}

    if proposer is not None:
        try:
            extracted = _normalise_proposer_claims(
                proposer(transcript, lang))
        except Exception:
            extracted = []
    else:
        extracted = extract_caller_claims(transcript)

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
        if kind == "policy_status":
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = (
                "Policy existence/status is known only to the insurer.")
            trace["claims"].append(entry)
            continue
        if kind == "revival_fee" and product != "linked":
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = (
                "Product type is %s; the no-fee rule covers linked "
                "products only, so this fee claim cannot be confirmed "
                "from the rules." % product)
            trace["claims"].append(entry)
            continue
        if not (evidence["exists"] and evidence["found"]):
            entry["verdict"] = CANNOT_BE_CONFIRMED
            entry["reason"] = (
                "Evidence check failed (exists=%s, found=%s)."
                % (evidence["exists"], evidence["found"]))
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
        entry["reason"] = result["reason"]
        entry["verdict"] = _DISPLAY.get(
            result["verdict"], CANNOT_BE_CONFIRMED)
        trace["claims"].append(entry)

    lines = []
    if not trace["claims"]:
        lines.append("No caller claims could be checked: %s"
                     % CANNOT_BE_CONFIRMED)
    for idx, claim in enumerate(trace["claims"], 1):
        lines.append("Claim %d: %s — %s" % (
            idx, claim["verdict"], claim["claim"]))
    trace["final_block"] = "\n".join(lines + [
        "Safety advice: " + SAFETY_ADVICE])
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
        lines.append(CANNOT_BE_CONFIRMED)
    for idx, claim in enumerate(claims, 1):
        lines.append("Claim %d: %s" % (idx, claim.get("verdict", "")))
        lines.append("  %s" % (claim.get("reason") or ""))
    lines += ["", "Final block", "-----------",
              str(trace.get("final_block") or "")]
    return "\n".join(lines)
