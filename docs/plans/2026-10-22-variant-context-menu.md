# Variant Context Menu Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> 按 @executing-plans 的逐项步骤在当前会话继续实施；Root 负责冻结、正式验证和证据应用。本文采用 @writing-plans 的文件级任务格式。已有持续实施授权，不新增 worktree，不要求执行方式选择，不 commit/push/reset/stash/clean。

**Goal:** 为查询结果与关注页的规格卡片提供右键、常驻“更多操作”按钮和键盘可达的同一上下文菜单，复用现有动作与限制。

**Architecture:** 在现有 `VariantCard` 接入一个规格卡片专用菜单；工作台只协调当前打开的卡片 owner，菜单组件只管理展现、定位、键盘和关闭。七项业务动作继续使用 `variantActions` 及现有取消关注确认，不增加 API、业务状态副本、持久化设置或通用菜单框架。

**Tech Stack:** 当前 React 19.3 / Next 16.3.6、TypeScript、原生 DOM/Keyboard/Pointer 事件、React portal、既有 CSS 主题变量；不新增依赖。

---

## 文档状态与依据

**状态：Root 于 2026-10-22 冻结，产品与工装尚未实施。** R126 新批与 Root 终核已通过。Root 已重新读取接入点并保存 `.artifacts/r127-variant-context-menu-20261022/before/manifest.json` 所列现有文件原字节，确认两个拟新增文件不存在。下述文件名、接口和验证命令仍是待实现方案，不代表命令已经通过或工装已经受审；不得套用旧构建证明新菜单代码。

原需求：`E:/Mix/SunBrowser/跨平台轮胎查询、证据化监控与 AI 知识应用需求规格及技术方案.md`。874–879 行分别要求 hover 预览、右键上下文操作、Ctrl/Cmd+K、Shift 多选、表格键盘移动与列宽调整；930–938 行要求移动端不依赖 hover、大触控目标及完整键盘访问。**Shift+F10 / ContextMenu 键是本草案建议的标准键盘实现方式，并非原文逐字指定的快捷键。**

当前源码核对结果：

| 入口 | 已确认行为 | 本轮处理 |
| --- | --- | --- |
| `apps/web/components/workbench.tsx:794`、`:811` | query/watch 共用 `VariantCard`；query 使用来源与精确 ID 的 rowKey，watch 按关注记录显示 | 只接入这两处卡片 |
| `workbench.tsx:586` | `toggleCompare` 用 functional update；已有项可移除，新增最多 4 项，revoked 不可新增 | 原回调保留最终防线 |
| `workbench.tsx:594` | `toggleWatch` 有按 variant ID 的 pending 锁，复用 `tireApi.watch/unwatch` 与 toast | 菜单不复制网络写入逻辑 |
| `workbench.tsx:623` | `variantActions` 汇总证据、比较、关注、核验、生命周期、车库与 AI 回调 | 菜单消费这七项现成动作 |
| `workbench.tsx:865` | `VariantCard` 有 query checkbox、bookmark、内联取消关注确认及底部动作 | 保留原入口与状态；增加常驻更多按钮 |
| `workbench.tsx:575` | `showEvidence` 以 `document.activeElement` 记录 `evidenceReturnFocus` | 动作前必须先回到常驻卡片触发者 |
| `apps/web/components/command-palette.tsx` | 独立原生 dialog、Ctrl/Cmd+K、方向键、Esc、焦点归还 | 只读参考，不改成菜单，不重做命令面板 |
| `apps/web/components/comparison-table-layout.tsx` | 已有表格逐行移动、首尾、列宽与子控件按键隔离 | 只读参考，不扩展菜单到表格 |
| `apps/web/app/globals.css:1626`、`components/theme-preferences.tsx:161` | 已有 forced-colors 变量与 focus；主题写入 `document.documentElement` | 菜单 portal 继承现有根主题 |

本次检索 `apps/web/**/*.tsx` 未发现 `onContextMenu` 或 `role="menu"/"menuitem"/"menuitemcheckbox"`。这只是当前 Web 源码范围的静态事实，不代表其他宿主或运行时已验证。

