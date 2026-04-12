"""
PDF Generator — One executive one-pager per target country.
Layout: header bar (with logo) | impact snapshot | top headlines (linked) | official signals | sentiment | actions

Drop your logo at:  public/medtronic_logo.png  (or .jpg / .svg)
Drop custom fonts at: public/fonts/SourceSansPro-Regular.ttf  + SourceSansPro-Bold.ttf
"""
import os
from datetime import datetime
from typing import Any
from backend.config import PDF_OUTPUT_DIR, TARGET_COUNTRIES

# ── Asset paths ────────────────────────────────────────────────────────────────
_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "public")
_FONT_DIR = os.path.join(_BASE, "fonts")

# Logo: accept .png / .jpg — drop whichever in public/
LOGO_PATH: str | None = None
for _ext in (
    "LOGO.png", "logo.png", "Logo.png",
    "medtronic_logo.png", "medtronic_logo.jpg", "medtronic_logo.jpeg",
    "logo.jpg", "logo.jpeg",
):
    _p = os.path.join(_BASE, _ext)
    if os.path.exists(_p):
        LOGO_PATH = _p
        break

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, PageBreak, KeepTogether, Image as RLImage,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("[PDF] ReportLab not installed. Run: pip install reportlab")

# ── Font registration ──────────────────────────────────────────────────────────
BODY_FONT      = "Helvetica"
BODY_FONT_BOLD = "Helvetica-Bold"

if REPORTLAB_AVAILABLE:
    _reg_path  = os.path.join(_FONT_DIR, "SourceSansPro-Regular.ttf")
    _bold_path = os.path.join(_FONT_DIR, "SourceSansPro-Bold.ttf")
    if os.path.exists(_reg_path) and os.path.exists(_bold_path):
        try:
            pdfmetrics.registerFont(TTFont("SourceSansPro",      _reg_path))
            pdfmetrics.registerFont(TTFont("SourceSansPro-Bold", _bold_path))
            BODY_FONT      = "SourceSansPro"
            BODY_FONT_BOLD = "SourceSansPro-Bold"
            print(f"[PDF] Using custom font: Source Sans Pro")
        except Exception as _e:
            print(f"[PDF] Custom font failed ({_e}), using Helvetica")

# ── Brand colours ──────────────────────────────────────────────────────────────
C_PRIMARY   = colors.HexColor("#0066CC")   # Medtronic blue
C_TEAL      = colors.HexColor("#00A38E")   # Medtronic teal accent
C_CRITICAL  = colors.HexColor("#DC2626")
C_HIGH      = colors.HexColor("#EA580C")
C_MEDIUM    = colors.HexColor("#0066CC")
C_LOW       = colors.HexColor("#6B7280")
C_TEXT      = colors.HexColor("#1F2937")
C_MUTED     = colors.HexColor("#6B7280")
C_BG        = colors.HexColor("#F8FAFC")
C_WHITE     = colors.white
C_BORDER    = colors.HexColor("#E5E7EB")
C_LINK      = colors.HexColor("#0066CC")

IMPACT_COLORS = {"critical": C_CRITICAL, "high": C_HIGH, "medium": C_MEDIUM, "low": C_LOW}
IMPACT_LABELS = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}


