"""Minimal dependency-free PDF writer for report export.

Deliberately not reportlab or weasyprint: this app deploys to a Vercel
serverless bundle where every megabyte of dependency is startup latency, and
both of those pull in native extensions. What a report needs is headings,
paragraphs, key-value stats and simple tables, all in the 14 standard PDF fonts
that every reader has built in. That is a few hundred lines of stream writing.

Layout is fixed A4 portrait. Text is wrapped by an approximate width table for
Helvetica; the approximation is generous, so lines wrap early rather than
overflowing the margin.
"""

from __future__ import annotations

import zlib
from typing import Iterable, Sequence

PAGE_WIDTH = 595.28  # A4 at 72 dpi
PAGE_HEIGHT = 841.89
MARGIN = 48.0
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

FONT_REGULAR = "F1"  # Helvetica
FONT_BOLD = "F2"  # Helvetica-Bold

# Average glyph width as a fraction of font size, per character class. Coarse
# but consistently over-estimates, which is the safe direction for wrapping.
_WIDE = set("MWmw@%&")
_NARROW = set("iljItf.,;:'\"|!()[]{} ")


def _text_width(text: str, size: float) -> float:
    total = 0.0
    for char in text:
        if char in _WIDE:
            total += 0.86
        elif char in _NARROW:
            total += 0.32
        elif char.isupper() or char.isdigit():
            total += 0.62
        else:
            total += 0.52
    return total * size


def _wrap(text: str, size: float, width: float) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(candidate, size) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _escape(text: str) -> str:
    out = []
    for char in str(text):
        if char in ("\\", "(", ")"):
            out.append("\\" + char)
        elif ord(char) < 32:
            out.append(" ")
        elif ord(char) < 128:
            out.append(char)
        else:
            # WinAnsi has no glyph for most of this; substitute rather than
            # emit a byte the reader will render as a box.
            out.append(_TRANSLITERATE.get(char, "?"))
    return "".join(out)


_TRANSLITERATE = {
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", " ": " ",
    "→": "->", "σ": "sigma", "≥": ">=", "≤": "<=",
}


