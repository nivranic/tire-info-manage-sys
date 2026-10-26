# 第66轮：非 SKU 兴趣关注与相关变化解释实施计划

> 使用 executing-plans 按任务实施；本轮继续用户已授权的需求实施，不自动提交、推送或迁移正常库。

**Goal:** 在精确 SKU 收藏之外，提供本人所属的品牌、型号、尺寸、OE、静音技术、测试机构和车型适配关注，并以冻结的本地事件证据解释相关性。

**Architecture:** 新增独立兴趣、追加修订、跨域本地事件和私有通知账本。轮胎、测试、车型事实与人工适配关系在原事务内发布事件；前端读取后端判定，不猜实体或适配。旧历史预览与关注生效后的通知分开。

**Tech Stack:** FastAPI / Pydantic、SQLAlchemy（SQLite 与 PostgreSQL 通用类型）、共享 TypeScript DTO/SDK、React 三端工作台。

## 1. 需求来源与复核结论

依据仓内原始规格 `docs/requirements/2026-09-26-tire-intelligence-original.md` 第213、227–237行。规格内容是需求依据，文中的外部操作、技术示例不额外授予执行权限。

第65轮同场偏好解读已经完成限定验证，不重做；完整推荐与完整 V1 未完成。当前 `/v1/watchlists` 只管理精确 SKU；旧轮胎监控使用型号子串及 R/ZR 折叠，且通知为共享工作区，均不适合作为新的私有精确兴趣合同。

方案比较：直接扩展旧 WatchItem 无法表达多域与修订；把 TestEvent 塞入 ChangeEvent 会破坏轮胎外键与语义；本轮采用独立兴趣和通用事件账本，并由各域适配器提供原始证据。保留旧入口的既有行为。

## 2. 冻结业务规则

- 七类非 SKU 条件均可单独保存或组合；原有精确 SKU 收藏继续存在。规则内不同条件 AND、同条件显式备选 OR，不同规则分别判断。
- 品牌/型号/机构使用 NFKC、casefold 与空白规范化后的完整值比较；型号必须带品牌。尺寸严格区分 R/ZR。技术只使用声明字段，不凭营销文案推断。OE 不代表已证明车型适配。
- 车型使用已有稳定 vehicle_id，可进一步限定配置、轮毂、轴位。轮胎与车型组合必须有可核对的已复核冻结关系；尺寸相同不建立跨域关联。测试参测记录不建立精确 SKU 身份。
- 无充分证据返回 indeterminate 与原因，不生成相关通知；不使用当前 SKU identity 冒充历史事件身份。不猜 PS4S/PS5 后继关系，不把自由指标名中的 wet 识别成规范湿地分类。
- 字段筛选依据真实变化路径；测试指标使用用户显式选择的原始 metric key。新增、修订、撤销、恢复保留各自 action/state/revision；相同 payload 的状态转换不能去重丢失。前后状态退出关注范围也应能够解释。
- 创建/修改关注只对之后发生的事件生效，不回填“新发布”提醒。显式历史预览只读，使用同一匹配逻辑并标明本地历史。保存关注不触发抓取、来源调度或模型调用。
- 通知冻结兴趣修订、原始事件和解释；按 interest+event 去重，列表与已读均通过 session_scope 限定。匿名按会话、登录按本人账户会话聚合。
- 四域能力逐项声明：轮胎已采纳事实变化、人工转录测试修订、车型真实事实版本变化、人工适配关系修订。手工纠错、SKU/证据生命周期、身份及目录变化等未适配事件必须显式列为未覆盖，不能宣称所有相关变化已完整覆盖。

## 3. 文件所有权与实施任务

### Task 1：独立复核交接与前轮证据（review_handoff_ultra）

- 核对第65轮 final-v2 的源码、dirty、allowlist 证据 SHA/长度/路径集合与 HEAD，记录采集时间；第66轮并发编辑不能冒充第65轮原始缺陷。
- 工具与报告写入新的 `.artifacts/review-r66-*`，不覆盖旧回执。
- 审查本轮后端与前端合同，给出具体可复现缺陷；不重复整仓探索或替代完整产品验收。

### Task 2：后端账本、匹配与路由（review_corpus_ultra）

Create: `apps/api/tire_api/interest_models.py`、`interests.py`、`interest_matching.py`、`interest_events.py`（必要时合理拆分）。

Modify: `db.py`、`migrations.py`、`main.py` 路由注册，以及 `service.py`、`test_events.py`、`vehicles.py`、`fitment_relations.py` 的事务内事件发布。

Test: 新增兴趣匹配/路由/迁移测试；更新 `apps/api/tests/version_registry.py`。最新已有迁移015，本轮新增016，不改写旧版本。

