# R91 车辆 binary 消费闭包设计冻结方案

状态：2026-10-19，R91设计冻结方案；实施／受管运行以Root Gate为准，当前尚未实施或运行。设计准备阶段仅写自有 `.artifacts` 的限制是历史授权边界；该阶段未改源码／测试／runner／Guard／ChildPolicy／正式docs，未创建baseline，未运行产品、collection、pytest、SQL、数据库、Provider、网络或probe。方案B已由Root通读认可，正式计划按交审通过原字节发布；本文件不授予生产来源用途许可。

## 1. 推荐结论与已确认输入

推荐一个闭合的八生产文件切片：统一只读 binary accepted capsule 和固定用途判定，修复关系的 selected／current head／列表路径，覆盖新 AI 包、普通及 Device 分析 admission、reservation、同步／异步实际 dispatch，以及报告新冻结、新导出、既有导出重用和下载。生产首代来源的 `structured_fact_use=pending_review` 时，本地新关系也拒绝；`provider_use` 和 `export_or_redistribution` 本轮恒为 false。正向 binary 本地关系仅在受信私有 fixture 明确允许 local 的条件下验证。

已确认依据如下，全部来自当前静态阅读或既有受管回执；代码可达性不等于本轮实测结果。

- [冻结 PDF 合同](../../docs/plans/2026-10-19-official-vehicle-pdf-contract.md) 的第 6／7 节要求原件与用途核验，并固定 Provider／导出关闭；公开 URL、HTTP 200、source enable、用户勾选或模型 allow_private 均不授予来源用途。
- [R90 唯一受管结果](../../.artifacts/r90-t-3e8a1c7b6904/result.json) 为 381／381、0 skip，680 source before／after 稳定，240 child 全部 exit0／live0，resources_closed；这是 R90 定向证据，不能声称 R91 已通过或 156 模块全回归。[R90 最终 seal](../../.artifacts/r90-close-6f2a9b40c783/verification-final.json) 已由Root逐项2101 pin实核PASS；[R91源码baseline](../../.artifacts/r91-baseline-1233b51fa2424a1e/baseline.json)已由Root归档，5213B／`0c41e3390886575551d2ad306079c9aaca45c90b01736fe6a8f15140b4ee404f`，精确8生产＋runner共9源，Root独立核源／副本均与R90 pins匹配。本设计作者未创建该baseline。
- [消费者调查](../../.artifacts/r90-next-consumers-596bc2e731d4/investigation.md) 确认 `fitment_relations.verify_raw` 对 vehicle 无条件 `body.encode()`，合法 binary 的 body=null 静态可达异常；尚未运行 HTTP，不宣称观测到 500。
- [vehicle_raw](../../apps/api/tire_api/vehicle_raw.py) 已有 R90 `checked_vehicle_history_baseline`：原件、schema／fact_hash、精确 Verification→QueryRun→ParserSelection。优先封装复用，不另写弱化的 accepted 规则。
- [ai_streaming](../../apps/api/tire_api/ai_streaming.py) 在排队／start_execution 后直接调用 `adapter.stream`；[ai_execution](../../apps/api/tire_api/ai_execution.py) 同步在 candidate 专用门后调用 generate。普通 vehicle 包没有 variant_id，现轮胎／candidate 门不能代替 vehicle 用途门。
- [专业材料用途目录](../../apps/api/tire_api/material_source_policy.py) 有自己的 startup catalog／身份与专业材料权利合同；不能向车辆继承授权。窄查车辆入口、SourceSpec、source_settings 未找到现成的受信车辆用途 resolver；本结论不是全仓不存在其他用途机制的断言。

## 2. 三个方案与取舍

| 方案 | 范围／收益 | 未满足或代价 | 决定 |
| --- | --- | --- | --- |
| A：仅关系＋新 prepare／新报告，约 4–5 文件 | 解决 body=null，并阻断常规新包；改动较少 | 旧包、旧 reservation、排队 stream、Device 早返回、直接 reserve、既有 export/content 可绕过。不能满足本轮闭包要求 | 不采用 |
| B：共享 capsule＋双阶段用途门，8 生产文件／2 新测试 | 所有本轮指定消费入口在副作用前失败关闭；复用既有事务／ledger／stream owner fencing；旧冻结字节不改 | 必须明确 fresh Session、普通／Device 引用绑定和固定安全码，并定向回归同步与 detached producer | 推荐 |
| C：通用许可证目录／可配置授权／DB 迁移／V2 客户端 | 可扩展未来来源、用途与管理界面 | 当前没有已验证 Provider／export 许可；新增配置可能被误用为提权，扩大 DTO、迁移、权限和客户端验收范围 | 另轮，不混入 R91 |

