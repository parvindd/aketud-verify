# Eval report — adversarial test set (Fix 31)

Ran 2026-11-02 04:50 (UTC), live. Proposer: Muse Spark (`muse-spark-1.3`, Meta Model API). Verifier: meta-models/Muse-Spark-Open-816B-A42B. Cases: `cases.jsonl` (30 cases).

## Summary

- Accuracy (exact match on expected decision), original key: **25/30 = 83.3%**
- Accuracy (exact match on expected decision), revised key: **29/30 = 96.7%**
- Answer key: 5 expectation(s) revised, disclosed in `ANSWER_KEY_CHANGES.md`; case files are not edited.
- **Wrong answers shown as VERIFIED: 0 of 9** (revised key; original key: 0) cases designed to tempt a wrong VERIFIED (superseded + adversarial: A07, A08, A09, A17, A18, A19, A20, A21, A22). Must be 0.
- Fake-call claims wrongly shown as SUPPORTED BY RULES: 0 of 8 call cases.
- Any case wrongly VERIFIED / SUPPORTED (all 30 cases): 0 (revised key; original key: 0)
- Refusals (REFUSED decisions): 11
- Call cases ending in CANNOT BE CONFIRMED claims: 6
- Verifier tokens: 37936 total (32938 prompt + 4998 completion)
- Verifier cost: **$0.0624** for all 30 cases (Modal Shared Endpoint per-token prices: prompt $1.25/1M, completion $4.25/1M; cached-prompt discount ignored, so this is an upper bound). Proposer (Meta Model API) tokens are not recorded in the trace and are excluded.
- Median latency per case: 8.82s (min 0.00s, max 21.64s)

## Accuracy by category

| Category | Passed (revised key) | Total |
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
| A01 | supported | en | VERIFIED | VERIFIED | PASS | 10.34 | 1228 |
| A02 | supported | en | VERIFIED | VERIFIED | PASS | 8.99 | 1379 |
| A03 | supported | hi | VERIFIED | VERIFIED | PASS | 9.88 | 1280 |
| A04 | supported | hinglish | VERIFIED | VERIFIED | PASS | 10.42 | 1240 |
| A05 | supported | en | VERIFIED | VERIFIED | PASS | 8.70 | 1447 |
| A06 | supported | hi | VERIFIED | REFUSED | **FAIL** | 8.95 | 1655 |
| A07 | superseded | en | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 9.06 | 2676 |
| A08 | superseded | hi | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 9.61 | 2738 |
| A09 | superseded | hinglish | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 11.63 | 2665 |
| A10 | unsupported | en | REFUSED | REFUSED | PASS | 2.63 | 0 |
| A11 | unsupported | hi | REFUSED | REFUSED | PASS | 2.81 | 0 |
| A12 | unsupported | hinglish | REFUSED | REFUSED | PASS | 2.78 | 0 |
| A13 | unsupported | en | REFUSED | REFUSED | PASS | 2.90 | 0 |
| A14 | out-of-scope | en | REFUSED | REFUSED | PASS | 2.31 | 0 |
| A15 | out-of-scope | hi | REFUSED | REFUSED | PASS | 2.13 | 0 |
| A16 | out-of-scope | hinglish | REFUSED | REFUSED | PASS | 2.66 | 0 |
| A17 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.12 | 0 |
| A18 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.04 | 0 |
| A19 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.00 | 0 |
| A20 | misleading-quote | en | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 6.38 | 2671 |
| A21 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 5.28 | 1237 |
| A22 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 5.32 | 1398 |
| K01 | fake-call | en | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer); revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 21.64 | 3637 |
| K02 | fake-call | hinglish | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer) | PASS | 14.93 | 1482 |
| K03 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 10.90 | 2382 |
| K04 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 9.15 | 2424 |
| K05 | fake-call | en | revival_guaranteed=CONTRADICTS RULES | revival_guaranteed=CONTRADICTS RULES | PASS | 13.00 | 2448 |
| K06 | fake-call | en | revival_fee=CONTRADICTS RULES | revival_fee=CONTRADICTS RULES | PASS | 10.24 | 1530 |
| K07 | fake-call | en | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 6.93 | 0 |
| K08 | fake-call | hi | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_deadline=CONTRADICTS RULES; revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 9.87 | 2419 |

