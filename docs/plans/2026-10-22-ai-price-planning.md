# AI Price Planning Implementation Plan

> Execute in this chat using the existing implementation and independent review agents. Root owns formal verification, evidence application and reports. 本轮不创建 worktree，不 commit/push；保留其他代理和既有 dirty 修改。

**Goal:** 交付“管理员人工追加模型价格版本 → 登录用户按明确版本和工作量进行费用规划”的后端、共享 SDK 与 Web 闭环。

**Architecture:** 新增一张只追加的价格版本表和独立费用规划模块；规划仅用显式选定版本及输入工作量进行 Decimal 计算，返回可复算快照，不调用 Provider。沿用现有账户、路由注册、附加迁移、共享 DTO、客户端和工作台入口；既有 AI 执行、usage 和 Token 护栏继续独立工作。

**Tech Stack:** 现有 Python 3.12 / FastAPI / Pydantic 2 / SQLAlchemy 2、stdlib Decimal、TypeScript、React 19 / Next 16、CSS；不新增依赖。

---

## 依据、现状与本轮边界

- 原规格 `docs/requirements/2026-09-26-tire-intelligence-original.md:738-758` 要求价格可由后台维护、不编译进客户端，并区分工作量示例与 Provider 实际 usage；846–847 列出管理员 AI Provider / 成本中心。版本、币种、来源说明和有效期等逐字段合同是本轮实现设计，不能声称原文逐字段规定。
- 已读当前 `docs/HANDOFF.md`：R119 为 `027_test_event_golden`，R120 为比较表交互；完整 V1 仍 active。当前 Git HEAD 为 `4d0ef60fa2240146113a3fac172759c665cf339f`，它不是当前 dirty 产品快照；Root 必须另绑定实际产品文件。
- `ai_gateway.safe_usage` 只保留 input/output/total tokens；`ai_models.AIRequest` 只存协议 provider 和 model，没有计费厂商/账户身份。旧 usage 不套价，未知 usage 不从 `reserved_tokens` 推实际金额。
- Responses、Chat、Anthropic、Embeddings、执行限制及历史已经存在。`ai-budget.tsx` 和 `insight-panel.tsx` 的 Token/预留口径继续保留；本轮不重做或改变这些合同。
- `auth.py` 实际存在 `current_user`、`require_admin` 和 `make_admin_guard`，没有通用 `require_user`。本模块用闭包登录依赖调用 `current_user`，仿 `test_event_golden.py` 的 `401 login_required`；写接口使用现有 `make_admin_guard`，未经管理员登录为 `403 admin_required`。
- `main.py:283-315` 将 `UserSession.id` 用作 `tire_local_session` cookie。**`actor_session_id` 仅可私存数据库审计，绝不进入公开 DTO、规划快照、错误、日志、SDK、浏览器 DOM 或验收输出。** 同样不公开幂等 key 和请求 hash。公开管理员归属只用 `actor_user_id`。
- 功能名称一律“费用规划”。它不表示已消费金额、供应商账单或金额硬预算；不写 AI 请求/完成、Token 账本或执行配置，不建立规划历史表。
- 本轮只覆盖标准文本 input/output token 费用；无内置价格、原规格示例价格种子、真实来源抓取、外发、缓存/工具/长上下文/多媒体/税/汇率计费或多币种总额。

## 冻结 API 合同

### 价格版本

| 方法与路径 | 授权 | 请求/返回 |
|---|---|---|
| `GET /v1/ai/price-versions?offset=0&limit=10` | 登录用户 | `AIPriceVersionPage`；`offset>=0`，`1<=limit<=25`，默认 10 |
| `POST /v1/ai/price-versions` | 管理员 | `AIPriceVersionCreate` + 必填 `Idempotency-Key` UUID；返回 `AIPriceVersion` |
| `POST /v1/ai/price-planning` | 登录用户 | `AIPricePlanningRequest`；返回 `AIPricePlanningResult`，不持久化规划 |

