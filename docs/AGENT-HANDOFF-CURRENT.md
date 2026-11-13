# 胎迹 Agent 接手卡

更新：2026-11-13。完整 V1 尚未完成。本卡说明当前交付点；历史实现与验收详见[阶段总表](AGENT-HANDOFF-2026-11-13.md)，需求以[原始规格](requirements/2026-09-26-tire-intelligence-original.md)为准。

## 先看结论

- 原规格按 **12 个核心模块、10 项发布 Gate、13 项 SLO、15 项待确认决策**组织；这些是不同维度，不能相加当作独立需求总数。12 个模块均有工程实现，完整发布验收仍未闭合，不能给出可靠的整体完成百分比。
- 已有在线查询、精确身份与冲突、比较、测试事件、证据保存、监控、账户与偏好、AI 证据链及外部权限工程。当前参数来源覆盖 11 个区域目录、7 个厂商品牌，另有 NHTSA、EU Safety Gate 与小米车型来源；可信 Parser 目录 15 项。
- 最近已交付 Safety Gate 周报证据、逐告警版本／变化历史、监控调度／应用内提醒／任务 SSE、独立的索引与周报持续回退权限。
- 上一交付点 `927a2e8` 为 **Safety Gate 外部受许可读取**：查询归属、许可绑定、专用 scope、固定窗口分页、共享 SDK 和 Web Key 管理已接通，后端仍限定受管 SQLite。最新已在后端基础上接通 **Safety Gate AI 共享类型／SDK／页面／报告消费**，并以官方历史卡车轮胎告警和合成 Provider 验证正常流程；真实模型及 Native 宿主／设备继续待验。
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

## 最新代码交付点：Safety Gate AI 消费流程

基线 `12e726e33fce4bdfb49c7d2da164d7252f665eb3`，提交标题 `feat: connect Safety Gate AI evidence workflows`，最终 SHA 以 Git 为准。[消费者验收记录](assurance/evidence/safety-gate-ai-consumers-2026-11-13.md)包含材料、正常流程、原始失败和未验范围。

- 周报告警及历史版本可直接进入 AI 对话框，按所选快照／原生告警 ID 准备历史证据或在线重核，单次历史回退与 AI 外发同意分别确认。
- 包、流式结果、保存／恢复报告展示固定适用性边界；事实引用定位与源专属原件恢复已接通。恢复校验快照、周报、哈希及原生告警身份，拒绝错绑 XML。
- 共享 AI 类型及 SDK 已扩展，设备离线 `OfflineReference` 保持原范围。Native 复用既有页面、桥接和轮询，没有新增权限。
- SDK 3 组、Web 59 项、三端类型与 422 输入生产构建通过。正常 HTTP 26 项、浏览器最终流程／布局 25 项和原件检查 10 项通过；首次浏览器提交 3 项失败观察保留，按原请求恢复后成功。Markdown／HTML／PDF 均验证身份、边界与冻结复用。
- 使用官方 Report-2026-19 的 Goodyear 卡车轮胎告警 `10098848` / `SR/01396/26`。8 次历史回放、3 次模拟超时、3 次合成模型调用，真实来源／模型调用 0。185 表全部行指纹关闭后不变、原件哈希有效，自有服务／端口关闭。

新增后端组合反例、真实 OpenAI、实际 Native、正式 PG 外部 Reader、长期监控与完整 V1 仍待完成。旧后端记录中的“前端尚未接入”仅描述当时阶段，已由本次交付推进。

## 此前后端交付点：Safety Gate AI

起点为 `927a2e89fb0c3fe6faa6e13c8050d254f7fa5dab`，正式提交标题为 `feat: add Safety Gate AI evidence backend`；最终 SHA 以 Git 和交付消息为准。完整实施范围见[计划](plans/2026-11-13-safety-gate-ai.md)，本轮检查与未验边界见[后端验收记录](assurance/evidence/safety-gate-ai-backend-2026-11-13.md)。

