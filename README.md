# Big Data: trabalhos práticos

Centro Universitário Católica de Quixadá (UniCatólica), Sistemas de Informação.
Disciplina: Big Data, Prof. Me. Decio Aguiar.

**Grupo 9:** Arisio Soares Andrade Filho · Raul De Queiroz Moura · José Kayky Barbosa Coelho · Levi Marques Waterloo ·
Carlos Neuan Sampaio Silva

| Pasta | Trabalho | Tecnologias |
|---|---|---|
| [`AP1/`](AP1/README.md) | Pipeline de Big Data em tempo real (e-commerce): streaming e batch | Python, Flume, Flink, Spark, HDFS, HBase, Hive, Docker Compose |
| [`AP2/`](AP2/README.md) | Plataforma distribuída de busca sobre o acervo de provas do ENADE | Kafka (KRaft), Elasticsearch, Redis, OpenLDAP, Kerberos, FastAPI, Prometheus, Grafana, Docker Compose |

Cada trabalho é independente: tem o próprio `docker-compose.yml`, README e instruções de execução. Entre na pasta
do trabalho (`cd AP1` ou `cd AP2`) antes de rodar qualquer comando.

## AP2 em resumo

Pipeline que lê as provas do ENADE em PDF (2014 a 2025), transforma cada questão em um documento (com tabelas em
Markdown e competências oficiais ou inferidas), publica no Kafka com autenticação Kerberos, indexa no Elasticsearch
e serve busca por API REST (JWT, perfis Estudante e Professor via LDAP, cache Redis) e por um cliente web.

- 6.405 questões de 159 provas, 94 cursos, 9 áreas
- Busca em português (stemming e sinônimos), filtros, destaque de termos, lista de questões e exportação
- Medições de carga (k6), injeção de falhas (consumidor, Kafka, Elasticsearch, Redis) e painel no Grafana
- 35 verificações de ponta a ponta na API e 44 testes unitários do extrator

Detalhes, como executar e limitações conhecidas: [`AP2/README.md`](AP2/README.md).
