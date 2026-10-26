# 来源质量隔离兴趣通知 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 对有合格历史基线的轮胎来源质量隔离，向明确订阅且完整条件在同一基线成员上成立的本人兴趣发送站内异常提醒，并能重开隔离原文和当时基线。

**Architecture:** 复用现有兴趣修订、私有通知账本及 `interest-event@1` 封套，新增独立的质量状态域、显式订阅字段和专用匹配／证据校验分支。事件描述某次查询的更新被隔离，身份匹配只取经过核对的历史基线成员；候选内容始终未采纳。本切片只发布站内通知，不进入现有 Webhook outbox。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite／PostgreSQL DDL、Pydantic、共享 TypeScript 类型和 SDK、React 工作台、既有隔离 API／Worker 回归入口。

---

## 状态、授权与需求依据

本文件是 **2026-10-25 下一步待审计划**。本次仅新增本文件，没有实施产品／迁移／测试，没有运行应用、数据库或网络，也不把 R134 的源码、测试或浏览器结果算作本计划验收。R134 已由 Root 另行验收收尾，当前产品保持冻结。

本计划采用 @writing-plans 的文件级任务、先反例后实现和分阶段验证；设计取舍沿用 @brainstorming。用户既有完整 V1 持续实施、由当前 agent 继续及材料自主判断授权保持有效。后续按当前持续授权，由 Root 技术审查并冻结合同后按 @executing-plans 实施，不重复询问执行方式／权限；本轮只落计划，不启动实现。当前协作边界覆盖技能中的通用 worktree／逐任务 commit／执行方式询问步骤：不新建或移动 worktree，不 commit/push，不改写或清理他人 dirty。

- 原规格 `docs/requirements/2026-09-26-tire-intelligence-original.md:67-73` 要求监控、个性化、数据质量与失败任务管理；`:236` 要求只推真正相关的变化；`:393` 要求质量异常进入隔离而非覆盖事实。
- `docs/HANDOFF-2026-10-18.md:184` 明确登记“拒收/隔离……尚无对应兴趣通知”。
- **原规格没有逐字单列本通知名称。** 这是上述业务要求与现存需求清单交集中的一个可独立交付切片，不把推导写成原文逐字要求。
- 范围仅为轮胎 `SourceQuarantine`，且须有能证明同来源、同查询的历史采纳基线。普通 `RejectedObservation`、无可核对基线的解析／Schema 拒收、车型隔离、恢复提醒、邮件／Push／Webhook、AI、真实来源长期运行均另行留账。

## 已核实的现状与复用边界

下列为写计划时静态阅读结果，行号是定位锚点，实施前须复核当前文件；没有运行证明。

