# Usare l'assistente con la documentazione di un'azienda

Lo stesso codice funziona in due modi:

| | Demo (KYROS) | Azienda |
|---|---|---|
| Dati | archivio, manuali e CMMS **sintetici** nel repository | documentazione reale in una cartella **fuori dal repository** |
| Si attiva con | niente (è il default) | variabile `DATI_AZIENDA=<cartella>` |
| Strumenti | manuali, casi simili, SQL, CMMS | schede, componenti, collegamenti, percorso dei segnali, datasheet, disegni evidenziati, istruzioni |
| Prompt | `prompts/sistema_v2.md` | `prompts/azienda_v1.md` (metodo di diagnosi guasti) |

## 1. La cartella dei documenti

**Con molti prodotti, una sottocartella per prodotto:** non scrivere prodotti.yaml a mano, generalo:

```
python -m scripts.scansiona_documenti C:\percorso\produzione1
```

Lo script (gira tutto in locale) trova i PDF Altium e le BOM in ogni sottocartella, unisce schema e montaggio
della stessa scheda, propone i collegamenti tra le schede (connettori che portano segnali con lo stesso nome sugli
stessi pin) e scrive `prodotti.yaml` più un rapporto `scansione.txt` con quello che manca. Controlla i
collegamenti proposti: sono suggerimenti.

**Con pochi documenti** puoi anche scriverlo a mano:

```
documentazione-azienda/          <- MAI dentro il repository, MAI su GitHub
├── prodotti.yaml                <- descrive schede, file e collegamenti
├── MONTAGGIO_SCHEDA_MADRE.pdf         <- PDF esportati da Altium (schemi o montaggi)
├── SCHEMA_MODULO_RADIO.pdf
├── BOM_SCHEDA_MADRE.xls <- distinte base (xls, xlsx o csv)
├── documenti/                   <- istruzioni e manuali (PDF o Markdown), facoltativo
└── datasheet/                   <- creata da sola: piedinature già estratte (cache)
```

`prodotti.yaml`:

```yaml
schede:
  - codice: MADRE
    nome: Scheda madre
    netlist: MONTAGGIO_SCHEDA_MADRE.pdf      # PDF Altium con segnalibri: da qui si ricava la netlist esatta
    bom: BOM_SCHEDA_MADRE.xls
  - codice: RADIO
    nome: Modulo radio 433 MHz
    netlist: SCHEMA_MODULO_RADIO.pdf
    componenti:                        # integrazioni a mano quando manca la BOM
      U1: {valore: NRF905, descrizione: "Transceiver 433 MHz"}
prodotti:
  - nome: Centralina XYZ
    schede: [MADRE, RADIO]
    collegamenti:
      - {da: MADRE.J4, a: RADIO.J1}      # pin uguali; altrimenti aggiungi  mappa: {1: 16, 2: 15}
```

Formati letti oggi: PDF esportati da Altium (netlist dai segnalibri, posizioni dalle etichette invisibili) e BOM
Excel/CSV con colonne riconosciute per nome. Il modello dati è indipendente dal CAD: per KiCad, IPC-D-356 o ODB++
basta aggiungere un importatore in `app/elettrico/`.

## 2. Riservatezza: dove vanno i dati

- **Documenti:** restano nella cartella sul PC o sul server aziendale. Il repository li ignora (`.gitignore`).
- **Modello linguistico:** con `LLM_PROVIDER=groq` schemi e collegamenti vengono inviati a un servizio esterno.
  Per documentazione riservata usa un **modello in locale** con Ollama: `LLM_PROVIDER=ollama`,
  `LLM_MODEL=qwen3:14b` (serve una GPU con circa 12 GB, oppure un modello più piccolo, meno preciso).
  In alternativa serve l'autorizzazione dell'azienda per il servizio esterno.
- **Datasheet:** a Mouser e alla ricerca web arrivano solo i **codici dei componenti** (es. `NRF905`), mai i documenti.

## 3. Chiavi per i datasheet

- `MOUSER_API_KEY`: gratuita, dal proprio account su mouser.it → *My Mouser* → *APIs* → *Search API*.
- `TAVILY_API_KEY` (facoltativa, ripiego quando Mouser non trova): gratuita su tavily.com.

La prima volta che chiedi la piedinatura di un componente il datasheet viene scaricato e la tabella dei pin estratta;
poi resta in `datasheet/` e non si cerca più. Se il codice esatto non si trova, si cerca un compatibile
(es. `STM32F401VDT6` → `STM32F401`) e la risposta lo dice.

