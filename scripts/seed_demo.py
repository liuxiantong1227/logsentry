"""初始化演示数据:往数据库灌一批模拟日志并跑完数据链路。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.db import OdsLogRaw, SessionLocal, init_db
from app.pipeline.aggregate import run_aggregate
from app.pipeline.detect import run_detect
from app.pipeline.parse_job import run_parse
from scripts.gen_traffic import make_batch

# ---------------- 数据规模 ----------------
COUNT = 3000            # 总条数
MINUTES = 90            # 覆盖时长(分钟),要大于看板默认查询窗口 120?不,90 < 120 即可
FAULT_MINUTES = 10      # 最后 N 分钟注入故障

# ---------------- 流量特征(正常段 / 故障段)----------------
NORMAL_FAIL_RATE = 0.01     # 正常段错误率 1%
NORMAL_SLOW_RATE = 0.01     # 正常段慢请求 1%
FAULT_FAIL_RATE = 0.50      # 故障段错误率 50%  ← 保证能触发告警
FAULT_SLOW_RATE = 0.40      # 故障段慢请求 40%  ← 保证 P95 能触发


def main() -> int:
    init_db()
    session = SessionLocal()
    try:
        # 幂等:已有数据就跳过,避免重复灌
        existing = session.execute(select(func.count()).select_from(OdsLogRaw)).scalar_one()
        if existing:
            print("已存在 %d 条日志,跳过 seed" % existing)
            return 0

        minutes_normal = MINUTES - FAULT_MINUTES
        count_normal = int(COUNT * minutes_normal / MINUTES)
        count_fault = COUNT - count_normal

        # 把"现在"对齐到整分钟:否则数据铺到此刻,当前这一分钟才过了一半,
        # 最新分钟的样本量会严重不足(每接口可能只有 1 条),指标不可信。
        now = datetime.now().replace(second=0, microsecond=0)
        base_time = now - timedelta(minutes=MINUTES)

        # ① 正常段:铺满前 80 分钟,错误率 1%、慢请求 1%
        logs = make_batch(count_normal, NORMAL_FAIL_RATE, NORMAL_SLOW_RATE,
                          base_time, minutes_normal * 60)

        # ② 故障段:最后 10 分钟,错误率 50%、慢请求 40%
        fault_start = base_time + timedelta(minutes=minutes_normal)
        logs += make_batch(count_fault, FAULT_FAIL_RATE, FAULT_SLOW_RATE,
                           fault_start, FAULT_MINUTES * 60)

        session.bulk_insert_mappings(OdsLogRaw, [
            {"raw_line": item["raw_line"], "source": "seed-demo", "parsed": False}
            for item in logs
        ])
        session.commit()
        print("已写入 %d 条原始日志(%d 分钟正常 + %d 分钟故障)"
              % (len(logs), minutes_normal, FAULT_MINUTES))

        # 跑完整数据链路
        print("解析:", run_parse(session, batch_size=100000))
        print("聚合:", run_aggregate(session))
        print("检测:", run_detect(session))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())