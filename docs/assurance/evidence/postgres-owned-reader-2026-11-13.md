# PostgreSQL 受许可外部读取验收（2026-11-13）

基线：`092dc218b88a9127e6a24d6445bd02a28af27335`。本轮接通 PostgreSQL 的轮胎单事实、轮胎分页、Safety Gate 分页及新查询归属写入，保留现有字段许可、证据检查和跨账户隔离。完整 V1 未完成。

## 实现与边界

- 共用现有 Reader，使用新鲜 READ COMMITTED 事务、现有 ingestion advisory 锁和固定 19 表 SHARE 锁。凭据、撤销、归属、许可、预算预检、物化与投影都在锁内；直接写入也不能穿透该窗口。
- 查询归属使用相同 advisory 锁，并冻结账户与会话表；创建失败回滚 QueryRun／审计／收据三元组，重放不追认历史匿名查询、不改变原账户。
- PG 使用 UTF-8 字节计量，二进制单独计数，JSON 数组长度有类型保护；未知数据库仍拒绝。锁、单条 SQL、事务空闲超时分别为 2／5／15 秒，事务结束恢复连接设置。
- 真 PG 发现 API Key 操作记录把 36 字符 UUID 写入 `VARCHAR(32)`；现改为 32 字符 UUID hex，保留既有表结构与历史记录。
- Reader Session 防止可信 helper 意外写入和更换事务；PG 因 SHARE 锁使用 read-write 事务，不宣称数据库级只读沙箱。吞吐、部署权限、生产 IAM／RLS 和主从部署不在本轮验收范围。
- 管理 Store 已在真实 PG 执行许可审批与撤销；现有面向本机 SQLite 的 CLI 没有扩展成 PG 运维入口，正式部署仍需单独交付该操作面。

决策与锁表维护要求见 [ADR-2026-064](../decisions/ADR-2026-064-postgres-owned-reader.md)。没有 schema 迁移、真实来源抓取或模型调用；所有本轮业务输入为合成材料。

## 验证结果

SQLite：11 模块 **248／248 通过**，无跳过；831 输入稳定、资源关闭、非自检意外拒绝 0、真实 Provider／接收端调用 0。回执 `.artifacts/pg-reader-sqlite-r2/result.json`，SHA256 `0ff07a40fdf164bb95690a085eeb6884b1825886b7c6d81652908454a3cdde07`。

真实 PostgreSQL 18.3：应用角色为非 superuser；分别取最新通过回执，**41 个不同场景全部通过**。这是分轮证据合并，不是一份 41／41 的单次绿色回执。每轮创建独立 loopback 集群，核对真实 data_directory，使用随机凭据并在 finally 关闭；没有连接已有未知数据库。

覆盖：20 项轮胎单事实正常与拒绝合同；轮胎分页／窗口撤回；5 项 Safety Gate 正常 HTTP、三页固定游标、跨账户／匿名、Key／许可撤销、许可新头失效；Unicode／反斜杠／二进制／非数组 JSON；8 MiB 文本含上限通过及超限物化前拒绝；错误 schema；无写入／无来源刷新；Key／许可／账户／直接材料写入并发；等待撤销后的新鲜读取；advisory／表锁超时；SQL 超时及连接设置恢复；actor 变化拒绝；归属部分失败回滚／同 ID 重放；helper 更换事务拒绝。

PG 外部 suite 的生产代码在第二轮后没有再变动；后续仅修正验收脚本的错误预期与测试装配，并增加独立边界场景。第三、四轮各核对 406 个 Python 输入稳定。

补充普通 PG 回归通过前 34 项（含并发初始化、普通查询与回退、监控、正文检索、报告、普通 Parser A/B/A），随后在 `recall_historical_replay_signed_code_upgrade_rollback_and_restart` 失败，断言位置为 `test_recall_parser_releases.py:160`：升级后的响应并非全部 `live`。备份恢复阶段尚未执行，不能宣称本轮已通过。回执 `.artifacts/postgres/pgverify-fbf7297546a54a63af558e9ef9dc838d/report.json`，SHA256 `627e2b0a592a99efbedc5c71542be703b5ce8efefdcf1e277baaa6116ac65942`。

