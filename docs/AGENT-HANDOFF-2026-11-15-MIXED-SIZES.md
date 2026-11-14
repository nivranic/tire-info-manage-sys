# 胎迹 Agent 交接卡

更新于2026-11-15。本阶段基线为已发布的fe63c73，沿现有main实施。完整V1目标继续进行。需求、验证与发布记录分别见[原始规格](requirements/2026-09-26-tire-intelligence-original.md)、[本阶段验收](assurance/evidence/mixed-test-sizes-2026-11-15.md)及项目Git忽略目录中的发布回执。

## 需求范围与已确定决定

- 原规格包含12个核心模块、10项发布Gate、13项SLO及15项待确认决策。各维度分别验收，整体完成率缺少完整验收依据。
- 用户授权持续实施、复核优化、验证、提交、push及交接。专业材料由agent自主选择和核对许可。首个真实模型使用OpenAI Responses API。EPREL目前没有Key，继续推进独立工程。
- 沿既有main工作。新建分支、worktree及代理使用须核对用户当次明确授权。PowerShell使用7。验证资料置于项目Git忽略目录。
- 前阶段已实现账户持久归属、登录与退出轮换、个人Garage和保存比较。旧共享记录归创建者私有，后续编辑历史保留。该归属策略由agent根据不可变创建记录制定。[个人资料交接](AGENT-HANDOFF-2026-11-15-PERSONAL-RECORDS.md)

## 本阶段交付

1. TestEvent支持逐参测胎tested_size。共同尺寸沿原合同保存，混合尺寸以场次tested_size为null表示，要求全部参测胎填写尺寸并包含至少两种尺寸。显式逐胎尺寸与共同尺寸冲突时拒绝保存。
2. 缺省逐胎尺寸序列化时省略。旧共同尺寸记录及指纹、历史修订和冻结离线包已复验。
3. SKU桥核对所选参测胎尺寸，关注匹配使用同一规则。FTS增加品牌／型号／尺寸的逐胎关联分面，派生索引从accepted-heads-fts@6升级到@7并按需重建。
4. Web正常录入、修订、详情、比较、偏好、候选和SKU复核显示混合尺寸及逐胎尺寸。比较附带尺寸差异说明，保留原数值和来源名次。
5. 离线导出按逐参测胎生成尺寸分面。Web、Rust和Android校验分面与对应参测胎的品牌、型号和尺寸，增加重新计算包摘要后的篡改反例。
6. 独立专业Golden字面量支持混合尺寸形状。补充检查定位并更新两项旧测试的036会话归属预期和正文FTS夹具。

数据库迁移仍为036。最新隔离PG合同为postgres-runtime-schema@4，部署目标须根据自身catalog和当前API源码重建批准合同。旧版客户端消费新混合尺寸包的兼容性仍待验。

## 实际验证

最终21模块受管回归532项通过、54项条件跳过，867个绑定输入稳定，23个子进程全部exit 0并回收。Web68项、桌面JS22项、移动JS24项、Web离线14项和Rust174项通过，Rust4项默认忽略。全前端类型检查、Web生产构建及Android生产Java依赖闭包编译通过。

正常生产浏览器9项、独立非拥有者PG18.3／TLS HTTP8项通过。当前API混合尺寸四领域离线包8项HTTP检查通过，5个member、9个document、81,001字节。Web消费和Rust原件安装／重开／搜索通过，Rust另复验冻结旧包。正常AI证据包与Markdown／HTML／PDF报告导出6项通过，真实Provider调用为0。

专业Golden全套观察器在验证历史R74私有材料时遇到原件缺失。54项依赖该观察目录的用例保持条件跳过，原始失败记录保留。资源审计核对5条服务记录、7个进程ID和6个端口关闭，以及临时口令和TLS私钥清理。Android instrumentation构建及设备执行、Native宿主与真实模型继续待验。

## 12个模块的当前进度

