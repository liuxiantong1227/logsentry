"""解析器单元测试。运行: pytest tests -q"""
from datetime import datetime

from app.pipeline.parser import parse_line, parse_many

VALID_LINE = ('10.0.1.23 - - [21/Sep/2026:10:23:45 +0800] '
              '"GET /api/orders HTTP/1.1" 200 1234 0.023')


def test_parse_valid_line():
    p = parse_line(VALID_LINE)
    assert p is not None
    assert p.client_ip == "10.0.1.23"
    assert p.method == "GET"
    assert p.path == "/api/orders"
    assert p.status == 200
    assert p.bytes_sent == 1234
    assert p.ts == datetime(2026, 9, 21, 10, 23, 45)


def test_latency_converted_to_ms():
    """0.023 秒 应换算为 23.0 毫秒。"""
    p = parse_line(VALID_LINE)
    assert p.latency_ms == 23.0


def test_parse_post_with_5xx():
    line = ('10.0.2.5 - - [21/Sep/2026:10:24:00 +0800] '
            '"POST /api/pay HTTP/1.1" 502 500 1.850')
    p = parse_line(line)
    assert p.status == 502
    assert p.method == "POST"
    assert p.latency_ms == 1850.0


def test_parse_invalid_returns_none():
    assert parse_line("这不是一条日志") is None
    assert parse_line("") is None
    assert parse_line(None) is None


def test_parse_truncated_line_returns_none():
    """被截断的日志必须判为失败,不能产生半截数据。"""
    truncated = '10.0.1.23 - - [21/Sep/2026:10:23:45 +0800] "GET /api/orders HTTP/1.1" 200'
    assert parse_line(truncated) is None


def test_parse_many_splits_ok_and_bad():
    ok, bad = parse_many([VALID_LINE, "坏数据", VALID_LINE])
    assert len(ok) == 2
    assert bad == ["坏数据"]