def build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "country_title": ParagraphStyle(
            "CountryTitle", parent=base["Title"],
            fontSize=18, textColor=C_WHITE,
            fontName=BODY_FONT_BOLD, alignment=TA_LEFT,
            spaceAfter=0, spaceBefore=0,
        ),
        "period_label": ParagraphStyle(
            "PeriodLabel", parent=base["Normal"],
            fontSize=8, textColor=colors.HexColor("#CBD5E1"),
            fontName=BODY_FONT, alignment=TA_RIGHT,
            spaceAfter=0, spaceBefore=0,
        ),
        "tier_badge": ParagraphStyle(
            "TierBadge", parent=base["Normal"],
            fontSize=7.5, textColor=C_TEAL,
            fontName=BODY_FONT_BOLD, alignment=TA_LEFT,
        ),
        "section_label": ParagraphStyle(
            "SectionLabel", parent=base["Normal"],
            fontSize=7, textColor=C_MUTED,
            fontName=BODY_FONT_BOLD,
            spaceBefore=6, spaceAfter=2,
        ),
        "headline": ParagraphStyle(
            "Headline", parent=base["Normal"],
            fontSize=8.5, textColor=C_TEXT,
            fontName=BODY_FONT_BOLD,
            spaceBefore=3, spaceAfter=1, leading=11,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontSize=8, textColor=C_TEXT,
            fontName=BODY_FONT,
            leading=11, spaceAfter=3,
        ),
        "action": ParagraphStyle(
            "Action", parent=base["Normal"],
            fontSize=7.5, textColor=C_PRIMARY,
            fontName=BODY_FONT_BOLD,
            leftIndent=8, spaceAfter=1,
        ),
        "muted": ParagraphStyle(
            "Muted", parent=base["Normal"],
            fontSize=7, textColor=C_MUTED,
            fontName=BODY_FONT,
            leading=10, spaceAfter=2,
        ),
        "link": ParagraphStyle(
            "Link", parent=base["Normal"],
            fontSize=8, textColor=C_LINK,
            fontName=BODY_FONT,
            leading=11, spaceAfter=3,
        ),
        "footer_text": ParagraphStyle(
            "Footer", parent=base["Normal"],
            fontSize=7, textColor=C_MUTED,
            fontName=BODY_FONT,
            alignment=TA_CENTER,
        ),
    }


def _draw_logo(canvas, x: float, y: float, max_w: float = 3.5*cm, max_h: float = 1.2*cm):
    """Draw the Medtronic Labs logo if available."""
    if not LOGO_PATH:
        return
    try:
        canvas.drawImage(LOGO_PATH, x, y, width=max_w, height=max_h,
                         preserveAspectRatio=True, anchor="nw", mask="auto")
    except Exception as e:
        print(f"[PDF] Logo draw failed: {e}")


def _draw_header_bar(canvas, w: float, h: float, period: str):
    """Common full-bleed header bar + teal accent strip."""
    canvas.setFillColor(C_PRIMARY)
    canvas.rect(0, h - 22*mm, w, 22*mm, fill=True, stroke=False)
    canvas.setFillColor(C_TEAL)
    canvas.rect(0, h - 24*mm, w, 2*mm, fill=True, stroke=False)


