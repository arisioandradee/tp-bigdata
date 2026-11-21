"""Competencia de Formacao Geral inferida para as provas anteriores a 2025 (RF05).

So a prova de 2025 traz a matriz oficial (competencia, habilidade, objetos). Para as questoes de Formacao Geral
dos outros anos, um classificador Naive Bayes multinomial (Python puro) treinado nas questoes de 2025 sugere a
competencia (C01/C02). O resultado vai marcado com fonte_metadados="inferido" e a acuracia medida por
leave-one-out e gravada em data/processed/classificacao.json. Objetos de conhecimento NAO sao inferidos
(acuracia medida ~13%, abaixo de qualquer uso util); competencias de Componente Especifico tambem ficam ausentes.
"""
import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PARADAS = set("para como pela pelo pelas pelos entre sobre mais menos esta este estes estas essa esse essas esses "
              "isso isto aquele aquela quando onde qual quais ainda assim cada tambem sendo foram sera seja ser "
              "dos das uma uns umas com por que nao nos nas seu sua seus suas ele ela eles elas sao tem pode "
              "podem apenas outro outra outros outras todo toda todos todas texto textos opcao assinale correto "
              "afirmacao afirmacoes questao".split())


def tokens(txt):
    t = unicodedata.normalize("NFD", txt.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return [w[:7] for w in re.findall(r"[a-z]{4,}", t) if w not in PARADAS]  # radical grosseiro


def texto_da_questao(q):
    alts = " ".join((q.get("alternativas") or {}).values())
    return f"{q.get('texto_base') or ''} {q.get('enunciado') or ''} {alts}"


class NaiveBayes:
    def __init__(self, amostras):
        self.cont = defaultdict(Counter)
        self.docs = Counter()
        self.vocab = set()
        for toks, y in amostras:
            self.docs[y] += 1
            self.cont[y].update(toks)
            self.vocab.update(toks)
        self.total = {y: sum(c.values()) for y, c in self.cont.items()}

    def prever(self, toks, fora=None):
        melhor, pontos = None, {}
        n = sum(self.docs.values())
        for y in self.docs:
            lp = math.log(self.docs[y] / n)
            tot, v = self.total[y], len(self.vocab)
            for w in toks:
                lp += math.log((self.cont[y][w] + 1) / (tot + v))
            pontos[y] = lp
        melhor = max(pontos, key=pontos.get)
        return melhor


def treino_2025(questoes):
    """Questoes FG de 2025 com competencia oficial, sem repeticao (a mesma questao aparece em todos os cursos)."""
    vistos, saida, rotulos = set(), [], {}
    for q in questoes:
        if str(q["ano"]) != "2025" or q.get("componente") != "FG" or not q.get("competencias"):
            continue
        chave = re.sub(r"\W+", " ", (q.get("enunciado") or "").lower())[:200]
        if chave in vistos:
            continue
        vistos.add(chave)
        rot = q["competencias"][0]
        cod = rot.split(".")[0]
        rotulos[cod] = rot
        saida.append((tokens(texto_da_questao(q)), cod))
    return saida, rotulos


def loo(amostras):
    """Acuracia leave-one-out e da classe mais frequente (linha de base)."""
    acertos = 0
    for i in range(len(amostras)):
        resto = amostras[:i] + amostras[i + 1:]
        if NaiveBayes(resto).prever(amostras[i][0]) == amostras[i][1]:
            acertos += 1
    freq = Counter(y for _, y in amostras)
    return acertos / len(amostras), max(freq.values()) / len(amostras)


def main():
    aqui = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(aqui / "data" / "processed"))
    a = ap.parse_args()
    arq = Path(a.dir) / "questoes.jsonl"
    questoes = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
    amostras, rotulos = treino_2025(questoes)
    if len(amostras) < 10:
        print("poucas questoes oficiais para treinar; nada inferido")
        return 0
    acc, base = loo(amostras)
    modelo = NaiveBayes(amostras)
    inferidas = Counter()
    cache = {}
    for q in questoes:
        if str(q["ano"]) == "2025" or q.get("componente") != "FG" or q.get("competencias"):
            continue
        chave = re.sub(r"\W+", " ", (q.get("enunciado") or "").lower())[:200]
        if chave not in cache:
            cache[chave] = modelo.prever(tokens(texto_da_questao(q)))
        q["competencias"] = [rotulos[cache[chave]]]
        q["fonte_metadados"] = "inferido"
        inferidas[str(q["ano"])] += 1
    arq.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questoes), encoding="utf-8")
    rel = {"treino_questoes_unicas": len(amostras), "acuracia_leave_one_out": round(acc, 3),
           "acuracia_classe_mais_frequente": round(base, 3), "inferidas_por_ano": dict(inferidas),
           "aviso": "amostra de treino pequena; competencia inferida e apenas uma sugestao, marcada como tal"}
    (Path(a.dir) / "classificacao.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
