# Deploy su Google Cloud Run: configurazione una tantum

Cloud Run esegue i container senza gestire server e ha un piano gratuito mensile. Serve un account Google Cloud
con la fatturazione attiva (carta richiesta, ma per un progetto dimostrativo i costi restano normalmente a zero:
imposta comunque un **avviso di budget** a pochi euro).

Esegui questi comandi una volta sola, nel [Cloud Shell](https://shell.cloud.google.com) (ha già `gcloud`).

```bash
PROGETTO=il-tuo-progetto        # crealo da console.cloud.google.com
REGIONE=europe-west8            # Milano
gcloud config set project $PROGETTO

# 1. servizi necessari
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# 2. registro delle immagini Docker
gcloud artifacts repositories create assistente --repository-format=docker --location=$REGIONE

# 3. chiave del modello in Secret Manager (non finisce mai nel codice né nei log)
printf "LA_TUA_CHIAVE_GROQ" | gcloud secrets create groq-api-key --data-file=-

# 4. service account usato da GitHub Actions per il deploy
gcloud iam service-accounts create github-deploy
SA=github-deploy@$PROGETTO.iam.gserviceaccount.com
for ruolo in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding $PROGETTO --member=serviceAccount:$SA --role=$ruolo
done
# il servizio Cloud Run deve poter leggere il secret
NUM=$(gcloud projects describe $PROGETTO --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding groq-api-key \
  --member=serviceAccount:$NUM-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
gcloud iam service-accounts keys create chiave.json --iam-account=$SA
cat chiave.json    # copia il contenuto, poi cancella il file: rm chiave.json
```

Su GitHub, nel repository: **Settings → Secrets and variables → Actions**
- *Secrets* → `GCP_SA_KEY` = contenuto di `chiave.json`; `GROQ_API_KEY` = la chiave Groq (per la valutazione dell'agente)
- *Variables* → `GCP_PROJECT_ID` = il tuo progetto, `GCP_REGION` = `europe-west8`

Poi **Actions → Deploy su Google Cloud Run → Run workflow**. A fine esecuzione il riepilogo mostra l'URL pubblico.

> Miglioramento possibile: sostituire la chiave JSON con *Workload Identity Federation* (nessuna chiave da custodire).
