# 本机外部轮胎事实 API

本接口从已有、属于当前账户的正式查询观察中读取单个轮胎事实项，或按固定观察窗口分页读取事实项。它使用独立 Bearer API key，仅返回当前获准的身份、来源证据和九类事实；不触发来源刷新、采集、Parser 或 Provider。

使用本文前，先确认所选数据库、账户归属、当前来源许可和部署配置。本文示例均为占位，未在编写文档时运行。运行验收状态以 [HANDOFF](HANDOFF.md) 和对应证据报告为准；代码或合成私库验证不能证明真实法律许可、正常库、实际 PostgreSQL、浏览器网络或完整 V1 已验收。

## 账户、key 与正式观察

在既有本机登录流程下，通过 POST /v1/api-keys 或 SDK tireApi.createApiKey 创建包含 facts:read 的 key。请求需要 acknowledged=true、规范 UUID 幂等键、1–90 天有效期，scopes 可只含 ["facts:read"]。旧 key 不会自动增加权限；目前 Web 创建界面仍只提供原有两项 scope。首次创建成功才返回 token；重放不会再次返回 token，应当妥善保存首个结果。

外部请求只接受单个格式正确的 Authorization: Bearer 请求头。Cookie 登录不能代替 Bearer，也不能把外部查询归属改到当前浏览器账户。sources:read、webhooks:read 与 facts:read 相互独立。

读取单个事实项时必须明确给出四个选择器；分页时不传 variant_id，但仍须提供 source_id、query_id、verification_id：

| 选择器 | 来源及要求 |
| --- | --- |
| variant_id | 所选正式 Snapshot 中的确切轮胎成员 |
| source_id | 该观察的来源 ID |
| query_id | 具有服务器签发账户归属回执的正式查询 |
| verification_id | 属于该 query 的确切成功 Verification |

本人登录后的新在线查询可由 POST /v1/sources/{source_id}/live-query 建立可信归属。匿名、旧历史、后台或既有 consent 查询不会在事后补绑到登录账户。读取接口不会通过 Snapshot、最新查询、可变 session 或猜测 owner 来寻找替代记录。

正式链必须为 live/ok 或 live_verified_304/not_modified。另一个本人 query 可以合法复用同一已获准 Snapshot，但仍须保有它自己的 query/verification 归属链。接口不接受 owner、grant_id、snapshot_id、原始 URL 或“已认证”标志代替这些选择器。

## 来源许可与服务端 mapping

先按 [外部事实许可治理说明](EXTERNAL-FACT-GOVERNANCE.md) 完成管理员条款审查、preview、approve 和 current 复核。该文描述 G1b 治理切片；其中旧“G2 后续实现”文字保留为当时范围，不能作为本接口的当前状态。真实权利材料缺失时只能使用合成数据，不能将演示声明冒充真实 approved。

可读取的 grant 不仅要覆盖观察，还须覆盖全部必要证据与身份字段：evidence.source_id、evidence.snapshot_id、evidence.raw_hash、evidence.parser_version；identity.variant_id、identity.identity_status、identity.identity_contract_version；以及下述 identity.values 对应的全部 16 个 identity 字段。至少一项 facts 字段或其获准冲突名须可外发。治理文档中仅覆盖 facts.weight_kg 的最小演示请求，并不自动满足事实接口的完整覆盖要求。

可信部署代码通过 create_app 的仅关键字 external_fact_routing 显式选择每个 source 唯一的 grant。客户端不能选择 grant 或 revision；许可被撤回后不会自动切换到其他 grant。更换 mapping 须重建 app/reader，不提供热加载、环境 JSON 或文件配置入口。

以下为自定义 ASGI factory 示例，路径与 ID 均须由部署者替换并审查：

~~~python
# private_fact_app.py
from tire_api.main import create_app

def create_private_app():
    return create_app(
        database_url="sqlite:///E:/private/facts.sqlite",
        external_fact_routing={"source-id": "approved-grant-id"},
    )
~~~

导入 tire_api.main 本身不再立即调用默认 create_app()，但仍会导入顶层依赖并执行相关平台探测，不能描述为完全无副作用。模块在首次读取默认 app（包括 from tire_api.main import app）时，通过 __getattr__('app') 在锁内构造并缓存真实 FastAPI；若构造失败则不缓存，后续访问可重试，同线程递归访问会报错。显式调用 create_app(...) 仍立即构造所选 app/Database 及相关对象；访问默认 app 亦可能创建目录或对象存储资源。真正启动所选 app 的 lifespan 仍会初始化数据库和执行既有迁移。本文不启动该示例；实际部署前须先确认目标库及迁移、备份边界。服务继续限制本机 loopback，并检查 Origin 和 Sec-Fetch-Site。

默认 mapping 为空时，正常 app 的单项请求和分页初页返回与不可见记录相同的 404；已验真续页遇到 mapping 缺失或变化，按下文返回 409 external_fact_window_changed。用于自定义组装的 register_external_api_routes(app, fact_reader=reader) 需要调用方显式注入已组装 reader；旧调用只注册而未注入 reader 时，事实请求返回 503，旧 key 管理及来源/webhook 路由仍可注册。

