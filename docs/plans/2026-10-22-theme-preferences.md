# Theme Preferences Implementation Plan

> **R123 A/B 已冻结并授权实施（2026-10-22）。** Root 已核原件与仓库规格 SHA 一致，R122 报告/独审/交接已完成，并在 `.artifacts/r123-theme-preferences-20261022/before/manifest.json` 保存本轮11份原字节基线；原 HANDOFF 为155524 B / SHA `d500a5b40d3323b2b442235383d439b555af299a11ed8f3ce099f56f17eefc45`。本轮进入共享四态与宿主前端传播，Phase C 仍独立后续。Root 独占正式测试、构建、浏览器、宿主及证据应用。不创建 worktree，不 commit/push；所有执行者都不是独自在代码库工作，不回退其他代理修改或既有 dirty。

**Goal:** 在现有工作台外观入口提供 System / Light / Dark / High Contrast 四种本地偏好，使共享 UI、body portal 和桌面/手机前端同步采用解析后的配色，并保留现有原生栏两态亮度合同。

**Architecture:** 复用 `tire-theme-v1`、现有 CSS token 和 `WorkbenchPlatform.onThemeChange`。用一个文档级主题 provider 管理偏好、系统媒体变化和实际配色；Workbench 独立挂载时创建 provider，已有宿主 provider 时复用；portal 使用同一 React context。统一 `html[data-theme]` 传播实际配色，原有单参数回调只发送两态原生亮度。将四种 preference、三种 resolved palette 与两种 native brightness 明确分开，System 不作为 CSS palette 或原生桥参数。

**Tech Stack:** 现有 React 19 / Next 16、TypeScript、CSS 自定义属性、原生 select / matchMedia / Storage；纯 helper 采用现有 Node test/assert。无新增依赖、后端接口、数据迁移或通用主题框架。

---

## 1. 依据、现状与本轮边界

原件 `docs/requirements/2026-09-26-tire-intelligence-original.md:943` 要求高对比模式；966–975 明确列出 Light、Dark、System、High Contrast，并要求状态同时提供文字。原文没有规定默认主题、存储字符串、高对比具体颜色、System 的解析算法或原生 chrome 协议；下文这些内容是本计划的工程选择。

本次只读审计已确认以下接入点。行号为 R122 实现期间的现场位置，Root 冻结时须重新核对，而非用 Git HEAD 代替 dirty 产品快照：

| 接入点 | 当前实现及影响 |
|---|---|
| `apps/web/components/workbench.tsx:207–208,219,348,375,464–466,741,749,759` | Workbench 的平台/认证/provider 边界；本地 light/dark state、存储读取、切换、命令面板和顶栏入口；`.app-shell[data-theme]`；两态平台回调 |
| `apps/web/components/workbench-platform.tsx:15–21` | `onThemeChange?: (theme: "light" \| "dark") => void`，不能直接放入 system/high-contrast |
| `apps/web/app/globals.css:65,68–71,257–258,346–349,387,846,1398,1430` | 浅色基础 token、dark 覆盖、焦点/状态/比较控件；selection、backdrop 和少数边框为固定色；没有 System / High Contrast 或 forced-colors 合同 |
| `apps/web/components/offline-library.tsx:134,190` | body portal 挂载时捕获一次主题，不能随之后的系统媒体变化同步 |
| `apps/web/components/device-ai-panel.tsx:56,405` | Web 设备 AI body portal 同样只有一次主题快照 |
| `apps/desktop/src/main.tsx:12,102–124`；`src/native-platform.ts:15–16`；`src/styles.css:1–33` | Workbench 之外还有连接页、宿主栏及离线/AI 入口；桌面平台没有主题回调，外层固定浅色 |
| `apps/desktop/src/device-ai-panel.tsx:107,467` | 桌面 AI body portal 使用挂载时主题快照 |
| `apps/mobile/src/main.tsx:22–31,208`；`src/styles.css:1–10,26–28` | 手机回调写 html 的 `data-mobile-theme` 并调用原生亮度桥；外层、连接页、设置与移动 AI portal 共用两态 mobile token |
| `apps/mobile/src/native-platform.ts:66`；Android `TireNativePlugin.java:503–505` / `MainActivity.java:156,162–167` | `setSystemTheme` 严格只接 light/dark，并以 boolean 控制原生背景和系统栏；扩大前端值域会触发 INVALID_THEME |
| `apps/web/app/layout.tsx:7,11` / `manifest.ts:8`；desktop `src-tauri/src/lib.rs:1022–1043` | Web/PWA theme-color 固定浅色；桌面原生窗口没有应用主题接线。这些 chrome 边界不由共享 UI 变更自动关闭 |

