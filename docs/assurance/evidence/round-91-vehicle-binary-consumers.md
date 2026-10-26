# 第91轮 车型二进制关系、AI 与报告消费闭包

日期：2026-10-19。**关系、普通/Device AI 与报告消费切片已实现；修复后单次受管运行275个唯一目标全部通过。**生产首代来源的本地结构化用途仍为 pending_review，Provider 与导出恒为 false。工程门通过不表示首代可上线或完整 V1 已完成。

本轮依据[冻结R91方案](../../plans/2026-10-19-vehicle-binary-consumers.md)与[原PDF合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)，承接[第90轮](round-90-vehicle-binary-governance.md)。主切片为 vehicle_raw、fitment_relations、ai_evidence、ai_analysis、reports、ai_execution、ai_streaming、ai_gateway 八生产文件；首次回归发现的非Web新库初始化问题另以 vehicle_binary_migration 的窄修闭合。未改 Guard、ChildPolicy、来源权限或旧pinned测试。

## 实际运行结果

最终自然完成的运行是 `.artifacts/r91-u-c96cd1dca114/result.json`，24579B / SHA256 `7086af3ac33828ccd1481a927a4ac39f7fa6c38c6a66acb8e74b6df1c421fe79`。Root独立核实275个nodeids、安全reports与JUnit逐项一致，825条阶段结果为 setup/call/teardown 各275通过；collected/protocol started/executed/unique均275，0fail/skip/incomplete，subtest为0，runner与pytest退出码均0。三个阶段不累计为825个测试。

| 实际模块 | 范围 | call通过 |
| --- | --- | ---: |
| test_ai.py | 整模块 | 35 |
| test_ai_stream_api.py | 整模块 | 14 |
| test_ai_stream_execution.py | 整模块 | 7 |
| test_device_ai_submit.py | 6个精确函数 | 6 |
| test_fitment_relations.py | 整模块 | 34 |
| test_interest_review.py | 1个精确函数 | 1 |
| test_reports.py | 整模块 | 21 |
| test_vehicle_binary_approval.py | 1个精确函数 | 1 |
| test_vehicle_binary_consumers.py | 新整模块 | 37 |
| test_vehicle_binary_dispatch.py | 新整模块 | 27 |
| test_vehicle_binary_ingestion.py | 1个精确函数 | 1 |
| test_vehicle_binary_migration.py | 11个精确函数，新增29＋旧门11 | 40 |
| test_vehicle_raw.py | 整模块 | 51 |

实际为8个整模块＋20个精确函数＝28个target条目、13个模块。**158仅注册manifest长度，未运行全158。**两个新模块共64项，初始化新增29项；本run另含其余182项既有回归。275全部取自这一次成功运行，不把首轮部分结果或R90的381累加为本轮覆盖。

## 首轮中断与三个失败的处理

首轮 `.artifacts/r91-t-84619f41d170` 已收集235项，安全progress仅证明137项具完整三阶段，其中134项通过、3项call失败；其余98项没有任何阶段结果，不能断言它们全部未进入protocol或setup。原session已不可恢复，后续匹配进程为0只是后续观测；原run没有正常终态证明，runner/pytest退出码、protocol started和resources_closed保持null。原result、test-reports、source-after缺失，不补造；安全progress和interruption原样保留。

三个红的参数由脱敏nodeids的稳定索引与源码顺序定位。以下原因是**静态确认的代码/夹具问题**，原安全报告没有异常正文，不倒填为实测IntegrityError或HTTP异常：

| 首run case | 静态原因 | 最小修复及最终复验 |
| --- | --- | --- |
| 92，旧非Web初始化测试 | preflight把仅含无关用户表的SQLite也送入要求四目标表齐备的旧库分类器，无法创建全新应用schema | 仅SQLite、无精确应用命名冲突时允许新建；已有应用残留仍走原legacy/current门，冲突view-only也在create_all前拒绝。最终旧关系34项及初始化40项通过 |
| 127，capture_size | 只改RawCapture.byte_count直接违反 byte_count=length(raw_body) CHECK，不能构成待消费的合法持久化反例 | 改为当前capture对应EvidenceObject.byte_count失配；参数列表/断言不改，最终consumer37项通过 |
| 132，encoding_downgrade | 改为utf-8但保留application/pdf，违反现有文本存储CHECK | 补application/json，保留固定source/首代身份，实际命中OR防降级门；最终consumer37项通过 |

初始化helper只反射sqlite_schema与当前已注册metadata所有权，不学习023预期定义、不新增模型注册或执行DDL。表名、显式index、精确ledger/FTS/辅助对象和保护trigger名按casefold查冲突；无关对象及同prefix的 knowledge_fts_personal 保留。旧schema_state及其他29个旧生产定义、原36个迁移测试定义逐字节保持；新增29项覆盖无关表/行/index/trigger/view/native helper保全、大小写及view-only冲突。非SQLite与023受控迁移合同保持，不能称活PG或正常库升级验收。

三个修复文件的原字节已保全。consumer只改damage函数两处，其函数外全字节及14参数顺序保持；另两文件只有新增初始化helper＋preflight替换、一个新增测试块。Root独立重建核和双方互审通过。没有修改旧run以伪装一次成功。

## 已闭合的消费行为

关系的所选快照、current head、列表/详情、preview和revision共用只读capsule。binary或固定首代身份均不能退回body.encode文本捷径；核真实原件/对象、completed provenance、schema/fact hash及精确Verification→QueryRun→Selection后才检查用途。坏件固定503，完整但本地pending固定403；坏最新head不回退旧head，列表不静默隐藏问题行。私有local-only许可fixture下，真实S2支持关系创建、复核、stale/ABA与保留旧binding的撤销；生产pending时撤销仍403。通知INSERT失败实际使关系与通知整体回滚，未验证外部通知送达。

