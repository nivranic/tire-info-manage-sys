# TestEvent 参测对象与精确 SKU 证据桥：后续设计卡

状态：**R70后续设计的历史建议；R71已另冻[人工证据桥合同](2026-10-18-test-sku-evidence-bridge.md)，A的工程工作流已实现并限定验证，真实来源支持和代表性Golden仍未验收。**本卡下方“建议/未实现”是当时设计背景，不替代R71精确合同与[验证报告](../assurance/evidence/round-71-test-sku-evidence-bridge.md)。B/C性能与AI推荐、完整V1仍未完成；不从本卡推导新来源采集、真实模型、正常库迁移或发布授权。R70现有AI摘录边界继续保持，见[该轮计划](2026-10-18-test-ai-grounding.md)。

## 1. 已确认的起点

- `Participant` 只有 key、brand、model、source_designation；公开 participant_id 为 `event_id:key`，跨事件修订不变。相同 key 可在新修订中指向不同对象。
- TestEvent 是 `manual_transcription / unverified / local_workspace`，source_url、机构名、短摘录和人工审核不构成独立来源核验。
- 事件 fingerprint 只覆盖 payload；撤销、恢复可有相同内容指纹。任何当前使用都必须额外绑定 revision_id、revision 和 state。
- R65 支持用户本次显式映射本场指标与七维偏好，不改来源成绩或名次；没有持久 SKU 性能映射。
- R69 候选已有严格车型轴位与 SKU 双侧证据、事实/身份/生命周期/目录门禁。该人工关系不证明官方原配，也不证明测试参测身份。
- R70 含测试的仓库 AI 包只做服务器事实摘录；自然语言模型不能替代身份桥。

## 2. 建议模型与证据等级

不向既有 Participant 直接填 variant_id，也不覆盖厂商 facts。新增独立 link 与 append-only revision 两表，固定 link 的 `(event_id, participant_key)` 范围；事件更新不自动改写旧 link。

每次修订至少冻结：

| 部分 | 必须保存 |
|---|---|
| 测试侧 | event_id、event_revision_id、revision、fingerprint、state、participant_key、完整原 participant、participant_hash；原尺寸、测试条件、来源关系/权利声明和原文位置 |
| SKU 侧 | variant_id、tire_snapshot_id、fact_version_id；精确原成员和真实 FactVersion、完整身份合同/命名空间、来源原文及 structured locator |
| 关联声明 | evidence_level、明确声明的身份字段、受限短引文与可重开来源位置、原文 hash、已知未知项；不得从 SKU 目录反填测试未披露字段 |
| 决定 | action、review_state、operator、reason、actor、timestamp、完整 before/after、request_hash、幂等键、完整 revision fingerprint |
| 当前绑定 | 事件修订/状态、身份合同和身份决定修订、生命周期修订、关联目录 transition 代次；历史原证据与当前有效性分别展示 |

证据等级应分轴表达：

1. `manual_assertion`：研究者认为可能相关；可记录线索，**不允许把成绩移植为精确 SKU 性能**。
2. `source_explicit_identifiers`：测试来源明确声明可区分版本的标识。需要代码及命名空间、市场和其他实际区分字段的直接证据，能重开原出处。仅型号、尺寸、OE 或外观近似均不足。
3. 审核状态 `pending_review/reviewed/revoked/needs_review` 是人工流程，与上面的证据等级分开；审核不能把人工转录提升成 online_verified、厂商确认或独立核验。尚无可核验来源材料时仍明确 `manual_reviewed_transcription/unverified`。

等级2不能仅靠上传一段操作者自写文字自动成立。需先冻结允许的材料入口、许可/归属、原始字节留存、结构化定位与“人工转录”和“已独立核验”的精确区别；这是实施前必须收敛的设计项。

## 3. 版本与拒绝规则