本计划使用 brainstorming、writing-plans 和简洁写作方法组织方案；用户已指定当前会话与文件，不执行技能示例中的新 worktree、commit、额外设计文件或实现确认问答。本文不实施产品，不运行任何验证。

## 2. 方案比较与推荐

**推荐方案 A：一个共享状态源，保留现有入口、回调和 token。** 新增轻量纯值 helper 与 React context/provider，复用现存储键。根节点、Workbench 和 portal 消费同一 actual palette；现单参数回调继续只发送 light/dark 原生亮度，手机 CSS 改消费统一根属性，不增加平台 metadata 或第二个配色属性。桌面/手机前端适配可独立完成；Java 参数和值域不变。增加少量明确边界，能覆盖宿主连接页和系统变化，同时不引入第二套偏好。

方案 B：直接把 Workbench 的 theme union 扩成四个字符串，并给 CSS 和手机 bridge 继续传该值。修改表面少，但 `data-theme="system"` 没有实际颜色，旧读取器会把新值回落为 light，Java 会拒绝新值；portal 和 Workbench 外的宿主仍不同步。不可采用。

方案 C：Web、desktop、mobile 分别建立自己的存储/系统订阅，再通过事件或 DOM observer 对齐。可按平台独立实现，但将产生多个权威状态、多个媒体监听和重复初始化，连接恢复或 portal 更新容易冲突。当前需求没有独立主题仓库的收益，不采用。

## 3. 冻结共享合同

### 3.1 纯类型、存储和解析

新增 `apps/web/components/theme-preference-values.ts`，不导入 React、DOM、平台实现或业务 DTO。精确导出：

```ts
export const THEME_STORAGE_KEY = "tire-theme-v1";
export type ThemePreference = "system" | "light" | "dark" | "high-contrast";
export type ThemePalette = "light" | "dark" | "high-contrast";
export type NativeBrightness = "light" | "dark";
export interface ThemeAppearance {
  preference: ThemePreference;
  palette: ThemePalette;
  nativeBrightness: NativeBrightness;
}
export type ThemeChangeHandler = (brightness: NativeBrightness) => void;

export function parseThemePreference(raw: unknown): ThemePreference {
  return raw === "light" || raw === "dark" || raw === "high-contrast" || raw === "system"
    ? raw : "system";
}

export function resolveThemeAppearance(
  preference: ThemePreference,
  systemDark: boolean,
): ThemeAppearance {
  const palette: ThemePalette = preference === "system"
    ? (systemDark ? "dark" : "light") : preference;
  return { preference, palette, nativeBrightness: palette === "light" ? "light" : "dark" };
}
```

- 继续使用原键和值的简单字符串格式；已有精确 light/dark 完整保留，不 JSON 化或增加另一个存储键。system/high-contrast 是本轮新合法值；缺失、非法、大小写变化或存储读取失败默认 system。默认 system 是工程选择，不伪称原件已有默认值。
- 偏好仍属当前浏览器/WebView origin，不变成登录账户设置，不写服务端、不把设置外发给 Provider。跨 tab 同步、跨设备同步和自定义颜色编辑器不作为本轮必要能力。
- nativeBrightness 只表示当前计划配色适用的原生栏亮度；高对比采用黑底，因此映射 dark。不得把 system 或 high-contrast 传给现 Java 方法。
- System 解析 `prefers-color-scheme: dark`。`forced-colors: active` 由 CSS 系统颜色适配，不改写保存偏好，也不把 `prefers-contrast` 变成第五种产品选项。操作系统强制颜色覆盖的真实结果须单独验证，不据此宣称所有平台均有相同系统设置。

### 3.2 一个 provider、初始化与生命周期

新增 `apps/web/components/theme-preferences.tsx`，提供 `ThemeProvider`、`WorkbenchThemeBoundary` 和消费 hook。Context 内容至少为 appearance、ready、`setPreference(next)`；不提供任意字符串 setter。`WorkbenchThemeBoundary` 先读取已有 context，有外层 provider 就直接复用，无 provider 才创建，避免 native root 与 Workbench 重复监听或重复写存储。

