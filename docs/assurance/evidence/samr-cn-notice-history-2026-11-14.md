# 中国召回逐公告版本与变化阶段验收

更新于 2026-11-14，基线为 `394742a`。本阶段交付监控通知所需的公告版本与事件基础。后台调度、通知和完整 V1 按后续计划继续。[实施计划](../../plans/2026-11-14-samr-cn-monitoring.md)

## 已交付

- 按官方原生文章 ID 建立内容版本、快照观察和变化事件。版本保存完整规范化公告与 SHA-256，观察绑定快照、核验回执及实际系统观察时间。
- 正常成功采纳在同一事务中派生历史。相同快照重复核验和 304 复用观察，原件序列化变化可复用内容版本。A→B→A 追加三次事件并复用最初版本。
- 显式历史可派生已有可信公告快照，分页固定 `through_sequence`。读取时核对文章、版本、原件、核验和前后字段变化，公告的日期字段继续分别保存。
- 新增三张只追加表 `samr_notice_revisions`、`samr_notice_observations`、`samr_notice_changes`，当前模型表为 171 张。运行角色对三表仅获得 SELECT／INSERT。
- 新增 `samrNoticeHistory` SDK 方法与工作台“读取公告版本与变化”入口，支持观察分页、内容回退、前后原件、日期和纯文本。关闭、会话失效和父面板切换沿既有请求取消链处理。

正常历史入口如下。

```text
GET /v1/samr-recalls/notices/<native-article-id>/history?mode=history&offset=0&limit=10
GET /v1/samr-recalls/notices/<native-article-id>/history?mode=history&offset=10&limit=10&through_sequence=<anchor>
```

## 实际验证

| 验证 | 结果与范围 |
| --- | --- |
| 受管 API 回归 | r3 共 96 项、r4 共 158 项、r5 共 77 项通过，各批覆盖存在重叠 |
| 回归边界 | 三批均为 856 项输入稳定、资源关闭、非自检意外拒绝 0 |
| SDK 合同 | 10 项通过，含历史的默认范围、编码、固定分页和取消信号 |
| Web 单元回归 | 59 项通过 |
| 类型与构建 | Web、Desktop、Mobile、native-client 类型检查及 Web 生产构建通过 |
| 正常浏览器 | 最终 42 项通过，包含真实来源查询与明确合成的变化、并发及失败控制 |
| 历史布局 | 独立副本另有 3 项通过，零来源查询，13 次合成观察展开后在 1440／390／320 宽度均无横向溢出，390 宽度截图已查看 |
| 真实旧 SQLite | 实际前阶段数据库副本原先缺少三张历史表，升级及正常 API 派生共 6 项检查通过；原有 7 条快照记录及 8 条核验记录逐行保留 |
| 独立 PostgreSQL／TLS | 正常 HTTP、Worker、中断恢复、资产恢复与中国来源历史专项通过，共 14 条成功记录、13 个不同检查名称 |
| 运行角色 | 三张新表的实际 INSERT／SELECT 经正常 API 使用，6 条 UPDATE／DELETE SQL 因权限不足被拒绝 |
| 资源关闭 | 共 22 个直接服务进程记录、13 个不同监听端口完成核对，进程／监听／Web Parser 目录为 0，临时密码、私钥及 postmaster.pid 均不存在 |

新 API 回归覆盖原文重复、304、原件序列化、正文变化与回退、日期元数据倒序、同标题不同文章、查询失败和历史回退、旧记录派生、固定范围分页、只追加及绑定篡改。扩展回归同时检查 Safety Gate 版本和监控、通用任务、来源治理与回退授权。

生产页面经正常 Web 代理和独立 HTTP API 读取真实官方检索及公告，再读取相同文章的历史和原件。合成流程形成 13 次公告观察，验证 A→B→A、前十条和后两条的固定分页、并发追加后的原范围、变化前原件、HTML 字面文本及关闭后的迟到响应。真实模型及 Native 宿主／设备继续待验。

PostgreSQL 中国来源专项取得四次 `live` 和一次 `live_verified_304`，两份真实公告历史均经非拥有者 HTTP 服务重开原件。其余 Worker 中断与恢复沿既有录制材料和隔离到期装配执行。独立资产恢复后模型表为 171 张。

## 原始失败与修正

1. r1 的受管入口因 `packages/api-client/package.json` 审查摘要过期而拒绝启动。已核对上一阶段差异只有新增 SAMR SDK 测试命令，并同步固定摘要，护栏继续执行。
2. r2 的 72 项中 49 项通过、23 项失败。私有诊断捕获到原件临时文件原子重命名的 `PermissionError / WinError 5`，随后包装为 `CaptureWriteError`。后续在宿主运行同一受管入口，r3、r4、r5 均通过。
3. PostgreSQL 私有包装器末尾复用了一个检查名称，因此保留 14 条记录与 13 个不同名称。验收范围依据具体动作及回执核对。

此前阶段的间歇 Parser 超时继续保留待查。本阶段时间范围覆盖隔离功能验收，后台自然长周期和生产通知 lag 继续建立实际证据。

## 源码与运行合同

当前 API 源码指纹为 `46c234c11bfb8a93721db111f84b7730bc1c5242b51caec74634481f752981fa`。本机批准空参考 `postgres-runtime-schema@4` 的摘要为 `b11e1e3fcb5ea71f97d038c22dbc9f88baf83ca11885c2c247d751e8ca102068`，包含 172 个受管 relation。部署时按实际源码与环境重建、审查合同。[运行合同流程](../../POSTGRES-RUNTIME-SCHEMA.md)

## 私有证据

- API 回归位于 `.artifacts/samr-history-20261114/r3/result.json`、`r4/result.json`、`r5/result.json`。r1 启动失败、r2 失败和隔离诊断一并保留。
- 最终浏览器记录位于 `.artifacts/samr-history-20261114/web/run-f1db5df1-95c4-4725-83bc-0fc311e93d72/report.json`，摘要为 `63c89f9e7f3ccd31addf283337ceeca0bda03b0652801ac6b9e1838c2132e7db`。
- 展开布局截图和零来源查询记录位于 `.artifacts/samr-history-20261114/web/run-ede50b32-0a46-46f5-aaa4-0df49391ae79/`。前一批 34 项浏览器记录保留于相邻运行目录。
- PostgreSQL 记录位于 `.artifacts/postgres/pgverify-622fd89be00d43faa7d8fa7032277408/report.json`，摘要为 `ccc5d95491efc147bd6ef34e92933eec5de664a12ef6bc2c4227479a56b151e6`。
- 实际旧库验收位于 `.artifacts/samr-history-20261114/legacy-da390faac048409c837b7a92add9aabd/report.json`，关闭核对位于 `.artifacts/samr-history-20261114/close.json`。

原件、数据库、凭据、源码合同和截图位于 Git 忽略目录，新 clone 按正式入口重新建立验证环境。来源的开放再分发许可、精确 SKU／批次适用性和模型外发继续依各自授权与验收推进。

## 接续工作

继续检索发现与指定公告监控、Worker 租约与来源代次、任务 SSE、应用内变化通知和实际通知 lag，沿本阶段不可变事件建立消费回执。随后推进人工 Golden、SKU／批次、许可及 AI 引用。首个真实生成 Provider 继续采用用户选定的 OpenAI Responses API，完整 V1 继续逐项验收。[当前接手卡](../../AGENT-HANDOFF-2026-11-14-SAMR.md)
