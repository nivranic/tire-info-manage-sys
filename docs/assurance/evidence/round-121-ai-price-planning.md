# R121：人工 AI 价格版本与费用规划

2026-10-22，本轮完成管理员追加人工价格版本、登录用户明确选版并按工作量规划费用的 API / SDK / Web 闭环。新增后端 76/76、必要回归 122/122、SDK 4/4 与类型检查通过，生产 Web 构建通过；最终全新 4df2 批次的真实产品 HTTP / React 浏览器 36 项检查通过。全部价格与业务数据为合成数据，不代表真实供应商价格、账单或完整 V1 验收。

## 需求依据与实际交付

[原规格](../../requirements/2026-09-26-tire-intelligence-original.md) 738–758 行要求后台维护动态价格，并区分工作量示例与 Provider 实际 usage；846–847 行列出管理端 AI Provider / 成本中心。[冻结计划](../../plans/2026-10-22-ai-price-planning.md)中的版本、币种、来源、有效期及幂等逐字段合同是本轮实现设计，不能说成原文逐字段要求。

- 管理员通过 `POST /v1/ai/price-versions` 追加价格，必填 UUID `Idempotency-Key`。相同管理员与相同提交内容重试返回同一版本，不同内容冲突 409；原生 guards 阻止 UPDATE / DELETE / 冲突 REPLACE。修正价格需追加版本。
- 登录用户通过 `GET /v1/ai/price-versions` 分页查看历史，明确选择精确版本 ID。人工计费方标签与协议分开，保留精确 model、币种、原始十进制费率、人工来源及 UTC 有效期；不自动推断厂商或选价。
- `POST /v1/ai/price-planning` 按明确时点和有界整数工作量计算。后端支持 1–50 项，本轮 Web 只交付单项；版本缺失或时点不覆盖时整单不给金额。历史、未来均可，结束时点不包含在有效期内。
- 金额按 Decimal 80 位局部精度计算，公开结果保留完整价格快照、公式、精确输入/输出/合计及固定六位 `ROUND_HALF_UP` 合计，前端金额保持字符串。极小非零额舍入成零时明确说明不代表免费，明确零价与缺价分开。
- Embeddings 输出费率和规划输出 tokens 均必须为零。无内置种子价格、在线抓价、汇率换算或跨币种总额；缓存、工具、长上下文、多媒体、税费、汇率及供应商调整明确列为未计入项。
- Web 接在“来源与证据”的 SourceInsight 后，复用现有账户 ownerEpoch / ownerSignal / isCurrentOwner。列表、追加、规划各自取消和管理状态；追加不自动替换选价，分页保留选版；失败原内容重试保留 UUID，编辑内容开始新提交。
- 登录/管理员依赖先于有效 JSON 的语义验证，不声称先于框架 JSON 解析。新增 pricing 错误固定 code/message，不返回 Pydantic input/context 或异常原文；公开 DTO、结果与 DOM 不提供认证 session、幂等 key 或请求 hash。

这是“费用规划”，不生成已消费金额、供应商账单、金额硬预算或规划历史；没有给既有 usage / 预留量补算金额，也未改变现有 Responses / Chat / Anthropic / Embeddings 的执行与 Token 护栏。

## 修改范围与隔离

[产品绑定](../../../.artifacts/r121-ai-price-planning-20261022/product-source-pins.json)覆盖 12 个产品文件，1822 B / SHA-256 `f51686ae7eafa8df408aa15afd76def30df814fc53d1bfe8d253d6c20c8f3782`。实际产品与测试共 20 个文件：

