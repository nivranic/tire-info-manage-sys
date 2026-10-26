# R123：四态主题偏好与宿主前端传播

2026-10-22，Asia/Hong_Kong。冻结计划 A/B 已完成产品实施及范围内工程验收：共享 UI、Web portal、桌面与手机前端使用同一四态偏好和解析配色。最终组件批 7b5a 五组、生产 Web 批 d123ae8d23f17945 同批 150 项、native 前端批 9d7c 六组通过，Root 已查看全部 36 张最终截图，终核通过。产品与工装静审已完成；最终文档独审见[独立复核回执](../../../.artifacts/r123-theme-preferences-20261022/independent-final-doc-review.json)。 Phase C 与完整 V1 仍未完成。

## 依据与实际修改

[原规格](../../requirements/2026-09-26-tire-intelligence-original.md)第943行要求高对比模式，第966–975行列出 Light / Dark / System / High Contrast。原件 53843 B，SHA-256 `f8a2a4434d83824afe36d3e46730ee183e4506acc0c91041b8a122b36e6fc46d`；[冻结计划](../../plans/2026-10-22-theme-preferences.md)28879 B，SHA-256 `0fcf3050e037ee766c86cb99913dbc1ce7a93e965c17e92eb81474f2b2e361b7`。默认 System、存储及以下值域分层为本轮工程选择，原件未规定这些细节。

| 层次 | 最终合同 |
|---|---|
| 本地 preference | `system / light / dark / high-contrast`；沿用 `tire-theme-v1`，兼容旧 light/dark。缺失、非法或读取失败回落 System；初始化和媒体变化不覆盖保存偏好，用户选择时 best-effort 写入 |
| 实际 palette | `light / dark / high-contrast`；System 订阅真实 `prefers-color-scheme: dark`。根 `data-theme` 写解析配色，`data-theme-preference` 单列用户偏好 |
| 原生 brightness | 仍为 `light / dark`；黑底高对比映射 dark。现单参数回调、Java 接受值域与拒绝安全行为保持原合同 |

单个 provider 负责存储、媒体订阅、根属性 ownership、卸载清理和回调。Workbench 独立挂载时创建 boundary，已有宿主 provider 时复用；宿主外层覆盖未连接页、顶栏、Workbench、离线及 AI。顶栏使用可见“主题”标签的四项原生 select，命令面板提供四个明确选项。Web 离线库、Web AI 与桌面 AI 的 body portal 订阅 live context，切换主题不靠重新挂载保持 DOM、输入、焦点和滚动。手机删除第二个 `data-mobile-theme` 控制路径，消费共享根 token。

桌面宿主栏由局部初测及 border-box ResizeObserver 记录实际高度；observer 不可用时使用 window resize fallback，卸载清理。sidebar、剩余高度与设置层据此布局，保留 document/window 滚动。最终 forced-colors 修订在 `.desktop-retry`、`button.mobile-primary` 明确使用 ButtonFace / ButtonText 及1px系统色边框，保留 `forced-color-adjust:auto`，也覆盖手机同类主按钮。

最终 [v3 输入清单](../../../.artifacts/r123-theme-preferences-20261022/product-source-pins-v3.json)绑定 **12 个产品文件与2个目标测试文件**，2082 B，SHA-256 `f15009e17eceeb3778fbb69233590c42ef9c0d1c061af28862e869b540842714`：

| 文件组 | 本轮范围 |
|---|---|
| `apps/web/components/theme-preference-values.ts`、`theme-preferences.tsx`、`theme-preference-control.tsx` | 4/3/2 合同、单 provider、四态控件 |
| `apps/web/components/workbench.tsx`、`apps/web/app/globals.css` | 主题入口、四个命令、共享 palette / 高对比 / forced-colors |
| `apps/web/components/offline-library.tsx`、`device-ai-panel.tsx` | 已打开的 Web portal live 主题 |
| `apps/desktop/src/main.tsx`、`styles.css`、`device-ai-panel.tsx` | 宿主外层 provider、实际 header 高度、连接页及桌面 AI |
| `apps/mobile/src/main.tsx`、`styles.css` | 统一根 token 与既有两态亮度桥 |
| `apps/web/tests/theme-preferences.mts`、`tsconfig.theme-preferences.json` | 七项独立合同测试及定向 Node 类型入口 |