已读 `apps/web/AGENTS.md` 与实际安装包 `node_modules/next/dist/docs/` 的 `01-app/01-getting-started/05-server-and-client-components.md`、`11-css.md`、`03-architecture/accessibility.md`；本项目依赖 hoist 在仓库根，`apps/web/node_modules/next/dist/docs` 不存在。菜单事件与 DOM 测量放在 Client Component，初始 SSR 不访问 `document/window`，不改 Server Component/API 边界。

## 范围、动作与行为合同

只覆盖 query/watch 两处规格卡片。不要接入比较表、保存比较、车库、车型、来源表格或研究首页，不新增全局快捷键注册器、上下文菜单 Provider、第三方菜单库、长按识别器或菜单配置系统。

hover 摘要预览尚未补齐；现有 toast 在移动端可能遮挡内容的问题另留账。本文不把这两项算入菜单轮，也不把完成右键操作称为整个桌面交互或完整 V1 完成。

### 入口与原生上下文

- 卡片头部常驻一个原生 `button type="button"`，可见文字“更多操作”，并以包含型号/尺寸的可访问名称区分卡片；触控目标首选至少 44×44 CSS px。不依赖 hover 显示，不只依赖 title，不为此扩展全局 IconName，复用文字即可。
- 普通点击、触屏点击、按钮的原生 Enter/Space 都打开同一菜单；按钮上 ArrowDown 可作为附加入口，不能替代 Enter/Space。
- 卡片空白和未选中的普通正文区域右键打开；仅在确实接管后 `preventDefault`。保留 input、textarea、select、可编辑区域、链接、其他动作按钮/summary 的原生上下文；常驻更多按钮自身是明确例外。
- 当前页面有非折叠文字选择时保留浏览器复制等原生菜单，不清选区。对 input/textarea 内部选择以原控件判断覆盖；不因选区 API 无结果而接管输入框。
- 在常驻更多按钮、或程序性聚焦的卡片根上支持 Shift+F10 与 `event.key === "ContextMenu"`；只处理目标卡片，保留输入/链接/其他交互子项。无需给整张卡新增普通 Tab 停靠点；常驻按钮已提供入口。无须给 Shift+F10 新增全局监听。
- 对 composing、已 `defaultPrevented`、其他不相关组合键不接管。若浏览器同一键盘操作随后再发 `contextmenu`，不要重复打开、重置位置或执行动作；以实际键盘/事件观察检验。

### 七项动作与限制

所有菜单项按当前 render 的 props 派生，不在打开时保存一份会过时的 `Variant`、watched、pending 或比较容量。描述如下，顺序可以直接采用表格顺序：

| 动作 ID | 可见名称/当前状态 | 执行及禁用规则 |
| --- | --- | --- |
| `evidence` | 查看证据 | 调用 `onEvidence`；revoked 仍可查看 |
| `compare` | 加入比较 / 从比较移除；显示当前勾选状态 | `onCompare`；仅 `!compared && (compareFull || revoked)` 禁用。已加入即使满 4 或已撤销仍能移除 |
| `watch` | 关注此规格 / 取消关注；显示当前关注状态 | pending 时禁用；未关注调用既有 `onWatch`，已关注只展示既有 `InlineConfirm`，确认后才调用 `onWatch` |
| `review` | 核验与纠错 | 调用 `onReview`，保留原核验权限/后续表单校验 |
| `lifecycle` | 版本状态 | 调用 `onLifecycle`，revoked 仍可核对 |
| `ai` | AI 分析 | 调用 `onAI`；revoked 时禁用，打开菜单不打开 AI 或发模型请求 |
| `garage` | 记入车库 | 调用 `onGarage`；revoked 时禁用，后续保存仍走现有流程 |

比较项对满额显示“比较已达 4 项”，对撤销显示“已撤销，不参与比较”；AI/车库的撤销原因同样可读。watch 保持当前产品规则，不擅自加“revoked 不可关注”的新限制。菜单自身不绕过权限、授权或后续确认。

