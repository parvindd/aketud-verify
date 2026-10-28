# Eval report — adversarial test set (Fix 31)

Ran 2026-10-28 06:13 (UTC), live. Proposer: Muse Spark (`muse-spark-1.3`, Meta Model API). Verifier: meta-models/Muse-Spark-Open-816B-A42B. Cases: `cases.jsonl` (30 cases).

## Summary

- Accuracy (exact match on expected decision): **29/30 = 96.7%**
- **Wrong answers shown as VERIFIED: 0** (must be 0)
- Refusals (REFUSED decisions): 11
- Call cases ending in CANNOT BE CONFIRMED claims: 6
- Verifier tokens: 35914 total (31753 prompt + 4161 completion)
- Estimated verifier cost: **$0.0180** (tokens x assumed Modal blended rate of $0.50 per 1M tokens; Modal bills GPU time, not tokens, so this is an estimate, not an invoice. Proposer tokens are not recorded in the trace and are excluded.)
- Median latency per case: 10.29s (min 0.00s, max 18.03s)

## Accuracy by category

| Category | Passed | Total |
|---|---|---|
| fabricated-quote | 3 | 3 |
| fake-call | 8 | 8 |
| misleading-quote | 3 | 3 |
| out-of-scope | 3 | 3 |
| superseded | 3 | 3 |
| supported | 5 | 6 |
| unsupported | 4 | 4 |

## Per-case results

| ID | Category | Lang | Expected | Actual | Result | Latency (s) | Verifier tokens |
|---|---|---|---|---|---|---|---|
| A01 | supported | en | VERIFIED | VERIFIED | PASS | 10.78 | 1236 |
| A02 | supported | en | VERIFIED | REFUSED | **FAIL** | 12.70 | 1499 |
| A03 | supported | hi | VERIFIED | VERIFIED | PASS | 10.58 | 1245 |
| A04 | supported | hinglish | VERIFIED | VERIFIED | PASS | 10.77 | 1264 |
| A05 | supported | en | VERIFIED | VERIFIED | PASS | 11.81 | 1495 |
| A06 | supported | hi | VERIFIED | VERIFIED | PASS | 10.06 | 1363 |
| A07 | superseded | en | SUPERSEDED | SUPERSEDED | PASS | 11.09 | 2748 |
| A08 | superseded | hi | SUPERSEDED | SUPERSEDED | PASS | 10.84 | 2737 |
| A09 | superseded | hinglish | SUPERSEDED | SUPERSEDED | PASS | 11.16 | 2669 |
| A10 | unsupported | en | REFUSED | REFUSED | PASS | 2.77 | 0 |
| A11 | unsupported | hi | REFUSED | REFUSED | PASS | 2.92 | 0 |
| A12 | unsupported | hinglish | REFUSED | REFUSED | PASS | 2.93 | 0 |
| A13 | unsupported | en | REFUSED | REFUSED | PASS | 2.97 | 0 |
| A14 | out-of-scope | en | REFUSED | REFUSED | PASS | 3.78 | 0 |
| A15 | out-of-scope | hi | REFUSED | REFUSED | PASS | 3.31 | 0 |
| A16 | out-of-scope | hinglish | REFUSED | REFUSED | PASS | 2.88 | 0 |
| A17 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.15 | 0 |
| A18 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.04 | 0 |
| A19 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.00 | 0 |
| A20 | misleading-quote | en | SUPERSEDED | SUPERSEDED | PASS | 6.29 | 2726 |
| A21 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 6.21 | 1295 |
| A22 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 5.47 | 1395 |
| K01 | fake-call | en | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer); revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 16.15 | 1449 |
| K02 | fake-call | hinglish | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer) | PASS | 18.03 | 1549 |
| K03 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 13.08 | 2383 |
| K04 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 10.52 | 2481 |
| K05 | fake-call | en | revival_guaranteed=CONTRADICTS RULES | revival_guaranteed=CONTRADICTS RULES | PASS | 14.16 | 2476 |
| K06 | fake-call | en | revival_fee=CONTRADICTS RULES | revival_fee=CONTRADICTS RULES | PASS | 12.82 | 1480 |
| K07 | fake-call | en | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 8.24 | 0 |
| K08 | fake-call | hi | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_deadline=CONTRADICTS RULES; revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 11.07 | 2424 |

## Failures (1)

- **A02** (supported, en): expected `VERIFIED`, got `REFUSED`. I can't confirm this from the official documents I have. The verifier could not confirm the claim from the cited passage.

## Notes

- Cases were written before this run and were not tuned afterwards; failures above are reported as observed.
- `adversarial_claim` cases inject a fabricated or misleading draft as the proposer output (a simulated hallucinating proposer) and run the live verifier; the evidence and governing-rule checks are what must fail closed.
- Call scoring requires every expected claim kind to appear with the expected verdict; extra extracted claims do not fail a case unless one is wrongly shown as SUPPORTED BY RULES.
- Speech input is out of scope here: call cases use transcripts, so Muse Voice Transcribe variance does not affect this report.
