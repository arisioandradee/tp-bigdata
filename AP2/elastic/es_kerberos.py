"""Cliente Elasticsearch autenticado por Kerberos (SPNEGO), com autenticacao MUTUA (RF22).

A cada requisicao o cliente gera um token SPNEGO novo (protecao contra replay) a partir do keytab
do servico (KRB5_CLIENT_KTNAME) e envia `Authorization: Negotiate <token>`. O Elasticsearch valida
com o keytab de `HTTP/elasticsearch` e devolve, no header `WWW-Authenticate`, um token que prova a
identidade DELE; o cliente verifica esse token e recusa a resposta se ele faltar ou for invalido.

Variaveis: ES_KERBEROS=1 liga o modo; ES_SPN (padrao HTTP@elasticsearch).
"""
import base64
import logging
import os

from elastic_transport import Urllib3HttpNode
from elastic_transport.client_utils import DEFAULT
from elasticsearch import Elasticsearch

log = logging.getLogger("es_kerberos")


def _token_spnego():
    import gssapi
    nome = gssapi.Name(os.getenv("ES_SPN", "HTTP@elasticsearch"), gssapi.NameType.hostbased_service)
    creds = gssapi.Credentials(usage="initiate")  # usa o keytab de KRB5_CLIENT_KTNAME
    ctx = gssapi.SecurityContext(name=nome, creds=creds, usage="initiate",
                                 flags=gssapi.RequirementFlag.mutual_authentication)
    return ctx, base64.b64encode(ctx.step()).decode()


class NoKerberos(Urllib3HttpNode):
    def perform_request(self, method, target, body=None, headers=None, request_timeout=DEFAULT):
        ctx, token = _token_spnego()
        headers = self._headers_com_token(headers, token)
        resp = super().perform_request(method, target, body=body, headers=headers,
                                       request_timeout=request_timeout)
        self._verificar_servidor(ctx, resp.meta.headers)
        return resp

    @staticmethod
    def _headers_com_token(headers, token):
        from elastic_transport import HttpHeaders
        h = HttpHeaders(headers or {})
        h["authorization"] = f"Negotiate {token}"
        return h

    @staticmethod
    def _verificar_servidor(ctx, headers):
        www = headers.get("www-authenticate", "")
        if not www.lower().startswith("negotiate "):
            raise ConnectionError("Autenticacao mutua falhou: o Elasticsearch nao enviou o token do servidor")
        ctx.step(base64.b64decode(www.split(" ", 1)[1]))
        if not ctx.complete:
            raise ConnectionError("Autenticacao mutua falhou: token do servidor invalido")


def criar_cliente(url, **kw) -> Elasticsearch:
    if os.getenv("ES_KERBEROS") == "1":
        return Elasticsearch(url, node_class=NoKerberos, **kw)
    return Elasticsearch(url, **kw)
