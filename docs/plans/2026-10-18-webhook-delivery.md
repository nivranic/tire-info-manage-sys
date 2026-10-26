# R78 Webhook Delivery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 沿用用户持续实施及ultra协作授权，不自动提交、切换工作树或丢弃既有dirty。

**Goal:** 落实原规格P1 `POST /v1/webhooks` 对外变化通知：受管理目标、用户明示订阅、事务内出站队列、签名、有限重试、人工重试／取消及可核历史。

**Architecture:** 现有站内通知保持原行与原语义；新增账户所有的Webhook修订和持久投递／尝试账本。通知创建与最小引用事件入队在同一数据库事务内完成，独立Worker租约派送。只有本机操作者配置的固定HTTPS目标可以接收，正文不携带来源事实、原件、私人规则／兴趣名称或偏好。

**Tech Stack:** FastAPI／Pydantic／SQLAlchemy／SQLite私库、aiohttp及现有PublicResolver、HMAC-SHA256、React／TypeScript共享三端前端。

---

## 依据、选择与未关闭范围

原始规格第560–561、597、1133行明确Webhook、创建端点及通知队列lag目标。本轮实现Webhook产品流程；邮件／Push、公共API生产鉴权、真实外部目标长周期与生产lag≤5min仍按各自证据验收。完整V1及R77未完成项不缩小、不标完成。

本轮研究已确认：EPREL正式API申请需签名声明和Key，官方接口语法文档转EU Login；Tyre Reviews API须账户／合同／付费或明确试用许可。不能猜正式合同、借网页内部API或代签申请。NHTSA新样本有TIN但缺完整SKU和已核整件许可；EU实验室校准样本编号不等于产品码。研究记录单独保存，不增加capture／Golden或模型授权。

方案比较：采用**通知事务内outbox＋独立Worker**，避免采集事务内网络调用及轮询旧通知补发。操作者固定目标目录比任意回调URL更适合当前本机形态；正式公开API端点注册与生产账户边界后续另验。首版发送有用的稳定通知／证据引用信号，不把受限来源事实外发；完整事实导出另依既有权利合同，不能用Webhook旁路。

修改前已重跑R77静态audit并通过：996源码／414展开dirty／34文档／61证据／4配置；清单SHA `a94340c9158715b3ceec463c4fe99bb863ca1d4ea274a18163e1f0c69510a9e2`。本轮根 `.artifacts/r78-webhooks-07dbe04ea45042c0bf98f0175fe5dbad/`，baseline已保存。历史封存均不回写。

## 冻结不变量

