# ADR-2026-055: 新增 anthropic（Messages API 原生）Provider 适配器

- Date: 2026-10-03
- Status: approved & implemented（用户指令"anthropic协议的吧"，接 ADR-2026-054 之后的第三通道）
- Affected assets: apps/api/tire_api/ai_gateway.py、tests/test_ai_anthropic_provider.py

## Context

用户在 openai_chat（ADR-2026-054）之后要求增加 Anthropic 原生协议通道。Anthropic
Messages API 与 OpenAI 两协议均不同：系统提示是顶层 `system` 字段而非消息、
`max_tokens` 必填、鉴权用 `x-api-key` + `anthropic-version` 头、无
response_format、usage 只有 input/output 无 total、SSE 为命名事件
（message_start/content_block_*/message_delta/message_stop，无 [DONE]）。

## Decision（沿用 054 的 D-A..D-G 骨架）

1. `TI_AI_PROVIDER=anthropic`；变量族 `TI_ANTHROPIC_MODEL` / `TI_ANTHROPIC_API_KEY`
   （独立钥匙，防跨主机误发）/ `TI_ANTHROPIC_BASE_URL`（**可选，默认
   https://api.anthropic.com**——协议属 Anthropic 官方故有权威默认；设置时走
   054 D-C 同一校验）/ `TI_ANTHROPIC_AUTH_HEADER`（x-api-key 默认｜bearer，
   中转网关用）。endpoint = base + `/v1/messages`。
2. 请求体：`{model, max_tokens(必填,取共享上限), system(顶层), messages:[user],
   stream}`；无 response_format（Anthropic 无该机制）——输出纪律靠系统提示词 +
   服务器端 grounding 校验兜底（与 chat 'none' 模式同语义）；recall 分支与
   48KiB 门/token 预留共享。
3. 非流响应：stop_reason 映射（end_turn=完成、max_tokens=incomplete、
   refusal=refused、stop_sequence/tool_use/None=invalid）；content 块仅取
   text（thinking/redacted_thinking 跳过且绝不存曝光——对齐 Responses 适配器
   的 reasoning 处理）；usage 合成 total=input+output 过 safe_usage 不变量。
4. 流式：复用 ai_stream_parser._SSEDecoder（其 event==data.type 校验正是
   Anthropic 事件约定）+ 事件状态机（message_start 一次、content_block_start/
   delta/stop 配对、text_delta 累计、thinking_delta 静默丢弃、message_delta
   定 stop_reason 与 output_tokens、message_stop 终结；ping 忽略；未知事件/
   顺序违规=协议错）；无 message_stop=ai_stream_interrupted；4MiB/64KiB/512KiB
   行/16384 事件上限与既有解析器一致。
5. AnthropicAdapter 与既有两适配器同篱笆（DNS 钉扎配置主机、60s/8s、体积上限、
   错误码映射、跨协议体互斥防御）；headers 按 auth_style 组装。
6. model_status：provider 'anthropic' + endpoint_host。
7. Embeddings：Anthropic 无 embeddings API，不适用（维持 OpenAI/兼容端点）。

## Verification

新 tests/test_ai_anthropic_provider.py（配置/body/extract/流式/互斥/状态）+
AI 家族回归。回滚 = 不设 TI_AI_PROVIDER=anthropic。
