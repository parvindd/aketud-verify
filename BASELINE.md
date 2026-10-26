# BASELINE — pre-hackathon foundation

Imported from MapleSage Pvt Ltd's private repository; pre-dates 27 Oct 2026.

Everything in this commit (tag `baseline-pre-hackathon`) existed **before** the
Meta Global AI Developer Hackathon building period (27 Oct – 4 Nov 2026).
It is the foundation, not the hackathon entry. All hackathon work is in commits
**after** this tag.

## What the foundation does

A deterministic, no-API insurance answering path for Indian health insurance:

- **ASK lookup** — answers only six frozen demo questions (English, Hindi,
  Hinglish), and only after verifying that the cited source PDF exists and
  every evidence passage is found in its extracted text. Near-misses are
  refused as ambiguous; anything else is refused as unsupported. Missing
  source or passage gives `needs_review`. **No language model is involved.**
- **HEALTH readiness flags** — two checks on explicit synthetic policy terms:
  pre-existing-disease waiting period and room limit. Outputs `flagged`,
  `clear` or `needs_review`. Never a coverage decision, never an amount.
- **NHCX packager** — builds and validates a synthetic FHIR R4 Claim Bundle
  with NHCX profile URLs.

## Files

Dates: "committed" = first commit date in the private repository;
"file date" = last-modified time of a file that existed there but was never
committed (UTC).

| File | What it does | Date |
|---|---|---|
| `health-corpus/nhcx_prototype/ask.py` | Deterministic ASK lookup with source/passage checks and refusals | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/test_ask.py` | 16 tests for the ASK lookup | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/demo_ask.py` | Runs the ASK lookup on the demo questions | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/health_readiness.py` | PED waiting-period and room-limit flags | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/test_health_readiness.py` | 26 tests for the readiness flags | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/demo_readiness.py` | Runs the flags next to a synthetic FHIR bundle | file date 2026-10-22 |
| `health-corpus/nhcx_prototype/nhcx_packager.py` | Synthetic FHIR R4 / NHCX Claim Bundle builder and validator | committed 2026-10-19 |
| `health-corpus/nhcx_prototype/example_1..3.json` | Synthetic claim inputs for the packager | committed 2026-10-19 |
| `health-corpus/nhcx_prototype/README.md` | Packager notes | committed 2026-10-19 |
| `health-corpus/SOURCES.csv` | Public source documents: issuer, date, URL | committed 2026-10-19; one row added 2026-10-22 |
| `health-corpus/CLAIM_READINESS_DESIGN.md` | Readiness design notes | committed 2026-10-19; edited 2026-10-22 |
| `DEMO_QUESTIONS.md` | The six frozen demo questions | committed 2026-10-20; edited 2026-10-22 |
| `DEMO.md` | How to run the readiness demo | file date 2026-10-22 |

## Source documents (not in this repository)

`ask.py` reads three public PDFs from `health-corpus/raw/`. They are listed with
their public URLs in `health-corpus/SOURCES.csv` and are **not committed**
(third-party documents; `health-corpus/raw/*.pdf` is git-ignored). Download them
to `health-corpus/raw/` before running the tests:

- `irdai-insurance-products-regulations-2024.pdf` — IRDAI (Insurance Products) Regulations, 2024
- `master-circular-health-2024.pdf` — IRDAI Master Circular on Health Insurance Business, 29 May 2024
- `arogya-sanjeevani-hdfc-ergo.pdf` — Arogya Sanjeevani prospectus (IRDAI standard product, HDFC ERGO specimen)

## Test result at baseline

```
cd health-corpus/nhcx_prototype
python3 -m unittest test_ask test_health_readiness
Ran 42 tests — OK   (16 ASK + 26 HEALTH)
```

Run on 26 Oct 2026, Python 3.10, with the three PDFs present. Requires
`pdftotext` (poppler) on PATH. Standard library only otherwise.

## Known gaps at baseline

- No language model anywhere. ASK only answers six hard-coded questions.
- No claim-level verification: nothing checks whether a generated answer is
  supported by its source, because nothing is generated.
- Readiness flags run on synthetic policy terms only; no real policy parsing.
- Source PDFs must be fetched manually; there is no fetch script.

## Deliberately excluded

Motor-photo prototype and its outputs, evaluation drafts, US corpus, planning
and task notes, editor extensions, and all private product code.
