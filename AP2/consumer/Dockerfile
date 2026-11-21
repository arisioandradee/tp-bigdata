# Contexto de build = raiz do repositorio (precisa de elastic/ e ingestion/schema/)
# confluent-kafka compilado contra o librdkafka do Debian para ter SASL/GSSAPI (Kerberos).
# gssapi (python) e usado para autenticar no Elasticsearch por SPNEGO.
FROM python:3.11-slim-bookworm

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential librdkafka-dev libkrb5-dev krb5-user libsasl2-modules-gssapi-mit \
 && pip install --no-cache-dir --no-binary confluent-kafka "confluent-kafka==2.0.2" \
 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY consumer/requirements.txt consumer/requirements.txt
RUN pip install --no-cache-dir -r consumer/requirements.txt

COPY consumer/ consumer/
COPY elastic/ elastic/
COPY ingestion/schema/ ingestion/schema/

ENV PYTHONUNBUFFERED=1
CMD ["python", "consumer/consumidor.py"]