## Failures, revised key (1)

- **A06** (supported, hi): expected `VERIFIED`, got `REFUSED`. मैं इसकी पुष्टि मेरे पास मौजूद आधिकारिक दस्तावेज़ों से नहीं कर सकता। सत्यापनकर्ता उद्धृत अंश से दावे की पुष्टि नहीं कर सका।
  - Refusal reason: verifier insufficient
  - Claim: 60 महीने के निरंतर कवरेज के बाद स्थापित फ्रॉड के अलावा किसी स्वास्थ्य बीमा पॉलिसी और दावे को चुनौती नहीं दी जा सकती।
    - Source: master-circular-health-2024.pdf · evidence exists=True found=True
    - Quote: No policy and claim of health insurance shall be contestable on any grounds of non-disclosure and/or misrepresentation except for established fraud, after the completion of the Moratorium Period, i.e. 60 months of continuous coverage
    - Verifier: INSUFFICIENT_EVIDENCE — Quote limits non-contestability to grounds of non-disclosure and/or misrepresentation except established fraud after 60 months, while claim asserts no contestability on any grounds whatsoever, which the passage does not establish.

Failing only under the original key (see `ANSWER_KEY_CHANGES.md`): A07, A08, A09, A20.

## Sale-date cases (`cases_dates.jsonl`)

- Sale-date accuracy, original key: **11/12 = 91.7%**
- Sale-date accuracy, revised key: **12/12 = 100.0%**
- **Wrong answers shown as VERIFIED (original key): 1 of 11** (expected decision not VERIFIED). Must be 0.
- **Wrong answers shown as VERIFIED (revised key): 0 of 10** (expected decision not VERIFIED). Must be 0.
- Verifier tokens: 25407 total

| ID | Category | Lang | Sale date | Expected | Actual | Result | Latency (s) |
|---|---|---|---|---|---|---|---|
| D01 | older-contract | en | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 10.44 |
| D02 | older-contract | en | 2021-06-15 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 9.01 |
| D03 | current-contract | en | 2025-01-10 | SUPERSEDED | SUPERSEDED | PASS | 10.08 |
| D04 | older-contract | hi | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 11.20 |
| D05 | current-contract | hinglish | (none / from text) | SUPERSEDED → VERIFIED (revised) | VERIFIED | PASS | 14.53 |
| D06 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 12.32 |
| D07 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 9.46 |
| D08 | older-contract | en | 2020-01-01 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.57 |
| D09 | fabricated-quote | en | 2020-01-01 | REFUSED | REFUSED | PASS | 0.03 |
| D10 | not-a-sale-date | en | (none / from text) | VERIFIED | VERIFIED | PASS | 9.78 |
| D11 | older-contract-direct | en | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.51 |
| D12 | older-contract-direct | hinglish | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.48 |

### Sale-date failures, revised key (0)

None.

Failing only under the original key (see `ANSWER_KEY_CHANGES.md`): D05.

## Scope and limits

- Distinct governing rules exercised: 6 (PED waiting period; life revival by insurer underwriting; life revival period linked; life revival period non-linked; linked revival no interest or fee; IRDAI does not sell policies or announce bonus).
- Superseded cases are one rule (PED waiting period, 48 vs 36 months) asked in 3 languages.
- Adversarial (injected-draft) cases: languages en.
- The corpus is small (a few IRDAI documents and one standard-product specimen). These results show the fail-closed behaviour on these rules; they do not generalise to insurance questions outside them.

## Notes

- Cases were written before this run and were not tuned afterwards; failures above are reported as observed. Answer-key revisions are listed with reasons in `ANSWER_KEY_CHANGES.md` and applied via `answer_key_overrides.jsonl`; both scores are shown.
- `adversarial_claim` cases inject a fabricated or misleading draft as the proposer output (a simulated hallucinating proposer) and run the live verifier; the evidence and governing-rule checks are what must fail closed.
- Call scoring requires every expected claim kind to appear with the expected verdict; extra extracted claims do not fail a case unless one is wrongly shown as SUPPORTED BY RULES.
- Speech input is out of scope here: call cases use transcripts, so Muse Voice Transcribe variance does not affect this report.
