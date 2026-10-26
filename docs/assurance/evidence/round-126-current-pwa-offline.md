# R126：当前生产构建真实 Service Worker 离线验证

2026-10-22。新批 `b126b95c2eb03746` 在 headless Chromium 中完成 **6 组场景、63 条检查记录**，实际交付当前生产构建的 SW，验证断网重载、同一上下文离线新文档、主题保留及网络恢复。Root 终核 27 门通过。**整浏览器冷重启、PWA 安装态、真实设备和完整 V1 仍未验收。**

## 范围与执行方式

依据[冻结计划](../../plans/2026-10-22-current-pwa-offline.md)，复用已通过的 R124 b124 生产构建、R122 合成私槽 fixture 和 R118 生产 listener；产品、依赖、默认 API 与正常/保留 SQLite 均未修改或打开。本轮新增专用 QA 和私有 host，没有新增产品服务器或通用代理。

监听器的根文档、manifest、chunks 来自固定 Next dist，五个 public 生成文件来自 live 目录。Root 已保存五件原字节及存在性；执行窗口仅 `sw.js` 与构建不同而实际替换，另外四件已匹配，未覆盖。安装前落盘清单，精确 temp 完整写入/hash/fsync 后原子替换，服务停止后恢复原件，外部改写保留并使整批失败。逐文件替换不是五文件事务或进程崩溃恢复保证。

浏览器使用新 nonpersistent context，允许真实 SW；没有 route.fulfill、脚本注入或 navigator 替换。仅两个固定 loopback 来源允许 continue。材料与账户身份是合成资料，未登录、未提交轮胎查询；fixture 最终来源、真实来源、Provider、模型及 embedding 调用均为 0。

[最终独审](../../../.artifacts/r126-current-pwa-offline-20261022/independent-review-final.json)为静态 ACCEPT，11897 B / SHA `e1708ac5c26da87e762457ce3e225eee5f353c6529fb8bdd9de5036e09980ad7`。绑定最终 QA `c0e41390fb11034cc130360225218eba95eef5310ef81351dca5289ba3cc8343`、host `429896d07a702a53f1859b6251e4f719c4019b26c492e37b85e000c1017444b7`、计划、before、build 与旧失败。[语法检查](../../../.artifacts/r126-current-pwa-offline-20261022/syntax-check-final.json)通过，语法与静态 ACCEPT 本身不计为运行验收。

## 同批实际结果

[浏览器结果](../../../.artifacts/r126browser-b126b95c2eb03746/result.json) passed，2338722 B / SHA `0c427783331813cda31e9f47702cb6415e207d8199e4b860aef4d87ea44c2145`。63 是流程内检查记录数，包含重复断言，不是 63 个独立测试或 V1 Gate。

- 实际 HTTP `/sw.js` 为 3871 B / SHA `1963f765e3f8b8017200bd309c1fba79d408fb02db8d641fc4adfdc080af8ae1`，与固定构建快照一致。JSON.parse 得到的 CONFIG 与独立从构建推导的 version `d822d928ddf06ca5bb76cab8`、29 个 assets 完全一致。
- 唯一注册 scope 为 `/`，active 与真实 document controller 均指向该 SW 且为 activated。五次 CacheStorage 观察均仅有该版本 cache，29 个 URL、成功状态、每件字节与 SHA 全部匹配静态构建。API/auth/evidence、query、RSC 和 router-state 均未进入缓存。
- 真正设置 context offline 后暖重载，根响应 fromServiceWorker=true、离线 marker 恰一个；关闭页面后在同一上下文新建页面，断网导航同样成立。两次离线响应均为 16281 B，实际生产脚本从 SW 返回并运行。
- 九次主题观察全部匹配：保存高对比后断网重载保持黑色 meta；离线 System 随真实媒体模拟在深/浅间更新；保存 light 后新文档和恢复网络均保持 light。没有用伪造 navigator 模拟离线。
- 六种实际 browser fetch 负例——API、证据、query-string、RSC、router-state、普通 root fetch——离线均返回浏览器 TypeError，缓存仍精确不变。这些是 fetch 负例，不是 query-string 文档导航验收。
- 网络恢复后的页面根响应仍可 fromServiceWorker=true，因为 SW 处理 navigation。另有 SW-owned、fromServiceWorker=false 的真实 HTTP200 网络根响应，文档恢复为原 16234 B，离线 marker 与提示消失，偏好保留，证明 network-first 恢复。
- 预期断网错误单列 **38 条事件**，包括 requestfailed 与 console 的同一失败重复观察，全部为限定阶段/路径的 `ERR_INTERNET_DISCONNECTED`。pageerror、其他 console、非预期来源/请求失败及 cleanup 均空；不能称没有网络错误。

