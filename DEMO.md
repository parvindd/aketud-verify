# DEMO.md — health-readiness flags (synthetic, no API)

Deterministic readiness flags next to a synthetic FHIR bundle. This is
not a coverage decision; the insurer decides admissibility. No amount
owed is worked out.

## Run

```
cd health-corpus/nhcx_prototype
../../.venv/bin/python -m unittest test_health_readiness -v
../../.venv/bin/python demo_readiness.py
../../.venv/bin/python nhcx_packager.py
```

Stdlib only. No network, no paid API, no SAM run.

## What the tests prove

Module: [health_readiness.py](health-corpus/nhcx_prototype/health_readiness.py),
separate from [nhcx_packager.py](health-corpus/nhcx_prototype/nhcx_packager.py)
(it imports nothing from the packager). Tests:
[test_health_readiness.py](health-corpus/nhcx_prototype/test_health_readiness.py)
(26 tests).

PED waiting-period check (`check_ped_waiting_period`), from explicit
synthetic policy terms, elapsed continuous coverage, and whether the
diagnosis matches a disclosed pre-existing disease:

- `flagged` when a disclosed PED is inside the policy's own waiting
  period (synthetic: 8 elapsed months vs a 24-month policy wait).
- `clear` when elapsed coverage reaches the policy wait, including at
  the exact boundary, and when the diagnosis is not a disclosed PED.
- The 36-month figure is regulatory context only. A synthetic 12-month
  policy wait is `clear` at 18 elapsed months, and a 30-month policy
  wait is `flagged` at 18 months. The regulatory maximum is never used
  as the policy's waiting period. Context cited: IRDAI (Insurance
  Products) Regulations, 2024, Schedule III, Regulation 7 (maximum up
  to 36 months of continuous coverage for disclosed PEDs, Overseas
  Travel Policies excepted).
- `needs_review` for missing facts (elapsed months, policy wording,
  disclosed-PED match), contradictory facts (negative months, or a
  supplied policy wait above 36 months for a non-overseas policy), and
  the overseas-travel context switches the regulatory context text.

Room-limit check (`check_room_limit`), from explicit synthetic room
entitlement and the selected category/cost:

- `flagged` when the selected category is above the entitled category,
  or the selected cost per day exceeds the limit, or both (synthetic:
  Deluxe at INR 8,000/day vs Private up to INR 5,000/day). The reason
  names a possible proportionate-deduction risk only.
- `clear` within entitlement, including at the exact cost limit.
- `needs_review` for missing entitlement/cost, non-positive or
  negative amounts, and an unrecognised room category.
  Context cited: Master Circular on Health Insurance Business,
  29 May 2024 (room-rent limits and proportionate-deduction terms to
  be disclosed in the policy wording / Customer Information Sheet).

Every result carries a status (`flagged` / `clear` / `needs_review`),
a concise reason, an evidence citation quoting the supplied synthetic
policy wording with its clause reference, and the regulatory context
above. Repeated calls with the same inputs give equal results.

## Alongside the FHIR bundle

[demo_readiness.py](health-corpus/nhcx_prototype/demo_readiness.py)
builds a synthetic bundle with the existing packager, validates it
(`validate_bundle` returns no problems; resources are Patient,
Coverage, Claim), runs both readiness checks, and shows that the
bundle is unchanged by the readiness step and carries no adjudication.
Both synthetic checks flag in the demo. The packager itself is
unchanged and still runs its three examples with no problems.

## Ask (deterministic lookup, no API)

This is a deterministic lookup, not a connected language model.
[ask.py](health-corpus/nhcx_prototype/ask.py) answers only the six
frozen questions in [DEMO_QUESTIONS.md](DEMO_QUESTIONS.md), keyed by
their frozen wordings (English, Hindi, and Hinglish where the frozen
spec gives them). Matching is exact after normalisation. It is
separate from the readiness checks and the FHIR packager above and
imports nothing from them. Stdlib plus `pdftotext` only, no network,
no paid API.

```
cd health-corpus/nhcx_prototype
../../.venv/bin/python -m unittest test_ask -v
../../.venv/bin/python demo_ask.py
```

Tests: [test_ask.py](health-corpus/nhcx_prototype/test_ask.py)
(16 tests). Every answered result carries the answer, the source
title, the exact clause/paragraph or page reference, and a short
supporting quotation. Before an answer is returned, the cited PDF in
`health-corpus/raw/` must exist and the cited passage must be found
in text extracted from that PDF; the tests re-extract the PDFs
independently and check the quotations again.

What the tests demonstrate:

- PED maximum: maximum up to 36 months of continuous coverage for
  disclosed pre-existing diseases, stated as a cap (insurers may have
  a lesser period), with the Overseas Travel Policies exception.
  Cited to IRDAI (Insurance Products) Regulations, 2024, Schedule III,
  Regulation 7 (Gazette p. 37). The Master Circular is not cited for
  this figure.
- Moratorium: 60 months of continuous coverage, after which no policy
  and claim is contestable except for established fraud. Cited to
  Master Circular on Health Insurance Business, 29 May 2024, para 13.
  The Hinglish frozen wording returns this answer in the demo.
- Initial waiting period (Arogya Sanjeevani specimen): 30 days for
  illness, not applicable to accidents. Cited to the Arogya Sanjeevani
  prospectus (specimen), Code-Excl03.
- Cosmetic surgery (Arogya Sanjeevani specimen): not covered, with
  the full "unless" qualification kept (reconstruction following an
  Accident, Burn(s) or Cancer, or medically necessary treatment to
  remove a direct and immediate health risk, certified by the
  attending Medical Practitioner). Cited to §4.5, Code-Excl08.
- The two frozen health-flow scenarios return flags only: PED waiting
  period not completed (policy started 8 months ago, declared PED;
  never "claim denied"), and proportionate-deduction risk (room
  category above the eligible limit; no payable computed).
- Unsupported questions are refused as unsupported. Questions that
  resemble a frozen question without matching it exactly, fragments,
  and questions touching two frozen topics are refused as ambiguous.
  No answer is inferred from resemblance.
- If the cited source or required passage is unavailable, the result
  is `needs_review` with no answer, citation, or quotation.
- Repeated calls with the same input give equal results.

[demo_ask.py](health-corpus/nhcx_prototype/demo_ask.py) runs the
Hinglish moratorium question (returns the 60-month cited answer),
then the Hinglish cosmetic-surgery question (returns the qualified
Code-Excl08 answer above).

## Not claimed

No coverage decision, no claim outcome, and no amount owed is stated
or worked out anywhere in the module, tests, or demo output.