| 范围 | 文件及作用 |
|---|---|
| 后端新增 | `ai_pricing_models.py` 的追加表/guards；`ai_pricing.py` 的闭合输入合同、路由、幂等、分页和纯计算 |
| 后端薄接线 | `db.py` 注册模型、`migrations.py` 追加 `028_ai_price_versions`、`main.py` 注册路由及仅 pricing 的固定验证错误 |
| 共享层 | domain-types 的 `ai-price-planning.ts` / index 出口；api-client 同名 factory / index 薄接现有 transport |
| Web | 独立 `ai-price-planning.tsx`、workbench 最小接线与该 panel 的 CSS；R120 comparison 组件未改 |
| 测试 | 两个新 Python 模块、独立 version registry、两个必要历史迁移断言、canonical runner 的两个具名登记；SDK `.mts` 与独立 tsconfig |

[原字节备份](../../../.artifacts/r121-ai-price-planning-20261022/before/manifest.json)保存 9 个既有受影响文件，[历史测试备份](../../../.artifacts/r121-ai-price-planning-20261022/before/test-manifest.json)保存另 3 个测试文件；其中 insight-panel 最终未改。028 默认启用，受 `include_vehicle_binary` / `include_test_event_golden` / `include_ai_pricing` 的历史隔离保护；027 构造处显式关闭 pricing，不将历史节点变成最新节点。

后端正式测试仅通过现有 canonical runner、全新 UUID 私槽及合成数据执行；SDK / Web / UI 使用本轮已审入口。浏览器原样复用受限 `test_sku_bridge_web_fixture.py` 与已审 Web service helper，未启动默认正常 API，未打开正常或保留的 SQLite。Root 新增的 UI QA 和本轮 artifacts 中的固定宿主脚本只服务本轮验收。没有 commit / push / reset / stash / clean，保留既有 dirty；相对 Git HEAD 的总 diff 不是本轮范围。

## 正式验证

| 验证 | 实际结果与证据 | 能支持的结论 |
|---|---|---|
| 收集与护栏 | [collect-381b](../../../.artifacts/r121collect-381b/result.json)：76 项收集，未执行用例，selfcheck 通过 | 收集可用，不计入运行通过数 |
| 新 API / 迁移 | [api-627c](../../../.artifacts/r121api-627c/result.json)：76/76 passed，0 failed/skipped/incomplete，source stable、非 selfcheck denial 0、资源汇总关闭 | 合成私库的输入、权限、幂等/并发、分页、Decimal/时间、纯规划无写及 027→028/追加防护/回滚/幂等 |
| 必要回归 | [reg-95af](../../../.artifacts/r121reg-95af/result.json)：122/122 passed，source stable、denial 0、资源汇总关闭 | Golden / vehicle / external fact 历史迁移，以及既有未知完成保留预留、usage 对账和共享 Embeddings Token 预算未出现所测回归 |
| SDK | [Root 观察记录](../../../.artifacts/r121-ai-price-planning-20261022/sdk-root-observation.json)：tsc exit0，注入 transport 的 4/4 测试通过 | 路径、分页、Header、AbortSignal、字符串金额/日期及错误透传；不是 HTTP 集成 |
| Web 构建 | [生产构建](../../../.artifacts/r118-material-workbench-20261021/web-build-e1217a9b6d48c203/verification.json)：passed，125678 B / SHA `dddd1ada6c1864f0404aec0e3bce273f9c4b52314ea5582e36cfe881e20d7256` | icons / Next / PWA 三阶段 supervisor0；源/依赖稳定、生成文件原样恢复；不是 PWA 离线或设备验收 |
| 真实 UI | [4df2 浏览器](../../../.artifacts/r121browser-4df2/result.json)：36 项同批 passed；3088 B / SHA `4bdea36ed679b0b586349b77dfafc6f214dc4b604f51ee7ba2eef9563d57c257` | 合成价格上的真实生产路由、React 与 headless 浏览器工作流 |