三个接口成功均返回 200。对于有效 JSON，读/规划的登录依赖及写入的管理员依赖先于请求体语义验证执行；这不表示鉴权先于框架 JSON 解析。所有请求继承项目 closed DTO 规则，拒绝未知字段；价格创建请求不得包含 actor、记录时间、版本 ID、幂等 key 或请求 hash。

`AIPriceVersionCreate` 精确字段如下，全部必填，只有明确标记者可为 `null`：

| 字段 | 合同 |
|---|---|
| `vendor_label` | 人工厂商/计费方标签，去首尾空白后 1–100 字符；不等同于已验证的账户或厂商身份 |
| `provider` | `openai_responses` / `openai_chat` / `anthropic` / `openai_embeddings`；表示协议，不从它推计费厂商 |
| `model` | 精确区分大小写，模式 `[A-Za-z0-9][A-Za-z0-9._:-]{0,119}`；不得以模糊匹配或别名选价 |
| `currency` | 严格三个大写 ASCII 字母 `[A-Z]{3}`；不做币种存在性或汇率推断 |
| `input_per_million`, `output_per_million` | 只接收字符串，完整模式 `(0\|[1-9][0-9]{0,8})(\.[0-9]{1,8})?`；即最多 9 位整数和 8 位小数，非负，零价有效 |
| `source_note` | 人工来源说明，去首尾空白后 1–1000 字符；不是服务端在线核验结论 |
| `source_url` | `null` 或最长 2048 字符的绝对 HTTP(S) URL；必须有 hostname，无 userinfo、控制字符或反斜杠，只做本地语法校验，不解析 DNS、不抓取 |
| `effective_from` | UTC 时间字符串，见下方时间合同 |
| `effective_until` | `null` 或 UTC 时间字符串；非空时必须严格大于 `effective_from` |

金额字符串拒绝 JSON number、bool、负数、正号、空白、指数、NaN/Infinity、前导零、超长或超 scale 值；不能因 `StrictModel` 全局 strip 而先修正非法金额。日期和 model 同样先校验原始输入，不能偷偷改写成有效请求。

创建 `openai_embeddings` 价格版本时，`output_per_million` 必须严格为数值零（仍使用上述十进制字符串合同）；不得录入非零输出费率。

时间合同：只接收 RFC3339 UTC `YYYY-MM-DDTHH:mm:ss[.fraction]Z`，小数秒 1–6 位，秒必填；拒绝无时区、日期单值、非零偏移和无效日历值，返回规范 UTC `Z`。`effective_from <= planned_for < effective_until`；until 为 null 表示无结束上界。**历史复算和未来规划都允许**，不使用服务器 today 拒绝它们；只有选定版本不覆盖 `planned_for` 时不能计算。

`AIPriceVersion` 为上述全部字段加 `id`（服务端 UUID）、`recorded_at`（服务端 UTC）、`actor_user_id`。价格记录只追加，旧版本不能修改、删除或替换；重叠有效期可以存在，因为用户必须选择精确 ID。服务器不提供“当前最便宜”“自动厂商匹配”或自动选新版本。

创建幂等合同：唯一约束 `(actor_user_id, idempotency_key)`；相同管理员和 UUID、相同规范请求 hash 返回原版本，保留原 `id/recorded_at`；同 key 不同内容返回 `409 ai_price_idempotency_conflict`。只需价格单表私存 key/hash，不新增通用操作框架。并发唯一冲突需回读并作相同判定。

`AIPriceVersionPage = {items, offset, limit, has_more, next_offset}`。按 `recorded_at DESC, id DESC` 确定排序，以 `limit+1` 判断 has_more，末页 `next_offset=null`。不只截取前 100 条；Web 提供上一页/更早版本入口，已选版本在翻页后仍可保留。新增版本后可从首页刷新，不自动替换已选版本。

### 费用规划