第八文件 `ai_gateway.py` 只补准确的固定安全码。现有 `safe_error` 会把未知码归为 `ai_provider_failed`；`ai_refused` 已表示 Provider refusal／content_filter，`candidate_ai_pre_dispatch_changed` 属于 candidate 合同，其他 disabled/config/grounding 码也不表示来源用途。为维持七文件而复用这些码会歪曲拒绝原因。无需因此修改 provider adapter、stream store、网络权限或预算。

## 3. 只读 capsule、固定用途与防降级

### 3.1 适用判别和旧文本路径

服务端对重新读取的持久化 snapshot 使用下列 OR 判别，不能只看可被降级的 encoding：

```text
binary_candidate = row.body_encoding == 'binary'
                   OR (row.source_id == SOURCE_ID
                       AND row.vehicle_id == FIRST_GENERATION_ID)
```

`SOURCE_ID='xiaomi-cn-vehicles'`、`FIRST_GENERATION_ID='xiaomi-su7-first-generation'`。命中固定首代身份后，encoding 改成 utf-8、body 填文本、capture/provenance 清空都不能绕回普通文本门；完整性检查应拒绝。其他来源的 binary 也不能进入 encode 文本捷径，不受信／不支持的 binary 身份固定失败。

普通 UTF-8 快照和轮胎 `Snapshot` 沿用原文本验证、原错误／hash 和六个 legacy 函数语义；不得为其增加 capture、mapping、parse_provenance 或新冻结 source 字段。不修改旧 pack/report/evidence 的 canonical hash 或字节。新增 consumer helper 不改变 R90 online、history、approval helper 的原合同。

### 3.2 proposed capsule 合同

在 `vehicle_raw.py` 增加薄接口 `checked_vehicle_consumer_capsule(db,snapshot_id,verification_id=None) -> dict | None`；普通legacy UTF-8返回None，由各caller保留旧门。binary返回仅为本次调用的深拷贝capsule，不落库、不回填冻结物。形状为 `snapshot_id,vehicle_id,source_id,raw_hash,parser_version,parser_identity,observed_at,verification_id,verified_at,payload,fact_hash,provenance`；时间／provenance沿用既有内部表示，禁止把该内部dict写入source八键合同。

1. 防止 ORM identity map 掩盖 DB 中被改变的原件或链路。先以 `db.no_autoflush` 检查相关证据模型的 `new/dirty/deleted`；当前真实读取链为 VehicleSnapshot／VehicleVerification／QueryRun／RawCapture／CaptureObject／EvidenceObject／ParserSelection／ParserExecution／ParserBundle／ParserDeploymentRevision。调用方若有这些模型的待写，固定拒绝，不用populate_existing覆盖。无关领域待写（例如关系revision／audit）保持原样，不flush、不清空；新增读取模型时同时补入该明确集合，不扩成全session拒绝。
2. 同一事务中 fresh 查询 snapshot、verification 和所需关联行，使用现有 helper 的 fresh／populate_existing 规则；先做上述 dirty 检查，再允许刷新已持有的干净实例。整个读取链处于 no_autoflush；禁止“refresh 全 session”或仅依赖调用方传来的 ORM 属性。
3. Device 给出 verification_id 时，只核该精确行，并要求 snapshot_id／vehicle_id 匹配；不存在或损坏不得退回同快照的另一条 Verification。普通历史引用没有 verification_id 时，按 `(verified_at desc,id desc)` 选择最新一条正式 Verification，再严格核该行；不能跳过坏最新行挑旧行。
4. 对 binary 候选调用 R90 `checked_vehicle_history_baseline(db,snapshot,verification=exact)`，覆盖保留原件 size/hash／receipt/capture FK／completed execution provenance／parser identity／schema／unique fitments／trim refs／fact_hash／Verification→QueryRun→Selection。不要只以 Verification exists、snapshot_hash 或 `vehicle_provenance` metadata 作为通过证据。
5. 返回 snapshot／verification 的标识与用于当前逻辑的 payload 深拷贝、fact_hash、已有 provenance 投影。raw bytes 仅用于核验，不返回给 AI／报告，不携带 content_path、对象读地址或新 source 键。已有需要 ORM row 的内部调用可在同一 no_autoflush 读取窗口使用已核干净 row；不得向外暴露可变证据 row 作为授权凭据。
6. helper 不 commit、不 rollback、不 flush、不另取 ingestion lock、不重放 parser、不读网络／Provider。调用方拥有当前事务、锁、错误响应与领域写；helper 失败不能改变调用方无关 dirty 对象。独立 dispatch reader 的 Session 生命周期见第 6 节。