- `safety_gate_ai_evidence.py` 定义 26 个固定字段，按 `snapshot_id + alert_id` 绑定一个官方告警；保留原生身份、哈希、Parser、时间、CC0 来源声明及适用性未评估边界。
- `ai_evidence.py` 新增历史引用 `kind=safety_gate` 与在线重核 `query_kind=safety_gate_report`，最多明确选择 6 个告警；保留单次回退同意及包容量限制，不静默截断。
- `ai_safety_gate_contract.py` 和既有网关／执行／流式链只允许模型选择事实 ID，禁止自由文字、推断和跨告警拼接；服务端生成文字，发送与完成前重核材料、包及请求绑定。
- 报告新增 `research-report@5` / `frozen-research-export@6`，创建时重核正式材料，恢复及导出使用冻结字段。旧报告仍使用原渲染版本。
- 本轮使用合成 Provider 验证后端，没有真实 OpenAI 或 Gemini 调用；外部读取权限、CC0 声明与持续回退权限均不替代本次 AI 外发同意。

最终相关后端回归 **20 模块 527／527 通过**，无跳过；826 输入稳定、资源关闭、非自检拒绝 0。包括专项 18 项及旧 AI／流式／正文／NHTSA／测试事实／报告／车型／历史 Provider 兼容检查。保留首次专项 17／18 失败和首次兼容回归停滞记录；均为测试装配边界问题，修正后重跑通过。详细回执和复跑命令见后端验收记录。

**该阶段尚未接入的消费者已在最新交付中完成工程验证。** Desktop／Android 共享工作台及相关流程代码，实际宿主／真机仍未验收；不能把共享代码等同于 Native 已通过。

## 上一交付点：Safety Gate 外部受许可读取

该阶段从 `7714db8074727198f143941d63f9c42fb02d5ec3` 交付至 `927a2e89fb0c3fe6faa6e13c8050d254f7fa5dab`，提交标题为 `feat: expose licensed Safety Gate alert pages`。

- 新增 `apps/api/tire_api/external_safety_gate.py`：源专属受管Reader、闭合字段投影、每页权限／证据重验、签名分页与HTTP路由。服务端配置固定grant ID，默认未配置，不由客户端指定。
- 新增独立 `safety-gate:read`，同步后端／旧Reader／SDK的四scope兼容；普通查询归属与许可账本沿用上一交付点，不新增表。
- 新增共享类型及 `api.safetyGateAlerts`，请求冻结、2MiB响应限制、严格DTO／游标校验及取消。Key界面新增独立选项，提示Key还需具体材料及字段许可。
- 每页要求本人成功 `query_id`、`mode=history`，limit为1–20，固定15分钟游标；保留原生身份、原件哈希／时间和未知适用性。不会抓取、继承Cookie或持续回退授权。
- 正式PostgreSQL外部Reader仍未实现；其锁、物化SQL、凭据／归属合同需专门验证。普通PG业务的既有回执不能替代这一验收。

该阶段后端13模块 **344／344通过**，823输入稳定、资源关闭、非自检拒绝0。新SDK8组与四组旧SDK、三端类型、Web55项和417输入生产构建通过。官方历史XML与CC0元信息走正常Parser／受管审批后，HTTP28项及SDK四页75条告警通过；生产Web完成Key签发／消费／撤销和1440／390／320布局。

关闭前15项、关闭后11项核对通过：185表指纹保留，原件／许可／归属完整，Parser Windows Job已完成并回收。两把测试Key撤销、grant撤回，API／Web及端口关闭。材料为保存的官方XML，真实来源／模型调用0，实时官网和PG／Native未验。[完整验收与原始失败](assurance/evidence/safety-gate-external-api-2026-11-13.md)

## 接手后优先做什么