R123 worker 精确接线接口：命名导出 `ThemeProvider` 与 `WorkbenchThemeBoundary`，二者 props 为 `{children: ReactNode; onThemeChange?: ThemeChangeHandler}`；命名导出 `useThemePreferences()`，返回 `{appearance: ThemeAppearance; ready: boolean; setPreference: (next: ThemePreference) => void}`，缺少 provider 时明确报错，不建立第二个隐式控制器。控件模块默认导出无必填 props 的 `ThemePreferenceControl`，复用此 hook。所有生产调用点必须在同一 provider/boundary 内；原生根可复用该控件，以便未连接时也能操作偏好。

1. SSR 与首次 hydration 使用确定的 system/light 占位和 ready=false，不在服务端读取 window、Storage 或 matchMedia。首次客户端初始化安全读取存储与媒体状态后，一次得到有效 appearance，再设 ready=true；不得先把默认值写回覆盖已保存 light/dark。
2. 现 Workbench 的主题读取、state、toggle 和回调 effect 移入这个权威路径；移除重复主题逻辑，不改同一 effect 中查询历史/排序读取。主题变化不加入 API 加载、查询 generation、离线授权或 R122 selection 的依赖。
3. System 初始化立即读取当前 media matches；订阅之后再读取一次，闭合初读与监听之间的变化窗口。System 媒体变化只更新 resolved palette，保存值继续是 system；显式 light/dark/high-contrast 不被系统深浅变化覆盖。
4. 使用同一 MediaQueryList 的 change listener，并在离开 System、provider 卸载和 StrictMode 重挂清理；环境无 matchMedia 或调用失败时保留 system 偏好、配色降为 light，不抛异常或阻断业务。若支持旧 addListener，则配套 removeListener；不要同时重复注册两套监听。
5. 用户选择时立即更新内存，再 best-effort 写原键；写入异常不回滚选择、不触发网络，也不产生无限重试。仅用户选择写入，不在 media change 或初次读取时写默认值。
6. ready 后由 provider 更新 `document.documentElement.dataset.theme` 为实际 palette、`data-theme-preference` 为偏好，并设置一致的 `color-scheme`；卸载只恢复自己拥有且未被其他 owner 改写的根属性。不要在 render 里写 DOM，不以 MutationObserver/全局自定义事件维护第二份状态。
7. ready 前不向原生回调发送占位 light；ready 后向现回调仅发送 `appearance.nativeBrightness`，原值域和单参数合同不变。初始化、切换和 media change 均沿这一条路径；卸载后不再发回调。不承诺尚未观测的 SSR 首帧或原生启动画面完全无颜色闪变。

`ThemeChangeHandler` 与现 `WorkbenchPlatform.onThemeChange` 结构兼容，不必修改平台接口或增加第二参数。provider 不反向导入 Workbench、portal、platform 或 native 模块，避免运行期循环；原生 root 把现有回调传给 provider，Workbench boundary 仅在实际创建 provider 时传入，删除旧 Workbench 通知 effect，保证只有一个通知 owner。Context 默认 null 表示未包 provider，不用默认主题对象猜测是否已有 provider。

### 3.3 四态入口、palette 与 portal

- 顶栏把旧深浅循环按钮换成有可见“主题”标签的原生 select，四项为“跟随系统 / 浅色 / 深色 / 高对比度”；选项值与 ThemePreference 精确一致。System 的实际深浅可用邻近简短说明表达，不能把当前 dark 展示成用户选择了 Dark。控件不得只靠图标、颜色或长 tooltip 表达当前设置。
- 命令面板复用同一 `setPreference`，提供四个明确选项或打开同一主题控件；不再保留语义不明的二态 toggle。Tab、方向键、Enter/Space 和焦点恢复遵循原生控件行为，不拦截全局快捷键。
- `data-theme` 只允许 light/dark/high-contrast；偏好 system 只能出现在 preference 位置。`.app-shell` 和 `.offline-portal` 都绑定 context 的实际 palette，根节点同样有 token，使 Workbench 外宿主可以继承。
- portal 不再 `useState(() => document.querySelector(...).dataset.theme)`；Web 离线、Web 设备 AI 和桌面设备 AI 都订阅 live context，createPortal 后保留 React context。主题或 media 变化时，已打开弹窗同步配色，保留表单、滚动、焦点、请求和业务状态，不为切换主题重新挂载 dialog。
- 手机设备 AI dialog 使用 root mobile token，随最高层 provider 与手机适配更新；手机样式直接消费统一 `html[data-theme]`，删除现 `data-mobile-theme` 写入源，不建立自己的主题 state。显式检查放在 Workbench 外的离线入口/portal 与连接失败页也处于同一个 provider 下。