| 入口 | 已有能力 | 本切片必须补的部分 |
|---|---|---|
| `apps/api/tire_api/service.py:332-371` `record_success` | 在采纳锁内选择最近成功 Verification，评估质量，创建 `SourceQuarantine`／audit 后抛 `SourceQualityQuarantined` | 在新隔离原行所在事务内冻结质量状态并发布通知，不能进入后面的采纳分支 |
| `service.py:144-275` `_execute`、`:460` `lock_ingestion` | 捕获隔离异常，保持在线失败／授权门；`lock_ingestion` **先 commit** 再取得下一段写锁 | 不把“异常处理后再发通知”误写成原子事务；新发布必须在隔离分支抛异常之前完成 |
| `apps/api/tire_api/quality.py:173,291,326` | 隔离元数据、列表及显式 history 详情；详情标 `accepted:false` | 通知侧绑定校验和精确读取；现有详情不是质量通知图的完整校验器 |
| `apps/api/tire_api/interest_matching.py:15,130,159,218,312` | 七类条件、九域 capabilities；明确不支持 `source_quality_rejection`；逐上下文完整 AND | 新域专用匹配、限定五类基线条件、显式订阅、过滤器政策、能力声明 |
| `apps/api/tire_api/interest_models.py:17-63` | 追加修订、`domain+origin_id` 事件唯一、`interest_id+event_id` 通知唯一；domain 是 `String(24)` | 当前修订没有质量订阅字段；ORM 防修改不是已存在的数据库原生防篡改证明 |
| `apps/api/tire_api/interests.py:39,68,151,167,181` | 固定字段视图／指纹／无变化判断；`session_scope` 本人读取；暂停／归档追加修订 | 所有字段复制路径显式携带订阅选项，保留旧指纹；新域通知读取时核图 |
| `apps/api/tire_api/interest_events.py:30,274,369,375,409,437` | 历史轮胎成员证明、通用封套／哈希、冻结／发布／历史重建；无回填设计 | 新 freezer／matcher／重建分支；不能直接套旧 fact diff 或 `allow_indeterminate=True` |
| `apps/api/tire_api/webhook_delivery.py:110,228` | 现有 interest 发布会调用 outbox；已登录 owner 会先核旧九域原行 | **新域显式跳过 outbox**。直接调用旧 publisher 即使无 Webhook 订阅也可能 `HistoryInvalid`；匿名夹具可能掩盖问题 |
| `packages/domain-types/src/interests.ts:55,77,155` | domain／evidence kind 是闭合 TS 联合；before／after 是通用记录 | 新 domain、evidence kind、质量事件及匹配结果的明确类型；泛型记录不等于已有质量合同 |
| `packages/api-client/src/index.ts:590,623-633` | 隔离 history、兴趣增改／通知读取／已读，均有 signal | 新字段及必要闭合解码；通知详情校验后才读绑定原文 |
| `apps/web/components/interest-center.tsx:187-284` | ownerEpoch／signal；已知类别按绑定版本重开；未知 kind 明确拒绝 | 显式订阅、质量文案、隔离＋基线分支；当前没有已证明的隔离 ID 精确深链 |

### Golden 与发布门的精确边界

- `apps/api/tire_api/golden.py:413` `evaluation_bindings`、`:444` `evaluation_gate`；`apps/api/tire_api/parser_releases.py:457` `_golden_gate`、`:512` `create_evaluation` 是现有 Parser Golden／发布链。
- `apps/api/tire_api/golden_checks.py:17-30` 的 `CONTRACT_FILES` 包含 `service.py`、`quality.py` 等宿主文件，`contract_descriptor()` 实时计算字节哈希。修改 service 会改变合同指纹；不得删除该绑定、硬编码旧 digest、回填旧回执或将旧报告追认为当前发布授权。
- 当前兴趣系统没有独立 Golden 匹配评估器。新匹配用独立合成断言验证；不能把这些断言称为真人 Golden，也不能用通知证明候选正确、解除隔离或绕过既有 Parser／审批门。

## 待审的精确合同

### 1. 显式订阅与历史兼容

新增严格布尔 `source_quality_notifications`：输入省略按 `false`；旧修订读作 `false`；旧客户端不因此自动订阅。创建、编辑、暂停、归档、恢复、详情／历史及 SDK 均显式传递或读回该有效值。

第一片只支持条件 `brand/model/size/oe/technology`，并要求 `metric_keys=[]`、`changed_fields=[]`。订阅为 true 却含测试机构／车型条件或指标／变化字段筛选时返回 422 `source_quality_interest_filter_unsupported`；前端解释限制，不静默删条件／清筛选，也不把基线字段伪造成此次字段变化。订阅为 false 的旧七类兴趣维持原行为。

拟追加 `030_interest_source_quality`，实施前复核真实迁移尾号及并行修改。仅向 `interest_revisions` 增加 `BOOLEAN NOT NULL DEFAULT false` 列；SQLite 用其方言合法的 `DEFAULT 0`。新鲜库映射与历史升级分别覆盖，不用当前全量 `Base.create_all` 充当旧库。

旧修订／false 选项保持既有五字段加 archived 的指纹算法；true 加受控键后重新计算，不更新旧行或旧通知：

```python
def settings_fingerprint(data, archived):
    frozen = {key: data[key] for key in
              ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    if data.get('source_quality_notifications', False):
        frozen.update(source_quality_notifications=True,
                      quality_subscription_schema='interest-source-quality@1')
    return digest({**frozen, 'archived': archived})
```

