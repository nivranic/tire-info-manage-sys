# R133 关注账户生命周期与原生用户名校验修复

2026-10-25。**本项修复与限定生产验收已完成：最终 c133 构建通过，f133 页面同批 4 场景/46 条检查、13 个原生 pattern 校验值通过，Root 实际查看三图并完成45项收尾检查。完整 V1 仍进行中。** 46 是检查记录数，13 个原生值包含在一条检查内；历史失败原件全部保留。

## 需求与已修改

原关注状态由初载、关注视图、账户变化和增删回调竞争写入；只比较 user.id 不能识别同 ID 重验或 A→B→A。旧账户迟到的 GET、POST、DELETE、错误、toast 和 finally 可影响当前账户。

Workbench 现实际消费局部 `use-owned-watch.ts`，复用既有 AuthProvider 的 ownerEpoch、ownerSignal、isCurrentOwner。账户操作开始即同步撤销旧 runtime，清空旧关注、变更、错误和 pending；渲染与回调继续校验归属。身份未确认或首读未就绪时禁止关注写入，卡片和菜单给出准确原因，不把账户未知称为正在写入。统一读取入口随 owner、视图和重读版本工作，离开或卸载取消读取；来源初载仍保留。

每个变体写操作拥有独立 controller 与锁；旧 finally 无权解除新 owner 的同变体锁。写入开始撤销旧 GET 并推进 revision，最后一个当前操作结束再重读，防止同 epoch 的旧快照抹去已完成写入。SDK watch/unwatch 增加兼容的可选 signal，保留 DELETE 204 body completion，不重试副作用请求。

取消关注确认保存发起时的 epoch 和原 onWatch 回调，仅当前 epoch 显示、执行；账户 epoch 变化同步关闭规格菜单。查询草稿、结果和比较选择保留，菜单确认、预览及人工身份/生命周期核验对当前关注项的更新保留。后端 session_scope、同 cookie 继承及同账户多 session 聚合合同未改。

e 批另确证账户 HTML pattern 的真实缺陷：旧 `[A-Za-z0-9_-]{3,32}` 在 Chromium v 模式中无效。只将 `account-dialog.tsx` 共用常量中的连字符转义，JS 源码保留双反斜线；允许字符、长度和后端规则不变。189 字节固定诊断文案与 e 批实际 SHA 完全匹配，证据见 `native-pattern-console-e-match.json`；此匹配不追认 d 批。

## 已验证及证据层级

- SDK 目标类型检查通过；signal/兼容调用/取消不重试共 4/4，原有 204 完成边界 4/4。见 `worker-checks.json`。这些是注入传输及真实 Response 检查。
- 真实 React StrictMode、AuthProvider 和实际 hook 组件路径通过 9 场景、100 断言，18 个已取消合成响应实际晚交付。覆盖同 ID、A→B→A、未 ready、登出失败重验、旧写成功/错误/finally、同变体新锁、GET/写排序及卸载取消。见 `component-qa-prepare-v2/result.json`。账号、传输响应均为内存合成，无 HTTP 服务或数据库，不算真实后端账户验收；也不替代后增 Card/pattern 的最终生产验证。
- pattern 修复后 Web、desktop、mobile 各实际执行一次 `tsc --noEmit --incremental false`，全部 exit 0。每次前后 Workbench、hook、Auth、SDK、AccountDialog 五产品 pin 精确一致，完整命令、时间与哈希见 `typecheck-*-pattern-final.json`、`worker-checks-pattern-final.json`。
- 产品、Card epoch 和 pattern 差量均有独立静审 ACCEPT；静审不等于运行验收。

## 构建与五个保留红批

首次 a133 构建在 icon.svg 相关目录遇原生 mkdir/EPERM，根因未确证，失败原件保留。b133 构建通过，但对应 pattern 修复前版本，不能覆盖当前产品。**最终 c133 构建通过**：`web-build-c1330a1b2c3d4e5f`，三阶段均 exit0，180 个源记录及8983个依赖记录稳定，生成原件精确恢复、mismatches为空。Next Job 25/25 全观察、active为空、natural_resources_closed=true。冻结 SHA `e35a1d67e376bbce1aa255d70beccde5325d2b5d0208bef7b0e53bb9e00f88cc`；verification 127936 B/SHA `621e3823d21bffa3d76814c3986a35f19f24416aad0173e9b7c93afc562fd406`。host_build.web 固定列表不含 AccountDialog，因此其值未变；完整 freeze.sources 正确绑定新文件，不能将该辅助指纹冒充完整源码指纹。

| UI 批次 | 实际停止原因与界限 |
|---|---|
| a133 | seed HTTP 200，但原文对象写入链报 CaptureWriteError→ObjectStoreError→原生 PermissionError，未获得预期规格。原日志不足以定位具体文件原语。不是 region 或分页问题。 |
| b133 | 把首屏按来源分页的 23 张卡误断言为全部 29 张，QA 漏操作分页。 |
| c133 | 分页按钮 exact 名称漏掉“· 余 6 项”，在展开结果处等待超时。 |
| d133 | 四个业务场景、44 条检查通过，控制台严格门失败；仅留泛化标记，具体原因未知，不能借 e 批追认。 |
| e133 | 四个业务场景、44 条检查通过，但唯一 189 字节控制台错误经摘要精确匹配，证实原生 HTML pattern 异常；整批仍 failed。 |

