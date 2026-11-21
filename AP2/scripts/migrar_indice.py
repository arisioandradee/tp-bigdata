"""Migra o indice para um novo mapping sem tirar a busca do ar (reindexacao + troca atomica do alias).

Uso (da raiz do projeto, com a stack no ar):
    python scripts/migrar_indice.py enade-questoes-v1 enade-questoes-v2 [--apagar-antigo]

1. cria o indice novo com settings/mapping de elastic/mapping.json;
2. copia os documentos (reindex) e confere as contagens;
3. move o alias `enade-questoes` do antigo para o novo em uma unica operacao atomica
   (as buscas nunca veem os dois indices nem nenhum).
Usa o usuario administrativo `elastic` (senha em .env), pois e uma tarefa de manutencao.
"""
import sys
from pathlib import Path

from elasticsearch import Elasticsearch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "elastic"))
import indice  # noqa: E402


def senha():
    for l in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if l.startswith("ELASTIC_PASSWORD="):
            return l.split("=", 1)[1].strip()
    sys.exit("ELASTIC_PASSWORD nao encontrado no .env")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    antigo, novo = sys.argv[1], sys.argv[2]
    es = Elasticsearch("http://127.0.0.1:9200", basic_auth=("elastic", senha()), request_timeout=300)
    if not es.indices.exists(index=antigo):
        sys.exit(f"indice {antigo} nao existe")
    if es.indices.exists(index=novo):
        sys.exit(f"indice {novo} ja existe; apague-o antes de migrar de novo")
    cfg = indice.carregar_config()
    es.indices.create(index=novo, settings=cfg["settings"], mappings=cfg["mappings"])
    r = es.reindex(source={"index": antigo}, dest={"index": novo}, wait_for_completion=True, refresh=True)
    n_antigo = es.count(index=antigo)["count"]
    n_novo = es.count(index=novo)["count"]
    print(f"reindexados: {r['total']} | contagem antigo={n_antigo} novo={n_novo} | falhas={len(r['failures'])}")
    if n_antigo != n_novo or r["failures"]:
        sys.exit("contagens divergentes; o alias NAO foi trocado")
    es.indices.update_aliases(actions=[{"remove": {"index": antigo, "alias": indice.ALIAS}},
                                       {"add": {"index": novo, "alias": indice.ALIAS}}])
    print(f"alias {indice.ALIAS}: {antigo} -> {novo} (troca atomica)")
    if "--apagar-antigo" in sys.argv:
        es.indices.delete(index=antigo)
        print(f"indice {antigo} apagado")


if __name__ == "__main__":
    main()
