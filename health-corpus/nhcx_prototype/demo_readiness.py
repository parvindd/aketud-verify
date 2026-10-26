# MIT License
# Copyright (c) 2026 Parvind — synthetic demo only.
"""Show readiness flags alongside a validated synthetic FHIR bundle.

The readiness module and the FHIR packager stay separate: this demo
imports both, runs each on synthetic data, and leaves the bundle
exactly as the packager built it (no adjudication is written into it).
Run: python3 demo_readiness.py
"""
import copy
import json

from health_readiness import assess_health_readiness
from nhcx_packager import build_bundle, validate_bundle

SYNTHETIC_CLAIM = {
    "patient": {"name": "Synthetic Person One", "abha": "00-0000-0000-0001"},
    "policy": {"payer": "Synthetic Insurer A", "number": "SYN-POL-001"},
    "provider": {"name": "Synthetic Hospital A"},
    "diagnosis": {"code": "E11.9", "display": "Type 2 diabetes mellitus"},
    "items": [{"code": "ROOM", "display": "Room charges", "net": 20000}],
    "total": 20000,
    "use": "claim",
}

# Explicit synthetic policy terms. The 24-month PED wait is this
# synthetic policy's own term; it is not the 36-month regulatory max.
SYNTHETIC_PED = {
    "policy_ped_waiting_months": 24,
    "policy_ped_wording": (
        "A waiting period of 24 months of continuous coverage "
        "applies to pre-existing diseases disclosed at proposal."
    ),
    "policy_ped_clause_ref": "Synthetic Policy SYN-HLTH-001, Clause 4.2",
    "elapsed_continuous_coverage_months": 8,
    "diagnosis_matches_disclosed_ped": True,
}
SYNTHETIC_ROOM = {
    "policy_room_limit_per_day_inr": 5000,
    "policy_entitled_room_category": "Private",
    "policy_room_wording": (
        "Room entitlement is a Private room up to INR 5,000 per day."
    ),
    "policy_room_clause_ref": "Synthetic Policy SYN-HLTH-001, Clause 5.1",
    "selected_room_category": "Deluxe",
    "selected_room_cost_per_day_inr": 8000,
}


def build_demo():
    bundle = build_bundle(copy.deepcopy(SYNTHETIC_CLAIM))
    before = copy.deepcopy(bundle)
    problems = validate_bundle(bundle)
    readiness = assess_health_readiness(
        ped_kwargs=copy.deepcopy(SYNTHETIC_PED),
        room_kwargs=copy.deepcopy(SYNTHETIC_ROOM),
    )
    return {
        "bundle_validation_problems": problems,
        "bundle_resource_types": [
            e["resource"]["resourceType"] for e in bundle["entry"]
        ],
        "bundle_unchanged_by_readiness": bundle == before,
        "readiness": readiness,
    }


if __name__ == "__main__":
    print(json.dumps(build_demo(), indent=2))
