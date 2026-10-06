"""定时调度:周期性执行 解析 → 聚合 → 检测 全链路。"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.pipeline.aggregate import run_aggregate
from app.pipeline.detect import run_detect
from app.pipeline.parse_job import run_parse

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_pipeline_once() -> dict:
    """执行一次完整数据链路:解析 → 聚合 → 检测。"""
    session = SessionLocal()
    try:
        parse_result = run_parse(session)
        agg_result = run_aggregate(session)
        detect_result = run_detect(session)
        result = {"parse": parse_result, "aggregate": agg_result, "detect": detect_result}
        log.info("管道执行完成: %s", result)
        return result
    except Exception:
        log.exception("管道执行失败")
        session.rollback()
        raise
    finally:
        session.close()


def start_scheduler() -> BackgroundScheduler | None:
    """启动后台调度器:每分钟跑一次数据链路。"""
    global _scheduler

    if not settings.scheduler_enabled:
        log.info("调度器已关闭(SCHEDULER_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        run_pipeline_once,
        trigger="interval",
        minutes=1,
        id="log_pipeline",
        max_instances=1,          # 同一任务不允许并发,避免数据竞争
        coalesce=True,            # 堆积的任务合并成一次执行
        replace_existing=True,
    )
    _scheduler.start()
    log.info("调度器已启动:每分钟执行一次数据管道")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("调度器已停止")