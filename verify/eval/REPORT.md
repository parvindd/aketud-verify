# Eval report — adversarial test set (Fix 31)

Ran 2026-11-02 03:32 (UTC), live. Proposer: Muse Spark (`muse-spark-1.3`, Meta Model API). Verifier: meta-models/Muse-Spark-Open-816B-A42B. Cases: `cases.jsonl` (30 cases).

## Summary

- Accuracy (exact match on expected decision): **26/30 = 86.7%**
- **Wrong answers shown as VERIFIED: 0 of 9** cases designed to tempt a wrong VERIFIED (superseded + adversarial: A07, A08, A09, A17, A18, A19, A20, A21, A22). Must be 0.
- Fake-call claims wrongly shown as SUPPORTED BY RULES: 0 of 8 call cases.
- Any case wrongly VERIFIED / SUPPORTED (all 30 cases): 0
- Refusals (REFUSED decisions): 10
- Call cases ending in CANNOT BE CONFIRMED claims: 6
- Verifier tokens: 38403 total (34010 prompt + 4393 completion)
- Verifier cost: **$0.0612** for all 30 cases (Modal Shared Endpoint per-token prices: prompt $1.25/1M, completion $4.25/1M; cached-prompt discount ignored, so this is an upper bound). Proposer (Meta Model API) tokens are not recorded in the trace and are excluded.
- Median latency per case: 8.96s (min 0.00s, max 14.09s)

## Accuracy by category

| Category | Passed | Total |
|---|---|---|
| fabricated-quote | 3 | 3 |
| fake-call | 8 | 8 |
| misleading-quote | 2 | 3 |
| out-of-scope | 3 | 3 |
| superseded | 0 | 3 |
| supported | 6 | 6 |
| unsupported | 4 | 4 |

## Per-case results

| ID | Category | Lang | Expected | Actual | Result | Latency (s) | Verifier tokens |
|---|---|---|---|---|---|---|---|
| A01 | supported | en | VERIFIED | VERIFIED | PASS | 10.57 | 1243 |
| A02 | supported | en | VERIFIED | VERIFIED | PASS | 9.92 | 1377 |
| A03 | supported | hi | VERIFIED | VERIFIED | PASS | 10.09 | 1246 |
| A04 | supported | hinglish | VERIFIED | VERIFIED | PASS | 10.22 | 1241 |
| A05 | supported | en | VERIFIED | VERIFIED | PASS | 10.65 | 1475 |
| A06 | supported | hi | VERIFIED | VERIFIED | PASS | 8.80 | 1386 |
| A07 | superseded | en | SUPERSEDED | DEPENDS_ON_SALE_DATE | **FAIL** | 10.24 | 2716 |
| A08 | superseded | hi | SUPERSEDED | DEPENDS_ON_SALE_DATE | **FAIL** | 8.78 | 2702 |
| A09 | superseded | hinglish | SUPERSEDED | DEPENDS_ON_SALE_DATE | **FAIL** | 9.76 | 2671 |
| A10 | unsupported | en | REFUSED | REFUSED | PASS | 3.08 | 0 |
| A11 | unsupported | hi | REFUSED | REFUSED | PASS | 3.11 | 0 |
| A12 | unsupported | hinglish | REFUSED | REFUSED | PASS | 3.55 | 0 |
| A13 | unsupported | en | REFUSED | REFUSED | PASS | 2.63 | 0 |
| A14 | out-of-scope | en | REFUSED | REFUSED | PASS | 2.53 | 0 |
| A15 | out-of-scope | hi | REFUSED | REFUSED | PASS | 2.29 | 0 |
| A16 | out-of-scope | hinglish | REFUSED | REFUSED | PASS | 3.01 | 0 |
| A17 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.15 | 0 |
| A18 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.04 | 0 |
| A19 | fabricated-quote | en | REFUSED | REFUSED | PASS | 0.00 | 0 |
| A20 | misleading-quote | en | SUPERSEDED | DEPENDS_ON_SALE_DATE | **FAIL** | 5.42 | 2653 |
| A21 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 5.18 | 1220 |
| A22 | misleading-quote | en | CORRECTED | CORRECTED | PASS | 5.21 | 1447 |
| K01 | fake-call | en | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer); revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 14.09 | 1644 |
| K02 | fake-call | hinglish | irdai_calling=CONTRADICTS RULES | irdai_calling=CONTRADICTS RULES; payment_link=CANNOT BE CONFIRMED (ask insurer) | PASS | 13.51 | 1553 |
| K03 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 11.72 | 2417 |
| K04 | fake-call | en | revival_deadline=CONTRADICTS RULES | policy_status=CANNOT BE CONFIRMED (ask insurer); revival_deadline=CONTRADICTS RULES | PASS | 9.12 | 2460 |
| K05 | fake-call | en | revival_guaranteed=CONTRADICTS RULES | revival_guaranteed=CONTRADICTS RULES | PASS | 9.31 | 2472 |
| K06 | fake-call | en | revival_fee=CONTRADICTS RULES | revival_fee=CONTRADICTS RULES | PASS | 11.11 | 1486 |
| K07 | fake-call | en | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_fee=CANNOT BE CONFIRMED (ask insurer); revival_guaranteed=CONTRADICTS RULES | PASS | 12.95 | 2589 |
| K08 | fake-call | hi | revival_fee=CANNOT BE CONFIRMED (ask insurer) | revival_deadline=CONTRADICTS RULES; revival_fee=CANNOT BE CONFIRMED (ask insurer) | PASS | 13.86 | 2405 |

