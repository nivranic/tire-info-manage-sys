# R127：查询与关注规格卡片菜单、证据关闭及 SDK 204 完成边界

2026-10-23。查询与关注页共用的规格卡片菜单已完成生产 Web 验收：最终批 `a12759a6b1c237e8` **12 组场景、774 条检查记录**通过，Root 已实际查看同批 **23 张截图**，最终终核 **45 门**通过。774 包含流程内重复断言，不是 774 个独立测试或 V1 Gate。**完整 V1 仍 active。**

## 变更与范围

依据[冻结计划](../../plans/2026-10-22-variant-context-menu.md)，为查询和关注卡片增加右键、常驻“更多操作”按钮及键盘入口。菜单复用查看证据、比较、关注、核验、版本、AI、车库七项既有动作。query 以来源 rowKey 标识 owner，watch 以关注记录 ID 标识，避免同 SKU 的跨来源卡片串状态。比较上限仍为四项；已比较的撤销规格仍可移除；关注 pending 与取消确认继续走既有锁和业务回调。

菜单支持实际 DOM 焦点、方向键、Home/End、Enter/Space、Esc 和 Tab；保留输入框、链接、其他交互项及非折叠选区的浏览器上下文。业务动作前回到连接中的常驻触发者，再交给原有对话框或证据逻辑；关闭、结果替换及卸载清理本次菜单资源。菜单移动焦点改用实际鼠标 `onPointerMove`，避免菜单定位后覆盖静止指针时，`onPointerEnter` 抢走首项焦点。

[范围补充 1](../../../.artifacts/r127-variant-context-menu-20261022/scope-amendment-1.json)增加真实 Web“关闭证据”按钮，包含加载/错误态，复用 `clearEvidence()` 的取消、清理与回焦。原 Web 轮胎证据没有该入口，不能以伪造状态代替用户关闭动作。

[范围补充 2](../../../.artifacts/r127-variant-context-menu-20261022/scope-amendment-2.json)允许共享 SDK 在 HTTP 204 分支先 `await response.arrayBuffer()`，再保持原 `undefined` 返回。读取错误原样传播，无重试、请求重发、错误吞掉或 transport 重映射；其他状态处理不变。该补充为 3180 B / SHA `b5133af771c87cb0ed06f85c0e1f1f16c800f1f60637890e701e748621c8ce49`。

forced-colors 的启用项最终使用 ButtonText/ButtonFace，焦点由 Highlight 边框/outline 表示，保留 `forced-color-adjust:auto`；禁用项继续使用 GrayText/Canvas 并显示原因。此前 Highlight 填充即使 computed 色对通过，实际图仍有黑块，因此最终验收同时要求真实截图可读。

本轮未增加依赖、API、数据库迁移或原生宿主代码。未 commit/push/reset/stash/clean，保留其他 dirty。Root 独占实际测试、构建、服务、浏览器及终核；子代理的 ACCEPT 均为静审结论。

## 最终源码绑定

以下字节与 SHA 在最终构建、浏览器/定向验证及终核中按适用范围核对。冻结计划保留冻结时的“尚未实施”状态；本报告给出后续运行结果，不改写计划历史。

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| `docs/plans/2026-10-22-variant-context-menu.md` | 26941 | `e5116b5f34d4bac19080dee7be3389e0044c7ccc9e89245bee2869adcbba2144` |
| `apps/web/components/variant-context-menu.tsx` | 8773 | `7af4c2b87949a470aa26833a2235b8d395c934d24fe57ddc54884fffcfaa5279` |
| `apps/web/app/globals.css` | 144325 | `63a36b9f4e405d3ba942f39768eec29b022cf91cfea00e437391d2c4e950004a` |
| `apps/web/components/workbench.tsx` | 117579 | `b4c6dd605f6991766475644182d66ec3517d0d5a774765a460f9415ab671995b` |
| `packages/api-client/src/index.ts` | 82848 | `d6d40a331befe6c7ffb692529f15c07b28e0d4ab3bb77e2bd20e92f2c615d580` |
| `packages/api-client/tests/response-204.mts` | 3943 | `a36dc1ecbecabcb0938037967934ffdda8c0217dbd28c0c4cb91a6629ac9fa1c` |
| `packages/api-client/tests/tsconfig.response-204.json` | 179 | `b743046cc4f8a90f9c771b07d7f17837c260829d8d90586923a87bd1158a44e4` |
| `scripts/variant_context_menu_web_ui_qa.mjs` | 104439 | `51ad4fe455dfea9c4f31badfb178ac7bec5b5d286f8113986f671e92135244fa` |

## 构建与 SDK 定向验证

