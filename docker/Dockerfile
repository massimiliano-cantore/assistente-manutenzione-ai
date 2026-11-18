# Un solo Dockerfile, due immagini (target):
#   docker build -f docker/Dockerfile --target cmms .        -> finto CMMS
#   docker build -f docker/Dockerfile --target assistente .  -> agente + API + interfaccia web

# --- 1. interfaccia TypeScript ------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. base Python comune ------------------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY app/ app/
COPY config/ config/
COPY prompts/ prompts/
COPY dati/ dati/
COPY scripts/ scripts/

# --- 3. finto CMMS --------------------------------------------------------------------------------------
FROM base AS cmms
USER app
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8001\")}/health')"
CMD ["sh", "-c", "uvicorn app.cmms.api:crea_app --factory --host 0.0.0.0 --port ${PORT:-8001}"]

# --- 4. assistente --------------------------------------------------------------------------------------
FROM base AS assistente
ENV FASTEMBED_CACHE_PATH=/app/modelli CARTELLA_INDICE=/app/indice
# il modello di embedding viene scaricato e l'indice costruito ORA, durante la build:
# il container parte in pochi secondi e non dipende da download a runtime
RUN python -m scripts.costruisci_indice && chown -R app:app /app/indice /app/modelli
COPY --from=frontend /fe/dist frontend/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8000\")}/api/salute')"
CMD ["sh", "-c", "uvicorn app.api:crea_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