class PdfBuilder:
    """Accumulates content streams, one per page, then serialises the file."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.pages: list[list[str]] = []
        self.stream: list[str] = []
        self.y = PAGE_HEIGHT - MARGIN
        self._new_page()

    # -- page management ---------------------------------------------------

    def _new_page(self) -> None:
        if self.stream:
            self.pages.append(self.stream)
        self.stream = []
        self.y = PAGE_HEIGHT - MARGIN

    def _ensure(self, needed: float) -> None:
        if self.y - needed < MARGIN + 24:
            self._new_page()

    # -- drawing primitives ------------------------------------------------

    def _draw(self, text: str, x: float, size: float, font: str, grey: float = 0.0) -> None:
        self.stream.append(
            f"BT /{font} {size:.1f} Tf {grey:.2f} {grey:.2f} {grey:.2f} rg "
            f"1 0 0 1 {x:.1f} {self.y:.1f} Tm ({_escape(text)}) Tj ET"
        )

    def rule(self, grey: float = 0.78) -> None:
        self._ensure(12)
        self.y -= 6
        self.stream.append(
            f"{grey:.2f} {grey:.2f} {grey:.2f} RG 0.6 w "
            f"{MARGIN:.1f} {self.y:.1f} m {PAGE_WIDTH - MARGIN:.1f} {self.y:.1f} l S"
        )
        self.y -= 10

    def space(self, amount: float = 10) -> None:
        self.y -= amount

    def title_block(self, heading: str, subtitle: str = "") -> None:
        self._ensure(70)
        self.y -= 18
        self._draw(heading, MARGIN, 20, FONT_BOLD)
        self.y -= 20
        if subtitle:
            self._draw(subtitle, MARGIN, 10, FONT_REGULAR, grey=0.42)
            self.y -= 16
        self.rule(0.55)

    def heading(self, text: str, size: float = 13) -> None:
        self._ensure(size + 22)
        self.y -= 14
        self._draw(text, MARGIN, size, FONT_BOLD)
        self.y -= size + 4

    def paragraph(self, text: str, size: float = 9.5, grey: float = 0.18, indent: float = 0.0) -> None:
        if not text:
            return
        for line in _wrap(text, size, CONTENT_WIDTH - indent):
            self._ensure(size + 4)
            self._draw(line, MARGIN + indent, size, FONT_REGULAR, grey=grey)
            self.y -= size + 3.5

    def label_value(self, label: str, value: str) -> None:
        self._ensure(18)
        self._draw(label, MARGIN, 9, FONT_REGULAR, grey=0.45)
        width = _text_width(label, 9)
        self._draw(str(value), MARGIN + max(width + 10, 150), 10, FONT_BOLD)
        self.y -= 15

    def badge_line(self, severity: str, title: str, headline: str) -> None:
        self._ensure(20)
        colour = {
            "alert": (0.78, 0.16, 0.16),
            "watch": (0.80, 0.52, 0.06),
            "good": (0.11, 0.51, 0.30),
        }.get(severity, (0.45, 0.45, 0.45))
        self.stream.append(
            f"{colour[0]:.2f} {colour[1]:.2f} {colour[2]:.2f} rg "
            f"{MARGIN:.1f} {self.y - 1:.1f} 4 10 re f"
        )
        self._draw(title, MARGIN + 12, 10.5, FONT_BOLD)
        headline_x = PAGE_WIDTH - MARGIN - _text_width(str(headline), 10.5)
        self.stream.append(
            f"BT /{FONT_BOLD} 10.5 Tf {colour[0]:.2f} {colour[1]:.2f} {colour[2]:.2f} rg "
            f"1 0 0 1 {headline_x:.1f} {self.y:.1f} Tm ({_escape(str(headline))}) Tj ET"
        )
        self.y -= 15

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[object]], max_rows: int = 25) -> None:
        if not headers:
            return
        column_width = CONTENT_WIDTH / len(headers)
        self._ensure(34)
        self.stream.append(
            f"0.93 0.94 0.96 rg {MARGIN:.1f} {self.y - 4:.1f} {CONTENT_WIDTH:.1f} 16 re f"
        )
        for index, header in enumerate(headers):
            self._draw(_clip(str(header), 8.5, column_width - 8), MARGIN + 4 + index * column_width, 8.5, FONT_BOLD)
        self.y -= 18

        for row in list(rows)[:max_rows]:
            self._ensure(16)
            for index, cell in enumerate(row):
                self._draw(
                    _clip(str(cell), 8.5, column_width - 8),
                    MARGIN + 4 + index * column_width,
                    8.5,
                    FONT_REGULAR,
                    grey=0.2,
                )
            self.y -= 13
        if len(rows) > max_rows:
            self.paragraph(f"... and {len(rows) - max_rows} further rows (see the spreadsheet export).",
                           size=8, grey=0.5)
        self.space(6)

    # -- serialisation -----------------------------------------------------

    def build(self) -> bytes:
        if self.stream:
            self.pages.append(self.stream)
        if not self.pages:
            self.pages.append([])

        page_count = len(self.pages)
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)  # object numbers are 1-based

        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

        # Reserve the Pages object number so page objects can reference it.
        pages_number = len(objects) + 1
        objects.append(b"")  # placeholder, filled once page numbers are known

        page_numbers: list[int] = []
        for index, stream in enumerate(self.pages, 1):
            footer = (
                f"BT /{FONT_REGULAR} 8 Tf 0.55 0.55 0.55 rg 1 0 0 1 {MARGIN:.1f} {MARGIN - 14:.1f} Tm "
                f"({_escape(self.title)}  -  page {index} of {page_count}) Tj ET"
            )
            content = "\n".join(stream + [footer]).encode("latin-1", "replace")
            compressed = zlib.compress(content)
            content_number = add(
                b"<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>\nstream\n"
                + compressed
                + b"\nendstream"
            )
            page_number = add(
                f"<< /Type /Page /Parent {pages_number} 0 R "
                f"/MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
                f"/Resources << /Font << /{FONT_REGULAR} {font_regular} 0 R "
                f"/{FONT_BOLD} {font_bold} 0 R >> >> "
                f"/Contents {content_number} 0 R >>".encode("latin-1")
            )
            page_numbers.append(page_number)

        kids = " ".join(f"{number} 0 R" for number in page_numbers)
        objects[pages_number - 1] = (
            f"<< /Type /Pages /Count {page_count} /Kids [{kids}] >>".encode("latin-1")
        )

        catalog_number = add(f"<< /Type /Catalog /Pages {pages_number} 0 R >>".encode("latin-1"))
        info_number = add(
            b"<< /Title (" + _escape(self.title).encode("latin-1", "replace")
            + b") /Producer (TVS Activity Desk) >>"
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

        xref_offset = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode("latin-1")
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_number} 0 R "
            f"/Info {info_number} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(out)


def _clip(text: str, size: float, width: float) -> str:
    if _text_width(text, size) <= width:
        return text
    while text and _text_width(text + "...", size) > width:
        text = text[:-1]
    return text + "..."


def render_report_pdf(report, school_name: str, generated_at: str, role_label: str) -> bytes:
    """Render a ``Report`` into a PDF. Same insight objects the screen uses."""
    pdf = PdfBuilder(f"{school_name} - {report.module_name}")
    pdf.title_block(
        report.module_name,
        f"{school_name}  |  {role_label} view  |  {report.period_label}  |  generated {generated_at}",
    )

    pdf.heading("At a glance")
    pdf.label_value("Records analysed", str(report.record_count))
    pdf.label_value("Access tier", report.tier.title())
    for insight in report.headline_stats:
        pdf.label_value(insight.title, insight.display)

    alerts = report.alerts
    if alerts:
        pdf.heading("Red flags")
        for insight in alerts:
            pdf.badge_line(insight.severity, insight.title, insight.headline)
            pdf.paragraph(insight.detail, indent=12)
            if insight.action:
                pdf.paragraph(f"Action: {insight.action}", grey=0.4, indent=12)
            pdf.space(4)

    if report.swot:
        pdf.heading("SWOT")
        for quadrant in report.swot:
            pdf.paragraph(quadrant.label, size=10.5, grey=0.0)
            for point in quadrant.points:
                pdf.paragraph(f"- {point}", size=9, grey=0.25, indent=12)
            pdf.space(4)

    for category, insights in report.by_category():
        pdf.heading(category)
        for insight in insights:
            pdf.badge_line(insight.severity, insight.title, insight.display)
            pdf.paragraph(insight.detail, indent=12)
            if insight.action:
                pdf.paragraph(f"Action: {insight.action}", grey=0.42, indent=12)
            if insight.table:
                headers = list(insight.table[0].keys())
                rows = [[row.get(header, "") for header in headers] for row in insight.table]
                pdf.table(headers, rows, max_rows=12)
            pdf.space(5)

    return pdf.build()