最终使用 [e127 构建回执](../../../.artifacts/r118-material-workbench-20261021/web-build-e1276b17c2d348f9/verification.json)，131251 B / SHA `a0fd05d9172b1bf9c3e54950c6555d4a488dd5060fb6f5feb12981a8d9dd0f04`，状态 passed。其 [freeze](../../../.artifacts/r118-material-workbench-20261021/web-build-e1276b17c2d348f9/freeze.json) 为 2136473 B / SHA `e163137885480b0de0dac9280d76fec266532333248207865efa1024fc141614`。图标、Next、PWA 三阶段 supervisor 均 exit 0，源码/依赖稳定、生成原件恢复通过。

新 SDK 改动使派生的 `host_build.web` 摘要变化。独审按 37 个输入文件独立重算新值 `2c155c29387c8b881054d62e67ef7b01cb243cf0f6d3a0b7994840a6bfd82a56`；仅将该 SDK 输入替换为归档旧源码字节，即精确回到旧值 `0ec1ff0944ae84cd29ca5eaf9b57269cf43d728724bcb630e8f2452a465795c8`。这解释了派生值变化；旧 b/c/d 构建只证明各自旧源码。

SDK 证据分两批记账，未把首批整批改为通过：

| 回执 | 实际结果 | bytes / SHA256 |
| --- | --- | --- |
| [a1277c28d3e459fa](../../../.artifacts/r127sdk204-a1277c28d3e459fa/result.json) | noEmit 类型检查 exit 0；随后 Node 在加载测试前因 Windows 绝对 `--import` 路径报 `ERR_UNSUPPORTED_ESM_URL_SCHEME`，整批仍 failed | 3803 / `b8c5526bbb0d96d5e70f0c5c86325b7f79cdce12b1dfe54988cc6ea60c871634` |
| [b1278d39e4f56a0b](../../../.artifacts/r127sdk204-b1278d39e4f56a0b/result.json) | 仅更正为相对 `--import` 后重跑 Node，4/4、exit 0；未重复跑 TSC | 3352 / `c8b131a45ae06387a3f084e1d2327cebb66f4f36510a624b24d85754ff5b3f16` |

两批九项输入一致、均稳定且匹配 live；B 精确引用 A 的成功类型检查阶段。四项覆盖等待读取完成才 settle、TypeError 原对象传播且无重发、AbortError 原对象传播且无重发、真实空 Response 返回 undefined。B 批 stderr 仅预期 experimental warning。这是注入 transport 的 SDK 单元证据，不能称真实 HTTP、原生 WebView 或设备验收。

## 最终应用浏览器结果

[浏览器结果](../../../.artifacts/r127browser-a12759a6b1c237e8/result.json) passed，3029935 B / SHA `74d0116cf1cccb2992542bd4f67872684b4e027847392e5de1e4ee9da66bcf96`。在固定 e127 生产 Next HTTP/React 页面与合成私槽 fixture 上完成以下 12 组：

| 场景 | 主要验收 |
| --- | --- |
| 双来源查询与 owner | 合成 26+3 行、28 个唯一 ID；同型号/同 ID 跨来源 owner 区分 |
| 右键、按钮与键盘入口 | 实际右键、更多按钮、Shift+F10；ContextMenu 原生尝试已交付，另有显式合成事件补充 |
| ARIA 与关闭 | menu/menuitemcheckbox、真实 roving focus、禁用项、方向/Home/End/Tab/Esc 与回焦 |
| 浏览器原生上下文 | 输入/链接/交互项与选区保护；部分 guard probe 为真实卡片内的显式合成子节点 |
| 既有交互回归 | Shift checkbox、Ctrl/Cmd+K 与菜单焦点交接 |
| 比较与撤销 | 四项容量、禁用原因、已有撤销项仍可移除 |
| 业务动作焦点 | 既有对话框与证据使用连接中的稳定原触发者 |
| 加载中关闭证据 | 点击真实关闭按钮，精确原 GET 中止，迟到响应不回填 |
| 证据错误与重试 | 一次限定的合成 503；真实重试入口与原证据回焦 |
| 关注及取消 | pending、确认/取消、真实 DELETE、卡片移除后的焦点补偿 |
| 几何与主题 | 1365/390/320px、真实下边缘、四态主题/forced-colors、内部滚动与末项可达 |
| 清理与替换 | 路由/新查询/resize/卸载及剩余菜单/焦点检查 |

**172 个菜单请求窗口均没有新增业务请求。** 这覆盖菜单开关、键盘、hover、主题与测量窗口；不能由此推断整页从不请求。来源调用为合成 4 次，真实来源/Provider/model/embedding 均 0，fixture 外网/子进程/正常库尝试均 0。

