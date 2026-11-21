## Vazão de ingestão (Kafka para Elasticsearch)

| Documentos | Publicação (msg/s) | Até indexar tudo (s) | Vazão ponta a ponta (docs/s) | Bulk p50 (s) | Bulk p95 (s) | Lag máximo | Indexados |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 11150 | 839.8 | 228.1 | 48.9 | 0.37676056338028163 | 0.9277777777777776 | 9950.0 | 11150 |

## Falhas induzidas durante a ingestão

| Falha | Documentos | Indexados na falha | Duração da falha (s) | Recuperação total (s) | Indexados no fim | Perdidos | Reprocessados |
|---|---:|---:|---:|---:|---:|---:|---:|
| Consumidor morto à força (SIGKILL) | 11150 | 2300 | 19.4 | 180.2 | 11150 | **0** | 100 |
| Kafka parado | 11150 | 2300 | 43.8 | 241.0 | 11150 | **0** | - |
| Elasticsearch parado | 11150 | 2300 | 55.2 | 173.5 | 11150 | **0** | - |

