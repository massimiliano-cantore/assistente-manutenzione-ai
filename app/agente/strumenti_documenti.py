"""Strumento dell'agente sull'indice dei documenti dei prodotti (istruzioni, schemi, altri documenti)."""
from __future__ import annotations

from urllib.parse import quote

from langchain_core.tools import tool

from app.documenti.indice import IndiceDocumenti


def crea_strumenti_documenti(indice: IndiceDocumenti) -> list:
    @tool
    def cerca_documenti(testo: str) -> dict:
        """Cerca nei documenti dei prodotti (istruzioni, schemi, BOM, manuali, note) per articolo, codice,
        componente o parola. Restituisce titolo, data, percorso e link: usalo per indicare al tecnico le
        istruzioni più recenti o lo schema da consultare."""
        r = indice.cerca(testo, limite=60)

        def breve(d):
            return {"titolo": d["titolo"], "data": d["data"], "percorso": d["percorso"],
                    "link": "/api/documenti/apri?p=" + quote(d["percorso"])}
        return {"istruzioni_ultima_versione": [breve(d) for d in r["istruzioni"][:5]],
                "schemi": [breve(d) for d in r["schemi"][:8]], "altri": [breve(d) for d in r["altri"][:8]],
                "totale": r["totale"], "pagina_completa": "/documenti?q=" + quote(testo)}

    return [cerca_documenti]
