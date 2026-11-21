# Contexto de build = raiz do repositorio (precisa de elastic/es_kerberos.py)
# gssapi (python) autentica no Elasticsearch por Kerberos/SPNEGO.
FROM python:3.11-slim-bookworm

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential libkrb5-dev krb5-user \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY elastic/ elastic/
COPY api/app api/app
WORKDIR /app/api

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
