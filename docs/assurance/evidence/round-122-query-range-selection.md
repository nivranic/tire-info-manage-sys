# R122：查询结果 Shift 多选、批量只追加比较与失败回退锁释放

2026-10-22，Asia/Hong_Kong。本轮子范围完成：查询卡片原生多选、可见范围 Shift 选择、最多四项比较的原子只追加入口，以及验收时发现的既有回退写锁释放缺口。纯 helper 25/25、相关后端 40/40、生产 Web 构建和同批浏览器 74 项检查通过。完整跨平台 V1 仍 active。

## 需求与交付

[原规格](../../requirements/2026-09-26-tire-intelligence-original.md:877)明确要求 Shift 多选；连续范围、来源 occurrence 锚点、目标 checked 赋值、批量只追加与超额整批拒绝是[冻结计划](../../plans/2026-10-22-query-range-selection.md)中的工程设计。沿用精确 variant ID、四项比较上限、撤销版本不得新增的既有规则，不将同名、同尺寸或相同产品代码推定为同一身份。

- 查询待选与证据焦点、已比较状态独立。pending 只保存精确 ID，按当前可见且合格的行规范化；同 ID 跨来源共享勾选，范围锚点保留具体 occurrence 位置。
- Shift 覆盖锚点到终点的可见区间，包含两端；将范围内合格 ID 设为终点的 checked，保留区间外选择及原锚点。反向、取消范围、无有效锚点均有明确语义。
- 展开、排序、可见集合或资格变化清锚点并裁剪无效待选；新查询 generation、同条件重查及车型预填清结果时清待选，保留已有比较。未提交草稿编辑不清待选。
- 一次 functional `setCompared` 从当前可见行解析对象，只追加缺少的精确 ID，保留已有对象与顺序。超容量、未知、隐藏或不可选 ID 整批拒绝，不截断、不部分加入、不循环 toggle。成功后保留待选并解释“所选均已在比较中”。
- 任一可见 occurrence 为 revoked 时，同 ID 全体禁选。已有 revoked 比较仍占名额，允许用户显式移除。候选、隔离及设备离线资料没有借此进入普通比较。
- 使用原生 checkbox 的 pointer、Tab、Space、Shift+Space，不增加全局 Shift 监听或整卡点击。关注页不增加查询 checkbox；证据、关注和原单项比较保留独立入口。

## 修改范围与新增后端修复

[最终产品绑定](../../../.artifacts/r122-query-range-selection-20261022/product-source-pins-final.json)共四个产品文件；[最终验证输入](../../../.artifacts/r122-query-range-selection-20261022/verification-source-pins-final.json)16 项。前端原始三文件清单继续单独保存，未用后端追加倒改旧宿主输入。

| 文件 | 本轮作用 |
|---|---|
| `apps/web/components/query-selection-values.ts` | 纯 reconcile、可见资格、范围状态转换、比较追加计划 |
| `apps/web/components/workbench.tsx` | 查询 checkbox、工具条、当前可见行、查询及生命周期接线 |
| `apps/web/app/globals.css` | 局部选择样式、状态和窄屏换行 |
| `apps/api/tire_api/query_fallback_policies.py` | 无策略消费分支及时提交，释放本函数重新取得的写锁 |

定向测试为 `apps/web/tests/query-selection.mts`、目标 tsconfig，以及现有 `apps/api/tests/test_query_fallback_policies49.py` 中新增的六项锁回归。没有新增迁移、API/SDK 合同、依赖或原生桥。

8b72 的[安全阶段诊断](../../../.artifacts/r122fixture-8b72/diagnostics.jsonl)记录：一个来源的失败回退 `_execute/result` 已退出，另一来源进入 `_lock_ingestion` 后得到 SQLITE_BUSY(5)。`claim_policy_use` 的 `lock()` 本来先提交、再取得写锁；没有可用策略、原因不可自动回退或已有一次 consent 的 no-use 分支原先直接返回 None，直到同步 Session 依赖退出才释放锁。并发异步路由中的同步 busy wait 可以阻止及时退出。

最小修复只在该 no-use 分支增加 `db.commit()` 及注释。四类调用者已经先提交失败状态/audit，新增提交结束本函数自己重开的事务；未授权历史读取、策略消费或其他业务写入没有新增。成功路径仍保持消费凭证持久化 → 重新校验并持锁 → 历史读取 → `authorized_result` 最终校验与提交。独立 ultra 只读复核接受此修复，未发现确认的授权或事务回归；不以序列化前端请求规避问题。

