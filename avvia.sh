#!/usr/bin/env bash
# Avvia l'assistente in locale o in GitHub Codespaces: interfaccia + API su http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ -z "$GROQ_API_KEY" ] && ! grep -qs '^GROQ_API_KEY=.\+' .env; then
  echo "Manca la chiave: copia .env.example in .env e inserisci GROQ_API_KEY (oppure impostala come secret di Codespaces)."
  exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "Compilo l'interfaccia (solo la prima volta)..."
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi
echo "Avvio su http://localhost:8000 (la prima volta scarica il modello di embedding, circa 1 minuto)"
exec uvicorn app.api:crea_app --factory --host 0.0.0.0 --port 8000
