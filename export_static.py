"""导出静态看板:把数据库里的指标/告警/AI 诊断生成一份【自包含】的 HTML。

特点:
1. 不依赖服务器 —— 直接读数据库,生成的文件双击就能打开;
2. 不依赖网络 —— 图表用内联 SVG 手绘,没有 CDN 引用;
3. 可托管 —— 生成到 docs/index.html,可直接用 GitHub Pages 托管。

用法:
    python scripts/export_static.py
    # 打开 docs/index.html 查看
"""
import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.db import (
    AdsAnomaly, AdsMetricMinute, AiDiagnosis, DwdLogEvent, OdsLogRaw, OpsAlert, SessionLocal,
)

BASE_DIR = Path(__file__).resolve().parent.parent
OUT = BASE_DIR / "docs" / "index.html"

MAX_TREND_POINTS = 120      # 趋势图最多画多少个点
MAX_ALERTS = 20             # 告警列表最多显示多少条


# ---------------------------------------------------------------- 数据采集

def collect() -> dict:
    """从数据库把看板需要的数据全部取出来。"""
    session = SessionLocal()
    try:
        total_raw = session.execute(select(func.count()).select_from(OdsLogRaw)).scalar_one()
        total_dwd = session.execute(select(func.count()).select_from(DwdLogEvent)).scalar_one()
        total_metric = session.execute(select(func.count()).select_from(AdsMetricMinute)).scalar_one()
        total_anomaly = session.execute(select(func.count()).select_from(AdsAnomaly)).scalar_one()
        total_alert = session.execute(select(func.count()).select_from(OpsAlert)).scalar_one()

        rng = session.execute(
            select(func.min(AdsMetricMinute.minute), func.max(AdsMetricMinute.minute))
        ).one()
        time_from, time_to = rng[0], rng[1]

        # ---- 趋势:按分钟把各接口汇总 ----
        rows = session.execute(
            select(AdsMetricMinute).order_by(AdsMetricMinute.minute)
        ).scalars().all()

        buckets: dict = {}
        for r in rows:
            b = buckets.setdefault(r.minute, {"req": 0, "err": 0, "p95": 0.0})
            b["req"] += r.req_count or 0
            b["err"] += r.error_count or 0
            b["p95"] = max(b["p95"], r.p95_latency or 0.0)

        minutes = sorted(buckets)[-MAX_TREND_POINTS:]
        trend = [{
            "t": m.strftime("%H:%M"),
            "error_rate": round(buckets[m]["err"] / buckets[m]["req"], 4) if buckets[m]["req"] else 0.0,
            "p95": round(buckets[m]["p95"], 1),
            "req": buckets[m]["req"],
        } for m in minutes]

        # ---- 接口维度汇总(用于表格) ----
        path_rows = session.execute(
            select(
                AdsMetricMinute.path,
                func.sum(AdsMetricMinute.req_count),
                func.sum(AdsMetricMinute.error_count),
                func.avg(AdsMetricMinute.p95_latency),
            ).group_by(AdsMetricMinute.path).order_by(func.sum(AdsMetricMinute.req_count).desc())
        ).all()
        paths = [{
            "path": p,
            "req": int(req or 0),
            "err": int(err or 0),
            "error_rate": round((err or 0) / req, 4) if req else 0.0,
            "p95_avg": round(float(p95 or 0), 1),
        } for p, req, err, p95 in path_rows]

        # ---- 告警(带异常信息 + AI 诊断)----
        alert_rows = session.execute(
            select(OpsAlert, AdsAnomaly)
            .join(AdsAnomaly, OpsAlert.anomaly_id == AdsAnomaly.id)
            .order_by(OpsAlert.created_at.desc())
            .limit(MAX_ALERTS)
        ).all()

        diag_map = {}
        for d in session.execute(select(AiDiagnosis)).scalars().all():
            diag_map[d.anomaly_id] = {
                "model": d.model,
                "answer": d.answer or "",
                "tokens": d.prompt_tokens or 0,
            }

        alerts = []
        for alert, anomaly in alert_rows:
            alerts.append({
                "level": alert.level,
                "message": alert.message,
                "acked": bool(alert.acked),
                "path": anomaly.path,
                "metric": anomaly.metric_name,
                "value": anomaly.value,
                "baseline": anomaly.baseline,
                "ratio": anomaly.ratio,
                "minute": anomaly.minute.strftime("%Y-%m-%d %H:%M") if anomaly.minute else "",
                "diag": diag_map.get(anomaly.id),
            })

        # ---- AI 诊断(取最新一条展示全文)----
        latest_diag = None
        for a in alerts:
            if a["diag"]:
                latest_diag = a
                break

        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kpi": {
                "raw": total_raw, "dwd": total_dwd, "metric": total_metric,
                "anomaly": total_anomaly, "alert": total_alert,
            },
            "time_from": time_from.strftime("%Y-%m-%d %H:%M") if time_from else "-",
            "time_to": time_to.strftime("%Y-%m-%d %H:%M") if time_to else "-",
            "trend": trend,
            "paths": paths,
            "alerts": alerts,
            "latest_diag": latest_diag,
        }
    finally:
        session.close()


