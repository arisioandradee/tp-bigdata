"""Cache de buscas no Redis (RF18).

- Chave: busca:{versao}:{sha1(parametros)}. Os parametros incluem pagina, tamanho e se o perfil e
  restrito (estudante), entao a chave identifica exatamente uma resposta.
- Valor: a RESPOSTA FINAL ja serializada em JSON (bytes). Um acerto so le do Redis e devolve, sem
  revalidar nem reserializar (essa etapa custava a maior parte do tempo de um acerto: ver bench/).
- Expiracao: TTL (CACHE_TTL, padrao 300 s).
- Invalidacao: o consumidor faz INCR em `cache:versao` apos indexar; a versao nova muda todas as chaves
  e as antigas expiram sozinhas pelo TTL. A versao e relida do Redis no maximo a cada 1 s por processo
  (uma indexacao pode levar ate 1 s para valer na busca). Tambem ha rota manual de invalidacao.
- Se o Redis cair, a API segue funcionando sem cache (degradacao controlada).
"""
import hashlib
import json
import logging
import time

from prometheus_client import Counter

from . import config
from .clientes import r, r_bin

log = logging.getLogger("cache")
HITS = Counter("api_cache_hits_total", "Buscas atendidas pelo cache Redis")
MISSES = Counter("api_cache_misses_total", "Buscas que precisaram ir ao Elasticsearch")

_versao_local = [0.0, "0"]  # [instante da leitura, valor]
ATUALIZACAO_VERSAO_S = 1.0


def _versao() -> str:
    agora = time.monotonic()
    if agora - _versao_local[0] > ATUALIZACAO_VERSAO_S:
        _versao_local[1] = r.get("cache:versao") or "0"
        _versao_local[0] = agora
    return _versao_local[1]


def chave(params: dict) -> str:
    h = hashlib.sha1(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"busca:{_versao()}:{h}"


def obter(params: dict):
    """Retorna (chave, bytes ou None)."""
    try:
        k = chave(params)
        v = r_bin.get(k)
        r.incr("metricas:cache:hit" if v else "metricas:cache:miss")
        (HITS if v else MISSES).inc()
        return k, v
    except Exception as e:  # noqa: BLE001
        log.warning("cache indisponivel (%s)", type(e).__name__)
        return None, None


def gravar(k, conteudo: bytes):
    if not k:
        return
    try:
        r_bin.setex(k, config.CACHE_TTL, conteudo)
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao gravar cache (%s)", type(e).__name__)


def invalidar() -> str:
    v = str(r.incr("cache:versao"))
    _versao_local[0], _versao_local[1] = time.monotonic(), v
    return v


def estatisticas() -> dict:
    hit = int(r.get("metricas:cache:hit") or 0)
    miss = int(r.get("metricas:cache:miss") or 0)
    total = hit + miss
    return {"hits": hit, "misses": miss, "consultas": total,
            "hit_rate": round(hit / total, 4) if total else None,
            "versao": r.get("cache:versao") or "0", "ttl_s": config.CACHE_TTL}
