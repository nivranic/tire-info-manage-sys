# R128：Toast 生命周期与底部布局验收

2026-10-23。**本轮通过，完整 V1 仍 active。** 提示现在按剩余时间恢复，阅读或交互时暂停；窄屏正文末尾的关键操作可以滚到浮层上方并操作。生产构建、组件和真实 Workbench 私槽 HTTP 验收分别记录，不能互相替代。

## 已实施范围

沿用[冻结计划](../../plans/2026-10-23-toast-lifecycle-layout.md)、唯一 ToastProvider 和原有 `useToast(): ShowToast` 入口。计划中的“尚未实施”是冻结时点记录，最终状态以本报告为准。

- 保留 4600ms 寿命、trim、消息种类和三条上限。hover、focus-within、document-hidden 可交叠暂停，最后一个原因解除才按剩余时间恢复。新增第四条保护真实持焦项，淘汰最旧的非持焦项。
- 到期、关闭、淘汰和卸载清理 timer；Provider 清理 listener、observer 和布局任务。StrictMode 重建保留正确剩余时间，过时代次不能误删新项。
- 关闭目标至少 44×44px；主动关闭持焦提示时，按存活相邻提示、原外部控件、稳定 main 兜底回焦。提示出现和自动消失不抢焦点。
- 实测导航、提示栈、比较栏高度，共享正文底部余量。短屏限制提示栈高度并保留单一内部滚动；长文关闭按钮 sticky。mobile 复用既有 keyboard flag，不增加键盘检测器。

产品只修改以下四文件；后端、SDK、数据库、依赖和原生宿主合同未纳入本轮：

| 文件（仓库相对路径） | 字节 | SHA-256 |
| --- | ---: | --- |
| `apps/web/components/toast.tsx` | 13773 | `4adda231ab5c4cdf11437194b88ecdcf157c2a20da54e306ed3c0d77f5e3f1ce` |
| `apps/web/components/workbench.tsx` | 117740 | `4113c33f3fae34cbbce41a02b9a2d59ca2143cb4e72400ed099a2d2f0efcf7ad` |
| `apps/web/app/globals.css` | 145116 | `cc1ff20fee6e0fa2ee6154e31c4f6fe0bfcc56b1d3c9d88fa771fb51c36a34a3` |
| `apps/mobile/src/styles.css` | 6937 | `82bd1082bca7168baa4d17d5784b1d1891774be707659029b7254eee257aa1ed` |

**布局合同保证正文末尾关键操作可滚达、可见、可操作；不保证任意滚动位置的正文或输入永不被 fixed 浮层覆盖。** 本轮实测视口为 1365×900、390×844、320×844、320×420。

## 实际验证与证据

以下链接均指向本仓库留存文件。生产页面的 193 是检查记录数量，不是 193 个独立测试；输入指纹和清理次数也不是测试数量。

| 验证层 | 实际结果 | 原始回执 |
| --- | --- | --- |
| 独立产品审查 | ACCEPT，限定四产品文件 | [产品审查](../../../.artifacts/r128-toast-lifecycle-layout-20261023/product-review.json) |
| 三端类型检查 | Web、desktop、mobile 的 `tsc --pretty false --noEmit --incremental false -p <项目 tsconfig>` 实际全部 exit0，所选输入未变 | [typecheck-root.json](../../../.artifacts/r128-toast-lifecycle-layout-20261023/typecheck-root.json) |
| 组件最终 e5 | 17 组通过；37 次 teardown 全 released；217 输入稳定；请求、页面、console、清理错误数组为空 | [prepare](../../../.artifacts/toast-component-qa-r128-live-e5/prepare.json)、[result](../../../.artifacts/toast-component-qa-r128-live-e5/result.json) |
| 生产构建 b128 | icons、Next、PWA 三阶段 supervisor exit0，源码/依赖稳定，生成原件恢复 | [freeze](../../../.artifacts/r118-material-workbench-20261021/web-build-b128d4e5f6071829/freeze.json)、[verification](../../../.artifacts/r118-material-workbench-20261021/web-build-b128d4e5f6071829/verification.json) |
| 生产 Workbench 最终 c128 | 同批 9 场景、193 条检查记录；9295 输入稳定；24 个 UI 请求窗口零业务请求 | [浏览器结果](../../../.artifacts/r128browser-c1280718293a4b5c/result.json) |
| Root 视觉核对 | 实际逐张查看最终组件 9 图、生产页面 10 图，未发现新增确认的视觉缺陷 | [组件看图](../../../.artifacts/r128-toast-lifecycle-layout-20261023/root-component-visual-review.json)、[完整观察绑定](../../../.artifacts/r128-toast-lifecycle-layout-20261023/root-observations.json) |
| Root 终核 | 实际 exit0 / passed，验证回执、当前输入、同批/同构建绑定、生成原件及资源观测 | [terminal-verification.json](../../../.artifacts/r128-toast-lifecycle-layout-20261023/terminal-verification.json) |