不能通过测试中临时修补 helper 本身跳过上述资格链。positive fixture 只能替换受信的用途 descriptor 为 local allowed，完整原件／formal 链必须真实通过。

### 3.3 固定用途 descriptor

vehicle_raw 内提供固定来源的只读descriptor与 `require_vehicle_consumer_use(capsule,purpose)`，purpose封闭为 `local_structured`、`provider`、`export`；legacy None为no-op，资格错误保持既有VehicleRawIntegrityError，用途错误为固定code的VehicleUseNotAllowed，由HTTP caller映射403、dispatch映射GatewayError。本轮不新增HTTP、环境变量、source setting、caller参数或持久化配置来赋权；调用方只能请求某用途，不能传入“已授权”布尔值。专业材料catalog、capture身份和enable状态均不能作为车辆授权依据。

生产首代 descriptor：`structured_fact_use=pending_review`，`provider_use=false`，`export_or_redistribution=false`。本轮任何用户输入、allow_external_processing、Device consent 六元组、privacy public、allow_private、旧包存在或完成报告都不能提升这些值。Provider／export 的 false 在受信 resolver 边界外固定拒绝；测试仅允许 local override，不能用 fixture 把 Provider／export 打开。

完整性门先于相应用途门：坏原件／formal 链统一 503 `vehicle_raw_integrity_failed`；完整但 local pending 403 `vehicle_structured_fact_use_not_allowed`；完整但 Provider 禁止 403 `vehicle_provider_use_not_allowed`；完整但 export 禁止 403 `vehicle_export_use_not_allowed`。先保留 owner/scope、DTO、幂等键绑定错误，再做来源核验，避免外泄他人证据是否存在；同请求同时不完整与无用途时，已拥有引用的结果固定为完整性错误。403 不表示通过原件核验即可获得未来许可。

## 4. 本地关系闭包

`fitment_relations.py` 内同时闭合四条路径，保持两侧 scope、人工关系、非官方 OE、revision、staleness／ABA 和 notification 原子性。

| 路径 | 新行为 | 失败策略 |
| --- | --- | --- |
| `accepted_vehicle`／`frozen_evidence` | binary 候选取 capsule＋local_structured 用途；tire 仍调用原文本 verify_raw | 不把 PDF decode 成正文；坏链503／local pending403，在 preview／任何 revision 或 audit 写前返回 |
| `latest_vehicle`→`current_binding` | 仍先选既有排序的最新正式 head，再核其 binary capsule／local 用途，随后才读取 fact_hash／scope／requirements | 坏最新 head 不向旧 head fallback；不要吞掉完整性／用途错误并伪造“无 head”或 stale=false；原 vehicle_parts 领域缺项的处理与安全错误分开 |
| snapshot 列表／详情 | 页内每个 binary 候选在 metadata／payload 投影前核；detail 与 list 使用同门 | 一项坏链整页503；一项 local pending整页403；不静默隐藏坏项并保留误导 total，不返回部分未经核验 metadata |
| relation summary／detail／mutation replay | 需要当前 binding 的响应仍须验证 current head；冻结 revision/event 序列化字节不改 | 不能为了使 history 路由“成功”而用未经核的当前 payload。该接口混有当前有效性，不承诺坏链时仍可展示 current summary；固定403/503不改写历史行 |

