# 胎迹 Agent 接手卡

更新：2026-11-13。完整 V1 尚未完成。本卡说明当前交付点；历史实现与验收详见[阶段总表](AGENT-HANDOFF-2026-11-13.md)，需求以[原始规格](requirements/2026-09-26-tire-intelligence-original.md)为准。

## 先看结论

- 原规格按 **12 个核心模块、10 项发布 Gate、13 项 SLO、15 项待确认决策**组织；这些是不同维度，不能相加当作独立需求总数。12 个模块均有工程实现，完整发布验收仍未闭合，不能给出可靠的整体完成百分比。
- 已有在线查询、精确身份与冲突、比较、测试事件、证据保存、监控、账户与偏好、AI 证据链及外部权限工程。当前参数来源覆盖 11 个区域目录、7 个厂商品牌，另有 NHTSA、EU Safety Gate 与小米车型来源；可信 Parser 目录 15 项。
- 最近已交付 Safety Gate 周报证据、逐告警版本／变化历史、监控调度／应用内提醒／任务 SSE、独立的索引与周报持续回退权限。
- 本次交付点为 **Safety Gate 外部受许可读取**：查询归属、许可绑定、专用 scope、固定窗口分页、共享 SDK 和 Web Key 管理已接通，后端仍限定受管 SQLite。
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
| 对外能力 | REST、SSE、SDK、Webhook、Key、轮胎事实许可读取 | 正式 PG Reader、公网接收端、SDK 产品化、完整 WebSocket |
| 管理后台 | Parser 健康／发布回滚、隔离、失败任务、纠错与审计 | 生产 IAM／租户／RLS、完整角色治理、灾备与发布验收 |

## 本次代码交付点

起点是已发布的 `7714db8074727198f143941d63f9c42fb02d5ec3`，本轮提交标题为 `feat: expose licensed Safety Gate alert pages`；最终SHA以Git和交付消息为准。

- 新增 `apps/api/tire_api/external_safety_gate.py`：源专属受管Reader、闭合字段投影、每页权限／证据重验、签名分页与HTTP路由。服务端配置固定grant ID，默认未配置，不由客户端指定。
- 新增独立 `safety-gate:read`，同步后端／旧Reader／SDK的四scope兼容；普通查询归属与许可账本沿用上一交付点，不新增表。
- 新增共享类型及 `api.safetyGateAlerts`，请求冻结、2MiB响应限制、严格DTO／游标校验及取消。Key界面新增独立选项，提示Key还需具体材料及字段许可。
- 每页要求本人成功 `query_id`、`mode=history`，limit为1–20，固定15分钟游标；保留原生身份、原件哈希／时间和未知适用性。不会抓取、继承Cookie或持续回退授权。
- 正式PostgreSQL外部Reader仍未实现；其锁、物化SQL、凭据／归属合同需专门验证。普通PG业务的既有回执不能替代这一验收。

本轮后端13模块 **344／344通过**，823输入稳定、资源关闭、非自检拒绝0。新SDK8组与四组旧SDK、三端类型、Web55项和417输入生产构建通过。官方历史XML与CC0元信息走正常Parser／受管审批后，HTTP28项及SDK四页75条告警通过；生产Web完成Key签发／消费／撤销和1440／390／320布局。

关闭前15项、关闭后11项核对通过：185表指纹保留，原件／许可／归属完整，Parser Windows Job已完成并回收。两把测试Key撤销、grant撤回，API／Web及端口关闭。材料为保存的官方XML，真实来源／模型调用0，实时官网和PG／Native未验。[完整验收与原始失败](assurance/evidence/safety-gate-external-api-2026-11-13.md)

## 接手后优先做什么