### 3.4 高对比与系统强制颜色

复用现 `--paper/--surface/--sidebar/--ink/--muted/--border/--soft-border/--accent/--accent-soft/--green/--green-soft/--hover/--shadow`。浅色和深色保持同一套变量入口；增加实际 high-contrast palette，不另建按业务页面分裂的主题表。

高对比基线为黑色 paper/surface/sidebar、白色正文与边框、近白 muted、黄色链接/焦点/重点、可读的成功色与有边框的状态标记。需要精确数值时可从 `#000000/#ffffff/#e6e6e6/#ffff00/#00ff99` 起步，但最终通过条件是浏览器计算值、关键颜色对与可见效果，不能仅因 token 名叫 high-contrast 就算验收。

- 覆盖正文、muted、链接、按钮/输入/原生 select、checkbox、表格和行/列宽焦点、边框、分隔线、已选项、错误与成功/警告标记；边框和焦点保持可见，选中、live/snapshot/conflict、错误、禁用仍有文字或原生语义，不能只靠不同颜色。
- 核对现有固定 selection、backdrop 和少数强调边框；只做高对比需要的局部 token/覆盖，不重构全站样式。不让高对比焦点被 outline:none、透明 border 或组件背景吞没。
- `@media (forced-colors: active)` 使用 Canvas / CanvasText / ButtonText / LinkText / Highlight 等系统颜色；保留浏览器默认的 forced-color-adjust:auto，不全局使用 none 来锁死产品配色。状态标签可加 currentColor 边框，checkbox 保留原生形态，焦点用系统 Highlight。
- 文字对比与焦点/边框检查只覆盖本轮指定核心场景；不得据此声称完整 WCAG 2.2 AA、屏幕阅读器矩阵或系统级辅助功能通过。

## 4. 分阶段交付和验证门

| 阶段 | 产品范围 | 必须有的证据 | 不能由该阶段宣称 |
|---|---|---|---|
| A：共享四态 | 纯合同、单 provider、原存储、System、顶栏/命令、共享 CSS、Web portal live 主题 | Root 目标 types/helper、真实 React/browser media/控件/portal、生产 Web 构建 | 原生栏、桌面标题栏、PWA chrome、设备或完整 WCAG |
| B：宿主前端传播 | native root 的 provider 位于连接状态/Workbench 外；桌面外层 token；手机 palette 与亮度分流 | desktop/mobile 前端目标 types/构建、真实浏览器的宿主外层 harness、注入回调值与顺序 | 真实 Tauri/Android OS 已执行、iOS/macOS/其它设备通过 |
| C：独立 chrome 适配与宿主验收 | 现 Android 两态亮度桥的真实结果；需要时另冻桌面受限标题栏桥与 Web/PWA theme-color | 真实宿主/系统栏观察、允许的原生入口及最终资源终态；PWA 按实际浏览器/安装态另验 | 用 A/B 合成浏览器替代原生系统效果、跨平台全验 |

A/B 的控制器设计一次冻结，实施可以先 A 后 B，报告分别记账；不能在 A 通过时把产品标为完整跨端四态。C 的 native/PWA 修改须在 Root 确定实际合同与现成验收入口后单独派发，不扩大通用窗口权限，不把现 Java 两态桥改成接受四种 preference。原件四态目标和完整 V1 始终保留。

## 5. 任务、文件 ownership 与依赖

所有 worker 只准备自己拥有的代码和目标用例，**不得运行测试、构建、服务、浏览器或设备**。Root 才能执行正式验证。共享文件由一个 owner 修改；必要的接口变更先协调，不能覆盖 R122/R121 或其他代理修改。

### Task 0：Root 冻结 R122 之后的现场