组件覆盖计时边界、三原因暂停、持焦保护、相邻回焦、过期回调、StrictMode、20 种布局组合、14/22px 长文、sticky 关闭、四视口及显示配色。visibility、受控时钟、native keyboard flag 为明确的合成控制。flag 开启/恢复分别经两个实际几何样本达到稳定，约 75/74ms 真实时间、64ms 虚拟时间；这不证明真实 IME、后台冻结或系统 safe-area。

生产 c128 使用当前 b128 构建及新私槽。两次实际查询得到 live 数据，分别 26/3 行；关注共六次 POST，其中五次真实 201，一次由浏览器 route 精确注入 503，解除后实际 201 成功。取消关注实际 DELETE 204。注入没有派发至后端；对应唯一 console 事件单列，不冒充后端故障。其他 HTTP≥400、requestfailed、页面、console、来源越界、覆盖与清理异常均为空。

四视口均将真实正文尾部 44px 比较按钮滚到浮层上方，检查 rect、hit test 并按 Enter 成功。查询节点、值、选区、焦点、比较选择及来源页未提交价格表单保持；菜单三种入口、七项动作及 Escape 回焦定向回归通过。输入保全基线在响应 held、输入已可见且滚动稳定时建立，响应释放后不滚动或重写基线。价格表单位于有意导航后的来源页，**不宣称跨视图保留 query DOM**，也不宣称所有任意滚动位置均不变。

组件 Chromium PID 50900、生产 Chromium PID 51984 均自然 exit0 / signal null / server close。[宿主](../../../.artifacts/r128uihost-c1280718293a4b5c/receipt.json)三个 supervisor 自然 0/0/0，forced 为空；[Web 服务](../../../.artifacts/r118-material-workbench-20261021/web-service-c1280718293a4b5c/service.json)Node 143，Job 2/2、active 为空；[fixture](../../../.artifacts/r128fixture-c1280718293a4b5c/stopped.json)shutdown_complete，外网、子进程、正常数据库尝试均 0。Root 实际查询的 36 个相关 PID 全不存在且无查询错误，18986/18987 各 5 秒上限的连接探针返回 10061。汇总关闭不证明逐 DBAPI 句柄 close 或私库删除；Job 和代码 guard 不是 OS sandbox。

### 关键回执指纹

| 回执 | 字节 | SHA-256 |
| --- | ---: | --- |
| 组件 e5 result | 240537 | `5426722f23aa1a9f468a7995b50175b88424bb54b9c1a602aa8c743326d44d25` |
| 构建 b128 verification | 131252 | `ee5a89c24f945e954d3c49421a43c18a93d8bfff1a0ac5ebb9a0383f5b5a2009` |
| 生产 c128 result | 2299551 | `40c4f1c5bcd8b6f228880e5251a4d4d7de178cf47d73f5a5c31673582f561e74` |
| 宿主 c128 receipt | 7874 | `d299bb729247cf6abee64a9fe49804725a8a6da0920e6a4ec8876c9998d314f5` |
| Root observations | 9190 | `06c585850721f78a07f741826cfaaa5bd866310f40b2710ebb911dbc3853b9b8` |
| Root terminal-verification | 6047 | `bd3dc60d25e5c5fac634557794b1bc159c953543b5c1e1c604a5c8e82ee3f37d` |

组件 QA 为 `scripts/toast_lifecycle_ui_qa.mjs`，75511 B / SHA `3b4f3e8e3d4222b7679e9a09ac7e163d437c752f75c69e9b344a15a02f339f3d`；生产 QA 为 `scripts/toast_workbench_ui_qa.mjs`，58364 B / SHA `61abbda8e08bc1fd5da69903df59b6790bb509b785b5cb043f0ca50c8be415e3`。薄宿主 [run-ui-host.py](../../../.artifacts/r128-toast-lifecycle-layout-20261023/run-ui-host.py)锁定旧 R127 宿主原字节，只作四处精确内存替换，复用已有守护、fixture 和 Web 服务。

最终工装调整分别经[恢复静审](../../../.artifacts/r128-toast-lifecycle-layout-20261023/static-review-resume.json)、[输入滚动基线静审](../../../.artifacts/r128-toast-lifecycle-layout-20261023/static-review-scroll-baseline.json)和[终核工具静审](../../../.artifacts/r128-toast-lifecycle-layout-20261023/terminal-tool-review.json)接受。静审不代替 Root 的运行、端口/PID 观测或看图；终核工具只读并比对这些独立证据。文档独审另存为本轮新回执，不改旧批状态。

