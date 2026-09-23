"""Testes unitários do HBaseSink (flink/hbase_sink.py), sem dependência de um HBase real."""
import json
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flink"))

from hbase_sink import HBaseSink  # noqa: E402


def make_sink_with_mock_table():
    sink = HBaseSink()
    sink.table = MagicMock()
    return sink


def test_write_alert_puts_expected_row():
    sink = make_sink_with_mock_table()
    record = {
        "row_key": "101_1700000000000",
        "product_id": "101",
        "click_count": 12,
        "window_start": "2026-09-22 10:00:00",
        "window_end": "2026-09-22 10:05:00",
        "alert_trend": True,
    }

    ok = sink.write_alert(json.dumps(record))

    assert ok is True
    sink.table.put.assert_called_once()
    row_key_arg, row_data_arg = sink.table.put.call_args[0]
    assert row_key_arg == b"101_1700000000000"
    assert row_data_arg[b"cf_metrics:click_count"] == b"12"
    assert row_data_arg[b"cf_alerts:is_trend"] == b"True"


def test_write_alert_returns_false_on_malformed_json():
    sink = make_sink_with_mock_table()
    ok = sink.write_alert("not-a-json-payload")
    assert ok is False
    sink.table.put.assert_not_called()


def test_write_alert_returns_false_on_missing_field():
    sink = make_sink_with_mock_table()
    ok = sink.write_alert(json.dumps({"row_key": "abc"}))
    assert ok is False
    sink.table.put.assert_not_called()


def test_write_alert_reconnects_and_retries_on_broken_connection():
    sink = make_sink_with_mock_table()
    sink.table.put.side_effect = [BrokenPipeError("Broken pipe"), None]
    sink.close = MagicMock()
    sink.open = MagicMock()
    record = {
        "row_key": "101_1700000000000",
        "product_id": "101",
        "click_count": 12,
        "window_start": "2026-09-22 10:00:00",
        "window_end": "2026-09-22 10:05:00",
        "alert_trend": True,
    }

    ok = sink.write_alert(json.dumps(record))

    assert ok is True
    sink.open.assert_called_once()
    assert sink.table.put.call_count == 2
