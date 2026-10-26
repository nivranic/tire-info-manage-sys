# Same-event Candidate Interpretation Implementation Plan（R75）

**Goal:** 将当前精确轴位候选、当前有效的参测对象身份桥和本人偏好连接成可核对的同场条件化解释，展示原始成绩与逐项取舍，不修改来源排名或产生综合推荐分。

**Architecture:** 新只读组合投影复用R69候选、R71完整重建及R65纯算法；请求绑定当前事件/偏好/桥修订，读尾释放快照后完整重建签名。SDK及三端共享React面板显式选场/桥/维度，无持久新表、模型、采集或导出入口。

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy、现有SQLite对象仓库、TypeScript SDK/共享React。

状态：实施合同冻结，独立设计初审通过，尚未验收。使用brainstorming与writing-plans收敛设计，在当前工作树直接实施，沿用用户持续实施授权，不另问是否执行。保留全部dirty，不commit/push/reset/clean/stash，不新建仅含HEAD的工作树替代当前实现。正常库/真实模型/设备不属于本轮验证。

基线：`.artifacts/r75-same-event-8e1d820cc22f43c8bbac303b8250fe06/baseline.json`，已实际核R74的940源码、27文档、121证据、4配置和349展开dirty一致；原需求关于TestEvent范围、原始值/条件和偏好不篡改来源排名仍为完整目标依据。

## 1. 设计选择与范围

采用即时只读组合，避免新增物化推荐记录的失效维护；也不要求用户手工在多个面板比对同一修订。模型生成推荐需独立用途/同意及新协议，后续C另做，不能借组合能力解除R70或R71权限。

本轮完成B工程链：后端、公开DTO/SDK、明确的产品入口、真实私有HTTP与React验证。R74真实磨损颗粒论文缺完整SKU，不能拿其商品名造正向身份；本轮完整正例为明确合成工程数据。代表性真实精确SKU/真人Golden与专业Golden评估器仍列后续目标，不把本轮合成工程通过写成它们完成。

## 2. 精确请求

`POST /v1/test-events/{event_id}/candidate-interpretation?mode=history`，只读，成功/错误均no-store。请求closed且严格类型：

1. `selection`：R69五键vehicle_id、vehicle_snapshot_id、trim_id、wheel_option_id、axle，原限长与front/rear不变。
2. `expected_event_revision_id`（1..64）、`expected_event_revision`（strict int≥1）、`expected_event_fingerprint`（64小写hex）。event_id仅在path，不接收客户端事件内容。
3. `expected_preference_revision`（strict int≥1）、`expected_preference_fingerprint`（64小写hex）。仅本人当前保存的七维权重，无默认补权重。
4. `candidates`：2..60项，每项严格五键`variant_id`、`link_id`、`expected_link_revision_id`（各1..64）、`expected_link_revision`（strict int≥1）、`expected_link_fingerprint`（64小写hex）；variant/link及从桥推导的participant都唯一。
5. `metric_dimensions`：1..24，沿用R65的metric_key与七维/null；必须恰好覆盖本场全部指标且无重复。默认null，只能由本次用户显式决定；不接收原值、来源排名、方向、participant ID、权重或资格标签。

## 3. 当前准入与读尾

新模块`test_candidate_interpretation.py`自持路由注册，不改既有R65/R69/R71公开合同。整个计算在no_autoflush下执行：

