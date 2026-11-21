import sys
import logging
from datetime import datetime, timedelta
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_json, to_date, count, sum as _sum, avg,
    window, when, countDistinct, expr
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, IntegerType, TimestampType
)

# Configuração de Logs
logging.basicConfig(level=logging.INFO)

def create_spark_session():
    """Inicializa a SparkSession com suporte ao Hive Metastore."""
    return SparkSession.builder \
        .appName("Ecommerce_Batch_ETL_Spark") \
        .config("spark.sql.warehouse.dir", "hdfs://namenode:9000/user/hive/warehouse") \
        .config("hive.metastore.uris", "thrift://hive-metastore:9083") \
        .config("spark.sql.files.ignoreCorruptFiles", "true") \
        .enableHiveSupport() \
        .getOrCreate()

def get_event_schema():
    """Esquema JSON dos eventos de e-commerce."""
    return StructType([
        StructField("event_id", StringType(), True),
        StructField("timestamp", StringType(), True),
        StructField("user_id", IntegerType(), True),
        StructField("product_id", IntegerType(), True),
        StructField("product_name", StringType(), True),
        StructField("category", StringType(), True),
        StructField("action", StringType(), True),
        StructField("price", DoubleType(), True),
        StructField("delivery_status", StringType(), True)
    ])

def main():
    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    logging.info("[Spark Job] Iniciando ETL Batch em lote do histórico...")

    # Histórico do dia anterior; se ainda não existir (ex.: demo no mesmo dia
    # em que o Flume começou a gravar), usa a partição do dia corrente.
    fs = spark._jvm.org.apache.hadoop.fs.FileSystem.get(
        spark._jvm.java.net.URI("hdfs://namenode:9000"), spark._jsc.hadoopConfiguration())
    hdfs_path = spark._jvm.org.apache.hadoop.fs.Path
    now = datetime.now()
    hdfs_raw_path = None
    for day in (now - timedelta(days=1), now):
        candidate = f"hdfs://namenode:9000/raw/events/{day.strftime('%Y-%m-%d')}"
        if fs.exists(hdfs_path(candidate)):
            hdfs_raw_path = candidate + "/events-*.log"
            break
    if hdfs_raw_path is None:
        raise RuntimeError("Nenhuma partição em /raw/events no HDFS (Flume já gravou algo?)")

    print(f"[Spark Job] Lendo logs brutos do HDFS: {hdfs_raw_path}")

    schema = get_event_schema()
    raw_df = spark.read.text(hdfs_raw_path)
    events_df = (
        raw_df.select(from_json(col("value"), schema).alias("data")).select("data.*")
        .filter(col("event_id").isNotNull())
        .withColumn("event_timestamp", col("timestamp").cast(TimestampType()))
        .withColumn("dt", to_date(col("event_timestamp")))
    )

    # Registra View temporária para consultas Spark SQL
    events_df.createOrReplaceTempView("stg_ecommerce_events")

    # -------------------------------------------------------------------------
    # 2. WIDE DEPENDENCY 1: Aggregation de Conversão por Categoria e Produto
    # Operação de Shuffle / Wide Dependency (groupBy + joins agregados)
    # -------------------------------------------------------------------------
    product_metrics_df = events_df.groupBy("category", "product_id", "product_name") \
        .agg(
            count(when(col("action") == "click", 1)).alias("total_clicks"),
            count(when(col("action") == "add_to_cart", 1)).alias("total_cart_additions"),
            count(when(col("action") == "checkout", 1)).alias("total_checkouts"),
            _sum(when(col("action") == "checkout", col("price")).otherwise(0)).alias("total_revenue"),
            countDistinct("user_id").alias("unique_buyers")
        ) \
        .withColumn(
            "conversion_rate", 
            when(col("total_clicks") > 0, (col("total_checkouts") / col("total_clicks")) * 100).otherwise(0)
        )

    # -------------------------------------------------------------------------
    # 3. WIDE DEPENDENCY 2: Cruzamento de Funil de Usuários com Status de Entrega
    # Wide Dependency (Join entre histórico de compras e status logístico)
    # -------------------------------------------------------------------------
    checkouts_df = events_df.filter(col("action") == "checkout").select("user_id", "product_id", "price", "dt")
    logistics_df = events_df.filter(col("action") == "delivery_status_update").select("user_id", "delivery_status")

    # Wide Join entre dados de compra e logística
    user_logistics_df = checkouts_df.join(
        logistics_df, 
        on="user_id", 
        how="left"
    ).groupBy("dt", "delivery_status") \
     .agg(
         count("user_id").alias("orders_count"),
         _sum("price").alias("total_order_value")
     )

    # -------------------------------------------------------------------------
    # 4. Gravação no Apache Hive (Data Warehouse Consolidado)
    # -------------------------------------------------------------------------
    spark.sql("CREATE DATABASE IF NOT EXISTS ecommerce_dw "
              "LOCATION 'hdfs://namenode:9000/user/hive/warehouse/ecommerce_dw.db'")

    # Gravação Tabela 1: Métricas de Desempenho de Produtos
    print("[Spark Job] Gravando tabela hive 'ecommerce_dw.fact_product_performance'...")
    product_metrics_df.write \
        .mode("overwrite") \
        .format("parquet") \
        .saveAsTable("ecommerce_dw.fact_product_performance")

    # Gravação Tabela 2: Métricas de Logística e Vendas
    print("[Spark Job] Gravando tabela hive 'ecommerce_dw.fact_logistics_summary'...")
    user_logistics_df.write \
        .mode("overwrite") \
        .format("parquet") \
        .saveAsTable("ecommerce_dw.fact_logistics_summary")

    print("[Spark Job] ETL Batch concluído com sucesso e tabelas persistidas no Hive Metastore!")
    spark.stop()

if __name__ == "__main__":
    main()