Owner：Root。

1. R122 最终通过/失败结论与交接应用完成后，核对本文接入点和 dirty 来源，再明确本计划 A/B 是否进入实施；本草稿作者不自行启动。
2. 为具体受影响文件保存原字节 before 与 manifest；绑定 helper/provider/control、三个 portal、宿主前端、测试及复用 QA/build helper 的实际输入。不得拿 Git HEAD 当回滚基线。
3. 只规划新 GUID 私槽或静态前端组件宿主；不启动默认 API，不打开、迁移或查询正常/保留数据库；关闭真实 Provider/Embeddings/外网来源。主题功能本身不需要任何数据库或凭据。

### Task 1：纯合同与有意义的目标用例

Owner：values/test worker。

- Create: `apps/web/components/theme-preference-values.ts`。
- Create: `apps/web/tests/theme-preferences.mts`、`apps/web/tests/tsconfig.theme-preferences.json`。
- Read: 本文 3.1、既有 `tests/tsconfig.query-selection.json` 和目标 Node test/assert 风格。

1. 先写独立输入/预期表：旧 light/dark；四个合法值；null/undefined/空串/大写/未知/非字符串；System 的浅/深环境；显式三 palette 在两种环境下不变；高对比 nativeBrightness 为 dark。
2. 按 3.1 的精确 exports 实现，保持纯函数、不读取存储/媒体/DOM、不 import React 或平台模块；公开值域不得出现 system palette 或四态 nativeBrightness。
3. 目标用例核对 native 回调旧单参数消费者兼容性、appearance 的三字段及输入不变；不要写仅复述每行实现的快照测试。
4. tsconfig 继承根 `../../../tsconfig.json`、Node types、allowImportingTsExtensions、incremental=false，include 仅新 `.mts`。准备后 STOP，正式红/绿运行均由 Root 记录，不由 worker 执行。

### Task 2：共享 provider、入口与 portal

Owner：shared UI worker；独占本任务所有文件，避免其他 owner 同改 Workbench/CSS。

- Create: `apps/web/components/theme-preferences.tsx`、`apps/web/components/theme-preference-control.tsx`。
- Modify: `apps/web/components/workbench.tsx`、`apps/web/app/globals.css`。
- Modify: `apps/web/components/offline-library.tsx`、`apps/web/components/device-ai-panel.tsx`。
- Read only: `apps/web/components/workbench-platform.tsx` 的现两态单参数回调；不扩接口。
- Read first: `apps/web/AGENTS.md` 及实际安装 Next 指南中与 client boundary / hydration 相关的当前文档，沿用现入口，不按旧 Next 经验新增配置。

1. 接入 Task 1 类型，建立单 provider/context 和复用外层 provider 的 boundary；把 Workbench 主题 state/read/toggle/effect 收束进去，保留查询历史/排序与其他业务 effect。
2. 实现 3.2 的初始化、ready、System 订阅/清理、容错读写和根属性 ownership；effect 内外不混业务 API，不在 render 或纯 updater 写 storage/DOM/callback。
3. 接四态原生控件与命令入口，当前 preference 与实际 palette 文案分开；保留现有命令面板的焦点/快捷键规则。
4. CSS 沿现 token 增加 root/high-contrast/forced-colors，并核对指定焦点/边框/状态/固定色；控制只在本轮需要范围，不改页面布局或 R122 选择算法。
5. 两个 Web portal 用 live context；不通过 key 重建 dialog，不增加 MutationObserver 或第二套 localStorage reader。
6. 准备浏览器验证所需的组件公开入口与可访问名称后 STOP。不得自行运行 QA/build，不得修改现旧回执或为了通过检查放松产品颜色/边界。

### Task 3：desktop/mobile 前端适配

Owner：host frontend worker；依赖 Task 1 exports 与 Task 2 provider 接口冻结，不写共享 Workbench/CSS。

- Modify: `apps/desktop/src/main.tsx`、`apps/desktop/src/styles.css`、`apps/desktop/src/device-ai-panel.tsx`。
- Modify: `apps/mobile/src/main.tsx`、`apps/mobile/src/styles.css`。
- Read only: `apps/mobile/src/native-platform.ts:66`、Android `TireNativePlugin.java:503–505` / `MainActivity.java:162–167`、桌面 native builder/capabilities。A/B 不修改 Java/Rust/capabilities/manifest。