```ts
interface AIPricePlanningItem {
  price_version_id: string;
  request_count: number;              // 严格整数 1..1_000_000
  input_tokens_per_request: number;   // 严格整数 0..100_000_000
  output_tokens_per_request: number;  // 严格整数 0..100_000_000
}
interface AIPricePlanningRequest {
  planned_for: string;                // 显式 UTC，不默认服务器 now
  items: AIPricePlanningItem[];       // 1..50；Web 首版显式提交一项
}
```

数字拒绝 bool、float、小数字符串、负数或越界；输入/输出 tokens 同时为 0 有效。`openai_embeddings` 版本的规划要求 `output_tokens_per_request=0`。价格版本 ID 使用严格 UUID 字符串。请求不再附带厂商/model/费率，避免与版本快照产生第二权威。

`AIPricePlanningResult` 顶层固定字段：`planned_for`、`calculated_at`（服务端 UTC）、`calculation_version: "standard-text-v1"`、`scale: 6`、`rounding: "ROUND_HALF_UP"`、`items`、`exclusions`、`notice`。逐项 `AIPricePlanningItemResult` 固定字段：`item_index`（从 0 开始）、`price_version`（完整公开版本快照）、`request_count`、`input_tokens_per_request`、`output_tokens_per_request`、`exact_input_total`、`exact_output_total`、`exact_total`、`rounded_total`、`formula`。

```python
# 在 localcontext() 内显式 ctx.prec = 80；不依赖 ambient Decimal precision。
exact_input_total = Decimal(request_count) * Decimal(input_tokens_per_request) * Decimal(input_per_million) / Decimal(1_000_000)
exact_output_total = Decimal(request_count) * Decimal(output_tokens_per_request) * Decimal(output_per_million) / Decimal(1_000_000)
exact_total = exact_input_total + exact_output_total
rounded_total = exact_total.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
```

80 位精度覆盖已界定 rate × tokens × count 的全部有效数字。三个 `exact_*` 均输出无指数的精确十进制字符串，去无意义尾零，零为 `"0"`；`rounded_total` 固定 6 位小数。零价与小额四舍五入为零要可区分，UI 同时显示 exact 和 rounded，禁止仅据 rounded 是否为零判缺价。每项 `formula` 固定为 `request_count * (input_tokens_per_request * input_per_million + output_tokens_per_request * output_per_million) / 1000000`。

`exclusions` 固定包含 `cached_input/tools/long_context/images_audio_video/tax/fx/supplier_adjustments`；notice 用中文说明只按所选人工价格估算标准文本费用、未在线核验，不是实际消费/账单/金额硬预算。逐项币种来自版本；不返回跨行 grand total，尤其不合并币种。

全部行先验证后计算，一行失败整单不返回金额。本模块所有新错误采用 `{detail:{code,message,item_index?}}`，code/message 固定且不回显 raw input/context：未知 ID 为 `404 ai_price_version_not_found`，不覆盖规划时点为 `409 ai_price_version_not_effective`，其余输入为 `422 ai_price_invalid_request`。局部适配框架/Pydantic 验证失败，不直接返回 `errors()`、原始 input/context 或异常文本；被误填的 URL 凭据、session、幂等 key、请求 hash 不得进入错误、日志或客户端。只改变新增 pricing 路由，不修改无关全局错误合同。错误明确指出哪一项不可算，不以零额代替错误。

## 分工与顺序

所有执行者都不是独自在代码库工作：不得回退其他代理修改；共享文件先协调 ownership。本文件由 plan agent 独占；产品和测试任务交给以下两位 worker；Root 独占正式运行、验收脚本/回执及报告应用。

### Task 1：后端 DTO、不可变价格版本和附加迁移

Owner：backend worker。

- Create: `apps/api/tire_api/ai_pricing_models.py`、`apps/api/tire_api/ai_pricing.py`、`apps/api/tests/test_ai_pricing.py`、`apps/api/tests/test_ai_pricing_migration.py`。
- Modify: `apps/api/tire_api/db.py`、`apps/api/tire_api/migrations.py`、`apps/api/tire_api/main.py`、`apps/api/tests/version_registry.py`；必要的历史迁移独立断言文件和 `scripts/run_api_worker_regression.py` 仅作新测试注册/具名 manifest 最小调整。