- 读当前latest事件，严格EventPayload重建与digest校验；核完整revision_id/revision/fingerprint与active，避免同payload恢复误复用。本人偏好必须已保存且绑定相等。
- 复用R69 projection的完整候选与signature；扫描truncated整次409，不能当全范围准入。其当前车型、精确轴位关系、原件、身份、生命周期、目录等门保持。
- 对每个link先取latest并要求完整请求修订元组相等，再调用完整只读link_view（包含R71事件/轮胎/双侧原件/声明/审核链重建与current_binding/assessment）。请求variant须与桥相等；event_id及event_revision_id须恰为本场当前修订，participant必须实际存在且唯一。历史review行、已撤销后旧行或恢复同payload不复用。
- 无效/损坏证据或错作用域返回固定422/409；当前修订虽匹配但review/payload级准入不足、或不在当前轴位候选的项，作为明确excluded保留。**任一所选项被排除时，整次不产生个人解释**；不可静默对余项生成伪完整推荐。用户可重新明确选择仍有效的集合再计算。
- 全部项有效时复用R65解释。原始source_evidence来自本次选定participant的实际事件，保留participant_only的来源身份标签；SKU关联仅在独立items中的当前条件性桥表达。少于两个可解释项或没有显式映射且有方向/至少两观察的指标时status不足。即使有个人结果，也只解释已录观察，不给综合排名。
- 组合签名包含当前事件完整元信息/内容、偏好、R69 signature、请求完整refs、全部完整link_view（含材料/身份/生命周期/目录状态）及规范映射。先算result/signature，`db.rollback(); db.expire_all()`释放快照/identity map，再完整重算；不同409。禁止调用GET TestEvent handler（其会audit/commit）、摄取锁、audit append或写事务。

### 组合签名字面合同

`interpretation_fingerprint = digest(preimage)`，digest为现有domain.digest：UTF-8、sort_keys=True、ensure_ascii=False、separators=(",", ":")、allow_nan=False的JSON做SHA-256。preimage严格为：

```text
{
  schema: "test-candidate-interpretation-binding@1",
  policy_version: "same-event-candidate-interpretation@1",
  actor_user_id: 当前已认证用户ID,
  event: { ...test_events.metadata(current_row), event: EventPayload校验后的model_dump() },
  preference: candidate_projection.preference,
  candidate_fingerprint: R69 projection返回的signature,
  selection: 请求selection.model_dump(),
  candidates: [
    { request: 请求ref.model_dump(),
      link: link_view(db, latest_row, actor=None, history=False)的完整结果,
      current_binding: current_link_binding(db, reconstruct_link_revision(db, latest_row)) }
  ],
  metric_dimensions: 按当前event.metrics顺序规范为[{metric_key, dimension}]
}
```

candidates保留请求序；映射仅按本场指标顺序规范，故交换映射输入顺序不改签名、交换候选输入顺序会改签名。完整link包含allowed_actions（actor=None时为空），不含history；current_binding必须显式纳入，不能只用assessment标签代替身份/生命周期/目录代次。返回的candidate_fingerprint必须恰等本次R69签名，不另hash。事件/偏好/完整材料内容及当前代次都由服务端读取，不接收调用者替代；签名用于快照绑定，不作为授权。独立测试不得调用生产签名辅助器构造预期，应手写字面preimage并独立JSON/SHA复算。

## 4. 固定响应

精确TypeScript合同位于`packages/domain-types/src/test-candidate-interpretation.ts`，字段冻结为：

- `schema:test-candidate-interpretation@1`，`policy_version:same-event-candidate-interpretation@1`，`data_state:local_snapshot`，`scope:actor`，`evidence_scope:local_workspace`，`comparison_scope:same_event_only`。
- `status:conditional_observations|insufficient_evidence`，`ranking:source_reported_only`，`performance_score:null`，`official_oe`沿用R69的not_established结构，`boundary`沿用R71固定用途/未核验标签。
- `selection`；`binding:{event:{id,revision_id,revision,fingerprint},preference:{revision,fingerprint},candidate_fingerprint,interpretation_fingerprint}`。candidate_fingerprint为R69签名；组合指纹为本轮规范签名摘要。
- `candidate_projection`为R69完整FitmentCandidates，保留excluded_relations和范围；`items`按请求序返回`{variant_id,participant_id,participant_key,eligible,reason_codes,link}`，link是当前桥的精简证据结构（严格字段见DTO），不重复完整事件60次。响应不包含管理allowed_actions或历史列表。
- `requested_count`、`eligible_count`、`excluded:[{variant_id,link_id,reason_codes}]`、`reason_codes`。未准入项必须可见；任何excluded时personal_interpretation为null、status不足。
- `source_evidence`沿用R65完整源结构，只含所选来源participant（包括被排除者的原始来源观察，不据此关联SKU）；`personal_interpretation`沿R65结构或null，`notices`。无比较指标时可保留R65限制/coverage但status不足；缺失不补零、原小数/负零/并列、方向未知和来源rank不改。

