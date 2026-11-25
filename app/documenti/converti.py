"""Conversione in PDF dei file che il browser non sa mostrare (LibreOffice: odg, odt, ods, odp; Office vecchi).

Serve LibreOffice installato sul PC (soffice). I PDF convertiti stanno in una cache e si rifanno solo se
il file originale cambia. Senza LibreOffice il file si scarica e si apre con il programma del PC.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# il browser li mostra così come sono
NEL_BROWSER = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".txt", ".md", ".csv", ".log",
               ".htm", ".html", ".mp4", ".webm", ".mp3", ".wav", ".json", ".xml"}
# LibreOffice li converte in PDF
DA_CONVERTIRE = {".odg", ".odt", ".ods", ".odp", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
                 ".pps", ".ppsx", ".rtf", ".vsd", ".vsdx", ".dxf", ".wmf", ".emf"}
# immagini che il browser non mostra: in PNG con Pillow
IMMAGINI_DA_CONVERTIRE = {".tif", ".tiff"}
# testi con estensioni tecniche (firmware, sorgenti, configurazioni): mostrati come testo
COME_TESTO = {".hex", ".c", ".h", ".cpp", ".asm", ".s", ".ini", ".cfg", ".yaml", ".yml", ".bat", ".py", ".net",
              ".lst", ".map"}
PERCORSI_WINDOWS = [r"C:\Program Files\LibreOffice\program\soffice.exe",
                    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]


def trova_soffice() -> str | None:
    if os.getenv("SOFFICE"):
        return os.environ["SOFFICE"]
    for nome in ("soffice", "libreoffice"):
        if p := shutil.which(nome):
            return p
    return next((p for p in PERCORSI_WINDOWS if Path(p).exists()), None)


def in_pdf(f: Path, cache: Path) -> Path | None:
    """PDF del file (dalla cache se aggiornato); None se non si può convertire."""
    soffice = trova_soffice()
    if not soffice:
        return None
    st = f.stat()
    chiave = hashlib.sha1(f"{f.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    uscita = cache / chiave
    pdf = uscita / (f.stem + ".pdf")
    if pdf.exists():
        return pdf
    uscita.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(uscita), str(f)],
                       check=True, timeout=120, capture_output=True)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("conversione in PDF non riuscita per %s: %s", f.name, e)
        return None
    return pdf if pdf.exists() else None


def in_png(f: Path, cache: Path) -> Path | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    st = f.stat()
    chiave = hashlib.sha1(f"{f.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    png = cache / chiave / (f.stem + ".png")
    if png.exists():
        return png
    png.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(f) as im:
            im.save(png)
    except Exception as e:  # noqa: BLE001
        log.warning("immagine non convertita %s: %s", f.name, e)
        return None
    return png


def apri_sul_pc(f: Path) -> bool:
    """Apre il file con il programma associato del PC (Altium, AutoCAD, ...). Solo Windows."""
    if os.name != "nt":
        return False
    try:
        os.startfile(str(f))  # type: ignore[attr-defined]  # noqa: S606
        return True
    except OSError as e:
        log.warning("apertura non riuscita %s: %s", f.name, e)
        return False
