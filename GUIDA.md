# Guida al progetto (per Massimiliano)

## 1. Messa online, una volta sola

1. **Repository.** Su GitHub crea un repository vuoto `assistente-manutenzione-ai` (senza README) e carica il progetto:
   `git remote add origin https://github.com/massimiliano-cantore/assistente-manutenzione-ai.git && git push -u origin main`
2. **Prima CI.** Dopo il push si avvia da sola la CI (scheda *Actions*). Controlla in particolare il job `rag-denso`:
   misura il recupero con il modello di embedding vero, che in fase di sviluppo non era scaricabile.
   Se resta sotto 0,80, guarda nel report quali domande sbaglia prima di toccare la soglia.
3. **Chiave del modello.** Crea una chiave gratuita su console.groq.com. Su GitHub aggiungi il secret
   `GROQ_API_KEY` (*Settings → Secrets and variables → Actions*), poi lancia *Actions → Valutazione agente*.
   Il numero che esce (es. 11/12) va nel README e nel CV.
4. **Cloud.** Segui [`deploy/cloud-run.md`](deploy/cloud-run.md) (circa 20 minuti), poi lancia il workflow di deploy.
   Ottieni un URL pubblico da mettere su CV e LinkedIn.
5. **Farlo girare:** vedi la sezione 1b qui sotto.

## 1b. Come farlo girare

**Senza installare nulla, nel browser (GitHub Codespaces) — consigliato**
1. Su GitHub, in alto a destra: foto profilo → *Settings* → *Codespaces* → *New secret*. Nome `GROQ_API_KEY`, valore la tua chiave Groq, e come repository scegli `assistente-manutenzione-ai`.
2. Apri il repository → pulsante verde *Code* → scheda *Codespaces* → *Create codespace on main*.
3. Si apre VS Code nel browser e installa tutto da solo (3-5 minuti la prima volta).
4. Nel terminale in basso scrivi `./avvia.sh`. Quando compare "Application startup complete", si apre la scheda con l'interfaccia (porta 8000). Se non si apre: scheda *Porte* → 8000 → icona del globo.
5. Quando hai finito, chiudi la scheda: il codespace si ferma da solo dopo 30 minuti di inattività. Il piano gratuito ha una quota mensile di ore.

**Sul tuo PC (Windows)**
Servono Python 3.11 o superiore, Node 22 e Git. In PowerShell:
```
git clone https://github.com/massimiliano-cantore/assistente-manutenzione-ai
cd assistente-manutenzione-ai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env        (poi apri .env con il Blocco note e incolla la chiave dopo GROQ_API_KEY=)
cd frontend; npm ci; npm run build; cd ..
uvicorn app.api:crea_app --factory --port 8000
```
Poi apri http://localhost:8000. La prima volta scarica il modello di embedding (circa 220 MB).

**Con Docker:** `docker compose up --build` avvia anche Qdrant come server separato, il CMMS come servizio a parte e Prometheus su http://localhost:9090.

## 2. Dove trovare ogni requisito dell'annuncio

| Requisito | Dove |
|---|---|
| LangGraph / LangChain | `app/agente/grafo.py`: grafo, nodi, checkpointer; `strumenti.py`: tool LangChain |
| AI Agents che usano sistemi esterni | `app/agente/strumenti.py` + `app/cmms/` (API REST chiamata via HTTP) |
| Integrazione CMMS / system integration | `app/cmms/api.py`, `client.py`; in docker compose è un servizio separato |
| RAG | `app/rag/indice.py` (Qdrant, filtri per famiglia), `app/dati.py` (chunking), `valutazioni/valuta_rag.py` |
| Robustezza | SQL in sola lettura, conferma umana prima di scrivere, limite di passi, errori degli strumenti restituiti al modello, modelli di riserva |
| Monitoraggio | `app/osservabilita.py`: `/metrics` per Prometheus, log JSON, Langfuse opzionale |
| CI/CD per AI, test automatici, versionamento | `.github/workflows/`, `tests/`, `config/agente.yaml` + `prompts/`, report con commit |
| Docker / Cloud / Kubernetes | `docker/Dockerfile`, `docker-compose.yml`, `deploy-cloud-run.yml`, `deploy/k8s/` |
| TypeScript | `frontend/src/` (React) |