比较/关注项采用 `role="menuitemcheckbox"` 和反映真实状态的 `aria-checked`；其余为 `role="menuitem"`。菜单为命名明确的 `role="menu"`；按钮用 `aria-haspopup="menu"`、`aria-expanded`、`aria-controls`。禁用项用 `aria-disabled="true"`，允许方向键到达并读到禁用原因，但在 pointer、Enter、Space 三条执行路径都必须拒绝调用；不依赖样式或单一 click 拦截。

共享的关注入口只能请求取消确认；不让打开菜单、选中“取消关注”、重复选中或 Esc/Tab 本身发 DELETE。沿用“只移除关注标记；已记录的变化与监控规则独立保留”的现确认内容。确认按钮的 pending/busy 取当前 `watchPending`，重复确认仍由现有 `watchLock` 防重。

### 焦点、关闭与零请求边界

菜单采用真正 DOM focus/roving `tabIndex`，不套用命令面板的 combobox/listbox 或伪造 grid。打开后聚焦首项；ArrowUp/Down 循环移动，Home/End 到首尾；Enter/Space 执行一次；移动后将项滚到菜单内部可见范围。禁用项可聚焦但不可执行。

Esc 关闭并回焦该卡片常驻按钮；只在菜单范围内消费事件。Tab/Shift+Tab 关闭，先同步聚焦常驻按钮再让浏览器继续正常 Tab 次序，不把菜单变成 modal focus trap；实际浏览器须证明后续/前序控件可达。点击外部关闭但不抢走被点击控件的焦点；滚动、resize、失焦、路由/结果切换及卡片卸载均清除菜单与本次监听/RAF。

**证据回焦风险必须单列验证：** `showEvidence()` 先读取 activeElement。若菜单项直接调用它，随后卸载菜单，证据回焦将指向消失的 menuitem。执行动作时按如下顺序处理：

1. 保存并核对原卡片常驻按钮或另一个仍连接的稳定原触发者；菜单项不能成为 restore target。
2. 请求关闭菜单，取消菜单内部尚未执行的聚焦 RAF；同步把 DOM 焦点还给稳定卡片触发者。
3. 再调用现有 `onEvidence/onAI/onReview/onLifecycle/onGarage/onCompare`，或展示取消关注确认，让现有业务流记录/接管正确焦点。
4. 此后 effect cleanup 只做资源清理，不再无条件 restore；业务对话框或确认已取得焦点时不得拉回按钮。

取消关注确认出现后聚焦现有确认块内的确认按钮；取消时回到卡片更多按钮。确认完成导致关注卡片被移除时，仅当焦点仍属于被移除的卡片，才转到下一张可用卡片的更多按钮或关注区标题；不要抢走用户已转移到其他控件的焦点，不给已卸载节点调用 focus。此为本地最小焦点补偿，不建立全局焦点管理框架。

同一工作台最多打开一个卡片菜单。query 的 owner 使用来源 rowKey，例如 `query:${rowKey}`；watch 使用关注记录 ID，例如 `watch:${item.id}`。同 SKU 在两个来源出现时不串 owner。单 owner 状态不写 route/hash/localStorage，不与 query 待选、证据 selected 或 compared 状态合并。

Ctrl/Cmd+K 从菜单中使用时，先结束菜单并把焦点交回稳定触发者，再让事件进入现有工作台命令面板路径；不阻止全局命令，不同时保留两个活动菜单层。真实 dialog 打开后不再把卡片菜单放在其上或抢焦点。

开/关菜单、hover 菜单项、方向键、Home/End、Esc/Tab、主题变化与定位测量都只改本地 UI：不调用 API、不预取证据、不刷新来源、不登录、不创建 AI 会话、不改监控规则。既有页面后台请求须与菜单因果区分；静态依赖请求也单独记账，不能把页面初始化请求说成开菜单引发请求。

### 定位与主题

