"""qr_generator.py -- QR-encodes the case Merkle root hash for the evidence
certificate, so a court or opposing counsel can scan and independently
re-derive the exact hash without running Sandhan's software."""
from __future__ import annotations

import io

import qrcode


def generate_qr_png_bytes(data: str) -> bytes:
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
