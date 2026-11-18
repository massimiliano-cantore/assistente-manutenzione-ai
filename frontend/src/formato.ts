import type { Passo } from "./api";

const NOMI: Record<string, string> = {
  cerca_manuale: "Manuali tecnici",
  casi_simili: "Casi simili nello storico",
  interroga_archivio: "Query sull'archivio",
  cerca_impianto: "CMMS · impianti",
  verifica_ricambio: "CMMS · magazzino",
  apri_ordine_di_lavoro: "CMMS · ordine di lavoro",
};

export const nomeStrumento = (s: string): string => NOMI[s] ?? s;

/** Riassunto di una riga per il passo: cosa ha cercato e quanto ha trovato. */
export function riassunto(p: Passo): string {
  const a = p.argomenti;
  const dettaglio =
    (a.query as string) ?? (a.domanda as string) ?? (a.sintomo as string) ?? (a.codice as string) ??
    (a.cliente as string) ?? (a.impianto_id as string) ?? "";
  if (p.errore) return `${dettaglio} → errore`;
  const e = p.esito as Record<string, unknown> | unknown[] | null;
  let quanti = "";
  if (Array.isArray(e)) quanti = `${e.length} risultati`;
  else if (e && typeof e === "object" && "trovati" in e) quanti = `${e.trovati} risultati`;
  else if (e && typeof e === "object" && "righe_totali" in e) quanti = `${e.righe_totali} righe`;
  else if (e && typeof e === "object" && "errore" in e) quanti = "errore, il modello riprova";
  else if (e && typeof e === "object" && "esito" in e) quanti = String(e.esito);
  return [dettaglio, quanti].filter(Boolean).join(" → ");
}
