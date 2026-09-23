import json
import logging
from datetime import datetime
from pyflink.common import WatermarkStrategy, Duration, Types
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.file_system import FileSource, StreamFormat
from pyflink.datastream.functions import ProcessWindowFunction, AggregateFunction, MapFunction
from pyflink.datastream.window import TimeWindow, SlidingEventTimeWindows, Time

from hbase_sink import HBaseSink

# Configuração de Logs
logging.basicConfig(level=logging.INFO)

class EventTimestampAssigner(TimestampAssigner):
    """Extrai o timestamp ISO-8601 em milissegundos do evento JSON para o Watermark."""
    def extract_timestamp(self, value, record_timestamp):
        try:
            dt = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return record_timestamp

class ProductClickAggregate(AggregateFunction):
    """Acumulador simples para contagem de cliques/ações por produto na janela."""
    def create_accumulator(self):
        return 0

    def add(self, value, accumulator):
        return accumulator + 1

    def get_result(self, accumulator):
        return accumulator

    def merge(self, a, b):
        return a + b

class TrendTopicsWindowFunction(ProcessWindowFunction):
    """Processa o resultado da janela e formata a saída de métricas para persistência/alerta."""
    def process(self, key, context, elements):
        count = next(iter(elements))
        window_start = datetime.fromtimestamp(context.window().start / 1000).strftime('%Y-%m-%d %H:%M:%S')
        window_end = datetime.fromtimestamp(context.window().end / 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        result = {
            "row_key": f"{key}_{context.window().end}",
            "product_id": key,
            "click_count": count,
            "window_start": window_start,
            "window_end": window_end,
            "alert_trend": count >= 10  # Alerta se houver 10 ou mais cliques na janela de 5 min
        }
        return [json.dumps(result)]

class HBaseAlertSinkFunction(MapFunction):
    """Abre uma conexão HBase por subtask e grava cada métrica de janela recebida."""

    def __init__(self, host="hbase-master", port=9090):
        self.host = host
        self.port = port
        self.sink = None

    def open(self, runtime_context):
        self.sink = HBaseSink(host=self.host, port=self.port)
        self.sink.open()

    def close(self):
        if self.sink is not None:
            self.sink.close()

    def map(self, value):
        self.sink.write_alert(value)
        return value


def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)

    # Definindo Watermark Strategy com BoundedOutOfOrderness (tolera até 30 segundos de atraso)
    watermark_strategy = WatermarkStrategy \
        .for_bounded_out_of_orderness(Duration.of_seconds(30)) \
        .with_timestamp_assigner(EventTimestampAssigner())

    # Leitura do stream de logs em tempo real
    log_file_path = "/opt/flink-job/logs/flink_stream"
    source = FileSource.for_record_stream_format(
        StreamFormat.text_line_format(),
        log_file_path
    ).monitor_continuously(Duration.of_seconds(2)).build()

    stream = env.from_source(
        source=source,
        watermark_strategy=WatermarkStrategy.no_watermarks(),
        source_name="EcommerceLogSource"
    )

    # Filtrar apenas cliques e adições ao carrinho (para medir engajamento / trend topics)
    processed_stream = stream \
        .map(lambda line: json.loads(line), output_type=Types.PICKLED_BYTE_ARRAY()) \
        .filter(lambda event: event.get("action") in ["click", "add_to_cart"]) \
        .assign_timestamps_and_watermarks(watermark_strategy) \
        .key_by(lambda event: str(event.get("product_id"))) \
        .window(SlidingEventTimeWindows.of(Time.minutes(5), Time.minutes(1))) \
        .aggregate(
            aggregate_function=ProductClickAggregate(),
            window_function=TrendTopicsWindowFunction()
        )

    # Sink: grava cada métrica de janela no HBase (tabela 'ecommerce_alerts')
    processed_stream.map(HBaseAlertSinkFunction(), output_type=Types.STRING()).print()

    print("[Flink Job] Iniciando Job Flink: Trend Topics com Janela Deslizante de 5 min (slide 1 min)...")
    env.execute("Ecommerce_TrendTopics_Flink_Job")

if __name__ == "__main__":
    main()
