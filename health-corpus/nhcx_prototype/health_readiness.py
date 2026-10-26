# MIT License
# Copyright (c) 2026 Parvind — health-readiness prototype (synthetic data only).
"""Deterministic, no-API health-claim readiness flags.

Two checks only: PED waiting period and room limit. Each check reads
explicit synthetic policy terms supplied by the caller. It never assumes
the regulatory maximum is the policy's own waiting period, never
calculates an amount owed, and never decides whether a claim succeeds.
The insurer decides admissibility.

Statuses: ``flagged``, ``clear``, ``needs_review``. Missing,
contradictory, or insufficient facts always give ``needs_review``.

Separate from ``nhcx_packager``: this module imports nothing from it and
never reads or writes a FHIR bundle.
"""
from dataclasses import asdict, dataclass

DISCLAIMER = (
    "Readiness check only — not a coverage decision. "
    "The insurer decides admissibility."
)

PED_REGULATORY_CONTEXT = (
    "IRDAI (Insurance Products) Regulations, 2024, Schedule III, "
    "Regulation 7: the waiting period for pre-existing diseases "
    "disclosed by the persons to be insured shall be maximum up to "
    "36 months of continuous coverage (Overseas Travel Policies "
    "excepted). This is a regulatory maximum, not the waiting period "
    "of any given policy; the policy wording may specify less, so "
    "this check uses only the supplied policy term."
)
PED_REGULATORY_CONTEXT_OVERSEAS = (
    "IRDAI (Insurance Products) Regulations, 2024, Schedule III, "
    "Regulation 7: the 36-month maximum for disclosed pre-existing "
    "diseases does not apply to Overseas Travel Policies. This check "
    "uses only the supplied policy term."
)
ROOM_REGULATORY_CONTEXT = (
    "Master Circular on Health Insurance Business, 29 May 2024: "
    "room-rent limits and any proportionate-deduction terms must be "
    "disclosed in the policy wording / Customer Information Sheet. "
    "This check flags a possible proportionate-deduction risk only; "
    "it does not work out any amount."
)

_ROOM_RANK = {
    "general ward": 1,
    "semi-private": 2,
    "semi private": 2,
    "private": 3,
    "deluxe": 4,
    "suite": 5,
}


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str  # flagged | clear | needs_review
    reason: str
    evidence: str
    regulatory_context: str

    def to_dict(self):
        return asdict(self)


def _evidence(clause_ref, wording):
    if clause_ref and wording and str(wording).strip():
        return f'{clause_ref}: "{str(wording).strip()}"'
    return "No usable policy wording supplied."


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_ped_waiting_period(
    *,
    policy_ped_waiting_months=None,
    policy_ped_wording=None,
    policy_ped_clause_ref=None,
    elapsed_continuous_coverage_months=None,
    diagnosis_matches_disclosed_ped=None,
    is_overseas_travel_policy=False,
):
    """Flag if a disclosed PED is still inside the policy's own wait.

    All policy facts are explicit caller-supplied synthetic terms. The
    36-month regulatory maximum is context only and is never used as
    the policy's waiting period.
    """
    context = (
        PED_REGULATORY_CONTEXT_OVERSEAS
        if is_overseas_travel_policy
        else PED_REGULATORY_CONTEXT
    )
    evidence = _evidence(policy_ped_clause_ref, policy_ped_wording)

    missing = []
    if policy_ped_waiting_months is None:
        missing.append("policy_ped_waiting_months")
    if not policy_ped_wording or not str(policy_ped_wording).strip():
        missing.append("policy_ped_wording")
    if not policy_ped_clause_ref or not str(policy_ped_clause_ref).strip():
        missing.append("policy_ped_clause_ref")
    if elapsed_continuous_coverage_months is None:
        missing.append("elapsed_continuous_coverage_months")
    if diagnosis_matches_disclosed_ped is None:
        missing.append("diagnosis_matches_disclosed_ped")
    if missing:
        return CheckResult(
            "ped_waiting_period", "needs_review",
            "Missing facts: " + ", ".join(missing) + ".",
            evidence, context,
        )

    if not _is_int(policy_ped_waiting_months) or not _is_int(
        elapsed_continuous_coverage_months
    ) or not isinstance(diagnosis_matches_disclosed_ped, bool):
        return CheckResult(
            "ped_waiting_period", "needs_review",
            "Contradictory facts: waiting period and elapsed coverage "
            "must be whole months and the disclosed-PED match must be "
            "true or false.",
            evidence, context,
        )
    if policy_ped_waiting_months < 0 or elapsed_continuous_coverage_months < 0:
        return CheckResult(
            "ped_waiting_period", "needs_review",
            "Contradictory facts: waiting period and elapsed coverage "
            "cannot be negative.",
            evidence, context,
        )
    if (
        not is_overseas_travel_policy
        and policy_ped_waiting_months > 36
    ):
        return CheckResult(
            "ped_waiting_period", "needs_review",
            "Contradictory facts: supplied policy PED waiting period "
            "exceeds the 36-month regulatory maximum for disclosed "
            "PEDs; confirm the policy wording.",
            evidence, context,
        )

    if not diagnosis_matches_disclosed_ped:
        return CheckResult(
            "ped_waiting_period", "clear",
            "Diagnosis does not match a disclosed pre-existing "
            "disease on the supplied facts, so this PED check raises "
            "no flag.",
            evidence, context,
        )
    if elapsed_continuous_coverage_months >= policy_ped_waiting_months:
        return CheckResult(
            "ped_waiting_period", "clear",
            f"Elapsed continuous coverage "
            f"({elapsed_continuous_coverage_months} months) has "
            f"reached the policy PED waiting period "
            f"({policy_ped_waiting_months} months) on the supplied "
            f"facts.",
            evidence, context,
        )
    return CheckResult(
        "ped_waiting_period", "flagged",
        f"Disclosed pre-existing disease with elapsed continuous "
        f"coverage ({elapsed_continuous_coverage_months} months) "
        f"below the policy PED waiting period "
        f"({policy_ped_waiting_months} months).",
        evidence, context,
    )


