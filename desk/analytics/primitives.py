"""Pure analysis primitives.

Every function here is deterministic arithmetic or string frequency counting.
Nothing calls a model, a network service, or an external API. See
METHODOLOGY.md section 3 and section 8.

Each primitive takes already-extracted series and returns an ``Insight`` or
``None`` when the data cannot support the claim.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import mean, median, pstdev
from typing import Any, Iterable, Sequence

from .types import (
    ALERT,
    CATEGORY_COMPARISON,
    CATEGORY_DISTRIBUTION,
    CATEGORY_OUTLIER,
    CATEGORY_QUALITY,
    CATEGORY_RISK,
    CATEGORY_TEXT,
    CATEGORY_TREND,
    CATEGORY_VOLUME,
    GOOD,
    NEUTRAL,
    WATCH,
    Insight,
)

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Words too common in school prose to be a useful theme.
STOP_WORDS = frozenset(
    """
    a an the and or but if of to in on at for with from by as is are was were be been
    being this that these those it its it's we our us they them their there here have
    has had do does did not no yes so than then too very can will would should could
    may might must about into over under again more most some such only own same
    other others also which who whom what when where why how all any both each few
    nor own s t just don now during before after above below up down out off further
    students student class classes school day days was were had has been done get got
    """.split()
)

MIN_SERIES = 3  # below this, most claims are noise


def _round(value: float, places: int = 2) -> float:
    return round(float(value), places)


def _pct(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return _round(part / whole * 100, 1)


def _bar_chart(labels: Sequence[str], values: Sequence[float], *, unit: str = "") -> dict[str, Any]:
    return {"type": "bar", "labels": list(labels), "values": [_round(v) for v in values], "unit": unit}


def _line_chart(labels: Sequence[str], values: Sequence[float], *, unit: str = "") -> dict[str, Any]:
    return {"type": "line", "labels": list(labels), "values": [_round(v) for v in values], "unit": unit}


def _donut_chart(labels: Sequence[str], values: Sequence[float]) -> dict[str, Any]:
    return {"type": "donut", "labels": list(labels), "values": [_round(v) for v in values], "unit": ""}


# --------------------------------------------------------------------------
# Volume & coverage
# --------------------------------------------------------------------------

def total_submissions(key: str, title: str, tier: str, count: int, period_label: str) -> Insight | None:
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        severity=NEUTRAL if count else WATCH,
        headline=f"{count}",
        detail=f"{count} submission{'s' if count != 1 else ''} recorded {period_label}.",
        value=count,
        unit="records",
    )


def numeric_total(key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str) -> Insight | None:
    if not values:
        return None
    total = sum(values)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        headline=f"{_round(total, 0):,.0f}",
        detail=f"Total {label.lower()} across {len(values)} submissions.",
        value=_round(total, 2),
        fields_used=(field_key,),
    )


def numeric_average(key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str) -> Insight | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    med = median(values)
    detail = f"Average {label.lower()} per submission is {_round(avg)}; median {_round(med)}."
    if abs(avg - med) > (avg * 0.25 if avg else 0):
        detail += " Mean and median differ, so a few entries are pulling the average."
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        headline=f"{_round(avg)}",
        detail=detail,
        value=_round(avg),
        fields_used=(field_key,),
    )


def numeric_range(key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str) -> Insight | None:
    if len(values) < MIN_SERIES:
        return None
    lo, hi = min(values), max(values)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        headline=f"{_round(lo, 0):,.0f} – {_round(hi, 0):,.0f}",
        detail=f"{label} ranged from {_round(lo)} to {_round(hi)}, a spread of {_round(hi - lo)}.",
        value=_round(hi - lo),
        fields_used=(field_key,),
    )


def reporting_coverage(key: str, title: str, tier: str, dates: Sequence[date], period_label: str) -> Insight | None:
    if len(dates) < 2:
        return None
    span = (max(dates) - min(dates)).days + 1
    distinct = len(set(dates))
    coverage = _pct(distinct, span)
    severity = GOOD if coverage >= 60 else WATCH if coverage >= 30 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        severity=severity,
        headline=f"{coverage}%",
        detail=(
            f"Entries exist for {distinct} of the {span} days {period_label}. "
            "Days with no entry cannot be analysed at all."
        ),
        action="Chase the missing days before drawing conclusions from this report."
        if severity != GOOD
        else "",
        value=coverage,
        unit="%",
    )


def submission_cadence(key: str, title: str, tier: str, dates: Sequence[date]) -> Insight | None:
    if len(dates) < MIN_SERIES:
        return None
    ordered = sorted(set(dates))
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:])]
    if not gaps:
        return None
    avg_gap = mean(gaps)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        headline=f"every {_round(avg_gap, 1)} days",
        detail=f"Entries arrive on average {_round(avg_gap, 1)} days apart (longest gap {max(gaps)} days).",
        value=_round(avg_gap, 1),
    )


def contributor_count(key: str, title: str, tier: str, owners: Sequence[str]) -> Insight | None:
    if not owners:
        return None
    counts = Counter(owners)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_VOLUME,
        headline=f"{len(counts)}",
        detail=f"{len(counts)} people filed these {len(owners)} entries.",
        value=len(counts),
        table=[{"Contributor": name, "Entries": n} for name, n in counts.most_common()],
        chart=_bar_chart([n for n, _ in counts.most_common(8)], [c for _, c in counts.most_common(8)], unit="entries"),
    )


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------

def _linear_slope(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = mean(xs), mean(values)
    denominator = sum((x - mx) ** 2 for x in xs)
    if not denominator:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, values)) / denominator


def trend_direction(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
    *, higher_is_better: bool = True,
) -> Insight | None:
    if len(pairs) < MIN_SERIES:
        return None
    ordered = sorted(pairs)
    values = [v for _, v in ordered]
    slope = _linear_slope(values)
    baseline = mean(values) or 1
    strength = abs(slope) / abs(baseline)
    if strength < 0.02:
        direction, severity = "holding steady", NEUTRAL
    elif slope > 0:
        direction = "rising"
        severity = GOOD if higher_is_better else WATCH
    else:
        direction = "falling"
        severity = WATCH if higher_is_better else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=severity,
        headline=direction,
        detail=(
            f"{label} is {direction} across {len(values)} entries, changing about "
            f"{_round(slope)} per entry (least-squares slope)."
        ),
        value=_round(slope),
        chart=_line_chart([d.strftime("%d %b") for d, _ in ordered], values, unit=label),
        fields_used=(field_key,),
    )


def period_over_period(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
    *, higher_is_better: bool = True,
) -> Insight | None:
    if len(pairs) < 4:
        return None
    ordered = sorted(pairs)
    midpoint = len(ordered) // 2
    earlier = [v for _, v in ordered[:midpoint]]
    later = [v for _, v in ordered[midpoint:]]
    before, after = mean(earlier), mean(later)
    if not before:
        return None
    change = _pct(after - before, abs(before))
    if abs(change) < 5:
        severity, word = NEUTRAL, "essentially unchanged"
    elif change > 0:
        word = "up"
        severity = GOOD if higher_is_better else WATCH
    else:
        word = "down"
        severity = WATCH if higher_is_better else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=severity,
        headline=f"{change:+.1f}%",
        detail=(
            f"{label} averaged {_round(before)} in the first half of this period and "
            f"{_round(after)} in the second — {word}."
        ),
        value=change,
        unit="%",
        chart=_bar_chart(["First half", "Second half"], [before, after], unit=label),
        fields_used=(field_key,),
    )


def weekday_seasonality(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < 5:
        return None
    buckets: dict[int, list[float]] = defaultdict(list)
    for day, value in pairs:
        buckets[day.weekday()].append(value)
    if len(buckets) < 3:
        return None
    averages = {day: mean(vals) for day, vals in buckets.items()}
    best = max(averages, key=averages.get)
    worst = min(averages, key=averages.get)
    if averages[best] == averages[worst]:
        return None
    labels = [WEEKDAY_NAMES[d] for d in sorted(averages)]
    values = [averages[d] for d in sorted(averages)]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=WATCH,
        headline=WEEKDAY_NAMES[worst],
        detail=(
            f"{label} is lowest on {WEEKDAY_NAMES[worst]} ({_round(averages[worst])}) and highest on "
            f"{WEEKDAY_NAMES[best]} ({_round(averages[best])})."
        ),
        action=f"If the {WEEKDAY_NAMES[worst]} dip is not intentional, it is worth investigating the timetable.",
        chart=_bar_chart(labels, values, unit=label),
        fields_used=(field_key,),
    )


def monthly_pattern(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for day, value in pairs:
        buckets[(day.year, day.month)].append(value)
    if len(buckets) < 2:
        return None
    ordered = sorted(buckets)
    labels = [f"{MONTH_NAMES[m - 1][:3]} {y % 100:02d}" for y, m in ordered]
    values = [mean(buckets[k]) for k in ordered]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        headline=f"{len(ordered)} months",
        detail=f"Month-by-month average {label.lower()} across {len(ordered)} months.",
        chart=_line_chart(labels, values, unit=label),
        table=[{"Month": lab, label: _round(val)} for lab, val in zip(labels, values)],
        fields_used=(field_key,),
    )


def streak_detection(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
    threshold: float, *, below: bool = True,
) -> Insight | None:
    if len(pairs) < MIN_SERIES:
        return None
    ordered = sorted(pairs)
    longest = current = 0
    streak_end: date | None = None
    for day, value in ordered:
        breached = value < threshold if below else value > threshold
        if breached:
            current += 1
            if current > longest:
                longest, streak_end = current, day
        else:
            current = 0
    if longest < 2:
        return None
    word = "below" if below else "above"
    severity = ALERT if longest >= 4 else WATCH
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK if severity == ALERT else CATEGORY_TREND,
        severity=severity,
        headline=f"{longest} in a row",
        detail=(
            f"{label} stayed {word} {_round(threshold)} for {longest} consecutive entries, "
            f"ending {streak_end:%d %b %Y}."
        ),
        action="A run this long is a standing problem, not a bad day. Escalate it.",
        value=longest,
        fields_used=(field_key,),
    )


def latest_vs_average(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
    *, higher_is_better: bool = True,
) -> Insight | None:
    if len(pairs) < MIN_SERIES:
        return None
    ordered = sorted(pairs)
    latest_date, latest = ordered[-1]
    history = [v for _, v in ordered[:-1]]
    avg = mean(history)
    if not avg:
        return None
    delta = _pct(latest - avg, abs(avg))
    if abs(delta) < 10:
        severity = NEUTRAL
    elif (delta > 0) == higher_is_better:
        severity = GOOD
    else:
        severity = WATCH
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=severity,
        headline=f"{delta:+.1f}%",
        detail=(
            f"The most recent entry ({latest_date:%d %b}) recorded {_round(latest)} against a "
            f"running average of {_round(avg)}."
        ),
        value=delta,
        unit="%",
        fields_used=(field_key,),
    )


def cumulative_progress(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < MIN_SERIES:
        return None
    ordered = sorted(pairs)
    running: list[float] = []
    total = 0.0
    for _, value in ordered:
        total += value
        running.append(total)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        headline=f"{_round(total, 0):,.0f}",
        detail=f"Cumulative {label.lower()} reached {_round(total, 0):,.0f} over the period.",
        value=_round(total),
        chart=_line_chart([d.strftime("%d %b") for d, _ in ordered], running, unit=label),
        fields_used=(field_key,),
    )


def volatility(
    key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str,
) -> Insight | None:
    if len(values) < 4:
        return None
    avg = mean(values)
    if not avg:
        return None
    spread = pstdev(values)
    cv = _pct(spread, abs(avg))
    severity = ALERT if cv > 60 else WATCH if cv > 30 else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=severity,
        headline=f"{cv}%",
        detail=(
            f"{label} varies by {_round(spread)} around a mean of {_round(avg)} "
            f"(coefficient of variation {cv}%)."
        ),
        action="High variability usually means the process is not standardised."
        if severity != GOOD
        else "",
        value=cv,
        unit="%",
        fields_used=(field_key,),
    )


# --------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------

def category_mix(
    key: str, title: str, tier: str, values: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    cleaned = [v for v in values if v]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    top, top_n = counts.most_common(1)[0]
    share = _pct(top_n, len(cleaned))
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_DISTRIBUTION,
        headline=top,
        detail=f"{top} accounts for {share}% of entries where {label.lower()} was recorded.",
        value=share,
        unit="%",
        table=[{label: name, "Entries": n, "Share": f"{_pct(n, len(cleaned))}%"} for name, n in counts.most_common()],
        chart=_donut_chart([n for n, _ in counts.most_common(6)], [c for _, c in counts.most_common(6)]),
        fields_used=(field_key,),
    )


def category_concentration(
    key: str, title: str, tier: str, values: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    cleaned = [v for v in values if v]
    if len(set(cleaned)) < 2:
        return None
    counts = Counter(cleaned)
    top_two = sum(n for _, n in counts.most_common(2))
    share = _pct(top_two, len(cleaned))
    severity = WATCH if share > 80 else NEUTRAL
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_DISTRIBUTION,
        severity=severity,
        headline=f"{share}%",
        detail=(
            f"The two most common {label.lower()} values cover {share}% of all entries, "
            f"out of {len(counts)} distinct values seen."
        ),
        action="A concentrated mix may mean the rest of the school is not being covered."
        if severity == WATCH
        else "",
        value=share,
        unit="%",
        fields_used=(field_key,),
    )


def category_coverage_gap(
    key: str, title: str, tier: str, values: Sequence[str], expected: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    expected_set = {e for e in expected if e and e.lower() != "all"}
    if not expected_set:
        return None
    seen = {v for v in values if v}
    missing = sorted(expected_set - seen)
    if not missing:
        return Insight(
            key=key,
            title=title,
            tier=tier,
            category=CATEGORY_DISTRIBUTION,
            severity=GOOD,
            headline="full coverage",
            detail=f"Every possible {label.lower()} value appears at least once.",
            fields_used=(field_key,),
        )
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_DISTRIBUTION,
        severity=WATCH if len(missing) < len(expected_set) else ALERT,
        headline=f"{len(missing)} missing",
        detail=f"No entries at all for: {', '.join(missing)}.",
        action="Either these were genuinely not covered, or the entries were never filed.",
        value=len(missing),
        table=[{label: name} for name in missing],
        fields_used=(field_key,),
    )


def numeric_histogram(
    key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str,
) -> Insight | None:
    if len(values) < 4:
        return None
    lo, hi = min(values), max(values)
    if lo == hi:
        return None
    bucket_count = min(6, len(set(values)))
    width = (hi - lo) / bucket_count
    edges = [lo + width * i for i in range(bucket_count + 1)]
    counts = [0] * bucket_count
    for value in values:
        index = min(int((value - lo) / width), bucket_count - 1)
        counts[index] += 1
    labels = [f"{_round(edges[i], 0):.0f}–{_round(edges[i + 1], 0):.0f}" for i in range(bucket_count)]
    busiest = counts.index(max(counts))
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_DISTRIBUTION,
        headline=labels[busiest],
        detail=f"Most entries fall in the {labels[busiest]} band for {label.lower()}.",
        chart=_bar_chart(labels, counts, unit="entries"),
        fields_used=(field_key,),
    )


def top_performers(
    key: str, title: str, tier: str, groups: dict[str, list[float]], label: str, group_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    usable = {k: v for k, v in groups.items() if v and k}
    if len(usable) < 2:
        return None
    averages = {k: mean(v) for k, v in usable.items()}
    ranked = sorted(averages.items(), key=lambda item: item[1], reverse=True)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        headline=ranked[0][0],
        detail=f"{ranked[0][0]} leads on {label.lower()} at {_round(ranked[0][1])}.",
        table=[
            {group_label: name, label: _round(value), "Entries": len(usable[name])}
            for name, value in ranked
        ],
        chart=_bar_chart([n for n, _ in ranked[:8]], [v for _, v in ranked[:8]], unit=label),
        fields_used=fields_used,
    )


def bottom_performers(
    key: str, title: str, tier: str, groups: dict[str, list[float]], label: str, group_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    usable = {k: v for k, v in groups.items() if v and k}
    if len(usable) < 2:
        return None
    averages = {k: mean(v) for k, v in usable.items()}
    ranked = sorted(averages.items(), key=lambda item: item[1])
    worst, worst_value = ranked[0]
    best_value = ranked[-1][1]
    gap = _pct(best_value - worst_value, abs(best_value)) if best_value else 0
    severity = ALERT if gap > 40 else WATCH if gap > 15 else NEUTRAL
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        severity=severity,
        headline=worst,
        detail=(
            f"{worst} sits lowest on {label.lower()} at {_round(worst_value)}, "
            f"{gap}% below the best-performing {group_label.lower()}."
        ),
        action=f"Ask what {worst} needs before the gap widens." if severity != NEUTRAL else "",
        value=gap,
        unit="%",
        fields_used=fields_used,
    )


def segment_gap(
    key: str, title: str, tier: str, groups: dict[str, list[float]], label: str, group_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    usable = {k: v for k, v in groups.items() if len(v) >= 2 and k}
    if len(usable) < 2:
        return None
    averages = {k: mean(v) for k, v in usable.items()}
    spread = max(averages.values()) - min(averages.values())
    overall = mean([v for values in usable.values() for v in values])
    relative = _pct(spread, abs(overall)) if overall else 0
    severity = ALERT if relative > 50 else WATCH if relative > 20 else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        severity=severity,
        headline=f"{_round(spread)}",
        detail=(
            f"{label} differs by {_round(spread)} between the highest and lowest {group_label.lower()} "
            f"({relative}% of the overall average)."
        ),
        action="A gap this wide is usually a resourcing or practice difference, not chance."
        if severity == ALERT
        else "",
        value=relative,
        unit="%",
        chart=_bar_chart(list(averages), list(averages.values()), unit=label),
        fields_used=fields_used,
    )


def owner_workload_balance(
    key: str, title: str, tier: str, owners: Sequence[str],
) -> Insight | None:
    counts = Counter(o for o in owners if o)
    if len(counts) < 2:
        return None
    values = list(counts.values())
    busiest, busiest_n = counts.most_common(1)[0]
    share = _pct(busiest_n, sum(values))
    severity = WATCH if share > 60 else NEUTRAL
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        severity=severity,
        headline=f"{share}%",
        detail=f"{busiest} filed {share}% of all entries ({busiest_n} of {sum(values)}).",
        action="Concentrated filing means the record depends on one person being available."
        if severity == WATCH
        else "",
        value=share,
        unit="%",
        table=[{"Contributor": n, "Entries": c} for n, c in counts.most_common()],
    )


# --------------------------------------------------------------------------
# Outliers
# --------------------------------------------------------------------------

def zscore_outliers(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < 5:
        return None
    values = [v for _, v in pairs]
    avg = mean(values)
    spread = pstdev(values)
    if not spread:
        return None
    flagged = [(d, v, (v - avg) / spread) for d, v in pairs if abs((v - avg) / spread) >= 2]
    if not flagged:
        return Insight(
            key=key,
            title=title,
            tier=tier,
            category=CATEGORY_OUTLIER,
            severity=GOOD,
            headline="none",
            detail=f"No {label.lower()} value sits more than two standard deviations from the mean.",
            fields_used=(field_key,),
        )
    flagged.sort(key=lambda item: abs(item[2]), reverse=True)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_OUTLIER,
        severity=WATCH,
        headline=f"{len(flagged)}",
        detail=(
            f"{len(flagged)} entries are statistical outliers for {label.lower()}; "
            f"the most extreme was {_round(flagged[0][1])} on {flagged[0][0]:%d %b %Y}."
        ),
        value=len(flagged),
        table=[
            {"Date": d.strftime("%d %b %Y"), label: _round(v), "Deviation": f"{z:+.1f}σ"}
            for d, v, z in flagged[:10]
        ],
        fields_used=(field_key,),
    )


def iqr_outliers(
    key: str, title: str, tier: str, values: Sequence[float], label: str, field_key: str,
) -> Insight | None:
    if len(values) < 6:
        return None
    ordered = sorted(values)
    n = len(ordered)
    q1 = ordered[n // 4]
    q3 = ordered[(3 * n) // 4]
    iqr = q3 - q1
    if not iqr:
        return None
    low_fence, high_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outside = [v for v in values if v < low_fence or v > high_fence]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_OUTLIER,
        severity=WATCH if outside else GOOD,
        headline=f"{len(outside)}",
        detail=(
            f"Typical {label.lower()} sits between {_round(q1)} and {_round(q3)}; "
            f"{len(outside)} entries fall outside the expected fence."
        ),
        value=len(outside),
        fields_used=(field_key,),
    )


def record_extremes(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < MIN_SERIES:
        return None
    best = max(pairs, key=lambda item: item[1])
    worst = min(pairs, key=lambda item: item[1])
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_OUTLIER,
        headline=f"{_round(worst[1])} / {_round(best[1])}",
        detail=(
            f"Lowest {label.lower()} was {_round(worst[1])} on {worst[0]:%d %b %Y}; "
            f"highest was {_round(best[1])} on {best[0]:%d %b %Y}."
        ),
        table=[
            {"Extreme": "Lowest", "Date": worst[0].strftime("%d %b %Y"), label: _round(worst[1])},
            {"Extreme": "Highest", "Date": best[0].strftime("%d %b %Y"), label: _round(best[1])},
        ],
        fields_used=(field_key,),
    )


def sudden_change(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < 4:
        return None
    ordered = sorted(pairs)
    jumps = []
    for (day_a, a), (day_b, b) in zip(ordered, ordered[1:]):
        if not a:
            continue
        jumps.append((abs(_pct(b - a, abs(a))), day_b, a, b))
    if not jumps:
        return None
    jumps.sort(reverse=True)
    magnitude, when, before, after = jumps[0]
    if magnitude < 40:
        return None
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_OUTLIER,
        severity=WATCH,
        headline=f"{magnitude:.0f}%",
        detail=(
            f"{label} moved from {_round(before)} to {_round(after)} between consecutive entries "
            f"ending {when:%d %b %Y}."
        ),
        action="A single-step change this large usually has a specific cause worth naming.",
        value=magnitude,
        unit="%",
        fields_used=(field_key,),
    )


# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------

def field_completeness(
    key: str, title: str, tier: str, filled: int, total: int, label: str, field_key: str,
) -> Insight | None:
    if not total:
        return None
    rate = _pct(filled, total)
    severity = GOOD if rate >= 90 else WATCH if rate >= 60 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=severity,
        headline=f"{rate}%",
        detail=f"{label} was filled in {filled} of {total} entries.",
        action=f"Every blank {label.lower()} is an entry that drops out of this report."
        if severity != GOOD
        else "",
        value=rate,
        unit="%",
        fields_used=(field_key,),
    )


def draft_backlog(key: str, title: str, tier: str, drafts: int, total: int) -> Insight | None:
    if not total:
        return None
    rate = _pct(drafts, total)
    severity = GOOD if rate < 10 else WATCH if rate < 30 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=severity,
        headline=f"{drafts}",
        detail=f"{drafts} of {total} entries ({rate}%) are still drafts and are excluded from submitted totals.",
        action="Drafts are invisible to everyone above the person who wrote them." if drafts else "",
        value=drafts,
    )


def filing_latency(
    key: str, title: str, tier: str, deltas: Sequence[int],
) -> Insight | None:
    if len(deltas) < MIN_SERIES:
        return None
    avg = mean(deltas)
    late = [d for d in deltas if d > 7]
    severity = GOOD if avg <= 2 else WATCH if avg <= 7 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=severity,
        headline=f"{_round(avg, 1)} days",
        detail=(
            f"Entries are filed on average {_round(avg, 1)} days after the activity date; "
            f"{len(late)} were more than a week late."
        ),
        action="Late filing means decisions were made without this data." if severity != GOOD else "",
        value=_round(avg, 1),
    )


def duplicate_suspicion(
    key: str, title: str, tier: str, signatures: Sequence[str], label: str, fields_used: tuple[str, ...],
) -> Insight | None:
    cleaned = [s for s in signatures if s]
    if len(cleaned) < 2:
        return None
    counts = Counter(cleaned)
    repeats = [(sig, n) for sig, n in counts.items() if n > 1]
    if not repeats:
        return Insight(
            key=key,
            title=title,
            tier=tier,
            category=CATEGORY_QUALITY,
            severity=GOOD,
            headline="none",
            detail=f"No two entries share the same {label.lower()}.",
            fields_used=fields_used,
        )
    repeats.sort(key=lambda item: item[1], reverse=True)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=WATCH,
        headline=f"{len(repeats)}",
        detail=f"{len(repeats)} {label.lower()} combinations appear more than once — possible duplicate entries.",
        value=len(repeats),
        table=[{label: sig[:80], "Times": n} for sig, n in repeats[:10]],
        fields_used=fields_used,
    )


def empty_narrative_rate(
    key: str, title: str, tier: str, texts: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    if not texts:
        return None
    thin = [t for t in texts if len((t or "").split()) < 4]
    rate = _pct(len(thin), len(texts))
    severity = GOOD if rate < 20 else WATCH if rate < 50 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=severity,
        headline=f"{rate}%",
        detail=f"{len(thin)} of {len(texts)} {label.lower()} entries are under four words.",
        action="One-word narratives cannot be acted on by anyone reading this later."
        if severity != GOOD
        else "",
        value=rate,
        unit="%",
        fields_used=(field_key,),
    )


# --------------------------------------------------------------------------
# Text / themes
# --------------------------------------------------------------------------

_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]{2,}")


def _keywords(texts: Iterable[str]) -> Counter:
    counts: Counter = Counter()
    for text in texts:
        if not text:
            continue
        words = {w.lower() for w in _WORD.findall(text)}
        counts.update(w for w in words if w not in STOP_WORDS)
    return counts


def recurring_themes(
    key: str, title: str, tier: str, texts: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    counts = _keywords(texts)
    recurring = [(w, n) for w, n in counts.most_common(12) if n > 1]
    if not recurring:
        return None
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TEXT,
        severity=WATCH if recurring[0][1] >= 3 else NEUTRAL,
        headline=recurring[0][0],
        detail=(
            f"'{recurring[0][0]}' appears in {recurring[0][1]} separate {label.lower()} entries — "
            "the most repeated theme."
        ),
        table=[{"Theme": w, "Entries mentioning it": n} for w, n in recurring],
        chart=_bar_chart([w for w, _ in recurring[:8]], [n for _, n in recurring[:8]], unit="entries"),
        fields_used=(field_key,),
    )


def persistent_theme(
    key: str, title: str, tier: str, dated_texts: Sequence[tuple[date, str]], label: str, field_key: str,
) -> Insight | None:
    if len(dated_texts) < 4:
        return None
    ordered = sorted(dated_texts)
    midpoint = len(ordered) // 2
    early = _keywords(t for _, t in ordered[:midpoint])
    late = _keywords(t for _, t in ordered[midpoint:])
    persistent = [(w, early[w] + late[w]) for w in early if w in late and early[w] + late[w] >= 3]
    if not persistent:
        return None
    persistent.sort(key=lambda item: item[1], reverse=True)
    word, total = persistent[0]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=ALERT,
        headline=word,
        detail=(
            f"'{word}' was raised in {label.lower()} in both halves of this period "
            f"({total} entries in total). It has not gone away."
        ),
        action="A problem reported across the whole period is an escalation, not a log entry.",
        value=total,
        table=[{"Theme": w, "Mentions": n} for w, n in persistent[:8]],
        fields_used=(field_key,),
    )


def issue_volume(
    key: str, title: str, tier: str, texts: Sequence[str], total: int, label: str, field_key: str,
) -> Insight | None:
    if not total:
        return None
    reported = [t for t in texts if t and len(t.split()) >= 3]
    rate = _pct(len(reported), total)
    severity = ALERT if rate > 50 else WATCH if rate > 20 else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{len(reported)}",
        detail=f"{label} was recorded in {len(reported)} of {total} entries ({rate}%).",
        action="Sort these by theme before the next review meeting." if reported else "",
        value=rate,
        unit="%",
        fields_used=(field_key,),
    )


def narrative_effort(
    key: str, title: str, tier: str, texts: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    lengths = [len((t or "").split()) for t in texts if t]
    if len(lengths) < MIN_SERIES:
        return None
    avg = mean(lengths)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        headline=f"{_round(avg, 0):.0f} words",
        detail=f"{label} entries average {_round(avg, 0):.0f} words (longest {max(lengths)}).",
        value=_round(avg, 1),
        fields_used=(field_key,),
    )


def issue_by_segment(
    key: str, title: str, tier: str, groups: dict[str, int], label: str, group_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    usable = {k: v for k, v in groups.items() if k}
    if len(usable) < 2 or not sum(usable.values()):
        return None
    ranked = sorted(usable.items(), key=lambda item: item[1], reverse=True)
    worst, worst_n = ranked[0]
    if not worst_n:
        return None
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=WATCH,
        headline=worst,
        detail=f"{worst} accounts for the most {label.lower()} ({worst_n} entries).",
        action=f"Target the next intervention at {worst} rather than school-wide.",
        table=[{group_label: name, "Entries with issues": n} for name, n in ranked],
        chart=_bar_chart([n for n, _ in ranked[:8]], [c for _, c in ranked[:8]], unit="entries"),
        fields_used=fields_used,
    )


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------

def threshold_breach(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
    threshold: float, *, below: bool = True,
) -> Insight | None:
    if not pairs:
        return None
    breaches = [(d, v) for d, v in pairs if (v < threshold if below else v > threshold)]
    rate = _pct(len(breaches), len(pairs))
    word = "below" if below else "above"
    severity = ALERT if rate > 30 else WATCH if breaches else GOOD
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{len(breaches)}",
        detail=(
            f"{label} fell {word} {_round(threshold)} on {len(breaches)} of {len(pairs)} entries ({rate}%)."
        ),
        action="Set a standing review for these dates." if severity == ALERT else "",
        value=rate,
        unit="%",
        table=[{"Date": d.strftime("%d %b %Y"), label: _round(v)} for d, v in sorted(breaches)[:10]],
        fields_used=(field_key,),
    )


def repeated_breach_red_flag(
    key: str, title: str, tier: str, groups: dict[str, list[float]], label: str, group_label: str,
    threshold: float, fields_used: tuple[str, ...], *, below: bool = True,
) -> Insight | None:
    offenders = {}
    for name, values in groups.items():
        if not name:
            continue
        breaches = [v for v in values if (v < threshold if below else v > threshold)]
        if len(breaches) >= 2:
            offenders[name] = len(breaches)
    if not offenders:
        return None
    ranked = sorted(offenders.items(), key=lambda item: item[1], reverse=True)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=ALERT,
        headline=ranked[0][0],
        detail=(
            f"{len(ranked)} {group_label.lower()} values breached the {label.lower()} threshold more than once; "
            f"{ranked[0][0]} did so {ranked[0][1]} times."
        ),
        action="Repeat breaches are the red flags the review meeting exists for.",
        value=len(ranked),
        table=[{group_label: name, "Breaches": n} for name, n in ranked],
        fields_used=fields_used,
    )


def stale_reporting(
    key: str, title: str, tier: str, dates: Sequence[date], today: date,
) -> Insight | None:
    if not dates:
        return None
    latest = max(dates)
    age = (today - latest).days
    severity = GOOD if age <= 7 else WATCH if age <= 21 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{age} days",
        detail=f"The most recent entry is dated {latest:%d %b %Y}, {age} days ago.",
        action="Nothing above this form knows what has happened since." if severity == ALERT else "",
        value=age,
    )


def declining_participation(
    key: str, title: str, tier: str, pairs: Sequence[tuple[date, float]], label: str, field_key: str,
) -> Insight | None:
    if len(pairs) < 4:
        return None
    ordered = sorted(pairs)
    recent = [v for _, v in ordered[-3:]]
    baseline = [v for _, v in ordered[:-3]]
    if not baseline:
        return None
    before, after = mean(baseline), mean(recent)
    if not before or after >= before * 0.85:
        return None
    drop = _pct(before - after, before)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=ALERT if drop > 30 else WATCH,
        headline=f"-{drop}%",
        detail=(
            f"The last three entries average {_round(after)} for {label.lower()}, "
            f"against {_round(before)} earlier in the period."
        ),
        action="A sustained recent drop is the earliest thing worth acting on in this report.",
        value=drop,
        unit="%",
        fields_used=(field_key,),
    )


def activity_rate_trend(
    key: str, title: str, tier: str, dates: Sequence[date], label: str,
) -> Insight | None:
    """Trend in how *often* something is recorded, for forms with no numbers."""
    if len(dates) < 4:
        return None
    buckets: Counter = Counter()
    for day in dates:
        buckets[day.isocalendar()[:2]] += 1
    if len(buckets) < 2:
        return None
    ordered = sorted(buckets)
    counts = [float(buckets[week]) for week in ordered]
    slope = _linear_slope(counts)
    direction = "rising" if slope > 0.2 else "falling" if slope < -0.2 else "steady"
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        severity=WATCH if direction == "rising" else NEUTRAL,
        headline=direction,
        detail=f"{label} recorded per week is {direction} across {len(ordered)} weeks.",
        value=_round(slope, 2),
        chart=_line_chart([f"W{w:02d}" for _, w in ordered], counts, unit="entries"),
    )


def category_cross_tab(
    key: str, title: str, tier: str, pairs: Sequence[tuple[str, str]], row_label: str, col_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    cleaned = [(r, c) for r, c in pairs if r and c]
    if len(cleaned) < MIN_SERIES:
        return None
    counts = Counter(cleaned)
    if len({r for r, _ in cleaned}) < 2 or len({c for _, c in cleaned}) < 2:
        return None
    (top_row, top_col), top_n = counts.most_common(1)[0]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        headline=f"{top_row} / {top_col}",
        detail=(
            f"The most frequent combination is {row_label.lower()} '{top_row}' with "
            f"{col_label.lower()} '{top_col}' ({top_n} entries)."
        ),
        table=[
            {row_label: r, col_label: c, "Entries": n}
            for (r, c), n in counts.most_common(20)
        ],
        fields_used=fields_used,
    )


def category_frequency_by_segment(
    key: str, title: str, tier: str, pairs: Sequence[tuple[str, str]], value_label: str, segment_label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    cleaned = [(s, v) for s, v in pairs if s and v]
    if not cleaned:
        return None
    per_segment: dict[str, Counter] = defaultdict(Counter)
    for segment, value in cleaned:
        per_segment[segment][value] += 1
    if len(per_segment) < 2:
        return None
    rows = []
    for segment, counts in sorted(per_segment.items(), key=lambda item: -sum(item[1].values())):
        dominant, n = counts.most_common(1)[0]
        rows.append({
            segment_label: segment,
            "Entries": sum(counts.values()),
            f"Most common {value_label.lower()}": dominant,
            "Share": f"{_pct(n, sum(counts.values()))}%",
        })
    busiest = rows[0]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        headline=str(busiest[segment_label]),
        detail=(
            f"{busiest[segment_label]} has the most entries ({busiest['Entries']}), "
            f"most often recording {value_label.lower()} '{busiest[f'Most common {value_label.lower()}']}'."
        ),
        table=rows,
        chart=_bar_chart([str(r[segment_label]) for r in rows[:8]], [r["Entries"] for r in rows[:8]], unit="entries"),
        fields_used=fields_used,
    )


def entries_per_segment(
    key: str, title: str, tier: str, segments: Sequence[str], segment_label: str, field_key: str,
) -> Insight | None:
    cleaned = [s for s in segments if s]
    if len(set(cleaned)) < 2:
        return None
    counts = Counter(cleaned)
    ranked = counts.most_common()
    share = _pct(ranked[0][1], len(cleaned))
    severity = WATCH if share > 50 else NEUTRAL
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_COMPARISON,
        severity=severity,
        headline=ranked[0][0],
        detail=(
            f"{ranked[0][0]} accounts for {share}% of entries; "
            f"{ranked[-1][0]} for only {_pct(ranked[-1][1], len(cleaned))}%."
        ),
        action="Skewed volume can mean one area is genuinely busier, or that the rest is under-reported."
        if severity == WATCH
        else "",
        value=share,
        unit="%",
        table=[{segment_label: name, "Entries": n} for name, n in ranked],
        chart=_bar_chart([n for n, _ in ranked[:10]], [c for _, c in ranked[:10]], unit="entries"),
        fields_used=(field_key,),
    )


def text_variety(
    key: str, title: str, tier: str, values: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    cleaned = [v for v in values if v]
    if len(cleaned) < MIN_SERIES:
        return None
    distinct = len(set(v.lower() for v in cleaned))
    ratio = _pct(distinct, len(cleaned))
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_DISTRIBUTION,
        headline=f"{distinct}",
        detail=(
            f"{distinct} distinct {label.lower()} values across {len(cleaned)} entries ({ratio}% unique)."
        ),
        value=distinct,
        table=[{label: name, "Entries": n} for name, n in Counter(cleaned).most_common(15)],
        fields_used=(field_key,),
    )


def repeat_subject(
    key: str, title: str, tier: str, values: Sequence[str], label: str, field_key: str,
) -> Insight | None:
    cleaned = [v.strip() for v in values if v and v.strip()]
    counts = Counter(v.lower() for v in cleaned)
    repeats = [(v, n) for v, n in counts.most_common() if n > 1]
    if not repeats:
        return None
    severity = ALERT if repeats[0][1] >= 4 else WATCH
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{len(repeats)}",
        detail=(
            f"{len(repeats)} {label.lower()} values recur across entries; "
            f"'{repeats[0][0]}' appears {repeats[0][1]} times."
        ),
        action="Repeat appearances usually mean the first intervention did not stick.",
        value=len(repeats),
        table=[{label: v, "Appearances": n} for v, n in repeats[:15]],
        fields_used=(field_key,),
    )


def text_length_trend(
    key: str, title: str, tier: str, dated_texts: Sequence[tuple[date, str]], label: str, field_key: str,
) -> Insight | None:
    if len(dated_texts) < 4:
        return None
    ordered = sorted(dated_texts)
    lengths = [float(len(t.split())) for _, t in ordered]
    slope = _linear_slope(lengths)
    if abs(slope) < 0.3:
        return None
    direction = "more detailed" if slope > 0 else "shorter"
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_QUALITY,
        severity=NEUTRAL if slope > 0 else WATCH,
        headline=direction,
        detail=f"{label} entries are getting {direction} over time (about {_round(slope, 1)} words per entry).",
        action="Shrinking narratives usually mean the form is being filed as a chore." if slope < 0 else "",
        value=_round(slope, 2),
        chart=_line_chart([d.strftime("%d %b") for d, _ in ordered], lengths, unit="words"),
        fields_used=(field_key,),
    )


def gap_between_dates(
    key: str, title: str, tier: str, spans: Sequence[tuple[date, int]], label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    """For forms carrying two dates (e.g. absence start vs report date)."""
    if len(spans) < MIN_SERIES:
        return None
    days = [d for _, d in spans]
    avg = mean(days)
    longest = max(spans, key=lambda item: item[1])
    severity = GOOD if avg <= 3 else WATCH if avg <= 10 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{_round(avg, 1)} days",
        detail=(
            f"{label} averages {_round(avg, 1)} days; the longest was {longest[1]} days "
            f"(recorded {longest[0]:%d %b %Y})."
        ),
        action="Long gaps mean the response started late." if severity != GOOD else "",
        value=_round(avg, 1),
        table=[{"Date": d.strftime("%d %b %Y"), "Days": n} for d, n in sorted(spans, key=lambda i: -i[1])[:10]],
        fields_used=fields_used,
    )


def weekday_activity_load(
    key: str, title: str, tier: str, dates: Sequence[date],
) -> Insight | None:
    if len(dates) < 5:
        return None
    counts = Counter(day.weekday() for day in dates)
    if len(counts) < 2:
        return None
    ordered = sorted(counts)
    busiest = max(counts, key=counts.get)
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        headline=WEEKDAY_NAMES[busiest],
        detail=f"{WEEKDAY_NAMES[busiest]} carries the most entries ({counts[busiest]}).",
        chart=_bar_chart([WEEKDAY_NAMES[d][:3] for d in ordered], [counts[d] for d in ordered], unit="entries"),
    )


def monthly_activity_load(
    key: str, title: str, tier: str, dates: Sequence[date],
) -> Insight | None:
    if len(dates) < 4:
        return None
    counts: Counter = Counter((day.year, day.month) for day in dates)
    if len(counts) < 2:
        return None
    ordered = sorted(counts)
    labels = [f"{MONTH_NAMES[m - 1][:3]} {y % 100:02d}" for y, m in ordered]
    values = [float(counts[k]) for k in ordered]
    busiest = ordered[values.index(max(values))]
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_TREND,
        headline=f"{MONTH_NAMES[busiest[1] - 1]} {busiest[0]}",
        detail=f"{MONTH_NAMES[busiest[1] - 1]} {busiest[0]} carried the most entries ({int(max(values))}).",
        chart=_line_chart(labels, values, unit="entries"),
        table=[{"Month": lab, "Entries": int(val)} for lab, val in zip(labels, values)],
    )


def utilisation_ratio(
    key: str, title: str, tier: str, actual: Sequence[float], expected: Sequence[float], label: str,
    fields_used: tuple[str, ...],
) -> Insight | None:
    pairs = [(a, e) for a, e in zip(actual, expected) if e]
    if not pairs:
        return None
    ratio = _pct(sum(a for a, _ in pairs), sum(e for _, e in pairs))
    severity = GOOD if ratio >= 85 else WATCH if ratio >= 60 else ALERT
    return Insight(
        key=key,
        title=title,
        tier=tier,
        category=CATEGORY_RISK,
        severity=severity,
        headline=f"{ratio}%",
        detail=f"{label} utilisation stands at {ratio}% of what was expected.",
        action="Persistent under-utilisation is a cost the school is already paying."
        if severity != GOOD
        else "",
        value=ratio,
        unit="%",
        fields_used=fields_used,
    )
