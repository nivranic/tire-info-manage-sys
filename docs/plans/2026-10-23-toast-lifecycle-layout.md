# Toast 生命周期与底部布局 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> 当前状态：Root 于 2026-10-23 冻结，尚未实施、未运行验证。原候选及四个允许修改的产品文件已按当前原字节归档；最终文本复核通过后按本计划继续当前会话的持续实施授权，不新增用户确认、worktree 或 commit/push 流程。实施沿用项目现有执行与独审入口，不因本计划新增技能安装、服务或自动执行流程。

**Goal:** 复用现有 ToastProvider，让提示可关闭、在阅读和交互期间暂停，并让受支持视口中的正文末尾关键操作可以滚动至底部浮层上方并实际操作。

**Architecture:** 保持 `useToast(): ShowToast` 与现有业务调用不变，继续使用一个 ToastProvider。每条提示拥有自己的剩余时间和清理边界；Provider 统一观察页面可见性与底部布局。以实际可见导航、toast 栈和比较栏高度协调同一局部布局变量，不重挂 Workbench、不建立第二套键盘检测器。

**Tech Stack:** 现有 React、TypeScript、共享 Web CSS、ResizeObserver、Page Visibility API；原生 mobile 只消费既有 `data-keyboard-open`。后续验证复用项目已有浏览器与私槽资源管理方式，不增加依赖。

---

## 1. 已确认依据与验收边界

本稿基于 QA 已完成的 toast 窄审，并只读核对相关实现；行号为编稿时导航位置，不是源码冻结 pin。

| 已确认事实 | 现有入口 |
| --- | --- |
| 唯一提示 Provider；寿命 4600ms；最多保留最近三条非空提示 | `E:/Mix/project/tire-info-manage-sys/apps/web/components/toast.tsx:19` |
| `show()` trim 文本、分配递增 ID；第四条截去最旧项，但旧 timer 仍留至到期；dismiss 和 Provider 卸载有清理 | 同文件的 `show`、`dismiss` 与卸载 effect |
| toast 不自动聚焦；现有 polite live region、普通 status/error alert 语义 | 同文件返回结构 |
| 关闭按钮被 toast 局部规则缩至 34×34px | `E:/Mix/project/tire-info-manage-sys/apps/web/app/globals.css:1444` |
| toast 固定底部且 z-index 90；窄屏底部是 74px 加 safe-area；正文只留导航空间，比较栏也在底部 | 同文件 `401`、`495`、`572`、`580`、`1437`、`1446` |
| Workbench 外层现有 Provider；真实关注/取消关注完成后触发成功提示，失败触发错误提示；查询存在比较栏 | `E:/Mix/project/tire-info-manage-sys/apps/web/components/workbench.tsx:211`、`621`、`855` |
| `keyboardOpen` 只在原生 mobile 外壳检测并写入 documentElement；普通 Web/Workbench 没有同名检测 | `E:/Mix/project/tire-info-manage-sys/apps/mobile/src/main.tsx:175` |
| 原生 mobile 用该 flag 隐藏导航，且另有 app-shell 底部 padding 覆盖 | `E:/Mix/project/tire-info-manage-sys/apps/mobile/src/styles.css:39` |

当前没有运行时新证据。既往窄屏提示遮挡的观察可作为问题线索；不能据此声称本候选已修复或所有设备都存在相同几何。

**本候选保证的是关键操作可滚达、可见且可操作。固定 toast 仍可能覆盖任意滚动位置的正文；不承诺所有位置无遮挡。** 支持的首批浏览器验收矩阵至少为 1365×900、390×844、320×844、320×420。低于该可用高度、真实 IME 导致的布局/视觉视口差异，另记证据边界，不以截图推断。

## 2. 方案选择与最小范围

| 布局选项 | 收益、代价与选择 |
| --- | --- |
| 保留 fixed，加真实高度测量与共享底部余量 | **推荐。** 保留现有提示位置和业务入口，只增加本候选实际消费的局部几何；可覆盖换行、三条提示、比较栏与原生导航显隐。重点限制 observer 和 CSS 变量数量。 |
| 只改 44px，再扩大固定 offset/padding | 差异最小，但无法可靠覆盖三条长提示、字体变化和比较栏；容易用更大常量换来空白或继续遮挡，不采用。 |
| 在正文增加流内提示槽 | 减少浮层重叠，但改变提示可见位置和用户滚动行为；跨不同视图和比较栏需要更多布局调整。本候选暂不采用，不扩大成全局浮层架构。 |

