"""Montagem das consultas ao Elasticsearch (RF12-RF16)."""

CAMPOS_TEXTO = ["enunciado^3", "texto_base^1.5", "alternativas.*", "tabelas_texto", "padrao_resposta"]
FILTROS = {  # parametro -> campo
    "area": "area", "curso": "curso", "ano": "ano", "tipo_questao": "tipo_questao",
    "componente": "componente", "competencia": "competencias", "objeto": "objetos_conhecimento",
}


def busca(p: dict) -> dict:
    # estudante (restrito) nao busca nem recebe destaque em padrao_resposta
    campos = [c for c in CAMPOS_TEXTO if not (p.get("restrito") and c.startswith("padrao_resposta"))]
    must = [{"multi_match": {"query": p["q"], "fields": campos, "type": "best_fields"}}] if p.get("q") \
        else [{"match_all": {}}]
    filtros = []
    for param, campo in FILTROS.items():
        vals = p.get(param)
        if vals:
            filtros.append({"terms": {campo: vals}})
    if p.get("incluir_anuladas") is False:
        filtros.append({"term": {"anulada": False}})
    corpo = {
        "query": {"bool": {"must": must, "filter": filtros}},
        "from": (p["page"] - 1) * p["size"],
        "size": p["size"],
        "track_total_hits": True,
        "aggs": {  # facetas para a interface de filtros
            "por_curso": {"terms": {"field": "curso", "size": 50}},
            "por_area": {"terms": {"field": "area", "size": 50}},
            "por_ano": {"terms": {"field": "ano", "size": 30, "order": {"_key": "desc"}}},
            "por_tipo": {"terms": {"field": "tipo_questao", "size": 5}},
            "por_componente": {"terms": {"field": "componente", "size": 5}},
            "por_competencia": {"terms": {"field": "competencias", "size": 30}},
            "por_objeto": {"terms": {"field": "objetos_conhecimento", "size": 30}},
        },
    }
    if p.get("q"):
        corpo["highlight"] = {
            "pre_tags": ["<mark>"], "post_tags": ["</mark>"],
            "fragment_size": 220, "number_of_fragments": 2, "require_field_match": False,
            "fields": {"enunciado": {}, "texto_base": {}, "alternativas.*": {},
                       **({} if p.get("restrito") else {"padrao_resposta": {}})},
        }
    return corpo


def competencias_por_ano(curso=None) -> dict:
    """RF15: histograma por competencia ao longo do tempo."""
    filtro = [{"terms": {"curso": curso}}] if curso else []
    return {"size": 0, "query": {"bool": {"filter": filtro}},
            "aggs": {"por_ano": {"histogram": {"field": "ano", "interval": 1, "min_doc_count": 1},
                                 "aggs": {"competencias": {"terms": {"field": "competencias", "size": 30}}}}}}


def distribuicao_por_curso() -> dict:
    """RF15: distribuicao quantitativa por curso."""
    return {"size": 0, "aggs": {"por_curso": {
        "terms": {"field": "curso", "size": 100},
        "aggs": {"tipo": {"terms": {"field": "tipo_questao"}},
                 "componente": {"terms": {"field": "componente"}},
                 "anuladas": {"filter": {"term": {"anulada": True}}}}}}}
