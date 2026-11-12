# Gemini 原生 Provider 实施计划

本计划依据原规格的 GeminiAdapter 要求，采用 brainstorming、writing-plans 与 executing-plans 的设计、实施和复核流程。用户已授权持续实施，工作使用既有main分支。

## 目标与设计

新增显式gemini Provider，使用Google原生generateContent及streamGenerateContent SSE协议。配置使用TI_GEMINI_MODEL、TI_GEMINI_API_KEY及既有TI_AI_PROVIDER。模型标识由本机配置提供，端点使用Google官方v1beta模型路径，密钥通过x-goog-api-key请求头传输。

共用现行证据封装、用途许可、单次同意、引用校验、Token预算及请求账本。请求以systemInstruction、contents及generationConfig表达现行JSON输出合同。流式路径共用UTF-8／SSE／严格JSON解码器，终态、身份、候选数和文本长度均核对。

计量将promptTokenCount与toolUsePromptTokenCount合计为输入，candidatesTokenCount与thoughtsTokenCount合计为输出，并核对totalTokenCount。缺失或非法用量沿用既有预留记账。模型推理文本和签名在协议读取阶段丢弃。

## 实施步骤

### 配置及协议

1. 在 `apps/api/tests/test_ai_gemini_provider.py` 写配置、请求体、响应及流式反例，登记到 `scripts/run_api_worker_regression.py`。
2. 使用受管入口运行新模块，保留缺少适配器时的失败回执。
3. 在 `apps/api/tire_api/ai_gateway.py` 补配置、工厂和请求体分派，在 `apps/api/tire_api/ai_gemini.py` 实现原生传输、响应及流解析。
4. 在 `apps/api/tire_api/ai_execution.py` 扩展最后一道车型用途核验对原生contents信封的读取，并补篡改反例。

### 正常入口与共享协议

1. 将gemini纳入 `candidate_ai_contract.py` 的接收方授权、`ai_pricing.py` 的人工价格类型及 `telemetry.py` 的低基数Provider统计。
2. 更新 `packages/domain-types/src/ai-price-planning.ts`、`apps/web/components/ai-budget.tsx` 和 `ai-price-planning.tsx`。
3. 使用真实应用路由验证配置状态、分析、请求幂等、账本、用量、流式解释及Provider标识。上游使用本次测试专有的合成响应。
4. 运行相关候选授权、价格规划、AI分析／流式／网关及SDK回归和三端类型检查。

## 验证命令

```powershell
apps/api/.venv/Scripts/python.exe scripts/run_api_worker_regression.py --phase run --output-root .artifacts/gem-r1 --targets apps/api/tests/test_ai_gemini_provider.py
node node_modules/typescript/bin/tsc -p apps/web/tsconfig.json --noEmit --incremental false
node node_modules/typescript/bin/tsc -p apps/desktop/tsconfig.json --noEmit --incremental false
node node_modules/typescript/bin/tsc -p apps/mobile/tsconfig.json --noEmit --incremental false
```

输出槽每批使用新名称。相关回归的最终目标清单、结果SHA及源码绑定写入续作记录。

## 验收范围

配置仅凭据与模型齐备时进入configured。非流式和流式响应均形成现行receipt，并在应用层执行现行grounding校验。安全拒绝、截断、工具内容、多个候选、终态后文本、非法JSON／UTF-8、超限及传输错误均取得固定错误结果。缺失用量由预留覆盖，单次同意和用途许可在实际外发前复核。

本机当前模型凭据缺失。真实Google运行、真实模型质量及真实OpenAI Responses语义继续保留为单独验收项。官方接口字段核对依据如下。

- [Google内容生成API](https://ai.google.dev/api/generate-content)
- [Google结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google API密钥](https://ai.google.dev/gemini-api/docs/api-key)

## 执行结果

配置／协议、正常API入口、候选授权、人工价格、遥测、共享类型及Provider选项均已落地。最终14模块受管回归366／366通过，包含本模块58项，源码稳定、资源关闭、非自检拒绝0。回执为 `.artifacts/gem-r5/result.json`，SHA256 `e17aeda2e5dfda4fce9a50d3b0e73a259f9643fb7588c1f0204fa36a4c4e211b`。

SDK价格与候选合同类型检查通过，合并Node运行56项通过。三端完整类型检查因Next／Vite／Capacitor安装内容缺失而失败，前端构建与界面验收继续待执行。原计划中的实际S2车型回归还需要恢复缺失的可信历史PDF。新增车型用例使用明确的合成capsule边界，覆盖原生信封、持久化绑定、用途许可及同步／流式终态。

真实Google模型、真实OpenAI Responses及Embeddings语义仍待本机凭据和专门验收。完整原始失败及过程见[续作记录](../assurance/evidence/continuation-2026-11-12.md)。