1. 核对main、HEAD、工作区与实时远端，读本卡、[外部API合同](EXTERNAL-API.md)及上述验收；新clone重建依赖和材料，不把本机私槽视为已随Git交付。
2. 继续Safety Gate的AI证据引用和Native业务消费，复用原生告警身份、用途授权及同意机制；告警适用性保持待核对，不把它转换成精确SKU推荐。
3. 为正式PG外部Reader单独设计与验证事务锁、物化预算、冻结归属和并发撤销语义。当前明确返回不支持，不能直接撤掉SQLite检查。
4. 验证监控自然长周期、多规则、真实变化提醒和通知lag；本轮外部读取、此前模拟到期均不证明这些指标。继续其他P0官方渠道、地区与SKU参数覆盖。
5. 扩充专业原件及复用许可、精确SKU身份、独立标注与真人Golden；继续代表性检索／重排质量输入和完整性能解释。
6. 凭据齐备后首先执行真实OpenAI Responses及Embeddings语义验收。显式设置 `TI_AI_PROVIDER=openai_responses` 并核对 `/v1/ai/status`；缺凭据时推进独立工程。
7. 收敛生产IAM／租户／RLS、六类平台、WCAG读屏、安全、性能、迁移／回退和灾备Gate，按实际验收逐项记录，不按已有实现推定完成。

关键入口：`external_safety_gate.py`、`external_api.py`、`external_fact_reader.py`、`external_fact_governance.py`、`query_ownership.py`、`packages/api-client/src/external-safety-gate.ts`、`packages/domain-types/src/external-api.ts`、`apps/web/components/api-keys.tsx`。详细配置和字段许可键见外部API合同。

## 发布仍未闭合

10 项 Gate：P0 provenance 全覆盖、未授权回退为零、Golden 错合并为零、AI 事实引用全覆盖、无高危 AuthZ／SSRF、无未处理 P0／P1、WCAG 2.2 AA、六平台 E2E、Adapter 健康／回滚、数据库／Parser 版本回退。各项均有待验部分。

13 项 SLO：结构化查询 P95≤300ms、设备检索 P95≤200ms、输入反馈≤100ms、移动 LCP≤2.5s、Adapter 开销≤300ms、权威源正常时 live query P95≤3s、按源 5–10s 超时、通知 lag≤5min、后续 99.9% 可用性、RPO≤15min、RTO≤60min、未授权回退零次、Golden 错合并零次。仍需逐项建立生产级证据。

15 项决策：首批轮胎范围、首发地区、本地知识库定义、完全单机、Offline Pack 大小、用户／Tenant、VIN 留存、AI 付费、中国区 Provider、价格／库存监控、专业数据购买、Windows 10 支持期、Native 分发、用户量／SLA、企业私有部署。除用户明确决定外，保留原文建议／待确认状态，不能替用户补成已批准。

## 验收与资料保留规则

- `.artifacts/`、原件、私库、凭据、依赖和构建产物不入 Git；新 clone 必须重建运行环境与验收材料。本次回归使用合成材料，正常链路另使用已保存的官方XML及许可元数据；没有真实模型调用。
- 不修改原规格字节；`docs/HANDOFF.md` 自 `## 当前交接入口（2026-10-26）` 起历史尾文保持封存。既有 KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 保持 `processing_unconfirmed`，不重 POST、不重开私槽、不换 UUID 抓取。
- 提交前检查源码绑定、差异与个人信息；推送前审查上游到 HEAD 的提交序列，推送后独立核对远端 SHA 和工作区。阶段完成不能将完整 V1 标记完成。

## 可复制的接手指令

> 继续实施胎迹完整 V1。先读 docs/AGENT-HANDOFF-CURRENT.md、原始规格和 Safety Gate 外部读取计划。当前已接通Safety Gate受许可外部Reader、scope、分页、SDK和Web Key管理，正常历史材料链路已验收；继续AI／Native消费、正式PG Reader、长期监控及其余V1 Gate。OpenAI Responses 是用户选定的首个真实 AI 接口，Gemini 仅是历史可选适配器。缺 OpenAI／EPREL 凭据时推进独立工作，不反复询问。保留所有历史失败、KIT C2 封存和材料许可边界；12 模块、10 Gate、13 SLO、15 决策仍需逐项完成。沿 main 工作，不自行创建分支／worktree 或使用代理；每次交付写清实际验证、未验边界和下一步。