def check_room_limit(
    *,
    policy_room_limit_per_day_inr=None,
    policy_entitled_room_category=None,
    policy_room_wording=None,
    policy_room_clause_ref=None,
    selected_room_category=None,
    selected_room_cost_per_day_inr=None,
):
    """Flag if the selected room exceeds the policy entitlement."""
    evidence = _evidence(policy_room_clause_ref, policy_room_wording)

    missing = []
    if policy_room_limit_per_day_inr is None:
        missing.append("policy_room_limit_per_day_inr")
    if not policy_entitled_room_category or not str(
        policy_entitled_room_category
    ).strip():
        missing.append("policy_entitled_room_category")
    if not policy_room_wording or not str(policy_room_wording).strip():
        missing.append("policy_room_wording")
    if not policy_room_clause_ref or not str(policy_room_clause_ref).strip():
        missing.append("policy_room_clause_ref")
    if not selected_room_category or not str(selected_room_category).strip():
        missing.append("selected_room_category")
    if selected_room_cost_per_day_inr is None:
        missing.append("selected_room_cost_per_day_inr")
    if missing:
        return CheckResult(
            "room_limit", "needs_review",
            "Missing facts: " + ", ".join(missing) + ".",
            evidence, ROOM_REGULATORY_CONTEXT,
        )

    if not _is_int(policy_room_limit_per_day_inr) or not _is_int(
        selected_room_cost_per_day_inr
    ):
        return CheckResult(
            "room_limit", "needs_review",
            "Contradictory facts: room limit and selected room cost "
            "must be whole rupees per day.",
            evidence, ROOM_REGULATORY_CONTEXT,
        )
    if policy_room_limit_per_day_inr <= 0 or selected_room_cost_per_day_inr <= 0:
        return CheckResult(
            "room_limit", "needs_review",
            "Contradictory facts: room limit and selected room cost "
            "must be above zero.",
            evidence, ROOM_REGULATORY_CONTEXT,
        )

    entitled_key = str(policy_entitled_room_category).strip().lower()
    selected_key = str(selected_room_category).strip().lower()
    if entitled_key not in _ROOM_RANK or selected_key not in _ROOM_RANK:
        return CheckResult(
            "room_limit", "needs_review",
            "Insufficient facts: unrecognised room category "
            f"(entitled={policy_entitled_room_category!r}, "
            f"selected={selected_room_category!r}); known categories "
            "are General Ward, Semi-Private, Private, Deluxe, Suite.",
            evidence, ROOM_REGULATORY_CONTEXT,
        )

    over_cost = selected_room_cost_per_day_inr > policy_room_limit_per_day_inr
    over_category = _ROOM_RANK[selected_key] > _ROOM_RANK[entitled_key]
    if over_cost or over_category:
        parts = []
        if over_category:
            parts.append(
                f"selected category {selected_room_category} is above "
                f"entitled category {policy_entitled_room_category}"
            )
        if over_cost:
            parts.append(
                f"selected cost INR {selected_room_cost_per_day_inr}/day "
                f"exceeds the limit INR "
                f"{policy_room_limit_per_day_inr}/day"
            )
        return CheckResult(
            "room_limit", "flagged",
            "Room above entitlement: " + "; ".join(parts) + ". "
            "Possible proportionate-deduction risk.",
            evidence, ROOM_REGULATORY_CONTEXT,
        )
    return CheckResult(
        "room_limit", "clear",
        f"Selected room ({selected_room_category}, INR "
        f"{selected_room_cost_per_day_inr}/day) is within the "
        f"entitlement ({policy_entitled_room_category}, INR "
        f"{policy_room_limit_per_day_inr}/day) on the supplied facts.",
        evidence, ROOM_REGULATORY_CONTEXT,
    )


def assess_health_readiness(*, ped_kwargs=None, room_kwargs=None):
    """Run both checks. ``None`` for a check gives ``needs_review``."""
    ped = (
        check_ped_waiting_period(**ped_kwargs)
        if ped_kwargs is not None
        else CheckResult(
            "ped_waiting_period", "needs_review",
            "Missing facts: no PED facts supplied.",
            "No usable policy wording supplied.",
            PED_REGULATORY_CONTEXT,
        )
    )
    room = (
        check_room_limit(**room_kwargs)
        if room_kwargs is not None
        else CheckResult(
            "room_limit", "needs_review",
            "Missing facts: no room facts supplied.",
            "No usable policy wording supplied.",
            ROOM_REGULATORY_CONTEXT,
        )
    )
    return {
        "disclaimer": DISCLAIMER,
        "checks": [ped.to_dict(), room.to_dict()],
    }
