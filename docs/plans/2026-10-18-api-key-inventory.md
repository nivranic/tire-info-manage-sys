# 有效密钥全集与历史分页 Implementation Plan

**Goal:** 用户无论签发／撤销过多少把Key，都能看见并撤销本人全部有效Key，且能逐页读取完整签发历史。

**Architecture:** 保留R79最近100条端点和写合同兼容；新增独立完整有效列表与有签名的历史keyset分页，共用现有不可变Key／撤销记录，不增加schema或迁移。新界面只通过新读取端点展示管理库存。游标利用首批窗口中一把不可变Key的cursor_secret作签名anchor，不把它当Bearer，不依赖该Key仍有效。

**Tech Stack:** FastAPI／SQLAlchemy、TypeScript SDK、共享React面板；GUID私库与真实loopback HTTP验证。

上一轮为实质进展，原完整V1 Goal保持active。已授权当前agent继续；复用现有ultra agent，保留全部dirty和R79封存，不提交、推送、迁移正常库或部署。

## 设计与合同

仅增加100上限不能消除隐藏Key；直接改变旧wire会破坏兼容。本轮选择有效列表＋独立分页历史：

1. `GET /v1/api-keys/active?mode=history` 返回精确字段 `{schema:"active-api-keys@1",items:ApiKeyRecord[],read_at:string}`。固定账户、未过期且无撤销，完整返回最多16条，按`(created_at,id)`倒序。用17条探测异常超限并409 `api_key_active_limit_invalid`，不能静默截断。`read_at`用于有效期分类，客户端时钟不作为权限依据。
2. `GET /v1/api-key-history?mode=history&limit=20&cursor=opaque` 返回 `{schema:"api-key-history@1",items:ApiKeyRecord[],limit,next_cursor:string|null,window_started_at:string,read_at:string}`，包含全部签发记录及本页读取时的撤销metadata，包括当前有效Key，与上方独立列表允许重叠。limit 1–100，默认20，末页next_cursor=null；不返回total。
3. 两端点只认已登录未过期Cookie，并要求单个 `X-Tire-Expected-Account` 安全ID（1–64 ASCII字母数字下划线连字符）与当前固定user ID相等。提示不是凭据，不能绕过Cookie。缺失／重复／格式非法422 `api_key_expected_account_invalid`，账户不符409 `api_key_owner_changed`，匿名／过期／删户401沿用 `api_key_login_required`。先验证账户和header，再验证query；Bearer仍由R79统一拒绝，不创建额外session机制。
4. mode必须恰为history；禁止未知／重复query。错误422 `api_key_inventory_query_invalid`。cursor最多2048字符，严格base64url、HMAC、闭合JSON、schema／route／limit／owner／anchor／窗口／after绑定；过期409 `api_key_history_cursor_expired`，其它损坏或错绑422 `api_key_history_cursor_invalid`。
5. 第一页冻结上界`(created_at,id)`、窗口起时和900秒绝对TTL；后续严格小于after且不超过上界。不得续期。anchor固定为该账户初页上界Key，验证其seal／owner并用独立namespace签名；owner仅用HMAC commitment，不把原user ID、cursor_secret或Bearer导出。anchor撤销或到期不使历史中断；删户／会话失效仍被账户守卫拒绝。同账户其它会话可继续，换账户不可继续。
6. 这是有上界的keyset窗口，不是跨请求数据库快照；新签发通常在窗口外，同时间或历史回填可能影响成员。撤销metadata以每页实际读取为准，不宣称冻结历史状态。`window_started_at`不得混称本页状态时间。
7. 每次查询通过单次SQL outer join读取Key和撤销记录，渲染已读取的记录并验证各自seal，不在结果投影时重新逐项读取可变化撤销状态；避免活跃选择后被撤销的并发读取产生自相矛盾DTO。不得写库、触发派送、读取token或新增签名配置／迁移。没有Key时直接空页，无anchor／cursor。

## SDK与界面

