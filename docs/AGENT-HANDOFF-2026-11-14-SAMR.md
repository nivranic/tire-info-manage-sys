# 胎迹中国召回阶段接手卡

后台检索发现／指定公告监控、即时变化通知、任务SSE、SDK与Web已进一步交付，当前179张模型表。最新状态、验证与后续顺序见[中国召回监控接手卡](AGENT-HANDOFF-2026-11-14-SAMR-MONITOR.md)及[监控验收](assurance/evidence/samr-cn-monitoring-2026-11-14.md)。

更新于 2026-11-14。完整 V1 持续进行。本卡补充中国市场监管召回来源，整体需求清单继续参照前序总表。

前一阶段已交付专用 DTO、3 个 SDK 方法与 Web 正常入口。新增 SDK 8 项、既有 SDK 3 项、Web 59 项、三端及 native-client 类型检查、Web 生产构建通过。浏览器 31 项通过，其中 6 次真实官方 live 查询，两类持续策略、单次授权、独立历史与取消均已核对。四批 11 个直接进程记录、5 个端口及 Parser 临时目录已检查。[SDK 与工作台验收](assurance/evidence/samr-cn-web-2026-11-14.md)

逐公告版本、快照观察及变化事件已接入正常 API、SDK 与 Web，新增三张只追加表，当前 171 张模型表。受管回归三批 96／158／77 项通过，SDK 10 项、Web 59 项及完整类型和构建通过。正常浏览器 42 项、展开布局 3 项、实际旧库 6 项及独立 PG／TLS 专项已验，6 条新表越权 SQL 拒绝。22 个直接服务进程记录、13 个端口及临时秘密已核对。下一步实施后台发现／公告监控、变化通知和任务 SSE。[逐公告版本验收](assurance/evidence/samr-cn-notice-history-2026-11-14.md)

## 接手入口

1. 阅读本卡和[中国来源阶段验收](assurance/evidence/samr-cn-source-2026-11-14.md)。
2. 阅读[完整进度与交接总表](AGENT-HANDOFF-2026-11-14-PUBLISH.md)中的 12 模块、10 Gate、13 SLO、15 决策及历史待验项。
3. 按[原始需求](requirements/2026-09-26-tire-intelligence-original.md)继续完整 V1，使用当前工作树、实际回执和实时远端核对进度。

## 已确认的用户决定

- 持续自主实施、复核优化、提交、推送及更新交接已获授权。专业材料由 agent 自行选择并核对来源与许可。
- 首个真实 AI 接入采用 OpenAI Responses API，真实模型与 Embeddings 仍待独立验收。
- EPREL 当前按无正式 Key 的既有决定继续独立工作。新凭据通过本机环境配置。
- 沿既有 `main` 工作。新分支、工作树及代理使用遵循用户明确授权要求，网络操作继续直连。

## 本阶段交付

| 范围 | 当前进度 |
| --- | --- |
| 中国召回来源 | 新增 `samr-cn-recalls`，使用官方汽车召回栏目公开 GET 列表及原生公告路径 |
| 检索与身份 | 关键字、页码、声明总数、本页结果和原站导航限制，绑定文章 ID、标题、栏目、域名及 URL |
| 公告与日期 | 原文、批次、措施、原显示发布日期、DeployTime、PubDate、原始资源引用及未知适用性 |
| 正常 API | 在线查询、证据保存、重复核验、304、显式历史及原文重开 |
| 授权与治理 | 来源启停、冻结查询归属、Parser 固定选择、单次同意、两类独立持续回退策略及失败留证 |
| Parser | 当前完整目录为 18 项，旧 17 项真实封存包已由当前宿主执行通过 |
| 数据库 | 快照、核验及新增三张公告版本／观察／变化表，当前模型表为 171 张，运行角色仅获必要 SELECT/INSERT |
| 前端支持 | 专用 DTO、SDK、Web 检索与公告、分页、日期、证据和两类回退策略已接通，正常浏览器 31 项检查通过 |
| 公告历史 | 正常采纳与旧快照派生、内容回退、固定观察范围、字段变化、前后原件及 Web 历史分页，最终浏览器 42 项通过 |

当前轮胎区域目录为 13 个、厂商品牌为 9 个。中国监管召回作为独立来源登记，车型来源与工作区文档 Parser 继续按各自目标种类组织。

## 来源与重要事实

