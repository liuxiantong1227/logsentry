"""造流量脚本:模拟业务系统持续产生访问日志并上报。

用法:
    python scripts/gen_traffic.py                          # 造 300 条正常日志
    python scripts/gen_traffic.py --count 3000             # 造 3000 条
    python scripts/gen_traffic.py --fail-rate 0.4 --slow-rate 0.3   # 注入故障
"""
import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_URL = "http://127.0.0.1:8000/api/logs/ingest"

# 模拟的接口列表:混合了高频接口和低频接口
PATHS = ["/api/orders", "/api/users", "/api/products", "/api/cart", "/api/pay", "/health"]
PATH_WEIGHTS = [0.30, 0.25, 0.20, 0.10, 0.10, 0.05]     # 访问分布不均衡,更贴近真实

METHODS = ["GET", "POST"]
CLIENTS = [f"10.0.{i // 254}.{i % 254 + 1}" for i in range(120)]


def build_line(ts: datetime, ip: str, method: str, path: str,
               status: int, size: int, latency: float) -> str:
    """按 Nginx combined 格式拼一行日志(末尾额外带响应耗时,单位秒)。"""
    t = ts.strftime("%d/%b/%Y:%H:%M:%S +0800")
    return f'{ip} - - [{t}] "{method} {path} HTTP/1.1" {status} {size} {latency:.3f}'


def make_batch(count: int, fail_rate: float, slow_rate: float,
               base_time: datetime) -> list[dict]:
    """生成一批日志。fail_rate = 错误请求比例;slow_rate = 慢请求比例。"""
    logs = []
    for i in range(count):
        # 时间在 base_time 前后均匀分布,模拟真实的时间跨度
        ts = base_time + timedelta(seconds=i * 0.2)

        path = random.choices(PATHS, weights=PATH_WEIGHTS, k=1)[0]
        method = random.choice(METHODS)
        ip = random.choice(CLIENTS)

        # 状态码:按 fail_rate 注入 4xx / 5xx
        if random.random() < fail_rate:
            status = random.choices([500, 502, 503, 404], weights=[0.5, 0.2, 0.2, 0.1], k=1)[0]
        else:
            status = random.choices([200, 201, 204], weights=[0.85, 0.1, 0.05], k=1)[0]

        # 延迟:按 slow_rate 注入慢请求(模拟下游拖慢或 GC 停顿)
        if random.random() < slow_rate:
            latency = random.uniform(1.2, 4.5)
        else:
            latency = random.uniform(0.008, 0.25)

        size = random.randint(120, 8000)
        logs.append({"raw_line": build_line(ts, ip, method, path, status, size, latency),
                     "source": "gen-traffic"})
    return logs


def send(logs: list[dict], batch_size: int = 200) -> int:
    """分批上报,返回成功条数。"""
    sent = 0
    with httpx.Client(timeout=30.0) as client:
        for i in range(0, len(logs), batch_size):
            chunk = logs[i:i + batch_size]
            resp = client.post(API_URL, json={"logs": chunk})
            resp.raise_for_status()
            sent += resp.json().get("received", 0)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description="生成并上报模拟访问日志")
    parser.add_argument("--count", type=int, default=300, help="生成日志条数")
    parser.add_argument("--fail-rate", type=float, default=0.05, help="错误请求比例(0~1)")
    parser.add_argument("--slow-rate", type=float, default=0.03, help="慢请求比例(0~1)")
    parser.add_argument("--minutes", type=int, default=10, help="日志时间跨度(分钟)")
    args = parser.parse_args()

    end_time = datetime.now()
    base_time = end_time - timedelta(minutes=args.minutes)

    logs = make_batch(args.count, args.fail_rate, args.slow_rate, base_time)
    try:
        sent = send(logs)
    except httpx.ConnectError:
        print("连接失败:请先启动服务 -> uvicorn app.main:app --reload")
        return 1
    except Exception as exc:
        print(f"上报失败: {exc}")
        return 1

    print(f"上报成功 {sent} 条日志")
    print(f"  错误请求比例: {args.fail_rate:.0%}")
    print(f"  慢请求比例:   {args.slow_rate:.0%}")
    print(f"  时间跨度:     {args.minutes} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
