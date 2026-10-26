# 二进制隔离审批 Task 1 接线增补

日期：2026-10-20。**状态：仅静态增补，Task 1 尚未实施或验收，完整 V1 继续 active。** 本文补充原计划的五项实际前置差异，不扩需求或审批流程。原 `docs/plans/2026-10-20-binary-quarantine-review-ui.md` 保留原字节，SHA-256 仍为 `fa114fa6bb3f4fade1d346d9f230d66de2c6e21048ba40069af35e95245e79cb`；其中冻结当时的状态和历史描述不覆写。Task 0 当前证据以 `docs/assurance/evidence/round-97-binary-review-boundary.md` 为准，其后端结果不能升级为 Task 1 或完整计划完成。

## 1. Native JS、Rust、Java 必须同时接精确 header 判词

当前 `packages/native-client/src/index.ts:229–251` 仅在 inventory GET 允许 `X-Tire-Expected-Account`，在 IPC 前检查原始 header 的重复、空白/安全 ID，并维持三 header 上限。Rust `apps/desktop/src-tauri/src/security.rs:174–177`、Java `apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/NativePolicy.java:89–90` 同样仅允许 inventory 场景。因此只改 Rust/Java，SDK 的 binary POST 仍会在 Native JS 被拒绝。

Task 1 目标文件补充 `packages/native-client/src/index.ts` 与 `packages/native-client/tests/transport.test.mjs`，并与原计划所列 Rust/Java policy/tests 一起接线。三端仅为 POST 原始规范串 `/v1/quarantines/<id>/reviews?mode=history&format=raw-evidence-v2` 精确允许携带单值 `[A-Za-z0-9_-]{1,64}` 账户 header，其中 id 也须为安全 ID，query 为上述有序 literal。直接匹配原始 path/query，拒绝编码别名；不先 URL decode/normalize 再放行。保留其他 path/method/query/header 的既有行为和 header 预算，不泛开 `/v1` 写入。

Native 这里只界定 expected-account header 允许携带的精确范围，不凭 URL 判断记录实际是否 binary，也不把所有缺 header 请求都改为 IPC 前拒绝。binary POST 缺 header 的必填 422 仍由后端合同承担。

验证需覆盖 JS 在 IPC 前与 Rust/Java 宿主处的同一组精确正反例，包括携带 header 的重/坏值、错误原始 path/method/query、query 顺序和编码别名，及既有 inventory/text 行为；另验证缺 header 的 Native 既有行为与后端 binary 422，分别记账。原 R96/R80 受管授权不覆盖本轮新目标；后续精确入口及 literal argv 仍须按原计划独审，不能据旧回执称这些测试已经运行。

## 2. 以 capture 补足 identity，冻结三份真实 metadata

当前 quarantine detail 来自 `apps/api/tire_api/quality.py:327–368`，返回原件公共字段与 `vehicle_payload`，没有 `parser_identity`；`QuarantineEvidenceMetadataV2` 也不声明该字段。不能为了满足原计划的完整 identity 核对而从 detail 读取不存在的字段，或让 decoder 接受伪造字段。

Task 1 复用既有 `captureEvidenceV2`，按 detail/review 的 `raw_capture_id` 补读 capture，取得完整 parser identity。核对 capture 的 id/raw_capture_id、query_id、source_id、target_kind=vehicle、完整 query 与当前选中车型查询，以及 detail/review/capture 的所有共享原件归属、hash、bytes、MIME、parser 版本和 identity；解析后 detail/review 还须核其完整 mapping/provenance。完整 `{ detail, review, capture }` 连同同一 owner、selection 和 transport 依据深复制冻结；提交时任一依据变化都清确认并重新读取，不能只比 PDF hash。

capture 表示未解析原件，真实 `parse_method`/`mapping_id` 为 null，见 `RawEvidenceUnparsedBinaryV2` 与原件 metadata builder；解析后的 detail 可有 mapping。应按各自合同保留并验证这一区别，不能强行要求 capture 两字段等于解析后的 detail，也不能将 capture receipt 当作事实采纳或来源许可。

验证需覆盖完整 identity 漂移、相同 hash 但 capture/query/source/parser/mapping 变化、错目标/错归属、共享 metadata 漂移，以及合法 capture null 与解析后 mapping 的组合。三份响应的完整闭合同与同一冻结上下文同时成立，才可进入人工确认。

