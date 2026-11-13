# 外部只读 API 与凭据管理

本机服务提供账户 API Key、来源目录、本人 Webhook 投递历史，以及受许可的轮胎事实与 Safety Gate 周报告警读取。它保持 loopback／TrustedHost 限制，没有开启公网部署。比较、AI、原件导出和外部写 API 尚未接入这套 Key。轮胎接口详见[事实读取合同](EXTERNAL-FACT-API.md)，Safety Gate 合同见下文。

在“我的关注”的监控区域打开“外部 API 凭据”。创建时选择权限、有效期并勾选授权；首次成功只显示一次密钥。界面关闭显示后无法重读。密钥不进入 LocalStorage、SessionStorage、URL 或文档；本地恢复指针只保存账户 ID 与操作 UUID。

R80 将管理库存拆成“本人全部有效密钥”和“密钥签发历史”。有效列表完整展示本人当前最多16把有效Key，历史每次读取一页，不受旧端点最近100条限制。历史读取失败不会隐藏有效列表；创建、撤销或刷新后从最新窗口重读。

| Scope | 可调用端点 |
|---|---|
| `sources:read` | `GET /external/v1/sources` |
| `webhooks:read` | `GET /external/v1/webhook-deliveries`、`GET /external/v1/webhook-deliveries/{id}` |
| `facts:read` | `GET /external/v1/tire-facts`、`GET /external/v1/tire-facts/{variant_id}`，另需冻结归属及字段许可 |
| `safety-gate:read` | `GET /external/v1/safety-gate-reports/{report_id}/alerts`，另需本人成功周报查询及字段许可 |

每账户最多16把有效 Key，期限1–90天。撤销即时阻止后续请求；到期、账户删除或 HTTP／CLI 重置密码也使凭据失效。注销本机会话不会撤销已授予应用的 Key。轮换时先创建新 Key，确认应用使用后撤销旧 Key。

外部端点仅接受严格的 `Authorization: Bearer …`。Cookie不能代替Key；带Authorization访问本机业务路由会被拒绝，不能借Key调用旧匿名／Cookie API。无效、过期、撤销、删户统一401，权限不足403。每个有效Key每分钟60次的固定窗口限额持久化在数据库，失败的路由／参数请求也占额，超限429附Retry-After。这不是生产网关或匿名流量防护。

## 管理 API

以下端点仅使用未过期的登录Cookie，不接受Bearer。所有POST都要求UUID `Idempotency-Key`。

| 请求 | 说明 |
|---|---|
| `GET /v1/api-keys?mode=history` | 本人最近100条metadata，包含撤销／过期 |
| `GET /v1/api-keys/active?mode=history` | 本人全部有效Key；`{schema:"active-api-keys@1",items,read_at}` |
| `GET /v1/api-key-history?mode=history&limit=20&cursor=…` | 全部签发历史的单页；`{schema:"api-key-history@1",items,limit,next_cursor,window_started_at,read_at}` |
| `POST /v1/api-keys` | `{name,scopes,expires_in_days,acknowledged:true}`；首次成功201含token |
| `POST /v1/api-keys/{id}/revoke` | `{acknowledged:true}`；撤销终态 |
| `GET /v1/api-key-operations?mode=history&key=UUID` | 冻结写回执，无token，不表示Key当前状态 |

同UUID重放只返回metadata，永不重新发放token；换payload／方法／路径返回409。写入结果未知时，界面阻止再次创建并只用GET核对。若服务器已创建但首次响应失落，撤销该Key后以新UUID创建。404只表示暂未观察到结果，不能证明在途事务不会提交。

数据库只保存Bearer的SHA256及独立游标签名秘密，不存Bearer原文。Key、撤销和操作回执为追加记录；管理员重置密码与撤销在同一事务完成。账户归属采用固定user ID，不随原Cookie会话换绑。

两个新库存GET额外要求单个 `X-Tire-Expected-Account`，值为调用方当前预期账户的安全ID（1–64个ASCII字母数字下划线连字符）。它是账户提示，不是凭据；匿名／失效Cookie仍401，缺失／重复／非法头422 `api_key_expected_account_invalid`，账户不符409 `api_key_owner_changed`。三端Native传输仅对这两个精确GET路径开放该头。