## 失败历史与修正

以下失败均保留。最终 e5/c128 通过只证明各自绑定的当前输入，不能把历史失败拼成单批通过。

| 历史批次/问题 | 处理与保留边界 |
| --- | --- |
| 原产品 baseline-c3 | [result](../../../.artifacts/toast-component-qa-r128-baseline-c3/result.json)保持 failed：复现 34px 关闭、无暂停、挤出旧 timer 未清三缺陷；清理结束后在 `archived_baseline_is_not_live_acceptance` 主动失败。对应原 QA 为本轮归档的 `pre-instant-scroll-qa.mjs`，不用当前 QA 指纹重核旧历史。 |
| 组件 a1 prepare | 归档 Provider 可选 hook 与 data URI 中文编码问题；改可选入口读取、UTF-8 base64，并保留七标签精确断言。 |
| 组件 b2 | Playwright main-world 懒初始化 MutationObserver 被计入产品资源；查明调用链后在 instrumentation 前 bootstrap，同 world barrier，未放宽零清理要求。见[分析](../../../.artifacts/r128-toast-lifecycle-layout-20261023/component-b2-observer-analysis.json)。 |
| 组件 live-c3 | QA `scrollTop` 仍受页面 smooth 行为影响，观察发生在滚动未完成时；改明确 instant 滚动并等待默认入场动画结束，未改产品 CSS 或放宽门。 |
| 组件 live-d4 | 旧等待不足以保证原生 ResizeObserver 与虚拟 rAF 收敛；增加有限真实 yield 与虚拟 frame，两次几何及 pending-frame 达稳后继续；live-e5 完整通过，不将调度假设写成唯一根因。 |
| 构建 a128 | 普通沙箱下 mkdir `_not-found` 报 EPERM；保留失败，新 b128 经自动批准提权后原工装成功。未认定唯一根因，未把 a128 回填成功。 |
| UI a128 | 两个 HTTP200 后 toolbar 未出现，旧批未保存 data_state；fixture 另见 `CaptureWriteError → ObjectStoreError → PermissionError winerror5`，不能由此确证具体 body 或唯一根因。QA 加 data_state/行数硬门。旧 host/Web 回执仍 running、exec 句柄中断，不能声称自然成功；[独立恢复观察](../../../.artifacts/r128-toast-lifecycle-layout-20261023/a128-interrupted-host-recovery.json)仅记录七 PID 缺席与端口拒绝，不改旧回执。 |
| UI b128 | live 查询已成功；旧 QA 未建立滚动稳定前置条件，记录 2323→1371，节点/值/焦点/选区仍保持。该批保持 failed，清理正常。c128 在 held response 释放前以 instant 滚动、两个真实样本建立稳定基线，释放后保持原判定门并完整通过。旧观察不构成唯一因果归因。 |

旧 QA 原字节均保留在本轮 artifact 目录。当前四产品文件在这些 QA 修正期间未再修改；因此没有为 QA 改动重复生产构建。已过检查无需无条件重跑。

## 未验证边界与续作

本轮为 headless Chromium、项目自有合成身份/材料/私槽。真实来源、Provider、模型、embedding 调用均为 0。生产浏览器 SW blocked，匹配 public 资源由 page route 交付；生成 PWA 产物不证明当前构建离线或安装态。R126 的真实 SW 离线证据仍只适用于当时 b124 构建。

真实原生宿主/设备、IME、物理安全区、后台调度、读屏和完整 WCAG 尚未验收。专业 SKU/真人 Golden、真实 Responses/Provider、正常库升级、PostgreSQL 及完整 V1 仍有工作。用户已说明无 EPREL Key，继续独立工作，不再追问凭据。

下一步先窄审“全部来源失败时总栏仍显示等待在线结果”的已知线索，确认代码分支和产品要求后再定修改范围；hover 预览也留在后续需求。R128 未扩入这些候选。正常/保留 SQLite 未打开，默认 API 未启动，其他 dirty 保留，未 commit/push/reset/stash/clean。

旧交接全文已备份为 [handoff-before-r128.md](../../../.artifacts/r128-toast-lifecycle-layout-20261023/handoff-before-r128.md)，171411 B / SHA `6daf87c62bf9fe8d35dfb5185c6a3c01de4e47cd80d6b70281377a2601bb7b3f`；HANDOFF 仅前置本轮摘要，保留该原字节尾文。
