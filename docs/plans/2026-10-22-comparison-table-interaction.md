# Comparison Table Interaction Implementation Plan

> Execute in this chat using the existing implementation and independent review agents; Root owns formal verification and evidence application.

**Goal:** 补齐原规格 878–880 行明确要求的键盘上下移动表格、可调整列宽和固定表头，并实际用于当前规格比较与已保存比较。

**Architecture:** 在现有 `ComparisonTable` 内保留身份、来源权威、事实和人工核验的原值构造，新增纯 React 布局组件接收列与行的 ReactNode。布局组件只处理焦点、宽度与滚动；不读取 API、不更改比较数据、保存合同或证据回调。当前比较和保存比较的两个既有调用共享这条路径。

**Tech Stack:** 现有 React 19 / Next 16、TypeScript、CSS、原生 Pointer Events；无新增依赖、数据库、Provider 或持久化设置。

---

## 已确认事实及实施边界

上传原件与 `docs/requirements/2026-09-26-tire-intelligence-original.md` 的 SHA 均为 `f8a2a4434d83824afe36d3e46730ee183e4506acc0c91041b8a122b36e6fc46d`。该规格 872–883 列出桌面交互要求，本轮兑现其中三个相关条目，其余要求与完整 V1 继续保留。

当前 `apps/web/components/workbench.tsx` 的 `ComparisonTable` 为原生 table，仅外层可聚焦和水平滚动；没有行键盘移动、列宽控制或固定表头。两处既有调用分别用于当前比较和 `SavedComparisonsPanel`。Ctrl/Cmd+K 已实现，不能作为新功能重做。

只修改 `apps/web/components/workbench.tsx`、比较表专属 CSS，并新增 `apps/web/components/comparison-table-layout.tsx`。保留所有既有 dirty，不 commit/push/stash/reset/clean。Root 已将两个既有文件原字节备份至 `.artifacts/r120-comparison-table-20261022/before/`。不得打开正常库或保留证据 SQLite；本轮无需任何外部凭据。

## Task 1：实现布局和真实调用接线

Owner：implementation agent。其余 agent 不写这些文件。

- 新组件保持原生 table/thead/tbody/th/td 语义，明确列和行标题，不假称 ARIA grid；每实例使用独立的提示关联。
- 外层或行焦点时用 ArrowUp/Down 逐行移动，Home/End 到首尾，边界稳定；焦点可见且滚入可见范围。来自 button/link/input 等交互子项的按键不拦截，Tab 和证据按钮保持可达。
- 每列有可操作、命名明确的列宽控制；支持 pointer 拖动和键盘调整、有界宽度与重置。按稳定 column ID 管理本组件会话内宽度，列重排/增删不串列；取消拖动、失去捕获与卸载时结束状态，不留全局监听或用户选择锁。
- 有界滚动区内表头固定；如固定字段列，交点层级正确。宽列长值可换行，横向滚动留在表内，390px 页面不整体溢出，用户放大字体后内容仍可访问。
- 原有字段行内容、冲突/来源/人工状态和每列原始证据按钮原样传入；保持当前/历史语义和回调。
- 只沿用现有字号、颜色、边框与焦点规范，不改整个工作台视觉设计。

## Task 2：静审和有意义的真实浏览器验证

Owner：independent review agent 只读；Root 独占正式执行。实现 owner STOP 后才运行。

- 类型/生产构建按既有可复核入口执行；不从默认 API 启动，不重跑无关 API/Worker 全套。
- 使用实际 React 布局组件及两个比较场景，构造至少两个独立 SKU 列和足够多的字段行；当前/历史数据标签和证据按钮应保持不变。可复用既有前端编译/浏览器工具，避免新增通用 launcher 框架。
- 实际按键验证入口、逐行、首尾、Tab/Enter 证据回调与子控件按键不被拦截；不是仅调用事件函数的模拟检查。
- 实际指针与键盘验证列宽变化、上下限、取消/重置及列增删/重排；验证两个实例的宽度与焦点隔离。
- 实际滚动和几何观察验证固定表头与焦点行可见；390px 验证内部横滚、无页面横溢；保留可读的局部截图。
- 准确区分组件浏览器验收、生产构建、完整工作台/API、原生设备和 WCAG 全流程。没有执行的范围不得宣称通过。

## Task 3：正式证据与交接

Root 核对最终源码、验证终态与截图后写 `docs/assurance/evidence/round-120-comparison-table-interaction.md`，前置 `docs/HANDOFF.md` 新摘要，旧尾文原字节保留。保留失败批次，不用后续成功改写旧证据。完整 V1 不按轮数或检查数计算完成率，EPREL、真实专业 SKU/真人 Golden、真实模型、真实 PostgreSQL、来源覆盖及设备验收等仍分别留账。

## 并行来源调查（独立于产品改动）

source agent 有界核验 EU Safety Gate 官方匿名入口、robots、技术/开放数据合同及再利用说明，记录至独立 `.artifacts/r120-safety-gate-discovery-20261022/`。没有真实可用合同前不注册 ready，不猜公告 wire，不绕拒绝，不将不同措施统称召回；调查结果决定后续 P0 Safety 来源工程，不作为本轮比较表通过的证据。
