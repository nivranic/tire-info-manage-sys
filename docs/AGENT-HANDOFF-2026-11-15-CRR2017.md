# 胎迹 Agent 交接卡

更新于2026-11-15，基线7eefe80，现有main继续完整V1。当前发布提交以Git及本阶段私有publish.json为准。[原始需求](requirements/2026-09-26-tire-intelligence-original.md) [本阶段验收](assurance/evidence/material-deadline-crr2017-2026-11-15.md)

## 需求与决定

原规格共12个核心模块、10项发布Gate、13项SLO及15项待确认决策。用户已授权持续实施、验证、提交、push、复核优化及更新交接，专业材料由agent自主选择。首个真实模型指定OpenAI Responses API，EPREL无Key，继续独立工作。

现有main继续，新分支／worktree及代理使用核对当次明确授权。PowerShell使用7。真实原件、隔离库及验收资料保存在Git忽略目录。账户、个人Garage及保存比较已落地，旧共享记录归创建者的策略由agent根据创建证据制定。

## 当前阶段完成

- 捕获策略支持1至70秒整数总期限，默认45。默认指纹兼容，自定义期限冻结、重放并在Web显示。70秒上限由agent依据75秒客户端期限制定。
- 完整保存许可滚阻论文，6页、2,413,872字节，原件摘要85d6850a21e912d345b9eda8b9ce18564a76a020ed2e4c2a201a15a9bd616a91。正常捕获约5秒，成功耗时本身不能证明期限扩展的实际作用。
- 正常录入MCPR／225/55R16及BLUECO／195/50R18的11路面22成绩，保留原4胎范围、selected_results、不同尺寸、50 km/h例外、来源名次null及22个PDF码点引用。
- 同场比较、关联FTS、离线v1／v2及Web消费通过。3个PDF chunk的原文研究、独立导出用途授权与三格式报告通过，真实模型调用0。
- API402通过，Web68、SDK材料16通过，全工作区类型检查及Web生产构建通过。正常生产浏览器8项、独立非拥有者PG／TLS4项通过，资源及临时秘密已清理。

数据库迁移036，PG运行合同postgres-runtime-schema@4，FTS派生索引accepted-heads-fts@7。

## 尚未完成

真实材料全链路acceptance.json整体仍为false。整场22成绩的结构化AI证据包61,421字节，超过44,000字节上限，正常入口422。已保存22条成绩保持manual_transcription／unverified，精确SKU及真人Golden均为0。PDF原文研究另有通过回执。

历史专业Golden的54项条件跳过仍需R74私有原件恢复。原始失败、超时、32MB拒绝和首次驱动错误保留在验收资料中。

## 12模块进度

| 模块 | 已有实现 | 主要余项 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、组合筛选、来源状态、授权回退、13区域目录 | 其余P0来源／地区及长期稳定性 |
| 精确版本 | 产品代码、GTIN、OE、地区、冲突、Golden与SKU桥 | 真实SKU、真人Golden及错合并指标 |
| 车型适配 | SU7前后轴、个人Garage、官方PDF与SKU桥 | 更多车型、完整OE及Native真实消费 |
| 比较 | SKU、个人保存、同场混合尺寸、条件与真实选录值 | 精确SKU正例及推荐质量 |
| 测评库 | TestEvent、逐胎尺寸、PDF码点引用、真实22成绩 | 人工复核、独立Golden原文引用合同 |
| 信息监控 | Worker、差异、三地召回、通知及SSE | 自然长期运行、lag与更多差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider与费用规划 | 全实体、生产权限、BYOK与账单 |
| 证据浏览 | 快照、SHA、Parser、HTML／PDF引用、许可原件捕获 | 实际部署、许可治理、对象存储 |
| 个性化 | 关注、偏好、兴趣、个人Garage／保存比较 | 跨设备验收、其他共享实体及长期质量 |
| AI研究 | grounding、流式、报告、检索评估、真实PDF研究 | 显式成绩选择、真实Responses／Embeddings及语义质量 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、PG角色 | 公网接收端、吞吐、SDK产品化及完整WebSocket |
| 管理后台 | 健康、回滚、隔离、失败任务、纠错与审计 | 生产IAM／Tenant／RLS与完整发布验收 |

10项Gate和13项SLO需继续逐项取证。Android instrumentation构建／设备、Native、六类平台E2E、WCAG、自然长周期、生产部署／恢复仍有余项。详细历史范围见[前阶段总表](AGENT-HANDOFF-2026-11-15-MIXED-SIZES.md)。

## 接手顺序

1. 核对git status、HEAD、origin/main及发布回执，阅读本阶段失败和验证边界。完整V1目标保持active。
2. 实现显式AI成绩选择，覆盖API、共享类型、SDK、Web、证据绑定与报告回查。保留原本场成绩N和manual_test_*.field_(N+7)，兼容旧缺省引用和指纹。
3. 使用现有真实22成绩隔离库从正常入口验收选择、超限提示、报告回查、删除／变更及浏览器流程。整场原失败继续保留。
4. 补齐独立Golden的PDF引用字面量合同，恢复R74摘要一致的原件后运行完整观察器及54项条件用例。旧KIT C2沿历史封存状态处理。
5. 持续推进真实SKU与真人Golden、Android／Native／跨设备、真实模型、监管接口和部署Gate。凭据问题按实际条件记录，继续独立工作。

## 实现与回执入口

捕获合同位于apps/api/tire_api/material_source_policy.py及material_source_transport.py，Web入口为apps/web/components/source-materials.tsx，共享类型为packages/domain-types/src/source-materials.ts。

真实验收资料位于.artifacts/real-crr2017-20261115-r6，包含workspace.sqlite、event-request.json、acceptance.json、research-result.json、离线包及Web报告。临时browser-session.json已删除。受管回归为material-deadline-20261115-final，PG指针及资源审计为material-deadline-20261115-pg。提交中的[验收索引](assurance/evidence/material-deadline-crr2017-2026-11-15.md)保留摘要，clone须重新生成私有证据。