- 打开后才 portal 到 `document.body`；初始 SSR 与 hydration 之前无 portal/DOM 测量。现主题边界写 html 根，portal 使用原变量，不复制/新存主题偏好。
- 用 `position: fixed`：pointer 入口以 client 坐标为锚，按钮/键盘入口以常驻按钮 rect 为锚；拿到实际菜单宽高后夹入可见区域，底部空间不足优先向上。初次测量完成前不把焦点项闪在视口外。
- 取 `visualViewport` 可用时的可见边界及 offset，缺失时回退 document viewport；保留约 8px 边距，宽度不超过可见宽度减双侧边距。最大高度不超过可见高度减边距，内部可滚；不设固定高度隐藏动作。
- 320/390px、右下/左下边缘、菜单滚动末项、200% CSS 字号应力都不能导致页面整体横溢或裁掉最后动作。关闭于页面/祖先滚动是本轮约定，菜单自身滚动不应误关闭；resize/visualViewport 变化允许直接关闭，避免留下错误锚点。
- 层级高于普通导航/比较 tray，真实 dialog 仍使用其原生顶层；不加全屏透明遮罩、不锁 body 滚动，不通过提高层级改造其他 UI。现 toast 的移动端布局问题仍独立留账。
- 现有 Light/Dark/高对比与 System 解析后的 palette 使用原 `--surface/--ink/--muted/--border/--accent`；forced-colors 用系统 Canvas/CanvasText/Highlight/GrayText、可见边框和 outline，不仅靠阴影/颜色区分焦点、选中、禁用。无需动画；不新增主题/焦点全局重置。

## Task 1：冻结输入与文件 ownership

**Files:**

- Read: `apps/web/AGENTS.md`、上述 Next 安装指南。
- Read: `apps/web/components/workbench.tsx`、`command-palette.tsx`、`comparison-table-layout.tsx`、`inline-confirm.tsx`、`theme-preferences.tsx`。
- Read: `apps/web/app/globals.css`、`scripts/command_palette_browser_qa.mjs`、`scripts/theme_preferences_component_qa.mjs`、`scripts/query_selection_web_ui_qa.mjs`。
- Create later, Root only: `.artifacts/r127-variant-context-menu-20261022/before/manifest.json` 及该轮真实 bytes 的 before 备份。

**Step 1:** Root 在 R126 终态之后重新读取上述相关接入点，确认本草案行号/谓词仍匹配，不沿用旧 HEAD 代表 dirty 源码。

**Step 2:** Root 为将修改的现有文件逐个记录 before bytes/SHA 并按原字节备份；确认新文件不存在，不覆盖同名他人文件。

**Step 3:** Root 冻结接口、预期文件和受限运行输入；本计划状态改为冻结需由 Root 单独应用。本轮 plan agent 到本文即 STOP。

**Step 4:** 指定产品 owner 负责 Task 2–4 的共享文件；QA owner 负责 Task 5；reviewer 只读，Root 独占 Task 6 正式执行。所有人均不是独自在代码库，不回退他人 dirty。涉及共享接口的实现先顺序完成，不让两个 worker 同写 `workbench.tsx` 或 `globals.css`。

## Task 2：增加规格卡片专用菜单组件

**Files:**

- Create: `apps/web/components/variant-context-menu.tsx`。
- Read: `apps/web/components/command-palette.tsx`，参考关闭前交接焦点与清理，勿改该文件。

**Step 1:** 定义局部接口；`VariantContextMenu` 只接受当前 actions、可见 label、anchor、稳定 trigger ref 和 `onClose`，不 import `tireApi`、`Variant` 数据读取器或任何业务 Provider。建议接口骨架如下，最终由 Root 冻结后实现：

```ts
export type VariantMenuAction = {
  id: "evidence" | "compare" | "watch" | "review" | "lifecycle" | "ai" | "garage";
  label: string;
  disabledReason?: string;
  checked?: boolean;
  run: () => void;
};

export type VariantMenuAnchor =
  | { kind: "pointer"; clientX: number; clientY: number }
  | { kind: "trigger" };

export type VariantMenuCloseReason =
  | "escape" | "tab" | "outside" | "action" | "viewport" | "replace";
```

**Step 2:** 实现打开后的 portal、真实宽高测量与固定定位。先处理越界、最大高度及 menu 内部滚动，再移入首项焦点；所有 DOM 查询有已挂载保护，ID 用 `useId` 保证每实例唯一。

