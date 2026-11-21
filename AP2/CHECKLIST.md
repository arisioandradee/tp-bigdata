# TP2 Big Data — Checklist para nota 10

Plataforma distribuída de busca sobre o acervo do ENADE.
**Prazo: 29/11/2026 às 23h59 (rígido).** Um único integrante submete pelo grupo.
(O cabeçalho do enunciado diz 06/12, mas o corpo diz 29/11: confirmar com o professor.)

Nota: Relatório 2,0 + Vídeo 2,0 + Repositório (obrigatório, sem código = zero).
Regra de ouro do relatório: **decisão + justificativa + evidência + discussão no texto**. Figura/tabela sem comentário não conta.

---

## 0. Organização da equipe
- [x] Equipe fechada (até 5 pessoas) e responsáveis por área definidos
- [x] Repositório Git criado (público ou com acesso ao professor)
- [x] Combinar quem submete no sistema
- [x] Cada membro consegue explicar o sistema inteiro (há arguição oral individual)
- [x] Divisão de tarefas registrada (vira seção do relatório)
- [x] Registro do uso de IA: modelo, custo estimado, taxa de erro, método de validação

## 1. Estrutura de pastas do repositório
```
TP2-BigData/
├── README.md                # docker compose up + passo a passo
├── docker-compose.yml
├── .env.example             # sem segredos reais
├── .gitignore               # .env, keytabs, *.keytab, dados brutos
├── docs/                    # relatório (LaTeX SBC), figuras, OpenAPI exportado
├── data/
│   ├── raw/                 # PDFs (fora do Git se pesados)
│   └── samples/             # amostra de 50+ questões validadas
├── ingestion/               # extração de PDF + LLM + produtor Kafka
├── consumer/                # consumidor Kafka -> Elasticsearch + DLQ
├── elastic/                 # mappings, analisadores, sinônimos
├── api/                     # backend REST (Swagger)
├── web/                     # cliente web
├── security/                # configs Kerberos (krb5, JAAS) e LDAP (ldif)
├── monitoring/              # Prometheus/Grafana, health checks
├── bench/                   # k6/Locust, resultados, gráficos
└── scripts/                 # utilitários (seed, reprocessar, falha induzida)
```
- [x] Estrutura acima criada
- [x] Um Dockerfile por serviço próprio (api, consumer, ingestion, web, kdc, ldap-seed e es-setup)

## 2. Infraestrutura (Docker Compose)
- [x] Kafka em modo KRaft (nós, tópicos e partições justificados) (rodando; a justificativa vai no relatório)
- [x] Elasticsearch (shards e réplicas justificados) + Kibana (rodam com segurança Kerberos; a justificativa vai no relatório)
- [x] Redis + Redis Insight
- [x] OpenLDAP
- [x] KDC Kerberos (MIT)
- [x] Prometheus + Grafana (observabilidade) (painel provisionado, 11 paineis)
- [x] Health checks e `depends_on` com condição de saúde
- [x] Volumes persistentes (Kafka, Elastic, Redis)
- [x] **`docker compose up` sobe tudo do zero** (testar em máquina limpa). Testado em 2 rodadas com `down -v` e volumes vazios: tudo saudável em 366 s, índice reconstruído (68 docs), 35/35 testes. Falta repetir em outra máquina antes da entrega

## 3. Coleta e engenharia de dados (RF01–RF06)
- [x] Coleta de provas, gabaritos e diretrizes de **todos os cursos e edições** (RF01), com 159 provas e 6.405 questões de 2014 a 2025 indexadas. Provas escaneadas de 2014 e 2017 (Sistemas de Informação) recuperadas por OCR por coluna: 32 e 31 de 35 objetivas; as que o OCR não leu vão para a DLQ
- [x] Tabela com volume do acervo (provas, páginas, questões por ano/área) (docs/volume-acervo.md, geração automática; cobre só as provas já extraídas)
- [x] Segmentação: 1 questão = 1 documento (texto-base, enunciado, alternativas, gabarito) (RF02) (1.115 documentos de 28 provas; 4 ou 5 alternativas)
- [x] Distinção objetiva x discursiva; anuladas sinalizadas, não descartadas (RF03) (17 anuladas sinalizadas)
- [x] Tabelas convertidas para Markdown (RF04): 488 questões com tabela. Figuras e fórmulas ficam como `pendente` (decisão: só tabelas são convertidas, de forma determinística)
- [x] Metadados: área, curso, ano, tipo (FG/CE), competências (RF05). Oficiais só em 2025 (713 questões); FG de 2018 a 2023 com competência inferida por Naive Bayes (80% leave-one-out, n=15), marcada "inferido". Objetos de conhecimento só em 2025; CE anterior a 2025 sem competência
- [x] Rastreabilidade: PDF e página de origem em todo documento (RF06)
- [ ] Amostra manual de **≥ 50 questões** com taxa de acerto calculada (RNF03)
- [ ] Taxa de erro por tipo (texto, fórmula, diagrama, tabela) discutida
- [ ] Escolha da ferramenta de extração justificada (comparar alternativas)

