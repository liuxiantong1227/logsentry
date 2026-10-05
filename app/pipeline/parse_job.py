"""解析任务:把 ODS 层中【未解析】的原始日志解析后写入 DWD 层。

幂等设计:
    只处理 parsed=False 的记录,处理完立即置为 True。
    重复执行任务不会重复写入 DWD,也不会漏处理。
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import DwdLogEvent, OdsLogDeadLetter, OdsLogRaw
from app.pipeline.parser import parse_line

log = logging.getLogger(__name__)


def run_parse(session: Session, batch_size: int = 1000) -> dict:
    """解析一批未处理的日志。返回执行统计。"""
    rows = session.execute(
        select(OdsLogRaw)
        .where(OdsLogRaw.parsed.is_(False))
        .order_by(OdsLogRaw.id)
        .limit(batch_size)
    ).scalars().all()

    if not rows:
        return {"scanned": 0, "parsed": 0, "failed": 0}

    events, dead_letters = [], []
    for row in rows:
        item = parse_line(row.raw_line)
        if item is None:
            dead_letters.append(
                OdsLogDeadLetter(raw_id=row.id, raw_line=row.raw_line[:2000],
                                 error="格式不匹配或时间非法")
            )
        else:
            events.append(DwdLogEvent(
                raw_id=row.id, ts=item.ts, client_ip=item.client_ip,
                method=item.method, path=item.path, status=item.status,
                bytes_sent=item.bytes_sent, latency_ms=item.latency_ms,
            ))
        row.parsed = True          # 无论成功失败都标记已处理,避免死循环

    if events:
        session.bulk_save_objects(events)
    if dead_letters:
        session.bulk_save_objects(dead_letters)

    session.commit()

    result = {"scanned": len(rows), "parsed": len(events), "failed": len(dead_letters)}
    if dead_letters:
        log.warning("解析失败 %d 条,已写入死信表", len(dead_letters))
    return result