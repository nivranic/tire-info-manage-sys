# R136：来源材料未确认请求的停止采纳

2026-10-25。**R136限定范围验收通过，完整V1仍active。** 材料核心core-a三模块251／251且runner0／passed:true，固定后端独审已接受该源与严格核心批；扩展final-a的468个pytest均过，但runner因一次被阻止的urllib3 IPv6导入探针仍exit3／passed:false。Parser完整独立复跑r136p2为27／27且runner0；原Parser-a两项业务断言失败的根因仍未定位，不以复跑通过反推“修复已证”。最终d生产UI七场景／126检查passed，Root实际四图接受且新资源观察通过；最终运行独审ACCEPT，Root实际执行124项收尾检查全部通过。首两UI红批、c图拒绝及首次资源failed全部保留。

## 需求与范围

依据[原计划](../../plans/2026-10-25-source-material-stop-adoption.md)、[冻结消费合同](../../../.artifacts/r136-source-material-stop-20261025/wire-contract.md)与[计划独审](../../../.artifacts/r136-source-material-stop-20261025/plan-review.json)，补的是操作者明确停止一条未确认请求继续采纳的能力。原需求中的原始证据、追加历史、失败任务管理及幂等要求支持本片；原文没有逐字列出本功能名，不能写成原规格逐字要求。原UUID GET、本人历史与同UUID同payload replay原来已经存在，本片复用这些恢复入口。

停止是持久化的采纳决定：未来迟到执行不得再为这次请求登记object／document／成功或失败outcome；网络结果继续未知。停止不证明socket已终止、原件已删除或捕获失败；物理store.put可能已留下无引用对象。不会自动重POST、恢复下载、换UUID重抓或清理这些对象。

