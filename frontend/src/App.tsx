import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chiedi, conferma, salute, type AzioneProposta, type Passo, type Risposta, type Salute } from "./api";
import { nomeStrumento, riassunto } from "./formato";

interface Messaggio {
  ruolo: "utente" | "assistente" | "sistema";
  testo: string;
  passi?: Passo[];
  secondi?: number;
}

const ESEMPI = [
  "Un lettore di badge non riconosce più i tesserini: cosa controllo?",
  "Centralina con acqua dentro e circuito sporco: cosa si sostituisce di solito?",
  "Quali impianti del cliente NOVAPORTA SRL hanno avuto più rientri?",
  "Quanti pezzi di SCB1180 abbiamo in magazzino?",
];

function Passi({ passi }: { passi: Passo[] }) {
  if (!passi.length) return null;
  return (
    <details className="passi">
      <summary>{passi.length} {passi.length === 1 ? "passo" : "passi"} dell'agente</summary>
      <ol>
        {passi.map((p, i) => (
          <li key={i} className={p.errore ? "errore" : ""}>
            <strong>{nomeStrumento(p.strumento)}</strong> <span>{riassunto(p)}</span>
            <pre>{JSON.stringify(p.esito, null, 1).slice(0, 1500)}</pre>
          </li>
        ))}
      </ol>
    </details>
  );
}

function Conferma({ azione, onDecidi, occupato }: {
  azione: AzioneProposta; onDecidi: (ok: boolean) => void; occupato: boolean;
}) {
  return (
    <div className="conferma" role="alertdialog" aria-label="Conferma azione">
      <h3>L'agente vuole aprire un ordine di lavoro nel CMMS</h3>
      <dl>
        <dt>Impianto</dt><dd>{azione.impianto_id}</dd>
        <dt>Descrizione</dt><dd>{azione.descrizione}</dd>
        <dt>Priorità</dt><dd className={`priorita-${azione.priorita}`}>{azione.priorita}</dd>
        <dt>Ricambi</dt><dd>{azione.ricambi.length ? azione.ricambi.join(", ") : "nessuno"}</dd>
      </dl>
      <div className="azioni">
        <button disabled={occupato} onClick={() => onDecidi(true)}>Conferma</button>
        <button disabled={occupato} className="secondario" onClick={() => onDecidi(false)}>Annulla</button>
      </div>
    </div>
  );
}

export default function App() {
  const [messaggi, setMessaggi] = useState<Messaggio[]>([]);
  const [testo, setTesto] = useState("");
  const [thread, setThread] = useState<string | null>(null);
  const [attesa, setAttesa] = useState<AzioneProposta | null>(null);
  const [occupato, setOccupato] = useState(false);
  const [info, setInfo] = useState<Salute | null>(null);
  const fondo = useRef<HTMLDivElement>(null);

  useEffect(() => { salute().then(setInfo).catch(() => setInfo(null)); }, []);
  useEffect(() => { fondo.current?.scrollIntoView({ behavior: "smooth" }); }, [messaggi, attesa]);

  function ricevi(r: Risposta) {
    setThread(r.thread_id);
    setAttesa(r.in_attesa_di_conferma);
    if (r.testo || r.passi.length) {
      setMessaggi((m) => [...m, { ruolo: "assistente", testo: r.testo, passi: r.passi, secondi: r.secondi }]);
    }
  }

  async function esegui(azione: () => Promise<Risposta>) {
    setOccupato(true);
    try { ricevi(await azione()); }
    catch (e) { setMessaggi((m) => [...m, { ruolo: "sistema", testo: String(e) }]); }
    finally { setOccupato(false); }
  }

  function invia(domanda: string) {
    const d = domanda.trim();
    if (!d || occupato) return;
    setMessaggi((m) => [...m, { ruolo: "utente", testo: d }]);
    setTesto("");
    void esegui(() => chiedi(d, thread));
  }

  function decidi(ok: boolean) {
    if (!thread) return;
    setMessaggi((m) => [...m, { ruolo: "utente", testo: ok ? "✔ Confermo l'ordine di lavoro" : "✖ Annulla" }]);
    void esegui(() => conferma(thread, ok));
  }

  function nuova() { setMessaggi([]); setThread(null); setAttesa(null); }

  return (
    <div className="pagina">
      <header>
        <div>
          <h1>Assistente tecnico</h1>
          <p className="sotto">KYROS ACCESS · laboratorio riparazioni (dati sintetici)</p>
        </div>
        <div className="stato">
          {info ? <>
            <span title="modello linguistico">{info.modello}</span>
            <span title="versione del prompt">prompt {info.versione_prompt}</span>
            <span title="knowledge base">{info.sezioni_manuali} sezioni · {info.profili_casi} profili casi</span>
          </> : <span>backend non raggiungibile</span>}
          <button className="secondario" onClick={nuova}>Nuova conversazione</button>
        </div>
      </header>

      <main>
        {messaggi.length === 0 && (
          <div className="vuoto">
            <p>Chiedi una diagnosi, un dato dallo storico o un'azione sul CMMS.</p>
            <div className="esempi">
              {ESEMPI.map((e) => <button key={e} className="esempio" onClick={() => invia(e)}>{e}</button>)}
            </div>
          </div>
        )}
        {messaggi.map((m, i) => (
          <div key={i} className={`msg ${m.ruolo}`}>
            {m.testo && <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.testo}</ReactMarkdown>}
            {m.passi && <Passi passi={m.passi} />}
            {m.secondi !== undefined && <div className="tempo">{m.secondi.toFixed(1)} s</div>}
          </div>
        ))}
        {attesa && <Conferma azione={attesa} onDecidi={decidi} occupato={occupato} />}
        {occupato && <div className="msg assistente carica">L'agente sta lavorando…</div>}
        <div ref={fondo} />
      </main>

      <form onSubmit={(e) => { e.preventDefault(); invia(testo); }}>
        <input value={testo} onChange={(e) => setTesto(e.target.value)} disabled={occupato || !!attesa}
               placeholder={attesa ? "Conferma o annulla l'azione proposta" : "Scrivi una domanda…"} />
        <button type="submit" disabled={occupato || !!attesa || !testo.trim()}>Invia</button>
      </form>
    </div>
  );
}
