"""Gera docs/volume-acervo.md (tabela de volume do acervo) a partir de data/processed/.

Uso: python ingestion/gerar_volume.py
"""
import json
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
proc = RAIZ / "data" / "processed"


def ler(nome):
    return [json.loads(l) for l in (proc / nome).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    docs, rejeitadas = ler("questoes.jsonl"), ler("rejeitadas.jsonl")
    rej = defaultdict(int)
    for x in rejeitadas:
        rej[x["id"].rsplit("-", 2)[0]] += 1  # chave: {ano}-{slug}
    linhas = defaultdict(lambda: {"obj": 0, "disc": 0, "anul": 0, "midia": 0})
    for x in docs:
        grau = "" if x["grau"] == "Bacharelado" else f" ({x['grau']})"
        k = (x["ano"], x["area"], x["curso"] + grau, x["id"].rsplit("-", 2)[0])
        L = linhas[k]
        L["obj" if x["tipo_questao"] == "objetiva" else "disc"] += 1
        L["anul"] += x["anulada"]
        L["midia"] += x["tem_midia_nao_textual"]
    chaves = {k[3] for k in linhas}
    so_rejeitadas = sorted(k for k in rej if k not in chaves)  # provas inteiras que foram para a DLQ

    md = ["# Volume do acervo processado", "",
          "Gerado por `python ingestion/gerar_volume.py` a partir de `data/processed/`. "
          "Cada linha é uma prova de um curso em um ano.", "",
          "| Ano | Área | Curso | Objetivas | Discursivas | Anuladas | Com figura/tabela | Rejeitadas (DLQ) |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for k in sorted(linhas):
        L = linhas[k]
        md.append(f"| {k[0]} | {k[1]} | {k[2]} | {L['obj']} | {L['disc']} | {L['anul']} | {L['midia']} | {rej.get(k[3], 0)} |")
    soma = lambda f: sum(f(v) for v in linhas.values())
    md.append(f"| | | **Total** | **{soma(lambda v: v['obj'])}** | **{soma(lambda v: v['disc'])}** | "
              f"**{soma(lambda v: v['anul'])}** | **{soma(lambda v: v['midia'])}** | **{len(rejeitadas)}** |")
    md += ["", f"Documentos indexados: {len(docs)} | provas: {len(linhas)} | cursos distintos: "
               f"{len({k[2] for k in linhas})} | áreas: {len({k[1] for k in linhas})} | anos: "
               f"{sorted({k[0] for k in linhas})}"]
    if so_rejeitadas:
        md += ["", "Provas inteiras mantidas fora do índice por não passarem no controle de qualidade "
                   "(OCR de provas em duas colunas com cobertura insuficiente): "
               + ", ".join(so_rejeitadas) + "."]
    md += ["", "O acervo do INEP tem 1.691 PDFs (provas, gabaritos e padrões de resposta, 2004 a 2025); "
               "aqui estão apenas as provas já extraídas."]
    (RAIZ / "docs").mkdir(exist_ok=True)
    (RAIZ / "docs" / "volume-acervo.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"docs/volume-acervo.md: {len(linhas)} provas, {len(docs)} documentos, {len(rejeitadas)} rejeitadas")


if __name__ == "__main__":
    main()