原C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0`仍封存为processing_unconfirmed，PDF未取得。本轮没有停止、恢复、重发或迁移该旧请求，没有打开其保留私库；新私槽合成验收不能追认为旧C2处理成功。

## 已落地的合同与文件范围

后端在`apps/api/tire_api/source_material_models.py`、`source_materials.py`、`migrations.py`增加不可变`source_material_stops`、031与原锁内仲裁。前端及SDK变更限共享`source-materials.ts`／导出、API client停止方法、原材料面板及必要CSS；没有另建查询旁路。详细来源见[后端实施便条](../../../.artifacts/r136-source-material-stop-20261025/backend-implementation-notes.md)、[前端独审](../../../.artifacts/r136-source-material-stop-20261025/product-review-frontend.json)及现已固定的[后端产品独审](../../../.artifacts/r136-source-material-stop-20261025/product-review-backend.json)。产品／静审接受范围与最终运行收尾分开。

| 边界 | 本片行为 |
| --- | --- |
| 状态 | request无outcome／stop沿用processing_unconfirmed；只有完整stop且无outcome显示stopped_unconfirmed。completed_at／failure_code／document／receipt仍四项null。旧三态stop:null，旧DTO缺省兼容null。 |
| 公共停止记录 | 仅`schema:'source-material-stop@1',request_id,idempotency_key,operator,reason,stopped_at`六字段。实际actor／session只在服务器核对，不以署名代替身份、不下发私有字段。 |
| 新API | `POST /v1/source-materials/requests/{原规范UUID}/stop`，精确payload为expected_request_id／operator／reason，200 effect为stopped／already_stopped／already_terminal。未知字段／类型拒绝，原因单段1–500、署名1–80。 |
| 身份顺序 | 管理员准入先于body错误；原ingestion lock内fresh核当前owner／admin、原request与expected ID。非管理员403；通过角色门的其他owner404。读取保持本人隔离。 |
| 仲裁 | 首个可信终态先胜返回already_terminal且零停止记录；同停止payload重放already_stopped，异payload409 source_material_stop_conflict。原UUID GET／历史／同payload capture replay返回冻结停止状态，replay不联网。 |
| 固定失败 | stop与outcome双存在、停止图／原请求损坏固定503 source_material_integrity_failed。停止提交回执未知固定503 source_material_stop_commit_unconfirmed；客户端只查询原UUID。 |
| 外部依赖 | 健康pending／stop只依赖冻结request元数据，当前policy删除／变更、TLS或对象库不可用不阻止停止。已有succeeded的already_terminal仍须原receipt／对象完整性核验，不能借此短路。 |

捕获在fetch／物理put之后、任何register_object／document／outcome／received审计之前，取得原锁后按原request_id重新db.get，并比对I/O前冻结fingerprint与owner。旧row可能已随db.close脱离Session，仅expire_all不足以fresh读取。Stop胜出则返回停止view，既不登记DB采纳也不补received审计。失败finalizer先rollback，再在同锁内fresh核request／stop／outcome互斥；Stop胜出不补failed／diagnostic审计。取消传播保持原合同，不能当成功捕获。

旧`test_robots_failure_audit_does_not_add_a_role_recheck`保留：网络阶段撤销管理员资格，不抹去可证明的原失败outcome与原session robots diagnostic。失败finalizer不新增当前role拒绝；新Stop和成功采纳仍严格重核当前owner／admin。这两条边界分别记账。

031只新增停止表、索引、不可变保护与ledger。020的sqlite_guards仍精确旧六条，停止三条由031安装器／after_create负责；R135旧030切片显式关闭031新门。历史夹具沿真实前驱到030后补字面020材料父表及旧JSON／receipt BLOB／行，核保全、重复升级和ledger失败回滚，不以当前全量create_all冒充旧库。旧vehicle_binary测试原tail漏030，本片分别补030兴趣bool列／版本与031表／版本断言，不把030 delta归到031。PG只做DDL编译，未接活PG。

## 首次红批、失败与修正

各批来源独立保留，不相加为一次全套执行，不用后来的通过追认旧失败批。

| 实际记录 | 结果及解释 |
| --- | --- |
| [首red-a](../../../.artifacts/r136-red-a/result.json) | 两模块43 executed／30 passed／13 failed，43个setup与teardown全过；失败在call阶段。764输入前后稳定、资源关闭、意外拒绝0。后来新增的坏图与锁竞争反例不归入这次首红覆盖。 |
| [首API-a](../../../.artifacts/r136-api-a/result.json) | 五模块360 executed／359 passed／1 failed，无skip／incomplete；setup／teardown360全过，源稳定、资源关闭、意外拒绝0。唯一取消向量漏接Starlette BaseHTTPMiddleware精确包装`RuntimeError('No response returned.')`。 |
| 取消修正 | 保存pre-json-decode原件后，仅测试在completion=cancelled且RuntimeError消息完全相等时接受该包装，继续核Stop唯一行、零DB采纳、零received／failed审计。没有改产品取消传播，也没有把API-a改成通过。 |
| [原始坏图专红](../../../.artifacts/r136-json-red-a/result.json) | 四向量0／4，setup／teardown全过，均在最终HTTP合同call失败；不是导入或环境前置失败。原红测试另存raw-json-first-red，SHA256 `27a189f962a6a7b2fc05c634359054bdd82b82968be5491368ae8ed621657c01`。 |

独审发现新Stop的JSON／DateTime加载可先于checked_stop失败，绕过固定integrity503；绑定request.payload和双存在outcome.receipt也存在继承的同类加载边界。四专红分别覆盖stop.payload原始坏JSON、stop.stopped_at坏串、绑定request.payload坏JSON、双存在outcome.receipt坏JSON；每例核本人lookup／history／replay／重复stop固定503，外管理员先404且历史空。产品只在owner过滤后查询、本人历史结果、原request刷新与Stop／Outcome读取的结果加载处，将ValueError／TypeError转固定integrity503；不吞DBAPI、权限guard或其他执行异常。Stop两项是本片新增类型，request／outcome两项是继承缺口，不能混记成031首次引入。

后增终态先胜重叠反例在capture持原事务锁、outcome INSERT尚未执行时用SQL event暂停；另一独立ASGI portal实际发Stop，并确认另一connection已尝试BEGIN IMMEDIATE且未完成后才释放capture，再核成功先提交／Stop already_terminal／零Stop行及唯一采纳审计。它补足原顺序“终态后再Stop”不能证明的锁竞争；新增前原件保存在pre-terminal-overlap。最终执行是否通过仍以下节新批回执为准。

PG函数体最终END是否必须分号的静态疑问经Root读取官方plpgsql-structure后撤回；产品和测试未因此改变，不记作产品修复或活PG验收。

## SDK、函数探针与生产构建

[SDK首红](../../../.artifacts/r136-source-material-stop-20261025/sdk-red-receipt.json)保留12旧例通过／4新例失败，tsc2、Node1；[SDK最终绿](../../../.artifacts/r136-source-material-stop-20261025/sdk-green-receipt.json)为tsc0、Node0／16例通过。只增加encoded原key的停止POST及调用方AbortSignal，旧六方法保持；SDK回执中较早材料TSX pin不代表当前界面通过。

[新生产函数探针红](../../../.artifacts/r136-source-material-stop-20261025/ui-stop-unicode-red-result.json)52向量有15失败，[同探针绿](../../../.artifacts/r136-source-material-stop-20261025/ui-stop-unicode-green-result.json)52／52。它以内存导出精确生产assertView／ReceiptDetails并用惰性替身导入，验证Unicode codepoint、Python whitespace／UTF-8、原因分隔符、规范请求ID及停止响应闭合；不执行React生命周期／DOM／HTTP／数据库。旧32向量是历史探针，不是当前52向量的验收，不把两次向量数叠加。[前端保留位置澄清](../../../.artifacts/r136-source-material-stop-20261025/frontend-review-correction.json)只修正备份说明：before-unicode-review保留早期候选／TSX／probe；旧32向量结果／回执与三端原noEmit回执仍在主工装目录原路径，原独审／hash链不改。

最终材料TSX为39935B／SHA256 `a7ccf32bc4174fdbe1026a2731cdd6f16d5fbb69804eca9f0e73d778c866ea76`。Web／desktop／mobile最新noEmit回执均exit0，使用`--noEmit --incremental false`，各自前后相关输入相同（[Web](../../../.artifacts/r136-source-material-stop-20261025/web-noemit-unicode-receipt.json)、[desktop](../../../.artifacts/r136-source-material-stop-20261025/desktop-noemit-unicode-receipt.json)、[mobile](../../../.artifacts/r136-source-material-stop-20261025/mobile-noemit-unicode-receipt.json)）。这些是起止点测量，不是全过程持续监测。

a136只冻结候选，未运行。[b136冻结独审](../../../.artifacts/r136-source-material-stop-20261025/build-freeze-review.json)核相对a135只有五个已审Web源pin、freeze时间及派生host hash／私槽名变化，其他门保留；[b136实际verification](../../../.artifacts/r118-material-workbench-20261021/web-build-b1361b2c3d4e5f60/verification.json)为passed，web-icons／web-next／web-pwa三监管阶段exit0，181源／8983依赖前后稳定、生成原件恢复passed、Next Job25／25全观察、active空、无forced_job_close。guard终态中8为own-exit-0，9为framework-parent-observed-sigint；不能概括为所有PID都exit0。verification为132473B／SHA256 `6af3a0cc02e521cae6c89d1674dde323190ac3a0c9a2908e84419132c799762d`，freeze SHA256 `7d3ee9c188f37a64bea8d02cf28f8e545a8e237a6cac1f191eb78ffd83687246`。Web freeze不绑定后端Python，后端须另连最终源与实际测试／fixture。

固定[后端产品独审](../../../.artifacts/r136-source-material-stop-20261025/product-review-backend.json)为ACCEPT，16630B／SHA256 `17f5f34c26e2fa68afbabd789acfd5d2d4c05fa49e3b992383edecbf3fc779a9`。它核三产品／七测试及历史门文件的源码／AST、strict core251回执与764输入前后map，10个当前pin均相等；core与扩展final-a源map完全相同。该独审明确保留final-a的runner3、Parser-a25／27和其审时后续复跑pending，不把浏览器／Parser接受写进后端结论。计划、前端、fixture／host、QA及b136冻结的ACCEPT也各自只覆盖其命名范围；原回执不因后续进展重写。QA独审记载审时尚缺后端review的状态是历史快照；现正式文件已存在，实际QA启动仍会重新pin它。

## 当前API／Parser批次与最终验收

[final-a实际回执](../../../.artifacts/r136-final-a/result.json)为11模块、468 executed／468 passed、pytest0，无skip／incomplete，764源前后稳定、资源关闭、other_unexpected_denials0；但raw_nonselfcheck_denials1且known_blocked_ipv6_import_probes1，原runner仍exit3／passed:false。这是被guard阻止的urllib3 IPv6导入探针，不豁免原门，不写“11模块严格全绿”。回执30577B／SHA256 `18c73dda5ccfc8bb0cc08391fef4cac7b8de19b98a0a44e1ae2d7f318eb3a5e3`。

[core-a材料核心实际回执](../../../.artifacts/r136-core-a/result.json)覆盖test_source_materials／test_source_materials_review／test_source_material_stop_migration三个完整模块，同一正式handle执行251／251、pytest0／runner0／passed:true，无skip／incomplete，setup／call／teardown各251全过；764源前后稳定、资源关闭，raw非自检拒绝／known IPv6 probe／other拒绝均0，managed children0／live0。回执19634B／SHA256 `c1195e0ea50f78ab9f04f80645ea67919eae7ea370796350ee50486a4995f399`。这是材料核心独立严格验收，没有豁免final-a的探针门；两批模块有重叠，不相加成719例单次执行或额外独立覆盖。

[Parser-a原批](../../../.artifacts/r136-parser-a/result.json)为两模块27 executed／25 passed／2 failed，pytest1／runner3；setup／teardown27全过，764源稳定、资源关闭，raw非自检拒绝／known IPv6 probe／other拒绝均0。35个真实managed_parser children全部exit0、live0，不能把它写成child crash。失败分别为实际A→B→A发布测试的evaluation.can_approve与inflight A→B→A测试的first review门；根因尚未定位，不能归为预存失败或长路径。Root对实际两棵sealed树测得最长247字符、lstat错误0。原批回执19728B／SHA256 `2142f753deb91e8a37eb914da4ccc0cf8e3c495730365dae96db0b75d19629e5`。

[r136pd单次有界诊断](../../../.artifacts/r136pd/result.json)只执行一例并通过，5个真实managed_parser children exit0／live0；Root观察首次／B evaluation的质量门均passed且can_approve、review201／activation201。它没有复现原两失败，不替代原27例、不证明原失败根因已经消除。临时诊断测试已恢复原字节，当前`test_parser_releases.py` SHA256 `d0fd3ce754ef48ab875c91b7210f34c18c7c188e2ce99655f961fd2c02675d32`；单诊断源码另存，不改旧回执。

[r136p2完整独立复跑](../../../.artifacts/r136p2/result.json)同一正式批次覆盖两模块27／27，pytest0／runner0／passed:true，setup／call／teardown各27全过，无skip／incomplete；764源前后稳定、资源关闭，raw非自检拒绝／known IPv6 probe／other拒绝均0。47个真实managed_parser children全部exit0、live0。回执19711B／SHA256 `c0fc49a7e3bc12d834cb0f537e661c1a2b853811fd733afa104ffcbe9db930dc`。这是真实完整复跑通过，不把原25过、单诊断1过与新27过相加拼绿，也不证明原两失败的根因或修复已确认；旧失败批与诊断原件继续保留。

| 收尾证据 | 实际状态 |
| --- | --- |
| 最终运行独审／源码绑定 | [Parser独审](../../../.artifacts/r136-source-material-stop-20261025/parser-regression-review.json)与[运行独审](../../../.artifacts/r136-source-material-stop-20261025/runtime-review.json)均ACCEPT；后端冻结源、fixture前后pin、实际UI、截图及资源已分别绑定。 |
| Root实际收尾 | [root-closeout.json](../../../.artifacts/r136-source-material-stop-20261025/root-closeout.json)实际exit0／124检查passed。最终报告和HANDOFF由随后独立文档回执绑定，不作为该checker的循环输入。 |

[fixture／host独审](../../../.artifacts/r136-source-material-stop-20261025/ui-adapters-review.json)接受有界改编，沿原私槽数据库、审计／Job、固定双端口、源pin与关闭链；合成material fetch只计数后故意RuntimeError，真实capture路由先提交reservation，不直接伪造request／outcome／stop行。[首QA独审](../../../.artifacts/r136-source-material-stop-20261025/qa-review.json)接受七场景源码，初版45717B／SHA256 `8e3f054cace5c157feb66caff14530c0418f25cc16e18edb0c38e18a31f3d298`可逐字重建并逆向恢复最终R135生命周期，Node --check0；该静审未识别后述入口hash／既有201两项工装问题，不能代替实际UI验收。8个预挂等待源码点（7response＋1event）立即arm，仍await原Promise；后续修正也不增加console／HTTP／cleanup／holds例外。

[首UI a136](../../../.artifacts/r136browser-a1361b2c3d4e5f60/result.json)实际failed，29个已完成检查／进入两个场景，Timeout停在independent_account_privacy_and_admin_guard。Root收handle98190 exit1并实际看failure.png仍在研究首页。QA初URL的`/#quality`在当前route-hash中不存在；[入口修正](../../../.artifacts/r136-source-material-stop-20261025/qa-route-correction.json)只在suite与generated各一处改为`/#/sources`，原件保存before；产品／构建／预算／错误门不变。首批host保留failed、api／web／browser监管进程0／0／3，forced空；Chromium自身0／null／server-close，浏览器输入／prepared runtime稳定、清理错误空，不等于该批业务通过。

