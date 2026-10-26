# 同场测试的驾驶偏好解读：设计与实施计划

日期：2026-10-18。依据原规格第213–225行的驾驶偏好与推荐解释要求。
状态：2026-10-18第65轮已实现并取得限定验证，以下合同已冻结；结果、工装失败及未验边界见[第65轮终态报告](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-65-test-preference-interpretation.md)。第63轮完整API/Worker回归（2705＋77子测试，exit0）是历史结果，不覆盖本功能。

## 用户目标与范围

用户已经能录入测试事件、比较同场原始成绩和保存七项驾驶偏好，但偏好尚未用于解读。
新增“按我的偏好解读本场”：用户把本场指标显式关联到偏好维度，看到哪些证据与自己
关心的性能有关、已覆盖多少权重、哪些成绩或判断条件缺失。

这是原需求中有证据的个人解释能力。完整车型/精确SKU推荐、跨来源研究、个人信息流、
AI推荐及后续私人映射模板继续保留在总目标中，不因本次实现而取消。

## 方案选择

采用**单次用户映射＋服务器只读计算**。不把用户主观分类写进共享测试事件，不需要
数据库迁移；既有事件修订和客观成绩保持原样。共享事件级映射需独立的来源与治理
合同，留作后续受控测试来源接入。直接按指标名称猜类别会把推测当事实，不能采用。

权重仅组织解释。当前没有统一量纲、维度内权重和归一化政策，因此不生成综合分或
综合排名。保留原来源名次；同场选录数值的极值只标明其所选已录观察范围，不冒充
来源排名或全体胜者。

## 接口与绑定

新增 `POST /v1/test-events/{event_id}/preference-interpretation?mode=history`。
请求为StrictModel，精确六个字段：

| 字段 | 约束 |
|---|---|
| `expected_event_revision` | StrictInt，至少1 |
| `expected_event_fingerprint` | 小写SHA-256 |
| `expected_preference_revision` | StrictInt，至少1 |
| `expected_preference_fingerprint` | 小写SHA-256 |
| `participant_ids` | 本场2–60个唯一参测对象；跨场、未知对象拒绝 |
| `metric_dimensions` | 本场1–24项指标的一一映射；每项仅`metric_key/dimension`，dimension为七维枚举或null |

七维为 `dry/wet/quiet/comfort/wear/energy/appearance`。必须显式覆盖本场指标；null表示
本次排除，不允许猜测、重复、遗漏或加入未知指标。不接受actor、weights、direction、
原值、名次、SKU或URL等覆盖字段。

既有偏好响应增加纯计算的 `fingerprint`，定义为
`digest({schema:"driving-preference-state@1", revision, weights})`，不新增数据库列。
它只用于内容绑定，不是权限令牌。权重仍从当前主体的`session_scope`读取；登录用户
聚合本人会话，匿名仅当前会话。测试事件仍按既有共享工作区读取，解读与偏好为actor私有。

同一计算绑定事件修订及指纹、本人偏好修订及指纹。事件不存在404；撤销、事件陈旧、
偏好清除或偏好陈旧409并有稳定机器code；输入域错误422。结果使用`Cache-Control:
no-store`。计算绑定实际读取的不可变快照，不能承诺响应到达时仍为最新。

## 输出：证据与解释分开

返回 `schema:"test-preference-interpretation@1"`、`data_state:"local_snapshot"`、
`scope:"actor"`、`evidence_scope:"local_workspace"`、`comparison_scope:"same_event_only"`、
`ranking:"source_reported_only"`、`policy_version:"same-event-preference@1"`。

- `binding`保留事件id/修订id/修订/指纹、偏好修订/指纹及本次解释指纹。解释指纹包含
  policy、两组绑定、规范化参测对象集合与显式映射，不包含计算时间。
- `source_evidence`保留机构与关系、发布日期、测试尺寸、条件、选录范围、来源URL、
  原指标/单位/方向、原参测对象、原始小数字符串和来源名次。继续标记人工转录、
  未在线核验、`participant_only`，不自动匹配精确SKU或证明车辆适配。
- `personal_interpretation`明确`mapping_origin:"user_explicit_once"`，包含本人的原权重、
  映射、维度分组、逐指标缺口、所选已录观察比较及覆盖。个人分类与规则推导不能
  写成测试机构结论。
