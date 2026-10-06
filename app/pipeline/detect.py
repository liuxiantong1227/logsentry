"""异常检测:动态基线 + 绝对阈值地板,双重条件判定。

设计要点:
1. 基线取最近 N 分钟的中位数(抗异常值污染);
2. 相对倍数 + 绝对地板双条件,降低误报;
3. 样本量不足时跳过(小样本统计不可信);
4. 同一(接口, 指标, 分钟)只产生一条异常,保证幂等。
"""
import logging
import statistics
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AdsAnomaly, AdsMetricMinute

log = logging.getLogger(__name__)

BASELINE_MINUTES = 60      # 基线窗口长度
MIN_SAMPLES = 5            # 基线样本数下限,少于这个数不判定

# (指标字段, 中文名, 相对倍数阈值, 绝对地板值, 严重级别)
RULES = [
    ("error_rate", "错误率", 2.0, 0.05, "critical"),
    ("p95_latency", "P95 延迟", 1.5, 200.0, "warning"),
]


def _median(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    return float(statistics.median(vals)) if vals else 0.0


def detect_anomalies(session: Session) -> list[dict]:
    """检测异常并写入 ads_anomaly,返回本次新增的异常列表。"""
    latest_minute = session.execute(select(func.max(AdsMetricMinute.minute))).scalar_one()
    if latest_minute is None:
        return []

    window_start = latest_minute - timedelta(minutes=BASELINE_MINUTES)

    # 基线窗口:最新分钟【之前】的数据(不含最新分钟,避免拿异常值当基线)
    baseline_rows = session.execute(
        select(AdsMetricMinute).where(
            AdsMetricMinute.minute >= window_start,
            AdsMetricMinute.minute < latest_minute,
        )
    ).scalars().all()

    # 待检测:最新分钟的数据
    current_rows = session.execute(
        select(AdsMetricMinute).where(AdsMetricMinute.minute == latest_minute)
    ).scalars().all()

    if not current_rows:
        return []

    # 按接口汇总基线样本
    baseline: dict[str, dict[str, list]] = {}
    for r in baseline_rows:
        bucket = baseline.setdefault(r.path, {"error_rate": [], "p95_latency": []})
        bucket["error_rate"].append(r.error_rate or 0.0)
        bucket["p95_latency"].append(r.p95_latency or 0.0)

    found = []
    for cur in current_rows:
        bucket = baseline.get(cur.path)
        if not bucket or len(bucket["p95_latency"]) < MIN_SAMPLES:
            continue          # 基线样本不足,跳过,避免误报

        for field, label, ratio_limit, floor, severity in RULES:
            value = getattr(cur, field) or 0.0
            base = _median(bucket[field])
            if base <= 0:
                continue      # 基线为 0 无法计算倍数,交给绝对阈值单独处理
            if value > base * ratio_limit and value > floor:
                found.append({
                    "minute": cur.minute,
                    "path": cur.path,
                    "metric_name": field,
                    "value": round(float(value), 4),
                    "baseline": round(base, 4),
                    "ratio": round(float(value) / base, 2),
                    "severity": severity,
                    "label": label,
                })
    return found


def save_anomalies(session: Session, items: list[dict]) -> int:
    """写入异常表,幂等:同一(分钟, 接口, 指标)已存在则跳过。"""
    saved = 0
    for item in items:
        exists = session.execute(
            select(AdsAnomaly).where(
                AdsAnomaly.minute == item["minute"],
                AdsAnomaly.path == item["path"],
                AdsAnomaly.metric_name == item["metric_name"],
            )
        ).scalar_one_or_none()
        if exists:
            continue
        session.add(AdsAnomaly(
            minute=item["minute"], path=item["path"],
            metric_name=item["metric_name"], value=item["value"],
            baseline=item["baseline"], ratio=item["ratio"],
            severity=item["severity"],
        ))
        saved += 1
    session.commit()
    return saved


def run_detect(session: Session) -> dict:
    """检测任务入口。"""
    items = detect_anomalies(session)
    saved = save_anomalies(session, items)
    if saved:
        log.warning("检测到 %d 条异常", saved)
    return {"detected": len(items), "saved": saved}