1. 在两个 createRoot 的应用最外层、连接屏与顶栏外放同一个 ThemeProvider；Workbench boundary 复用，不在连接成功后才第一次读取偏好。断线、重连或 Workbench 重建不能重置外观或重复注册媒体监听。
2. 桌面固定浅色外层改消费根共享 token，覆盖连接状态、设置、错误、重试与最外背景；桌面 AI portal 改用 live context。此处不声称已同步操作系统标题栏。
3. 手机保留现单参数 `onThemeChange`，brightness 继续交给 `native.setSystemTheme({theme: brightness})`；删除 `data-mobile-theme` 写入，避免第二个根属性漂移。不要把新三态 palette 当 Java 参数，也不增加第二个 appearance 回调参数。
4. 手机现 mobile token 增加 high-contrast，将 CSS 的 `:root[data-mobile-theme]` 选择器改消费统一 `:root[data-theme]`，覆盖外层、连接/错误页、设置 dialog、移动 AI portal 及按钮/焦点；不引入新偏好、全局事件或独立媒体订阅。
5. 原生亮度调用失败仍只影响 chrome 尝试，不能清表单、改变认证/请求安全或回写偏好；本轮注入回调验证只能证明发送值，不证明系统栏真实结果。完成后 STOP。

### Task 4：独审与 Root 正式验证

Owner：independent reviewer 只读；Root 独占正式执行与 `.artifacts` / evidence / HANDOFF。所有产品 worker STOP 后才运行。

正式入口由 Root 冻结实际 Node/依赖路径，在 PowerShell 7 中执行；以下为所需 payload，不是本文已运行的命令：

```text
node node_modules/typescript/bin/tsc --noEmit --incremental false -p apps/web/tests/tsconfig.theme-preferences.json
node --test --experimental-strip-types apps/web/tests/theme-preferences.mts
node node_modules/typescript/bin/tsc --noEmit --incremental false -p apps/web/tsconfig.json
node node_modules/typescript/bin/tsc --noEmit --incremental false -p apps/desktop/tsconfig.json
node node_modules/typescript/bin/tsc --noEmit --incremental false -p apps/mobile/tsconfig.json
```

1. 独审先核最小 owned diff、三种值域、旧读取兼容、唯一 provider、context/类型无循环、System listener 配对、存储异常、portal 和宿主 callback 传播，明确可触发问题；不因无源码报错就认定 runtime 通过。
2. Root 记录目标 types/helper 的真实红/绿批与源绑定；Node 类型重解析等 warning 如实保留。按受影响范围运行现有平台/弹窗目标回归，不运行无关后端、SDK或全仓套件。
3. Web 生产构建复用当前受审 helper 开全新批，记录生成文件恢复、源/依赖首尾稳定及 owned 资源终态；desktop/mobile 前端按现有已审入口构建和恢复生成文件。不得直接用默认 npm dev/start 启动正常 API。
4. 先用真实 React 组件与现成静态受限浏览器宿主验证 provider/控件/portal，再以新 GUID 合成生产工作台确认真实接线；如需 API，只用已经独立审过的显式私槽 fixture/NoNetwork，不直接复用 R122 活跃进程或改写其失败批。
5. 所有浏览器执行使用 headless 与精确 owned 进程，不移动用户鼠标、发送系统按键或切换用户窗口；Root 实际查看最终截图。记录请求边界、console/page/cleanup、端口/进程关闭和输入稳定，失败批不拼绿。

## 6. 浏览器与集成验收矩阵

以下都是待执行标准，不是已有通过结果：