实现时 `append`、无变化判断和修订完整性检查共用此函数。false→true／true→false 都须产生新 revision；重复相同请求仍走现有无变化冲突。旧指纹不绑定一个原来不存在的字段，true 指纹则必须绑定明确订阅。

### 2. 质量状态事件与基线

拟新增域 `tire_source_quality`（长度在当前 String(24) 内），action `quarantined`、state `quarantined`、revision `1`、subject_id 为隔离原行 ID。它是查询采集状态，不能用某个 SKU 作为事件主体或叫作采纳事实版本。

沿用 `interest-event@1` 外层键与稳定 ID 算法：

```python
event_id = digest({'schema': 'interest-event@1',
                  'domain': 'tire_source_quality', 'origin_id': quarantine.id})
# payload 包含现有封套各键；先完整构造，再 seal，一次计算最终哈希。
payload['event_hash'] = digest(payload)
```

新 freezer 显式构造 `before:null`、`changed_paths:['source_quality']`；after 是以下状态记录，不复用 `_event` 对全部基线字段自动求 diff 的结果：

```text
after = {
  accepted: false,
  state: "quarantined",
  quarantine: {id, query_id, source_id, query_key, query,
               source_url, raw_hash, parser_version, observed_at,
               reason_codes, metrics, previous_snapshot_id},
  baseline: {snapshot_id, source_id, query_key, source_url, raw_hash,
             identity_contract_version, parsed_variants_hash,
             verification_id, verification_status, verified_at},
  baseline_members: [{variant_id, structured_locator, member_hash,
                     identity, facts, fact_version_id, fact_version,
                     facts_hash, evidence_valid}],
  evidence_valid: true
}
```

这里 `evidence_valid` 只表示隔离／基线引用图核对通过，**不表示候选已采纳**。`quarantine.candidates`、候选身份／参数、body、内部 session／actor／私有路径不进入事件或匹配。来源 URL 不要求与基线完全相同来伪造变化，只绑定两份各自原始 URL；通知不评价 URL 漂移。

合格基线须逐项证明：

1. 原隔离 `query_id` 对应实际 `QueryRun`，canonical query 的 digest 等于三者 query_key，source_id 一致；不从名称／尺寸反查另一查询。
2. baseline 是隔离行明确的 `previous_snapshot_id`，并与创建时传入的 `previous_verification` 一致；Verification status 为 `ok/not_modified`、snapshot/source/query 关联一致，verified_at 不晚于隔离 observed_at。首次发布在持有原采纳锁时核为实际最近成功前驱；历史读取按冻结 ID 核，不选今天的最新记录。
3. 两份 UTF-8 原文 SHA 各自与 raw_hash 一致；基线 parsed_variants 整体哈希、原身份合同及逐成员 locator／member hash 精确绑定。
4. 成员按基线保存的 id、fact_version 找到同来源历史 FactVersion，核事实哈希和原快照成员；可定向复用 `_tire_side` 的历史校验核心，但不能用当前 TireVariant.identity、当前 manual overlay 或当前合并映射补全。
5. 合法历史资料缺少证明时结果为 indeterminate／不通知，隔离仍照旧保留；实际哈希矛盾、错关联或损坏须固定失败关闭，不能当成历史资料缺失吞掉。具体异常分类须在实现前以反例冻结。

候选缺少某 SKU、行数减少、技术字段消失都不产生该 SKU 消失／停售／被撤销的断言。空基线或无可验证成员不能匹配；只在某一个合格成员上全部条件成立才相关。

### 3. 匹配、修订和幂等

增加 `match_source_quality_event` 专用入口；只复用受控条件规范化与逐成员 AND 判定核心。不得把质量域直接送旧 `match_event` 后靠默许字段绕过。

```text
未显式订阅 -> no_match / source_quality_not_subscribed
不支持的条件或非空筛选 -> 入口422；历史异常输入防御为indeterminate
隔离或基线证明不足 -> indeterminate / baseline_evidence_unverifiable
任一单一baseline member满足完整AND -> matched
只能跨成员／跨来源／跨快照凑齐 -> 不匹配
```

