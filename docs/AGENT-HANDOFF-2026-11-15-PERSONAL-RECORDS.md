# 胎迹 Agent 交接卡

更新于2026-11-15，沿既有main实施，阶段基线为已发布f66c4c0。当前完成车库与保存比较的个人账户归属，完整V1继续进行。[阶段验收](assurance/evidence/personal-records-2026-11-15.md)

## 需求与已确认决定

- 总需求包含12个核心模块、10项发布Gate、13项SLO及最多15项产品决策。需求以原始规格为准，整体完成率尚缺完整验收依据。[原始规格](requirements/2026-09-26-tire-intelligence-original.md)
- 用户授权持续实施、复核优化、验证、提交、push及更新交接。专业材料由agent自主选取并核对许可。首个真实模型为OpenAI Responses API，EPREL目前没有Key，继续推进独立工程。
- 本阶段旧共享车库与比较归创建者私有，后续共同编辑历史保留。该归属策略由agent依据现有创建记录制定，接手须保留这一决策来源。
- 新建分支／worktree及代理使用按当前用户授权执行。前序单次Git代理许可绑定相应发布操作，后续网络操作须重新核对授权范围。验证资料使用项目Git忽略目录。

## 本次完成与验证

1. Garage按revision=1创建会话、保存比较按根记录创建会话确定归属，复用036持久owner。列表、总数、分页、详情、编辑、当前轮胎、归档／恢复及离线导出统一过滤本人资料。
2. Web的车库、保存比较及相关窗口复用ready／ownerEpoch／ownerSignal，身份重验销毁旧状态、取消请求并拒绝迟到响应。
3. 新离线车库context和reason使用actor。Web、SDK、共享类型、Rust与Java兼容历史local_workspace包。
4. API 269项、Web68项、桌面JS22项、移动JS24项、Web离线13项通过，全前端类型及Web生产构建通过。16个Parser子进程正常退出并回收。
5. Rust库173项通过、4项默认忽略。实际当前API包和仓库冻结旧包分别跑通生产者原件安装／重开／搜索专项。Android生产Java验证器及依赖闭包编译通过，instrumentation测试仍待构建和设备验证。
6. 正常生产Web浏览器13项、全新非拥有者PG18.3／TLS HTTP 8项通过。旧共同编辑形状的4表6行保留，服务与临时凭据关闭核对通过。原始失败及沙箱复验过程保留在阶段验收中。

当前13个轮胎区域目录、9个厂商品牌、18项可信Parser、179张模型表。数据库版本为036。PG合同为@4，部署时须为目标环境重建批准合同。上阶段账户持久owner、Cookie轮换、报告／AI及通知修复见[账户归属卡](AGENT-HANDOFF-2026-11-15-ACCOUNT-OWNERSHIP.md)。

## 12个模块的当前进度

| 模块 | 当前实现 | 未完成或待验 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、筛选、来源状态、授权回退、13区域目录 | 其余P0来源及地区、长期稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区、冲突与Golden工作台 | 真实代表性SKU、真人Golden、错合并指标 |
| 车型适配 | SU7前后轴、个人Garage、SKU桥及官方PDF | 更多车型、完整OE、Native真实消费 |
| 比较 | 精确SKU、个人保存记录、同场成绩／条件及偏好 | 真实成绩与专业解释、推荐质量 |
| 测评数据库 | TestEvent、环境指标、PDF成绩原件引用 | 真实逐胎精确数值、SKU正例、许可及真人审核 |
| 信息监控 | Worker、差异、NHTSA／Safety Gate／中国召回、通知和任务SSE | 自然长周期、通知lag、更多网页／PDF差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider及费用规划 | 全实体、生产权限、BYOK和真实账单 |
| 证据浏览 | 快照、SHA、Parser、HTML／PDF引用恢复及许可研究PDF | 实际部署库、完整许可治理、生产对象存储 |
| 个性化 | 关注、偏好、兴趣、账户私有Garage与保存比较 | 跨设备真实验收、其余共享实体策略、长期质量 |
| AI研究 | grounding、同步／流式、报告、FTS／向量／融合检索与离线评估 | 真实Responses／Embeddings、语义质量及治理 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key和PG角色 | 公网接收端、生产吞吐、SDK产品化、完整WebSocket |
| 管理后台 | Parser健康、回滚、隔离、失败任务、纠错和审计 | 生产IAM／Tenant／RLS、完整角色与发布验收 |

10项发布Gate仍须逐项核验P0来源provenance、回退授权、Golden错合并、AI引用覆盖、高危AuthZ／SSRF、P0／P1故障、WCAG核心流程、六类平台E2E、Adapter健康与回滚，以及数据库／Parser版本回退。当前合成数据及局部验收各有明确适用范围。

## 下一步

1. 核对HEAD、origin/main、git status及本阶段回执，复用现有main和当前授权继续。接手时读取阶段验收中的失败与未验边界。
2. 复核其余个人及共享实体的产品范围，推进Native真实账户切换、离线owner变化和跨设备E2E。Android新增instrumentation测试优先补构建与设备运行。
3. 从许可原件取得真实逐胎精确数值、测试条件与参测身份，完成精确SKU桥和真人Golden。已保存研究PDF图表的逐胎精确值继续待证。[材料卡](AGENT-HANDOFF-2026-11-14-MATERIAL.md)
4. 配置本机已有凭据后验收真实OpenAI Responses，再验Embeddings网络与语义。EPREL正式资格和API合同仍待外部条件。
5. 推进自然长周期监控、WCAG／读屏／PWA、生产IAM／部署／恢复、SLO及全部发布Gate。旧KIT C2材料沿已封存状态处理，原始失败与不确定状态保留。

主要入口为apps/api/tire_api/garage.py、research.py、offline_evidence.py，Web对应garage.tsx、research.tsx及AuthProvider，离线消费者为offline-values.ts、Rust offline/wire.rs和Android OfflinePackageValidator.java。[实施计划](plans/2026-11-15-personal-garage-comparisons.md)
