# Current Production PWA Offline Verification Plan

**Goal:** 用当前已验生产构建的真实 Service Worker，证明在线安装、断网重载、离线新文档和恢复网络时的应用外壳、主题偏好及缓存边界。

**Architecture:** 复用 R124 b124 Next 产物、R125 合成私槽 API 与 R118 生产监听器。执行窗口内临时安装匹配构建的五个 public 生成文件，使实际 `/sw.js` 网络响应与构建一致；结束后恢复原字节。浏览器允许真实 SW，不使用路由 fulfill、注入脚本或伪造 navigator 模拟离线能力。

**Tech Stack:** 当前 Next 16.3.6、Playwright 1.63.0 / Chromium headless1243、既有 Python owned-process host；无产品、依赖、数据库迁移或原生代码改动。

---

## 冻结依据与边界

R125 已证明实际生产 hydration，但显式阻止SW。2026-10-01 production-h 只证明旧版本同上下文暖离线重载，不能替代当前构建。本轮使用 b124 report SHA `2f5d44f67ac12c20779f6a60c0ec435d315776e5f957040ff5fff2adb480beb9`，运行前后核源、依赖和输出。

已确认 `/`、manifest 与静态 chunks 来自固定 Next dist，而 `/sw.js`、favicon及三张icons来自 live public。build freeze 的 sources 排除这五个生成文件，generated_inputs 指向私有before备份；原监听器另核 dist 和 web-public 快照。因此选择五文件的具名、可恢复执行窗口，避免新通用代理/服务器和产品配置改动。只用page route.fulfill无法证明真实SW脚本网络交付，不采用。

Root 已保存 `.artifacts/r126-current-pwa-offline-20261022/before/public-manifest.json`（SHA `e77a0f8b2e3358db30052ecc90f6e7c84ca75b33dd7411c8e01ccd6a59dd9dbd`）与五份原字节、目录存在性；五文件和public/icons目录当前均存在。HANDOFF原163552 B / SHA `5660d89164bb668d15855740c4f75dfaa09cc13b080e4c50db8e77e5d97cd875`已备份。

本计划按持续实施授权冻结。继续当前工作区，不额外问执行方式、不建worktree、不commit/push/reset/stash/clean。所有执行者不是独自在代码库，不回退他人dirty；本轮独占五个具名public文件的写窗口。默认API、正常/保留SQLite、真实Provider均不打开；EPREL无Key不再询问。

## 任务与 ownership

1. Host worker 仅新增 `.artifacts/r126-current-pwa-offline-20261022/run-ui-host.py`。复用原fixture/listener/停止流程，R126新批槽与QA路径；创建服务前核Root before与完整快照。首个变更前将before/安装清单落盘，逐文件以本轮精确temp完整写入/核hash，再原子replace。解析绝对路径始终在public，拒reparse。finally先结束浏览器和服务，再仅恢复仍等于本轮安装值或原before的具名条目。外部改写保留并整批failed；部分安装失败仍恢复已安装项。tmp只清本轮精确regular文件，目录仅本轮新建且仍空才rmdir，绝不递归删。恢复、temp清理、原字节/存在性复核是最终passed门，保留全部备份与回执。
2. QA worker 仅新增 `scripts/current_pwa_offline_web_ui_qa.mjs`。复用已审build/source/runtime与自然关闭支架，将suite收敛为真实SW场景，不重跑188业务断言。新context启用SW；只continue两个固定loopback来源、拒绝其他来源，不fulfill页面/资源/SW。
3. 独立 reviewer 只读核计划、host变更与真实SW断言，尤其恢复路径、失权、请求/缓存/离线错误界限。Root独占正式运行、浏览器、看图、证据与HANDOFF；workers不得自行运行验证。

## 必须观察的结果

- 真实HTTP `/sw.js` 响应字节/SHA匹配固定web-public快照；用JSON.parse解析生成的CONFIG，核version/assets；不eval脚本来得到预期值。
- production页面真实注册、activated、controller且scriptURL正确。CacheStorage唯一目标`tire-shell-version`，key精确等于构建白名单，响应成功，无API/auth/evidence/query/RSC或个人数据缓存。
- 保存高对比偏好，context真正断网后重载，根响应fromServiceWorker、离线marker恰一个、navigator.onLine=false、实际UI可用且meta黑。离线切System并实际媒体变化，更新实际palette/meta。
- 离线保存light、关闭页面并在同一上下文新建页面断网导航，fromServiceWorker和保存偏好/实际meta均正确。记录离线static响应来源，不能用“页面没崩溃”代替生产脚本执行。
- 浏览器实际fetch几个API/query/RSC/普通root负例离线失败，缓存白名单不变。预期网络错误按明确离线阶段、精确同源路径和错误类型单列；真实pageerror、其他console/unexpected均失败，不全局吞错。
- 恢复网络后导航走network-first且离线marker消失、偏好保持。自然关闭context/BrowserServer后精确fixture shutdown、Web停止；所有输入和runtime原条目稳定，具名侧日志单列，public五文件原字节恢复。

## 交付与验收范围

Root保存本批输入、HTTP/SW/cache/导航观察、截图及自然关闭/恢复回执，独立终核后写 `docs/assurance/evidence/round-126-current-pwa-offline.md` 并前置HANDOFF，原163552 B尾文完整保留。失败批原样保留，只有同批全部通过才成立。

本轮证明当前构建在headless真实SW控制下的暖重载、同上下文新文档及网络恢复；不等于浏览器整进程冷重启、PWA安装/standalone、OS重启、iOS/Android设备、真实chrome颜色或完整离线资料库各业务域。专业材料/SKU/真人Golden、Responses/Provider、正常库升级、PG、完整无障碍与完整V1继续留账。