`action='revoke'` 现有冻结 binding 与 stale withdrawal 语义必须保留，不能因为新增门而把旧 relation 改成 reviewed 或偷偷重绑。本轮选择保留现有 preview／detail 的完整证据链：binary local pending 时撤销入口同样固定403，原件坏链同样503，不临时增加来源许可豁免或新增撤销DTO／响应分支。受信local允许时，事实已stale仍可按原合同撤销且保留旧binding；旧UTF-8撤销测试原样保留。后续若需不消费结构化事实的纯状态撤销，应另设计精确冻结响应，不能读取未经核验的新head。

`interest_events._vehicle_side` 现已有 R89 checked provenance／fact_hash／asof Verification，不是完全无门。R91 不改该 producer、不在纯 `interest_matching` 中回查当前 DB，不重算或 backfill 历史事件。`interest_applicability` 的 encode 属于轮胎文本，`report_rendering` 的 body 是冻结报告 JSON，均不因命名或 binary 而泛化。

## 5. 普通／Device 冻结引用与 AI admission

`ai_evidence.py` 提供共享的 vehicle 引用枚举／冻结绑定核验入口，供 analysis、reservation、dispatch、reports 复用。它读取既有冻结形状，不给旧包添加键；只要包含 vehicle 项，就不得因无 variant_id 得到“空集合即允许”。

- 普通 vehicle evidence 为 `kind='oem_fitment'`，已有 snapshot_id／source/raw/parser provenance，facts 指向同一 evidence_id。按 snapshot_id 得到 capsule，将冻结 metadata 和三组允许的车型／配置／轮毂值与 capsule 逐项绑定；不能只比较 pack 自身 fingerprint。可识别的 vehicle markers（kind、固定首代 source／车型身份、`oem_fitment.*` field codes）必须一致；缺 snapshot_id、错 kind、错 source 或值冒充不被当成非 vehicle 放行。
- Device 由 DB 的 preparation→pack FK 权威判别，vehicle 引用是闭合 `{kind:'vehicle',snapshot_id,verification_id}`；从 item.reference 取精确引用，连同现有八键 source 校验 snapshot／verification／raw_hash／parser identity 等。现有 `_device_gate_evidence` 仅提 variant_id，不能覆盖 vehicle。保持现有 reference/source 字段和 D4 exact coverage，不伪造 variant_id、不增加 encoding/capture/mapping。
- 若 payload 无 vehicle，入口是 no-op，既有 tire/test/recall/candidate/Device 合同、hash、隐私与错误顺序保持。识别为 vehicle 但缺项／不一致时固定409 `vehicle_evidence_binding_failed`；底层原件／formal 链失败仍503完整性码，不能归成普通 ValueError 再映射 provider failure。
- 每个被消费的 vehicle fact 都须绑定其 evidence 和合法 capsule；不因 analysis 选择了少数 fact 而豁免包内其他 vehicle 引用。report 也不允许以只选择非 vehicle 文本来洗掉实际携带的 vehicle 证据。

新 `prepare_pack` 的 vehicle 分支先核 accepted capsule 和 `local_structured`，再构造包。生产首代 pending 因此不会生成新 vehicle 包；既有旧包仍能按原 owner/hash 合同只读。不要在 `owned_pack` 或 pack_view 添加当前原件门而破坏旧包读取。

`prepare_analysis` 保留 owner、purpose、Device origin/DTO 判别、stream_only、过期、当前问题、显式同意、配置／隐私等既有门。普通与 `_prepare_device_analysis` 在各自既有合同核验后、request_body 或 Device claim plan 写入前，调用共享 vehicle 绑定＋provider 用途门；Device 早返回前必须实际覆盖。来源检查发生在任何外发、预算 reservation、AIRequest／claim／execution／audit 插入前。Provider false 不能由用户同意代替。

`reserve_response` 同一 caller transaction／ingestion lock 内再跑共享核验与 provider 用途，放在 `budget_usage`、AIRequest flush、candidate claim、Device consent claim、before_commit execution 之前，以封住直接调用 reserve 或 admission 后改件的路径。helper 不消费／清理调用方 Device claim plan；失败不得留下任何新请求、claim、execution 或 audit。原有 Device claim-or-nothing／claim conflict、预算与幂等合同保持。

