# Web Theme Color Implementation Plan

**Goal:** 让 Web 文档的运行期 `theme-color` 随既有四态主题的实际配色更新，保留服务端初始输出与完整 V1 的平台验收边界。

**Architecture:** Next Server Layout 保留静态 viewport，body 内使用 Web 专用客户端 boundary，复用现 ThemeProvider。同步组件只消费 ready 与 actual palette，操作 Next 已生成的唯一 meta；原生宿主继续沿用现 provider 和两态亮度桥。

**Tech Stack:** 当前 Next 16.3.6、React、TypeScript、DOM effect；无新依赖、API、迁移或凭据。

---

## 冻结依据与选择

R123 A/B 已实施并有独立复核与正式报告。原规格第966–975行的四态主题继续作为范围依据，R123计划第7节明确 Web/PWA chrome 为独立后续。现场 layout 的 viewport 与 manifest 均固定浅色，ThemeProvider 只同步根配色。当前本地 Next 指南明确 viewport/generateViewport 只在 Server Component 支持，推荐静态 viewport；支持 layout 将 children 传入 client provider。PWA build 要求根页面完全预渲染。

采用 Web 专用 boundary：light `#f6f5f1`、dark `#191d1c`、high-contrast `#000000`；System 用解析后 palette。对比方案：在共享 provider 中加入所有平台 DOM 副作用会扩大宿主影响；按媒体导出两个服务端 meta 无法表达用户显式偏好和高对比，因此均不采用。

本计划已按用户持续实施授权冻结。brainstorming / writing-plans 用于方案与任务组织；继续当前工作区，不额外问执行方式、不建 worktree、不 commit/push。各执行者不是独自在代码库，不回退他人 dirty。Root 已在 `.artifacts/r124-web-theme-color-20261022/before/` 保存 layout、共享 provider、manifest、HANDOFF 原字节；新 boundary 原先不存在。

## 实施任务与 ownership

1. 产品 worker 独占新增 `apps/web/components/web-theme-boundary.tsx`、修改 `apps/web/app/layout.tsx`。保留 layout 的 Server Component 和原静态 viewport；将 boundary 放在 body 内，children 不以主题为 key，不重挂表单。内部使用现 ThemeProvider 与消费 hook；WorkbenchThemeBoundary 复用外层，只有一个媒体监听 owner。
2. 同步在 ready 后才发生。只接管 head 内唯一、无 media 条件的 theme-color meta；缺失、多标签或条件标签降级 no-op，不创建节点或 observer，不猜测媒体条件。记录原 content 是否存在；卸载仅恢复仍由本组件持有的节点及最后写值。外部 content 改写或替换节点不得在清理中被覆盖；后续主动主题更新若接管新值须保存可恢复基准。
3. QA worker 独占新增 `scripts/web_theme_color_browser_fixture.tsx`、`scripts/web_theme_color_qa.mjs`。复用已审组件 QA 的受限准备/运行/自然关闭模式，实际载入产品组件；明确合成 fixture、无产品服务/API/DB/Provider。覆盖四态、System媒体变化、重载、旧值、StrictMode、唯一 provider/meta、原 content 缺失恢复、缺失/多meta安全降级、外部改写/替换节点及输入DOM/值/焦点保持。
4. 独立 reviewer 只读审产品与 QA。Root 独占类型检查、组件浏览器和生产构建正式执行。只运行必要范围，不重跑无关 API/SDK/native 全套。所有输入绑定 live，失败批原样保留；浏览器自然关闭，Root查看最终截图。

## 验证与交付

- 定向 QA prepare 实际 TypeScript 检查与真实 React bundle；Root查看 prepare、独审后运行，记录四态 meta 唯一性、具体 content、生命周期与业务DOM保全。
- 复用 `.artifacts/r118-material-workbench-20261021/build-web-v3-r120.mjs` freeze/run，新16位批次；实际 Web生产构建及 PWA shell阶段通过，生成文件恢复、源稳定。
- 检查生产 prerendered HTML 的唯一初始浅色 meta、client boundary 引用及完全静态根路由。组件浏览器不能替代完整生产 hydration，若没有生产浏览器证据则明确留账。
- Root写 `docs/assurance/evidence/round-124-web-theme-color.md` 并前置 HANDOFF，完整保留原158669 B尾文（SHA `c07456843f55a046b1ceafaa5bc7b6e1e21e067a4d210761da13d6b3ef323420`）。

完成标准是运行期DOM同步的实际证据。headless meta正确不能证明真实浏览器栏取色；manifest初始色、Android安装PWA/离线冷启动/iOS状态栏、Tauri标题栏、Android原生系统栏、完整WCAG及完整V1继续留账。现 Web QA 阻止SW，不把它算离线安装验收。正常/保留SQLite、默认API和真实Provider本轮不打开。EPREL无Key不再询问。

## 回滚

只撤新增 boundary 与本轮 layout 差异，按 before 原字节恢复；保留共享主题实现、其他dirty、历史证据与Storage。验证工装及失败记录归档保留，不 reset/stash/clean。
