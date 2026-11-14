# 胎迹 Agent 交接卡

2026-11-15，沿现有main继续完整V1，阶段基线6e0aa65。发布SHA以Git及本阶段私有publish.json核对。[原始需求](requirements/2026-09-26-tire-intelligence-original.md) [本阶段验收](assurance/evidence/ai-test-measurement-selection-2026-11-15.md)

## 总需求与已授权决定

原规格共12个核心模块、10项发布Gate、13项SLO及15项待确认决策。用户授权持续实施、验证、提交、push、复核优化和交接，专业材料自主选择。真实模型首选OpenAI Responses API，EPREL暂无Key，继续独立工作。

使用现有main，分支／worktree及代理按当次明确授权处理。PowerShell使用7。原件、隔离库及验收资料置于Git忽略目录。账户和个人资料已落地，旧共享记录归创建者的策略由agent根据创建证据制定。

## 最新进度

- 已发布6e0aa65，来源捕获支持1至70秒冻结期限、默认45秒兼容旧指纹。70秒上限由agent依据75秒客户端期限制定。
- 许可滚阻论文已捕获完整6页、2,413,872字节，两胎、11路面、22条真实转录成绩已核验比较、检索及离线。原件、出处、许可、原值和方法见[前阶段卡](AGENT-HANDOFF-2026-11-15-CRR2017.md)。
- 本阶段增加AI显式成绩选择，保留原序号、PDF引用和7项场次条件，冻结范围事实。Web通用对话框支持选录、清空、恢复整场和修改后重新准备。
- 真实成绩以agent选择的10条及12条两组通过，证据包30,120／35,558字节，22值各出现一次。两份报告的回查及三格式导出通过，真实模型调用0。完整22条单包仍因44,000字节上限返回422。
- 全工作区类型检查、Web构建、Web69、桌面22、移动24及离线14通过，PG／TLS6项和生产浏览器复跑11项通过。最终API5模块239通过、0失败，867输入稳定，143子进程exit 0并回收。8服务记录、10记录进程及7端口关闭，临时会话文件、PG口令和TLS私钥已清理。

迁移036，PG运行合同postgres-runtime-schema@4，FTS索引accepted-heads-fts@7。API首批233通过、6失败，对应11参数用例独立诊断及最终完整批均通过。首批PDF相关失败及首次浏览器409根因尚未确认，保留失败和复跑两类回执。

## 12模块当前状态

| 模块 | 已实现 | 主要余项 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、筛选、授权回退、13区域目录 | 其余P0来源／地区及长期稳定性 |
| 精确版本 | 代码、GTIN、OE、地区、冲突、Golden及SKU桥 | 真实SKU、真人Golden及错合并指标 |
| 车型适配 | SU7轴位、个人Garage、官方PDF与SKU桥 | 更多车型、OE及Native真实消费 |
| 比较 | SKU、个人保存、混合尺寸、条件和真实选录值 | 精确SKU正例及推荐质量 |
| 测评库 | TestEvent、逐胎尺寸、PDF引用、22条真实成绩 | 人工复核及独立Golden原文引用合同 |
| 信息监控 | Worker、差异、三地召回、通知与SSE | 自然长周期、lag及更多差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider与费用规划 | 全实体、生产权限、BYOK及账单 |
| 证据浏览 | SHA、Parser、引用恢复、许可PDF捕获 | 实际部署、许可治理及对象存储 |
| 个性化 | 关注、偏好、兴趣、个人Garage及保存比较 | 跨设备、其他共享实体及长期质量 |
| AI研究 | grounding、流式、报告、检索评估及显式成绩选择 | 真实Responses／Embeddings及语义质量 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、PG角色 | 公网接收端、吞吐、SDK产品化及完整WebSocket |
| 管理后台 | 健康、回滚、隔离、任务、纠错与审计 | 生产IAM／Tenant／RLS及完整发布验收 |

10项Gate、13项SLO和六类平台E2E需继续逐项取证。已保存成绩保持manual_transcription／unverified，精确SKU正例和真人Golden为0。历史专业Golden的54项条件跳过需R74摘要一致的私有原件。Native宿主、Android instrumentation／设备、WCAG、长期监控和生产恢复继续待验。

## 接手顺序

1. 核对HEAD、origin/main、git status、发布回执与本阶段最终API及资源结果。完整V1目标保持active。
2. 如本阶段首次PDF失败仍未复现，保留其根因待确认状态，依据原始失败开展独立定位。
3. 补齐独立Golden的PDF引用字面量合同，从正常入口复现真实选录值。恢复R74原件后运行完整观察器和54项条件用例。旧KIT C2沿封存状态处理。
4. 推进真实SKU及真人Golden、Android／Native／跨设备、真实OpenAI、EPREL与部署Gate。缺少凭据时继续其余独立工作。

## 代码及资料入口

API选择位于apps/api/tire_api/ai_evidence.py，PDF原序号绑定复用test_measurement_originals.py。Web入口为ai-analysis.tsx和test-ai-measurement-selection.tsx，引用键为recall-evidence-values.ts，共享引用类型在packages/domain-types/src/index.ts。

真实验收为.artifacts/ai-measurement-selection-20261115-real，API首批为ai-measurement-selection-20261115-regression，诊断为ai-measurement-selection-20261115-diagnostic，最终批为ai-measurement-selection-20261115-final，独立PG、资源及发布回执为ai-measurement-selection-20261115-pg。临时browser-session.json已删除。完整回执摘要见验收文档，clone须重建私有资料。
