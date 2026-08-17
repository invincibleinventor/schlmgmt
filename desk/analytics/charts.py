"""Server-rendered inline SVG charts.

The app's CSP is ``script-src 'self'; style-src 'self'``, so no CDN chart
library will load and no ``style=`` attribute will apply. Everything here emits
plain SVG whose appearance comes from classes in ``static/desk/app.css``.
Geometry attributes (x, y, width, height, points) are presentation-neutral and
are set directly, which CSP permits.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from django.utils.html import escape
from django.utils.safestring import mark_safe

PALETTE_SIZE = 6  # matches .chart-series-0 .. .chart-series-5 in app.css


def render_chart(chart: dict[str, Any] | None) -> str:
    if not chart:
        return ""
    kind = chart.get("type")
    labels = [str(label) for label in chart.get("labels", [])]
    values = [float(value) for value in chart.get("values", [])]
    unit = str(chart.get("unit", ""))
    if not labels or not values or len(labels) != len(values):
        return ""
    if kind == "bar":
        return _bar(labels, values, unit)
    if kind == "line":
        return _line(labels, values, unit)
    if kind == "donut":
        return _donut(labels, values)
    return ""


def _fmt(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _bar(labels: Sequence[str], values: Sequence[float], unit: str) -> str:
    width, height = 640, 260
    left, right, top, bottom = 48, 16, 20, 56
    plot_width = width - left - right
    plot_height = height - top - bottom
    peak = max(values + [0])
    floor = min(values + [0])
    span = (peak - floor) or 1
    slot = plot_width / len(values)
    bar_width = max(6.0, slot * 0.62)

    parts = [
        f'<svg class="chart chart-bar" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Bar chart of {escape(unit or "values")}" preserveAspectRatio="xMidYMid meet">'
    ]
    zero_y = top + plot_height * (peak / span if peak > 0 else 0)
    parts.append(f'<line class="chart-axis" x1="{left}" y1="{zero_y:.1f}" x2="{width - right}" y2="{zero_y:.1f}" />')

    for index, (label, value) in enumerate(zip(labels, values)):
        magnitude = abs(value) / span * plot_height
        x = left + slot * index + (slot - bar_width) / 2
        y = zero_y - magnitude if value >= 0 else zero_y
        parts.append(
            f'<rect class="chart-bar-rect chart-series-{index % PALETTE_SIZE}" '
            f'x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{max(magnitude, 1):.1f}" '
            f'rx="3"><title>{escape(label)}: {_fmt(value)} {escape(unit)}</title></rect>'
        )
        parts.append(
            f'<text class="chart-value" x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" '
            f'text-anchor="middle">{_fmt(value)}</text>'
        )
        parts.append(
            f'<text class="chart-label" x="{x + bar_width / 2:.1f}" y="{height - bottom + 18:.1f}" '
            f'text-anchor="middle">{escape(_truncate(label))}</text>'
        )

    parts.append("</svg>")
    return mark_safe("".join(parts))


def _line(labels: Sequence[str], values: Sequence[float], unit: str) -> str:
    width, height = 640, 260
    left, right, top, bottom = 48, 16, 20, 56
    plot_width = width - left - right
    plot_height = height - top - bottom
    peak, floor = max(values), min(values)
    span = (peak - floor) or 1
    step = plot_width / max(len(values) - 1, 1)

    points = []
    for index, value in enumerate(values):
        x = left + step * index
        y = top + plot_height * (1 - (value - floor) / span)
        points.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{left:.1f},{top + plot_height:.1f} " + polyline + f" {points[-1][0]:.1f},{top + plot_height:.1f}"

    parts = [
        f'<svg class="chart chart-line" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Line chart of {escape(unit or "values")}" preserveAspectRatio="xMidYMid meet">',
        f'<polygon class="chart-area" points="{area}" />',
        f'<polyline class="chart-line-path" points="{polyline}" />',
    ]

    label_every = max(1, len(labels) // 8)
    for index, ((x, y), label, value) in enumerate(zip(points, labels, values)):
        parts.append(
            f'<circle class="chart-point" cx="{x:.1f}" cy="{y:.1f}" r="3.5">'
            f'<title>{escape(label)}: {_fmt(value)} {escape(unit)}</title></circle>'
        )
        if index % label_every == 0 or index == len(points) - 1:
            parts.append(
                f'<text class="chart-label" x="{x:.1f}" y="{height - bottom + 18:.1f}" '
                f'text-anchor="middle">{escape(_truncate(label, 10))}</text>'
            )

    parts.append(
        f'<text class="chart-axis-value" x="{left - 8}" y="{top + 6}" text-anchor="end">{_fmt(peak)}</text>'
    )
    parts.append(
        f'<text class="chart-axis-value" x="{left - 8}" y="{top + plot_height}" '
        f'text-anchor="end">{_fmt(floor)}</text>'
    )
    parts.append("</svg>")
    return mark_safe("".join(parts))


def _donut(labels: Sequence[str], values: Sequence[float]) -> str:
    total = sum(values)
    if total <= 0:
        return ""
    size = 240
    centre = size / 2
    outer, inner = 96, 58

    parts = [
        f'<svg class="chart chart-donut" viewBox="0 0 {size + 260} {size}" role="img" '
        f'aria-label="Share breakdown" preserveAspectRatio="xMidYMid meet">'
    ]
    angle = -math.pi / 2
    for index, (label, value) in enumerate(zip(labels, values)):
        sweep = value / total * 2 * math.pi
        end = angle + sweep
        large_arc = 1 if sweep > math.pi else 0
        x1, y1 = centre + outer * math.cos(angle), centre + outer * math.sin(angle)
        x2, y2 = centre + outer * math.cos(end), centre + outer * math.sin(end)
        x3, y3 = centre + inner * math.cos(end), centre + inner * math.sin(end)
        x4, y4 = centre + inner * math.cos(angle), centre + inner * math.sin(angle)
        path = (
            f"M {x1:.1f} {y1:.1f} A {outer} {outer} 0 {large_arc} 1 {x2:.1f} {y2:.1f} "
            f"L {x3:.1f} {y3:.1f} A {inner} {inner} 0 {large_arc} 0 {x4:.1f} {y4:.1f} Z"
        )
        share = value / total * 100
        parts.append(
            f'<path class="chart-slice chart-series-{index % PALETTE_SIZE}" d="{path}">'
            f'<title>{escape(label)}: {_fmt(value)} ({share:.1f}%)</title></path>'
        )

        legend_y = 28 + index * 26
        parts.append(
            f'<rect class="chart-legend-swatch chart-series-{index % PALETTE_SIZE}" '
            f'x="{size + 12}" y="{legend_y - 10}" width="12" height="12" rx="3" />'
        )
        parts.append(
            f'<text class="chart-legend-text" x="{size + 32}" y="{legend_y}">'
            f'{escape(_truncate(label, 22))} — {share:.1f}%</text>'
        )
        angle = end

    parts.append("</svg>")
    return mark_safe("".join(parts))


def _truncate(text: str, limit: int = 14) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