**Step 3:** 实现本草案的 roving focus、循环方向键、首尾、Enter/Space 单次执行及 `aria-disabled` 三路径拒绝。点击执行和键盘执行合用一个 dispatcher，避免 keydown 与 button 默认 click 双调用。

**Step 4:** 实现关闭原因区分：Esc/动作需要稳定 trigger 的同步焦点交接；outside/viewport/replace 不强制恢复；Tab 交还原生顺序。effect 清理取消监听/observer/RAF，不在 cleanup 再抢焦点。

**Step 5:** 仅打开期间绑定必要的 outside pointer、scroll capture、window blur/resize 和 visualViewport 监听，过滤菜单自身滚动并在关闭/卸载全部解绑。与 Root 复核组件未引入网络、存储或新全局菜单系统。

## Task 3：接入两处卡片并复用业务回调

**Files:**

- Modify: `apps/web/components/workbench.tsx`，限相关 import、单活动 owner 状态、两处 `VariantCard` props 与 `VariantCard` 内部。
- Read: `apps/web/components/inline-confirm.tsx`；优先在卡片局部包裹/ref 定位现有确认按钮，不为单个菜单重构通用确认组件。

**Step 1:** 在 `WorkbenchContent` 增加单个当前菜单 owner；query/watch 传入互不冲突的稳定 owner key。切视图、发起新查询、移除卡片时失效关闭；只控制 UI，不顺带清 query checkbox、比较或证据。

**Step 2:** `VariantCard` 维护更多按钮 ref、卡片 ref 和本次 anchor。header 添加常驻更多按钮；根上按“原生上下文”合同处理右键/键盘，保留当前 checkbox Shift 行为与底部动作入口。

**Step 3:** 基于现有 props 生成七项菜单 descriptor。比较禁用谓词必须与底部按钮一致：

```ts
const revoked = variant.lifecycle?.state === "revoked";
const compareDisabled = !compared && (compareFull || revoked);
const compareReason = compareDisabled
  ? revoked ? "已撤销，不参与比较" : "比较已达 4 项"
  : undefined;
```

`compare` 仍直接调用 `onCompare`，不得复制 setCompared、slice 截断、替换比较列表或改写批量 add-only 逻辑。AI/garage 与当前 revoked 条件一致；watchPending 取实时 props。

**Step 4:** 整理卡片内的请求关注入口：未关注且非 pending 才 `onWatch()`；已关注只 `setConfirmUnwatch(true)`。bookmark 与菜单共享这个入口，确认按钮沿用现有 `onWatch`，取消仅关闭确认。重复选菜单“取消关注”不得绕过确认；按当前 pending 给确认块 busy。

**Step 5:** 在统一动作 dispatcher 中先结束菜单与同步聚焦常驻触发者，再调用原动作。特别核对 `onEvidence` 进入 `showEvidence` 时 activeElement 已是稳定节点；InlineConfirm 的首次焦点在本卡片局部完成，dialog 自己接管焦点。

**Step 6:** 对关注删除与卡片卸载补局部 fallback；如果用户焦点已经到其他地方不干预。保持 `variantActions`、toggleWatch/Compare、API 客户端与业务权限逻辑本身不扩张。

## Task 4：添加局部样式与无障碍状态

**Files:**

- Modify: `apps/web/app/globals.css`，只新增 `.variant-context-*`、更多按钮局部 header 布局及对应 forced-colors 样式。

**Step 1:** 更多按钮与 bookmark 放在局部 heading actions 中；320px 长型号可换行，按钮不收缩至不可触控，不改整个工作台间距/字号。

**Step 2:** 菜单用现有主题变量、边框和有限层级，项目内高/宽可读；较长禁用理由换行，44px 首选触控目标，菜单宽度由可见 viewport 限制。

**Step 3:** focus 与 current/checked/disabled 有明确语义和可见状态；forced-colors 使用系统颜色、实线边框及 outline，避免透明 outline、禁用纯 opacity 或仅阴影。

**Step 4:** 记录需实测的 320/390、右下锚点、向上翻转、内部滚动和字体应力预期；本步骤不把 CSS 静态查看等同真实几何通过。

