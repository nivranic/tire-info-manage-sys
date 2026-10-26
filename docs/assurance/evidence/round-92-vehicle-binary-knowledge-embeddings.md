# 第92轮 车型二进制知识索引与 Embedding 用途闭包

日期：2026-10-19。**知识索引、dense 与 Embedding 本地/Provider 用途闭包已实现；单次受管运行92个唯一测试全部通过。**生产首代来源的 local_structured 仍为 pending_review，Provider/export 恒为 false；本轮不授来源许可，不表示首代 ready 或完整 V1 完成。

承接[第91轮](round-91-vehicle-binary-consumers.md)，依据[冻结R92提案](../../../.artifacts/r92-knowledge-embedding-design-7173941929c049119f6e70777fe4ce62/proposal.md)与[原PDF合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)。冻结提案是实施前设计快照，其“未实施、未运行”不覆盖本报告的实际结果；原件字节保持。范围限四个生产文件、一个新测试模块、旧ingestion的窄fixture授权块及runner的一行模块登记/help计数；未改schema、Guard、ChildPolicy或Provider call_embedding。

## 唯一实际运行

[result.json](../../../.artifacts/r92-t-e1c74b8a093d/result.json)：20097B / SHA256 `968a102baa52caa16141f8401382e61988bed3ec6a676c7e9f921a925c6493ee`。Root独立核实92个nodeids、安全reports与JUnit逐项一致；collected/protocol started/executed/unique均92。276条阶段结果为setup/call/teardown各92通过，0fail/skip/incomplete、subtest0，runner/pytest退出码均0。三个阶段不累计为276个测试。

| 实际模块 | 范围 | call通过 |
| --- | --- | ---: |
| test_knowledge.py | 整模块 | 26 |
| test_embeddings.py | 整模块 | 29 |
| test_vehicle_binary_ingestion.py | test_binary_index_checks_before_cold_or_cached_search_and_embedding 精确函数 | 8 |
| test_vehicle_binary_knowledge.py | 新整模块，12函数 | 29 |

3whole＋1exact＝4targets/4模块；**159仅注册manifest长度，未运行全159。**旧knowledge/embeddings/ingestion合计63项与新29项均来自这一单次当前代码运行，无复跑；旧63不是改动前后对照证据。

37个受管parser child全部exit0/live0；resources_closed=true，metrics两个计数均0，非selfcheck拒绝/IPv6 probe/意外拒绝均0，正常数据库未启动，真实Provider/receiver调用0。Guard为Python audit/wrapper边界，不声称OS系统调用隔离。新模块的ForbidProvider、mirror、save_vectors哨兵均0；另有受控fake query用例在接收durable query后返回错误，不能把“真实外部调用0”写成“全部adapter调用0”。

## 已闭合的行为

- **全库head先核。**knowledge cold/warm、signature早返、dense过滤/cache及embedding config/capability前，先对全库vehicle current heads核完整性与local权利。tire-only过滤也不能绕过，坏行不静默移除。用精确head Verification取得只读capsule；坏链HTTP409 `vehicle_raw_integrity_failed`，完整但本地pending为403。binary OR固定首代身份阻止伪降文本。
- **文档与plan不洗白原件。**实际vehicle KnowledgeDocument绑定当前head/capsule及既有语义材料；错head/verification、缺snapshot、改payload或移除vehicle标记均以409 `vehicle_evidence_binding_failed`拒绝。plan预览只核local；build/reserve/fresh对全部selected vehicle docs核Provider，即使all-cached或实际inputs为空也不能提权。
- **durable授权绑定实际inputs。**fresh门使用独立`database.sessions()`与no_autoflush，只关闭自身reader，不改变caller脏对象或事务。index要求双plan_id一致，并以显式`{plan_id, allow_external_processing: True}`及kind重建request_hash。hybrid按严格KnowledgeSearch模型归一化durable search，再以显式flag及kind重建hash；缺flag不默认True。当前文档、plan fingerprint、冻结语义chunk及实际ordered inputs全部绑定；chunk比较text/hash/cache_id/privacy_class，允许cached状态变化，旧signature/cache key保持。
- **query用途独立。**hybrid只发送durable query；vehicle文档provider=false不误作query禁令，也不授文档出站权。structured hybrid空inputs只核local，已有vector/cache不成为当前用途许可。
- **拒绝与usage如实记账。**API在Provider safe_error外执行fresh门。仅确定未dispatch的本地拒绝可标失败并释放为零usage；已dispatch返回同名错误不得归零，receipt之后local状态变化仍保留实际usage。若本地完成写入失败，保持durable pending及reservation，不伪造完成。