1. 核对 main、HEAD、工作区与实时远端，读本卡、Safety Gate AI 计划及消费者验收；新 clone 重建依赖和材料，本机私槽没有随 Git 交付。
2. 补齐新 Safety Gate 后端合同的容量、错核验状态、最终发送包／body／收件模型篡改、完成时材料损坏及混合证据反例；保留既有 527 项后端回执，不能用旧域覆盖代替新增组合验证。
3. 核对实际 Native 宿主的正常桥接和轮询消费。Web 工程验收已完成，真机／宿主权限、文件保存与恢复仍需实际证据，不扩离线包域或 IPC 权限。
4. 为正式 PG 外部 Reader 单独设计与验证事务锁、物化预算、冻结归属和并发撤销语义。当前明确返回不支持，不能直接撤掉 SQLite 检查。
5. 验证监控自然长周期、多规则、真实变化提醒和通知 lag；继续其他 P0 官方渠道、地区与 SKU 参数覆盖。模拟超时、历史回放和固定材料验证不能证明这些运行指标。
6. 扩充专业原件及复用许可、精确 SKU 身份、独立标注与真人 Golden；继续代表性检索／重排质量输入和完整性能解释。
7. 凭据齐备后首先执行真实 OpenAI Responses 及 Embeddings 语义验收，显式核对 Provider 与 `/v1/ai/status`；缺凭据时推进独立工程，不反复询问。
8. 收敛生产 IAM／租户／RLS、六类平台、WCAG 读屏、安全、性能、迁移／回退和灾备 Gate，按实际验收逐项记录。

新消费者入口：`apps/web/components/safety-gate-ai-values.ts`、`safety-gate-ai-evidence.tsx`、`safety-gate.tsx`、`ai-analysis.tsx`、`ai-stream-progress.tsx`、`reports.tsx`。后端入口为 `apps/api/tire_api/safety_gate_ai_evidence.py`、`ai_safety_gate_contract.py`；外部读取配置与字段许可键见[外部 API 合同](EXTERNAL-API.md)。

## 发布仍未闭合

10 项 Gate：P0 provenance 全覆盖、未授权回退为零、Golden 错合并为零、AI 事实引用全覆盖、无高危 AuthZ／SSRF、无未处理 P0／P1、WCAG 2.2 AA、六平台 E2E、Adapter 健康／回滚、数据库／Parser 版本回退。各项均有待验部分。

13 项 SLO：结构化查询 P95≤300ms、设备检索 P95≤200ms、输入反馈≤100ms、移动 LCP≤2.5s、Adapter 开销≤300ms、权威源正常时 live query P95≤3s、按源 5–10s 超时、通知 lag≤5min、后续 99.9% 可用性、RPO≤15min、RTO≤60min、未授权回退零次、Golden 错合并零次。仍需逐项建立生产级证据。

15 项决策：首批轮胎范围、首发地区、本地知识库定义、完全单机、Offline Pack 大小、用户／Tenant、VIN 留存、AI 付费、中国区 Provider、价格／库存监控、专业数据购买、Windows 10 支持期、Native 分发、用户量／SLA、企业私有部署。除用户明确决定外，保留原文建议／待确认状态，不能替用户补成已批准。

## 验收与资料保留规则

- `.artifacts/`、原件、私库、凭据、依赖和构建产物不入 Git；新 clone 必须重建运行环境与验收材料。本次回归使用合成材料，正常链路另使用已保存的官方XML及许可元数据；没有真实模型调用。
- 不修改原规格字节；`docs/HANDOFF.md` 自 `## 当前交接入口（2026-10-26）` 起历史尾文保持封存。既有 KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 保持 `processing_unconfirmed`，不重 POST、不重开私槽、不换 UUID 抓取。
- 提交前检查源码绑定、差异与个人信息；推送前审查上游到 HEAD 的提交序列，推送后独立核对远端 SHA 和工作区。阶段完成不能将完整 V1 标记完成。

## 可复制的接手指令

> 继续实施胎迹完整 V1。先读 docs/AGENT-HANDOFF-CURRENT.md、原始规格、Safety Gate AI 计划和消费者验收。现已接通 Safety Gate 受许可外部读取、AI 后端与共享类型／SDK／页面／报告流程，并用官方历史卡车轮胎材料及合成 Provider 完成对应工程验收；补齐新后端组合反例、实际 Native、正式 PG Reader、长期监控及其余 V1 Gate。首个真实 AI 接口保持用户选择的 OpenAI Responses，Gemini 仅是历史可选适配器。缺 OpenAI／EPREL 凭据时推进独立工作，不反复询问。保留历史失败、KIT C2 封存、材料许可及单次外发边界；12 模块、10 Gate、13 SLO、15 决策分别跟踪，不宣称完整 V1 已完成。沿 main 工作，不自行建分支／worktree 或使用代理；提交前验证、审查，推送后独立核对远端 SHA 与工作区。
