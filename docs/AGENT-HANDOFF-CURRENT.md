# 胎迹 Agent 接手卡

更新：2026-11-13。完整 V1 尚未完成。本卡说明当前交付点；历史实现与验收详见[阶段总表](AGENT-HANDOFF-2026-11-13.md)，需求以[原始规格](requirements/2026-09-26-tire-intelligence-original.md)为准。

## 先看结论

- 原规格按 **12 个核心模块、10 项发布 Gate、13 项 SLO、15 项待确认决策**组织；这些是不同维度，不能相加当作独立需求总数。12 个模块均有工程实现，完整发布验收仍未闭合，不能给出可靠的整体完成百分比。
- 已有在线查询、精确身份与冲突、比较、测试事件、证据保存、监控、账户与偏好、AI 证据链及外部权限工程。当前参数来源覆盖 11 个区域目录、7 个厂商品牌，另有 NHTSA、EU Safety Gate 与小米车型来源；可信 Parser 目录 15 项。
- 最近已交付 Safety Gate 周报证据、逐告警版本／变化历史、监控调度／应用内提醒／任务 SSE、独立的索引与周报持续回退权限。
- 本次交付点为 **Safety Gate 查询归属与受管许可绑定**。外部告警读取 API、专用 scope、分页、SDK 和管理界面尚未接通。
- 首个真实 AI 接口始终是用户指定的 **OpenAI Responses API**。Gemini 是此前 agent 按原规格多模型备选表提前实现的可选适配器，提交为 `d5fded1`；没有用户改选 Gemini 的指令，也没有真实 Google 调用验收。

## 用户已确定的边界

1. 持续依据需求实施，并已授权复核优化、总结、提交、push 全部改动和编写交接文档。
2. 专业材料由 agent 自行选择、核对来源与许可，无需反复追问选材。
3. 当前没有 EPREL Key；缺少外部凭据时推进独立工作。此前记录 OpenAI 模型／Key 亦缺失，本次收尾未重新检查凭据，也未调用真实模型。
4. 原规格中的功能建议属于需求材料；用户消息决定任务授权与接入顺序。原文中模型版本、定价等外部事实使用前须重新核验。
5. 沿既有 `main` 工作。创建分支／worktree、使用或修改代理均须另有明确授权。PowerShell 使用 7，命令显式指定工作目录。

## 12 个模块做到哪里

| 模块 | 已有能力 | 仍缺的主要验收或实现 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、来源与状态、组合筛选、单次与持续回退授权 | 更多 P0 来源／地区、长期在线稳定性 |
| 精确版本识别 | 产品代码／GTIN／OE／地区身份、冲突、Golden 工作台 | 代表性真实 SKU、人工 Golden、错合并指标 |
| 车型适配 | SU7 前后轴、车库、SKU 证据桥、官方 PDF 工程 | 更多车型、完整 OE 事实、Native 消费 |
| 比较 | 精确 SKU 比较、保存、同场测试与条件偏好 | 专业性能解释、真实推荐质量 |
| 测评数据库 | TestEvent、环境／指标／原件、身份桥、真实原报道隔离验证 | 精确 SKU 正例、正式原件与复用许可、真人审核 |
| 信息监控 | Worker、参数差异、NHTSA、Safety Gate 规则／历史／应用内提醒 | 自然长周期、通知质量与可靠性、任意网页／PDF 差异 |
| 传统 CRUD | 来源、规则、偏好、测试、账户、Provider、Key 与费用规划 | 全实体覆盖、生产权限、BYOK、真实账单 |
| 证据浏览 | 快照／哈希／Parser、原件、HTML／PDF 正文、引用恢复 | 部署旧库切换、完整许可治理、生产对象存储 |
| 个性化 | 车库、关注、偏好、保存比较、非 SKU 兴趣 | 跨设备、长期运行与真实推荐质量 |
| AI 研究 | grounding、流式、报告、正文证据包、FTS／向量／融合检索与评估 | 真实 Responses／Embeddings 语义、代表性检索质量与模型治理 |
| 对外能力 | REST、SSE、SDK、Webhook、Key、轮胎事实许可读取 | Safety Gate 外部 API、正式 PG Reader、公网接收端、SDK 产品化、完整 WebSocket |
| 管理后台 | Parser 健康／发布回滚、隔离、失败任务、纠错与审计 | 生产 IAM／租户／RLS、完整角色治理、灾备与发布验收 |

## 本次代码交付点

起点是已发布的 `d8a42a1146ca2684fcce5c3534eae1e64e8aa059`。交付提交使用 `feat: bind Safety Gate query ownership and license evidence`，最终完整 SHA 以 Git 和交付消息为准。

- `apps/api/tire_api/safety_gate.py`：普通登录查询在干净会话中捕获账户，以既有机制原子保存查询、审计及不可变 owner 收据。匿名旧查询不追认、会话换绑不转移归属，单次 consent 不新增归属。失败尝试有 owner 不等于成功核验。
- `apps/api/tire_api/external_fact_governance.py`：固定 `eu-safety-gate` 分支使用自己的 Snapshot／Verification 表校验指定周报、原件与文档摘要、查询、Parser 和成功状态；保持原许可 receipt 结构，仍走管理员预览／确认账本。索引不能按周报告警审批，CC0 声明不绕过受管审批。
- 新增 `test_safety_gate_query_ownership.py` 和 `test_safety_gate_external_governance.py`，并登记受管回归入口。没有新增数据库表或外部路由。
- 归属读写和外部受管 Reader 仍受既有 SQLite 限制；普通 PostgreSQL 查询可以运行，但不能因此宣称正式 PostgreSQL 外部读取已实现。本次没有执行 PG 验收。