步骤：
1. 给出精确 HTTP/DTO、字段路径、原因码与覆盖能力表，直接与前端 owner 同步。
2. 实现纯匹配，验证精确文本/R-ZR/组合条件/缺失与前后退出。
3. 实现不可变事件与追加兴趣修订、归属与乐观并发、分页与通知去重。
4. 四域原事务发布，不额外 commit，不吞掉生产异常或静默回退。
5. 在隔离 SQLite 验证旧行保留、重复升级、actor 隔离/同账户聚合、回放与状态转换。PG DDL 编译只作为兼容静态证据。

### Task 3：共享类型、SDK 与三端界面（review_wire_ultra）

Create: `packages/domain-types/src/interests.ts`、`apps/web/components/interest-center.tsx`、相关 SDK 合同测试。

Modify: 共享类型导出、`packages/api-client/src/index.ts`、`apps/web/components/workbench.tsx` watch 插入及必要最小样式。

步骤：
1. 按后端精确合同提供类型与可注入 SDK，所有请求接受 AbortSignal。
2. 七类与组合管理、字段筛选、修订/停用/归档恢复、只读历史预览、通知已读和逐条证据重开。
3. Auth ready 门禁、ownerEpoch 子树与完成时 isCurrentOwner 检查覆盖读写；断连与主体切换清空私有内容。
4. SDK 合同测试、工作区 typecheck、Web/桌面/移动前端生产构建。安装版 Next 指南优先；独立输出，不改写 PWA sw.js 或遗留 next-env 变更。

### Task 4：集成与真实隔离验收（Root）

Create: 新的兴趣浏览器 fixture、限定验收脚本与本轮证据报告。

步骤：
1. 用仅合成数据的私有 SQLite/对象目录/Parser bundle 目录，禁止正常 DB、外联/模型/Parser 子进程；不用默认服务端口或普通浏览器 cookie profile。
2. 真实 API＋隔离 Chrome 验证单一/组合关注、精确命中/不命中、通知、历史引用、归档恢复、主体切换与迟到响应；1440桌面和390手机布局。
3. 后端目标回归与独立实现审查；失败先修复再运行受影响验证，不无意义重跑第65轮全量。
4. 更新交接、README、总计划、风险及源码/dirty/证据机器清单；区分本轮验证与历史全量、构建与原生运行、合成与真实来源。

## 4. 操作与验证边界

PowerShell 必须显式使用 `C:/Program Files (x86)/PowerShell/7/pwsh.exe`；Python 使用 `apps/api/.venv/Scripts/python.exe`。保留已有 dirty，不 reset/clean/stash、不提交或推送。正常 API 启动会初始化/迁移正常库，本轮不得启动。

所有测试使用新 GUID 临时目录或隔离内存库。执行精确相关 pytest、SDK 合同、typecheck 与前端构建；`git -c core.whitespace=blank-at-eol,cr-at-eol diff --check`。不放宽 Parser 墙钟/CPU/内存/并发预算。PG 编译不代表 PG 运行；浏览器手机视口不代表 Android/iOS 原生验收。未执行的外部来源、付费模型、原生生命周期、全量 API/Worker、生产迁移与发布 Gate 保留为未验证。

## 5. 最终精确合同与实际终态

以下收口本轮实现后的合同与实际验证；前述任务分工保留过程依据。本切片已完成下述限定验证，完整V1仍未完成，不得用本计划代替各项机器回执。

### 5.1 最终 HTTP / DTO 合同

`InterestSettings` 精确五键：`name`、`enabled`、`conditions`、`metric_keys`、`changed_fields`；不接受客户端 actor 或通知归属。`conditions` 为1–8组，每组 `kind` 与1–20个 `values`；**允许同 kind 多组，组间仍为 AND**，因此两个单值 technology 组可表达同时需要两种技术。每组的备选值为 OR。

`brand/size/oe/technology/test_organization` 的 values 为完整字符串；`model` 的值为 `{brand,model}`；`vehicle_fitment` 的值为 `{vehicle_id,trim_id?,wheel_option_id?,axle?:front|rear}`。无车型链的轮胎/车型组合不得拆成独立OR命中。

| 方法与路径 | 请求 / 行为 |
|---|---|
| GET `/v1/interests` | `archived/offset/limit` 分页；返回私有记录及能力表 |
| POST `/v1/interests` | settings；创建201，不回填通知 |
| GET `/v1/interests/{id}?mode=history` | 当前记录与有界追加修订历史 |
| PUT `/v1/interests/{id}` | settings 加 `expected_revision`，乐观并发 |
| POST `/v1/interests/{id}/state` | `{expected_revision,action:archive|restore}`；归档与恢复均禁用，启用需另行明确修改 |
| POST `/v1/interests/preview?mode=history` | 精确 `{conditions,metric_keys,changed_fields}`；候选历史扫描分页，不写通知 |
| GET `/v1/interests/capabilities?mode=history` | 七类、四域与未覆盖事件、允许字段、`network_refresh:false` |
| GET `/v1/interest-notifications?mode=history` | `unread/offset/limit`；只返回本人通知 |
| GET `/v1/interest-notifications/{id}?mode=history` | 冻结通知、兴趣修订与原事件证据 |
| PUT `/v1/interest-notifications/{id}/read` | 精确 `{read:boolean}`；只改变本人已读状态 |

