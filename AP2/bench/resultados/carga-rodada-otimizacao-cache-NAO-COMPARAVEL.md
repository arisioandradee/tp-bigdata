| Cenário | p50 (ms) | p90 (ms) | p95 (ms) | p99 (ms) | máx (ms) | Meta de referência | Atingiu |
|---|---:|---:|---:|---:|---:|---|:--:|
| Sem cache (10 VUs) | 286 | 572 | 676 | 925 | 1498 | p95 < 500 ms | não |
| Com cache (10 VUs) | 27 | 48 | 59 | 91 | 260 | p95 < 50 ms | não |
| Misto 80/20 (10 VUs) | 31 | 69 | 92 | 173 | 425 | p95 < 500 ms | sim |
| Rampa 5 a 60 VUs, sem cache | 381 | 698 | 810 | 1045 | 1757 | p95 < 2000 ms | sim |

Total: 46901 requisições em 335 s (139.9 req/s em média); taxa de erro HTTP: 0.00%.