后端两个运行批次共 198 个用例执行记录，不能称同批全仓通过。测试覆盖包括严格字符串费率/整数/UTC、Embeddings 双端零输出、零价/半入/微额、低 ambient Decimal precision 下精确运算、50/51 项边界、未知版本/失效时点整单失败、重放冲突和并发、公开字段白名单及误填秘密不回显、分页旧版可达、规划不写业务/价格账本。SQLite 原生 UPDATE / DELETE / REPLACE 与 ORM 防护、独立 027→028 DDL/旧行保全、回滚及重复初始化均在新私槽测试；PostgreSQL DDL 仅静态断言，未运行真实 PG。

构建仍有无构建缓存和受控 home / outputFileTracingRoot 的框架提示；通过结论保留这些限制，不改写成全环境无警告。

## 最终同批浏览器：4df2

[宿主终态](../../../.artifacts/r121uihost-4df2/receipt.json)为 passed/completed，3067 B / SHA `781addef9801d723a3faacfdeb31e104b9f5ffafa71b2a21f04ab5a899df3139`；本批实际完成：

1. 正式账户路由注册首位管理员及普通账户；匿名读 401，普通账户写 403，有效 JSON 未登录语义验证先被 401 拦下。
2. 管理员从真实页面追加第一版，QA 在服务端已保存后故意丢弃响应；原内容重试使用同 UUID，得到同 ID / recorded_at，列表仍只有一条。再次页面录价使用新 UUID，保留原规划选择；同 key 变更内容服务端返回 409。
3. 合成 12 个追加版本后，普通账户翻页访问旧版并明确选价，回首页仍保留所选旧版本。结果标准输入/输出费率 2/8、100 次 × 每次 1000/500 tokens，精确合计 `0.6 USD`，舍入 `0.600000`，公式与快照一致。
4. 有效结束时点 UI 清掉旧金额并提示不覆盖，服务端独立返回 409；微额 `0.00000000000001` 与舍入 `0.000000` 同时展示且说明不免费，零价单独说明并非缺价。Embeddings 输出 tokens 为只读零。
5. 最大输入边界所得 `199999999999999998` 仍按字符串展示；120 字符模型、长来源说明/URL 和金额在 390 / 320px 下换行，页面无整体横向溢出；实际 Tab 到请求次数字段。重载后价格持久、规划选择/结果重置。
6. 持有已完成真实 HTTP 计算但尚未给页面的响应，在注销、现有 auth revalidate 完成且 workspace 消失后才释放；旧规划结果没有回流。此证据限于 pending plan 注销，不代表跨账户 pending create 已验收。

Root 实际查看了 [标准结果](../../../.artifacts/r121browser-4df2/desktop-standard-result.png)、[非零微额](../../../.artifacts/r121browser-4df2/desktop-tiny-result.png)、[390px 长字段](../../../.artifacts/r121browser-4df2/mobile-390-result.png)和 [320px 长字段](../../../.artifacts/r121browser-4df2/mobile-320-result.png)四张截图。截图含既有固定导航/跳转链接；窄屏 headless 合成检查不表示真实手机、原生宿主或完整无障碍认证。

本批 `unexpected_origins/page_errors/console_errors/cleanup_failures` 全空；`intentional_transport_errors=1` 对应故意丢响应，不能描述成完全没有网络错误。API / Web supervisor / browser 脚本父进程自然 0/0/0，无 forced；Chromium 62972 自然 exit0 / signal null，并观察 BrowserServer close。Web 实际 Node 71488 自然 exit143，Job 2/2、active[]、无 forced job cleanup，详见 [Web service](../../../.artifacts/r118-material-workbench-20261021/web-service-e1217a9b6d484df2/service.json)。[fixture stopped](../../../.artifacts/r121fixture-4df2/stopped.json)在原 lifespan 退出后记录 shutdown_complete，外网/子进程/正常库尝试全 0，所列源首尾一致；不因此宣称逐 SQLite DBAPI 句柄关闭或私库已删除。

## 独审、失败批与终核

