# Assistente tecnico AI – configurazioni per il cliente

*Aggiornato al 26/11/2026*

## In sintesi

L'assistente si può offrire in due configurazioni. Gran parte del sistema (ricerca documenti, scansione schemi e BOM, analisi firmware, storico riparazioni) **non usa modelli AI** e gira in azienda su un PC d'ufficio in entrambe. Cambia solo dove gira il modello che fa la chat di diagnosi e la lettura delle schede scritte a mano.

| | **Cloud** (consigliata) | **Tutto in azienda** |
|---|---|---|
| Dove gira il modello | Claude (Anthropic), via API o AWS Bedrock / Google Vertex in data center UE | Server con GPU nella rete del cliente |
| Dati che escono | Solo la domanda e gli estratti necessari alla risposta | Nessuno |
| Qualità diagnosi | Massima | Buona su casi comuni, inferiore su guasti complessi |
| Lettura schede a mano | Buona | Sensibilmente peggiore: più correzione manuale |
| Hardware | PC d'ufficio o piccolo server, nessuna GPU | Server con GPU (vedi sotto) |
| Costo iniziale hardware | ~0 € (riuso PC esistente) | ~1.500–2.000 € (base) / ~4.500–5.500 € (avanzato) |
| Costo d'uso | A consumo: centesimi per domanda, ~0,08 $ per scheda letta | Solo elettricità e manutenzione |
| Aggiornamento modello | Automatico | Manuale (si scarica il nuovo modello) |

## Cosa gira comunque in azienda

- Ricerca nei documenti (istruzioni, schemi, altri documenti) con accesso utenti e registro accessi
- Scansione schemi Altium e BOM, catalogo prodotti
- Analisi firmware (STM32, PIC, AVR)
- Storico riparazioni e statistiche guasti

Nessuno di questi usa un modello AI né manda dati fuori.

## Configurazione Cloud

- **Modello:** Claude Sonnet per la diagnosi, Haiku come riserva più economica.
- **Riservatezza:** via API Anthropic i dati non vengono usati per addestrare i modelli. Per chi richiede che i dati restino in Europa, Claude è disponibile su AWS Bedrock e Google Vertex in regioni UE (Francoforte, Irlanda, Parigi, Stoccolma; Belgio su Vertex). L'API diretta di Anthropic invece non ha una regione di elaborazione UE.
- **Hardware:** il PC o server che già ospita i documenti; i tecnici usano il browser.
- **Costo:** a consumo, con tetto di spesa mensile impostabile.

## Configurazione Tutto in azienda

Un solo server per tutta l'azienda; i tecnici si collegano dal browser.

| | **Base** | **Avanzato** |
|---|---|---|
| Scheda video | RTX 5060 Ti 16 GB | RTX 5090 32 GB |
| Prezzo indicativo scheda (IVA incl.) | ~450–600 € | ~2.900–3.100 € |
| Resto del PC | ~1.000–1.400 € (CPU recente, 32–64 GB RAM, SSD 1–2 TB) | ~1.600–2.400 € (CPU recente, 64–128 GB RAM, SSD 2 TB, alimentatore 1000 W+) |
| Totale indicativo | ~1.500–2.000 € | ~4.500–5.500 € |
| Modello consigliato | Qwen 3.5/3.6 9B–14B | Qwen 3.6 27B o 35B-A3B |
| Adatto a | Chat di diagnosi su casi comuni, pochi utenti contemporanei | Diagnosi più affidabile e uso degli strumenti (firmware, storico, documenti), più utenti |
| Schede a mano | Sconsigliato | Possibile, con verifica manuale |

Oggi la famiglia Qwen è quella più affidabile tra i modelli locali per l'uso degli strumenti, che è ciò che serve all'assistente per consultare catalogo, firmware e storico. Sotto i ~9 miliardi di parametri l'affidabilità cala molto.

**Senza GPU** (solo processore) il modello locale è troppo lento per un uso reale.

## Soluzione intermedia

Tutto in azienda tranne la chat di diagnosi, che usa Claude in regione UE e riceve solo la domanda e i pochi estratti necessari, mai i documenti interi. È il compromesso che di solito unisce qualità massima e riservatezza accettabile.

## Note

- I prezzi hardware sono indicativi (novembre 2026), al dettaglio in Italia, e oscillano molto: da riverificare a ogni preventivo.
- Il passaggio tra le configurazioni non richiede modifiche al software: si cambia il fornitore del modello nella configurazione (`LLM_PROVIDER` nel `.env`).
- I modelli locali migliorano rapidamente: la configurazione Avanzato va rivalutata ogni 6–12 mesi.
