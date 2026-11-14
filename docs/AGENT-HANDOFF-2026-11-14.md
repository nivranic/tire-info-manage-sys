# 胎迹 Agent 交接卡

更新于2026-11-14。完整V1持续进行。本文交接需求全貌、已交付能力及PostgreSQL／Parser最新证据，补充真实Web停机自动恢复、Webhook HTTPS取消与自然租约验收。

## 接手基线

- 既有分支为 `main`，活动HTTP／AI流验收已在 `f42e587` 发布，Provider及Parser诊断复核已在 `4a54531` 发布，真实Web恢复记录已在 `285a5f1` 发布，Webhook HTTPS验收已在 `13c4c0e` 发布。本轮短时自动恢复以 `13c4c0e` 为基线。最终交付提交通过 `git log -1` 核对，实时远端通过GitHub核对。
- 用户已授权持续实施、复核优化、总结、提交、push 全部改动和编写交接文档。沿既有分支工作，新分支、worktree 及代理操作须另有明确授权。
- [原始需求](requirements/2026-09-26-tire-intelligence-original.md)保持原字节。[当前入口](AGENT-HANDOFF-CURRENT.md)与[此前阶段总表](AGENT-HANDOFF-2026-11-13.md)保留历史验收范围。
- `.artifacts/`、`data/`、原件、私库、凭据、依赖及构建产物留在 Git 忽略范围。新 clone 需要重建依赖、材料和隔离验收环境。

## 总共有哪些需求

原文按 **12 个核心模块、10 项发布 Gate、13 项 SLO、15 项产品决策**组织，各自独立跟踪。细项存在跨模块依赖，目前没有经逐项验收的整体完成百分比。

| 核心模块 | 已实现或已有验收记录 | 仍需实施或验收 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、来源状态、组合筛选、单次与持续回退授权 | 更多 P0 来源及地区、长期在线稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区身份、冲突、Golden 工作台 | 代表性真实 SKU、人工 Golden、错合并指标 |
| 车型适配 | SU7 前后轴、车库、SKU 证据桥、官方 PDF 链路 | 更多车型、完整 OE 事实、实际 Native 消费 |
| 比较 | 精确 SKU 比较、保存、同场测试和条件偏好 | 专业性能解释、真实推荐质量 |
| 测评数据库 | TestEvent、环境与指标、原件、身份桥、真实原报道隔离验证 | 精确 SKU 正例、正式复用许可、真人审核 |
| 信息监控 | Worker、参数差异、NHTSA、Safety Gate 历史、调度及提醒 | 自然长周期、提醒可靠性、任意网页和 PDF 差异 |
| 传统 CRUD | 来源、规则、偏好、测试、账户、Provider、Key 和费用规划 | 全实体覆盖、生产权限、BYOK、真实账单 |
| 证据浏览 | 快照、哈希、Parser、原件、HTML／PDF 正文、引用恢复 | 部署旧库切换、完整许可治理、生产对象存储 |
| 个性化 | 车库、关注、偏好、保存比较、非 SKU 兴趣 | 跨设备、长期运行、真实推荐质量 |
| AI 研究 | grounding、流式、报告、正文证据包、FTS／向量／融合检索、离线评估 | 真实 Responses 和 Embeddings 语义、代表性质量、模型治理 |
| 对外能力 | REST、SSE、SDK、Webhook、Key、SQLite／PG 受许可事实读取、许可 CLI及运行角色策略 | 实际部署DML权限、吞吐、公网接收端、SDK 产品化、完整 WebSocket |
| 管理后台 | Parser 健康、发布回滚、隔离、失败任务、纠错、审计 | 生产 IAM、租户、RLS、完整角色治理及发布验收 |

此前阶段总表记录了 11 个轮胎区域目录、7 个厂商品牌和 15 项可信 Parser，并包含 NHTSA、EU Safety Gate 及小米车型来源。本轮收尾聚焦数据库角色，没有重新执行全部来源在线验收。

### 发布 Gate 与 SLO

10 项 Gate 分别为 P0 provenance 全覆盖、未授权回退零次、Golden 错合并零次、AI 事实引用全覆盖、无高危 AuthZ／SSRF、无未处理 P0／P1、WCAG 2.2 AA、六平台核心 E2E、Adapter 健康与回滚、数据库与 Parser 版本回退。每项均保留待验部分。