1. 默认目标目录为空、无订阅、无外发。只读API、页面加载、导入模块、创建暂停订阅均不联网。只有用户明确启用且有可用目标时，未来新通知才入队；不扫描旧通知补发。
2. Webhook按稳定`owner_user_id`归属；所有写与读取先登录再验证body，外账户404。同cookie既有聚合非全站安全边界，额外Webhook所有权不能宣称修复旧体系。
3. 支持三类channel：`tire_monitor`（本机共享轮胎提醒，界面明说共享）、`recall_monitor`（本人当前账户会话的召回通知）、`interest`（本人兴趣通知，含当前九域）。私人通知创建时绑定当时账户，不可因会话换绑改投新账户；匿名私人通知不外发。共享轮胎规则无稳定账户owner，只有明确选择共享channel的订阅接收引用。
4. 正文仅固定schema、稳定delivery ID、channel、notification ID、原event ID、interest domain（非interest为null）、原发生时间、`data_scope=notification_reference_only`及固定边界文字。无规则／兴趣名、条件、账户ID、用户名、来源正文、数值、问题、偏好、URL、cookie、原件或API key。私人的通知引用本身也须启用时明示同意外发。
5. 入队与新站内通知同事务，唯一键`(subscription_id,channel,notification_id)`；回滚不可留下outbox。只在`monitoring.py`、`recall_monitoring.py`、`interest_events.py`三个现有通知创建点显式调用enqueue，不增加SQL全局flush扫描或Worker事后反查owner。为尚未分配PK的本次新通知分配UID后冻结正文，不能修改原通知／原事件或事后读当前业务事实生成正文。坏hash／不完整引用拒绝派送。tire的event_id=AlertEvent.id，occurred_at=底层ChangeEvent.observed_at；recall=RecallEvent.id/observed_at；interest=InterestEvent.id/observed_at。
6. 目标来自`TI_WEBHOOK_TARGETS_FILE`可信JSON：`schema=webhook-targets@1,targets:[{id,title,url,signing_key_env}]`，≤256KiB、≤16项。HTTPS固定URL、443、无userinfo／query／fragment，合法host，禁止任意URL／headers／Cookie／环境代理。签名key仅从`TI_WEBHOOK_SIGNING_[A-Z0-9_]+`引用读取，要求64位hex（32字节）；不写数据库、日志、JSON或前端。目录加载一次，Worker各自加载，变更重启生效。
7. 目标policy指纹绑定实际URL、目录字段和当前签名key的承诺；订阅修订绑定准确指纹。目录／密钥变化后旧投递不得自动改接收端或改签。API仅暴露目标ID、标题、接收host、ready与opaque指纹；无key及完整私有URL。缺配置／缺key有明确状态，不能假装可发。
8. 订阅create／edit／pause／resume／archive／restore均追加修订，乐观`expected_revision`；create默认暂停。restore保持暂停。启用或改接收策略须当前target指纹及`acknowledged_external_delivery=true`。任何新修订使旧队列失效，pause／resume ABA不复活旧队列；新通知用新修订。不支持修改订阅target_id，另建订阅。
9. 上限每账户16个未归档订阅、单订阅最多1000个未终态投递。达到上限保持站内通知，同事务聚合增加订阅运行字段`suppressed_count,last_suppressed_at`，该修订首次overflow另追加一条审计；不为每次省略追加大量outbox。新修订取消旧未终态队列，不将无限old-pending留给扫描。计数是可变运行统计，不能修改owner／同意／body／历史ledger；详情明确queue_capacity，不能写成已送达。终态历史仍会增长，不宣称全库容量有界。
10. Worker显式运行，claim在ingestion lock内，以随机lease token和过期时间fence；预留尝试先commit再HTTP。每次attempt起点不可变、completion独立追加，queue只改运行字段。超时／崩溃不推断已送达；租约过期补unknown completion后有限重试。旧claim不能覆盖新claim结果。
11. 最多5次自动尝试，退避60／300／1800／7200秒；408／429／5xx与网络超时可重试，其他4xx、3xx、超限响应及无效目标明确失败，不跟跳转；2xx才确认接收成功。支持429／503整数Retry-After，限定1–3600秒。单次total8秒、响应体≤64KiB且不保留、并发1、逐目标≥1秒、一次cycle≤100jobs；队列TTL7天。签名使用当前时间、稳定delivery ID、attempt number和精确body hash，正文原字节不随重试变化。
12. HMAC签名明确定义为`HMAC-SHA256(key, timestamp + '.' + delivery_id + '.' + attempt_number + '.' + raw_body)`，前三段均为ASCII，timestamp为UTC epoch秒十进制ASCII，raw_body为固定sort_keys/ensure_ascii=false/separators(',',':')的UTF-8原字节，无BOM／尾换行；头：`X-Tire-Webhook-Id`、`X-Tire-Webhook-Attempt`、`X-Tire-Webhook-Timestamp`、`X-Tire-Webhook-Signature: v1=<hex>`及JSON Content-Type。接收方核时间窗口和恒时签名比较，并以delivery ID去重。文档提供独立验证示例与明确at-least-once语义，不承诺exactly-once。
13. 真正adapter调用前重读当前enabled修订／owner存在／冻结body／目标policy／lease；暂停、删账户或配置变化都零新调用。开始HTTP后无法追回，UI／文档明确边界。网络用PublicResolver实际connector防非公网和DNS重绑定，TLS校验正常、trust_env=false、redirect=false、无自动重试。
14. 人工retry需本人、`expected_attempts`及明确确认，仅限同一仍有效订阅修订的terminal failed/blocked；最多每次增加5次预算、总上限20、稳定delivery ID和body，追加审计；失效订阅不能重试。cancel可在缺key／目标目录删除或订阅归档后操作，但无法撤回已发请求；重复UUID同请求只读重放，异body冲突。attempt次数／租约／签名key不由用户自由提交。
15. API错误／任务／遥测只记录安全code、HTTP状态、次数、时间、body hash，不保存异常repr、URL、响应头／body或签名。历史API重校冻结bodyhash和关联，损坏明确拒绝。创建、变更及人工动作UUID幂等，绝不自动发送测试消息或以GET派送。
16. 022仅新增Webhook表及严格append保护；SQLite/ORM禁止ledger update/delete/replace绕过。正常API/DB不启动、不迁移；PG运行另验。R70/R71/R74专业Provider/export限制与R77 C合同不改。

