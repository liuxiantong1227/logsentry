"""指标聚合单元测试。"""
import numpy as np
import pandas as pd
import pytest

from app.pipeline.aggregate import compute_metrics


def _df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ts", "path", "status", "latency_ms"])


def test_empty_input_returns_empty():
    out = compute_metrics(_df([]))
    assert out.empty


def test_group_by_minute_and_path():
    df = _df([
        ("2026-09-21 10:00:05", "/api/orders", 200, 10.0),
        ("2026-09-21 10:00:35", "/api/orders", 200, 20.0),
        ("2026-09-21 10:00:40", "/api/users", 200, 30.0),
        ("2026-09-21 10:01:05", "/api/orders", 200, 40.0),
    ])
    out = compute_metrics(df)
    # 10:00 有 2 个接口,10:01 有 1 个接口 => 共 3 行
    assert len(out) == 3


def test_req_count_and_qps():
    df = _df([("2026-09-21 10:00:0%d" % i, "/a", 200, 10.0) for i in range(6)])
    row = compute_metrics(df).iloc[0]
    assert row["req_count"] == 6
    assert row["qps"] == pytest.approx(0.1)      # 6 / 60


def test_error_rate_only_counts_5xx():
    """4xx 是客户端错误,不该计入错误率。"""
    df = _df([
        ("2026-09-21 10:00:01", "/a", 200, 10.0),
        ("2026-09-21 10:00:02", "/a", 404, 10.0),   # 4xx,不算错
        ("2026-09-21 10:00:03", "/a", 500, 10.0),   # 5xx,算错
        ("2026-09-21 10:00:04", "/a", 200, 10.0),
    ])
    row = compute_metrics(df).iloc[0]
    assert row["error_count"] == 1
    assert row["error_rate"] == pytest.approx(0.25)


def test_p95_latency():
    """1~100 的 P95 应为 95.05(线性插值)。"""
    df = _df([("2026-09-21 10:00:00", "/a", 200, float(v)) for v in range(1, 101)])
    row = compute_metrics(df).iloc[0]
    assert row["p95_latency"] == pytest.approx(95.05, abs=0.01)


def test_p95_greater_than_average_on_long_tail():
    """长尾场景:P95 应该明显高于平均值 —— 这正是用 P95 的理由。"""
    values = [20.0] * 90 + [5000.0] * 10          # 10% 的慢请求
    df = _df([("2026-09-21 10:00:0%d" % (i % 10), "/a", 200, v)
              for i, v in enumerate(values)])
    row = compute_metrics(df).iloc[0]

    # 平均值 518ms,看起来"还能接受"
    assert row["avg_latency"] == pytest.approx(518.0)
    # 但 P95 = 5000ms,暴露出最慢的 10% 用户等了 5 秒
    assert row["p95_latency"] == 5000.0
    assert row["p95_latency"] > row["avg_latency"] * 5