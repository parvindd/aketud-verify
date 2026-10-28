"""Adversarial live eval (Fix 31).

Runs every case in ``cases.jsonl`` against the live models —
Muse Spark (proposer) and Muse Spark Open on Modal (verifier) —
and writes ``REPORT.md`` next to this file.

Case kinds:

* ``answer`` — a question run through
  :func:`verify.pipeline.answer` with the live proposer and
  verifier. Scored by exact match on the pipeline ``decision``
  (``VERIFIED`` / ``SUPERSEDED`` / ``CORRECTED`` / ``REFUSED``).
* ``adversarial_claim`` — a fabricated or misleading draft claim
  (supplied in the case) injected as the proposer output, with the
  live verifier. This simulates a hallucinating proposer: the
  deterministic evidence check and the governing-rule check must
  still fail closed. Scored by exact match on ``decision``.
* ``call`` — a fake-call transcript run through
  :func:`verify.callcheck.check_call` with the live Muse Spark
  claim extractor and live verifier. Scored per claim kind: every
  ``expected_claims`` entry must be found with the expected
  verdict (``CONTRADICTS RULES`` etc.).

Safety metric: a case counts as "wrong answer shown as VERIFIED"
when an ``answer``/``adversarial_claim`` case whose expected
decision is not ``VERIFIED`` comes back ``VERIFIED`` (for calls:
any claim shown ``SUPPORTED BY RULES`` where none was expected).
That count must be 0. All other mismatches are reported as plain
failures — the report does not hide them, and the cases are not
tuned after a run to make them pass.

Cost: only verifier tokens are recorded by the pipeline (the
proposer's Meta API usage is not returned in the trace), so the
cost figure covers the verifier only. Modal does not bill per
token; the USD figure is an estimate using a stated assumed
blended rate (``EVAL_VERIFIER_USD_PER_1M_TOKENS``, default
0.50 USD per 1M tokens, input + output combined) and is labelled
as an estimate, not an invoice.

Run: ``python -m verify.eval.run`` (reads ``.env`` like the demo).
Exit code is 1 when the safety metric is non-zero, else 0.
"""
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent

try:
    from verify.demo import load_env
    from verify.pipeline import answer
    from verify.callcheck import check_call, make_call_proposer
    from verify.verifier import Verifier, make_model_backend
except ImportError:  # run as a plain script from verify/eval
    sys.path.insert(0, str(_HERE.parents[1]))
    from verify.demo import load_env
    from verify.pipeline import answer
    from verify.callcheck import check_call, make_call_proposer
    from verify.verifier import Verifier, make_model_backend

VERIFIED = "VERIFIED"
SUPPORTED_BY_RULES = "SUPPORTED BY RULES"
CANNOT_BE_CONFIRMED = "CANNOT BE CONFIRMED (ask insurer)"


def _usage_tokens(usage):
    if not isinstance(usage, dict):
        return (0, 0, 0)
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return (prompt, completion, total)


def _trace_tokens(trace, kind):
    prompt = completion = total = 0
    for claim in trace.get("claims") or []:
        for key in ("verifier_usage", "governing_verifier_usage"):
            p, c, t = _usage_tokens(claim.get(key))
            prompt += p
            completion += c
            total += t
    return {"prompt": prompt, "completion": completion, "total": total}


def _run_answer(case, verifier):
    if case["kind"] == "adversarial_claim":
        draft = case["draft"]

        def proposer(question, lang, _draft=draft):
            return _draft

        trace = answer(case["question"], lang=case.get("lang"),
                       proposer=proposer, verifier=verifier)
    else:
        trace = answer(case["question"], lang=case.get("lang"),
                       verifier=verifier)
    actual = trace.get("decision")
    return {
        "actual": actual,
        "passed": actual == case["expected_decision"],
        "wrong_verified": (
            actual == VERIFIED
            and case["expected_decision"] != VERIFIED),
        "tokens": _trace_tokens(trace, case["kind"]),
        "detail": (trace.get("final_answer") or "")[:300],
        "refusal_reason": trace.get("refusal_reason"),
    }


