# Query Range Selection Implementation Plan

> Execute in this chat using the existing implementation and independent review agents. Root owns formal tests, builds, browser verification and evidence/report application. 不创建 worktree，不 commit/push；保留既有 dirty 和其他代理修改。

**Goal:** 在查询结果增加原生 checkbox 与 Shift 连续范围选择，并将所选精确 ID 一次性、只追加地加入现有最多四项的比较。

**Architecture:** 用无 React 副作用的纯 helper 管理待选 ID、来源内 occurrence anchor、范围修改和比较追加；工作台按实际可见卡片的顺序调用同一合同。待选和已比较状态独立，批量操作在一次 functional `setCompared` 中以最新 previous 检查容量，不循环调用现有 toggle。查询卡片展示独立 checkbox，不改证据焦点、关注卡片、比较表、后端或 SDK。

**Tech Stack:** 现有 React 19 / Next 16、TypeScript、原生 checkbox / 键盘事件、CSS、Node 内置 test/assert；无新增依赖。

---

## 依据与已确认接入点

- 原上传原件与 `docs/requirements/2026-09-26-tire-intelligence-original.md` 的 SHA 为 `f8a2a4434d83824afe36d3e46730ee183e4506acc0c91041b8a122b36e6fc46d`。877 行只明确要求“Shift 多选”；连续范围和批量 add-only 是本轮实现设计，不伪称原文逐字段要求。
- 当前 Git HEAD 为 `4d0ef60fa2240146113a3fac172759c665cf339f`，不是 dirty 产品快照。Root 已建立 `.artifacts/r122-query-range-selection-20261022/before/manifest.json` 三文件原字节备份；后续按本轮 owned diff 及实际 pins 验证，不以 Git 总 diff 认定范围。
- `workbench.tsx:55` 的 `hasQueryData` 仅接受 live / live_verified_304 / local_snapshot；485–487 原位更新来源结果，648–659 的 `orderedRuns` 决定来源组顺序。743 直接按每来源 `variants.slice(0, visibleCounts[sourceId] || 20)` 渲染卡片，744 每次再展示 20 项，没有 VariantList 层。
- `VariantCard.selected` 在查询 743、关注 760 都按证据 snapshotId 判定；812–817 的 article 无整卡点击。这个 selected 和 `.variant-card.selected` 继续表示证据焦点，不能复用作待选态。
- `toggleCompare` 589–594 按精确 variant.id 先允许移除现有项，再拒绝新增第五项或 revoked。生命周期保存 616–623 更新各处 Variant，但保留 `compared` 中的 revoked 选择，仅从实际 comparison 移除；这些已有占位和主动移除行为不变。
- `variantActions` 626–635 的证据、候选证据、关注、核验、AI、车库、版本动作保留；查询传 sourceId，关注不传。候选、隔离、独立设备离线记录不能通过多选绕过已有比较门，仍只从当前 hasQueryData 查询卡片取对象。

## 冻结交互与数据合同

### 选择状态和可见顺序

1. pending 只保存唯一精确 variant ID；reconcile / toggle 后按当前可见 eligible IDs 的视觉顺序规范化并去重。anchor 保存来源与该卡片 occurrence 的 key。不得把旧 `Variant[]` 存为待选状态，也不得按型号/尺寸/产品代码推身份或合并不同 ID。
2. 构造 `visibleRows`：按 **orderedRuns → hasQueryData → 每来源已展开的 slice** 展平，与实际查询 JSX 渲染使用同一份派生行，不按来源响应到达时间、全部隐藏结果或 DOM 文本重建顺序。
3. 冻结 `QuerySelectionRow = {rowKey:string; variant:Variant}`，UI 的 rowKey 使用 `JSON.stringify([source.id, variant.id])`，同 ID 在不同来源有独立 occurrence；如同来源同 ID 重复，可由两 worker 统一追加该 ID 在本来源的 occurrence 计数，仍用结构化编码，不用简单 index 拼 ID。pending 按 ID 去重，anchor 按 rowKey 定位。只允许当前正常查询可见记录；同一精确 ID 任一可见 occurrence 为 revoked 时，该 ID 全体 fail closed，所有对应 checkbox 禁用且不呈现为已选。
4. 维护 helper 的 orderKey，只含 rows 顺序和 eligibility 结构信息。发生顺序、可见集合或 eligibility 变化时：pending 与当前可见 eligible IDs 求交，anchor 废弃。展开新 20 项和更换排序均清 anchor，仍可见且可选的 ID 继续选中；排序操作即使结果顺序碰巧相同也由 UI 显式废弃 anchor。只改参数对象但顺序和 eligibility 未变不清选择。
5. 当前渲染/handler 必须使用 reconcile 后的有效状态，不能等 effect 才屏蔽旧 anchor/已撤销 ID；如用 effect 回写压缩 state，它仅同步结构变化，不因每次生成新数组而循环。不得从 query 草稿 size/model/filterDrafts 等字段派生选择 context。
6. `runQuery` 真正开始新 generation 时立即清 pending/anchor，已有 compared 保留；同条件重新在线查询也一样。车型尺寸预填会清 runs（现 680–683），相应清待选；仅编辑未提交草稿不清待选，不改已提交查询或其授权。