## 4. Kafka e ingestão (RF07–RF11)
- [x] Produtor publica JSON estruturado nos tópicos (RF07)
- [x] Consumidor indexa no Elasticsearch (RF08)
- [x] Commit manual de offset após indexar (sem perda) (RF09)
- [x] **Idempotência**: ID determinístico do documento (hash/ano+curso+questão); reprocessar não duplica (RF10)
- [x] **DLQ**: tópico de erro para mensagens inválidas, fluxo continua (RF11)
- [x] Experimento de falha induzida (derrubar consumidor/Kafka/Elastic): consumidor morto à força, Kafka parado e Elasticsearch parado durante a ingestão de 11.150 docs; 0 perdidos nos três; ver bench/resultados/experimentos.md
- [x] Lag do consumidor (máximo de 9.950 mensagens na ingestão de 11.150 docs; série em bench/resultados/vazao-lag.csv)
- [x] Vazão de ingestão medida (docs/s e tempo total) (RNF02) (48,9 docs/s, 228 s para 11.150 documentos)
- [ ] Configs Kafka justificadas (partições, replicação, acks, retries, chave)

## 5. Elasticsearch (RF12–RF16)
- [ ] Mapping detalhado e explicado campo a campo
- [x] Analisador `brazilian` + stemming (RF13)
- [x] Dicionário de sinônimos (RF13)
- [x] Filtros combináveis: área, curso, ano, tipo, competência (RF12)
- [x] Busca interdisciplinar: mesma consulta retorna questões de cursos diferentes (ex.: ética) (RF14) (\
- [x] Agregação: histograma de competência ao longo do tempo (RF15)
- [x] Agregação: distribuição por curso (RF15)
- [x] Paginação e highlight do termo (RF16)
- [ ] Exemplos de consultas no relatório, com discussão da relevância

## 6. API e cache (RF17–RF19)
- [x] Rotas REST padronizadas + OpenAPI/Swagger acessível (RF17)
- [x] Status HTTP corretos (200, 201, 400, 401, 403, 404, 500)
- [x] Cache Redis em buscas frequentes, com TTL e política de invalidação (RF18)
- [x] Carrinho/sessão de questões persistido no Redis (RF19)
- [x] Hit rate do Redis: cerca de 96% nos cenários com cache (com_cache e misto), em 3 rodadas
- [x] Comparação de latência com e sem cache (sem cache p50 133 ms e p95 295 ms; com cache p50 29 ms e p95 61 ms)

## 7. Cliente web (RF20–RF21)
- [x] Busca, filtros, paginação e highlight (testado no navegador)
- [ ] Renderização de fórmulas (LaTeX) e diagramas (Mermaid). O cliente já renderiza KaTeX e Mermaid quando `midia[].conteudo` vem convertido; falta a conversão das figuras (RF04)
- [x] Gerenciamento da lista (adicionar/remover/limpar)
- [x] Exportação da lista em PDF e JSON (RF21)
- [x] Telas diferentes para Estudante e Professor (estudante sem gabarito e com 403 ao exportar; professor com gabarito, painel e exportação)
- [x] Painel analítico (Professor) com as agregações (competências vazias até o campo ser preenchido)

## 8. Segurança (RF22–RF25)
- [x] Kerberos: principals criados para Kafka, Elasticsearch, API e consumidor (RF22) (6 principals e keytabs gerados pelo KDC)
- [x] SASL/GSSAPI funcionando no Kafka; autenticação mútua entre serviços (broker, admin, produtor e consumidor no Kafka; consumidor e API no Elasticsearch, com token do servidor verificado; cliente sem Kerberos rejeitado)
- [x] Keytabs fora do Git (ficam em volume Docker; `.gitignore` cobre `*.keytab`)
- [x] LDAP: árvore (OUs, grupos Estudante e Professor, usuários de teste) (RF23)
- [x] Login da API integrado ao LDAP
- [x] Perfis: Estudante sem gabarito restrito; Professor com gabaritos, painéis e exportação (RF24)
- [x] **Teste de negação: Estudante em rota restrita retorna 403** (RF25), mostrado no vídeo (testado: 4 rotas retornam 403; falta gravar no vídeo)
- [ ] Diagrama da árvore LDAP e lista de principals no relatório

## 9. Avaliação experimental (RNF01, RNF05, RNF06)
- [x] Teste de carga (k6/Locust/JMeter) com cenário descrito (k6 em 4 cenários; bench/k6/busca.js e bench/rodar_carga.ps1; 3 rodadas com o ambiente isolado)
- [x] Latência p50, p95 e p99: sem cache p95 295 ms (meta 500, atingida nas 3 rodadas); com cache p95 61 ms (meta 50, não atingida); ver bench/resultados/carga.md
- [x] Gráficos com eixos, unidades e legenda (bench/resultados/latencia-busca.png)
- [x] Vazão de ingestão (docs/s): 48,9 docs/s ponta a ponta (11.150 docs em 228 s; bulk p95 0,93 s)
- [x] Lag do consumidor (máximo de 9.950 mensagens na ingestão de 11.150 docs; série em bench/resultados/vazao-lag.csv)
- [x] Hit rate do Redis: cerca de 96% nos cenários com cache (com_cache e misto), em 3 rodadas
- [x] Experimento de resiliência com relato detalhado (3 falhas induzidas, 0 documentos perdidos)
- [x] Testes unitários do extrator: 44 testes passando (`python -m pytest ingestion/testes -q`)
- [x] Degradação com Redis fora do ar testada (`api/testes/redis_fora.py`): defeito de 40 s por busca encontrado e corrigido com disjuntor
- [x] Health checks, logs e métricas consultáveis (RNF06)
- [ ] Metas não atingidas explicadas (medir e explicar é o que vale)

## 10. Relatório (PDF, modelo SBC, máx. 12 páginas)
Seções mínimas:
- [ ] 1. Resumo/Abstract
- [ ] 2. Introdução
- [ ] 3. Arquitetura (diagrama, papéis dos nós)
- [ ] 4. Coleta e Engenharia de Dados
- [ ] 5. Ingestão Kafka/Elasticsearch
- [ ] 6. Busca e API
- [ ] 7. Cache e Sessão
- [ ] 8. Segurança (LDAP/Kerberos)
- [ ] 9. Avaliação Experimental
- [ ] 10. Gargalos e Lições
- [ ] 11. Conclusão
- [ ] 12. Divisão de Tarefas

Qualidade:
- [ ] Toda decisão tem justificativa; toda figura/tabela é citada e discutida no texto
- [ ] Métricas obrigatórias presentes: volume do acervo, qualidade (≥50), docs/s, lag, p50/p95/p99, hit rate
- [ ] Declaração de uso de IA (modelo, custo, taxa de erro, validação)
- [ ] Referências no padrão SBC; dentro de 12 páginas
- [ ] Revisão ortográfica e figuras legíveis
- [ ] Link do repositório e do vídeo no relatório

## 11. Vídeo (máx. 5 min; o excedente é ignorado)
- [ ] Roteiro cronometrado e ensaiado
- [ ] Fluxo completo: PDF -> Kafka -> Elastic -> API -> web
- [ ] Busca interdisciplinar
- [ ] Cache (primeira busca lenta x segunda rápida, chave no Redis Insight)
- [ ] Login por perfil (Estudante x Professor)
- [ ] **403 do Estudante em rota restrita**
- [ ] Carrinho e exportação
- [ ] (Se couber) falha induzida, health e painel
- [ ] Link acessível sem login (YouTube não listado ou Drive aberto), testado em aba anônima

## 12. Repositório e commit final
- [ ] README: visão geral, pré-requisitos, `docker compose up`, como carregar os dados, usuários de teste, como rodar os testes de carga
- [ ] `.env.example` presente; **`.env`, keytabs e chaves de API fora do Git** (RNF08)
- [ ] Varredura de segredos no histórico (gitleaks ou `git log -p` + grep). Feita a varredura da árvore de arquivos em 21/11 (nenhum valor do `.env` fora dele, keytabs fora da pasta, `.env` no `.gitignore`); repetir no histórico depois do commit final
- [ ] Commits de todos os integrantes (histórico mostra a divisão de trabalho)
- [ ] Clone limpo + `docker compose up` testado em outra máquina
- [ ] Acesso ao professor garantido (público ou convite)
- [ ] Tag `v1.0-entrega` no commit final
- [ ] Relatório em PDF dentro de `docs/` e link do vídeo no README

## 13. Submissão (até 29/11, 23h59)
- [ ] Meta interna: tudo pronto até 27/11 (folga de 2 dias)
- [ ] PDF do relatório anexado
- [ ] Link do vídeo e do repositório informados
- [ ] Checklist da submissão do enunciado conferido (PDF SBC, vídeo ≤ 5 min, repo com README funcional, sem credenciais)
- [ ] Um único integrante submete e guarda o comprovante
- [ ] Todos se preparam para a arguição oral

---

## Cronograma de referência (ajustado)
| Data | Meta |
|---|---|
| Até 17/11 | Infra no Compose + extração funcionando em ao menos uma área |
| Até 20/11 | Acervo completo processado, pipeline Kafka -> Elastic, DLQ e idempotência |
| Até 23/11 | API, cache, carrinho e cliente web |
| Até 25/11 | LDAP + Kerberos, testes de carga e falha induzida |
| Até 27/11 | Relatório fechado, vídeo gravado, repo limpo e testado |
| 28–29/11 | Folga e submissão |
