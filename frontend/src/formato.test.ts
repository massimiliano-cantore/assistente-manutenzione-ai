import { describe, expect, it } from "vitest";
import { nomeStrumento, riassunto } from "./formato";

describe("riassunto dei passi", () => {
  it("conta le righe di una query", () => {
    const p = { strumento: "interroga_archivio", argomenti: { query: "SELECT 1" },
                esito: { righe_totali: 3, righe: [] }, errore: false };
    expect(riassunto(p)).toBe("SELECT 1 → 3 righe");
  });
  it("segnala gli errori che il modello deve correggere", () => {
    const p = { strumento: "interroga_archivio", argomenti: { query: "SELECT x" },
                esito: { errore: "no such column" }, errore: false };
    expect(riassunto(p)).toContain("il modello riprova");
  });
  it("conta i risultati della ricerca", () => {
    const p = { strumento: "cerca_manuale", argomenti: { domanda: "badge" }, esito: [{}, {}], errore: false };
    expect(riassunto(p)).toBe("badge → 2 risultati");
    expect(nomeStrumento("cerca_manuale")).toBe("Manuali tecnici");
  });
});
