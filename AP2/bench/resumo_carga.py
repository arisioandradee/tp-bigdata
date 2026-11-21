"""Resume as rodadas do teste de carga (k6) em tabela Markdown e grafico.

Le bench/resultados/k6-resumo-r1.json, r2, r3... (ou k6-resumo.json se houver uma so) e gera:
  carga.md   : mediana e variacao (minimo a maximo) das rodadas, por cenario
  carga.json : os mesmos numeros em JSON
  latencia-busca.png : grafico de p50, p95 e p99 por cenario (barras = mediana, linhas = minimo a maximo)

Uso: python bench/resumo_carga.py
"""
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = Path(__file__).resolve().parent / "resultados"
CEN = [("sem_cache", "Sem cache (10 VUs)", 500), ("com_cache", "Com cache (10 VUs)", 50),
       ("misto", "Misto 80/20 (10 VUs)", 500), ("estresse", "Rampa 5 a 60 VUs, sem cache", 2000)]
METRICAS = [("med", "p50"), ("p(95)", "p95"), ("p(99)", "p99")]

arqs = sorted(RES.glob("k6-resumo-r[0-9]*.json")) or [RES / "k6-resumo.json"]
rodadas = [json.loads(a.read_text(encoding="utf-8")) for a in arqs]


def vals(t):
    return t["values"] if "values" in t else t


linhas = [f"Rodadas: {len(rodadas)} (cada uma com os 4 cenários). Valores: mediana [mínimo a máximo] em ms.", "",
          "| Cenário | p50 (ms) | p95 (ms) | p99 (ms) | Meta de referência | Rodadas que atingiram a meta |",
          "|---|---:|---:|---:|---|:--:|"]
saida, extremos = {}, {}
for chave, nome, meta in CEN:
    por_rodada = [vals(r["metrics"][f"http_req_duration{{scenario:{chave}}}"]) for r in rodadas]
    cel, saida[chave] = [], {}
    for k, rot in METRICAS:
        xs = [v[k] for v in por_rodada]
        med, lo, hi = statistics.median(xs), min(xs), max(xs)
        cel.append(f"{med:.0f} [{lo:.0f} a {hi:.0f}]")
        saida[chave][rot] = {"mediana": round(med, 1), "min": round(lo, 1), "max": round(hi, 1)}
        extremos[(chave, rot)] = (med, lo, hi)
    ok = sum(1 for v in por_rodada if v["p(95)"] < meta)
    saida[chave]["rodadas_que_atingiram_a_meta"] = f"{ok} de {len(por_rodada)}"
    linhas.append(f"| {nome} | {cel[0]} | {cel[1]} | {cel[2]} | p95 < {meta} ms | {ok} de {len(por_rodada)} |")

tot = [vals(r["metrics"]["http_reqs"]) for r in rodadas]
falha = [vals(r["metrics"]["http_req_failed"])["rate"] for r in rodadas]
linhas += ["", f"Vazão média por rodada: {', '.join(f'{t['rate']:.0f}' for t in tot)} req/s. "
               f"Requisições por rodada: {', '.join(f'{t['count']:.0f}' for t in tot)}. "
               f"Taxa de erro HTTP: {max(falha) * 100:.2f}% (pior rodada)."]
(RES / "carga.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
(RES / "carga.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

fig, eixos = plt.subplots(1, 4, figsize=(15, 4.4))
for ax, (chave, nome, meta) in zip(eixos, CEN):
    topo = max(extremos[(chave, rot)][2] for _, rot in METRICAS)
    for i, (k, rot) in enumerate(METRICAS):
        med, lo, hi = extremos[(chave, rot)]
        ax.bar(i, med, 0.55, color="#0f5e57")
        ax.vlines(i, lo, hi, color="#1c1c1a", linewidth=1.6)
        ax.text(i, hi + topo * 0.025, f"{med:.0f} ms", ha="center", va="bottom", fontsize=8)
    ax.axhline(meta, color="#a3262a", linestyle="--", linewidth=1, label=f"meta de p95: {meta} ms")
    ax.set_ylim(0, max(topo, meta) * 1.5)  # folga para rotulos e legenda; escala linear (a base e zero)
    ax.set_xticks(range(3)); ax.set_xticklabels([r for _, r in METRICAS])
    ax.set_title(nome, fontsize=10); ax.set_ylabel("latência (ms)")
    ax.ticklabel_format(style="plain", axis="y")
    ax.grid(axis="y", alpha=0.25); ax.legend(fontsize=7, loc="upper left")
fig.suptitle(f"Latência de GET /questoes: mediana de {len(rodadas)} rodada(s), barras de erro = mínimo a máximo (k6 na rede do Docker)", fontsize=10)
fig.tight_layout(); fig.savefig(RES / "latencia-busca.png", dpi=160)
print("\n".join(linhas))
print("grafico:", RES / "latencia-busca.png")
