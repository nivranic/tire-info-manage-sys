# Safety Gate AI 合同篡改与混合证据验证

日期：2026-11-13。基线 `2e97f9244f19bf53fb8d70bb6c7f1a6abb146201`。本轮依据[AI 实施计划](../../plans/2026-11-13-safety-gate-ai.md)补齐发送前、完成前、容量、精确身份及混合证据反例，并修正反例证明的源专属检查缺口。

## 已确认问题及修正

原实现根据证据包、外发内容和运行时包中的标记决定是否执行 Safety Gate 检查，但未将已受理请求合同中的 Safety Gate 标记纳入判定，也未核对该合同的 policy、prompt 版本及用途。

在隔离测试中，直接注入存储／调度输入变化，篡改合同摘要、版本、移除合同标记，或同时移除存储包和外发内容的全部 Safety Gate 标记，8 个同步／流式场景仍实际调用一次合成模型并完成。这个结果证明防御性检查有缺口；注入绕过了普通接口的只追加保护，不是正常客户端获准改写账本的证明。

`ai_safety_gate_contract.require_dispatch` 现在同时读取已落账合同中的 policy、专属 prompt 版本、主 prompt 版本和用途标记。任一表明 Safety Gate 的输入都必须执行专属校验；不能因其他可变输入的标记消失而降级。发送及完成时要求受理合同与有效冻结包的 policy、prompt 和用途一致，沿用原有正文哈希、归属、收件模型与原件重验。

不新增表、权限、重试、降级或 Provider 配置，不修改既有报告正文与渲染版本。

## 新增验证范围

`apps/api/tests/test_safety_gate_ai_guards.py` 共 35 项：

- 20 项同步／流式发送前反例：正文、问题、模型、Provider、存储包、归属、合同摘要、合同版本、合同标记移除、全部可变输入标记移除。拒绝时无 Provider 调用，持久化失败终态、零用量。
- 4 项完成前反例：原件或受理合同在生成后变化，结果拒绝，已发生的合成 Provider 用量保留为 30 tokens，流式草稿不作为正式结果返回。
- 3 项混合证据正常流程：Safety Gate＋NHTSA、Safety Gate＋人工测试、三域组合，分别引用并保存／导出 Markdown、HTML、PDF，保留各域边界；跨域拼接单条 claim 拒绝。
- 4 项历史选择反例：核验状态失败、关联 QueryRun 非成功、Parser 身份不符、告警不在快照，均不保存包、不调用模型。
- 1 项超过 6 个选择在抓取前拒绝，2 项历史／在线大字段容量超限拒绝且不截断或落包。
- 1 项正常负 ID 流程：`-1782`、未知字段，经过准备／分析／保存／PDF 导出仍保持身份、null 与固定边界。

存储包内容或归属被破坏时，流式详情端点仍分别返回 409／404。测试同时核对私库中的失败完成记录，没有放宽读取端权限或完整性检查。

## 回执与失败保留

1. `.artifacts/sg-ai-guards-r1/result.json`：30 项中 20 通过、10 失败；SHA256 `0e46ea7c72509d0a42d1f7687e2ecbe83af3a2f7222b5913d43a5366b8336a40`。8 项为上述实际漏检，另 2 项为测试预期仍可读取已被破坏的包，实际端点按既有合同正确拒绝。已保存逐场景模型调用数、终态与用量，失败未覆盖。
2. 修正后 `.artifacts/sg-ai-guards-r2/result.json`：新增 35 项＋原有 18 项，**53／53 通过**，829 输入稳定、资源关闭、非自检拒绝 0、真实 Provider／接收端调用 0；SHA256 `1eb337b340d2c9b79b441f532cd25c311a6ed5364e068e7d5650ff995702ff72`。
3. 最终 `.artifacts/sg-ai-guards-final/result.json`：13 模块 **306／306 通过**、无跳过，829 输入稳定、资源关闭、非自检拒绝 0、真实 Provider／接收端调用 0；SHA256 `9f0f7e6b7a2791eeafccabb5e8a2cc3f232707c10000194076604eadb82d432e`。

最终模块包括本轮两份 Safety Gate AI 测试、`test_ai.py`、`test_ai_stream_api.py`、`test_ai_stream_execution.py`、`test_ai_original_text.py`、`test_recall_ai_consumers.py`、`test_test_ai_contract.py`、`test_test_ai_stream_terminal.py`、`test_test_ai_reports.py`、`test_reports.py`、`test_report_rendering.py`、`test_ai_rule_drafts.py`，均位于 `apps/api/tests/`。旧域正常调用、流式生命周期、冻结报告及规则草稿兼容性在本轮范围内通过。

收尾静态检查：9 个改动文件、3 个 Python 文件 AST、127 个本地文档链接通过；未发现新增个人路径或凭据模式，`git diff --check` 通过。原规格字节不变，封存交接尾文 Git LF SHA256 保持 `55e7f298d159af75eefa0bb4230a9f1193b2938223e51cf2a41c1f9c79d43bab`。

复跑使用项目 Python 环境，从仓库根目录执行；每轮使用新的输出目录：

```sh
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/sg-ai-guards-recheck-001 --targets apps/api/tests/test_safety_gate_ai_guards.py apps/api/tests/test_safety_gate_ai.py
```

原件、私库、凭据和 `.artifacts/` 不入 Git；新 clone 须自行重建测试环境，不能把文档中的本机回执当作已现场复核。

## 尚未证明

本轮均为受管隔离数据库与合成 Provider，没有真实官网或模型调用，没有生产浏览器或 Native 新验收；上一消费者阶段的 HTTP／页面回执单独保留。本轮修正不改变首个真实 Provider 为 OpenAI Responses API 的选择。

真实模型质量、正式 PostgreSQL 外部 Reader、实际 Native 宿主／设备、自然长周期监控、真实 SKU／专业材料／人工 Golden、生产身份与发布 Gate 继续推进。不能把本轮合同回归解释为完整 V1 已完成。