1. 在 `ai_pricing.py` 定义 closed DTO、原始金额/日期/model/URL验证器及显式有界常量；创建 Embeddings 版本要求输出费率为零，规划要求输出 tokens 为零。实现本模块 login dependency 和局部错误整形，不给 `auth.py` 或全局异常处理增加无关修改；鉴权顺序承诺限定为有效 JSON 的语义验证。
2. 新模型 `AIPriceVersion` / 表 `ai_price_versions` 私存上述数据、服务器 actor user/session、idempotency_key/request_hash；费率用字符串列，禁止浮点列。按 `(recorded_at,id)` 和 actor/key 建必要索引/唯一约束。
3. 沿现有 append-only 模型实现 ORM 更新/删除防护，以及 SQLite UPDATE/DELETE/冲突 INSERT 防护（覆盖 INSERT OR REPLACE；不依赖连接 recursive_triggers）；PostgreSQL 添加对应原生防护 DDL。不得把旧版本“修正”为新值。
4. `migrations.py` 追加 `028_ai_price_versions`，`db.py.initialize()` 注册新模型，`main.create_app()` 注册 `register_ai_pricing_routes(app)`。新增迁移必须附加/幂等，并遵循 `include_vehicle_binary=False` 的历史隔离；需要构造 027 起点时增加显式 `include_ai_pricing=False`，默认 True，不改变旧参数语义。
5. `version_registry.py` 独立追加 028；更新真正消费“当前全集”的迁移断言，包括 `test_vehicle_binary_migration.py` 的 CURRENT_TAIL_TABLES/尾部版本契约，保留描述 026/027 历史节点的切片。不要从产品生成器导入期望 DDL。
6. 实现分页读、管理员幂等追加和纯规划；公开 view 手工 allowlist 字段，绝不直接 ORM dump，不输出 session/key/hash。只有创建写 price 表，规划不写业务表。
7. 编写 Task 4 约定的 Python 用例，并将两个新模块加入既有 canonical runner 具名清单；不运行验证，不创建另一套 launcher/guard。

### Task 2：共享合同与客户端

Owner：frontend worker；依赖 Task 1 合同，不等待后端完工即可并行。

- Create: `packages/domain-types/src/ai-price-planning.ts`、`packages/api-client/src/ai-price-planning.ts`、`packages/api-client/tests/ai-price-planning.mts`、`packages/api-client/tests/tsconfig.ai-price-planning.json`。
- Modify: `packages/domain-types/src/index.ts`、`packages/api-client/src/index.ts`。

1. 导出 `AIPriceProvider`、`AIPriceVersionCreate`、`AIPriceVersion`、`AIPriceVersionPage`、`AIPricePlanningItem`、`AIPricePlanningRequest`、`AIPricePlanningItemResult`、`AIPricePlanningResult`；金额一律 string，actor_session_id/key/hash 不存在于公开类型。
2. 沿现模块惯例在 `packages/api-client/src/ai-price-planning.ts` 实现注入现有 request/transport 的 API factory，`index.ts` 只作薄接线，提供 `tireApi.aiPriceVersions(signal?, offset=0, limit=10)`、`aiPriceVersionCreate(payload, key, signal?)`、`aiPricePlanning(payload, signal?)`，路径/JSON/Header 与冻结合同一致。
3. SDK 注入 transport 用例覆盖路径、分页、Header、AbortSignal、原始十进制/日期保真和 ApiError 透传；使用与 `test-event-golden.mts` 相同的隔离测试方式，不连接 API。

### Task 3：Web 费用规划闭环

Owner：frontend worker。