[原字节备份](../../../.artifacts/r122-query-range-selection-20261022/before/manifest.json)及[后端修复前源码](../../../.artifacts/r122-query-range-selection-20261022/fallback-before/query_fallback_policies.py)均保留。修复前后端 SHA `a210c48ef9dc202d0c6220f45f301f7b6059eb06f482018594897559c9f57b89`，修复后 `abbb83cf373ae302ed041f3e6893bf41cb42f0f6826262b152156435dd000334`。本轮范围以备份和 pins 为准，不能以相对 Git HEAD 的全量 dirty diff 代替。

## 实际验证

| 检查 | 结果与证据 | 结论范围 |
|---|---|---|
| helper 类型与逻辑 | [Root 观察](../../../.artifacts/r122-query-range-selection-20261022/helper-root-observation.json)：tsc exit0、25/25，0 fail/skip/cancel | 正反范围、取消、重复 occurrence、资格/顺序变更、视觉序、容量原子拒绝、不可变输入；不代替原生事件 |
| 回退后端模块 | [f72a](../../../.artifacts/r122fallback-f72a/result.json)：40/40，0 fail/skip/incomplete，自然 exit0、源稳定、非 selfcheck 拒绝0、资源汇总关闭 | 含六项新增实际独立 DBAPI 连接测试；另外连接用 busy_timeout=0 检查 no-use 立即可写、成功授权持续持锁到最终结果 |
| 生产 Web | [构建](../../../.artifacts/r118-material-workbench-20261021/web-build-f122a463ed90c715/verification.json)：passed；126185 B / SHA `5f479587804ef8578049d692cdc98649301ccbf50364fb56e756e57d35cbc3c6` | icons/Next/PWA 三阶段 supervisor0，源/依赖稳定、生成文件恢复。后端补丁不改变该 Web 构建输入 |
| 真实本机 HTTP/React | [d842 浏览器](../../../.artifacts/r122browser-d842/result.json)与[宿主](../../../.artifacts/r122uihost-d842/receipt.json)：同批74项通过 | 真实业务路由、生产构建和原生浏览器事件，资料/来源为合成 |
| Root 终核 | [terminal-verification](../../../.artifacts/r122-query-range-selection-20261022/terminal-verification.json)：passed；5313 B / SHA `4b62fae03b67201006b05c907d4b0dc76b9bb0667834aedcdafafd960b8ce123` | 四产品、16验证输入与对应正式源绑定匹配，六个精确 PID 缺席，两端口独立5秒探针均10061拒绝；终核未打开 SQLite |

helper 执行使用现 Node strip-types；有 `MODULE_TYPELESS_PACKAGE_JSON` 重解析提示，未为此修改 package 配置。原始 TAP 经工具观察，没有伪造未保存的 TAP 日志。Web 构建父进程成功不表示每个框架 worker 自身都 exit0；相关 Job 终态见构建回执。

d842 用全新私库和两个项目合成来源，经正常注册、查询、比较、撤销、证据及关注入口执行。A 返回26行，B返回3行；QA 显式断言29行/28个唯一 ID，A0=B0 为同一服务端 ID。合成 MSPN 命名空间与完整身份字段仅用于身份分支验证，不声称真实厂商 SKU。

UI 实测覆盖正反 Shift、目标 false 取消、跨来源可见边界、20→26 展开、排序清锚点、草稿保留与重查重置、原生 Space/Shift+Space/Tab/label、已有项保留与批量追加、真实201撤销及重复 ID 禁选、撤销占位移除、证据焦点和关注不改待选、关注页无 checkbox、原比较表、390/320px 页面无横向溢出。超容量 UI 禁用并解释“本次不会部分加入”；真正的整批拒绝由 helper 用例验证，不能把 disabled 当作已经真实点击拒绝。

Root 实际查看五张最终截图：[桌面工具条](../../../.artifacts/r122browser-d842/desktop-bulk-complete.png)、[390工具条](../../../.artifacts/r122browser-d842/mobile-390-toolbar.png)、[390卡片](../../../.artifacts/r122browser-d842/mobile-390-selected-card.png)、[320工具条](../../../.artifacts/r122browser-d842/mobile-320-toolbar.png)、[320卡片](../../../.artifacts/r122browser-d842/mobile-320-selected-card.png)。选择控件、状态与换行可读；移动卡片底部存在原关注通知覆盖，不能据这些截图声称全部卡片内容无遮挡或完成完整视觉/无障碍验收。

