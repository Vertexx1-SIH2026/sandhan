"""
Renders data/demo/fir_narratives.json into uploadable FIR files:
  data/demo/<CASE>/FIR-xxxx.pdf   (PDF, like a scanned FIR -- needs reportlab)
  data/demo/<CASE>/FIR-xxxx.txt   (plain text -- works even without PyMuPDF)

    python scripts/generate_sample_firs.py
"""
import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo"


def main():
    styles = getSampleStyleSheet()
    firs = json.loads((DEMO / "fir_narratives.json").read_text(encoding="utf-8"))
    for fir in firs:
        out_dir = DEMO / fir["case_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{fir['fir_id']}.txt").write_text(fir["text"], encoding="utf-8")
        pdf = out_dir / f"{fir['fir_id']}.pdf"
        doc = SimpleDocTemplate(str(pdf), pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm,
                                leftMargin=20 * mm, rightMargin=20 * mm)
        doc.build([
            Paragraph(f"First Information Report -- {fir['fir_id']}", styles["Title"]),
            Spacer(1, 12),
            Paragraph(f"Associated case: {fir['case_id']}", styles["Normal"]),
            Spacer(1, 12),
            Paragraph("Narrative:", styles["Heading3"]),
            Paragraph(fir["text"], styles["BodyText"]),
        ])
        print(f"Wrote {pdf} (+ .txt)")


if __name__ == "__main__":
    main()