匹配结果采用新 `policy_version:'source-quality-interest@1'`，冻结有效订阅、完整 criteria、`matched_sides:['after']` 以及匹配成员的 `variant_id/structured_locator/member_hash`。既有 `explicit-interest@1` 结果原字节保留；TS match 类型须显式接纳新分支。

新发布只取**当前最新** enabled 且未 archived 的兴趣修订，并要求兴趣／该修订 created_at 均不晚于隔离 observed_at。创建、编辑、暂停、归档与来源写入继续共用 ingestion lock；不能倒选旧 enabled 修订。暂停不补发；恢复仍为 paused，保留选项但须另行启用；旧通知保持原兴趣修订和匹配成员，不跟随后续修改。

事件唯一键复用 `(domain, origin_id)`；通知复用 `(interest_id, event_id)`。已有事件重放只返回原事件，不重新匹配、补通知或进入 outbox。同正文的不同实际隔离观察仍是不同 origin；本片不另造跨 origin 的“同一故障”聚合模型。

现有兴趣 create POST 没有已核实的请求 UUID 幂等合同，不能把上述存储去重说成 HTTP 创建可盲目重试。修改未知结果时先读详情核修订，创建未知结果先读列表核对；UI 不自动重复写入。

### 4. 事务、站内边界和读取

发布位置为 `SourceQuarantine` 新建／audit 后、抛 `SourceQualityQuarantined` 前，继续持有原写锁。发布函数不 commit、不联网、不吞 DBAPI／守护异常。隔离行、质量事件、新通知共用该事务；注入通知 INSERT 失败应使这三者均不新增，已采纳表与验证时间不动。已在更早阶段独立提交的 QueryRun／RawCapture 不承诺被该回滚删除。

新域必须显式跳过 `enqueue_notification`，不修改 Webhook 的 DOMAINS、原行映射或外发 payload。不能靠“当前没有订阅”规避，也不能只用匿名样本验证。保留旧九域现有 outbox 行为。

`source_quality_notifications` 默认 false，无新抓取、Worker 计划或后台服务。只有原有 query／monitor job 执行实际形成的新隔离记录才可能通知。通用历史扫描／preview／GET／迁移不得调用发布器；第一片 preview 保持现有九域扫描，capabilities 明说“质量通知暂不提供历史预览”，不做旧隔离补发。只增加新域已有事件／通知的精确读取与重放校验分支，不暗中扩大历史候选 union。

通知列表／详情／已读继续按 `session_scope` 限定本人，未知 owner 不读写，越权保持404。现有同 cookie 会话继承政策按 ADR-057 保留，不能宣称永久账户或生产租户隔离。

新域读取须核：完整 event_hash、domain/origin/id 一致、通知归属／interest id／冻结修订／有效订阅及匹配结果绑定、隔离原行与基线／成员图。损坏固定503 `source_quality_interest_history_invalid`，不回传底层异常、正文或内部字段；合法不足证明显示 indeterminate，不用新快照修补。列表只核可取的元数据与封存绑定，不读取正文，也不声称已核正文内容；显式详情／证据重开才核两份正文 SHA，不能复制“列表核全文”造成每次刷新读全原文。

## 前端与证据动作

