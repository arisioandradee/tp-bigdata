"""Experimentos de ingestao e resiliencia (RNF02, RNF04). Uso:

    python bench/experimentos.py vazao | falha-consumidor | falha-kafka | falha-es | todos

Cada experimento gera documentos sinteticos (copias dos reais, com ids `bXX...-<id original>`), publica no
Kafka pelo job `produtor` e acompanha a indexacao no Elasticsearch; no fim apaga os documentos sinteticos.
Como o `_id` e o id da questao, o numero de documentos no indice prova ausencia de perda e de duplicata.
Resultados: bench/resultados/experimentos.json e experimentos.md (+ vazao-lag.csv).
"""
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "bench" / "resultados"
ES = "http://127.0.0.1:9200"
PROM = "http://127.0.0.1:9090"
COPIAS = 10  # 10 x 1.115 = 11.150 documentos por experimento


def ler_env():
    e = {}
    for l in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in l and not l.startswith("#"):
            k, v = l.split("=", 1)
            e[k.strip()] = v.strip()
    return e


ENV = ler_env()
AUTH = "Basic " + base64.b64encode(f"elastic:{ENV['ELASTIC_PASSWORD']}".encode()).decode()


def sh(cmd, check=False, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, cwd=RAIZ)
    if check and r.returncode:
        raise RuntimeError(f"{cmd} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
    return (r.stdout or "") + (r.stderr or "")


def es(metodo, caminho, corpo=None, tentar=True):
    req = urllib.request.Request(ES + caminho, method=metodo, headers={"Authorization": AUTH, "Content-Type": "application/json"},
                                 data=json.dumps(corpo).encode() if corpo is not None else None)
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception:
        if not tentar:
            raise
        return None


def contar(prefixo):
    es("POST", "/enade-questoes/_refresh")
    r = es("POST", "/enade-questoes/_count", {"query": {"prefix": {"id": prefixo}}})
    return r["count"] if r else -1  # -1 = Elasticsearch indisponivel


def apagar(prefixo):
    es("POST", "/enade-questoes/_delete_by_query?refresh=true&conflicts=proceed", {"query": {"prefix": {"id": prefixo}}})


def prom(consulta):
    try:
        u = PROM + "/api/v1/query?query=" + urllib.parse.quote(consulta)
        r = json.load(urllib.request.urlopen(u, timeout=15))["data"]["result"]
        return float(r[0]["value"][1]) if r else None
    except Exception:
        return None


def prom_serie(consulta, t0, t1, passo=5):
    u = f"{PROM}/api/v1/query_range?query={urllib.parse.quote(consulta)}&start={t0}&end={t1}&step={passo}"
    r = json.load(urllib.request.urlopen(u, timeout=30))["data"]["result"]
    return [(float(t), float(v)) for t, v in r[0]["values"]] if r else []


def lag_grupo():
    """Lag somado do grupo do consumidor, lido do broker (kafka-consumer-groups)."""
    out = sh(["docker", "exec", "kafka", "/opt/kafka/bin/kafka-consumer-groups.sh", "--bootstrap-server",
              "kafka:29092", "--command-config", "/etc/kafka/jaas/admin.properties", "--describe",
              "--group", "enade-indexador"], timeout=120)
    total, achou = 0, False
    for l in out.splitlines():
        p = l.split()
        if len(p) >= 6 and p[0] == "enade-indexador" and p[1] == "enade.questoes" and p[5].isdigit():
            total += int(p[5]); achou = True
    return total if achou else None


def gerar(prefixo):
    pasta = RAIZ / "data" / "bench" / prefixo
    pasta.mkdir(parents=True, exist_ok=True)
    docs = [json.loads(l) for l in (RAIZ / "data" / "processed" / "questoes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    n = 0
    with (pasta / "questoes.jsonl").open("w", encoding="utf-8") as f:
        for k in range(COPIAS):
            for d in docs:
                f.write(json.dumps(dict(d, id=f"{prefixo}{k:02d}-{d['id']}"), ensure_ascii=False) + "\n")
                n += 1
    return pasta, n


def publicar(pasta):
    t0 = time.time()
    out = sh(["docker", "compose", "run", "--rm", "-v", f"{pasta}:/data/bench:ro", "produtor", "python",
              "ingestion/produtor.py", "--bootstrap", "kafka:29092", "--dir", "/data/bench"], timeout=1200)
    m = re.search(r"publicados: (\d+).*?([\d.]+) msg/s", out)
    return time.time() - t0, (int(m.group(1)) if m else None), (float(m.group(2)) if m else None)


def esperar(cond, timeout, passo=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return time.time() - t0
        time.sleep(passo)
    return None


def consumidor_ok():
    st = sh(["docker", "inspect", "consumer", "--format", "{{.State.Status}}|{{.RestartCount}}|{{.State.StartedAt}}"]).strip()
    return st


def preparar(prefixo):
    apagar(prefixo)
    esperar(lambda: lag_grupo() == 0, 120, 3)
    return gerar(prefixo)


# ---------------------------------------------------------------- experimentos
def vazao():
    pasta, n = preparar("bvz")
    ind0 = prom("consumidor_docs_indexados_total") or 0
    t0 = time.time()
    t_pub, pub, msgs = publicar(pasta)
    ate = esperar(lambda: contar("bvz") == n, 1200)
    t_total = time.time() - t0
    t1 = time.time()
    time.sleep(12)  # deixa o Prometheus raspar as ultimas amostras
    janela = int(t_total + 15)
    p50 = prom(f"histogram_quantile(0.5, sum by (le) (increase(consumidor_bulk_segundos_bucket[{janela}s])))")
    p95 = prom(f"histogram_quantile(0.95, sum by (le) (increase(consumidor_bulk_segundos_bucket[{janela}s])))")
    serie = prom_serie("consumidor_lag_mensagens", int(t0) - 5, int(t1) + 12)
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "vazao-lag.csv").write_text("segundos,lag\n" + "\n".join(f"{t - int(t0):.0f},{v:.0f}" for t, v in serie), encoding="utf-8")
    r = {"documentos": n, "publicacao_s": round(t_pub, 1), "publicacao_msg_s": msgs,
         "ate_indexar_tudo_s": round(t_total, 1), "vazao_ponta_a_ponta_docs_s": round(n / t_total, 1) if ate else None,
         "bulk_p50_s": p50, "bulk_p95_s": p95, "lag_maximo": max((v for _, v in serie), default=None),
         "indexados_final": contar("bvz"), "completo": ate is not None}
    apagar("bvz")
    return r


def _meio_da_ingestao(prefixo, fracao=0.2):
    pasta, n = preparar(prefixo)
    t0 = time.time()
    publicar(pasta)
    esperar(lambda: contar(prefixo) >= fracao * n, 300, 1)
    return n, t0


def falha_consumidor():
    n, t0 = _meio_da_ingestao("bfc")
    antes = contar("bfc")
    t_falha = time.time()
    sh(["docker", "kill", "consumer"])  # SIGKILL: nao ha commit nem encerramento limpo
    time.sleep(15)
    lag_parado = lag_grupo()
    ate_reiniciar = contar("bfc")
    t_volta = time.time()
    sh(["docker", "start", "consumer"])
    t_ok = esperar(lambda: contar("bfc") == n and lag_grupo() == 0, 900, 3)
    log = sh(["docker", "logs", "consumer", "--since", str(int(t_volta))])
    ind = [int(x) for x in re.findall(r"indexados=(\d+)", log)]
    processados = max(ind) if ind else None
    falta_no_reinicio = n - ate_reiniciar
    r = {"documentos": n, "indexados_no_momento_da_falha": antes, "lag_com_consumidor_parado": lag_parado,
         "tempo_parado_s": round(t_volta - t_falha, 1), "tempo_ate_recuperar_s": round(t_ok, 1) if t_ok else None,
         "indexados_final": contar("bfc"), "perdidos": n - contar("bfc"),
         "reprocessados_na_retomada": (processados - falta_no_reinicio) if processados is not None else None}
    apagar("bfc")
    return r


def falha_kafka():
    n, t0 = _meio_da_ingestao("bfk")
    antes = contar("bfk")
    ini = consumidor_ok()
    t_falha = time.time()
    sh(["docker", "stop", "kafka"])
    time.sleep(30)
    t_volta = time.time()
    sh(["docker", "start", "kafka"])
    saudavel = esperar(lambda: "healthy" in sh(["docker", "inspect", "kafka", "--format", "{{.State.Health.Status}}"]), 600, 3)
    t_ok = esperar(lambda: contar("bfk") == n and lag_grupo() == 0, 900, 3)
    fim = consumidor_ok()
    r = {"documentos": n, "indexados_no_momento_da_falha": antes, "kafka_parado_s": round(t_volta - t_falha, 1),
         "kafka_saudavel_apos_s": round(saudavel, 1) if saudavel else None,
         "tempo_ate_recuperar_s": round(t_ok, 1) if t_ok else None, "indexados_final": contar("bfk"),
         "perdidos": n - contar("bfk"), "consumidor_antes": ini, "consumidor_depois": fim,
         "consumidor_reiniciou": ini.split("|")[2] != fim.split("|")[2]}
    apagar("bfk")
    return r


def falha_es():
    n, t0 = _meio_da_ingestao("bfe")
    antes = contar("bfe")
    ini = consumidor_ok()
    t_falha = time.time()
    sh(["docker", "stop", "elasticsearch"])
    time.sleep(40)
    lag_na_queda = lag_grupo()
    t_volta = time.time()
    sh(["docker", "start", "elasticsearch"])
    pronto = esperar(lambda: contar("bfe") >= 0, 600, 3)
    t_ok = esperar(lambda: contar("bfe") == n and lag_grupo() == 0, 900, 3)
    fim = consumidor_ok()
    r = {"documentos": n, "indexados_no_momento_da_falha": antes, "elasticsearch_parado_s": round(t_volta - t_falha, 1),
         "lag_durante_a_queda": lag_na_queda, "elasticsearch_voltou_apos_s": round(pronto, 1) if pronto else None,
         "tempo_ate_recuperar_s": round(t_ok, 1) if t_ok else None, "indexados_final": contar("bfe"),
         "perdidos": n - contar("bfe"), "consumidor_reiniciou": ini.split("|")[2] != fim.split("|")[2]}
    apagar("bfe")
    return r


EXPERIMENTOS = {"vazao": vazao, "falha-consumidor": falha_consumidor, "falha-kafka": falha_kafka, "falha-es": falha_es}


def main():
    alvo = sys.argv[1] if len(sys.argv) > 1 else "todos"
    nomes = list(EXPERIMENTOS) if alvo == "todos" else [alvo]
    RES.mkdir(parents=True, exist_ok=True)
    arq = RES / "experimentos.json"
    todos = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    for nome in nomes:
        print(f"[{datetime.now():%H:%M:%S}] {nome} ...", flush=True)
        todos[nome] = EXPERIMENTOS[nome]()
        todos[nome]["executado_em"] = datetime.now().isoformat(timespec="seconds")
        arq.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(todos[nome], ensure_ascii=False, indent=2), flush=True)
    print(f"[{datetime.now():%H:%M:%S}] fim")


if __name__ == "__main__":
    main()