两个不同关注 DELETE 都有真实 HTTP 204、Playwright finished 与 CDP loadingFinished，无 DELETE abort。唯一 requestfailed 是关闭加载中证据触发的原 GET abort，按精确请求身份核验。一次合成证据 503 的 injected=observed=console_errors=1，结束 active=false；其错误单列，其他 page/console/unexpected-origin/gate/cleanup 门均为空。不能称没有网络错误，也不能把合成 503 称自然后端故障。

18 次主题观察、40 条几何记录与 3 次静止指针开菜单观察均保留。320×420 下菜单字号由实际 computed 13px 变 26px，菜单 scrollHeight 423/clientHeight 402，末项可滚到且临时样式恢复。这是菜单局部 CSS 字号应力，非浏览器真实缩放。真实边缘点击与合成角落坐标分开记录；window blur 为合成事件，未切换 OS 窗口。

[Root 看图记录](../../../.artifacts/r127-variant-context-menu-20261022/root-screenshot-view-final.json)为 5023 B / SHA `5bc8659103f1cd0d31baaf8b9ad92fea49b508a981bad72ff490ce0327c3377b`。Root 已逐张通过 view_image 查看同批 23 张图：1365/390/320 启用项文字与真实勾选不再出现此前黑块，禁用原因可读；dark/high-contrast/system/light、下边缘及双倍菜单字号末项均已看。截图检查不替代键盘、HTTP、取消和资源回执，也不代表整页 WCAG、toast、读屏或真实设备验收。

## DELETE 204 因果实验与应用修复

先进行独立本机 HTTP 实验，两个探针都是显式合成 server/client，不计入应用验收：

- [消费空 body 批](../../../.artifacts/r127deleteprobe-a12790abcdef1234/result.json)：84837 B / SHA `0e47f0e72ba8d1388157757c4c0215ae623e377d00e55542dcc960119cafb7d2`。A 透传、B 原 fulfill、C 显式空体均正常 finished，D 跳过。
- [不消费 body 批](../../../.artifacts/r127deleteprobe-b127a1bcdef02345/result.json)：87860 B / SHA `26d9d378f0bf463c93a095da629f71f41ad517480496653c9d168c8698ca660b`。A/B/C/D 每例 server 恰收到一次，fetch 均得到真实 204，但 PW/CDP 均 aborted/canceled=true，包含直接透传。

两批资源自然关闭、errors/cleanup 空、inputs/runtime 稳定；Root 另核两批精确 PID 缺席及 18988 拒绝。[比较独审](../../../.artifacts/r127-variant-context-menu-20261022/delete204-consumption-comparison-review.json)静态 ACCEPT。实验区分了 HTTP 响应成功与浏览器资源中止；合成 server 本身不证明业务删除成功，也不能据资源 abort 把旧 DELETE 称业务失败。SDK 修复后，**最终完整应用批两个 DELETE 均 finished**，才构成应用修复有效的运行证据。QA 没有放行 DELETE abort、归一化响应或放宽意外失败门。

## 资源关闭与最终终核

[宿主回执](../../../.artifacts/r127uihost-a12759a6b1c237e8/receipt.json) passed，5976 B / SHA `84e708e175980f9c3d9d2e4779b8b0a8422a3395bd05984432fa56cc5a2f9bea`。API/Web/browser supervisor 自然退出 0/0/0，forced=[]；Chromium PID12072 自然 0、signal null、server_close_observed=true。

[Web 服务](../../../.artifacts/r118-material-workbench-20261021/web-service-a12759a6b1c237e8/service.json) Node 自然143、Job2/2、active 空、无强制 Job 清理；[fixture](../../../.artifacts/r127fixture-a12759a6b1c237e8/stopped.json) shutdown_complete，所列源稳定。运行时及源码输入保持稳定。这些汇总不证明逐 DBAPI 句柄 close 或私库删除；Job/guard 不是 OS sandbox。

[Root 终核](../../../.artifacts/r127-variant-context-menu-20261022/terminal-verification.json) passed，19608 B / SHA `3e95b58318f1eab9fa7e363150569f183f189d696682f60a44e160966ca928f1`。45 门无失败，核对 9291 个浏览器输入 pin、host/build/review/SDK 跨批证据、源/依赖/可执行文件、生成原件与截图。6 个 UI 和 29 个 build 精确回执 PID 全部查询缺席、无查询错误；18986/18987 各 5 秒探针均返回 10061。构建 worker 保留 9 个 framework-parent-observed-sigint 与 8 个 own-exit-0 的区别，未把所有 worker 都称自然 exit 0。