| 文件 | 后续职责与限制 |
| --- | --- |
| `E:/Mix/project/tire-info-manage-sys/apps/web/components/toast.tsx` | 每项计时/暂停/幂等移除；Provider 页面可见性监听；toast 栈测量；局部布局变量与最小内部注册入口。保留 ShowToast 签名、种类、trim、4600ms、三条上限和业务消息。 |
| `E:/Mix/project/tire-info-manage-sys/apps/web/components/workbench.tsx` | 只给现有 app-shell、mobile-nav、comparison-tray 接入局部布局和实际元素注册；必要时提供现有 main 作为焦点兜底。不得改查询/关注/比较请求、表单状态、菜单实现或 Provider key。 |
| `E:/Mix/project/tire-info-manage-sys/apps/web/app/globals.css` | toast 关闭目标至少 44×44；动态底部间距、正文滚动余量、比较栏偏移、toast 栈高度上限与内部滚动。保留主题与系统色体系。 |
| `E:/Mix/project/tire-info-manage-sys/apps/mobile/src/styles.css` | 仅消除现有 39–41 行 padding/导航规则与共享动态余量的冲突；在原生 keyboard flag 下去除导航占用。不得增加第二键盘状态。 |
| `E:/Mix/project/tire-info-manage-sys/scripts/toast_lifecycle_ui_qa.mjs`（后续新增） | 用真实组件验证计时边界与布局；再通过真实 Workbench 关注入口验证集成。优先单一 QA 入口复用既有私槽/浏览器宿主，不复制调度器、进程守护或数据库封装。具体 CLI/输入清单在执行前独审时确定，本稿不冻结。 |

`apps/mobile/src/main.tsx` 是只读合同依据。原生外壳、SDK、后端、数据库、依赖清单、持久化格式不在产品修改范围。若实施发现必须修改这些边界，应先给具体证据并修订候选范围，不能顺手扩项。

不纳入 hover 预览、其他 V1 缺口、通知历史、消息合并、用户可配寿命、永久错误通知、全局浮层系统或重写 ARIA 播报策略。不覆写 R127 的冻结归档、工装、既有批次、评审或历史 pin。本轮允许表所列 live 产品源码的后续增量必须绑定新构建和新验收批次；R127 的通过仅证明当时绑定的源码，不能套用于本轮修改后源码。

## 3. 生命周期与焦点合同

### 3.1 保持既有入口和上限

- 非空 trim 文本才产生 toast；默认 info、kind 及现有文案不变。ID 在当前 Provider 生命周期内递增，旧回调不能命中新项。
- 最多显示三条，默认保留新消息；新增第四条时保护当前真实 `document.activeElement` 所属的那一条 toast，挤出最旧的非持焦项。不增加隐藏队列，也不保护仅 hover/hidden 的项；同时最多只有一条真正持焦。没有真实持焦项时仍挤出最旧项；焦点离开后不永久保留该项。此为对现有“最近三条”的一项有意收窄，避免“focus 期间不自动消失”被容量淘汰绕过。
- 自动到期、关闭、挤出、Provider 卸载共用同一幂等释放语义；重复调用不改变其他提示。Provider 卸载清监听、observer、待执行布局任务和全部 timer。
- React state updater 保持纯函数。可优先把单项 timer 放在内部 toast 子组件，借挂载/卸载承接清理，避免在 `setItems(previous => ...)` 中读写 Map、clearTimeout、读取 DOM 或移动焦点；不为测试新建业务 scheduler 服务。
- StrictMode 的 `setup → cleanup → setup` 不是显示项被业务移除。cleanup 清当前 timer/监听并使旧回调失效，但不能清空仍显示项的剩余时间元数据、永久标记 disposed，导致第二次 setup 无法重建 timer；第二次 setup 按当前可见性/暂停原因和剩余值恢复，不能重置为完整寿命或重复建 timer。

### 3.2 每条提示的暂停与剩余时间

每项分别维护 `hover`、`focus-within`、`document-hidden` 三个暂停原因。任一存在就暂停；只有最后一个原因解除才恢复。示例：hover 后聚焦关闭按钮，再移开鼠标，仍因 focus 暂停；随后页面隐藏、焦点离开，仍因 hidden 暂停；恢复可见后才继续计时。