DTO沿用 `ApiKeyRecord`；新增 `ActiveApiKeys`、`ApiKeyHistory`、`ApiKeyHistoryRequest`。SDK方法：`activeApiKeys(expectedAccountId,signal?)`；`apiKeyHistory(expectedAccountId,{limit?,cursor?,signal?}={})`，显式发送账户header，只走Cookie共享transport；严格验证闭合字段／唯一ID／倒序／页尺寸／末页与时间格式。正确处理微秒时间和Unicode，不引入客户端密钥持久化或自动写重试。

现有创建、一次token、未知操作GET恢复、撤销及owner epoch不变。有效列表独立显示全部项，保留逐Key显式撤销。历史只读、一页一屏，手动“查看更早记录”与“从最新记录重新读取”，无本地100条总上限，不维护无限拼接数组。历史失败不隐藏已成功取得的有效列表。分页cursor与窗口同时绑定；刷新／写成功回到最新窗口，旧请求abort且迟到响应不覆盖新页。账户变化立即清空两列表、cursor与secret。过期提示显式重新读取，不自动重复写入。

## 所有权与执行步骤

- Backend ultra：新增 `apps/api/tire_api/api_key_inventory.py`、`apps/api/tests/test_api_key_inventory.py`，只在 `external_api.py`注册新路由；不改models／migration／R79写合同。私根验证先复现101条历史遮住旧有效Key，再证明新列表包含并可经现有revoke撤销；遍历全部页无重复／遗漏。单query投影、时限／anchor／跨账户／header／坏cursor反例。
- Root：修改domain-types的external-api.ts、SDK external-api.ts及新SDK测试；修改api-keys.tsx／CSS；新增R80专用浏览器fixture／QA及真实wire工装，更新使用与交接／风险。读取Next本地use-client.md和11-css.md后沿用现有客户端模式。
- Reviewer ultra：独立 `apps/api/tests/test_api_key_inventory_review.py`及新轮审查回执；从合法HTTP签发和现有账本构造隐藏Key、分页／TTL／账户并发反例，不照抄预期，不改生产。

所有agent均不独自在代码库，不回滚他人编辑；复用现有agent，不新建child。

### 验证

1. 新轮基线先索引当前1090文件和R79清单SHA；复制并改R79私库runner为R80，保证main导入前GUID绑定数据库／objects／bundles／TEMP和审计护栏。
2. 后端目标与独立反例；再按影响跑R79鉴权／Key回归。无新迁移，不重复正常库保全或上线动作。分阶段文件库存变化如实记录，生产输入稳定。
3. 新SDK合同正负例、现有43项；workspace类型、三端前端build；真实私有HTTP及桌面1440／390／320 React验证：旧有效Key跨100条历史仍可见并撤销、分页到达旧行、历史失败不隐藏active、cursor过期重读、刷新／换账户／迟到响应、未知写恢复和单次显示。
4. 关闭私有API／Next、撤销测试Key、清除浏览器emulation；Next生成声明仅在完整受控前缀替换后全字节等于基线时恢复。新轮静态封存；旧R79证据不回写。

PG、公网、真实Responses／专业Golden、原生／WCAG／完整V1继续各自验收。回退仅撤销本轮路由注册／新模块及界面读取接入，保留R79基础能力和全部旧dirty，不做git reset/clean/stash。

## 原生接入补充（2026-10-19）

新账户提示头会被现有Native传输白名单拒绝，必须同时接入TS桥、桌面Rust和Android Java策略。仅精确的GET `/v1/api-keys/active`、`/v1/api-key-history`（query剥离后canonical路径）允许 `x-tire-expected-account`，值限制为1–64 ASCII字母数字下划线连字符；其它路径仍拒绝该头，凭据／任意头规则不变。现有backend_core负责上述策略和对应目标测试，Root负责DTO／SDK／UI。该头不授予身份，服务端Cookie与账户归属守卫仍为权限依据。原生策略测试不替代设备运行验收。

## 文档勘误

当前安装包 `node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md` 和 `01-app/01-getting-started/11-css.md` 实际存在；默认rg忽略dist，上一轮又请求了`.mdx`路径，不能据此断言目录不存在。本轮已用限定目录`rg --files --no-ignore`定位并读取，后续报告纠正该工具判断，不改旧封存原文。