# ---------------------------------------------------------------- SVG 图表

def line_chart(values: list, *, width=860, height=230, color="#2b6cb0",
               fmt="{:.0f}", unit="") -> str:
    """用内联 SVG 画折线图 —— 不依赖任何 JS 图表库。"""
    n = len(values)
    if n == 0:
        return '<div class="nodata">暂无数据</div>'
    if n == 1:
        values = values * 2
        n = 2

    pad_l, pad_r, pad_t, pad_b = 62, 18, 18, 30
    pw = width - pad_l - pad_r
    ph = height - pad_t - pad_b

    top = max(values)
    top = top * 1.15 if top > 0 else 1.0

    def px(i):
        return pad_l + pw * i / (n - 1)

    def py(v):
        return pad_t + ph * (1 - v / top)

    parts = []
    # 网格 + Y 轴刻度
    for k in range(5):
        v = top * k / 4
        y = py(v)
        parts.append(
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#eaeff5" stroke-width="1"/>'
            % (pad_l, y, width - pad_r, y)
        )
        parts.append(
            '<text x="%d" y="%.1f" text-anchor="end" font-size="11" fill="#93a1b3">%s%s</text>'
            % (pad_l - 8, y + 4, fmt.format(v), unit)
        )

    pts = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, v in enumerate(values))
    # 面积
    parts.append(
        '<polygon points="%.1f,%.1f %s %.1f,%.1f" fill="%s" fill-opacity="0.10"/>'
        % (px(0), py(0), pts, px(n - 1), py(0), color)
    )
    # 折线
    parts.append(
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" '
        'stroke-linejoin="round" stroke-linecap="round"/>' % (pts, color)
    )
    # 首尾点
    for i in (0, n - 1):
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>' % (px(i), py(values[i]), color)
        )

    return '<svg viewBox="0 0 %d %d" class="chart" preserveAspectRatio="none">%s</svg>' % (
        width, height, "".join(parts)
    )


# ---------------------------------------------------------------- HTML 渲染

def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render(d: dict) -> str:
    kpi = d["kpi"]
    trend = d["trend"]

    er_values = [t["error_rate"] * 100 for t in trend]      # 百分比
    p95_values = [t["p95"] for t in trend]

    er_chart = line_chart(er_values, color="#b00020", fmt="{:.1f}", unit="%")
    p95_chart = line_chart(p95_values, color="#b8860b", fmt="{:.0f}", unit="ms")

    first_t = esc(trend[0]["t"]) if trend else "-"
    last_t = esc(trend[-1]["t"]) if trend else "-"

    # 接口表格
    path_tr = "".join(
        "<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s ms</td></tr>" % (
            esc(p["path"]), p["req"], p["err"], "%.2f%%" % (p["error_rate"] * 100), p["avg_p95"] if False else p["p95_avg"]
        ) for p in d["paths"]
    ) or '<tr><td colspan="5" class="nodata">暂无数据</td></tr>'

    # 告警列表
    alert_html = []
    for a in d["alerts"]:
        cls = "critical" if a["level"] == "critical" else "warning"
        ack = '<span class="tag ok">已确认</span>' if a["acked"] else '<span class="tag pending">待处理</span>'
        alert_html.append(
            '<div class="alert %s">'
            '<div class="alert-head"><span class="tag %s">%s</span>%s'
            '<span class="alert-time">%s</span></div>'
            '<div class="alert-msg">%s</div>'
            '</div>' % (cls, cls, esc(a["level"].upper()), ack, esc(a["minute"]), esc(a["message"]))
        )
    alerts_block = "".join(alert_html) or '<div class="nodata">暂无告警</div>'

    # AI 诊断
    if d["latest_diag"] and d["latest_diag"]["diag"]:
        dg = d["latest_diag"]
        diag_block = (
            '<div class="diag-meta">针对接口 <code>%s</code> 的 <code>%s</code> · '
            '模型 %s · 消耗 %s tokens</div><pre class="diag-body">%s</pre>'
            % (esc(dg["path"]), esc(dg["metric"]), esc(dg["diag"]["model"]),
               dg["diag"]["tokens"], esc(dg["diag"]["answer"]))
        )
    else:
        diag_block = '<div class="nodata">暂无 AI 诊断记录</div>'

    tpl = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LogSentinel · 智能运维日志分析平台</title>
