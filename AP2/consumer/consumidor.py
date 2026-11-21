"""Consumidor Kafka -> Elasticsearch (RF08, RF09, RF10, RF11).

Garantias:
- Sem perda (RF09): offsets so sao confirmados DEPOIS da indexacao bem sucedida
  (at-least-once). Se o Elasticsearch estiver fora, o lote nao e confirmado e
  e tentado de novo; ao voltar, retoma exatamente do ultimo offset confirmado.
- Idempotencia (RF10): `_id` do documento = `id` da questao; reprocessar
  sobrescreve o mesmo documento, nunca duplica.
- DLQ (RF11): mensagem malformada, fora do esquema ou recusada pelo
  Elasticsearch (mapping) vai para `enade.questoes.dlq` sem parar o fluxo.
"""
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from confluent_kafka import Consumer, KafkaException, Producer, TopicPartition
from elasticsearch import helpers
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from jsonschema import Draft202012Validator

# permite rodar da raiz do repo ou dentro do container (/app)
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "elastic"))
from es_kerberos import criar_cliente  # noqa: E402
from indice import ALIAS, garantir_indice  # noqa: E402

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
TOPICO = os.getenv("TOPICO", "enade.questoes")
TOPICO_DLQ = os.getenv("TOPICO_DLQ", "enade.questoes.dlq")
GRUPO = os.getenv("GRUPO", "enade-indexador")
LOTE = int(os.getenv("LOTE", "100"))
ESQUEMA = RAIZ / "ingestion" / "schema" / "questao.schema.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("consumidor")
parar = False