- Create: `apps/web/components/ai-price-planning.tsx`。
- Modify: `apps/web/components/workbench.tsx`、`apps/web/app/globals.css`。
- Read first: `apps/web/AGENTS.md` 及实际安装的 `node_modules/next/dist/docs/01-app/01-getting-started/03-layouts-and-pages.md`，再编写相关 Next/React 接线。

1. 在现有 `view === "sources"` 的 `SourceInsight` 相邻位置接入独立 `AiPricePlanning`；组件内部直接复用 `useWorkbenchAuth()` 的账户状态、`ownerEpoch/ownerSignal/isCurrentOwner`，并按 ownerEpoch 在内部挂载 key，不新增 workbench auth props、不复制或绕过现有认证。保留现有导航/运行洞察/Token 计量。所有登录用户可看、可规划，管理员额外看到追加价格表单。
2. 展示价格分页列表、精确 ID/人工厂商/协议/model/币种/费率、有效期、来源说明及安全链接；提供上一页和更早版本按钮，不把列表第一页误称全部价格。来源链接 `target="_blank" rel="noopener noreferrer"`，标签明确“人工提供，未在线核验”。
3. 首版规划 UI 只提交一项：显式选择版本、UTC 规划时间、请求次数和每次 input/output tokens。日期显示 UTC，不暗中用浏览器本地时区代替输入。版本未覆盖时点、找不到、无价列表、零价和 rounded 为零小额都有明确状态。
4. 展示完整费率来源/版本/日期、逐项公式、exact 与 6 位舍入结果及排除项；币种作为标签显示，不用 JS Number/Intl 把金额转换成浮点。所有“费用规划”结果旁保留非账单声明。
5. 管理员表单创建成功后显示新版本并刷新首页，但用户规划选择由显式操作决定；同次提交生成并保留 UUID 以重试丢响应，成功后再创建生成新 UUID，编辑请求内容需新 UUID，账户切换废弃 pending key。
6. 列表、创建、规划请求分别管理 pending/error；直接消费现有 ownerSignal/isCurrentOwner，并使用按参数的局部取消避免切参数或卸载后的迟到响应污染，不另造账户 generation。ownerEpoch 的内部挂载 key 负责切账户后立即清价格/结果/待提交草稿、幂等 key 与错误，防止旧 actor 元信息回流。
7. 可见 label、键盘可操作控件、`role="status"/"alert"`；320/390px 不发生页面横向溢出，长 ID/来源/精确金额可换行，内容不可只靠颜色传意。不得把 API 支持 50 项写成已交付批量 UI。

### Task 4：Root 正式验证与独立复核

Owner：Root 执行，独立 reviewer 只读复核；worker 不运行正式验证、不写结果报告。

1. Root 已建立 `.artifacts/r121-ai-price-planning-20261022/before/manifest.json`，覆盖 db/migrations/main、domain/client index、workbench/insight-panel/CSS、runner 共 9 文件；后续受影响既有测试另补原字节备份。正式执行前完成实际产品/测试范围 pin 和受限入口检查。不得打开正常库或任何保留证据 SQLite；只使用新 UUID 私槽、新建合成数据、无 Provider/外网。不启动常规默认应用入口进行 smoke。
2. Python 定向用例至少包括：有效 JSON 的鉴权先于 body 语义验证；各 DTO 边界/金额字符串/日期区间/零价；精度在 ambient context 人为低精度时仍准确；半入舍入及小额 exact 非零；历史/未来覆盖；未知版本/一行错误整单失败；50/51 行边界；Embeddings 输出费率及输出 tokens 的零值限制；同 key 重放/内容冲突/并发；分页旧版本可达；响应和错误无 session/key/hash；在畸形 URL/未知字段/验证 context 中误填凭据仍只返回固定安全错误；规划前后账本和 price 表计数不变。
3. 迁移用例在私库验证 027→028 仅新增价格表/索引/原生 guards/版本；失败事务回滚、重复初始化、启动幂等、旧行/旧业务表不变；ORM 和原生 UPDATE/DELETE/REPLACE 拒绝。历史节点断言保持独立；PostgreSQL DDL 静审不冒称真实 PG 通过。
4. 运行既有入口，不直接普通 pytest、不跑整个 175 模块 suite；新增两个模块先定向，再按迁移影响选择 `test_test_event_golden_migration.py`、`test_vehicle_binary_migration.py` 等真实必要回归：

   ```powershell
   & 'C:/Program Files/PowerShell/7/pwsh.exe' -NoProfile -Command "& './apps/api/.venv/Scripts/python.exe' -X utf8 -B './scripts/run_api_worker_regression.py' --phase run --output-root '<Root建立的fresh私槽>' --targets apps/api/tests/test_ai_pricing.py apps/api/tests/test_ai_pricing_migration.py"
   ```

   占位私槽必须由 Root 替换为实际路径；先按既有流程 selfcheck/collect。新测试登记不能放宽网络/正常库/子进程护栏；runner 回执不等于逐 SQLite 句柄 close 证明。
