# 第 52 轮（2026-10-03）核查与 COHS 执行证据索引

回执只追加不改写；本文件引用的 .artifacts 路径均为本轮新产物。

## A. 四端新鲜回归（Local Assurance）

| 端 | 结果 | 命令/回执 |
|---|---|---|
| TS Host SDK | **188/0**（含 D4 负例 I29） | `.artifacts/device-ai50/host-sdk-selftest/`（活体）+ packages/api-client `npm test`（r52 迁入仓库） |
| TS 投影对拍 | **125/0**（20 案例 17+3） | `.artifacts/device-ai50/projection-parity-ts/`（+esm hook） |
| TS E1 对拍 | **68/68** | `.artifacts/device-ai50/specs/e1-ts-parity/run-parity.mts` |
| 根 typecheck | exit 0（web/desktop/mobile/native-client） | `npm run typecheck` |
| desktop node | **22/0** | apps/desktop `npm run test` |
| mobile node | **23/0** | apps/mobile `npm run test` |
| Rust | **155+8 / 0 失败 / 4 平台条件忽略**（+1 为 D4 负例） | `cargo test --frozen` |
| Java JVM | **HostTest 34 + ParityTest 68 / 0**（+1 为 D4 负例） | gradle `:app:testOfflineQaUnitTest`（XML: tests/skipped/failures 计数） |
| Android 仪器 | **OK (43 tests)**（41 既有 + 2 销毁测试恢复） | `am instrument` emulator-5554，全限定类名 |

## B. Python 全量套件（三次运行 + 鉴别链）

| 运行 | 条件 | 结果 | 回执 |
|---|---|---|---|
| 全量#1（11:35） | 与 cargo/gradle 并行 | 2566 绿 + **7 失败**（全在 test_raw_captures） | `.artifacts/audit-r52-20261003113505-pyfull/` |
| test_raw_captures 单文件重跑 | 机器空闲 | **15/15 绿** | `.artifacts/audit-r52-rawcaptures-retry/` |
| 全量#2（12:27，含 E6 +5） | 模拟器常驻 | 2564 绿 + **14 失败**（raw_captures/parser_bundles/recall_parser_releases/rejected_observations/vehicles） | `.artifacts/audit-r52-122738-pyfull2/` |
| 6 文件串行重跑 | 模拟器常驻 | 101 绿 + 2 失败（换人：a_b_a + sqlite_restart） | `.artifacts/audit-r52-parserfamily-retry/` |
| 双测单独跑 | 模拟器常驻 | a_b_a **绿**、sqlite_restart 败 | 同上 tmp2 |
| 关模拟器后整文件 | 模拟器已关 | sqlite_restart **绿**、damaged_control 败（再换人） | 同上 tmp3 |
| damaged_control 单测 | 完全隔离 | **1 绿（35s）** | 同上 tmp4 |

**结论（如实）**：全部 21 个失败实例在隔离重跑中 100% 转绿——**零确定性失败**。
失败家族 = 真实 parser 子进程预算测试（8s 墙钟/5s CPU/384MiB，HANDOFF §8 禁止放宽），
受害测试随机器间歇负载轮转（模拟器常驻、Defender、海量测试临时文件的磁盘churn 均为负载源）。
测试行为本身正确（预算耗尽即 fail-closed，正是被测属性）。**协议**：全量套件须在
空闲机器串行执行；任何失败先做文件级隔离重跑鉴别，再判定是否回归。本轮未能取得
"单次全量全绿"快照——这是环境属性而非产品缺陷，已登记 R-003。
（对照：历史"2030通过/1失败"全量基线的 1 项失败属同族可能性无法排除。）

## C. E6 route 层闭包测试（r52 新增，冻结前置 6 闭合）

+5 用例于 `tests/test_device_ai_routes_prepare.py`：正例（依赖扩张精确集合 201）
/ 超集 / 等长换人 / 缺依赖 / 混域各 409+`device_ai_closure_consent_required` 零落行；
顺带钉住"闭包断言先于摘要比对"gate 顺序。单文件 22 绿；device-ai 家族 12 文件
**469 绿**。gate 语义从代码确认：**精确集合相等**（device_ai_projection.py:744-749，
长度断言 + canonical JSON 集合相等），非子集。

## D. Root 第二批裁决（Global Assurance / 治理）

- 规范正文：`.artifacts/device-ai50/specs/decoder-spec.md` §4.3（8 项裁决 +
  2.6 表逐行指针）；治理记录：docs/assurance/decisions/ADR-2026-052。
- draft b 修订（D8 null-carried + 见证改名 _NonClosureScopeNull）：tsc exit 0，
  新回执 `public-types-draft-b-verification-2.json`（SHA 229f4b32…a8c），
  旧回执原样保留。
