"""Assembles a tier-appropriate report for one module.

Everything is computed on the fly: fetch via the store, decrypt in memory,
aggregate in Python, render. No derived data is written anywhere. See
METHODOLOGY.md section 4.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from tvs_dms.forms import MODULES, Module

from .access import can_see, owns_scope, tier_of
from .engine import build_insights, build_swot, observations_from
from .types import Insight, Observation, Report, sort_insights
from .visibility import filter_insights

HEADLINE_KEYS = (
    "volume.total",
    "num.participants.avg",
    "volume.coverage",
    "quality.drafts",
)


def parse_window(value: str | None) -> tuple[date | None, str]:
    """Translate a window token into a start date and a human label."""
    today = date.today()
    windows = {
        "30": (30, "in the last 30 days"),
        "90": (90, "in the last 90 days"),
        "180": (180, "in the last 6 months"),
        "365": (365, "in the last 12 months"),
    }
    if value in windows:
        days, label = windows[value]
        return today - timedelta(days=days), label
    return None, "across all records"


def select_observations(
    records: Iterable[Any],
    module: Module,
    *,
    viewer_id: str,
    tier: str,
    since: date | None = None,
    standard: str = "",
) -> list[Observation]:
    observations = observations_from(records, module.key)
    if owns_scope(tier):
        observations = [obs for obs in observations if obs.owner_id == str(viewer_id)]
    if since:
        observations = [obs for obs in observations if obs.event_date and obs.event_date >= since]
    if standard:
        observations = [obs for obs in observations if str(obs.get("standard") or "") == standard]
    return observations


def build_report(
    module: Module,
    observations: Sequence[Observation],
    *,
    role: str,
    period_label: str = "across all records",
    today: date | None = None,
) -> Report:
    tier = tier_of(role)
    everything = build_insights(module, observations, today=today, period_label=period_label)
    permitted = [insight for insight in everything if can_see(tier, insight.tier)]
    permitted = filter_insights(permitted, module.key, role)

    headline_map = {insight.key: insight for insight in permitted}
    headline = [headline_map[key] for key in HEADLINE_KEYS if key in headline_map]
    if len(headline) < 4:
        for insight in sort_insights(permitted):
            if insight not in headline and insight.value is not None:
                headline.append(insight)
            if len(headline) >= 4:
                break

    body = [insight for insight in permitted if insight not in headline]

    return Report(
        module_key=module.key,
        module_name=module.name,
        tier=tier,
        role=role,
        period_label=period_label,
        record_count=len(observations),
        insights=sort_insights(body),
        swot=build_swot(permitted) if tier == "decision" else [],
        headline_stats=headline[:4],
    )


def report_rows(report: Report) -> tuple[list[str], list[list[Any]]]:
    """Flatten a report into spreadsheet rows. Used by XLSX/CSV export."""
    headers = ["Category", "Analysis", "Tier", "Severity", "Headline", "Detail", "Recommended action"]
    rows = []
    for insight in list(report.headline_stats) + list(report.insights):
        rows.append([
            insight.category,
            insight.title,
            insight.tier_label,
            insight.severity.title(),
            str(insight.headline),
            insight.detail,
            insight.action,
        ])
    return headers, rows


def detail_rows(report: Report) -> list[tuple[str, list[str], list[list[Any]]]]:
    """Every insight that carries a table, as its own sheet-ready block."""
    blocks = []
    for insight in list(report.headline_stats) + list(report.insights):
        if not insight.table:
            continue
        headers = list(insight.table[0].keys())
        rows = [[row.get(header, "") for header in headers] for row in insight.table]
        blocks.append((insight.title, headers, rows))
    return blocks
