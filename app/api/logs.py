"""日志接口:批量上报 + 分页查询。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import OdsLogRaw, get_session
from app.schemas import IngestResult, LogBatchIn, LogOut

router = APIRouter(prefix="/api/logs", tags=["日志"])


@router.post("/ingest", response_model=IngestResult, summary="批量上报日志")
def ingest_logs(payload: LogBatchIn, session: Session = Depends(get_session)) -> IngestResult:
    """接收客户端批量上报的日志,【原样】写入 ODS 层,不做任何加工。"""
    rows = [
        {
            "raw_line": item.raw_line,
            "source": item.source,
            "received_at": datetime.now(),
            "parsed": False,
        }
        for item in payload.logs
    ]
    try:
        # 批量插入:一次请求可能带几百条日志,逐条 add 会产生几百次数据库往返
        session.bulk_insert_mappings(OdsLogRaw, rows)
        session.commit()
    except Exception as exc:
        session.rollback()          # 失败必须回滚,否则会话处于脏状态
        raise HTTPException(status_code=500, detail=f"日志写入失败: {exc}")
    return IngestResult(received=len(rows))


@router.get("", summary="分页查询原始日志")
def list_logs(
    source: str | None = None,
    parsed: bool | None = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    """按来源 / 解析状态过滤,返回分页结果。"""
    stmt = select(OdsLogRaw)
    if source:
        stmt = stmt.where(OdsLogRaw.source == source)
    if parsed is not None:
        stmt = stmt.where(OdsLogRaw.parsed.is_(parsed))

    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(
        stmt.order_by(OdsLogRaw.id.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [LogOut.model_validate(r) for r in rows],
    }