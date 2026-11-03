# Answer-key changes

The case files (`cases.jsonl`, `cases_dates.jsonl`) are never edited
after a run. When an expected decision has to change, the change is
listed here and applied through `answer_key_overrides.jsonl`, which
`run.py` reads. An override only applies while the case still expects
its listed original value.

`REPORT.md` shows both scores, the **original key** and the **revised
key**. Revised rows read `ORIGINAL → REVISED (revised)`.

| Case | Original | Revised | Kind | Reason |
|---|---|---|---|---|
| A07 | SUPERSEDED | DEPENDS_ON_SALE_DATE | Design change (Fix 36) | No sale date in the question. The 2024 regulation (36 months, Reg 7) governs contracts from 1 April 2024. Reg 9(3) keeps the terms of earlier contracts, where the specimen says 48 months. Which one applies depends on the sale date. |
| A08 | SUPERSEDED | DEPENDS_ON_SALE_DATE | Design change (Fix 36) | Same question as A07, in Hindi. No sale date. |
| A09 | SUPERSEDED | DEPENDS_ON_SALE_DATE | Design change (Fix 36) | Same question as A07, in Hinglish. No sale date. |
| A20 | SUPERSEDED | DEPENDS_ON_SALE_DATE | Design change (Fix 36) | Injected real specimen quote (48 months). No sale date. |
| D05 | SUPERSEDED | VERIFIED | Key error | The policy was bought in 2025, after 1 April 2024. The model cited the governing rule (Reg 7) directly, and 36 months is correct for that contract. The case was written assuming the model would cite the specimen. |

## How the key was changed

- The **design changes** (A07, A08, A09, A20) come from a deliberate
  change to the decision rules in Fix 36 (sale-date aware precedence).
  The cases were written before that rule existed.
- The **key error** (D05) was found in the first live run after
  Fix 36 (report of 2026-11-02). It counted as one wrong VERIFIED
  under the original key. The decision itself was checked against the
  source: the quoted Reg 7 text was found in the PDF, and the verifier
  rated it SUPPORTED.
- Changing an expectation does not change the code being measured.
  Only the scoring changes, and the original score is still reported
  next to the revised one.

## Cases added (not changes)

- **D11** (English) and **D12** (Hinglish) were added for Fix 37. In
  both, the policy was bought in 2021 and the claim cites Reg 7
  directly. Expected: APPLIES_TO_OLDER_CONTRACT.

## Filename rename

- `arogya-sanjeevani-hdfc-ergo.pdf` was renamed to
  `arogya-sanjeevani-specimen.pdf` in the code, the case files
  (A18, A20, A22, D08, D09) and the docs: filename rename only, no
  expectation changed.
