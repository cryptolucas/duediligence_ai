"""Exporta los documentos del caso demo como archivos reales (XLSX y PDF) en ``backend/demo_files/``.

Sirven para probar el flujo de carga de archivos propios (parser + agentes) con el mismo caso
sintético del seed, por ejemplo arrastrándolos al Dropzone de /deals/new.

Uso:  python scripts/export_demo_documents.py [carpeta_destino]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.data_loader import load_demo_dossier  # noqa: E402
from app.services.numbers import parse_number  # noqa: E402

ROW_RE = re.compile(r"^Fila (\d+) \| (.*)$")
LATIN1_FIXES = {"—": "-", "–": "-", "“": '"', "”": '"', "’": "'", "≤": "<=", "…": "..."}


def _latin1(text: str) -> str:
    for bad, good in LATIN1_FIXES.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def export_xlsx(document, target: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for page in document.pages:
        ws = wb.create_sheet(page.page_or_sheet[:31])
        for line in page.content.splitlines():
            match = ROW_RE.match(line)
            if not match:
                ws.cell(row=1, column=1, value=line)
                continue
            row = int(match.group(1))
            for col, raw in enumerate(match.group(2).split(" | "), start=1):
                value: object = raw
                if col >= 3 and re.fullmatch(r"-?[\d.]+,\d{2}", raw):
                    value = parse_number(raw)
                ws.cell(row=row, column=col, value=value)
        ws.column_dimensions["B"].width = 55
        ws.column_dimensions["C"].width = 22
    wb.save(target)


def export_pdf(document, target: Path) -> None:
    import pymupdf as fitz

    pdf = fitz.open()
    for page_def in document.pages:
        page = pdf.new_page(width=595, height=842)  # A4
        y = 60.0
        page.insert_text((50, 40), _latin1(f"{document.document_name} - {page_def.page_or_sheet}"), fontsize=7, fontname="helv")
        for line in page_def.content.splitlines():
            line = _latin1(line)
            parts = line.split(" | ")
            if len(parts) >= 2 and all(re.fullmatch(r"\(?[\d.]+\)?", p.strip()) for p in parts[1:]):
                # Fila de tabla: etiqueta a la izquierda y cifras alineadas a la derecha en columnas.
                page.insert_text((50, y), parts[0], fontsize=8.5, fontname="helv")
                for i, number in enumerate(parts[1:]):
                    x_right = 440 + i * 95
                    width = fitz.get_text_length(number, fontname="helv", fontsize=8.5)
                    page.insert_text((x_right - width, y), number, fontsize=8.5, fontname="helv")
                y += 14
                continue
            rect = fitz.Rect(50, y - 9, 545, y + 200)
            text = line.replace(" | ", "    ")
            unused = page.insert_textbox(rect, text, fontsize=8.5, fontname="helv")
            # insert_textbox devuelve el alto libre restante: el alto usado es rect.height - unused.
            y += max(11.0, rect.height - unused) + 4
            if y > 800:
                page = pdf.new_page(width=595, height=842)
                y = 60.0
    pdf.save(target)
    pdf.close()


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND_DIR / "demo_files"
    out_dir.mkdir(parents=True, exist_ok=True)
    dossier = load_demo_dossier()
    for document in dossier.documents:
        target = out_dir / document.document_name
        if document.file_format == "XLSX":
            export_xlsx(document, target)
        else:
            export_pdf(document, target)
        print(f"OK -> {target}")


if __name__ == "__main__":
    main()