## Task 5：编写有意义的定向浏览器验收

**Files:**

- Create: `scripts/variant_context_menu_web_ui_qa.mjs`。
- Read: `scripts/web_theme_color_web_ui_qa.mjs`、`scripts/query_selection_web_ui_qa.mjs`，借用现有生产 Web/合成私槽、runtime 固定、请求记账与自然关闭合同。
- Create later, Root only if required by existing runner: `.artifacts/r127-variant-context-menu-20261022/run-ui-host.py`，仅当前轮必要的精确派发增量，不新增公共 launcher。

**Step 1:** QA owner 编写但不自行运行脚本；实际操作生产 `Workbench` 两处真实 `VariantCard`，不复制一张长得相似的假卡片，不只证明单独菜单组件。复用现有 R122 合成私槽建立关注/比较/可撤销规格；若现 fixture 缺少数据，仅在 Root 审查后给本轮新私槽最小合成输入，不修改旧证据 fixture。

**Step 2:** 定向断言覆盖此前不存在的行为：右键/按钮/Shift+F10/ContextMenu 打开、唯一 owner、ARIA 与焦点、关闭和无菜单业务请求。菜单入口缺失已有原源码及 before 字节证据，不单独增加旧版浏览器批；实施后的通过必须来自新构建实际行为。不要写只检查类名/源码字符串或逐行复述实现的单元测试。

**Step 3:** 使用真实浏览器 `click({button:"right"})`、click 与 keyboard 操作；ContextMenu 按键若驱动/平台不能真实发送，明确以合成 KeyboardEvent 补测并将真实系统 ContextMenu 键列为未验，不能混作原生硬件通过。以原生事件 defaultPrevented/回调及选区保留证明“未拦截”的范围，headless 无法展示的操作系统原生菜单单独注明。

**Step 4:** 写入下方验收矩阵，数据包含两个来源相同 variant ID、不同 ID 同型号、4 个已比较、已比较又 revoked、未比较 revoked、已关注/pending 与可移除关注卡片。请求日志区分初始化、动作请求和打开菜单窗口；开菜单阶段必须没有新增业务 API/Provider 请求。

**Step 5:** 每个新批保存源/依赖/构建 pins、逐项结果、几何、局部截图、page/console/unexpected_requests 和 owned 进程关闭终态。保留失败批，不以跨批拼接记录宣称全部通过；脚本完成向 Root STOP，不自行启动服务/浏览器。

### 必须覆盖的验收矩阵

| 场景 | 预期结果 |
| --- | --- |
| query/watch 三种入口，连续开第二张卡 | 同一套动作；仅一份活动菜单；不同来源相同 SKU 不串卡 |
| 更多按钮 Enter/Space、Shift+F10/ContextMenu | 首项真实焦点；无双开、双调用或滚动副作用 |
| ArrowUp/Down、Home/End、禁用项 | 焦点可见、循环/首尾正确；禁用原因可读，任何路径不执行 |
| Esc、Tab/Shift+Tab、外部点击、滚动、blur、卸载 | 分原因关闭；原生 Tab 可离开；新焦点不被 cleanup 拉回；无遗留监听 |
| 菜单→证据→关闭 | `evidenceReturnFocus` 指向原卡片稳定按钮；关闭回卡片，不是 body/已卸载 menuitem |
| 菜单→AI/核验/版本/车库 | 现有对话流接管；焦点不被后续 effect 抢回；revoked 限制正确 |
| 关注/取消确认/取消确认后重开/双点击/pending | 未确认不发 DELETE；确认走现有锁；结果与 bookmark 同步；移除后焦点有存活 fallback |
| 比较第 4/第 5 项，已比较 revoked 再移除 | 最多 4；不替换/截断；已比较仍可移除；菜单与底部按钮状态一致 |
| 输入、链接、summary、其他动作按钮、选中文字 | 不阻止原生右键/键盘上下文；选区与正常文本操作保留 |
| 打开/导航/关闭菜单的请求窗口 | 不出现菜单触发的新业务 API、取证、模型、监控写入；实际业务动作另记 |
| query checkbox 与 Shift+Space、Ctrl/Cmd+K | 原 Shift 待选/比较与命令面板正常；打开菜单不改待选、证据 selected 或比较 |
| 320/390/桌面，四角，向上翻转，末项滚动 | bounding rect 在可见区域；页面无整体横溢；末项和焦点可达 |
| Light/Dark/高对比/System、forced-colors、字号应力 | 主题实时一致；outline、checked、disabled 可辨；没有仅颜色/阴影状态 |