## Failures (4)

- **A07** (superseded, en): expected `SUPERSEDED`, got `DEPENDS_ON_SALE_DATE`. From 1 April 2024: max 36 months (Reg 7). Policies bought earlier keep their contract terms (Reg 9(3)); the specimen says 48 months.
IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7: Waiting period for pre-existing diseases disclosed by the persons to be insured, shall be max
  - Claim: The Arogya Sanjeevani policy has a 48-month pre-existing disease waiting period of continuous coverage after the date of inception of the first policy.
    - Source: arogya-sanjeevani-hdfc-ergo.pdf · evidence exists=True found=True
    - Quote: Expenses related to the treatment of a pre-existing Disease (PED) and its direct complications shall be excluded until the expiry of 48 months of continuous coverage after the date of inception of the first policy with us.
    - Verifier: SUPPORTED — The quoted passage directly states that expenses for pre-existing Disease and its direct complications are excluded until expiry of 48 months of continuous coverage after inception of the first policy, which establishes the 48-month waiting period claimed.
- **A08** (superseded, hi): expected `SUPERSEDED`, got `DEPENDS_ON_SALE_DATE`. 1 अप्रैल 2024 से: अधिकतम 36 महीने (Reg 7)। इससे पहले खरीदी गई पॉलिसियों पर उनके कॉन्ट्रैक्ट की शर्तें लागू रहती हैं (Reg 9(3)); स्पेसिमेन में 48 महीने लिखा है।
IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7: Waiting period for pre-existing diseases disclosed by the persons 
  - Claim: आरोग्य संजीवनी पॉलिसी में प्री-एग्ज़िस्टिंग बीमारी का वेटिंग पीरियड 48 महीने है।
    - Source: arogya-sanjeevani-hdfc-ergo.pdf · evidence exists=True found=True
    - Quote: Expenses related to the treatment of a pre-existing Disease (PED) and its direct complications shall be excluded until the expiry of 48 months of continuous coverage after the date of inception of the first policy with us.
    - Verifier: SUPPORTED — Quote directly states pre-existing Disease expenses are excluded until expiry of 48 months of continuous coverage, which establishes the 48-month waiting period claimed.
- **A09** (superseded, hinglish): expected `SUPERSEDED`, got `DEPENDS_ON_SALE_DATE`. 1 April 2024 se: maximum 36 months (Reg 7). Isse pehle li gayi policies par unke contract ki terms lagu rehti hain (Reg 9(3)); specimen mein 48 months likha hai.
IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7: Waiting period for pre-existing diseases disclosed by the person
  - Claim: Arogya Sanjeevani mein pre-existing disease ka waiting period 48 months hai
    - Source: arogya-sanjeevani-hdfc-ergo.pdf · evidence exists=True found=True
    - Quote: Expenses related to the treatment of a pre-existing Disease (PED) and its direct complications shall be excluded until the expiry of 48 months of continuous coverage after the date of inception of the first policy with us.
    - Verifier: SUPPORTED — The passage directly states that expenses for pre-existing Disease (PED) are excluded until expiry of 48 months of continuous coverage after inception, which establishes the 48-month waiting period claimed.
