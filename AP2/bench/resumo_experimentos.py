"""Monta bench/resultados/experimentos.md a partir de experimentos.json (vazao e falhas induzidas).

Uso: python bench/resumo_experimentos.py
"""
import json
from pathlib import Path

RES = Path(__file__).resolve().parent / "resultados"
d = json.loads((RES / "experimentos.json").read_text(encoding="utf-8"))
md = []

v = d.get("vazao")
if v:
    md += ["## Vazão de ingestão (Kafka para Elasticsearch)", "",
           "| Documentos | Publicação (msg/s) | Até indexar tudo (s) | Vazão ponta a ponta (docs/s) | Bulk p50 (s) | Bulk p95 (s) | Lag máximo | Indexados |",
           "|---:|---:|---:|---:|---:|---:|---:|---:|",
           f"| {v['documentos']} | {v['publicacao_msg_s']} | {v['ate_indexar_tudo_s']} | {v['vazao_ponta_a_ponta_docs_s']} | "
           f"{v['bulk_p50_s']} | {v['bulk_p95_s']} | {v['lag_maximo']} | {v['indexados_final']} |", ""]

linhas = []
for chave, nome in (("falha-consumidor", "Consumidor morto à força (SIGKILL)"), ("falha-kafka", "Kafka parado"),
                    ("falha-es", "Elasticsearch parado")):
    e = d.get(chave)
    if not e:
        continue
    queda = e.get("tempo_parado_s") or e.get("kafka_parado_s") or e.get("elasticsearch_parado_s")
    linhas.append(f"| {nome} | {e['documentos']} | {e['indexados_no_momento_da_falha']} | {queda} | "
                  f"{e.get('tempo_ate_recuperar_s')} | {e['indexados_final']} | **{e['perdidos']}** | "
                  f"{e.get('reprocessados_na_retomada', '-')} |")
if linhas:
    md += ["## Falhas induzidas durante a ingestão", "",
           "| Falha | Documentos | Indexados na falha | Duração da falha (s) | Recuperação total (s) | Indexados no fim | Perdidos | Reprocessados |",
           "|---|---:|---:|---:|---:|---:|---:|---:|", *linhas, ""]
(RES / "experimentos.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