## 4. Avvio (Windows, PowerShell)

```
cd assistente-manutenzione-ai
.venv\Scripts\activate
$env:DATI_AZIENDA = "C:\documentazione-azienda"
$env:LLM_PROVIDER = "ollama"; $env:LLM_MODEL = "qwen3:14b"      # oppure groq con GROQ_API_KEY
$env:MOUSER_API_KEY = "..."
uvicorn app.api:crea_app --factory --port 8000
```

Poi http://localhost:8000. Domanda di prova: *"la centralina non comunica più tramite RF, cosa potrebbe essere?"*

## 6. Firmware

Lo scanner elenca il firmware di ogni prodotto (binari, sorgenti, progetti) e lo associa alle schede; i file nelle
cartelle chiamate `old` sono ignorati. L'assistente ricava dal binario, senza sorgente, come il firmware usa ogni
pin (ingresso con pull-up, uscita, PWM, seriale...) e lo incrocia con lo schema: strumento `firmware_scheda`.

| Microcontrollore | File | Metodo |
|---|---|---|
| STM32 (ARM Cortex-M) | .hex, .bin, .elf | emulazione dall'avvio: si registra cosa scrive nei registri GPIO e delle periferiche (HAL, LL o registri) |
| PIC16 midrange (16F6xx, 16F8xx, 12F6xx) | .hex | analisi statica delle scritture su TRIS, PORT, OPTION_REG e periferiche |
| PIC18 | .hex | analisi statica su TRIS, LAT, INTCON2/WPUB e periferiche |
| AVR (ATmega) | .hex | analisi statica su DDR, PORT (pull-up) e periferiche |

Il risultato va in `firmware_analisi/` (una volta per file). L'architettura si riconosce dal micro sullo schema o,
se manca, dagli indirizzi del .hex (gli AVR partono da 0 come altri: lì serve il codice del micro, `mcu` nella
scheda in `prodotti.yaml` o `--mcu`).

Rapporto su tutti i prodotti: `python -m scripts.analizza_firmware --tutti C:\percorso\produzione1` scrive
`firmware_report.txt`: per ogni scheda la versione più recente analizzata e incrociata con lo schema, per il
firmware senza scheda una riga per serie (le versioni dello stesso firmware sono raggruppate).

Per passare dal nome della porta (es. `PA2`) al numero di pin serve la piedinatura del micro: viene presa dal
datasheet (chiave Mouser/Tavily) oppure si scrive a mano nella scheda in `prodotti.yaml`:

```yaml
- codice: OPR030
  mcu: {designator: U4, codice: STM32G031G4U6}     # facoltativo, se la BOM non lo dice
  piedinatura_mcu: {PA2: 8, PA3: 9, PA15: 22, PB6: 26, PB8: 28}
```

Prova da riga di comando: `python -m scripts.analizza_firmware percorso\file.hex --mcu STM32G031G4U6`

Limiti: per gli STM32 un pin analogico non si distingue da uno non usato; per PIC e AVR l'analisi è statica
(dice cosa il programma configura in almeno un punto, non lo stato in un istante). PIC16F1xxx (enhanced) non ancora.
Il firmware è proprietà dell'azienda: l'analisi richiede la sua autorizzazione.
Licenze: l'emulatore Unicorn è GPL-2.0 (va bene per uso interno; per distribuire il prodotto a terzi va valutato),
Capstone e intelhex sono BSD, pyelftools è di pubblico dominio.

## 7. Storico delle riparazioni (da Document AI)

Le schede di riparazione lette e confermate con **Document AI** (progetto `document-ai-prodotto`) diventano lo
storico dei guasti dell'assistente. Le tre parti sono collegate da file, così ognuna si può usare anche da sola:

```
schede RESO (PDF/foto) ─► Document AI ─► conferma operatore ─► export JSON ─► DATI_AZIENDA\storico\ ─► assistente
                                                                docai-scheda/1   (un file per scheda)
```