| 状态变化 | 必须行为 |
| --- | --- |
| 可见页面新增、无交互原因 | 从 4600ms 开始一段计时，不自动聚焦 |
| 隐藏页面新增 | 保留完整 4600ms，不启动 timer；初值读取当前可见性，不能等第一次 visibilitychange |
| 从无暂停进入首个暂停 | 使用 `performance.now()` 等单调时钟扣除本段已运行时间一次，剩余值下限为 0，然后清 timer |
| 已暂停时新增/移除部分原因 | 不再次扣时、不重置寿命、不创建新 timer |
| 最后一个原因解除 | 只按剩余值恢复；剩余 0 则通过统一到期路径收敛，不能赠送新的 4600ms |
| 计时结束回调 | 检查该项仍存在、计时版本仍有效、当前无暂停且未释放；旧排队回调不得删除已暂停/被替换的项 |

hover 只来自实际支持悬停的指针交互，触摸点击不制造永久 hover 暂停。focus 使用整项 `focus-within` 语义，内部焦点移动不产生先恢复再暂停的瞬间。document hidden 是所有现存项的公共原因，项级 hover/focus 仍各自独立；不使用 window blur 代替页面可见性，也不自动隐藏提示。

不要求浏览器 timer 毫秒精确；要求暂停和恢复的逻辑时间正确、没有提前到期、没有重复 timer 或晚回调误删。页面冻结/休眠后的实际调度另列浏览器/设备边界。

### 3.3 焦点与输入保全

- toast 出现、自动消失或尺寸变化均不得抢焦点、强制滚动或重挂 Workbench。当前输入节点、值、选区、查询草稿、未提交价格表单和比较选择保持原对象与状态。
- 焦点在某 toast 内时自动到期暂停。用户明确关闭且焦点仍位于该 toast 时，优先移向相邻存活提示的关闭按钮；没有存活提示时，返回进入 toast 前记录的、仍 connected 且可聚焦的外部元素。不可用时使用现有 main 的稳定兜底，不能跳到任意新业务按钮或重开菜单。
- 容量淘汰保护真实持焦项，不主动挤出它。新增消息与焦点变化交错时，不能让陈旧的“待挤出 ID”把新近持焦项移除；需要在事件/提交边界维护一致性。若其他明确移除路径使持焦项消失，只能按同一局部兜底处理。焦点已在外部时，关闭/挤出/旧回调绝不覆盖用户的新焦点；焦点调整只发生在确认旧焦点归属被移除项之后。
- 点击关闭只移除目标项，不调用业务 API。保留现有关闭 aria-label、可见焦点和通知语义；本轮不把提示改成 modal，也不新增键盘陷阱。

## 4. 动态底部布局合同

### 4.1 一个局部占用来源

在现 Provider 作用域内持有 toast 栈及可见底部导航、比较栏的实际元素。通过局部 wrapper 上的 CSS 自定义属性向其 app-shell 子树及 toast 栈共同传值；若添加 wrapper，采用不新建滚动容器/固定定位包含块的布局方式。现 `useToast()` 仍只返回稳定 show 函数；布局注册只供现 Workbench 消费，不修改全部业务调用点，也不写 documentElement 的全局几何变量。

初次显示、提示数量/文案换行、字体/宽度改变、比较栏挂载/卸载、导航显隐及容器恢复可见时，ResizeObserver/现生命周期统一重测。隐藏或不存在的元素占用为 0；同值不反复写入，observer 不改其被测元素宽度造成反馈循环。清理后将局部占用归零，不遗留样式或 scheduled frame。

可见 mobile-nav 的实际高度包含其 safe-area padding；只计一次 safe-area，禁止同时把已测导航高度再加原 `74px/76px` 和另一份 inset。桌面导航不存在时为 0。空 toast 栈或空比较栏不保留其高度或专属间隔。

### 4.2 位置与正文余量

从视口底部向上排列：可见底部导航/底部安全间隔 → toast 栈 → 比较栏。冻结采用 **8px 层间间隔、桌面 20px 基础边距、窄屏无导航 12px 基础边距**。所有固定底锚与可用高度统一使用 **layout viewport 坐标系**；不得取 `visualViewport.height` 却仍按较大 layout viewport 的 bottom 定位。本轮不新建键盘检测，不把这份布局 viewport 合同当成真实 IME/视觉视口恢复验收。

定义 `N` 为可见导航实际 border-box 高度（已含其 safe-area），`T` 为受上限约束后实际 toast 栈高度，`C` 为可见比较栏实际高度，`S` 为当前 safe-area bottom，缺失/隐藏层为 0。窄屏沿现有 max-width 767px；原生 keyboard=true 只适用于 mobile 外壳现有 flag。