新增29项覆盖pending全入口、warm/tire-only坏head、projection/plan洗白、cache/provider、durable consent与ordered inputs、实际派发前raw变更、hybrid query及caller reader生命周期、structured local、未派发零usage/重放、已派发与postcall usage、完成失败。真实历史S2在私有SQLite/ObjectStore中走离线actual parser child/receipt；mapping/deployment/directory及local-only权利均为合成fixture，不代表生产许可、在线采集、正式release或真人Golden。

旧ingestion仅增加717B module-local autouse块，以精确originalname/nodeid/private fixture graph限定原1函数的8参数local授权。原19个顶层定义（含decorators）保持，删除新增块可逐字节重建原文件。双方独立静审与Root核通过；旧head SQL/output AST、`_document/_vehicle_documents/refresh_index/INDEX_VERSION`及Provider call_embedding保持。runner仅新增module一行及help158→159。

## 字节与保全证据

683项source before＝after＝live，Root已独立复核；相对R91旧682项为6变、676不变、1新增、0删除。[source-after.json](../../../.artifacts/r92-t-e1c74b8a093d/source-after.json)：123142B / `3f4d80502cd8b2d756dad99f53d4dee98b50e1347042c7e561377df78f3b3f85`。

| 本轮冻结文件 | bytes | SHA256 |
| --- | ---: | --- |
| apps/api/tire_api/knowledge_index.py | 27059 | 1f0cacc34873f1ec427622099cbb04ef3ce9e90e49f231e5d44977df056310f0 |
| apps/api/tire_api/embedding_service.py | 15231 | a12bf06e94da1fc4f20a7b02cf365ffca3e04b2bba6baa5e1e0342c0fa9ac8cd |
| apps/api/tire_api/dense.py | 7710 | 7b038a8972ed36305881f1f0e3a3a3bd764075a81c871f10785cfe150430666c |
| apps/api/tire_api/embedding_api.py | 14204 | d393741cca4d86a358510728716dd69b86e3fb25fbb44b507e1f0a1b63761481 |
| apps/api/tests/test_vehicle_binary_knowledge.py | 24548 | 26e66643ebfce9f695a40bd3ef0d5e7debab8c0a7a0cc3a169a672d503560b7a |
| apps/api/tests/test_vehicle_binary_ingestion.py | 24741 | 58b13a8147da7415abfe97143d59a070506bdb2bc033d7f083085ce10b0e1d63 |
| scripts/run_api_worker_regression.py | 42790 | 85271a5fbc4dc1be3c01f4efb2b8fe823c2ce844f16c4ede58ea93ab4388a8c2 |

冻结提案10118B / `ed7d68690bc35c9c6a1df68df720b8cd52e9092713c31043784a1ed470e1732c`；[六源baseline](../../../.artifacts/r92-baseline-4db7e5b053094a92/baseline.json)1591B / `5294f07a5e7b24db9471b60d83f5d4f112eb2422ec5be7518476e09cf75eae03`。历史R91报告/seal、冻结设计与原PDF合同不覆盖。

S2显式采样为[s2-before](../../../.artifacts/r92-meta-e1c74b8a093d/s2-before.json) UTC `2026-10-19T08:16:28.8067520Z`及[s2-after](../../../.artifacts/r92-meta-e1c74b8a093d/s2-after.json) UTC `2026-10-19T08:26:26.4868074Z`，夹住实际run。两次与live原件均为3240150B / `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，原件位于`.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf`。显式前后采样、每次pre-use核及683源码稳定是三类独立证据。

R38历史文件`.artifacts/runtime/round38-before.sqlite`的actual before/after metadata与Root实际hash相同：25374720B / `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`；未打开历史库内容。

## 开放边界与下一入口

未验证live PostgreSQL/pgvector ranking、真实外部Provider、正常数据库升级、SDK/UI/Native或正式release。首代fetch/ready仍关闭，`requires_source_verification`保持；生产local pending为403、Provider/export恒false。完整PDF/V1 Gate及原Goal继续active。

下一R93的HTTP＋SDK地图与addendum仅完成静审，尚未实施；API可由既有runner受管验证，新增SDK `.mts`当前没有合法测试入口，只能给静态证据，不能称SDK已验收。本轮不索要Key/URL，不提交或推送。

机器seal候选为`.artifacts/r92-close-c0179e5b6a84/verification-final.json`，待4份文档冻结后由runner实际生成并经Root复核；此处不预填hash或提前称已封存。三个交接入口只追加新前缀，R91整个旧文件作为suffix保留其原字节及行尾。