## Task 6：Root 正式验证、证据和回滚

**Files:**

- Read/freeze: 本轮两个产品 TSX、局部 CSS、新 QA 及所用运行输入。
- Create after verification: `docs/assurance/evidence/round-127-variant-context-menu.md`。
- Modify after verification, Root only: `docs/HANDOFF.md`，前置新摘要，旧尾文原字节保留。

**Step 1:** 产品/QA owner STOP 后，独立 reviewer 只读检查全部冻结文件，重点审焦点归还、原生选区、动作权限/4 项/revoked、pending 防重与清理。Root 修正明确问题后只重跑受影响验证，不追加无关后端全套。

**Step 2:** Root 执行适当的 Web 类型验证和一个新生产构建，沿当前受审 build 入口执行并记录源稳定及生成物恢复；不把旧 R124/R125 产物套在新菜单上。常规 payload 为：

```pwsh
npm run typecheck --workspace @tire/web
npm run build --workspace @tire/web
```

以上是 package 中已有命令，不是在本草案阶段直接运行的授权派发命令；正式受管执行由 Root 使用当前已审入口、全新 batch 和精确 Node/Python 路径。若已有类型检查因共享 dirty 报无关问题，分清基线与新增，不把未执行/失败写成通过；不为本轮增加测试框架。

**Step 3:** Root 使用本轮合成私槽与匹配新构建运行新 QA。拟定 CLI 与现生产 QA 一致，待新增脚本和 pins 受审后才实际执行：

```pwsh
node scripts/variant_context_menu_web_ui_qa.mjs --origin http://127.0.0.1:18987 --output $menuQaOutput --build $menuBuildOutput --build-report-sha $menuBuildReportSha
```

三个 `$menu*` 变量由 Root 绑定到本轮全新工件路径及匹配的 64hex SHA；不得把空值、正常库路径或旧批输出带入。预期自然 exit 0、同批所有必要断言通过、source/dependency/build 稳定、非预期请求/页面异常/清理失败为空。服务与浏览器由现精确 owned-process 合同启动/回收，不操作用户浏览器、鼠标、桌面或系统进程。

**Step 4:** Root 查看该批局部截图并检查几何及焦点记录，至少桌面、390px、320px、forced-colors 与 dark/高对比；截图不能单独证明键盘或业务写入。ContextMenu 合成补测、200% CSS 字号应力、媒体 emulation、headless 与真实设备边界分别列明。

**Step 5:** 通过后写正式报告并更新 HANDOFF，报告写清已修改、实际已验证、未验证/延后与失败批。此菜单验收不证明真实厂商/专业 SKU/真人 Golden、Provider/Responses、正常库升级、PostgreSQL、PWA 离线、原生设备、读屏/完整 WCAG 或完整 V1；hover 与移动 toast 继续留账。

**Step 6:** 若本轮需要回滚，由 Root 按本轮 manifest 对照 after pins，仅恢复本轮 owned diff。新增 `variant-context-menu.tsx` 与 QA 在仍匹配本轮 SHA 且无他人后续更改时才可移除；现有 workbench/CSS 只撤回本轮改动，不用 Git checkout/reset/stash/clean。若共享文件已被别人续写，逐段回退并重新核对，不覆盖他人内容。菜单没有迁移/持久化状态，无数据库回滚；失败证据原样保留。

## 草案完成判定

计划现已由 Root 冻结。产品实施、QA 编写、测试/构建、真实浏览器验收和证据/HANDOFF 应用仍待完成；不得据计划冻结把本需求或完整 V1 标为 complete。
