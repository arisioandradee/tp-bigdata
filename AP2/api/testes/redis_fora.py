"""Teste de degradacao: o que acontece com a API quando o Redis cai e quando volta.

Uso (da raiz do projeto, com a stack no ar; o script para e reinicia SO o container `redis`):
    python api/testes/redis_fora.py

Esperado: com o Redis parado a busca continua respondendo (HTTP 200, cache=False) em dezenas de ms; carrinho e
metricas do cache respondem 503 imediato; /health/ready informa "degradado" (503). Ao voltar, tudo normaliza.
A senha de desenvolvimento do professor vem do .env.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE = "http://localhost:8080/api"
ESPERADO = {  # fase -> {rota: status}
    "no ar": {"busca": 200, "carrinho": 200, "metricas": 200, "ready": 200},
    "parado": {"busca": 200, "carrinho": 503, "metricas": 503, "ready": 503},
    "de volta": {"busca": 200, "carrinho": 200, "metricas": 200, "ready": 200},
}
ROTAS = {"busca": "/questoes?q=etica&tamanho=5", "carrinho": "/carrinho", "metricas": "/metricas/cache",
         "ready": "/health/ready"}


def env(chave):
    for l in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if l.startswith(chave + "="):
            return l.split("=", 1)[1].strip()


def chamar(metodo, rota, dados=None, cab=None):
    req = urllib.request.Request(BASE + rota, data=dados, headers=cab or {}, method=metodo)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as x:
            return x.status, json.load(x), (time.time() - t) * 1000
    except urllib.error.HTTPError as e:
        return e.code, None, (time.time() - t) * 1000


def fase(nome, espera_s=0):
    time.sleep(espera_s)
    s, corpo, _ = chamar("POST", "/auth/token", urllib.parse.urlencode(
        {"username": "professor1", "password": env("LDAP_PROFESSOR_SENHA")}).encode())
    cab = {"Authorization": "Bearer " + corpo["access_token"]}
    falhas = 0
    for rota, caminho in ROTAS.items():
        st, c, ms = chamar("GET", caminho, cab=cab)
        ok = st == ESPERADO[nome][rota] and ms < 2000
        extra = f" cache={c.get('cache')}" if rota == "busca" and c else ""
        print(f"[{'OK ' if ok else 'ERRO'}] redis {nome:9} {rota:9} HTTP {st} {ms:6.0f} ms{extra}")
        falhas += not ok
    return falhas


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=RAIZ, check=True, capture_output=True)


if __name__ == "__main__":
    falhas = fase("no ar")
    compose("stop", "redis")
    try:
        falhas += fase("parado", 8)    # a sonda do disjuntor detecta a queda em ate ~6 s
        falhas += fase("parado", 15)   # continua rapido: nenhuma requisicao espera pelo Redis
    finally:
        compose("start", "redis")
    falhas += fase("de volta", 10)
    print("\ntudo certo" if not falhas else f"\n{falhas} verificacoes falharam")
    sys.exit(1 if falhas else 0)