13 项 SLO 为结构化查询 P95≤300ms、设备检索 P95≤200ms、输入反馈≤100ms、移动 LCP≤2.5s、Adapter 开销≤300ms、权威源正常时 live query P95≤3s、按源 5–10s 超时、通知 lag≤5min、后续 99.9% 可用性、RPO≤15min、RTO≤60min、未授权回退零次、Golden 错合并零次。生产级证据仍需逐项建立。

15 项决策涉及轮胎范围、首发地区、知识库定义、完全单机、Offline Pack 大小、用户与 Tenant、VIN、AI 付费、中国区 Provider、价格与库存、专业数据购买、Windows 10 支持期、Native 分发、用户量与 SLA、企业私有部署。用户已明确决定的项目按下节执行，其余继续依据原文和后续决策跟踪。

## 用户决策与历史实现

1. 首个真实 AI 接口采用 **OpenAI Responses API**，配置及工厂的默认值均为 `openai_responses`。真实接入时显式设置 `TI_AI_PROVIDER=openai_responses` 并核对 `/v1/ai/status`。
2. Gemini 源于原规格的多模型备选表，此前 agent 自行提前排期并在 `d5fded1` 实现可选适配器。已有合成测试，真实 Google 调用待验。当前没有用户改选 Gemini 的指令。后续继续依 OpenAI 接入顺序实施。
3. 专业材料由 agent 自行选择和核对来源及许可，用户已授权自行决定选材。
4. 当前没有 EPREL Key，继续推进独立工程。此前记录 OpenAI 模型和 Key 亦缺失，本轮未重新核验凭据，未调用真实模型。不要要求用户把密钥发到聊天。
5. 需求文档中的模型表、版本、价格及技术建议属于需求材料。任务授权和优先顺序依据用户消息，外部事实使用前重新核验。

## 最近已经交付的数据库能力

| 阶段 | 交付提交 | 已留证的范围 |
| --- | --- | --- |
| PostgreSQL 许可治理 CLI | `e0310f6` | 隐藏双密码、SCRAM／TLS、审批与撤回、幂等与审计，40 项受管回归、6 项真实 PG 场景 |
| 非拥有者许可操作员 | `19d0cf0` | 审查 SQL、有效 ACL 检查、越权拒绝，43 项受管回归、9 项真实 PG 场景 |
| 迁移与运行启动分离 | `6d5f4e0` | 显式 verify、源码绑定及空参考合同，141 项受管回归、22 项真实 PG 检查 |
| 升级库列排序兼容 | `3bf187f` | 按逻辑列身份比对、历史 035 升级保留旧行，141 项受管回归、29 项真实 PG 检查 |
| 旧 PG 车型 024 显式维护 | `08e40ff` | 锁内快照备份、ALTER TABLE、独立恢复、旧原件读取，142 项受管回归、17 项维护检查及30项运行合同检查 |

当前合同为 `postgres-runtime-schema@4`，显式保存完整模型空间与维度声明，并与索引catalog对应。它绑定包内Python源码，升级后需要从受控空参考库重新生成、审查并固定合同及摘要。已有数据库的预期结构继续通过空参考库建立。

## 本轮阶段代码

### 已实现

- `apps/api/tire_api/postgres_runtime_roles.py` 固定列出 166 张模型表，生成经过前后检查的事务 GRANT，并提供只读 `check`。按列授予 UPDATE，按既有删除入口授予 DELETE，可选处理 `embedding_vectors`。
- 运行角色可以读取 `external_fact_grant_revisions` 与 `external_fact_license_evidence`，追加许可证据和批准修订的权限继续归既有治理操作员。收尾补充了这两张表的拒绝测试。
- `external_fact_governance_roles.py` 复用既有 catalog 检查，扩展逐列写入、DELETE、可选表和固定锁函数，同时保留治理角色的默认策略。
- `external_fact_sql.py` 安装两个固定、无参数的 SHARE 表锁函数，表名使用 public 限定，固定 search_path，并撤去 PUBLIC EXECUTE。运行角色仅获取审查过的函数执行权。`db.py` 在迁移阶段安装函数。
- `recent_history_acceptance.py` 显式区分拥有者触发器拒绝的 P0001 与运行角色 ACL 拒绝的 42501，检查点保存具体预期错误码。
- `scripts/postgres_acceptance.py --runtime-role` 及 `scripts/verify-postgres.ps1 -Suite runtime-role` 提供正式复现入口。建库、迁移、人工结构实验、扩展安装及恢复由拥有者执行，业务消费改用运行账户与 verify 合同。
- `scripts/postgres_schema_acceptance.py` 改为应用真实运行角色策略，并增加八条越权 DML 拒绝检查。原核心拥有者模式仍有独立验收入口。