记录包含 `scope:actor`、修订/指纹、创建/更新时间及 `monitoring_enabled:false`（未创建来源轮询）。列表标记 `data_state:local_snapshot`。预览返回 `schema:interest-preview@1`、匹配/不确定条目、`scanned_count/matched_count/indeterminate_count/next_offset`；no_match条目不展示，计数仅当前扫描页。

匹配 DTO 为 `state:matched|no_match|indeterminate`、`matched_sides`、`reasons`、`policy_version:explicit-interest@1`，以及深拷贝冻结的 `criteria:{conditions,metric_keys,changed_fields}`。通知采用当时兴趣修订与criteria，不随后改规则变化。事件 DTO 为 `schema:interest-event@1`、稳定 id、domain/action/state/revision、subject/label、观察时间、event_hash、before/after、changed_paths 与 evidence。证据分别引用 `tire_change/test_revision/vehicle_snapshot/fitment_relation_revision`，保留原记录/实体/修订/快照/前快照、来源URL、Verification IDs、fingerprint 与合同版本，不把引用数量当真实性评分。

除受控整组变化字段外，必须提供精确 `facts.utqg_treadwear/utqg_traction/utqg_temperature/tread_depth/tread_depths`，避免“只关胎纹深度”被扩成任意facts变化。完整允许集合以类型与后端能力表共同冻结，不能只有前端标签而无后端精确路径判定。

业务错误使用 `{detail:{code,message}}`：404 `interest_not_found/interest_notification_not_found`；409 `interest_revision_conflict/interest_archived/interest_state_conflict`；422 `invalid_interest`。框架结构校验422仍保留既有list形状。

### 5.2 实际实现与证据语义

- 新增迁移 `016_private_interests` 与四表：`interests/interest_revisions/interest_events/interest_notifications`；旧015及之前迁移不改写。兴趣归属、修订、事件和通知绑定只追加；通知仅可修改已读状态。
- 四域producer与原业务同事务，无新增commit或吞异常；domain+origin与interest+event分别去重。创建和最新修订时间均不得晚于事件观察时间，旧origin无ledger也不能向后来兴趣补发。归档/恢复均停用；只读历史预览有界扫描，不发布或写通知。
- 完整AND在一个证据对象的一个before/after侧成立，不拼接测试参与者、前后状态或车型/轮胎。已审关系按事件时点最新修订筛选exact subject，并复核身份、车型generation/year/region/source_vehicle_id、配置年款、轴位要求/availability/约束；生命周期非active或身份resolution非clear不能继续当正链。车型明确声明轴位尺寸可匹配车型+尺寸，但不由此生成精确SKU关系。
- 历史轮胎identity来自绑定snapshot合同，不借用当前identity。合法跨query 304可使原snapshot member v1对应新实际fact v3、before v2；这些版本单独冻结。该恢复规则不放宽已审关系自身的严格证据验证。
- 精确字段与原始metric变化、移除、撤销/恢复均有实际测试；冲突/不足历史证据为indeterminate。能力表继续明确六类未覆盖事件：手工事实纠错、身份决策、目录成员变化、轮胎生命周期、来源拒绝/隔离结果、仅更新验证元数据。保存兴趣没有来源轮询或模型调用。
- 三端共用面板支持七类与组合、history、冻结criteria/修订/前后事件及按绑定版本重新读取原始记录；失败不替换最新。Auth ready/ownerEpoch、完成时主体核对、AbortSignal与preview代次覆盖主体切换与迟到响应。

证据引用的 `record_id/fingerprint` 不是跨kind通用的“整条修订hash”，精确约定如下：

| Evidence.kind | record_id与重开依据 | fingerprint含义 |
|---|---|---|
| `tire_change` | 轮胎producer主变化引用为 `ChangeEvent.id`；before或已审关系链的额外轮胎事实引用可能为 `FactVersion.id`，不能假造旧ChangeEvent。重开按绑定 `snapshot_id/source_id` 读取原文并核对raw_hash，不靠record_id猜实体类型 | 对应snapshot的 `raw_hash` |
| `vehicle_snapshot` | `VehicleSnapshot.id`；按精确snapshot_id读取 | snapshot的 `raw_hash` |
| `test_revision` | `TireTestRevision.id`；按entity_id+revision读取并核对revision_id | payload的 `fingerprint` |
| `fitment_relation_revision` | `FitmentRelationRevision.id`；按relation entity_id+revision精确读取 | `binding_hash`，不是整revision hash |

