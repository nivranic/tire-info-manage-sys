# R124：Web 运行期 theme-color 同步

2026-10-22。已实现 Web 文档 meta 随现有主题配色同步，并完成组件浏览器与生产构建验证。**真实浏览器栏取色、生产 Next hydration、已安装 PWA、离线启动及真实设备仍未验收；完整 V1 保持 active。**

## 实际修改

依据[冻结计划](../../plans/2026-10-22-web-theme-color.md)及[R123 Phase C 留账](round-123-theme-preferences.md)，新增 Web 专用 `web-theme-boundary.tsx`，在 Server Layout 的 body 内包裹 children。保留原 metadata 与静态 viewport，不引入动态服务端数据。复用现 ThemeProvider，嵌套 Workbench boundary 共享 context，无第二套存储或媒体监听。

ready 后按实际 palette 写入既有唯一、无 media 属性的 `theme-color` meta：light `#f6f5f1`、dark `#191d1c`、high-contrast `#000000`。System 使用解析后配色。缺失、重复或带 media 条件时不创建、不改写标签。外部改写 content 或替换节点后失权，直到组件重挂；卸载仅恢复仍持有节点的原 content，包括原先没有 content 属性的情况。主题更新不重挂 children。

[产品输入清单](../../../.artifacts/r124-web-theme-color-20261022/product-source-pins.json)绑定两文件：layout 717 B / SHA `838a9a3f81440ffd6545d71027d4ffc9d099d21f082f92b54624186d1e647586`；boundary 2523 B / SHA `4f218cc1a3d1f69482758f6e5cd6f506bc84e9c43b6a3515e17bc41bf9e8bfc9`。共享 provider、manifest、Android/Tauri 原生代码、后端、数据库与依赖未为本轮修改。回滚只撤两处本轮差异，layout 的[原字节基线](../../../.artifacts/r124-web-theme-color-20261022/before/manifest.json)保留，不清用户 Storage 或回退其他 dirty。

## 已执行验证

- [独立静审](../../../.artifacts/r124-web-theme-color-20261022/independent-review.json) ACCEPT，未发现确认 P1/P2；绑定产品、QA、计划和两份构建 freeze。审阅者未运行验证。
- [组件 prepare](../../../.artifacts/web-theme-color-qa-r124-a17c/prepare.json) 实际类型检查与 Webpack bundle 均无错误，绑定214项输入；不是仅语法检查。
- [组件浏览器结果](../../../.artifacts/web-theme-color-qa-r124-a17c/result.json) 同批六组通过，SHA `d2ad0ff032ea7def9d1dce759037807a9e102229eb0565bbaa1889289de73132`。覆盖旧 dark、四态具体颜色与唯一 meta、重载、System 真实 media emulation、StrictMode/共享 context/单监听、输入节点/值/焦点、两种原 content 恢复、外部改写/替换及三种安全 no-op。
- [Root 看图记录](../../../.artifacts/r124-web-theme-color-20261022/root-browser-observation.json)确认两张最终截图已查看。Chromium PID72008 自然 exit0/signal null/server close，随后精确 PID 缺席；page/console/unexpected/cleanup 均空，原输入及 prepared runtime 条目稳定，新增侧日志单列保存。没有产品 HTTP 服务、API 或数据库；这是合成文档中的真实 React 组件验收。
- [最终生产构建 b124](../../../.artifacts/r118-material-workbench-20261021/web-build-b124e62f9b8d0413/verification.json) passed，129241 B / SHA `2f5d44f67ac12c20779f6a60c0ec435d315776e5f957040ff5fff2adb480beb9`。Root 观察 orchestrator 自然 exit0，icons / Next Webpack / PWA 三阶段 supervisor 与 child 均0、资源自然关闭、无强制 Job close；源/依赖稳定、生成文件恢复通过，denied/optional 均空。沿用原受审框架 worker 清理分类，不声称每个内部 worker 都 exit0。
- [Root 终核](../../../.artifacts/r124-web-theme-color-20261022/terminal-verification.json) passed，3900 B / SHA `aa50dbdce5b82f2001f110b931a3b854bd6f536161f08f2babc523775bd2f7f3`。生产 HTML 恰有一个初始 `<meta name="theme-color" content="#f6f5f1"/>`；根路由完全静态预渲染；client-reference manifest 包含新 boundary；两产品与 live 匹配，共享 provider / manifest / 当时 HANDOFF 与 before 一致。

## 失败批与边界

[首次构建 a124](../../../.artifacts/r118-material-workbench-20261021/web-build-a124d51e8a7c9302/verification.json)保留 failed：Next 在新输出目录创建 `server/app/_not-found` 时 EPERM，生成恢复通过、源稳定、进程自然关闭。后续经自动审批在放开执行限制的环境使用同一工装、同一产品及全新 b124 输出通过；不改写旧批，也不声称单独证明唯一根因。构建仍保留无缓存与受控 home / outputFileTracingRoot 警告。

动态 meta 的证据来自组件文档，生产证据目前是构建及静态 HTML/client-reference。二者不等于生产页面实际 hydration 或真实浏览器栏取色。下一步先补生产 Web 页面中的四态/System/重载与状态保全，再分别验已安装 PWA 的启动/离线/恢复及平台 chrome。manifest 默认色和 Apple statusBarStyle 仍按既有静态合同，不能称四态动态启动画面。

真实 Android 系统栏、桌面标题栏、专业材料/SKU/真人 Golden、Provider/Responses、正常库升级、PG 和完整无障碍继续留账。本轮未启动默认 API、未打开正常/保留 SQLite、未 commit/push，保留其他 dirty。EPREL 无 Key，继续独立工作，不再询问。
