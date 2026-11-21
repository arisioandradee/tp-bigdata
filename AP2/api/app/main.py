"""API REST de busca do acervo ENADE (RF12-RF19, RF21, RF24, RF25)."""
import io
import json
import time
from html import escape
from typing import Annotated, Any

import redis
from elasticsearch import NotFoundError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from pydantic import BaseModel, Field

from . import cache, config, consultas
from .clientes import es, r
from .seguranca import autenticar, criar_token, exigir_perfil, usuario_atual

app = FastAPI(
    title="ENADE Search API",
    version="1.0.0",
    description="Busca e indexacao distribuida sobre o acervo historico de provas do ENADE. "
                "Estudante: busca sem gabarito. Professor: gabaritos, paineis analiticos e exportacao.",
    openapi_tags=[
        {"name": "auth", "description": "Login e identidade"},
        {"name": "busca", "description": "Busca full-text, filtros, paginacao e highlight"},
        {"name": "analise", "description": "Agregacoes (somente professor)"},
        {"name": "carrinho", "description": "Lista de questoes da sessao (Redis) e exportacao"},
        {"name": "operacao", "description": "Saude, metricas e cache"},
    ],
)

@app.exception_handler(redis.RedisError)
async def redis_fora(_, exc):
    """Redis fora do ar: a busca segue sem cache (ver cache.py); lista de questoes e metricas respondem 503."""
    return JSONResponse(status_code=503, content={"detail": "Servico de lista/cache temporariamente indisponivel"})


# Metricas Prometheus em /metrics (latencia por rota com buckets finos para p50/p95/p99)
Instrumentator(excluded_handlers=["/metrics", "/health", "/health/ready"]) \
    .add(metrics.latency(buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))) \
    .add(metrics.requests()) \
    .instrument(app).expose(app, include_in_schema=False)

Texto = Annotated[list[str] | None, Query()]
RESTRITOS = ("gabarito", "padrao_resposta")


# ----------------------------------------------------------------- modelos
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Questao(BaseModel):
    id: str
    ano: int
    area: str
    curso: str
    grau: str | None = None
    componente: str
    tipo_questao: str
    numero: int
    anulada: bool
    texto_base: str | None = None
    enunciado: str
    alternativas: dict[str, str] = {}
    gabarito: str | None = Field(None, description="Somente perfil professor")
    padrao_resposta: str | None = Field(None, description="Somente perfil professor")
    tem_midia_nao_textual: bool = False
    midia: list[dict[str, Any]] = []
    competencias: list[str] = []
    habilidades: list[str] = []
    objetos_conhecimento: list[str] = []
    fonte_metadados: str | None = Field(None, description="oficial (matriz 2025) | inferido (classificador) | ausente")
    origem: dict[str, Any]


class Item(BaseModel):
    id: str
    score: float | None
    questao: Questao
    destaques: dict[str, list[str]] = {}


class ResultadoBusca(BaseModel):
    total: int
    pagina: int
    tamanho: int
    paginas: int
    tempo_es_ms: int
    cache: bool
    itens: list[Item]
    facetas: dict[str, list[dict[str, Any]]]


class Erro(BaseModel):
    detail: str


def limpar(doc: dict, perfil: str) -> dict:
    """Estudante nunca recebe gabarito nem padrao de resposta."""
    if perfil == "professor":
        return doc
    return {k: v for k, v in doc.items() if k not in RESTRITOS}


# -------------------------------------------------------------------- auth
@app.post("/auth/token", response_model=Token, tags=["auth"],
          responses={401: {"model": Erro}})
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    try:
        perfil = autenticar(form.username, form.password)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if not perfil:
        raise HTTPException(401, "Usuario ou senha invalidos")
    return Token(access_token=criar_token(form.username, perfil))


@app.get("/auth/me", tags=["auth"], responses={401: {"model": Erro}})
def eu(u: dict = Depends(usuario_atual)):
    return u


# ------------------------------------------------------------------- busca
@app.get("/questoes", response_model=ResultadoBusca, response_model_exclude_unset=True, tags=["busca"],
         responses={401: {"model": Erro}, 422: {"model": Erro}, 503: {"model": Erro}})
