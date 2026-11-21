Rodadas: 3 (cada uma com os 4 cenários). Valores: mediana [mínimo a máximo] em ms.

| Cenário | p50 (ms) | p95 (ms) | p99 (ms) | Meta de referência | Rodadas que atingiram a meta |
|---|---:|---:|---:|---|:--:|
| Sem cache (10 VUs) | 133 [117 a 154] | 295 [263 a 358] | 411 [364 a 503] | p95 < 500 ms | 3 de 3 |
| Com cache (10 VUs) | 29 [28 a 33] | 61 [61 a 81] | 91 [85 a 115] | p95 < 50 ms | 0 de 3 |
| Misto 80/20 (10 VUs) | 37 [34 a 41] | 108 [94 a 125] | 205 [156 a 233] | p95 < 500 ms | 3 de 3 |
| Rampa 5 a 60 VUs, sem cache | 425 [400 a 462] | 1216 [1008 a 2211] | 1864 [1321 a 7146] | p95 < 2000 ms | 2 de 3 |

Vazão média por rodada: 136, 110, 131 req/s. Requisições por rodada: 45170, 36430, 43708. Taxa de erro HTTP: 0.00% (pior rodada).
