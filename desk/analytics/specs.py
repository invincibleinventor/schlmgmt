"""Hand-authored, form-specific analyses.

The generative engine covers what a field's *type* implies. This module covers
what a field's *meaning* implies — relationships between two named fields, and
thresholds that only mean something in context. Everything here is still plain
arithmetic; no model or external service is consulted.

To add a form: append an entry to ``SPECS``. Each builder receives the module,
the decrypted observations, and today's date, and returns extra insights. See
METHODOLOGY.md section 7.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import mean
from typing import Any, Callable, Sequence

from tvs_dms.forms import Module

from .access import DECISION, ENTRY, SUPPORT
from .types import (
    ALERT,
    CATEGORY_COMPARISON,
    CATEGORY_RISK,
    CATEGORY_SYNTHESIS,
    CATEGORY_TREND,
    CATEGORY_VOLUME,
    GOOD,
    NEUTRAL,
    WATCH,
    AnalysisDef,
    Insight,
    Observation,
)

Builder = Callable[[Module, Sequence[Observation], date], list[Insight]]

# Analyses that a generic primitive produces but which are noise on a given
# form. Keyed by module key.
SUPPRESSED: dict[str, frozenset[str]] = {
    # Shift is "Not applicable" on most day-boarding entries, so the weekday
    # cross-tab on it is a table of one row.
    "dayboarding": frozenset({"num.participants.by_shift.top", "num.participants.by_shift.bottom"}),
}

# Tier corrections for generated analyses. Keyed by module key, then by
# analysis key. See the escalation rule in METHODOLOGY.md section 2.
TIER_OVERRIDES: dict[str, dict[str, str]] = {
    # Whether today's assembly ran is the class teacher's own business.
    "assembly_console": {"num.participants.latest": ENTRY},
    # Exam attendance shortfalls need the supervisor, not just the filer.
    "exam_details": {"num.students_appeared.latest": SUPPORT},
}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _numbers(observations: Sequence[Observation], key: str) -> list[float]:
    return [n for n in (_number(obs.get(key)) for obs in observations) if n is not None]


def _dated_numbers(observations: Sequence[Observation], key: str) -> list[tuple[date, float]]:
    out = []
    for obs in observations:
        value = _number(obs.get(key))
        if obs.event_date and value is not None:
            out.append((obs.event_date, value))
    return out


def _text(obs: Observation, key: str) -> str:
    value = obs.get(key)
    return str(value).strip() if value else ""


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _choices(observations: Sequence[Observation], key: str) -> list[str]:
    return [text for text in (_text(obs, key) for obs in observations) if text]


# Ratings are ordered worst-to-best so a mean position is meaningful. Anything
# outside the scale (a legacy free-text answer) is dropped rather than guessed.
_RATING_ORDER = ("Poor", "Needs improvement", "Satisfactory", "Good", "Excellent")
_EXTENT_ORDER = ("None", "Minimal", "Moderate", "High", "Very high")


def _scale_score(values: Sequence[str], order: Sequence[str] = _RATING_ORDER) -> float | None:
    """Mean position on a 0-100 scale, or None when nothing maps."""
    points = [order.index(v) for v in values if v in order]
    if not points:
        return None
    return round(mean(points) / (len(order) - 1) * 100, 1)


def _adverse_rate(values: Sequence[str], adverse: Sequence[str]) -> tuple[float, int, int]:
    """Share of entries landing on the bad end of a scale."""
    usable = [v for v in values if v in _RATING_ORDER or v in _EXTENT_ORDER]
    hits = sum(1 for v in usable if v in adverse)
    return _pct(hits, len(usable)), hits, len(usable)


def _bar(labels, values, unit=""):
    return {"type": "bar", "labels": list(labels), "values": [round(float(v), 2) for v in values], "unit": unit}


def _line(labels, values, unit=""):
    return {"type": "line", "labels": list(labels), "values": [round(float(v), 2) for v in values], "unit": unit}


# --------------------------------------------------------------------------
# Day boarding / canteen committee  (deck slide 2)
# --------------------------------------------------------------------------

def _dayboarding_quality(observations: Sequence[Observation]) -> list[Insight]:
    """The deck's canteen asks: wastage, the four ratings, waiting time, utilisation."""
    out: list[Insight] = []

    wastage = _choices(observations, "food_wastage")
    if wastage:
        rate, hits, total = _adverse_rate(wastage, ("High", "Very high"))
        counts = Counter(wastage)
        out.append(Insight(
            key="dayboarding.wastage_level",
            title="Food wastage",
            tier=DECISION,
            category=CATEGORY_RISK,
            severity=ALERT if rate > 30 else WATCH if rate > 10 else GOOD,
            headline=f"{rate}%",
            detail=(
                f"{hits} of {total} services recorded high or very high wastage. "
                "Wastage is prepared food that was paid for and not eaten."
            ),
            action="Match preparation to the weekday demand profile before changing the menu.",
            value=rate,
            unit="%",
            chart=_bar(
                [name for name in _EXTENT_ORDER if counts.get(name)],
                [counts[name] for name in _EXTENT_ORDER if counts.get(name)],
                "Services",
            ),
            fields_used=("food_wastage",),
        ))

    # Left-over notes are the deck's "left over identification" / preference read.
    leftovers = [_text(obs, "wastage_notes") for obs in observations]
    leftovers = [text for text in leftovers if text]
    if leftovers:
        out.append(Insight(
            key="dayboarding.leftover_items",
            title="What gets left over",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            severity=WATCH,
            headline=f"{len(leftovers)} note{'s' if len(leftovers) != 1 else ''}",
            detail="Recurring left-over items are the clearest signal of what students will not eat.",
            action="Drop or rework an item that appears repeatedly rather than cooking less of everything.",
            value=len(leftovers),
            table=[{"Left over": text[:120]} for text in leftovers[:20]],
            fields_used=("wastage_notes",),
        ))

    rating_fields = (
        ("rating_food", "food served"),
        ("rating_student_feedback", "student feedback"),
        ("rating_staff_feedback", "staff feedback"),
        ("rating_waiting_time", "waiting time"),
    )
    scored: list[tuple[str, float]] = []
    for key, label in rating_fields:
        values = _choices(observations, key)
        score = _scale_score(values)
        if score is None:
            continue
        scored.append((label, score))
        rate, hits, total = _adverse_rate(values, ("Poor", "Needs improvement"))
        out.append(Insight(
            key=f"dayboarding.{key}",
            title=f"Rating: {label}",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            severity=ALERT if rate > 30 else WATCH if rate > 10 else GOOD,
            headline=f"{score}/100",
            detail=(
                f"Mean rating for {label} is {score} out of 100. "
                f"{hits} of {total} entries rated it poor or needing improvement."
            ),
            action=(
                "Rated well; hold the current arrangement." if rate <= 10
                else f"Trace the {hits} weak entries to a day and a menu before acting."
            ),
            value=score,
            unit="/100",
            fields_used=(key,),
        ))

    if len(scored) >= 2:
        weakest = min(scored, key=lambda item: item[1])
        out.append(Insight(
            key="dayboarding.quality_profile",
            title="Where the canteen is weakest",
            tier=DECISION,
            category=CATEGORY_SYNTHESIS,
            severity=ALERT if weakest[1] < 50 else WATCH if weakest[1] < 70 else GOOD,
            headline=weakest[0].title(),
            detail=(
                f"Of the rated dimensions, {weakest[0]} scores lowest at {weakest[1]}/100. "
                "The others: " + ", ".join(f"{label} {score}" for label, score in scored if label != weakest[0]) + "."
            ),
            action=f"Fix {weakest[0]} first — it is the binding constraint on satisfaction.",
            value=weakest[1],
            unit="/100",
            chart=_bar([label.title() for label, _ in scored], [score for _, score in scored], "/100"),
            fields_used=tuple(key for key, _ in rating_fields),
        ))

    waits = _numbers(observations, "waiting_minutes")
    if waits:
        worst = max(waits)
        average_wait = round(mean(waits), 1)
        out.append(Insight(
            key="dayboarding.waiting_time",
            title="Queue waiting time",
            tier=DECISION,
            category=CATEGORY_RISK,
            severity=ALERT if worst > 20 else WATCH if worst > 10 else GOOD,
            headline=f"{average_wait} min",
            detail=f"Average longest wait is {average_wait} minutes, peaking at {round(worst)} minutes.",
            action="Waiting time cuts into the next period. Stagger sittings before adding counters.",
            value=average_wait,
            unit="min",
            fields_used=("waiting_minutes",),
        ))

    # Utilisation: availed against expected is the deck's "day wise utilization".
    ratios = [
        (obs.event_date, _number(obs.get("attendance")), _number(obs.get("expected_attendance")))
        for obs in observations
    ]
    usable = [(d, a, e) for d, a, e in ratios if a is not None and e]
    if usable:
        availed = sum(a for _, a, _ in usable)
        expected = sum(e for _, _, e in usable)
        utilisation = _pct(availed, expected)
        out.append(Insight(
            key="dayboarding.utilisation",
            title="Day boarding utilisation",
            tier=DECISION,
            category=CATEGORY_VOLUME,
            severity=ALERT if utilisation < 60 else WATCH if utilisation < 80 else GOOD,
            headline=f"{utilisation}%",
            detail=(
                f"{round(availed)} of {round(expected)} expected students actually availed day boarding."
            ),
            action="Under-utilisation is paid-for capacity going unused. Ask the non-takers why.",
            value=utilisation,
            unit="%",
            fields_used=("attendance", "expected_attendance"),
        ))

    return out


