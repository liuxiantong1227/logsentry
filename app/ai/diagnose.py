"""AI 根因分析编排:收集证据 → 构造 Prompt → 调用模型 → 落库缓存。"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import LLMClient
from app.config import settings
from app.db import AdsAnomaly, AdsMetricMinute, AiDiagnosis, DwdLogEvent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一名资深 SRE(站点可靠性工程师),负责分析线上服务异常并给出排查方案。

请严格遵守以下要求:
1. 只基于我提供的证据推理,不要编造未提供的信息(如服务器配置、代码实现);
2. 若证据不足以确定根因,请明确指出"需要进一步确认",并说明用什么方法确认;
3. 输出必须使用以下固定结构:
【结论】一句话概括最可能的原因
【可能原因】按可能性从高到低列出,每条注明判断依据
【排查步骤】可直接执行的命令或操作,标出先后顺序
【处置建议】短期止血措施 + 长期改进建议
4. 排查步骤要具体(如具体看哪个日志、查哪个指标),不要写"检查服务状态"这类空话。"""


def _recent_metrics(session: Session, path: str, minute: datetime, window: int = 10) -> list:
    """取该接口在异常时间附近的指标序列,作为趋势证据。"""
    start = minute - timedelta(minutes=window)
    return session.execute(
        select(AdsMetricMinute)
        .where(AdsMetricMinute.path == path,
               AdsMetricMinute.minute >= start,
               AdsMetricMinute.minute <= minute)
        .order_by(AdsMetricMinute.minute)
    ).scalars().all()


def _log_samples(session: Session, path: str, minute: datetime, limit: int = 12) -> list:
    """取该时间窗内的日志样本,错误请求优先(它们最有诊断价值)。"""
    start, end = minute, minute + timedelta(minutes=1)
    rows = session.execute(
        select(DwdLogEvent)
        .where(DwdLogEvent.path == path,
               DwdLogEvent.ts >= start,
               DwdLogEvent.ts < end)
        .order_by(DwdLogEvent.status.desc(), DwdLogEvent.latency_ms.desc())
        .limit(limit)
    ).scalars().all()
    return rows


def _build_prompt(anomaly: AdsAnomaly, metrics: list, samples: list) -> str:
    """把证据组织成结构化文本。Prompt 的结构化程度直接决定输出质量。"""
    lines = [
        "## 一、异常信息",
        f"- 接口路径: {anomaly.path}",
        f"- 发生时间: {anomaly.minute}",
        f"- 指标名称: {anomaly.metric_name}",
        f"- 当前值: {anomaly.value}",
        f"- 历史基线: {anomaly.baseline}",
        f"- 超出倍数: {anomaly.ratio}",
        f"- 严重级别: {anomaly.severity}",
        "",
        "## 二、该接口近期指标序列",
    ]
    if metrics:
        for m in metrics:
            lines.append(
                f"- {m.minute:%H:%M} 请求{m.req_count}次 "
                f"错误率{m.error_rate:.2%} P95={m.p95_latency:.0f}ms "
                f"平均{m.avg_latency:.0f}ms QPS={m.qps}"
            )
    else:
        lines.append("- (无历史指标)")

    lines += ["", "## 三、异常时段日志样本(已按状态码、耗时排序)"]
    if samples:
        for s in samples:
            lines.append(f"- [{s.ts:%H:%M:%S}] {s.client_ip} {s.method} {s.path} "
                         f"状态{s.status} 耗时{s.latency_ms:.0f}ms")
    else:
        lines.append("- (该时段无日志样本)")

    lines += ["", "请基于以上证据给出诊断。"]
    return "\n".join(lines)


def _fallback_analysis(anomaly: AdsAnomaly) -> str:
    """规则引擎兜底:没有 API Key 或模型不可用时使用。"""
    if anomaly.metric_name == "error_rate":
        return (
            f"【结论】接口 {anomaly.path} 错误率异常升高至 {anomaly.value:.2%},"
            f"为基线的 {anomaly.ratio} 倍(规则引擎判定)。\n"
            "【可能原因】\n"
            "1. 上游依赖服务异常(数据库 / 缓存 / 第三方接口超时);\n"
            "2. 新版本发布引入代码缺陷;\n"
            "3. 突发流量导致资源不足(连接池耗尽、线程池打满)。\n"
            "【排查步骤】\n"
            "1. 查看应用错误日志中 5xx 请求的异常堆栈,定位错误类型;\n"
            "2. 检查下游依赖的健康状态与响应时间;\n"
            "3. 对比异常前后的发布记录,确认是否有变更;\n"
            "4. 查看数据库连接池与线程池的使用率。\n"
            "【处置建议】\n"
            "短期:若确认是某依赖故障,先降级该功能或增加超时重试;\n"
            "长期:为该依赖增加熔断机制,并补充对应的告警规则。"
        )
    return (
        f"【结论】接口 {anomaly.path} 的 P95 延迟升至 {anomaly.value:.0f}ms,"
        f"为基线的 {anomaly.ratio} 倍(规则引擎判定)。\n"
        "【可能原因】\n"
        "1. 慢 SQL 或数据库锁等待;\n"
        "2. 缓存失效导致请求穿透到数据库;\n"
        "3. 下游接口响应变慢;\n"
        "4. GC 停顿或 CPU 资源紧张。\n"
        "【排查步骤】\n"
        "1. 查看该接口慢请求的日志与调用链;\n"
        "2. 检查数据库慢查询日志;\n"
        "3. 查看缓存命中率;\n"
        "4. 观察服务所在机器的 CPU / 内存 / GC 指标。\n"
        "【处置建议】\n"
        "短期:对慢查询加索引或加缓存;\n"
        "长期:补齐性能监控与压测基线。"
    )


def diagnose_anomaly(session: Session, anomaly_id: int, force: bool = False) -> dict:
    """对指定异常做根因分析。默认优先返回缓存。"""
    anomaly = session.get(AdsAnomaly, anomaly_id)
    if anomaly is None:
        return {"ok": False, "error": f"异常 {anomaly_id} 不存在"}

    cached = session.execute(
        select(AiDiagnosis).where(AiDiagnosis.anomaly_id == anomaly_id)
    ).scalar_one_or_none()

    if cached and not force:
        return {"ok": True, "cached": True, "model": cached.model,
                "answer": cached.answer, "tokens": cached.prompt_tokens}

    # 1) 收集证据
    metrics = _recent_metrics(session, anomaly.path, anomaly.minute)
    samples = _log_samples(session, anomaly.path, anomaly.minute)

    # 2) 调用模型(不可用时降级)
    client = LLMClient()
    if client.available:
        result = client.chat(SYSTEM_PROMPT, _build_prompt(anomaly, metrics, samples))
        answer = result["text"] if result["ok"] else _fallback_analysis(anomaly)
        model = settings.llm_model if result["ok"] else "rule-engine(LLM 调用失败)"
        tokens = result["tokens"]
    else:
        answer, model, tokens = _fallback_analysis(anomaly), "rule-engine(未配置 Key)", 0

    # 3) 落库(已存在则更新,避免违反唯一约束)
    if cached:
        cached.model, cached.answer = model, answer
        cached.prompt_tokens, cached.created_at = tokens, datetime.now()
    else:
        session.add(AiDiagnosis(anomaly_id=anomaly_id, model=model,
                                answer=answer, prompt_tokens=tokens))
    session.commit()

    log.info("诊断完成 anomaly=%s model=%s tokens=%s", anomaly_id, model, tokens)
    return {"ok": True, "cached": False, "model": model, "answer": answer, "tokens": tokens}