### 普通 / Shift checkbox

| 操作 | 结果 |
|---|---|
| 普通 toggle | 仅将本 ID 设为目标 checked；本 occurrence 成为 anchor |
| 有效 anchor + Shift | 将 anchor 至终点的 inclusive **可见行**内 eligible ID 设为终点目标 checked；跳过 revoked，ID 去重；保留区间外选择和原 anchor |
| 无 anchor / anchor 失效 + Shift | 退化为单项 toggle，并以终点建立 anchor |
| 取消选择范围 | 目标 checked=false，移除范围内 eligible IDs，区间外不变；不是反转每一项 |
| 清空待选 | pending=[]、anchor=null；不清 compared |

反向范围同样生效。重复 ID 的 eligible occurrence 共享一个 pending membership，不能重复计数/追加；具体范围仍按 occurrence 位置。已在 compared 中的 eligible ID 允许选中，但不占新增名额。

checkbox 事件只作用于查询卡片本地：按本次原生目标 checked 和 Shift 修饰状态产生一次状态转换。保留原生 Tab / Space / Shift+Space 行为；必要时用 checkbox 本地 ref 传递修饰状态并在消费/失焦时清理，禁止全局 Shift 监听、整卡点击选择或同时在 click/change/keydown 重复 toggle。证据、候选字段证据、比较、关注等按钮及其键盘操作不能改变 pending。

### 一次批量只追加

- 点击时从当前 `visibleRows` 解析 pending IDs 对应的 eligible Variant；同一 ID 取当前可见顺序中的首个 eligible occurrence。旧选中对象不能绕过新的可见/撤销状态。
- 一次 `setCompared(previous => { const result = planComparisonAddition(previous, pendingIds, visibleRows); return result.ok ? result.compared : previous; })`；helper 只读参数、返回结果，不改变参数。不得循环 toggle，不在 updater 内 setState/toast、访问 DOM、生成随机值或写副作用。
- 保留 previous 现有对象、顺序和精确 ID，新追加部分按当前可见 eligible IDs 的视觉顺序排列。pending 中已存在于 previous 的 ID 不移除、不替换、不占新名额。现有 revoked 项继续占四项容量，沿用原移除按钮处理。
- `missingIds` 去重后，若 `previous.length + missingIds.length > 4`，整批拒绝并返回原 previous；不截断、不选部分、不替换已有项。handler 与 helper 都检查容量，不能只依赖 disabled。
- helper 对空选择、未知/不可见 ID、不可选 ID 也明确整批拒绝；正常 UI 先 reconcile，但操作边界仍须复查，不能把失效 ID 静默吞掉后部分追加。
- 成功后保留 pending，由当前 compared 派生“所选均已在比较中”。不需要在 updater 外猜测提交结果或通过嵌套 setState 发成功提示。
- UI status 直接从有效 pending、当前 rows 与 compared 派生：已选唯一 ID 数、其中已在比较数量、待加入数量、四项剩余容量，以及明确超额原因。超额禁用 bulk；无待加入也禁用并解释。状态紧邻按钮且可见，可用 `role="status"` / `aria-live="polite"`；错误不只靠 toast/颜色。

## 任务与 ownership

所有执行者都不是独自在代码库工作。各自只写约定文件，不回退其他代理的 dirty；共享文件先协调。plan agent 仅写本文。实现按下列接口协作，Root 独占正式验证与报告。

### Task 1：纯选择 / 追加 helper 与定向用例

Owner：values/test worker。

- Create: `apps/web/components/query-selection-values.ts`。
- Create: `apps/web/tests/query-selection.mts`、`apps/web/tests/tsconfig.query-selection.json`。
- Read: `apps/web/components/workbench.tsx` 的 Variant、现比较容量/生命周期入口，`apps/web/tests/route-hash.test.ts` 的 Node test/assert 惯例。