首次独立复现 `pgverify-2439cedcf5314c128cf7d0a62e8360cf/report.json` 在首次查询就返回 `source_unavailable`（SHA256 `b688c1f7cc07f84bb67214154ee0ad586ff173995d90315684722eb5cdc0ca3e`）。增加私有 Adapter 异常观察后、生产代码未变，第二次独立流程完整通过：campaign／search 均经过 A/B/A、304、历史重解析和重启核对；回执 `pgverify-9c42e22b42a04619b70fcb288937833c/report.json`，SHA256 `3f00b1877d4d974c8ad21b6a39b683f9c80d596c19054ad4a86d877c06b99b37`。该成功不能解释此前失败，根因仍未确定，没有修改 Parser 超时、重试或业务行为。

全部 8 个本轮私有集群已关闭，postmaster PID 文件和初始化口令文件均不存在，55486／55487 无监听。原始失败保留；普通 PG 综合回归及备份恢复仍是下一步，不以独立通过替代。

## 原始失败和回执

以下路径均为 `.artifacts/postgres/<slot>/report.json`；私有回执和数据库不随 Git 交付。

| 阶段／slot | 结果与原因 | SHA256 |
| --- | --- | --- |
| 基线 `pgverify-5de720c6ba23440e80538cb1d854611f` | Reader 拒绝 PG、分页 BLOB SQL 错误、归属捕获为空；空表长度查询不能证明字节语义正确 | `eca75c3f8461396cd7fd2b9b91c39d55950113821408e91a90a3893481120cca` |
| R1 `pgverify-ae93359ae7a64b18b6f190de69f0c5ab` | 37 场景都受 Key 操作 ID 列宽错误阻断 | `767cfc1295e82f82dd31aa246a76e8c25ac92594b6d641dd5a28ac46c4809dac` |
| R2 `pgverify-abd3062cd3d545878001e1e23eeed109` | 30／38 通过；3 项分页拒绝码预期不符；5 项 HTTP 被脚本日志开关 `false` 阻断，合法值为 `0`／`1` | `779b76ee4b04f035c07b5e048fd122b25c7810dae0343f96e5e527fcec2ea604` |
| R3 `pgverify-c13457b3bce1403ea18fa720e154e40d` | 重跑 8 项并新增 3 项，10／11 通过；文本测试在新摄取前未恢复故意篡改的旧原件，来源变化链正确拒绝 | `ea382ef57781d1bba9fe8abe64e802899d451bad7c16739867e95a8a3dc97e87` |
| R4 `pgverify-db1df7ef287d4012941487c2ae371ee7` | 恢复测试旧原件后，文本专项 1／1 通过 | `263cde41777f8a385e0dd19c3e8040fb24c1befe635d9c843a41445b3a9d4575` |

SQLite 首轮保留 `.artifacts/pg-reader-sqlite-r1/result.json`：96／97；唯一失败为旧测试仍要求拒绝 PG。现以未知后端测试保留拒绝合同，不把假 dialect 当成真实 PG 验收。

轮胎分页沿既有隐私合同：已验证游标的许可变化返回 `reader_window_changed`；无游标时部分预算／治理错误归一为 `reader_not_available`。单事实和 Safety Gate 各保持原合同，未为测试放宽拒绝或统一所有错误码。

## 复跑与下一步

从仓库根目录、已配置项目 Python 依赖的环境执行：

```powershell
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin '<PostgreSQL bin directory>' -Port 55486 -Suite external-reader
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin '<PostgreSQL bin directory>' -Port 55487 -Suite core
```

`external-reader` 默认运行完整 41 场景。Python 入口的 `--checks` 可在受控集群环境内选择明确场景；未知或遗漏选择会使结果失败。不能手工传入生产连接串。

下一步：实际 Native 宿主／设备、长期监控；PG 部署管理入口、权限与并发吞吐；真实 OpenAI Responses／Embeddings 条件齐备后的语义验收；其余发布 Gate。新 clone 必须重建环境并复跑，不能把本文当作现场验收。

后续更新：已捕获 Parser 超时回执、减少准备阶段重复校验并通过 84 项专项；另完成该合成 PG 快照的全表与原件／报告／归档独立恢复。完整混合流程仍未通过，见[后续验收](parser-preparation-2026-11-13.md)，不能覆盖本文保留的原始失败。
