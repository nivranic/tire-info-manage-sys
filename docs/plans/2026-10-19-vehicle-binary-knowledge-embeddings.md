# R92 知识索引与 Embedding 用途闭包建议

仅只读设计，未实施、未运行。R91 正在运行时源码闭包保持冻结。最小范围为 knowledge_index.py、embedding_service.py、dense.py、embedding_api.py 四生产文件；不增加 gateway、schema、policy、Guard、ChildPolicy 或新的审计脚本。

## 四文件实施入口

1. **knowledge_index.py**：把现 `_heads` 的车型 head 查询原样提成内部 helper，保持 source/vehicle 分组及 verified_at/id 排序。`_check_binary_vehicle_heads` 对所有 head 的 binary OR 固定首代身份分支，按 head 的精确 verification id 调 R91 原始 `checked_vehicle_consumer_capsule`；先核全部原件/formal 链，再逐一 `require_vehicle_consumer_use(..., 'local_structured')`。在 signature/warm 早返、任何过滤、文档构建或 DELETE/INSERT 前运行。坏链沿用现 HTTP409 `vehicle_raw_integrity_failed`，用途为403 `vehicle_structured_fact_use_not_allowed`。不使用 ai_evidence 的503包装，不降为旧文本或过滤掉未授权车型。

   同文件提供窄只读 document 绑定 helper：由当前 head/capsule 产生现有 `_vehicle_documents` 等价预期字段；绑定 KnowledgeDocument.id、kind/source、payload.reference、现有完整 payload/语义材料，保持原 payload/reference/signature/INDEX_VERSION。判别同时看当前 binary head 的预期 doc id、vehicle 标记和固定 source/首代值；去 kind/source/reference 标记仍不能把原 vehicle doc 洗成 tire。已识别却缺 snapshot、错当前 head/verification、错值或无法证明绑定，409 `vehicle_evidence_binding_failed`。不扩大投影以添加 verification/raw/capture 字段。

2. **dense.py**：`current_materials` 在 `_filtered_statement`、document_chunks、cache 查找之前运行同一全库 current-head local 门；选出的实际 vehicle documents 再绑定 capsule。直接内部调用和 tire-only filters 也不能跳门。不改 coverage、cosine/RRF、mirror 格式与语义 cache key；已有向量只是内容缓存，不授予当前 local/provider 权利。

3. **embedding_service.py**：`prepare_plan` 在 config/capability 检查前先跑只读全库 local 门（不提前 refresh/写 index），无 binary 时保留原 config/privacy/批量错误顺序；随后 refresh 门及 document 绑定通过后才构造/插入 plan/audit；plan 只是本地预览，允许 local 的私有 fixture 可以预览 binary，不因预览授予 Provider。`validate_plan` 继续核 owner/过期/fingerprint/model/text_contract/current content，新增绑定和明确用途参数：preview/local 与 build/provider 分开，build 对所选每个 vehicle 文档核 provider，不能只核 missing chunks。缓存全命中也不能使 binary build 成功。

   `reserve_request` 在 budget_usage、request flush/audit/commit 前再核全库 local 与本次用途；index 从 server-owned plan_id 取持久化计划与材料核 provider，防直接 reserve 绕 admission。真实无 binary 的旧直接 reserve 单元合同和预算错误顺序保持；不要为无关旧 synthetic payload 增加通用新格式约束。若 binary 相关却没有可证明的 durable plan/doc 绑定，固定绑定409。

   同文件实现 fresh dispatch reader：接 server-owned database/request_id、实际 config/inputs 与必要 actor；独立 `database.sessions()` + no_autoflush，只读，不 ingestion lock/refresh_index/commit，也不触 caller Session。按 durable row.kind 重新取 plan/query；核 actor、model_space/实际模型维度、请求 hash/显式 consent、plan fingerprint/owner/有效期/text_contract、当前 head/capsule 与实际材料。index 用 durable plan_id/input_hashes 与当前重新生成的 chunks 精确绑定 actual ordered inputs，任何文本替换、空/丢失 durable 绑定、标记剥离或降级均拒绝。缓存状态改变不授新权，不把调用方 plan/deepcopy 当权威。hybrid 由 durable query payload 重新解释 filters，actual inputs 必须仅为该 query.text，保留 query 自身明确 consent/config/privacy 合同；只核当前材料 local，不把 document provider=false 误套为 query 禁令或 query 许可。reader 的 Session/transaction 在返回前关闭，只返回普通数据；同步 worker 内结束后才进入 asyncio.run/embed，不新建后台 DB task。

   **durable consent 的精确重建**：index 先核 `row.kind == 'index'` 且 `row.plan_id == row.payload['plan_id']`、合法且非空；从该 durable plan_id 重建原高层 body `{'plan_id': row.plan_id, 'allow_external_processing': True}`。hybrid 先核 kind，用现有 `KnowledgeSearch` 严格解析 durable row.payload，并核其规范 `model_dump()` 与持久化原 shape 一致，再重建 `{'search': search.model_dump(), 'allow_external_processing': True}`。二者均在重建 body 加上 durable kind 后，按现有 `digest({'kind': row.kind, **body}) == row.request_hash` 精确比较，才能证明当初包含显式 True 的原请求；绝不对持久化缺失 flag 用 `.get(..., True)` 补授权，也不以传入布尔值为证。

   index 即使 actual inputs 为空/全部缓存命中，仍先证明非空且完整的所选 durable plan/document 绑定并核所有 selected vehicle 的 provider。`input_hashes` 必须显式存在、类型合法、与实际有序 inputs 逐项匹配；缺字段、空 plan/document 集合、文本非空却 hash 空、或其他无法证明的 binary 绑定固定409。显式 `input_hashes=[]` 仅表示完整绑定的真实无外发分支，不能跳过 selected-doc provider 门。结构化 hybrid 的空 inputs 只需 local，不凭空构造一次外发 consent 或套 doc provider 门。上述新格式/consent约束用于真实 dispatch 和 binary 相关调用，不给无 binary 的旧 synthetic 直接 reserve 增加通用格式门或改变其既有预算错误顺序。