# Metricas Prometheus (porta 9100): vazao, DLQ, latencia do bulk e lag do consumidor Kafka
M_INDEXADOS = Counter("consumidor_docs_indexados_total", "Documentos indexados no Elasticsearch")
M_DLQ = Counter("consumidor_dlq_total", "Mensagens enviadas para a DLQ")
M_BULK = Histogram("consumidor_bulk_segundos", "Duracao do bulk no Elasticsearch",
                   buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
M_LAG = Gauge("consumidor_lag_mensagens", "Lag total do grupo no topico de questoes")


def _sinal(*_):
    global parar
    parar = True


def seguranca_kafka():
    """Kerberos (SASL/GSSAPI) quando KAFKA_SASL_PRINCIPAL esta definido; senao conexao simples (dev)."""
    if not os.getenv("KAFKA_SASL_PRINCIPAL"):
        return {}
    return {"security.protocol": "SASL_PLAINTEXT", "sasl.mechanism": "GSSAPI",
            "sasl.kerberos.service.name": "kafka",
            "sasl.kerberos.principal": os.environ["KAFKA_SASL_PRINCIPAL"],
            "sasl.kerberos.keytab": os.environ["KAFKA_SASL_KEYTAB"]}


_redis = None


def invalidar_cache():
    """Politica de invalidacao (RF18): novos documentos mudam a versao das chaves do cache de busca.
    Opcional: sem REDIS_HOST o consumidor funciona normalmente; falha no Redis nunca bloqueia a indexacao."""
    global _redis
    host = os.getenv("REDIS_HOST")
    if not host:
        return
    try:
        if _redis is None:
            import redis
            _redis = redis.Redis(host=host, port=int(os.getenv("REDIS_PORT", "6379")),
                                 password=os.getenv("REDIS_PASSWORD") or None, socket_timeout=2)
        _redis.incr("cache:versao")
    except Exception as e:  # noqa: BLE001
        log.warning("nao foi possivel invalidar o cache (%s)", type(e).__name__)


def lag_total(consumer, topico):
    """Lag = fim do log - offset confirmado, somado nas particoes."""
    meta = consumer.list_topics(topico, timeout=10).topics[topico]
    tps = [TopicPartition(topico, p) for p in meta.partitions]
    total = 0
    for tp, comm in zip(tps, consumer.committed(tps, timeout=10)):
        _, alto = consumer.get_watermark_offsets(tp, timeout=10)
        base = comm.offset if comm.offset >= 0 else 0
        total += max(alto - base, 0)
    return total


def main():
    start_http_server(int(os.getenv("METRICS_PORT", "9100")))
    signal.signal(signal.SIGINT, _sinal)
    signal.signal(signal.SIGTERM, _sinal)

    es = criar_cliente(ES_URL, request_timeout=30, retry_on_timeout=True, max_retries=3)
    while True:  # espera o ES ficar disponivel
        try:
            if garantir_indice(es, os.getenv("ES_REPLICAS")):
                log.info("indice criado")
            break
        except Exception as e:  # noqa: BLE001
            log.warning("Elasticsearch indisponivel (%s); tentando de novo", type(e).__name__)
            time.sleep(3)
            if parar:
                return

    validador = Draft202012Validator(json.loads(ESQUEMA.read_text(encoding="utf-8")))
    consumer = Consumer({
        **seguranca_kafka(),
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GRUPO,
        "enable.auto.commit": False,          # commit manual apos indexar
        "auto.offset.reset": "earliest",
        "isolation.level": "read_committed",
    })
    dlq = Producer({**seguranca_kafka(), "bootstrap.servers": BOOTSTRAP, "acks": "all",
                    "enable.idempotence": True})
    consumer.subscribe([TOPICO])
    log.info("consumindo %s -> %s (grupo %s)", TOPICO, ALIAS, GRUPO)

    total_ok = total_dlq = 0
    t_ini, ultimo_log = time.time(), 0.0

    def enviar_dlq(msg, motivo):
        dlq.produce(TOPICO_DLQ, key=msg.key(), value=msg.value(),
                    headers=[("motivo", motivo[:300].encode()), ("origem", b"consumidor")])
        dlq.poll(0)

    while not parar:
        msgs = consumer.consume(num_messages=LOTE, timeout=1.0)
        if not msgs:
            continue
        acoes, por_id, rejeitadas = [], {}, 0
        for m in msgs:
            if m.error():
                if m.error().fatal():
                    raise KafkaException(m.error())
                log.warning("erro transitorio do Kafka (%s); o cliente reconecta sozinho", m.error().name())
                continue
            try:
                doc = json.loads(m.value())
                erros = list(validador.iter_errors(doc))
                if erros:
                    raise ValueError("esquema_invalido: " + erros[0].message)
            except Exception as e:  # noqa: BLE001
                enviar_dlq(m, f"{type(e).__name__}: {e}")
                rejeitadas += 1
                continue
            por_id[doc["id"]] = m  # mesmo id no lote: vale o ultimo
            acoes.append({"_op_type": "index", "_index": ALIAS, "_id": doc["id"], "_source": doc})

        # indexa; se o ES cair, repete o MESMO lote (nenhum offset foi confirmado)
        while not parar and acoes:
            try:
                with M_BULK.time():
                    ok, erros = helpers.bulk(es, acoes, raise_on_error=False, refresh=False)
                for er in erros:
                    item = er.get("index", {})
                    msg = por_id.get(item.get("_id"))
                    if msg is not None:
                        enviar_dlq(msg, "es_recusou: " + json.dumps(item.get("error", {}))[:250])
                        rejeitadas += 1
                total_ok += ok
                M_INDEXADOS.inc(ok)
                invalidar_cache()
                break
            except Exception as e:  # noqa: BLE001
                log.warning("falha ao indexar (%s); repetindo lote em 3s", type(e).__name__)
                time.sleep(3)
        else:
            if parar:
                break  # encerrando sem confirmar o lote em andamento

        dlq.flush(10)
        try:
            consumer.commit(asynchronous=False)  # so aqui o offset avanca
        except KafkaException as e:
            # Broker indisponivel: o commit fica para a proxima volta. Nada se perde, pois a indexacao e
            # idempotente (no pior caso o lote e reprocessado e sobrescreve os mesmos documentos).
            log.warning("commit adiado (%s)", e.args[0].name())
        total_dlq += rejeitadas
        M_DLQ.inc(rejeitadas)

        agora = time.time()
        if agora - ultimo_log > 2:
            ultimo_log = agora
            dt = agora - t_ini
            try:
                lag = lag_total(consumer, TOPICO)
                M_LAG.set(lag)
            except KafkaException as e:  # broker reiniciando: uma metrica nao pode derrubar o consumidor
                lag = -1
                log.warning("lag indisponivel (%s)", e.args[0].name())
            log.info("indexados=%d dlq=%d  %.1f docs/s  lag=%d",
                     total_ok, total_dlq, total_ok / dt if dt else 0, lag)

    consumer.close()
    dlq.flush(10)
    log.info("encerrado: indexados=%d dlq=%d", total_ok, total_dlq)


if __name__ == "__main__":
    main()