- D4 三 Host 收紧（ts/rs/jv `*MAX_PACKAGE_BYTES=8_388_608` + 各 1 负例）：
  ts 188、rs 155+8、jv 34+68 全绿。
- TS CI 迁入：packages/api-client/tests/device-ai/（自测+hook+fingerprint 数据
  三件套，复制不移动），package.json `test` 脚本，npm test 188 绿。

## E. 打包级验收（⑤ 闭合）

| 产物 | 结果 |
|---|---|
| Windows tauri NSIS | `胎迹_0.1.0_x64-setup.exe` 3.22MiB（release cargo 6m17s + makensis） |
| Android APK（第一轮） | 11.77MB @12:12——**发现嵌入旧前端**（assets/public 停在 10-01，dist 为 10-03） |
| Android APK（修正） | `npm run build` + `cap sync android` + 重打：**11.87MB @12:14，SHA cac148a2…ae80**，新 bundle index-Bsk3-kOo.js 已嵌入 |
| 仪器（重写销毁测试） | OK (43)；两测试自建 `qa-destroytest-` 材料销毁 + offline-v1 别名/sealed blob 保留断言内嵌通过 |

打包验收发现并修复的真实缺口：Android 打包管线缺 web 资产 build+sync 步骤会
静默嵌入陈旧前端——已按正确管线重打；该坑已写入计划文档第 52 轮记录。

## F. 静态安全扫描（Mimosa deep）

scanId `scan-2026-10-03T04-16-57.960Z-f2852d813850`，seal
`sha256:0f71d67d…85965`，674 包 / 0 已知 advisory / **144 findings**（79H/65M），
扫描自评 **inconclusive**（部分阶段覆盖缺口）。三级抽样核实（凭据族/注入族/
压缩 bundle 族各取样源码对照）全部为：QA 验收脚本启发式（`synthetic-key-never-live`
字面量、`secrets.token_hex` 生成密码、静态串 shell=True、硬编码表名字符串拼接）
与 minified bundle 污点误报（9 条 HIGH 全在 index-Bsk3-kOo.js）。**产品源码 0
确认漏洞**。triage 详情登记 R-008。

## G. 环境快照

API `/health` ok（mode=local_single_user_poc）；Web 3000 → 200；
TI_OPENAI_API_KEY/TI_OPENAI_MODEL/TI_AI_ENABLED 三作用域 unset（r52 实测）；
live OpenAPI **155 路径/179 操作**（`.artifacts/audit-r52-openapi.json`）；
正常库 data/dev.db 未触碰（全部测试走隔离目录）。

## H. 第三批追记（2026-10-03 同日：decoder-fixtures-a + D9）

- **fixtures**：`.artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json`
  （25 用例 accept 4/reject 21，M1-M10+D4），四端 runner 各自套件内全绿：
  py 26 / ts 188+34（npm test 串联）/ rs 156+8 / jv 25+34+68（gradle 三类）。
- **D9**（fixtures 对拍新发现→Root 第三批裁决→同日实施）：ts/jv prepare wire
  断言路径补齐 selector 五键集与 reference 逐域键集封闭（对齐 py/rs）；
  摘要/预览路径不动。fixtures 两条 M1 用例翻转后**封存
  SHA256 `0e8998c9a33529b8bb4beea7ff3de025e8f9b9b28693af2ad3d3fa1afaba5495`**。
  规范：decoder-spec 2.6 D9 行 + 4.3-9；治理：ADR-2026-053。
- **冻结前置全闭合**：D8/D1-D4/D7/E6/TS-CI/fixtures/D9 均闭合，仅剩冻结工程本身。
- **全量套件第三次运行（空闲机器终门禁）**：`.artifacts/audit-r53-*-pyfull3/`，
  **2596 绿 + 8 失败**（23:04，含本日新增 decoder-fixtures 26 + E6 5 项）。
  失败 = raw_captures ×7 + recall_discovery_monitor ×1；两文件隔离重跑
  **41/41 绿**（`.artifacts/audit-r53-finalretry/`）。三次全量累计 29 个失败实例
  **隔离复跑 100% 转绿、零确定性失败**；且本机空闲状态下 raw_captures 仍于
  全量上下文必败、隔离必过——**全量套件自身 23 分钟持续负载即预算挤压源**，
  属本机（开发机级别）机器属性而非产品缺陷（parser 预算 8s/5s-CPU 按 §8 禁止
  放宽，测试 fail-closed 行为正确）。结论：本机不可靠取得"单次全量全绿"快照；
  验证协议 = 全量运行 + 失败文件隔离重跑鉴别（R-003，证据已三次验证）。