| 冻结值 | 公式与空态 |
| --- | --- |
| 底部基础 `b` | `N > 0` 时 `N + 8`；无导航 desktop 为 `20`；无导航普通窄屏为 `12 + S`；native keyboard=true 且导航隐藏为既有 `12` 例外。不可把 `S` 再加到已包含它的 `N` 上。 |
| toast bottom | 存在时为 `b`。 |
| 比较栏 bottom | `T > 0` 时 `b + T + 8`；否则 `b`，不保留空 toast 层间隔。 |
| 有 toast 或比较栏时正文底部余量 `O` | `b + T + C + (T > 0 且 C > 0 ? 8 : 0) + 8`。最后 8px 为正文操作与最上浮层的间距。 |
| toast/比较栏均为空时 `O` | `N > 0` 为 `N + 8`；无导航普通窄屏为 `12 + S`；native keyboard=true 为 `12`；desktop 为 `0`，无专属 toast/tray 留白。 |
| toast 栈高度预算 | `H - b - C - (C > 0 ? 8 : 0) - 44 - 8`，`H` 与 fixed bottom 均来自同一 layout viewport；44px 留给正文关键操作，8px 为其上方与浮层的间距。支持矩阵内还必须容纳含 padding 的完整 44px 关闭目标；不足时记实际几何失败，不能缩目标或靠重叠通过。 |

正文末尾 padding/必要的 scroll-margin 消费上述同一总占用量。比较栏按 toast 当前高度上移；toast 到期、关闭或缩行后比较栏与正文余量同步回落。以上公式是实际消费合同，具体以 CSS 表达还是局部测量值实现可沿现有结构选择，不能让不同选择器各自猜 offset。

**验收不是比较 padding 数字，而是把正文末尾关键操作实际滚到浮层上方，核对 rect、hit test，并完成一次按钮或键盘操作。** 固定区域在页面中途覆盖部分内容仍可能发生；用户可以滚动使目标进入可操作区域或主动关闭提示，不声称任意内容永不被覆盖。

三条长提示在短屏或字体放大后必须有受当前可用高度约束的栈上限，并允许栈内部滚动；测量的是受限后的实际占用。高度预算先扣可见导航/底部间隔、比较栏及间隔，并给正文至少留一个 44px 操作区域，不能把比较栏推到视口外。空比较栏不占预算。

单条文本也可能高于整个栈：保留完整文案和换行，不截断成不可读取内容；只保留一个栈滚动口，不再给每段文本叠第二个滚动容器。关闭按钮采用独立不收缩的 44px 列、顶部对齐，并在本条范围内相对栈滚动口保持 sticky，使滚读超长项时仍有可达关闭入口。后续真实组件检查必须验证 sticky 的实际 rect/hit test，而非只检查 CSS 声明。栈上限至少容纳一个含 padding 的完整关闭目标；若预算不够，不以挤压目标尺寸或遮住比较栏解决。

换行不能造成横向溢出，关闭目标的实际命中区域至少 44×44px。内部滚动不能困住 Tab 或吞掉栈外页面触摸；进入离屏关闭按钮时只做必要的局部可见性滚动，不强行把整页滚回顶部。

在支持的最小 320×420 视口中，toast 栈与比较栏仍须为关键正文操作留下至少一个 44px 高的可操作区域。若既定固定布局无法满足，记录失败几何并返回修订窄布局方案，不以负高度、重叠或“用户等到到期”判通过，也不在实施中临时改成全局浮层重构。

### 4.3 复用原生键盘状态

普通 Web 不新建 keyboardOpen 检测；正常响应 viewport/布局变化即可。原生 mobile 继续消费 `:root[data-keyboard-open="true"]`：导航隐藏后实际占用归 0，底部基础间隔沿用该状态的 12px 语义；不能继续使用 74px 导航偏移，也不能让旧 12px/76px padding 规则覆盖新动态 toast/比较栏余量。

不修改现有 140px 阈值、visualViewport 监听或 IME 判定。合成设置 flag 只能验证 CSS 分支和余量协调，不能证明真实 Android 键盘探测、安全区、输入光标可见性或旋转恢复。

## 5. 分步实施与停止条件

