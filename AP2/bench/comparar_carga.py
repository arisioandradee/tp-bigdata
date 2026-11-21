"""Compara as rodadas do teste de carga e gera graficos para o relatorio.

Rodadas (em bench/resultados/): antes (carga-antes.json), otimizacao do cache (carga-otimizacao-cache.json)
e final, com indice de posicoes (carga.json). Saidas: comparacao-carga.md e latencia-busca.png.

Uso: python bench/comparar_carga.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = Path(__file__).resolve().parent / "resultados"
RODADAS = [("Antes", "carga-antes.json"), ("Cache da resposta final", "carga-otimizacao-cache.json"),
           ("Final (indice com offsets)", "carga.json")]
CEN = [("sem_cache", "Sem cache\n(10 VUs)"), ("com_cache", "Com cache\n(10 VUs)"),
       ("misto", "Misto 80/20\n(10 VUs)"), ("estresse", "Rampa 5 a 60 VUs\nsem cache")]
METAS = {"sem_cache": 500, "com_cache": 50, "misto": 500, "estresse": 2000}
dados = {nome: json.loads((RES / arq).read_text(encoding="utf-8")) for nome, arq in RODADAS}

# tabela
linhas = ["| Cenário | Métrica | " + " | ".join(n for n, _ in RODADAS) + " | Meta |", "|---|---|" + "---:|" * len(RODADAS) + "---:|"]
for chave, rotulo in CEN:
    for metrica, nome in (("med", "p50"), ("p(95)", "p95"), ("p(99)", "p99")):
        vals = " | ".join(f"{dados[n][chave][metrica]:.0f} ms" for n, _ in RODADAS)
        meta = f"p95 < {METAS[chave]} ms" if metrica == "p(95)" else ""
        linhas.append(f"| {rotulo.replace(chr(10), ' ')} | {nome} | {vals} | {meta} |")
(RES / "comparacao-carga.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

# grafico: p50/p95/p99 por cenario e rodada
cores = ["#b5b5ad", "#6aa6a0", "#0f5e57"]
fig, eixos = plt.subplots(1, 4, figsize=(15, 4.2), sharey=False)
for ax, (chave, rotulo) in zip(eixos, CEN):
    larg = 0.26
    for j, (nome, _) in enumerate(RODADAS):
        ys = [dados[nome][chave][m] for m in ("med", "p(95)", "p(99)")]
        ax.bar([i + (j - 1) * larg for i in range(3)], ys, larg, label=nome, color=cores[j])
    ax.axhline(METAS[chave], color="#a3262a", linestyle="--", linewidth=1, label="meta de p95")
    ax.set_xticks(range(3)); ax.set_xticklabels(["p50", "p95", "p99"])
    ax.set_title(rotulo.replace("\n", " "), fontsize=10); ax.set_ylabel("latência (ms)")
    ax.set_yscale("log"); ax.grid(axis="y", alpha=0.25)
eixos[0].legend(fontsize=7, loc="upper left")
fig.suptitle("Latência de GET /questoes (escala logarítmica), k6 dentro da rede do Docker", fontsize=11)
fig.tight_layout(); fig.savefig(RES / "latencia-busca.png", dpi=160)
print("\n".join(linhas)); print("grafico:", RES / "latencia-busca.png")