### 此前HNSW失败与后续维护

此前真实综合运行角色验收在 `original_text_embedding_pgvector_permissions_and_accounting` 失败。原始PostgreSQL日志报 `must be owner of table embedding_vectors`，触发SQL为按模型空间动态创建HNSW索引。

后续已实现 `postgres_vector_indexes.py`，由拥有者依据显式清单及批准合同维护HNSW。空参考库使用同一清单创建索引，完整声明进入@4合同。verify的ensure_hnsw在外发前和构建后仅读取并核对完整模型空间、维度和实际目录，默认migrate保留本地建索引行为。运行账户的DDL权限继续由原策略拒绝。

最终七模块141项回归及36项PG／TLS专项通过。@4完整运行角色59项通过，包含向量、Parser、备份恢复及恢复后消费。48次Parser观察无失败，原三份超时与OS根因待查状态继续保留。生产权限、IAM／RLS、终端与远端部署继续待验。[本轮验收](assurance/evidence/postgres-vector-indexes-2026-11-14.md)

### 后续权限专项

已补23项真实缺权及ACL／成员／RLS／锁函数漂移反例，并验证部分GRANT后检查回滚、完整重授及幂等。正式PG／TLS专项60项、治理CLI与启动相关受管回归45项通过，842输入稳定。6个一次性集群已关闭，原始装配失败及最小探针保留。生产权限、实际终端和远端部署继续待验。[权限专项记录](assurance/evidence/postgres-runtime-permissions-2026-11-14.md)

### Parser 文件打开取证

54组文件系统样本及16次原入口复验，将主要耗时收敛到Windows新文件打开链路。直接CreateFileW也复现慢打开。16次正常结果和回收均通过，系统目录／项目私槽监督器回执分别3937–4781／2016–2547ms。具体OS归因、原间歇超时和生产尾延迟继续待查。已有TEMP／TMP进程配置及架构诊断环境详见[性能取证](assurance/evidence/parser-file-open-2026-11-14.md)。

### Windows 缺省架构启动修正

原宿主缺少两个Windows架构变量时会在创建子进程前失败，现从bundle环境声明采用的platform.machine派生缺省值。8次真实原入口、当前与修改前封存bundle均通过，最终五模块125项和PG／TLS60项通过，842输入稳定。部署须重建批准@4源码合同，原OS延迟及间歇超时继续待查。接续正常HTTP／Worker部署、实际环境传播及恢复。[启动修正验收](assurance/evidence/parser-host-architecture-2026-11-14.md)

### 独立HTTP与Worker进程

已将 `runtime-process` 接入正式PG wrapper。实际uvicorn HTTP和独立Worker使用非拥有者账户、TLS及空参考@4合同，9项进程检查和55项相关受管回归通过，843输入稳定。核对了架构字段缺省时的HTTP Parser执行、持久规则不可用终态、中断后租约恢复、错误合同拒绝及HTTP重启事件cursor。

独立恢复保持166张模型表逐行摘要、1个原件和197个Parser资产文件摘要一致。原资产目录移入本轮离线槽后，恢复服务从备份目录读取原件、执行封存Parser并继续Worker消费。9个服务进程回收，3个HTTP端口关闭，运行账户后端连接关闭。

材料采用已有录制片段，Worker显式禁用来源，中断采用进程终止，租约到期使用隔离任务时间戳装配。真实来源成功消费、自然租约期限、优雅停机和远端部署继续验收。原始锁装配失败、连接关闭时差及受限硬链接写入失败均保留。[进程验收](assurance/evidence/postgres-process-runtime-2026-11-14.md)

### 真实来源与自然租约

正式入口增加 `-LiveSource -NaturalLease`，使用正常HTTP和独立Worker读取Hankook官方型号／尺寸。最终9项PG／TLS检查通过，4次业务查询均为live，4份Parser完成回执均回收且退出码0。原600秒租约实际观察601.859秒、共61次状态记录，期限一致，到期转为result_unknown后重新消费成功。

独立恢复保持166张模型表、3个原件及197个Parser资产文件摘要一致，恢复后Worker继续在线消费。原录制模式9项及相关回归55／55通过，843输入稳定。三个集群与本轮服务进程已核对关闭。自然长周期真实变化提醒、优雅停机、远端及生产SLO继续验收。[真实进程记录](assurance/evidence/postgres-live-process-2026-11-14.md)

