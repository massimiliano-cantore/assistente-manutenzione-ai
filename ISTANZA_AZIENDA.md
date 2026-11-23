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
cartelle chiamate `old` sono ignorati. Per i microcontrollori **STM32** l'assistente ricava dal binario
(`.hex`, `.bin`, `.elf`), senza sorgente, come il firmware usa ogni pin (ingresso con pull-up, uscita, PWM,
seriale...) e lo incrocia con lo schema: strumento `firmware_scheda`.

Come funziona: il codice viene eseguito in un emulatore dall'avvio e si registra cosa scrive nei registri GPIO e
delle periferiche. Funziona con HAL, LL e codice a registri. Il risultato va in `firmware_analisi/` (una volta per
file).

Per passare dal nome della porta (es. `PA2`) al numero di pin serve la piedinatura del micro: viene presa dal
datasheet (chiave Mouser/Tavily) oppure si scrive a mano nella scheda in `prodotti.yaml`:

```yaml
- codice: OPR030
  mcu: {designator: U4, codice: STM32G031G4U6}     # facoltativo, se la BOM non lo dice
  piedinatura_mcu: {PA2: 8, PA3: 9, PA15: 22, PB6: 26, PB8: 28}
```

Prova da riga di comando: `python -m scripts.analizza_firmware percorso\file.hex --mcu STM32G031G4U6`

Limiti: PIC e AVR non ancora supportati; un pin analogico non si distingue da uno non usato.
Il firmware è proprietà dell'azienda: l'analisi richiede la sua autorizzazione.
Licenze: l'emulatore Unicorn è GPL-2.0 (va bene per uso interno; per distribuire il prodotto a terzi va valutato),
Capstone e intelhex sono BSD, pyelftools è di pubblico dominio.
