# 第66轮：非 SKU 兴趣关注与相关变化解释（2026-10-18）

本轮落实原规格第213、227–237行中的本地兴趣关注切片：在原有精确SKU收藏之外，支持品牌、型号、尺寸、OE、静音技术、测试机构、车型适配七类条件及组合，按已采纳的本地变化生成有冻结依据的通知。完整相关信息流、实时监控、完整推荐与完整V1仍未完成。未提交、推送、迁移正常库或发布。

## 实现与最终合同

- 新增 `interests`、`interest_revisions`、`interest_events`、`interest_notifications` 四表及迁移 `016_private_interests`。兴趣归属、追加修订和冻结事件不可覆盖；通知只允许修改已读状态。迁移只在私有合成SQLite上验证，正常库未升级。
- [最终HTTP/DTO合同](../../plans/2026-10-18-interest-following.md)列出接口、精确输入、字段筛选、错误码与能力范围。设置请求只含 `name/enabled/conditions/metric_keys/changed_fields`，不接受客户端actor。编辑使用 `expected_revision`；归档与恢复都停用，恢复后须明确启用。列表、详情、编辑、通知和已读沿用 `session_scope`。
- 条件组之间AND、每组显式备选OR；同kind的多组仍为AND。品牌、型号与机构使用NFKC/casefold/空白规范化后的完整值比较，型号包含品牌，R/ZR保持区别。技术只用声明值，冲突或不足证据返回 `indeterminate`。完整AND必须在同一证据对象、同一个before或after上成立，不拼接参测者或前后状态，不猜别名、后继型号或湿地指标分类。
- 轮胎与车型混合条件须有可复核的已审exact SKU/配置/轮毂/轴位关系；关系按事件时点冻结，并核对当时车型范围、要求与状态。同尺寸不证明SKU适配。车型自身明确轴位的尺寸条件可用其已录声明，不扩成SKU关系；测试参测者也不成为精确SKU。
- 轮胎已采纳事实、人工测试修订、车型事实版本、人工适配关系四域在原业务事务中发布，不额外commit；通知失败使原域写入一起回滚。事件按domain+origin去重，通知按interest+event去重；撤销/恢复即使payload相同也保留各自action/state/revision。保存兴趣不创建抓取、调度或模型任务。
- 变化筛选保留空对象、加入/移除和真实零；提供精确UTQG及胎纹深度路径。原始metric key只筛选实际相关指标或成绩变化，移除可以由完整before侧证明。创建/修订兴趣仅对之后的事件生效；旧origin即使没有事件账本，也不能向后来兴趣补发。历史预览有界、只读，不生成通知。
- 通知冻结兴趣修订、原事件和 `match.criteria={conditions,metric_keys,changed_fields}`；后改关注不会改写解释。历史引用实际重新读取绑定的测试修订、适配修订或快照原文，校验ID/修订/指纹，失败不换用最新记录。原snapshot member版本与实际fact版本分别保留，支持合法跨query 304恢复旧snapshot时的member v1、actual v3、before v2。
- 共享类型、可注入SDK与三端共用兴趣面板接入“我的关注”。Auth ready、ownerEpoch、完成时主体检查与请求取消覆盖私有读取、预览、变更、通知及历史reader；主体切换或连接unavailable时清空私有子树，旧响应不回填新编辑器。

能力表明确未覆盖手工事实纠错、身份决策、目录成员变化、轮胎生命周期事件、来源拒绝/隔离结果和只更新验证元数据等事件。轮胎生命周期/身份状态会限制已审关系继续作为正向证据，但这些动作本身没有因此成为完整兴趣通知来源。OE和人工已审关系均不等于官方OE认证。

引用指纹按kind解释：轮胎/车型snapshot为raw_hash，测试为payload fingerprint，适配为binding_hash而非整revision hash；action/state/revision另由event_hash覆盖。轮胎主变化引用的record_id是ChangeEvent.id，before或关系链辅助引用可能是FactVersion.id，重开始终依据绑定snapshot_id/raw_hash，不假造旧ChangeEvent。完整映射已列入计划§5.2。

