# LDAP

Árvore (criada por `seed.py`, serviço `ldap-seed` do compose):

```
dc=enade,dc=local
├── ou=people
│   ├── uid=estudante1
│   ├── uid=estudante2
│   └── uid=professor1
└── ou=groups
    ├── cn=estudantes   (uniqueMember: estudante1, estudante2)
    └── cn=professores  (uniqueMember: professor1)
```

O perfil de acesso da API é o grupo do usuário. As senhas ficam em `.env`
(`LDAP_ESTUDANTE_SENHA`, `LDAP_PROFESSOR_SENHA`) e são gravadas com hash SSHA.
