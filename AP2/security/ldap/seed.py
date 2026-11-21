"""Popula o OpenLDAP (idempotente) com a arvore do projeto.

dc=enade,dc=local
|-- ou=people   : uid=estudante1, uid=estudante2, uid=professor1
`-- ou=groups   : cn=estudantes, cn=professores   (groupOfUniqueNames, atributo uniqueMember)

Perfil de acesso = grupo ao qual o usuario pertence. Senhas vem do ambiente.
"""
import os
import sys
import time

from ldap3 import Connection, Server
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult, LDAPException
from ldap3.utils.hashed import hashed
from ldap3 import HASHED_SALTED_SHA

URL = os.getenv("LDAP_URL", "ldap://ldap:389")
BASE = os.getenv("LDAP_BASE", "dc=enade,dc=local")
ADMIN = f"cn=admin,{BASE}"
SENHA_ADMIN = os.environ["LDAP_ADMIN_PASSWORD"]

USUARIOS = [  # uid, nome, sobrenome, grupo, variavel de ambiente da senha
    ("estudante1", "Ana", "Estudante", "estudantes", "LDAP_ESTUDANTE_SENHA"),
    ("estudante2", "Bruno", "Estudante", "estudantes", "LDAP_ESTUDANTE_SENHA"),
    ("professor1", "Carlos", "Professor", "professores", "LDAP_PROFESSOR_SENHA"),
]


def conectar():
    for _ in range(30):
        try:
            return Connection(Server(URL), ADMIN, SENHA_ADMIN, auto_bind=True)
        except LDAPException as e:
            print("aguardando LDAP:", type(e).__name__)
            time.sleep(3)
    sys.exit("LDAP indisponivel")


def criar(c, dn, classes, attrs):
    try:
        c.add(dn, classes, attrs)
        print("criado  ", dn if c.result["result"] == 0 else f"{dn} -> {c.result['description']}")
    except LDAPEntryAlreadyExistsResult:
        print("existe  ", dn)
    if c.result["result"] not in (0, 68):
        sys.exit(f"erro em {dn}: {c.result}")


def main():
    c = conectar()
    criar(c, f"ou=people,{BASE}", ["organizationalUnit"], {"ou": "people"})
    criar(c, f"ou=groups,{BASE}", ["organizationalUnit"], {"ou": "groups"})
    for uid, nome, sobrenome, _, var in USUARIOS:
        criar(c, f"uid={uid},ou=people,{BASE}", ["inetOrgPerson"], {
            "uid": uid, "cn": f"{nome} {sobrenome}", "sn": sobrenome, "givenName": nome,
            "mail": f"{uid}@enade.local",
            "userPassword": hashed(HASHED_SALTED_SHA, os.environ[var]),
        })
    # O overlay memberOf desta imagem usa groupOfUniqueNames/uniqueMember. Recria os grupos a cada
    # execucao para que o overlay preencha memberOf nos usuarios (a API le o perfil por esse atributo).
    for grupo in ("estudantes", "professores"):
        membros = [f"uid={u[0]},ou=people,{BASE}" for u in USUARIOS if u[3] == grupo]
        c.delete(f"cn={grupo},ou=groups,{BASE}")
        criar(c, f"cn={grupo},ou=groups,{BASE}", ["groupOfUniqueNames"],
              {"cn": grupo, "uniqueMember": membros})
    print("arvore LDAP pronta")


if __name__ == "__main__":
    main()