## 读取一个事实项

~~~http
GET /external/v1/tire-facts/variant-id?source_id=source-id&query_id=query-id&verification_id=verification-id
Authorization: Bearer <token>
Accept: application/json
~~~

source_id 接受 1–80 个 ASCII 字母、数字、下划线或连字符，其余三个 ID 接受同类字符且最多 64 个。三项 query 必须各出现一次；未知、重复、空值、缺失或非法选择器返回 422。此单项接口没有 limit/cursor，不能通过请求体传选择器；分页接口的规则见下文。

成功返回 status="projected"、reason="projected"、item 三个顶层键。item 的 schema 为 external-tire-fact-projection@1，data_state 为 local_snapshot，source_refresh_performed 为 false；另含 observation、identity、facts、conflicted_fields。

- observation：source_id、snapshot_id、raw_hash、parser_version。不含来源 URL、query/verification、账户或许可台账。
- identity：variant_id、contract_version="variant-identity@2"、complete/source_scoped 状态及 values。values 恰含 brand、model、region、manufacturer_product_code、product_code_type、size、load_index、speed_rating、xl、hl、run_flat、oe_mark、acoustic_technology、gtin、technology_features、eprel_id。source_scoped 的未知值保持 null，不推断或合并。
- facts：当前许可允许的九类字段子集；缺键与显式 null 有不同含义，合法 0、false 和 null 不因真假判断丢失。false 只用于 identity 的布尔字段。
- conflicted_fields：只提供获准的规范字段名，不提供互相冲突的值；同名不会同时出现在 facts。

| facts 字段 | 非 null 的值 |
| --- | --- |
| utqg_treadwear | 0–5000 的整数 |
| utqg_traction / utqg_temperature | AA/A/B/C；A/B/C |
| eu_fuel_class / eu_wet_grip | A–G |
| eu_external_noise_db | 0–200 的整数 |
| eu_noise_class | A/B/C |
| weight_kg | 大于 0、最多 200，最多 3 位小数 |
| tread_depth | {value,unit}；mm：0–100/最多 3 位小数，1/32 in：0–128/最多 3 位，in：0–4/最多 4 位 |

这些界限是工程合同，不是法规结论；不进行 EU 等级、噪声或胎纹单位换算。人工覆盖、撤销、待复核及身份/生命周期状态会影响可外发结果；接口不公开人工说明或替代值。

raw_hash 是所存 Snapshot.body 的 UTF-8 摘要，不保证等于来源原始 HTTP 字节摘要。采集暂停也不等于历史事实许可已撤回，是否可读仍由当前许可和治理决定。

## 单项 SDK

~~~typescript
import { createExternalApiClient } from "@tire/api-client";

const apiOrigin = new URL("http://127.0.0.1:8000"); // 可信固定 origin
const api = createExternalApiClient(
  token,
  (path, init) => fetch(new URL(path, apiOrigin), init),
);

const result = await api.tireFact({
  source_id: "source-id",
  query_id: "query-id",
  verification_id: "verification-id",
  variant_id: "variant-id",
  signal: abortController.signal,
});
~~~

token 和 abortController 由调用方管理。该 client 使用 GET、omit Cookie、no-store、禁止重定向及 no-referrer；不会读取浏览器登录凭据。SDK 检查完整响应形状、九类值域、身份、冲突、返回 source/variant 与请求相符，以及响应字节预算。query/verification 未公开在响应中，SDK 不能独立核实数据库归属或许可。

## 分页读取同一正式观察

分页接口读取单个 source、精确 owned query/verification 指向的同一个不可变 Snapshot。它不跨来源或查询搜索，也不触发来源刷新、Parser 或 Provider；每一页都会重新核验当前 key、账户、归属、许可和候选治理。

~~~http
GET /external/v1/tire-facts?source_id=source-id&query_id=query-id&verification_id=verification-id&limit=20
Authorization: Bearer <token>
Accept: application/json
~~~

source_id、query_id、verification_id 必须各出现一次，分别符合上文的 ASCII ID 范围。可选 limit、cursor 各最多一次，不接受其他查询参数、重复键、空 cursor 或请求体选择器。limit 默认 20，只接受无前导零、无符号、无空白的 ASCII 十进制 1–20。续页须原样重复 source_id、query_id、verification_id 和有效 limit；省略 limit 仍表示 20。不能把一个窗口或 key 的 cursor 用到另一个请求。

成功页的根对象恰有 schema="external-tire-fact-page@1"、items、next_cursor、limit、data_state="local_snapshot"、source_refresh_performed=false 六个字段。items 是 1 到 limit 个上文的 projection item，不带单项接口的 status/reason 外层；按 variant_id 的 ASCII 顺序严格递增，同页均来自同一 source/Snapshot。没有 total、hidden 数量或隐藏原因。next_cursor=null 表示此窗口已到末页；非 null 时本页必有 limit 个 item。恰好满页也可能是末页。

