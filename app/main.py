
"""FastAPI 应用入口:创建应用、挂载路由、管理生命周期。"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import __version__
from app.api import health, logs, metrics, alerts, ai          # 后续阶段会继续加入 metrics / alerts / ai
from app.db import init_db
from app.pipeline.scheduler import start_scheduler, stop_scheduler

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("logsentry")

STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期钩子:启动时建表并启动调度器,关闭时停止调度器。"""
    init_db()
    log.info("数据库初始化完成,LogSentinel 启动")
    start_scheduler()
    yield
    stop_scheduler()
    log.info("LogSentinel 关闭")


app = FastAPI(
    title="LogSentinel",
    version=__version__,
    description="智能运维日志分析平台:采集 → 解析 → 聚合 → 异常检测 → AI 根因分析",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(logs.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(ai.router)

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """返回前端看板页面。"""
    return FileResponse(STATIC_DIR / "index.html")