1. 两 worker 使用 Root 已接受的精确 exports：`QuerySelectionRow {rowKey:string;variant:Variant}`、`QuerySelection {ids:string[];anchor:string|null;orderKey:string}`；纯 `querySelectionOrderKey(rows)`、`querySelectionEligibleIds(rows)`、`reconcileQuerySelection(selection,rows)`、`toggleQuerySelection(selection,rows,rowKey,checked,shiftKey=false)`、`clearQuerySelection(rows)`、`planComparisonAddition(previous,selectedIds,rows)`。不另建第二套算法。
2. reconcile 按精确 IDs / rowKey / orderKey 做 prune、视觉顺序规范化与 anchor 失效；无变化返回原 selection 引用以避免 UI 同步 effect 循环。toggle 在 reconcile 后执行上表的单项/范围动作，再规范化。没有有效终点、终点不可选或失效上下文时不能扩大选择；同 ID 任一 revoked 全体 fail closed。
3. `planComparisonAddition` 返回 `{ok:true;compared:Variant[];addedIds:string[]}` 或 `{ok:false;reason:'empty_selection'|'unknown_selection'|'ineligible_selection'|'capacity_exceeded';rejectedIds:string[]}`；由最新 previous 再计算。不导入 React，不读取外部 mutable 状态。UI 基于有效 IDs、eligible IDs 和 compared 派生 selectedCount / alreadyComparedCount / addCount / remaining / overflow，不要求新增 summary export。
4. 写独立例子断言：正常单选/取消、顺向/反向 inclusive range、无 anchor、保留区间外、Shift 取消是赋 false 而非反转、Shift 保留原 anchor、跨来源、重复 ID/occurrence、revoked 跳过及变更 prune、展开/排序清 anchor、仍可见 ID 保留、无效端点与旧 context。
5. 写追加断言：已有比较项原对象/顺序保留，新项按当前视觉顺序；反向操作后的 pending 仍按视觉顺序规范化；相同 ID 不移除替换；重复 pending 只加一次；current rows 对象生效而非旧对象；空/未知/不可见/撤销选择整批拒绝；满四项/已有 revoked 占位/超剩余容量整批原样拒绝；成功至四项；连续调用幂等；所有输入不被 mutate；reconcile 无变化保留引用。
6. tsconfig 继承根 `../../../tsconfig.json`，开启 Node types、allowImportingTsExtensions、incremental=false，include 仅该 `.mts`；采用可被现 Node strip-types 执行的 TypeScript。仅准备测试，不运行，不新增测试执行框架或修改 package scripts。

### Task 2：工作台接线与局部 CSS

Owner：UI worker。

- Modify: `apps/web/components/workbench.tsx`、`apps/web/app/globals.css`。
- Read first: `apps/web/AGENTS.md` 与实际安装的相关 Next 指南；例如 `node_modules/next/dist/docs/01-app/01-getting-started/03-layouts-and-pages.md`。

1. 引入 helper，新增独立 query selection state。在 orderedRuns 后派生 rows/context；将查询卡片渲染改为消费这同一份行，保留来源组结构、每组分页、所有现有说明和证据回调。
2. 查询调用给 `VariantCard` 增加可选 query checkbox slot/props，关注调用不传就不渲染。不要改 selected 的证据含义、现 article 选中样式、关注行为或单个比较按钮的 toggle 规则。
3. 原生 checkbox 提供可见“选择此规格”文案，accessible name 含来源和可辨认的精确 ID/型号；同 ID 关联状态由 helper 决定。用独立 CSS class 表示 pending，明确与证据焦点/已比较状态不同。
4. 接本地 Shift / checked 动作，覆盖 pointer、Space 和 Shift+Space；保持纯转换，只设置待选 state，不触发 evidence、compare 或 watch。清空按钮只清 pending/anchor。
5. 在查询结果工具区邻近插入状态和“将所选加入比较”按钮，展示 selected/add/remaining、超额与均已加入说明；一次 functional setCompared 调用 pure append，保留原 comparison-tray 导航。不要在 updater 内 toast/setState；成功后 pending 保留。
6. `runQuery` 新 generation 开始时清 selection；排序/展开和生命周期变更按 context reconcile，车型预填清 runs 时同步清。草稿输入回调不清 selection，不改现查询 generation、授权或 fallback 合同。
7. CSS 仅作用于查询 checkbox/选择工具条及其状态；320/390px 可换行、控件可触达、无页面横向溢出，长 ID 可读/换行。禁止通用 article 全卡 click 或覆盖比较表/关注卡片布局。
8. 完成后 STOP，向 Root 报 owned 文件、helper 合同、需验证情形及原生键盘事件选择；不自行运行测试/构建/browser。