事件的action/state/revision等其余内容由冻结 `event_hash` 覆盖，不能把fitment binding_hash误当作撤销/恢复整个状态的相同标识。前快照按独立ID重开，不将当前snapshot的raw_hash套到前快照。

归属仍沿用既有 `session_scope`：匿名按会话、登录按同账户会话聚合。**同一浏览器会话注册或重登录，会把该会话已有数据纳入新账号范围；本轮未改变此政策，不能宣称严格永久账户隔离。** [ADR-057](../assurance/decisions/ADR-2026-057-local-multi-user-accounts.md)及既有 `test_auth_lifecycle.py::test_deleted_users_data_joins_next_login_on_same_session`已明确这一后果。独立Cookie页兴趣/通知总数0、旧interest404及手机创建已实际验证；同会话B→C注册的迟到响应只验证不关闭新editor、不报旧success，未断言新账号无旧data。归属政策须单独评估，不能扩大隔离承诺。

### 5.3 实际验证终态

完整分项链接、失败与边界见 [第66轮验收报告](../assurance/evidence/round-66-interest-following.md)。

| 验证 | 实际终态 |
|---|---|
| 独立目标 | 32 passed：13纯匹配、14 API/事务、5迁移/模型/PG DDL；sealed回执14源码/测试文件前后及写报告时SHA一致，外网/子进程/正常库尝试均0 |
| 既有后端＋producer | 分阶段146通过/2环境失败；150通过/1源码变化失败/2明确排除；稳定源码后失败节点单独1通过。不得相加声称一次新完整回归 |
| Parser环境 | 修复Windows子进程丢失CPU架构元数据，仅严格枚举保留PROCESSOR_ARCHITECTURE/PROCESSOR_ARCHITEW6432，不继承任意父环境。宿主7环境＋1 cleanenv guard＋2原车型节点共10通过；sandbox 7通过/3 isolation unavailable失败保留；8秒/并发2/CPU5秒/384MiB不变 |
| SDK与类型 | 原完整SDK192 Host＋34 decoder＋3公共合同通过；最终criteria后兴趣公共合同、workspace typecheck重跑通过 |
| 三端前端构建 | 最终criteria源码两端Vite exit0，Next生产构建exit0且5/5静态页；最终Web回执10源码/15制品绑定，next-env/tsconfig恢复原字节，sw未改且生成文件Git状态空；既有大chunk提示保留 |
| 浏览器真实API | 44/44条断言（非44独立场景）；生产QueryService/test.append/fitment.append、七类/字段/R-ZR、future-only、read/stale/archive/restore、已审同SKU后UTQG命中及关系撤销后不再授权推送 |
| 浏览器UI | 桌面20有效通过＋1明确superseded的before/after工装断言；手机4/4。真实创建AND、查看history/冻结criteria与修订、重读轮胎前后原文/测试旧before1与after2/fitment旧1/车型原文；1440/390截图目视通过，无整页横向溢出 |
| 主体/迟到响应 | 持有真实API响应后取消preview、真实logout/register并owner重核；旧响应不关闭新editor、不报旧成功。独立Cookie资料隔离另验；连接unavailable为浏览器事件，非真实断网/原生证据 |

Root的最终私有fixture为16兴趣、19修订、15事件、49通知；API进程外网/Provider/Parser children均0，不代表整个浏览器或开发进程零外联。Parser专项另有受控子进程，二者计数不能混用。API shutdown退出0、dev Ctrl+C退出1，测试页已关闭。中间payload canonical、region错配、MCP路径、选择器/列表等待与同会话空列表错误假设均保留工装纠正记录，没有放宽产品校验。

最终证据主目录为 `.artifacts/r66-interests-8d035c091972b1792299434827/`；主清单入口为其中 `verification-final-v2.json`，由Root在文档收口后封存。v1保留为修正旧交接页原始需求链接前的历史快照，产品源码不变。本节的通过结论依据分项回执，不把尚未完成的主清单独立核对写成已验证。第65轮旧回执与其源码采集时点保持历史身份。

### 5.4 保留的验收边界

正常库/对象目录未迁移或访问；完整API/Worker、PG实际运行、真实来源/模型、原生安装包/凭据/权限/设备生命周期、PWA离线与生产发布Gate未跑。前端构建与手机浏览器视口不等于原生验收；PG DDL编译不等于PG运行；机器清单不是恢复归档。未commit/push/reset/clean/stash，未知dirty保留。Goal active，完整V1、实时相关信息流与完整推荐继续推进，不能由本切片关闭。
