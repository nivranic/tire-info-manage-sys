# ADR-2026-056: Web 三端采用 hash 路由实现可分享深链

- Date: 2026-10-03
- Status: approved & implemented（波次3；用户裁决走 hash 路由，commit 5e0f2e3）
- Affected assets: apps/web/components/route-hash.ts（新）、workbench.tsx、
  apps/web/tests/route-hash.test.ts（新）、apps/mobile/src/back-navigation.ts（返回链）
- Related: risk-register R-013；WorkbenchPlatform 平台抽象（workbench-platform.tsx）

## Context

产品原为单路由 `/` 内的 view state 切换（apps/web/components/workbench.tsx 的
`useState<View>`）：比较视图、查询预填等状态不可 URL 直达，也无法分享/收藏。
workbench.tsx 被 web（Next）/desktop（Tauri）/mobile（Capacitor）三端作为共享
单文件编译，组件树零 `next/*` 依赖；Tauri（tauri.localhost）与 Capacitor
（https://localhost）均无路径 fallback。若采用 Next 原生路由（App Router 多页），
`next/link`、`next/navigation` 会随共享文件进入桌面/移动构建并使其失败；且
Tauri/Capacitor 侧仍需自建路径服务——等于维护两套路由。

## Decision（7 项）

1. **hash 路由**：视图地址为 `#/query|vehicles|garage|compare|watch|sources`；
   比较深链 `#/compare?ids=…`（≤4 个变体 id）；查询预填 `#/query?size=…`。
   编解码收敛在新模块 apps/web/components/route-hash.ts 的纯函数
   `parseRouteHash`/`serializeRouteHash`（非法 hash 返回 null，回退 query）。
2. **放弃 Next 原生路由**：理由即 Context 的勘察结论——三端共享单文件编译、
   Tauri/Capacitor 无路径 fallback、引入 next/link 系构件必然破坏两壳构建。
3. **navigate() 收敛 12 处视图切换**：统一写 `window.location.hash`，由
   `hashchange` 监听同步 view state（单一事实源；hash 未变时直接 setView）。
4. **初次挂载 useEffect 应用深链**：初始服务端渲染恒为 query，挂载后读取
   `window.location.hash` 再切换——hydration 安全，先例为主题 localStorage 读取
   （同样在 effect 中进行）。`hashchange` 同时驱动浏览器前进/后退。
5. **compare 深链占位→回填**：深链载入的 id 先以占位变体进入选择，compare
   视图既有按 id 拉取成功后回填真实变体（撤销等未返回的保持占位展示）；
   视图内增删选择用 `history.replaceState` 静默同步 URL，不产生历史条目。
6. **移动端返回键链语义不变**：`backRequested` → `consumeMobileBack`（先对
   打开的 dialog 派发 cancel）→ `workbenchBack`（workbench 经
   `platform.registerBackHandler` 注册）：先关证据检查器 → 非 query 视图回
   query → 返回 false 交还原生（退出）。hash 历史与该链并存，前进/后退由
   hashchange 承接。
7. **诚实边界**：证据检查器、弹窗、查询草稿保持瞬态，不进入 URL（深链只承诺
   视图与 compare ids/查询 size 两个稳定锚点）。`sw.js` 与 manifest 零改动
   ——fragment 不会进入 Service Worker 或服务端请求。

## Verification

- route-hash.test.ts：bare 视图解析、ids trim 与 4 项上限、非法视图/多段路径
  回退、size 仅对 query 生效。该文件同时是 web 首个
  `node --test --experimental-strip-types` 测试设施（apps/web/package.json
  `test` 脚本）。
- 波次3浏览器验收范围：深链直达、前进/后退、刷新存活、compare 占位回填、
  移动返回链；三端构建门禁继续把守共享文件不引入 next/* 构件。

## Known disadvantages / Residual risk

- 放弃 Next 路由生态：Link 预取、RSC、SEO 深链均不可用——本产品为本地工作台
  形态，无此需求方。
- 桌面 brand 链接 `href="/"` 整页回根（非 hash 切换）；移动返回链与 hash 历史
  两套机制并存存在回归面。均登记 risk-register R-013。

## Rollback trigger / Revisit condition

备选演进路径：按 `WorkbenchPlatform.registerBackHandler` 的既有模式预留平台
路由接口（hash 路由可降格为该接口的 Web 实现）；任何导航结构改动或新增平台壳
时复评（联动 R-013）。
