"""Strumenti dell'agente sul firmware: quali file ci sono per una scheda e cosa fa il firmware sui pin del
microcontrollore, ricavato dal binario e incrociato con lo schema."""
from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from app.datasheet.servizio import ServizioDatasheet
from app.elettrico.catalogo import Catalogo
from app.firmware import analisi, inventario, stm32


def _chiave_versione(nome: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", nome)]


def _mcu(catalogo: Catalogo, scheda: str) -> tuple[str, str]:
    """(designator, codice) del microcontrollore: da prodotti.yaml se indicato a mano, altrimenti dallo schema."""
    s = catalogo.scheda(scheda)
    a_mano = catalogo.extra.get(s.codice, {}).get("mcu")
    if isinstance(a_mano, dict):
        return a_mano.get("designator", ""), a_mano.get("codice", "")
    trovati = inventario.mcu_della_scheda(s)
    return (trovati or [("", "")])[0]


def scegli_file(file: list[dict], richiesto: str = "") -> dict | None:
    if richiesto:
        for f in file:
            if richiesto.lower() in Path(f["file"]).name.lower():
                return f
        return None
    con_codice = [f for f in file if f.get("byte", 1) and f.get("formato") != "bin"] or file
    return max(con_codice, key=lambda f: _chiave_versione(Path(f["file"]).name), default=None)


def scheda_funzionale(catalogo: Catalogo, datasheet: ServizioDatasheet | None, scheda: str, file: str = "") -> dict:
    """Analisi del firmware di una scheda incrociata con lo schema (usata dallo strumento e dal rapporto)."""
    cartella = catalogo.cartella or Path(".")
    s = catalogo.scheda(scheda)
    disponibili = catalogo.firmware.get(s.codice, [])
    if not disponibili:
        return {"errore": f"nessun firmware associato alla scheda {s.codice} in prodotti.yaml "
                          "(rilanciare lo scanner o aggiungerlo a mano)"}
    scelto = scegli_file(disponibili, file)
    if not scelto:
        return {"errore": f"nessun file che contenga '{file}'", "disponibili":
                [Path(f["file"]).name for f in disponibili][:30]}
    des, codice = _mcu(catalogo, s.codice)
    try:
        r = analisi.analizza(cartella / scelto["file"], cache=cartella / "firmware_analisi", mcu=codice)
    except stm32.FirmwareNonSupportato as e:
        return {"scheda": s.codice, "file": Path(scelto["file"]).name, "errore": str(e)}
    mappa = {k.upper(): str(v) for k, v in (catalogo.extra.get(s.codice, {}).get("piedinatura_mcu") or {}).items()}
    fonte_mappa = "prodotti.yaml" if mappa else None
    if not mappa and datasheet is not None and codice and des:
        try:
            info = catalogo.info_componente(s.codice, des)
            p = datasheet.piedinatura(codice, n_pin=len(info["pin"]), package=info.get("footprint", ""))
            mappa = stm32.nome_pin_a_numero(p)
            fonte_mappa = f"datasheet ({p.get('fonte', '')})" if mappa else None
        except Exception:  # noqa: BLE001 - senza datasheet si danno solo i nomi delle porte
            mappa = {}
    pin, anomalie = [], []
    for v in r["pin"]:
        numero = mappa.get(v["pin"])
        voce = dict(v)
        if numero and des:
            rif = f"{des}-{numero}"
            net = s.net_del_pin(rif)
            voce.update({"pin_componente": rif, "net": net or "(non collegato)",
                         "collegato_a": sorted(x for x in s.nets.get(net, ()) if x != rif)[:6] if net else []})
            if not net and v["modo"] == "uscita":
                anomalie.append(f"{v['pin']} ({rif}) è un'uscita nel firmware ma sullo schema non è collegato")
        pin.append(voce)
    out = {"scheda": s.codice, "file": Path(scelto["file"]).name, "microcontrollore": f"{des} {codice}".strip(),
           "architettura": r.get("architettura") or "ARM Cortex-M (STM32)",
           "versioni_disponibili": len(disponibili), "pin": pin,
           "periferiche_configurate": r.get("periferiche_configurate", []),
           "moduli_sorgente": r.get("moduli_sorgente", []), "testi": r.get("testi", [])[:20], "limiti": r["limiti"]}
    if anomalie:
        out["da_verificare"] = anomalie
    if not mappa:
        out["avviso"] = ("corrispondenza porta -> numero di pin non disponibile: indicare 'piedinatura_mcu' in "
                         "prodotti.yaml o configurare la ricerca datasheet; i pin sono dati come nomi di porta")
    else:
        out["corrispondenza_pin_da"] = fonte_mappa
    return out


def crea_strumenti_firmware(catalogo: Catalogo, datasheet: ServizioDatasheet | None) -> list:
    @tool
    def elenca_firmware(scheda: str) -> dict:
        """Elenca i file firmware (.hex, .bin, .elf) associati a una scheda, con la famiglia di microcontrollore
        probabile. Utile per sapere quali versioni esistono (es. personalizzazioni per cliente)."""
        file = catalogo.firmware.get(catalogo.scheda(scheda).codice, [])
        return {"scheda": scheda, "file": [{"nome": Path(f["file"]).name, "formato": f.get("formato"),
                                            "famiglia": f.get("famiglia", "")} for f in
                                           sorted(file, key=lambda f: _chiave_versione(Path(f["file"]).name))]}

    @tool
    def firmware_scheda(scheda: str, file: str = "") -> dict:
        """Cosa fa il firmware sui pin del microcontrollore di una scheda (STM32, PIC16, PIC18, AVR), ricavato dal
        binario senza sorgente: per ogni pin usato dice se è ingresso (con pull-up), uscita o funzione alternativa
        (timer/PWM, seriale, SPI, I2C) e a quale net e componenti è collegato sullo schema. Elenca anche le
        periferiche usate e i moduli del programma. file: parte del nome di una versione precisa ('' = la più recente).
        Usalo per sapere cosa aspettarsi su un pin (es. ingresso con pull-up: a riposo alto) e per capire quale
        segnale il micro legge o comanda."""
        return scheda_funzionale(catalogo, datasheet, scheda, file)

    return [elenca_firmware, firmware_scheda]
