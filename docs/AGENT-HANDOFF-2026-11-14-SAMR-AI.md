# 中国召回 AI Agent 接手卡

更新于 2026-11-14。完整 V1 目标持续进行，本阶段完成中国召回公告的 AI 证据、引用与报告链路。首个真实 Provider 继续采用用户选择的 OpenAI Responses API。[阶段验收](assurance/evidence/samr-cn-ai-evidence-2026-11-14.md)

## 需求与当前进度

原规格分为 12 个核心模块、10 项发布 Gate、13 项 SLO 和 15 项待确认决策。各维度独立跟踪，完整 V1 继续验收。当前覆盖 13 个轮胎区域目录、9 个厂商品牌、18 项可信 Parser、179 张模型表，整体范围与全部待验项见总表。[原规格](requirements/2026-09-26-tire-intelligence-original.md) [需求总表](AGENT-HANDOFF-2026-11-14-PUBLISH.md)

| 领域 | 当前交付 |
| --- | --- |
| 轮胎／车型事实 | 精确版本、区域产品编码、冲突并存、字段依据、车型与车轴适配及来源证据 |
| 监管 | NHTSA、EU Safety Gate、中国召回查询、原件、历史版本及变化 |
| 中国召回监控 | 后台发现／指定公告监控、去重应用内通知、任务 SSE、SDK／Web |
| 本阶段 AI | 当前在线核验、精确历史公告、11 字段冻结、同步／流式、逐包外发授权、原件引用和三种报告导出 |
| 知识应用 | 结构化证据、测试材料、原文引用、用途授权、网关账本与引用校验已有工程及限定验收 |
| 数据运维 | 非拥有者 PG／TLS、固定运行权限、显式迁移／只读 verify、源码绑定 @4 合同及隔离备份恢复已有验收 |
| 平台 | Web／PWA 与共享 Desktop／Mobile 前端已有实现，真实 Native 宿主、设备和分发继续待验 |

## 本阶段接口与实现

- 历史引用固定 `kind=samr_recall`、`snapshot_id`、原生 `article_id`。当前准备固定 `query_kind=samr_recall_notice`，使用官方公告原生路径并再次在线核验。
- `samr-recall-fact-selection@1` 保存完整 11 字段与出处，独立保留原发布日期、DeployTime、PubDate、观察和核验时间。模型选择 ID，服务端生成文字，适用性为 `not_assessed`。
- 受理、实际派发、草稿、完成采纳与报告分别复核。派发绑定账户、问题、收件模型、请求体、原件和精确核验，已受理合同可识别包标记删除。当前 AI 回退使用独立 `ai_current` audience。
- 混合监管／测试包保留各自边界，新增 SAMR 独立提示词版本。报告为 `research-report@6`，导出为 `frozen-research-export@7`。正文及 HTML 原件以纯文本呈现。
- 正常入口从中国公告详情或某次历史观察进入现有 AI 对话框，可核对原件、逐包同意外发、读取流式进度并保存／下载报告。[实施计划与文件](plans/2026-11-14-samr-cn-ai-evidence.md)

## 已验证

- 最终受管回归 519／519，865 输入稳定，资源关闭。包含 7 种混合材料的同步、流式和三种报告导出，保留此前失败回执。
- SDK 14 项、Web 66 项、全工作区类型检查及生产构建通过。
- 生产 Web 隔离浏览器 15 项通过，1440／390／320 无横向溢出，包含篡改原件拒绝、纯文本 canary、精确历史、单次回退和报告下载。
- 独立非拥有者 PG／TLS 最终 14 条通过记录、13 个不同检查名称。真实官方公告取得 live，合成 Provider 调用 2 次，真实模型调用 0 次，报告三种格式摘要与跨会话 404 通过。
- 三次浏览器与两个 PG 集群的 33 个直接进程、18 个端口及临时秘密已核对关闭。[回执与失败说明](assurance/evidence/samr-cn-ai-evidence-2026-11-14.md)

API 源码指纹为 `381b584a40a803fe98b5df649c6bcca2e0f233c9f899b4aa2119edbb928eed3e`。本阶段 @4 合同 catalog 与此前监控阶段一致，源码绑定已更新并通过非拥有者 verify。部署时使用目标环境匹配的审查批准合同。

## 剩余需求与接续顺序

1. 建立中国召回和其他来源的自然长周期、真实变化质量、通知 lag 与恢复证据。通知队列目标继续按原规格 ≤5 分钟验收。
2. 推进代表性真实精确 SKU／生产批次、人工 Golden、专业测试材料原件与复用许可，以及尚未闭合的 P0 来源 provenance。
3. 配置可用时优先验收真实 OpenAI Responses／Embeddings 的语义、引用与费用。当前专用凭据缺失，继续执行独立工程和材料核验。EPREL 正式 Key 仍未取得。
4. 继续 Parser 间歇超时原始日志与文件操作耗时定位，保留失败时间线。
5. 继续公网 Webhook、生产 IAM／Tenant／RLS、真实 Native 宿主／设备、六平台 E2E、读屏／WCAG、安全、性能、灾备及其余发布 Gate。[10 Gate／13 SLO／15 决策](AGENT-HANDOFF-2026-11-14-PUBLISH.md)

## 接手执行

```text
git status --short --branch
git log -8 --oneline --decorate
git log --oneline origin/main..HEAD
git ls-remote origin refs/heads/main
```

沿既有 main 核对工作树、待发布提交和实时远端。阶段基线为 `d61d3b2`，本次最终提交与推送结果以 Git 和交付消息核对。原件、数据库、截图、合同及运行脚本位于 Git 忽略目录，新 clone 通过正式入口重建。

> 继续实施胎迹完整 V1。先读本卡、阶段验收、PUBLISH 需求总表及原规格。当前中国召回已接通发现／查询、原件、逐公告版本、后台监控、通知、任务 SSE 和本阶段 AI 引用／报告。首个真实 Provider 使用 OpenAI Responses API，真实调用继续待验。保持精确公告／快照／核验、独立日期、逐包外发和实物适用性待核对，按所改源码重新审查 @4 合同。复用有效回执，接续自然长周期、SKU／批次、人工 Golden、材料许可、Parser 诊断和完整 V1 验收。