旧请求的 exact idempotent replay、详情和 SSE 订阅只读既有 ledger，不重新启动 Provider，也不重写完成物；同键不同 body 仍先409。未 dispatch 的旧 reservation／排队任务要在真正发出前走第6节，不能因为历史 admission 成功就豁免。

## 6. 同步／stream 实际 dispatch 再核验

在 `ai_execution.py` 提供共享的 fresh dispatch reader，普通同步和 `AIStreamSupervisor._run` 均调用。该 reader 接收 server-owned database／request_id、实际 config、实际 body／必要的冻结 pack 校验输入；不接受“可信”布尔值，不复用 caller Session 的 identity map。

1. 使用 `database.sessions()` 开独立 Session（同步取 app.state.database，stream 取 supervisor.database），其既有 session info 提供 object_store；不手动复制环境或自行 create_engine。只读阶段开启 no_autoflush，不取 ingestion lock、不写 ledger。
2. 先以最小读取重新取AIRequest及其 `row.pack_id` 所指AIEvidencePack，按durable pack判断vehicle；真实无vehicle时不施加新的generic body/config/pack约束，沿用原执行合同。vehicle分支才取Device preparation（如有）、精确refs和原件链，并核row.pack_id／request actor／实际provider/model／请求 `body_hash` 与传入实际body，及持久化pack自身fingerprint、Device preparation／冻结引用既有绑定。queued body或入参pack被替换必须固定失败，不能用内存deepcopy作为当前权威。
3. vehicle refs 完整核验后执行 provider 用途门；source/provider/export false 不能被已有 reservation 的 budget 或 consent 提权。vehicle判别必须以fresh durable request.pack_id所指的持久化pack及其实际body绑定为准，不能只因入参pack/body被替换成无vehicle就跳过。同步将本门置于candidate专用before_dispatch前；binary vehicle本轮在本门拒绝，无vehicle仍沿用candidate门和原执行合同，不读取vehicle原件／capture／parser／formal链或调用用途resolver，不加载无关领域。
4. reader自己的只读transaction和Session在返回前全部关闭；不commit／rollback／refresh caller Session，不把reader的ORM row、connection或transaction跨generate／stream的await。此断言仅针对R91新reader，不能宣称本轮修复所有旧caller/candidate事务生命周期：现candidate before_dispatch对普通包查询后早返回可能开启caller读事务，本轮不改candidate_ai、不增第9生产文件。同步reader在现有worker内调用；stream使用 `asyncio.to_thread` 等现有安全线程机制等待reader结束，避免把DB文件读取阻塞在event loop。
5. stream 先由现有 `start_execution` 完成 owner/deadline fence，再立即 fresh 核验，核验通过后才创建 projector／调用 adapter.stream。read worker 若遇 cancellation，沿用现有 shield／等待已派发同步工作的策略，必须收完 reader 并关闭 Session；不遗留后台 DB 任务或在取消后触发 Provider。read-only reader 不新增 store API／所有权状态或 retry。
6. 同步／stream 捕获本地fresh门固定 GatewayError，且本次执行已证明generate/stream尚未调用时，进入各自既有 terminal 写入：state=`failed`、answer=None、provider_response_id=None、usage=`{input_tokens:0,output_tokens:0,total_tokens:0}`。这是本地已证实未派发的零token记账，并非Provider返回usage；`safe_usage`已接受该形状，现行budget_usage因此释放token reservation及pending，保留当日请求次数、AIRequest／claim／审计。不删账本、不重新reserve／重试Provider，不记Provider refusal或outcome_unknown。内部必须记录确在本地门拒绝且尚未dispatch的状态，不能仅凭同名error_code给Provider错误归零。可能已派发、超时、unknown沿用保守reservation，不冒写零usage。stream由现有owner-fenced finish_execution追加终态；finalization失败维持既有unknown边界，不伪称已写failed或已释放预算。