无新增后端/API 合同、SQL 迁移、依赖、Java/Rust、capability 或 manifest 修改。[原字节基线](../../../.artifacts/r123-theme-preferences-20261022/before/manifest.json)、[布局修订前备份](../../../.artifacts/r123-theme-preferences-20261022/layout-v1-before/manifest.json)及[强制颜色修订前备份](../../../.artifacts/r123-theme-preferences-20261022/forced-colors-v1-before/manifest.json)保留；回滚只撤本轮已审差异或这些原字节，保留其他 dirty、历史证据和用户 Storage。旧版对 system/high-contrast 按其既有逻辑回落 light，不以清空 Storage 处理。

## 已执行验证及其证据边界

| 验证门 | 最终回执与结果 | 支持范围 |
|---|---|---|
| helper | [Root观察](../../../.artifacts/r123-theme-preferences-20261022/helper-root-observation.json) / [TAP](../../../.artifacts/r123-theme-preferences-20261022/helper-tests.tap)：typecheck exit0、tests exit0，7 pass / 0 fail | 原键兼容、默认/非法值、System 解析、显式配色、两态亮度与旧回调合同 |
| 组件 7b5a | [result](../../../.artifacts/theme-component-qa-r123-7b5a/result.json)：五组通过，8469 B / SHA `93b6dc1ecdfe9fb3138d4f6df38393689d71f0570298331b5c5e813d0bad4637` | 真实 React/provider/control、Web portal DOM/值/焦点/滚动、媒体变化、StrictMode/ownership、存储异常、320/390 高对比与强制颜色；资料为合成空载荷 |
| 生产 Web 构建 c56b | [verification](../../../.artifacts/r118-material-workbench-20261021/web-build-a123c56b92ed4071/verification.json)：passed，127136 B / SHA `38f7635709ee83c95d5378d3320b93eea7a185122fe36b0c73cc472f5be9f615` | icons / Next / PWA 三阶段 supervisor 与 final exit0；源/依赖稳定、生成文件精确恢复，资源自然关闭，无强制 Job close；不据此声称每个框架内部 worker 均 exit0 |
| 三端前端构建 d67c | [verification](../../../.artifacts/query-fallback49/frontend-final-build-r123-d67c/verification.json)：passed，8016 B / SHA `f0d96ed79b82cd8607bd2132be26de8864f29081406d792213d6967a99fa0d09` | Web/desktop/mobile 三项 tsc、desktop/mobile 两项 Vite 均 exit0，source_drift[]；仅前端产物 |
| 生产 Web UI d123ae8d23f17945 | [browser](../../../.artifacts/r123browser-d123ae8d23f17945/result.json) / [host](../../../.artifacts/r123uihost-d123ae8d23f17945/receipt.json)：同批150项通过；browser result 2243452 B / SHA `6e7368c2700b1644670dfbda42621e143adecbbcf83aa6b924ab1e431981a9dd` | 固定生产构建的真实 HTTP/React、四态入口/键盘命令/重载/System、320/390 配色/焦点/边框及既有工作台回归；材料与身份为合成私槽 |
| native 前端 9d7c | [result](../../../.artifacts/theme-native-qa-r123-9d7c/result.json)：六组通过，32000 B / SHA `82e430f3fd40817307857d812ad2922e6f8c2cf35130214d562b7bcefd25124e` | 固定 desktop/mobile dist 的无桥连接页、四态/媒体、320/390 高对比/强制颜色、布局 fallback、合成 IPC 桌面 AI 状态保持及合成 Capacitor 两态分流/拒绝安全 |
| Root 看图 | [最终看图回执](../../../.artifacts/r123-theme-preferences-20261022/root-screenshot-view-final.json)：6组件 + 11 Web + 19 native，共36图全部实际查看 | 本轮捕获状态的配色、焦点、布局及重试文字。窄屏 Web 的既有 watch 提示仍覆盖部分下方内容，未宣称全部卡片无遮挡 |
| Root 终核 | [terminal-verification.json](../../../.artifacts/r123-theme-preferences-20261022/terminal-verification.json)：passed、自然 exit0，40347 B / SHA `64c2f66f3e3b7db0c8889da3c05445808532804947197d5148a51bc59a6adce8` | 14条产品/测试 pins 与18项实际使用验证输入匹配 live；28个精确回执 PID 均缺席；18986/18987 各自5秒独立探针返回10061拒绝连接；103份归档标准文件哈希保留 |

最终组件、Web、native 批的 page/console/非预期请求或来源/cleanup 列表均空；Chromium 均 exit0、signal null、观察到 server close 且未强杀。原 prepared 文件/目录稳定与允许新增日志分别记账，不能称私 runtime 完全无新增。helper TAP 的 `MODULE_TYPELESS_PACKAGE_JSON` 提示保留，未单为消提示改包配置。

