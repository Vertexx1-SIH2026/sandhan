"""
evidence_engine.py -- BSA Section 63 certificate PDF:
  1. Case summary (case ID, investigator, date range, source files)
  2. Merkle root hash (text + QR)
  3. Linked cases (historical + live) with the evidence for each link
  4. Verified graph snapshot (masked per DPDP; predicted edges only if verified)
  5. Historical reference database provenance (file SHA-256s)
  6. Dual-certificate block, BSA Sec. 63(4)(c)
  7. Case audit trail excerpt

Only produced after hitl_gate.has_pending_unverified_predictions() is False.
"""
from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak,
)

from app.services.qr_generator import generate_qr_png_bytes

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="SandhanTitle", fontSize=18, leading=22, spaceAfter=12, textColor=colors.HexColor("#0B1F3A")))
styles.add(ParagraphStyle(name="SandhanH2", fontSize=13, leading=16, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#0B1F3A")))
styles.add(ParagraphStyle(name="SandhanMono", fontName="Courier", fontSize=9, leading=12))
styles.add(ParagraphStyle(name="SandhanBody", fontSize=10, leading=14))
styles.add(ParagraphStyle(name="SandhanCell", fontSize=7.5, leading=9.5))

_HEADER_STYLE = [
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F3A")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
]


def _cell(text) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), styles["SandhanCell"])


