"""引擎、会话、6 张表模型。"""
"""数据库层:引擎、会话,以及数仓三层模型 ODS / DWD / ADS。"""

from datetime import datetime

from sqlalchemy import(
    Boolean, Column, DateTime, Float, Index, Integer, String, Text, create_engine,
)

from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()

#ODS原始层
class OdsLogRaw(Base):
    """原始日志表:原样落库,不加工,保证可回溯、可重跑。"""
    __tablename__ = "ods_log_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_line = Column(Text, nullable=False)      # 原始日志整行
    source = Column(String(100), default="app")  # 来源标识
    received_at = Column(DateTime, default=datetime.now)
    parsed = Column(Boolean, default=False, index=True)  # 是否已解析

#DWD明细层
class DwdLogEvent(Base):
    """结构化事件表:正则解析后的字段。"""
    __tablename__ = "dwd_log_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_id = Column(Integer, index=True)         # 关联 ODS 的 id,便于溯源
    ts = Column(DateTime, index=True)            # 请求时间
    client_ip = Column(String(64))
    method = Column(String(10))
    path = Column(String(255), index=True)       # 接口路径
    status = Column(Integer, index=True)         # HTTP 状态码
    bytes_sent = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)      # 响应耗时(毫秒)

#ADS应用层
class AdsMetricMinute(Base):
    """分钟级指标表:看板和异常检测的数据源。"""
    __tablename__ = "ads_metric_minute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    minute = Column(DateTime, index=True)        # 分钟(截断到分)
    path = Column(String(255), index=True)
    req_count = Column(Integer, default=0)       # 请求数
    qps = Column(Float, default=0.0)             # 每秒请求数
    error_count = Column(Integer, default=0)
    error_rate = Column(Float, default=0.0)      # 错误率 0~1
    p95_latency = Column(Float, default=0.0)     # P95 延迟(毫秒)
    avg_latency = Column(Float, default=0.0)


Index("idx_metric_minute_path", AdsMetricMinute.minute, AdsMetricMinute.path, unique=True)

class AdsAnomaly(Base):
    """异常表:检测出的异常记录。"""
    __tablename__ = "ads_anomaly"

    id = Column(Integer, primary_key=True, autoincrement=True)
    minute = Column(DateTime, index=True)
    path = Column(String(255))
    metric_name = Column(String(50))             # error_rate / p95_latency / qps
    value = Column(Float)
    baseline = Column(Float)
    ratio = Column(Float)                        # 超出倍数
    severity = Column(String(20), default="warning")   # warning / critical
    created_at = Column(DateTime, default=datetime.now)

#运维
class OpsAlert(Base):
    """告警表:供运维人员确认与追踪。"""
    __tablename__ = "ops_alert"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anomaly_id = Column(Integer, index=True)
    level = Column(String(20), default="warning")
    message = Column(Text)
    acked = Column(Boolean, default=False, index=True)   # 是否已确认
    created_at = Column(DateTime, default=datetime.now)
    acked_at = Column(DateTime, nullable=True)

#AI
class AiDiagnosis(Base):
    """AI 诊断结果表:缓存 LLM 输出,避免重复付费。"""
    __tablename__ = "ai_diagnosis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anomaly_id = Column(Integer, index=True, unique=True)
    model = Column(String(100))
    answer = Column(Text)
    prompt_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


def init_db() -> None:
    """建表。应用启动时调用一次。"""
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖注入用的会话生成器。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()







