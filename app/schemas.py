"""Pydantic 出入参模型。"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

# ---------------- 上报 ----------------

class LogItem(BaseModel):
    """单条日志。"""
    raw_line: str = Field(min_length=10, description="原始日志整行")
    source: str = Field(default="app", max_length=100, description="来源标识")

class LogBatchIn(BaseModel):
    """批量上报:一次请求可提交多条日志。"""
    logs: list[LogItem] = Field(min_length=1, max_length=1000)

    @field_validator("logs")
    @classmethod
    def check_total_size(cls, v: list[LogItem]) -> list[LogItem]:
        """防止单次上报内容过大,拖垮服务。"""
        total = sum(len(item.raw_line) for item in v)
        if total > 2_000_000:      # 约 2MB
            raise ValueError("单次上报总大小超过 2MB,请拆分批次")
        return v


class IngestResult(BaseModel):
    """上报结果。"""
    received: int
    message: str = "ok"

# ---------------- 查询 ----------------

class LogOut(BaseModel):
    id: int
    source: str
    received_at: datetime
    parsed: bool
    raw_line: str

    model_config = {"from_attributes": True}


class MetricOut(BaseModel):
    minute: datetime
    path: str
    req_count: int
    qps: float
    error_count: int
    error_rate: float
    p95_latency: float
    avg_latency: float

    model_config = {"from_attributes": True}

class AnomalyOut(BaseModel):
    id: int
    minute: datetime
    path: str
    metric_name: str
    value: float
    baseline: float
    ratio: float
    severity: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: int
    anomaly_id: int
    level: str
    message: str
    acked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DiagnosisOut(BaseModel):
    anomaly_id: int
    model: str
    answer: str
    prompt_tokens: int
    created_at: datetime
    cached: bool = False

    model_config = {"from_attributes": True}