def _dayboarding(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    out: list[Insight] = []
    out.extend(_dayboarding_quality(observations))
    # `attendance` is the real headcount; `participants` is the pre-IMPACT
    # field kept as a fallback so older records still analyse.
    pairs = _dated_numbers(observations, "attendance") or _dated_numbers(observations, "participants")
    if not pairs:
        return out

    # "on which day day boarding was less" — the deck's own example.
    by_day = sorted(pairs)
    lowest = min(by_day, key=lambda item: item[1])
    average = mean(v for _, v in by_day)
    shortfall = _pct(average - lowest[1], average) if average else 0
    out.append(Insight(
        key="dayboarding.lowest_day",
        title="Quietest day boarding day",
        tier=DECISION,
        category=CATEGORY_TREND,
        severity=ALERT if shortfall > 40 else WATCH,
        headline=lowest[0].strftime("%d %b %Y"),
        detail=(
            f"Only {round(lowest[1])} took day boarding on {lowest[0]:%d %b %Y}, "
            f"{shortfall}% below the daily average of {round(average)}."
        ),
        action="Find out what was different about that day before assuming demand fell.",
        value=shortfall,
        unit="%",
        chart=_line([d.strftime("%d %b") for d, _ in by_day], [v for _, v in by_day], "Participants"),
        fields_used=("attendance", "participants", "event_date"),
    ))

    # Utilisation swing drives catering quantity, which is the cost lever.
    high = max(v for _, v in by_day)
    low = min(v for _, v in by_day)
    swing = _pct(high - low, high) if high else 0
    out.append(Insight(
        key="dayboarding.demand_swing",
        title="Day-to-day demand swing",
        tier=DECISION,
        category=CATEGORY_RISK,
        severity=ALERT if swing > 50 else WATCH if swing > 25 else GOOD,
        headline=f"{swing}%",
        detail=(
            f"Headcount swings {swing}% between the busiest ({round(high)}) and quietest "
            f"({round(low)}) day. Catering is purchased against the high figure."
        ),
        action="Every point of swing is food prepared and not eaten. Forecast from the weekday pattern, not the peak.",
        value=swing,
        unit="%",
        fields_used=("attendance", "participants"),
    ))

    # Weekday demand profile -> the actual catering planner.
    buckets: dict[int, list[float]] = defaultdict(list)
    for day, value in by_day:
        buckets[day.weekday()].append(value)
    if len(buckets) >= 3:
        names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        ordered = sorted(buckets)
        averages = [mean(buckets[d]) for d in ordered]
        quietest = ordered[averages.index(min(averages))]
        out.append(Insight(
            key="dayboarding.weekday_planner",
            title="Weekday catering profile",
            tier=SUPPORT,
            category=CATEGORY_TREND,
            severity=WATCH,
            headline=names[quietest],
            detail=(
                f"{names[quietest]} is consistently the lightest day at {round(min(averages))} on average; "
                f"the heaviest is {names[ordered[averages.index(max(averages))]]} at {round(max(averages))}."
            ),
            action="Order to the weekday average rather than a flat daily quantity.",
            chart=_bar([names[d] for d in ordered], averages, "Participants"),
            fields_used=("attendance", "participants", "event_date"),
        ))

    # Which sessions carry the load — the deck's "food preference" insight.
    sessions: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        session = _text(obs, "session")
        value = _number(obs.get("attendance"))
        if value is None:
            value = _number(obs.get("participants"))
        if session and value is not None:
            sessions[session].append(value)
    if len(sessions) >= 2:
        ranked = sorted(((k, mean(v), len(v)) for k, v in sessions.items()), key=lambda i: i[1], reverse=True)
        out.append(Insight(
            key="dayboarding.session_preference",
            title="Which sessions draw the numbers",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            headline=ranked[0][0],
            detail=f"{ranked[0][0]} averages the highest turnout at {round(ranked[0][1])} per sitting.",
            action="Low-turnout sessions are where wastage concentrates.",
            table=[{"Session": k, "Average turnout": round(v), "Times run": n} for k, v, n in ranked],
            chart=_bar([k for k, _, _ in ranked[:8]], [v for _, v, _ in ranked[:8]], "Participants"),
            fields_used=("session", "attendance", "participants"),
        ))

    # Staffing continuity: one person carrying the hub is an operational risk.
    staff = Counter(_text(obs, "staff") for obs in observations if _text(obs, "staff"))
    if staff:
        top, count = staff.most_common(1)[0]
        share = _pct(count, sum(staff.values()))
        out.append(Insight(
            key="dayboarding.staff_dependency",
            title="Supervision dependency",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if share > 70 else WATCH if share > 50 else GOOD,
            headline=f"{share}%",
            detail=f"{top} supervised {share}% of recorded sittings ({count} of {sum(staff.values())}).",
            action="Cross-train a second supervisor before absence forces it." if share > 50 else "",
            value=share,
            unit="%",
            table=[{"Staff in charge": k, "Sittings": v} for k, v in staff.most_common()],
            fields_used=("staff",),
        ))

    return out


_DAYBOARDING_CATALOGUE = (
    ("dayboarding.wastage_level", "Food wastage", DECISION, CATEGORY_RISK, ("food_wastage",)),
    ("dayboarding.leftover_items", "What gets left over", SUPPORT, CATEGORY_COMPARISON, ("wastage_notes",)),
    ("dayboarding.rating_food", "Rating: food served", SUPPORT, CATEGORY_COMPARISON, ("rating_food",)),
    ("dayboarding.rating_student_feedback", "Rating: student feedback", SUPPORT, CATEGORY_COMPARISON, ("rating_student_feedback",)),
    ("dayboarding.rating_staff_feedback", "Rating: staff feedback", SUPPORT, CATEGORY_COMPARISON, ("rating_staff_feedback",)),
    ("dayboarding.rating_waiting_time", "Rating: waiting time", SUPPORT, CATEGORY_COMPARISON, ("rating_waiting_time",)),
    ("dayboarding.quality_profile", "Where the canteen is weakest", DECISION, CATEGORY_SYNTHESIS, ("rating_food", "rating_student_feedback", "rating_staff_feedback", "rating_waiting_time")),
    ("dayboarding.waiting_time", "Queue waiting time", DECISION, CATEGORY_RISK, ("waiting_minutes",)),
    ("dayboarding.utilisation", "Day boarding utilisation", DECISION, CATEGORY_VOLUME, ("attendance", "expected_attendance")),
    ("dayboarding.lowest_day", "Quietest day boarding day", DECISION, CATEGORY_TREND, ("participants", "event_date")),
    ("dayboarding.demand_swing", "Day-to-day demand swing", DECISION, CATEGORY_RISK, ("participants",)),
    ("dayboarding.weekday_planner", "Weekday catering profile", SUPPORT, CATEGORY_TREND, ("participants", "event_date")),
    ("dayboarding.session_preference", "Which sessions draw the numbers", SUPPORT, CATEGORY_COMPARISON, ("session", "participants")),
    ("dayboarding.staff_dependency", "Supervision dependency", SUPPORT, CATEGORY_RISK, ("staff",)),
)


# --------------------------------------------------------------------------
# Exam committee  (deck slide 3)
# --------------------------------------------------------------------------

def _exam_readiness(observations: Sequence[Observation]) -> list[Insight]:
    """Deck slide 3: QP availability, paper arrangement, invigilation, OD, portions."""
    out: list[Insight] = []

    qp = _choices(observations, "qp_status")
    if qp:
        counts = Counter(qp)
        unready = counts.get("Delayed", 0) + counts.get("Not started", 0)
        rate = _pct(unready, len(qp))
        out.append(Insight(
            key="exam_details.qp_readiness",
            title="Question paper readiness",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if unready else WATCH if counts.get("In preparation") else GOOD,
            headline=f"{rate}%",
            detail=(
                f"{unready} of {len(qp)} papers are delayed or not started; "
                f"{counts.get('Ready', 0)} are ready."
            ),
            action="A delayed paper stops an exam. Clear these before the schedule is published.",
            value=rate,
            unit="%",
            chart=_bar(list(counts.keys()), list(counts.values()), "Papers"),
            fields_used=("qp_status",),
        ))

    arrangement = _choices(observations, "paper_arrangement")
    if arrangement:
        counts = Counter(arrangement)
        pending = counts.get("Pending", 0) + counts.get("Partial", 0)
        out.append(Insight(
            key="exam_details.paper_arrangement",
            title="Paper arrangement status",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if counts.get("Pending") else WATCH if pending else GOOD,
            headline=f"{pending} outstanding",
            detail=f"{pending} of {len(arrangement)} entries report arrangement as partial or pending.",
            action="Confirm printing and collation dates for each outstanding paper.",
            value=pending,
            fields_used=("paper_arrangement",),
        ))

    # Invigilator cover per hall: the deck's "Invigilation" and "Support needed".
    cover: list[tuple[str, float, float]] = []
    for obs in observations:
        invigilators = _number(obs.get("invigilators"))
        appeared = _number(obs.get("students_appeared"))
        if invigilators and appeared:
            cover.append((_text(obs, "exam") or "Exam", invigilators, appeared))
    if cover:
        ratios = [appeared / invigilators for _, invigilators, appeared in cover]
        worst_index = ratios.index(max(ratios))
        worst = cover[worst_index]
        average_ratio = round(mean(ratios), 1)
        out.append(Insight(
            key="exam_details.invigilation_cover",
            title="Invigilation cover",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if max(ratios) > 40 else WATCH if max(ratios) > 30 else GOOD,
            headline=f"1:{average_ratio}",
            detail=(
                f"On average one invigilator per {average_ratio} students. "
                f"The thinnest cover was {worst[0]} at 1:{round(ratios[worst_index], 1)}."
            ),
            action="Thin cover is where malpractice and mis-collection happen. Staff the worst hall first.",
            value=average_ratio,
            fields_used=("invigilators", "students_appeared", "exam"),
        ))

    # OD planning: on-duty students still need a re-sit, so this is a planner.
    od = _numbers(observations, "od_count")
    if od:
        total_od = sum(od)
        out.append(Insight(
            key="exam_details.od_load",
            title="On-duty students to re-schedule",
            tier=SUPPORT,
            category=CATEGORY_VOLUME,
            severity=ALERT if total_od > 30 else WATCH if total_od else GOOD,
            headline=f"{round(total_od)}",
            detail=(
                f"{round(total_od)} OD absences across {len(od)} entries. "
                "Each one is a paper that still has to be sat."
            ),
            action="Build the re-sit plan from this figure, not from the absentee list.",
            value=total_od,
            fields_used=("od_count",),
        ))

    # Portions: the deck's dedicated PORTIONS hub, read per standard and subject.
    portions: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        covered = _number(obs.get("portion_covered"))
        if covered is None:
            continue
        subject = _text(obs, "subject") or _text(obs, "subjects") or "Unspecified"
        standard = _text(obs, "standard")
        portions[f"{subject} · {standard}" if standard else subject].append(covered)
    if portions:
        averages = {name: round(mean(values), 1) for name, values in portions.items()}
        ordered = sorted(averages.items(), key=lambda item: item[1])
        behind = [name for name, value in ordered if value < 75]
        overall = round(mean(averages.values()), 1)
        out.append(Insight(
            key="exam_details.portions_coverage",
            title="Syllabus portions covered",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            severity=ALERT if any(v < 60 for v in averages.values()) else WATCH if behind else GOOD,
            headline=f"{overall}%",
            detail=(
                f"Mean coverage is {overall}% across {len(averages)} subject-standard combinations. "
                + (f"{len(behind)} sit below 75%: {', '.join(behind[:5])}." if behind else "None sit below 75%.")
            ),
            action="Examining un-taught portions is the fastest way to lose a cohort's confidence.",
            value=overall,
            unit="%",
            chart=_bar([name for name, _ in ordered[:8]], [value for _, value in ordered[:8]], "%"),
            table=[{"Subject / standard": name, "Covered %": value} for name, value in ordered],
            fields_used=("portion_covered", "subject", "subjects", "standard"),
        ))

    return out


def _exam_details(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    out: list[Insight] = []
    out.extend(_exam_readiness(observations))

    # Appeared vs expected — the absentee picture without naming students.
    gaps: list[tuple[date, float, float, float]] = []
    for obs in observations:
        expected = _number(obs.get("students_expected")) or _number(obs.get("participants"))
        appeared = _number(obs.get("students_appeared"))
        if obs.event_date and expected and appeared is not None:
            gaps.append((obs.event_date, expected, appeared, expected - appeared))

    if gaps:
        total_expected = sum(e for _, e, _, _ in gaps)
        total_appeared = sum(a for _, _, a, _ in gaps)
        rate = _pct(total_appeared, total_expected)
        out.append(Insight(
            key="exam.appearance_rate",
            title="Exam appearance rate",
            tier=ENTRY,
            category=CATEGORY_VOLUME,
            severity=GOOD if rate >= 95 else WATCH if rate >= 85 else ALERT,
            headline=f"{rate}%",
            detail=(
                f"{round(total_appeared)} of {round(total_expected)} expected candidates appeared "
                f"across {len(gaps)} sittings."
            ),
            action="Every absentee is a re-exam, an invigilator, and a fresh question paper."
            if rate < 95 else "",
            value=rate,
            unit="%",
            fields_used=("students_expected", "participants", "students_appeared"),
        ))

        worst = max(gaps, key=lambda item: item[3])
        if worst[3] > 0:
            out.append(Insight(
                key="exam.worst_absence_day",
                title="Heaviest absence sitting",
                tier=SUPPORT,
                category=CATEGORY_RISK,
                severity=ALERT if _pct(worst[3], worst[1]) > 20 else WATCH,
                headline=f"{round(worst[3])} absent",
                detail=(
                    f"{round(worst[3])} candidates missed the sitting on {worst[0]:%d %b %Y} "
                    f"({_pct(worst[3], worst[1])}% of that cohort)."
                ),
                action="Plan the OD and re-exam slot for this cohort now.",
                value=worst[3],
                table=[
                    {"Date": d.strftime("%d %b %Y"), "Expected": round(e), "Appeared": round(a), "Absent": round(g)}
                    for d, e, a, g in sorted(gaps, key=lambda i: i[3], reverse=True)[:10]
                ],
                fields_used=("students_expected", "participants", "students_appeared", "event_date"),
            ))

        # Repeated shortfall by class -> the deck's "repeated absentees" report.
        by_standard: dict[str, list[float]] = defaultdict(list)
        for obs in observations:
            expected = _number(obs.get("students_expected")) or _number(obs.get("participants"))
            appeared = _number(obs.get("students_appeared"))
            standard = _text(obs, "standard")
            if standard and expected and appeared is not None:
                by_standard[standard].append(_pct(expected - appeared, expected))
        repeat = {k: v for k, v in by_standard.items() if sum(1 for x in v if x > 10) >= 2}
        if repeat:
            ranked = sorted(((k, mean(v)) for k, v in repeat.items()), key=lambda i: i[1], reverse=True)
            out.append(Insight(
                key="exam.repeat_absence_classes",
                title="Classes with repeated absence",
                tier=DECISION,
                category=CATEGORY_RISK,
                severity=ALERT,
                headline=ranked[0][0],
                detail=(
                    f"{len(ranked)} classes recorded above-10% absence in more than one sitting; "
                    f"{ranked[0][0]} averages {round(ranked[0][1], 1)}%."
                ),
                action="This is a pattern, not a set of individual absences. It needs a class-level conversation.",
                table=[{"Standard": k, "Average absence": f"{round(v, 1)}%"} for k, v in ranked],
                chart=_bar([k for k, _ in ranked[:8]], [v for _, v in ranked[:8]], "% absent"),
                fields_used=("standard", "students_expected", "participants", "students_appeared"),
            ))

    # Portions / subject coverage — the deck's "Portions report".
    subject_mentions: Counter = Counter()
    for obs in observations:
        # The structured single-subject field is authoritative when present;
        # `subjects` is the older free-text list, still parsed for old records.
        single = _text(obs, "subject")
        if single:
            subject_mentions[single] += 1
            continue
        for chunk in _text(obs, "subjects").replace("\n", ",").split(","):
            cleaned = chunk.strip()
            if cleaned:
                subject_mentions[cleaned] += 1
    if subject_mentions:
        out.append(Insight(
            key="exam.subject_coverage",
            title="Subject coverage across sittings",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            headline=f"{len(subject_mentions)} subjects",
            detail=(
                f"{len(subject_mentions)} distinct subjects appear across the exam records; "
                f"'{subject_mentions.most_common(1)[0][0]}' appears most often."
            ),
            action="Subjects listed once may still have papers to prepare.",
            table=[{"Subject": k, "Sittings": v} for k, v in subject_mentions.most_common(20)],
            fields_used=("subject", "subjects"),
        ))

    # Exam schedule density -> invigilation and hall arrangement load.
    per_day: Counter = Counter(obs.event_date for obs in observations if obs.event_date)
    if per_day:
        busiest, count = per_day.most_common(1)[0]
        if count > 1:
            out.append(Insight(
                key="exam.schedule_density",
                title="Busiest exam day",
                tier=SUPPORT,
                category=CATEGORY_RISK,
                severity=ALERT if count >= 4 else WATCH,
                headline=f"{count} sittings",
                detail=f"{busiest:%d %b %Y} carries {count} separate sittings.",
                action="Confirm hall capacity and invigilator count for that date.",
                value=count,
                table=[{"Date": d.strftime("%d %b %Y"), "Sittings": n} for d, n in per_day.most_common(10)],
                fields_used=("event_date",),
            ))

    return out


_EXAM_CATALOGUE = (
    ("exam_details.qp_readiness", "Question paper readiness", SUPPORT, CATEGORY_RISK, ("qp_status",)),
    ("exam_details.paper_arrangement", "Paper arrangement status", SUPPORT, CATEGORY_RISK, ("paper_arrangement",)),
    ("exam_details.invigilation_cover", "Invigilation cover", SUPPORT, CATEGORY_RISK, ("invigilators", "students_appeared", "exam")),
    ("exam_details.od_load", "On-duty students to re-schedule", SUPPORT, CATEGORY_VOLUME, ("od_count",)),
    ("exam_details.portions_coverage", "Syllabus portions covered", SUPPORT, CATEGORY_COMPARISON, ("portion_covered", "subject", "standard")),
    ("exam.appearance_rate", "Exam appearance rate", ENTRY, CATEGORY_VOLUME, ("participants", "students_appeared")),
    ("exam.worst_absence_day", "Heaviest absence sitting", SUPPORT, CATEGORY_RISK, ("participants", "students_appeared", "event_date")),
    ("exam.repeat_absence_classes", "Classes with repeated absence", DECISION, CATEGORY_RISK, ("standard", "participants", "students_appeared")),
    ("exam.subject_coverage", "Subject coverage across sittings", SUPPORT, CATEGORY_COMPARISON, ("subjects",)),
    ("exam.schedule_density", "Busiest exam day", SUPPORT, CATEGORY_RISK, ("event_date",)),
)


# --------------------------------------------------------------------------
# Field trip  (deck slide 5)
# --------------------------------------------------------------------------

def _field_trip_outcomes(observations: Sequence[Observation]) -> list[Insight]:
    """Deck slide 5: venue changes, transport, budget, engagement, feedback."""
    out: list[Insight] = []

    # Planned venue vs where the trip went — the deck's "arrangement planner".
    changed = [
        (_text(obs, "venue_planned"), _text(obs, "destination"))
        for obs in observations
        if _text(obs, "venue_planned") and _text(obs, "destination")
    ]
    diverged = [(p, d) for p, d in changed if p.lower() != d.lower()]
    if changed:
        rate = _pct(len(diverged), len(changed))
        out.append(Insight(
            key="field_trip.venue_changes",
            title="Trips that changed venue",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if rate > 30 else WATCH if diverged else GOOD,
            headline=f"{rate}%",
            detail=f"{len(diverged)} of {len(changed)} trips went somewhere other than the planned venue.",
            action="Repeated late changes point to a booking process that is not holding.",
            value=rate,
            unit="%",
            table=[{"Planned": p, "Actual": d} for p, d in diverged[:15]],
            fields_used=("venue_planned", "destination"),
        ))

    transport = _choices(observations, "transport_mode")
    if transport:
        counts = Counter(transport)
        out.append(Insight(
            key="field_trip.transport_mix",
            title="Transport used",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            severity=NEUTRAL,
            headline=counts.most_common(1)[0][0],
            detail=(
                f"{counts.most_common(1)[0][1]} of {len(transport)} trips used "
                f"{counts.most_common(1)[0][0].lower()}."
            ),
            action="Concentration on hired transport is a cost lever worth negotiating.",
            value=counts.most_common(1)[0][1],
            chart=_bar(list(counts.keys()), list(counts.values()), "Trips"),
            fields_used=("transport_mode",),
        ))

    costs = _numbers(observations, "budget")
    if costs:
        total_cost = sum(costs)
        heads = sum(_numbers(observations, "participants")) or 0
        per_head = round(total_cost / heads, 1) if heads else None
        out.append(Insight(
            key="field_trip.budget",
            title="Field trip spend",
            tier=DECISION,
            category=CATEGORY_VOLUME,
            severity=NEUTRAL,
            headline=f"{round(total_cost)}",
            detail=(
                f"{round(total_cost)} spent across {len(costs)} trips"
                + (f", about {per_head} per student." if per_head else ".")
            ),
            action="Compare cost per student against learning outcome before approving the next term's trips.",
            value=total_cost,
            fields_used=("budget", "participants"),
        ))

    turnout = [
        (_number(obs.get("participants")), _number(obs.get("students_expected")))
        for obs in observations
    ]
    usable = [(went, planned) for went, planned in turnout if went is not None and planned]
    if usable:
        rate = _pct(sum(w for w, _ in usable), sum(p for _, p in usable))
        out.append(Insight(
            key="field_trip.turnout",
            title="Turnout against plan",
            tier=SUPPORT,
            category=CATEGORY_VOLUME,
            severity=ALERT if rate < 60 else WATCH if rate < 80 else GOOD,
            headline=f"{rate}%",
            detail=f"{round(sum(w for w, _ in usable))} students went against {round(sum(p for _, p in usable))} planned.",
            action="Seats booked and unused are money spent. Confirm numbers closer to the date.",
            value=rate,
            unit="%",
            fields_used=("participants", "students_expected"),
        ))

    engagement = _choices(observations, "student_engagement")
    score = _scale_score(engagement)
    if score is not None:
        rate, hits, total = _adverse_rate(engagement, ("Poor", "Needs improvement"))
        out.append(Insight(
            key="field_trip.engagement",
            title="Student engagement",
            tier=DECISION,
            category=CATEGORY_SYNTHESIS,
            severity=ALERT if score < 50 else WATCH if score < 70 else GOOD,
            headline=f"{score}/100",
            detail=(
                f"Mean engagement is {score}/100 across {total} rated trips; "
                f"{hits} were rated poor or needing improvement."
            ),
            action="A well-run trip that does not engage is a cost without a learning return.",
            value=score,
            unit="/100",
            fields_used=("student_engagement",),
        ))

    return out


def _field_trip(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    out: list[Insight] = []
    out.extend(_field_trip_outcomes(observations))

    # Escort ratio is the safety and staffing decision on this form.
    ratios: list[tuple[date, float, float, float]] = []
    for obs in observations:
        students = _number(obs.get("participants"))
        staff = _number(obs.get("staff_count"))
        if obs.event_date and students and staff:
            ratios.append((obs.event_date, students, staff, students / staff))
    if ratios:
        average_ratio = mean(r for _, _, _, r in ratios)
        worst = max(ratios, key=lambda item: item[3])
        out.append(Insight(
            key="trip.escort_ratio",
            title="Student-to-escort ratio",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if average_ratio > 25 else WATCH if average_ratio > 15 else GOOD,
            headline=f"{round(average_ratio, 1)}:1",
            detail=(
                f"Trips run at {round(average_ratio, 1)} students per accompanying staff member on average; "
                f"the thinnest cover was {round(worst[3], 1)}:1 on {worst[0]:%d %b %Y}."
            ),
            action="Set a maximum ratio and staff to it before the trip is approved.",
            value=round(average_ratio, 1),
            table=[
                {"Date": d.strftime("%d %b %Y"), "Students": round(s), "Staff": round(t), "Ratio": f"{round(r, 1)}:1"}
                for d, s, t, r in sorted(ratios, key=lambda i: i[3], reverse=True)[:10]
            ],
            fields_used=("participants", "staff_count", "event_date"),
        ))

        understaffed = [r for r in ratios if r[3] > 25]
        if understaffed:
            out.append(Insight(
                key="trip.understaffed_trips",
                title="Trips run thin on escorts",
                tier=DECISION,
                category=CATEGORY_RISK,
                severity=ALERT,
                headline=f"{len(understaffed)}",
                detail=f"{len(understaffed)} of {len(ratios)} trips exceeded 25 students per escort.",
                action="This is a liability question, not a logistics one.",
                value=len(understaffed),
                fields_used=("participants", "staff_count"),
            ))

    # Destination repetition -> the learning-outcome and budget question.
    destinations = Counter(_text(obs, "destination") for obs in observations if _text(obs, "destination"))
    if destinations:
        repeats = [(k, v) for k, v in destinations.most_common() if v > 1]
        out.append(Insight(
            key="trip.destination_mix",
            title="Destination variety",
            tier=DECISION,
            category=CATEGORY_COMPARISON,
            severity=WATCH if repeats and repeats[0][1] >= 3 else NEUTRAL,
            headline=f"{len(destinations)} venues",
            detail=(
                f"{len(destinations)} distinct destinations across {sum(destinations.values())} trips."
                + (f" '{repeats[0][0]}' was visited {repeats[0][1]} times." if repeats else "")
            ),
            action="Repeat venues are cheaper to run but narrow the learning exposure." if repeats else "",
            table=[{"Destination": k, "Trips": v} for k, v in destinations.most_common(15)],
            chart=_bar([k for k, _ in destinations.most_common(8)],
                       [v for _, v in destinations.most_common(8)], "trips"),
            fields_used=("destination",),
        ))

    # Which classes are actually getting out of the building.
    by_standard = Counter(_text(obs, "standard") for obs in observations if _text(obs, "standard"))
    if len(by_standard) >= 2:
        ranked = by_standard.most_common()
        out.append(Insight(
            key="trip.class_access",
            title="Which classes get field trips",
            tier=DECISION,
            category=CATEGORY_COMPARISON,
            severity=WATCH if ranked[0][1] >= 3 * ranked[-1][1] else NEUTRAL,
            headline=ranked[0][0],
            detail=(
                f"{ranked[0][0]} took {ranked[0][1]} trips; {ranked[-1][0]} took {ranked[-1][1]}."
            ),
            action="Uneven access is a curriculum-equity issue as much as a budget one.",
            table=[{"Standard": k, "Trips": v} for k, v in ranked],
            chart=_bar([k for k, _ in ranked[:10]], [v for _, v in ranked[:10]], "trips"),
            fields_used=("standard",),
        ))

    return out


_TRIP_CATALOGUE = (
    ("field_trip.venue_changes", "Trips that changed venue", SUPPORT, CATEGORY_RISK, ("venue_planned", "destination")),
    ("field_trip.transport_mix", "Transport used", SUPPORT, CATEGORY_COMPARISON, ("transport_mode",)),
    ("field_trip.budget", "Field trip spend", DECISION, CATEGORY_VOLUME, ("budget", "participants")),
    ("field_trip.turnout", "Turnout against plan", SUPPORT, CATEGORY_VOLUME, ("participants", "students_expected")),
    ("field_trip.engagement", "Student engagement", DECISION, CATEGORY_SYNTHESIS, ("student_engagement",)),
    ("trip.escort_ratio", "Student-to-escort ratio", SUPPORT, CATEGORY_RISK, ("participants", "staff_count", "event_date")),
    ("trip.understaffed_trips", "Trips run thin on escorts", DECISION, CATEGORY_RISK, ("participants", "staff_count")),
    ("trip.destination_mix", "Destination variety", DECISION, CATEGORY_COMPARISON, ("destination",)),
    ("trip.class_access", "Which classes get field trips", DECISION, CATEGORY_COMPARISON, ("standard",)),
)


# --------------------------------------------------------------------------
# Assembly console  (deck slide 6)
# --------------------------------------------------------------------------

def _assembly_quality(observations: Sequence[Observation]) -> list[Insight]:
    """Deck slide 6: programme flow, student performance, values shared, turnout."""
    out: list[Insight] = []

    for key, label, tier in (
        ("flow_rating", "programme quality and flow", DECISION),
        ("student_performance", "student performance", SUPPORT),
    ):
        values = _choices(observations, key)
        score = _scale_score(values)
        if score is None:
            continue
        rate, hits, total = _adverse_rate(values, ("Poor", "Needs improvement"))
        counts = Counter(values)
        out.append(Insight(
            key=f"assembly.{key}",
            title=f"Rating: {label}",
            tier=tier,
            category=CATEGORY_SYNTHESIS,
            severity=ALERT if score < 50 else WATCH if score < 70 else GOOD,
            headline=f"{score}/100",
            detail=(
                f"Mean rating for {label} is {score}/100 across {total} assemblies; "
                f"{hits} were rated poor or needing improvement."
            ),
            action=(
                "Holding well — keep the current format." if rate <= 10
                else "Review the weak assemblies for a common cause: rehearsal time, or the slot itself."
            ),
            value=score,
            unit="/100",
            chart=_bar(
                [name for name in _RATING_ORDER if counts.get(name)],
                [counts[name] for name in _RATING_ORDER if counts.get(name)],
                "Assemblies",
            ),
            fields_used=(key,),
        ))

    # "Values shared" is the deck's stated purpose for this hub.
    values_shared = Counter(
        _text(obs, "values_shared").lower() for obs in observations if _text(obs, "values_shared")
    )
    if values_shared:
        repeats = [(name, count) for name, count in values_shared.most_common() if count > 1]
        out.append(Insight(
            key="assembly.values_shared",
            title="Values covered",
            tier=DECISION,
            category=CATEGORY_COMPARISON,
            severity=WATCH if len(values_shared) < 4 else GOOD,
            headline=f"{len(values_shared)} distinct",
            detail=(
                f"{len(values_shared)} distinct values across {sum(values_shared.values())} assemblies."
                + (f" Most repeated: {repeats[0][0].title()} ({repeats[0][1]}×)." if repeats else "")
            ),
            action="A narrow set of values repeated is a curriculum gap, not reinforcement.",
            value=len(values_shared),
            table=[{"Value": name.title(), "Assemblies": count} for name, count in values_shared.most_common(15)],
            fields_used=("values_shared",),
        ))

    turnout = [
        (_number(obs.get("participants")), _number(obs.get("students_expected")))
        for obs in observations
    ]
    usable = [(present, roll) for present, roll in turnout if present is not None and roll]
    if usable:
        rate = _pct(sum(p for p, _ in usable), sum(r for _, r in usable))
        out.append(Insight(
            key="assembly.turnout",
            title="Assembly turnout",
            tier=SUPPORT,
            category=CATEGORY_VOLUME,
            severity=ALERT if rate < 70 else WATCH if rate < 85 else GOOD,
            headline=f"{rate}%",
            detail=f"{round(sum(p for p, _ in usable))} attended against {round(sum(r for _, r in usable))} on roll.",
            action="Persistent low turnout means the assembly slot is competing with something else.",
            value=rate,
            unit="%",
            fields_used=("participants", "students_expected"),
        ))

    return out


def _assembly(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    out: list[Insight] = []
    out.extend(_assembly_quality(observations))

    # Theme repetition -> "values shared", and whether they are being repeated.
    themes = Counter(_text(obs, "theme").lower() for obs in observations if _text(obs, "theme"))
    if themes:
        repeats = [(k, v) for k, v in themes.most_common() if v > 1]
        out.append(Insight(
            key="assembly.theme_variety",
            title="Themes and values covered",
            tier=DECISION,
            category=CATEGORY_COMPARISON,
            severity=WATCH if repeats and repeats[0][1] >= 3 else GOOD,
            headline=f"{len(themes)} themes",
            detail=(
                f"{len(themes)} distinct themes across {sum(themes.values())} assemblies."
                + (f" '{repeats[0][0]}' recurred {repeats[0][1]} times." if repeats else "")
            ),
            action="Check repeats are deliberate reinforcement, not a gap in planning." if repeats else "",
            table=[{"Theme": k, "Assemblies": v} for k, v in themes.most_common(15)],
            fields_used=("theme",),
        ))

    # Assembly type mix -> the deck's "standard wise and section wise report".
    type_counts = Counter(_text(obs, "assembly_type") for obs in observations if _text(obs, "assembly_type"))
    if type_counts:
        out.append(Insight(
            key="assembly.type_balance",
            title="Balance of assembly types",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            headline=type_counts.most_common(1)[0][0],
            detail=(
                f"{type_counts.most_common(1)[0][0]} assemblies make up "
                f"{_pct(type_counts.most_common(1)[0][1], sum(type_counts.values()))}% of the total."
            ),
            table=[{"Assembly type": k, "Count": v} for k, v in type_counts.most_common()],
            chart={"type": "donut", "labels": [k for k, _ in type_counts.most_common()],
                   "values": [v for _, v in type_counts.most_common()], "unit": ""},
            fields_used=("assembly_type",),
        ))

    # Who is actually running assemblies -> staff development and load.
    conductors = Counter(_text(obs, "conducted_by") for obs in observations if _text(obs, "conducted_by"))
    if len(conductors) >= 2:
        share = _pct(conductors.most_common(1)[0][1], sum(conductors.values()))
        out.append(Insight(
            key="assembly.conductor_spread",
            title="Who leads assemblies",
            tier=SUPPORT,
            category=CATEGORY_COMPARISON,
            severity=WATCH if share > 50 else GOOD,
            headline=f"{len(conductors)} leaders",
            detail=f"{conductors.most_common(1)[0][0]} led {share}% of assemblies.",
            action="Rotating the lead spreads both the load and the exposure." if share > 50 else "",
            value=share,
            unit="%",
            table=[{"Conducted by": k, "Assemblies": v} for k, v in conductors.most_common()],
            fields_used=("conducted_by",),
        ))

    # Participation against class size, day by day -> engagement.
    pairs = _dated_numbers(observations, "participants")
    if len(pairs) >= 3:
        ordered = sorted(pairs)
        recent = mean(v for _, v in ordered[-3:])
        overall = mean(v for _, v in ordered)
        if overall:
            delta = _pct(recent - overall, overall)
            out.append(Insight(
                key="assembly.engagement_direction",
                title="Assembly engagement direction",
                tier=DECISION,
                category=CATEGORY_TREND,
                severity=GOOD if delta >= 0 else ALERT if delta < -20 else WATCH,
                headline=f"{delta:+.1f}%",
                detail=(
                    f"Recent assemblies average {round(recent)} participants against {round(overall)} "
                    "across the whole period."
                ),
                action="Falling attendance at assemblies usually shows up in other engagement measures next."
                if delta < 0 else "",
                value=delta,
                unit="%",
                fields_used=("participants", "event_date"),
            ))

    return out


_ASSEMBLY_CATALOGUE = (
    ("assembly.flow_rating", "Rating: programme quality and flow", DECISION, CATEGORY_SYNTHESIS, ("flow_rating",)),
    ("assembly.student_performance", "Rating: student performance", SUPPORT, CATEGORY_SYNTHESIS, ("student_performance",)),
    ("assembly.values_shared", "Values covered", DECISION, CATEGORY_COMPARISON, ("values_shared",)),
    ("assembly.turnout", "Assembly turnout", SUPPORT, CATEGORY_VOLUME, ("participants", "students_expected")),
    ("assembly.theme_variety", "Themes and values covered", DECISION, CATEGORY_COMPARISON, ("theme",)),
    ("assembly.type_balance", "Balance of assembly types", SUPPORT, CATEGORY_COMPARISON, ("assembly_type",)),
    ("assembly.conductor_spread", "Who leads assemblies", SUPPORT, CATEGORY_COMPARISON, ("conducted_by",)),
    ("assembly.engagement_direction", "Assembly engagement direction", DECISION, CATEGORY_TREND, ("participants", "event_date")),
)


# --------------------------------------------------------------------------
# Stationary / inventory  (deck slide 4)
# --------------------------------------------------------------------------

def _stationary(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    out: list[Insight] = []

    def closing(obs: Observation) -> float | None:
        """Recorded closing stock, else derived from the movement."""
        recorded = _number(obs.get("closing_stock"))
        if recorded is not None:
            return recorded
        opening = _number(obs.get("opening_stock"))
        received = _number(obs.get("received")) or 0
        issued = _number(obs.get("issued")) or 0
        return None if opening is None else opening + received - issued

    status = _choices(observations, "stock_status")
    if status:
        counts = Counter(status)
        critical = counts.get("Out of stock", 0) + counts.get("Critically low", 0)
        out.append(Insight(
            key="stationary.stock_status",
            title="Stock status",
            tier=DECISION,
            category=CATEGORY_RISK,
            severity=ALERT if counts.get("Out of stock") else WATCH if critical else GOOD,
            headline=f"{critical} at risk",
            detail=(
                f"{counts.get('Out of stock', 0)} items are out of stock and "
                f"{counts.get('Critically low', 0)} are critically low, of {len(status)} tracked."
            ),
            action="An out-of-stock item stops a department. Indent these before the next cycle.",
            value=critical,
            chart=_bar(list(counts.keys()), list(counts.values()), "Items"),
            fields_used=("stock_status",),
        ))

    # Items to be indented — the deck's "Pending items" report.
    pending: list[tuple[str, str, float]] = []
    for obs in observations:
        quantity = _number(obs.get("pending_count")) or 0
        note = _text(obs, "pending_items")
        if quantity or note:
            pending.append((_text(obs, "item") or "Unspecified", note, quantity))
    if pending:
        total_pending = sum(quantity for _, _, quantity in pending)
        out.append(Insight(
            key="stationary.pending_indent",
            title="Items to be indented",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if len(pending) > 10 else WATCH,
            headline=f"{len(pending)} item{'s' if len(pending) != 1 else ''}",
            detail=f"{len(pending)} entries carry a pending indent, totalling {round(total_pending)} units.",
            action="Consolidate these into one purchase order rather than repeated small buys.",
            value=len(pending),
            table=[
                {"Item": item, "Pending": round(quantity), "Note": note[:80]}
                for item, note, quantity in sorted(pending, key=lambda row: -row[2])[:20]
            ],
            fields_used=("pending_items", "pending_count", "item"),
        ))

    # Department-wise consumption -> "Stock movement report dept. wise".
    by_department: dict[str, float] = defaultdict(float)
    for obs in observations:
        issued = _number(obs.get("issued"))
        if issued:
            by_department[_text(obs, "department") or "Unassigned"] += issued
    if by_department:
        ordered = sorted(by_department.items(), key=lambda item: -item[1])
        total_issued = sum(by_department.values())
        share = _pct(ordered[0][1], total_issued)
        out.append(Insight(
            key="stationary.department_usage",
            title="Consumption by department",
            tier=DECISION,
            category=CATEGORY_COMPARISON,
            severity=ALERT if share > 50 else WATCH if share > 35 else NEUTRAL,
            headline=ordered[0][0],
            detail=(
                f"{ordered[0][0]} took {round(ordered[0][1])} units, {share}% of the "
                f"{round(total_issued)} issued across {len(ordered)} departments."
            ),
            action="A department well above its peers is where controlled consumption saves the most.",
            value=share,
            unit="%",
            chart=_bar([name for name, _ in ordered[:8]], [value for _, value in ordered[:8]], "Units"),
            table=[{"Department": name, "Issued": round(value)} for name, value in ordered],
            fields_used=("department", "issued"),
        ))

    # Stock turnover: issued against what was available to issue.
    available = 0.0
    issued_total = 0.0
    for obs in observations:
        opening = _number(obs.get("opening_stock"))
        received = _number(obs.get("received")) or 0
        issued = _number(obs.get("issued"))
        if opening is not None and issued is not None:
            available += opening + received
            issued_total += issued
    if available:
        turnover = _pct(issued_total, available)
        out.append(Insight(
            key="stationary.turnover",
            title="Stock turnover",
            tier=DECISION,
            category=CATEGORY_VOLUME,
            severity=WATCH if turnover > 85 or turnover < 15 else GOOD,
            headline=f"{turnover}%",
            detail=(
                f"{round(issued_total)} units issued from {round(available)} available. "
                + ("Stock is turning over fast enough to risk a stock-out." if turnover > 85
                   else "Most stock is sitting unused — capital tied up on shelves." if turnover < 15
                   else "Turnover is in a healthy band.")
            ),
            action="Set reorder points from this rate rather than from the calendar.",
            value=turnover,
            unit="%",
            fields_used=("opening_stock", "received", "issued"),
        ))

    # Major expenses — the deck's principal-level "Budget planner".
    spend: dict[str, float] = defaultdict(float)
    for obs in observations:
        cost = _number(obs.get("unit_cost"))
        received = _number(obs.get("received"))
        if cost and received:
            spend[_text(obs, "item") or "Unspecified"] += cost * received
    if spend:
        ordered = sorted(spend.items(), key=lambda item: -item[1])
        total_spend = sum(spend.values())
        top_share = _pct(sum(value for _, value in ordered[:3]), total_spend)
        out.append(Insight(
            key="stationary.major_expenses",
            title="Major expenses",
            tier=DECISION,
            category=CATEGORY_SYNTHESIS,
            severity=WATCH if top_share > 60 else NEUTRAL,
            headline=f"{round(total_spend)}",
            detail=(
                f"{round(total_spend)} spent on stock received. The top three items are "
                f"{top_share}% of it: {', '.join(name for name, _ in ordered[:3])}."
            ),
            action="Negotiate on the few items that carry the spend, not across the whole catalogue.",
            value=total_spend,
            chart=_bar([name for name, _ in ordered[:8]], [value for _, value in ordered[:8]], "Cost"),
            table=[{"Item": name, "Cost": round(value)} for name, value in ordered],
            fields_used=("unit_cost", "received", "item"),
        ))

    # Items whose closing stock is falling entry over entry.
    trails: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for obs in observations:
        value = closing(obs)
        if obs.event_date and value is not None:
            trails[_text(obs, "item") or "Unspecified"].append((obs.event_date, value))
    depleting = []
    for item, points in trails.items():
        if len(points) < 3:
            continue
        ordered_points = sorted(points)
        if ordered_points[-1][1] < ordered_points[0][1]:
            drop = _pct(ordered_points[0][1] - ordered_points[-1][1], ordered_points[0][1])
            depleting.append((item, drop, ordered_points[-1][1]))
    if depleting:
        depleting.sort(key=lambda row: -row[1])
        out.append(Insight(
            key="stationary.depleting_items",
            title="Items running down",
            tier=SUPPORT,
            category=CATEGORY_TREND,
            severity=ALERT if depleting[0][1] > 70 else WATCH,
            headline=depleting[0][0],
            detail=(
                f"{len(depleting)} items show falling stock. {depleting[0][0]} is down "
                f"{depleting[0][1]}%, now at {round(depleting[0][2])} units."
            ),
            action="Reorder against this trend line, before the status flag turns critical.",
            value=depleting[0][1],
            unit="%",
            table=[
                {"Item": item, "Down %": drop, "Now": round(level)}
                for item, drop, level in depleting[:15]
            ],
            fields_used=("item", "closing_stock", "opening_stock", "received", "issued", "event_date"),
        ))

    # Receipts missing against stock received is an audit exposure.
    received_entries = [obs for obs in observations if _number(obs.get("received"))]
    if received_entries:
        missing = [obs for obs in received_entries if not _text(obs, "receipt_reference")]
        rate = _pct(len(missing), len(received_entries))
        out.append(Insight(
            key="stationary.receipt_coverage",
            title="Receipts on record",
            tier=SUPPORT,
            category=CATEGORY_RISK,
            severity=ALERT if rate > 25 else WATCH if missing else GOOD,
            headline=f"{rate}%",
            detail=f"{len(missing)} of {len(received_entries)} receipt entries have no bill reference.",
            action="Stock received without a receipt cannot be reconciled at audit.",
            value=rate,
            unit="%",
            fields_used=("received", "receipt_reference"),
        ))

    return out


_STATIONARY_CATALOGUE = (
    ("stationary.stock_status", "Stock status", DECISION, CATEGORY_RISK, ("stock_status",)),
    ("stationary.pending_indent", "Items to be indented", SUPPORT, CATEGORY_RISK, ("pending_items", "pending_count", "item")),
    ("stationary.department_usage", "Consumption by department", DECISION, CATEGORY_COMPARISON, ("department", "issued")),
    ("stationary.turnover", "Stock turnover", DECISION, CATEGORY_VOLUME, ("opening_stock", "received", "issued")),
    ("stationary.major_expenses", "Major expenses", DECISION, CATEGORY_SYNTHESIS, ("unit_cost", "received", "item")),
    ("stationary.depleting_items", "Items running down", SUPPORT, CATEGORY_TREND, ("item", "closing_stock", "event_date")),
    ("stationary.receipt_coverage", "Receipts on record", SUPPORT, CATEGORY_RISK, ("received", "receipt_reference")),
)


SPECS: dict[str, Builder] = {
    "stationary": _stationary,
    "dayboarding": _dayboarding,
    "exam_details": _exam_details,
    "field_trip": _field_trip,
    "assembly_console": _assembly,
}

_CATALOGUES: dict[str, tuple] = {
    "stationary": _STATIONARY_CATALOGUE,
    "dayboarding": _DAYBOARDING_CATALOGUE,
    "exam_details": _EXAM_CATALOGUE,
    "field_trip": _TRIP_CATALOGUE,
    "assembly_console": _ASSEMBLY_CATALOGUE,
}


def apply_spec(module: Module, observations: Sequence[Observation], today: date) -> list[Insight]:
    builder = SPECS.get(module.key)
    if builder is None:
        return []
    return builder(module, observations, today)


def spec_catalogue(module: Module) -> list[AnalysisDef]:
    return [
        AnalysisDef(key=key, title=title, tier=tier, category=category, fields_used=fields)
        for key, title, tier, category, fields in _CATALOGUES.get(module.key, ())
    ]


def suppressed_for(module_key: str) -> frozenset[str]:
    return SUPPRESSED.get(module_key, frozenset())


def tier_override_for(module_key: str, analysis_key: str) -> str | None:
    return TIER_OVERRIDES.get(module_key, {}).get(analysis_key)
