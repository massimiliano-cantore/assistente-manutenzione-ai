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

DA_CONVERTIRE = {".odg", ".odt", ".ods", ".odp", ".doc", ".ppt", ".pptx", ".rtf"}
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
