# 中国召回 AI 证据与引用实施计划

## 目标

沿 `d61d3b2` 接通中国召回的当前／历史公告分析、精确字段引用、同步及流式生成与正常 Web 入口。使用现有 AI 网关、幂等账本、逐包外发授权及引用校验，首个真实 Provider 采用用户选择的 OpenAI Responses API。[原规格](../requirements/2026-09-26-tire-intelligence-original.md)

## 架构与不变量

- 历史引用使用 `kind=samr_recall`、精确 `snapshot_id` 与原生 `article_id`。当前请求使用 `query_kind=samr_recall_notice`，只接受公告原生路径，并通过现有 SamrRecallService 在线优先流程核验。
- 来源检索列表继续承担发现功能。分析材料来自一份明确公告，字段选择策略固定为 `samr-recall-fact-selection@1`，保存完整所选字段、日期、来源访问依据、原件哈希、文档哈希及精确 verification。
- 全文和所选字段遵循现有证据包字节上限，超限返回明确错误。模型输出使用事实引用 ID，服务端从冻结字段生成文字，统一呈现实物适用性 `not_assessed`。
- 混合包保留既有监管目的及提示词版本，追加中国召回的独立策略和提示词标识。含中国召回材料的包使用事实选择语义，每条中国公告 claim 绑定同一份证据。
- 准备、调用受理、实际外发、流式投影及完成采纳分别核验。外发前重新加载所选原件和精确核验，核对已受理合同、问题、收件 Provider／模型及请求体哈希。标记被移除时仍依据已受理合同识别。
- Web 沿现有 AI 对话框，展示来源、独立日期、访问依据、适用性、字段和原件引用。外发使用现有逐包授权。原文及问题按数据处理。

## 实施步骤

### 1. 冻结证据选择与合同

新增 `apps/api/tire_api/samr_ai_evidence.py`、`apps/api/tire_api/ai_samr_contract.py`，复用不可变快照和 QueryRun／Verification 绑定。固定字段顺序、原生身份、时间、访问依据与事实渲染，定义完整包校验、claim 校验及实际外发校验。

### 2. 正常准备与生成入口

修改 `ai_evidence.py`、`ai_analysis.py`、`ai_gateway.py`、`ai_execution.py`、`ai_streaming.py`、`ai_stream_parser.py` 和 `ai_stream_store.py`。接入当前／历史请求、单次回退授权与 `ai_current` audience，贯通同步、流式草稿、完成前复核及历史边界。`reports.py` 和 `report_rendering.py` 冻结公告字段及合同，使用 `research-report@6` 与 `frozen-research-export@7`。验证混合监管包的既有目的和提示词版本。

### 3. 共享类型与工作台

扩展 `packages/domain-types/src/samr-recalls.ts`、`index.ts`，为证据、分析目标、准备结果、边界和输出增加类型。通过 `samr-recalls.tsx` 和公告历史入口选择精确快照，沿现有 `ai-analysis.tsx`、`ai-stream-progress.tsx` 及报告引用显示公告元数据和原件。复用已有 SDK 准备与分析方法。

### 4. 受管回归与反例

新增中国公告 AI 回归并登记 `scripts/run_api_worker_regression.py`，验证官方公告范围、原生身份、全部所选字段、当前在线核验、304、单次回退、独立持续回退范围、账户授权、历史问题、超限、日期与引用。同步及流式覆盖合法字段、空答案、自由文字、跨公告／领域拼接、未知 ID、提示注入、篡改、标记移除、实际外发绑定及费用预留。

使用正式入口运行新测试及既有 Safety Gate／NHTSA、混合证据、AI 流式与引用回归。

```text
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/<fresh-run> --targets apps/api/tests/test_samr_ai.py apps/api/tests/test_samr_ai_guards.py apps/api/tests/test_safety_gate_ai.py apps/api/tests/test_safety_gate_ai_guards.py
npm run typecheck
npm run test:samr-recalls --workspace @tire/api-client
npm run test --workspace @tire/web
npm run build
```

### 5. 实际进程与交付

执行正常 Web／HTTP 及独立非拥有者 PostgreSQL／TLS 验收，按当前 API 源码重建并审查 `@4` 合同。使用明确合成的模型适配器核对网关、费用与引用链，真实模型凭据及调用按实际可用状态独立验收。记录原始失败、源码摘要、资源关闭和剩余边界，更新交接，审查待发布提交后直连推送并核对实时远端。

## 验收完成条件

中国公告经正常在线／显式历史入口进入证据包，精确原件与字段可重开，外发需现有逐包同意，模型和源文本中的越界指令无法生成未绑定结论。同步、流式及已保存报告均展示独立日期和适用性边界，既有监管与跨平台入口通过相关回归。自然长周期、人工 Golden、精确 SKU／批次、来源许可和完整 V1 Gate 继续按总交接逐项实施。

## 当前执行

已完成冻结合同、正常 API、SDK／Web 与报告入口。最终519项受管回归、SDK14项、Web66项、生产浏览器15项、全工作区类型与构建通过，独立非拥有者PG／TLS取得真实官方公告live并完成合成Provider生成及三种导出。原始失败、合同摘要、资源关闭与剩余范围见[阶段验收](../assurance/evidence/samr-cn-ai-evidence-2026-11-14.md)，接手顺序见[阶段卡](../AGENT-HANDOFF-2026-11-14-SAMR-AI.md)。使用既有 `main`，完整V1持续进行。