## Wire合同（实现前冻结）

- `GET /v1/webhooks/targets` → `{schema:'webhook-targets@1',items:[{id,title,endpoint_host,ready,policy_fingerprint}],notice}`。
- `POST /v1/webhooks` →201，`Idempotency-Key: UUID`；body `{name,target_id,target_fingerprint,channels,enabled,acknowledged_external_delivery}`。
- `GET /v1/webhooks?mode=history&limit=...&offset=...` → `{schema:'webhooks@1',items,total,limit,offset}`；`GET /v1/webhooks/{id}?mode=history` →专用详情。
- `PUT /v1/webhooks/{id}` →body `{expected_revision,name,target_fingerprint,channels,enabled,acknowledged_external_delivery}`，UUID幂等；target_id固定。
- `POST /v1/webhooks/{id}/state` →body `{expected_revision,action:'pause'|'resume'|'archive'|'restore',target_fingerprint,acknowledged_external_delivery}`，UUID幂等；revoke/pause/archive不要求target可用。
- 订阅详情 `{schema:'webhook@1',id,owner_scope:'current_account',revision,revision_id,name,target_id,target_fingerprint,endpoint_host,channels,enabled,archived,created_at,updated_at,readiness,notice}`；无owner ID或私有URL。
- `GET /v1/webhooks/{id}/deliveries?mode=history&limit=...&offset=...` → `{schema:'webhook-deliveries@1',items,total,limit,offset}`；`GET /v1/webhooks/{id}/deliveries/{delivery_id}?mode=history` →详情。
- 投递摘要 `{id,webhook_id,webhook_revision,channel,notification_id,event_id,domain,state,attempts,max_attempts,next_attempt_at,created_at,completed_at,error_code,http_status,body_sha256}`；详情再加`schema:'webhook-delivery@1',body,attempt_history:[{number,started_at,completed_at,state,error_code,http_status}],current:false`。状态固定`pending|inflight|delivered|failed|blocked|cancelled`。
- `POST .../deliveries/{delivery_id}/retry` →`{expected_attempts,acknowledged:true}`；`POST .../cancel`同body，UUID幂等，返回投递详情。
- 正文 `{schema:'tire-webhook-event@1',delivery_id,channel,notification_id,event_id,domain,occurred_at,data_scope:'notification_reference_only',notice}`，所有字段封闭，domain为null或真实interest域。
- 如必要wire变更，先Root与前端对齐并新建addendum，冻结正文不覆盖。

### 冻结前补齐的wire闭包

- targets顶层增加`catalog_state:'empty'|'ready'|'invalid'`，item增加`state:'ready'|'key_unavailable'`，`policy_fingerprint:string|null`。非法目录整体fail closed为空items／invalid，不导致正常查询服务失去可用性；不会输出原错误repr。valid目录缺key的目标保留host并not-ready／null。允许保存该目标的paused草稿，指纹必须等于当前null；启用必须ready、非null准确指纹及同意。缺目录目标不能创建。
- 订阅`readiness`为`'ready'|'paused'|'archived'|'target_missing'|'key_unavailable'|'policy_changed'|'owner_missing'|'configuration_invalid'`；按archived、invalid、missing、key、changed、paused、ready优先展示。详情再加`suppressed_count:number,last_suppressed_at:string|null`。pause/archive/restore与取消不依赖目录、key或非null指纹；旧owner ID为历史字符串，不用外键阻止既有删账户。
- 所有write改为返回冻结动作回执：`{schema:'webhook-operation@1',id,idempotency_key,action,created_at,resource_type:'webhook'|'delivery',resource_id,response,current:false,replayed:boolean}`。`response`为该动作首次提交时的订阅／投递详情，另GET读取当前状态。所有动作追加WebhookOperation，唯一`(owner_user_id,idempotency_key)`，绑定HTTP method/path、封闭request与response hash；同key异body/path/action冲突。
- 新增`GET /v1/webhook-operations?mode=history&key=UUID`，本人专用只读恢复该冻结动作回执，`replayed=true`，不存在404。POST首次`replayed=false`，同键重放和GET均true；不会再写、派送或重建为当前响应。客户端创建响应丢失也不靠名称猜是否成功。回执损坏或关联无效明确拒绝。
- 分页统一`limit`默认20、范围1–100，`offset`默认0、范围0–10000；只接受整数，SDK不发送undefined；列表total为本账户过滤后的总数。
- 所有时间为带UTC时区ISO字符串；摘要的`next_attempt_at,completed_at,error_code,http_status`可null；`body_sha256`64hex，`attempts`0–20、`max_attempts`5–20且不小于attempts。attempt_history.number≥1，started_at必有，completed_at/error_code/http_status可null；state封闭为`inflight|delivered|retryable_failure|failed|blocked|unknown|cancelled`。HTTP状态为100–599整数或null；error_code为安全snake_case短码或null。
- domain只允许null或`tire|test_event|vehicle|fitment|tire_curation|tire_lifecycle|tire_identity|tire_catalog|tire_curation_validity`；只有interest使用非null，其他为null。不推造业务证据链接。