1. **确认冻结范围。** 只读重核上表实际入口和已有 dirty，记录本轮允许差异；在新批次建立后续验证输入，不借用 R127 的成功/失败输出作本轮结果。原候选与四个产品文件的 Root 快照见 `.artifacts/r128-toast-lifecycle-layout-20261023/before-manifest.json`；实施前须确认它们仍匹配。
2. **先补失败证据。** 新 QA 入口加载真实 ToastProvider 和真实 CSS，在受控时钟下重现 34px、暂停缺失、旧 timer 未清；组件夹具只负责造消息，不复制 Provider。浏览器 timer 包装仅用于观察资源，不能改产品的计时算法。
3. **完成生命周期。** 先保持 ShowToast 和三条上限，再做项级剩余计时、三原因交叠、失效回调与所有释放路径；检查 StrictMode 下无重复 timer/监听。完成后只跑目标组件场景，不扩全仓。
4. **接入动态布局。** 先让 Provider 测量 toast，再注册现有导航/比较栏；统一共享 CSS 与 mobile 两条 padding 覆盖，验证空态归零、实际换行和尺寸变化。不要改 Workbench 的业务 state 或 key。
5. **验证真实产品入口。** 用新的、绑定当前源码的生产 Web 构建和独立私槽，通过真实查询结果关注/取消关注等既有动作出现 toast；目标点击/键盘回归与输入保全必须在真实 Workbench 完成。合成 component fixture 不能替代此阶段。
6. **独审后记录结果。** 只有实际通过的检查才写入结果，保留失败批次；汇总输入稳定性、资源自然退出和当前仍未验证边界。设备检查单独留账，不把此候选升级为完整 V1 完成。

后续已知的窄静态入口是 `npm run typecheck --workspace @tire/web`。共享 TSX 改动还需按原有 native 项目的 typecheck 入口核两端消费合同；不默认全仓 tests 或三端完整原生打包。生产 build/QA 采用执行前已独审的项目宿主与新输出，不直接启动默认 API，也不直接用普通 `npm run build` 替代现有生成文件保护流程。以上命令与执行均未在编稿时运行。

## 6. 浏览器验收矩阵

| 场景 | 必须观察的结果 |
| --- | --- |
| 基础寿命、空文本、一条/三条 | 空 trim 不新增；无暂停约 4600ms 后只移除目标；最多三条；无自动聚焦、额外请求或横向溢出。受控时钟证明边界，真实时钟只作有限容差观察。 |
| hover 与 focus 单独暂停 | 在即将到期前进入，超过原截止仍存在；离开后仅剩余时间运行，不能重置寿命；触摸点击不遗留 hover。 |
| 三原因重叠、不同解除顺序 | hover→focus→hidden，再逐一解除；仍有任一原因就不倒计时。逆序与内部 focus 移动亦成立。隐藏中新提示保留完整寿命。 |
| 旧回调与清理竞态 | 临近到期暂停/关闭/挤出，再推进时钟；旧回调不删新项、不重复 dismiss。第四条立即释放最旧非持焦项 timer，Provider 卸载后 timer/监听/observer/布局任务为空。包含已排队但被 clear 的旧 timeout 代次验证。 |
| StrictMode 生命周期 | 显示项经历 setup→cleanup→setup 后仍有且仅有一个应运行 timer；paused 项仍为零。剩余时间不重置，第二 setup 能恢复，旧代次不执行业务移除。 |
| 关闭与焦点归属 | 每个关闭 rect/hit target 至少 44×44；键盘可达且无陷阱。第四条保护当前真实持焦项，淘汰最旧非持焦项，焦点不落 body；非真实焦点的旧标记不能无限保护。手动关闭仅在 activeElement 仍属本条时按相邻 close 或已连接原控件兜底，外部新焦点不被抢回。 |
| 动态尺寸和正文末尾 | 1365、390、320 宽；单条/三条、长中文和长 token、正常/放大字体、320×420。单条超过栈时能滚读全文且关闭仍可命中；比较栏不被推出视口。测实际高度变化、比较栏间隔、空态归零；滚到底使真实末尾操作完整可见且 hit test/点击或键盘成功。 |
| 有/无比较栏、有/无 toast、有/无导航 | 覆盖组合；三层不相互覆盖，专属空层间隔归零；toast 移除/字体换行后比较栏和正文同步回落，不残留大空白。 |
| 原生 keyboard flag 合成分支 | 在加载 mobile 样式的真实共享组件中显式切换现 flag，核导航 hidden→高度0、toast/比较栏/正文重测；恢复后导航实际高度归位。普通 Web 不应获得新的检测器或误用 native flag。 |
| 真实 Workbench 业务链路 | 复用现关注成功/取消关注成功/错误分支的实际 UI 入口，记录真实 HTTP 与请求数量；toast 生命周期/关闭/hover/focus/布局变化本身发起零业务请求，不允许为了 toast 放宽请求失败门。 |
| 输入、选择和视图状态保全 | 保留 size/model/region 等草稿与未提交价格输入 DOM、值、选区/焦点；比较项和查询选择保持。toast 显示、暂停、尺寸变化、关闭均不重挂 Workbench、不提交表单、不重跑查询。 |
| 主题与辅助操作 | 浅/深/高对比和 forced-colors 下关闭图标、文本、焦点可读，Root 实际看图；ARIA 无新增 modal/陷阱。DOM/截图不能宣称读屏播报已验证。 |

