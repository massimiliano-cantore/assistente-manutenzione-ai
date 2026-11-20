"""Evidenzia componenti sul disegno (schema o montaggio) e salva l'immagine da mostrare al tecnico."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageDraw, ImageFont

from app.elettrico import altium_pdf

COLORI = [(220, 38, 38), (37, 99, 235), (22, 163, 74), (217, 119, 6), (147, 51, 234)]


def evidenzia(pdf: str, designators: list[str], cartella: Path, scala: float = 2.5) -> dict:
    pos = altium_pdf.posizioni(pdf, designators)
    if not pos:
        return {"errore": f"nessuno di {', '.join(designators)} trovato sul disegno"}
    pagina = max(set(p for p, _ in pos.values()), key=lambda k: sum(1 for p, _ in pos.values() if p == k))
    doc = pdfium.PdfDocument(pdf)
    try:
        img = doc[pagina].render(scale=scala).to_pil().convert("RGB")
    finally:
        doc.close()
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=int(9 * scala))
    for i, des in enumerate(designators):
        if des not in pos or pos[des][0] != pagina:
            continue
        x0, y0, x1, y1 = (v * scala for v in pos[des][1])
        # l'etichetta del componente è piccola: si allarga il riquadro attorno al simbolo
        m = 28 * scala / 2.5
        colore = COLORI[i % len(COLORI)]
        d.rectangle([x0 - m, y0 - m * 0.6, x1 + m * 1.6, y1 + m * 1.8], outline=colore, width=int(3 * scala / 2.5) + 1)
        d.text((x1 + m * 1.6 + 4, y0 - m * 0.6), des, fill=colore, font=font)
    cartella.mkdir(parents=True, exist_ok=True)
    nome = hashlib.sha1(f"{pdf}|{'|'.join(designators)}".encode()).hexdigest()[:12] + ".png"
    img.save(cartella / nome)
    return {"immagine": nome, "pagina": pagina + 1, "evidenziati": [d for d in designators if d in pos],
            "non_trovati": [d for d in designators if d not in pos]}
