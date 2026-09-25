"""
Stage 1/2 ingestion parsers.
  PDF  -> PyMuPDF text extraction (FIRs)      -- imported lazily
  TXT  -> plain-text FIR narrative (handy for tests / quick demos)
  CSV  -> csv module, every value kept as a string (pandas used to turn IMEIs
          into floats like 3.56938e+14 whenever a column had a blank cell)
"""
from __future__ import annotations

import csv
import io
from typing import Any

from app.services import normalizer


def route_file_type(filename: str, declared_type: str | None = None) -> str:
    lower = filename.lower()
    if lower.endswith((".pdf", ".txt")):
        return "fir"
    if declared_type in ("cdr", "upi", "ipdr", "records"):
        return declared_type
    if lower.endswith(".csv"):
        return "auto"
    raise ValueError(f"Unsupported file type for '{filename}' (expected .csv, .pdf or .txt)")


def parse_pdf_fir(raw_bytes: bytes) -> dict[str, Any]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is not installed: pip install pymupdf") from exc
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    pages_text = [page.get_text("text") for page in doc]
    doc.close()
    return {"content_type": "fir", "full_text": "\n".join(pages_text), "page_count": len(pages_text)}


def parse_txt_fir(raw_bytes: bytes) -> dict[str, Any]:
    return {"content_type": "fir", "full_text": raw_bytes.decode("utf-8", errors="replace"), "page_count": 1}


def parse_csv_structured(raw_bytes: bytes, declared_type: str | None) -> dict[str, Any]:
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    records = [dict(r) for r in reader]
    cols = [c.strip().lower().replace(" ", "_") for c in (reader.fieldnames or [])]
    kind = normalizer.detect_kind(cols, declared_type if declared_type != "auto" else None)
    return {"content_type": kind, "columns": cols, "row_count": len(records), "records": records}


def parse_file(filename: str, raw_bytes: bytes, declared_type: str | None = None) -> dict[str, Any]:
    file_type = route_file_type(filename, declared_type)
    lower = filename.lower()
    if lower.endswith(".pdf"):
        parsed = parse_pdf_fir(raw_bytes)
    elif lower.endswith(".txt"):
        parsed = parse_txt_fir(raw_bytes)
    else:
        parsed = parse_csv_structured(raw_bytes, file_type)
    parsed["file_type"] = parsed["content_type"]
    parsed["source_filename"] = filename
    return parsed
