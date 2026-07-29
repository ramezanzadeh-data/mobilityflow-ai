"""
PDF rendering for the value realisation report.

The screen version is for the customer's HR lead. This one is for the
person who signs the renewal, and it will be read without anybody from
the vendor in the room. Two consequences shape the layout:

* Every estimate prints its own arithmetic on the same line. A reader who
  cannot reconstruct a figure will assume it was chosen to flatter, and
  will then discount the whole document.
* The assumptions the customer supplied are restated in full, on the
  page, attributed to them. "You told us 12 minutes" is a very different
  sentence from "industry average 12 minutes", and only the first one
  survives a procurement review.

Facts and estimates are printed in separate blocks so the reader can
trust the first group unconditionally.
"""

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# Matches the palette in apps/web/components/theme.py so a customer who
# has seen the screen recognises the document.
INK = colors.HexColor("#0f172a")
INK_MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")
ACCENT = colors.HexColor("#1d4ed8")
SURFACE_ALT = colors.HexColor("#f8fafc")


def _styles():

    base = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "ValueTitle", parent=base["Title"],
            fontSize=20, leading=24, textColor=INK, alignment=0,
        ),
        "subtitle": ParagraphStyle(
            "ValueSubtitle", parent=base["Normal"],
            fontSize=10, leading=14, textColor=INK_MUTED,
        ),
        "heading": ParagraphStyle(
            "ValueHeading", parent=base["Heading2"],
            fontSize=12, leading=16, textColor=INK, spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "ValueBody", parent=base["Normal"],
            fontSize=9, leading=13, textColor=INK,
        ),
        "note": ParagraphStyle(
            "ValueNote", parent=base["Normal"],
            fontSize=8, leading=11, textColor=INK_MUTED,
        ),
        "headline": ParagraphStyle(
            "ValueHeadline", parent=base["Normal"],
            fontSize=26, leading=30, textColor=ACCENT, alignment=TA_RIGHT,
        ),
    }


def _metric_label(key, labels):
    """Translated label, falling back to the key made readable."""

    return labels.get(key, key.replace("_", " ").capitalize())


