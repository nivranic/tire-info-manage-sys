# 第95轮：Raw Evidence V2 SDK 精确受管入口

2026-10-20。本轮新增 SDK 合成行为的固定受管入口。第三次同源、同三目标的 `require_escalated` 执行上下文对照通过；前两次普通执行上下文的旧路由 wrapper 失败完整保留，底层 I/O 原因仍 unknown。完整 V1 继续 active，未提交或推送。

## 实现与冻结

按[正式静态计划](../../plans/2026-10-20-raw-evidence-v2-sdk-managed.md)新增一个 Python wrapper，只运行固定 literal `await import('regression:raw-evidence-v2-sdk');`；Node 缺失失败，30 秒，exit0 且 stdout 恰为唯一固定成功行。ChildPolicy 只新增 wrapper 和原样 `.mts` 两个精确 pin，18 个旧 REVIEWED 键/value 保留；第三项沿用双 hook 和 `node_wire_3`，既有启动限制、预算和并发未放宽。

Node guard 增唯一 alias，并在所有最终 resolve 结果中核 `.mts` 的解码路径、canonical URL、无 query/fragment 与 realpath；固定入口本身也不得是 symlink。旧 SDK 映射和网络、DB 模块、写入、后代进程拒绝保持。该拒绝控制流经独立静审，本轮没有动态 guard 负例验收。

runner manifest 为 162（160 API＋2 Worker），实际只选以下三个 nodeid；新 wrapper 为 **1 pytest 项、1 Node child**，不把内部循环算成更多测试：

```text
apps/api/tests/test_device_ai_public_contract.py::test_public_sdk_exports_match_closed_server_dto_fields
apps/api/tests/test_device_ai_routes_prepare.py::test_preparation_response_views_are_consumable_through_public_sdk
apps/api/tests/test_raw_evidence_v2_sdk.py::test_raw_evidence_v2_sdk_behavior
```

四源候选及三旧脚本完整字节见[实现冻结](../../../.artifacts/r95-impl-1de95e43ed6b404ab9c476bc3e40771d/candidate-pins.json)和[精确 diff](../../../.artifacts/r95-impl-1de95e43ed6b404ab9c476bc3e40771d/source.diff)。`.mts` 原样 23381B／`db7bf5e993a89f226feae671a72cbb8c2385563441eb612e0cd8a644377d527c`；SDK、旧 wrapper/hook/package、产品、模型、迁移和 Native 未改。正式计划保留实施时静态状态，当前验收以本文和实际回执补充。

## 三次实际账

| 实际回执 | 上下文 | setup / call / teardown | Node child | runner / pytest exit |
| --- | --- | --- | --- | --- |
| [首 run](../../../.artifacts/r95-t-9f62b18c4d7a/result.json) | 普通 | 3P / 2P1F / 3P | wire1＋wire3，各1；2 exit0/live0 | 3 / 1 |
| [第二 run](../../../.artifacts/r95-f-6c39a0e72bd1/result.json) | 普通、未改源复验 | 3P / 2P1F / 3P | wire1＋wire3，各1；2 exit0/live0 | 3 / 1 |
| [第三 run](../../../.artifacts/r95-u-813ab5d7c209/result.json) | require_escalated 上下文对照 | 3P / 3P / 3P | wire1/2/3，各 authorized=started=1；3 exit0/live0 | 0 / 0 |

每次 collected/protocol/executed 均为3，3 unique、0 skip/incomplete，nodeids、reports 和 JUnit 一致。历史合计 **9 protocol/call＝7 pass＋2 red，仍为3个唯一目标，共7个 Node child 全 exit0/live0**；不是9 unique，也不是全 suite 回归。

首两次新 SDK wrapper 和 public wrapper 已通过；旧 routes wrapper 失败位置为 `object_store.py:79`。静态链显示这里把底层 OSError 包装为 `ObjectStoreError('object_write_failed')`，未到 wire2；原回执未保留 errno/winerror，根因不能确认。第三次只改变外层工具执行上下文，所有源码、pin、内置 Guard/ChildPolicy、自检、预算、target 和 ACL 均未改；不是 I/O 代码修复，也未证实某个 sandbox 或 syscall 原因。

三次各688 source 首尾/live 完全相同，6份 manifest 零漂移；相对 R94 的687项恰三旧脚本改变＋一个新 wrapper，其他684项不变。各次 raw 非 selfcheck 拒绝0、resources_closed=true、metrics0、R38原 pin 保持、normal_database_started=false、真实 Provider/receiver 调用0。Root 独立重核 R38、S2、R94 seal 和 R93 v2 seal 仍为原 pin；本轮未使用 S2 开展新 SDK 验收。

独立证据：[pre-run 静审](../../../.artifacts/r95-review-8672e4a31e814063aa71ca13458921c6/review.md)、[首 run post-review](../../../.artifacts/r95-post-review-a9e2ba172e0e4e9c829e46bce4e97634/review.md)、[第二/三 run post-review](../../../.artifacts/r95-post-review-4171a00f2ea5460cbe958a5f16226ac2/review.md)；[首 verifier](../../../.artifacts/r95-verifier-93c7a1b64de8/verification.json)、[第二 verifier](../../../.artifacts/r95-recheck-verifier-30d6a7f18bc2/verification.json)、[第三 verifier](../../../.artifacts/r95-u-verifier-76f8d0c21e9a/verification.json)。

## 保全、限制与下一步

三入口先保存完整原字节，再统一顶部 prepend；完整 R94 及更早 suffix 逐字节保持，见[原文件 metadata](../../../.artifacts/r95-close-b65e1fa8d043/entry-baseline.json)。[本轮单份机器 seal](../../../.artifacts/r95-close-b65e1fa8d043/verification-final.json)绑定源冻结、三次各14份顶层回执、独审/verifier、报告、入口及完整备份；不自绑定、不复制私库。其实际大小/hash及最终独立核验以生成后的文件为准。

SDK 通过仅证明受控 transport、真实 Response/Blob/SHA256 下的已审行为断言。当前没有 `ApiError.code` 断言；四异步边界共用 vehicle content helper，不能称六方法各阶段独立覆盖。Node transform 不是 tsc。真实 HTTP→SDK、账户切换 UI、Native 保存、PG/正常库保全升级、正式来源许可和完整 PDF/V1 Gate 仍开放。

Python/JS API fence 不是 OS 沙箱，普通只读 FS 仍允许；no-artifacts hook 不能代表完整读取隔离。生产原件/结构化 pending、首代 fetch/ready 关闭、requires_source_verification、Provider/export=false 保持。下一步为共享 UI/Native 保存前 caller fence，以及独立精确的真实 HTTP→SDK 和类型验证入口；EPREL 无 Key 不作为本切片阻塞，不再索要 Key。