最终 console/page/unexpected/cleanup 均空，intentional transport errors=0。四次来源查询 POST200、生命周期 POST201；fixture 来源调用4、外网/子进程/正常库尝试0，模型/embedding请求0。API/Web supervisor/browser 脚本自然0/0/0、forced[]；Chromium0/signal null/BrowserServer close，Web Node自然143、Job2/2、active[]、无强停。[fixture 关闭](../../../.artifacts/r122fixture-d842/stopped.json)和[Web service](../../../.artifacts/r118-material-workbench-20261021/web-service-f122a463ed90d842/service.json)源绑定稳定。fixture shutdown 不等于逐个 DBAPI 句柄均已确认关闭或私库已删除。

## 旧失败批与权限边界

以下失败整批保存，不用绿批回填：

| 批次 | 实际失败及后续处理 |
|---|---|
| [6a31](../../../.artifacts/r122browser-6a31/result.json) | 三个先行检查后 first_real_query 超时；关闭请求失败，宿主最终自然关闭、无强停。原日志只有新会话写锁异常，无法独自定位到查询。原 QA/fixture/pins 已归档 |
| [8b72](../../../.artifacts/r122browser-8b72/result.json) | 七个先行检查后仍超时；新增固定阶段诊断捕获 CaptureWriteError、失败回退持锁及另一路 SQLITE_BUSY，服务最终409/200。页面未及时收齐响应，不能与服务诊断计数混淆。携带原会话的关闭请求成功 |
| [c593](../../../.artifacts/r122browser-c593/result.json) | 锁修复后两路及时200，但都是来源失败状态。异常上下文为 ObjectStoreError → PermissionError(winerror5/errno13)，因此 live 状态断言失败；无强停 |
| [c4e8 API](../../../.artifacts/r122fallback-c4e8/result.json) | 同40项执行37pass/3fail，新六项锁测试均pass。最终 f72a 与其 source-before 完全相同且40/40通过；旧三项失败不称为基线既有失败，也没有逐项保存硬链接异常来证明唯一根因 |

[独立合成文件探针](../../../.artifacts/r122-query-range-selection-20261022/filesystem-probe-sandbox.json)在当前沙箱复现 `os.link` winerror5/errno13，两个临时文件及目录已移除。最终 UI/API 通过自动审批在放开该限制的环境运行同一套受限脚本与新私槽；没有改写 FileObjectStore 的原子硬链接逻辑、伪造材料保存或绕过真实业务路由。该环境变化及同源复跑支持权限影响的解释，但不追溯改写早批结果。

fixture 的 Python 审计钩子、Web Node guard 与自建 Windows Job 不是 OS sandbox，不能据升级权限后的通过宣称操作系统级隔离。最终 source/QA/helper 稳定及进程清理分别有回执；默认正常 API、正常库及保留 SQLite 没有为本轮验收启动或打开。

## 剩余 V1 与下一步

本轮没有验收真实来源材料/专业 SKU、真人 Golden、OpenAI Responses/真实 Provider、正常库升级、真实 PostgreSQL、PWA 离线、原生宿主及设备、完整 WCAG 或跨平台 V1。合成 parser 输出不是实际 Parser 执行凭证；后端验证仅限两个回退模块，SDK 与无关全仓测试未重跑。

下一候选的[四态主题计划](../../plans/2026-10-22-theme-preferences.md)只完成只读审计与草稿：当前 Light/Dark，System/High Contrast 及 portal/宿主传播仍有缺口。Root 需重新核现场输入后冻结再实施；真实原生窗口/系统栏/PWA chrome 另行验收。其余来源、专业证据/Golden、平台矩阵及 V1 Gate 继续保留。EPREL 无 Key，按用户指示继续不依赖该凭据的独立工作，不再重复索要。

完整 goal 继续 active。未 commit/push；交接按新前缀追加并完整保留原151438 B / SHA `7b66b1f31941ab03b70dcae0fa007ccdd64672476e8700ec86348bc15bbd3caa`尾文，不回退其他 dirty。