[第二UI b136](../../../.artifacts/r136browser-b1362c3d4e5f6071/result.json)实际failed，52个已完成检查／进入三个场景，失败检查same_uuid_capture_replay_status。既有capture路由对同UUID replay仍返回201，QA helper默认200与原产品合同不符；[状态修正](../../../.artifacts/r136-source-material-stop-20261025/qa-replay-status-correction.json)只在suite与generated精确增加该call的expected201，另存before。Root实际看此批failure.png已显示停止状态／署名／原因，但该图不追认为完整场景通过；host同为failed、监管0／0／3、forced空，Chromium／输入稳定／正常清理另保留。两次修正后的历史generated45722B／SHA256 `9d3c6574f7757c449db0234e1dd2d05772db626d752b1acfa2ebdb9eb424572d`经各自补审后进入c批，不改产品、b136生产构建、请求预算或console等门。

Root对[首UI资源](../../../.artifacts/r136-source-material-stop-20261025/first-ui-resource-observations.json)与[第二UI资源](../../../.artifacts/r136-source-material-stop-20261025/second-ui-resource-observations.json)分别实际执行观察并exit0：各35指定PID缺席、query_error空、18986／18987均连接拒绝10061。分别记账，不相加为70个唯一PID，也不因资源关闭而将a／b改为成功。