HTTP admission 返回第3节403／503和绑定409；已接受 reservation 的 dispatch 无新 HTTP admission，使用 ledger.error_code：`vehicle_provider_use_not_allowed`、`vehicle_raw_integrity_failed`、`vehicle_evidence_binding_failed`。`ai_gateway.SAFE_ERRORS` 仅加这三个固定码，`ai_stream_store.safe_stream_error` 会经其保真；不改 UNKNOWN_ERRORS，不扩权限／预算，也不泄漏原件路径或异常正文。

## 7. 报告历史、新冻结和导出

| 操作 | 合同与顺序 |
| --- | --- |
| 旧 pack／已完成 answer／旧报告 list/detail／metadata edit/archive/restore | 维持各自 owner、自身hash、revision与既有读取合同。纯冻结历史只读不回查当前vehicle，不重算body/hash/renderer bytes；现有本地metadata操作不获取新的来源用途 |
| 新 report（含不带 analysis_id） | owned_pack／canonical 引用后，冻结前复用 shared vehicle 绑定＋capsule＋local_structured；pending403／坏链503／绑定409，在 report/revision/audit 插入前失败。过期包保存等非vehicle旧合同不改 |
| 同键同内容 report replay | 是读取已有冻结report，保留原返回与字节；不同内容先409，不因新用途状态重写或重建report |
| 新 export | owned_report、revision/document 自身hash合法后，从冻结 report evidence/facts 取精确 vehicle refs，核当前原件/冻结绑定及 export 用途；在 renderer、object_store.put 与 export receipt/audit前拒绝 |
| existing-export 返回与并发重用分支 | 与新export使用同用途门；不能先返回export_view再检查。并发渲染后进入最终既有锁区时，用干净／fresh已验证状态重核，不复用渲染前Session缓存；目前binary export恒false，故根本不进入渲染／写对象。未来允许时须另审TOCTOU与对象收敛，不在R91打开 |
| export content download | 先owner＋record/report/revision/document绑定，再capsule／冻结绑定＋export用途，之后才读导出对象并返回／追加download audit；有既有对象不构成再分发许可 |

报告核验只读取其冻结 evidence/facts 和精确 snapshot 资格；不能用当前 pack 内容替换旧报告 evidence。缺少可证明 vehicle 绑定的旧产物可保留本地历史读取，但新 export/download 固定绑定错误，不补字段、不猜测引用、不修改 renderer。`report_rendering.py`、schema/version、旧 Markdown/HTML/PDF字节保持；不嵌入原PDF、base64或capture对象地址。

## 8. 文件责任与依赖次序

| Owner 建议 | 文件 | 责任 |
| --- | --- | --- |
| capsule／关系 owner | `apps/api/tire_api/vehicle_raw.py`、`fitment_relations.py` | 共用只读capsule／固定用途；selected/current/list/detail闭包；原文本和freeze/stale/ABA兼容 |
| AI／报告 owner | `ai_evidence.py`、`ai_analysis.py`、`reports.py` | 闭合普通/Device引用、admission、新报告/export/content；旧只读字节兼容 |
| dispatch owner（与AI owner协调） | `ai_execution.py`、`ai_streaming.py`、`ai_gateway.py` | reserve再核、fresh dispatch reader、sync/stream接线、3固定安全码；原ledger/owner fencing不改 |
| tests owner | 拟新增 `apps/api/tests/test_vehicle_binary_consumers.py`、`test_vehicle_binary_dispatch.py` | 真实S2 actualchild本地关系正例、坏件／用途和side-effect负例；不改旧pinned测试 |
| AI／dispatch owner 的窄旧test适配 | 非pinned `apps/api/tests/test_ai_stream_execution.py` | 仅增module-local autouse noop-reader fixture，适配其object()/Store()纯producer测试；原7函数／断言／参数逐字节不改。生产reader不因custom store或缺sessions跳门；真实fresh gate在新dispatch模块验证 |
| 唯一 runner／seal owner | 后续独立登记 `scripts/run_api_worker_regression.py` | 仅正式审后新增测试manifest和计数，准备显式targets／命令，受管运行和封存；不由本草稿直接授权 |

先冻结设计及精确baseline，再由capsule owner给其他owner冻结helper合同；AI/dispatch独立实现时明确共享文件ownership，不能互相回退dirty。实现静审／互审通过后，runner owner才能登记、冻结具体targets与script/request pins，再等待运行Gate；禁止裸pytest、collection或probe。正式docs由其owner在新证据后写，不预写通过数。

