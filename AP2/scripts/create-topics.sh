#!/bin/bash
# Cria os topicos do pipeline (idempotente), autenticando por Kerberos (kafka-admin).
set -e
BIN=/opt/kafka/bin
BS=kafka:29092
CFG=/etc/kafka/jaas/admin.properties
P=${TOPIC_PARTITIONS:-3}

for t in enade.questoes enade.questoes.dlq; do
  $BIN/kafka-topics.sh --bootstrap-server "$BS" --command-config "$CFG" --create --if-not-exists \
    --topic "$t" --partitions "$P" --replication-factor 1
done

echo "Topicos:"
$BIN/kafka-topics.sh --bootstrap-server "$BS" --command-config "$CFG" --list