### Task 3：Root 定向验证、真实工作台验收和报告

Owner：Root；独立 reviewer 仅只读审完整冻结实现。后端/SDK 没有产品变更，不跑 API 全套或 SDK 全套。

1. Root 绑定最终 helper/UI/test/CSS 与受限验证输入，保留 before 原字节和所有失败回执。仅使用新 UUID 私槽和合成记录，不打开正常或保留 SQLite，不调用 Provider/外部来源。
2. 正式定向 payload：`tsc -p apps/web/tests/tsconfig.query-selection.json`、`node --test --experimental-strip-types apps/web/tests/query-selection.mts`。由 Root 沿现已审受限入口执行并记录类型/断言结果，不由 worker 执行；不把 helper 测试当作原生事件或真实 UI 证明。
3. 按实际影响运行必要的 Web typecheck；复用当前受审 Web build helper 开全新 batch 构建，不重跑后端175模块，不引入通用 wrapper/调度框架。对 before 差异确认 R120 comparison 和 R121 pricing 没有被改写。
4. Root 准备本轮独立的受限 synthetic query HTTP fixture，复用既有 FilterRegistry 接口、真实 create_app/查询工作台、新私库、NoNetwork、Provider disabled；旧历史 fixture/helper 原字节不改。fixture 通过正常查询返回至少两个来源、首组超过20条、重复精确ID、不同ID但同型号、可撤销记录和可核对的合成证据。任何仅为 QA 合成的生命周期/来源设置都在回执明确。
5. 使用真实生产 Web / HTTP / React 与 headless 浏览器验证同一新批：跨来源范围、20项可见边界和再展开、排序清anchor、重复ID去重、反向范围、无anchor、取消范围保留区间外、原生Tab/Space/Shift+Space；不能只 dispatch 合成 change 来证明键盘。
6. 验容量与 add-only：先比较现有项，再选包含已有ID的范围；不移除/替换已有项、不多占容量；超剩余容量时有可见解释、disabled且完整状态不变；helper负例补充 handler不能只靠disabled。四项限制及 existing revoked 占位行为不变。
7. 验时序/边界：生命周期撤销后 pending prune 且anchor失效；新查询/同条件重查清pending而compared保留；修改未提交草稿保持pending；证据/候选证据/关注/版本/单项比较动作不误选；关注页没有query checkbox。候选/隔离/设备离线记录不能借多选进入比较。
8. 实际查看390/320px截图，记录长ID、按钮、状态和无整体横向溢出，检查 console/page errors及非预期请求；真实Shift pointer/键盘结果与helper各自记账。记录owned API/Web/browser父子进程自然终态、BrowserServer关闭、端口关闭及源首尾稳定，不能从构建通过推UI通过。
9. 独审发现可触发缺陷后由 owner 修复，Root仅重跑受影响检查；正式报告区分已修改/已验证/延后，既有失败批不能拼绿，HANDOFF旧尾文原字节保留，完整V1继续active。

## 验收标准、边界和回滚

- 查询checkbox对当前真实可见顺序执行准确的Shift目标状态区间修改；pending为去重精确IDs，revoked不可选，排序/展开/失效anchor不扩散到错误区间。
- bulk为一次原子add-only，已有比较对象/顺序不变，最多四项，超过剩余容量不部分加入；derived status解释实际数量、超额和均已加入状态。
- 新查询清待选但保留已比较，未提交草稿不清；证据selected、关注页、单项compare toggle及旧撤销处理继续按原合同运行。
- 本文阶段只读核对并写计划，**未运行测试、构建、服务、SQL或浏览器**。后续合成HTTP/UI即使通过，也不证明真实厂商、真实专业SKU、Provider、正常库升级、PostgreSQL、PWA离线、原生设备、完整无障碍或完整V1验收。
- 回滚只恢复本轮 owned helper/UI/CSS/test 的原字节或已审差异，保留其他dirty、before和失败证据；无需迁移或服务器数据回写，不使用reset/stash/clean。新私槽按既有关闭/保全流程处理，不回写正常或保留数据库。