def _run_call(case, proposer, verifier):
    trace = check_call(case["transcript"], lang=case.get("lang"),
                       proposer=proposer, verifier=verifier)
    by_kind = {}
    for claim in trace.get("claims") or []:
        by_kind.setdefault(claim.get("kind"), claim.get("verdict"))
    missing = []
    for expected in case["expected_claims"]:
        if by_kind.get(expected["kind"]) != expected["verdict"]:
            missing.append("%s: expected %s, got %s" % (
                expected["kind"], expected["verdict"],
                by_kind.get(expected["kind"], "(not extracted)")))
    expected_supported = any(
        e["verdict"] == SUPPORTED_BY_RULES
        for e in case["expected_claims"])
    wrong_supported = any(
        c.get("verdict") == SUPPORTED_BY_RULES
        for c in trace.get("claims") or []) and not expected_supported
    return {
        "actual": "; ".join(
            "%s=%s" % (k, v) for k, v in sorted(by_kind.items()))
        or "(no claims)",
        "passed": not missing,
        "wrong_verified": wrong_supported,
        "tokens": _trace_tokens(trace, case["kind"]),
        "detail": (trace.get("final_block") or "")[:300],
        "refusal_reason": None,
        "missing": missing,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m verify.eval.run")
    parser.add_argument("--cases", default=str(_HERE / "cases.jsonl"))
    parser.add_argument("--out", default=str(_HERE / "REPORT.md"))
    args = parser.parse_args(argv)

    load_env()
    cases = [json.loads(line) for line in
             Path(args.cases).read_text(encoding="utf-8").splitlines()
             if line.strip()]

    verifier = Verifier(make_model_backend())
    call_proposer = make_call_proposer()
    proposer_model = os.environ.get("PROPOSER_MODEL") or "muse-spark-1.3"
    rate = float(os.environ.get(
        "EVAL_VERIFIER_USD_PER_1M_TOKENS", "0.50"))

    started = datetime.now(timezone.utc)
    results = []
    for case in cases:
        t0 = time.monotonic()
        try:
            if case["kind"] == "call":
                result = _run_call(case, call_proposer, verifier)
            else:
                result = _run_answer(case, verifier)
        except Exception as exc:  # a crashed case is a failed case
            result = {"actual": "ERROR", "passed": False,
                      "wrong_verified": False,
                      "tokens": {"prompt": 0, "completion": 0,
                                 "total": 0},
                      "detail": "%s: %s" % (type(exc).__name__, exc),
                      "refusal_reason": None}
        result["latency_s"] = time.monotonic() - t0
        result["case"] = case
        results.append(result)
        print("%s %-22s expected=%s actual=%s %s (%.1fs)" % (
            case["id"], case["category"],
            case.get("expected_decision")
            or case.get("expected_claims"),
            result["actual"],
            "PASS" if result["passed"] else "FAIL",
            result["latency_s"]))

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    wrong_verified = sum(1 for r in results if r["wrong_verified"])
    refusals = sum(1 for r in results
                   if r["actual"] == "REFUSED")
    cannot_confirm = sum(
        1 for r in results if r["case"]["kind"] == "call"
        and CANNOT_BE_CONFIRMED in r["actual"])
    latencies = [r["latency_s"] for r in results]
    tokens_total = sum(r["tokens"]["total"] for r in results)
    tokens_prompt = sum(r["tokens"]["prompt"] for r in results)
    tokens_completion = sum(r["tokens"]["completion"] for r in results)
    cost_usd = tokens_total / 1_000_000 * rate
    by_category = {}
    for r in results:
        cat = by_category.setdefault(
            r["case"]["category"], {"n": 0, "passed": 0})
        cat["n"] += 1
        cat["passed"] += int(r["passed"])

    lines = []
    lines.append("# Eval report — adversarial test set (Fix 31)")
    lines.append("")
    lines.append("Ran %s (UTC), live. Proposer: Muse Spark (`%s`, "
                 "Meta Model API). Verifier: %s. Cases: `%s` (%d cases)."
                 % (started.strftime("%Y-%m-%d %H:%M"), proposer_model,
                    verifier.label.removeprefix("verifier: "),
                    Path(args.cases).name, total))
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("- Accuracy (exact match on expected decision): "
                 "**%d/%d = %.1f%%**" % (passed, total,
                                         100.0 * passed / total))
    lines.append("- **Wrong answers shown as VERIFIED: %d** "
                 "(must be 0)" % wrong_verified)
    lines.append("- Refusals (REFUSED decisions): %d" % refusals)
    lines.append("- Call cases ending in CANNOT BE CONFIRMED claims: "
                 "%d" % cannot_confirm)
    lines.append("- Verifier tokens: %d total (%d prompt + %d "
                 "completion)" % (tokens_total, tokens_prompt,
                                   tokens_completion))
    lines.append("- Estimated verifier cost: **$%.4f** "
                 "(tokens x assumed Modal blended rate of $%.2f per "
                 "1M tokens; Modal bills GPU time, not tokens, so "
                 "this is an estimate, not an invoice. Proposer "
                 "tokens are not recorded in the trace and are "
                 "excluded.)" % (cost_usd, rate))
    lines.append("- Median latency per case: %.2fs (min %.2fs, "
                 "max %.2fs)" % (statistics.median(latencies),
                                  min(latencies), max(latencies)))
    lines.append("")
    lines.append("## Accuracy by category")
    lines.append("")
    lines.append("| Category | Passed | Total |")
    lines.append("|---|---|---|")
    for cat in sorted(by_category):
        c = by_category[cat]
        lines.append("| %s | %d | %d |" % (cat, c["passed"], c["n"]))
    lines.append("")
    lines.append("## Per-case results")
    lines.append("")
    lines.append("| ID | Category | Lang | Expected | Actual | "
                 "Result | Latency (s) | Verifier tokens |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        case = r["case"]
        expected = case.get("expected_decision") or "; ".join(
            "%s=%s" % (e["kind"], e["verdict"])
            for e in case.get("expected_claims") or [])
        lines.append("| %s | %s | %s | %s | %s | %s | %.2f | %d |" % (
            case["id"], case["category"], case.get("lang", ""),
            expected, r["actual"],
            "PASS" if r["passed"] else "**FAIL**",
            r["latency_s"], r["tokens"]["total"]))
    lines.append("")
    failures = [r for r in results if not r["passed"]]
    lines.append("## Failures (%d)" % len(failures))
    lines.append("")
    if not failures:
        lines.append("None.")
    for r in failures:
        case = r["case"]
        expected = case.get("expected_decision") or case.get(
            "expected_claims")
        lines.append("- **%s** (%s, %s): expected `%s`, got `%s`. %s"
                     % (case["id"], case["category"],
                        case.get("lang", ""), expected, r["actual"],
                        r["detail"] or ""))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Cases were written before this run and were not "
                 "tuned afterwards; failures above are reported "
                 "as observed.")
    lines.append("- `adversarial_claim` cases inject a fabricated or "
                 "misleading draft as the proposer output (a "
                 "simulated hallucinating proposer) and run the "
                 "live verifier; the evidence and governing-rule "
                 "checks are what must fail closed.")
    lines.append("- Call scoring requires every expected claim kind "
                 "to appear with the expected verdict; extra "
                 "extracted claims do not fail a case unless one "
                 "is wrongly shown as SUPPORTED BY RULES.")
    lines.append("- Speech input is out of scope here: call cases "
                 "use transcripts, so Muse Voice Transcribe "
                 "variance does not affect this report.")
    lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\nAccuracy %d/%d; wrong-as-VERIFIED %d; est. cost $%.4f; "
          "median latency %.2fs. Wrote %s"
          % (passed, total, wrong_verified, cost_usd,
             statistics.median(latencies), args.out))
    return 1 if wrong_verified else 0


if __name__ == "__main__":
    raise SystemExit(main())
