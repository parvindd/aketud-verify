"""Demo CLI (verify Fix 9).

Usage::

    python -m verify.demo "<question>"

Prints a clean, readable trace::

    question -> Muse Spark draft -> per-claim evidence check
    (found / not found, source) -> verifier verdict -> governing
    check if any -> final decision in large text.

Reads ``.env`` itself (no ``set -a`` needed): variables already in
the environment win over ``.env`` values. Colour is used only when
the output stream is a terminal that supports it.
"""
import json
import os
import sys
from pathlib import Path

try:
    from verify.authority import effective_display
    from verify.pipeline import answer as _pipeline_answer
except ImportError:  # run as top-level module (cd verify)
    from authority import effective_display
    from pipeline import answer as _pipeline_answer

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"

_DECISION_COLOURS = {
    "VERIFIED": _GREEN,
    "REFUSED": _RED,
    "CORRECTED": _YELLOW,
    "SUPERSEDED": _MAGENTA,
}


def _env_candidates():
    here = Path(__file__).resolve()
    return [here.parents[1] / ".env", Path.cwd() / ".env"]


def load_env(env_path=None):
    """Load ``.env`` into ``os.environ``; return the values read.

    Existing environment variables are never overwritten, so no
    ``set -a; source .env`` dance is needed before running the demo.
    """
    paths = [Path(env_path)] if env_path else _env_candidates()
    loaded = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            if text.startswith("export "):
                text = text[len("export "):].lstrip()
            key, _, value = text.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] \
                    and value[0] in ("'", '"'):
                value = value[1:-1]
            if not key:
                continue
            loaded[key] = value
            os.environ.setdefault(key, value)
        if loaded:
            break
    return loaded


def supports_color(stream=None):
    """True when ``stream`` is a colour-capable terminal."""
    stream = stream if stream is not None else sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _paint(code, text, enabled):
    return "%s%s%s" % (code, text, _RESET) if enabled else text


def _stage(lines, number, title, colour):
    heading = "Stage %d — %s" % (number, title)
    lines.append(_paint(_BOLD + _CYAN, heading, colour))
    lines.append("-" * len(heading))


def _large_decision(decision, colour):
    text = "FINAL DECISION: %s" % decision
    bar = "=" * (len(text) + 4)
    code = _DECISION_COLOURS.get(decision, _BOLD)
    return [
        _paint(code, bar, colour),
        _paint(_BOLD + code, "  " + text + "  ", colour),
        _paint(code, bar, colour),
    ]


def _draft_claims(trace):
    claims = trace.get("claims") or []
    if claims:
        return claims
    draft = trace.get("draft")
    if isinstance(draft, str):
        try:
            draft = json.loads(draft)
        except (ValueError, TypeError):
            return []
    if isinstance(draft, dict):
        items = draft.get("claims")
        if isinstance(items, list):
            return [c for c in items if isinstance(c, dict)]
    return []