def country_page_header(canvas, doc, country: str, tier: str, period: str, page_num: int, total_pages: int):
    """Draw the full-bleed header bar and footer for a country page."""
    canvas.saveState()
    w, h = A4

    _draw_header_bar(canvas, w, h, period)

    # Logo (top-right of header)
    _draw_logo(canvas, w - 4.5*cm, h - 20*mm, max_w=3.5*cm, max_h=1.4*cm)

    # Country name
    canvas.setFillColor(C_WHITE)
    canvas.setFont(BODY_FONT_BOLD, 16)
    canvas.drawString(1.5*cm, h - 14*mm, country.upper())

    # Tier badge
    canvas.setFont(BODY_FONT, 8)
    canvas.setFillColor(colors.HexColor("#93C5FD"))
    canvas.drawString(1.5*cm, h - 20*mm, tier)

    # Brief name (center)
    canvas.setFillColor(C_WHITE)
    canvas.setFont(BODY_FONT_BOLD, 9)
    canvas.drawCentredString(w / 2, h - 12*mm, "DIGI-HEALTH BRIEF")
    canvas.setFont(BODY_FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#CBD5E1"))
    canvas.drawCentredString(w / 2, h - 18*mm, f"7-Day Snapshot  |  {period}")

    # Page number (right, above logo)
    canvas.setFillColor(C_WHITE)
    canvas.setFont(BODY_FONT, 8)
    canvas.drawRightString(w - 1.5*cm, h - 8*mm, f"Page {page_num} of {total_pages}")

    # Footer
    canvas.setFillColor(C_MUTED)
    canvas.setFont(BODY_FONT, 6.5)
    canvas.drawString(1.5*cm, 0.8*cm, "Medtronic Labs  |  Digi-Health Intelligence")
    canvas.drawRightString(w - 1.5*cm, 0.8*cm, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(1.5*cm, 1.2*cm, w - 1.5*cm, 1.2*cm)

    canvas.restoreState()


def clean(text: str, max_chars: int = 0) -> str:
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("##"):
            line = line.lstrip("#").strip()
        lines.append(line)
    result = " ".join(l for l in lines if l)
    if max_chars and len(result) > max_chars:
        result = result[:max_chars].rsplit(" ", 1)[0] + "..."
    return result


def _safe_xml(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def impact_pill_color(level: str) -> colors.Color:
    return IMPACT_COLORS.get(level, C_LOW)


def build_impact_table(dist: dict, total: int, styles: dict) -> Table:
    """4-column impact distribution row."""
    levels = ["critical", "high", "medium", "low"]
    labels = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    pill_colors = [C_CRITICAL, C_HIGH, C_MEDIUM, C_LOW]

    header_row = [Paragraph(f'<font color="white"><b>{l}</b></font>', ParagraphStyle(
        "ph", fontSize=7.5, fontName=BODY_FONT_BOLD, alignment=TA_CENTER, textColor=C_WHITE,
    )) for l in labels]

    count_row = [Paragraph(f'<b>{dist.get(lv, 0)}</b>', ParagraphStyle(
        "pc", fontSize=20, fontName=BODY_FONT_BOLD, alignment=TA_CENTER, textColor=pill_colors[i],
    )) for i, lv in enumerate(levels)]

    sub_row = [Paragraph(
        f'of {total} articles' if i == 0 else "",
        ParagraphStyle("ps", fontSize=6.5, alignment=TA_CENTER, textColor=C_MUTED)
    ) for i in range(4)]

    t = Table([header_row, count_row, sub_row], colWidths=[3.5*cm]*4)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), C_CRITICAL),
        ("BACKGROUND",    (1, 0), (1, 0), C_HIGH),
        ("BACKGROUND",    (2, 0), (2, 0), C_MEDIUM),
        ("BACKGROUND",    (3, 0), (3, 0), C_LOW),
        ("BACKGROUND",    (0, 1), (-1, -1), C_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def build_country_story(section: dict, styles: dict, w_usable: float) -> list:
    """Build the ReportLab story elements for one country page (below header)."""
    story = []
    story.append(Spacer(1, 0.3*cm))

    dist         = section.get("impact_distribution", {})
    total        = section.get("article_count", 0)
    content_text = section.get("content", "")
    top_articles = section.get("top_articles", [])
    official_sig = section.get("official_signals", [])
    sentiment    = section.get("sentiment", "neutral")
    actions      = section.get("recommended_actions", [])

    # ── Impact distribution ───────────────────────────────────────────────────
    story.append(Paragraph("IMPACT SNAPSHOT — THIS WEEK", styles["section_label"]))
    story.append(build_impact_table(dist, total, styles))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.2*cm))

    if total == 0:
        story.append(Paragraph("No digital health developments captured this week.", styles["muted"]))
        return story

    # ── Top headlines (with hyperlinks) ───────────────────────────────────────
    story.append(Paragraph("TOP HEADLINES", styles["section_label"]))

    if top_articles:
        headline_data = []
        for a in top_articles[:5]:
            level    = a.get("impact_level", "low")
            pill_col = impact_pill_color(level)
            badge    = Paragraph(
                f'<font color="white"><b> {level.upper()} </b></font>',
                ParagraphStyle("badge", fontSize=6.5, fontName=BODY_FONT_BOLD,
                               backColor=pill_col, textColor=C_WHITE,
                               borderPadding=2, alignment=TA_CENTER)
            )
            title_raw  = _safe_xml((a.get("executive_headline") or a.get("title", ""))[:110])
            src_raw    = _safe_xml(a.get("source_name", a.get("source", ""))[:30])
            official_t = " ★" if a.get("is_official") else ""
            url        = a.get("url", "")

            # Linked title when URL is available
            if url:
                title_markup = (
                    f'<a href="{url}" color="{C_LINK.hexval()}">'
                    f'<u>{title_raw}</u></a>'
                    f'<font color="#9CA3AF" size="6.5"> — {src_raw}{official_t}</font>'
                )
            else:
                title_markup = (
                    f'<b>{title_raw}</b>'
                    f'<font color="#9CA3AF" size="6.5"> — {src_raw}{official_t}</font>'
                )

            title_para = Paragraph(title_markup, styles["body"])

            action_text = a.get("recommended_action", "")
            action_para = (
                Paragraph(f'→ {_safe_xml(action_text)}', styles["action"])
                if action_text else Paragraph("", styles["muted"])
            )

            headline_data.append([badge, title_para, action_para])

        hl_table = Table(headline_data, colWidths=[1.5*cm, 9.5*cm, 5.5*cm])
        hl_table.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [C_WHITE, C_BG]),
            ("LINEBELOW",     (0, 0), (-1, -2), 0.3, C_BORDER),
        ]))
        story.append(hl_table)
    else:
        # Fall back to AI-generated text
        for line in content_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if any(line.startswith(x) for x in ["TOP HEADLINES", "OFFICIAL", "SOCIAL", "RECOMMENDED"]):
                story.append(Spacer(1, 0.15*cm))
                story.append(Paragraph(line, styles["section_label"]))
            elif line.startswith("→"):
                story.append(Paragraph(line, styles["action"]))
            elif line.startswith(("•", "-", "*")):
                story.append(Paragraph(f"• {line.lstrip('•-* ').strip()}", styles["body"]))
            elif line[:1].isdigit() and line[1:3] in (". ", ") "):
                story.append(Paragraph(line, styles["body"]))
            else:
                story.append(Paragraph(line, styles["body"]))
        return story

    story.append(Spacer(1, 0.2*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.15*cm))

    # ── Bottom two-column: Official signals | Sentiment + Actions ─────────────
    half = (w_usable - 0.4*cm) / 2

    # Left: official signals (with links where available)
    left_els = [Paragraph("OFFICIAL SIGNALS & PRONOUNCEMENTS", styles["section_label"])]
    if official_sig:
        for sig in official_sig[:3]:
            left_els.append(Paragraph(f"★  {_safe_xml(clean(sig, 90))}", styles["body"]))
    else:
        in_official = False
        for line in content_text.split("\n"):
            line = line.strip()
            if "OFFICIAL SIGNALS" in line.upper():
                in_official = True
                continue
            if in_official:
                if any(x in line.upper() for x in ["SOCIAL SENTIMENT", "RECOMMENDED"]):
                    break
                if line:
                    left_els.append(Paragraph(f"• {_safe_xml(line.lstrip('•-* ').strip())}", styles["body"]))
        if len(left_els) == 1:
            left_els.append(Paragraph("No official signals this week.", styles["muted"]))

    # Right: sentiment + recommended actions
    right_els = [Paragraph("SOCIAL SENTIMENT", styles["section_label"])]
    sent_color = {"positive": C_TEAL, "negative": C_CRITICAL, "mixed": C_HIGH}.get(sentiment, C_MUTED)
    right_els.append(Paragraph(
        f'<font color="{sent_color.hexval() if hasattr(sent_color, "hexval") else "#6B7280"}"><b>{sentiment.upper()}</b></font>',
        ParagraphStyle("sent", fontSize=9, fontName=BODY_FONT_BOLD)
    ))
    in_sent = False
    for line in content_text.split("\n"):
        line = line.strip()
        if "SOCIAL SENTIMENT" in line.upper():
            in_sent = True
            continue
        if in_sent:
            if "RECOMMENDED" in line.upper():
                break
            if line and not line.upper().startswith("SOCIAL"):
                right_els.append(Paragraph(_safe_xml(line.lstrip("•-* ").strip()), styles["body"]))

    right_els.append(Spacer(1, 0.1*cm))
    right_els.append(Paragraph("RECOMMENDED ACTIONS", styles["section_label"]))
    if actions:
        for i, act in enumerate(actions[:2], 1):
            right_els.append(Paragraph(f"{i}.  {_safe_xml(act)}", styles["action"]))
    else:
        in_actions = False
        for line in content_text.split("\n"):
            line = line.strip()
            if "RECOMMENDED" in line.upper():
                in_actions = True
                continue
            if in_actions and line:
                right_els.append(Paragraph(_safe_xml(line.lstrip("123. ").strip()), styles["action"]))

    bottom_table = Table([[left_els, right_els]], colWidths=[half, half])
    bottom_table.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (0, -1),  10),
        ("LINEAFTER",   (0, 0), (0, -1),  0.5, C_BORDER),
    ]))
    story.append(bottom_table)
    return story