### 独立设计审查后的最终闭包

- 三类映射固定：`NotificationDelivery.id → AlertEvent.id → ChangeEvent.observed_at`（正文event_id取AlertEvent.id，历史同时核其ChangeEvent关联）；`RecallNotification.id → RecallEvent.id/observed_at`；`InterestNotification.id → InterestEvent.id/observed_at/domain`。`RecallDiscoveryNotification`只有candidate_id，本轮不入队，界面明确召回channel仅已形成RecallEvent的规则通知；不伪造event_id。个人owner须在通知创建事务中从该通知session的**未过期且仍绑定现存账户**冻结，过期／匿名不外发；Webhook API自身也验证未过期登录，不借此宣称修复原账户系统。
- enqueue只add/flush，绝不调用`lock_ingestion()`（其实现会先commit）、commit、新Session或网络。新通知UID先分配，原通知及全部outbox同事务回滚；不处理read_at变更，不用全局flush扫描。冻结原始关联与最小正文，owner后续不靠session_scope重算。
- 禁止IP字面量host以及legacy numeric形式（纯数字／十六进制／点分数字等），不允许以PublicResolver替代URL语法校验；域名连接仍使用真实connector的PublicResolver并逐次拒绝非公网地址，不复用旧DNS连接绕过复核。
- 跨进程并发1须持久全局dispatch slot，另持久每target的next_allowed_at；在同一个ingestion锁事务领取全局槽、目标槽及delivery，不能仅进程锁／sleep。lease固定30秒，HTTP总超时8秒；HTTP前复核剩余lease至少10秒，否则不发并等待过期unknown流程。完成须同token＋attempt且lease未过期；过期补unknown与迟到completion只能有一个终结。全局槽只由所属token释放，过期旧claim不能释放新claim的槽；每target间隔从claim起至少1秒，HTTP串行上限仍由全局槽保证。
- 历史必须核不可变envelope与owner/subscription/revision/notification/event/origin/domain/policy/body关联、attempt起点和唯一completion的连续性。不能只比较可变queue行自己的body/hash；queue只存运行状态、索引和不可变记录引用。损坏历史fail closed，不修写后再称原件完整。
- retry仅同一有效修订、未过TTL、正文及关联完整、owner仍存在的failed/blocked；可恢复配置缺失仅在**同一冻结policy重新可用**时允许，策略变更、过期修订、取消、投递成功、损坏及TTL过期均不可retry。每次+5（总20），attempt编号不重置，body/delivery ID不变，retry后next_attempt_at为当前时间；后续退避按本轮5次中的失败序号重复60/300/1800/7200秒。人工动作追加独立账本。cancel inflight只停止后续派送，迟到2xx可追加该attempt的事实completion但不能将cancelled队列改成delivered；若lease已过期则只保留先赢的unknown，旧返回不得覆盖。
- overflow每subscription为有界可变统计（详情/列表`suppressed_count,last_suppressed_at`），首次每revision追加一次不可变审计，不能每次另插blocked delivery；revision变更后保留累计统计并以新revision首次审计作区分。pause/archive/restore/cancel不依赖目标配置，动作body的target_fingerprint允许null；resume仍严格验当前指纹和同意。`owner_missing`历史只作明确内部状态，账户删除后不允许凭旧session读取。
- API所有写以`WebhookOperation`冻结响应为准；上方简略“返回投递详情”等措辞统一服从动作回执闭包，不能混合两种成功shape。目录items的`ready:boolean`保留并与`state`严格一致；UTC时间均须显式带时区。前端无默认channel、默认enabled=false／同意false，超时保留UUID并只读恢复，不自动重复POST。

