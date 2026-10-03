# ADR-2026-054: 新增 openai_chat（Chat Completions 兼容）Provider 适配器

- Date: 2026-10-03
- Status: approved & implemented（用户指令"就做c"）
- Affected assets: apps/api/tire_api/ai_gateway.py、ai_analysis.py（1 行）、
  embedding_gateway.py（可选 base URL）、tests/test_ai_chat_provider.py
- Related: 原规格 A5 多模型体系；HANDOFF §3 域11 与 §7"中国区Provider未指定"；
  ADR-2026-052/053（同轮纪律）

## Context

当前唯一真实协议适配器是 OpenAI Responses（端点硬编码 api.openai.com，DNS 钉扎）。
国内模型（GLM/DeepSeek/Kimi/Qwen）与本地运行时（vLLM/Ollama）提供的是
OpenAI **Chat Completions** 兼容协议，形状不同（messages/max_tokens/
response_format，SSE 为 delta 分片），无法经现有适配器接入。用户选择实现
Chat Completions 适配器（选项 c）作为第二个真实 Provider 通道。

## Decision

1. **D-A 选择机制**：`TI_AI_PROVIDER` ∈ {'openai_responses'（默认，向后完全兼容）,
   'openai_chat'}。配置与适配器按此分派；不改任何既有 Responses 路径的字节形状。
2. **D-B 变量族**：openai_chat 使用独立 `TI_CHAT_BASE_URL` / `TI_CHAT_MODEL` /
   `TI_CHAT_API_KEY`（**不复用** TI_OPENAI_API_KEY——防同一把钥匙误发到第三方主机）；
   共享 TI_AI_ENABLED / TI_AI_MAX_OUTPUT_TOKENS / TI_AI_DAILY_* / TI_AI_ALLOW_PRIVATE。
   供应商兼容旋钮：`TI_CHAT_RESPONSE_FORMAT`（默认 json_object；可选 json_schema/none）、
   `TI_CHAT_TOKENS_PARAM`（默认 max_tokens；可选 max_completion_tokens）、
   `TI_CHAT_STREAM_USAGE`（默认 1，发送 stream_options.include_usage；怪异供应商可关）。
3. **D-C 端点安全**：base URL 必须 https；明文 http 仅允许环回主机
   （localhost/127.0.0.1/::1，本地 vLLM/Ollama）；拒绝 userinfo/query/fragment。
   传输沿用 PublicResolver DNS 钉扎——允许集从 {api.openai.com} 变为
   {配置主机名}；超时 60s/连接 8s、体积上限、错误码映射与 Responses 适配器一致。
4. **D-D 单一入口**：provider 分支做在 `configured_model()`/`request_body()`/
   新工厂 `configured_adapter()` 内；ai_analysis 启动接线改用工厂（1 行），
   ai_rule_drafts/ai_execution/SSE/device-ai 链零改动。预算公式复用
   outbound_measurement（48KiB 请求门 + token 预留），两条协议同一计量。
5. **D-E 输出合同不变**：系统提示词/JSON schema/recall 分支/引用校验全部复用；
   chat 侧 response_format 默认 json_object（供应商兼容面最宽），输出仍经
   服务器端 grounding 校验兜底；json_schema 旋钮供支持的供应商加严。
6. **D-F 流式与用量**：chat SSE 解析复用 STRICT_JSON（重复键/常量拒绝）与
   4MiB/64KiB 上限；delta 累计、finish_reason 映射（stop=完成、length=
   incomplete、content_filter/refusal=refused、其余=invalid）；[DONE] 缺失=
   ai_stream_interrupted；usage（prompt/completion/total）映射为既有
   input/output/total 不变量校验；流上无 usage 时按预留计（与 Responses
   "未知用量保预留"同语义）。
7. **D-G Embeddings 顺带**：`TI_EMBEDDINGS_BASE_URL`（同 D-C 校验）可选，
   默认仍 OpenAI 官方；密钥仍 TI_OPENAI_API_KEY。
8. **model_status()**：provider 字段反映选择，chat 分支附 endpoint_host 便于核对。

## Verification

新测试文件覆盖：配置解析（缺项/非法 base/环回 http/https 任意主机/旋钮合法值）、
请求体形状（两协议/body 门与预留共享/recall 分支/旋钮）、extract_chat_response
（stop/length/content_filter/refusal/畸形/usage 不变量）、chat SSE 解析
（delta 拼接+on_text/usage 末块/[DONE] 缺失/超限/协议错）、适配器工厂选择；
回归 AI 家族 + device-ai 家族 + embeddings 现有测试。

## Residual risk / Rollback

- 供应商行为差异（不识别 response_format/stream_options/max_tokens 拼写）由三个
  旋钮兜底；全关（none/max_tokens 默认/0）即最朴素 chat 形状。
- 生产化前置：多租户下 base URL 需收敛为服务端白名单（本机单用户 PoC 阶段
  环境变量即信任边界）；已登记 risk-register。
- 回滚 = 不设 TI_AI_PROVIDER（默认 openai_responses，行为与改动前逐字节一致）。
