from __future__ import annotations

from .types import DECISION, ENTRY, SUPPORT, TIER_ORDER

# The five existing roles map onto three decision tiers. No new roles are
# introduced; see METHODOLOGY.md section 2.
ROLE_TIERS = {
    "class_teacher": ENTRY,
    "catalyst_member": ENTRY,
    "office": ENTRY,
    "academic_supervisor": SUPPORT,
    "administrator": DECISION,
}

# Fields that identify individual students or staff. Analyses that expose these
# verbatim are capped at SUPPORT; above that the same data is aggregated.
IDENTITY_FIELD_HINTS = (
    "roll",
    "student_name",
    "absentee",
    "names",
    "student_list",
    "staff_name",
    "participants_list",
    "od_students",
    "student_reference",
    "person_reference",
    "staff_reference",
)


def tier_of(role: str) -> str:
    return ROLE_TIERS.get(role, ENTRY)


def tier_rank(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def can_see(viewer_tier: str, analysis_tier: str) -> bool:
    """Analyses are inherited upward only."""
    return tier_rank(viewer_tier) >= tier_rank(analysis_tier)


def is_identity_field(field_key: str) -> bool:
    lowered = field_key.lower()
    return any(hint in lowered for hint in IDENTITY_FIELD_HINTS)


def owns_scope(tier: str) -> bool:
    """ENTRY sees only its own records; higher tiers see everyone's."""
    return tier == ENTRY
