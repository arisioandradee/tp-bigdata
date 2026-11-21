"""Autenticacao (JWT) e perfis (RF23-RF25).

`autenticar()` e o unico ponto que muda na etapa de seguranca: hoje valida usuarios
locais de desenvolvimento (AUTH_MODE=dev); depois sera trocado por bind no LDAP.
O restante (token, perfis, 401/403) ja e o definitivo.
"""
import hmac
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from . import config

esquema = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def autenticar(usuario: str, senha: str):
    """Retorna o perfil ('estudante' | 'professor') ou None."""
    if config.AUTH_MODE == "dev":
        reg = config.DEV_USUARIOS.get(usuario)
        if reg and reg[0] and hmac.compare_digest(reg[0], senha):
            return reg[1]
        return None
    return _autenticar_ldap(usuario, senha)


def _autenticar_ldap(usuario: str, senha: str):
    """Bind direto como o usuario (a senha nunca e comparada pela API) e perfil pelo grupo."""
    from ldap3 import BASE, Connection, Server
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.dn import escape_rdn

    if not usuario or not senha:  # bind sem senha seria "anonimo" no LDAP
        return None
    dn = f"uid={escape_rdn(usuario)},ou=people,{config.LDAP_BASE}"
    try:
        with Connection(Server(config.LDAP_URL, connect_timeout=5), dn, senha, auto_bind=True) as c:
            # a ACL so deixa o usuario ler a propria entrada; o overlay memberOf expoe os grupos nela
            c.search(dn, "(objectClass=*)", search_scope=BASE, attributes=["memberOf"])
            grupos = {g.split(",")[0].removeprefix("cn=") for e in c.entries for g in e.memberOf.values}
    except LDAPException:
        return None  # usuario inexistente, senha errada ou LDAP indisponivel
    for grupo, perfil in (("professores", "professor"), ("estudantes", "estudante")):
        if grupo in grupos:
            return perfil
    raise PermissionError("usuario sem grupo de acesso")


def criar_token(usuario: str, perfil: str) -> str:
    agora = int(time.time())
    return jwt.encode({"sub": usuario, "perfil": perfil, "iat": agora,
                       "exp": agora + config.JWT_EXP_MIN * 60}, config.JWT_SECRET, algorithm="HS256")


def usuario_atual(token: str | None = Depends(esquema)) -> dict:
    if not token:
        raise HTTPException(401, "Autenticacao necessaria", headers={"WWW-Authenticate": "Bearer"})
    try:
        dados = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token invalido ou expirado", headers={"WWW-Authenticate": "Bearer"})
    return {"usuario": dados["sub"], "perfil": dados["perfil"]}


def exigir_perfil(*perfis: str):
    def dep(u: dict = Depends(usuario_atual)) -> dict:
        if u["perfil"] not in perfis:
            raise HTTPException(403, f"Perfil '{u['perfil']}' sem permissao para este recurso")
        return u
    return dep
