# 胎迹 Agent 交接卡

更新于2026-11-15。当前沿既有main实施，阶段基线为已发布b393b25。本卡汇总账户归属修复及完整V1余项，最终提交与远端SHA见本轮交付记录。完整V1目标继续进行。

## 接手入口

- 阅读原始需求、当前卡及本阶段验收，分别核对需求、实现和实际验证。原始规格包含12个核心模块、10项发布Gate、13项SLO、15项产品决策，整体完成率仍缺完整验收依据。[原始规格](requirements/2026-09-26-tire-intelligence-original.md)
- 用户授权持续实施、复核优化、提交、push及编写交接。专业材料由agent自行选择并核对许可。首个真实模型使用OpenAI Responses API，EPREL尚无Key，继续推进独立工作。[Provider记录](assurance/evidence/provider-handoff-review-2026-11-14.md)
- 阶段证据包含失败、修正、部署合同及本机忽略回执。新clone须重新建立验证环境，原件与私有回执位于Git忽略目录。[会话归属验收](assurance/evidence/session-data-ownership-2026-11-15.md)

## 本次完成

1. 修正同浏览器退出、换号后报告及AI历史随会话重绑而转入另一账户的问题。登录、注册及已登录退出均轮换cookie，已退休凭据失效。
2. 036迁移为local_sessions增加owner_user_id及anonymous_claimable，179张模型表。持久资料按owner聚合，当前登录通过user_id、期限和归属一致性认证。在线及CLI密码重置、过期清理和删户均保留资料owner。
3. 新匿名资料可首次认领一次。旧有明确user_id的资料回填owner。旧无绑定资料保留原记录且关闭自动认领，历史错绑须依独立证据确定原属。该迁移策略由agent据已有数据形状制定。
4. 报告和AI使用现有AuthProvider账户代次，在身份重验时清除旧私有状态、取消请求并拒绝迟到结果。报告不确定保存按账户分区，AI恢复指针按账户保存在sessionStorage。匿名指针存于当前代次内存，刷新后从服务端历史核对。
5. 私人监控通知使用持久owner，并要求该账户存在有效登录后投递至已授权Webhook订阅。同账户重新登录可继续投递，其他账户登录不会恢复其投递资格。
6. 增加真实旧会话形状升级、036失败回滚／重复执行、并发认领、CLI恢复和报告／AI／导出隔离回归。更新历史迁移夹具的明确增量及FTS前置，旧列与旧业务行仍逐项比较。

## 验证状态

- 最终受管18模块共414项，413通过、1项因指定Round38原始备份缺失而跳过，0失败／不完整，867输入稳定，资源关闭。此前扩大回归485项及账户／Webhook专项238项均通过。
- 最终非拥有者PG／TLS12项通过，正常HTTP进程完成Cookie轮换、旧凭据拒绝、口令重置、报告／AI／原件及重启恢复。正式b393b25源码创建的真实035旧PG库升级后保留180个关系中42条原行，重复执行稳定，@4合同匹配。
- 生产浏览器25项、Web68项、四个前端工作区类型及生产构建通过。真实模型调用为0。
- 两批PG和两批浏览器共14条服务记录、20个进程ID、11个端口及临时口令／TLS私钥已核对。完整摘要与失败记录见阶段验收。

模型调用采用合成Responses，浏览器及PG使用项目生成的合成PDF和成绩。真实模型、真实专业成绩以及生产远端部署继续待验。浏览器首批脚本把车库误按私有资料断言，已依据其local_workspace协议纠正，失败回执保留。

## 12个模块的当前进度

