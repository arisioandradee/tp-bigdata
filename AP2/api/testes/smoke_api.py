"""Teste de ponta a ponta da API (usa so a biblioteca padrao).

Uso: python api/testes/smoke_api.py [--url http://localhost:8000]
Le as senhas de desenvolvimento do .env (via app.config).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

BASE = "http://127.0.0.1:8000"
resultados = []


def chamar(metodo, caminho, token=None, dados=None, form=None):
    h = {}
    corpo = None
    if token:
        h["Authorization"] = f"Bearer {token}"
    if form is not None:
        corpo = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif dados is not None:
        corpo = json.dumps(dados).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + caminho, data=corpo, headers=h, method=metodo)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            bruto, status, tipo = r.read(), r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        bruto, status, tipo = e.read(), e.code, e.headers.get("Content-Type", "")
    ms = (time.perf_counter() - t0) * 1000
    corpo = json.loads(bruto) if "json" in tipo and bruto else bruto
    return status, corpo, ms


def checar(nome, cond, detalhe=""):
    resultados.append((nome, bool(cond)))
    print(f"[{'OK ' if cond else 'FALHA'}] {nome} {detalhe}")


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=BASE)
    BASE = ap.parse_args().url

    s, _, _ = chamar("GET", "/questoes")
    checar("sem token -> 401", s == 401)
    s, _, _ = chamar("POST", "/auth/token", form={"username": "professor", "password": "errada"})
    checar("senha errada -> 401", s == 401)

    import os
    ldap = config.AUTH_MODE == "ldap"
    contas = {"estudante": ("estudante1", os.getenv("LDAP_ESTUDANTE_SENHA", "")),
              "professor": ("professor1", os.getenv("LDAP_PROFESSOR_SENHA", ""))} if ldap else \
             {k: (k, v[0]) for k, v in config.DEV_USUARIOS.items()}
    if ldap:  # entradas hostis contra o LDAP: nenhuma pode autenticar
        for nome, usr, pw in (("senha vazia (bind anonimo)", "professor1", ""),
                              ("injecao de filtro no usuario", "*)(uid=*", "x"),
                              ("usuario inexistente", "fantasma", "x")):
            s, _, _ = chamar("POST", "/auth/token", form={"username": usr, "password": pw})
            checar(f"LDAP: {nome} rejeitado", s in (401, 422), f"(HTTP {s})")
    tok = {}
    for u in ("estudante", "professor"):
        s, c, _ = chamar("POST", "/auth/token",
                         form={"username": contas[u][0], "password": contas[u][1]})
        checar(f"login {u}", s == 200 and "access_token" in c)
        tok[u] = c["access_token"]
    E, P = tok["estudante"], tok["professor"]

    # --- busca e perfis
    q = urllib.parse.quote("banco de dados")
    s, ce, _ = chamar("GET", f"/questoes?q={q}", E)
    checar("estudante busca 'banco de dados'", s == 200 and ce["total"] > 0, f"({ce['total']} resultados)")
    checar("estudante NAO recebe gabarito", all("gabarito" not in i["questao"] and
                                                  "padrao_resposta" not in i["questao"] for i in ce["itens"]))
    checar("highlight com <mark>", any("<mark>" in f for i in ce["itens"]
                                       for fr in i["destaques"].values() for f in fr))
    s, cp, _ = chamar("GET", f"/questoes?q={q}&componente=CE&tipo_questao=objetiva", P)
    checar("professor recebe gabarito", s == 200 and all(i["questao"].get("gabarito") or i["questao"]["anulada"]
                                                         for i in cp["itens"]) and cp["itens"])
    # estudante nao busca no padrao de resposta (nao vaza conteudo restrito)
    # Frase tirada do meio do padrao de resposta de uma discursiva (independe do volume de dados):
    # o professor acha a questao por ela; o estudante nao pode achar a mesma questao.
    s, dis, _ = chamar("GET", "/questoes?tipo_questao=discursiva&tamanho=20", P)
    import re
    alvo, termos = None, []
    for it in dis["itens"]:  # palavras longas que existem SO no padrao de resposta (nao no texto visivel)
        q = it["questao"]
        visivel = (q.get("texto_base", "") + " " + q["enunciado"]).lower()
        raras = [w for w in set(re.findall(r"[a-zçãõáéíóúâêô]{11,}", (q.get("padrao_resposta") or "").lower())) if w not in visivel]
        if len(raras) >= 3:
            alvo, termos = it, sorted(raras, key=lambda w: (-len(w), w))[:3]  # deterministico
            break
    prof_acha, estud_acha = [], []
    for w in termos:
        _, a, _ = chamar("GET", f"/questoes?q={urllib.parse.quote(w)}&tamanho=50", E)
        _, b, _ = chamar("GET", f"/questoes?q={urllib.parse.quote(w)}&tamanho=50", P)
        estud_acha.append(alvo["id"] in {i["id"] for i in a["itens"]})
        prof_acha.append(alvo["id"] in {i["id"] for i in b["itens"]})
    # o estudante NUNCA pode achar a questao por essas palavras; o professor tem de achar por alguma
    checar("padrao_resposta so pesquisavel pelo professor",
           alvo is not None and not any(estud_acha) and any(prof_acha),
           f"(questao {alvo['id'] if alvo else '-'}; termos={termos}; professor acha={prof_acha}, estudante acha={estud_acha})")

    # --- filtros, paginacao, validacao
    s, f, _ = chamar("GET", "/questoes?ano=2021&tipo_questao=discursiva&componente=FG", P)
    checar("filtros combinados (2021+discursiva+FG)", s == 200 and f["total"] >= 2 and all(i["questao"]["ano"] == 2021 and i["questao"]["tipo_questao"] == "discursiva" and i["questao"]["componente"] == "FG" for i in f["itens"]), f"(total={f['total']})")
    s, p1, _ = chamar("GET", "/questoes?tamanho=5&pagina=1", P)
    s, p2, _ = chamar("GET", "/questoes?tamanho=5&pagina=2", P)
    checar("paginacao sem repetir itens", {i["id"] for i in p1["itens"]}.isdisjoint({i["id"] for i in p2["itens"]})
           and p1["paginas"] == -(-p1["total"] // 5))
    checar("facetas presentes", all(k in p1["facetas"] for k in ("curso", "ano", "tipo", "componente")))
    s, _, _ = chamar("GET", "/questoes?pagina=0", P)
    checar("pagina=0 -> 422", s == 422)
    s, _, _ = chamar("GET", "/questoes/nao-existe", P)
    checar("questao inexistente -> 404", s == 404)

    # --- RF25: 403 explicito
    for nome, caminho in (("distribuicao por curso", "/analise/distribuicao-por-curso"),
                          ("competencias por ano", "/analise/competencias-por-ano"),
                          ("exportar carrinho", "/carrinho/exportar?formato=json"),
                          ("metricas de cache", "/metricas/cache")):
        s, c, _ = chamar("GET", caminho, E)
        checar(f"estudante em '{nome}' -> 403", s == 403, f"({c.get('detail') if isinstance(c, dict) else ''})")
    s, c, _ = chamar("GET", "/analise/distribuicao-por-curso", P)
    checar("professor em analise por curso -> 200", s == 200 and c and c[0]["total"] > 0)

    # --- cache Redis
    chamar("POST", "/cache/invalidar", P)
    url = "/questoes?q=" + urllib.parse.quote("desigualdades sociais") + "&tamanho=20"
    s, m1, t1 = chamar("GET", url, P)
    s, m2, t2 = chamar("GET", url, P)
    checar("1a busca sem cache, 2a do cache", m1["cache"] is False and m2["cache"] is True,
           f"({t1:.0f} ms -> {t2:.0f} ms)")
    s, est, _ = chamar("GET", "/metricas/cache", P)
    checar("hit rate calculado", s == 200 and est["hit_rate"] is not None, f"({est})")
    s, v, _ = chamar("POST", "/cache/invalidar", P)
    s, m3, _ = chamar("GET", url, P)
    checar("invalidacao forca nova consulta", m3["cache"] is False)

    # --- carrinho
    chamar("DELETE", "/carrinho", P)
    ids = [i["id"] for i in p1["itens"][:2]]
    for i in ids:
        s, _, _ = chamar("PUT", f"/carrinho/{i}", P)
        checar(f"adicionar {i}", s == 201)
    s, _, _ = chamar("PUT", f"/carrinho/{ids[0]}", P)
    checar("adicionar duplicada -> 409", s == 409)
    s, _, _ = chamar("PUT", "/carrinho/nao-existe", P)
    checar("adicionar inexistente -> 404", s == 404)
    s, c, _ = chamar("GET", "/carrinho", P)
    checar("carrinho lista 2", c["total"] == 2)
    s, pdf, _ = chamar("GET", "/carrinho/exportar?formato=pdf", P)
    checar("exportar PDF", s == 200 and pdf[:4] == b"%PDF", f"({len(pdf)} bytes)")
    s, js, _ = chamar("GET", "/carrinho/exportar?formato=json", P)
    checar("exportar JSON", s == 200 and len(js) == 2)
    # carrinho do estudante e isolado do professor
    s, c, _ = chamar("GET", "/carrinho", E)
    ids_estudante = {q["id"] for q in c["questoes"]}
    checar("carrinho isolado por usuario", s == 200 and ids_estudante.isdisjoint(ids),
           f"(o estudante tem {len(ids_estudante)} questoes proprias, nenhuma do professor)")
    s, _, _ = chamar("DELETE", f"/carrinho/{ids[0]}", P)
    checar("remover do carrinho -> 204", s == 204)
    chamar("DELETE", "/carrinho", P)

    s, h, _ = chamar("GET", "/health/ready")
    checar("health/ready", s == 200 and h["status"] == "ok")

    falhas = [n for n, ok in resultados if not ok]
    print(f"\n{len(resultados) - len(falhas)}/{len(resultados)} verificacoes passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