[c136原始功能回执](../../../.artifacts/r136browser-c1363d4e5f607182/result.json)实际passed，七场景／118检查、9307输入前后稳定、prepared runtime稳定、页面／console／HTTP／外源／清理错误空。host实际exit0，api／web／browser三个监管进程自然0／0／0、forced空；Chromium0／null／server-close、fixture shutdown成功。实际Stop／原UUID预算及最终fixture均满足下述等式；这份raw功能passed原件保留。Root随后实际看四图，[c图审查](../../../.artifacts/r136-source-material-stop-20261025/c-ui-visual-review.json)为REQUEST_CHANGES：wide只有历史／页脚、两张390落在Golden／Parser／身份区，320落在来源区／toast，均未拍到命名的停止目标。PNG尺寸／hash及功能通过不替代像素审查，不能追认为视觉验收。

[截图目标修正](../../../.artifacts/r136-source-material-stop-20261025/qa-screenshot-target-correction.json)针对globals.css的smooth scroll与立即截图，只改suite／generated／generator三个QA文件并保存before：显式instant定位、等fonts与两帧、四图各核截图前后bbox及可见中心hit。原118业务／生命周期检查、产品、b136构建、HTTP预算与错误门不改，另增加8个截图检查。首截图候选47353B／SHA256 `0c6d6db537ceb8f0e5d517e835854f4d69e68caa6b7f62b62eab642c7360dca2`保留；独审又发现failure.png调用无target会丢诊断图，仅补[失败图fallback](../../../.artifacts/r136-source-material-stop-20261025/qa-screenshot-failure-fallback.json)，正常图仍强制target。最终QA47548B／SHA256 `ced7a754350478f899fd9a5b0b631129ddf48dc0a0af2e71ff6320ce0b35b44f`经[截图及fallback补审](../../../.artifacts/r136-source-material-stop-20261025/qa-screenshot-target-correction-review.json)ACCEPT，补审11513B／SHA256 `2b67a90bfa6050e52bbce6ecb231f74d9854770e43490de99cc2c962e691a3f2`。原metadata／首独审保留为历史候选，精确修正链不重写旧失败或旧hash。