def _table(header: list[str], rows: list[list], widths: list[float]) -> Table:
    data = [header] + [[_cell(c) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle(_HEADER_STYLE))
    return t


def build_evidence_pdf(
    case_id: str,
    investigator_id: str,
    date_range: str,
    source_files: list[str],
    merkle_root: str,
    graph_snapshot: dict,
    audit_excerpt: list[dict],
    linked_cases: list[dict] | None = None,
    historical_sources: list[dict] | None = None,
    verified_predictions: list[dict] | None = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm)
    story = []

    story.append(Paragraph("Sandhan &mdash; Digital Evidence Certificate", styles["SandhanTitle"]))
    story.append(Paragraph("Issued under Bharatiya Sakshya Adhiniyam (BSA) 2023, Section 63", styles["SandhanBody"]))
    story.append(Spacer(1, 8))

    # 1. summary
    story.append(Paragraph("1. Case Summary", styles["SandhanH2"]))
    stats = graph_snapshot.get("stats", {})
    t = _table(["Field", "Value"], [
        ["Case ID", case_id],
        ["Investigator ID", investigator_id],
        ["Date range (ingestion)", date_range],
        ["Certificate generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")],
        ["Source files", ", ".join(source_files) if source_files else "-"],
        ["Case network", f"{stats.get('cases', 0)} cases ({stats.get('historical_cases', 0)} historical), "
                         f"{stats.get('nodes', 0)} entities, {stats.get('edges', 0)} relationships"],
    ], [45, 133])
    story.append(t)

    # 2. merkle
    story.append(Paragraph("2. Case Integrity &mdash; Merkle Root Hash", styles["SandhanH2"]))
    story.append(Paragraph(
        "Every file ingested for this case is a leaf of a per-case Merkle tree. Any change to any "
        "file changes the root below.", styles["SandhanBody"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(merkle_root, styles["SandhanMono"]))
    story.append(Spacer(1, 6))
    story.append(RLImage(io.BytesIO(generate_qr_png_bytes(merkle_root)), width=32 * mm, height=32 * mm))

    # 3. linked cases
    story.append(Paragraph("3. Linked Cases", styles["SandhanH2"]))
    story.append(Paragraph(
        "Cases connected to this investigation by the link-discovery engine. Only CONFIRMED links "
        "(exact identifier matches on the suspect side) and links VERIFIED by the investigator form part "
        "of the evidence graph; probable leads are listed for completeness only.", styles["SandhanBody"]))
    rows = []
    for l in (linked_cases or [])[:40]:
        ev = "; ".join(
            (s.get("identifier") or s.get("handle") or s.get("fir_id") or "") + f" ({s['signal']})"
            for s in (l.get("evidence") or [])[:3]
        )
        rows.append([l["other_case_id"], "historical" if l.get("other_is_historical") else "live",
                     l["status"], f"{l['score']:.2f}", ev])
    story.append(Spacer(1, 4))
    story.append(_table(["Case", "Source", "Status", "Score", "Evidence"], rows or [["-", "-", "-", "-", "none"]],
                        [26, 20, 20, 14, 98]))

    # 4. graph snapshot
    story.append(Paragraph("4. Verified Graph Snapshot", styles["SandhanH2"]))
    story.append(Paragraph(
        "Confirmed entities and relationships of the case network. Third-party identifiers are masked "
        "(DPDP Act 2023, Sec. 17(1)(c) safeguards) unless escalated. Predicted links appear only if "
        "verified by the investigator.", styles["SandhanBody"]))
    nodes = sorted(graph_snapshot.get("nodes", []),
                   key=lambda n: (not n.get("in_root_case"), not n.get("is_subject"), n.get("entity_type") or ""))
    label = {n["entity_id"]: n.get("display_value") or n["entity_id"] for n in nodes}
    node_rows = [[n.get("display_value"), n.get("entity_type"),
                  "suspect" if n.get("is_subject") else "third party",
                  ", ".join(n.get("cases", [])[:4])] for n in nodes[:80]]
    story.append(Spacer(1, 4))
    story.append(_table(["Entity", "Type", "Side", "Cases"], node_rows, [55, 28, 22, 73]))
    edges = graph_snapshot.get("edges", [])
    edge_rows = []
    for e in edges[:80]:
        detail = f"x{e.get('count', 0)}"
        if e.get("total_amount"):
            detail += f", Rs. {e['total_amount']:,.0f}"
        if e.get("verified"):
            detail += ", HITL-verified"
        edge_rows.append([label.get(e["source"], e["source"]), e["relation"], label.get(e["target"], e["target"]), detail])
    story.append(Spacer(1, 6))
    story.append(_table(["From", "Relationship", "To", "Detail"], edge_rows, [52, 34, 52, 40]))
    if len(nodes) > 80 or len(edges) > 80:
        story.append(Paragraph(f"(showing first 80 of {len(nodes)} entities / {len(edges)} relationships)",
                               styles["SandhanBody"]))

    if verified_predictions:
        story.append(Paragraph("Verified predicted links (Human-in-the-Loop)", styles["SandhanBody"]))
        story.append(_table(["From", "To", "Score", "Verified by", "At"], [
            [label.get(v["source"], v["source"]), label.get(v["target"], v["target"]),
             f"{v['score']:.3f}", str(v.get("verified_by"))[:8], v.get("verified_at")]
            for v in verified_predictions
        ], [45, 45, 18, 30, 40]))

    # 5. historical provenance
    story.append(Paragraph("5. Historical Reference Database Provenance", styles["SandhanH2"]))
    hs_rows = [[h["kind"], h["filename"], h["row_count"], h["sha256"]] for h in (historical_sources or [])]
    story.append(_table(["Kind", "File", "Rows", "SHA-256"], hs_rows or [["-", "not loaded", "-", "-"]],
                        [20, 55, 13, 90]))

    story.append(PageBreak())

    # 6. certificate
    story.append(Paragraph("6. Certificate under BSA Section 63(4)(c)", styles["SandhanH2"]))
    story.append(Paragraph(
        "This certificate is issued in two parts as required under Section 63(4)(c) of the Bharatiya "
        "Sakshya Adhiniyam, 2023. Signature fields are placeholders for the hackathon demo scope.",
        styles["SandhanBody"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>(a) Device / Data Custodian Declaration</b>", styles["SandhanBody"]))
    story.append(Paragraph(
        f"I certify that the electronic record identified by case ID {escape(case_id)} and Merkle root hash "
        f"{merkle_root[:24]}... was produced from data lawfully obtained and has been maintained without "
        "alteration since ingestion.", styles["SandhanBody"]))
    story.append(Paragraph("Name: ______________________&nbsp;&nbsp;&nbsp; Designation: ______________________", styles["SandhanBody"]))
    story.append(Paragraph("Signature: ______________________&nbsp;&nbsp;&nbsp; Date: ______________________", styles["SandhanBody"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>(b) Independent Expert Declaration</b>", styles["SandhanBody"]))
    story.append(Paragraph(
        f"I certify that I have independently verified the hash value {merkle_root[:24]}... against the "
        "case bundle described above.", styles["SandhanBody"]))
    story.append(Paragraph("Name: ______________________&nbsp;&nbsp;&nbsp; Designation: ______________________", styles["SandhanBody"]))
    story.append(Paragraph("Signature: ______________________&nbsp;&nbsp;&nbsp; Date: ______________________", styles["SandhanBody"]))

    # 7. audit
    story.append(Paragraph("7. Case Audit Trail Excerpt", styles["SandhanH2"]))
    story.append(_table(["Timestamp", "Investigator", "Action", "Target"], [
        [str(a.get("timestamp", ""))[:19], str(a.get("investigator_id", ""))[:8], a.get("action", ""),
         str(a.get("target", ""))[:60]]
        for a in audit_excerpt[:40]
    ], [38, 24, 22, 94]))

    doc.build(story)
    return buf.getvalue()
