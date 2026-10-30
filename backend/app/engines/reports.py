import csv
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LABELS = {
    "organic_traffic": "Organic traffic", "paid_traffic": "Paid clicks", "seo_score": "SEO score", "geo_visibility": "GEO visibility",
    "impressions": "Ad impressions", "engagement": "Instagram engagement", "spend": "Ad spend", "ctr": "CTR", "cpc": "CPC",
    "cpl": "CPL", "cpa": "CPA", "roas": "ROAS", "conversions": "Conversions",
}


def fmt(v, unit: str, currency: str) -> str:
    if v is None:
        return "—"
    if unit == "money":
        return f"{currency} {v / 100:,.2f}"
    if unit == "ratio":
        return f"{v:.2%}" if v < 1.5 else f"{v:.2f}x"
    return f"{v:,}"


def to_csv(overview: dict, series: dict, channels: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    cur = overview["currency"]
    w.writerow(["Report period", overview["range"]["start"], overview["range"]["end"]])
    w.writerow([])
    w.writerow(["KPI", "Value", "Previous", "Change %", "Provenance", "Sources"])
    for key, k in overview["kpis"].items():
        w.writerow([LABELS.get(key, key), fmt(k["value"], k["unit"], cur), fmt(k["previous"], k["unit"], cur),
                    k["change_pct"], k["kind"], "; ".join(k["sources"])])
    w.writerow([])
    w.writerow(["Channel", "Spend", "Clicks", "Impressions", "Conversions", "CPA", "ROAS", "Sources"])
    for c in channels:
        w.writerow([c["channel"], fmt(c["spend_minor"], "money", cur), c["clicks"], c["impressions"], c["conversions"],
                    fmt(c["cpa_minor"], "money", cur), c["roas"], "; ".join(c["sources"])])
    w.writerow([])
    w.writerow(["Date", "Organic clicks", "Organic sessions", "Instagram engagement"])
    for d in series["days"]:
        w.writerow([d["date"], d["organic_clicks"], d["organic_sessions"], d["instagram_engagement"]])
    for platform, days in series["paid"].items():
        w.writerow([])
        w.writerow([f"{platform} ads: date", "Impressions", "Clicks", "Spend", "Results", "CTR", "CPC"])
        for d in days:
            w.writerow([d["date"], d["impressions"], d["clicks"], fmt(d["spend_minor"], "money", cur), d["results"], d["ctr"],
                        fmt(d["cpc_minor"], "money", cur)])
    return buf.getvalue().encode()


def to_pdf(title: str, workspace_name: str, overview: dict, channels: list[dict], summary: list[str],
           recommendations: list[dict], white_label: dict | None) -> bytes:
    buf = io.BytesIO()
    brand_color = colors.HexColor((white_label or {}).get("primary_color") or "#4F46E5")
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=title)
    styles = getSampleStyleSheet()
    styles["Title"].textColor = brand_color
    story = []
    by = (white_label or {}).get("agency_name") or "MarketingOS"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(f"{workspace_name} · {overview['range']['start']} to {overview['range']['end']} · prepared by {by}",
                           styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Summary", styles["Heading2"]))
    for line in summary:
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))
    cur = overview["currency"]
    rows = [["KPI", "This period", "Previous", "Change", "Type"]]
    for key, k in overview["kpis"].items():
        change = f"{k['change_pct']:+.1f}%" if k["change_pct"] is not None else "—"
        rows.append([LABELS.get(key, key), fmt(k["value"], k["unit"], cur), fmt(k["previous"], k["unit"], cur), change, k["kind"]])
    story.append(Paragraph("Key metrics", styles["Heading2"]))
    story.append(_table(rows, brand_color))
    if channels:
        story.append(Paragraph("Channels", styles["Heading2"]))
        rows = [["Channel", "Spend", "Clicks", "Conversions", "CPA", "ROAS"]]
        for c in channels:
            rows.append([c["channel"].replace("_", " ").title(), fmt(c["spend_minor"], "money", cur), fmt(c["clicks"], "count", cur),
                         fmt(c["conversions"], "count", cur), fmt(c["cpa_minor"], "money", cur),
                         f"{c['roas']:.2f}x" if c.get("roas") else "—"])
        story.append(_table(rows, brand_color))
    if recommendations:
        story.append(Paragraph("Recommendations", styles["Heading2"]))
        for r in recommendations[:10]:
            story.append(Paragraph(f"<b>{r['title']}</b> — {r.get('action') or r.get('reason', '')}", styles["Normal"]))
            story.append(Spacer(1, 2 * mm))
    if overview.get("contains_demo_data"):
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("<i>This report contains demo data.</i>", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"<font size=8>Measured = reported by the platform; calculated = derived from measured values; internal = "
        f"{by} indicator. Generated {date.today().isoformat()}. {(white_label or {}).get('footer', '')}</font>",
        styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def _table(rows, color):
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t
