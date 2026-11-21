| Cenário | p50 (ms) | p90 (ms) | p95 (ms) | p99 (ms) | máx (ms) | Meta de referência | Atingiu |
|---|---:|---:|---:|---:|---:|---|:--:|
| Sem cache (10 VUs) | 353 | 808 | 1095 | 1507 | 2010 | p95 < 500 ms | não |
| Com cache (10 VUs) | 65 | 152 | 206 | 324 | 604 | p95 < 50 ms | não |
| Misto 80/20 (10 VUs) | 77 | 193 | 268 | 575 | 1463 | p95 < 500 ms | sim |
| Rampa 5 a 60 VUs, sem cache | 1032 | 1828 | 2078 | 2576 | 4518 | p95 < 2000 ms | não |

Total: 18460 requisições em 335 s (55.2 req/s em média); taxa de erro HTTP: 0.00%.
