# MIT License
# Copyright (c) 2026 Parvind — synthetic data only.
"""Deterministic tests for health_readiness. Stdlib unittest only.

Run: python3 -m unittest test_health_readiness -v
"""
import copy
import unittest

from health_readiness import (
    assess_health_readiness,
    check_ped_waiting_period,
    check_room_limit,
)

PED_WORDING = (
    "A waiting period of 24 months of continuous coverage applies "
    "to pre-existing diseases disclosed at proposal."
)
ROOM_WORDING = "Room entitlement is a Private room up to INR 5,000 per day."

PED_BASE = {
    "policy_ped_waiting_months": 24,
    "policy_ped_wording": PED_WORDING,
    "policy_ped_clause_ref": "Synthetic Policy SYN-HLTH-001, Clause 4.2",
    "elapsed_continuous_coverage_months": 30,
    "diagnosis_matches_disclosed_ped": True,
}
ROOM_BASE = {
    "policy_room_limit_per_day_inr": 5000,
    "policy_entitled_room_category": "Private",
    "policy_room_wording": ROOM_WORDING,
    "policy_room_clause_ref": "Synthetic Policy SYN-HLTH-001, Clause 5.1",
    "selected_room_category": "Private",
    "selected_room_cost_per_day_inr": 4000,
}

FORBIDDEN = ("denied", "claim denied", "payable", "is covered", "not covered")


def assert_clean(test, result):
    blob = (result.reason + " " + result.evidence).lower()
    for word in FORBIDDEN:
        test.assertNotIn(word, blob)
    test.assertTrue(result.evidence)
    test.assertTrue(result.regulatory_context)
    test.assertTrue(result.reason)


class TestPed(unittest.TestCase):
    def ped(self, **over):
        kw = dict(PED_BASE)
        kw.update(over)
        return check_ped_waiting_period(**kw)

    def test_flagged_within_policy_wait(self):
        r = self.ped(elapsed_continuous_coverage_months=8)
        self.assertEqual(r.status, "flagged")
        self.assertIn("24 months", r.reason)
        self.assertIn(PED_WORDING, r.evidence)
        self.assertIn("Clause 4.2", r.evidence)
        self.assertIn("36 months", r.regulatory_context)
        assert_clean(self, r)

    def test_clear_after_policy_wait(self):
        r = self.ped(elapsed_continuous_coverage_months=30)
        self.assertEqual(r.status, "clear")
        assert_clean(self, r)

    def test_clear_at_exact_boundary(self):
        r = self.ped(elapsed_continuous_coverage_months=24)
        self.assertEqual(r.status, "clear")

    def test_clear_when_not_disclosed_ped(self):
        r = self.ped(
            elapsed_continuous_coverage_months=2,
            diagnosis_matches_disclosed_ped=False,
        )
        self.assertEqual(r.status, "clear")

    def test_regulatory_max_is_not_assumed_as_policy_wait(self):
        # Policy wait is 12 months; 18 elapsed is clear even though
        # it is below the 36-month regulatory maximum.
        r = self.ped(
            policy_ped_waiting_months=12,
            elapsed_continuous_coverage_months=18,
        )
        self.assertEqual(r.status, "clear")
        # And a 30-month policy wait still flags at 18 months.
        r2 = self.ped(
            policy_ped_waiting_months=30,
            elapsed_continuous_coverage_months=18,
        )
        self.assertEqual(r2.status, "flagged")

    def test_incomplete_missing_elapsed(self):
        r = self.ped(elapsed_continuous_coverage_months=None)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("elapsed_continuous_coverage_months", r.reason)

    def test_incomplete_missing_wording(self):
        r = self.ped(policy_ped_wording=None)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("policy_ped_wording", r.reason)

    def test_incomplete_missing_match_fact(self):
        r = self.ped(diagnosis_matches_disclosed_ped=None)
        self.assertEqual(r.status, "needs_review")

    def test_contradictory_negative_elapsed(self):
        r = self.ped(elapsed_continuous_coverage_months=-1)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("Contradictory", r.reason)

    def test_contradictory_policy_wait_above_regulatory_max(self):
        r = self.ped(policy_ped_waiting_months=48)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("36-month", r.reason)

    def test_overseas_travel_exception_context(self):
        r = self.ped(
            policy_ped_waiting_months=48,
            is_overseas_travel_policy=True,
            elapsed_continuous_coverage_months=50,
        )
        self.assertEqual(r.status, "clear")
        self.assertIn("Overseas Travel", r.regulatory_context)

    def test_deterministic(self):
        self.assertEqual(self.ped(), self.ped())