| 场景 | 必须可观察结果 |
|---|---|
| 无保存值 + 系统浅/深 | 初始化后 preference=system，实际 palette 随初始媒体；回调不先发送未读取的默认 light |
| 已保存旧 light/dark | 重载后保留精确显式选择；系统反向变化不覆盖；原键仍是简单字符串 |
| System 动态媒体变化 | 用真实浏览器 media emulation 触发 change，根/Workbench/已开 portal 同步；保存值不被改为实际 dark/light |
| 切离 System / 卸载 / StrictMode | 再变媒体不覆盖显式偏好；监听移除且重挂无累积/重复通知；根属性只清自己拥有的值 |
| Storage 或 matchMedia 不可用 | 页面和控件仍可操作；当前会话选择可见；不阻断查询、认证、下载或弹窗 |
| High Contrast | 实际计算值与截图显示正文、muted、边框、焦点、链接、原生控件/checkbox、状态可读；四种偏好标签与当前值可识别 |
| OS forced-colors | 浏览器实际 forced-colors emulation 下使用系统色、原生 checkbox/焦点仍可见；没有全局 forced-color-adjust:none；不冒称真实 Windows 系统验证 |
| 键盘和窄屏 | Tab 到有名控件、原生方向键/Space/Enter 可选、命令入口可用、焦点稳定；390/320px 长标签/工具区无整体横溢 |
| portal 打开后改媒体 | 离线/Web AI/桌面 AI palette 随变，dialog 不重建；已输入字段、请求、焦点与滚动保持；手机 AI 随 root token |
| 宿主未连接/断线/重连 | desktop/mobile 外层也用当前 palette；Workbench 重挂不建立第二 provider、不覆盖保存偏好 |
| 原生两态分流 | 注入 callback/bridge 观察到的参数只为 light/dark；高对比发送 dark 亮度且前端 palette 保持 high-contrast；无 INVALID_THEME |
| 既有业务保全 | 切换外观不改 R122 待选/比较、证据焦点、R121 价格输入/选版或当前 API 授权，不额外发事实/模型请求；单项比较和原弹窗操作保持 |

高对比指定关键文字对可测 WCAG AA 常规文本 4.5:1，大字及必要非文字边界/焦点按相应场景核对 3:1，并记录实际元素与颜色；这只是本轮局部检查，不是完整 WCAG 声明。系统颜色、disabled/装饰元素和真实焦点可见性按实际场景解释，不用单一静态 hex 表代替浏览器观察。

## 7. Phase C 的独立后续合同

本计划 A/B 实施不修改原生代码或 PWA chrome。Root 后续分别判断是否实施下列小合同并另存对应证据：

- Android：现 `setSystemTheme(light/dark)` 真机/明确设备的系统栏图标、背景、恢复前台、配置变化与快速切换最终状态。现 dark 亮度仍映射 Java 的 `#191d1c` 背景，不等于原生栏已有黑底高对比配色。启动 splash/Java 初始 light 与 JS ready 之后分开观察；不能由注入 Promise 成功推断原生效果。
- 桌面标题栏：如需要跟应用偏好变更，先核当前 Tauri 版本/受限窗口 API，新增或开放精确亮度方法，明确只接 light/dark；不使用 `core:window:*` 广泛权限。Windows/macOS 分别验，不从一个宿主推断另一个。
- Web/PWA：动态 theme-color、layout 的状态栏设置与 manifest 启动画面属于不同机制。若调整运行期 meta，使用实际 palette 的明确颜色，不写 system；验证真实浏览器/安装态，manifest 初始色不伪称可动态四态。PWA 离线/已安装启动、iOS 状态栏另留账。

这些后续不成为 A/B 的隐藏依赖，也不因延期而从完整 V1 清单删除。真正宿主/设备验收前，不把共享四态或三端前端构建称为六平台全部通过。

## 8. 回滚、证据与停止点

产品回滚只撤回本轮具名 helper/provider/control、三个 portal 和宿主前端的已审差异或 before 原字节；保留 R122/R121、其他 dirty 和历史证据，不 reset/stash/clean，不更改数据库或服务端数据。保留原 `tire-theme-v1`：回滚到旧版后 light/dark 仍可读取；旧版对 system/high-contrast 会按其既有逻辑回落 light，必须如实记录，禁止回滚时清空用户全部 Storage。

Root 报告分别列已修改、helper/types、组件浏览器、生产工作台、三端前端构建、native/PWA 延后项与失败批；保留旧 evidence/HANDOFF 尾文原字节。源码、配置或构建通过不替代实际宿主、屏幕阅读器、WCAG 全流程或完整 V1 Gate。完整 V1 goal 保持 active，EPREL、专业真实 SKU/真人 Golden、真实模型/来源、生产与平台边界继续分别留账。

**R123 实施起点：A/B 已由 Root 冻结；所有实现与验收尚待本轮执行，不能把原草稿或此冻结动作算作产品通过。C 和完整 V1 继续保留。**