[首次最终资源观察](../../../.artifacts/r136-source-material-stop-20261025/root-resource-observations.json)实际failed：35指定PID中，原构建记录的PID155532当时被Get-Process观察为conhost，其余指定PID缺席，query_error空，双端口均10061。Root的默认CIM身份补查不可访问，后来Get-Process已见该PID缺席；这些观察不足以断言原Node泄漏或PID复用根因，未kill进程、不改原failed回执。

[最终d136生产回执](../../../.artifacts/r136browser-d1364e5f60718293/result.json)实际passed，七场景／126检查（原118业务／生命周期＋8截图几何，不是126个独立测试），9307输入及prepared runtime前后稳定，页面／console／HTTP／外源／清理错误空；原业务预算与fixture等式全部满足。四个目标的前后bbox相同、可见中心hit均true，图名／尺寸不变。host实际exit0，api／web／browser三个监管进程自然0／0／0、forced空，三个终态门与双口关闭均true；Chromium0／null／server-close及fixture shutdown成功。result为2227667B／SHA256 `9d010150b89cd6d486aa287562171362257b8fcc8cceb528c35149117337e11a`。d的abort观察为expected3／actual1／finished-before-abort2；与c的6／1／5分别记账，不要求本来已完成的GET也abort。

[Root最终实际四图](../../../.artifacts/r136-source-material-stop-20261025/root-visual-review.json)ACCEPT，5917B／SHA256 `f23fbd4c69eb216cef5f0c1fe08913da37f32f30ba967d6f43475c5ca2b41d4a`：1365宽停止状态／UUID／时间／署名原因完整可读，390确认区的说明／显式checkbox／两动作与操作近图可读；320的状态／UUID／网络边界／时间可读，但两条登录toast遮住下方署名和原因，需关toast或继续滚动。接受范围只覆盖实际目标与这些画面，不保证任何位置全文无遮挡、完整WCAG／读屏／设备。新增几何门不能替代Root看图，c的四张错误区域图仍REQUEST_CHANGES。