下一页只需将原样 next_cursor 作为 cursor 传回。它是服务端签名的、不透明的私有 13 字段载荷，不是加密容器；客户端不应解码、修改或把它当成 Bearer、权限证明或可长期保存的结果集。签发时间起固定 900 秒，续页不延长；key 或许可可更早失效。相同 cursor 可重放同页；页间没有持久窗口表或跨请求数据库事务。SDK 只检查编码形状、请求绑定及响应内容，不能核验服务端签名、数据库归属或法律许可。

服务端每页都按固定 Snapshot 重建全部候选 U，再从可见成员中取页；U 最多 256 项，已返回、未返回和合法隐藏成员都参与治理与窗口指纹。合法 identity correct/merge、lifecycle revoke 或经完整校验后无可外发字段的成员可隐藏，但隐藏不能掩盖坏事实、坏 binding 或其它损坏。任何候选治理变化都可能令下一页失效，即使已返回的 facts 看起来相同；不会返回部分页。初页无可见项或不可用统一为 404 external_fact_not_available。对已验真的续页 cursor，窗口、许可或候选变化统一为 409 external_fact_window_changed；过期为 409 external_fact_cursor_expired。收到 409 后从不带 cursor 的第一页重新读取，不能把新窗口的页接到旧窗口结果后面。失效 key 仍优先 401，缺 facts:read 仍为 403；坏参数或 cursor 为 422。

全 U 的工程预算按每次 read_page 累积，而非按返回的 20 项分摊：实际 SQL 结果行数不得超过保守计费行数，后者最多 8192；四类成员历史窄列记录合计最多 4096；待物化字符串/JSON/二进制最多 16 MiB，规范 JSON 最多 262144 个节点、深度 16。所有候选的事实值投影调用最多 4096、最终投影最多 256，投影 item 累计最多 8 MiB 与 65536 节点。单个 item 编码最多 65536 字节，整页响应最多 1327104 字节。超过预算时初页 404、已验真续页 409，均不输出截断或部分结果。

沿用上文创建的 api，可以这样继续读取：

~~~typescript
const selection = {
  source_id: "source-id",
  query_id: "query-id",
  verification_id: "verification-id",
  limit: 20,
} as const;
const abortController = new AbortController();
const first = await api.tireFacts({ ...selection, signal: abortController.signal });
const second = first.next_cursor === null
  ? null
  : await api.tireFacts({
      ...selection,
      cursor: first.next_cursor,
      signal: abortController.signal,
    });
~~~

每页请求都计入共享的每 key 每分钟 60 次预约限额。不要把 token、完整 URL、选择器或 cursor 写入共享日志、截图或外部监控。

## 限额、错误与隐私

所有外部路由共享每 key 每分钟 60 次的预约限额；事实读取即使最终被拒绝，也可能已消耗一次预约。单项成功 JSON 响应预算为 65792 字节；分页成功响应最多 1327104 字节，且每个 item 编码最多 65536 字节。超限不截断；SDK 在解析前执行对应流式字节限制。既有来源/webhook 方法保持原容量。

| 状态 | 含义 |
| --- | --- |
| 401 | Bearer 不合法、key 到期/撤销、账户已失效；返回 WWW-Authenticate: Bearer |
| 403 | 缺 facts:read，或本机/跨站边界不允许 |
| 404 external_fact_not_available | 单项或分页初页无可外发事实；包括未映射、跨账户、缺正式链、许可撤回/不适用、治理拒绝或内部数据超限/损坏，不能据此判断记录是否存在 |
| 422 external_query_invalid | 选择器、参数集合或重复参数不合约定 |
| 422 external_cursor_invalid | 分页 cursor 无效或与当前 key/窗口选择器/limit 不匹配 |
| 429 | 速率预约已满；按 Retry-After 等待 |
| 503 external_fact_service_unavailable | reader 未注入，或后端、必要 schema、时钟不可用 |
| 409 external_fact_cursor_expired / external_fact_window_changed | 分页 cursor 到期，或已验真窗口不再可继续；须重取第一页 |
| 405 / 409（既有外部边界） | 外部方法不允许，或既有认证/速率历史状态无法通过检查；保留既有固定错误码 |

SDK 对非成功 HTTP 返回 ExternalApiError(status,"external_request_rejected")，不把原始错误响应体带入异常信息。所有外部响应使用 no-store/nosniff；单项与分页均不提供 ETag、304 或客户端事实缓存。不要把 token、完整 URL、选择器或 cursor 写入共享日志、截图或外部监控。

每次 reader 在 SQLite 锁内以同一个当前时点复核 key、账户、归属、许可和治理。读取完成后才发生的撤销或许可变化不会收回已传出的响应；下一次读取重新检查。首片只支持 SQLite owned reader；PostgreSQL 管理模块或 DDL 存在不代表事实读取支持 PG。本接口不启用 Provider/导出，也不表示完整 V1 已完成。