5. SDK 定向 payload 为 `tsc -p packages/api-client/tests/tsconfig.ai-price-planning.json` 与 `node --experimental-transform-types --import ./packages/api-client/tests/device-ai/json-esm-hook.mjs ./packages/api-client/tests/ai-price-planning.mts`；由 Root 复用已审隔离运行方式执行。再做受控 Web typecheck，生产构建复用既有 `build-web-v3-r120.mjs` 的全新 batch，不新建通用执行框架。
6. Root 复用 `scripts/test_sku_bridge_web_fixture.py` 的受限私 DB / NoNetwork / create_app 与 R119 owned host 流程，只新增 `scripts/ai_price_planning_web_ui_qa.mjs`，不修改旧历史 fixture/helper。在同一新批覆盖：管理员创建两个费率版本→普通用户读旧/新与规划→同 key 重试与409→日期不覆盖→零价/极小额→权限拒绝→320/390px、键盘和长字符串。UI 可用合成记录，但要走真实产品 HTTP/React；查看实际截图并记录 console/page errors、请求、进程自然终态、资源及端口关闭，不拼接失败批次。
7. 独立 reviewer 审查金额/时间/权限/泄露/迁移/异步竞态，Root修复后只重跑受影响检查。Root 更新本轮 evidence/HANDOFF：分别列已修改、已实际验证、未验证，完整 V1 继续 active。

## 验收标准与证据边界

- 管理员可以追加、重试创建价格，旧版本不可覆盖；普通用户只读/规划；匿名不可访问；历史价格通过分页可达。
- 相同公开版本快照与工作量可独立算出相同 exact/rounded 金额。历史和未来 planned_for 只按所选有效期判断；选价失败不会伪造零金额；无混币种总计。
- API、SDK 和实际 Web 入口合同一致，用户能看见来源、版本、UTC 日期、公式、排除项及非账单声明；不泄露认证 session。
- 当前计划产出阶段仅做源码/规格只读核对和本文写入，**没有运行测试、构建、API、Provider、浏览器或迁移**。后续测试和合成 UI 通过也不证明真实厂商价格、账单、真实 Provider、正常库升级、PostgreSQL、宿主/设备或完整 V1 已验收。

## 替代方案与回滚

不采用：内置示例价格（过时且误导）、只保留一条可编辑价格（失去复算依据）、按协议/model 自动选厂商（没有账户身份）、用旧 usage/预留量生成“实际成本”（事实不成立）、新增持久规划历史或通用操作框架（当前闭环不需要）。

Root 修改前仅备份本轮受影响文件，回滚按实际 owned diff/原字节恢复并保留其他 dirty，不执行 stash/reset/clean。未运行私库迁移时回退本轮源即可；已运行的验收私库按既有关闭/保全流程处置。若以后在授权业务库应用 028，停用新增路由/UI并保留追加表与版本历史，不删除/降级业务库、不改写价格记录；需要修正时追加新版本。恢复旧应用前必须确认其初始化不会误处理新 schema，此项不能由本轮私库测试替代。