本次八模块 **143／143 通过**，818 个源码输入稳定、自有资源关闭、非自检拒绝 0；原始失败和修正见[交付点验收记录](assurance/evidence/safety-gate-external-foundation-2026-11-13.md)。此前持续回退的 API 116、SDK 7、Web 55、三端类型、构建、PG 34、HTTP 26、生产 Web 45 项属于上一阶段证据，本次未重跑前端／浏览器／PG，不混用成新改动验收。

## 接手后优先做什么

1. 核对 `main`、HEAD、工作区、实时远端，读本卡与[外部读取计划](plans/2026-11-13-safety-gate-external-api.md)。先确认本次回归和源码绑定，再继续计划步骤 3。
2. 实现源专属 Reader 与 `GET /external/v1/safety-gate-reports/{report_id}/alerts`。要求本人成功 `query_id` 与 `mode=history`；不抓取、不继承 Cookie 或持续回退权限。
3. 新增独立 `safety-gate:read` scope，固定服务端 grant 路由。每页在新鲜受管事务中重验 Bearer、账户、冻结归属、许可头、快照及字段范围；游标绑定 Key、owner 承诺、路由、query、report、limit、快照与许可头，15 分钟固定到期。
4. 定稿闭合 DTO 与许可字段映射、输入／物化／响应容量上限。保留 `local_snapshot`、原生告警 ID、证据哈希／时间与未知适用性，禁止透传 XML、私人规则、账户 ID、许可审核原文。联动旧 scope 数量限制，避免破坏旧 Key。
5. 接共享类型、SDK 严格响应校验、API Key 界面与文档。覆盖跨账户、匿名旧查询、失败／索引查询、撤销、错绑、分页重放、容量、并发及旧轮胎接口兼容。
6. 完成真实许可材料、正常 HTTP、生产 Web 签发／撤销／消费和资源关闭验收；新源码独立绑定，保留所有失败记录后再宣称外部链路接通。
7. 并行方向由接手 agent 按授权安排：继续 P0 来源、专业材料／精确 SKU、人工 Golden 与质量输入、Safety Gate AI／Native 和自然长周期。凭据齐备后首先验收 OpenAI Responses，显式设置 `TI_AI_PROVIDER=openai_responses` 并核对 `/v1/ai/status`。

关键复用入口：`query_ownership.py`、`external_fact_governance.py`、`external_fact_reader.py`、`external_api.py`、`safety_gate.py`、`packages/domain-types/src/external-api.ts`、`packages/api-client/src/external-api.ts`、`apps/web/components/api-keys.tsx`。新增 scope 时需同时核对后端 Key、Reader 与 SDK 的三 scope 上限。

## 发布仍未闭合

10 项 Gate：P0 provenance 全覆盖、未授权回退为零、Golden 错合并为零、AI 事实引用全覆盖、无高危 AuthZ／SSRF、无未处理 P0／P1、WCAG 2.2 AA、六平台 E2E、Adapter 健康／回滚、数据库／Parser 版本回退。各项均有待验部分。

13 项 SLO：结构化查询 P95≤300ms、设备检索 P95≤200ms、输入反馈≤100ms、移动 LCP≤2.5s、Adapter 开销≤300ms、权威源正常时 live query P95≤3s、按源 5–10s 超时、通知 lag≤5min、后续 99.9% 可用性、RPO≤15min、RTO≤60min、未授权回退零次、Golden 错合并零次。仍需逐项建立生产级证据。

15 项决策：首批轮胎范围、首发地区、本地知识库定义、完全单机、Offline Pack 大小、用户／Tenant、VIN 留存、AI 付费、中国区 Provider、价格／库存监控、专业数据购买、Windows 10 支持期、Native 分发、用户量／SLA、企业私有部署。除用户明确决定外，保留原文建议／待确认状态，不能替用户补成已批准。

## 验收与资料保留规则

- `.artifacts/`、原件、私库、凭据、依赖和构建产物不入 Git；新 clone 必须重建运行环境与验收材料。本次新增验证只用合成材料，没有真实模型调用。
- 不修改原规格字节；`docs/HANDOFF.md` 自 `## 当前交接入口（2026-10-26）` 起历史尾文保持封存。既有 KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 保持 `processing_unconfirmed`，不重 POST、不重开私槽、不换 UUID 抓取。
- 提交前检查源码绑定、差异与个人信息；推送前审查上游到 HEAD 的提交序列，推送后独立核对远端 SHA 和工作区。阶段完成不能将完整 V1 标记完成。

## 可复制的接手指令

> 继续实施胎迹完整 V1。先读 docs/AGENT-HANDOFF-CURRENT.md、原始规格和 Safety Gate 外部读取计划。当前最新交付仅完成查询归属与许可证据绑定；从源专属外部 Reader、scope、分页、SDK 和 Web 开始，补正常链路及真实许可材料验收。OpenAI Responses 是用户选定的首个真实 AI 接口，Gemini 仅是历史可选适配器。缺 OpenAI／EPREL 凭据时推进独立工作，不反复询问。保留所有历史失败、KIT C2 封存和材料许可边界；12 模块、10 Gate、13 SLO、15 决策仍需逐项完成。沿 main 工作，不自行创建分支／worktree 或使用代理；每次交付写清实际验证、未验边界和下一步。
