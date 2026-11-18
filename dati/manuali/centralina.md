# Manuale di assistenza – Centraline di controllo accessi KYROS serie 408xx
famiglia: centralina

Documento sintetico per il progetto dimostrativo: KYROS ACCESS è un'azienda fittizia.

## La centralina non si accende
Misurare l'alimentazione in ingresso: 12-24 Vdc. Se la tensione è presente ma i led restano spenti, controllare il fusibile di protezione e il connettore di alimentazione CON1015. Se il circuito SCB1180 mostra componenti bruciati o piste interrotte va sostituito. Prima di rimontare verificare che l'alimentatore del cliente non superi i 26 V: le sovratensioni sono la causa più frequente dei circuiti bruciati.

## La centralina si riavvia da sola
Riavvii improvvisi indicano un'alimentazione instabile o un assorbimento eccessivo dei dispositivi collegati. Misurare la tensione durante l'apertura di una porta: se scende sotto 11 V l'alimentatore è sottodimensionato. Controllare anche i cavi CAV2210 verso le serrature: un cortocircuito intermittente causa riavvii. Se il problema persiste con alimentazione stabile, aggiornare il firmware alla versione V17.

## Circuito sporco o con segni di umidità
Polvere conduttiva e umidità creano dispersioni tra le piste. Pulire il circuito con alcool isopropilico e un pennello antistatico, asciugare e verificare al microscopio. Se ci sono piste corrose o interrotte sostituire il circuito SCB1180. Montare la scatola neutra SCA4471N con la guaina isolante GUA4420 nelle installazioni in locali umidi.

## Gli ingressi porta non rilevano l'apertura
Se la centralina non vede lo stato porta, verificare i sensori collegati: sensore magnetico SEN4420 o sensore reed SEN4425. Con il multimetro controllare che il contatto commuti avvicinando il magnete. Un sensore che non commuta va sostituito. Controllare anche il micro di antimanomissione MIC1195, che se aperto blocca gli ingressi.

## Aggiornamento firmware della centralina
Le centraline con firmware precedente alla V17 possono perdere la configurazione dopo un'interruzione di corrente. Collegare la centralina al PC con il cavo di servizio, salvare la configurazione, aggiornare alla V17 e ricaricare la configurazione salvata. Annotare la versione installata nella scheda di riparazione.
