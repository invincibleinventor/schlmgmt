"""Per-school field visibility overrides.

Deny-only. This layer can hide a field the tier matrix allows; it can never
reveal one the tier matrix withholds. See METHODOLOGY.md section 5.
"""

from __future__ import annotations

from typing import Any, Sequence

from tvs_dms.forms import Module

from ..store import get_store
from .access import is_identity_field, tier_of
from .types import DECISION, ENTRY, SUPPORT, Insight


def hidden_field_keys(module_key: str, role: str) -> set[str]:
    return get_store().hidden_fields().get((module_key, role), set())


def visible_fields(module: Module, role: str) -> list[Any]:
    hidden = hidden_field_keys(module.key, role)
    tier = tier_of(role)
    result = []
    for field in module.fields:
        if field.key in hidden:
            continue
        # Identity-bearing raw fields stop below DECISION; the tier still sees
        # them aggregated inside insights.
        if tier == DECISION and is_identity_field(field.key):
            continue
        result.append(field)
    return result


def filter_insights(insights: Sequence[Insight], module_key: str, role: str) -> list[Insight]:
    """Drop insights that depend on a field this role may not see."""
    hidden = hidden_field_keys(module_key, role)
    if not hidden:
        return list(insights)
    return [
        insight
        for insight in insights
        if not (set(insight.fields_used) & hidden)
    ]


def redact_row(values: dict[str, Any], module_key: str, role: str) -> dict[str, Any]:
    hidden = hidden_field_keys(module_key, role)
    if not hidden:
        return values
    return {k: v for k, v in values.items() if k not in hidden}