- 创建/修订进入待复核，审核为管理员写入；恢复只回到待复核。不能点一次恢复便复活旧审核。
- 不同代码、编码类型/命名空间、市场、OE、载重/速度、XL/HL、静音/缺气保用等区分字段不能按名字或尺寸自动合并；未知不等于相同或否。
- 事件新修订，即使 payload 最终恢复相同，也不能复用旧审核。事件撤销、身份 redirect/clear、SKU revoke/restore、目录 remove/reentry 同样按修订代次失效。
- 当前有效性重建时核验完整原文、成员、事实、payload hash 与冻结详情，不只核摘要标签；损坏原证据明确排除，不能返回篡改后的证明。
- 元数据观察刷新但事实未变，应保留原已审历史引用；一般性能事实变化与精确身份变化应分开解释，不能宣称身份变更。具体粒度在实施合同内冻结。
- 读取历史不触发重审核，不调用带 audit/commit 的 GET handler 作为计算 helper；新增使用走无副作用纯重建函数。
- 写端点需要预览 fingerprint、expected_revision、幂等与冲突检查；新增表/迁移仅在 GUID 私有库验证，正常库另核保全与适用授权。

## 4. 建议交付顺序与成立条件

| 步骤 | 可交付内容 | 关闭条件 |
|---|---|---|
| A 证据桥 | 查看精确双侧证据、声明/审核/修订/撤销、重开历史与当前失效解释 | 合同/SDK/界面完成，正反例与真实私有HTTP验证；有来源支持的代表性人工Golden |
| B 条件化推荐解释 | 车型轴位当前已审候选＋有效身份桥＋同一个 TestEvent＋本人偏好；保留来源值/名次，显式本次指标映射 | 至少两项可比较候选；缺失与未知明确；权重只组织取舍，不能把覆盖率当性能、缺失补零或跨场直排 |
| C AI 推荐 | 服务器先形成有引用的限定解释/取舍，再让专用有版本模型合同选择或解释；事实与推断分开 | 逐项支持关系、participant/SKU/车型作用域、来源关系/许可、自由文语义与不确定性评测；真实 Provider＋浏览器完整管线验收 |

同场推荐只能说明本场尺寸、条件、方法与录入范围内的取舍；不能宣称所有场次或全部性能的总冠军。独立与厂商委托测试分别标明。跨场研究先分别引用；后续归一化如实施，必须明确是推断，不能替代原始成绩。

只有 A 完成不能宣称 B/C 完成；只有合成合同通过不能宣称代表性真实专业样本或完整推荐完成。

## 5. 必须保留的反例

- 同名同尺寸但代码/市场/OE不同；代码看似相同但命名空间不同；只有一侧声明关键身份字段。
- 同 participant_key 在新修订换对象；事件撤销恢复同 fingerprint；生命周期/身份决定/目录离开重入回到同终态。
- 元数据刷新保留旧原证据；错误 snapshot/fact/version；冻结 facts/locator/完整详情被损坏；原文 hash 与内容不符。
- 人工关联审核冒充来源确证；人工转录或机构名称冒充 online_verified/independent verified。
- 前后轴、配置、代际或年款借用；车型适配审核被用于声称官方 OE 或测试身份。
- 缺失成绩补零、覆盖当性能分、无方向指标推断优劣、重排来源名次、跨场绝对成绩直接总榜。
- AI 单引、双引、跨 claim 或 uncertainty 写入无桥推荐；流式 draft/直接 store、保存/导出绕过。

## 6. 接手文件

后端：`test_events.py`、`test_preference_interpretation.py`、`fitment_relations.py`、`recommendation_candidates.py`、`identity_contract.py`、`lifecycle.py`、`ai_test_contract.py`。共享与界面：`packages/domain-types/src/`、`packages/api-client/src/index.ts`、`test-events.tsx`、`test-preference-interpretation.tsx`、`personalized-home.tsx`、`ai-analysis.tsx`。历史冻结资料保持只读，新实施用独立计划与新 artifact。