### Windows控制台停机

正式进程入口追加正常API及空闲Worker的隐藏控制台Ctrl+C检查，真实来源和录制模式各11项通过。API完成lifespan清理并退出0；Worker沿既有asyncio取消／KeyboardInterrupt路径退出为Windows的0xC000013A。两项均持有实际服务与启动器句柄，核对进程、指标／HTTP端口及PG后端关闭。

四模块相关回归75／75通过。首批74／75中的旧遥测断言遗漏Safety Gate周期，独立诊断确认4个idle span后修正为4，保留父子trace、无任务和空指标检查。API及进程验收脚本与PG批次一致，最终843输入稳定，原探针及回归失败保留。运行中任务、活动HTTP／AI流、服务管理器及远端继续验收。[停机记录](assurance/evidence/windows-service-shutdown-2026-11-14.md)

### 最新活动Worker取消与重启

基线 `c8b1aac`。正式PG反例证实运行中Worker收到Ctrl+C后，进程已退出而尝试和租约仍占用。现补轮胎、召回和召回发现的取消收尾，四类队列取消时保留原到期时间，复用既有fencing保护后来接手者。八例参数化专项覆盖自身与替换租约。

最终八模块159／159受管回归通过，843输入稳定、资源关闭、非自检拒绝0。真实来源PG／TLS12项、录制模式串行复跑11项通过。第5次尝试在数据库INSERT锁等待期间取消，记录interrupted／worker_cancelled并释放租约；第6次尝试按原到期时间重启成功。共5次真实Hankook业务结果为live，Parser回执均完成回收。两模式分别恢复166张表、197个Parser资产及3／1个原件。

本轮四个集群、20个端口和临时口令／TLS私钥已核对收尾，成功两批25个受管服务及10个实际控制台进程句柄已核对。新API源码SHA-256为 `cbbbb5de20e1a5bec37a8a6843da0f5fdf6e727a906ee62912b7c9640a85a061`，两份新空参考@4合同摘要一致，部署需要重新生成并批准匹配合同。

首轮受限回归122／159、正常权限硬链接对照和最终159项回执分别保留。录制PG首批种子查询为source_fetch_failed，单用户只读诊断取得1条原件及Parser not_started；具体原始异常根因待查，随后同源码串行11项通过。活动网络／AI流、Webhook取消、服务管理器、Linux信号、远端与长周期继续验收。[活动Worker验收与原始失败](assurance/evidence/active-worker-shutdown-2026-11-14.md)

### 最新活动HTTP／AI流与Webhook取消恢复

基线 `6f866a3`。正式进程入口在正常create_app／lifespan上注入合成Responses生产任务，实际HTTP/SSE客户端保持订阅，2秒停机宽限到期后取消活动请求。AI任务关闭并写入持久outcome_unknown／ai_stream_interrupted，预算保守计入，重启后原cursor取得终态，原UUID重放的Provider调用为0。

最终七模块220项受管回归、真实来源13项／录制12项PG／TLS通过，843输入稳定。三个本轮集群、18个端口及临时秘密已核对，成功两批29个服务记录、18个实际控制台进程句柄已核对。当前API源码摘要及@4合同与上节匹配，部署按既有匹配合同工作流执行。

新增两种Webhook发送取消恢复用例，覆盖未知结果、原租约、退避、旧token和用户取消状态。旧022当前形状夹具的12个FTS关系遗漏已据实补齐，首批218／220与探针保留。真实来源首批upstream_timeout后等待30秒，同源码正式复跑13项通过。此前录制source_fetch_failed的具体原异常待查，验收现补安全异常类型／栈记录。

本轮模型端采用合成实现。实际OpenAI网络、真实Web界面断线恢复、Webhook网络／自然租约、默认及其他宽限配置、服务管理器、Linux与远端继续验收。[活动HTTP／AI流验收](assurance/evidence/active-http-ai-shutdown-2026-11-14.md)

### Provider复核与浏览器交接收尾

配置、适配器工厂及状态入口的默认Provider均已复核为OpenAI Responses。当前执行环境未设置 `TI_AI_PROVIDER`，同时提供两种合成凭据时默认仍选择OpenAI。Gemini由此前agent依据原规格备选表提前实现，接入顺序继续按用户选择执行。