| 模块 | 当前实现 | 主要余项 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、组合筛选、来源状态、授权回退，已发布基线覆盖13个区域目录 | 其余P0来源和地区、长期稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区、冲突、Golden及SKU证据桥 | 代表性真实SKU、真人Golden、错合并指标 |
| 车型适配 | SU7前后轴、个人Garage、官方PDF和SKU桥 | 更多车型、完整OE事实、Native真实消费 |
| 比较 | 精确SKU、个人保存、同场共同／混合尺寸、条件与偏好解读 | 真实专业成绩、推荐质量 |
| 测评数据库 | TestEvent、环境指标、PDF成绩区间与逐胎尺寸 | 真实逐胎精确值、SKU正例、真人审核 |
| 信息监控 | Worker、参数差异、NHTSA／Safety Gate／中国召回、通知和任务SSE | 自然长周期、通知lag、更多网页／PDF差异 |
| CRUD | 来源、规则、偏好、测试、账户、Provider及费用规划 | 全实体、生产权限、BYOK和真实账单 |
| 证据浏览 | 快照、SHA、Parser、HTML／PDF引用恢复、已保存许可研究PDF | 实际部署库、完整许可治理、生产对象存储 |
| 个性化 | 关注、偏好、兴趣、账户私有Garage和保存比较 | 跨设备真实验收、其余共享实体策略、长期质量 |
| AI研究 | grounding、同步／流式、报告、FTS／向量／融合检索及离线评估 | 真实Responses／Embeddings、检索语义质量和治理 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、PG角色及受许可读取 | 公网接收端、生产吞吐、SDK产品化、完整WebSocket |
| 管理后台 | Parser健康、回滚、隔离、失败任务、纠错和审计 | 生产IAM／Tenant／RLS、完整角色和发布验收 |

已发布基线另记载9个厂商品牌、18项可信Parser、179张模型表。本阶段增加混合尺寸合同与检索关联。

10项发布Gate继续逐项核验来源provenance、回退授权、Golden错合并、AI引用覆盖、高危AuthZ／SSRF、P0／P1故障、WCAG核心流程、六类平台E2E、Adapter健康与回滚，以及数据库／Parser版本回退。13项SLO仍需实际部署和负载证据。

## 真实专业材料进度

选定《Tyre rolling resistance and its influence on fuel consumption》，DOI 10.19206/CE-2017-110，Combustion Engines 2017,168(1),62–67。前序核对出版方CC BY 4.0及开放下载说明，许可观察记录保留在私有捕获槽。[出版页](https://www.combustion-engines.eu/Tyre-rolling-resistance-and-its-influence-on-fuel-consumption,116799,0,2.html) [版权页](https://www.combustion-engines.eu/Copyright,6171.html) [开放获取条款](https://www.combustion-engines.eu/Open-Access-Policy,6168.html)

正常PDF路由两次返回200及2,413,872字节声明长度，下载均在既有45秒总期限内超时。另一路由返回32,084,170字节并按8MiB限制拒绝。完整论文原件、22条计划选录成绩及其PDF区间绑定仍待完成。[PDF路由](https://www.combustion-engines.eu/pdf-116799-46024)

## 接手顺序

1. 核对git status、HEAD、origin/main、本阶段验收及发布回执。读取原始失败和条件跳过范围，按当前明确授权继续。
2. 处理真实PDF下载期限。依据已保存的200响应和下载时间线，设计有界捕获期限并验证旧策略指纹、取消、客户端超时和资源关闭，然后通过正常捕获入口取得完整原件。
3. 复核PDF页码、码点引用、表1身份、表2数值和方法。计划选录明确支持的公制乘用车尺寸，保留原始4胎参测总数及selected_results。195R14C等原文规格需保留原样并单独评估支持范围。Concrete block路面原文为50km/h，其余相关行80km/h，指标条件逐项核对。
4. 原件完成后录入22条选录值，验收比较、FTS、关注、离线、AI和报告。精确SKU及真人Golden继续单列。PDF引用进入独立Golden字面量合同仍需正常入口复现，MeasurementLiteral目前缺少pdf_reference字段。
5. 补齐历史R74原件和捕获／核对记录后再生成完整专业Golden观察目录，执行条件跳过用例。恢复材料须与冻结清单的摘要和字节数一致。
6. 推进Android instrumentation构建／设备运行、Native账户切换及跨设备E2E。真实OpenAI Responses、Embeddings、EPREL、自然长周期、WCAG、生产部署／恢复及SLO继续按条件验收。

## 主要入口

- API位于apps/api/tire_api/test_events.py、test_sku_links.py、interest_matching.py、knowledge.py、knowledge_index.py、offline_evidence.py和professional_golden_checks.py。
- Web位于apps/web/components/test-event-editor.tsx、test-events.tsx及相关偏好、候选和SKU窗口。共享合同位于packages/domain-types/src/index.ts。
- 离线消费者位于Web的offline-values.ts、Rust的offline/wire.rs和Android的OfflinePackageValidator.java。专项回归入口为scripts/offline_frontend_qa.mjs及受管API回归脚本。
- 需求与阶段实施顺序见[本阶段计划](plans/2026-11-15-mixed-test-sizes.md)。旧KIT C2继续沿封存状态及原始失败记录处理。
