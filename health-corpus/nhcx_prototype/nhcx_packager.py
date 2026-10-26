# MIT License
# Copyright (c) 2026 Parvind — NHCX packager prototype (synthetic data only).
"""Build and validate a FHIR R4 Claim Bundle following NHCX profiles (NRCeS IG).

Input: structured claim fields (dict). Output: FHIR R4 Bundle (dict/JSON).
Dependency-light: Python standard library only. Synthetic examples only.
This prototype never makes a coverage decision.
"""
import json, uuid

PROFILE_BASE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"

def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

def build_bundle(claim: dict) -> dict:
    """claim keys: patient{name,abha}, policy{payer,number}, provider{name},
    diagnosis{code,display}, items[{code,display,net}], total, use(claim|preauthorization)"""
    patient_id, coverage_id, claim_id = _id("patient"), _id("coverage"), _id("claim")
    entries = [
        {"resource": {"resourceType": "Patient", "id": patient_id,
                      "meta": {"profile": [PROFILE_BASE + "NHCXPatient"]},
                      "name": [{"text": claim["patient"]["name"]}],
                      "identifier": [{"system": "https://abha.abdm.gov.in", "value": claim["patient"].get("abha", "SYNTHETIC")}] }},
        {"resource": {"resourceType": "Coverage", "id": coverage_id,
                      "meta": {"profile": [PROFILE_BASE + "NHCXCoverage"]},
                      "status": "active", "beneficiary": {"reference": f"Patient/{patient_id}"},
                      "payor": [{"display": claim["policy"]["payer"]}],
                      "subscriberId": claim["policy"]["number"]} },
        {"resource": {"resourceType": "Claim", "id": claim_id,
                      "meta": {"profile": [PROFILE_BASE + "NHCXClaim"]},
                      "status": "active", "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "institutional"}]},
                      "use": claim.get("use", "claim"),
                      "patient": {"reference": f"Patient/{patient_id}"},
                      "provider": {"display": claim["provider"]["name"]},
                      "priority": {"coding": [{"code": "normal"}]},
                      "insurance": [{"sequence": 1, "focal": True, "coverage": {"reference": f"Coverage/{coverage_id}"}}],
                      "diagnosis": [{"sequence": 1, "diagnosisCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": claim["diagnosis"]["code"], "display": claim["diagnosis"]["display"]}]}}],
                      "item": [{"sequence": i + 1, "productOrService": {"coding": [{"code": it["code"], "display": it["display"]}]},
                                "net": {"value": it["net"], "currency": "INR"}} for i, it in enumerate(claim["items"])],
                      "total": {"value": claim["total"], "currency": "INR"}}},
    ]
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}

def validate_bundle(bundle: dict) -> list:
    """Return list of problems; empty list means the bundle passes prototype checks."""
    problems = []
    if bundle.get("resourceType") != "Bundle":
        problems.append("root resourceType must be Bundle")
    types = [e.get("resource", {}).get("resourceType") for e in bundle.get("entry", [])]
    for need in ("Patient", "Coverage", "Claim"):
        if need not in types:
            problems.append(f"missing {need} resource")
    claim = next((e["resource"] for e in bundle.get("entry", []) if e.get("resource", {}).get("resourceType") == "Claim"), None)
    if claim:
        total = claim.get("total", {}).get("value")
        summed = sum(i.get("net", {}).get("value", 0) for i in claim.get("item", []))
        if total is not None and abs(total - summed) > 0.01:
            problems.append(f"Claim.total {total} != sum of items {summed}")
        if not claim.get("diagnosis"):
            problems.append("Claim.diagnosis is required")
    return problems

EXAMPLES = [
    {"patient": {"name": "Synthetic Person One", "abha": "00-0000-0000-0001"}, "policy": {"payer": "Synthetic Insurer A", "number": "SYN-POL-001"}, "provider": {"name": "Synthetic Hospital A"}, "diagnosis": {"code": "K35.8", "display": "Acute appendicitis"}, "items": [{"code": "APPX", "display": "Appendicectomy package", "net": 45000}], "total": 45000, "use": "claim"},
    {"patient": {"name": "Synthetic Person Two", "abha": "00-0000-0000-0002"}, "policy": {"payer": "Synthetic Insurer B", "number": "SYN-POL-002"}, "provider": {"name": "Synthetic Hospital B"}, "diagnosis": {"code": "H25.9", "display": "Senile cataract"}, "items": [{"code": "CAT", "display": "Cataract surgery", "net": 28000}], "total": 28000, "use": "preauthorization"},
    {"patient": {"name": "Synthetic Person Three", "abha": "00-0000-0000-0003"}, "policy": {"payer": "Synthetic Insurer A", "number": "SYN-POL-003"}, "provider": {"name": "Synthetic Hospital C"}, "diagnosis": {"code": "J18.9", "display": "Pneumonia"}, "items": [{"code": "ROOM", "display": "Room charges", "net": 12000}, {"code": "MED", "display": "Medicines", "net": 8000}], "total": 20000, "use": "claim"},
]

if __name__ == "__main__":
    for i, ex in enumerate(EXAMPLES, 1):
        b = build_bundle(ex)
        print(f"example {i}: problems={validate_bundle(b)}")
        print(json.dumps(b)[:200], "...")
