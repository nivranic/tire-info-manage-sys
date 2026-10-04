# 胎迹 · 轮胎情报工作台

以精确轮胎 SKU、官方在线查询、可追溯证据和用户授权的离线回退为基础，逐步实现跨平台轮胎情报系统。

**当前状态：领域与数据 PoC 迭代版本。实际停点为第49轮四域设备历史查询与持续策略（未收尾）和第50轮设备保存证据的 AI 桥接基础模块（仅三个内部核心，整链未实现）；第48轮三端持续授权与历史包条件更新、第47轮普通轮胎查询的一次设备历史授权和第46轮三端手动离线包均为已封存的阶段验收历史。** 当前为 **8 个轮胎参数来源、4 个厂商品牌 + 1 个 NHTSA 召回来源**；另有独立小米车型来源，完整 Parser 目录为 10 源——这不是原规格全部 P0 来源完成，EPREL 仍为待配置入口、未接入。Pirelli 美国 P ZERO (PZ4) 的 20/21 寸真实响应包含 11 个精确 SKU，产品代码、GTIN、R/ZR、OE、PNCS/ELECT 与防爆语义分别保留；型号营销和尺寸导航不替代 SKU 事实。28 字段、最多 16 项 AND 筛选仍仅覆盖已接入型号。

第49轮四域（普通轮胎＋高级筛选、车型适配、正式召回公告、召回发现候选页）设备历史查询与持续策略**未收尾**：正常库 011 迁移未执行，正常服务重启、旧行保全与唯一 after49 收尾未完成；最新前端的 Windows 证据只有 build-c 编译与最终 JS/CSS 嵌入校验（未签名 dev EXE 24,451,072 字节，SHA `720c23140cd96bda06fba0ffadb6042793bf842d335d8dffbd8a0e34f47f6584`），最新前端的打包运行未验收，旧 14 项真实 Tauri/Keyring/IPC 验证只绑定旧前端资产、仅为历史局部证据；Android 最新主/测试 APK（build-b）仅构建通过，最新 Store/IPC/Keystore 运行未验收，旧 72 项仪器结果不能证明当前 49 源码通过；旧测试 cleanup 补丁（保留合成 QA 资料/Keystore 别名并跳过两个销毁凭据测试）被自动审批拒绝、未应用，`OfflinePackStoreTest`、`OfflineCipherTest`、`OfflineSyncPolicyTest` 在该授权问题处理前不得直接运行，也不得以复制、overlay、改名或超时默认同意绕过；`continuous_policies=false` 保持，不得提前启用。Web 侧 Chrome/IndexedDB **40/40**、Node **58/58**、专项 8/8、SDK 5/5 为已封存历史结果，不替代原生运行或真实上游/模型验收。

第50轮设备保存证据的 AI 桥接只有三个内部模块，测试数字均为已封存历史结果：`device_ai_projection.py`（**97/97**）、`device_ai_models.py`（**56/56**＝47 模型＋9 既有迁移回归）、`device_ai_archive.py`（**92/92**）。共享 DTO 草案 b 仍为 draft，wire 未冻结、未导入产品协议；未注册 device API endpoint、未在 `Database.initialize` 注册新模型、未注册/执行 012 迁移、未接任何 Host 或真实 Provider；共享 runtime decoder → Host 本机预览 → 导出同意 → owned prepare/gate → Provider 同意 → SSE grounding → 精确引用重开的整链全部未实现。DTO 草案 a 曾被交错任务误改，其 TS 已恢复原 SHA，但 a-verification 原始 JSON 无法恢复，不得写成原样封存。

2026-10-02 交接核验时本机 3000/8000 均未监听，当前没有服务在运行，旧报告中的正常服务运行状态不可沿用。该次交接只做只读盘点、回执核对与文档同步，未运行产品测试、迁移、浏览器或设备；详细停点、授权边界与接手顺序见[交接手册](docs/HANDOFF.md)，第49/50轮回执目录为 `.artifacts/query-fallback49/` 与 `.artifacts/device-ai50/`。

第48轮新增历史包条件prepare：完整语义没有变化时不生成Plan/Pack/object，变化时复用原冻结计划与确认。同步专用请求在API入口固定归属，缺失/过期会话不自动建立新会话。持续授权、手动安装和单次历史查询分别保存；Web仅页面打开期间调度，不能可靠检测的Wi-Fi/充电条件明确不支持。Windows由Rust在应用打开期间独立调度，关闭后的OS任务仍不支持；Android使用WorkManager与应用共用会话/离线runtime，Activity销毁不会关闭任务authority，force-stop不保证继续执行。外接电源与实际充电分别判断，多个条件全AND，未知阻断。重启或prepare/confirm响应未知时保留旧包并暂停，不盲重放；宿主或validator版本变化逐包完整检查，旧归属密文也检查但不解锁。

当前阶段证据：API104项目标测试通过；旧全套1989通过/41失败/1错误中的41失败节点在修复测试fixture后的48项定向回归和最终完整重跑中全部通过。完整重跑真实终态为2030通过/1失败/0错误（另77 subtests），剩余telemetry fixture修正后5项定向测试通过；产品源码哈希相同，没有再次完整重跑，不能改写成全套2031通过。前端目标14项、相邻49项、真实Chromium生产13项分别通过；三端前端类型/构建通过。Rust72通过/0失败/3跳过，Windows真实Tauri/OS凭据库19项通过，包含禁用JS后的首次到期调度；其HTTP为合成transport。Android最终API34独立应用75项通过，覆盖Keystore、FTS5、真实WorkManager两策略、撤销、双钟到期、加密保存后条件变化回滚及真实producer完整预览契约。真实设备暴露的Python日期+00:00解析已修复，最新APK绑定52项源/配置/测试和最终前端资源；当前APK真实FastAPI原生IPC的9个唯一阶段通过，包含原子更新、no_change、撤销、重载、未知prepare/confirm强停重启、旧归属授权拒绝及UI。正常开发3000→8000两宽页面与离线入口只读验收通过，API写/外联/page errors为0。上述结果不等于完整平台、真实来源或模型质量验收。

第48轮唯一after快照26,181,632字节，107表结构与全部旧行保留；仅正常只读浏览器增加1个会话（130→131），其他106表完全不变，391封存文件逐SHA相同、objects0。仅停止验收进程和精确转发，QA资料/凭据保留（"正常3000/8000保持运行"为第48轮当时终态；2026-10-02 交接核验时 3000/8000 已无监听，不可沿用）；未提交、推送或发布。

第47轮固定本次查询后，仅对明确的网络/超时失败提供独立设备授权。未答与拒绝不解密包内参数；用户选择一份当前归属包后，五分钟内单次消费，核对完整查询、profile/归属代次、包版本及SHA。重载、重启、查询/已观察许可变化、删除替换与归属重置都会使旧授权失效，同一attempt不能重复创建授权。三端各保存最多64条加密审计，pending16、当前host最多1024个决定且不淘汰旧attempt。结果是所选包的精确历史子集，原参数与整包跨来源字段上下文分别展示，不进入在线比较、关注、报告或AI。

本阶段仅普通轮胎查询、无高级筛选、精确来源/型号/尺寸、单个当前归属包。R/ZR不合并，旧归属即使解锁也不能回退；HTTP403/通用5xx、取消、无目录冷启动和来源权限失败不产生授权。API断线只保留本进程此前成功取得的来源信息，不声称验证了当前服务器许可。Node10、Rust9加2相邻回归、Android实际36项分别通过；Chrome完整10组流程/15组宿主边界与最终6组专项分开记录。Windows OS凭据库/WebView2、Android Keystore/WebView原生单次消费、真实重载及进程重启通过；最终d三端构建、类型/PWA与正常只读6图通过。合成API与原生IPC证据不替代真实上游失败或模型质量验收。

正常107表结构和全部旧行保留，本轮无DDL；仅会话129→130、audit123不变，391封存包逐SHA及objects0不变。唯一after为26,181,632字节，详细源码版本、验收边界和剩余范围见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第46轮新增独立冻结离线包和010迁移。先预览Garage、当前会话关注项、最近正式查询及精确证据引用，再明确授权保存到设备；三端核对同一原始JSON字节、长度和SHA。Windows/Android用独立系统密钥加密原包与元数据，SQLite/FTS5索引在内存；PWA用WebCrypto非导出密钥加密IndexedDB，不把浏览器存储称为系统凭据库。断网可主动读历史，手动更新按本机版本原子替换；删除保留版本墓碑，重置会锁定旧私人资料，单独解锁后仍显示旧归属。历史资料不会自动回填在线查询或AI。

本机限制为每包8MiB、200份不同证据、50个Garage档案、100个关注项、4000个搜索文档，已装原字节共32MiB、最多16个活动包。超数量范围明确413；数量合规但字节超限仍返回完整不可确认预览，不裁剪事实。独立审查修复了同快照多回执候选冲突及字段重复复制导致的内存峰值；最终后端相关71项通过，20/190引用压力测试另列。真实PG20引用逻辑包10,373,741字节，正确阻断确认，Python峰值11,208,028字节。

PWA生产浏览器11组/4处几何检查、390px在线入口专项、Android API34实际25项离线测试及8项既有安全回归通过；Windows真实凭据库/WebView2与Android Keystore/WebView均完成原生安装、FTS检索、进程重启、实际API关闭后的冷启动和归属重置验证。三端类型/构建及正常3000→8000只读6图通过。PG18.3完整迁移/并发/恢复9组属于P1版本，最终P2另有3组资源与冻结复验，分别保留证据。正常库105旧表和旧行保留，仅新增两张空离线表；会话126→129、审计123不变，391封存包和对象0文件不变，唯一after为26,181,632字节。

Windows关闭应用后的后台更新、长期周期/物理条件/设备矩阵、高级筛选/车型/召回/AI设备回退、macOS/iOS/其它Android设备、真实OpenAI质量及其余原需求仍待落实，完整Goal保持active。原生离线设备证明与合成来源业务证明分别记录，未提交、推送或发布。最新证据和边界见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第45轮将正式 NHTSA 公告及明确的空查询观察接入 Knowledge、Evidence Pack、同步/流式 AI 和三格式报告。品牌、型号在同一产品记录匹配，分析选择整份公告；Snapshot、语义 Revision 与本次 Verification 分别冻结。同内容的新原文快照可引用原修订，最新空观察不会刷新旧公告内容时间。当前查询先在线核验，失败时只有一次授权才能回退；空在线响应不带入旧摘要。含召回的整包采用 `recall-fact-selection@1`，只选择有引用的事实，独立拒绝推断、自由文字和模型不确定性；各处展示 `not_assessed`，不推断具体轮胎安全或适用性。

第45轮核心召回边界21项、原相邻回归67项分别通过；AI/报告相关回归195项、最终策略修复后消费者52项分别通过，不累加为一套测试。目标前端6项、私有HTTP7组、主浏览器4组/6处布局及最终卡片1组/2处布局通过。独立审查复现并修复了旧报告导出依赖活动策略的问题：归档按冻结版本校验，策略升级后导出字节不变。PG18.3的7组检查、2个真实writer通过，98注册表/869列四阶段值一致，完整schema另核对99表；22表非空、76表为空。10个明确枚举约束的恢复反解析差异经67个输入及实际非法UPDATE验证等价，其他schema逐项一致。

第45轮全工作区类型检查、Web/桌面前端/移动前端构建和正常3000→8000只读浏览器检查通过；桌面/移动JS为871.80/884.02 kB，保留500 kB chunk提示。本轮无DDL，105表schema与全部旧行、派生Knowledge、92 SKU/95事实/13快照/1关注、83绑定/1迁移回执和391包文件保留；会话123→126，审计122→123仅新增`recall_history_read`，唯一after为26,136,576字节。正常AI/召回/报告/任务业务表仍空，AI/Embeddings关闭，私有资源已清理。合成来源和Provider不替代真实OpenAI、官网新查询或设备验收；完整Goal仍active。详细证据与剩余范围见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第44轮使用独立受理、持久事件和Web SSE／原生REST读取，逐条展示引用核对后的临时草稿；完整回答最终校验并提交后才可保存含分析报告。丢响应、断线、关窗和刷新沿原UUID读取，不自动再次调用模型。核心与API/迁移相关组分别157项、72项通过；前端专项18项、相关26项通过；私有合成HTTP7组、完整浏览器6组/9处布局及中文提示2项复验通过。PG18.3的6个独立writer和7组检查通过，98表/869列四阶段值指纹一致，其中17表非空、81表为空；这些均不替代真实OpenAI连通、模型质量或原生设备验收。

第44轮全工作区类型检查、Web/桌面前端/移动前端构建及正常3000→8000只读检查通过；桌面/移动JS为863.12/875.34 kB，保留chunk提示。迁移009仅增加两张空表，103张旧表结构/旧行、92 SKU/95事实/13快照/1关注、83绑定/1迁移回执及391包文件保留，审计仍122；唯一after备份26,136,576字节。API/Web已恢复、私有资源清理，AI/Embeddings关闭，完整Goal仍active。详细证据与剩余范围见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第43轮名称发现规则默认暂停，从第一页进行有界双遍核对；首个完整扫描静默建立基线，之后只提醒该任务首次观察到的公告候选。未完成扫描保留逐页证据而不推进基线；候选选择仅填入公告编号，须明确核验。后端执行/API/后续约束组分别170/50/29项通过，组间存在重叠；私有合成HTTP8项、浏览器7场景、前端七组69项通过。PG18.3的6个独立writer与10项检查通过，96表/858列及对象恢复一致。这些结果不代表全球召回覆盖或真实官网连续监控已经验收。

第43轮全工作区类型检查及三端前端构建通过；正常截图发现的390px手机标题挤压已修复，私有浏览器实测从6行恢复为1行、桌面坐标不变，并再次完成三端构建。桌面/移动JS为844.78/857.00 kB，仍保留chunk提示。正常3000→8000只读检查通过，迁移008仅追加9张空表，94张旧表及旧行保留；92 SKU/95事实/13快照/1关注、83绑定/1迁移回执、391包文件不变，备份26,107,904字节。API/Web已恢复、私有验收已清理，AI/Embeddings关闭；本轮未新增真实来源、模型或原生设备验收。完整Goal仍active，证据和剩余边界见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第42轮为轮胎与召回规则队列增加持久执行历史、真实阶段和只读任务中心。Web已在真实浏览器验证约25秒流窗口、心跳、断流恢复和游标续接；原生使用同游标REST轮询，已验证JavaScript传输。后端目标组分别58项、150项通过，私有HTTP6项、浏览器7项场景/7处布局、Node六组61项通过；PG18.3的10个独立writer验证竞争及旧执行隔离，87表/767列和对象恢复一致。全工作区类型检查及三端前端构建通过，桌面/移动JS为811.31/823.53 kB，仍保留chunk提示；本轮没有新增原生设备、真实官网或模型验收。

正常3000→8000只读验收通过，任务总数仍0，没有自动创建或运行规则。迁移007仅新增两张空表，原92表schema及旧列旧行保留；92 SKU/95事实/13快照/1关注、83绑定/1迁移回执和391包文件不变。会话114→117，审计118→120仅两条隔离列表读取；备份25,911,296字节，来源管理修订仍0，旧请求pin仍NULL，AI/Embeddings关闭。API/Web已恢复，验证进程/端口已清理。阶段性通过不代表完整需求或发布Gate完成，完整Goal仍active；详情见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第41轮管理目录含11项（另含待配置EPREL），支持预览、固定UUID提交恢复与追加历史；四条查询服务、授权回退、Worker和AI当前证据采纳共同核对来源访问代次。两组后端测试分别33项、215项通过（后者8项排除），私有HTTP6项、最终浏览器6项UI/3项HTTP通过；PG18.3以6个真实writer进程验证竞争和重放，并核对85表/747列与对象恢复。一次保存韩泰原文的真实受限Parser在3.8秒正常退出，暂停后只留原文/回执、未采纳事实。合成来源、历史原文回放和正常只读证据分别记录，没有新增官网或真实模型验收。

第41轮全工作区类型检查及Web/桌面前端/移动前端构建通过；来源管理、桌面、移动、PWA、共享原生传输Node组分别8/14/13/8/6项通过。桌面/移动JS为790.14/802.39 kB，仍有500 kB chunk提示，不代表原生设备或性能达标。正常3000→8000浏览器只读验收通过，11来源均保持默认enabled/revision0/generation0，未写管理修订。迁移006仅追加一表一nullable列，23个旧请求pin仍NULL；原91表旧列旧行、92 SKU/95事实/13快照/1关注、83绑定/1迁移回执及391包文件保留。会话111→114，审计116→118仅两条隔离列表读取，备份25,862,144字节；AI/Embeddings关闭。API/Web已恢复、私有进程和端口已清理，详细证据见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。完整Goal仍active，生产管理员认证、更多来源、真实模型与原生设备等边界继续独立验收。

