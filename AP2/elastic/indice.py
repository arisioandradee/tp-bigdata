"""Criacao idempotente do indice `enade-questoes-v1` (alias `enade-questoes`)."""
import json
from pathlib import Path

from elasticsearch import Elasticsearch

AQUI = Path(__file__).resolve().parent
INDICE = "enade-questoes-v3"
ALIAS = "enade-questoes"


def carregar_config():
    cfg = json.loads((AQUI / "mapping.json").read_text(encoding="utf-8"))
    regras = [l.strip() for l in (AQUI / "sinonimos.txt").read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.lstrip().startswith("#")]
    cfg["settings"]["analysis"]["filter"]["sinonimos"]["synonyms"] = regras
    return cfg


def garantir_indice(es: Elasticsearch, replicas=None):
    if es.indices.exists(index=INDICE):
        if not es.indices.exists_alias(name=ALIAS):
            es.indices.put_alias(index=INDICE, name=ALIAS)
        return False
    cfg = carregar_config()
    if replicas is not None:
        cfg["settings"]["number_of_replicas"] = int(replicas)
    es.indices.create(index=INDICE, settings=cfg["settings"], mappings=cfg["mappings"])
    es.indices.put_alias(index=INDICE, name=ALIAS)
    return True


if __name__ == "__main__":
    import os
    es = Elasticsearch(os.getenv("ES_URL", "http://localhost:9200"))
    print("criado" if garantir_indice(es) else "ja existia", INDICE)
