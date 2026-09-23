-- Script DDL Hive para inicialização do Data Warehouse
CREATE DATABASE IF NOT EXISTS ecommerce_dw
LOCATION 'hdfs://namenode:9000/user/hive/warehouse/ecommerce_dw.db';

USE ecommerce_dw;

-- Tabela Fato: Desempenho de Produtos e Taxa de Conversão
CREATE TABLE IF NOT EXISTS fact_product_performance (
    category STRING,
    product_id INT,
    product_name STRING,
    total_clicks BIGINT,
    total_cart_additions BIGINT,
    total_checkouts BIGINT,
    total_revenue DOUBLE,
    unique_buyers BIGINT,
    conversion_rate DOUBLE
)
STORED AS PARQUET;

-- Tabela Fato: Resumo de Logística e Vendas
CREATE TABLE IF NOT EXISTS fact_logistics_summary (
    dt DATE,
    delivery_status STRING,
    orders_count BIGINT,
    total_order_value DOUBLE
)
STORED AS PARQUET;
