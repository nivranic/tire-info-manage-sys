# ADR-2026-053: decoder-fixtures-a 落地与 D9 嵌套键集裁决

- Date: 2026-10-03（第三批）
- Status: approved & implemented
- Affected assets: 四端 Host 断言层（ts device-ai-host.ts / jv DeviceAiHost.java）、
  decoder-fixtures-a 载体、decoder-spec 2.6/4.3
- Related: ADR-2026-052（第二批 D8/D1-D4/D7 与 fixtures 载体裁定）

## Context

按 ADR-2026-052 第 3 项裁定实施统一 closed-decoder fixtures（冻结前最后一项
工程前置）。实施中对拍四端实现时发现一项规范未登记的分歧：嵌套未知键
（selector/reference 内）py 递归 extra=forbid 拒、rs deny_unknown_fields 递归拒，
而 ts 运行时仅断言顶层键集（嵌套靠编译期类型）、jv 仅断言 reference 键集——
ts/jv 运行时接受嵌套未知键，仅靠服务端 422 兜底。

## Decision

1. **fixtures 载体按裁定落地**：`.artifacts/device-ai50/specs/decoder-fixtures-a/
   fixtures.json`，schema `device-ai-decoder-fixtures@1`，25 用例（accept 4 /
   reject 21）覆盖 M1-M10+D4；四端 runner 接入各自套件（py
   test_device_ai_decoder_fixtures.py、ts tests/device-ai/decoder-fixtures.mts、
   rs decoder_fixtures_replay_all_cases、jv DeviceAiDecoderFixturesTest）。
   M7（view 层时间）与 M5（submit 链 question）不在本 prepare-body 载体，notes
   已说明；consent 消息以 message="provider_consent" 单独落地。
2. **D9 = 嵌套键集封闭下沉 ts/jv 运行时**（decoder-spec 2.6 D9 行 + 4.3-9）：
   理由——本规范 1.1"多余键拒绝"是运行时 decoder 合同而非仅编译期类型合同
   （编译期类型不约束第三方构造的 payload 对象直入 assert 层）；与 D4 同属
   消除"Host 更松"方向。实施范围仅 prepare wire 断言路径（requested selectors
   与 approved_closure 两循环），摘要/预览路径（assertDeviceAiAnySelector/
   computeLocalPreview）不动——包内派生对象可合法携带内部字段。fixtures 两条
   M1 用例 expected 同步翻转并封存。
3. fixtures.json 定稿封存 SHA256 `0e8998c9a33529b8bb4beea7ff3de025e8f9b9b28693af2ad3d3fa1afaba5495`；
   此后 expected 变更须走新 schema 版本号。

## Verification（全部实际运行）

py fixtures 26 绿；ts npm test = selftest 188 + fixtures 34 绿 + 根 typecheck 绿；
rs cargo test --frozen 156+8 绿；jv gradle 三类 25/34/68 绿。

## Residual risk / Rollback

- M6 无连字符/version-0 UUID 在 py 端仍按 D1 已裁决超集接受（fixtures 以
  expected.py="accept" 如实记录，非本轮新风险）。
- 若冻结工程发现 fixtures 载体需扩 message 种类（submission/question），按
  schema 版本号新增，不改 @1 既有用例。