## 9. Guard／ChildPolicy交集与源pin治理

本草稿静态读取 [ChildPolicy](../../scripts/regression_children.py) 顶层 `REVIEWED` 18条，和 [RegressionGuard](../../scripts/regression_guard.py) 源码；未import或实例化它们。精确交集由伴随静态回执计算：

- 八生产候选与 `REVIEWED` 交集为空；两个新测试目前不存在，也无现有pin。优先新测试文件，旧 `test_fitment_relations.py`、`test_device_ai_routes_prepare.py`、`test_device_ai_public_contract.py` 虽在回归targets内且命中REVIEWED，但本方案保持其原字节。
- Guard本身没有独立REVIEWED source hash表；其执行限制与ChildPolicy不是通用权限配置。ChildPolicy在初始化／每次受管launch核其REVIEWED表，support bootstrap/node_guard另有运行时原字节绑定；本方案不修改这些文件、权限类别、launch模板或预算。
- runner `bindings()`动态收集本轮8生产、2新tests及runner本身，受管run必须before／after一致；R90的680是上一轮输入观察，不是R91计数承诺。新文件登记后的数量必须由正式runner静态清单与run回执实核。
- 若实施确需修改任何REVIEWED命中文件，先停止该处编辑／运行，单列必要diff、child可执行literal/code变化和调用边界，经独立源码审查正式批准后，仅由boundary owner更新精确源码pin；不扩大权限／模板／预算，不自动再算hash以绕过changed拒绝。新文件内测试若新建子进程也不自动被允许：正例必须走既有受管parser launch；新增任何launch种类需另轮Gate。

## 10. 验证矩阵与验收边界

本节是未来验证要求，当前未运行任何一项。两新测试不能以mock parser输出代替S2 actual child正例，也不能通过Provider/export授权fixture制造本轮不存在的生产许可。

现有 `test_ai_stream_execution.py` 的7个纯producer单元使用object() database与自定义Store，Root已额外授权上述局部autouse noop-reader fixture；其原测试函数保持，不能将此适配当真实原件／用途门覆盖。新dispatch模块必须用真实database.sessions覆盖最后门；生产不增加hasattr/store类型豁免。

| 类别 | 必须证明 |
| --- | --- |
| 实际binary本地正例 | 受管私有目录内用既有S2离线pin，经真实parser child、正式capture/receipt/completed provenance与R90批准采纳链形成body=null snapshot；受信私有resolver仅允许local。关系list/detail/preview/create/review/revise以及current head/stale/ABA得到预期；两侧scope、非官方OE、interest冻结/回滚不变；Provider/renderer/objectwrite全0 |
| 生产用途负例 | 不patch用途resolver时，完整S2 snapshot的local新关系/新包/新报告403 structured_fact_use；有效旧包新analysis/reserve/sync/stream403或ledger provider_use码；新/既有export/content403 export码。public、enable、allow_external_processing、Device同意、环境/caller输入均不能提升 |
| 原件／正式链破坏 | selected与current head分别覆盖缺对象、同长不同bytes、错size/hash/receipt/capture FK、错误completed provenance、parser identity、schema、fitment/trim refs、fact_hash、Verification query/identity、Selection；body_encoding降为utf-8且保留固定首代身份仍拒绝，不fallback旧head或另一Verification |
| 普通／Device冻结绑定 | 改pack evidence source/values/field mapping、丢snapshot、错kind、Device精确verification错配、空vehicle refs、相同快照多Verification；拒绝且旧pack/source八键/fingerprint不写。无vehicle旧fixtures继续原结果 |
| actual dispatch／TOCTOU | admission/reserve后、generate前及stream排队/start后替换raw／formal引用；直接旧reservation execute；普通和Device均实际到共享fresh reader后被阻断。ForbidProvider.generate/stream哨兵均0调用，不只断言prepare失败；reader独立Session关闭、caller dirty未丢／本门无autoflush、本门reader事务不跨Provider，cancel无遗留任务；不把此证据扩大成旧candidate/caller所有事务已修复 |
| ledger与错误 | admission失败不增加AIRequest/claim/execution/audit；旧reservation在确定未派发的本地门被挡后failed固定安全码、answer/provider_response_id为空、显式全零token记账，token reservation和pending释放但请求次数/claim/audit保留，不重试；Provider可能已派发／timeout不归零。finish失败保持既有unknown边界；owner/deadline/双supervisor/幂等回放不产生第二次调用 |
| report副作用 | ForbidRenderer、ForbidObjectWrite与ForbidProvider哨兵证明未许可时均0；已有export不先return、content不先读/返回对象。旧report body/hash、revision与renderer version/三格式既有字节不漂移；纯历史读取仍可用 |

