# Job de publicacao no Kafka (autenticado por Kerberos). A extracao de PDFs/OCR roda no host.
# O wheel do confluent-kafka nao traz GSSAPI no Linux: compila-se contra o librdkafka do Debian
# (que usa libsasl2 + GSSAPI). Versao fixada na mesma do librdkafka do Debian 12 (2.0.2).
FROM python:3.11-slim-bookworm

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential librdkafka-dev krb5-user libsasl2-modules-gssapi-mit \
 && pip install --no-cache-dir --no-binary confluent-kafka "confluent-kafka==2.0.2" "jsonschema>=4.23" \
 && apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ingestion/produtor.py ingestion/produtor.py
COPY ingestion/schema ingestion/schema
ENV PYTHONUNBUFFERED=1
CMD ["python", "ingestion/produtor.py", "--dir", "/data/processed"]