a 批之后的全新私槽纯存储探针，在默认执行上下文精确观察到 `FileObjectStore.put` 的 os.link 被拒；require_escalated 的另一新槽 put/get 通过，父目录 SDDL 相同，未改 ACL 或 guard。见 `object-store-capability-comparison.json`。这证明该次上下文能力差异，不能倒推 a 批具体失败原语，也不修复或复用旧槽。

五批红色结果和 QA 原件均保留。Root 每批均留下 35 个指定 PID 缺席及 18986/18987 双端口关闭记录，见 first 至 fifth `ui-resource-observations.json`。资源观察通过不改变业务失败状态，也不证明逐个数据库句柄已关闭或私库已删除。

## 最终生产、视觉与资源结果

**最终 f13360718293a4b5 同批 passed**。使用修复后的 c133 生产构建及全新私库，4场景/46条检查，9300项输入与准备运行时稳定。9300项稳定来自QA前后记录，Root没有重新扫描全部输入。13个原生校验值通过实际登录输入的 pattern 克隆验证，覆盖连字符/下划线/大小写数字、3/32长度边界、过短/过长/空值及非法字符。所有控制台错误严格阻断，无取消例外，最终 console_events、page/console/HTTP状态/外源/cleanup错误均空。

页面实际66个请求（含静态资源），APIRequestContext另有12次初始化/核对调用。页面退出、登录、关注POST、取消DELETE各1次；合成来源fetch共3次（种子1+UI两来源），实际返回26/3行并展开到29张卡。真实外部来源、Provider、model、embedding均0；正常库/外连/子进程attempt计数均0。账户、session和关注增删来自新私库与真实业务路由，轮胎记录为项目合成来源。

A的另一会话持有A关注，主会话不持有它，防止同cookie继承混淆；切换B后保持B记录，A另一会话仍在。一个旧A GET已取得真实HTTP200 body，浏览器实际撤销该请求；解除route后不回退B。route.fulfill返回不证明React收到了撤销后的body，忽略AbortSignal的18次晚交付由独立组件矩阵证明。同B重新确认身份期间关注写入口disabled，恢复后原取消确认不复用；查询草稿、29张结果和比较选择保留。

**Root实际看完三张最终图**：1365×900及390×844的关注图显示1项B关注、产品代码R122-A-002及对应书签/更多操作；390px查询图保留查询卡片与比较栏。账户未确认的禁用及旧确认消失由同批DOM检查证明，截图没有展示悬停理由。长卡片需滚动，底部比较栏和提示覆盖截图下方部分正文；本项未承诺任意位置全部正文无遮挡，也未验完整WCAG/读屏/设备/PWA离线。

最终host三个子进程exit0、forced空；Chromium自然0/null、server-close返回；Web Node退出143，Job2/2、全观察、active为空、受控关闭通过。fixture shutdown_complete=true。Root实际查询34个指定PID均缺席、查询错误空，18986/18987各5秒上限探针均10061。所有本轮执行已结束；汇总关闭不等于逐DBAPI句柄close或私库删除证明。五个红批各35PID/双端口终态另存。Python guard和Job不是OS sandbox；最终UI受限宿主由工具require_escalated执行，未改ACL/guard。

Root单次执行closeout.py实际exit0/45项检查通过，root-closeout.json为8698 B/SHA `36d8110bdc178e744f1426983dcfc2fdf4439c75a932831d0f4f296ca40975dd`，绑定五个最终产品、三端收据、组件实际消费的hook/Auth/SDK、构建、最终UI、三图和失败历史。静态ACCEPT与Root执行/看图区分记账。

材料工装兼容 patch 已保存，另有离线216断言通过：验证时仅在内存应用候选，冻结源未应用；未导入完整产品、未执行整runner、网络或数据库。216是断言数，不是216个独立测试。原 UUID 不重发，结果仍未确认，PDF 未取得，不能记材料获得或 C2 完成。

`docs/plans/2026-10-25-source-page-change-monitoring.md` 已存在，当前仅下一项实施计划，不代表产品、迁移或测试已执行。本轮未 commit/push，既有 dirty 和失败证据保留，正常及保留 SQLite 未打开。私人关注本项的局部结果不关闭完整权限、真实来源、材料、设备或完整 V1 Gate。

## 证据入口

- [原计划](../../plans/2026-10-25-owned-watch-state.md)、[原生pattern补充范围](../../../.artifacts/r133-owned-watch-state-20261025/scope-amendment-native-pattern.md)
- [最终生产结果](../../../.artifacts/r133browser-f13360718293a4b5/result.json)、[最终构建](../../../.artifacts/r118-material-workbench-20261021/web-build-c1330a1b2c3d4e5f/verification.json)
- [Root收尾](../../../.artifacts/r133-owned-watch-state-20261025/root-closeout.json)、[三图观察](../../../.artifacts/r133-owned-watch-state-20261025/root-visual-review.json)、[实际资源核对](../../../.artifacts/r133-owned-watch-state-20261025/root-resource-observations.json)
- [组件矩阵](../../../.artifacts/r133-owned-watch-state-20261025/component-qa-prepare-v2/result.json)、[最终三端收据](../../../.artifacts/r133-owned-watch-state-20261025/worker-checks-pattern-final.json)
- [对象存储上下文对比](../../../.artifacts/r133-owned-watch-state-20261025/object-store-capability-comparison.json)、[e控制台固定文案匹配](../../../.artifacts/r133-owned-watch-state-20261025/native-pattern-console-e-match.json)
- [材料离线兼容结果](../../../.artifacts/material-c2-resume-20261025/offline-check-result.json)、[下一项页面变化监控计划](../../plans/2026-10-25-source-page-change-monitoring.md)
