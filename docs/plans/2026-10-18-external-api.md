# 外部 API 凭据与游标 Implementation Plan

**Goal:** 交付账户持有、可撤销的只读 API Key，以及来源目录和本人 Webhook 投递引用的游标 API；保持在线优先及来源用途许可边界。

**Architecture:** 新 `/external/v1` 路由只认 Bearer，绕过本机会话创建，绝不把 Key 变成 cookie session。`/v1/api-keys` 仍只认已登录、未过期本机会话。复用 R78 不可变 envelope、现有账户及 ingestion 锁；不修改历史证据。

**Tech Stack:** FastAPI / SQLAlchemy / SQLite；TypeScript SDK；共享 React 面板。

本计划据原规格 REST P0、API Key、cursor pagination 及 R78 尚未交付项制定。用户已授权当前 agent 继续实施，复用 ultra 子 agent；不另询问实施批准，不提交推送。本轮不是完整外部 CRUD、云 IAM、生产公网或 V1 发布验收。

## 冻结合同

1. 凭据由服务端 `secrets` 生成：`ti_<32hex-id>.<64hex-secret>`；至少256bit随机秘密。仅创建首次成功响应含 `token`，其余读／幂等重放均 `token:null`。DB只存 bearer SHA256和另用的游标签名秘密，不存 bearer 原文；审计、异常、日志不得输出秘密。每账户最多16未撤销且未过期 Key，1–90天期限；name去空白、可打印、1–80字符。
2. 允许 scope 恰为 `sources:read`、`webhooks:read` 的非空去重排序子集。管理必须显式 `acknowledged:true`。所有新写带 UUID `Idempotency-Key`；同账户同key不同方法/路径/payload→409。重放不能重新签发token；失落创建结果可GET操作metadata并撤销后新建。撤销是幂等终态；不支持改scope/延期，轮换为创建新Key并撤销旧Key。注销不撤销，管理员重置密码须同事务撤销目标全部Key，删户后的旧Key永远401。
3. 管理API：`GET /v1/api-keys?mode=history` 返回 `{schema:"api-keys@1",items:ApiKey[]}`（包含已过期/撤销，最多最近100条）；`POST /v1/api-keys` payload `{name,scopes,expires_in_days,acknowledged:true}`；`POST /v1/api-keys/{id}/revoke` payload `{acknowledged:true}`；`GET /v1/api-key-operations?mode=history&key=UUID`。写/操作结果 `{schema:"api-key-operation@1",idempotency_key,action:"create"|"revoke",key:ApiKey,token:string|null,replayed:boolean}`。操作中的 key 是冻结写结果，不冒充当前状态。
4. `ApiKey` 精确字段 `{schema:"api-key@1",id,name,scopes,created_at,expires_at,revoked_at}`。归属仅用永久user ID，不用session_scope；不导出owner_user_id、hash、cursor secret。管理请求在校验body前验证账户并取得锁，防并发创建越限；403/401不得读别人的key。所有响应no-store/nosniff。
5. 外部仅两种GET列表及投递详情：`/external/v1/sources`，`/external/v1/webhook-deliveries`，`/external/v1/webhook-deliveries/{id}`。本机loopback/TrustedHost/origin边界维持；不新增公网监听或代理信任。外部路径Cookie不参与鉴权、不创建续期session；Authorization在本机业务路径一律拒绝，防Bearer误落匿名/cookie语义。拒绝重复Authorization、非严格Bearer、query token、过长token；无效/过期/撤销/删户统一401＋`WWW-Authenticate: Bearer`，scope不足403。本轮不开放Bearer写、模型调用、原文或事实导出。
6. 外部合法Key逐Key持久化固定分钟限额60次；原子计数，超限429＋Retry-After，进程重启不清零。有效Key的失败路由/分页请求也计数；无效Key不写库。外部仅允许GET；未知路径/方法不降级本机session。限额不等于生产网关/匿名DDoS防护。
7. 列表 `limit` 默认20，1–100；cursor最多2048字符，严格HMAC校验及15分钟固定失效。绑定Key id、owner、路由、limit及查询过滤；跨Key/账户/路由/limit不可复用，不因后续页延长期限。禁止重复/未知查询参数。列表 `{schema:"external-sources@1"|"external-webhook-deliveries@1",items,next_cursor:string|null,limit,data_state:"local_snapshot"}`。最后页next_cursor必须null。游标不是权限，每页重验Key和owner。
8. 来源目录只投影 `{id,name,source_class,region,parser_version,status}`（字符串或null），不输出源凭据/URL/私人设置。按id排序；cursor绑定本次目录摘要，目录变化409 `external_catalog_changed`，重新开页。明确它是适配器目录状态，不是轮胎查询结果或来源实时健康。
9. 投递列表只读当前账户冻结owner的envelope，按`(created_at,id)`递增keyset，初页冻结上界tuple；可选`channel`=R78三值、`webhook_id`<=64安全ID，cursor绑定过滤。复用R78 `delivery_view`/校验器；详情复用 `webhook-delivery@1`。列表成员窗口有上界，但不是跨请求数据库快照，mutable派送状态取读取时值；历史回填或同时间插入可能影响窗口，不宣称精确快照。没有原文/事实/私人条件导出，接收端引用仍不代表获得内网业务API权限。

## 文件所有权与实施

- Backend ultra：新增 `apps/api/tire_api/external_api_models.py`、`external_api.py`，修改 `db.py`、`migrations.py`、`main.py`、`auth.py`；新增 `apps/api/tests/test_external_api.py`。必要前置迁移夹具只做最小适配。023纯追加，私库测试旧行保全与失败回滚。
- Root：共享DTO/SDK、`apps/web/components/api-keys.tsx`与样式、monitoring挂载；文档/新轮runner及证据。SDK外部客户端显式注入transport、每次请求带Bearer、credentials=omit、拒绝重定向、不自动重试写，不把Key放全局浏览器transport或持久存储。管理SDK走既有cookie transport。
- Reviewer ultra：独立反例测试 `test_external_api_review.py`，重点身份/游标/并发/秘密泄露/幂等与隔离。先审合同再审实现。所有agent不得回滚他人dirty，不改R78封存、不启动正常DB、不调用Provider/公网。

## 验收与回退

新GUID私根先绑定数据库/objects/bundles/TEMP再导入产品，沿用R78无外网/子进程/正常库审计。新轮baseline保存R78 v2引用、当前dirty字节索引和源码哈希。使用复制至新轮的runner；禁止回写R78文件。

先跑目标后端和独立反例，再跑账户/迁移/Webhook相关回归。SDK类型及行为验证覆盖丢失token、串户/串cursor、损坏响应、参数与无持久化；工作区typecheck，三端前端build；真实私有ASGI采样和React账户失效/窄屏验收。未运行的PG、公网TLS/接收端、真实Responses及原生设备列为未验。

回退仅撤销本轮新路由/注册和新增模块，保留旧dirty及历史证据；正常库尚未迁移。已发放的私库凭据不写入文档/receipt，测试期结束关闭服务、丢弃内存显示，私库保全于忽略目录。本轮结果在独立review后更新交接和风险；原Goal保持active。
