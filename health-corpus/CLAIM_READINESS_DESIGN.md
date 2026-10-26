# Claim-Readiness Check — Design

Status: design draft, 2026-10-18. Sources are the corpus in `raw/` (see `SOURCES.csv`). This feature flags risks before a health claim is filed. **It never makes a coverage decision** — only the insurer can admit, repudiate or settle a claim. Every output says so.

## 1. Inputs

| Input | Form | Required |
| --- | --- | --- |
| Policy wording / Customer Information Sheet (CIS) | PDF or structured fields: sum insured, PED waiting period, disease-wise waiting periods, sub-limits, room-rent cap, co-pay %, exclusions, policy start/inception date, renewals | Yes |
| Hospital documents | Discharge summary, bills, pre-auth form, investigation reports (PDF/image → OCR text) | Yes |
| Claim facts | Admission/discharge dates, diagnosis (ICD-10 if available), treatment, billed amount, hospital network status | Yes |
| Consent artefact | ABDM/ABHA consent or explicit in-app consent (see §6) | Yes — no processing without it |

All people in examples/tests are synthetic.

## 2. Rule checks (each cites its clause)

| # | Check | Logic | IRDAI source |
| --- | --- | --- | --- |
| R1 | Waiting period (initial 30 days) | Admission date < policy inception + initial waiting period (except accident) → flag | Health Insurance Regulations 2016; standard terms in Master Circular on Health Insurance Business, 29.05.2024 |
| R2 | Pre-existing disease (PED) | Diagnosis matches declared/un-declared PED and the policy's PED waiting period not completed → flag. For disclosed PEDs the 2024 cap is maximum up to 36 months of continuous coverage (Overseas Travel Policies excepted); the policy may specify less, so check the wording, not the cap alone | IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7; Health Regs 2016 |
| R3 | Disease-specific waiting period | Listed ailment (e.g. hernia, cataract) within its 1–2 yr wait → flag | Policy wording per standard exclusions framework, Master Circular 2024 |
| R4 | Moratorium | After 5 continuous years (60 months), no claim contestable except proven fraud/non-disclosure of material fact → suppress PED/non-disclosure flags, note protection | Master Circular 2024 (moratorium reduced 8 yrs → 5 yrs) |
| R5 | Sub-limits | Billed head (e.g. cataract, AYUSH) exceeds disease/procedure sub-limit → flag excess | Policy wording; standard-product norms (Arogya Sanjeevani prospectus) |
| R6 | Room rent / proportionate deduction | Room category above eligible limit → flag proportionate deduction risk on associated charges | Policy wording; Master Circular 2024 disclosure norms |
| R7 | Co-pay | Senior-citizen / floater co-pay % applied → show expected patient share (estimate, not a decision) | Policy wording; CIS per Master Circular 2024 |
| R8 | Exclusions | Treatment matches standard exclusion list (e.g. cosmetic, obesity, infertility unless covered) → flag with exclusion name | Standard exclusions framework, Master Circular 2024; Arogya Sanjeevani wording |
| R9 | Missing documents | Discharge summary, final bill, payment proof, ID, cancelled cheque/NEFT, pre-auth approval (cashless) absent → list | Health Regs 2016 claim-document norms; NHCX document requirements (NRCeS FHIR IG) |
| R10 | Cashless / timelines | Non-network hospital → reimbursement route; claim intimation/filing window from discharge date → flag deadline | Master Circular 2024 (cashless authorisation timelines); Health Regs 2016 Reg. 27 claim settlement timelines |
| R11 | Sum insured adequacy | Cumulative claims + current bill vs sum insured + restored/CB amounts → flag shortfall risk | Policy wording |
| R12 | AYUSH / modern treatments | AYUSH inpatient or listed modern treatment treated at par → no adverse flag; flag only if wording restricts | Master Circular 2024 (AYUSH & modern treatments at par) |

Each flag carries: rule id, severity (blocker-risk / warning / info), evidence snippet from the document, clause citation (document name + section), and a plain-language explanation.

## 3. Output format

```json
{
  "disclaimer": "Readiness check only — not a coverage decision. The insurer decides admissibility.",
  "summary": {"blocker_risks": 1, "warnings": 2, "info": 1},
  "flags": [{"rule": "R2", "severity": "blocker-risk", "clause": "IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7 — PED waiting period", "evidence": "...", "explanation": {"en": "...", "hi": "...", "hinglish": "..."}}],
  "missing_documents": ["final hospital bill"],
  "next_steps": ["..."]
}
```

Languages: English; Hindi in Devanagari with English insurance terms transliterated in Devanagari (e.g. वेटिंग पीरियड, को-पे, सब-लिमिट); Hinglish in Roman script mixing Hindi grammar with English terms. The same flag is rendered in all three; no language version may soften or strengthen the risk wording.

## 4. Refusal cases (system declines to answer)

- Asked to decide/predict claim approval, repudiation or payable amount → refuse that part; offer the readiness flags instead.
- No consent artefact, or request involves another person's policy/documents without authorisation → refuse processing.
- Request to alter, back-date or fabricate hospital/policy documents → refuse.
- Non-health lines (motor, life, travel-only), legal advice, or Ombudsman-filing drafting presented as legal representation → out of scope; may signpost the Insurance Ombudsman (Rules 2017) factually.
- Illegible/absent policy wording → do not guess clauses; ask for the document.

## 5. NHCX FHIR mapping

Per the NRCeS *Implementation Guide for Adoption of FHIR in ABDM and NHCX* (`raw/nrces-fhir-ig-abdm-nhcx.pdf`), using NHCX profiles on FHIR R4:

| Claim-readiness field | FHIR resource |
| --- | --- |
| Patient (ABHA-linked) | `Patient` |
| Policy / coverage | `Coverage` (payer, policy no., sum insured) |
| Hospital | `Organization` (provider), treating doctor `Practitioner` |
| Encounter / admission | `Encounter` |
| Diagnosis | `Condition` (ICD-10) referenced from `Claim.diagnosis` |
| Procedures / line items | `Claim.item` (productOrService, quantity, unitPrice, net) |
| Bill total / patient share estimate | `Claim.total`, `ClaimResponse.request`/adjudication in response |
| Documents (discharge summary, bills) | `DocumentReference` / `Claim.supportingInfo` |
| Pre-auth & claim exchange | `Claim.use` = `preauthorization` / `claim`; payer reply `ClaimResponse` (outcome, adjudication, error) |
| Bundle for exchange | `Bundle` (type `collection`) with NHCX profile URLs `https://nrces.in/ndhm/fhir/r4/StructureDefinition/...` |

The readiness check runs **before** packaging; its flags are internal and are never written into the FHIR bundle as adjudication data.

## 6. Data privacy

- Health data is sensitive personal data under India's DPDP Act 2023: purpose-limited, consent-first processing; consent artefact stored with the claim packet and revocable.
- India hosting only (data residency in India regions); encryption in transit (TLS) and at rest; no document retention beyond the stated purpose without fresh consent.
- Minimum-necessary extraction: parse documents, retain structured fields; raw PDFs in access-controlled, audit-logged storage; no use of any customer data for model training.
- Access: role-based, per-case; secrets via a vault, never in code/logs; redaction of ABHA/Aadhaar numbers in logs and outputs.
- Breach/incident process and grievance contact named in the consent notice, in en/hi/hinglish.