Web 同批 `price_write_requests=0`、Provider/model/embedding 调用0，来源调用4次。[fixture](../../../.artifacts/r123fixture-d123ae8d23f17945/stopped.json)记录 shutdown_complete、sources_stable，外网/子进程/正常库尝试均0；[host](../../../.artifacts/r123uihost-d123ae8d23f17945/receipt.json) API/Web/browser supervisor 自然0/0/0、forced[]；[Web服务](../../../.artifacts/r118-material-workbench-20261021/web-service-d123ae8d23f17945/service.json) Node 自然143、Job 2/2、active[]、无强制 Job 清理。fixture 关闭不等于逐 DBAPI 句柄关闭或私库已删除，Job/guard 也不是 OS sandbox。终核未打开正常或保留 SQLite。

native 六组通过仍属于浏览器中的前端验收：虚拟静态 origin、明确合成 Tauri IPC / Capacitor，不启动真实 Tauri/Android 或产品后端。四个320/390 forced-colors 重试按钮的实际文字/背景及四边框对比值均21，Root 已看19图。其 computed 对象 `width:"2px"` 被 select outline width 展开覆盖，**该字段不能证明 viewport 宽度**；320/390 来自场景配置和截图名，原回执不改写。

## 保留的失败批与视觉缺口

| 原批次 | 原结论及修订后边界 |
|---|---|
| [组件4e27](../../../.artifacts/theme-component-qa-r123-4e27/prepare-or-input-failure.json) | prepare_types 的 TS2591：QA 缺 Node 类型入口，未启动浏览器；补入口后使用新槽 |
| [组件5f38](../../../.artifacts/theme-component-qa-r123-5f38/result.json)、[6a49](../../../.artifacts/theme-component-qa-r123-6a49/result.json) | 各五组及 Chromium 自然0，但新增日志导致 cleanup 失败；两批仍 failed，不以功能中间项拼绿 |
| [Web a1237b5a90de4612](../../../.artifacts/r123uihost-a1237b5a90de4612/receipt.json) | browser exit1，QA 非 async 体内 await import 产生 SyntaxError；不是 c56b 生产构建失败 |
| [Web b1238c6b01ef5723](../../../.artifacts/r123browser-b1238c6b01ef5723/result.json) | 36项后 four_theme_commands_real_keyboard 失败、browser3；补 opening ready 前提并对齐 R119 后另开新批，不声称已证明唯一产品根因 |
| [Web c1239d7c12f06834](../../../.artifacts/r123browser-c1239d7c12f06834/result.json) | 139项后 QA 取错 top border；仅改为实际 bottom separator 并提前保存 computed，未为此改产品 CSS；最终 d123 独立150项通过 |
| [native8c6b](../../../.artifacts/theme-native-qa-r123-8c6b/result.json) / [视觉审阅](../../../.artifacts/r123-theme-preferences-20261022/native-8c6b-visual-review.json) | 自动六组 passed，但 Root 查看全部15图发现四张 forced-colors 页重试文字黑块，明确 superseded_visual_gap_not_final_native_acceptance；原回执保留，宿主系统色修复及更强断言后由9d7c重新验收 |

日志边界修订不删除日志：原 prepared 文件/目录严格不变，新增只允许常规 exact debug.log 或精确 timestamp log，合计≤4、每份1..1MiB，记录字节与 SHA。[12项 validator 回放](../../../.artifacts/r123-theme-preferences-20261022/runtime-validator-replay-v1/result.json)只证明该工装规则。失败批、8c6b视觉缺口、旧脚本和中间 pins 均不贡献最终通过数。

## 仍保留的验收边界

Phase C 按冻结计划独立处理真实 Android 系统栏、桌面原生标题栏与 Web/PWA chrome/安装态。高对比发送 dark brightness 不等于现 Java 深色背景已成为黑底高对比；合成桥 Promise 成功不证明系统效果。真实设备、前后台/快速切换、PWA离线/安装启动、iOS、完整屏幕阅读器及 WCAG 2.2 AA 尚未验收，局部对比度与 forced-colors emulation 不关闭这些门。

真实专业材料/SKU/真人 Golden、真实 Provider/Responses/来源、正常库升级、PG 及完整 V1 继续分别留账。EPREL 无 Key，继续独立工作，不再次追问。本轮未 commit/push，保留其他 dirty；A/B 完成不将完整 V1 标为 complete。