## 验证与回执

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 独立匹配/API/迁移 | 32 passed：13纯匹配、14 API/生产事务边界、5迁移/模型/PG DDL；14文件运行前后及报告时SHA一致 | [sealed回执](../../../.artifacts/review-r66-handoff-14af7e39a8ca4be3b10b44a22a54fb04/sealed-9eaa392b921448f7bf429158ae4335ae/verification.json)、同目录日志/XML；[独立审查报告](../../../.artifacts/review-r66-handoff-14af7e39a8ca4be3b10b44a22a54fb04/R66-REVIEW.md) |
| 既有后端与producer回归 | 初次五组146通过/2环境失败；随后六文件150通过/1源码变化失败/2明确排除；源码冻结后原失败节点单独1通过。三个阶段不相加为一次新全量回归 | [后端分阶段汇总](../../../.artifacts/review-r66-backend-summary-e8f811e9042c481e9fd6fb98299cc51c/verification.json)及所指原回执 |
| Windows Parser修复 | 宿主目标10 passed：7环境枚举用例、1 clean-environment/Python guard、2既有车型adapter节点；sandbox原7通过/3 isolation unavailable失败保留 | [宿主退出回执](../../../.artifacts/r66-interests-8d035c091972b1792299434827/parser-host-exit.json)、`parser-host-final.log/xml`；同目录 `parser-final.log/xml`、`parser-exit.json` |
| SDK与类型 | SDK原完整套件192 Host＋34 decoder＋3公共合同通过；最终criteria扩展后重跑兴趣公共合同及工作区typecheck通过 | [前端总回执](../../../.artifacts/runtime/interests-frontend-dca794f10eb443068314729620060e62/verification.json)、[criteria补验](../../../.artifacts/runtime/interests-frontend-dca794f10eb443068314729620060e62/criteria-checks.json) |
| Desktop/Mobile前端 | 最终criteria源码的两端Vite生产构建exit0；保留既有大chunk提示，非原生安装包 | 同目录 `criteria-checks.json` 与 `desktop-vite-criteria.log`、`mobile-vite-criteria.log` |
| Web生产构建 | 最终criteria源码直接Next build exit0，5/5静态页；回执10源码及15制品绑定、source_drift为空；next-env/tsconfig恢复构建前字节，sw未改，生成文件Git状态空 | [最终Web回执](../../../.artifacts/runtime/interests-frontend-dca794f10eb443068314729620060e62/web-criteria-verification.json)及 `web-production-criteria.log` |
| 隔离Chrome内真实API | 44/44条断言通过，包括准备、接口与生产写入检查，不是44个独立场景 | [browser-api-final-v4.json](../../../.artifacts/r66-interests-8d035c091972b1792299434827/browser-api-final-v4.json) |
| 桌面与手机交互 | 桌面20条有效通过；另保留1条被两条正确before/after检查明确取代的工装断言。手机4/4；1440桌面与390手机无整页横向溢出，最终截图已目视核对 | [browser-ui-final.json](../../../.artifacts/r66-interests-8d035c091972b1792299434827/browser-ui-final.json)、[桌面截图](../../../.artifacts/r66-interests-8d035c091972b1792299434827/desktop.png)、[手机截图](../../../.artifacts/r66-interests-8d035c091972b1792299434827/mobile.png) |

浏览器使用独立Cookie profile、专属SQLite/对象/Parser bundle目录和合成来源，经过真实生产 `QueryService`、`test.append`、`fitment.append` 写入。覆盖七类、完整值与R/ZR、精确事实字段、未来通知、已读/未读、陈旧409、归档/恢复，以及已审同SKU关系后的UTQG推送与撤销关系后停止授权后续事实推送。界面实际创建三组AND关注、查看只读history和冻结criteria/原兴趣修订，重读轮胎before/after原文、测试before修订1/after修订2（当前已到4）、适配旧修订1（当前已到3）与车型原文。

迟到响应测试先取得真实API响应再持有，取消preview或经过真实logout/register与owner重核后释放；旧响应没有关闭新编辑器或显示旧成功状态。这不是后端Mock。连接unavailable通过浏览器事件触发，未模拟真实断网，也未证明原生WebView/设备生命周期行为。

## 归属政策与环境边界