| 模块 | 当前实现与阶段结果 | 未完成或待验 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、组合筛选、来源状态、回退授权，13个区域目录、9个品牌 | 其余P0来源、地区和型号、长期稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区身份、冲突、Golden工作台 | 代表性真实SKU独立绑定、真人Golden、错合并指标 |
| 车型适配 | SU7前后轴、Garage、SKU证据桥、官方PDF | 更多车型、完整OE、Native实际消费 |
| 比较 | 精确SKU、保存比较、同场成绩和条件、偏好 | 专业性能解释与真实推荐质量 |
| 测评数据库 | TestEvent、环境指标、PDF成绩引用、身份桥 | 真实逐胎数值与SKU正例、许可及真人审核 |
| 信息监控 | Worker、轮胎差异、NHTSA、Safety Gate、中国召回历史及调度、通知和任务SSE | 自然长周期、真实通知lag、更多任意网页与PDF差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider、Key和费用规划 | 全实体覆盖、生产权限、BYOK及真实账单 |
| 证据浏览 | 快照、SHA、Parser、原件、HTML/PDF正文和引用恢复，已保存1份CC BY研究PDF | 实际部署库切换、完整许可治理、生产对象存储 |
| 个性化 | 关注、个人偏好、兴趣、Garage和保存比较 | 车库／保存比较等账户私有化、跨设备、长期推荐质量 |
| AI研究 | grounding、同步／流式、报告、FTS／向量／融合检索和离线评估，账户归属修复 | 真实Responses／Embeddings网络与语义、代表性质量及治理 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、SQLite／PG许可读取和角色 | 公网接收端、生产吞吐、SDK产品化、完整WebSocket |
| 管理后台 | Parser健康、发布回滚、隔离、失败任务、纠错和审计 | 生产IAM／Tenant／RLS、完整角色及发布验收 |

当前车库、保存比较及部分工作区实体采用local_workspace范围。完整个人／团队隔离需要后续实体归属设计与历史数据处理。本阶段已修正已复现的报告及AI会话资料转移路径，整体AuthZ和发布Gate继续逐项验收。

## 主要代码入口

- 认证、迁移与Cookie位于apps/api/tire_api/auth.py、db.py、migrations.py、main.py和manage.py。运行角色新列权限位于postgres_runtime_roles.py。
- 私人通知归属位于webhook_delivery.py。报告与AI页面位于apps/web/components/reports.tsx和ai-analysis.tsx，沿既有AuthProvider实现。
- 测试在既有账户、查询归属、报告、Webhook和迁移模块。子进程护栏的REVIEWED摘要按审查后的原始字节更新。[实施计划](plans/2026-11-15-session-data-ownership.md)

## 接下来按此顺序推进

1. 先核对git status、HEAD与origin/main，以及本阶段最终回执。恢复实现时保持PowerShell7和现有分支，按当前用户授权处理提交和网络操作。
2. 处理完整个人账户范围，逐实体明确Garage、保存比较及共享工作区数据的归属与迁移，覆盖旧库、正常SDK和Native客户端。
3. 从已保存许可研究PDF或其他可核对原材料取得真实逐胎数值、测试条件和参测身份，完成精确SKU证据桥及真人Golden。当前研究图表的逐胎精确值继续待证。[材料卡](AGENT-HANDOFF-2026-11-14-MATERIAL.md)
4. 以OpenAI Responses推进真实网络和语义验收，再验Embeddings；密钥使用本机环境配置。已有其他Provider适配器沿历史合成证据记录。[AI阶段卡](AGENT-HANDOFF-2026-11-14-SAMR-AI.md)
5. EPREL官方访问资格及正式API合同仍待外部条件，继续来源、长期监控及不依赖该Key的工程。
6. 推进Native安装／设备E2E、跨端账户与离线owner变化、WCAG／读屏／PWA、生产IAM／部署／恢复和SLO。逐项补齐10项发布Gate，完成完整V1验收。

旧KIT C2材料沿既有封存边界处理，继续保留原始失败与不确定状态。部署当前API前，须为目标PG主版本、catalog、源码和向量索引声明重新生成并批准@4合同。历史会话资料回退应核对数据库备份、owner及原件，记录核验结果。