## Task 1：后端、事务队列与Worker（backend所有）

**Files:** 新建`apps/api/tire_api/webhook_models.py`、`webhook_policy.py`、`webhook_transport.py`、`webhooks.py`、`webhook_delivery.py`；修改`db.py`／`migrations.py`／`main.py`／`monitoring.py`／`recall_monitoring.py`／`interest_events.py`／`apps/worker/monitor.py`／`apps/api/tests/version_registry.py`；新建`apps/api/tests/test_webhooks.py`、support及必要迁移测试。

1. 先读auth/通知三种来源、ingestion锁、追加保护及transport；先为缺权限／目标／同意、重复事件、回滚／租约／pauseABA写有意义反例。
2. 实现配置与models／022、路由、同事务enqueue、签名受限transport、workercycle与命令行显式`--webhooks-once`入口。普通monitor cycle也处理已启用的Webhook队列；默认空目标保持无外发。
3. 目标测试必须真SQL／ASGI／生产入队与冻结正文，受控transport仅替代边界的实际上游；不mock账户／队列／lease／policy。签名由独立预期计算。报告每阶段计数和hash。
4. 所有权归属不明或上限／overflow账本设计先报告Root；禁止弱化冻结不变量以求绿。

## Task 2：类型、SDK与面板（frontend所有）

**Files:** 新建`packages/domain-types/src/webhooks.ts`、`packages/api-client/src/webhooks.ts`、`packages/api-client/tests/webhooks.mts`及contract tsconfig、`apps/web/components/webhooks.tsx`／`.css`；修改公共导出／package script及现有monitoring面板挂载点。遵守`apps/web/AGENTS.md`及Next当前版本文档。

1. 严格类型／SDK封闭字段和安全接收；查询强制history，写带UUID，失败先GET读取状态，不自动POST重试。
2. 目标空／缺key说明，选择操作者目标和接收host、明确共享轮胎与私人引用channel范围，默认暂停；启用必须勾选外发同意。提供编辑／暂停／归档／恢复、分页投递／完整冻结正文／尝试历史、明确人工retry／cancel。
3. actor／选择变化清空私有状态、隔离迟到结果；错误保留UUID便于回看，不显示key或内部异常。不能把at-least-once、HTTP超时或取消显示为对端一定未收到。
4. SDK正反例、typecheck与三端前端build，Root再做桌面／390／320和owner迟到HTTP验收；不称原生设备或真实接收端验收。

## Task 3：独立反例与集成（review／Root所有）

独立审查默认空／权限先于body、跨账户、共享与私人归属、同事务回滚、前后notification重复、pause/resume及目标变更ABA、重复UUID、崩溃unknown/租约fence、deadletter与人工retry预算、正文变异、签名原字节及redirect／内网／DNS重绑定。独立测试新建`apps/api/tests/test_webhooks_review.py`，只写独立测试，不改生产。Root核跨Worker迁移和相关原监控、兴趣／召回回归，做真实React私库流程，实际外部接收端为0。

## 验证、保全与退出

- PowerShell7与`apps/api/.venv/Scripts/python.exe -X utf8 -B`；导入main前清宿主数据库／Provider／proxy／遥测，两数据库环境变量指同GUID短私根，objects/bundles私根。normal DB、真实外联与未许可子进程用护栏拒绝；Windows内部socketpair精确临时endpoint单列。
- 所有既有dirty与R77历史证据保留，Parser8秒／5秒CPU／384MiB／并发2不改。失败留新GUID回执，不覆盖历史final，不做正常服务smoke或外部真人通知。
- 合同／研究／源码／独立反例／SDK／UI证据分别封存；更新README／两交接／风险和本轮报告，后续封存单独核R77允许变更及全部保全。完整Goal保持active。
- 回滚通过暂停订阅／Worker队列派送，保留历史；正常库未应用022，无生产库回退或清理操作。