新增Parser诊断将固定错误码及六个回执字段写入已有安全报告，5项新增专项与既有AI／Parser回归合计75项通过，843输入稳定、资源关闭。沙箱首批67／75，8项既有测试的硬链接发布被WinError5拒绝，已保存原始取证及普通权限同入口75／75对照。

此前两批浏览器恢复尝试均已记录失败。第一批在录制种子查询取得ParserRunError，具体错误码仍待复现。第二批11项PG前置检查通过，生产页面已连接，私有驱动误用另一合成口令导致登录401，AI请求尚未开始。两批服务、PG、三个端口及临时秘密均已核对收尾。后续在下节记录新私槽的页面停机恢复结果。[前置失败复核](assurance/evidence/provider-handoff-review-2026-11-14.md)

### 真实Web停机恢复后续验收

以 `4a54531` 为基线修正私有驱动凭据装配后，正常登录、历史证据选择、明确外发同意及分析POST202通过。页面取得1条草稿和活动SSE，API经2秒宽限停机后草稿隐藏。较长停机后通过重新读取进度恢复原请求的持久outcome_unknown／ai_stream_interrupted，保留47,433 tokens预算且pending=false，重启Provider调用0次。

刷新并重新打开AI窗口后继续只读恢复同一请求，cursor序号1推进至4，新增分析POST为0。390、768及1440三种视口无横向溢出。PG进程12项检查通过，843输入匹配既有75项回归，422项构建输入匹配。14个服务记录、8个端口、PG及临时秘密已核对收尾，独立浏览器context已关闭。模型端为合成Responses，短断线自动恢复、真实模型网络及Native设备继续验收。[Web停机恢复记录](assurance/evidence/web-ai-stream-recovery-2026-11-14.md)

### Webhook实际HTTPS与自然租约

实际API事务产生通知及outbox，独立Worker沿原webhooks-once入口经WebhookTransport发送至本机TLS接收端。验收进程注入精确loopback目标与测试CA，原生产URL检查在注入前拒绝该地址。接收端共收到3次TLS1.3请求，独立HMAC及引用正文核对全部通过。

两次Worker Ctrl+C后连接关闭，原30秒租约自然到期后写入unknown。普通投递继续自然经历60秒退避，以相同delivery ID／正文完成attempt2及204；旧token无法释放新slot。用户先取消的投递保持cancelled，后续Worker未再发送。142项受管回归、12项PG进程检查通过，843输入稳定，20个服务记录、8个端口、PG与临时秘密已核对。回执核验器跨时钟严格比较的误断言已据原始UTC及单调时钟样本修正，差异保留。公网DNS、接收端部署及通知生产SLO继续待验。[HTTPS与自然租约记录](assurance/evidence/webhook-https-recovery-2026-11-14.md)

### 原页面短时中断自动恢复

以已发布 `13c4c0e` 为基线完成。正常页面发起1次分析并显示草稿，API以2秒宽限停机，退出后自然等待2秒并同库重启。原页面在断线后清除草稿，自动GET依次500、500、200，7.107秒后读回同一请求的持久outcome_unknown／ai_stream_interrupted。全部保存样本保持visible，手动读取0次，恢复期间新增分析POST及重启Provider调用均为0。

预算保留47,444 tokens且pending=false，answer／usage为空，terminal=true、projection_only=false。PG进程12项和Web单元59项通过，843公共输入、422构建输入匹配。14个服务记录、18个进程ID、8个端口及临时秘密已核对，独立浏览器context已关闭。模型端采用合成Responses，真实OpenAI网络、其他停机配置和设备继续待验。[短时自动恢复记录](assurance/evidence/web-ai-short-outage-2026-11-14.md)

## 运行角色阶段验证

此前运行角色阶段七模块受管回归124／124通过，841输入稳定、资源关闭、非自检拒绝0。真实PG／TLS结构与权限检查31项、拥有者核心兼容58项、旧许可操作员兼容9场景均通过。该阶段运行角色综合验收前37项后遇到HNSW失败，后续由上述显式维护处理。

该阶段六个隔离集群已停止，临时口令、TLS私钥及端口已核对。完整范围、SHA-256和原始红批见[运行角色阶段验收记录](assurance/evidence/postgres-runtime-role-2026-11-14.md)。后续索引维护操作见[HNSW维护说明](POSTGRES-VECTOR-INDEXES.md)。

## 接手顺序

