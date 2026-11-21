"""Configura a seguranca do Elasticsearch (idempotente): papeis, mapeamento Kerberos e senha do Kibana.

Cada principal Kerberos recebe o MENOR privilegio necessario:
  consumidor@ENADE.LOCAL -> enade_indexer (cria indice/alias e escreve em enade-questoes*)
  api@ENADE.LOCAL        -> enade_reader  (somente leitura em enade-questoes*)
"""
import os
import sys
import time

from elasticsearch import ApiError, Elasticsearch, NotFoundError

URL = os.getenv("ES_URL", "http://elasticsearch:9200")
SENHA = os.environ["ELASTIC_PASSWORD"]
REALM = os.getenv("KRB_REALM", "ENADE.LOCAL")

PAPEIS = {
    "enade_indexer": {
        "cluster": ["monitor"],
        "indices": [{"names": ["enade-questoes*"],
                     "privileges": ["create_index", "index", "create", "write", "read",
                                    "view_index_metadata", "manage"]}],
    },
    "enade_reader": {
        "cluster": ["monitor"],
        "indices": [{"names": ["enade-questoes*"], "privileges": ["read", "view_index_metadata"]}],
    },
    "enade_monitor": {  # usado pelo elasticsearch-exporter (Prometheus): somente metricas
        "cluster": ["monitor"],
        "indices": [{"names": ["*"], "privileges": ["monitor", "view_index_metadata"],
                    "allow_restricted_indices": True}],  # _all/_stats inclui indices internos; so metricas
    },
}
MAPEAMENTO = {"enade_kerberos_consumidor": ("consumidor", "enade_indexer"),
              "enade_kerberos_api": ("api", "enade_reader")}


def main():
    es = Elasticsearch(URL, basic_auth=("elastic", SENHA), request_timeout=30)
    for _ in range(60):
        try:
            es.security.authenticate()  # so responde quando o indice de seguranca esta disponivel
            break
        except Exception as e:  # noqa: BLE001
            print("aguardando Elasticsearch:", type(e).__name__)
            time.sleep(3)
    else:
        sys.exit("Elasticsearch indisponivel")

    # O realm Kerberos exige licenca trial/platinum. Em volume novo a trial e gerada no 1o start
    # (xpack.license.self_generated.type=trial); em volume antigo (licenca basic) inicia-se aqui.
    # Em cluster novo, GET /_license devolve 404 por alguns segundos (a trial ainda esta sendo gerada).
    lic = {"type": "basic", "status": "ausente"}
    for _ in range(60):
        try:
            lic = es.license.get()["license"]
            break
        except NotFoundError:
            print("aguardando a licenca ser gerada")
            time.sleep(3)
    if lic["type"] == "basic":
        es.license.post_start_trial(acknowledge=True)
        print("licenca trial iniciada (30 dias)")
    else:
        print("licenca:", lic["type"], lic["status"])

    for nome, corpo in PAPEIS.items():
        es.security.put_role(name=nome, **corpo)
        print("papel", nome)
    for nome, (principal, papel) in MAPEAMENTO.items():
        es.security.put_role_mapping(name=nome, enabled=True, roles=[papel], rules={"all": [
            {"field": {"realm.name": "kerb1"}},
            {"field": {"username": f"{principal}@{REALM}"}}]})
        print("mapeamento", f"{principal}@{REALM}", "->", papel)
    es.security.put_user(username="exporter", password=os.environ["ES_EXPORTER_PASSWORD"],
                         roles=["enade_monitor"], full_name="Prometheus exporter")
    print("usuario exporter (enade_monitor)")
    try:
        es.security.change_password(username="kibana_system", password=os.environ["KIBANA_PASSWORD"])
        print("senha do kibana_system definida")
    except ApiError as e:
        print("kibana_system:", e)


if __name__ == "__main__":
    main()
