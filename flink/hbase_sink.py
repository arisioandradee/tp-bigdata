"""
HBase Sink Connector para Flink / Python
Persiste métricas e alertas em tempo real na tabela HBase 'ecommerce_alerts'.
"""
import json
import logging

TABLE_NAME = "ecommerce_alerts"
COLUMN_FAMILIES = {"cf_metrics": {}, "cf_alerts": {}}


class HBaseSink:
    def __init__(self, host="hbase-master", port=9090, table_name=TABLE_NAME):
        self.host = host
        self.port = port
        self.table_name = table_name
        self.connection = None
        self.table = None

    def open(self):
        """Abre a conexão Thrift com o HBase e garante que a tabela exista."""
        import happybase

        self.connection = happybase.Connection(host=self.host, port=self.port, timeout=10000)
        self.connection.open()

        existing_tables = {t.decode("utf-8") for t in self.connection.tables()}
        if self.table_name not in existing_tables:
            self.connection.create_table(self.table_name, COLUMN_FAMILIES)
            logging.info(f"[HBase Sink] Tabela '{self.table_name}' criada com as families {list(COLUMN_FAMILIES)}.")

        self.table = self.connection.table(self.table_name)

    def close(self):
        if self.connection is not None:
            self.connection.close()

    def _put_with_retry(self, row_key, hbase_row):
        """A conexão Thrift fica ociosa entre janelas e pode ser derrubada pelo
        servidor (Broken pipe); reconecta e tenta de novo uma vez."""
        try:
            self.table.put(row_key, hbase_row)
        except Exception as first_error:
            logging.warning(f"[HBase Sink] Conexão perdida ({first_error}); reconectando...")
            try:
                self.close()
            except Exception:
                pass
            self.open()
            self.table.put(row_key, hbase_row)

    def write_alert(self, record_json):
        """
        Grava a família de colunas no HBase.
        Coluna Family: 'cf_metrics' (product_id, click_count, window_start, window_end)
        Coluna Family: 'cf_alerts' (is_trend)
        """
        try:
            record = json.loads(record_json)
            row_key = record["row_key"]

            hbase_row = {
                b"cf_metrics:product_id": str(record["product_id"]).encode("utf-8"),
                b"cf_metrics:click_count": str(record["click_count"]).encode("utf-8"),
                b"cf_metrics:window_start": record["window_start"].encode("utf-8"),
                b"cf_metrics:window_end": record["window_end"].encode("utf-8"),
                b"cf_alerts:is_trend": str(record["alert_trend"]).encode("utf-8"),
            }

            self._put_with_retry(row_key.encode("utf-8"), hbase_row)
            logging.info(f"[HBase Sink] Gravado com sucesso no HBase -> RowKey: {row_key}")
            return True
        except Exception as e:
            logging.error(f"[HBase Sink Error] Falha ao gravar no HBase: {e}")
            return False