[Root最终新资源观察](../../../.artifacts/r136-source-material-stop-20261025/root-resource-observations-final.json)实际exit0／passed，5760B／SHA256 `fd4ca450adb9ac4e6ded805aa931d2d71fae4d1108234c9258878f00cb27faaf`：35指定PID全部缺席、query_error空，双端口18986／18987均10061。此为新的独立观察，不覆盖首failed、不证明PID155532先前身份或根因。Python审计／Windows Job不是OS syscall sandbox；上述关闭汇总不证明每个DBAPI句柄关闭或私库已删除。

最终d与c各自完整覆盖三次APIRequestContext真实capture503预留，独立B context的404／403和空本人历史，再由实际页面显式停止、原GET／reload历史重开／同UUID replay201。第二stop先route.fetch200并取得真实已提交原body，再只向浏览器交付200空应用正文，真实JSON解析失败后只GET；它不是socket丢ack。第三stop真实bodyheld，经实际AccountDialog完成A→B→A、实际abort、release／settle／remove；delivered:true仅表示route.fulfill返回，不证明React收到忽略AbortSignal的晚body。同ID无退出重验未执行。新Unicode输入向量只改变DOM并在提交前恢复有效值，不冒称已向真实后端提交这些向量。d是完整新批，不借c的功能检查拼接后续截图。