既有最小建议whole targets为 `test_fitment_relations.py`、`test_ai.py`、`test_reports.py`、`test_ai_stream_api.py`、`test_ai_stream_execution.py`、`test_vehicle_raw.py`，当前静态展开为162cases（不是collection结果）。Device只选 `test_device_ai_submit.py` 中full chain、D18 minimal outbound、same-key replay、D7 reserve bypass，以及legacy包携带device_submission的sync/stream兼容，共6精确函数；binary基线只选既有ingestion actual S2与approval new actual observation两精确函数。Interest保留下列1精确函数，通知写失败原子性由新consumer测试复用既有私有fixture验证。runner owner静态建议为171旧cases，加两新whole，共17targets／12模块，最终cases=171+A+B，以正式run实际结果为准。新增两tests复用既有fixture／managed child，不重做完整Golden／release大套。renderer与source八键兼容若冻结diff触达时再按必要性选择现有精确函数，不预设整模块全跑。

```text
apps/api/tests/test_interest_review.py::test_review_reviewed_vehicle_sku_chain_delivers_later_exact_sku_fact_changes
```

runner owner应根据冻结diff缩减或扩大必要现有targets并给出静态cases，不盲跑全仓；新增触达candidate/rule/recall行为时必须相应回归，不把本草稿列名当已覆盖。不得抄R90的381为R91预期数。唯一运行需正常库false／ProviderReceiver0、非selfcheck denials0、实际child exit0/live0、resources_closed、源before/after一致和S2 before/after pin；失败必须保留首红与窄修复证据，不改写为一次全绿。

## 11. 冻结、回退与当前待决点

R90最终seal已由Root独立核实。R91必要源码baseline已由Root归档至 [baseline.json](../../.artifacts/r91-baseline-1233b51fa2424a1e/baseline.json)，5213B／`0c41e3390886575551d2ad306079c9aaca45c90b01736fe6a8f15140b4ee404f`，精确保存8生产＋runner共9源原字节及副本；本设计作者未创建它。Guard／ChildPolicy与冻结PDF合同沿用R90封存引用及原字节边界，不扩成新配置。只采用必要设计、源码baseline、受管测试和交接摘要，不为本稿再叠加独立meta回执层。设计静态检查不替代正式run或来源许可，无须重跑R90来准备R91。

Root追加授权的非pinned纯producer旧test适配不改变8生产／2新测试边界；互审与封存须单列该旧文件差异，证明仅新增局部fixture且原7函数逐字节保持，不混入Guard／ChildPolicy或既有pinned tests变动。

回退只按R91显式baseline恢复本轮owner确认的差异；不得stash/reset/clean或覆盖其他dirty，不回写旧产物，不清理未知artifact／DB／对象，不改R89/R90封存。运行前如果来源许可仍pending，接受生产local/Provider/export关闭作为正确结果，不以“功能不可用”为由放开policy。

Root已认可的冻结决定：采用B八文件／两个新测试；三个固定ledger安全码；确定未dispatch的本地门failed以全零token释放reservation/pending并保留请求次数；生产local pending也拒绝；Provider/export恒false；纯旧report/pack读取保持；关系当前summary完整性错误显式403/503，binary pending时保留现有完整链统一拒绝撤销、不加许可豁免。其余命名、内部capsule结构与no-op快速路径可按既有风格定，不增加用户确认流程。

当前为R91设计冻结方案，实施／运行以Root Gate为准，尚未实施或运行；未核正常库／PostgreSQL／浏览器／Native／真实来源许可／生产Provider，没有完整消费者／完整V1或生产ready声明。