精简link保留id/revision_id/revision/fingerprint/binding_hash、selection、review_state/effective_state/eligibility/evidence_level、materials/material_evidence/assertions/checks/required_identity_fields/unknown_fields/blockers/stale_reasons、boundary、declaration_revision_id、confirmed_event_revision_id/confirmed_participant_hash。完整轮胎/事件原证据已由服务器重建并纳入组合签名；通过现有桥详情入口可另核。

新错误使用固定`test_candidate_*` code；既有R69/R71安全错误可沿用。404事件缺失，409事件/偏好/请求桥修订变化、truncated、读尾变化；422严格输入/重复/作用域或证据完整性失败。不回显非法请求或原件内容。

## 5. UI行为

在personalized-home候选区新增独立TestCandidateInterpretation，不改变R65参测对象解释。父候选选择、关系/车型/偏好或账户epoch变化时整体重建，旧草稿/桥/结果立即清空。

显式选择当前active场次、分页读取场次与桥，不能把单页当完整无记录结论。逐候选勾选并明确选择本场桥，不用名称/尺寸猜配。显示SKU代码/命名空间/市场、participant、当前桥修订、许可/未核验限制。全指标初始null；用户映射七维后显式计算。

所有读取/计算沿用AbortController+generation+ownerEpoch guard；账户/草稿/桥/映射/偏好变化或409清空结果，迟到响应丢弃。结果分开展示轴位证据、条件性桥/定位、原始成绩和逐项偏好解释/coverage及排除不足；原值不经过Number转写。无AI、保存、导出或下载材料新入口。

## 6. 所有权与实施任务

- Backend owner：新后端模块、`tests/test_test_candidate_interpretation.py`与必要新`candidate_interpretation_support.py`合成私库辅助；先做正向完整2SKU/双侧材料/已审车型关系/双账户桥，完成最小红例再实现。Root仅负责main注册，不改已有R65/R69/R71代码。
- Frontend owner：新组件、新独立CSS、personalized-home最小接入。先读apps/web/AGENTS.md对应本机Next指南；保持三端共享，不引next专有依赖。DTO/SDK由Root独占。
- Root：新DTO、domain-types出口、SDK方法/公开消费验证、main注册、计划/基线、私有HTTP/真实React验证、相关typecheck/构建和资源/生成配置恢复、报告/风险/交接/最终清单。
- Independent owner：新独立反例/报告，仅改其新文件；复核latest、ABA、完整材料、身份namespace与同名不同SKU、作用域、偏好与账户隔离、纯只读SQL、尾读变化及组合字面量。

所有owner并行不回滚他人变更。验证先清除TIRE/TI/数据库/Provider/代理环境，main全局app导入前显式TIRE_DATABASE_URL/DATABASE_URL指向GUID私库，objects/bundles用短私根；网络/正常库/子进程护栏。sandbox硬链接拒绝时保留失败并以相同护栏宿主跑，不mock存储或提parser预算。

## 7. 验收与回退

目标反例至少覆盖：错event/link/variant、stale/restore同payload/撤销后旧review；only-name/size、代码namespace、市场/OE/技术未知；当前关系/身份决定/生命周期/catalog ABA；原件同长损坏；全null/未知方向/缺失与0/负零/并列/原始rank；请求重复/额外字段/6与60不混淆；truncated；偏好清除/换账户/读取中变化。SQL观察证明不新增/覆盖业务/审计记录，允许会话middleware既有更新时间，不把它冒称业务写入。

执行新目标及必要R65/R69/R71最小相关回归，公开SDK编译正负例/注入transport消费、workspace typecheck、相关三端构建。真实GUID私有API与React验证正例、失效、排除、账户迟到响应、桌面/390/320布局；合成来源明确标识，不冒称真实SKU/专业人员/原生设备或模型验收。阶段不相加为全量，失败/修正保留原回执。

回退只按本轮文件与差异人工处理，不reset/clean整树；没有新表、正常库迁移或业务历史需删除。冻结合同保留验收前原字节，终态另写报告。完整原Goal继续active，真实代表性Golden/C/更多来源与各V1 Gate不因B工程通过而消失。