- `notices`明确原始资料与个人解释、缺口和范围。证据id稳定绑定事件/修订/参与者/指标，
  引回已有历史修订入口。

参测对象保留事件原顺序，指标在维度内保留原顺序；仅偏好维度按权重降序组织，
同权重采用固定七维顺序。不得把按偏好组织显示变成重新计算来源排名。

## 数值、缺失与覆盖

1. 原始字符串逐字保留，包括`38.00`、`40.0`、`-0`。内部用Decimal比较，不转float、
   不换单位、不做跨指标加总。极值并列全部保留；`-0`与`0`数值相等但显示各自原文。
2. 只有已声明的lower/higher方向才可解释数值倾向；unspecified只展示证据与限制。
   缺失记录不补零、不罚分；真实0有效，来源名次null不等于成绩缺失。
3. 每指标列出有成绩和缺失的所选参与者、方向未知等可并存限制。至少两条成绩且方向
   明确时才给出已录观察极值，存在缺失时明确不能据此判断缺失对象。
4. 映射权重按“至少映射一项指标”的维度只计一次。同维度多项不能重复累加。
5. 具有完整可比较指标的权重按“至少有一项方向明确且全部所选参与者都有成绩”的
   维度只计一次；不表示该维度全部性能均已覆盖。
6. 未映射权重=`100-映射权重`；已映射但不可完整比较权重=两者之差。绝不把已覆盖
   部分重新放大到100。零权重不抹掉证据；全部null可返回覆盖0/未映射100并解释原因。

## 界面与失效处理

在现有同场比较旁提供“按我的偏好解读本场”。独立子组件承载映射和结果，不修改
录入事件编辑器；沿用现有中文工作台视觉、响应式和键盘/触控方式，三端共享。

打开时读取本人偏好，显示七项权重及修订。未设置时给出明确的偏好设置入口，
不填默认权重或替用户保存。每个本场指标展示来源名称、单位、方向及显式维度选择，
默认“不纳入本次解读”。用户看到全表后明确发起本次计算。

结果区分“原始测试证据”和“本次个人解读”，展示覆盖、未覆盖及缺口；原始名次和
值始终可核对。请求中/失败/无偏好/全部排除均有状态与aria-live说明。切换事件、
修订、参测选择、账户或映射时清空旧结果；取消/旧响应不得回写新选择。

本人状态与请求必须绑定AuthContext的owner，不能只依赖sessionReady。登录、退出或
换账户时立即清空个人结果、abort旧请求；旧owner的迟到响应不得回填。偏好修订是
服务端全局单调编号，前端不能自行加1。内联复用现有偏好编辑器并在保存/清除后通知
解释面板失效，避免跳去车库丢失当前选择；复用编辑器本身也需处理owner失效。

历史修订、撤销场次不能产生新的“当前偏好解读”。断连重连后需重核依据。三端共用
组件与SDK，浏览器桌面/手机视口不替代WebView2、Android WebView或原生断连验收。

## 实施分工与验证

- 后端：新纯计算模块＋test_events只读路由，公开复用本人偏好状态计算；避免拷贝
  一套身份/偏好/事件治理逻辑。权重状态字段和指纹只有一个实现来源。
- 共享合同/SDK：新增请求/响应类型及可注入客户端调用，保持普通比较行为兼容。
- 前端：独立映射/解释组件、接入test-events、必要样式与真实浏览器流程。
- Root：协调合同、独立review、证据与原需求追踪；实施前确认第63轮回归终态与源码绑定。

验证必须覆盖Decimal精度与原文/负零并列/缺失与0/方向未知、映射闭合与重复计权、
跨场拒绝、事件撤销和双版本失效、本人/跨账户/同账户多会话、旧比较与事实记录不变。
前端运行工作区typecheck及相关测试，并在真实私有API＋真实浏览器验证映射、偏好
保存后生效、缺口/失败/陈旧与桌面/390移动布局。模拟传输测试不代替真实浏览器，
私有合成库验收不冒称正常用户资料、真实专业测评或完整推荐质量已验收。