async def generate_pdf(report: dict[str, Any], run_id: str) -> str:
    """Generate the one-pager-per-country PDF. Returns file path."""
    if not REPORTLAB_AVAILABLE:
        fallback_path = os.path.join(PDF_OUTPUT_DIR, f"report_{run_id[:8]}.txt")
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(f"DIGI-HEALTH BRIEF\n{report.get('title', '')}\n\n")
            f.write(f"EXECUTIVE OVERVIEW\n{report.get('executive_summary', '')}\n\n")
            for section in report.get("sections", []):
                f.write(f"\n{'='*60}\n{section.get('country','').upper()}\n{'='*60}\n")
                f.write(f"{section.get('content', '')}\n")
            f.write(f"\nSTRATEGIC OUTLOOK\n{report.get('strategic_analysis', '')}\n")
        return fallback_path

    filename  = f"digihealth_{datetime.utcnow().strftime('%Y%m%d')}_{run_id[:8]}.pdf"
    pdf_path  = os.path.join(PDF_OUTPUT_DIR, filename)
    styles    = build_styles()
    sections  = report.get("sections", [])
    period    = report.get("period", report.get("date", ""))
    date_str  = report.get("date", datetime.utcnow().strftime("%B %d, %Y"))
    total_pgs = 1 + len(sections) + 1   # cover + country pages + outlook

    story = []

    # ── COVER PAGE ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 2.5*cm))

    # Logo on cover (if available)
    if LOGO_PATH:
        try:
            logo_img = RLImage(LOGO_PATH, width=5*cm, height=2*cm)
            logo_img.hAlign = "CENTER"
            story.append(logo_img)
            story.append(Spacer(1, 0.6*cm))
        except Exception as e:
            print(f"[PDF] Cover logo failed: {e}")

    story.append(Paragraph(
        "DIGI-HEALTH BRIEF",
        ParagraphStyle("ct", fontSize=22, fontName=BODY_FONT_BOLD,
                       textColor=C_PRIMARY, alignment=TA_CENTER, spaceAfter=8)
    ))
    story.append(Paragraph(
        "Medtronic Labs  |  Digital Health Intelligence Unit",
        ParagraphStyle("org", fontSize=10, fontName=BODY_FONT,
                       textColor=C_TEAL, alignment=TA_CENTER, spaceAfter=4)
    ))
    story.append(Paragraph(
        f"7-Day Country Snapshots  |  {period}",
        ParagraphStyle("cs", fontSize=11, fontName=BODY_FONT,
                       textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=4)
    ))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=C_TEAL))
    story.append(Spacer(1, 0.8*cm))

    # Summary stats
    stats = report.get("stats", {})
    stat_data = [
        ["Articles Analysed", "Countries Active", "Critical Items", "High Items"],
        [
            str(stats.get("total_articles", 0)),
            str(stats.get("countries_active", 0)),
            str(stats.get("critical", 0)),
            str(stats.get("high", 0)),
        ],
    ]
    stat_t = Table(stat_data, colWidths=[4*cm]*4)
    stat_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), BODY_FONT_BOLD),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND",    (0, 1), (-1, 1), C_BG),
        ("FONTSIZE",      (0, 1), (-1, 1), 18),
        ("FONTNAME",      (0, 1), (-1, 1), BODY_FONT_BOLD),
        ("TEXTCOLOR",     (0, 1), (-1, 1), C_PRIMARY),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(stat_t)
    story.append(Spacer(1, 0.8*cm))

    # Country index
    story.append(Paragraph("COUNTRIES IN THIS BRIEF", ParagraphStyle(
        "ci", fontSize=9, fontName=BODY_FONT_BOLD, textColor=C_PRIMARY,
        spaceAfter=6, spaceBefore=8,
    )))
    for i, section in enumerate(sections, 2):
        country = section.get("country", "")
        tier    = section.get("tier", "")
        cnt     = section.get("article_count", 0)
        dist    = section.get("impact_distribution", {})
        crit    = dist.get("critical", 0)
        high    = dist.get("high", 0)
        flags   = []
        if crit: flags.append(f'{crit} CRITICAL')
        if high: flags.append(f'{high} HIGH')
        flag_str = "  |  " + "  ".join(flags) if flags else ""
        story.append(Paragraph(
            f'<b>{_safe_xml(country)}</b>  '
            f'<font color="#9CA3AF">— {_safe_xml(tier)}  |  {cnt} articles{_safe_xml(flag_str)}  |  Page {i}</font>',
            ParagraphStyle("cil", fontSize=8.5, fontName=BODY_FONT, spaceAfter=3, leading=12)
        ))

    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph("Executive Overview", ParagraphStyle(
        "eoh", fontSize=10, fontName=BODY_FONT_BOLD, textColor=C_PRIMARY, spaceAfter=4
    )))
    for line in (report.get("executive_summary", "") or "").split("\n"):
        line = line.strip()
        if line:
            story.append(Paragraph(_safe_xml(line), ParagraphStyle(
                "eo", fontSize=8.5, fontName=BODY_FONT, leading=13, textColor=C_TEXT, spaceAfter=3
            )))

    # ── COUNTRY PAGES ─────────────────────────────────────────────────────────
    w_usable = A4[0] - 3*cm   # left + right margins = 1.5cm each

    for section in sections:
        story.append(PageBreak())
        story.append(Spacer(1, 0.5*cm))
        story.extend(build_country_story(section, styles, w_usable))

    # ── STRATEGIC OUTLOOK ─────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("STRATEGIC OUTLOOK", ParagraphStyle(
        "sol", fontSize=13, fontName=BODY_FONT_BOLD, textColor=C_PRIMARY, spaceAfter=6
    )))
    story.append(HRFlowable(width="100%", thickness=1, color=C_TEAL))
    story.append(Spacer(1, 0.2*cm))
    for line in (report.get("strategic_analysis", "") or "").split("\n"):
        line = line.strip()
        if line:
            story.append(Paragraph(_safe_xml(line), ParagraphStyle(
                "sa", fontSize=9, fontName=BODY_FONT, leading=13, textColor=C_TEXT, spaceAfter=4
            )))

    # ── on_page callback ──────────────────────────────────────────────────────
    def on_page(canvas, doc):
        canvas.saveState()
        pg = doc.page
        w, h = A4

        if pg == 1:
            # Cover page header
            _draw_header_bar(canvas, w, h, period)
            _draw_logo(canvas, w - 4.5*cm, h - 21*mm, max_w=3.5*cm, max_h=1.5*cm)
            canvas.setFillColor(C_WHITE)
            canvas.setFont(BODY_FONT_BOLD, 10)
            canvas.drawCentredString(w / 2, h - 13*mm, "DIGI-HEALTH BRIEF")
            canvas.setFont(BODY_FONT, 8)
            canvas.setFillColor(colors.HexColor("#CBD5E1"))
            canvas.drawCentredString(w / 2, h - 19*mm, f"7-Day Snapshot  |  {period}")

        elif 2 <= pg <= len(sections) + 1:
            sec = sections[pg - 2]
            country_page_header(
                canvas, doc,
                country=sec.get("country", ""),
                tier=sec.get("tier", ""),
                period=period,
                page_num=pg,
                total_pages=total_pgs,
            )
        else:
            # Strategic outlook page
            _draw_header_bar(canvas, w, h, period)
            _draw_logo(canvas, w - 4.5*cm, h - 21*mm, max_w=3.5*cm, max_h=1.5*cm)
            canvas.setFillColor(C_WHITE)
            canvas.setFont(BODY_FONT_BOLD, 10)
            canvas.drawCentredString(w / 2, h - 13*mm, "STRATEGIC OUTLOOK")
            canvas.setFont(BODY_FONT, 8)
            canvas.setFillColor(colors.HexColor("#CBD5E1"))
            canvas.drawCentredString(w / 2, h - 19*mm, f"{period}  |  Page {pg} of {total_pgs}")

        # Footer (all pages)
        canvas.setFillColor(C_MUTED)
        canvas.setFont(BODY_FONT, 6.5)
        canvas.drawString(1.5*cm, 0.8*cm, "Medtronic Labs  |  Digi-Health Intelligence")
        canvas.drawRightString(w - 1.5*cm, 0.8*cm, f"Generated {datetime.utcnow().strftime('%Y-%m-%d')}")
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(1.5*cm, 1.2*cm, w - 1.5*cm, 1.2*cm)

        canvas.restoreState()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        topMargin=3*cm,
        bottomMargin=2*cm,
        leftMargin=1.5*cm,
        rightMargin=1.5*cm,
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"[PDF] Generated: {pdf_path} (logo: {'yes' if LOGO_PATH else 'no'}, font: {BODY_FONT})")
    return pdf_path
