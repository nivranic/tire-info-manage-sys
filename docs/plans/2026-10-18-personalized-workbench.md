# 第69轮：个人兴趣历史信息流与已审轴位候选实施计划

**目标：**补齐独立首页，按本人当前兴趣回看本地历史，并为显式选定的车型配置、轮毂和轴位提供证据仍有效的已审核精确 SKU 候选。完整性能推荐、AI 推荐与完整 V1 继续保留。

**架构：**复用九域原始历史重建、本人 session_scope 兴趣和偏好，以及人工车型轴位关系的严格当前门禁。新增接口只读，无迁移、无通知补发、无网络/模型调用；共享车库和保存比较不当作私人画像。

**技术：**FastAPI / SQLAlchemy、共享 TypeScript 类型及注入式 SDK、三端共用 React Workbench。沿用 brainstorming、writing-plans、executing-plans 工作流；用户已授权当前 agent 继续实施，不自动提交/推送或迁移正常库。

## 1. 原需求与取舍

原规格第213、225、227–237、658、826–832行分别要求兴趣与驾驶偏好、只解释不篡改客观排序、车型/Variant/偏好推荐及独立个性化信息流。已审适配候选只关闭一个产品子范围，不关闭第658行的性能/AI 推荐。TestEvent 仍为 participant_only，没有可复核的参测对象到精确 SKU 的桥；不做名称/尺寸关联，不计算综合分或用资料覆盖率代替质量。

选择独立首页而非改名通知列表：当前兴趣可命中创建前历史，同事件多关注合并并保留理由。通知保留发布时冻结条件，不改写、不补发。读历史只限九域已声明的本地可重放记录，不代表外网全历史。

## 2. 冻结接口行为

### 2.1 当前兴趣历史信息流

`POST /v1/personal-feed/preview?mode=history`，StrictModel body：`domain`（九域之一或null）、`limit`（严格整数1–50，默认20，表示每页扫描预算）、`cursor`（null或签名游标）。不接受 actor、session、用户条件或偏好覆盖。

只读取本人最新且 enabled、未归档的兴趣；每条独立三值匹配，任一 matched 则事件 matched，否则存在 indeterminate 则为 indeterminate；no_match 不展示。同事件只返回一次，保留全部非 no_match 的兴趣ID、修订、指纹、名称与匹配理由。不得跨兴趣、来源、前后侧拼 AND。无有效关注返回真实空态，不扫描历史。

分页使用全序 `(at DESC, domain ASC, origin_id ASC)`，按候选扫描推进；空页如有下一段仍返回 next_cursor。响应必须区分 scanned_count、matched_count、indeterminate_count、has_more、next_cursor、active_interest_count，并声明 current_interests_history、local_snapshot、actor 范围及非实时性质。

游标 HMAC 签名，绑定当前主体（不返回原始 session 标识）、当前兴趣完整集合/标签/修订、domain、limit、策略及候选集合摘要；最多4096字符，1小时有效，进程重启后旧签名失效。跨主体或篡改返回400 `personal_feed_cursor_invalid`；过期或兴趣/候选集合变化返回409 `personal_feed_binding_changed`。续页与页末重新核对绑定，拒绝混合快照。仅时间戳上界不能排除并列时间/迟到回填，所以本轮采用集合变化显式失效，而非声称持久数据库快照。

为零写入与资源有界，最多100条启用关注、每次最多50000条候选元数据用于成员摘要、最多50条事件重建；超限显式409容量错误，不能静默丢弃后声称完整。domain 可用于缩小历史集合。摘要只读，不创建 InterestEvent、通知或审计行。

### 2.2 已审精确轴位候选

`POST /v1/fitment-candidates/preview?mode=history`。StrictModel body：`selection`（精确 vehicle_id、vehicle_snapshot_id、trim_id、wheel_option_id、axle）、`expected_preference_revision`、`expected_preference_fingerprint`。只读取本人偏好，修订/指纹变化409；未设置偏好合法，明确无权重上下文。

显式车型快照必须正式采纳并仍代表当前车型事实；配置/轮毂/轴位须在同一快照存在，不按文本或同尺寸补齐。SQL先限精确轴位范围并取关系最新头，最多200条，响应声明 inspected_count、relation_count、truncated；超过预算不声称候选完整。

