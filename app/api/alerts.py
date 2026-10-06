"""告警接口:查询告警列表 + 确认告警(状态流转)。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AdsAnomaly, AdsMetricMinute, OpsAlert, get_session
from app.schemas import AlertOut

router = APIRouter(prefix="/api/alerts", tags=["运维"])


def sync_alerts(session: Session) -> int:
    """把「尚未生成告警」的异常转成告警记录(幂等)。"""
    anomalies = session.execute(select(AdsAnomaly)).scalars().all()
    created = 0
    for a in anomalies:
        exists = session.execute(
            select(OpsAlert).where(OpsAlert.anomaly_id == a.id)
        ).scalar_one_or_none()
        if exists:
            continue
        # 基线为 0 时无法计算倍数,文案要单独处理
        # (否则会显示成"基线 0.0,超出 0.0 倍",读起来莫名其妙)
        if a.baseline > 0:
            message = (f"[{a.severity.upper()}] 接口 {a.path} 的 {a.metric_name} "
                       f"达 {a.value},基线 {a.baseline},超出 {a.ratio} 倍")
        else:
            message = (f"[{a.severity.upper()}] 接口 {a.path} 的 {a.metric_name} "
                       f"达 {a.value}(历史基线为 0,本次突增)")

        session.add(OpsAlert(
            anomaly_id=a.id,
            level=a.severity,
            message=message,
        ))
        created += 1
    if created:
        session.commit()
    return created


@router.get("", summary="查询告警列表")
def list_alerts(
    acked: bool | None = Query(None, description="是否已确认"),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    # 每次查询前先同步一次,保证异常能及时变成告警
    sync_alerts(session)

    stmt = select(OpsAlert)
    if acked is not None:
        stmt = stmt.where(OpsAlert.acked.is_(acked))
    rows = session.execute(
        stmt.order_by(OpsAlert.created_at.desc()).limit(limit)
    ).scalars().all()
    return {"total": len(rows), "items": [AlertOut.model_validate(r) for r in rows]}


@router.post("/{alert_id}/ack", summary="确认告警")
def ack_alert(alert_id: int, session: Session = Depends(get_session)) -> dict:
    """把告警标记为已处理。这是运维值班的标准动作。"""
    alert = session.get(OpsAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.acked:
        return {"id": alert_id, "acked": True, "message": "该告警已确认过"}

    alert.acked = True
    alert.acked_at = datetime.now()
    session.commit()
    return {"id": alert_id, "acked": True, "message": "已确认"}
