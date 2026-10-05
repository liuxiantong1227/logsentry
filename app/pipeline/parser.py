"""日志解析:把 Nginx 格式的原始日志行解析成结构化字段。"""

import re
from datetime import datetime
from typing import NamedTuple

# 匹配 Nginx combined 格式(末尾额外带响应耗时,单位秒)
LOG_PATTERN = re.compile(
    r"^(?P<ip>\S+)\s+-\s+-\s+"
    r"\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[0-9.]+\"\s+'
    r"(?P<status>\d{3})\s+"
    r"(?P<bytes>\d+)\s+"
    r"(?P<latency>[\d.]+)$"
)

TS_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


class ParsedLog(NamedTuple):
    """解析结果。用 NamedTuple 兼顾可读性与轻量。"""
    client_ip: str
    ts: datetime
    method: str
    path: str
    status: int
    bytes_sent: int
    latency_ms: float


def parse_line(raw_line: str) -> ParsedLog | None:
    """解析一行日志。解析失败返回 None,由调用方计入死信。"""
    if not raw_line:
        return None

    m = LOG_PATTERN.match(raw_line.strip())
    if not m:
        return None

    try:
        ts = datetime.strptime(m.group("ts"), TS_FORMAT)
    except ValueError:
        return None

    return ParsedLog(
        client_ip=m.group("ip"),
        ts=ts.replace(tzinfo=None),                  # 统一存 naive 时间,避免时区比较出错
        method=m.group("method"),
        path=m.group("path"),
        status=int(m.group("status")),
        bytes_sent=int(m.group("bytes")),
        latency_ms=round(float(m.group("latency")) * 1000, 2),   # 秒 → 毫秒
    )


def parse_many(raw_lines: list[str]) -> tuple[list[ParsedLog], list[str]]:
    """批量解析,返回 (成功列表, 失败列表)。"""
    ok, bad = [], []
    for line in raw_lines:
        p = parse_line(line)
        (ok if p else bad).append(p if p else line)
    return ok, bad