def buscar(
    u: dict = Depends(usuario_atual),
    q: Annotated[str | None, Query(max_length=300, description="Texto livre (PT-BR, stemming e sinonimos)")] = None,
    area: Texto = None, curso: Texto = None,
    ano: Annotated[list[int] | None, Query()] = None,
    tipo_questao: Annotated[list[str] | None, Query(description="objetiva | discursiva")] = None,
    componente: Annotated[list[str] | None, Query(description="FG | CE")] = None,
    competencia: Texto = None, objeto: Texto = None,
    incluir_anuladas: bool = True,
    pagina: Annotated[int, Query(ge=1, le=1000)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=50)] = 10,
    cache_control: Annotated[str | None, Header(description="`no-cache` ignora o cache Redis nesta consulta (usado nas medicoes)")] = None,
):
    ignorar_cache = bool(cache_control and "no-cache" in cache_control.lower())
    params = {"q": (q or "").strip() or None, "area": area, "curso": curso, "ano": ano,
              "tipo_questao": tipo_questao, "componente": componente, "competencia": competencia,
              "objeto": objeto, "incluir_anuladas": incluir_anuladas, "page": pagina, "size": tamanho,
              "restrito": u["perfil"] != "professor"}  # estudante nao busca em padrao_resposta
    chave, em_cache = (None, None) if ignorar_cache else cache.obter(params)
    if em_cache is not None:
        # Acerto: a resposta final ja esta serializada no Redis (a chave inclui o perfil), entao nao ha
        # revalidacao nem reserializacao. So se troca a marca "cache", campo que vem antes de "itens".
        return Response(content=em_cache.replace(b'"cache":false', b'"cache":true', 1),
                        media_type="application/json")
    corpo = consultas.busca(params)
    try:
        resp = es.search(index=config.ALIAS, body=corpo).body
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Servico de busca indisponivel ({type(e).__name__})")
    total = resp["hits"]["total"]["value"]
    resultado = ResultadoBusca(
        total=total, pagina=pagina, tamanho=tamanho, paginas=-(-total // tamanho),
        tempo_es_ms=resp["took"], cache=False,
        itens=[Item(id=h["_id"], score=h["_score"], questao=limpar(h["_source"], u["perfil"]),
                    destaques=h.get("highlight", {})) for h in resp["hits"]["hits"]],
        facetas={k.replace("por_", ""): [{"valor": b["key"], "total": b["doc_count"]} for b in v["buckets"]]
                 for k, v in resp["aggregations"].items()})
    conteudo = resultado.model_dump_json(exclude_unset=True).encode()
    if not ignorar_cache:
        cache.gravar(chave, conteudo)
    return Response(content=conteudo, media_type="application/json")


def _obter(qid: str) -> dict:
    try:
        return es.get(index=config.ALIAS, id=qid).body["_source"]
    except NotFoundError:
        raise HTTPException(404, f"Questao '{qid}' nao encontrada")


@app.get("/questoes/{qid}", response_model=Questao, response_model_exclude_unset=True, tags=["busca"],
         responses={401: {"model": Erro}, 404: {"model": Erro}})
def questao(qid: str, u: dict = Depends(usuario_atual)):
    return limpar(_obter(qid), u["perfil"])


# ----------------------------------------------------------------- analise
@app.get("/analise/competencias-por-ano", tags=["analise"],
         responses={401: {"model": Erro}, 403: {"model": Erro}})
def competencias_por_ano(curso: Texto = None, _: dict = Depends(exigir_perfil("professor"))):
    resp = es.search(index=config.ALIAS, body=consultas.competencias_por_ano(curso)).body
    return [{"ano": int(b["key"]), "total": b["doc_count"],
             "competencias": [{"competencia": c["key"], "total": c["doc_count"]}
                              for c in b["competencias"]["buckets"]]}
            for b in resp["aggregations"]["por_ano"]["buckets"]]


@app.get("/analise/distribuicao-por-curso", tags=["analise"],
         responses={401: {"model": Erro}, 403: {"model": Erro}})
def distribuicao_por_curso(_: dict = Depends(exigir_perfil("professor"))):
    resp = es.search(index=config.ALIAS, body=consultas.distribuicao_por_curso()).body
    return [{"curso": b["key"], "total": b["doc_count"], "anuladas": b["anuladas"]["doc_count"],
             "por_tipo": {t["key"]: t["doc_count"] for t in b["tipo"]["buckets"]},
             "por_componente": {t["key"]: t["doc_count"] for t in b["componente"]["buckets"]}}
            for b in resp["aggregations"]["por_curso"]["buckets"]]


# ----------------------------------------------------------------- carrinho
def _ck(u): return f"carrinho:{u['usuario']}"


def _ids(u) -> list[str]:
    return r.zrange(_ck(u), 0, -1)


@app.get("/carrinho", tags=["carrinho"], responses={401: {"model": Erro}})
def ver_carrinho(u: dict = Depends(usuario_atual)):
    ids = _ids(u)
    if not ids:
        return {"total": 0, "questoes": []}
    docs = es.mget(index=config.ALIAS, ids=ids).body["docs"]
    qs = [limpar(d["_source"], u["perfil"]) for d in docs if d.get("found")]
    return {"total": len(qs), "questoes": qs}


@app.put("/carrinho/{qid}", status_code=201, tags=["carrinho"],
         responses={401: {"model": Erro}, 404: {"model": Erro}, 409: {"model": Erro}})
def adicionar(qid: str, u: dict = Depends(usuario_atual)):
    _obter(qid)  # 404 se nao existir
    if r.zscore(_ck(u), qid) is not None:
        raise HTTPException(409, "Questao ja esta no carrinho")
    r.zadd(_ck(u), {qid: time.time()})
    r.expire(_ck(u), config.CARRINHO_TTL)
    return {"id": qid, "total": r.zcard(_ck(u))}


@app.delete("/carrinho/{qid}", status_code=204, tags=["carrinho"],
            responses={401: {"model": Erro}, 404: {"model": Erro}})
def remover(qid: str, u: dict = Depends(usuario_atual)):
    if not r.zrem(_ck(u), qid):
        raise HTTPException(404, "Questao nao esta no carrinho")
    return Response(status_code=204)


@app.delete("/carrinho", status_code=204, tags=["carrinho"], responses={401: {"model": Erro}})
def limpar_carrinho(u: dict = Depends(usuario_atual)):
    r.delete(_ck(u))
    return Response(status_code=204)


@app.get("/carrinho/exportar", tags=["carrinho"],
         responses={401: {"model": Erro}, 403: {"model": Erro}, 404: {"model": Erro},
                    200: {"content": {"application/pdf": {}, "application/json": {}}}})
def exportar(formato: Annotated[str, Query(pattern="^(json|pdf)$")] = "json",
             u: dict = Depends(exigir_perfil("professor"))):
    ids = _ids(u)
    if not ids:
        raise HTTPException(404, "Carrinho vazio")
    docs = [d["_source"] for d in es.mget(index=config.ALIAS, ids=ids).body["docs"] if d.get("found")]
    if formato == "json":
        return Response(json.dumps(docs, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="simulado.json"'})
    return Response(_pdf(docs), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="simulado.pdf"'})


def _pdf(docs: list[dict]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    st = getSampleStyleSheet()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, title="Simulado ENADE")
    el = [Paragraph("Simulado ENADE", st["Title"])]
    for n, d in enumerate(docs, 1):
        el.append(Paragraph(f"<b>Questao {n}</b> ({d['curso']}, {d['ano']}, {d['componente']})", st["Heading3"]))
        if d.get("texto_base"):
            el.append(Paragraph(escape(d["texto_base"][:1500]).replace("\n", "<br/>"), st["Italic"]))
        el.append(Paragraph(escape(d["enunciado"]).replace("\n", "<br/>"), st["BodyText"]))
        for letra, txt in d.get("alternativas", {}).items():
            el.append(Paragraph(f"<b>{letra})</b> {escape(txt)}", st["BodyText"]))
        el.append(Spacer(1, 10))
    el.append(Paragraph("Gabarito", st["Heading2"]))
    for n, d in enumerate(docs, 1):
        g = "ANULADA" if d["anulada"] else (d.get("gabarito") or "discursiva")
        el.append(Paragraph(f"{n}: {g}", st["BodyText"]))
    pdf.build(el)
    return buf.getvalue()


# ----------------------------------------------------------------- operacao
@app.get("/health", tags=["operacao"])
def vivo():
    return {"status": "ok"}


@app.get("/health/ready", tags=["operacao"], responses={503: {"model": Erro}})
def pronto(resp: Response):
    estado, ok = {}, True
    try:
        h = es.cluster.health().body
        estado["elasticsearch"] = {"status": h["status"], "docs": es.count(index=config.ALIAS).body["count"]}
        ok &= h["status"] in ("green", "yellow")
    except Exception as e:  # noqa: BLE001
        estado["elasticsearch"] = {"status": "fora", "erro": type(e).__name__}
        ok = False
    try:
        estado["redis"] = {"status": "ok" if r.ping() else "fora"}
    except Exception as e:  # noqa: BLE001
        estado["redis"] = {"status": "fora", "erro": type(e).__name__}
        ok = False
    if not ok:
        resp.status_code = 503
    return {"status": "ok" if ok else "degradado", **estado}


@app.get("/metricas/cache", tags=["operacao"], responses={401: {"model": Erro}, 403: {"model": Erro}})
def metricas_cache(_: dict = Depends(exigir_perfil("professor"))):
    return cache.estatisticas()


@app.post("/cache/invalidar", tags=["operacao"], responses={401: {"model": Erro}, 403: {"model": Erro}})
def invalidar_cache(_: dict = Depends(exigir_perfil("professor"))):
    return {"versao": cache.invalidar()}
