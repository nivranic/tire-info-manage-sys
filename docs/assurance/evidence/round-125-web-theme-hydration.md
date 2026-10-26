# R125：生产 Web hydration 与四态主题色集成验证

2026-10-22。新批 `a125f73a0c9e1524` 在实际 Next 生产 HTTP 页面同批完成 **188 项检查、34 次动态 meta 观察**，证明 R124 boundary 在生产 hydration 后按四种偏好/三种实际配色同步 `theme-color`，并保留工作台既有状态。**真实浏览器栏取色、SW离线、安装态、真实设备及完整 V1 仍未验收。**

## 范围与改动

依据[冻结计划](../../plans/2026-10-22-web-theme-hydration.md)，复用[R124 b124生产构建](round-124-web-theme-color.md)，未修改产品或重新构建。新增 `scripts/web_theme_color_web_ui_qa.mjs`，从已审 R123 QA 增量派生；新增本轮 `run-ui-host.py` 适配私槽和 QA 路径。旧 R123 工装与回执未改写。

QA 在现有导航响应中提取服务端 head，随后在实际主题 helper 中等待根属性、控件、唯一无 media 的 meta 与具体颜色一致；每次成功及超时观察均有保存路径。复用原业务、请求、runtime目录/原文件、有限侧日志及自然关闭合同，未新增测试上下文或请求。Host 复用既有 R122 合成私槽 fixture、R118 Next listener，全部服务由 Root 正式运行和关闭。

[独审](../../../.artifacts/r125-web-theme-hydration-20261022/independent-review.json) ACCEPT，4408 B / SHA `47415951c67bede03fd2aa6535d237eabc830e754fbb3a904b69fc2147c549c9`；绑定 QA `d56a91bf0a2ecdc8da9bb7f8a22f79b3fd2514e482561c44fb50b73f9bb264f1`、host `e39715f8b293dcd358049b53bd845e7f3c95a5834bd28ebb44b01040cc81db72`、计划及 b124 回执。[Root语法检查](../../../.artifacts/r125-web-theme-hydration-20261022/tool-syntax-check.json) Node check 与 Python AST 均0；这些语法检查本身不计为产品验收。

## 实际结果

- [浏览器正式结果](../../../.artifacts/r125browser-a125f73a0c9e1524/result.json) passed，SHA `3d78ce42b88e43b9d976ca2dd6ee8eeb2e739c4255293e8215a703f82596f361`。188为同一流程的检查记录数，包含重复场景断言，不是188个独立测试或完整V1 Gate。
- 初次导航实际 HTTP200 响应为16234 B / SHA `19390ae958fa074a35d6d3eb485c674883eb4490d69572a3c0498272305d2f0e`，head 恰有一个无 media、content=`#f6f5f1` 的初始 meta。它与 hydration 后的动态 DOM 观察分开记录。
- 34次动态观察全部 matched，覆盖 `light / dark / high-contrast / system` 偏好，实际颜色分别为 `#f6f5f1 / #191d1c / #000000`，System 随真实 media emulation 解析。包含旧 light/dark、非法值回落、重载、四个键盘命令、命令关闭后的焦点恢复。
- 同批保留 R122 查询/Shift多选/比较/撤销/证据/关注回归；主题切换及 System 变化保持 pending、compared、证据 DOM/焦点。R121 未提交价格表单的节点/值/焦点保持，价格写请求0；fixture 来源调用4，最后快照断言模型/embedding0。材料、身份和返回数据是合成资料，不是真实厂商 SKU 或真人 Golden。
- page / console / unexpected origin / cleanup 均空，intentional transport errors0；输入与 prepared runtime 原条目稳定，允许新增的具名日志另存字节与SHA。Chromium76244自然 exit0/signal null/server close，无强杀。
- Root实际查看全部11张最终截图，包括320/390px与高对比/forced-colors。既有 watch 通知仍覆盖窄屏部分下方内容，不能称整张卡片全部无遮挡。局部颜色与浏览器强制颜色模拟不代表完整无障碍验收。

## 关闭、源绑定与证据

[宿主回执](../../../.artifacts/r125uihost-a125f73a0c9e1524/receipt.json) passed，SHA `b6c15df3517215df36a97294bf341429490375657b43be827c974bcc6205e87d`；API/Web/browser supervisor 自然0/0/0，forced空，源与所有声明输入稳定。

[Web服务回执](../../../.artifacts/r118-material-workbench-20261021/web-service-a125f73a0c9e1524/service.json)为 stopped，Node自然143、Job2/2、active空、资源关闭，无强制Job清理。[fixture回执](../../../.artifacts/r125fixture-a125f73a0c9e1524/stopped.json) shutdown_complete，源稳定，外网/子进程/正常库尝试均0。fixture汇总关闭不证明逐DBAPI句柄close或私库删除；Job/guard不是OS sandbox。

[Root终核](../../../.artifacts/r125-web-theme-hydration-20261022/terminal-verification.json) passed，6877 B / SHA `985ab0d84d80878a0fc7164fbea72393220042168e63a0fcd9ab552dc42683a9`：核对34次实际meta值、四偏好覆盖、初始HTTP响应、产品/QA/host live绑定与构建输入、11图哈希；6个精确回执PID均缺席，18986/18987各自5秒探针返回10061拒绝。未打开数据库。

本轮在既有原子hardlink限制所需的自动审批环境中执行同一受审私槽工装；未绕过对象存储或改变产品来通过。未启动默认正常API、未打开正常/保留SQLite、未commit/push，保留其他dirty。

## PWA后续与完整V1边界

本轮仍明确阻止SW，匹配的五个public文件由浏览器路由提供；这些不能算真实SW安装脚本的网络交付、离线或安装验收。

只读调查确认真实注册链为 Workbench → `pwa-status.tsx`，仅 production 注册 `/sw.js`，dev注销并清旧壳缓存。Worker按构建白名单缓存同源无query/非RSC的静态资源，根文档仅导航时network-first，离线返回固定缓存壳并注入 `tire-offline-shell`；API/auth/evidence不缓存。`test-pwa.mjs` 是VM模拟，不能替代真实SW。

[历史 production-h](../../../.artifacts/offline-pack/browser-production-h/report.json)为2026-10-01旧构建的真实SW暖离线重载通过记录（12877 B / SHA `a51a09e20e3328b09db2eb3df2539a5b04e1b4de56f48fc0b61d849dc35929fa`），不能证明当前b124或冷启动。下一步复用受审生产HTTP入口，让当前匹配SW通过真实网络交付；核注册/activated/controller、精确缓存白名单后断网，断言fromServiceWorker、离线marker、主题偏好/meta与生产UI，再检查离线新文档。浏览器整进程冷重启、安装/standalone、OS及设备另外留账。

真实浏览器栏、Android系统栏、桌面标题栏、专业材料/SKU/真人Golden、Responses/Provider、正常库升级、PG、完整WCAG及完整V1仍保持未完成。EPREL无Key，不再询问。
