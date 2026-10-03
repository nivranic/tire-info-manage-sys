# ADR-2026-058: 可观测性趋势走 DB 聚合只读端点，而非内存 telemetry

- Date: 2026-10-03
- Status: approved & implemented（波次2，commit 20189ea）
- Affected assets: apps/api/tire_api/quality.py（health_trends）、
  embedding_budget.py（budget_history）、ai_analysis.py（/v1/ai/usage/history
  接线）、apps/web/components/insight-panel.tsx、
  apps/api/tests/test_observability_trends.py
- Related: telemetry.py（内存态维持现状）；ADR-2026-054/055 的预算计量口径

## Context

`/v1/observability` 为进程内内存态（span deque maxlen=256、Prometheus 计数
器）：重启清零、无时间维度，不适合"最近 N 天来源成功率趋势"。但原始数据已
持久化——query_runs / rejected_observations / ai_requests(+completions)；
且 `source_health()` 已有 24h 聚合先例（quality.py）。

## Decision（4 项）

1. **GET /v1/source-health/trends?days=N**（1-90，默认 14；quality.py
   `health_trends`）：按 UTC 日逐日聚合 attempts/successes/failures/
   rejected；聚合在 Python 侧完成以避免 SQL 方言差异；空日补零，输出连续
   日期序列（前端折线不因无活动日断档）。
2. **GET /v1/ai/usage/history?days=N**（embedding_budget.py
   `budget_history`，经 ai_analysis.py 暴露）：ai 与 embeddings 合并（后者
   仅 billable）；有 Provider usage 用实际 total_tokens，否则按保守预留——
   与预算护栏 `budget_usage` 同口径（accounting 字符串同源），面板标注
   "不是账单金额"。
3. **前端「运行洞察」面板**（apps/web/components/insight-panel.tsx）：
   纯手写 SVG 折线图（成功率）/柱状图（解析拒绝、AI 日用量），零新依赖；
   窗口 7/14/30 天切换。
4. **内存 telemetry 维持现状**：继续服务进程诊断（span 明细、Prometheus
   抓取），不为其增加持久化。

## Verification

apps/api/tests/test_observability_trends.py：只读 GROUP-BY-日投影、零填充
连续序列、严格日期边界（query_runs / rejected_observations /
ai_requests(+completions)）。端点均只读（GET），无写路径副作用。

## Known disadvantages / Residual risk

- 趋势数据自 DB 派生、重启不丢；代价是每次查询扫描窗口内全部行——PoC 规模
  可接受，未加物化 rollup，若数据量大再议。
- 指标历史持久化 / 时序库明确不做（适度工程化，见 COHS）。

## Rollback trigger / Revisit condition

查询运行量级显著增长（趋势端点成为热点）时再评估物化 rollup；引入任何指标
后端（Prometheus 远程存储等）须重开本 ADR。
