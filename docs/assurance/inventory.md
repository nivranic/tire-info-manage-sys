# 资产清单快照 — r52（2026-10-03 核查轮）

来源校准：live OpenAPI（`/openapi.json`，GET-only）+ 源码树 + docs/HANDOFF §3（16 工作域）
+ docs/plans 实施记录。差异即 Finding 的原则下，本快照与 HANDOFF §3 无冲突项。

## Surfaces

| Surface | 形态 | 关键事实（r52 实测） |
|---|---|---|
| API | FastAPI 单体，127.0.0.1:8000 | **155 路径 / 179 操作**（live openapi 实测）；健康 `mode=local_single_user_poc` |
| Web | Next.js 中文工作台，127.0.0.1:3000 | HTTP 200（本轮实测）；IndexedDB 加密 journal |
| Worker | apps/worker 监控调度 | test_monitor.py 计入全量套件 |
| Windows | Tauri 2（Rust + WebView2） | NSIS 安装包 3.22MiB（r52 新打包）；6 个 device-ai IPC 命令两处齐全 |
| Android | Capacitor 8（Java Host） | offlineQa APK 11.87MiB（r52 新资产重打包）；40 个 @PluginMethod（6 个 device-ai） |

## 共享包

| 包 | 角色 | 测试入口（r52 起） |
|---|---|---|
| packages/domain-types | 领域协议类型 | 根 `npm run typecheck` |
| packages/api-client | 可注入 SDK + device-ai Host | `npm test`（188 项，r52 迁入仓库） |
| packages/native-client | 原生传输 | 根 typecheck 覆盖 |

## 设备AI链（第50/51轮新增域）

OwnedArchive(actor 归属 404 先于 409) → 投影核(原bytes/NumberLexeme/canonical SHA) →
metadata-only prepare(D10 十一步 gate + 闭包精确集合相等[r52 起 route 层 5 用例钉住]) →
actor-owned claim(013 触发器) → SSE reservation/grounding 复用 → N18 lookup-first 恢复 →
五重 fence journal(owner/generation/SHA/clock/session)。四端 parser 对拍 68/68 向量。

## 数据资产

| 资产 | 保全状态 |
|---|---|
| data/dev.db（正常库） | 011/012/013 已应用；唯一 after49 SHA 6de69277…7115（112 表口径） |
| 对象存储 + parser bundles | 391 封存文件基线不变（manifest round48-normal-files-before.json） |
| .artifacts/ 证据库 | 只追加不改写；本轮回执全部新文件 |
| Android Keystore QA 凭据 | 61 sealed blob 保留（用户 2026-10-03 批准；r52 仪器测试内置断言再验证） |

## 集成

| 集成 | 状态 |
|---|---|
| 10 个 Parser 来源（8 轮胎参数源+1 召回+1 车型） | 已接入，限定范围（HANDOFF §4.1） |
| EPREL | 待配置入口，未接入 |
| OpenAI Responses | 已授权走环境变量；三作用域均 unset（r52 实测），真实验收待用户设置密钥 |

## 测试资产基线（r52 新鲜实测）

| 端 | 计数 | 命令口径 |
|---|---|---|
| Python 全量 | 见 evidence/round-52（干净重跑基线） | pytest tests + worker/test_monitor.py，隔离 env |
| TS Host SDK | 188/0 | packages/api-client `npm test`（含 D4 负例 I29） |
| TS 投影对拍 | 125/0（20 案例） | run-projection-parity.mts + esm hook |
| TS E1 对拍 | 68/68 | run-parity.mts |
| desktop node | 22/0 | apps/desktop `npm run test` |
| mobile node | 23/0 | apps/mobile `npm run test` |
| Rust | 155+8（+4 ignored 平台条件） | `cargo test --frozen` |
| Java JVM | HostTest 34 + ParityTest 68 / 0 | gradle testOfflineQaUnitTest |
| Android 仪器 | 43/0（含 2 项恢复的销毁测试） | am instrument（emulator-5554） |