有效全集以服务端 `read_at` 分类；异常超过16把返回409 `api_key_active_limit_invalid`，不静默截断。历史按 `(created_at,id)` 倒序、limit默认20且范围1–100、末页cursor=null，无total。首个不可变Key作为签名anchor，owner只输出HMAC承诺；anchor撤销或到期不影响翻页，每页仍验证登录账户。窗口上界和900秒期限固定，不续期，超时409 `api_key_history_cursor_expired` 后须显式重读；其它坏cursor422。未知／重复query422 `api_key_inventory_query_invalid`。

历史是有上界的keyset窗口，不是跨请求数据库快照；撤销metadata来自本页单次joined SQL读取，`window_started_at`不是本页状态时间。新签发、同时间插入和历史回填可能影响窗口成员。界面每次只保留当前一页；历史错误时可从最新重新读取。

## 分页与数据含义

来源目录与Webhook两个外部Bearer列表均返回 `{schema,items,next_cursor,limit,data_state:"local_snapshot"}`。这两个列表的`limit`默认20、范围1–100；最后页`next_cursor=null`。后续页使用原limit、过滤及cursor，不能跨Key、账户或端点复用。未知／重复参数、损坏cursor均拒绝。游标签名不加密数据，其owner绑定使用逐Key HMAC承诺值，payload不包含原user ID。15分钟有效期从第一页起固定，不随翻页延长。轮胎事实与Safety Gate另有更严格的页面容量限制。

来源目录只含 `id/name/source_class/region/parser_version/status`。ID最多80个安全字符，其余字段null或最多500个可打印Unicode码点。它描述适配器目录，不证明实时来源可达。目录摘要变化返回409 `external_catalog_changed`，从第一页重读。

投递列表可加 `channel=tire_monitor|recall_monitor|interest` 和 `webhook_id`。使用 `(created_at,id)`递增keyset与第一页上界，仅返回冻结归属于本人账户的envelope。当前派送状态取读取时值；它不是跨请求数据库快照，历史回填或同时间插入可能影响窗口。详情包含R78的最小引用正文及尝试历史，不含事实值、私人条件或原件。引用ID本身不授予其它业务API的权限。

## TypeScript SDK

`tireApi.apiKeys/createApiKey/revokeApiKey/apiKeyOperation`走已有Cookie传输。外部客户端单独创建，不污染浏览器共享传输：

库存使用 `tireApi.activeApiKeys(expectedAccountId, signal?)` 和 `tireApi.apiKeyHistory(expectedAccountId, {limit?,cursor?,signal?})`。SDK显式发送账户提示头，验证闭合DTO、唯一ID及微秒级倒序；不向外部Bearer客户端发送Cookie或库存请求。

```ts
import { createExternalApiClient } from "@tire/api-client";

const api = createExternalApiClient(process.env.TI_EXTERNAL_API_TOKEN!, (path, init) =>
  fetch(new URL(path, "http://127.0.0.1:8000"), init));
const first = await api.sources({ limit: 20 });
// 后续页沿用limit；first.next_cursor为null时停止。
```

示例为服务器／可信本机程序。应用必须把transport固定到可信服务origin，不能让用户或远程内容选择接收凭据的目标。SDK仅发送GET，使用credentials=omit、no-store、redirect=error及no-referrer，不自动重试；来源／Webhook响应最多1MiB，轮胎事实按其专属合同限额，Safety Gate每页最多2MiB。严格校验DTO与投递正文摘要，HTTP／传输异常使用无凭据文案。

023迁移的历史私库验证见[第79轮报告](assurance/evidence/round-79-external-api.md)，R80库存补修见[第80轮报告](assurance/evidence/round-80-api-key-inventory.md)。当前受管外部事实Reader支持SQLite与PostgreSQL；PG采用新鲜READ COMMITTED、ingestion advisory锁及固定表SHARE锁，具体并发、预算和超时边界见[独立验收](assurance/evidence/postgres-owned-reader-2026-11-13.md)。生产TLS／IAM／RLS、PG运维管理入口／吞吐、分布式网关和完整外部CRUD仍待交付，普通业务与外部Reader分别验收。