实际浏览器补测：全null默认与覆盖0、内联偏好保存/清空、同维多个指标不重复计权、
来源名次和精确小数、missing及unspecified并存、事件/偏好陈旧、账户切换迟到响应，
1440/390布局及键盘操作、恶意指标文本按文本显示；记录真实六字段请求和无新增
事件/偏好修订的计算边界。既有同场/偏好浏览器报告只作历史参考，不覆盖这些新交互。

## 第65轮实施合同（2026-10-18冻结）

本节将上述原则变为精确合同。使用现有`domain.digest`：按键排序、UTF-8、不转义中文、
紧凑JSON、禁止NaN。请求参测集合按事件participants顺序规范化；映射按事件metrics
顺序规范化，包括显式null。请求数组重排不改变解释指纹；输出也保持来源顺序。

解释指纹输入为`{schema:"test-preference-interpretation-binding@1",
policy_version:"same-event-preference@1",event:{id,revision_id,revision,fingerprint},
preference:{revision,fingerprint},participant_ids,metric_dimensions}`，不含时间或actor标识。
它仅绑定内容，不能用于授权或跨主体读取。偏好指纹在`research.preference_state`
唯一生成，包括未设置/清除状态的revision和null weights。

每条已录成绩的证据ID为`test-measurement:`加digest，输入为
`{schema:"test-event-measurement-evidence@1",event_id,revision_id,event_revision,
event_fingerprint,participant_id,metric_key}`。没有成绩不生成伪证据。
每条证据另有`reference:{event_id,revision,participant_id,metric_key}`，用既有历史修订入口核对。

响应顶层除已约定常量外，`binding`为`{event:{id,revision_id,revision,fingerprint},
preference:{revision,fingerprint},interpretation_fingerprint}`。`source_evidence`包含：
`event`（原payload排除三张列表后的全部元数据）、`participants`（所选原参测者加id和
identity_status）、`metrics`（全部原指标）、`measurements`（所选原成绩加participant_id、
evidence_id、reference）、record_kind/verification_status/verified_at/recorded_at，
recorded_participant_count/selected_participant_count。原始字符串和来源名次逐字保留。

`personal_interpretation`包含mapping_origin、weights、规范化metric_dimensions、
`dimensions`（七维按权重降序、同权重按固定七维顺序，每项dimension/weight/metric_keys/
complete_comparable_metric_keys）、`metrics`（事件原序，每项metric_key/dimension/
observed_participant_ids/missing_participant_ids/evidence_ids/limitations/
complete_comparable/observation_comparison）和`coverage`。
limitations固定顺序为excluded_by_user、missing_measurements、direction_unspecified、
insufficient_observations，可同时存在。null映射不产生个人比较；非null且至少两条成绩、
方向明确时observation_comparison为`{scope:"selected_recorded_observations",
favorable_participant_ids,evidence_ids}`，否则为null。并列全部保留，不产生新名次。
complete_comparable仅在非null、方向明确、所选全部有成绩时为true。
coverage四项整数为mapped_weight、fully_comparable_weight、unmapped_weight、
mapped_not_fully_comparable_weight，按维度各计一次，不重新归一。

错误：框架形状/类型/必填/mode验证先于处理，422 code为
`invalid_preference_interpretation`；通过形状校验后依次判定：
404 `test_event_not_found`；409 `test_event_revoked`；409 `test_event_changed`
（修订或指纹任一不同）；409 `driving_preference_missing`（本人当前weights为null）；
409 `driving_preference_changed`；422 `invalid_preference_interpretation`
（重复/跨场/未知参与者，映射重复/遗漏/未知指标）。业务detail为`{code,message}`。
只读处理不调用事件GET的审计提交，不新增事件/偏好修订，不进行网络访问或迁移。

实施所有权：Root负责纯计算模块与其单元验证、合同/证据文档及最终协调；后端agent
负责research.py偏好指纹、test_events.py路由、main.py本路由422格式及API测试；前端agent
负责共享类型/SDK、独立解读组件、偏好编辑器owner失效、必要AuthContext修复和样式。
不触及已有设备AI合同补修、封存向量和正常库。实施验证采用隔离数据库与私有端口；
在合同、API和UI实现后审读，再做类型/目标回归与真实浏览器验收。未运行的检查继续记未验证。
