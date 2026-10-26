# 外部只读 API 与凭据管理

R79 提供本机服务上的账户 API Key、来源目录与本人 Webhook 投递历史。它保持 loopback／TrustedHost 限制，没有开启公网部署。轮胎事实查询、比较、AI、原件导出和外部写 API 尚未接入这套 Key。

在“我的关注”的监控区域打开“外部 API 凭据”。创建时选择权限、有效期并勾选授权；首次成功只显示一次密钥。界面关闭显示后无法重读。密钥不进入 LocalStorage、SessionStorage、URL 或文档；本地恢复指针只保存账户 ID 与操作 UUID。

R80 将管理库存拆成“本人全部有效密钥”和“密钥签发历史”。有效列表完整展示本人当前最多16把有效Key，历史每次读取一页，不受旧端点最近100条限制。历史读取失败不会隐藏有效列表；创建、撤销或刷新后从最新窗口重读。

| Scope | 可调用端点 |
|---|---|
| `sources:read` | `GET /external/v1/sources` |
| `webhooks:read` | `GET /external/v1/webhook-deliveries`、`GET /external/v1/webhook-deliveries/{id}` |

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

两个外部Bearer列表均返回 `{schema,items,next_cursor,limit,data_state:"local_snapshot"}`。`limit`默认20、范围1–100；最后页`next_cursor=null`。后续页使用原limit、过滤及cursor，不能跨Key、账户或端点复用。未知／重复参数、损坏cursor均拒绝。游标签名不加密数据，其owner绑定使用逐Key HMAC承诺值，payload不包含原user ID。15分钟有效期从第一页起固定，不随翻页延长。

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

示例为服务器／可信本机程序。应用必须把transport固定到可信服务origin，不能让用户或远程内容选择接收凭据的目标。SDK仅发送GET，使用credentials=omit、no-store、redirect=error及no-referrer，不自动重试；响应最多1MiB，严格校验DTO与投递正文摘要。HTTP／传输异常使用无凭据文案。

023迁移只在新GUID私库验证。正常数据库未迁移；PostgreSQL运行、生产TLS／代理／IAM／RLS、分布式网关和完整外部CRUD仍待独立交付。R79基础与迁移边界见[第79轮报告](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-79-external-api.md)，R80库存补修及当前验收见[第80轮报告](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-80-api-key-inventory.md)。
