"""Configuracao via variaveis de ambiente (com leitura opcional do .env da raiz, so em dev)."""
import os
from pathlib import Path


def _carregar_env():
    arq = Path(__file__).resolve().parents[2] / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_carregar_env()

# 127.0.0.1 (e nao "localhost"): no Windows "localhost" tenta IPv6 primeiro e adiciona ~2 s por conexao
ES_URL = os.getenv("ES_URL", "http://127.0.0.1:9200")
ALIAS = os.getenv("ES_ALIAS", "enade-questoes")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "60"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
CARRINHO_TTL = int(os.getenv("CARRINHO_TTL", "86400"))
AUTH_MODE = os.getenv("AUTH_MODE", "dev")  # "dev" (usuarios locais) | "ldap"
LDAP_URL = os.getenv("LDAP_URL", "ldap://127.0.0.1:389")
LDAP_BASE = os.getenv("LDAP_BASE", "dc=enade,dc=local")
DEV_USUARIOS = {
    "estudante": (os.getenv("DEV_ESTUDANTE_SENHA", ""), "estudante"),
    "professor": (os.getenv("DEV_PROFESSOR_SENHA", ""), "professor"),
}