## Safety Gate受许可周报告警

请求为 `GET /external/v1/safety-gate-reports/{report_id}/alerts?mode=history&query_id=…&limit=20&cursor=…`。report_id沿官方数字身份；query_id必须来自当前Key所属账户的新成功周报查询，包含正常304重核验。匿名旧查询、失败请求、索引查询与历史回退不能替代成功周报查询。limit为1–20、默认20；未知／重复参数422，缺失或无权材料统一404。

需要同时满足新scope、冻结查询归属和当前受管字段许可。旧Key不自动取得scope；Key最多包含四种受支持scope。账户、Key撤销／过期、许可头与证据在每页新鲜受管事务中重核，支持SQLite与PostgreSQL；请求不抓取、不继承Cookie或持续回退授权。许可变化使旧窗口失效，仍获准的新头返回409 `external_safety_gate_window_changed`，撤回许可返回404。游标固定15分钟到期，损坏／过期或跨Key／query／report／limit复用返回422。未配置grant或许可不覆盖时统一404；不支持的Reader后端返回503。

服务端通过 `create_app(external_safety_gate_grant=...)` 配置固定grant ID，来源固定为eu-safety-gate；默认未配置，不能从客户端指定grant。管理员沿[许可账本流程](EXTERNAL-FACT-GOVERNANCE.md)预览并确认具体Snapshot／Parser／原件哈希与字段范围。官方CC0元信息可以作为审核材料，但不会自动批准或绕过账本；哈希本身不是权利证明。

所有成功投影必须获准以下14个身份／证据字段：

```text
identity.report_id, identity.report_reference, identity.alert_id, identity.case_number
evidence.report_published_date, evidence.alert_published_date, evidence.alert_source_url
evidence.source_id, evidence.snapshot_id, evidence.raw_hash, evidence.parser_version
evidence.source_url, evidence.observed_at, evidence.verified_at
```

其余19个可选字段均使用 `facts.` 前缀：category、product、brand、name、model_number、batch_number、barcode、risk_type、danger、measures、recall_url、description、notifying_country、country_of_origin、type、level、online_trader、company_recall_code、production_dates。只输出许可覆盖的字段；获准但源值未知的字段保留null。官方原文仍是源声明，不生成轮胎SKU适配或解除风险结论。

响应schema为 `external-safety-gate-alert-page@1`，包含query_id、report、observation、items、limit及next_cursor，固定 `data_state=local_snapshot`、`source_refresh_performed=false`。每项包含原生alert_id、case_number、published_date、source_url、`applicability=not_assessed`及获准facts。它不返回XML正文、图片、账户ID、私人规则或许可审核原文。每份XML／文档物化前分别限8MiB，累计存储读取限32MiB，沿受管预算限制行数／JSON深度／节点，最终页面限2MiB。合法大字段超限时拒绝整页，可由调用方明确选择更小limit重新读取。

```ts
const page = await api.safetyGateAlerts({
  report_id: "10000331", query_id: process.env.TI_OWNED_QUERY_ID!,
  mode: "history", limit: 20,
});
// 后续页带上page.next_cursor并保持query_id、report_id与limit不变。
```

SDK冻结请求字段，校验闭合DTO、固定来源URL、身份、证据时间、字段白名单和游标页序；跨页保持窗口与到期时间，不自动重试。SDK只能校验签名游标的形状，HMAC权限验证由服务端执行。支持AbortSignal，即便传输或流取消不响应，也不会无限等待。

2026-11-13验收覆盖正常HTTP、官方历史XML、官方许可元数据、共享SDK及生产Web签发／读取／撤销；没有实时官网或模型调用，没有公网／正式PG／Native验收，详见[本阶段记录](assurance/evidence/safety-gate-external-api-2026-11-13.md)。
