# ADR-2026-063：设备 AI v1 请求合同与可移交向量库

- 日期：2026-10-18
- 状态：实现、目标验证及完整API/Worker回归通过（2705＋77子测试、exit0）；工作区尚未提交/推送。本裁决仅关闭所述请求合同范围，不是完整V1验收，见实施计划第63轮终态与最新交接卡
- 依据：ADR-2026-052/053、当前服务端 closed DTO、四端已有 decoder 与密封向量
- 涉及风险：R-004、R-007；R-005 的补充覆盖另行保留

第64轮复核补记：GET lookup/detail返回`DeviceAiPreparationView`基础存储视图，不含POST专属`replayed/provider_preview`；POST结果`DeviceAiPrepareResultView`扩展基础视图并仍要求boolean replayed。TS/Rust/Java分别校验，新增实际API响应→公共SDK的回归。本补修不改变12/6/4键请求冻结面或opaque内部载荷边界。旧第63轮完整回归为历史证据，新目标验证和移交清单见[复核报告](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-64-handoff-review.md)。

## 问题与选择

设备 AI 桥接已在第51/52轮继续实现，而类型仍定义在 SDK 内部。旧 draft b 的 prepare
带有 `device_binding` 等分层字段，Provider consent 与 submission 也包含尚未实现的键；
现行服务端 `extra=forbid` 会拒绝这些字段。因此本轮以当前实际接收的合同为迁移依据，
不把历史提案直接改名为已实现协议，也不改写其原始证据。

将真实类型发布到 `packages/domain-types/src/device-ai.ts`，SDK 公共根入口导出 Host
客户端和类型，旧 `device-ai-host` / `device-ai-projection` 路径保留兼容重导出。
类型使用普通 JSON 字符串及数字；类型检查不充当 UUID、哈希、大小、归属或权限验证。
所有原有 runtime decoder 和服务端 gate 继续生效。

## 本轮冻结的精确范围

| 表面 | 合同 |
|---|---|
| prepare 请求 | `package_id/expected_sha256/expected_byte_count/expected_schema/expected_owner_scope_id/selectors/projection_mode/approved_closure/expected_projection_sha256/question_sha256/host_receipt_id/intent_id`，共12键 |
| Provider consent | `expected_pack_fingerprint/expected_device_context_fingerprint/question_sha256/provider/model/expected_provider_policy_fingerprint`，共6键 |
| device_submission | `prepare_id/host_receipt_id/device_context_fingerprint/provider_consent`，共4键，嵌入既有分析请求 |
| selector/reference | 与四端当前闭合键集及 ADR-052/053 一致；5类引用形状中只有4类可 prepare |
| SDK prepare 响应 | 共享当前客户端实际检查的最小 view；`contract/pack/provider_preview` 的内部载荷仍为 opaque，不在本轮声明完整闭合响应 schema |

`approved_closure` 在非闭包模式显式为 null，不可通过省略键改写 Host 合同。
prepare 只有5种已实现 mode；`test_event` 只保留引用/受限投影的表达能力，v1 prepare
及 restricted 材料仍拒绝。mixed-domain、个人上下文、test_event 权利与完整引用/数值
载荷的后续合同仍是完整目标义务，须另行设计并按版本演进，不能由本次类型迁移解禁。

`DEVICE_AI_WIRE_CONTRACT.wire_frozen=true` 是上述请求合同的版本声明，不是服务器
运行能力探针，也不证明真实 Provider、完整平台矩阵、全部设备 AI 协议或 V1 发布完成。
破坏性字段、规范化、模式或向量预期变动须走新协议/fixture版本，不覆盖旧版本。
服务端接收侧的历史宽容仍按 ADR-052 的 D1/D2 等裁决保留，不能用类型收紧冒称运行时已收紧。

## 验证资产与移交

既有测试读取被 Git 忽略的 `.artifacts`，clone 后无法复现。将其所需的合成向量原字节
纳入 `packages/domain-types/fixtures/device-ai-v1/`，以 provenance 记录原来源、长度和
SHA，并在消费者中核对实际读取的字节。历史证据文件保持原样；不带入正常数据库、
用户密钥或本机私人资料。新增 Git 管理的合同向量是测试输入，不是本轮新增真实采集。

沿用已有向量不补造覆盖：8MiB 边界权威向量和多成员闭包对拍等 R-005 缺口继续登记。
已有工具链、依赖安装和其他测试域自己的输入仍是各自的环境前置，不能据此宣称整个
项目的所有测试已经与 `.artifacts` 解耦。

## 必须保留的检查

- 从 `@tire/api-client` / `@tire/domain-types` 公共入口实际导入与编译，兼容旧路径。
- TypeScript 正负例保护12/6/4键、4域/5mode、显式 null 及无虚假校验品牌。
- Python DTO 与公共 SDK 常量实测对拍；注入 transport 验证 prepare 与独立 consent
  提交分支。模拟传输只证明合同，不证明 API 完整业务链或 Provider 接受。
- TS/Python/Rust/Java 在各自 decoder 读取受管理向量；完整性失败应直接失败。
- 每次报告区分类型、纯模块、构建、原生运行、真实来源与真实模型证据。本轮不启动
  正常服务，不执行正常迁移、真实联网、Provider 或设备仪器。