Page Visibility 原因需要实际 Page Visibility 事件/状态证据。若所用 headless 宿主无法把文档变为 hidden，受控组件场景只能标作合成状态验证，并将真实隐藏/恢复留为未验；不能单靠派发一个 visibilitychange 事件就宣称浏览器已隐藏。测试内部时钟或 native flag 的合成控制不得冒充真实后台调度和真实 IME。

后续浏览器批次应记录 source/build/input pins、截图及实际 rect、受控计时观察、请求门、异常和资源终态；使用新输出目录，失败不覆盖。沿用私槽、不启动正常 API、不打开正常/保留 SQLite；fixture 汇总关闭不等于逐数据库句柄关闭，浏览器组件通过不等于生产集成通过。

## 7. 合成验证、真实设备与风险

- 组件场景可证明真实 React 组件的可控计时、DOM、CSS 和清理逻辑；真实私槽 HTTP/生产构建可证明当前 Workbench 的实际入口及浏览器几何。两者均不证明真实供应商、Provider/model、正常数据库、原生 IPC 或完整 V1。
- 原生 keyboard flag 合成分支与浏览器 viewport 变化不能证明 Android WebView/桌面宿主的真实布局；真实触摸、安全区、系统字级、软键盘开合/旋转、后台暂停/恢复、VoiceOver/TalkBack/屏幕阅读器要有相应设备或辅助技术证据。本候选可分别报告浏览器通过与这些未验项。
- 固定提示和 live region 继续沿用现有层级/语义；原生 modal 顶层遮蔽提示、既有多 live region 可能重复播报等情况不自动扩为无障碍重构。若发现本改动新增不可达/重复播报，保留失败并修本候选引入的问题。
- observer 反馈循环、StrictMode 双执行、计时版本竞态、长提示占满短屏、陈旧焦点保护、原生 CSS specificity 覆盖是重点风险；分别用同值不写、纯 updater/可重入 setup、回调失效检查、栈上限/单滚动口与关闭列、真实焦点归属检查、原生分支实测控制。
- 动态 padding 增减可能影响滚动锚定。不得每次 toast 变化强行 scrollTo；验收输入焦点/选区及用户滚动保全，只有用户明确滚动/聚焦目标时才确保目标可达。

## 8. 窄回滚与本稿交付

实施前只归档本候选允许修改文件的原字节及其当前差异。需要回滚时只撤销本候选在 toast、Workbench 连接点、toast/底部 CSS、mobile 对应覆盖上的增量；若文件含他人 dirty，按差异逐段回退，不能整文件覆盖。新 QA 文件只移除本候选独占新增文件。先释放 timer、observer 和事件资源，再撤除其局部布局消费者，避免残留未消费变量。

不 reset/stash/clean，不改写 R127 任何历史回执、归档或 pin，不清空 storage、不恢复数据库、不回滚 SDK 204 修复。本轮允许的 live 源码增量不受这条历史保护语句禁止，必须另用本轮 pin 和新验证记账。回滚后重核原 ShowToast 接口、最多三条与原布局入口；失败/新批次证据保留，不删除来制造通过。

**候选起草阶段已做：** 复用 QA 窄审，只读相关入口，编写原候选。其原字节保留为 `.artifacts/r128-toast-lifecycle-layout-20261023/candidate-plan-v1.md`。

**Root 冻结阶段已做：** 归档四个产品文件原字节、确认新 QA 路径原先不存在、静审候选并修正文案歧义、写实上表布局公式；候选 QA 审阅与最终文本复核分别记账。

**尚未做：** 产品/工装修改、测试、类型检查、构建、服务、浏览器、数据库、设备或读屏验证；也未 commit/push。冻结不代表实现或验收，完整 V1 仍 active。