受审终核工具 `root-terminal-check.py` 为 39187 B / SHA `97322fb55708551160c2b03e5f8d8903cd1556bf8a282cc3283d7b7bb545d83b`，Root 完整读差异、AST 检查及实际终核均 exit 0。本轮未打开正常/保留 SQLite，未启动默认 API；测试仅使用受审固定构建、合成私槽和 loopback 服务。结束后无待续 exec/service/browser session。

产品、最终 QA、e freeze、终核工具四份静态 ACCEPT 分别见 [product](../../../.artifacts/r127-variant-context-menu-20261022/sdk-204-product-review.json)、[QA](../../../.artifacts/r127-variant-context-menu-20261022/sdk-204-final-qa-review.json)、[freeze](../../../.artifacts/r127-variant-context-menu-20261022/sdk-204-freeze-review.json)、[terminal tool](../../../.artifacts/r127-variant-context-menu-20261022/sdk-204-terminal-tool-review.json)。它们不替代 Root 运行结果；最终文档复核另见[具名独审回执](../../../.artifacts/r127-variant-context-menu-20261022/independent-final-doc-review.json)。

## 历史失败、中断与更正

所有旧批保留原结果，不拼接为绿，不覆写为最终结果：

| 记录 | 事实与处理 |
| --- | --- |
| [首个构建失败](../../../.artifacts/r127-variant-context-menu-20261022/first-build-failure.json) | Next 编译/类型 exit 0，但 Job25 只观察24，因此整批 failed；未观察身份未知，不能猜成 conhost。后续 b/c/d 通过只对应其当时源码，最终 SDK 使用新 e 构建。 |
| [首次 UI 及更正](../../../.artifacts/r127-variant-context-menu-20261022/first-ui-failure-correction.json) | 归档第291行是 click，第294行才是 menu.waitFor；超时发生在 click 返回后的等待。首批无事件 trace，原因未确认；旧原因字段有误，以此更正为准。 |
| [第二批诊断](../../../.artifacts/r127-variant-context-menu-20261022/diagnostic-ui-failure.json) | 实际 trace 为 offscreen 目标自动滚动后右键开菜单，随后排队的外部 scroll 关闭。QA 改为先安排可见稳定目标，再执行真实点击；未因此改产品。 |
| [第三批失败](../../../.artifacts/r127-variant-context-menu-20261022/third-ui-failure.json) | 程序聚焦卡片 Shift+F10 后超时；默认 focus 滚动造成关闭仍为假设，无该次事件 trace。旧 QA 归档由逆差重构，非 runtime backup，元数据已注明。 |
| [第四批失败](../../../.artifacts/r127-variant-context-menu-20261022/fourth-ui-failure.json) | 615 条后390px首焦点失败；Root 看图确认文字黑块，另有两 DELETE abort。定位后的静止指针可能夺焦当时为推测；最终实际无移动观察验证修复。 |
| [e12737849fa015c6 中断](../../../.artifacts/r127-variant-context-menu-20261022/fifth-ui-interruption.json) | exec89007 句柄消失，原回执停在359条/running，无正式清理终态；Root另核6精确PID缺席与双端口10061后新建批。中断原因未证，不称产品通过/失败或自然关闭。 |
| [f1274895a0b126d7 失败](../../../.artifacts/r127-variant-context-menu-20261022/sixth-ui-failure.json) | 758条后 QA 使用 `#watch`，未按现路由 `#/watch` 导致1142行超时；computed色通过而真实图仍黑块。两DELETE实际204后CDP abort，自然supervisor0/0/3、Chromium0。Root只看该批4/24图；旧QA完整归档。 |
| SDK 首批入口失败 | 上文 A 保持 failed，只引用其 TSC 成功阶段；修正入口后 B 的4项单独记账。 |

末次只读统计曾误用 PowerShell `.PSObject.Properties.Count`，输出大量1并截断；随后 Python 读取终核标量得出上述计数。该命令输出错误未改变产品或原验收回执。

## 未完成与后续

下一候选为既有 toast 的窄屏遮挡、34px关闭按钮及计时生命周期；先形成文件级计划并冻结，再改现唯一 Provider。hover 摘要预览另留账。

本轮 SW blocked、匹配 public 由 page 路由提供，不能称菜单版已通过真实 SW 离线。R126 只证明旧 b124 构建；最终 e127 的新菜单/SDK 离线仍须独立验收。整浏览器冷重启、安装/standalone、OS重启、原生宿主/设备、真实系统栏、读屏及完整 WCAG 继续未验。共享 native transport 构造 `Response(null)` 且宿主先读取字节的兼容性仅静态核对，未验 WebView/Tauri/设备。

真实专业 SKU/真人 Golden、真实 Responses/Provider、正常库升级和 PG 仍留账。EPREL 无 Key，依用户答复继续独立工作，不再询问。上述局部验收不代表完整 V1 完成。