def format_trace(trace, *, color=False, raw=False):
    """Render ``trace`` (from :func:`verify.pipeline.answer`).

    Stage 2 lists each draft claim as ``claim — source``; the raw
    draft JSON is shown only with ``raw=True`` (``--raw``), dimmed
    when colour is on.
    """
    lines = []
    stage = 0

    stage += 1
    _stage(lines, stage, "Question", color)
    lines.append(str(trace.get("question") or ""))
    lines.append("")

    stage += 1
    _stage(lines, stage, "Muse Spark draft (proposer)", color)
    draft = trace.get("draft")
    draft_claims = _draft_claims(trace)
    if draft is None:
        lines.append("(no draft)")
    elif not draft_claims:
        lines.append("(no claims in draft)")
    else:
        for idx, claim in enumerate(draft_claims, 1):
            text = claim.get("claim", claim.get("text", ""))
            source = claim.get("source_file",
                               claim.get("source", ""))
            lines.append("%d. %s — %s" % (idx, text, source))
    if draft is not None:
        if raw:
            raw_text = draft if isinstance(draft, str) else json.dumps(
                draft, indent=2, ensure_ascii=False)
            lines.append(_paint(_DIM, raw_text, color))
        else:
            lines.append(_paint(
                _DIM, "(raw draft hidden — use --raw to show)", color))
    lines.append("")

    claims = trace.get("claims") or []

    stage += 1
    _stage(lines, stage,
           "Evidence check — deterministic (per claim)", color)
    if not claims:
        lines.append("(no claims to check)")
    for idx, claim in enumerate(claims, 1):
        evidence = claim.get("evidence") or {}
        found = bool(evidence.get("exists") and evidence.get("found"))
        label = _paint(_GREEN if found else _RED,
                       "FOUND" if found else "NOT FOUND", color)
        lines.append("Claim %d: %s" % (idx, claim.get("claim", "")))
        lines.append("  Source: %s" % claim.get("source_file", ""))
        lines.append("  Evidence: %s (exists=%s, found=%s)"
                     % (label, evidence.get("exists"),
                        evidence.get("found")))
        lines.append("  Quote: %s" % claim.get("quote", ""))
    lines.append("")

    stage += 1
    _stage(lines, stage,
           "Verifier verdict — cited source (per claim)", color)
    if not claims:
        lines.append("(no claims to verify)")
    for idx, claim in enumerate(claims, 1):
        verdict = (claim.get("verifier_verdict")
                   or claim.get("verdict") or "(not verified)")
        reason = claim.get("verifier_reason")
        if reason is None:
            reason = claim.get("reason") or ""
        lines.append("Claim %d: %s — %s" % (idx, verdict, reason))
        lines.append("  Cited source: %s"
                     % claim.get("source_file", ""))
    lines.append("")

    stage += 1
    _stage(lines, stage,
           "Governing check — authority precedence", color)
    if not any(c.get("governing_source") or c.get("governing_verdict")
               for c in claims):
        lines.append("(no governing rule applies)")
    for idx, claim in enumerate(claims, 1):
        if not (claim.get("governing_source")
                or claim.get("governing_verdict")):
            continue
        display = (claim.get("governing_effective_display")
                   or effective_display(
                       claim.get("governing_effective_date", "")))
        lines.append(
            "Claim %d: governing source %s (%s, %s)"
            % (idx, claim.get("governing_source", ""),
               claim.get("governing_title", ""), display))
        gov_ev = claim.get("governing_evidence") or {}
        gov_found = bool(gov_ev.get("exists") and gov_ev.get("found"))
        lines.append("  Governing evidence: %s"
                     % ("FOUND" if gov_found else "NOT FOUND"))
        lines.append("  Governing verdict: %s — %s"
                     % (claim.get("governing_verdict") or "(none)",
                        claim.get("governing_reason") or ""))
        if claim.get("governing_quote"):
            lines.append("  Governing quote: %s"
                         % claim["governing_quote"])
    lines.append("")

    stage += 1
    _stage(lines, stage, "Final decision", color)
    lines.extend(_large_decision(str(trace.get("decision", "")), color))
    if trace.get("refusal_reason"):
        lines.append("Refusal reason: %s" % trace["refusal_reason"])
    if trace.get("final_answer"):
        lines.append("Final answer: %s" % trace["final_answer"])
    return "\n".join(lines)


def main(argv=None, stream=None):
    """Run the demo for one question; return an exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    stream = stream if stream is not None else sys.stdout
    raw = "--raw" in args
    args = [a for a in args if a != "--raw"]
    if not args or not " ".join(args).strip():
        print('Usage: python -m verify.demo [--raw] "<question>"',
              file=sys.stderr)
        return 2
    question = " ".join(args).strip()
    load_env()
    # Import here so .env is loaded before any default model call.
    try:
        from verify.pipeline import answer
    except ImportError:
        from pipeline import answer
    trace = answer(question)
    print(format_trace(trace, color=supports_color(stream), raw=raw),
          file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
