# ADR-2026-052: 设备AI wire 冻结前置——Root 第二批协议裁决

- Date: 2026-10-03
- Status: approved（Root=主会话；用户对第一批 4 项"全部按建议批准"确立裁决模式）
- Affected assets: device-ai 四端 Host（TS/Rust/Java）+ 服务端 DTO + 草案 b + decoder 规范
- Related findings: decoder-spec.md 2.6 偏差表 D1-D8、4.2 冻结前置清单
- 规范正文：`.artifacts/device-ai50/specs/decoder-spec.md` §4.3（本 ADR 是其治理侧记录）

## Context

wire 冻结（`wire_frozen=true` + draft b 迁入 domain-types）前有 7 类硬性前置。E1-E5
规范与实现已闭合；遗留：D8（absent-never vs null-carried）、D1-D4/D7 方向性偏差、
fixtures 载体、TS CI、类型迁移时机、mixed-domain@2 与 test_event 冻结口径。

## Decision（8 项）

1. **D8 = (a) null-carried**：非闭包模式 `approved_closure` 显式 null，全键在场；
   修订草案 b（已改，tsc 见证 verification-2，SHA 229f4b32…）；四端实现不动。
2. **D1/D2/D3/D7 以"Host 更严或等价"为冻结口径**，服务端宽容登记为接收侧历史
   超集不改（D7 确立 explicit-presence 原则）。
3. **D4 三 Host 收紧 expected_byte_count ≤ 8,388,608** 并各加负例——已实现
   （ts I29 / rs 155 / jv 34 各 +1 用例）。
4. **fixtures 载体 = `.artifacts/device-ai50/specs/decoder-fixtures-a/`**，
   四端 runner 接入各自套件；实施排冻结工程轮。
5. **TS 覆盖进 CI = 自测迁入 packages/api-client**（已实施，npm test 188 项）。
6. **draft b → domain-types 迁移时机 = 冻结时**；迁入时去除 Validated<T,Name> 品牌。
7. **mixed-domain@2 表述批准**（@1 无混合域；演进以 @2 新版本承载，不复用
   include_context_ids）。
8. **test_event 冻结口径批准**（类型在、运行时拒，解禁以 @2 承载）。

## Rationale

- null-carried：closed key set + 全键在场使 schema 漂移即刻暴露；四端现状、全部
  向量与 request_hash 稳定性证明均基于它；draft 修订零迁移成本。
- 服务端宽容不改：均为"Host 更严"方向（规范化后 hash 一致，无漂移路径）；全局
  收紧（str_strip/UUID 域）影响 legacy 模型与 2000+ 测试，收益低。
- D4 反向收紧：唯一"Host 更松"项，且 8MiB 是 HANDOFF §8 不可放宽的产品约束，
  下沉后分层一致、失败更早。

## Known disadvantages / Residual risk

- 草案 b 与旧 verification 回执 SHA 脱钩（历史回执保留，新回执 verification-2 追加）。
- 服务端接收侧宽容仍在（D1/D2）：对第三方直连 API 客户端略宽于冻结文本声明。

## Required tests（均已绿）

ts selftest 188、cargo test 155+8、gradle HostTest 34 + ParityTest 68、
E6 route 闭包 5 用例（家族 469）、仪器 43。

## Rollback trigger / Revisit condition

fixtures 实施或冻结工程发现 null-carried 与既有 ledger/wire 实测冲突时重开 D8。