- **A20** (misleading-quote, en): expected `SUPERSEDED`, got `DEPENDS_ON_SALE_DATE`. From 1 April 2024: max 36 months (Reg 7). Policies bought earlier keep their contract terms (Reg 9(3)); the specimen says 48 months.
IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7: Waiting period for pre-existing diseases disclosed by the persons to be insured, shall be max
  - Claim: The pre-existing disease waiting period in Arogya Sanjeevani is 48 months.
    - Source: arogya-sanjeevani-hdfc-ergo.pdf · evidence exists=True found=True
    - Quote: Expenses related to the treatment of a pre-existing Disease (PED) and its direct complications shall be excluded until the expiry of 48 months of continuous coverage after the date of inception of the first policy with us.
    - Verifier: SUPPORTED — The passage directly states that expenses for pre-existing Disease (PED) are excluded until 48 months of continuous coverage after inception, which establishes the 48-month waiting period claimed.

Of these, A07, A08, A09, A20 returned `DEPENDS_ON_SALE_DATE` (Fix 36): `cases.jsonl` predates sale-date precedence, has no sale date for them and is not edited. They are counted as failures.

## Sale-date cases (`cases_dates.jsonl`)

- Accuracy: **9/10 = 90.0%**
- **Wrong answers shown as VERIFIED: 1 of 9** (expected decision not VERIFIED). Must be 0.
- Verifier tokens: 21718 total

| ID | Category | Lang | Sale date | Expected | Actual | Result | Latency (s) |
|---|---|---|---|---|---|---|---|
| D01 | older-contract | en | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 9.49 |
| D02 | older-contract | en | 2021-06-15 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 9.23 |
| D03 | current-contract | en | 2025-01-10 | SUPERSEDED | SUPERSEDED | PASS | 9.73 |
| D04 | older-contract | hi | (none / from text) | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 10.94 |
| D05 | current-contract | hinglish | (none / from text) | SUPERSEDED | VERIFIED | **FAIL** | 11.47 |
| D06 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 10.96 |
| D07 | depends | en | (none / from text) | DEPENDS_ON_SALE_DATE | DEPENDS_ON_SALE_DATE | PASS | 8.82 |
| D08 | older-contract | en | 2020-01-01 | APPLIES_TO_OLDER_CONTRACT | APPLIES_TO_OLDER_CONTRACT | PASS | 5.45 |
| D09 | fabricated-quote | en | 2020-01-01 | REFUSED | REFUSED | PASS | 0.03 |
| D10 | not-a-sale-date | en | (none / from text) | VERIFIED | VERIFIED | PASS | 9.93 |

### Sale-date failures (1)

- **D05** (current-contract, hinglish): expected `SUPERSEDED`, got `VERIFIED`. Pre-existing disease ke liye waiting period maximum 36 months hai. (Source: irdai-insurance-products-regulations-2024.pdf)
  - Claim: 2025 me li gayi Arogya Sanjeevani policy me pre-existing disease ka waiting period maximum 36 months continuous coverage tak hai
    - Source: irdai-insurance-products-regulations-2024.pdf · evidence exists=True found=True
    - Quote: Waiting period for pre-existing diseases disclosed by the persons to be insured, shall be maximum up to 36 months of continuous coverage under the Health Insurance policy.
    - Verifier: SUPPORTED — Quote directly states waiting period for disclosed pre-existing diseases shall be maximum up to 36 months of continuous coverage, which matches the claim about Arogya Sanjeevani (a health insurance policy) in 2025.

## Scope and limits

- Distinct governing rules exercised: 6 (PED waiting period; life revival by insurer underwriting; life revival period linked; life revival period non-linked; linked revival no interest or fee; IRDAI does not sell policies or announce bonus).
- Superseded cases are one rule (PED waiting period, 48 vs 36 months) asked in 3 languages.
- Adversarial (injected-draft) cases: languages en.
- The corpus is small (a few IRDAI documents and one standard-product specimen). These results show the fail-closed behaviour on these rules; they do not generalise to insurance questions outside them.

## Notes

- Cases were written before this run and were not tuned afterwards; failures above are reported as observed.
- `adversarial_claim` cases inject a fabricated or misleading draft as the proposer output (a simulated hallucinating proposer) and run the live verifier; the evidence and governing-rule checks are what must fail closed.
- Call scoring requires every expected claim kind to appear with the expected verdict; extra extracted claims do not fail a case unless one is wrongly shown as SUPPORTED BY RULES.
- Speech input is out of scope here: call cases use transcripts, so Muse Voice Transcribe variance does not affect this report.
