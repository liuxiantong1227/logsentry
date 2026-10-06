"""分钟级指标聚合。"""
import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import AdsMetricMinute, DwdLogEvent

SECONDS_PER_MINUTE = 60
METRIC_COLUMNS = ["minute", "path", "req_count", "qps",
                  "error_count", "error_rate", "p95_latency", "avg_latency"]


def load_events(session: Session, limit: int = 200_000) -> pd.DataFrame:
    """从 DWD 层读取明细数据到 DataFrame。"""
    rows = session.execute(select(DwdLogEvent).limit(limit)).scalars().all()
    if not rows:
        return pd.DataFrame(columns=["ts", "path", "status", "latency_ms"])
    return pd.DataFrame([
        {"ts": r.ts, "path": r.path, "status": r.status or 0, "latency_ms": r.latency_ms or 0.0}
        for r in rows
    ])


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """核心聚合逻辑:纯函数,不碰数据库,方便单元测试。"""
    if df.empty:
        return pd.DataFrame(columns=METRIC_COLUMNS)

    work = df.copy()

    # 1) 时间截断到「分钟」——这是时间维度聚合的关键
    work["minute"] = pd.to_datetime(work["ts"]).dt.floor("min")

    # 2) 标记错误请求(只算服务端错误)
    work["is_error"] = (work["status"] >= 500).astype(int)

    # 3) 按「分钟 + 接口」分组聚合
    out = work.groupby(["minute", "path"], as_index=False).agg(
        req_count=("status", "size"),
        error_count=("is_error", "sum"),
        avg_latency=("latency_ms", "mean"),
        p95_latency=("latency_ms", lambda s: float(np.percentile(s, 95))),
    )

    # 4) 派生指标
    out["error_rate"] = (out["error_count"] / out["req_count"]).round(4)
    out["qps"] = (out["req_count"] / SECONDS_PER_MINUTE).round(3)
    out["avg_latency"] = out["avg_latency"].round(2)
    out["p95_latency"] = out["p95_latency"].round(2)

    return out[METRIC_COLUMNS]


def save_metrics(session: Session, df: pd.DataFrame) -> int:
    """写入 ADS 层。

    幂等策略:先删掉这批数据涉及的分钟分区,再整体插入。
    这叫「分区覆盖写」,重跑多少次结果都一样。
    """
    if df.empty:
        return 0

    minutes = pd.to_datetime(df["minute"]).unique().tolist()
    session.execute(delete(AdsMetricMinute).where(AdsMetricMinute.minute.in_(minutes)))

    session.bulk_insert_mappings(AdsMetricMinute, [
        {
            "minute": r["minute"], "path": r["path"],
            "req_count": int(r["req_count"]), "qps": float(r["qps"]),
            "error_count": int(r["error_count"]), "error_rate": float(r["error_rate"]),
            "p95_latency": float(r["p95_latency"]), "avg_latency": float(r["avg_latency"]),
        }
        for r in df.to_dict("records")
    ])
    session.commit()
    return len(df)


def run_aggregate(session: Session) -> dict:
    """聚合任务入口。"""
    df = load_events(session)
    metrics = compute_metrics(df)
    saved = save_metrics(session, metrics)
    return {"events": int(len(df)), "metric_rows": int(saved)}