[Root 看图记录](../../../.artifacts/r126-current-pwa-offline-20261022/root-screenshot-view-final.json)确认三张最终 1365×900 截图均实际查看：高对比离线、新文档浅色离线、恢复网络浅色。离线页面明确显示 API/来源不可用及应用外壳范围，没有虚构在线结果；恢复后显示 API 已连接并去掉离线提示。本轮没有移动端截图，也不把主题视觉检查等同完整 WCAG。

## 关闭、恢复与 Root 终核

[宿主回执](../../../.artifacts/r126uihost-b126b95c2eb03746/receipt.json) passed，26825 B / SHA `bed3b77a97beb1a05cd5332c5198d525d14755b012cac5fe2e4d1e19481477cb`。API/Web/browser supervisor 自然退出 0/0/0，无 forced。Chromium 自然 0/signal null/server close，context close 已返回。

[Web 服务](../../../.artifacts/r118-material-workbench-20261021/web-service-b126b95c2eb03746/service.json)自然 Node143、Job2/2、active 空、资源关闭，无强制 Job 清理；[fixture](../../../.artifacts/r126fixture-b126b95c2eb03746/stopped.json) shutdown_complete、源稳定，外网/子进程/正常库尝试均 0。汇总关闭不证明逐 DBAPI 句柄 close 或私库删除；Job/guard 不是 OS sandbox。

[Root 终核](../../../.artifacts/r126-current-pwa-offline-20261022/terminal-verification.json) passed，7764 B / SHA `986cead21f3d66be2dee8fb5102aa1bee3a08c4f9ebf8ea53f7ba5d10c576222`。实际运行 27 门：浏览器 9294 项输入中，五件安装态 public 与 build 快照单独核对，其余与 live 匹配；所有 host/review 绑定保持。五件 public 原始字节与目录存在性恢复，十个具名 temp 均无残留。六个精确回执 PID 均缺席，18986/18987 各自 5 秒探针返回 10061 拒绝。终核只读文件、进程与端口，没有打开 SQLite。

原 live `sw.js` 已恢复为 3018 B / SHA `362a5ade75824cb0d4fbb1696b8c45ff59b69879869f68022e4f7847080e33d8`；执行时匹配构建的临时安装值与结束后的原值分开核验。继续开发或部署时应走正常构建生成流程，不能把测试窗口的暂装视为永久发布。

## 首批失败与保留证据

[首批浏览器](../../../.artifacts/r126browser-a126a84b1daf2635/result.json)与[首批 host](../../../.artifacts/r126uihost-a126a84b1daf2635/receipt.json)保持 failed，没有回填或拼绿。首批 HTTP/config 检查通过后，QA 在唯一注册/controller 断言失败；快照只有 scope，没有 active/controller。

根因已由两次独立源码检查确认：当前 Playwright 1.63 的 poller 同步读取 predicate 返回值，async predicate 立即返回 truthy Promise 而停止轮询，即使 Promise 最后 resolve(false) 也不会继续等待。QA 仅一个 hunk 改为同步等待真实 controller URL/activated，随后 await 完整注册快照并加强 active/controller URL/state/scope 断言。产品未改；不能由首批现象推断产品 SW 注册失败。最终结论只取新批完整运行。

[首批恢复记录](../../../.artifacts/r126-current-pwa-offline-20261022/first-failed-run-safety.json)已证明五件原值和端口，但初次 OpenProcess 查询对两个 PID 返回 access-denied，未形成缺席证据；原记录保留。[后续精确 Get-Process 查询](../../../.artifacts/r126-current-pwa-offline-20261022/first-failed-run-pid-followup.json)才确认全部六个 PID 缺席。原 QA/host 已另存 first-run 字节。

## 仍未完成

本轮只证明当前固定构建在 headless 真 SW 下的暖重载、同一上下文离线新文档及网络恢复。浏览器整进程冷重启、PWA 安装/standalone、OS 重启、Android/iOS/桌面原生宿主、真实浏览器栏与完整离线业务域仍须分别验收。

规格卡片 hover/右键/完整键盘菜单、窄屏提示遮挡、专业 SKU/真人 Golden、真实 Responses/Provider、正常库升级、PG 和完整 WCAG 继续留账，完整 V1 仍 active。EPREL 无 Key，按用户决定继续独立工作，不再询问。未 commit/push/reset/stash/clean，保留其他 dirty。
