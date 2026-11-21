| Cenário | p50 (ms) | p90 (ms) | p95 (ms) | p99 (ms) | máx (ms) | Meta de referência | Atingiu |
|---|---:|---:|---:|---:|---:|---|:--:|
| Sem cache (10 VUs) | 669 | 1299 | 1524 | 2247 | 2875 | p95 < 500 ms | não |
| Com cache (10 VUs) | 66 | 145 | 179 | 243 | 389 | p95 < 50 ms | não |
| Misto 80/20 (10 VUs) | 63 | 180 | 272 | 530 | 1253 | p95 < 500 ms | sim |
| Rampa 5 a 60 VUs, sem cache | 764 | 1606 | 1901 | 2477 | 3506 | p95 < 2000 ms | sim |

Total: 20098 requisições em 336 s (59.8 req/s em média); taxa de erro HTTP: 0.00%.