[独立静审记录](../../../.artifacts/r121-ai-price-planning-20261022/independent-review.json)核对本轮 before 差异与冻结合同，未发现可确认产品 P1/P2；审查指出 QA 原先使用不存在的 `Browser.process()` 兜底。首个 UI 执行前已换成公开 BrowserServer 的 process / close / kill，并要求自然 exit0、无信号和 server close；失败强制清理仍使整批失败。最终实际观察满足自然关闭门。

- [8b14 宿主](../../../.artifacts/r121uihost-8b14/receipt.json) / [浏览器](../../../.artifacts/r121browser-8b14/result.json)：10 项检查后第二次录价超时，整批 failed。首次 QA 粒度不足，不能独立从其回执精确断言失败字段；原 [v1 源](../../../.artifacts/r121-ai-price-planning-20261022/qa-v1-8b14.mjs)保留。
- [2c97 宿主](../../../.artifacts/r121uihost-2c97/receipt.json) / [浏览器](../../../.artifacts/r121browser-2c97/result.json)：补安全 stage / 行号与管理员截图后同样 10 项后 failed，明确停在 `second_ui_price_field_6`。Root 实际查看 [失败截图](../../../.artifacts/r121browser-2c97/failure-admin-panel.png)：第二版模型/费率已填入，source_note textarea 保有旧内容，未发生第二 POST。已有内容进入 label 文本，使 QA 的 `exact:true` 定位失效；仅将该 textarea 改前缀匹配，再全新重跑，产品未改。原 [v2 源](../../../.artifacts/r121-ai-price-planning-20261022/qa-v2-2c97.mjs)保留。

两个旧批均 failed，父进程分别 0/0/3、forced[]、端口关闭、产品/QA 稳定；先行通过项不拼成完整绿批。正式 UI 通过仅使用完整独立 4df2。最终 QA SHA `e22dba923dec2cb930a5806b373e2b1087961a7ca70341cff64152b24abaffc2`。

[Root 终核](../../../.artifacts/r121-ai-price-planning-20261022/terminal-verification.json)passed，3960 B / SHA `cdc15f4f28bd6f98d76926791a0b6c4929fcbe1d3d0b6f27e2bc30566182ccb1`：12 个产品 pins 匹配 live 与正式 API / build 输入，14 个[最终验证 pins](../../../.artifacts/r121-ai-price-planning-20261022/verification-source-pins-final.json)匹配 live，六个精确 owned PID 均缺席，两个端口独立 connect_ex 为 10061。早期验证清单及失败回执原字节保留，不回填旧批。[首次终核探测](../../../.artifacts/r121-ai-price-planning-20261022/terminal-attempt1.json)用 0.5s 超时得到 Windows 10035，未通过；保留原脚本后改 5s 等待，实际观察到两端口拒绝连接。终核只读文件和进程/端口，未打开任何 SQLite。

## 未验收与下一步

本轮不代表真实厂商价格核验、真实 Provider / Responses、usage 金额对账、BYOK / 充值 / 金额硬预算、正常库 028 升级、真实 PostgreSQL、PWA 离线或原生设备验收。真实专业 SKU / 真人 Golden、来源覆盖及完整 V1 仍各自未完成；EPREL 没有 Key，按用户指示继续不依赖该凭据的工作，不反复索要。

后续已确认的产品缺口包括查询结果 Shift 连续多选并批量 add-only 加入比较、System / Light / Dark / High Contrast 四态主题、hover 预览与右键/键盘菜单。选择下个闭环时应对照原规格与当前入口，保留比较四项容量、精确 ID、撤销门和既有跨端合同。Safety Gate 仍 `discovered_contract_pending`，没有因本轮进展升为 ready。完整 V1 goal 继续 active。

更新 HANDOFF 时保留此前 146698 B / SHA `3fdf4ac5984dfef65d516c9679310c6162d471a64b965dfe51c82c416e1231f7` 的原字节尾文；本轮只是前置最新状态，不重写旧轮次结论。
