"""Produtor Kafka (RF07, RF09, RF10, RF11).

Le data/processed/questoes.jsonl e publica em `enade.questoes`.
Registros rejeitados pelo extrator ou invalidos no esquema vao para
`enade.questoes.dlq`, com o motivo nos headers.

- chave da mensagem = id do documento (mesma questao -> mesma particao, em ordem)
- acks=all + enable.idempotence=true (sem duplicatas por retry do produtor)
- idempotencia ponta a ponta: o id e deterministico e sera o _id no Elasticsearch

Uso: python produtor.py [--bootstrap localhost:9092] [--dir ../data/processed]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from confluent_kafka import Producer
from jsonschema import Draft202012Validator

TOPICO = "enade.questoes"
TOPICO_DLQ = "enade.questoes.dlq"
ESQUEMA = Path(__file__).parent / "schema" / "questao.schema.json"


def seguranca_kafka():
    """Kerberos (SASL/GSSAPI) quando KAFKA_SASL_PRINCIPAL esta definido; senao conexao simples (dev)."""
    if not os.getenv("KAFKA_SASL_PRINCIPAL"):
        return {}
    return {"security.protocol": "SASL_PLAINTEXT", "sasl.mechanism": "GSSAPI",
            "sasl.kerberos.service.name": "kafka",
            "sasl.kerberos.principal": os.environ["KAFKA_SASL_PRINCIPAL"],
            "sasl.kerberos.keytab": os.environ["KAFKA_SASL_KEYTAB"]}


def ler_jsonl(caminho):
    if not caminho.exists():
        return
    for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        if linha.strip():
            yield n, linha


def main():
    raiz = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--dir", default=str(raiz / "data" / "processed"))
    a = ap.parse_args()
    pasta = Path(a.dir)

    validador = Draft202012Validator(json.loads(ESQUEMA.read_text(encoding="utf-8")))
    prod = Producer({
        **seguranca_kafka(),
        "bootstrap.servers": a.bootstrap,
        "acks": "all",
        "enable.idempotence": True,
        "compression.type": "lz4",
        "linger.ms": 20,
    })
    cont = {"ok": 0, "dlq": 0, "erro_entrega": 0}

    def entregue(err, msg):
        if err:
            cont["erro_entrega"] += 1
            print("falha de entrega:", err, file=sys.stderr)

    def para_dlq(chave, valor, motivo, origem):
        prod.produce(TOPICO_DLQ, key=chave, value=valor,
                     headers=[("motivo", motivo.encode()), ("origem", origem.encode())],
                     on_delivery=entregue)
        cont["dlq"] += 1

    t0 = time.time()
    for n, linha in ler_jsonl(pasta / "questoes.jsonl"):
        try:
            doc = json.loads(linha)
        except json.JSONDecodeError as e:
            para_dlq(f"linha-{n}", linha.encode(), f"json_malformado: {e}", "questoes.jsonl")
            continue
        erros = sorted(validador.iter_errors(doc), key=lambda e: e.path)
        if erros:
            para_dlq(doc.get("id", f"linha-{n}"), linha.encode(),
                     "esquema_invalido: " + erros[0].message[:200], "questoes.jsonl")
            continue
        prod.produce(TOPICO, key=doc["id"], value=json.dumps(doc, ensure_ascii=False).encode(),
                     on_delivery=entregue)
        cont["ok"] += 1
        prod.poll(0)

    for n, linha in ler_jsonl(pasta / "rejeitadas.jsonl"):
        rej = json.loads(linha)
        para_dlq(rej["id"], linha.encode(), rej["motivo"], "extrator")
        prod.poll(0)

    prod.flush(30)
    dt = time.time() - t0
    total = cont["ok"] + cont["dlq"]
    print(f"publicados: {cont['ok']} em {TOPICO} | DLQ: {cont['dlq']} em {TOPICO_DLQ} | "
          f"falhas de entrega: {cont['erro_entrega']} | {total / dt:.1f} msg/s")
    return 1 if cont["erro_entrega"] else 0


if __name__ == "__main__":
    sys.exit(main())
