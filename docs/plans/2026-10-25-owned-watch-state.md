# R133 关注数据与账户操作生命周期

2026-10-25。继续原规格的个人关注/提醒、对象级访问与完整键盘可用性要求。R132 原 UUID 保持未确认，不重发材料捕获；完整 V1 仍进行中。

## 已确认问题

Workbench 的初载、关注视图读取、账户变化重读及增删操作分别写同一组 watches/changes/pending 状态。视图读取只依赖 view，账户读取只比较 user.id，两者不取消彼此。AuthProvider 已在每次身份操作开始时同步撤销 ownerSignal、递增 ownerEpoch，但关注入口未使用。因此旧账户的迟到成功、错误或 finally 可影响新账户；同 ID 重验和 A→B→A 也不能用 user.id 区分。

后端 watchlists/changes 已按 session_scope 过滤。本轮不改该合同：匿名仅当前会话、登录聚合同用户会话；同 cookie 的既有数据继承不在此处重构。验收用 A 的另一会话所持记录与 B 数据区分，避免把既有继承行为误判为问题。

## 方案与范围

仅增加 user.id 依赖仍无法覆盖同 ID 重验、旧 mutation 和 finally；全局重挂整个工作台会丢查询草稿、比较与其他公共状态。采用现有 AuthProvider 的 ownerEpoch/ownerSignal/isCurrentOwner，将关注读写统一绑定本次账户操作，保留工作台其余状态。

- 产品范围：`apps/web/components/workbench.tsx`，以及共享 SDK 的 watch/unwatch 可选 AbortSignal；若隔离关注状态确有助于复用和清晰性，可新增一个实际由 Workbench 消费的局部 hook，不建立通用账户框架。
- 保留 sources/health/source-access 初载，移除 loadInitial 对私人关注状态的竞争写入。关注标记在账户确认后统一读取；在 watch 视图还读取当前账户 changes。账户 epoch 改变时同步使旧回调失效、清掉旧可见关注/变更/错误/pending，确认身份后重读。视图离开/卸载也取消对应读取。
- 使用既有 ownerSignal 的同步撤销及 isCurrentOwner 检查，不能只靠 effect cleanup 或请求 abort；宿主可能晚交付已取消请求。未 ready/已撤销期间不提交关注增删，提供准确的不可用状态，不能把未确认账户误称已关注或正在执行写入。
- 每次 mutation 绑定原 epoch、请求 controller 和自身锁。旧成功、错误、toast及finally均不能污染新 epoch，不能解除新账户对同 variant 的锁。不重试有副作用请求；本地取消不保证服务器未接受，当前账户重读为准。
- 关注表、卡片/菜单标记、MonitoringCenter 输入均只消费当前 owner 的状态；身份人工核验后更新当前关注变体的行为保留。查询草稿、比较选择、source状态及其他面板不因账户变化被清空。
- 不改 API wire、数据库、后端 session_scope、鉴权或材料历史；旧 dirty 保留，不commit/push/reset/stash/clean，不打开正常/保留 SQLite。

## 验证

先保存 before 与本计划。独立 ultra 审查产品和验证方案，Root 执行与本次改动相匹配的检查。

1. 类型检查覆盖 Web、desktop、mobile 的共享调用；SDK 可选 signal保持旧调用兼容，增加实际转发/取消的目标验证。
2. 使用真实 React/AuthProvider/Workbench 消费路径，受控延迟响应验证旧关注/变更不覆盖新 owner；测试同 ID 重验、A→B→A、未 ready、登出失败后的重验、旧 mutation成功/错误/finally、同 variant新锁、卸载与取消。
3. 验证读取正确范围且不因 StrictMode、初载/账户effect重叠重复取关注。旧请求取消与合成迟到响应单列；不把合成账号或数据称为真实后端账户验收。
4. 新生产构建及小范围生产页面验收复用已审私槽入口；只用新私槽、合成来源及loopback，不启动默认 API。核关注标记、变更内容、禁用理由、查询草稿/比较保全及无额外写入；截图由Root实际查看。
5. 保存失败和新通过证据，按实际运行检查/构建/浏览器/清理分别记账，不把这一项当完整权限或 V1 验收。

材料工装兼容 patch 另由 worker 在内存离线验证，冻结 R132 源与原 UUID 不变。其结果不能代替本项业务验证或材料取得。