## 3. raw operation manager 单 active，读取不能互相撤销

`apps/web/components/raw-evidence-v2-context.ts:49–76` 的 manager 只有一个 active operation；每次 `begin()` 先 `invalidate()`，立即 abort 前一操作。因此 detail、review、capture 各自调用同一个 manager 的 `begin()` 再并行读取，会互相取消。

Task 1 选择串行读取，或只 `begin()` 一次后在同一 operation/fence/signal 内并行读取三份数据；提交阶段同样使用完整当前依据。关闭、选源、切记录、刷新必须同步撤销 operation、人工确认与提交资格，继续遵循既有 auth/owner/transport/unmount fence。迟到读取、POST 或 finally 不得恢复旧资格。

验证需覆盖三份读取互不取消、任一读取失败清资格、关闭/选源/切记录/刷新立即撤销，以及迟到完成不复活旧 UI。该调整复用现有 manager 的单 active 合同，不增加并行 manager 权限或新的审批流程。

## 4. 新 SDK 方法显式复用 fence，POST 解码真实 latest state

新增设计方法签名为：

```ts
quarantineReviewV2(id, fence, signal?)
reviewQuarantineV2(id, payload, expectedAccountId, fence, signal?)
```

`fence` 复用既有 `RawEvidenceContextFence`；GET/POST 使用原计划的 V2 精确路径、query、六键 body 与账户 header，并在既有异步边界核当前上下文。旧 `quarantineReview`、`reviewQuarantine` 保持现有 text 调用合同，不隐式升级。此处是待实施接口，不是当前已提供能力。

后端在 `quarantine_review.py:492–499` commit 后重新读取 `binary_review_state`。POST 返回的是重读时的 latest state，可能已有同 binding 的更新；decoder 不得强制 `revision === expected_revision + 1`，也不得强制 history[0] 必须是本次 action/operator/reason。继续校验真实闭合同、归属与服务端 binding，不凭公共 history 推断本次认证 actor 或幂等 receipt。409/丢响应/abort 后只读重新核对，不自动改 revision 重发。

验证需覆盖合法 latest revision/action 超过本次预期、commit 后响应 403/503 的不确定写入状态、409 与丢响应不自动重发，以及旧 text 方法回归。SDK/helper 结果不能替代真实 HTTP→SDK→UI 验收。

## 5. DescriptionText 不 trim，SDK 与 UI 的字符串策略分开

当前 `research.py:63–73` 的 `DescriptionText` 验证 UTF-8 与部分控制字符，允许 CR/LF/TAB，返回原值而不 trim。`ReviewRequest` 只叠加 operator 1–80、reason 5–2000 的长度界限；写入也直接保存 payload.operator/reason。原计划中“trim 后”的描述不能作为当前后端已实现行为。

Task 1 SDK 的请求/历史 decoder 按真实后端合同保留合法字符串，包括合法空白、CR/LF/TAB；不得复用会拒绝所有控制字符或要求 trim 等值的原件 metadata 文本 helper 来拒绝合法 history。UI 可对本次新输入采取更窄的 trim 与显示/提交策略，但须明确这是 UI 策略，不能据此修改旧 history、伪称后端已经 trim，或顺带收紧生产 API。

验证需分别覆盖后端合法空白与 CR/LF/TAB 的 SDK 接受/保留、原有长度边界、UI 新输入 trim 策略，以及 history 的安全文本呈现。本文不授权新增后端字符串变更。

## 实施与验证边界

仅在原计划 Task 1 的 SDK、共享 UI、Native 精确 policy 范围内实施以上差异。实施前仍遵循目标目录规则、已安装 Next guide 与原计划的 before 保全；新增或不在旧授权内的 Node/TypeScript/Native/UI 入口先静审精确 source/argv/私有输出。类型、helper、policy、构建、私 HTTP 与真实浏览器、设备/OS 验收分别记账，不互相替代。

本文只写文档并核对当前源码，没有运行产品 import、pytest/API、Node/tsc/build、浏览器、Native、正常库、网络/Provider 或设备，也不改原计划、生产、测试、旧 seal、Guard/ACL 或 HANDOFF。Task 1 未实施，活 PG、真实许可/online response 用途闭包、Provider、设备/OS 保存、EPREL 与完整 V1 继续开放。