UI等式在最终d与c各自回执中实际满足：stop POST按原请求1／1／1、原UUID GET3／2／4、退出／登录各2；页面capture／preview／download／source-query均0；harness capture=3seed＋1同UUID replay；最终合成material fetch／request／stop各3、outcome／document／object均0，轮胎来源／真实来源／Provider／model／embedding及三项fixture禁止尝试计数均0。坏GET停止视图拒止／干净GET恢复、所有page请求终结、held实际abort均过。最终d还独立通过新增截图几何门；c错误区域图片不能作为320／390目标布局证据。

最终[运行独审](../../../.artifacts/r136-source-material-stop-20261025/runtime-review.json)为37810B／SHA256 `6938fcc76cf20cb577225258a7d649ddb0e09edf2202df38ef24a24a3f8110ad`，仅只读命名JSON／源码／PNG，没有重开私库或重跑UI。它独立核92个页面HTTP均有终态、165个fixture源前后及当前一致、164个与core交集一致、四PNG双pin／几何及8份资源收据的35PID并集。9306输入直接匹配；唯一conhost差异来自审查工具实际为32位PowerShell7、System32经WOW64重定向，显式Sysnative原生视图1003520B／SHA256 `c86146188b78e484f32cc29e2331689659943b47689a85570342044f499938ac`与浏览器冻结期望完全一致，合计9307项对应。初次直接比较差异及原生视图证据均保留，没有改原pin或推断OS漂移。

[Root最终收尾](../../../.artifacts/r136-source-material-stop-20261025/root-closeout.json)由Root实际执行，同一handle87439收取exit0，124检查全部passed，31140B／SHA256 `85892b23d591ba6ecf312fcf7c977746fd30767a558fd147c14b1409e5b4cd36`。它只读命名JSON／源码／PNG并写新回执，复核当前产品与固定独审、原执行source-map、逐批结论、最终UI／四图／资源以及原HANDOFF备份；不运行产品、数据库、网络或服务。脚本静审、Root实际执行、真实浏览器和Root实际看图／资源观察各自留证。最终报告与HANDOFF在checker之后定稿，再由独立文档回执绑定，避免循环哈希。

## 未验收、交接与回退

本片限定范围已闭合。真实公网材料／PDF、专业精确SKU／真人Golden、真实Responses／Provider、正常或部署旧库整体迁移／活PG、原生宿主／真机、完整WCAG／读屏／PWA离线、完整V1继续未关闭；没有EPREL Key继续独立工作，不再询问。私槽合成与构建证据均不填补这些边界。

只可隐藏创建停止动作作为界面回退；原停止记录读取与所有成功／失败采纳屏障必须继续生效。不得drop停止表／删停止行／回写原request或outcome，不部署不了解031的旧二进制混跑；停止不授权后台到期重试或新UUID补发。原始失败回执、前置候选和各before副本保留。

报告worker维护此前草稿，没有修改产品／QA／HANDOFF或执行测试／构建／服务／数据库／浏览器／网络；Root保留草稿备份后完成本文最终更新。Root已写HANDOFF新前缀，原207804B／SHA256 `18d0a1e38243dd481acd106dd377c1911fb523b941cd0ef7aae6406a45439bc7`旧尾文完整保留，并负责最终实际执行、看图、资源观察和收尾。本轮正常／保留SQLite未打开，默认API未启动，未commit／push／reset／stash／clean，保留他人dirty。后续文档回执只核最终文档、链接、旧尾文与上述固定证据，不重新打开数据库或启动服务。
