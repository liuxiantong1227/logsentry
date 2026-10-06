"""指标接口:查询分钟级聚合指标。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AdsMetricMinute, get_session
from app.schemas import MetricOut

router = APIRouter(prefix="/api/metrics", tags=["数据开发"])


@router.get("", summary="查询分钟级指标")
def list_metrics(
    path: str | None = Query(None, description="按接口路径过滤,如 /api/orders"),
    minutes: int = Query(60, ge=1, le=1440, description="往前查询多少分钟"),
    session: Session = Depends(get_session),
) -> list:
    """返回指定时间范围内的分钟级指标,按时间升序。"""
    since = datetime.now() - timedelta(minutes=minutes)
    stmt = select(AdsMetricMinute).where(AdsMetricMinute.minute >= since)
    if path:
        stmt = stmt.where(AdsMetricMinute.path == path)
    rows = session.execute(stmt.order_by(AdsMetricMinute.minute)).scalars().all()
    return [MetricOut.model_validate(r) for r in rows]