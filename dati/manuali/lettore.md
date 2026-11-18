# Manuale di assistenza – Lettori di badge KYROS serie 312xx
famiglia: lettore

Documento sintetico per il progetto dimostrativo: KYROS ACCESS è un'azienda fittizia.

## Il lettore non legge i badge
Verificare che il led del lettore si accenda: se è spento il problema è nell'alimentazione o nel cavo CAV2210. Se il led è acceso ma i badge non vengono letti, la causa più comune è la bobina d'antenna BOB5510 danneggiata o scollegata. Misurare la resistenza della bobina: un circuito aperto richiede la sostituzione. Provare sempre con un badge di test nuovo per escludere badge smagnetizzati.

## Il lettore legge solo a distanza ravvicinata
Una distanza di lettura ridotta sotto i 2 cm indica un'antenna fuori sintonia o un'installazione su superficie metallica. Verificare il distanziale previsto per le superfici metalliche. Se l'installazione è corretta, sostituire la bobina BOB5510 e ricontrollare la distanza di lettura, che deve essere tra 4 e 6 cm.

## Il lettore non comunica con la centralina
Controllare il cavo dati e il connettore CON1015: inversioni di polarità e connettori ossidati sono le cause più frequenti. Verificare l'indirizzo del lettore sul bus: due lettori con lo stesso indirizzo si bloccano a vicenda. Se il cablaggio è corretto e il lettore non risponde, sostituire il circuito SCB1180.

## Il lettore è stato manomesso o il guscio è aperto
Il micro di antimanomissione MIC1195 segnala l'apertura del guscio. Se il micro è rotto la centralina riceve un allarme continuo. Sostituire il micro e la scatola neutra SCA4471N se danneggiata, poi verificare che l'allarme rientri a guscio chiuso.

## Nessun difetto riscontrato al banco
Quando il lettore funziona correttamente al banco, il problema è quasi sempre nell'impianto del cliente: lunghezza eccessiva del cavo, alimentazione insufficiente o disturbi. Annotare nella scheda le prove eseguite e restituire il lettore con una nota per l'installatore sulle verifiche da fare in campo.
