"""Demo CLI (verify Fix 9).

Usage::

    python -m verify.demo "<question>"
    python -m verify.demo --sale-date 2021-06-15 "<question>"

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
import re
import sys
from pathlib import Path

try:
    from verify.authority import contains_devanagari, effective_display
    from verify.pipeline import answer as _pipeline_answer
except ImportError:  # run as top-level module (cd verify)
    from authority import contains_devanagari, effective_display
    from pipeline import answer as _pipeline_answer

_LANGS = ("en", "hi", "hinglish")


def detect_lang(text):
    """Auto-detect language: Devanagari -> hi, else en (Fix 15)."""
    return "hi" if contains_devanagari(text) else "en"


def resolve_lang(lang, question):
    """Resolve --lang; auto-detect Devanagari -> hi if not given."""
    if lang is None:
        return detect_lang(question)
    return lang

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
    "APPLIES_TO_OLDER_CONTRACT": _MAGENTA,
    "DEPENDS_ON_SALE_DATE": _YELLOW,
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
    ``months of``). Stored trace/evidence data is unchanged.
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
    """Which model verified ``claim`` (Fix 27), for Stage 4/5."""
    claim = claim or {}
    model = claim.get("verifier_model") or trace.get("verifier_model")
    fallback = claim.get("verifier_fallback")
    if fallback is None:
        fallback = trace.get("verifier_fallback")
    if model:
        return "%s%s" % (model, " (fallback)" if fallback else "")
    label = claim.get("verifier") or trace.get("verifier") or ""
    return str(label).removeprefix("verifier: ") or "(not configured)"


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
        lines.append("  Quote: %s" % normalise_display_text(
            claim.get("quote", "")))
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
        lines.append("  Verifier: %s" % _verifier_display(trace, claim))
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
        lines.append("  Verifier: %s" % _verifier_display(trace, claim))
        if claim.get("governing_quote"):
            lines.append("  Governing quote: %s"
                         % normalise_display_text(
                             claim["governing_quote"]))
    lines.append("")

    stage += 1
    _stage(lines, stage, "Final decision", color)
    lines.extend(_large_decision(str(trace.get("decision", "")), color))
    sale = trace.get("sale_date")
    if sale:
        lines.append("Sale date: %s to %s (%s: %s)" % (
            sale["earliest"], sale["latest"], sale["source"],
            sale["text"]))
    if trace.get("sale_date_error"):
        lines.append("Sale date not used: %s" % trace["sale_date_error"])
    for saving in trace.get("savings") or []:
        ev = saving.get("evidence") or {}
        lines.append("Savings clause: %s — evidence %s" % (
            saving.get("citation"),
            "FOUND" if ev.get("exists") and ev.get("found")
            else "NOT FOUND"))
    if trace.get("refusal_reason"):
        lines.append("Refusal reason: %s" % trace["refusal_reason"])
    if trace.get("final_answer"):
        lines.append("Final answer: %s" % trace["final_answer"])
    return "\n".join(lines)


def _live_call_trace(transcript, lang):
    """Check a call with live Muse Spark proposer + verifier.

    The proposer is Muse Spark (claim extraction mapped to the
    registered rules); the verifier is Spark Open via ``VERIFIER_*``
    (Meta fallback, labelled). Either failing to build falls back
    honestly: no proposer means the deterministic extractor, no
    verifier means ``rule only (no model)`` (Fix 30).
    """
    try:
        from verify.callcheck import check_call
    except ImportError:
        from callcheck import check_call
    proposer, verifier = _call_models()
    return check_call(transcript, lang=lang, proposer=proposer,
                      verifier=verifier)


def _call_models():
    """Return (proposer, verifier) for call modes; either may be None."""
    try:
        from verify.callcheck import make_call_proposer
        from verify.verifier import Verifier, make_model_backend
    except ImportError:
        from callcheck import make_call_proposer
        from verifier import Verifier, make_model_backend
    proposer = None
    try:
        proposer = make_call_proposer()
    except Exception:
        proposer = None
    verifier = None
    try:
        verifier = Verifier(make_model_backend())
    except Exception:
        verifier = None
    return proposer, verifier


_build_call_models = _call_models


def format_voice_stage(transcript, *, color=False):
    """Render Stage 0 — Muse Voice Transcribe for ``transcript``."""
    lines = []
    _stage(lines, 0, "Muse Voice Transcribe", color)
    lines.append(str(transcript or ""))
    return "\n".join(lines)


def _build_parser():
    import argparse

    class _Parser(argparse.ArgumentParser):
        def error(self, message):
            raise SystemExit(2)

    parser = _Parser(prog="python -m verify.demo", add_help=False)
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--lang", choices=_LANGS, default=None)
    parser.add_argument("--sale-date", dest="sale_date", default=None)
    parser.add_argument("--call", dest="call", default=None)
    parser.add_argument("--call-audio", dest="call_audio", default=None)
    parser.add_argument("question", nargs="*")
    return parser


def main(argv=None, stream=None):
    """Run the demo for one question; return an exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    stream = stream if stream is not None else sys.stdout
    try:
        parsed = _build_parser().parse_args(args)
    except SystemExit:
        print('Usage: python -m verify.demo [--raw] '
              '[--lang en|hi|hinglish] [--sale-date YYYY-MM-DD] '
              '"<question>" | --call "<transcript>" [--lang en|hi|hinglish] | '
              '--call-audio <call.wav> [--lang en|hi|hinglish]',
              file=sys.stderr)
        return 2
    if parsed.call_audio is not None:
        if parsed.question or parsed.call is not None:
            print('Usage: python -m verify.demo --call-audio '
                  '<call.wav> [--lang en|hi|hinglish]',
                  file=sys.stderr)
            return 2
        load_env()
        try:
            from verify.voice import transcribe
        except ImportError:
            from voice import transcribe
        try:
            transcript = transcribe(parsed.call_audio)
        except Exception as exc:
            print("Transcription failed: %s" % exc, file=sys.stderr)
            return 1
        call_lang = resolve_lang(parsed.lang, transcript)
        try:
            from verify.callcheck import format_call_trace
        except ImportError:
            from callcheck import format_call_trace
        trace = _live_call_trace(transcript, call_lang)
        use_color = supports_color(stream)
        print(format_voice_stage(transcript, color=use_color),
              file=stream)
        print("", file=stream)
        print(format_call_trace(trace, color=use_color,
                                show_transcript=False), file=stream)
        return 0
    if parsed.call is not None:
        if parsed.question:
            print('Usage: python -m verify.demo --call '
                  '"<transcript>" [--lang en|hi|hinglish]',
                  file=sys.stderr)
            return 2
        call_lang = resolve_lang(parsed.lang, parsed.call)
        load_env()
        try:
            from verify.callcheck import format_call_trace
        except ImportError:
            from callcheck import format_call_trace
        trace = _live_call_trace(parsed.call, call_lang)
        print(format_call_trace(
            trace, color=supports_color(stream)), file=stream)
        return 0
    if not parsed.question or not " ".join(parsed.question).strip():
        print('Usage: python -m verify.demo [--raw] '
              '[--lang en|hi|hinglish] [--sale-date YYYY-MM-DD] '
              '"<question>"',
              file=sys.stderr)
        return 2
    if parsed.sale_date is not None:
        try:
            from verify.saledate import parse_iso
        except ImportError:
            from saledate import parse_iso
        try:
            parse_iso(parsed.sale_date)
        except ValueError as exc:
            print("Invalid --sale-date: %s" % exc, file=sys.stderr)
            return 2
    question = " ".join(parsed.question).strip()
    lang = resolve_lang(parsed.lang, question)
    load_env()
    try:
        from verify.pipeline import answer
    except ImportError:
        from pipeline import answer
    extra = ({"sale_date": parsed.sale_date}
             if parsed.sale_date is not None else {})
    trace = answer(question, lang=lang, **extra)
    print(format_trace(trace, color=supports_color(stream),
                       raw=parsed.raw), file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
