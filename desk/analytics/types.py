from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

ENTRY = "entry"
SUPPORT = "support"
DECISION = "decision"

TIER_ORDER = (ENTRY, SUPPORT, DECISION)

TIER_LABELS = {
    ENTRY: "Entry",
    SUPPORT: "Support",
    DECISION: "Decision",
}

GOOD = "good"
NEUTRAL = "neutral"
WATCH = "watch"
ALERT = "alert"

SEVERITY_ORDER = {ALERT: 0, WATCH: 1, GOOD: 2, NEUTRAL: 3}


@dataclass(frozen=True)
class Observation:
    """One decrypted submission, flattened for analysis."""

    record_id: str
    module_key: str
    owner_id: str
    owner_name: str
    status: str
    event_date: date | None
    created_at: Any
    values: dict[str, Any]

    def get(self, key: str) -> Any:
        return self.values.get(key)


@dataclass
class Insight:
    """A single analysis result, ready to render."""

    key: str
    title: str
    tier: str
    category: str
    severity: str = NEUTRAL
    headline: str = ""
    detail: str = ""
    action: str = ""
    value: Any = None
    unit: str = ""
    table: list[dict[str, Any]] = field(default_factory=list)
    chart: dict[str, Any] | None = None
    fields_used: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        """Headline with its unit, without repeating a unit the headline already carries."""
        headline = str(self.headline)
        if not self.unit or self.unit in headline:
            return headline
        return f"{headline} {self.unit}"

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 9)

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier.title())


@dataclass(frozen=True)
class AnalysisDef:
    """A catalogue entry: an analysis this module is capable of producing."""

    key: str
    title: str
    tier: str
    category: str
    fields_used: tuple[str, ...] = ()
    description: str = ""


@dataclass
class SwotQuadrant:
    label: str
    slug: str
    points: list[str] = field(default_factory=list)


@dataclass
class Report:
    module_key: str
    module_name: str
    tier: str
    role: str
    period_label: str
    record_count: int
    insights: list[Insight] = field(default_factory=list)
    swot: list[SwotQuadrant] = field(default_factory=list)
    headline_stats: list[Insight] = field(default_factory=list)

    def by_category(self) -> list[tuple[str, list[Insight]]]:
        grouped: dict[str, list[Insight]] = {}
        for insight in self.insights:
            grouped.setdefault(insight.category, []).append(insight)
        return sorted(grouped.items(), key=lambda item: CATEGORY_ORDER.index(item[0])
                      if item[0] in CATEGORY_ORDER else 99)

    @property
    def alerts(self) -> list[Insight]:
        return [i for i in self.insights if i.severity == ALERT]


CATEGORY_VOLUME = "Volume & coverage"
CATEGORY_TREND = "Trends over time"
CATEGORY_DISTRIBUTION = "Distribution & mix"
CATEGORY_OUTLIER = "Outliers & anomalies"
CATEGORY_COMPARISON = "Comparisons"
CATEGORY_QUALITY = "Data quality"
CATEGORY_TEXT = "Issues & themes"
CATEGORY_RISK = "Risk & red flags"
CATEGORY_SYNTHESIS = "Synthesis"

CATEGORY_ORDER = (
    CATEGORY_RISK,
    CATEGORY_SYNTHESIS,
    CATEGORY_VOLUME,
    CATEGORY_TREND,
    CATEGORY_COMPARISON,
    CATEGORY_DISTRIBUTION,
    CATEGORY_OUTLIER,
    CATEGORY_TEXT,
    CATEGORY_QUALITY,
)


def sort_insights(insights: Sequence[Insight]) -> list[Insight]:
    return sorted(insights, key=lambda i: (i.severity_rank, i.title))