## 3. Il progetto in 60 secondi (da dire al colloquio)

"Ho costruito un assistente per il laboratorio riparazioni. È un agente LangGraph con sei strumenti: due fanno RAG
su manuali e storico dei casi con Qdrant, uno interroga l'archivio in SQL in sola lettura, tre lavorano su un CMMS
tramite API REST. Ogni scrittura nel CMMS si ferma con un interrupt e aspetta la conferma del tecnico. Il recupero
è valutato a ogni push con hit@k e MRR, l'agente una volta a settimana con il modello vero. Se i numeri scendono
sotto soglia, la pipeline fallisce. Gira in Docker, si pubblica su Cloud Run da GitHub Actions ed espone metriche
Prometheus. Viene dal mio lavoro reale: i dati sono sintetici, ma il processo è quello di un laboratorio riparazioni vero."

## 4. Domande probabili e come rispondere

- **Perché LangGraph e non un ciclo scritto a mano?** Il ciclo a mano l'ho già fatto nel progetto Document AI.
  LangGraph mi dà lo stato persistente per thread, la ripresa dopo l'interrupt e un grafo estendibile
  (es. un nodo di verifica prima della risposta) senza reinventarli.
- **Come eviti che l'agente faccia danni?** Su tre livelli. L'SQL è in sola lettura (`PRAGMA query_only` e solo
  SELECT/WITH). Le scritture richiedono l'approvazione umana. Il CMMS valida tutto (impianto, priorità, codici).
  In più c'è un limite al numero di passi.
- **Come valuti un RAG?** Prima il recupero, separato dalla generazione: 26 domande scritte come le farebbe un
  tecnico, con parole diverse dai titoli, e la sezione attesa; misuro hit@4 e MRR. TF-IDF è la baseline: il
  modello denso deve fare meglio. Poi la valutazione end-to-end, dove i valori attesi sono calcolati con SQL.
- **Allucinazioni?** Il prompt obbliga a usare gli strumenti, le risposte citano la sezione del manuale e
  l'interfaccia mostra ogni passo con i dati usati. La valutazione controlla i numeri esatti.
- **Come lo porteresti in produzione su larga scala?** Checkpointer su Postgres al posto della memoria, più
  repliche, Qdrant gestito, autenticazione tra i servizi, Workload Identity al posto della chiave JSON,
  dashboard e allarmi su latenza ed errori.
- **Versionamento di modelli e prompt?** Prompt in file con versione, modello in `config/agente.yaml`. Ogni
  report di valutazione salva configurazione e commit: posso confrontare v1 e v2 di un prompt con gli stessi casi.
- **Perché nei test c'è un LLM finto?** Per testare grafo, strumenti, interrupt e API in modo deterministico,
  gratuito e senza rete. La qualità del modello vero si misura a parte, nella valutazione.

## 5. Per farlo davvero tuo (consigliato prima del colloquio)

Ti chiederanno dettagli. Il modo più veloce per padroneggiarlo è modificarlo:
1. Aggiungi uno strumento `stato_ordini` (lista degli ordini aperti di un impianto) con il suo test.
2. Crea `prompts/sistema_v2.md`, cambia `versione_prompt` e confronta i due report di valutazione.
3. Aggiungi tre domande a `valutazioni/domande_rag.yaml` e guarda come cambia hit@4.

## 6. Limiti da dichiarare apertamente

Dati sintetici: le note sono estratte a caso, quindi le statistiche dei "casi simili" mostrano il meccanismo, non
correlazioni reali. Conversazioni in memoria (una sola replica). CMMS dimostrativo senza autenticazione.
