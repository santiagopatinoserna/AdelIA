"""Render a ClinicalCase body to a realistic PDF (reportlab, monospaced)."""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.clinical_corpus.cases import ClinicalCase


def case_to_pdf_bytes(case: ClinicalCase) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont("Courier", 9)
    x, y = 40, height - 50
    leading = 12
    for line in case.body.splitlines():
        if y < 50:
            c.showPage()
            c.setFont("Courier", 9)
            y = height - 50
        c.drawString(x, y, line[:110])
        y -= leading
    c.showPage()
    c.save()
    return buf.getvalue()