4. **embedding_api.py**：保留同键同内容历史 replay 和 run list/detail 的原只读合同；不同 body 先409。新 status 在 capability/config 之前先走只读全库 local 门，故有 pending binary 时即使无 pgvector/config 也显式403；无 binary 时原 capability 结果保持。新 build/hybrid 在既有 replay/同键冲突、显式 consent/current-question 门之后、config/reserve之前跑只读全库 local 门，真正 embed 前立即 fresh；index inputs 为空的缓存分支也须核本次当前 local/provider 用途后才能写新完成回执。structured hybrid 无外发，但 search 与 reserve 之间仍再核 local，防来源状态变化。

   fresh 本地拒绝在 `call_embedding` 之外处理，直接 `complete` 固定本地安全码，不丢到现 gateway.safe_error。仅内部已证明 adapter.embed 未调用时，失败追加 completion/result=None、全零 input/output/total tokens；释放 token reservation/pending，保留 billable 请求次数和审计，不删 row、不再 reserve/重试。允许本地码仅 structured_fact/provider/raw_integrity/evidence_binding 四个 vehicle 固定码。完成写入失败保持原 unknown/保守记账，不声称释放。Provider 抛同名字串、超时、可能已调用、事后 refresh 被拒或 storage failure 均不归零：已有 receipt 保留实际 usage，未知 usage 保留 reservation。事后本地403/409可保真固定码，不能广义 except 伪装 storage failure；先 rollback 自己本次失败事务再沿现 complete，不改已完成历史。

## 必要测试

旧必要集合是 **63 cases**，不是63个模块/CLI target：test_knowledge.py 26、test_embeddings.py 29、ingestion 的 binary_index 精确函数8（whole2 + exact1，共3 CLI targets/3模块）。这是源码 AST 静态展开，非 collection/运行结果。

旧8case原函数逐字节保持，均硬断言完整性409；只新增 module-local autouse fixture，先检查精确 originalname/nodeid，仅这8case的 fixture graph 安装私有 local-only resolver；provider仍恒false，其他函数不受影响；不得 patch integrity/helper 或 HTTP状态。原有 warm 搜索/plan成功及破坏后409继续证明原链；其余旧 ingestion 函数保持。

新单独非pinned test module 复用 actual S2 受管 child/采纳 fixture；聚焦：

- 生产 pending：cold/warm、无 filters/tire-only/status/materials/prepare 均显式403，原 index signature/doc/plan/audit无变化；私有 local fixture 只证明本地成功，provider仍0。
- 完整性/绑定：当前 head与精确verification、坏对象/formal、legacy encoding降级、doc标记剥离、plan空durable绑定、payload/label/chunk替换，拒绝前Provider/cache/mirror/新ledger副作用为0。
- build：新/旧plan、missing/all-cached、直接reserve、reserve后actual输入替换/原件或head变化；均真正到共享fresh门且 embed哨兵0；无vehicle旧路径保留原调用与缓存命中行为。
- hybrid：显式 consent=false与当前 local pending拒绝；私有local且 binary document provider=false时，只发 durable query 原文；替换inputs为doc文本/多条/别的query或篡durable绑定拒绝；不借doc权限授权query。
- durable consent反例：kind/hash与原body不符、index两个plan_id不一致/缺失、hybrid search缺字段或非规范shape、原flag为False但调用者传True、缺input_hashes/非空inputs配空hash/空doc集合均拒绝；cache-only index仍核provider，structured hybrid空inputs保持local；旧无binary synthetic预算单元保持。
- ledger/lifecycle：确定本地未派发失败零usage且request count保留、pending/token释放；Provider同名错误/timeout/after-dispatch变化不归零；completion失败保守；reader Session已关、caller dirty未丢、reader无autoflush/无跨embed事务，replay不第二次调用。

不修改 embedding_gateway.py：本地门在其 safe_error 外，Provider错误继续既有sanitize。也不改 embedding_budget/models/text/knowledge.py，除非未来独立静审发现四文件无法闭合的新必需路径，再明确扩范围。正常库、活PG、外部Provider和完整V1均不在本设计证据内。