- 官方栏目路径为 `/zhxx/jdczh/jdczh/index.html`。列表从页面公开声明的 `/api-gateway/jpaas-publish-server/front/page/build/unit` 读取。JSON 请求显式设置 `Accept: application/json`。[官方栏目](https://www.samrdprc.org.cn/zhxx/jdczh/jdczh/index.html)
- 轮胎关键字现场返回 47 条，四页分别为 15、15、15、2。默认栏目声明 2325 条，原站导航最多 60 页。本阶段页码按原站导航范围校验，默认列表总数完整保留。
- 固铂与德安通公告显示日期和 DeployTime 为 2021 年，PubDate 为 2026 年。日期差异原因待来源说明，各字段已分别保存。
- 官方批次、缺陷和措施保留原文，具体 SKU 和实物适用性为 `not_assessed`。图片与附件状态为 `not_fetched`，开放再分发许可待核验，模型外发沿单独授权流程。

## 正常入口

```text
POST /v1/samr-recalls/query
GET /v1/samr-recalls/history?operation=search&keyword=轮胎&page=1&mode=history
GET /v1/samr-recalls/evidence/<snapshot-id>?mode=history
```

在线检索请求如下。

```json
{"query":{"operation":"search","keyword":"轮胎","page":"1"},"fallback_policy":"never"}
```

公告查询使用 `operation=notice` 和列表返回的 `reference`。持续回退类型为 `samr_recall_search` 与 `samr_recall_notice`。单次同意仍通过 `/v1/fallback-consents` 创建，再回到同一查询消费。

监管成功任务的 QueryRun 状态沿既有合同为 `live`，304 在响应、核验行及 Parser 执行状态体现。采用现行监管状态合同编写验收。

## 验证和失败记录

最终结果、对应源码摘要、回执路径与资源关闭状态见[阶段验收](assurance/evidence/samr-cn-source-2026-11-14.md)。保留首批沙箱原件写入错误、201 测试断言错误、私有 304 断言错误、真实 Parser 超时和子进程路径误判的原始回执。

已定位回归子进程将 `\\?\` 等价 Windows 路径判断为越界，导致服务崩溃用例在 Parser 前返回。修正使用主护栏既有的解析后路径比较规则，并补真实越界及设备路径反例。与生产 Parser 的现有期限和操作系统限制分别验收。

`.artifacts/`、`data/`、真实原件、凭据、依赖与构建产物保持 Git 忽略。新 clone 按正式入口重建验证环境与证据。PostgreSQL 使用匹配实际 API 源码的批准空参考 `@4` 合同。[运行合同流程](POSTGRES-RUNTIME-SCHEMA.md)

## 后续执行顺序

1. 依[监控实施计划](plans/2026-11-14-samr-cn-monitoring.md)接通后台发现／公告监控、变化通知、任务 SSE 和通知 lag，消费现有逐公告事件，保留来源原生文章 ID 与批次范围。
2. 继续许可核验、精确 SKU 与生产批次绑定、人工 Golden、AI 证据与引用、真实 Responses/Embeddings 验收。
3. 继续 Parser 间歇超时的原始错误与耗时取证、公网 Webhook、自然长周期、生产 IAM/Tenant/RLS、六平台 E2E、WCAG、安全、性能、灾备及其余 Gate。

KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 继续依前序交接封存。`docs/HANDOFF.md` 的封存尾文依旧保留，其状态语义和历史失败参照总交接。

## 可复制的接手指令

> 继续实施胎迹完整 V1。先读 docs/AGENT-HANDOFF-2026-11-14-SAMR.md、中国来源／Web／逐公告版本验收、监控实施计划、PUBLISH 总交接和原规格，核对 main、工作区、本地提交与实时远端。当前 13 个轮胎区域目录、9 个厂商品牌、18 项可信 Parser、171 张模型表。中国召回已有官方检索、原生公告、日期、不可变证据、304、来源治理、回退授权，以及正常 API／SDK／Web 逐公告版本和变化事件。最终浏览器 42 项，实际旧库和非拥有者 PG／TLS 已验。下一步接通后台发现与公告监控、变化通知和任务 SSE，再推进批次/SKU、人工 Golden、许可和 AI 引用。首个真实 AI 使用 OpenAI Responses。保留 Parser 间歇超时与原始失败，API 源码摘要46c234c1，按最新验收重建并批准 @4 合同。沿已有授权自主推进并提交推送，完整 V1 的 Gate、SLO、Native 和生产验收继续逐项完成。