1. 兴趣编辑器提供“相关查询的更新被质量隔离时也提醒”选项，默认关；展示限定五类条件和空变化筛选要求，不清空用户原条件。旧记录读到缺省时按 false 展示。
2. 通知文字为“与你关注范围相关的查询，本次更新被隔离”；说明相关性来自当时采纳基线，不能据此确认本次候选或该 SKU 参数变化。单独标“未采纳／本地历史”，不套旧 accepted 标识。
3. 点击“重开冻结证据”先 GET 本人通知详情；返回新域及绑定核对通过后，按 exact quarantine ID 调 `quarantineEvidence`，按 exact baseline snapshot ID 调 `evidence`。查询范围由新域服务端通知图核验；现有隔离详情有 query_id，但没有 query_key／query，客户端不能假定已有这些键。客户端分别核现有DTO中的 id、query_id（隔离）、source、各自 hash／时间和基线指针；全文按实际SHA核验，失败不展示替代记录，不为本片扩大旧隔离DTO。
4. 扩 `HistoricalEvidenceReader` 的 `tire_source_quarantine` 分支；为基线另给明确证据 kind／校验，不伪装 `tire_change`，因为没有对应 ChangeEvent。现有 `InterestEvidence.kind` 联合和 UI label map 都须扩。
5. 首片在通知下方打开／聚焦冻结证据区域，取消或账户 epoch 变化关闭并撤销读取。当前没有证明 `#/quality` 能携带并选择隔离 ID，不能写成已有精确跳转；不以只切换面板来冒充已重开指定记录。如后续需要跨面板跳转，须另加受控 selectedId 并验收。
6. 复用现有 ownerEpoch／isCurrentOwner／AbortSignal，读取后再次核归属；同账户重验和 A→B→A 也失效。未知 owner、迟到响应、取消和卸载不能展示旧原文、写入已读或发旧成功提示。390px／320px 原文可滚动，触控不依赖 hover。

## 实施任务与文件所有权

以下均为未来任务，不是本次已修改清单。实施者不是独自在代码库；每次只改分配文件，遇并行编辑先协调，不回滚他人工作。

### Task 1：冻结兼容向量和订阅迁移

**Files:** Modify `apps/api/tire_api/{interest_matching,interest_models,interests,migrations}.py`；必要时 `db.py` 导入／注册；Create `apps/api/tests/test_source_quality_interest_migration.py`；定向更新 `apps/api/tests/version_registry.py` 及受影响历史隔离断言。

1. 写独立旧029兴趣 schema／非空修订／通知夹具；先覆盖旧false有效值、旧指纹字节、旧payload和ledger保全。不能由当前 ORM 全量造旧库。
2. 通过下文受管 runner 仅运行新迁移目标，保存未实现时红批原件；没有新字段／迁移时应因合同断言失败，不能因导入环境错误就算有效红例。
3. 最小增加 false 列及迁移、严格布尔输入、公共视图和共用指纹；修改状态复制和 no-op 判断。迁移中不 seed 兴趣、事件或通知。
4. 同一目标新批验证升级、重复升级、新鲜初始化、版本ledger写失败DDL回滚、旧对象／旧列值／旧JSON字节／旧fingerprint保全及 FK／integrity。PG只做DDL编译时明确非活PG验证。
5. 独审确认旧客户端省略保持false、true双向变化产生revision、false旧指纹不变、暂停／归档／恢复都不丢显式选项，再冻结本阶段pin。不提交。

### Task 2：纯基线匹配与冻结证据

**Files:** Create `apps/api/tire_api/interest_source_quality.py`、`apps/api/tests/test_source_quality_interests.py`；Modify `interest_matching.py`、`interest_events.py` 的明确dispatch，不重构旧九域。

1. 写完整AND反例：两个成员分别满足条件、跨来源、R与ZR、缺字段／冲突／unknown、候选满足而基线不满足、后来的身份／manual覆盖、旧false订阅、非空指标／字段过滤器。
2. 保存新纯计算目标的受管红批，再实现只读规范化、逐成员完整AND和专用匹配结果；新增明确 capabilities 限制，旧九域结果保持。
3. 写有效图与坏图反例，再实现冻结基线和公共隔离绑定。利用传入前驱和隔离previous_snapshot_id；禁止查询当前identity补全。
4. 事件最终只seal一次；仅 `source_quality` 路径，不生成 `facts.*` 或 `identity.*` 变化。缺证明与真损坏分开断言；未采纳候选不得进入匹配。
5. 新批运行以上目标；独审事件／匹配完整JSON、各字段用途与基线成员引用。此处不测试真人Golden，也不改Golden真值。

### Task 3：新隔离事务发布、本人读取与 Worker

