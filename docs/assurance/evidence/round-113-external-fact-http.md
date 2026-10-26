# R113：single-item事实HTTP/ASGI与SDK有限验证通过

2026-10-21。G2d v4单项事实HTTP合同已实施，backend/SDK静审接受。独立TS v2通过；ASGI v3的14主/0子全pass，Root与G1分别只读终核接受限定范围。ASGI v1前置失败、v2整批失败分别保留；不跨批拼接通过。验证覆盖新建FastAPI应用中既有external middleware、路由和owned reader的进程内HTTP/ASGI消息流程，不包含完整main.create_app/lifespan、TCP监听或真实材料验收。V1仍active，provider/export=false。

冻结合同：`.artifacts/fact-http-contract-20261021/G2D-SINGLE-ITEM-CANDIDATE-v4.md`，12815B，SHA `a15a9424a75450615dfd802f341bf06e4bdca6abdb5b8d481e261dc342fef6fa`。产品说明见[外部事实API](../../EXTERNAL-FACT-API.md)。

## 实现与边界

GET /external/v1/tire-facts/{variant_id}仅接source_id/query_id/verification_id各一次；四个ASCII ID，不接grant/owner/snapshot/URL/limit/cursor。main增加仅关键字external_fact_routing，默认空mapping；在state已赋后创建app专属OwnedFactReader并显式注入。旧无state FastAPI直接register入口保持可用，None reader在facts请求安全503；无多线程lazy构造、新env/文件loader、schema027或Web checkbox。

保留原external_boundary本机/origin/cross-site、Bearer认证、GET/路径allowlist及60/min预约提交；随后handler仅以_scope作前置拒绝，原Authorization getlist重新capture交reader，锁内fresh key/User/期限/revoke/scope/owner与许可/治理才授权事实。前置速率写与reader是两事务，不声称HTTP全链只读或同一事务。reader/governance/G2a维持R112 SHA不变。

成功直接返回G2a projected/projected/item，保留九facts、16identity、null/false/0、source_scoped和冲突名，隐藏Q/V/owner/grant/人工说明。JSONResponse编码后与SDK流读取均核65792B，超限整项拒绝；没有硬内存隔离宣称。固定401/403/503/404映射，存储坏/超限、跨owner、撤回/不适用和未mapping统一404。no-store/nosniff，无ETag/HTTP304或分页/刷新。

SDK新增tireFact、准确DTO与独立validator，root深度5/节点272，G2a同构精度/身份/Unicode码点printable及features排序，返回source/variant相关。静审修正合法speed ZR/(Y)、全字符串regex末尾LF拒绝及await前四selector/signal局部快照，deferred mutation正反例齐。package只补独立test:external-tire-facts入口，没有运行npm。用户说明为docs/EXTERNAL-FACT-API.md，明确可信factory导入默认main.app/Database的构造及目录副作用，lifespan初始化/迁移，不将示例作无副作用导入或执行证明。

旧test_external_api.py仅将invalid scopes示例facts:read换真正未知unknown:read；未运行该旧Python suite，不能记其已回归。新HTTP fixture种子仍直接真实KeyCreate/query service/governance调用，不能叫HTTP管理/main/lifespan验收。

## TS v2独立批：已通过

Root唯一36eebb exit0，独审只读终核ACCEPT；receipt .artifacts/fact-http-sdk-verification-20261021/run-741c0684f6f14bf587457b5b53b7519f/receipt.json，10797B，SHA d6fda1fb943d78b344a31b1349fa98d958264b9275d9ded6b380e7cef3305889。

三目标types各exit0、stdout/stderr0；三合成runtime分别136新facts、59旧external、47inventory检查，exit0，stdout115/113/112B、stderr各183B（非空），无timeout/forced。21关键pins before/after全match并Root live无drift，非完整依赖closure；12流length/hash独核匹配。SDK assertions是检查计数，不是命名test ID序列，也不代表真实HTTP/账户/许可或浏览器网络。

v2 launcher14634B SHA ce548aa3d66b6a9677d205df659a5e1f03a423dd0ee0bc35af5aaa5d7ad56a35，pins4811B SHA 1ddb57b1098052e2141101110c127fc3eb0ab0ae451e8b7431742db88c4f1e3c。v1候选完整保留，因静审修正而未运行，不能称v1失败批。

## ASGI v1独立失败批：完整保留

Rootfreeze436436生成1360关键pins（400736B，SHA 81b854c78f1f0335db210e668cf20698cbea2778548475366484cbf40d2b5ded），Root live721f73 drift0。唯一run6261ae自然exit1，receipt .artifacts/fact-http-verification-20261021/run-338ad5ed4f8a4476ba2d43da7b0526af/receipt.json，16842B，SHA 82fb786bbd31eb05cbc9a87236925313f5b78222295a1a70a64e68191320ef28。