1. In Document AI: sezione **Esporta** → "Prepara lo zip JSON" (e scompatta in `storico\`), oppure
   `python elabora.py ... --esporta-json C:\percorso\produzione1\storico`
2. Controllo del collegamento: `python -m scripts.riepilogo_storico C:\percorso\produzione1` scrive
   `storico_report.txt` (riparazioni per prodotto, componenti più sostituiti, seriali tornati più volte).
3. Gli articoli che non si riconoscono da soli si associano a mano in `storico\storico.yaml`:
   ```yaml
   articoli:
     "40806": "Elettromaniglie - seriale 03 000"     # codice articolo -> nome del prodotto in prodotti.yaml
   campi:                                            # facoltativo: nomi dei campi diversi da quelli soliti
     note: [difetto_riscontrato]
   ```
   In alternativa, nel prodotto in `prodotti.yaml`: `articoli: ["40806", "40810"]`.

All'avvio l'assistente carica lo storico e ha due strumenti in più: `storico_riparazioni` (casi simili a un sintomo,
storia di un seriale) e `statistiche_guasti` (componenti più sostituiti, cause annotate, firmware, seriali che
tornano). Quando le note citano un componente dello schema (es. "sostituito K1"), il riferimento viene collegato
alla scheda del prodotto. `/api/salute` mostra quante riparazioni ha caricato.

## 8. Ricerca nei documenti dei prodotti

Una pagina tipo motore di ricerca per tutti i file di Produzione1 (PDF, Word, Excel, testi): **http://localhost:8000/documenti**.
Si scrive un articolo, un codice, un componente o una parte di parola e si ottengono tre riquadri:
**Istruzioni** (per ogni documento l'ultima versione, con le precedenti a parte), **Schemi** e **Altri documenti**,
ognuno con titolo, data e link che apre il file.

L'indice si costruisce con `python -m scripts.indicizza_documenti C:\percorso\Produzione1` (lo fa anche
`prepara_opera.bat`): la prima volta legge tutti i file, poi solo quelli nuovi o modificati. Sta in
`Produzione1\indice_documenti.db`. Anche l'assistente lo usa (strumento `cerca_documenti`).

Come si decide la categoria: *schemi* sono i PDF riconosciuti dallo scanner come schemi Altium e i file con
"sch", "schema", "asm" nel nome; *istruzioni* i file con "istruz", "manual", "installaz", "montaggio", "guida" nel
nome o nella cartella; il resto è *altri*. La data è la prima trovata nel documento (es. il cartiglio dello schema),
altrimenti quella di modifica del file. Le versioni dello stesso documento si riconoscono dal nome senza
"rev", "v1.2", date e copie.

## 9. Meccanica: assiemi, tavole e particolari SolidWorks

Lo scanner legge i file SolidWorks del PDM (.SLDASM, .SLDDRW, .SLDPRT) **senza SolidWorks**:

    python -m scripts.scansiona_meccanica C:\OPERA_PDM C:\percorso\Produzione1

Per ogni codice ricava denominazione, date, stato, autore, categoria (dalla cartella del PDM: A commerciali,
E elettronica, F particolari a disegno, G grezzi, L gruppi, V viteria), la **distinta** della tavola con le
descrizioni, i sottogruppi e i gruppi che lo contengono, gli articoli di prodotto citati nella denominazione
(es. 2560030) e le immagini di anteprima (esploso e 3D). Le cartelle X_ (progettazione), di prova e "old" si
saltano. Tutto va in `Produzione1\meccanica\` (indice.json, img\), mai nel repository.

**Funzionamento meccanico.** Con `--descrivi N` l'AI guarda esploso, 3D e distinta di N assiemi (prima quelli
con parti elettriche) e propone come funzionano: descrizione, catena (es. scheda → bobina → nucleo → leva →
catenaccio → molla, sensore di fine corsa) e guasti tipici con i controlli. Vanno in
`Produzione1\meccanica\funzionamento.yaml` come `da_confermare`: il tecnico li corregge e mette `confermato`.
Le voci confermate non vengono più riscritte. Costo indicativo: circa 0,03 $ ad assieme.

L'assistente usa tutto con lo strumento `scheda_meccanica` (codice disegno, articolo di prodotto o parole):
le parti elettriche della distinta (bobina, sensori, scheda SP...) si agganciano alle schede degli schemi, così
la diagnosi segue la catena completa, elettrica e meccanica. Anche la ricerca documenti trova i file SolidWorks
per codice, denominazione e righe di distinta, e li apre con SolidWorks.

Limiti: dai file nativi non si leggono geometria, vincoli e quantità. Per i particolari senza file proprio nel
PDM la descrizione viene dalla riga di distinta del gruppo che li contiene.