def export_value_report_pdf(filename, report, labels=None):
    """
    Write the report to ``filename``.

    Args:
        filename: Destination path.
        report: A core.reporting.value.ValueReport.
        labels: Optional mapping of metric key to translated label, so
            the document follows the customer's language. Falls back to a
            readable form of the key rather than failing - a missing
            translation must never block a report the customer asked for.
    """

    labels = labels or {}
    style = _styles()

    document = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Value Report - {report.company}",
    )

    content = []

    # ---------------------------------------------------------- header --
    content.append(Paragraph("Value Realisation Report", style["title"]))

    period = (
        f"{report.period_start[:10]} to {report.period_end[:10]}"
        if report.period_start and report.period_end
        else "All recorded activity"
    )

    content.append(
        Paragraph(f"{report.company} &nbsp;·&nbsp; {period}", style["subtitle"])
    )
    content.append(Spacer(1, 10 * mm))

    # -------------------------------------------------------- headline --
    headline_value = f"{report.total_hours_saved:g} hours"

    if report.total_cost_saved is not None:
        headline_value += (
            f"<br/>{report.assumptions.currency} "
            f"{report.total_cost_saved:,.0f}"
        )

    content.append(
        Table(
            [[
                Paragraph(
                    "<b>Estimated specialist time returned</b><br/>"
                    "<font size=8 color='#64748b'>Calculated from activity "
                    "recorded by the system, using the rates you supplied. "
                    "Each line below shows its own calculation.</font>",
                    style["body"],
                ),
                Paragraph(headline_value, style["headline"]),
            ]],
            colWidths=[105 * mm, 69 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE_ALT),
                ("BOX", (0, 0), (-1, -1), 0.75, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]),
        )
    )
    content.append(Spacer(1, 8 * mm))

    # Estimates and facts are separated deliberately: one group is
    # arithmetic over an assumption, the other is a count of things that
    # happened. Presenting them in one table would invite a reader who
    # disputes an assumption to discount the counts as well.
    estimates = [m for m in report.metrics if m.hours_saved is not None]
    facts = [m for m in report.metrics if m.hours_saved is None]

    if estimates:
        content.append(
            Paragraph("Time saved — estimated", style["heading"])
        )
        content.append(
            Paragraph(
                "Each figure is the recorded volume multiplied by the "
                "manual-effort rate you provided.",
                style["note"],
            )
        )
        content.append(Spacer(1, 3 * mm))

        rows = [["Activity", "Volume", "Calculation", "Hours"]]

        for entry in estimates:
            rows.append([
                Paragraph(_metric_label(entry.key, labels), style["body"]),
                str(entry.count),
                Paragraph(entry.basis or "", style["note"]),
                f"{entry.hours_saved:g}",
            ])

        rows.append([
            Paragraph("<b>Total</b>", style["body"]), "", "",
            f"{report.total_hours_saved:g}",
        ])

        content.append(_table(rows, total_row=True))
        content.append(Spacer(1, 8 * mm))

    # Value against cost, only when both figures came from the customer.
    # Placed after the estimates it is derived from, so a reader meets the
    # arithmetic before the ratio rather than the other way round.
    if report.value_cost_ratio is not None:

        content.append(Paragraph("Value against cost", style["heading"]))
        content.append(
            Paragraph(
                "Both figures are yours: the rate you gave for a specialist "
                "hour, and the platform cost you stated. We have divided "
                "one by the other and nothing else - this is not a return "
                "on investment model.",
                style["note"],
            )
        )
        content.append(Spacer(1, 3 * mm))

        currency = report.assumptions.currency

        content.append(
            _table([
                ["", "", "", ""],
                [
                    Paragraph("Value created", style["body"]), "", "",
                    f"{currency} {report.total_cost_saved:,.0f}",
                ],
                [
                    Paragraph("Platform cost, this period", style["body"]),
                    "", "",
                    f"{currency} {report.platform_cost_for_period:,.0f}",
                ],
                [
                    Paragraph("<b>Net value</b>", style["body"]), "", "",
                    f"{currency} {report.net_value:,.0f}",
                ],
                [
                    Paragraph("<b>Value / cost</b>", style["body"]), "", "",
                    f"{report.value_cost_ratio:g}x",
                ],
            ], total_row=True)
        )
        content.append(Spacer(1, 8 * mm))

    # An annual figure, marked as a projection on the same line. A
    # quarterly window understates a recurring saving; extending it is
    # useful, and pretending the extension is a measurement is not.
    if report.annualised_hours_saved is not None:

        annual = f"{report.annualised_hours_saved:g} hours"

        if report.annualised_cost_saved is not None:
            annual += (
                f" / {report.assumptions.currency} "
                f"{report.annualised_cost_saved:,.0f}"
            )

        content.append(
            Paragraph(
                f"<b>Annual projection:</b> {annual}. This is the rate "
                f"observed in this period extended to twelve months, "
                f"assuming similar activity levels. It is a projection, "
                f"not a measurement.",
                style["note"],
            )
        )
        content.append(Spacer(1, 8 * mm))

    if facts:
        content.append(Paragraph("Recorded outcomes", style["heading"]))
        content.append(
            Paragraph(
                "Counts of what the system did. No monetary value is "
                "attached: what a prevented compliance failure is worth "
                "depends on the penalty avoided, which only you can put a "
                "figure on.",
                style["note"],
            )
        )
        content.append(Spacer(1, 3 * mm))

        rows = [["Outcome", "Count", "What this counts", ""]]

        for entry in facts:
            rows.append([
                Paragraph(_metric_label(entry.key, labels), style["body"]),
                str(entry.count),
                Paragraph(entry.basis or "", style["note"]),
                "",
            ])

        content.append(_table(rows))
        content.append(Spacer(1, 8 * mm))

    # ----------------------------------------------------- assumptions --
    content.append(Paragraph("Assumptions you provided", style["heading"]))
    content.append(
        Paragraph(
            "These are your figures, not ours. Change them and every "
            "estimate above changes with them.",
            style["note"],
        )
    )
    content.append(Spacer(1, 3 * mm))

    assumptions = report.assumptions
    rows = [
        ["Manual review of one document",
         f"{assumptions.minutes_per_document_review:g} min"],
        ["Identifying and requesting a missing document",
         f"{assumptions.minutes_per_document_request:g} min"],
        ["Chasing and recording one status change",
         f"{assumptions.minutes_per_case_status_update:g} min"],
    ]

    if assumptions.hourly_cost is not None:
        rows.append([
            "Fully loaded specialist hour",
            f"{assumptions.currency} {assumptions.hourly_cost:,.2f}",
        ])

    if assumptions.platform_cost_per_month is not None:
        rows.append([
            "Platform cost, as stated by you",
            f"{assumptions.currency} "
            f"{assumptions.platform_cost_per_month:,.2f} / month",
        ])

    content.append(
        Table(
            rows,
            colWidths=[130 * mm, 44 * mm],
            style=TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]),
        )
    )

    content.append(Spacer(1, 8 * mm))
    content.append(
        Paragraph(
            "Volumes are counted from the system's own audit trail. "
            "Activity whose timestamp could not be read is excluded rather "
            "than assigned to a period it may not belong to, so these "
            "figures are conservative.",
            style["note"],
        )
    )

    document.build(content)

    return filename


def _table(rows, total_row=False):

    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, LINE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    if total_row:
        style += [
            ("LINEABOVE", (0, -1), (-1, -1), 0.75, INK),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, -1), (-1, -1), INK),
        ]

    return Table(rows, colWidths=[52 * mm, 18 * mm, 84 * mm, 20 * mm],
                 style=TableStyle(style))
