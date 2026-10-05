"""健康检查接口:容器编排平台和监控系统的探针会周期调用它。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.config import settings
from app.db import OdsLogRaw, get_session

router = APIRouter(prefix="/api", tags=["运维"])


@router.get("/health", summary="健康检查")
def health(session: Session = Depends(get_session)) -> dict:
    """检查服务自身与依赖(数据库)是否正常。"""
    try:
        session.execute(text("SELECT 1"))                 # 探活数据库连接
        rows = session.execute(select(func.count()).select_from(OdsLogRaw)).scalar_one()
    except Exception as exc:
       
        raise HTTPException(status_code=503, detail=f"依赖不可用: {exc}")

    return {
        "status": "ok",
        "version": __version__,
        "raw_log_rows": rows,
        "llm_enabled": settings.llm_enabled,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