0主/0子、0SQLite、0fresh/0remain、0ASGI requests/responses/nonempty/bytes/management；14为预期而不是实测通过。19bootstrap判据真、7probe各1，仅4次预期files拒绝，其余denied0；stdout9545B/stderr0、自然child1，无timeout/forced，1360pins首尾unchanged。失败在selfpipe_capability_v1.py:108复合pair_binding校验，唯一harness_error RuntimeError；driver/fixture/test尚未导入执行，不把这一前置失败说成事实路由失败或产品已受验。

selfpipe记录窗1/new_socket_calls2/bind1/connect1、window_closed/thread_verified真；branch=not_constructed、pair_verified/temporary_listener_closed/pair_closed假。没有errno/winerror。复合判据尚不能仅凭此回执细分失败条件；G1在静读CPython accept包装与audit事件差异后另作最小候选，不能把推测写成已运行证明。已知loop finally回收代码保留；pair_closed为假不能改写为通过。

新runner/fixture/driver/selfpipe/tests与launcher/freeze均新目录CreateNew；v1全部源码/pins/receipt保留不改。正常FastAPI+external_boundary+路由/reader的ASGI scope/receive/send是拟验证链，无TestClient、HTTP listener或TCP请求。受审单次Windows SelectorEventLoop selfpipe能力约束exact code/path/thread、真实socket对象/peer；必要自唤醒native/fallback不等于零socket或OS网络隔离。

## ASGI v2完整失败批：分别记账

Root唯一941af6/session90115→8bfcd2 exit1，receipt .artifacts/fact-http-verification-20261021/run-8a3ae19d1d88418d942ce13b9b37ff77/receipt.json，24183B，SHA 51070eb57bef66c1216757be6ce1c813010f3d12de3b4440504a8f56105fb3dd。1371pins（403552B，SHA e9b6ed6136ed22acc6528797b40bec81e1ce718788ba814e8529f2a514032391）unchanged。

14主开始/完成，11成功/2失败/1错误，0子；67requests=responses、10非空fact200、12680响应字节、HTTP管理成功0；391SQLite、14fresh/0remain；stdout14602B/stderr0、自然child1、无timeout/forced。整批failed，局部非空事实响应不能替代完整验收。

v2 selfpipe实际为stdlib_loopback_fallback：窗1/new2/bind1/connect1；闭窗/thread/pair/临时listener关闭/pair_closed全真，diagnostics四必要标志和accepted_endpoint_registered均真。v2固定代码把唯一未曾记录创建事件的accepted端严格绑定到实际已审connector、listener endpoint、精确socket类型/协议与双向peer后登记；原审计allow事件/调用链/线程/次数cap未放宽。v1旧回执没有该诊断，仍不回填其具体复合失败分支或断言旧根因已证明。

三处issue均在新测试：test01/test13指纹比较未排除真实ApiKeyMinute表，属于同一处硬编码表名错误；test10修改不可变ApiKey字段，真实trigger在HTTP前以IntegrityError拒绝。Root静审与G1仅修新测试：改用ApiKeyMinute.__tablename__；另INSERT新UUID、正确BearerSHA但坏seal的key，保留真实HTTP401/无rate断言，不改或移除immutable trigger。新test_fact_http_v3.py与runner_v3另建，v2所有证据保留。

## ASGI v3独立成功批：限定范围接受

Root唯一556982/session82932→3bfabb exit0；Root4645f6独核ACCEPT，G1随后独立只读终核ACCEPT，没有重跑。receipt：`.artifacts/fact-http-verification-20261021/run-c77d9862d8a1458b91ae5d4ee6e29e0b/receipt.json`，18978B，SHA `f6c450979a7074ee1b66cc79dc40a7667a175ffa372f1fa437a0381943b83493`。pins v3为1380关键输入，405856B，SHA `1cfb85118dbb3858153e178721146d272b140da1f71d14bc76b80db5951590c1`；首尾/live全部匹配、无重复，不是完整传递依赖闭包。

14主/0子全pass，fail/error/skip/issues0；pins.expected及receipt.expected/started/completed四序列同序，各14唯一。68 requests=68 responses、10次非空fact200、12723响应字节、HTTP管理成功0。393次SQLite连接、14 fresh/0 remain，现场临时目录t为空；stdout11818B/stderr0，自然child0，无timeout/forced。`normal_database_or_service_started=false`。