**Files:** Modify `service.py` 隔离分支、`interest_events.py`、`interests.py`；如必要，增加质量元数据定向读取 helper 于 `interest_source_quality.py`；Test `test_source_quality_interests.py`、`apps/worker/test_monitor.py`；Root注册两个新模块到 runner manifest。

1. 写真实私有API＋文件SQLite用例：先采纳基线、明确订阅、同查询字段损失隔离，得到一条新域私人通知；事实／快照／Verification及它们时间／hash保持不变。
2. 写新通知INSERT失败回滚、两个writer竞争、重复origin回放、暂停／启用／归档／恢复、事后创建／事后开启不补发、历史GET／preview零发布、两账户404／同账户既有聚合、通知冻结及已读幂等反例。
3. 在新隔离分支最小接发布；共用现有唯一约束与写锁，新增新域站内限定路径，**显式跳过outbox**。已登录账户且存在Webhook配置／订阅的用例也必须证明无新outbox；旧域外发回归维持原行为。
4. 新域通知读取分支核图／固定503，列表metadata-only；分别破坏原行引用／baseline member／revision选项／hash／JSON，证明固定错误且不泄露正文。
5. Worker测试复用实际既有调度入口／合成adapter／新私库：同一job基线→下一次due隔离→私人通知；不开第二套scheduler，不把手动改due或合成时间称为长期运行。
6. 执行最小相关新批，确认通知失败不被泛异常改成成功采纳或部分commit。随后只加受影响Golden／Parser发布、既有兴趣／质量／Worker回归，不宣称全API/Worker最新全绿。

### Task 4：共享协议、SDK和界面闭环

**Files:** Modify `packages/domain-types/src/interests.ts`、必要的根出口、`packages/api-client/src/index.ts`、`apps/web/components/interest-center.tsx`；Create `packages/api-client/tests/source-quality-interests.mts` 与对应tsconfig；必要时定向修改 `apps/web/components/source-quality.tsx` 以提取纯展示组件，不改变审批路径。前端如有 `apps/web/AGENTS.md` 则先读，不因虚构规则文件缺失阻断。

1. 先写SDK合同负例：新opt-in精确序列化、缺省false／历史读取、新policy／domain／evidence类型、编码ID、AbortSignal、固定503／404。新模块按现有测试清单接入。
2. 更新共享类型和SDK；静态类型不冒充运行时验证。对新域JSON在实际读取边界做封闭校验，拒未知关键kind／缺绑定，不改读其他证据。
3. 更新capability文案、表单约束、冻结criteria／匹配成员和状态展示，增加隔离＋基线精确读取；保留旧九域页面和现有写入确认。
4. 跑定向SDK合同与Web／desktop／mobile noEmit，使用既有受管构建流程创建新批并恢复生成文件；不以类型／构建证明UI或原生设备行为。
5. Root以新私库及合成来源做实际桌面／390／320浏览器闭环，核网络门、当前账户、准确原文、取消／迟到响应、读状态、错误不替代；截图由Root实际查看。浏览器viewport不等于设备验收。

### Task 5：收尾、证据与回退

**Files:** 后续按实际结果新建正式报告并追加 `docs/HANDOFF.md`；本次不修改这些现有文件。

1. 汇总同批源码pin、真实解释器、targets／收集执行唯一数、失败原件、guard拒绝、资源关闭和生成件恢复；不得将红批与绿批拼成一次全绿。
2. 逐项对照需求、修改、实际验证和未验证范围；明确质量状态／未采纳、默认false、五类条件、没有历史preview／回填或外发。
3. 独审Golden合同变化及旧九域兼容，确认R134证据未被覆盖；由Root复核报告和浏览器截图后才可标本切片完成。
4. 回退采用新修订关闭质量选项／暂停相应兴趣；保留旧事件与通知。不可drop列／删通知／回写旧revision。代码回退必须保留已迁移schema读取兼容，不能把停用功能称为数据库降级。

## 最小受管验证命令与证据门

