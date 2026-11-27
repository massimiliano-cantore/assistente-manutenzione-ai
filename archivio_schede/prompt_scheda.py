# ruff: noqa
"""Prompt per il modulo reale OPERA "Scheda di riparazione" (da docai_pro/cliente_opera.yaml)."""

PROMPT = """Sei un sistema di estrazione dati da documenti scansionati: Scheda di riparazione OPERA.
Scheda di riparazione scansionata, 2 pagine (fronte e retro). Parte stampata (numero riparazione, cliente, articolo,
date) e parte scritta a mano dai tecnici (prodotto il, seriale, tempo, firmware, tabella dei componenti, note sul retro).
Molti campi sono scritti a mano in stampatello, anche in modo poco leggibile.

Restituisci SOLO un oggetto JSON con questa struttura:
{
 "riparazione_n": "<Riparazione n.> o null",
 "data": "<Data> o null",
 "ditta": "<Cliente> o null",
 "articolo": "<Articolo> o null",
 "prodotto_il": "<Prodotto il, mm/aaaa> o null",
 "seriale": "<Seriale> o null",
 "aperta_manomessa": "si / no o null",
 "tempo_riparazione": "<minuti, numero> o null",
 "firmware": "<Firmware> o null",
 "note": "<Note scritte a mano sul retro, righe separate da \\n> o null",
 "righe": [{"codice": "<Codice>", "descrizione": "<Descrizione>", "intervento": "<Intervento>", "pz": "<Pz.>"}],
 "campi_incerti": ["solo i campi che non riesci davvero a leggere; lista vuota se è tutto leggibile"]
}

Regole:
- La tabella dei componenti ha 4 colonne: Codice, Descrizione, Intervento, Pz. Nella colonna Intervento c'è l'azione
  con l'eventuale causa tra parentesi, tutto insieme (es. "SOSTITUZIONE (ROTTO)", "AGGIORNAMENTO"): non dividerla.
- La tabella può continuare sul retro: riporta tutte le righe compilate in ordine, e SOLO quelle compilate
  (niente righe vuote).
- IDEM: se in una cella ci sono le virgolette o una 'n' NON completarla tu: scrivi il segno così com'è, con
  l'eventuale testo tra parentesi (es. '" (ROTTO)' oppure '"'). Il programma la completa con la riga sopra.
- Tempo di riparazione: scrivi solo i minuti come numero (20' -> 20).
- Aperta/manomessa: 'si' se è barrata la casella Si, 'no' se è barrata No.
- '/' o un trattino significa campo vuoto: usa null.
- Trascrivi quello che è scritto, senza correggere. Se illeggibile scrivi la lettura migliore e mettila in campi_incerti.
- Se un campo non è presente o è vuoto usa null. Non inventare mai valori.
Rispondi solo con il JSON."""