14主覆盖：非空事实与真实304查询复用snapshot；旧sources/webhooks scope兼容；Bearer形状/无cookie身份；封闭selector和方法/路径；本机/Origin/cross-site边界；跨owner/缺证同一404；外层auth后真实revoke/withdraw锁内fresh重核；共享60/min预约；坏seal不耗rate；source_scoped/unknown/人工抑制；mapping复制/默认空/旧注册兼容；GET业务写仅rate；容量/schema固定错误。304来自内部query的live_verified_304/not_modified采纳，外部facts响应仍无HTTP304。

selfpipe实际为`stdlib_loopback_fallback`，window1/new_socket_calls2/bind1/connect1；window_closed/thread_verified/pair_verified/temporary_listener_closed/pair_closed均真。diagnostics的`loop_identity_verified`、`pair_objects_verified`、`pair_peer_match`、`pair_registration_verified`、`accepted_endpoint_registered`五项均真。19bootstrap判据真，7probe各1，仅files4预期拒绝，其余denied0；Winreg基线与system/自然缓存保持。单次严格selfpipe能力使用真实loopback socket；没有HTTP listener，不宣称零socket或OS网络隔离。

v3仅修新测试两处逻辑及imports：使用真实`ApiKeyMinute.__tablename__`；另INSERT新UUID、正确BearerSHA但坏seal的新key，以真实HTTP401验证不耗rate，原immutable trigger保持。runner只切换测试module/14ExpectedId前缀。selfpipe_v2/fixture/driver、所有产品/SDK不变；SDK不重跑，schema及selfpipe11键(含diagnostics5bool)/http_driver5键与14/0/14成功门不放宽。v3 launcher/freeze从v2_final精确派生，另hard核+pin旧v1/v2 receipt/pins，旧SDK-v1和R112-v1支持路径保持。

最终新工装：runner_v3 41528B/SHA `4b205d62b2da20deb0fdcd88dfafb6cb8e52f319166f3fe716afe66c236dedb3`；test_v3 15831B/SHA `7db8455650631bd9a60569b3a4e2610f3be21f2032a26dd1deeb5be05e8a14d9`；launcher_v3 31109B/SHA `617fee5bb848af2b91993f82043ef94b3e65cfa1331a89738a1aa766991c5404`；freeze_inputs_v3 10207B/SHA `b2c985a26027cf25e9e670fb0fa2c31b82fc8588ff271e8375db35fa15cc0f48`。static-v3 1624B/SHA `20e872812a2e9e5bc13dc41bdcc0389f1609235589288b5d28bc6b4f78fbbbb8`仅为静态回读，运行证明以本批receipt为准。

v2实际选用`freeze_inputs_v2_final.ps1`；初版`freeze_inputs_v2.ps1`是未运行候选，曾误替换两旧支持manifest引用，final已修回。全部候选、v1/v2失败批及pins/receipts保留，不合并计数、不改写旧结论。

## 保全与尚未验证

HANDOFF原基线122582B、SHA `3262225c1e03b6f0c0687af33e8740647212b2fda8c184a297e32ab06cc2398d`已CreateNew保全于`.artifacts/fact-http-report-20261021/HANDOFF.before.md`。新前缀候选把原字节完整保留为尾文；独审和正式应用单独记账，不将文档回读记作额外产品测试。

完整`main.create_app`、lifespan、CORS与全部middleware组合未运行；导入默认main.app/Database有构造及目录副作用，lifespan会初始化/迁移，未在正常库启动。Key发行/query/governance fixture通过真实函数直接调用，HTTP管理成功0；registry仅合成fetch，无真实来源、材料、Parser或法律许可真实性证明。没有正常库/实际PG、TCP/HTTP监听、浏览器、Provider、设备或完整V1验收。

Python hook不是OS sandbox，native/cached活动盲点及capture无硬内存限延续；Node批也不是OS sandbox。R112 v2 `service.transport_cache OperationalError`根因未知、未修复；新增静审仅指出宽body排序/临时资源风险，缺原sqlite_errorcode，不把推测作根因或本片作修复证明。未重跑旧Python全suite、R112旧25主/41sub或其他旧治理批；SDK仅上述独立v2批。

本片是single-item HTTP/SDK增量；原规格要求的cursor分页、完整main/主入口集成与真实材料恢复仍是后续独立产品缺口。分页须先冻结一致的reader/治理/cursor合同；完整主入口与真实材料分别取得自己的运行与许可证据，不能用本片ASGI或合成fixture替代。不commit/push，不修改旧报告/工装/pins/receipts；V1仍active，provider/export=false。