新vehicle证据包核local用途；普通和Device的analysis/reservation核冻结vehicle引用与原件；Device早返回、直接reserve和无variant_id的车型包均覆盖。真正generate/stream前用durable request.pack_id重新核pack、实际body/config、精确vehicle引用与来源用途，不能靠替换内存包、剥标或旧reservation绕过。stream在start_execution之后、adapter.stream之前执行fresh门；取消会等待reader收尾。

新增reader用独立Session、no_autoflush，只关闭自身读取事务，不commit/rollback调用方，也不跨Provider await保留自身Session。dirty证据模型被拒，无关pending对象保留。**这不等于旧candidate/caller全部事务生命周期已修复**；candidate before_dispatch等旧路径仍有独立后续边界。

只有内部已确定本次尚未dispatch、在本地fresh门被拒时，completion才failed、answer/provider_response_id为空，usage显式input/output/total全零。它释放token reservation与pending，保留请求次数、claim和审计；零usage是本地记账，不是Provider返回usage。新测试另让受控fake adapter实际调用一次并抛同名错误，验证已派发错误usage仍为None、不会冒记零token。finish失败沿既有unknown/保守记账边界。

新报告冻结前核local用途；新导出、既有export重用和content下载在renderer/put/对象读取前核export用途。ForbidProvider.generate/stream哨兵均断言0；报告ForbidRenderer、object put、export content read均断言0。上述受控fake一次与真实外部Provider/receiver为0分开统计。纯旧pack、已完成answer、旧report读取/metadata操作及其body/hash/revision/renderer字节保持原合同，不回填新来源字段；source八键不加encoding/capture/mapping。

## 源码、S2与资源证据

本run682源码输入before/after逐项相同并与live一致，Root已独立重新hash；相对R90的680项为12变、668不变、2增、0删。相对首次R91的682项恰3变，其余679不变。旧test_ai_stream_execution仅新增局部autouse noop-reader fixture，原7个函数逐字节保持；其纯producer结果不代替真实fresh reader覆盖。冻结R91计划、原PDF合同、历史报告/seal和五个023静态fixture保持原字节。

| 主要回执 | bytes | SHA256 |
| --- | ---: | --- |
| .artifacts/r91-u-c96cd1dca114/source-before.json | 122968 | ee988c98d21801c427db2d02f4611fe0b9ba251b083a74329060ffd8cf941872 |
| .artifacts/r91-u-c96cd1dca114/source-after.json | 122968 | ee988c98d21801c427db2d02f4611fe0b9ba251b083a74329060ffd8cf941872 |
| .artifacts/r91-u-c96cd1dca114/test-reports.json | 146390 | 5204b475aaeb8e8286aae993fe041c5e574ba22c809722c5ec76f3d2b3c2312a |
| .artifacts/r91-u-c96cd1dca114/junit.xml | 42010 | c81105d5a21d7e86269beb3d5b4d1f718ac79f97cf944d8d96983593150463c0 |
| .artifacts/r91-t-84619f41d170/progress.jsonl | 92220 | 661653068083755226a92140ef355ad53d5551405cd80728f75a5025f1b69a68 |
| .artifacts/r91-t-84619f41d170/interruption.json | 7448 | b63e2ffece601872c740998eb77b181ad28d8490d4116072a9ef5a2b6e199de3 |

历史S2原件为3240150B / SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`。显式before/after采样包围最终actual run，两份和live原件相同；每次pre-use核是另一层证据，不混称682源码观测。

| S2采样回执 | UTC | bytes / SHA256 |
| --- | --- | --- |
| .artifacts/r91-meta-c96cd1dca114/s2-before.json | 2026-10-19T07:26:34.8857728Z | 274 / 65d5d58c6d6e4d99514f0f7050aa373abeaa6376c6c02007961682fbaa6823c0 |
| .artifacts/r91-meta-c96cd1dca114/s2-after.json | 2026-10-19T07:43:30.5637341Z | 274 / bf06343ba18fbd7cb94f07ba4cceac1ba86e2fb1e439b2993ab33bc729975972 |

最终run的80个受管child包括79个parser及1个非Web初始化，均exit0，live0；resources_closed=true，metrics0，非selfcheck拒绝/已知IPv6 import probe/其他意外拒绝均0，正常DB=false，真实Provider/receiver调用0。R38保全文件前后metadata一致，Root另实际hash确认25374720B / `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`未变，未打开历史库内容。Python Guard不等于OS/native syscall保证。

## 当前边界与下一步

真实历史S2只在私有SQLite/ObjectStore中离线重放，经actual parser child、receipt与采纳链验证。私有mapping/deployment/directory和local-only来源许可为合成fixture，不等于新在线capture、生产ready、正式release或外部真人Golden。正常库、活PostgreSQL、真实外部Provider、HTTP/SDK/UI/Native原件链与完整消费者/完整PDF/V1 Gate均未验收。

下一精确入口为R92知识索引与embedding四文件：全库current head在cold/warm、过滤及缓存早返前核local；tire-only不得静默绕过；plan仅本地预览，build/admission/reserve/fresh dispatch另核Provider，缓存不提权。hybrid只发送明确同意的durable query，不把document Provider禁令误套给query，也不把query许可扩成文档许可。该方案目前仅只读设计，**尚未实施或运行**。生产首代仍requires_source_verification，fetch/ready未开放；EPREL继续configuration_required，不再索要Key或URL。

最终机器封存候选为 `.artifacts/r91-close-2d58d7a34eb1/verification-final.json`，待本报告与三个入口落盘后实际生成并由Root复核，不预填hash或提前声称seal已完成。未提交或推送；原完整V1 Goal继续active。
