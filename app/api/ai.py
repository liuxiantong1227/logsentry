"""AI 诊断接口:对指定异常触发根因分析。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.diagnose import diagnose_anomaly
from app.db import get_session

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])


@router.post("/diagnose/{anomaly_id}", summary="对异常做 AI 根因分析")
def diagnose(
    anomaly_id: int,
    force: bool = Query(False, description="true 表示忽略缓存,强制重新诊断"),
    session: Session = Depends(get_session),
) -> dict:
    """调用 AI 分析指定异常的原因并给出排查建议。"""
    result = diagnose_anomaly(session, anomaly_id, force=force)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "诊断失败"))
    return result