class TestRoom(unittest.TestCase):
    def room(self, **over):
        kw = dict(ROOM_BASE)
        kw.update(over)
        return check_room_limit(**kw)

    def test_flagged_over_cost_and_category(self):
        r = self.room(
            selected_room_category="Deluxe",
            selected_room_cost_per_day_inr=8000,
        )
        self.assertEqual(r.status, "flagged")
        self.assertIn("proportionate-deduction", r.reason)
        self.assertIn(ROOM_WORDING, r.evidence)
        assert_clean(self, r)

    def test_flagged_over_cost_same_category(self):
        r = self.room(selected_room_cost_per_day_inr=6000)
        self.assertEqual(r.status, "flagged")

    def test_flagged_over_category_within_cost(self):
        r = self.room(
            selected_room_category="Deluxe",
            selected_room_cost_per_day_inr=4000,
        )
        self.assertEqual(r.status, "flagged")

    def test_clear_within_entitlement(self):
        r = self.room()
        self.assertEqual(r.status, "clear")
        assert_clean(self, r)

    def test_clear_at_exact_limit(self):
        r = self.room(selected_room_cost_per_day_inr=5000)
        self.assertEqual(r.status, "clear")

    def test_incomplete_missing_selected_cost(self):
        r = self.room(selected_room_cost_per_day_inr=None)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("selected_room_cost_per_day_inr", r.reason)

    def test_incomplete_missing_entitlement(self):
        r = self.room(policy_entitled_room_category=None)
        self.assertEqual(r.status, "needs_review")

    def test_contradictory_non_positive_limit(self):
        r = self.room(policy_room_limit_per_day_inr=0)
        self.assertEqual(r.status, "needs_review")
        self.assertIn("Contradictory", r.reason)

    def test_contradictory_negative_cost(self):
        r = self.room(selected_room_cost_per_day_inr=-100)
        self.assertEqual(r.status, "needs_review")

    def test_insufficient_unknown_category(self):
        r = self.room(selected_room_category="ICU")
        self.assertEqual(r.status, "needs_review")
        self.assertIn("unrecognised", r.reason)

    def test_deterministic(self):
        self.assertEqual(self.room(), self.room())


class TestCombinedAndBundle(unittest.TestCase):
    def test_assess_both_and_no_inputs(self):
        out = assess_health_readiness(
            ped_kwargs=dict(PED_BASE), room_kwargs=dict(ROOM_BASE)
        )
        self.assertEqual(
            [c["status"] for c in out["checks"]], ["clear", "clear"]
        )
        self.assertIn("not a coverage decision", out["disclaimer"])
        empty = assess_health_readiness()
        self.assertEqual(
            [c["status"] for c in empty["checks"]],
            ["needs_review", "needs_review"],
        )

    def test_inputs_not_mutated(self):
        ped, room = dict(PED_BASE), dict(ROOM_BASE)
        assess_health_readiness(ped_kwargs=ped, room_kwargs=room)
        self.assertEqual(ped, PED_BASE)
        self.assertEqual(room, ROOM_BASE)

    def test_alongside_validated_fhir_bundle(self):
        from demo_readiness import build_demo
        from nhcx_packager import build_bundle, validate_bundle

        demo = build_demo()
        self.assertEqual(demo["bundle_validation_problems"], [])
        self.assertEqual(
            demo["bundle_resource_types"],
            ["Patient", "Coverage", "Claim"],
        )
        self.assertTrue(demo["bundle_unchanged_by_readiness"])
        statuses = {
            c["check"]: c["status"]
            for c in demo["readiness"]["checks"]
        }
        self.assertEqual(
            statuses,
            {"ped_waiting_period": "flagged", "room_limit": "flagged"},
        )
        # Readiness writes no adjudication into the bundle.
        claim = copy.deepcopy(build_bundle({
            "patient": {"name": "Synthetic Person One"},
            "policy": {"payer": "Synthetic Insurer A",
                       "number": "SYN-POL-001"},
            "provider": {"name": "Synthetic Hospital A"},
            "diagnosis": {"code": "E11.9", "display": "Diabetes"},
            "items": [{"code": "ROOM", "display": "Room", "net": 20000}],
            "total": 20000,
        }))
        self.assertEqual(validate_bundle(claim), [])
        claim_res = next(
            e["resource"] for e in claim["entry"]
            if e["resource"]["resourceType"] == "Claim"
        )
        self.assertNotIn("adjudication", claim_res)


if __name__ == "__main__":
    unittest.main()
