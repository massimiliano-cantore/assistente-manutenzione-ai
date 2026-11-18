// Tipi e chiamate all'API dell'assistente (stessi campi di app/agente/servizio.py: Risposta).

export interface Passo {
  strumento: string;
  argomenti: Record<string, unknown>;
  esito: unknown;
  errore: boolean;
}

export interface AzioneProposta {
  azione: string;
  impianto_id: string;
  descrizione: string;
  priorita: "bassa" | "media" | "alta";
  ricambi: string[];
}

export interface Risposta {
  thread_id: string;
  testo: string;
  passi: Passo[];
  in_attesa_di_conferma: AzioneProposta | null;
  secondi: number;
}

export interface Salute {
  stato: string;
  modello: string;
  versione_prompt: string;
  embedder: string;
  sezioni_manuali: number;
  profili_casi: number;
}

async function post<T>(url: string, corpo: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo),
  });
  if (!r.ok) throw new Error(`Errore ${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

export const chiedi = (messaggio: string, thread_id: string | null) =>
  post<Risposta>("/api/chat", { messaggio, thread_id });

export const conferma = (thread_id: string, approvato: boolean) =>
  post<Risposta>("/api/conferma", { thread_id, approvato });

export async function salute(): Promise<Salute> {
  const r = await fetch("/api/salute");
  if (!r.ok) throw new Error(`Errore ${r.status}`);
  return (await r.json()) as Salute;
}