第40轮补核了其他P0品牌的公开访问与数据合同，但未取得可采纳的逐SKU响应，因此来源数量保持。同期修复轮胎canary混入召回源、重核验失败仍退出成功的问题；13项离线测试及实际CLI拒绝路径通过。这些证据不等于新增官网Adapter或真实canary通过，具体限制见下方来源说明与[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

`field-authority@1` 为正式轮胎证据逐字段保留全部候选及五项选择依据；平级矛盾没有默认值，有偏好的冲突仍不视为已解决。比较、知识检索、AI 证据包及报告保存各自范围内的判定，旧记录不回填。第39轮最终私有浏览器 **5项UI/3项HTTP**通过，覆盖来源筛选、指定字段纠错入口、混合字段默认、平级无默认、冻结比较和桌面/手机布局；使用真实浏览器、私有HTTP/SQLite与合成来源，真实Parser、外网和模型调用均为0，验收进程、端口与临时存储已清理。

第39轮最终全工作区类型检查、Web构建、桌面前端构建及移动前端构建均exit0；桌面Node **14项**、移动Node **13项**、PWA **8项**、共享原生传输JavaScript **6项**及字段前端专项 **7项**通过，各组分别记录，不累加为完整套件。桌面/移动主JS分别766.55/778.80 kB，仍有超过500 kB的提示；本轮构建不代表Tauri/Rust、Android原生、设备或性能达标验收，没有新增官网来源、真实OpenAI或Embeddings调用验收。

第39轮正常API重启后，真实3000→8000只读浏览器验收通过：字段规则目录48项，历史冲突目录返回9个版本；已绑定样本14字段/9默认，待核对身份样本19字段/0默认。桌面1440/手机390均无横向溢出，console错误、API写请求、来源和模型查询均0，AI/Embeddings关闭。唯一after核验通过：91张表schema完全不变，全部旧列旧行保留；规格/事实/快照/关注仍92/95/13/1，83条身份绑定及1份迁移回执不变。仅会话107→110、审计114→116，两条审计均为`quarantines_list_read`；备份25,841,664字节，4张Golden及7张Parser业务表仍空，对象0文件、391个包文件逐SHA不变。最终运行终态在2026-10-01 01:58:15 +08核验通过：API83176（父进程63284）、Web69824（父进程77428）仅监听回环地址；8003/55439无监听，Parser及验收进程为0。

第38轮历史验证：`variant-identity@2` 区分相同数字的不同代码类型；正常库已为 **83 项**有完整历史证明的旧 SKU 追加现行绑定，**9 项**未知/混合类型保留待核对，原 UUID、事实、快照与关注不改。身份键/Golden **82项**、三品牌 **156项**、动态视图/知识 **81项**等目标组通过；私有浏览器 **6项UI/4项HTTP**通过，独立三次受限Parser均正常退出。PostgreSQL并发与恢复核对84张注册表/728列值及对象哈希。各组范围与重叠分别记录，不累加为完整套件。真实人工Golden审核仍为 **0**，本机结构迁移不属于人工真值签署。首代 SU7/OE、代表性人工真值、Parser性能目标、设备离线包、真实模型、更多来源/平台与生产发布仍未完成，完整 Goal 保持 active。详见[实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

第38轮正常环境记录：三端前端构建与全工作区类型检查通过，正常 API/Web 已恢复。真实3000→8000只读复看通过；89张原表旧列/旧行保留，仅追加快照合同版本列、005版本记录与两张身份表，旧快照版本仍NULL。新增83条绑定和1份迁移回执；会话104→107、只读列表审计112→114，规格/事实/快照仍92/95/13。391个既有Parser包文件哈希不变；未写入合成样本或调用真实模型。桌面/移动构建仍有单chunk超过500kB提示，第38轮没有原生设备或性能达标验收。

## 已实现

- **监控任务中心与进度**：来源与证据页、轮胎及召回规则均可查看任务、执行尝试、旧版终态历史和追加事件。领取/进入服务/结束来自真实事务节点，租约失配或过期显示结果未知，回收后记录中断；不使用伪百分比。Web SSE有界续接，原生按同游标读取；断线明确保留最后确认内容，读取不启动/重试/取消Worker。轮胎任务沿用本机共享工作区，召回任务仍属于当前会话，旧watchlist批轮询不伪造阶段。AI内容流使用独立请求账本和事件接口，原生同样使用REST读取；原生SSE桥尚未交付。

- **本机来源管理**：已登记来源支持启用、暂停、归档、恢复为暂停、备注与只追加历史。完整管理目录含8个轮胎源、NHTSA、小米及待配置EPREL共11项；启用不能解除环境、来源能力或Parser限制。预览绑定修订/指纹，固定UUID支持未知结果恢复。暂停或恢复会使旧请求、旧回退授权和已领取监控任务的访问代次失效，备注编辑不使其失效；采纳前再次检查，已收到的原文保留。历史证据与原规则不删除，不声称能撤回已发HTTP或Parser进程。署名仍为本机自报，任意新增Adapter与生产管理员认证尚未实现。

- **轮胎字段权威与冲突中心**：按字段权威、精确身份、地区、可靠发表/原文观察时间及证据完整度选择默认展示值，保留全部来源。平级矛盾明确无默认，不回退最新来源某一侧；来源内纠错、人工值和v2身份合同独立保留。冲突中心支持规则查看、字段/来源筛选、原文与指定来源字段纠错入口。其他领域的规则目录不代表对应来源已经接入。

- **命名空间身份与追加式迁移**：相同代码按明确CAI/MSPN等类型区分；旧证据保持原样，只对可证明项追加权威合同绑定。未知或混合类型不自动合并，旧关注和精确监控不会跟随新候选；预览、署名、修订/指纹、UUID恢复与历史回执可核对。比较预览和保存入口、人工身份、关系及待执行AI证据共同检查现行合同，历史已完成内容保持原语义。

- **人工 Golden 工作流**：原文对照、预期草稿、单独人工审核、同来源冻结及历史修订查看；轮胎完整身份/字段与不同SKU碰撞、车型/配置/前后轴结构精确评估。轮胎/车型新发布必须通过有效集合，单SKU不能冒称零错合并，参考缺口确认不能豁免；署名仍为本机自报，生产身份认证、测试事件与跨来源真值尚未完成。

- **统一运行观测**：API、来源 HTTP/查询、AI/Embeddings、数据库采纳锁与 Worker 周期/任务使用真实 SDK span 关联，提供次数、耗时、已领取任务延迟及已校验 usage 回执的 token 指标。每个进程保留最近 256 个 span；操作属性组合最多 1024 组及 overflow，不等于展开后的 Prometheus series 总数。诊断只读当前进程，默认不向外部导出、不自动启动 Worker；Grafana/Collector、长期托管与生产 SLO 尚未验收。

- **历史证据知识检索**：结构化筛选优先，配合真实 SQLite FTS5 / PostgreSQL 全文索引，按所选字段的来源规则、词法相关度和核验时间排序。索引只包含正式保存的轮胎、车型与有效测试事件，目录成员以最新正式核验为准；支持中文/英文检索、精确引用、冲突展示和选择后准备 AI 证据。普通搜索不联网、不调用模型；另有独立授权的 OpenAI Embeddings 索引与 pgvector 混合召回，真实模型及语义效果尚未验收。

- **有引用的 AI 分析**：首个网关采用 OpenAI Responses API；先准备精确证据，逐次确认外部处理后发送。当前轮胎问题先在线核验，失败仍需单次快照授权；历史轮胎/车型/测试事件显式指定版本。事实文字由服务器据引用字段生成，模型推断单独标注；引用无效、拒绝或输出不完整则不采纳。调用有幂等键、只追加账本与 token 预留。真实 OpenAI 调用尚未验收，配置方法见下文。

- **冻结证据报告**：将已预览证据及可选的已完成分析保存为本浏览器会话私有报告；正文固定，标题、备注与归档状态追加修订。可按修订导出 Markdown、HTML、嵌入中文字体的 PDF，下载前校验字节数与 SHA-256。保存、打开和导出不调用模型，不把报告写回事实或知识索引。

- **在线查询与组合筛选**：按来源、型号与可选尺寸访问已接入的官方目录；可增加最多 16 项类型化 AND 条件，按品牌、型号、精确版本/产品代码、载重/速度、XL/HL、OE、静音/防爆、季节、UTQG、EU 标签等筛选本次完整返回结果。显示来源返回、匹配、明确不匹配和未能判定数量；未知不等于“否”，冲突不按一侧值匹配。独立保留 MSPN、CAI、EAN、Material Code、区域及 R/ZR 等身份语义，不提供全球任意 SKU 搜索。
- **证据链**：原始 HTML/JSON/静态目录、SHA-256、来源 URL、Parser 版本、观察时间与验证时间。快照不可覆盖；事实追加版本；页面或证据定位变化但参数未变不生成重复参数事件。来源同页字段冲突保留双方值，不能默选一个值。
- **解析前原文接收日志**：API/Worker 的轮胎、车型与召回抓取先提交原文，再执行 Parser。后续解析中断或事务回滚仍可核对已收到的原文；保存失败则停止解析和采纳。日志按需打开，显示原请求范围，不作为参数、304 缓存或授权回退数据。
- **历史重解析与审阅**：从轮胎、车型或召回接收记录选择已登记 Parser 包，在独立受限子进程中重解析历史原文。保存候选、质量差异和署名审阅，始终标记未采纳；不会刷新在线核验时间、修改正式参数/召回记录或产生告警。支持本机受控代码封存、发布评估和可执行回滚，召回公告与名称检索分别校验；操作系统级网络/文件权限沙箱与生产审核权限尚未完成。
- **原文对象与 PDF 收件**：新接收原文先写入按 SHA-256 寻址的对象存储，读取校验长度和哈希，损坏时拒绝返回。支持文件系统及 S3 兼容配置；PDF 可声明来源、署名和保存授权后留存/下载，保持“未解析、未核验”，不自动生成事实。历史数据库原文保持原样，尚未迁移至对象存储。
- **质量隔离与来源健康**：同源、同查询对照上一份已采纳结果；记录缺失或已对齐记录的已知字段缺失达到 30%，以及无法稳定对应时，单独隔离本次内容，不生成正式事实、变更或验证记录。车型按车型信息、配置版本、轮毂/轴位分别计算，不用合计比例掩盖某一类缺失；同车型标识的代际/区域/来源身份漂移也会隔离。轮胎/车型已返回的 Parser/schema 失败另行保存有界文本原文，即使没有已采纳基线也能核对。来源健康基于持久查询记录统计最近 24 小时，覆盖轮胎 registry 与小米车型源；页面只读查看记录，不自动发起官网抓取。
- **隔离人工确认**：核对原文、对照参数和候选内容后，可追加署名/理由，批准或保留隔离。批准绑定具体内容、Parser、来源、查询和基线，24 小时内仅可由后续匹配的在线请求消费一次，不直接采纳旧内容、不替代回退授权。身份变化/匹配歧义及 Parser/schema 失败不可跳过。
- **车型适配**：小米当前新一代 SU7 的 3 个配置、18 个轮毂项；保留前后轴、标配/选配/不可用、颜色条件和独立车型证据。首代来源待核验；不从车型描述推断精确轮胎 SKU 或 OE 标记。
- **车型轴位与 SKU 人工证据关系**：独立历史入口分别固定车型要求和精确 SKU 事实，保留完整代际、年款、市场、配置、轮毂、轴位与双侧引用。状态为 `pending_review / reviewed / revoked`，来源或身份变化派生 `needs_review`；修订、撤销和恢复只追加历史，撤销中更新证据仍保持撤销。固定 UUID 与预览指纹控制重试和陈旧写入，已知矛盾不能由未知确认消除。官方 OE 始终独立为 `not_established`，车库装胎或人工复核不能替代官方桥接证据。
- **我的车库**：手工保存品牌、车型、年款、代际、配置、当前/可选轮毂、前后轴尺寸，或从已核验车型配置复制并保留来源。当前轮胎关联精确 SKU，校验轴位尺寸并显示撤销提示；支持追加编辑、历史、归档和恢复。车库属于当前本地工作区，重启/换浏览器会话仍保留，不等于云端个人账户或官方适配认证。
- **授权门**：默认 `ask`。在线失败未答复或拒绝时不返回本地参数或筛选计数；允许后返回醒目标记的 `LOCAL SNAPSHOT`，保留原观察时间。授权绑定会话、来源、精确轮胎/车型查询及轮胎查询的规范化筛选条件，5 分钟过期且仅使用一次；不同条件、车型与轮胎授权不能串用。
- **比较与关注**：显式历史 SKU 比较、当前浏览器会话的关注列表、证据检查器和变更记录 API。
- **测试事件与同场成绩**：人工录入场次、方法/条件、参测身份、数值、单位与短证据；仅在同一事件内对照，保留来源名次，不补齐缺失、不生成跨场总榜。修订、撤销与恢复追加历史，陈旧提交拒绝；不自动关联精确 SKU 或覆盖厂商事实。
- **保存比较与驾驶偏好**：固定保存已核对的比较参数、人工修订选择与证据版本，来源发生变化时拒绝陈旧保存；名称/备注、归档/恢复只追加说明历史。七项驾驶权重总和须为 100，默认未设置，可清除并保留历史；偏好不改写官方事实，尚未启用推荐评分。两者属于本地共享工作区。
- **人工核验**：非身份参数可新增/修改人工值、撤销参数或恢复来源值；每次操作追加署名、原因、前后值、证据和时间。来源更新后旧处理待复核，陈旧编辑返回冲突。普通查询保留来源值，历史比较可主动选择包含人工修订。
- **版本撤销与恢复**：精确轮胎版本可追加本地撤销或恢复记录，要求署名、原因及包含该版本的已采纳证据；原始身份和历史不删除。在线/304/授权回退显示来源参数与独立的撤销标记，比较明确排除撤销版本。新的来源响应不会自动恢复它；撤销不等于厂商停售或召回。
- **身份更正与逻辑合并**：从版本状态进入，将原SKU明确指向已有正式证据的目标SKU；逐项保存身份差异说明、双方证据、署名与理由，可追加撤回。合并需要合法且相同的稳定标识，已知身份矛盾不能合并，未知项须另行确认。普通查询保持原SKU，历史比较可明确采用目标并去重；原事实、关注、监控和旧引用不迁移。
- **监控与站内提醒**：持久化规则支持来源、型号、可选尺寸/精确 SKU、变化类型和字段过滤，以及暂停、编辑、历史、归档/恢复。同查询合并调度，默认每 6 小时；独立 Worker 使用数据库租约、来源串行间隔和入库租约校验。采纳事实与站内提醒同事务提交，去重并引用前后证据，可标已读。失败策略固定 `never`，不替用户授权回退；没有自动启动后台服务或外部通知投递。
- **NHTSA 轮胎召回**：按品牌/型号关键词分页查找候选，再显式核验轮胎类公告编号；保存原文、独立召回修订与历史，支持单次授权回退、所选公告变化监控，以及名称检索范围的持续候选发现。两类规则与站内提醒属于当前会话，名称发现先建立完整基线，再提醒后来首次观察到的候选。候选不生成公告正式修订或轮胎参数，首次观察不等于新发布，空结果不等于无风险；尚未核对 DOT/TIN 与生产批次，实物适用性保持 `not_assessed`。
- **Web/H5/PWA 外壳**：中文桌面三栏、手机触控布局、深浅主题、键盘快捷键。生产构建支持安装入口、受控更新及离线打开静态外壳；不缓存 API、参数、证据或授权。设备离线数据包与真机安装验收仍待完成。外部 HTML 仅以文本显示。
- **Windows 桌面入口**：本地打包 React/Vite + Tauri 2，复用业务界面及 SDK，通过受限 Rust 通道连接本机 FastAPI。会话保存在系统凭据库，已验证跨进程保持与重置隔离；PDF 经原有校验后使用系统保存对话框，取消不显示成功。Web 默认行为保留，桌面不注册 PWA。API 服务须另行启动，显式手动设备包与本次轮胎历史授权已有运行验收；完整离线同步与云端账户仍待交付。
- **Android 移动入口**：本地打包 React/Vite + Capacitor 8.5.2，自定义受限原生桥复用共享 SDK。Debug 仅通过专属设备 `adb reverse` 访问固定 `127.0.0.1`；Release 未配置生产 API 时返回 `RELEASE_API_NOT_CONFIGURED`。会话由 Android Keystore / AES-GCM 保护且禁止备份，已实际验证进程重启保持；SAF 保存/取消、受限 PDF 选择、证据与弹窗 Back、恢复前台重检连接及真实软键盘避让已在 Android 16 模拟器验证。恢复不重放写请求，移动端不注册 PWA；iOS、真机和正式发布仍待完成。

### 来源范围

| 来源 ID | 当前能力 |
|---|---|
| `michelin-us` | PSEV / PS4S 官方 SSR；保留 MSPN、GTIN、OE 与技术标记 |
| `michelin-cn` | PSEV / PS4S 公开静态目录；严格解析 JSON 字面量、不执行脚本，保留 CAI；未声明参数不借用其他地区数据 |
| `michelin-uk`、`michelin-fr`、`michelin-de` | 3 个独立区域来源；PSEV / PS4S、CAI/EAN、厂商标签声明、HL 与同页 XL 冲突；相同代码也不跨地区自动合并 |
| `toyo-us` | Proxes Sport / Proxes Sport A/S 官方 JSON 规格；产品代码、EAN、逐 SKU UTQG 等 |
| `hankook-us` | Ventus S1 evo3 / SUV / EV 官方规格卡；Material Code、UTQG、静音棉、防爆及 OEM 适用品牌；OEM 品牌名不冒充胎侧 OE 标记 |
| `pirelli-us` | P ZERO (PZ4) 美国公开尺寸页，须填尺寸；逐 SKU 产品码/EAN、R/ZR、`(Y)`、XL、OE、PNCS/ELECT 与防爆。已核对 265/40R20 的 3 条和 265/40R21 的 8 条；不将型号营销或尺寸导航当成规格，不静默修正来源异常 UTQG |
| `nhtsa-us-recalls` | 独立美国监管召回源：按品牌/型号逐页查找产品候选，再按轮胎类公告编号核验原文；支持公告历史与所选编号的变化监控，不判定精确 SKU 或实物适用性 |
| `xiaomi-cn-vehicles` | 独立车型源：当前新一代 SU7 配置、轮毂与前后轴；精确年款、轮胎 SKU 和 OE 胎侧标记保持未确认 |
| `eprel` | 待配置；需要 API Key、正式 Adapter 和条款核验，当前不返回数据，不计入 8 个轮胎来源 |

八个轮胎来源覆盖四个品牌，其中五个是米其林的不同区域目录；这个数量不代表八个独立厂商。中国目录中的 `m` 混有 OE 与厂商标记，暂保留原始标记，不全部归类为 OE。

参数与召回按不同领域计数：**8 个轮胎参数来源 + 1 个 NHTSA 召回来源**；小米仍是独立车型来源，待配置 EPREL 不计入已接入来源。召回候选不会生成轮胎参数或自动关联精确 SKU。

Pirelli 接入范围是美国 P ZERO (PZ4) 尺寸页合同，其他型号、地区和未核验尺寸不计为已验收；无尺寸不会请求型号导航页。官方逐行技术布尔保留真/假，缺失仍为未知。来源将 UTQG 温度声明为 `AA` 的记录保留原串、原分项和异常说明，标准三项暂不采纳；不会擅自把它换成常见顺序。官网本次返回无校验器且 `no-store`，真实重核验采用新请求，不声称已验收 304。这里只验证本机个人 PoC；US 使用条款、商业采集与再分发许可尚未核验，不把 UK 的个人摘录例外当成 US 授权。

测试 fixture 只在测试目录中使用。开发数据库默认空库，不自动插入虚构参数。正常使用时数据来自本次官网查询。

第40轮对其他P0品牌的核查结果如下；这些站点尚未登记为可用来源，也没有用客户端字段名或合成数据替代实际SKU响应：

| 官方区域 | 已观察结果 | 当前边界 |
| --- | --- | --- |
| Continental US | robots请求返回403 | 停止该域探测，没有产品响应 |
| Continental UK | robots允许，SportContact7页面及其官方脚本200；页面没有逐SKU数据，独立产品API域的robots请求403 | 脚本中的Article/EAN等只是接口线索，动态合同未验证；没有使用页面中的service-key。普通本机研究不构成商用复制/分发许可 |
| Bridgestone US | 新域首页和条款200，条款明确限制scraping | 停止后续产品及动态接口请求，不能依据首页可达声称已接入 |
| Goodyear US | 两次同URL、同生产通道的robots请求均发生HTTP处理异常 | 未取得robots正文、条款或SKU；异常属性status=400不能认定为已确认的官方HTTP400或403 |
| Yokohama US | 既有第31轮条款证据明确禁止自动查询 | 本轮未再次请求，待有适用授权或其它正式渠道后再评估 |

来源发现共15次请求尝试，包含10份200正文、2次明确403、1次无效路径404和2次未返回正常响应的处理异常；404仅说明所试路径无效。原文/hash和失败证据均保留在忽略的`.artifacts/round40-discovery/`，未写入正常事实库。下一步应依据这些具体缺口取得正式接口/授权或修复可证明的传输问题，不能盲目重试拒绝资源。

## 本地启动

需要 Node.js 22.12+、Python 3.12+、`uv`；Windows 脚本必须使用 PowerShell 7。

```powershell
npm install
uv sync --project apps/api --extra dev
pwsh -NoProfile -File scripts/dev.ps1
```

打开 [本地工作台](http://127.0.0.1:3000)。API 在 [本机 8000 端口](http://127.0.0.1:8000/docs)。启动脚本检查端口冲突，API 日志位于忽略的 `.artifacts/runtime/`；退出 Web 命令会停止脚本创建的 API 进程。

也可在两个终端分别运行：

```text
uv run --project apps/api uvicorn tire_api.main:app --host 127.0.0.1 --port 8000
npm run dev
```

默认数据文件为 `data/dev.db`，重启保留已采集证据和会话关注。当前自动执行显式版本化的兼容迁移；不要通过删除数据库处理升级问题。

服务只接受本机访问，当前模式是 `local_single_user_poc`。HttpOnly 会话隔离用于本地授权与关注，不能替代生产身份认证或团队隔离。**不要将本模式暴露到公网。** OIDC/PKCE/RLS、生产密钥管理和完整数据库迁移/回滚属于后续阶段。

### 桌面入口（Windows 运行已验证）

`apps/desktop` 使用 React/Vite + Tauri 2，打包本地界面并复用 Web 的业务组件和 SDK。本机 FastAPI 需要另行启动；桌面不依赖 Next Web 服务运行，也不会自动启动监控 Worker。Windows 构建需要 Rust 1.90+ stable/MSVC、Windows SDK 与 WebView2；系统缺少 WebView2 时，安装程序需要联网下载运行时。macOS 代码配置使用系统钥匙串，但尚未在 Mac 上构建验收。

```text
uv run --project apps/api uvicorn tire_api.main:app --host 127.0.0.1 --port 8000
npm run desktop:dev
```

第二条命令在另一个终端运行。构建使用 `npm run desktop:build`；Windows 默认生成当前用户安装的 NSIS 包。`npm run desktop:frontend` 仅构建界面，`npm run test:desktop` 检查 JavaScript 传输行为，Rust 检查使用 `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml`；这些结果需与实际原生运行验收区分。

本机构建产物为 `apps/desktop/src-tauri/target/release/tire-desktop.exe`（5,414,400 字节）及 `target/release/bundle/nsis/胎迹_0.1.0_x64-setup.exe`（相对 `src-tauri`，1,853,423 字节）。Release 可执行文件已实际运行，安装包未签名，尚未执行安装/卸载。有效外链在系统浏览器打开、报告各导出格式的原生保存、macOS 构建和签名更新仍需独立验收；当前已验证 PDF 保存取消/成功、字节哈希、远程导航及通用插件权限拒绝。

桌面会话独立于 Web 浏览器，只保存在 Windows 凭据管理器或 macOS 钥匙串。安全存储失败时停止连接；“重置本机安全会话”会使旧会话私有记录无法继续访问，但不删除后端工作区数据。下载通过校验后再选择保存位置，外链交由系统浏览器，桌面不注册 PWA 缓存。

默认仅连接 `http://127.0.0.1:8000`。隔离验收可通过启动进程环境设置 `TI_DESKTOP_API_PORT` 和 `TI_DESKTOP_SESSION_NAMESPACE`；renderer 无法指定任意服务地址。桌面包当前不包含 API/Python/数据库服务，不代表离线数据包、云端账户、签名发布或自动更新已交付。AI 配置与逐次授权门沿用后端；本轮验收保持真实 Responses/Embeddings 关闭。

### 移动入口（Android 16 模拟器运行已验证）

`apps/mobile` 使用 React/Vite + Capacitor 8.5.2 打包本地资源，复用 Workbench 和 `packages/native-client` 的二进制、错误与取消传输。Android 目前需要另行启动本机 FastAPI；构建需要 JDK 21、Android SDK API 36 与 PowerShell 7。项目 `minSdkVersion=24`、`compileSdkVersion=targetSdkVersion=36`，本轮实际运行仅覆盖 Android 16 / API 36，不能据此声称其他版本或实体设备已验收。

先按“本地启动”运行正常 API，再构建默认连接 8000 端口的 Debug 包。将 `$deviceSerial` 改为本应用专属设备的实际序列号；所有转发与安装都显式指定该设备：

```powershell
pwsh -NoProfile -File scripts/build-mobile.ps1 -JavaHome D:/JAVA_21 -AndroidSdk E:/Android_Studio_SDK
$deviceSerial = '你的专属设备序列号'
& 'E:/Android_Studio_SDK/platform-tools/adb.exe' -s $deviceSerial reverse tcp:8000 tcp:8000
& 'E:/Android_Studio_SDK/platform-tools/adb.exe' -s $deviceSerial install -r apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

安装后打开“胎迹”。`npm run mobile:frontend` 只构建 Vite 界面，`npm run mobile:sync` 同步 Android 资源；`npm run mobile:android` 调用上述构建脚本，可通过环境变量指定 JDK/SDK。`-ApiPort` / `-SessionNamespace` 仅用于 Debug 隔离验收，本轮 `emulator-5556` 的 8003 私有验收包不是正常 8000 包，日常使用应按上述默认值重建并配置对应转发。API authority 由构建固定，renderer 不可指定任意 URL；不用 `10.0.2.2` 或 LAN 放宽后端本机边界。

会话不交给 JavaScript 或普通文件，安全存储失败明确阻断；重置本机安全会话会失去旧会话私有记录的访问，但不删除后端共享工作区。文件下载经类型、长度和 SHA-256 校验后才进入 SAF 系统创建器，取消独立提示，HTML/PDF 不自动执行；PDF 输入只读取用户在系统选择器明确选择的受限文件。Back 优先关闭业务弹窗或证据面板；后台恢复保留界面与草稿，只重检连接，不重放写请求。系统 Insets 与真实 IME 驱动安全区及键盘避让，移动端不注册 Service Worker。

`-Configuration Release` 已生成未签名 `apps/mobile/android/app/build/outputs/apk/release/app-release-unsigned.apk`（3,800,782 字节）；临时 QA 签名副本（3,845,141 字节）已在本轮设备实际运行，本地页面明确显示“未配置正式 API”。当前没有生产 HTTPS API / OIDC 配置，`apiRequest`、`apiCancel`、会话重置均以 `RELEASE_API_NOT_CONFIGURED` 闭锁，未增加私有 API 请求，不因 Debug 的 `-ApiPort` 开启联网。应用 Release 为非 DEBUGGABLE、`BuildConfig.DEBUG=false`，源码与最终字节码均关闭 WebView 调试；本轮 userdebug 模拟器的 Chromium 133 按系统调试标记强制开放 DevTools，因此生产 user 系统（`ro.debuggable=0`）的调试关闭尚未验收。临时签名私钥已删除，该签名不代表生产签名。生产 HTTPS/OIDC、真机、商店发布、iOS、通知与设备离线包继续待办，APK 不包含 API/Python/数据库服务；产物哈希见 `.artifacts/runtime/round30-android-artifacts.json`。

### 查询示例

在页面中选择 Michelin US 和 `Pilot Sport EV · PSEV`，输入 `265/40R20`。2026-09-26 真实验收返回独立 MSPN：

| MSPN | 来源规格 | OE | Acoustic |
|---|---|---|---|
| `08150` | `265/40ZR20 104Y XL` | LM1 | 官网标记 Acoustic |
| `36055` | `265/40R20 104Y XL` | AO | 来源未标明 |
| `22743` | `265/40R20 104H XL` | AO | 来源未标明 |

这张表是当日验收记录，不替代应用的在线查询，也不能据此判定中国区域或某车型适配。官网数据可能随时间变化。

车型入口提供独立在线查询。当前 SU7 20 英寸选项明确为前 `245/40R20`、后 `265/40R20`；点击轴位进入轮胎查询时只带入尺寸，不自动指定型号、地区或发起请求，也不因此宣称某个候选 SKU 已经适配。

### 普通在线查询的组合条件

在普通查询中展开“更多规格条件”，从服务端目录选择字段、判断方式和类型化值，最多组合 16 项，全部条件同时满足才返回。增加、删除、清空或编辑均只改变草稿；点击“查询轮胎”后重新请求来源。已提交结果和待处理历史授权保持原来的型号、尺寸与条件；“按本次条件重新在线查询”也使用原提交范围。目录加载失败会保留现有条件并提供重试，不会悄悄改为无条件查询。当前型号未接入时，下拉框明确提示重新选择，不假显示另一个可用型号。

`GET /v1/tire-query-filters` 返回 `version: "tire-query-filters@1"`、`max_conditions: 16` 及 28 个字段的类型、支持操作、选项、单位和说明。`POST /v1/sources/{source_id}/live-query` 的 `filters` 与 `query` 同级，省略时为 `[]`。例如向 `michelin-us` 提交以下请求；这是接口用法，实际命中以本次官网响应为准：

```json
{
  "query": { "model": "Pilot Sport EV", "size": "265/40R20" },
  "filters": [
    { "field": "xl", "op": "eq", "value": true },
    { "field": "manufacturer_product_code", "op": "eq", "value": "08150" }
  ],
  "fallback_policy": "ask"
}
```

字段范围包括品牌、系列、型号、版本 ID、区域、厂商代码、GTIN、EPREL 编号、尺寸、结构、载重/速度、OE、静音与技术列表、XL/HL、防爆、静音棉、EV 营销标识、季节、UTQG 和 EU 标签。字段是否实际有值取决于来源声明；当前真实 Parser 尚未产出 `family` 和 `ev_marketing_mark`，不会从型号中的“EV”、营销文字、品牌或产品名补推，也不因目录列有 EPREL 编号而声称 EPREL 已接入。

| 条件 | 实际语义 |
|---|---|
| 文本 `eq` | Unicode NFKC、合并空白、忽略大小写后的完整值匹配，不做子串/模糊查询；代码与 GTIN 保留前导零。尺寸保留 R/ZR，双载重指数按完整文本，速度级别不按字母排序；技术列表按完整成员匹配 |
| 数值 `eq` / `gte` / `lte` | 只接受有限 JSON 数字，例如 `{"field":"utqg_treadwear","op":"gte","value":300}`；布尔、数字字符串、带单位对象不充当数值。噪声按来源实际 dB 字段，不自动换算其他单位 |
| 布尔 `eq` | `value` 必须是 `true` 或 `false`，明确的“否”不包含未声明，也不从缺失技术标记推断 |
| `is_known` / `is_unknown` | 不携带 `value`。`is_unknown` 只匹配缺失、null、空文本、空技术列表及技术文本的 `unknown`/`unspecified`；该哨兵规则不套用于产品代码等标识。来源字段冲突或非法类型仍未能判定，不命中“来源未声明” |

服务端将值规范化、重复条件去重并稳定排序，生成用于记录和授权比较的 canonical filters；等价顺序不改变授权范围。资源 `query`、查询键、Parser 输入、质量对照、完整快照成员和 304 缓存仍使用原来的型号/尺寸范围；筛选只投影本次已采纳结果，不生成筛选后的新事实基线。`query_runs.selection_filters` 通过兼容迁移 `004_query_selection_filters` 追加，旧记录保留 SQL NULL 并按无条件解释，不重写历史行。

响应新增 `selection: {filters, source_count, matched_count, excluded_count, undetermined_count}`。计数只覆盖本次单一来源、型号和可选尺寸实际返回的范围，三类数量之和等于 `source_count`，不代表官网完整目录或全球 SKU 总量。AND 中任一条件明确不满足则计入 `excluded_count`；无明确否定但仍有条件不可判定则计入 `undetermined_count`；全部满足才返回规格。无条件时返回该范围全部规格。有效响应的零匹配仍保持 `live`、`live_verified_304` 或已授权的 `local_snapshot`，不转成来源失败，也不宣称官网目录为空。

来源失败、等待授权或拒绝时四项计数为 null，界面不展示本地数量与参数。允许回退仅消费与本会话、来源、资源查询及同一 canonical filters 匹配的授权；换条件会在读取本地参数或消耗授权前被拒绝。普通查询的带条件授权不能扩大给 AI 的无条件准备请求。组合筛选不调用 AI 或 Embeddings。

## 配置

`.env.example` 是配置参考；API/脚本读取进程环境变量，**不会自动加载根目录 `.env`**。例如：

```powershell
$env:TI_DISABLED_SOURCES = 'michelin-us'  # 来源停止开关，在线请求明确失败
$env:TI_DISABLED_SOURCES = ''            # 解除停止；重新启动API后生效
```

| 变量 | 说明 |
|---|---|
| `TIRE_DATABASE_URL` | SQLAlchemy URL；默认本地 SQLite，也兼容 `DATABASE_URL` |
| `TIRE_CORS_ORIGINS` | 仅允许 loopback origins，默认 3000 端口的 localhost/127.0.0.1 |
| `TI_DISABLED_SOURCES` | 逗号分隔来源 ID，停止采集 |
| `TI_API_BASE_URL` | Next.js 服务器代理地址，默认 `http://127.0.0.1:8000` |
| `TI_OBJECT_STORE_BACKEND` | 默认 `filesystem`；可选 `s3`，API 与 Worker 必须指向同一存储 |
| `TI_OBJECT_STORE_ROOT` | 文件系统对象目录；SQLite 默认 `<数据库文件名>.objects`，PostgreSQL 默认项目 `data/objects` |
| `TI_S3_BUCKET`、`TI_S3_PREFIX` | S3 桶及前缀；默认前缀 `tire-evidence` |
| `TI_S3_ACCESS_KEY_ID`、`TI_S3_SECRET_ACCESS_KEY` | S3 模式必填服务器凭据，不使用环境中隐式 AWS 凭据发现；不要写入前端或版本库 |
| `TI_S3_ENDPOINT_URL`、`TI_S3_REGION` | 可选 HTTPS 兼容端点；默认区域 `us-east-1`，R2 可配置 `auto`。真实云端验收待完成 |
| `TI_OBSERVABILITY_ENABLED` | `0/1`，默认 `1`；启用本地 SDK 观测，无网络 exporter |
| `TI_OBSERVABILITY_LOGS` | `0/1`，默认 `1`；启用 stderr 安全 JSON 关联日志 |
| `OTEL_SDK_DISABLED` | `true/false`，默认 `false`；`true` 优先关闭 SDK。此开关不配置外部 Collector |

抓取器固定 HTTPS/域名白名单，通过实际连接使用的 DNS 解析器拒绝非公网地址；不继承系统代理环境。GET 每跳重定向重新验证，固定只读 POST 不跟随重定向；限制超时、按来源指定的 MIME、解压后大小及抓取频率。robots 支持通配符、末尾锚点和最长规则匹配，访问失败时关闭该次抓取；NHTSA 固定公共 API 的有限 robots 例外见下文召回说明，其他来源策略不变。只访问已核验的公开页面、静态目录或固定只读 API，不访问 robots 禁止的路径和查询参数。轮胎、车型与召回 Parser 均使用有界子进程，Windows 使用 JobObject 限制内存、CPU 和进程数量；未部署操作系统级网络/文件权限沙箱，Python 层网络拒绝只是纵深保护，不能替代安全沙箱。生产仍需逐站商业许可与更强隔离。

### 本机运行观测

新版本 API 启动后可读取 `GET /v1/observability` 与 `GET /v1/observability/metrics`，默认位于 `http://127.0.0.1:8000`。端点保留 loopback、Host 与 Origin 检查，不创建会话、不读写业务数据库，scrape 不计入观测。状态只属于当前进程：API 的 `worker_presence=not_observed_here` 不证明另一进程运行了 Worker，重启后内存 span 和计数重新开始。

Worker 默认不监听指标端口。需要本机采集时显式启动，端口范围为 1024–65535；同一命令会正常执行启用的监控任务，并非只启动诊断服务：

```powershell
uv run --no-sync --project apps/api python apps/worker/monitor.py --metrics-port 9465
```

该命令使用已同步的同一 API 解释器环境，`--no-sync` 不自动变更依赖，避免改变 Parser 封存包所要求的精确环境。启动后打印实际安全监听配置，读取 `http://127.0.0.1:9465/v1/observability/metrics`；退出时统一关闭。API 与 Worker 指标独立，不能只采集 API 就声称覆盖 Worker。以下是供已有本机 Prometheus 使用的配置示例；本轮未部署 Prometheus、Grafana、Loki 或 Collector：

```yaml
scrape_configs:
  - job_name: tire-api
    metrics_path: /v1/observability/metrics
    static_configs:
      - targets: ["127.0.0.1:8000"]
  - job_name: tire-worker
    metrics_path: /v1/observability/metrics
    static_configs:
      - targets: ["127.0.0.1:9465"]
```

可用 PromQL 示例（需已有持续采集样本，不能由一次读取宣称 P95/SLO 达标）：

```promql
# API 按模板路由的五分钟耗时 P95，单位秒
histogram_quantile(0.95, sum by (le, route) (rate(tire_operation_duration_seconds_bucket{job="tire-api",operation="api.request"}[5m])))

# 来源查询失败速率；local_snapshot/consent_required 应独立展示，不能计为在线成功
sum by (source, outcome) (rate(tire_operations_total{operation="source.query",outcome=~"error|source_unavailable"}[5m]))

# 实际领取的到期任务延迟 P95，不是全队列积压或调度 SLO
histogram_quantile(0.95, sum by (le) (rate(tire_worker_queue_lag_seconds_bucket{job="tire-worker"}[5m])))

# 已报告 token 按 provider/kind 分开；不得再跨 kind 求和
sum by (provider, kind) (rate(tire_ai_tokens_total[5m]))
```

`source.http` 的一次操作可能包含重定向，HTTP 状态取最后响应，不能当作每一跳请求计数。任务延迟仅对实际领取且有到期时间的任务采样；未来任务、未领取任务和 legacy 关注列表不补零。usage 来自已校验供应商回执，不是账单；input/output/cached/total 含重叠口径，未知值不补 0，也不推算 cost。

SDK 关联日志和诊断字段不包含 URL、原始路径、查询/body/header、Cookie、SQL 或异常文本，不采纳外部 trace/baggage 作为上下文；**既有 uvicorn access log 不在本轮脱敏保证内**。最近 256 个 span 仅保存在内存；1024+overflow 限制的是操作属性组合，histogram buckets、token kind 和采集器标签会额外展开 series。没有配置远程 exporter、留存平台或自动观测后台进程。

### PostgreSQL 验证与候选环境

已使用本机 PostgreSQL **18.3** 的独立临时集群完成第二十八轮 **45 项检查、76 张业务表**备份恢复验收，备份为 **321,594 字节**，恢复后逐行哈希一致。覆盖既有证据、授权、车型、人工修订、监控、知识检索、AI 账本、报告、召回及 Parser 发布/重解析链；本轮增加完整来源筛选、重启及恢复后未消费授权的条件绑定，并验证迁移 `004_query_selection_filters` 为旧行保留 NULL。恢复后校验 10 个原文引用对象（40,392 字节）、4 个报告导出对象（82,261 字节）和共同 `parser-bundles.backup` 中的 3 个封存包（2,370,924 字节）。本轮报告 `vector_available=false`，不扩大为向量验收；此前真实 pgvector 的独立验收记录仍保留。输入是合成测试数据，数据库是真实 PostgreSQL，不代替官网、生产负载、RLS、灾备或完整降级迁移验收。临时集群已停止、55434 无监听、临时密码已删除；各轮检查数不累计。

Windows 下可指定已有 PostgreSQL 二进制目录复现：

```powershell
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin 'E:/PostgreSQL/18/bin'
```

脚本使用项目 `.artifacts/postgres/` 下的全新目录和独立 loopback 端口（默认 55432），创建随机凭据与非 superuser 应用角色，结束后停止临时服务并清除密码文件。结果和备份保存在忽略的运行目录；不会连接或修改系统已有数据库，普通开发仍使用 `data/dev.db`。最新路径见 `.artifacts/postgres/latest-run.json`。

`compose.yaml` 提供 PostgreSQL 17 + pgvector 的候选服务。设置自己的 `POSTGRES_PASSWORD` 后可执行 `docker compose up -d`，再设置 `TIRE_DATABASE_URL`。当前 Docker 引擎未运行，**PG17 容器尚未实机验收**。本机已在工作区内隔离复制 PG18 并编译固定版本 pgvector 0.8.1，实际验证 cosine、过滤、HNSW 与备份恢复；没有修改系统 PostgreSQL 安装，普通开发库仍为 SQLite。

## 验证与监控命令

第三十六轮相关 17 文件回归 `.artifacts/runtime/round36-related-regression.log` 为 **360 passed、1 条既有 Starlette warning（74.54 秒）**。随后包含最新 Worker 指标监听与 CLI 的四份新目标测试为 **63 passed、1 warning（8.40 秒）**，日志 `.artifacts/runtime/round36-telemetry-four-target-6761e6d82a994714b4a4a088035bbcf9/pytest.log`；两组有重叠，不相加为套件规模。覆盖真实 SDK、Prometheus 解析、关联/脱敏、线程/并发、禁用与关闭、诊断零会话/数据库访问、Worker 显式回环监听，以及到期任务延迟只采集已领取任务。

`.artifacts/observability/4e6c77c027a44040a8923c95709f2682/report.json` 为私有真实 HTTP **7 checks passed**：真实回环 API/SDK 配合合成来源传输，验证 304、拒绝/单次授权回退、4 个并发请求和重复诊断无会话或自观测增长；记录 API/source/DB 关联日志 **47 条**，模拟 HTTP 调用 **9**、真实外部网络/模型请求与 Parser 子进程均为 **0**。模型与 Worker HTTP 不在这份报告范围，由独立目标测试覆盖。首次 `e5ffb2e27aff43ce9f0d8847459453fb` 业务 7 项已过但 SQLite 句柄导致清理失败，原 failed 报告保留，后续 `cleanup.json` 记录已清理；新成功报告未覆盖旧失败。

Parser 额外目标 `round36-parser-current-target.log` 为 **11 passed、27 deselected、1 warning（62.84 秒）**。`round36-parser-environment-check/report.json` 为 passed：保存的官网正文 **583,301 字节**及原 SHA 不变，当前 builtin 在实际 Windows Job 子进程解析出 3 个 SKU，exit=0/reaped=true、回执 **2781 ms**，无新官网/模型/数据库请求；8 秒/2 进程/CPU 5 秒/384 MiB 保持。第 33 轮旧归档因新增 5 个依赖被明确拒绝为 `parser_bundle_environment_incompatible`、**0 child**，原 manifest 保留；这是预期兼容性拒绝，旧包恢复仍需匹配旧依赖，不称旧包已执行或性能 P95 达标。

正常 API 已重启，Web 未重启；`round36-normal-final/report.json` 为真实 **3000→8000**、无 route 替换的浏览器检查，主代理已查看桌面/手机截图，宽度 **1440/1440、390/390**，console/API mutation=0。`round36-normal-observability/report.json` 为 passed：20 个只读入口 span、2 个 Prometheus families，重复诊断无新 span/Set-Cookie，source/model 操作与外发为 0，未观测 Worker。唯一 `round36-data-check.json` after 保留 **85 表**全部旧 schema/旧列旧行哈希，无新增表/schema，integrity=ok/FK=0；备份 **25,284,608→25,292,800 字节**。仅会话 **95→98**，审计 **110**、规格/快照/事实/核验 **92/13/95/19** 不变；正常 7 张 Parser 表均为空，没有旧部署，AI/Embeddings disabled、请求/token=0。本轮无前端修改、未重做构建。`round36-runtime-final.json` 为 passed（2026-09-30 22:09:10 +08），API8000/Web3000 均仅监听 127.0.0.1，观测到的 Parser/test/私有 HTTP 进程与验收临时目录均为 0，私有子进程退出且存储清理。`uv lock --check --project apps/api` exit=0，解析 59 个依赖；以下历轮结果保持各自范围。

第三十五轮新增独立关系表、历史 API、双侧证据预览和车型内关系工作流；不会覆盖车型要求、轮胎事实、车库或关注。目标测试最终 **33 passed、1 条既有 warning（10.08 秒）**，包含公开响应不暴露会话字段、事实 A→B→A 仍需复核、范围/轴位/冲突、撤销恢复、幂等与陈旧写入；初次 29 项结果保留。`.artifacts/runtime/round35-backend-regression.log` 为相关十文件 **183 passed、1 条既有 Starlette warning（59.95 秒）**。末两处 UI 修复后的 `round35-typecheck-final.log` 与 `round35-{web-build,desktop-frontend,mobile-frontend,pwa}-final.log` 均通过：Web 静态页面 **5/5**、PWA **17 个资源 / 8 项检查**；桌面和移动前端保留大于 500 kB 的 bundle warning。本轮没有新原生构建或设备验收。

真实 PostgreSQL 18.3 报告 `.artifacts/postgres/pgverify-6cb2d3ff7e344a20b97c92b7a5854631/report.json` 为 **9 checks passed**，4 个关系修订、78 张注册业务表的列值恢复指纹一致，备份 **208,909 字节**。两个线程以独立数据库 session 验证同 UUID 单事件、不同 UUID 陈旧版本 409，以及事实 ABA、同集群新数据库和新 API 的恢复。关系写入前后显式比对 6 张来源表；该范围不扩大为全 schema、角色/权限、跨机灾备或生产负载验收。私有集群已停止、55435 无监听、临时密码文件已删除，该私有 PG 报告的 `real_source_calls / real_model_calls / real_parser_children` 均为 0，分别对应真实官网请求、真实模型请求和 Parser 子进程，不表示未执行进程内解析。

浏览器最终分段汇总 `.artifacts/runtime/round35-ui-flow-12f25a36eafb419d8a7db902b4640a05/report.json` 为 **passed**：真实 API/私有 SQLite 保存 **10 个修订**；创建和复核各一次入库后丢失响应，关闭重开以相同 UUID/payload 重放且不增事件。详情 503 阻止新预览，陈旧 409 不写入，未知确认不能抹除已知矛盾；撤销中修订仍撤销、恢复后待复核，双侧证据检查保留草稿。唯一事实推进明确为合成输入，旧行保留；该私有 UI 夹具的真实官网/模型请求与 Parser 子进程为 0，进程内 `parse_config` 已实际执行。桌面/手机 **1440/1440、390/390**，候选卡自然高度无裁切、pageerrors=0，4 条 console 均对应主动注入故障。`round35-normal-final/report.json` 的真实正常入口截图也已查看，console/API mutation=0、关系 total=0、无来源查询。唯一 `round35-data-check.json` after 保留原 **83 表 schema 和全部旧列旧行**，仅新增两张空关系表及索引，共 **85 表**；integrity=ok/FK=0，备份 **25,235,456→25,284,608 字节**。仅会话 **89→95**，审计 **110**、规格/快照/事实/核验 **92/13/95/19** 及其他原表不变，AI/Embeddings 禁用且请求/token=0。`round35-runtime-final.json` 为 passed，正常 API/Web 保持 loopback，验收资源清理、私有数据独立备份；正常对象目录尚未首次写入，本轮不证明正常对象写入。helper 失败保留，完成的业务写入不因汇总选择器失败重放；详情见计划，以下历轮结果各自记账。

第三十四轮仅将 `apps/api/tire_api/adapters/__init__.py` 改为 PEP 562 lazy registry，保留属性访问、`from`/`star` 导入的同一模块身份与未知属性的 `AttributeError`。`.artifacts/runtime/round34-after-imports.log` 为 **8 passed（4.05 秒）**，修改前的 **5 failed / 3 deselected** 日志保留；`round34-parser-regression.log` 为相关五文件 **272 passed、1 warning（297.75 秒）**，覆盖固定 Parser、来源合同、安全边界与重建 8/9/eager 10 包。保留的第 33 轮真实 10 源归档另在当前 host 下回放通过；重建布局与原保留归档分别记账。

同一保存正文的有限离线 baseline/after 各四个 case 通过；只对各两次未加测量包装的普通回执计算均值 **3148.5→2679.5 ms，约改善 14.9%**，诊断和计时包装样本不计入该均值。复制/完整性校验仍为主要剩余开销，本轮未改 fsync、校验或执行模型。新官网报告 `.artifacts/pirelli/round31-live/round34-222adf7360134017897f568a6994803e/acceptance.json` 为 **passed（31.451 秒）**：4 次新正文（registry 按合同推断为 200）、20/21 寸 11 个精确 SKU、历史检索/比较和随后独立注入的离线授权检查通过；三次 20 寸新正文 raw hash 各不相同，没有复用旧正文。Parser 回执约 **2.89–3.11 秒**，registry 查询约 **5.1–7.4 秒**；真实 304 未发生，自身处理开销 ≤300 ms、live query P95 ≤3 秒及人工 Golden Set 仍未验证达标。

`round34-normal-status.json`、`round34-data-check.json`、`round34-runtime-final.json` 均通过：83 表旧行/schema 保全、integrity=ok、FK 违规 0、新表 0，备份 **25,235,456 字节**；仅会话 **88→89**，审计 **110**，正式规格/快照/事实/核验 **92/13/95/19** 不变。正常 loopback API/Web 已恢复，最终观测验收/Parser进程及临时目录为 0，AI/Embeddings 禁用且账本为 0。正常 object root `data/dev.db.objects` 由首次 `put` 延迟创建，目前目录不存在、对象关联两表为 0，本轮没有验证正常对象写入；首次 helper 误要求目录存在的失败记录保留。旧归档回放首次 helper 静态断言失败也保留，未覆盖为成功。本轮没有新增前端构建、浏览器或原生验收；以下第 33 轮及更早结果保留其历史范围，不累加为完整套件。

第三十三轮执行 `apps/api/.venv/Scripts/python.exe scripts/pirelli_acceptance.py --live`，在独立临时 SQLite、对象目录与封存包目录完成新的官方查询。新报告为 `.artifacts/pirelli/round31-live/round33-bbb1e36561d14ed9b3820a50dafc62cb/acceptance.json`；父目录名保留旧脚本兼容路径，此报告属于第 33 轮，未覆盖第 31 轮记录。四次真实产品查询均为新的 200 正文，经生产 Parser 接收、解析与采纳，20 寸 3 个 SKU、21 寸 8 个 SKU；历史检索/比较及单独注入的离线授权检查通过。真实 304 未发生，脚本对 304 的修正只由明确合成的定向检查验证；Parser 回执耗时 **4391/4765/4875/5078 ms**，不宣称 live query P95 达标或人工 Golden Set 完成。

脚本现在在私有 DB/对象/包环境设置后才导入应用，合法 304 要求 API 与持久账本均为 `not_modified / {}` 且该查询无新原文；robots 所需等待超过 60 秒时停止验收，不缩短官网间隔后继续请求。`round33-pirelli-script-check-final.log` 为 **16/16**，首次合成 manifest 缺字段的失败日志仍保留。`round33-data-check.json`、`round33-normal-status.json` 和 `round33-runtime-final.json` 均通过：83 表旧行/schema 不变、完整性检查通过，仅会话 **87→88**，审计 **110** 和其他表计数不变；正常 loopback API/Web 保持，验收进程与临时目录清理。模型/Embeddings 禁用，正常库没有新来源查询。本次 registry 查询约 **6.1–7.1 秒**，性能仍超过需求中的 3 秒目标，需要继续定位启动/解析瓶颈；该层计时不等于端到端 P95。本轮只修改验收脚本与文档，未重跑前端或原生构建；下述第 32 轮及以前的结果保留其原范围。


第三十二轮将 `_tire_parser_host` 固定四个 host 模块及封存执行目录中的 `tire_api` 模块限定为直接编译 `.py` 源码；缺失、未知 host helper、越界、namespace、pyc-only、native 或 zip 来源均拒绝，不回退到其他 finder。标准库和已安装受信依赖可读缓存，`-I/-S/-B`、文件树/环境/导入来源校验保持；依赖版本清单不等于缓存内容完整性证明。复制后/Popen 前与安装 OS 限制后/GO 前检查取消和剩余预算，耗尽时不再创建或喂入进程，已有进程仍回收；后验校验/清理与 `elapsed_ms` 口径未变。轮胎、小米车型及 NHTSA Adapter 的公开 `reason`、拒收记录与执行错误码使用同一固定可信代码，`parser_timeout` 不再标为 schema drift，未知码统一 `parser_failed`，真正 schema 错误仍保留；正文、hash、receipt、质量计数和回退授权门保持。

独立日志 `.artifacts/runtime/round32-parser-runtime.log` 为 **38 passed、1 warning（181.74 秒）**，`round32-parser-cache-policy.log` 为 **19 passed（0.52 秒）**。`round32-typecheck.log`、`round32-web-build.log`、`round32-desktop-frontend.log`、`round32-mobile-frontend.log` 与 `round32-pwa.log` 分别确认全工作区 TypeScript、三端前端构建及 PWA **8 passed、0 failed**；Web 静态生成 **5/5**、17 项外壳白名单资源，桌面/移动 JS **643.64 / 655.81 kB** 并保留 **>500 kB** 警告。前端构建不扩大为本轮原生 APK/Tauri 验收。

`.artifacts/runtime/round32-sealed-replay-6a73110ff7ce4860a54a94e47736cc3c/report.json` 为限定离线 **7/7 passed**、固定顺序/无自动重试。5 个实际子进程均 exit 0/reaped=true，保存的原失败完整正文在原已保留 10 源包及当前 10 源包下回执分别 **3109 / 3172 ms**；正文 **583,301 字节**及 SHA-256 `0f52064a90a6cf465cdc646715739a6b687c007591d43d36068b8b1968b09e56`、原归档均保持。旧 8/9 是按历史源码结构重建并加不同语义标记的样包，不能称原历史归档；两个样包的 Pirelli 请求以 `parser_source_not_allowed` 在 PID 前拒绝。应用阶段 parent audit 的网络/数据库连接均 **0**，event loop 已闭合，未使用正常库、未新增来源或模型请求；这些检查不构成子进程 OS 网络/SQLite 隔离证明，不是新 live API 或 P95 验收。首轮 runner 误挡 Windows 标准库自管线，**7 failed / 0 child** 的 `round32-sealed-replay-ccefc709478f405b86bab74f78b01928/report.json` 与日志仍保留。

`round32-failure-reasons-regression.log` 初轮相关 6 文件为 **188 passed、1 failed、1 warning（87.16 秒）**，唯一失败是旧车型断言把明确的 `ParserRunError('parser_schema_changed')` 期望成 `vehicle_source_schema_changed`；只修期望，未改故障注入或生产授权规则。`round32-parser-history-regression.log` 本次历史/针对回归为 **86 passed、1 条既有 warning（550.95 秒）**，包含第 31 轮两个原失败用例及旧车型精确期望修复复验；仅证明本次范围，不倒推旧无回执错误原因，也不把初轮输出改为全绿。`round32-source-check.json` 确认 **12 份 Python AST / 14 个生产与测试文件**直接空白检查通过，包含未跟踪文件。

`.artifacts/runtime/round32-browser-f13fa4413d124b38bc48ba9e239bc608/report.json` 为 **passed**，主代理已实际查看桌面/手机/健康卡三张截图。使用合成 transport 与 Parser timeout、真实私有 API/SQLite/浏览器；桌面 **1440/1440**、手机 **390/390** 无横向溢出，console error **0**。查询结果显示“来源内容解析超时，本次核验未完成，请稍后重试。”，健康卡与拒收记录显示“来源内容解析超时，本次核验未完成。”，授权按钮正确，`reason=parser_timeout`、`state=consent_required`，未答复授权、参数/溯源均 **0**。原文/拒收/失败执行各 **0→1**，失败执行无 PID，`fallback_consents=0`；快照/规格/事实/核验四张正式表及 source_quarantines、AI/Embeddings 请求均 **0**，真实来源、模型和 Parser 子进程均 **0**。这是显式注入 UI 验收，不称官网实际超时。

`round32-normal-status.json` 为 **passed**：正常 Web3000 直接连接正常 API8000，未拦截或替换路由；主代理已查看桌面/手机两张截图，宽度/滚动宽度 **1440/1440、390/390**，console error 与 API 写请求均 **0**，health=ok / SQLite。`openai_responses / ai_disabled`、`connection_verified=false`，Embeddings 为 `embeddings_disabled`，两者 requests/accounted_tokens 均 **0**，未提交正常库来源查询。

`round32-data-check.json` 为 **passed**，after 核对仅执行一次、源库只读打开：原 **83 张表**全部旧列/旧行多重 hash 保全，`sqlite_master` schema 完全相同，integrity=ok、FK 违规 **0**、新表 **0**，before/after 备份均 **25,235,456 字节**。仅正常读取新增 `local_sessions` **85→87**，`audit_events` 保持 **110**，其他所有表行数不变；规格/快照/事实/核验四表保持 **92 / 13 / 95 / 19**。

`round32-runtime-final.json` 为 **passed**：2026-09-30 19:16:05 +08 核对时，正常 API8000（PID **33696**）/Web3000（PID **51468**）仅监听 `127.0.0.1`，私有 API8003 已停止，QA 临时目录及最终时刻观测到的 Parser 子进程均 **0**；整轮 runtime 测试及离线重放曾运行真实子进程，不把终态 0 写成整轮未运行。正常库 `data/dev.db`、bundle root `data/parser-bundles`、object root `data/dev.db.objects` 已按历史配置恢复。首次恢复误设 `data/objects`，在任何正常证据读写前发现并重启纠正，旧 startup 记录保留为非最终记录，以最终 runtime 报告为准。本轮限定验证与收尾检查已完成；新增 live 官网验收、P95 及完整规格 Goal 仍未完成，未标记生产 full suite 或真实来源整套验收通过。下列第 31 轮及以前结果为历史证据，各范围不相加、不抵消。

第三十一轮相关 10 文件完整回归为 **371 passed、6 failed（788.64 秒）**，随后限定回归为 **130 passed、2 failed（293.01 秒）**，日志分别为 `.artifacts/runtime/round31-catalog-tests.log` 与 `round31-catalog-final-targeted.log`。静默外部阶段诊断中的原两个失败用例 **2 passed**、更严缓存候选的应用/host 陈旧字节码复核 **2 passed**，均只证明各自范围；候选此前仍有 **2 passed、2 failed**，故意开放 host 缓存的反例则触发预期协议失败，不能计为绿测或上线证明。范围重叠，不相加，也不把诊断通过当成完整回归或最后真实来源验收通过。第 31 轮当时未改生产缓存策略、8 秒预算及最多 2 个进程。

第三十一轮最终全工作区类型检查及 Web/桌面前端/移动前端构建均通过，日志为 `.artifacts/runtime/round31-close-final-typecheck.log`、`round31-close-final-web-build.log`、`round31-close-final-desktop-frontend.log` 与 `round31-close-final-mobile-frontend.log`。Web 静态生成 **5/5**，PWA shell 为 **17 个 allowlisted assets**，API 与证据不缓存；桌面/移动 JS 分别 **642.54 / 654.71 kB**，均保留 Vite **>500 kB** 警告。`round31-close-final-pwa.log` 为 **8 passed、0 failed**；本轮未重建原生 Android APK 或 Tauri/Rust，不把前端构建扩大为原生验收。

第三十一轮独立恢复报告 `.artifacts/pirelli/round31-live/run-4e76e6a0a0e04b95b299fe48c5b392a9/acceptance.json` 仅恢复此前已成功采纳的 P ZERO (PZ4) `265/40R20` 检查点，并显式注入离线故障/授权条件，`scoped_faults=passed`、overall **failed**。未答复/拒绝/NEVER 策略闭锁、授权范围绑定与顺序规范化、单次消费及正式快照/规格/事实/变化指纹保全均通过；新增来源、Parser 子进程及模型请求均为 **0**。`265/40R21` 八 SKU、11 项词法历史检索及完整真实验收仍未验证，不能计为通过。

第三十一轮 `round31-close-browser-check.json` 为 **passed**：正常桌面 **1440/1440**、手机 **390/390**，无横向溢出、console error **0**；Pirelli 尺寸必填及其他来源可选尺寸切换通过。正常浏览器未发送业务写入 HTTP 请求，GET 读取仍会创建会话或读审计；正常 Parser 包目录 **total=0**，实际验收的是“本页没有已登记包”，旧包缺兼容来源的文案仅静态复核。

私有浏览器从实际 partial checkpoint 的副本恢复，未造来源/模型数据。选中精确 SKU `4159300` 自动填入 `265/40ZR20`，取消 SKU 限定仍保留尺寸；实际保存的是查询范围暂停规则（`enabled=false`、`variant_id=null`、`last_run=null`），规则/任务各 **0→1**，不把它标为精确 SKU 规则或调度执行通过。五个正式表旧行指纹保持，ParserExecution **4→4**、ParserEvaluation **0→0**、AI/Embeddings 请求及新增来源尝试均 **0**。

第三十一轮 `round31-data-check.json` 为 **passed**：正常库原 **83 张表**全部旧列/旧行保留，无新表；before/after 备份分别 **25,231,360 / 25,235,456 字节**。仅 `local_sessions` **69→85**、`audit_events` **104→110**，新增 6 条审计均为 `quarantines_list_read`，由 `round31-close-added-audit-summary.json` 佐证；其他表行数不变。`round31-close-runtime-final.json` 为 **passed**：正常 API8000/Web3000 恢复且仅监听 `127.0.0.1`，观测到的 Parser 子进程、私有 UI API 进程与 QA 临时目录均 **0**；`round31-close-normal-status.json` 记录 `openai_responses / ai_disabled`、`connection_verified=false`、requests/accounted_tokens **0**，正常库新增来源查询 **0**。这些收尾结果不抵消本轮 Python 回归或完整真实来源验收的失败。

第三十轮（2026-09-30）最终移动/桌面 Node 传输 **33/33**、JDK 主机自定义原生核心 **74 项**及下载任务 **21 项检查**通过；后者不是 JUnit，也不等于 Android 设备测试。专用 Android 16 / API 36 `emulator-5556` 通过实际 `AndroidJUnitRunner` **8/8（12.311 秒）**。Gradle `connected` 调度在安装 test APK 前停于 UTP 依赖解析，已仅停止本任务进程；最终使用相同已编译 test APK 经 `adb am instrument` 实际运行，不将未完成的 Gradle 调度标为通过。初次仪器 **5 通过/3 失败**来自 MockWebServer 将主机规范化为 `localhost` 超出 Debug 固定 `127.0.0.1` 策略，只修测试 URL 后通过。日志见 `.artifacts/runtime/round30-js-final.log`、`round30-native-core-final.log`、`round30-android-instrumented-final.log`。

真实打包 Android WebView 查询显示 **6 张卡/实时核验**，宽度/滚动宽度 **412/412**，来源 script 仅按文字展示、canary 未执行，证据 Back 清除正确；失联后重试恢复保留同一 DOM 与草稿，恢复没有重放写请求。真实 IME 可见时 viewport **839.24→527.24**、底部导航 **grid→none**，系统状态栏未覆盖业务内容，截图已实际查看。最终 APK 的 SAF 保存取消/成功、系统 PDF 选择及读取原字节再次通过，合成样本 **40 字节**、SHA-256 `19f93661ef30078e0f77e29eca4c56161263f6fce6e8dc8ab27d2ffdd803db33`；它不是 PDF 解析验收。Keystore 进程重启保持会话通过。以上使用私有真实 FastAPI/SQLite 与合成 source/Parser 输出，真实来源及模型调用均为 0，不能称本轮官网 Parser 或真实 AI 验收。

全工作区类型检查、Web/桌面前端/移动构建和 PWA **8/8** 已通过；正常开发入口已恢复，桌面 **1440/1440**、手机 **390/390** 无横向溢出，health=ok、console 0；AI 为 `openai_responses / ai_disabled`，`connection_verified=false`、requests/accounted_tokens=0，未在正常库提交来源查询。`round30-data-check.json` 为 passed：正常库原 **83 张表**全部旧列/旧行哈希保留、无新表，前后备份均 **25,231,360 字节**；唯一行数变化为正常服务/UI 读取创建的 `local_sessions` **65→69**，其他表行数不变，没有新增业务或 AI 事实。`round30-release-native.json` 记录实际 Release API 闭锁通过，fixture 请求 **87→87**、合成 source calls **3→3**；生产 user 系统的 WebView 调试关闭仍待验收。`round30-runtime-final.json` 为 passed：私有 API8003及专用 AVD 已停止、3 个 QA 安装包已卸载、8003 reverse 与 9224/9226 forward 已移除、临时私钥为 0；正常 API8000/Web3000 继续仅在 `127.0.0.1` 运行，AVD 配置保留。完整日志与未验证边界见[第 30 轮实施记录](docs/plans/2026-09-26-tire-intelligence.md#第三十轮实际交付与验收2026-09-30)。下列第 28 轮后端、官网、数据库恢复和浏览器结果保留为历史证据，未作为本轮重跑结果。

第二十八轮最终全后端/Worker为 **1014 passed、77 subtests passed（1021.71 秒）**，有 2 条警告：既有 Starlette/httpx 弃用提示，以及隔离审阅并发用例触发的 Pydantic `alias='variant_id'` 元数据提示；相关路由本轮未改，用例通过，不记作零警告。初次相关 **132 项**、后续筛选专项 **73 项**与监控旧迁移 **1 项**存在重叠，均不与最终全量相加。真实 Michelin US 的 PSEV `265/40R20` **5 项检查通过**：3 个来源规格中 Acoustic AND XL=true 只匹配 MSPN `08150`，其余 2 项为未能判定；不存在代码的筛选仍在线成功且零匹配，完整快照与原观察时间保持不变。两次官网实际均为 200，真实封存 Parser 子进程退出 0 并回收；故障和授权阶段为显式注入，不声称官网掉线或本次真实发生 304。

合成浏览器服务自检 **5 组通过**，实际桌面 1440×1000 浅色及手机 390×844 深色验证组合筛选、草稿冻结、允许/拒绝历史授权、304 零匹配、目录故障恢复、16 条上限、校验、焦点及无横向溢出，两端 console error/warn 均 0。该浏览器验收使用合成传输与合成 Parser 输出、真实业务 API/独立临时数据库，没有真实子进程回执；与上述官网验收分别记录，AI/Embeddings 调用为 0。PostgreSQL **45 项**、最终类型检查/生产构建/PWA **8/8** 已通过，静态白名单 17 项。正常库原 **83 张表**全部原列/原行哈希保留、无新表；仅新增 1 条会话与迁移版本004，23条旧查询的 `selection_filters` 均为 SQL NULL，业务事实及AI没有新增。正常3000/8000入口已恢复，真实开发入口核对目录28字段/16条件及添加/清空控件通过，没有从正常库发起官网或模型查询。QA/临时PG已停止，3001/8001/55432/55433/55434无监听、Parser子进程0。本轮早期 `/fixture/mode` 422 来自验收夹具的局部请求类前向注解，移至模块级并让自检实际调用 POST 后通过，不是生产后端错误。上一轮偶发 8 秒 Parser 超时仍未确定根因，生产限制未放宽；其他未交付范围与完整历史证据见[实施计划](docs/plans/2026-09-26-tire-intelligence.md#2026-09-28-第二十八轮计划普通查询的组合-sku-筛选)。

```text
# 离线回归：领域、HTTP安全、Parser、授权、历史、迁移、并发及Worker（含遥测监听）
uv run --project apps/api --extra dev pytest apps/api/tests apps/worker/test_monitor.py apps/worker/test_telemetry_monitor.py -q

# TypeScript与生产构建；请先停止next dev，避免共用.next写入
npm run typecheck
npm run build
npm run test:pwa

# JS/TS 单测：web（route-hash 纯函数）、api-client（含 decoder-fixtures 34 用例）、native-client 传输
npm run test --workspace @tire/web
npm run test --workspace @tire/api-client
npm run test --workspace @tire/native-client

# 移动/桌面 Node 传输回归；不是 Android 仪器或真实来源验收
npm run test:mobile
npm run test:desktop
npm run mobile:frontend
npm run desktop:frontend

# 一键串联全量验证：typecheck → 五端单测 → web 生产构建（含PWA白名单构建期校验）→ API全量pytest + Worker两套测试
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/verify-all.ps1

# 显式联网，不在普通测试中自动执行；不修改开发业务库
uv run --project apps/api python scripts/canary.py
uv run --project apps/api python scripts/canary.py --model PS4S --size 265/40R20
uv run --project apps/api python scripts/canary.py --all-sources --revalidate
uv run --project apps/api python scripts/canary.py --source michelin-cn --model PSEV --size "" --revalidate

# 真实来源查询 + 临时数据库 + 显式网络失败注入 + 授权/比较/关注验收
uv run --project apps/api --extra dev python scripts/acceptance.py

# 扩展：真实US/CN条件请求/当前SU7，另行注入解析字段缺失验证隔离与授权
uv run --project apps/api --extra dev python scripts/acceptance.py --extended

# 真实韩泰来源 + 临时库模拟人工新增/修改/撤销/恢复；不向开发库写模拟纠错
uv run --project apps/api --extra dev python scripts/curation_acceptance.py

# 真实小米当前配置 + 临时库模拟车库复制/编辑/归档/恢复；不代表用户实际持有该车
uv run --project apps/api --extra dev python scripts/garage_acceptance.py

# 真实韩泰来源 + 临时库模拟保存比较/编辑/归档/偏好；不写正常开发库
uv run --project apps/api --extra dev python scripts/research_acceptance.py

# 真实韩泰证据 + 临时库保存报告、三格式下载与中文 PDF 文本检查；不调用模型
uv run --project apps/api --extra dev python scripts/report_acceptance.py

# 真实韩泰来源 + 临时库模拟监控规则，验证调度/证据/站内提醒
uv run --project apps/api --extra dev python scripts/monitoring_acceptance.py

# 真实当前 SU7 基线 + 明确注入解析配置缺失，验证隔离和单次授权回退
uv run --project apps/api --extra dev python scripts/vehicle_quality_acceptance.py

# 执行当前到期的已启用规则一次；或以前台方式每60秒检查到期任务
uv run --project apps/api python apps/worker/monitor.py --once
uv run --project apps/api python apps/worker/monitor.py

# 兼容旧关注刷新（单实例）：不依赖监控规则，默认每6小时
uv run --project apps/api python apps/worker/monitor.py --legacy-watchlists --once
```

Worker 与 API 共用领域写入路径和数据库。规则模式的同查询任务共享租约，同来源任务串行且完成后至少间隔 2.1 秒；实际 Adapter 仍执行来源策略和限流。租约为 10 分钟，过期后可重新领取，旧持有者不能采纳事实或覆盖任务结果。普通轮询只执行到期任务，不因为重启而立刻重抓全部来源。旧 `--legacy-watchlists` 模式仍要求单实例，不与规则模式共用调度限流。外部 Push/邮件/Webhook、服务托管和持续运行监测尚未接入。

`acceptance.py --extended` 使用独立临时数据库，18 项检查已通过；其中包含真实 US、CN 304 和当前 SU7 请求，也包含明确注入的网络/解析字段缺失场景。注入用于验证隔离与授权门，不表示厂商发生了相应故障，不写入开发业务库。浏览器质量验收同样使用独立临时 SQLite，在测试入口重放已下载的真实 CN body 并注入 Parser 字段缺失；它与正常开发环境的真实官网验收分别记录。

本轮通过正式抓取器观察到 Michelin CN 条件请求返回真实 304；原始 body 与观察时间保留，只追加本次在线验证时间。`live_verified_304` 仍要求匹配的资源、Parser 版本与缓存证据，不能因为存在历史数据库就标记在线成功。其他来源没有返回验证器时，继续走实际 200 查询。

第三轮后端回归已记录 **202 passed、77 subtests passed**，质量增量通过独立审查。故障注入浏览器验证覆盖健康统计、显式隔离原文、未答复/拒绝/允许以及桌面/手机布局；允许后仅返回上次合格的 CN 104Y/104W 两条结果。第三轮 `npm run typecheck` 与 `npm run build` 已通过（Next.js 16.3.6，4/4 静态页）；临时 QA 服务已停止，正常 API/Web 已恢复且保留旧库记录。正常 3000 入口的真实 CN 查询返回在线 304 与 `858877 / 763400` 两条结果；健康面板显示 8 个登记来源（7 个轮胎来源和 EPREL）、隔离列表为空。桌面 1440px 与手机 390px 验收通过，手机无横向溢出、5 个底部导航均可正确点击，console error/warn 为 0。

### 质量记录的使用与边界

第十二轮将小米车型源纳入健康面板。车型采纳前分别检查车型信息、配置版本、轮毂/轴位，任一组的记录或已知字段缺失达到 30% 即隔离；同标识代际、地区或来源身份变化也需核对。配置 ID、前后轴及轮毂归属必须一致，非法结构走 schema 拒收。首份记录没有基线时不虚构损失率。

车型隔离独立保存于 `vehicle_quarantines`，沿用 `/v1/quarantines` 的元信息列表及按需原文读取，包含分组比例与原始对照快照；不进入正式车型证据、车库配置复制或授权回退。授权回退仍只读取上一份已采纳配置。质量隔离是待核验状态，不代表认定官网数据错误；第十五轮增加人工批准后等待在线核验的流程；历史重解析已提供候选与审阅，正式历史重新采纳尚未实现。

第四轮回归为 **230 passed、77 subtests passed**；TypeScript 与最终生产构建通过。真实韩泰来源的人工修订验收脚本通过 7 项检查；参数修改是独立临时库中的明确模拟，不是对官方数据作出纠错结论。桌面/手机浏览器验证了人工值的选择应用、版本冲突、撤销与恢复、历史证据、纯文本显示和关闭窗口后的焦点返回。正常开发入口再次查询真实韩泰 `205/45R17` 返回 `1022631 / 1022632`，核验视图显示来源值 260、人工修订 0；正常开发库没有模拟人工记录。

核验接口为 `GET /v1/tire-variants/{id}/fact-review?source_id=...&mode=history` 与追加操作 `POST /v1/tire-variants/{id}/fact-revisions`。比较默认保持来源值，显式 `include_manual=true` 才返回另列的 `effective_facts` 和修订标记。人工署名是本地工作区自报信息，不等于已完成生产身份认证。

整版本管理使用 `GET /v1/tire-variants/{id}/lifecycle?mode=history` 与 `POST /v1/tire-variants/{id}/lifecycle-events`；撤销/恢复都追加记录，`expected_revision` 防止陈旧表单覆盖。比较接口在 `excluded_variants` 明确列出已撤销版本，只为未撤销项生成对照和冲突。关注记录仍保留，Worker 仍可观察其来源；撤销状态不会被抓取改回，也不会自动影响同型号其他 SKU。

- `/v1/source-health` 只返回轮胎来源最近 24 小时的聚合统计；授权读取历史不会被记为在线成功，不返回会话或查询内容。
- `/v1/quarantines` 只列字段缺失与 Parser/schema 异常记录元信息；打开 `/v1/quarantines/{id}?mode=history` 才读取原文。页面标记 `LOCAL SNAPSHOT` 和未采纳状态，原文仅以文本展示。无法形成合格参数的响应不展示虚构的字段缺失百分比，车型异常可单独筛选。
- `False`、`0` 是已知值；证据定位、源时间等元数据不稀释缺失分母。匹配歧义不会靠行号猜测；隔离记录不能进入在线 304 缓存或离线回退结果。
- 当前实现自动隔离、只读核对、正常数据恢复、非身份参数的人工纠错/字段撤销，以及精确轮胎版本的整实体撤销/恢复；第十五轮增加受绑定约束的人工批准和后续在线采纳，第二十二轮增加历史重解析与未采纳候选审阅。第二十五轮增加指向已有证据版本的身份更正与逻辑合并。任意新身份创建、疑似等价组、历史重新采纳及其他实体类型的完整状态工作流仍待完成。Parser/schema 返回受控错误时，单独保留不超过 8 MiB 的有效 UTF-8 文本，含 NUL 的内容通过二进制字段保存；无响应、超限或不安全元数据不留存。该内容不会进入正式事实、304 缓存、授权回退或比较。
- `/v1/captures?mode=history` 按需列出解析前已提交的接收元信息，`pending_only=true` 筛选处理结果未确认的查询；打开 `/v1/captures/{id}?mode=history` 才读取正文并追加审计。`pending` 可能仍在处理，也可能已经中断，不会据此判定来源失败或自动重放。老查询不补造日志，真实 304 不新增不存在的响应正文。
- **保全边界**：API/Worker 在 Parser 启动前先发布对象，再提交独立数据库事务；该提交之后的进程退出与下游回滚已验证。响应下载中或提交前的退出、真实断电/磁盘故障和云端存储灾备仍未覆盖。现有文本 Adapter 保留解码后文本的 UTF-8 字节，不是压缩或网络传输的原始字节；用户 PDF 收件按上传字节保存。直接运行无数据库的 Adapter canary 不写接收日志。首条没有已采纳基线时不计算字段损失率。

第六轮七源真实 canary 均返回成功；Toyo/Hankook 的 `265/40R20` 筛选结果为零，不代表这两源有匹配 SKU。正常 3000 入口真实 CN 查询返回在线 304、`858877 / 763400`，手机 390px 无横向溢出且 console error/warn 为 0。故障注入仅写独立临时库，正常库保留 12 份快照，人工修订和异常原文均为 0。

第七轮正常入口真实韩泰 `205/45R17` 返回 `1022631 / 1022632`，接收日志显示 922,438 字节和“已完成在线核验”，哈希与正式快照一致。开发库现有 13 份真实快照、1 份接收记录，人工修订与异常原文仍为 0。当时独立临时库验证的是承载查询的宿主进程在解析时退出后，日志仍可读取与筛选；这不等于已经验证 Parser 与宿主隔离，也不能据此宣称厂商发生过中断。第二十二轮的隔离运行器另行验收。

第八轮在独立临时库验证版本撤销、比较排除、关注标记、陈旧表单冲突及手机端恢复；正常入口真实 CN 查询仍返回在线 304，状态窗口显示“未撤销 · 修订 #0”。正常库版本撤销/恢复事件为 0，未对真实产品作模拟撤销。

## 测试事件与同场成绩

“规格比较 → 测试事件”支持录入测试标题、机构、发布日期、测试尺寸、车辆/路面、条件、测试关系和留存依据；每个指标保留原单位与方法，每条成绩必须有短证据摘录和原文定位。可录多种指标、多条参测胎与部分结果，未知保持空值。独立测试、厂商委托和关系未确认分别标记，均属于本地人工记录，**不是自动在线核验结果**。

数值使用有界十进制字符串，保留如 `38.00` 的表示，不计算跨场次总分。参测身份独立于精确 SKU，不能凭型号和尺寸关联产品；成绩不会覆盖厂商事实。比较请求绑定单一事件及当前修订，混入其他场次参测 ID 会拒绝；来源名次只保留已录入值，选录子集不重排，未记录名次不推断，缺少成绩不补零。

创建、修订、撤销和恢复都追加署名、理由及内容指纹，旧记录可按修订号查看。并发或陈旧表单返回 409；撤销事件排除比较但保留历史。列表不加载全部成绩和短摘录；历史最多列最近 100 次并标记截断，指定修订仍可读取。当前没有自动 ADAC/TyreReviews Adapter、测试来源在线授权回退、自动 SKU 关联或跨场归一化推断；本地署名不能替代生产账号。

API 为 `/v1/test-events` 创建/历史分页列表，`/{id}?mode=history&revision=...` 详情，`PUT /{id}` 追加修订，`POST /{id}/state` 撤销/恢复，`POST /{id}/compare?mode=history` 同场比较。链接只作引用，不由服务器抓取；仅接受数值、元信息和有界短摘录，不默认保存全文、图表或登录后 PDF。

`uv run --project apps/api --extra dev python scripts/test_event_acceptance.py` 用 2026-09-27 浏览器核对的 [ADAC 2026 官方页面](https://www.adac.de/rund-ums-fahrzeug/ausstattung-technik-zubehoer/reifen/reifentest/sommerreifen/225-50-r17-2026/) 中三条公开评分，在独立临时库验证录入、同场比较、缺失名次、事实隔离及重启，共 6 项通过。脚本输入是当日手工转录，**执行脚本不会刷新官网**；这些评分不是制动距离，不能迁移到其他尺寸/场次。未保存全文、图片、完整表格或需登录的 PDF，商用转载许可尚未核实。

## 隔离人工确认的使用与边界

在“来源与证据”打开字段/记录缺失的隔离原文，核对原始内容、已采纳参数与本次候选，填写署名、决定依据并确认已核对。可选择“批准，待在线核验”或“保留隔离 / 撤回批准”。本地署名是自报信息，不代表已完成生产审核员认证。

批准不会抓取来源、修改旧隔离记录或直接生成事实。它绑定来源、精确查询、对照快照、原文 SHA-256、URL、MIME、Parser 版本及已知代码包/部署修订、完整候选与质量报告，24 小时内仅能随批准后启动的匹配在线请求消费一次。基线或内容变化须重新核验；相同内容的重复隔离记录共享审批修订，旧表单返回 409。过期、保留隔离、已消费、身份/对齐问题都不能绕过质量门槛；304、离线回退和批准前已启动的请求不能消费批准。

下一次匹配请求通过结构校验后，批准使用记录与新事实同事务提交，失败则一起回滚；新快照保留审批署名、理由和记录引用。原隔离记录始终保留为历史未采纳内容，不能撤写；生效后需使用事实纠错/版本管理处理后续问题。人工确认只允许明确核对的缺失变化，不会合并身份，不能把 Parser/schema 失败或不确定身份强行采纳。历史重解析另有候选与审阅流程；正式历史重新采纳、跨源权威裁决与生产审批权限仍待完成。

### 历史原文重解析

在“来源与证据 → 原文接收日志”打开轮胎、车型或召回接收记录，点击“历史重解析与审阅”。先核对原观察时间、来源、查询范围和所选包的 Parser 版本及代码指纹，再明确发起一次历史处理。默认选项是当前安装源码，与活动部署身份分别显示；旧包只能处理它实际声明的来源，旧八源包不具备 NHTSA 能力。接口只接受收件 ID 和目录中的 Parser，不接受新 URL、上传代码或任意模块；PDF 收件不在此入口的解析范围内。

任务保存原文 SHA-256、字节数、查询范围和当时的正式对照基线。已有对象映射时，读取以对象为准；缺失、损坏或映射错配会记录失败，不使用数据库副本替代。旧数据库收件也先核对哈希与字节数。解析期间不持有数据库写锁；无论成功或失败，任务和完成记录保留独立历史，同一 UUID 不重复执行。宿主中断后超过 120 秒仍无完成记录会显示结果未知，重读不会悄悄重跑。

成功结果可查看候选、字段/记录缺失分母、身份差异和冻结基线。追加“已审阅”“需修复”或“不认可”时填写署名与理由；这是对历史解析的审阅，**不批准事实采纳**，也不会修改原来的查询、在线核验、比较、索引或监控提醒。Parser 本机发布与实际旧包回滚使用下述独立 Gate；正式历史重新采纳尚未实现。修复后的正式数据仍须重新在线查询并通过既有质量门。

运行器采用固定解释器、JSON 管道、净化环境和有界并发。每个 API/Worker 进程最多同时执行 2 个解析子进程；默认正文上限 8 MiB、标准输出 4 MiB、错误输出 64 KiB、8 秒总时限、5 秒用户 CPU 和 384 MiB 内存。具体能力以目录返回的限制与回执为准，平台支持和实测边界见实施计划。子进程不继承模型密钥、代理或数据库环境变量，但仍具有当前 OS 用户的文件权限，不应被当作不可信 Python 代码执行服务。

接口为 `GET /v1/reparse/catalog?mode=history`、`GET /v1/reparse/runs?mode=history`、`POST /v1/reparse/runs`（UUID `Idempotency-Key`）、历史详情及追加 `/reviews`。读取和写入都要求显式历史模式；记录在当前本地工作区可见，本地署名不是生产账号认证。

`uv run --project apps/api --extra dev python scripts/reparse_acceptance.py` 在临时库查询真实韩泰、保全原文、隔离重解析并追加审阅，不调用模型。`scripts/reparse_browser_qa.py` 使用合成传输、真实已部署 Parser 和临时库，只提供 8001 端口的独立浏览器验收服务；它不连接厂商，也不写正常开发数据。

接口为 `GET /v1/quarantines/{id}/review?mode=history` 与 `POST /v1/quarantines/{id}/reviews`；写入要求 `action`、`expected_revision`、`operator`、`reason` 和严格布尔 `confirmed_loss=true`。审批历史最多返回最近 100 条并标记截断；记录不删除。`keep_quarantined` 撤回该内容/基线待生效的批准，不是永久禁用该来源。

## 车库记录的使用与边界

在“我的车库”手工添加车辆，或在“车型适配”核验配置后选择“将此配置存入车库”。轮胎卡片的“记入车库”按实际安装情况记录前/后轴；已填写尺寸须与精确 SKU 一致，R/ZR 分别保留。尚无尺寸时，用户显式选择当前轮胎会同时保存该 SKU 的尺寸；这不构成 OE 或安全适配认证。

车库记录独立于官方事实库，保存/编辑不会自动抓取或修改官方配置。由车库按尺寸跳转只填入查询条件，仍需自行选择型号、地区并发起在线查询。年款未知保持空值；复制时优先使用明确的所选配置年款，不从代际名称猜测。编辑来源复制的车辆后标记为用户记录，原参考快照继续保留。

API 提供 `/v1/garage` 列表/创建、`/from-fitment` 配置复制、`/{id}?mode=history` 历史、`PUT /{id}` 编辑，以及 `/{id}/tires` 与 `/{id}/state`。写入使用 `expected_revision` 防止覆盖，历史只追加。当前是一个本地共享工作区，**不是会话私有车库或多租户账户隔离**；云端账号和外部通知尚待完成。不收集 VIN/车牌字段。

第九轮真实来源验收选中当前 SU7 官方标配，前 `245/45R19`、后 `265/45R19`，年款为 null；模拟车库记录只写临时库，6 项检查通过。它不代表首代 SU7 Golden Case，也不表示用户持有该车辆。正常开发库保持空车库。

## 保存比较与驾驶偏好

在“规格比较”核对所选 SKU 后，选择“保存本次比较”。服务端在同一事务锁内重新计算比较并校验 `expected_fingerprint`；事实、人工修订、版本状态或字段规则/候选变化时返回 409，需重新核对。保存时固定参数、证据版本、字段默认值及全部候选依据和冲突明细；后续来源更新不会替换记录。旧比较缺少字段权威信息时明确显示未记录，不以当前规则补算。版本后来撤销时另外提示当前状态，保存时内容仍保留。

`/v1/saved-comparisons` 提供保存和分页元信息列表，`/{id}?mode=history` 按需读取固定内容与说明历史，`PUT /{id}`、`POST /{id}/state` 修改说明或归档/恢复。描述操作使用 `expected_revision`，不改变固定事实。保存内容限 8 MiB；原文通过既有证据引用读取。

“我的车库”内可设置干地、湿地、静音、舒适、耐磨、能耗、外观七项权重，均为 0–100 整数且合计 100。示例只填表，不自动保存。`GET/PUT /v1/driving-preferences` 与 `POST /v1/driving-preferences/clear` 保留追加历史，换会话或重启仍保留。当前仅保存偏好，**推荐评分、个性化排序和信息流尚未实现**。

第十轮真实韩泰两项 SKU 的临时库验收通过 6 项检查。独立合成浏览器场景验证了来源更新后旧保存被拒绝、已保存值保持不变、说明历史和偏好清除；修复重复证据卡片与 120 字符连续名称溢出。正常入口仅显示空记录/未设置偏好，保留 13 份真实快照、1 份原文接收记录，未混入模拟个人数据。

## 监控规则与站内提醒

在“我的关注”下方创建规则，选择来源、型号、可选尺寸，可从当前关注列表选择同来源精确 SKU。检查间隔为 4–168 小时，默认 6 小时；默认暂停，显式勾选启用后等待 Worker 调度。相同查询共享抓取任务，采用当前已启用规则中最短的间隔。字段过滤使用参数键，留空表示全部业务参数。可另设技术条件，例如 `Acoustic`；只对 SKU 身份中的完整技术值做规范化匹配，营销文案、未知值和 `Foam` 不会被当成 Acoustic。技术条件与其它筛选同时满足才触发，并随规则修订保存。

规则只匹配启用后新采纳的变化，不扫描旧变更补发。`variant_observed` 表示本库首次观察该来源规格，不能解释为厂商新品发布；`facts_changed` 保留变更前后值及缺失状态。页面内容变化但业务参数不变、未通过质量隔离或查询失败时，不产生参数提醒。提醒与事实同事务写入，以规则/变更 ID 去重；普通在线查询和 Worker 均可触发。暂停或归档不删除历史提醒，恢复归档规则后仍为暂停状态。

`/v1/alert-rules` 提供创建/分页列表，`/{id}?mode=history` 读取历史，`PUT /{id}` 编辑，`POST /{id}/state` 归档/恢复；写入使用 `expected_revision`。来源/查询/SKU 是规则固定目标，更换目标需新建规则。`GET /v1/notifications` 与 `PUT /{id}/read` 提供站内提醒和已读状态，保留当时规则修订及前后来源快照。所有记录当前属于本地共享工作区，不是账户私有通知。

第十一轮真实韩泰调度验收 6 项通过；故障和规则变更场景另在合成临时库验证。正常开发库六张轮胎监控表均为空，未启动持久后台 Worker。第二十六轮另设独立召回域，支持所选公告的变化监控；第四十三轮增加名称检索范围的持续候选发现，见下文。名称匹配不承诺整个品牌的精确覆盖或官方新发布识别。独立测试/车型事件、优先级摘要、外部渠道投递重试、长期运行心跳或调度服务托管仍待完成。未配置来源不会凭空产生这些提醒。

### 变化解释与自然语言规则草稿

每条站内提醒可选择“解释这次变化”，先核对事件的前后快照和字段差异，再单独授权分析。事实文字由冻结差异生成，保留“字段未声明”“明确未知”和数值之间的区别；模型只补充带引用的推断与不确定性。首次观察限定为本系统在该来源首次记录该精确版本，不代表新品发布。解释使用历史证据，不重新获取当前参数，不发送规则名称等私人配置。

“用自然语言起草监控规则”先选择已接入来源、输入需求，服务端在本地冻结原文、型号目录和支持能力。允许外部处理后才调用 Responses。规则意图按非公开工作区数据处理，除了模型配置还需 `TI_AI_ALLOW_PRIVATE=1`；不会沿用之前的分析或向量授权。

模型输出仅为待审草稿，默认暂停；未解决的条件、频率或渠道会阻止直接应用。无未解决项时，可打开审核表单修改完整规则，核对原始需求后确认保存，也可主动勾选启用。保存将规则与父草稿、最终人工修改及审计一起写入，同一草稿重复确认只产生一个规则。明确条件的保守校验不等于理解所有自然语言，用户仍需核对原文与最终范围。

草稿使用 `/v1/ai/rule-draft-packs` 准备、`/v1/ai/rule-drafts` 生成/读取会话历史、`/{id}/apply` 确认应用。生成与应用分别使用 UUID 幂等键，共用现有 AI 调用预算；调用失败或未知用量保留预留，不能自动重试或自动创建规则。变化证据使用 `kind:change_event` 与精确 `change_id` 接入原证据包接口。

本轮的模型流程使用隔离合成供应商验证，真实 OpenAI 输出质量未验收。自动批量解释与外部通知投递尚未实现；当前保存/启用仍是用户明确操作，定时运行仍依赖独立 Worker。

## PWA 的本地验证

保持 API 运行，先停止 `next dev`，再执行 `npm run build` 和 `npm run start`。在固定的 localhost/127.0.0.1 来源下打开网页，首次联网完成静态资源安装后，支持的浏览器会显示“安装胎迹”；也可使用浏览器的安装菜单。localhost 用于安全上下文验收，其他部署需要 HTTPS；本地 PoC 的 API 仍不应直接暴露公网。

构建脚本生成图标与 `/sw.js`，按构建 ID 缓存明确列出的静态资源；若首页不再是完整静态预渲染，构建会失败。API、原始证据、授权、RSC、带查询参数或跨来源请求均不进入此缓存。第46轮已实现单独预览和授权保存的设备离线包，以非导出WebCrypto密钥加密IndexedDB；断网打开外壳后，可主动进入“设备离线资料库”检索冻结历史。保存或阅读授权不会自动授权在线查询使用历史参数。

新版本在后台完成静态资源准备后等待用户点击“更新应用并重新载入”，随后清理旧外壳缓存。开发模式注销本应用 `/sw.js` 并清理 `tire-shell-` 缓存，避免开发页面受旧生产版本影响。`npm run test:pwa` 验证这些缓存边界；Chromium 已验证安装提示、更新、停止服务后的离线重载和恢复，Windows/iOS/Android 等设备的实际安装仍需后续验收。

## 原文对象、PDF 收件与备份

在“来源与证据 → 原始 PDF 文档”选择文件，填写名称、留存署名和保存授权依据；来源 HTTPS 链接可留空，填写后也不会自动访问。最多 8 MiB，只检查 `%PDF-` 文件标识，**未验证 PDF 结构、未解析/OCR、未核验内容**。保存后属于本地共享工作区的原文收件，不会成为轮胎、车型或 AI 知识事实。下载前服务端与浏览器分别检查 SHA-256 和长度，作为附件下载，不在页面内执行文件。

`POST /v1/documents` 接收 `application/pdf` 字节和 `X-Evidence-Metadata`（UTF-8 JSON 的 base64）；`GET /v1/documents?mode=history` 只列元信息，`GET /v1/documents/{id}/content?mode=history` 校验后返回附件并记录审计。相同字节共用对象，各次收件说明独立保留。当前不支持删除、说明更正、解析审批或文档事实采纳。

新接收原文按 `sha256/<前两位>/<完整哈希>` 存储。文件系统使用临时文件、fsync 和原子无覆盖链接；S3 使用条件写入和读取校验。对象缺失或损坏会拒绝读取，不静默回退数据库副本，也不覆盖同键损坏对象。旧接收记录继续使用 `database_legacy`；现有快照与文本副本仍留在数据库，尚未执行全量外置或回填。

**备份须同时包含数据库与对象目录/桶**。本地 SQLite 默认为 `data/dev.db` 和 `data/dev.db.objects`；备份时停止 API/Worker 写入后保存数据库（使用 SQLite backup 或完整停库后的文件）与对应对象目录。恢复到匹配的数据库和存储配置后，按引用哈希与字节数校验对象；不能只恢复数据库或在不迁移对象的情况下切换后端。PG 验收脚本已演示数据库恢复及配套对象副本校验，生产一致性备份、桶版本/保留期/WORM 和灾备演练仍待完成。

日常快照可使用可执行备份入口（第61轮 G2-3 交付）：`uv run --project apps/api python scripts/backup_dev.py` 以只读连接对运行中的正常库做 SQLite backup，并复制对象目录与 Parser 封存包，输出带 schema 版本、字节数与行数清单的 `manifest.json`；目标目录已存在时拒绝覆盖。它不代替上段的生产一致性备份要求。

`uv run --project apps/api --extra dev python scripts/object_store_acceptance.py` 在独立临时库中显式查询真实韩泰，核对解析前对象、正式快照哈希、合成 PDF 字节往返和重启持久性；本轮 6 项通过。S3/R2 只通过 SDK Stubber 协议测试，没有真实云端验收。对象先于数据库提交，失败可能留下未引用对象，尚无垃圾回收；应用无覆盖不等于存储管理员无法修改或断电持久性保证。

## Parser 本机受控发布与回滚

身份治理的使用方式与边界见下方“精确版本身份核对”；Parser 发布不会自动创建身份更正或合并决定。

正常 API/Worker 在首次请求某个可用来源时，将当前受信 `tire_api` Python 源码封存为具体内容寻址包，并为该来源创建部署修订 1。之后修改当前源码不会自动替换已选包；要先封存候选、评估、审批，再显式切换。已封存代码损坏、缺失或环境不兼容时停止解析，不回退到当前源码。

设置 `TI_PARSER_BUNDLE_ROOT` 指向 API/Worker 共享的服务私有目录；默认是进程工作目录下的 `data/parser-bundles`。备份时必须同时保存数据库、原文对象与此目录。包包含全部 Python 源码与文件哈希，不包括依赖安装包；当前采用精确 Python、操作系统/架构、协议、资源策略和**全部已安装 Python 分发包版本**兼容检查。环境升级后旧包可能被拒绝，须保留兼容运行环境；这不是跨环境的完整容器镜像。

在“来源与证据 → 管理解析器发布”选择来源，查看当前部署、历史修订、已登记代码包和原文样本。选择包与1–3份同来源原文后可显式评估；查看候选/对照、同原文正式参考或缺口、质量差异及执行回执，再署名审批。批准不切换部署，激活、暂停、恢复、回滚和首次初始化均需单独确认。质量阻断不能批准，参考缺口另行确认；过期修订须重新读取。

Web 只使用已登记受信包。封存新候选仍使用本机 CLI：把署名请求保存到本地 JSON 文件，例如 `{"operator":"审核人","reason":"本次变更依据"}`，使用正常 API 同一数据库环境执行：

```powershell
uv run --project apps/api python scripts/parser_release.py import-deployed --request signature.json
uv run --project apps/api python scripts/parser_release.py list
```

`import-deployed` 只能封存当前受信安装的固定包，不能指定源码目录或上传 Python。封存本身不启用候选。其余 CLI 动作为 `bootstrap --source <source_id>`、`evaluate`、`review --evaluation <id>`、`transition --source <source_id>`；请求写在 `--request` 指定的有界 JSON 文件中，评估与切换还必须提供 UUID `--idempotency-key`。CLI 与 HTTP 使用相同 Gate：

| API | 用途与关键字段 |
| --- | --- |
| `GET /v1/parser-bundles?mode=history` | 已登记包与环境、版本、指纹；不接受 HTTP 代码导入 |
| `GET /v1/parser-deployments/{source_id}?mode=history` | 当前状态及部署修订历史；读取不封存或抓取 |
| `POST /v1/parser-evaluations` | `mode:"history"`、`source_id`、`target_bundle_id`、1–3 个 `capture_ids`、`expected_deployment_revision`；UUID 幂等键。轮胎/车型发布还须同时传 `golden_set_id / expected_golden_set_revision / golden_set_fingerprint`，`capture_ids` 与冻结集全量一致；不传时只能做相对回归，不能新批准发布 |
| `POST /v1/parser-evaluations/{id}/reviews` | `mode:"history"`、`expected_revision`、`completion_fingerprint`、`action:"approve"/"reject"`、`acknowledged:true`、署名与理由 |
| `POST /v1/parser-deployments/{source_id}/transitions` | `action`、`expected_revision`、署名与理由，UUID 幂等键；激活还需目标包、评估 ID 与审批修订；回滚仅接受 `target_revision` |
| `GET /v1/parser-executions/{query_id}?mode=history` | 网络前的固定选择、本次成功/失败回执，以及查询最终状态；解析完成不等于已采纳 |

评估对同一历史原文运行候选和当前对照包，优先使用这份原文当时产生的正式快照作为参考。没有同原文正式参考时明确列出缺口，审批必须增加 `acknowledge_reference_gaps:true`；不能把当前最新快照当旧原文真值。解析/完整性/schema 失败或身份漂移会阻止批准；轮胎/车型保留原 30% 相对损失门，并要求下述人工 Golden 精确门通过才能新批准或部署。可信召回没有本轮 Golden 类型，明确为 `not_applicable / legacy_recall_regression`，继续原有严格回归、参考缺口与最新审核约束；已知成员或纳入评估的已知安全字段只要缺失即阻断。历史重解析的“已审阅”不能用作发布批准。

激活动作为 `activate`，必须绑定 `target_bundle_id`、`evaluation_id`、`expected_review_revision`，且评估所依据的部署修订仍为当前。`pause` 阻止后续来源请求；即使存档包损坏仍可暂停。`resume` 重新校验包和适用审批。`rollback` 只能指向该来源曾经活动的历史修订，并追加新修订；它实际执行封存旧代码，不修改旧事实或回退数据库。切换动作本身不访问官网，也不采纳候选。

在线请求在网络前固定代码包与部署修订；采纳时在同一数据库锁内再次核对。A→B→A 后，第一次 A 的晚到结果仍不采纳，但已提交原文和执行回执保留。304 必须匹配完整代码与部署修订，旧身份未知记录以及切换/回滚后首个请求必须取得新正文。相同正文换部署身份创建新证据快照；业务值不变不重复增加事实版本。Worker 租约检查继续生效。

### 人工 Golden 候选与冻结集合

在“来源与证据 → 管理 Golden 样本”选择轮胎或车型的已保存原文，查看 SHA-256 与原文内容后填写预期 JSON。复制已保存解析候选只生成待审草稿，轮胎 `golden_sku_id` 留空待人工定义；保存候选不会批准、采纳事实、访问官网或调用模型。轮胎 `value` 须显式填写全部 `VariantInput` 顶层字段，未知使用 null；真实审核还需逐项对照原文，不能将解析输出本身当作正确性依据。

车型预期只包含 `vehicle / trims / fitments` 三组；`vehicle` 使用实际 `model` 与结构化 `manufacturer`，代际、年款、区域与前后轴均须明确。组内字段与完整成员集合精确核对，只排除证据定位字段；顶层 `coverage / documents / footnotes` 保留在候选中，不属于本轮车型 Golden 断言。数值按 JSON number 比较，19 与 19.0 相等；布尔、字符串、null 与字段缺失仍分别判断，数值差异不使用近似容差。

保存后单独填写署名与依据并确认审核。署名为本机操作者自报，不是身份认证或数字签名。选取同来源、同种类、1–3 份不同原文的已审核案例后再次确认冻结。所有写入绑定 UUID、修订和指纹；响应未知时保留原请求重试，陈旧请求须重新读取。新内容、审核或撤回会使旧冻结集合不再满足发布要求，先撤回再重新批准也不会恢复旧集合；历史修订仍可查看。

发布页选择整个冻结集合，评估输入绑定案例、审核、原文、比较器摘要和 Parser 完整执行摘要。轮胎精确字段/身份集合必须一致，所有不同 SKU 对都须完成领域 `identity_key` 检查；只有一个 SKU、无法对应或执行失败时不显示“零错合并通过”。车型通过只证明三组结构，不声称轮胎零错合并。任何字段错误、漏行、替换或碰撞都会阻断，参考缺口确认不能豁免 Golden 失败。

轮胎/车型新 `approve / activate / resume / rollback` 都重新核对有效冻结集、完整结果、当前包与执行环境。首次受信源码 bootstrap 可供初始查询，但明确 Golden 未验证，不能经恢复或回滚 bootstrap 绕过门槛；暂停始终可用。源码、比较契约或执行宿主变化后需重评。可信召回保留上文明确标识的不适用路径，不能将它用于轮胎、车型或未知来源。

本轮交付的是人工工作流和有界精确比较能力。真实人工审核样本仍为 0；自动验收署名均明确为合成测试。测试事件、跨来源集合、代表性覆盖和完整生产 Golden Data 仍待完成。第38轮另行将产品代码命名空间纳入现行身份合同，保留全部旧身份和引用，详见下文。

### 产品代码命名空间与旧身份迁移

新采纳的 `variant-identity@2` 将明确的 `facts.product_code_type` 纳入身份键；同数字的 CAI、MSPN、MATERIAL_CODE、PRODUCT_CODE、IP_CODE 不再共享键。代码类型不根据来源或数字猜测，不归一大小写或别名；前导零、R/ZR 和已有版本字段继续保留。代码类型未知时，记录仍按来源、查询及行保留临时身份，不因同代码自动合并。韩泰、Toyo、Pirelli Parser 升至 `1.1.0`，新类型均有对应原文字段定位。

旧实体的 UUID、原身份 JSON、键、事实、快照、关注与监控引用保持原样。新增的 `variant_identity_bindings` 独立保存现行身份，`variant_identity_migration_applications` 保存固定预览、署名及应用回执。来源与证据页的“预览身份迁移”核对全部历史原文、正式核验、快照成员和事实；只有证据一致、类型明确、键唯一的记录可追加绑定。未知或混合类型继续待核对，后续来源新观察可形成独立实体，并仅列出尚未确认的关联候选，不自动接管旧关注或提醒。

迁移预览只读；应用需要明确确认、署名、理由、修订号和指纹，并使用固定 UUID 幂等键。响应丢失后通过“核对同一次迁移应用”恢复原结果，不重复创建回执。署名是本机自报，此操作不是人工 Golden 真值审核。旧身份未完成迁移评估时，采纳遇到原键会阻断并保留已接收原文；旧快照不能直接复用 304，首次新 200 建立 v2 快照后才能条件核验。

API 为 `GET /v1/identity-contract/migration-preview?mode=history`、`POST /v1/identity-contract/migration-applications`，以及同路径的历史列表和详情。CLI 可执行 `uv run --project apps/api python scripts/identity_contract.py preview`；预览不会初始化数据库，首次升级须先启动 API 完成兼容 schema 迁移。`apply` 要求显式 `--request <JSON文件>` 和 `--idempotency-key <UUID>`；不要使用删除数据库或重写旧身份的方式升级。

页面从独立 `identity_contract` 显示现行、待核对和关联提示，不从参数事实反推身份。普通/混合知识结果显示检索时合同，AI 证据和报告显示保存时合同；旧完成内容不回填。缺少有效合同的旧待执行 AI 证据必须重新准备并重新授权。人工身份决定升级为 `identity-resolution@2`，旧非 clear 决定需复核；相同代码只有类型已知且一致才是合并依据，已知类型冲突不能由相同 GTIN 消除。

### 字段权威、默认展示与冲突中心

`field-authority@1` 对同一精确SKU逐字段给出展示依据：EU标签优先已登记监管记录，UTQG与产品代码优先厂商记录，静音等技术还须具体SKU的字段证据。规则目录同时说明OE、召回、测试及交易信息的来源层级；目录不表示这些来源已全部接入，人工填写的组织名称不会使记录变成官方或独立测试权威。

选择顺序为字段权威、精确身份、地区、可靠发表或原文观察时间、证据完整度。304只更新核验时间，不当作新事实发布时间。相同层级仍有不同取值时不选赢家；missing/null是证据缺口，false、0、字符串与原单位保持各自语义。相同字面产品代码的不同命名空间或地区不会自动分组。不同来源的报价、库存和在售声明属于各自交易范围，当前没有统一Offering实体，不把它们当成SKU技术参数的矛盾来选默认值。

在“来源与证据”打开字段冲突中心，可按字段与来源筛选，查看默认值或“无法确定”、全部候选、出处、时间、规则版本和五项依据。来源筛选只选择包含该来源的冲突，仍保留竞争候选。可以打开候选自身的原文或对指定来源/字段进入现有“核验与纠错”；实体疑问进入身份核对。中心只读，不新增人工裁决表，也不提供任意提高网站等级的编辑器。

候选保留原SKU、来源、当前正式目录成员的快照与对应事实版本；同一来源不同查询中仍有效的成员分别核对，不以一份查询的最新结果覆盖其它查询。原文或元数据变化但业务参数未变时，可引用新快照和原事实版本；后续304沿用对应快照，不重写已冻结比较。普通来源卡片把技术字段默认值与原快照参数分开显示，身份字段仍按独立v2合同核对；旧身份待核对时不给默认值。

`field_resolution`是独立展示结果，原`facts`、人工`effective_facts`和身份不改。规格比较使用服务端技术字段默认值并保留冲突，无默认时不会退回最新来源某一侧的值。明确采用仍有效的人工merge时，本次已选择的双方证据保留原ID并进入展示组；correct、clear、陈旧决定和未选祖先不作为等价事实汇聚。已保存比较冻结当时的候选与依据，后续来源变化不会回填。

普通live/304只评估本次已授权来源；跨来源核对须显式历史入口。知识结果显示检索时依据，AI包只对已选证据冻结字段决策；未选证据继续仅提示存在冲突并按需要升级private，不外发其值、来源或URL。AI使用包内共享材料无损去重，44KB限制保持；旧待执行包缺少字段合同或规则变化时要求重新准备并重新授权。报告正文和Markdown/HTML/PDF导出保留保存时的默认值、候选与未解决冲突，旧记录不补算新策略。

只读API：`GET /v1/field-policies`、`GET /v1/field-conflicts?mode=history&field=utqg_treadwear&source_id=...&offset=0&limit=20`、`GET /v1/tire-variants/{id}/field-resolution?mode=history`。冲突列表要求显式history，字段与来源须来自登记目录，分页最多100项；这些历史结果不代表当前库存或自动选胎结论。

第39轮最终浏览器证据位于 `.artifacts/field-authority/round39-browser-final-20261001-014530-4a0813c8/`：报告为 **5项UI/3项HTTP通过**，9次几何检查覆盖1440/1440与390/390；实际核看的截图清楚显示默认300、另一来源500及平级无默认值。私有合成来源调用共10次，包含6次种子采纳、2次UI条件核验及元数据更新后的200/304；未改旧证据，固定保存比较1份，未执行人工纠错写入或真实模型/Parser。首轮选择器失败与中间成功证据保留，不覆盖失败或将重跑次数相加。

评估与部署切换若丢失响应，会在当前标签页内保留相同 UUID 和固定请求；关闭、重开弹窗后可继续核对。同一请求不会变成新任务。整页刷新会清除这份内存状态，应先查看部署/评估历史；审批冲突或结果未知时锁定表单，重新读取后再次确认。

原文接收日志的“重解析与审阅”支持选择已登记旧包，默认选项明确是“当前安装源码”，不代表当前活动部署。已保存结果另行展示它实际使用的包，与新任务选择分开。API 也支持可选 `bundle_id`：先用 `GET /v1/reparse/catalog?mode=history&bundle_id=<id>` 查询该包的描述，再将包 ID、版本与指纹一同提交 `/v1/reparse/runs`。不会更改活动部署，仍始终是未采纳历史候选。上线前未封存的旧代码不能凭版本标签恢复。历史输入仍须符合当前固定来源的查询、URL 与 MIME 契约；来源迁址后的旧契约兼容尚未扩展，回滚代码不会回滚网络访问白名单。

独立验收可执行 `uv run --project apps/api --extra dev python scripts/parser_release_acceptance.py`。它在临时数据库、私有包目录中显式访问真实韩泰，验证同代码包的修订 1→2→3、评估/审批和真实执行回执，并核对真实小米车型的封存包、原文与回执。A/B 不同代码再回滚 A 的验证使用临时受信源码及录制原文测试，两类证据分别记录。没有真实模型调用、正常数据库写入或对外发布。当前仍是 loopback 单人工作区，自报署名不是生产认证；OS 网络/文件权限沙箱、Linux 实机、生产多角色发布权限与数据库降级仍待验收。

`scripts/canary.py` 是无数据库的当前安装源码探针，结果明确记录 `installed_tire_source_code_without_database_deployment`，不能代表活动发布包，也不读取工作区数据库中的来源启用/暂停/归档设置。`--all-sources`仅检查状态为ready的已登记轮胎Adapter，不包含独立召回或车型目录；没有可检查的轮胎来源时退出失败。显式选择未知、未配置或非轮胎来源会返回明确原因，不发起对应查询。它按运行器容量限制并发；`--revalidate`再次获取正文，第二次核验失败也使命令退出失败。无部署修订时不会发送条件验证器，未经证明的304不视为成功。

## NHTSA 轮胎召回公告

从“来源与证据 → 查询与监控召回公告”进入。默认关键词和 `23T001000` 只是可编辑示例，打开面板不自动请求。先在“按品牌或型号找公告”输入关键词并在线查询，每页最多 10 个产品候选；翻页是新的独立查询。本页未返回候选不能推导其他页、其他地区或具体轮胎没有召回。选用候选公告编号只会填入编号输入框，仍须显式点击“在线核验公告”，才保存该公告的正式召回证据与修订。

仅接受 `两位数字 + T + 六位数字` 的轮胎类公告编号。来源范围是美国 NHTSA，不代表中国、欧洲或全球全部召回。名称、型号、尺寸相同均不足以判定某个精确 SKU 或手中轮胎受影响；缺少 DOT/TIN、生产批次和官方适用范围时保持 `not_assessed`。不需要 VIN 或个人信息，不将召回候选写入轮胎身份、参数事实或车型适配结果。

公告保留厂家、品牌/型号、官方日期、Summary、Consequence、Remedy、Notes 与各产品记录。名称检索还保留官方关联产品及文件地址；均作为文本按需展开，不执行来源脚本。旧公告接口的 `ReportReceivedDate` 按 **DD/MM/YYYY** 解读，`report_received_date` 保存规范 ISO 日期，`report_received_date_raw` 保留原文；`ModelYear=9999` 也保留原始值，不当作轮胎生产年。来源 URL、原文 SHA-256、Parser 版本/身份、原文观察与本次核验时间可独立核对。

在线失败默认请求一次回退授权：允许后才读本地历史，拒绝则保持无结果。授权绑定当前会话、来源及完整查询，5 分钟有效、仅消费一次；名称关键词和页码、公告编号各自绑定，不能串用。更改输入或关闭面板会取消前端等待，晚到结果不能进入新查询。“已保存的历史”是明确的本地入口，始终标记 `LOCAL SNAPSHOT`；历史核验时间不冒充本次在线时间。真实 304 须匹配请求时的原响应及 Parser 身份，并在入库锁内确认它仍是最新快照；迟到 304 不能重新确认已被替代的缓存。有效空响应、来源失败、正文缺失都不会自动撤销旧公告或生成“安全 / 召回解除”结论。

“公告监控”只跟踪**已选定的公告编号**，规则与站内提醒属于当前浏览器会话。默认暂停，可显式启用、调整 1–168 小时检查间隔、追加修订、归档及恢复为暂停状态。`first_observed` 表示本系统首次观察，不代表官方新发布；`content_changed` 保留完整变化前后记录与证据。已读标记只管理本地提醒，不向外部发送消息。监控使用既有独立 Worker，页面不会自行启动它；API 与 Worker 须使用同一数据库和对象存储：

```powershell
uv run --project apps/api python apps/worker/monitor.py --once
uv run --project apps/api python apps/worker/monitor.py
```

“名称发现监控”从已查询或历史页面的“持续发现这些关键词的召回候选”进入，也可手动创建。规则只保存规范关键词，不限于当时页码；默认暂停，启用须明确保存。同会话相同关键词共享扫描，首次完整扫描只建立基线，不批量通知旧公告。后续完整扫描对该任务从未观察到的公告编号提醒一次，并保留所有匹配产品及双遍页证据；消失后再出现不重复提醒，已读不代表已核验。规则保存支持同一 UUID 核对原操作修订和当前状态。

每轮从第一页连续遍历，完成后再遍历一次；产品身份、分页 total 与两遍内容均须一致。最多每遍 20 页/200 产品、总计 40 次页面操作、累计原文 64 MiB（304 计入复用正文）；这不是 HTTP 请求数。应用在扫描及最终候选/通知写入阶段持续检查 300 秒预算，超时回滚本次正式结果，只保留已取得的页证据，再记录未完成终态。检查覆盖到调用数据库 commit 前，不能据此声称能取消已开始的数据库提交；界面的“扫描与核对用时”截止于不可变扫描记录构造时，不含其后写入和提交尾部。页失败、重复产品、范围超限、内容或 Parser 漂移均不推进完整基线或产生新增提醒。完整表示双遍观察一致，不代表官方原子快照、整个品牌覆盖或没有安全风险。

名称扫描与所选公告队列共同占用 NHTSA 来源，沿用来源间隔和受限重试。规则在途变更仍保留来源占用，旧执行返回后拒绝采纳并释放；最终提交同时检查规则、来源代次、已保存的 Parser 选择和预算。任务中心新增 `recall_discovery`，Web 使用真实 SSE、原生桥使用同游标 REST；阶段仍为领取、执行、结束，覆盖情况与逐页 query/snapshot/verification 另行展示。候选“选用此编号”只切换到在线输入，必须再次明确点击核验，不会自动采纳公告、关联 SKU 或创建固定公告规则。

接口为 `/v1/recall-discovery-rules`、`/v1/recall-discovery-rules/{id}/revisions`、`/v1/recall-discovery-runs?job_id=...&mode=history`、`/v1/recall-discovery-runs/{id}?mode=history` 与 `/v1/recall-discovery-notifications`，均按当前会话限制；扫描页和列表有独立分页。`008_recall_discovery_monitoring` 只追加七张业务表和两张专用任务记录表，共用既有任务协议与生命周期，旧两类任务的数据库约束和游标保持。

正式来源 ID 为 `nhtsa-us-recalls`，仅允许两个固定官方 HTTPS 查询入口：[按名称查询轮胎产品](https://api.nhtsa.gov/tires/bySearch)（固定 `query`、`dataSet=safetyIssues`、`data=recalls` 和分页/排序参数），以及[按公告编号核验](https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=23T001000)。`campaignNumber` 有官方公开文档；`tires/bySearch` 是官方现行网页使用的站内接口，[datasets-and-apis](https://www.nhtsa.gov/nhtsa-datasets-and-apis#recalls) 未承诺其公开稳定性，自由文本名称检索不等于受保证的品牌/型号精确匹配。请求显式发送 `Accept: application/json`，不接受任意 URL。已核验 API 主机的 `/robots.txt` 当前返回 403，按 RFC 9309 §2.3.1.3 对 robots 资源的不可用 4xx 语义，仅在这一固定来源将 403/404/410 视为未提供规则；若成功返回 robots 正文，仍解析并遵守其规则。robots 的 429、网络和 5xx 故障，以及实际 API 的 403/429/5xx 均不会被当作有效数据；受限重试仍失败后停止本次获取。此例外不改变其他来源的访问策略。

NHTSA 首次使用会 bootstrap 当前受信安装代码的封存包，并记录查询固定的部署身份与真实子进程回执。已有固定包不会因代码更新或服务重启而自动升级。召回原文现可在接收日志中选择“历史重解析”，使用已登记包生成未采纳候选，再通过独立的“管理解析器发布”评估、审批、激活或回滚。旧八源包仍可运行原来源，但不能执行 NHTSA；含召回的新九源包同时服务公告与名称检索两个入口。

召回历史重解析冻结同查询最新正式快照作为比较基线；发布评估则按接收记录的 `query_id`、来源、规范查询、原文 SHA-256、URL 与 MIME 关联该次原文自己的正式快照，不把后来取得的内容冒充同原文真值。没有正式参考时显示缺口，审批须明确确认。公告记录列表与名称检索页保留各自形状，`products`、`campaigns`、`documents`、`associated_products` 四组独立比较；已知成员或纳入评估的已知安全字段缺失、身份/分页漂移、无法稳定对齐都会阻断发布，不能由其他新增行抵消。重复或未知身份不会折叠为可安全对齐的一条记录。非空正文修正会显示差异，保留人工核对后批准的路径。评估仅覆盖明确选择的 1–3 份原文，并不自动保证两个查询入口或完整 Golden Set 都已覆盖。

审阅候选不等于批准发布；发布或回滚只影响后续请求，不写回历史公告、不刷新核验时间、不生成召回事件或提醒。所有候选保持 `not_assessed`。独立真实来源演练可运行 `uv run --project apps/api --extra dev python scripts/recall_parser_acceptance.py`：使用临时库和两个仅注释不同的受信代码包验证封存身份的 A→B→A，官方内容保持原样；不同输出行为与损失阻断另用合成数据验证。第45轮已将正式公告和空观察接入 AI 证据包、知识索引与冻结报告，采用只选择公告事实的合同；名称发现能力不承诺全球新公告全量监控，中国/欧洲召回来源、实物适用性核验和外部通知仍是剩余工作。

第二十七轮真实官方重解析/发布演练通过 **8 项检查**：在独立临时库对 `XCELLENT ROADBREAKER` 名称检索及 `26T008000` 公告执行两个入口的 A→B→A，6 次在线隔离 Parser 均完成并回收。B 仅修改本地受信包注释，官方正文及解析语义保持不变；因此验证的是代码包切换与证据保全，行为差异和损失阻断另由合成数据验证。重解析、审阅、评估和发布均不采纳历史候选，只有后续真实在线请求产生新快照；轮胎事实和模型调用均为 0。`scripts/recall_reparse_browser_qa.py --self-test` 另通过 **7 组合成传输与真实封存子进程检查**，不等于实际浏览器或官网验收。证据见[第二十七轮计划与验收记录](docs/plans/2026-09-26-tire-intelligence.md#2026-09-28-第二十七轮计划召回历史重解析与-parser-发布升级)。第二十六轮原有 **6 项**真实召回链和 **41 项** PostgreSQL 检查保留为历史结果，不与本轮相加；`uv run --project apps/api --extra dev python scripts/recall_acceptance.py` 可独立复核原召回来源链。

## 精确版本身份核对

在轮胎卡片的“版本状态 → 核对身份更正与合并”选择已有正式证据的目标SKU。先查看双方完整身份与来源事实版本，再逐项解释差异、选择覆盖双方的快照、填写原文位置、署名与理由。只保存追加的本机决定，原始ID、快照、事实版本、关注和监控规则保持原引用。

也可从“来源与证据 → 精确版本身份 → 查找历史版本”按品牌、型号或产品代码打开已有记录；点击入口后才加载历史目录，每页20个版本。此入口与会话关注列表独立。

“身份更正”必须存在可说明的身份差异；“重复版本合并”要求相同且格式有效的厂商产品代码、GTIN或EPREL编号之一，任何已知身份矛盾都会拒绝。GTIN必须是合法长度与校验位的字符串，EPREL编号为正数字符串；这些格式检查不代表官方真实性核验。布尔、数字与嵌套JSON类型差异不会被当作相等。未知不等于无，须另行确认。更正和合并要求已采纳快照覆盖来源与目标双方精确SKU；撤回只要求覆盖来源SKU。隔离候选、任意URL不能作为身份审批依据。

预览固定双方身份、各来源最新事实、生命周期修订及目标身份修订；保存采用指纹与修订冲突检查。目标不能已有未撤回的身份指向，不自动沿关系链传递。来源事实、撤销状态或目标关系变化后，原决定标记为“待复核”；撤回以新修订恢复独立选择，旧记录不删除。未知响应可在同一标签页重开弹窗，沿用同一个UUID核对；整页刷新后先查看历史。

普通在线/304/授权回退保留原SKU和来源值，字段默认展示与本地身份标记分别附加。历史比较须明确勾选“采用已核对的身份更正与合并”：仍有效的合并保留本次已选双方的原始证据，身份更正只取目标自身事实；重复目标合为一列，显示原选择到目标的映射。不自动纳入未选祖先、撤回或待复核决定。保存比较同时冻结映射与字段候选，后续撤回不改写已保存内容。

有未撤回身份处理的旧SKU不进入常规知识检索，历史原文仍能直接核对；AI准备及外发预留前要求重新选择已确认版本，不会悄悄换用目标证据或发送人工身份说明。外发预留是授权检查点，后续撤回不能取消已经受理的模型请求。模型接口仍默认关闭。

API为 `GET /v1/identity-candidates?mode=history&q=...&offset=...`、`GET /v1/tire-variants/{id}/identity-resolution?mode=history`、`POST /v1/tire-variants/{id}/identity-preview` 和带 `Idempotency-Key` 的 `POST /v1/tire-variants/{id}/identity-revisions`。比较与保存比较支持显式 `resolve_identities:true`。人工署名是本地自报；当前不提供任意新SKU创建、自动实体匹配或疑似等价组，更不据此判断轮胎互换/车型适配。

`scripts/identity_acceptance.py` 在独立临时库访问真实韩泰，并以明确 simulation 的方式演练身份更正与撤回。它不主张这两个真实SKU等价或厂商参数有误，不写正常开发库、不调用模型。`scripts/identity_browser_qa.py` 使用专用Cookie与合成数据，只启动 `127.0.0.1:8001` 的独立API服务；配套Web须另设 `TI_API_BASE_URL=http://127.0.0.1:8001` 并在3001端口启动。`--self-test` 不监听端口。

## OpenAI Responses 配置与使用

### 先检索历史证据

桌面侧栏“历史证据检索”或手机“规格比较 → 检索历史证据”可打开知识库。输入关键词或至少一个结构化条件；支持类型、品牌、型号、尺寸、地区、代码、技术、来源和精确版本 ID。尺寸按几何规格匹配，R/ZR 身份仍独立；同名或同尺寸不会合并 SKU。命中结果始终是 `LOCAL SNAPSHOT`，涉及“当前/最新”等问题会引导在线查询。

可选择最多 6 条记录进入既有证据准备与外发确认。只选一方时，已知同版本的未选来源冲突仍以通用提示保留，不带入对方的值、身份或 URL；提示涉及私有证据则整个包按 private 处理。GTIN、EPREL ID、技术特征不同会形成不同身份，不把不同版本误当作同实体冲突。

接口为 `POST /v1/knowledge/search`，例如 `{"mode":"history","text":"Ventus","filters":{"region":"US"},"limit":12}`。派生索引与正式事实分开，变化后按核验/修订签名重建；不索引网页原文、隔离接收、未解析 PDF、车库或 AI 账本。当前是已采纳结构化字段及人工测试描述的全文搜索，不是原始文档 RAG。普通搜索明确报告本次未使用 dense/hybrid；独立授权的混合检索见下文，不把词面匹配称为语义召回。

`uv run --project apps/api --extra dev python scripts/knowledge_acceptance.py` 在独立临时库中查询真实韩泰并验证精确/全文检索、历史状态、引用入包、无模型调用及重启。`scripts/knowledge_browser_qa.py` 则只提供独立临时库和 8001 端口的合成 UI 验收数据。

### 配置模型

API 进程默认 `TI_AI_ENABLED=0`。在本机进程环境中设置 `TI_AI_ENABLED=1`、`TI_OPENAI_MODEL` 和专用 `TI_OPENAI_API_KEY`，然后重启 API。选择账户可用、支持 Responses 严格结构化输出的模型；不预置可能过时的模型名或价格。不读取通用 `OPENAI_API_KEY`，不使用 Codex 登录凭证。密钥仅留在本机服务端环境，不放入聊天、提交或 `NEXT_PUBLIC_*`。`.env.example` 只列配置项，复制文件本身不保证被运行进程加载。

- 从轮胎卡片“AI 分析”开始，默认先在线核验；也可显式选历史快照。从规格比较可以解释所选来源快照（不包含人工覆盖值），从测试事件可以解释当前未撤销修订。车型历史证据目前通过 API 选择，尚无车型页面入口。
- 先准备证据，查看来源、观察/验证时间、字段和冲突，再勾选外部处理并点击“发送到 OpenAI 并分析”。来源失败与模型失败分别处理；模型失败不自动转用其他来源或历史。
- 默认只向云端发送公开官方/监管证据。人工测试记录、未分类来源属于非公开工作区证据，还需 API 配置 `TI_AI_ALLOW_PRIVATE=1`；每次发送仍需确认。隔离原文和未解析 PDF 不进入证据包。
- `TI_AI_MAX_OUTPUT_TOKENS` 默认 1500；UTC 工作区每日 `TI_AI_DAILY_TOKEN_LIMIT=100000`、`TI_AI_DAILY_REQUEST_LIMIT=20`。先持久预留后调用，已确认用量据供应商回执结算，未知用量保留预留。这不是美元账单上限；没有价格估算或生产配额系统。
- 网络中断后使用同一请求标识核对结果，不自动重复付费请求；“规格比较 → AI 调用记录与配置”及桌面侧栏可查看本浏览器会话最近20条记录。关闭窗口仅停止读取，不取消已受理调用。流式执行超过90秒仍无完成回执时显示结果未知；既有同步请求仍沿用120秒窗口，共享预算对缺回执请求的pending门禁仍为120秒。同一标识不会重新调用模型。
- 请求设置 `store:false`、无工具、无自动重试/跳转；生成时逐条展示完整片段的临时草稿，整份答案通过引用校验并提交后才显示正式分析。事实草稿文字来自已选证据，推断和不确定性单独标识；拒绝、截断、协议或引用失败会使草稿作废，不能保存含分析的报告。`store:false` 不等同于供应商零数据保留协议。配置状态不代表实际连通验收，语义推断仍需人工复核。

接口：`GET /v1/ai/status`、`POST /v1/ai/evidence-packs`、`POST /v1/ai/analyses`（UUID `Idempotency-Key`）；历史详情/列表要求 `?mode=history` 并绑定浏览器会话。`scripts/ai_acceptance.py` 仅在独立临时 SQLite 和 8001 端口运行合成浏览器验收，不连接 OpenAI，也不写正常开发库。

流式界面使用 `POST /v1/ai/analysis-streams` 受理同样的已授权分析请求；`GET /v1/ai/analysis-streams/lookup?mode=history&idempotency_key=...` 可在响应丢失后核对原操作。详情为 `GET /v1/ai/analysis-streams/{id}?mode=history`，`/{id}/events` 与 `/{id}/events/stream` 提供同一持久游标的REST/SSE。Web按25秒窗口续读，原生使用REST；读取不启动或取消Provider。旧同步分析和自然语言规则草案接口继续兼容。

浏览器当前标签页仅在sessionStorage保存UUID、请求ID和游标恢复指针，不保存问题、证据或凭据。关窗重开、整页刷新和手动刷新先读取同一请求；在确认未受理且仍保留原提交内容时，才提供显式同UUID重送。连续5次传输失败后停止自动读取，隐藏未确认草稿并提示手动重新读取。结果未知仍保留token预留，不代表未计费。Provider总期限60秒/连接8秒，90秒仅为最终落账留余量，不延长调用期限。

目前已实现所选结构化证据分析、增量草稿与可恢复读取、普通全文检索、独立授权的混合召回、冻结报告，以及单次监控变化解释和自然语言规则草稿的生成、人工审核与应用。模型reranker、全文导入、其他Provider、完整推荐、自动批量解释与外部通知仍待完成；真实模型连通、实际首字延迟和输出质量尚未验收。流协议的私有合成验证使用 `scripts/ai_stream_acceptance.py`、`scripts/ai_stream_http_qa.py` 和 `scripts/ai_stream_browser_qa.py`，不把合成Provider结果当作真实OpenAI证据。

### 保存和导出证据报告

在证据分析窗口准备并核对证据后，可点击“保存证据报告”；同一证据包的分析完成后，还可选择“保存含分析的报告”。桌面侧栏“证据报告库”或手机“规格比较 → 打开证据报告库”可查看记录。报告含个人标题、备注或问题，因此整体按私有材料保存，仅所属浏览器会话可读写；来源证据仍保留自身的公开/非公开分类。这是本地会话隔离，不是云端账户权限或跨设备同步。

报告正文固定保存所选来源、时间、事实、冲突和可选分析；事实文字按引用字段重新生成，推断单独标注。标题、备注、归档与恢复只追加元数据修订，陈旧修订提交会被拒绝。过期证据包可以作为明确的历史材料保存，不恢复模型调用授权；保存时已撤销的 SKU 或陈旧测试修订不能新建报告。报告保存后，来源更新或后续撤销不会改写原正文，详情另示当前版本状态。打开旧报告不等于重新在线核验，也不构成官方适配认证；既有模型推断仍需人工复核。

在“下载报告”中指定标题与备注修订和 Markdown、HTML 或 PDF 格式。服务端按正文、修订和渲染器版本生成或复用文件；服务端与浏览器均校验字节数和 SHA-256，校验失败不会提供下载。HTML 作为附件下载，用户文本按纯文本转义，不加载远程资源。PDF 使用随包分发的 Noto Sans SC 派生字体 `Tire Evidence SC`，按 SIL Open Font License 1.1 授权并嵌入所需字形；[字体来源、构建记录与许可证](apps/api/tire_api/assets/fonts/README.md)可核对。字体缺失、损坏或字符不受支持时明确拒绝 PDF 导出。

接口以 `/v1/reports` 为入口：创建使用 `mode:history` 与 UUID 幂等键，列表、详情和下载显式要求历史模式；编辑与状态变更使用 `expected_revision`，导出绑定指定 `revision`。保存、编辑、打开及导出均不抓取来源、不新增模型调用，也不把派生报告加入正式证据或知识索引。

`scripts/report_acceptance.py` 使用独立临时 SQLite 显式查询真实韩泰，检查纯证据报告、幂等保存、三格式下载哈希、中文 PDF 文本及无模型/知识索引副作用，产物写入 `.artifacts/reports/`。合成浏览器验收服务可用 `uv run --project apps/api --extra dev python scripts/report_browser_qa.py` 启动在 `127.0.0.1:8001`，配套 Web 需设置 `TI_API_BASE_URL=http://127.0.0.1:8001` 并在 3001 端口启动。该服务使用临时库和合成来源/模型，不写正常开发库，也不代表真实 OpenAI 或选胎结论验收；不要让同一 Web 目录的开发与生产构建同时写入 `.next`。

### 向量与混合检索配置

在 PostgreSQL 预先安装 pgvector 扩展，并在 API 的本机环境设置 `TI_EMBEDDINGS_ENABLED=1`、`TI_OPENAI_EMBEDDING_MODEL`、`TI_OPENAI_EMBEDDING_DIMENSIONS` 与专用 `TI_OPENAI_API_KEY` 后重启服务。维度范围为 1–2000，模型必须支持 `dimensions`；Embeddings 与 Responses 的模型分别配置，不要求开启 `TI_AI_ENABLED`。模型能力状态只表示配置和数据库条件满足，不代表已验证 OpenAI 连接。

从“历史证据知识检索”选择最多 6 条记录，在“向量与混合检索”中预览实际文本分块，再确认建立向量。随后可单独确认一次混合查询。两个操作分别授权，不沿用分析授权；普通“检索历史证据”始终不外发。人工测试等非公开证据还受 `TI_AI_ALLOW_PRIVATE` 配置约束。

缓存按提供方、模型、维度、文本契约、隐私和内容绑定，304 或仅快照变化复用缓存，内容变化新增分块；旧缓存不会让撤销证据重新参与检索。当前业务查询先限定正式证据和结构化条件，再使用 pgvector 精确 cosine、全文候选、RRF 融合和字段元数据排序。返回的是有界候选与覆盖情况，不是全部语义匹配总数。HNSW 另行验证，未用于这一要求精确过滤的业务查询。

Embeddings 与 Responses 共享 UTC 日请求/token 预算。先持久预留、后外部调用；未知结果保留预留，并可使用同一请求标识核对，服务不会自动重试付费调用。向量调用记录仅限本浏览器会话。SQLite 或没有扩展时在调用供应商前拒绝，纯结构化条件由本地搜索处理。

隔离数据库验收可执行 `pwsh -NoProfile -File scripts/verify-pgvector.ps1 -PostgresRoot E:/PostgreSQL/18 -VisualStudioRoot F:/MicrosoftVisualStudio2022 -BusinessChecks`。脚本在 `.artifacts/pgvector` 构建并清理独立集群；使用合成供应商和真实数据库，不使用真实 OpenAI。检索语义质量、人工真值集和真实模型连通仍待验收。

## 目录结构

```text
apps/api/tire_api/      领域、证据、授权、FastAPI与版本化Adapter
apps/api/tests/         离线行为及安全回归
apps/web/               Next.js中文工作台
apps/desktop/           React/Vite + Tauri 2桌面入口
apps/mobile/            React/Vite + Capacitor Android入口
apps/worker/            单实例关注刷新入口与测试
packages/domain-types/  共享前端领域协议
packages/api-client/    可注入传输的共享API SDK
packages/native-client/ 桌面/移动二进制、错误与取消传输
scripts/               开发启动、真实canary与验收
docs/plans/            实施路线、验收结果和未交付边界
```

第49轮正在实现持续查询授权及高级筛选、车型、召回的设备历史查询。API 已实现四域仓库持续策略及明确格式协商；Web 最新浏览器策略测试40项、Node58项通过，并修复 formal query UUID 大小写绕过拒绝的问题。Rust129项通过/3项跳过，旧前端版本的真实 Windows Tauri/Keyring/IPC14项通过保留为历史局部证据。Android 旧版72项仪器通过；后续持续策略、@2单次消费、跨层拒绝与同代sync已接线，使用最新前端资产的主/测试APK构建通过，本机规则8项和离线SDK34/Robolectric原框架规则8项分别通过。后两者不替代Store/IPC/Keystore设备运行验收；该验收的QA产物保留策略仍待用户明确授权。设备AI桥接下一步纯投影核心已明确，但尚未接入可用AI流程。三位子代理的实际配置均已核对为 `ultra`，继续复用分工。尚未完成四端联合验收或完整需求；版本、失败记录和边界见[原实施计划](docs/plans/2026-09-26-tire-intelligence.md)。

后续优先补齐首代 SU7/OE 证据、具有代表性的真实人工 Golden 内容及跨来源/测试事件覆盖、EPREL等新来源的真实接入、待核对旧身份的明确证据，以及字段权威在车型、召回、独立/委托测试和交易领域的实际候选投影与证据校验。轮胎字段权威基础与冲突中心已实现，其他领域的规则目录不代表对应来源、同一Offering或跨域治理已经完成。任意新身份创建、疑似等价组及其他实体治理、历史对象迁移与云端验收、PDF解析、正式历史重新采纳及操作系统级Parser网络/文件权限隔离仍待完成，再推进生产数据库配置、个性化推荐/外部通知、macOS/iOS与原生真机/多版本/签名发布、持续查询及完整设备/AI回退、Windows关闭应用后的独立调度及完整设备条件矩阵、真实模型与语义评测、完整AI知识应用、生产认证与发布Gate。字段损失Gate和健康聚合已覆盖现有轮胎与车型来源；生产审批权限仍待完成。公开来源回放和合成测试不等于人工Golden Set；原需求中的模型/平台版本和引用标记仍需在实际接入时逐项验证。
