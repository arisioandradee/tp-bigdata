import sys
import time
from pathlib import Path

import redis

from . import config

# es_kerberos.py fica em elastic/ (na raiz do repo; em /app/elastic no container)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "elastic"))
from es_kerberos import criar_cliente  # noqa: E402

es = criar_cliente(config.ES_URL, request_timeout=15, retry_on_timeout=True, max_retries=2)
_args = dict(host=config.REDIS_HOST, port=config.REDIS_PORT, password=config.REDIS_PASSWORD,
             socket_timeout=2, socket_connect_timeout=2)

PAUSA_REDIS_S = 15.0  # tempo sem tentar o Redis depois de uma falha de conexao
_redis_ate = [0.0]    # instante (monotonic) ate o qual o disjuntor fica aberto


class RedisComDisjuntor(redis.Redis):
    """Cliente Redis com disjuntor: quando o Redis cai, a resolucao de nome/conexao pode demorar ~10 s por chamada
    (a busca faz varias). Depois da primeira falha, as chamadas seguintes falham na hora por PAUSA_REDIS_S segundos
    e a API segue sem cache (busca) ou responde 503 (carrinho), em vez de travar cada requisicao."""

    def execute_command(self, *args, **kwargs):
        if time.monotonic() < _redis_ate[0]:
            raise redis.ConnectionError("Redis indisponivel (disjuntor aberto)")
        try:
            return super().execute_command(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError):
            _redis_ate[0] = time.monotonic() + PAUSA_REDIS_S
            raise


r = RedisComDisjuntor(decode_responses=True, **_args)       # contadores, versao, carrinho (texto)
r_bin = RedisComDisjuntor(decode_responses=False, **_args)  # respostas em cache (bytes)


def _sonda():
    """Verifica o Redis a cada 3 s em segundo plano e mantem o disjuntor: nenhuma requisicao espera pelo Redis
    caido (a falha de conexao leva ~40 s). Se o ping nao responde em 3 s, abre; ao responder, fecha."""
    import threading
    sonda = redis.Redis(**_args)
    while True:
        resultado = []
        t = threading.Thread(target=lambda: resultado.append(_ping(sonda)), daemon=True)
        t.start()
        t.join(3)
        if resultado and resultado[0]:
            _redis_ate[0] = 0.0
        else:
            _redis_ate[0] = time.monotonic() + 8.0
        time.sleep(3)


def _ping(cli):
    try:
        return bool(cli.ping())
    except Exception:  # noqa: BLE001
        return False


import threading as _t  # noqa: E402
_t.Thread(target=_sonda, daemon=True, name="sonda-redis").start()