只接受 `effective_state=reviewed`，且重新验证 binding_hash、冻结原文/精确成员/实际事实、当前身份/生命周期/来源目录等严格关系门禁。失效与证据损坏不进入候选；逐项展示排除原因。多个关系指向同 SKU 时合并候选但保留全部关系及版本证据。顺序只按稳定标识，不表达优劣；`performance_score=null`、`ranking=not_computed`、`official_oe=not_established`。前后轴分别展示不意味着整车组合通过验证。

七维偏好按权重列出研究重点，明确每维 exact SKU 性能证据未建立；已核对的身份/技术声明可按原文展示，不推导安静、抓地等性能。适配检查未知字段保持 unknown，不补零，不把人工关系称官方原配，也不代表当前库存。

## 3. 文件与责任

1. 后端 agent：新 `apps/api/tire_api/personalized_feed.py`、`recommendation_candidates.py`、目标 `tests/test_personalization.py`；最小修改 `interest_events.py` 公开只读候选构造/重建 helper、`main.py` 注册新路由。先写能揭示缺失/错误行为的测试再实现。
2. 前端/合同 agent：新 `packages/domain-types/src/personalization.ts`、SDK方法与合同测试、新 `apps/web/components/personalized-home.tsx`；最小修改类型出口、SDK根出口、route-hash、workbench与局部CSS。只按已冻结行为实现，精确响应字段与后端同步。不修改研究编辑器或兴趣核心逻辑；若必须复用FrozenEvent，最小导出并保留其owner fence。
3. 独立 agent：仅拥有 `apps/api/tests/test_personalization_review.py`，从需求反例验证隔离、分页、迟到/变更、完整历史、证据错误、禁止性能猜测；不修改实现。
4. Root：协调合同、独立复核、限定集成验收、证据封存与交接/风险更新。所有 agent 共享 dirty 工作树，保留其他改动。

## 4. 验收与回滚

先重新核对R68终态，建立本轮preflight，保留旧证据原字节。后端目标/受影响回归；独立反例；SDK公开消费/类型检查；Web、Desktop、Mobile前端生产构建；隔离私有API与1440/390浏览器流程，覆盖历史创建前命中、重复合并、空页续页、变更失效、换主体迟到响应、候选证据重开/空态/缺口及布局。

实际验证分阶段记录，不累加为单次全量。浏览器手机视口/前端构建不等于原生设备验收。正常库、真实来源/模型、完整API/Worker、真实PG与新原生/平台矩阵不在本轮新验收范围。

只在新GUID私有库/对象/Parser bundle运行，导入应用前关闭AI/Embeddings并配置护栏，不启动默认正常库。结束后停止私有进程、核对端口、恢复构建自动改写配置。回滚仅撤回本轮具名修改，保留R63–68既有dirty和证据，不reset/clean/stash。

## 5. 终态

冻结时尚无R69通过结论；实施后的结果与边界见下方终态补记，以本轮报告和最终机器清单为准。

## 6. 实施终态补记

已按本合同交付独立首页、本人当前兴趣九域历史流和已审精确轴位候选。发现1个完整冻结详情核验根因，3种损坏反例已修复；同事实新车型元数据快照允许保留旧关系原快照。宽屏介绍区跨两列，信息流/候选1.25:1并排，≤1100单列。

受影响195项、独立69项、注入SDK/workspace types/导航6项、最终三端前端生产构建、真实私有API39条及1440/390 UI各24条断言分别通过。首轮红测、fixture时序与质量门禁误用、初版canonical详情不足、QA预期修正及沙箱连通失败均保留为历史，不累加通过数。三配置和七构建生成文件分阶段恢复，私有3369/8969已停止。

详细结果见[第69轮报告](../assurance/evidence/round-69-personalized-workbench.md)；当前清单`.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/verification-final.json`。本节在测试后追加，独立运行绑定的是追加前的计划；产品与测试代码不变。性能/AI推荐、真实模型/来源、正常库与原生/平台/完整V1 Gate继续未完成，Goal保持active，未提交推送。
