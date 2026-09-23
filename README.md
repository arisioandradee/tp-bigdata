# Trabalho Prático - Arquitetura de Big Data em Tempo Real

**E-commerce Data Pipeline: Streaming (Flink) & Batch (Spark)**

## 📁 Estrutura do Projeto

```text
tp-bigdata/
├── docker/              # Dockerfiles e docker-compose para o ambiente
├── generator/           # Script Python (01gerador.py) para simulação de eventos
├── flume/               # Configuração do Apache Flume (flume.conf, log4j.properties)
├── flink/               # Jobs Apache Flink (Streaming, Janelas & Watermarks) + sink HBase
├── spark/               # Jobs Apache Spark (ETL Batch, Hive integration)
├── tests/               # Testes unitários (pytest) do gerador e do sink HBase
└── logs/                # Diretório compartilhado para geração e leitura de logs
```

---

## 🚀 Como Executar o Pipeline Completo (Docker Compose)

```bash
cd docker
docker compose up --build
```

Isso sobe 16 containers (2 são jobs de inicialização que saem com `Exited (0)`):
gerador Python → `hadoop-client-init` (extrai o cliente Hadoop da imagem do NameNode
para um volume, usado pelo sink HDFS do Flume) → Flume (fan-out: HDFS + `logs/flink_stream/`)
→ HDFS (namenode/datanode) → HBase → Hive (Postgres com healthcheck + metastore +
HiveServer2, com `hive-init` criando o banco no HDFS) → Flink (jobmanager/taskmanager +
`flink-job`, que submete o job PyFlink ao cluster via `flink run`, lendo o stream e
gravando alertas no HBase) → Spark (master/worker + `spark-job` rodando o ETL batch sobre
o HDFS e gravando no Hive).

Painéis web disponíveis:
- HDFS NameNode: http://localhost:9870
- Flink Dashboard: http://localhost:8081
- Spark Master: http://localhost:8080
- HBase Master: http://localhost:16010
- HiveServer2 (JDBC): `jdbc:hive2://localhost:10000`

Para acompanhar um serviço específico: `docker compose logs -f flink-job` (ou `spark-job`,
`generator`, `flume`).

Pré-requisitos: Docker Desktop (ou Docker Engine + Compose v2) com pelo menos 8 GB de RAM
disponíveis e as portas 8080, 8081, 9000, 9083, 9090, 9870, 10000 e 16010 livres. Na
primeira subida o download das imagens e a inicialização de HDFS/Hive levam alguns minutos;
serviços dependentes se reconectam sozinhos (`restart: on-failure`).

## 🔎 Como Validar Cada Camada

```bash
# Flume -> HDFS (logs brutos)
docker exec namenode hdfs dfs -ls -R /raw/events

# Flink -> HBase (alertas de janela; aparecem ~5 min após a subida)
docker exec -it hbase_master hbase shell     # dentro: scan 'ecommerce_alerts'

# Spark -> Hive (Data Warehouse)
docker exec -it hive_server /opt/hive/bin/beeline -u jdbc:hive2://localhost:10000
#   SELECT * FROM ecommerce_dw.fact_product_performance LIMIT 10;
#   SELECT * FROM ecommerce_dw.fact_logistics_summary LIMIT 10;
```

Se as tabelas do Hive estiverem vazias (o `spark-job` rodou antes de haver dados no
HDFS), reexecute o ETL: `docker compose run --rm spark-job`. Para encerrar:
`docker compose down` (use `-v` para apagar também os dados dos volumes).

## 🧪 Como Executar Apenas o Gerador (modo local, sem Docker)

```bash
python generator/01gerador.py
```

Os eventos JSON serão impressos no terminal e salvos continuamente no arquivo `logs/ecommerce_events.log`.

## ✅ Testes Automatizados

```bash
pip install -r tests/requirements-dev.txt
python -m pytest tests/ -v
```

Cobrem a geração de eventos (`generator/01gerador.py`) e a lógica de gravação do
`HBaseSink` (`flink/hbase_sink.py`), com o cliente HBase mockado (não precisam de
nenhum serviço do docker-compose no ar).