以下是**未来执行模板**，不是本次执行记录。工作目录为仓库根；PowerShell必须使用7。新测试文件须先注册在 `scripts/run_api_worker_regression.py:TEST_MODULES`，不能直接运行普通pytest、默认app或正常／保留SQLite。每次输出目录须全新且不存在，失败重跑也换目录。

```powershell
$qualitySelfcheck = Join-Path '.artifacts' ('quality-interest-selfcheck-' + [guid]::NewGuid().ToString('N'))
& '.\apps\api\.venv\Scripts\python.exe' -X utf8 -B '.\scripts\run_api_worker_regression.py' --phase selfcheck --output-root $qualitySelfcheck

$qualityCollect = Join-Path '.artifacts' ('quality-interest-collect-' + [guid]::NewGuid().ToString('N'))
& '.\apps\api\.venv\Scripts\python.exe' -X utf8 -B '.\scripts\run_api_worker_regression.py' --phase collect --output-root $qualityCollect --targets apps/api/tests/test_source_quality_interests.py apps/api/tests/test_source_quality_interest_migration.py

$qualityRun = Join-Path '.artifacts' ('quality-interest-run-' + [guid]::NewGuid().ToString('N'))
& '.\apps\api\.venv\Scripts\python.exe' -X utf8 -B '.\scripts\run_api_worker_regression.py' --phase run --output-root $qualityRun --targets apps/api/tests/test_source_quality_interests.py apps/api/tests/test_source_quality_interest_migration.py
```

首次订阅迁移／纯计算阶段，`--targets` 改为已实现且已注册的新文件或具体nodeid；适当的红例原件需记录真正业务断言失败。新片通过后才扩相关目标：`test_interest_events.py`、`test_interest_review.py`、`test_interest_migration.py`、`test_quality.py`、`test_quarantine_review.py`、`test_golden_checks.py`、`test_golden_release_gate.py` 与新增Worker nodeid；发现具体影响再增加对应目标，避免无依据重复全套。

前端命令先核当前package script／runner；定向SDK测试沿用 `packages/api-client/tests/tsconfig.interests-contract.json` 的编译执行方式新增配置，不能凭此计划猜现成script已存在。noEmit至少覆盖三端；构建／浏览器须由Root使用已审受管入口，不在本计划里启动默认服务。

通过条件以实际 result 为准：selfcheck通过、目标collected／executed／unique完整、无意外非selfcheck guard denial、源稳定、资源汇总关闭及终态exit0；失败原件保留。Python guard和进程Job不是OS沙箱，资源汇总关闭也不是逐DBAPI句柄或私库删除证明。

| 必须验收 | 明确通过依据 |
|---|---|
| 显式订阅 | 旧行／省略false不通知；true仅受支持条件；双向变更有新revision且旧指纹保留 |
| 精确相关性 | 同一基线成员完整AND；跨成员／来源／查询不能拼接，候选不参与 |
| 原事实不变 | 隔离后采纳表、核验时间／原hash不动；不推断SKU消失 |
| 原子性与幂等 | 隔离／事件／通知同事务；重放不补发；并发只一份event／notice |
| 暂停与归档 | 当前最新修订门、事后开启零补发、恢复为paused、旧通知冻结 |
| 本人边界 | 登录／匿名、独立Cookie、越权404及owner epoch迟到响应；不扩大为生产租户隔离 |
| 站内限定 | 已登录且有Webhook配置仍零新outbox／零外发；旧域回归不变 |
| 证据闭环 | 列表不读body，详情／重开各自SHA及准确ID核对；损坏固定503、不换当前记录 |
| UI | 桌面／390／320真实浏览器、键盘焦点、取消／读状态／错误；不冒充原生或完整WCAG |
| 迁移与Golden | 独立旧029slice、旧值／字节／指纹保全、失败DDL回滚；动态Golden合同不被绕过 |

本片不验真实上游长期监控、EPREL、真实Provider／Embeddings、C2重发、代表性真人Golden、正常库升级、活PostgreSQL、原生宿主／物理设备、生产权限／通知服务或完整V1 Gate。没有这些依赖仍可交付上述工程闭环，但不得据此关闭它们。
