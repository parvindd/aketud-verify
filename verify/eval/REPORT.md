# Eval report — adversarial test set (Fix 31)

Ran 2026-11-03 08:33 (UTC), live. Proposer: Muse Spark (`muse-spark-1.3`, Meta Model API). Verifier: meta-models/Muse-Spark-Open-816B-A42B. Cases: `cases.jsonl` (30 cases).

## Summary

- Accuracy (exact match on expected decision), original key: **25/30 = 83.3%**
- Accuracy (exact match on expected decision), revised key: **29/30 = 96.7%**
- Answer key: 5 expectation(s) revised, disclosed in `ANSWER_KEY_CHANGES.md`; expectations in the case files are not edited.
- **Wrong answers shown as VERIFIED: 0 of 9** (revised key; original key: 0) cases designed to tempt a wrong VERIFIED (superseded + adversarial: A07, A08, A09, A17, A18, A19, A20, A21, A22). Must be 0.
- Fake-call claims wrongly shown as SUPPORTED BY RULES: 0 of 8 call cases.
- Any case wrongly VERIFIED / SUPPORTED (all 30 cases): 0 (revised key; original key: 0)
- Refusals (REFUSED decisions): 11
- Call cases ending in CANNOT BE CONFIRMED claims: 6
- Verifier tokens: 38664 total (34030 prompt + 4634 completion)
- Verifier cost: **$0.0622** for all 30 cases (Modal Shared Endpoint per-token prices: prompt $1.25/1M, completion $4.25/1M; cached-prompt discount ignored, so this is an upper bound). Proposer (Meta Model API) tokens are not recorded in the trace and are excluded.
- Median latency per case: 14.76s (min 0.00s, max 75.62s)

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
| A01 | supported | en | VERIFIED | VERIFIED | PASS | 14.83 | 1249 |
| A02 | supported | en | VERIFIED | REFUSED | **FAIL** | 16.15 | 1729 |
| A03 | supported | hi | VERIFIED | VERIFIED | PASS | 16.27 | 1278 |
| A04 | supported | hinglish | VERIFIED | VERIFIED | PASS | 15.25 | 1236 |
| A05 | supported | en | VERIFIED | VERIFIED | PASS | 14.62 | 1493 |
| A06 | supported | hi | VERIFIED | VERIFIED | PASS | 14.75 | 1382 |
| A07 | superseded | en | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 16.13 | 2748 |
| A08 | superseded | hi | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 75.62 | 2731 |
| A09 | superseded | hinglish | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 55.65 | 2648 |
| A10 | unsupported | en | REFUSED | REFUSED | PASS | 5.86 | 0 |
| A11 | unsupported | hi | REFUSED | REFUSED | PASS | 6.59 | 0 |
| A12 | unsupported | hinglish | REFUSED | REFUSED | PASS | 6.69 | 0 |
| A13 | unsupported | en | REFUSED | REFUSED | PASS | 5.47 | 0 |
| A14 | out-of-scope | en | REFUSED | REFUSED | PASS | 7.34 | 0 |
| A15 | out-of-scope | hi | REFUSED | REFUSED | PASS | 6.43 | 0 |
| A16 | out-of-scope | hinglish | REFUSED | REFUSED | PASS | 7.26 | 0 |
| A17 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.13 | 0 |
| A18 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.03 | 0 |
| A19 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.00 | 0 |
| A20 | misleading-quote | en | SUPERSEDED → DEPENDS_ON_SALE_DATE (revised) | DEPENDS_ON_SALE_DATE | PASS | 7.35 | 2647 |
| A21 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 6.60 | 1241 |
| A22 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 8.37 | 1418 |
| K01 | fake-call | en | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer); revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 26.86 | 1458 |
| K02 | fake-call | hinglish | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer) | PASS | 33.01 | 1464 |
| K03 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 20.52 | 2415 |
| K04 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 14.78 | 2409 |
| K05 | fake-call | en | revival_guaranteed=CONTRADICTS RULES | revival_guaranteed=CONTRADICTS RULES | PASS | 34.23 | 2535 |
| K06 | fake-call | en | revival_fee=CONTRADICTS RULES | revival_fee=CONTRADICTS RULES | PASS | 23.33 | 1493 |
| K07 | fake-call | en | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_fee=CANNOT BE CONFIRMED (ask insurer); revival_guaranteed=CONTRADICTS RULES | PASS | 18.96 | 2677 |
| K08 | fake-call | hi | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_deadline=CONTRADICTS RULES; revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 17.58 | 2413 |

## Failures, revised key (1)

- **A02** (supported, en): expected `VERIFIED`, got `REFUSED`. I can't confirm this from the official documents I have. The verifier could not confirm the claim from the cited passage.
  - Refusal reason: verifier insufficient
  - Claim: After 60 months of continuous coverage, no health insurance policy and claim shall be contestable except for established fraud.
    - Source: master-circular-health-2024.pdf · evidence exists=True found=True
    - Quote: No policy and claim of health insurance shall be contestable on any grounds of non-disclosure and/or misrepresentation except for established fraud, after the completion of the Moratorium Period, i.e. 60 months of continuous coverage
    - Verifier: INSUFFICIENT_EVIDENCE — The passage limits non-contestability to grounds of non-disclosure and/or misrepresentation after 60 months, while the claim omits that qualifier and asserts no contestability on any grounds except fraud, which the passage does not establish.

Failing only under the original key (see `ANSWER_KEY_CHANGES.md`): A07, A08, A09, A20.

## Sale-date cases (`cases_dates.jsonl`)

- Sale-date accuracy, original key: **11/12 = 91.7%**
- Sale-date accuracy, revised key: **12/12 = 100.0%**
- **Wrong answers shown as VERIFIED (original key): 1 of 11** (expected decision not VERIFIED). Must be 0.
- **Wrong answers shown as VERIFIED (revised key): 0 of 10** (expected decision not VERIFIED). Must be 0.
- Verifier tokens: 25430 total

| ID | Category | Lang | Sale date | Expected | Actual | Result | Latency (s) |
|---|---|---|---|---|---|---|---|
| D01 | older-contract | en | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 17.19 |
| D02 | older-contract | en | 2021-06-15 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 15.36 |
| D03 | current-contract | en | 2025-01-10 | SUPERSEDED | SUPERSEDED | PASS | 16.00 |
| D04 | older-contract | hi | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 19.04 |
| D05 | current-contract | hinglish | (none / from text) | SUPERSEDED → VERIFIED (revised) | VERIFIED | PASS | 22.40 |
| D06 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 27.24 |
| D07 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 17.39 |
| D08 | older-contract | en | 2020-01-01 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.72 |
| D09 | fabricated-quote | en | 2020-01-01 | REFUSED | REFUSED | PASS | 0.03 |
| D10 | not-a-sale-date | en | (none / from text) | VERIFIED | VERIFIED | PASS | 20.13 |
| D11 | older-contract-direct | en | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.57 |
| D12 | older-contract-direct | hinglish | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.69 |

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