1. 核对 `main`、HEAD、工作区和实时远端，读取本文、原规格、运行角色阶段验收、[运行 schema 方案](POSTGRES-RUNTIME-SCHEMA.md)与[024 维护说明](POSTGRES-VEHICLE-MIGRATION.md)。复用已有证据，先取新失败的 SQLSTATE、调用入口和日志。
2. 复用已通过的23项运行角色反例及部分GRANT回滚检查，依据新失败补充专项。HNSW维护采用显式清单与@4合同，运行角色使用已审查DML策略。接续推进Parser性能取证、实际终端及远端部署。
3. 复用本机Webhook HTTPS取消／自然30秒租约／60秒退避、真实Web长停机手动／刷新恢复与短停机自动恢复、活动HTTP／AI流及此前Worker证据，继续实际OpenAI网络、公网Webhook DNS／TLS及接收端部署、通知生产SLO、其他停机宽限、服务管理器、Linux信号、自然长周期变化、多规则提醒和远端部署。录制source_fetch_failed已取得ParserRunError，具体错误码与根因按新增诊断继续定位。OS打开链路继续按54组文件系统及16次原入口取证定位，监督器采用8秒期限，原始失败和生产尾延迟独立跟踪。[最新Web自动恢复](assurance/evidence/web-ai-short-outage-2026-11-14.md)
4. 完善部署操作说明，验证实际终端、远端角色、对象／Parser 全资产恢复，再推进 IAM／RLS、吞吐及灾备指标。
5. 凭据齐备时，先执行真实 OpenAI Responses 和 Embeddings 的 API、外发同意、Provider、引用恢复和 Web 语义验收。无凭据期间推进独立工程。
6. 继续真实精确 SKU、人工 Golden、专业材料正式许可、更多来源与车型、自然长周期监控、实际 Native 宿主与设备、无障碍和其余发布 Gate。

### 复跑入口

使用 PowerShell 7，所有输出使用全新 Git 忽略槽。runtime-schema专项要求现有PostgreSQL运行时已安装pgvector，执行期间保持受测源码稳定。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_text_embeddings.py apps/api/tests/test_embeddings.py apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_safety_gate_external_governance.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-role
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite core
```

标准wrapper使用项目既有uv工作流，并将TEMP／TMP／TMPDIR设为每批私有目录，结束时恢复进程原值。本轮私有wrapper仅改仓库定位、使用已安装Python，保留完整正式验收入口和参数。

## 证据与封存状态

- KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 继续封存，继承状态 `processing_unconfirmed`。后续不重 POST、不重开私槽、不换 UUID 抓取。
- `stopped_unconfirmed` 表示停止后续采纳且网络结果未知，来源材料和抓取状态按已有记录解释。
- `docs/HANDOFF.md` 自 `## 当前交接入口（2026-10-26）` 起保留封存历史尾文。本机原字节 SHA-256 为 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`，Git LF blob 的 SHA-256 为 `55e7f298d159af75eefa0bb4230a9f1193b2938223e51cf2a41c1f9c79d43bab`。
- 阶段回执中的 Mock、合成材料、ASGI TestClient 和真实 PG 范围分别保留。生产权限、真实模型、真实材料许可及设备验收按对应证据推进。

## 可复制的接手指令

> 继续实施胎迹完整V1。先读docs/AGENT-HANDOFF-2026-11-14.md、原规格和docs/assurance/evidence/web-ai-short-outage-2026-11-14.md，核对main、HEAD、工作区与实时远端。本次以13c4c0e为基线，PG进程12项、Web单元59项通过，843公共输入及422构建输入匹配。实际生产Web短时中断后自动读回同一持久终态，手动读取与恢复期间新增分析POST均为0，预算保留47,444 tokens，重启合成Provider调用0次。14个服务记录、18个进程ID、8个端口及临时秘密已核对。复用此前长停机手动／刷新恢复、本机Webhook HTTPS／自然30秒租约／60秒退避、权限反例和PG独立恢复证据。首个真实AI依用户选择采用OpenAI Responses，Gemini由此前agent提前实现为可选适配器。真实模型网络与语义仍待验，缺凭据时推进独立工程。接续公网Webhook及生产SLO、其他停机配置、Linux／服务管理器／远端部署、长期真实变化、ParserRunError错误码和Windows间歇延迟、精确SKU／人工Golden／专业许可／Native／无障碍。12模块、10Gate、13SLO、15决策分别跟踪。保留KIT C2与历史封存，沿main和PowerShell7工作，分支／worktree及代理遵循既有授权边界。每次发布后核对实时远端SHA与工作区。
