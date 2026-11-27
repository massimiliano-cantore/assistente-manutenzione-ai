"""PASSO 1 (sul PC): dai PDF dell'archivio resi alle immagini delle pagine, pronte per Kaggle.

    python archivio_schede\\prepara_pagine.py "CARTELLA_SCHEDE_RESO" 2025 2026

Per ogni PDF (anno\\mese\\file.pdf) salva le pagine in JPEG in scala di grigi (abbastanza per la scrittura a mano)
nella cartella archivio_kaggle\\pagine\\ e scrive archivio_kaggle\\pagine.csv (pagina, anno, mese, file, n. pagina).
Poi comprime tutto in archivio_kaggle.zip da caricare su Kaggle come dataset PRIVATO.
Se lo rilanci, salta i PDF già convertiti.
"""
from __future__ import annotations

import csv
import hashlib
import sys
import zipfile
from pathlib import Path

import pypdfium2 as pdfium

DPI = 170
USCITA = Path("archivio_kaggle")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    base, anni = Path(sys.argv[1]), sys.argv[2:]
    (USCITA / "pagine").mkdir(parents=True, exist_ok=True)
    righe, n_pdf = [], 0
    for anno in anni:
        for pdf in sorted((base / anno).rglob("*.pdf")):
            rel = pdf.relative_to(base)
            mese = rel.parts[1] if len(rel.parts) > 2 else ""
            sigla = hashlib.sha1(str(rel).encode()).hexdigest()[:10]   # nome corto e stabile del PDF
            try:
                doc = pdfium.PdfDocument(str(pdf))
            except Exception as e:  # noqa: BLE001
                print("  non letto:", rel, e)
                continue
            for k in range(len(doc)):
                nome = f"{anno}_{sigla}_p{k + 1:03d}.jpg"
                f = USCITA / "pagine" / nome
                if not f.exists():
                    img = doc[k].render(scale=DPI / 72, grayscale=True).to_pil()
                    img.save(f, "JPEG", quality=82)
                righe.append({"pagina": nome, "anno": anno, "mese": mese, "file": str(rel), "n": k + 1,
                              "di": len(doc)})
            n_pdf += 1
            if n_pdf % 50 == 0:
                print(f"  ... {n_pdf} PDF, {len(righe)} pagine", flush=True)
    with open(USCITA / "pagine.csv", "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=["pagina", "anno", "mese", "file", "n", "di"])
        w.writeheader()
        w.writerows(righe)
    print(f"{n_pdf} PDF, {len(righe)} pagine. Comprimo...", flush=True)
    with zipfile.ZipFile("archivio_kaggle.zip", "w", zipfile.ZIP_STORED) as z:   # JPEG già compressi
        z.write(USCITA / "pagine.csv", "pagine.csv")
        for r in righe:
            z.write(USCITA / "pagine" / r["pagina"], "pagine/" + r["pagina"])
        for f in ("prompt_scheda.py", "leggi_su_kaggle.py"):
            z.write(Path(__file__).parent / f, f)
    mb = Path("archivio_kaggle.zip").stat().st_size / 1e6
    print(f"Pronto: archivio_kaggle.zip ({mb:.0f} MB) da caricare su Kaggle come dataset privato.")


if __name__ == "__main__":
    main()
