# Safety Gate AI 后端阶段验收与交接

日期：2026-11-13。基线 `927a2e89fb0c3fe6faa6e13c8050d254f7fa5dab`。本次交付后端阶段，不代表 Safety Gate AI 完整页面流程或完整 V1 已完成。[当前交接卡](../../AGENT-HANDOFF-CURRENT.md)列明全部模块、发布条件与接手顺序。

## 实现范围

- 精确选择 `snapshot_id + alert_id`，支持历史引用和指定周报的在线重核；最多 6 个告警，沿用 400 事实／44000 字节限制，超限拒绝。
- `safety-gate-fact-selection@1` 固定 26 个字段及完整有序事实，绑定官方原生身份、报告／告警发布时间、观察／核验时间、哈希、Parser 与许可声明。
- `safety-gate-grounding@1` 只允许模型选择事实 ID，文字由服务器生成；禁止推断、非空模型文字／uncertainty、跨告警拼接。适用性保持 `not_assessed`。
- 复用单次外发确认、预算、请求账本、同步／流式执行及最终材料重验。外部 Key 或持续回退权限不自动取得 AI 授权。
- 报告使用 `research-report@5` / `frozen-research-export@6`；创建时核对正式材料，恢复与导出使用冻结合同，旧 schema 保持原版本。

## 本轮已验证

专项受管测试 `.artifacts/sg-ai-core-r2/result.json`：18／18 通过，无跳过；826 个输入前后稳定、自有资源关闭、非自检拒绝 0、真实 Provider／接收端调用 0。

结果 SHA256：`1350b52c4635e9639e54d28183003d01271e59fd3d08d7d9f49b82c9d1a15878`。

覆盖历史包、在线重核及单次回退、8 种材料／事实篡改、外发同意、历史问题时态限制、同步与流式事实输出、拒绝推断和空白文字、准备后原件损坏零模型调用、Markdown／HTML 冻结恢复及跨告警拼接拒绝。所有 Provider 为测试合成类，不评价真实模型语义质量。

最终兼容回归 `.artifacts/sg-ai-regression-r2/result.json`：20 模块 **527／527 通过**，无跳过；826 个输入前后稳定、自有资源关闭、非自检拒绝 0、真实 Provider／接收端调用 0。结果 SHA256：`8e45ef837a73b64d5a216bd8cae6ebfdd5a262ed69eafa48e927cb0887dfc888`。包含旧报告的固定导出字节回归与 Markdown／HTML／PDF 兼容检查；新增 Safety Gate 本身的 PDF 仍待专项验收。

收尾静态检查覆盖 20 个改动文件、14 个 Python 文件 AST 与 122 个本地文档链接，未发现新增个人路径／凭据匹配；`git diff --check` 通过。原规格字节保持一致，封存交接尾文 Git LF SHA256 保持 `55e7f298d159af75eefa0bb4230a9f1193b2938223e51cf2a41c1f9c79d43bab`。静态扫描不能替代完整安全审计。

兼容范围为以下 20 个测试模块（均位于 `apps/api/tests/`）：

| 范围 | 模块 |
| --- | --- |
| Safety Gate | `test_safety_gate_ai.py`、`test_safety_gate.py` |
| 通用 AI／流式／正文 | `test_ai.py`、`test_ai_stream_api.py`、`test_ai_stream_parser.py`、`test_ai_stream_execution.py`、`test_ai_original_text.py` |
| NHTSA | `test_recall_ai_consumers.py`、`test_recall_grounding.py`、`test_recall_reports.py` |
| 专业测试事实合同 | `test_test_ai_contract.py`、`test_test_ai_grounding_review.py`、`test_test_ai_stream_terminal.py`、`test_test_ai_reports.py` |
| 报告 | `test_reports.py`、`test_report_rendering.py` |
| 车型材料 | `test_vehicle_binary_dispatch.py` |
| 历史可选 Provider 协议兼容 | `test_ai_chat_provider.py`、`test_ai_anthropic_provider.py`、`test_ai_gemini_provider.py` |

新 clone 安装项目依赖后，使用项目 Python 环境从仓库根目录执行受管入口；每轮使用新的输出目录，不覆盖旧失败：

```sh
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/sg-ai-recheck-001 --targets apps/api/tests/test_safety_gate_ai.py
```

完整兼容回归将上表 20 个模块路径全部传给 `--targets`。需核对最终 result.json 的 passed、输入稳定、资源关闭及非预期拒绝情况，不能只依据 progress 的末行或 pytest 数量。

## 原始失败与修正

1. 初始 red 回执 `.artifacts/sg-ai-red-r1/result.json` 记录引用类型尚未实现时的失败，SHA256 为 `fb9407115c1a7208b57321bddddc6569bf744b970befb51577159164f868b83b`。
2. `.artifacts/sg-ai-core-r1/result.json` 为 17 通过／1 失败，SHA256 为 `484295c4631c48526f833d8a7c47079026e7bbef12e99d0be7a9e3b7dd785b29`。失败为同步／流式正常路径测试的终态等待超时。只读核对隔离数据库发现流式完成记录为 `outcome_unknown / ai_provider_network_error`。
3. 根因是测试在应用 lifespan 启动后才替换 `app.state.ai_adapter`，流式 supervisor 已保存原适配器。隔离规则记录一次非自检拒绝，真实 Provider／接收端调用仍为 0。修正为启动前注入合成 Provider 和来源 Adapter，并使用 `execution.terminal` 等待所有终态；没有修改生产网络重试、超时或降级行为。随后专项 18／18 通过。
4. 首次 20 模块兼容回归 `.artifacts/sg-ai-regression-r1/` 在第 136 个用例停滞，没有最终 result.json，不能按通过计入。该旧生命周期单元测试以 `object()` 代替数据库，原隔离 fixture 未替换新增 Safety Gate dispatch 检查，随后无限等待 Provider ready。精确终止本轮两个 Python 进程并确认匹配进程为 0，保留 progress 与 interruption.json；为该纯单元测试补齐隔离端口，并给 6 处 ready 等待增加 5 秒上限。生产检查不放宽，真实数据库路径由正常 API 测试覆盖。

历史失败回执原样保留；私有数据库、原件、凭据及 `.artifacts/` 不提交，新 clone 不带这些本机回执。

## 未验范围与下一步

1. 共享 TypeScript 类型、SDK prepare 返回联合类型、Safety Gate 告警分析按钮、AI 目标、包预览、原件恢复及流式边界提示尚未接入。普通 Safety Gate 页面及 Native 共享工作台已存在，新增 AI 消费流程尚未完成。
2. 补齐负 ID、错周报／错告警、核验失效、容量、最终发送包／收件模型／body 篡改、完成时材料损坏、预算／幂等／跨会话和混合证据专项反例；补 Safety Gate PDF 验收。
3. 前端接通后运行 SDK、三端类型、Web、生产构建及正常 HTTP／生产页面流程。本轮仅后端测试，不复用上一阶段前端绿灯冒充新增 AI 界面验收。
4. 使用公开官方历史材料与明确合成 Provider 完成正常工程链验证；真实 Responses、Embeddings 质量、真实宿主／设备、正式 PostgreSQL 外部 Reader、公网与自然长周期继续待验。
5. 首个真实 AI Provider 保持 OpenAI Responses API。原规格包含 Gemini 备选，历史提交 `d5fded1` 已实现可选适配器；那是 agent 提前排期，不是用户改选或真实 Google 调用验收。

本次不启动长期业务服务，不改数据库 schema，不修改原规格、封存交接尾文或 KIT C2。完整 V1 目标持续开放。
