from __future__ import annotations

from django import template

from ..analytics.charts import render_chart

register = template.Library()


@register.simple_tag
def chart(spec) -> str:
    """Render an insight's chart spec as inline SVG.

    Returns empty markup when the spec is missing or malformed, so a template
    never has to guard the call.
    """
    return render_chart(spec)


@register.filter
def accessible_field(bound_field):
    """Render a form widget with the ARIA wiring its label and errors imply.

    Required state and error text were previously conveyed only visually, so
    screen readers got no signal at all. Applied centrally here rather than in
    each form's widget attrs so every form gets it.
    """
    attrs = {}
    if bound_field.field.required:
        attrs["aria-required"] = "true"
    described_by = []
    if bound_field.help_text:
        described_by.append(f"{bound_field.id_for_label}-help")
    if bound_field.errors:
        attrs["aria-invalid"] = "true"
        described_by.append(f"{bound_field.id_for_label}-error")
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)
    return bound_field.as_widget(attrs=attrs)