本轮复用既有 `session_scope`：匿名按会话、登录按同账户会话聚合。**同一浏览器会话内注册或重新登录，会将该会话已有记录纳入新账号可见范围；本轮没有修改这一既有政策，不能宣称严格的永久账户隔离。** 该限制已见[ADR-057](../decisions/ADR-2026-057-local-multi-user-accounts.md)及既有 `test_auth_lifecycle.py::test_deleted_users_data_joins_next_login_on_same_session`；本轮没有把该既有节点算作新增通过项。浏览器最初对同Cookie新注册期待空列表的工装假设被纠正。随后独立Cookie页实际验证兴趣列表与通知总数均为0、旧interest详情404，并完成手机端创建；这证明该隔离profile下的范围检查，不能扩大为所有账号切换场景的隔离承诺。B→C真实注册后的持有响应检查只证明旧响应不关闭新editor、不报旧success，没有断言新账号不带入原会话数据。

[最终fixture回执](../../../.artifacts/r66-interests-8d035c091972b1792299434827/runtime-v4-final/fixture-final.json)记录16条兴趣、19条兴趣修订、15条事件、49条通知；计数包含有意制造的验证写入，不是独立场景数。API进程内外部网络尝试、Provider调用、Parser子进程均0，正常库未使用；计数不覆盖整个浏览器或Next开发进程。单独Parser专项验证会运行受控本地子进程，不能与API fixture的零子进程计数混用。Root记录API shutdown退出0，开发会话Ctrl+C退出1，测试页已关闭。

正常数据库与对象目录、真实来源/官网、付费模型、完整API/Worker回归、PostgreSQL实际运行、Android/iOS或桌面原生安装包、凭据与权限、物理设备及PWA离线资产更新均未验收。源码/证据清单只能证明所采集快照一致，不能替代这些Gate或充当工作区恢复归档。Goal保持active，完整V1未完成。

## 修复、失败保留与后续

独立审查发现并修复了空对象/存在性变化遗漏、首观察精确fact路径回归、型号brand冲突依赖、technology_features冲突使用；Root另补旧origin未来边界、无效历史证据门禁、已审关系的当前车型引用与范围复核，以及真正重开原始记录。修前失败与修后独立32项回执保留，未靠放宽条件通过。

后端回归同时暴露既有Windows Parser清理环境遗漏CPU架构元数据的问题：子进程 `platform.machine()` 为空而与绑定环境不兼容。本轮只允许 `PROCESSOR_ARCHITECTURE/PROCESSOR_ARCHITEW6432` 的严格枚举值，不继承任意父环境、PATH或PYTHONPATH；保持墙钟8秒、并发2、CPU5秒、内存384MiB。宿主10项目标通过；sandbox isolation unavailable失败如实保留，Parser仍是进程故障隔离，不是内核网络/文件权限安全沙箱。

其他工装修正包括初始测试payload未canonical、车型/轮胎region不一致被正确拒绝、MCP sourcePath限制、toggle/details及列表等待选择器、选错测试before/after引用、审查runner误拦Windows asyncio自唤醒，以及合成来源更新触发质量门禁。修正限于工装与前提，没有放宽产品校验、来源质量门禁或Parser预算。中间回执与最终结果分开保留。

本轮主清单入口：[verification-final-v2.json](../../../.artifacts/r66-interests-8d035c091972b1792299434827/verification-final-v2.json)。独立清单核验发现旧交接页的原始需求链接含裸空格，文件虽存在但不能形成有效CommonMark链接；已改用角括号包裹目的地，产品源码不变。v1及其生成脚本保留原字节，作为该文档修正前快照；v2在文档收口后重新封存。本文结果来自上表分项回执，不因列出该入口就声称已独立核验最终主清单。第63轮历史全量、第64轮及第65轮清单保持原有时间与身份，本轮后续源码不能重新冒充其覆盖。

本切片已实现并取得上述限定证据。后续仍需明确共享浏览器会话的归属政策、补充真实专业样本/人工Golden、更多相关事件/来源及原生生命周期矩阵，并继续完整推荐、设备/平台、AI质量与生产发布Gate。保存兴趣仍不等于已开启实时采集。