<style>
  :root{--ink:#1f3a5f;--bg:#f4f6f9;--card:#fff;--line:#e6ecf3;--muted:#7b8a9c;
        --danger:#b00020;--warn:#b8860b;--ok:#1e7b4f;}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:#20303f;
       font-family:"Microsoft YaHei",system-ui,-apple-system,sans-serif;}
  header{background:linear-gradient(120deg,#1f3a5f,#2b6cb0);color:#fff;padding:26px 34px;}
  header h1{margin:0 0 8px;font-size:22px;font-weight:700;}
  header p{margin:0;opacity:.88;font-size:13px;line-height:1.7;}
  .snapshot{display:inline-block;margin-top:10px;padding:3px 10px;border-radius:12px;
            background:rgba(255,255,255,.18);font-size:12px;}
  main{max-width:1180px;margin:0 auto;padding:24px 34px 60px;}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:20px;}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;}
  .kpi .label{font-size:12px;color:var(--muted);}
  .kpi .value{font-size:26px;font-weight:700;color:var(--ink);margin-top:6px;line-height:1.1;}
  .kpi .sub{font-size:11px;color:var(--muted);margin-top:4px;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:18px 20px;margin-bottom:18px;}
  .card h2{margin:0 0 14px;font-size:15px;color:var(--ink);display:flex;
           justify-content:space-between;align-items:center;}
  .card h2 .range{font-size:12px;color:var(--muted);font-weight:400;}
  .chart{width:100%;height:230px;display:block;}
  .nodata{color:var(--muted);font-size:13px;padding:16px 0;text-align:center;}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);}
  th{color:var(--muted);font-weight:600;font-size:12px;}
  code{background:#f2f6fa;padding:1px 6px;border-radius:4px;
       font-family:Consolas,Monaco,monospace;font-size:12.5px;}
  .tag{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11px;font-weight:600;}
  .tag.critical{background:#fdecea;color:var(--danger);}
  .tag.warning{background:#fff8e1;color:var(--warn);}
  .tag.ok{background:#e8f5e9;color:var(--ok);font-weight:400;margin-left:8px;}
  .tag.pending{background:#eef2f7;color:var(--muted);font-weight:400;margin-left:8px;}
  .alert{border-left:3px solid var(--line);padding:10px 14px;margin-bottom:8px;
         border-radius:0 6px 6px 0;background:#fbfcfe;}
  .alert.critical{border-left-color:var(--danger);}
  .alert.warning{border-left-color:var(--warn);}
  .alert-head{display:flex;align-items:center;gap:4px;margin-bottom:5px;}
  .alert-time{font-size:11px;color:var(--muted);margin-left:auto;}
  .alert-msg{font-size:13px;line-height:1.6;}
  .diag-meta{font-size:12px;color:var(--muted);margin-bottom:10px;}
  pre.diag-body{white-space:pre-wrap;background:#fafbfc;border:1px solid var(--line);
                border-radius:8px;padding:14px;font-size:12.8px;line-height:1.75;
                font-family:"Microsoft YaHei",Consolas,monospace;margin:0;max-height:420px;
                overflow:auto;}
  footer{text-align:center;color:var(--muted);font-size:12px;padding:22px;line-height:1.8;}
</style>
</head>
<body>
<header>
  <h1>LogSentinel · 智能运维日志分析平台</h1>
  <p>日志采集 → 数仓分层 → 指标聚合 → 异常检测 → 告警闭环 → AI 根因分析</p>
  <div class="snapshot">📸 静态数据快照 · 生成于 {{generated_at}}</div>
</header>

<main>
  <div class="kpis">
    <div class="kpi"><div class="label">原始日志(ODS)</div><div class="value">{{raw}}</div><div class="sub">条</div></div>
    <div class="kpi"><div class="label">结构化事件(DWD)</div><div class="value">{{dwd}}</div><div class="sub">条 · 解析成功</div></div>
    <div class="kpi"><div class="label">分钟级指标(ADS)</div><div class="value">{{metric}}</div><div class="sub">行</div></div>
    <div class="kpi"><div class="label">检出异常</div><div class="value" style="color:var(--danger)">{{anomaly}}</div><div class="sub">条</div></div>
    <div class="kpi"><div class="label">生成告警</div><div class="value" style="color:var(--warn)">{{alert}}</div><div class="sub">条</div></div>
  </div>

  <div class="card">
    <h2>错误率趋势 <span class="range">{{time_from}} ~ {{time_to}}</span></h2>
    {{er_chart}}
  </div>

  <div class="card">
    <h2>P95 延迟趋势 <span class="range">{{first_t}} ~ {{last_t}}</span></h2>
    {{p95_chart}}
  </div>

  <div class="card">
    <h2>接口维度汇总</h2>
    <table>
      <thead><tr><th>接口</th><th>请求数</th><th>错误数</th><th>错误率</th><th>平均 P95</th></tr></thead>
      <tbody>{{path_tr}}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>告警列表 <span class="range">最近 {{alert}} 条</span></h2>
    {{alerts_block}}
  </div>

  <div class="card">
    <h2>AI 根因分析(示例)</h2>
    {{diag_block}}
  </div>
</main>

<footer>
  LogSentinel v0.1.0 · 本页面为静态数据快照,由 <code>scripts/export_static.py</code> 生成<br/>
  技术栈:FastAPI · SQLAlchemy · pandas · APScheduler · Docker · GitHub Actions · LLM
</footer>
</body>
</html>
"""
    for key, value in {
        "generated_at": esc(d["generated_at"]),
        "raw": kpi["raw"], "dwd": kpi["dwd"], "metric": kpi["metric"],
        "anomaly": kpi["anomaly"], "alert": kpi["alert"],
        "time_from": esc(d["time_from"]), "time_to": esc(d["time_to"]),
        "first_t": first_t, "last_t": last_t,
        "er_chart": er_chart, "p95_chart": p95_chart,
        "path_tr": path_tr,
        "alerts_block": alerts_block,
        "diag_block": diag_block,
    }.items():
        tpl = tpl.replace("{{" + key + "}}", str(value))
    return tpl


def main() -> int:
    print("正在从数据库采集数据 ...")
    data = collect()
    print("  原始日志 %d 条 | 结构化 %d 条 | 指标 %d 行 | 异常 %d 条 | 告警 %d 条"
          % (data["kpi"]["raw"], data["kpi"]["dwd"], data["kpi"]["metric"],
             data["kpi"]["anomaly"], data["kpi"]["alert"]))
    print("  趋势点 %d 个 | 接口 %d 个 | 告警 %d 条"
          % (len(data["trend"]), len(data["paths"]), len(data["alerts"])))

    html_text = render(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_text, encoding="utf-8")

    size_kb = OUT.stat().st_size / 1024
    print()
    print("已生成静态看板: %s" % OUT)
    print("文件大小: %.1f KB(自包含,无外部依赖)" % size_kb)
    print()
    print("下一步:")
    print("  1. 双击打开这个 HTML 预览")
    print("  2. 上传到 GitHub 仓库的 docs/ 目录")
    print("  3. 仓库 Settings -> Pages -> Source 选 main 分支 /docs 目录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
