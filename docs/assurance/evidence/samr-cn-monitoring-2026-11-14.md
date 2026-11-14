# 中国召回后台监控与通知阶段验收

更新于 2026-11-14。沿 `17de977` 的逐公告版本与变化事件继续实施原规格的监控、通知和任务 SSE。

## 交付范围

新增 `samr_monitor_jobs`、`samr_monitor_rules`、`samr_rule_revisions`、`samr_task_attempts`、`samr_task_events`、`samr_monitor_checks`、`samr_monitor_runs`、`samr_notifications`，当前模型表为 179 张。新执行记录只追加，任务仅可更新调度／租约字段，通知仅可更新 `read_at`。

正常入口如下。

```text
POST /v1/samr-recall-monitor-rules
GET /v1/samr-recall-monitor-rules
GET /v1/samr-recall-monitor-rules/<rule-id>?mode=history
POST /v1/samr-recall-monitor-rules/<rule-id>/revisions
GET /v1/samr-recall-monitor-rules/<rule-id>/runs?mode=history
GET /v1/samr-recall-notifications?mode=history
PUT /v1/samr-recall-notifications/<notification-id>/read
GET /v1/monitor-tasks/samr/<job-id>/events/stream
```

检索规则默认最多 4 页、60 份公告，使用两遍规范化列表核对。重复原生文章 ID、声明总数或列表变化形成不完整结果。配置范围完成、所选公告核验和来源结果完整覆盖分别记录。指定公告规则绑定原生路径，通知关键词匹配变化前后的标题及正文。

Worker 每次查询前续租，采纳和通知前核对来源代次、规则修订及租约。每份公告完成后即保存通知，通过 attempt 左关联最终 Run，执行中的 `run_id` 可为空。通知保存观察、排队、送达时间与实际 lag，按规则／事件去重。

## 验证结果

| 验证 | 实际结果 |
| --- | --- |
| 受管 API 回归 | r4 共 117 项、r7 共 192 项通过，覆盖存在重叠 |
| 回归边界 | 两批均为 861 项输入稳定、资源关闭、非自检意外拒绝 0 |
| SDK／Web | 13／62 项通过，包含监控写入幂等键、历史过滤、空 Run 关联、原生路径和取消信号 |
| 类型与构建 | Web、Desktop、Mobile、native-client 类型检查和 Web 生产构建通过 |
| 正常浏览器 | 最终隔离 CDP 22 项通过，正常 Web 代理、独立 HTTP API、实际 Worker 函数及明确合成变化输入 |
| 布局与清理 | 1440／390／320 宽度无横向溢出，390 监控截图已查看，关闭任务时 reader.cancel 已观察 |
| 实际旧 SQLite | 前阶段 171 表库副本升级 6 项通过，新建 8 表，原有 20 条快照、23 条核验、13 个版本、14 次观察和 14 个变化逐行一致 |
| 非拥有者 PG／TLS | 14 条成功记录、13 个不同检查名称，正常 HTTP、独立 Worker、恢复及当前源码合同验收通过 |
| 官方后台链路 | 两遍检索及 2 份公告共 4 次 live 查询，配置范围完成，来源完整覆盖为 false，保存 2 条通知并重开原件 |
| 运行权限 | 8 张新表均可经应用读取／插入，任务调度和通知已读经正常入口更新，16 条身份 UPDATE／DELETE SQL 因权限不足被拒绝 |
| 资源关闭 | 22 个直接服务进程记录、12 个不同端口已核对，活动进程、监听、浏览器 Parser 目录为 0，临时密码、私钥及 postmaster 文件均不存在 |

受管回归覆盖双遍列表、跨页重复、配置截断、指定公告、304、即时通知、部分失败、旧事件、前后关键词匹配、续租、过期恢复、暂停、修订、来源代次、账户隔离、只追加、正常总调度及 SSE 重连。

## 原始失败与修正

1. r1 的 69 项中 63 项通过。覆盖统计提前访问检索规则不存在的公告 `reference`，已修正初始化分支。
2. r2 的 117 项中 110 项通过。合成夹具将空 `fail_reference` 与检索的缺省值比较，导致检索被标记离线，另有动态 `server_time` 全对象比较。按原始回执修正夹具和断言。
3. r3 的 117 项中 116 项通过。列表变化夹具修改标题后遗漏可见文本，触发来源校验，已补成合法变化输入。
4. r5 的 180 项中 178 项通过，r6 的 192 项中 189 项通过。旧迁移夹具遗漏既有 035 文本嵌入授权固定触发器合同及来源／文档全文索引初始化。补齐三个当前形状的合成前驱夹具，继续执行严格 DDL、旧行保留、回滚和并发断言，r7 全部通过。
5. 首次 SDK 命令使用了不存在的脚本别名，随后使用正式 `test:samr-recalls`。新增写入断言起初按普通对象读取 Headers，已改为标准 Headers 读取，最终 13 项通过。
6. Chrome DevTools MCP 报告共用 profile 已被占用，改用现有隔离 CDP 验收模式。首批 12 项止于把请求信号状态当作 SSE 消费者关闭依据，随后直接观察既有 `reader.cancel`，两批 22 项通过。
7. PG 包装器末尾重复记录最后一个检查名称，按 14 条记录、13 个不同检查名称保存实际范围。

此前 Parser 间歇超时继续待查。本阶段覆盖隔离功能和短时真实来源验收，生产通知质量、自然长周期及队列 lag SLO 继续待验。

## 源码与运行合同

当前 API 源码指纹为 `21537e3b6da5da800632593a59272ef915595fadc7939b21cc5e7832221fb4b8`。本次批准空参考 `postgres-runtime-schema@4` 合同摘要为 `c02a45d6abe1201272bf42ae13544f28857d17e898c1375dd9fc3f64f57ccc59`，包含 180 个 relation。交付时按实际源码与环境重建、审查并批准合同。[部署流程](../../POSTGRES-RUNTIME-SCHEMA.md)

## 私有证据

- 受管回归位于 `.artifacts/samr-monitor-20261114/r4/result.json` 与 `r7/result.json`，r1／r2／r3／r5／r6 和隔离诊断保留各次失败。
- SDK、Web 单元、构建和类型记录位于同目录的 `sdk.log`、`web-tests.log`、`build.log`、`typecheck.log`。
- 最终浏览器记录位于 `.artifacts/samr-monitor-20261114/web/run-670d6c0b-76a1-44de-b18d-f31f2430d620/report.json`，摘要为 `6bfc3505f0caed311fbc08e20efccad8a2d6ea387a2c24ede77c5a61b4c23eb4`。
- PostgreSQL 记录位于 `.artifacts/postgres/pgverify-7785547d3a794cc8922491498f8f60ae/report.json`，摘要为 `2c6999e44ca892af55253e91f21dbeff731edd2e7ad0a6401a1272921db88f51`。
- 实际旧库记录位于 `.artifacts/samr-monitor-20261114/legacy-5592b40e4596409cbac626d43c2122f0/report.json`，资源核对位于 `.artifacts/samr-monitor-20261114/close.json`。

原件、数据库、凭据、截图和合同保存在 Git 忽略目录，新 clone 通过正式入口重建环境。后续接续自然长周期、SKU／批次、人工 Golden、许可与 AI 引用，真实 AI 沿用户选择的 OpenAI Responses API 验收。[最新接手卡](../../AGENT-HANDOFF-2026-11-14-SAMR-MONITOR.md)
