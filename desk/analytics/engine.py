"""Binds analysis primitives to a module's field definitions.

Field ``kind`` is the entire contract: the engine reads ``Module.fields`` and
applies every primitive whose input shape the field can supply, plus the
cross-field pairings (numeric x date, numeric x category, text x category) that
carry a typical form past fifty analyses. See METHODOLOGY.md section 3B.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import mean
from typing import Any, Callable, Iterable, Sequence

from tvs_dms.forms import Module

from . import primitives as p
from .access import DECISION, ENTRY, SUPPORT, is_identity_field
from .types import (
    ALERT,
    CATEGORY_SYNTHESIS,
    GOOD,
    NEUTRAL,
    WATCH,
    AnalysisDef,
    Insight,
    Observation,
    Report,
    SwotQuadrant,
    sort_insights,
)

# Fields that segment the school rather than measure it.
SEGMENT_KEYS = ("level", "standard", "shift", "section")

# Numeric fields where a lower number is the better outcome.
LOWER_IS_BETTER_HINTS = ("wastage", "waste", "absent", "absentee", "issue", "problem",
                         "complaint", "pending", "delay", "loss", "damage", "shortage")

# Narrative fields that describe a problem rather than an outcome.
PROBLEM_TEXT_HINTS = ("challenge", "problem", "issue", "concern", "difficult", "constraint")


def _is_lower_better(field_key: str, label: str) -> bool:
    haystack = f"{field_key} {label}".lower()
    return any(hint in haystack for hint in LOWER_IS_BETTER_HINTS)


def _is_problem_text(field_key: str, label: str) -> bool:
    haystack = f"{field_key} {label}".lower()
    return any(hint in haystack for hint in PROBLEM_TEXT_HINTS)


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class FieldSeries:
    """Extracted, type-coerced values for one field across observations."""

    def __init__(self, field, observations: Sequence[Observation]) -> None:
        self.field = field
        self.key = field.key
        self.label = field.label
        self.kind = field.kind
        self.raw = [obs.get(field.key) for obs in observations]
        self.filled = sum(1 for value in self.raw if value not in (None, "", []))
        self.total = len(observations)

    def numbers(self) -> list[float]:
        return [n for n in (_to_number(v) for v in self.raw) if n is not None]

    def texts(self) -> list[str]:
        return [t for t in (_text_of(v) for v in self.raw) if t]

    def categories(self) -> list[str]:
        return [t for t in (_text_of(v) for v in self.raw) if t]


def observations_from(records: Iterable[Any], module_key: str) -> list[Observation]:
    """Decrypt records in memory. Nothing derived from this is persisted."""
    result: list[Observation] = []
    for record in records:
        if record.module_key != module_key:
            continue
        try:
            values = record.get_data() or {}
        except Exception:  # a single unreadable payload must not blank the report
            continue
        profile = getattr(record.owner, "desk_profile", None)
        owner_name = getattr(profile, "display_name", None) or record.owner.username
        result.append(
            Observation(
                record_id=str(record.id),
                module_key=record.module_key,
                owner_id=str(record.owner_id),
                owner_name=owner_name,
                status=record.status,
                event_date=_to_date(record.event_date) or _to_date(values.get("event_date")),
                created_at=record.created_at,
                values=values,
            )
        )
    return result


def _pairs(observations: Sequence[Observation], series: FieldSeries) -> list[tuple[date, float]]:
    pairs = []
    for obs, raw in zip(observations, series.raw):
        number = _to_number(raw)
        if obs.event_date and number is not None:
            pairs.append((obs.event_date, number))
    return pairs


def _groups(
    observations: Sequence[Observation], value_series: FieldSeries, segment_key: str
) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for obs, raw in zip(observations, value_series.raw):
        number = _to_number(raw)
        segment = _text_of(obs.get(segment_key))
        if number is not None and segment:
            groups[segment].append(number)
    return dict(groups)


def _dated_texts(observations: Sequence[Observation], series: FieldSeries) -> list[tuple[date, str]]:
    return [
        (obs.event_date, _text_of(raw))
        for obs, raw in zip(observations, series.raw)
        if obs.event_date and _text_of(raw)
    ]


def build_insights(module: Module, observations: Sequence[Observation], *, today: date | None = None,
                   period_label: str = "in this period") -> list[Insight]:
    """Run every applicable primitive. Returns unfiltered insights of all tiers."""
    today = today or date.today()
    out: list[Insight] = []

    def add(insight: Insight | None) -> None:
        if insight is not None:
            out.append(insight)

    fields = list(module.fields)
    series = {field.key: FieldSeries(field, observations) for field in fields}
    numeric_fields = [f for f in fields if f.kind == "integer"]
    choice_fields = [f for f in fields if f.kind == "choice"]
    text_fields = [f for f in fields if f.kind in ("text", "longtext")]
    segment_fields = [f for f in choice_fields if f.key in SEGMENT_KEYS]

    dates = [obs.event_date for obs in observations if obs.event_date]
    owners = [obs.owner_name for obs in observations]
    drafts = sum(1 for obs in observations if obs.status != "submitted")

    # --- volume & coverage -------------------------------------------------
    add(p.total_submissions("volume.total", "Entries recorded", ENTRY, len(observations), period_label))
    add(p.reporting_coverage("volume.coverage", "Reporting coverage", SUPPORT, dates, period_label))
    add(p.submission_cadence("volume.cadence", "Reporting cadence", SUPPORT, dates))
    add(p.contributor_count("volume.contributors", "Who is filing", SUPPORT, owners))
    add(p.owner_workload_balance("compare.workload", "Filing balance across staff", SUPPORT, owners))
    add(p.draft_backlog("quality.drafts", "Unsubmitted drafts", ENTRY, drafts, len(observations)))
    add(p.stale_reporting("risk.stale", "Freshness of this record", SUPPORT, dates, today))

    latencies = [
        (obs.created_at.date() - obs.event_date).days
        for obs in observations
        if obs.event_date and hasattr(obs.created_at, "date")
    ]
    add(p.filing_latency("quality.latency", "Filing delay", SUPPORT, [d for d in latencies if d >= 0]))
    add(p.activity_rate_trend("volume.rate_trend", "How often this is recorded", SUPPORT, dates, module.name))
    add(p.weekday_activity_load("volume.weekday_load", "Which days carry the entries", SUPPORT, dates))
    add(p.monthly_activity_load("volume.month_load", "Entries month by month", DECISION, dates))

    # --- per numeric field -------------------------------------------------
    for field in numeric_fields:
        current = series[field.key]
        values = current.numbers()
        pairs = _pairs(observations, current)
        higher_better = not _is_lower_better(field.key, field.label)
        stem = f"num.{field.key}"
        add(p.numeric_total(f"{stem}.total", f"Total {field.label.lower()}", ENTRY, values, field.label, field.key))
        add(p.numeric_average(f"{stem}.avg", f"Average {field.label.lower()}", ENTRY, values, field.label, field.key))
        add(p.numeric_range(f"{stem}.range", f"{field.label} range", ENTRY, values, field.label, field.key))
        add(p.numeric_histogram(f"{stem}.hist", f"{field.label} distribution", SUPPORT, values, field.label, field.key))
        add(p.volatility(f"{stem}.vol", f"{field.label} consistency", SUPPORT, values, field.label, field.key))
        add(p.iqr_outliers(f"{stem}.iqr", f"{field.label} typical band", SUPPORT, values, field.label, field.key))
        add(p.trend_direction(f"{stem}.trend", f"{field.label} trend", SUPPORT, pairs, field.label,
                              field.key, higher_is_better=higher_better))
        add(p.period_over_period(f"{stem}.pop", f"{field.label} half-on-half", DECISION, pairs, field.label,
                                 field.key, higher_is_better=higher_better))
        add(p.weekday_seasonality(f"{stem}.weekday", f"{field.label} by day of week", DECISION, pairs,
                                  field.label, field.key))
        add(p.monthly_pattern(f"{stem}.month", f"{field.label} month by month", DECISION, pairs,
                              field.label, field.key))
        add(p.cumulative_progress(f"{stem}.cumulative", f"Cumulative {field.label.lower()}", DECISION, pairs,
                                  field.label, field.key))
        add(p.latest_vs_average(f"{stem}.latest", f"Latest {field.label.lower()} vs average", ENTRY, pairs,
                                field.label, field.key, higher_is_better=higher_better))
        add(p.zscore_outliers(f"{stem}.z", f"{field.label} outlier days", SUPPORT, pairs, field.label, field.key))
        add(p.record_extremes(f"{stem}.extremes", f"{field.label} best and worst days", SUPPORT, pairs,
                              field.label, field.key))
        add(p.sudden_change(f"{stem}.jump", f"{field.label} sudden movement", SUPPORT, pairs, field.label, field.key))
        add(p.declining_participation(f"{stem}.decline", f"Recent drop in {field.label.lower()}", DECISION,
                                      pairs, field.label, field.key))
        add(p.field_completeness(f"{stem}.complete", f"{field.label} completeness", ENTRY, current.filled,
                                 current.total, field.label, field.key))

        if values:
            average = mean(values)
            add(p.threshold_breach(f"{stem}.threshold", f"{field.label} below par", SUPPORT, pairs,
                                   field.label, field.key, average, below=higher_better))
            add(p.streak_detection(f"{stem}.streak", f"{field.label} sustained run", DECISION, pairs,
                                   field.label, field.key, average, below=higher_better))

        for segment in segment_fields:
            groups = _groups(observations, current, segment.key)
            used = (field.key, segment.key)
            gstem = f"{stem}.by_{segment.key}"
            add(p.segment_gap(f"{gstem}.gap", f"{field.label} gap across {segment.label.lower()}", SUPPORT,
                              groups, field.label, segment.label, used))
            add(p.top_performers(f"{gstem}.top", f"{segment.label} leading on {field.label.lower()}", SUPPORT,
                                 groups, field.label, segment.label, used))
            add(p.bottom_performers(f"{gstem}.bottom", f"{segment.label} lagging on {field.label.lower()}",
                                    SUPPORT, groups, field.label, segment.label, used))
            if values:
                add(p.repeated_breach_red_flag(f"{gstem}.redflag",
                                               f"Repeat {field.label.lower()} breaches by {segment.label.lower()}",
                                               DECISION, groups, field.label, segment.label, mean(values), used,
                                               below=higher_better))

    # --- numeric x numeric: utilisation ------------------------------------
    if len(numeric_fields) >= 2:
        first, second = numeric_fields[0], numeric_fields[1]
        add(p.utilisation_ratio(f"ratio.{first.key}_{second.key}",
                                f"{first.label} against {second.label}", DECISION,
                                series[first.key].numbers(), series[second.key].numbers(),
                                first.label, (first.key, second.key)))

    # --- per choice field --------------------------------------------------
    for field in choice_fields:
        current = series[field.key]
        categories = current.categories()
        stem = f"cat.{field.key}"
        add(p.category_mix(f"{stem}.mix", f"{field.label} mix", ENTRY, categories, field.label, field.key))
        add(p.category_concentration(f"{stem}.conc", f"{field.label} concentration", SUPPORT, categories,
                                     field.label, field.key))
        add(p.field_completeness(f"{stem}.complete", f"{field.label} completeness", ENTRY, current.filled,
                                 current.total, field.label, field.key))
        add(p.entries_per_segment(f"{stem}.entries", f"Entries by {field.label.lower()}", SUPPORT, categories,
                                  field.label, field.key))
        if field.choices:
            add(p.category_coverage_gap(f"{stem}.gap", f"{field.label} coverage gaps", SUPPORT, categories,
                                        field.choices, field.label, field.key))
        for segment in segment_fields:
            if segment.key == field.key:
                continue
            cross = [
                (_text_of(obs.get(segment.key)), _text_of(obs.get(field.key)))
                for obs in observations
            ]
            used = (field.key, segment.key)
            add(p.category_cross_tab(f"{stem}.x_{segment.key}",
                                     f"{field.label} against {segment.label.lower()}", SUPPORT,
                                     [(b, a) for a, b in cross], field.label, segment.label, used))
            add(p.category_frequency_by_segment(f"{stem}.freq_{segment.key}",
                                                f"{field.label} pattern per {segment.label.lower()}",
                                                DECISION, cross, field.label, segment.label, used))

    # --- per text field ----------------------------------------------------
    for field in text_fields:
        current = series[field.key]
        texts = current.texts()
        stem = f"txt.{field.key}"
        add(p.field_completeness(f"{stem}.complete", f"{field.label} completeness", ENTRY, current.filled,
                                 current.total, field.label, field.key))
        if field.kind == "longtext":
            add(p.recurring_themes(f"{stem}.themes", f"Recurring themes in {field.label.lower()}", SUPPORT,
                                   texts, field.label, field.key))
            add(p.narrative_effort(f"{stem}.effort", f"Detail written in {field.label.lower()}", ENTRY, texts,
                                   field.label, field.key))
            add(p.empty_narrative_rate(f"{stem}.thin", f"Thin {field.label.lower()} entries", ENTRY, texts,
                                       field.label, field.key))
            add(p.persistent_theme(f"{stem}.persistent", f"Unresolved themes in {field.label.lower()}",
                                   DECISION, _dated_texts(observations, current), field.label, field.key))
            if _is_problem_text(field.key, field.label):
                add(p.issue_volume(f"{stem}.volume", f"How often {field.label.lower()} is reported", SUPPORT,
                                   texts, len(observations), field.label, field.key))
                for segment in segment_fields:
                    counts: dict[str, int] = defaultdict(int)
                    for obs, raw in zip(observations, current.raw):
                        segment_value = _text_of(obs.get(segment.key))
                        if segment_value and len(_text_of(raw).split()) >= 3:
                            counts[segment_value] += 1
                    add(p.issue_by_segment(f"{stem}.by_{segment.key}",
                                           f"{field.label} concentrated by {segment.label.lower()}",
                                           DECISION, dict(counts), field.label, segment.label,
                                           (field.key, segment.key)))
            add(p.text_length_trend(f"{stem}.length_trend", f"Detail in {field.label.lower()} over time",
                                    SUPPORT, _dated_texts(observations, current), field.label, field.key))
        else:
            add(p.duplicate_suspicion(f"{stem}.dupes", f"Possible duplicate {field.label.lower()}", SUPPORT,
                                      current.texts(), field.label, (field.key,)))
            add(p.text_variety(f"{stem}.variety", f"{field.label} variety", SUPPORT, texts, field.label, field.key))
            add(p.repeat_subject(f"{stem}.repeat", f"Recurring {field.label.lower()}", SUPPORT, texts,
                                 field.label, field.key))
            for segment in segment_fields:
                cross = [
                    (_text_of(obs.get(segment.key)), _text_of(obs.get(field.key)))
                    for obs in observations
                ]
                add(p.category_frequency_by_segment(f"{stem}.freq_{segment.key}",
                                                    f"{field.label} pattern per {segment.label.lower()}",
                                                    DECISION, cross, field.label, segment.label,
                                                    (field.key, segment.key)))

    # --- secondary date fields --------------------------------------------
    for field in fields:
        if field.kind != "date" or field.key == "event_date":
            continue
        spans = []
        for obs in observations:
            other = _to_date(obs.get(field.key))
            if obs.event_date and other:
                spans.append((obs.event_date, (obs.event_date - other).days))
        add(p.gap_between_dates(f"date.{field.key}.gap", f"Days between {field.label.lower()} and reporting",
                                SUPPORT, [s for s in spans if s[1] >= 0], field.label,
                                (field.key, "event_date")))
        add(p.field_completeness(f"date.{field.key}.complete", f"{field.label} completeness", ENTRY,
                                 series[field.key].filled, series[field.key].total, field.label, field.key))

    # --- module-specific overrides ----------------------------------------
    from .specs import apply_spec, suppressed_for, tier_override_for

    out.extend(apply_spec(module, observations, today))

    suppressed = suppressed_for(module.key)
    out = [insight for insight in out if insight.key not in suppressed]

    for insight in out:
        override = tier_override_for(module.key, insight.key)
        if override:
            insight.tier = override
        # Identity-bearing analyses never rise above SUPPORT.
        if insight.tier == DECISION and any(is_identity_field(k) for k in insight.fields_used):
            insight.tier = SUPPORT

    return out


def build_swot(insights: Sequence[Insight]) -> list[SwotQuadrant]:
    """Assemble a SWOT from insight severity and category. Deterministic."""
    strengths = SwotQuadrant("Strengths", "strength")
    weaknesses = SwotQuadrant("Weaknesses", "weakness")
    opportunities = SwotQuadrant("Opportunities", "opportunity")
    threats = SwotQuadrant("Threats", "threat")

    for insight in sort_insights(insights):
        line = f"{insight.title}: {insight.headline}"
        if insight.severity == GOOD:
            if len(strengths.points) < 6:
                strengths.points.append(line)
        elif insight.severity == ALERT:
            target = threats if insight.category.startswith("Risk") else weaknesses
            if len(target.points) < 6:
                target.points.append(line)
        elif insight.severity == WATCH:
            if insight.action and len(opportunities.points) < 6:
                opportunities.points.append(f"{insight.title}: {insight.action}")
            elif len(weaknesses.points) < 6:
                weaknesses.points.append(line)

    return [q for q in (strengths, weaknesses, opportunities, threats) if q.points]


def catalogue_for(module: Module) -> list[AnalysisDef]:
    """Every analysis this module is *capable* of, independent of data.

    Used by the visibility console and by the >=50-per-form test. Built by
    running the engine against one synthetic observation per field kind, so the
    catalogue can never drift from what the engine actually emits.
    """
    from .specs import spec_catalogue

    defs: list[AnalysisDef] = []
    seen: set[str] = set()

    def register(key: str, title: str, tier: str, category: str, fields_used: tuple[str, ...] = ()) -> None:
        if key in seen:
            return
        seen.add(key)
        defs.append(AnalysisDef(key=key, title=title, tier=tier, category=category, fields_used=fields_used))

    for insight in build_insights(module, _synthetic_observations(module)):
        register(insight.key, insight.title, insight.tier, insight.category, insight.fields_used)
    for entry in spec_catalogue(module):
        register(entry.key, entry.title, entry.tier, entry.category, entry.fields_used)
    return defs


def _synthetic_observations(module: Module, count: int = 8) -> list[Observation]:
    """Dense fake data so every primitive fires when enumerating the catalogue."""
    from datetime import timedelta

    base = date(2024, 6, 3)
    observations: list[Observation] = []
    for index in range(count):
        values: dict[str, Any] = {}
        for field in module.fields:
            if field.kind == "integer":
                values[field.key] = 10 + (index * 7) % 40
            elif field.kind == "choice" and field.choices:
                values[field.key] = field.choices[index % len(field.choices)]
            elif field.kind == "choice":
                values[field.key] = f"Option {index % 3}"
            elif field.kind == "date":
                values[field.key] = (base + timedelta(days=index * 3)).isoformat()
            elif field.kind == "longtext":
                values[field.key] = (
                    f"Recurring transport delay affected the schedule again in session {index}; "
                    "canteen queue length remained a challenge for participants."
                )
            else:
                values[field.key] = f"Entry {index}"
        observations.append(
            Observation(
                record_id=f"synthetic-{index}",
                module_key=module.key,
                owner_id=f"owner-{index % 3}",
                owner_name=f"Staff {index % 3}",
                status="submitted",
                event_date=base + timedelta(days=index * 3),
                created_at=datetime(2024, 6, 4 + index),
                values=values,
            )
        )
    return observations
