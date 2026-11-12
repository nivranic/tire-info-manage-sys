# 2026-11-12 续作记录

> 最新通用PostgreSQL完整运行47项检查及204项受管回归通过。后续pgvector独立10项运行／12项业务检查通过，149张业务表恢复指纹一致，相关回归55／55通过。既有开发库015→032副本升级、恢复及回退演练也已通过。前次记录保留历史范围，最新结果、原失败及剩余范围见本文末节。

本轮从提交 `ea09acc` 的干净工作区继续原规格完整 V1 目标。代码已包含迁移032的来源地址迁移监控，旧交接卡顶部的R136状态需要结合后续报告阅读。本轮核对了新的真实材料候选，并修复来源地址迁移提醒读取损坏历史时的异常响应。

## 真实材料核对

核对依据为检索工具返回的出版者页面和PDF文本。下表记录采纳判断及其依据，保留原件捕获、精确SKU关联和真人审核的开放状态。

| 材料 | 原站证据 | 本轮判断 |
| --- | --- | --- |
| Aloksa、Novina、Protasenko，2026冬胎比较论文，DOI `10.30977/AT.2219-8342.2026.58.0.01` | 出版页与PDF首页均声明CC BY 4.0。PDF第1页说明使用测试、评论、厂商资料及概括观察，第3页表1按品牌汇总制动值，未建立具体产品代码与同场试验身份 | 许可依据可定位。作为背景材料候选保留，精确SKU／同场测试资格仍缺证。保存与导入计数均为0。[出版页](https://at.khadi.kharkov.ua/article/view/346125)、[PDF](https://at.khadi.kharkov.ua/article/download/346125/348428/843694)、[许可页](https://at.khadi.kharkov.ua/Licensing) |
| Liang等，2020滚阻／抓地研究，DOI `10.1177/1687814020981173` | 出版页声明CC BY 4.0。Test tires段明确将表1的性能数据追溯到参考文献17，后者是2016年汽车之家测试 | 该文可用于定位研究与数据引用关系。表1的原始测试出版者须继续追溯，样本的完整SKU身份与原始数据许可均待核对。汽车之家原链接本轮由工具返回超时。[论文](https://journals.sagepub.com/doi/10.1177/1687814020981173)、[引用的原测试](https://www.autohome.com.cn/drive/201608/891160-2.html) |
| Goodyear德国EfficientGrip Performance 2产品页与TÜV报告线索 | 产品页链接路径含产品代码542251，页内测试脚注声明2019年由Goodyear委托TÜV SÜD，测试尺寸另有说明。网站使用条款的版权段要求复制前取得书面同意 | 产品页代码和脚注中的参测身份需各自核对。原件保存许可仍待证明，策略配置和材料捕获计数均为0。[产品页](https://www.goodyear.eu/de_de/consumer/tires/efficientgrip_performance_2/205-60-16-92-V-542251.html)、[条款](https://www.goodyear.eu/de_de/consumer/terms-of-use.html) |
| NHTSA公开的FMVSS 139报告 `139-SSS-20-107` | PDF载明ACCELERA ECO PLUSH、165/65R14及测试样本DOT标识，报告页面同时印有Smithers版权保留声明 | 样本身份与耐久／高速试验线索可定位。报告发布主体与承包商权利需继续核对后确定原件保存依据。捕获和导入计数均为0。[原报告](https://static.nhtsa.gov/odi/ctr/9999/TRTR-6283767-2020-001.pdf) |

旧KIT C2保持交接时的封存状态。真实精确SKU正例与外部真人Golden继续开放。本轮材料核对未产生新的TestEvent或SKU关联。

## 来源地址迁移提醒的历史解码故障

`source_page_url_monitoring.py` 原先在列表及 `require_url_move_notification` 中直接装载ORM行，再调用历史引用校验。SQLAlchemy会在装载行时解码JSON和时间字段，损坏值会使执行提前抛出异常。

新增六个端点反例覆盖两种损坏与三个动作的笛卡尔积。两种损坏分别为事件query中的非法JSON、通知delivered_at中的非法时间。三个动作分别为历史列表、详情读取和标记已读。损坏记录在测试自己的新私库中构造，测试移除该私库相应的更新触发器，以模拟外部损坏后的保留数据。

首个标准受管批 `urlbad-r1` 收集／执行6项，全部在call阶段失败，setup与teardown各6项通过。独立诊断批 `urldiag` 重现同六例，记录JSON场景的 `JSONDecodeError` 和时间场景的 `ValueError`，定位到列表和单条读取的行装载语句。两批均输入稳定、资源关闭、非自检拒绝0。原失败回执保留在各自本机槽中。

产品新增一个由列表及单条读取共同消费的行装载函数，仅捕获 `ValueError` 并沿用 `source_page_history_invalid` 的固定503响应。JSON解码错误属于该异常族。测试继续断言响应不回显损坏片段，并通过直接读取read_at确认失败的已读动作没有更改已读状态。另有两个边界反例确认DBAPIError与RuntimeError按原异常实例向上传播。

## 验证与后续

最终标准受管批 `urlbad-r2` 在同一批中完整执行以下四个模块。

```text
apps/api/tests/test_source_page_url_moves.py
apps/api/tests/test_source_page_monitoring.py
apps/api/tests/test_monitoring.py
apps/api/tests/test_monitor_conditions.py
```

收集、协议启动和实际执行均为127项，127通过，失败／跳过／incomplete均为0。`runner_exit_code=0`、`passed=true`、`sources_stable=true`、`resources_closed=true`。`raw_nonselfcheck_denials`、`known_blocked_ipv6_import_probes` 和 `other_unexpected_denials` 均为0。`normal_database_started=false`、`real_provider_or_receiver_calls=0`。六个损坏历史反例和两个异常传播反例均包含在该批中。

本机结果文件为 `.artifacts/urlbad-r2/result.json`，SHA256为 `f745d81c5bb44ad4331c951686d8b4e533aea4fb4ec324dbfbaea387a7270471`。首个红批和独立诊断批分别保留在 `.artifacts/urlbad-r1/`、`.artifacts/urldiag/`。这些目录沿用既有Git忽略规则。

本次产品改动为后端的行解码边界与回归测试，校验了真实应用路由和合成私库。本轮没有重新执行浏览器、前端构建、全量API／Worker、Provider和原生设备验证。PostgreSQL的部分实测结果见下节。交付复核重新计算了上述结果文件SHA256，与记录一致。

## PostgreSQL初期实测停点

使用既有 `scripts/verify-postgres.ps1` 和 `scripts/postgres_acceptance.py`，在本机原生PostgreSQL 18.3上创建全新隔离集群。监听仅在loopback，应用使用非超级用户角色，输入均为合成夹具。启动环境在独立进程内移除继承的业务／模型配置，默认数据库指向内存，AI、Embeddings和遥测关闭。本次环境 `vector_available=false`。

两次运行均通过隔离集群／应用角色检查及四个并发进程的空库初始化。随后均停在 `api_evidence_curation_and_fallback`。首次失败报告只有断言位置，因此给 `assert_status` 增加有限诊断字段，保留原断言。诊断记录期望／实际HTTP状态、方法、路径及结构化错误码，不记录请求体、凭据、完整响应或连接URL。

第二次运行确认，`POST /v1/tire-variants/{variant_id}/fact-revisions` 期望201，实际返回403，错误码为 `admin_required`。现行路由有 `Depends(admin_guard)`，验收脚本在该请求前没有注册或登录管理员。下一步应先让验收夹具经真实认证入口取得管理员会话，再继续执行后续断言。

| 本机回执 | 结果 |
| --- | --- |
| `.artifacts/postgres/pgverify-43ae2a889f7443d797df1bcd2691a5e7/report.json` | 首次失败，停在事实修订状态断言 |
| `.artifacts/postgres/pgverify-ea650fde00f445f18ae44796ea654c1d/report.json` | 第二次失败，记录403与 `admin_required`，SHA256 `ba4b39343292daf26780628b855df63e350980feaf23a8d23edf7489a6356c1f` |

两次脚本均输出服务停止。第二次交付复核额外执行该集群的 `pg_ctl status`，返回 `no server running`，并独立确认验证端口55452没有监听。首轮停止亦已有独立状态检查。失败回执和隔离数据保留在忽略目录。

当前可确认真实PostgreSQL的隔离启动与并发空库初始化。事实修订／回退阶段尚未通过，后续持久化、并发操作、迁移、dump／restore和029–032业务语义仍待验。实际部署旧库升级及pgvector能力继续开放。

认证修正后还需关注持久化辅助用例在共享数据库中重复 `register_admin` 的行为。代码阅读发现Parser、reparse及recall Parser辅助入口各自注册默认管理员，这一后续风险尚未执行验证，应根据下一次原始失败判断处理。

## 交付复核

交付前对三个改动Python文件执行AST解析，3／3通过。当前产品文件与回归测试文件的字节哈希均匹配 `urlbad-r2/source-after.json`，沿用本轮127项通过结果。

单独提取 `assert_status` 函数并使用本地构造的HTTP响应验证成功分支，以及含结构化错误码、非JSON正文、JSON数组三种失败分支。原断言均保留，诊断字段仅为上述五个键，路径不包含查询参数。该函数检查没有发起HTTP请求或导入产品应用。`git diff --check`通过。

完整V1剩余工作继续按原规格推进。材料方面继续追溯原始测试出版物、保存许可与完整身份，工程方面继续推进真实Responses链路、正常部署升级与平台验收。候选来源的后续导入应使用已具备的捕获／测试事件链路，并保留本轮确认的数据出处与参测身份缺口。

## PostgreSQL前阶段45项验收通过

本节记录 `ac854dc` 交接后的继续实施。原始失败回执按原内容保留。

### 已确认原因及修正

1. 事实修订验收在匿名会话下调用管理员写入口。验证入口现在先经真实注册建立首个管理员，后续共享库阶段经真实登录复用该管理员。
2. 旧断言直接要求live、历史回退和304复验的完整variants对象相等。现行协议在 `field_resolution` 中携带当前数据状态及复验时间。本轮复用既有 `assert_frozen_query_evidence`，完整核对事实、身份、证据、候选、指纹及允许变化的验证元数据。
3. 隔离审核、重解析、Parser及召回Parser的持久化辅助入口各自假设首次注册。新增可选认证回调，独立调用默认注册，共享PostgreSQL验收显式登录。身份验收入口同样支持该调用方式。
4. 真实重解析返回 `parser_isolation_unavailable`。独立诊断定位至 `parser_runtime.py` 的架构变量校验，receipt中pid为null。本次执行环境缺少两项Windows架构环境变量。PostgreSQL验证入口沿用受管runner的做法，通过 `sysconfig.get_platform()`确定当前Python架构，设置验证进程的架构元数据。
5. 身份合并夹具缺少产品代码命名空间。两份新私库中的真实预览分别得到 `can_merge=false / stable_anchors=[]` 和 `can_merge=true / stable_anchors=['manufacturer_product_code']`。合成夹具现显式提供MSPN命名空间，与既有身份测试口径一致。

架构环境修正后的独立解析器实际返回2项，子进程exit0、`windows_job_object`、`reaped=true`。该运行使用8秒墙钟、5秒CPU和384MiB限制。诊断回执分别位于 `.artifacts/pgparse-diag.json`、`.artifacts/pgparse-env.json`。命名空间对照位于 `.artifacts/pg-ident-d1/result.json`。身份辅助入口的默认注册路径另在新SQLite私库验证通过，保留3条身份事件及重启／重放检查，回执为 `.artifacts/pg-ident-r1/result.json`。

### 单次完整PostgreSQL结果

最终运行目录为 `.artifacts/postgres/pgverify-fb6bd9e0260748df87ae81e5d08cd691/`。`report.json` 的 `status=passed`，共45项命名检查，运行退出0。SHA256为 `c21e5a1a1d31a01644181c3a43bb2294aa27e1abc7979b0abafe963c22eb1026`。

| 验证范围 | 实测结果 |
| --- | --- |
| 数据库 | PostgreSQL 18.3，loopback新集群，非超级用户应用角色，四进程并发空库初始化通过 |
| 查询／治理／并发 | 证据、人工修订、一次性授权回退、304复验、隔离、车库、比较、偏好、事务回滚、API／Worker并发、调度租约、身份CAS／UUID／撤销均通过 |
| 持久化 | 测试事件、合成AI账本、二进制对象、PostgreSQL全文检索、监控规则／草稿、报告及导出、重解析、Parser A→B→A、召回和查询筛选的重启检查通过 |
| 真实备份／恢复 | 实际执行pg_dump和pg_restore，恢复后147张模型表逐行指纹及schema版本列表一致，备份文件674306字节 |
| 对象备份 | 10个证据对象共40392字节，4个报告导出对象共215263字节，恢复读取使用备份对象目录 |
| Parser归档 | 3个不同归档共7668420字节，包含召回归档2个，恢复检查实际执行归档代码 |
| 恢复后复核 | 身份原事件／重放、监控草稿、全文引用、报告文件、重解析、Parser及召回历史／回滚、查询筛选与未消费授权均通过 |

该批包含合成旧schema缺列后的001–004迁移检查。正常部署旧库的整库升级仍待独立验收。`vector_available=false`，pgvector继续待验。029–032表的初始化与归档包含在本批，相关新增业务的专门PostgreSQL场景仍待补齐。

脚本输出服务停止后，另行执行当前集群的 `pg_ctl status`，得到exit3及 `no server running`，并通过完整监听列表确认端口55452的监听数为0。独立关闭凭据保存在该目录的 `closure.json`。

### 兼容回归与源码核对

受管批 `.artifacts/pghelp-r1/` 执行隔离审核、真实重解析、真实Parser A→B→A、召回Parser重启四个既有用例，以及Windows架构环境模块。11／11通过，runner退出0，失败／跳过／incomplete均为0，源码稳定、资源关闭、非自检拒绝及依赖探针拒绝均为0。25个managed_parser子进程全部exit0，live计数0。正常数据库启动false，真实Provider／接收端调用0。

`result.json` SHA256为 `6d8d7078baea6b8a11eae91079d3cbf63135978808190c5d34dd1343b83a7d7a`。六个改动Python文件均在该批输入绑定中，交付复核的当前SHA均匹配source-after，AST解析6／6通过。PostgreSQL的45项检查和该11项pytest分别记录。

### 中间失败与范围

| 保留目录，均在 `.artifacts/postgres/` 下 | 当次停点 |
| --- | --- |
| `pgverify-ffcbc8f0dc2a4e76b71d433da0b19561` | 受限执行通道的initdb停在内存参数选择，核对两个本轮进程身份后结束，正常权限通道随后初始化成功。保留initdb日志 |
| `pgverify-4bfc52ba17aa4213868edae9ce8cb27d` | 注册后事实修订通过，旧variants全对象相等断言失败 |
| `pgverify-71033d7c1c66474ea7b05586432c9f30` | 20项通过，共享库重复注册失败 |
| `pgverify-3457e3418b45434db3fe4f19986f63a2` | 28项通过，历史重解析完成状态失败 |
| `pgverify-1b40077f965940e885bc4f46ad7a5ee8` | 28项通过，诊断确认 `parser_isolation_unavailable` |
| `pgverify-449fb08c7ff04b7eac52fc1e08cfb67a` | 33项通过，身份管理写HTTP状态断言失败 |
| `pgverify-464d2306fb4144ac833a3bd6952abdb6` | 33项通过，合并并发预期失败，后续预览对照定位命名空间缺口 |

本轮修改覆盖六个验收／测试文件，输入为合成数据与仓库已有的录制片段。真实专业材料／真人Golden、真实Responses语义链、pgvector、029–032专门业务场景、正常部署旧库升级及六类平台／无障碍／完整V1继续开放。

## 029–032业务与恢复专项完成

本节记录 `7ae3967` 之后的新增验收。前节45项及11项回归为此前阶段的记录，最新结果以本节的47项及204项回执为准。

### 实现与执行范围

新增 `scripts/recent_history_acceptance.py`，复用现行API、应用工厂及既有合成夹具。`scripts/postgres_acceptance.py` 在报告持久化检查后固定执行新业务场景，实际恢复库检查中再次执行checkpoint。所有数据位于同一新建隔离PostgreSQL数据库及其恢复副本，应用角色为非超级用户。

| 场景 | 实际验证 |
| --- | --- |
| 029原文变化通知 | 冻结前后证据、已读幂等、晚建规则不补发、事件重入去重 |
| 032地址迁移通知 | 同正文A→B→A地址迁移，与页面正文变化分别记录，晚建规则不补发、事件重入去重 |
| 通知事务 | 分别在页面、地址、兴趣通知插入处注入失败，相关采纳事务及状态计数回滚 |
| 030质量隔离兴趣 | 订阅默认false、显式true，仅通知订阅者，保留已采纳事实，退订后旧通知匹配条件及兴趣修订冻结 |
| 031并发停止 | 合成传输在物理put后等待，两个独立应用／PG连接并发停止，结果分别为stopped与already_stopped，停止决定一致 |
| 031迟到与重放 | 迟到捕获保持stopped_unconfirmed，新增outcome、document、EvidenceObject均为0，原UUID重放读取既有结果 |
| 原生写保护 | 五张历史表分别拒绝UPDATE、DELETE、TRUNCATE及重复INSERT，另验证兴趣通知唯一约束。每个checkpoint21次，应用重启及恢复库各执行一次，共42次 |
| 恢复读取 | 完整通知、兴趣修订、停止决定，以及原UUID停止与捕获幂等重放均保持 |

并发停止场景中的物理put执行1次，可能留下无引用对象。现行停止采纳合同允许该结果，网络结果继续未知。场景中的材料为项目自有合成输入。

### 最新完整PostgreSQL结果

最终运行目录为 `.artifacts/postgres/pgverify-1f9e174e87674047aaaf2bba4cf12723/`。`report.json` 为 `status=passed`，共47项命名检查，进程退出0。SHA256为 `34c54da3ce3cc26b06428ce49579eae966ec1f30fc44c54746b68f1bb48ebc7c`。

- PostgreSQL 18.3，loopback隔离集群，非超级用户应用角色。
- 实际执行pg_dump及pg_restore，备份684790字节，147张模型表逐行恢复指纹及schema版本列表一致。
- 10个证据对象共40392字节、4个报告导出对象共215285字节、3个Parser归档共7668420字节的恢复检查通过，恢复后实际执行归档代码。
- 同目录 `closure.json` 记录 `pg_ctl status` 为exit3及 `no server running`，端口55452监听数0。
- `vector_available=false`，pgvector实际运行与检索质量仍待验。

首批绿色运行保留于 `.artifacts/postgres/pgverify-b2fc6bf1100144479b869d55cc912d27/`。最终批在应用重启及恢复库checkpoint中均执行原生写保护。两个批次各自保留原回执。

### 七模块受管回归

`.artifacts/pghist-r1/result.json` 对以下模块实际执行204项，204通过，失败／跳过／incomplete均为0，runner退出0。

```text
apps/api/tests/test_source_page_monitoring.py
apps/api/tests/test_source_quality_interests.py
apps/api/tests/test_source_materials.py
apps/api/tests/test_source_page_url_moves.py
apps/api/tests/test_source_page_migration.py
apps/api/tests/test_source_quality_interest_migration.py
apps/api/tests/test_source_material_stop_migration.py
```

结果SHA256为 `ddb3f302310faf13e80d6d7307925a9713161be9a7eed8274038bd92a4d17546`。`sources_stable=true`、`resources_closed=true`。非自检拒绝、已知探针拒绝和其他拒绝均为0。正常数据库启动false，真实Provider／接收端调用0，子进程计数0。两个改动Python脚本均匹配该批 `source-after.json`，AST通过，`git diff --check`通过。

### 当前剩余与交接

最新源码及报告入口已汇总至[Agent交接卡](../../AGENT-HANDOFF-2026-11-12.md)。后续优先推进pgvector，以及正常部署旧库029–032的备份、显式迁移、恢复与回退。真实专业材料／精确SKU／外部真人Golden、OpenAI Responses真实语义、全文RAG／reranker、生产权限、长期监控、六类平台与无障碍及完整V1继续开放。

本次交付沿用上述已绑定源码的实际执行结果，交付复核重新核对回执SHA、源码绑定、AST和文档链接。浏览器、前端构建、完整API／Worker、真实模型和设备的本次新增结果仍待取得。私有回执与隔离数据沿用Git忽略规则，接手时按本机可用性检查或在新槽复验。

交付复核确认七模块回归绑定的772个输入文件均保持原字节，两个改动脚本AST通过，11个本地文档链接均存在。`docs/HANDOFF.md` 历史尾文保留216248字节，SHA256为 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`。新增行的机器路径及高置信度凭据模式检查通过。本机复核回执为 `.artifacts/handoff-pghist-20261112/validation.json` 及 `tail-validation.json`。

## pgvector真实运行与业务验收完成

`a6d2d07` 推送后按原目标继续执行。复用既有 `scripts/verify-pgvector.ps1` 及 `scripts/pgvector_acceptance.py`，从已有PostgreSQL发行版复制运行副本，在项目忽略目录内编译固定官方pgvector 0.8.1源码。下载入口新增 `-NoProxy`，确保本次网络使用直连。

源码提交为 `778dacf20c07caf904557a88705142631818d8cb`，归档SHA256为 `5badef2cdfed828d93b7f70ae6ad38236e36954420bb24001aa5508e61bf2d7c`，本次DLL的SHA256为 `ad472932aba82b6a5b664432eba2955297c8cef14433bd4abbe866d88fecf92b`。构建日志及来源凭据位于本机运行目录内。原PostgreSQL安装中vector.dll及vector.control均保持缺席。

### 实际数据库结果

运行目录为 `.artifacts/pgvector/vectorverify-a7627452e5e649b7902891f21f8843a7/`。`report.json` 为 `status=passed`，进程退出0，SHA256为 `a7fcc09f9d06109f2544f32919ef23929774ae022389229adc8aa38a713e6f13`。

| 范围 | 结果 |
| --- | --- |
| 数据库与扩展 | PostgreSQL 18.3，pgvector 0.8.1，loopback新集群，业务使用非超级用户角色 |
| 向量原生操作 | 写入1006个固定合成向量，拒绝维度错误及NaN／Infinity，验证余弦距离、命名空间／状态／隐私筛选 |
| HNSW | EXPLAIN实际使用cosine索引，ef_search=100、iterative_scan=strict_order，固定语料Recall@2为1.0 |
| 重启与恢复 | 实际数据库重启及pg_dump／pg_restore后，1006行向量指纹、精确查询结果、扩展版本及HNSW索引保持。备份21973字节 |
| 业务API | 12项检查通过，覆盖计划、显式同意、并发幂等、预算预留、cosine／RRF、相同硬筛选、304／同事实缓存复用、模型／维度／隐私隔离、撤回排除、增量更新、失败固化、共享预算及应用重启 |
| 业务恢复 | 149张业务表逐行指纹一致，保留3条embedding_vectors和1个HNSW索引，实际备份525118字节 |

报告顶层10项检查与嵌套12项业务检查分别记录。业务检索执行筛选后精确cosine扫描，HNSW执行计划来自独立合成向量场景。真实模型检索质量、生产规模召回和语义reranker继续待验。

### 回归与资源

受管批 `.artifacts/vector-r1/` 实际执行 `test_embeddings.py` 及 `test_knowledge.py`，55／55通过，runner退出0，失败／跳过／incomplete均为0。源码稳定、资源关闭，非自检拒绝、已知探针拒绝及其他拒绝均为0。正常数据库启动false，真实Provider／接收端调用0，子进程0。结果SHA256为 `0be2e2f88c0a7c9b31fc437a8bc01b6c2e1387453ef07e681bcd853c57a63c89`。

脚本输出server stopped后，独立核对该集群的pg_ctl status为exit3、端口55453监听数0，保存同目录 `closure.json`。首个受限通道的CIM监听查询被拒绝，随后通过正常权限的只读查询完成核验。PowerShell改动脚本AST解析通过，语法错误0，`git diff --check`通过。

### 下一步

正常部署旧库029–032的备份、显式迁移、恢复与回退继续开放。本轮仅读取正常库文件元数据，确认本机有既有开发库及备份工具。后续应复用 `scripts/backup_dev.py` 的数据库／原文对象／Parser归档备份逻辑，并在明确副本中演练迁移。

真实Responses／Embeddings语义、专业材料及精确SKU／真人Golden、全文RAG／reranker、生产权限、长期监控、六类平台／无障碍与完整V1仍按原规格推进。

## 既有开发库015→032副本演练完成

### 输入及只读备份

通过现有 `scripts/backup_dev.py` 的SQLite backup API读取既有开发库，并将数据库、对象目录和Parser归档保存到 `.artifacts/upgrade-rehearsal-20261112/backups/backup-20261112T063834Z/`。数据库27996160字节，迁移账本为001–015，共113张SQLite物理表。PRAGMA integrity_check返回ok，foreign_key_check无违规。Parser归档1179个文件，对象文件和证据对象引用均为0。

备份前后及全部演练结束时，原开发库SHA256一致。原库仅经只读备份入口访问，升级和恢复操作使用新副本。原始盘点保存在 `source-inventory.json`，源文件核对保存在 `source-backup-check.json`，二者位于本轮本机目录。

### 显式升级及原数据保全

复用 `vehicle_binary_migration.private_rehearsal`，在停止写入的独立副本执行024车型原文存储迁移，再调用当前 `Database.initialize` 完成至032的后续迁移。升级后32个版本、154张SQLite物理表。所有113张原表的原有列及原有值保持一致，新增版本另行核对。

升级结果为 `.artifacts/upgrade-rehearsal-20261112/rehearsal-r1/report.json`，status=passed、进程退出0，SHA256 `27261c8ade9ec60d68494dfda183d2e3b1b70401f3a517d0d9cd487048b15041`。原函数返回的 `normal_upgrade_ready=false` 继续保留其范围，本轮后续资产及恢复检查独立记录。

### 失败原证据及定位

| 回执 | 实际原因与处理 |
| --- | --- |
| `recovery-result-r1.json` | Parser归档核对返回parser_bundle_environment_incompatible。比较环境后确认唯一差异为machine，归档为amd64而验证进程为空。Python版本与全部依赖一致。工装按sysconfig.get_platform设置实际Python架构环境变量后，原校验通过 |
| `recovery-result-r2.json` | 工装请求知识检索时使用limit=100，真实路由返回422，既有协议上限30。随后复核输入还要求有效文本或筛选条件，工装修正为kind=tire、每页30条，使用既有has_more／total分页 |

两份红批及工装版本按原内容保留。环境差异见 `parser-environment-diff.json`，422原始诊断的安全字段见 `knowledge-diagnostic.json`。Parser及检索产品合同沿用现有实现。

### 最终恢复运行

最终 `.artifacts/upgrade-rehearsal-20261112/recovery-result-r3.json` 为status=passed，进程退出0，SHA256 `db558fb47658a7176f8dc763de7b3323726da21d0fa0c75b9bbc823a207fad45`。

| 检查 | 结果 |
| --- | --- |
| 资产及引用 | 1179个Parser资产文件的相对路径／哈希映射一致，数据库实际引用的1个Parser归档通过既有verify_bundle完整校验。证据对象引用为0 |
| 四点失败回滚 | 在after_copy、after_replace、before_version、before_commit注入故障。每次失败后，完整schema、行数据、版本列表、完整性及外键均与原始备份一致 |
| 升级后API | 真实应用路由读取13份轮胎原文及2份车型原文，body和raw_hash均匹配。完整分页取得97条轮胎历史检索结果，三个新通知列表为空 |
| 升级后备份恢复 | 复用既有backup_database及copy_tree，将升级库和资产恢复到新目录。数据库完整状态及资产哈希映射一致，重新执行相同API读取，得到相同统计 |
| 完整原备份回退 | 文本回退屏障通过后，将原始整库备份及资产恢复到另一个新目录。015版本、schema、行数据及资产均一致，Parser引用归档再次通过校验 |
| 来源与原库 | 两次API检查的来源fetch调用均为0，全过程结束后原开发库SHA保持一致 |

### 归档旧后端实际启动

数据库引用的可信Parser归档包含当时的旧后端main.py及migrations.py，共105个源码文件。逐文件校验后，在独立进程从该归档加载旧后端，确认实际加载的main路径属于该归档，并在新的015恢复副本经TestClient完成真实应用启动、历史读取与关闭。

13份轮胎原文、2份车型原文及30条历史检索首页读取通过，body／raw_hash匹配，完整性和外键检查通过，版本列表保持015，来源fetch调用0，原开发库SHA保持一致。回执为 `.artifacts/upgrade-rehearsal-20261112/rollback-runtime-result.json`，status=passed、进程退出0，SHA256 `32d2bc74c0a7a96a185fe24fc481ef89a9af3afd797c756163cbe06b9a87f78b`。

### 迁移相关受管回归

受管批 `.artifacts/umig-r1/` 实际执行以下五模块，154／154通过，runner退出0，失败／跳过／incomplete均为0。

```text
apps/api/tests/test_vehicle_binary_migration.py
apps/api/tests/test_source_page_migration.py
apps/api/tests/test_source_quality_interest_migration.py
apps/api/tests/test_source_material_stop_migration.py
apps/api/tests/test_source_page_url_moves.py
```

源码稳定、资源关闭，非自检拒绝、已知探针拒绝及其他拒绝均为0。正常数据库启动false，真实Provider／接收端调用0，子进程0。结果SHA256为 `81bede3fbc32e0ac5d5e86661f91da969c008c54658fbc7588d775987818764a`。受管回归使用合成私库，既有开发库副本与归档旧后端为上述独立运行。

实际部署目标切换、对应发布包完整回退、含二进制对象的部署库恢复及生产PostgreSQL旧库升级继续开放。已有通用PostgreSQL及pgvector报告另有二进制对象／向量恢复的限定证据。本轮结果供具体部署方案复用。

交付复核确认154项回归绑定的772个输入字节一致，5个本机验收脚本AST通过，11个本地文档链接有效，HANDOFF历史尾文SHA保持。原开发库及源资产树与备份核对一致，新增行机器路径／高置信度凭据模式检查通过，`git diff --check`通过。复核回执为本机 `.artifacts/upgrade-rehearsal-20261112/delivery-validation.json`。

## Gemini适配收尾与本次交接

用户要求汇总进度、push全部改动并形成Agent交接文档。本次在既有main上收尾此前进行中的Gemini适配，文档入口为[Agent交接卡](../../AGENT-HANDOFF-2026-11-12.md)。完整V1目标及各项发布Gate继续开放。

### 已完成范围

- 新增 `ai_gemini.py`，采用Google原生generateContent及streamGenerateContent SSE，固定官方v1beta模型端点和x-goog-api-key请求头。配置使用TI_GEMINI_MODEL、TI_GEMINI_API_KEY及TI_AI_PROVIDER=gemini。
- 复用共享证据封装、结构化输出schema、单次同意、预算预留、请求账本、引用恢复和失败终态。usage包含thought tokens，推理正文及签名在响应投影阶段过滤。
- 共享网关支持原生systemInstruction／contents／generationConfig，车型最终外发检查读取原生contents信封。候选接收方授权、人工价格类型、低基数遥测、共享TypeScript类型及Web选项均贯通。
- 新增58项配置、协议、HTTP、流式、真实应用路由、候选授权／撤销、价格／遥测和合成车型最终外发用例。SDK增加Gemini价格透传回归。用户选定的首个真实Provider继续为OpenAI Responses。

### 原始失败及处理

| 运行 | 原结果与后续处理 |
| --- | --- |
| `gem-r1` | 实现前红批，47项中7通过、40失败。缺功能证据保留，SHA256为 `4bc8a31671b9ddbf8fadfbe6368aabdde5c06f99d4553082c33ecf548d160e94` |
| `gem-r2` | 首批实现后47／47通过，SHA256为 `a4bf6c1b0613a6bfb2d5b239352a8d68fa7291d6a157f56889f79574e9a62110`，仅覆盖该阶段源码 |
| `gem-r3` | 扩展后58项中49通过、9失败。一个测试错误读取推荐结果顶层provider，修正为preparation.provider.provider。其余8项setup失败，追溯到历史S2原件缺失，API返回vehicle_source_fetch_failed且provenance为空。新增用例改用明确的合成capsule边界，真实S2集成继续待原件 |
| `gem-r4` | 14模块366项中359通过、7失败。四个合成设备用例在object_store.put的原子硬链接失败，两项既有遥测捕获未取得live结果，另有30ms生产者时限断言失败。原回执SHA256为 `ce5ed3c171bd6e85098b12893bdefe70bddc92e5f8312d41ff874517d7c52d80` |
| `gemdiag-r1` | 相同源码的9项目标复跑，生产者时限通过，4个设备用例仍在object_store.py失败。单独最小硬链接探针确认PermissionError、errno13、WinError5。探针只使用忽略目录内合成字节，源和链接已清理 |
| `gem-r5` | 保持同一源码和受管守卫，改用正常OS权限串行运行完整14模块，366／366通过，零失败／跳过／incomplete。对象写入与上述既有用例均通过 |

原S2文件当前缺失，预期为3240150字节及SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，路径为 `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf`。新增车型夹具对capsule读取作合成替身，持久化请求／材料、正文绑定、普通／设备分支及同步／流式执行仍使用现行实现，用途拒绝使用实际规则。真实原文、Parser与二进制capsule资格链需要恢复原件后另行验收。

### 最终受管回归

最终命令使用新槽并取得终态。

```powershell
apps/api/.venv/Scripts/python.exe scripts/run_api_worker_regression.py --phase run --output-root .artifacts/gem-r5 --targets apps/api/tests/test_ai_gemini_provider.py apps/api/tests/test_ai.py apps/api/tests/test_ai_chat_provider.py apps/api/tests/test_ai_anthropic_provider.py apps/api/tests/test_ai_stream_api.py apps/api/tests/test_ai_stream_execution.py apps/api/tests/test_ai_stream_parser.py apps/api/tests/test_candidate_ai.py apps/api/tests/test_candidate_ai_review.py apps/api/tests/test_ai_pricing.py apps/api/tests/test_ai_pricing_migration.py apps/api/tests/test_telemetry.py apps/api/tests/test_telemetry_api.py apps/api/tests/test_telemetry_domain.py
```

`.artifacts/gem-r5/result.json` SHA256为 `e17aeda2e5dfda4fce9a50d3b0e73a259f9643fb7588c1f0204fa36a4c4e211b`，runner退出0，366／366通过。774个输入源码稳定，资源关闭，非自检拒绝、已知探针拒绝和其他拒绝均为0，正常数据库启动false，真实Provider／接收端调用0，子进程及存活子进程均为0。上游使用本次测试专有的合成HTTP响应。

### TypeScript及交付复核

| 检查 | 实际结果 |
| --- | --- |
| SDK价格规划合同类型 | `tsc -p packages/api-client/tests/tsconfig.ai-price-planning.json --noEmit --incremental false`，exit0 |
| SDK候选合同类型 | `tsc -p packages/api-client/tests/tsconfig.candidate-ai-contract.json --noEmit --incremental false`，exit0 |
| Node运行 | Web的四个test.ts文件、SDK价格规划及候选脚本合并运行56／56通过，零失败／跳过。候选脚本包含59项wire／transport断言 |
| Web完整类型 | exit2。现有Next包缺少dist，Metadata、Viewport、MetadataRoute和NextConfig导出无法解析，安装包内Next指南同样缺失 |
| Desktop完整类型 | exit2。Vite和@vitejs/plugin-react无法解析 |
| Mobile完整类型 | exit2。Vite、@vitejs/plugin-react和@capacitor/cli无法解析 |
| Python与PowerShell语法 | 本次八个改动Python文件AST通过，verify-pgvector.ps1语法错误0 |
| 历史验收回执 | 八份PostgreSQL／pgvector／开发库演练权威回执均存在，SHA与原记录一致，保持各自执行时点与覆盖范围 |
| 凭据现状 | 只核对配置布尔值，OpenAI及Gemini模型／Key、EPREL Key当前均缺失 |

Node实际命令如下。

```powershell
node --test --experimental-strip-types --import ./packages/api-client/tests/device-ai/json-esm-hook.mjs ./packages/api-client/tests/ai-price-planning.mts ./packages/api-client/tests/candidate-ai.mts ./apps/web/tests/*.test.ts
```

三端完整类型检查使用各自tsconfig及 `--noEmit --incremental false`。前端构建、浏览器、设备、真实Google／Responses／Embeddings语义继续待本轮验收。后续先恢复锁定依赖及可信S2材料，再继续生产部署切换、真实专业材料／精确SKU／真人Golden、来源、权限、平台和无障碍Gate。

### Git交付

推送前通过GitHub官方SSH 443直连核对原仓库，远端为 `a6d2d07f2d72e5fc5d7f5a3ce8b136464eb61254`，同步后与本地基线一致，既有待推送提交数0。HTTPS直连曾低速超时，沙箱内Git SSH因MSYS命名对象权限拒绝而无法启动，正常权限SSH查询和同步成功。全过程沿用直连。

本次正式提交包括pgvector下载参数、Gemini适配及共享协议／回归，以及开发库演练和交接记录。最终提交与远端一致性由实际push后查询核对，详见交付消息及接手时Git核对。忽略目录内的数据库、私有回执、依赖与构建产物按现有规则保留在本机。

工程提交为 `4ea023f`（pgvector直连参数）及 `d5fded1`（Gemini原生适配与回归），随后交付进度与交接文档提交。全部提交均为本次范围内的正式提交，既有历史保留。

最终静态复核保存在 `.artifacts/handoff-final-20261112/validation.json`。774个输入与绿色批source-after逐字节匹配，14个本地文档链接有效，HANDOFF历史尾文216248字节及SHA保持。新增行机器路径／高置信度凭据模式检查零命中，`git diff --check`通过。

## 交付后依赖、构建与S2恢复

`bce22a4`推送后按持续目标继续执行。用户已再次核对AI方向，首个真实接入及后续主线为OpenAI Responses。原规格中的其他适配能力沿用已交付范围。

### 锁定依赖及三端构建

核对package-lock与安装内容，发现Next、Vite、Capacitor及其依赖缺少dist文件。对44份对应锁定版本归档逐一验证SRI哈希，结果全部匹配。39个包实际补回9520个缺失文件，1226个既有文件与归档逐字节相同，既有差异0。其余5个入口省略扩展名的包归档内容完整。下载显式直连，一份归档复用已有本机内容缓存。

三端 `tsc --noEmit --incremental false` 均exit0。恢复后的Next包内TypeScript、构建及部署指南已阅读。随后通过既有npm构建入口完成以下三项。

| 平台 | 实际结果 |
| --- | --- |
| Web | Next生产构建exit0，独立 `.next-gemini-20261112` 目录，PWA白名单19项 |
| Desktop | TypeScript及Vite生产构建exit0，输出至本机 `.artifacts/frontend-repair-20261112/desktop-dist` |
| Mobile | TypeScript及Vite生产构建exit0，输出至本机 `.artifacts/frontend-repair-20261112/mobile-dist` |

Desktop／Mobile保留大chunk告警。构建后将Next生成的next-env.d.ts恢复到预先保存的字节，623个受管前端输入与构建前完全一致。包清单和锁文件保持原字节。该批为前端编译验收，Native安装、原生运行、浏览器交互及性能SLO继续待验。

本机回执位于 `.artifacts/frontend-repair-20261112/`，包括 `download-result.json`、`restore-result.json`、`build-result-r1.json`、三个构建日志和 `post-build-verification.json`。

### 可信S2及实际二进制链

直连小米官方PDF地址得到HTTP200、application/pdf、3240150字节，SHA256为 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，与既有S2常量完全一致。验证后恢复到原 `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf` 路径。下载回执为 `s2-download-result.json`。

新增8个实际S2／Parser／capsule下的原生外发检查，覆盖普通／设备、同步／流式、冻结正文／篡改正文。原Provider用途拒绝和错误终态规则保持。另运行2个同长度原文损坏用例及此前14模块，受管批 `.artifacts/gems2-r1/` 共376／376通过，runner退出0，失败／跳过／incomplete及非自检拒绝均为0。

774个输入稳定、资源关闭。10个受管Parser子进程均exit0、live为0。正常数据库启动false，真实Provider／接收端调用0。该批SHA256为 `ba2b7d128fee9233f32a6e8e246e31c2e93bdb82a825a3bebff4bf28b27568df`。实际原件与Parser资格链已经执行，模型侧使用合成或禁止调用的适配器。

## OpenAI Responses冒烟脚本假通过修复

### 可证伪原始证据

独立合成探针给既有 `scripts/ai_real_provider_smoke.py` 传入未知fact／evidence ID、自由文本fact及usage=None。原 `check_contract` 正常返回，判定通过。回执为 `.artifacts/responses-smoke-20261112/pre-fix-probe.json`，外部调用0、数据库参与0。

该脚本只检查claims／uncertainty顶层形状，并明确允许usage为空。合成信封还使用evidences及facts.evidence_ids旧形状，缺少应用grounding所需的evidence、facts.evidence_id、conflicts和source_state。

### 修复范围及成功条件

补齐合成信封，复用应用现有 `grounded_answer` 和 `safe_usage`。事实文本从项目自有输入恢复，每次调用须至少产生一条已绑定事实及合法usage。未知引用、重复引用、自由文本事实、空答案、缺失／非法用量和流式正文不一致均拒绝。失败输出为固定错误码，成功输出为计数和规范化用量。

调用入口仍为环境驱动的configured_model／configured_adapter，默认OpenAI Responses，顺序为generate后stream，首错停止。配置失败在创建适配器之前终止。该脚本验证Provider回执与应用grounding，API同意、持久化、幂等和账本沿用各自既有验收。

### 受管验证及失败记录

| 回执 | 实际范围与结果 |
| --- | --- |
| `rsp-r1` | 首个受管批在collection阶段退出，实际收集／执行0项，pytest退出3。保留原结果，未形成测试红批结论 |
| `rsp-r2` | 相同测试导入问题仍导致collection退出，实际执行0项。两份原始回执保留 |
| `rsp-diag`／`import-diagnostic.json` | 独立探针确认受管搜索路径内不存在scripts包命名空间。收集诊断通过仅证明该诊断入口可导入。测试改为使用runner已注册scripts目录的直接模块导入 |
| `rsp-r3` | 新模块26项及既有AI、流解析、Chat、Anthropic五模块共122／122通过，runner退出0，零失败／跳过／incomplete |

最终运行命令如下。

```powershell
apps/api/.venv/Scripts/python.exe scripts/run_api_worker_regression.py --phase run --output-root .artifacts/rsp-r3 --targets apps/api/tests/test_ai_provider_smoke.py apps/api/tests/test_ai.py apps/api/tests/test_ai_stream_parser.py apps/api/tests/test_ai_chat_provider.py apps/api/tests/test_ai_anthropic_provider.py
```

结果SHA256为 `099eac3593628081ca4f72db79b214a461237d64837f40634192ecf6f2d352b1`。775个输入稳定，包含smoke脚本，资源关闭，非自检拒绝、正常数据库启动、真实Provider／接收端调用及子进程均为0。该批与前述376项为分别执行的限定验收。

另用Python优化模式执行独立探针，合法回执通过，未知引用、缺失usage和总量不一致均拒绝，回执为 `post-fix-optimized-probe.json`。禁用状态CLI实际返回ai_disabled及exit2。只核对配置布尔值，Process／User／Machine三个作用域的TI_OPENAI_MODEL及TI_OPENAI_API_KEY当前均缺失。

独立冷启动CLI审计记录数据库连接0、外部网络尝试0，以及Python标准库platform.win32_ver发起的1次系统版本查询。最初工装要求全部子进程计数为0，诊断明确该查询为cmd的ver命令后，工装按实际事件分别记录，产品行为沿用。原工装回执保留，最终为 `cold-cli-audit-r2.json`，passed=true、CLI仍exit2、其他子进程0。

真实OpenAI Responses语义与API→Provider→Web全链继续待凭据、用途许可及专门验收。EPREL现状及旧KIT C2封存约束保持。完整V1目标继续开放。

正式工程提交为 `243d72b`（实际S2外发回归）和 `0e2eb3f`（Responses冒烟修复），其后交付本轮记录与交接更新。复核时775个最新输入逐字节匹配，623个前端构建输入保持一致。与376项批次相比，共有输入仅smoke脚本及受管runner发生变化，新增输入为smoke测试模块。

四个改动Python文件AST通过，13个本地文档链接有效，HANDOFF历史尾文216248字节及SHA保持。新增行机器路径／高置信度凭据模式检查零命中，差异检查通过。回执为 `.artifacts/responses-smoke-20261112/delivery-validation.json`。

## Responses生产Web合成验收与交接补充

### 方向与实现范围

用户选定的首个真实AI接入为OpenAI Responses API。Gemini列于原规格的多模型接入表中，此前Agent自行提前交付其原生Adapter。本轮围绕Responses主线，补齐既有生产Web合成验证及交接。

修改限于 `scripts/ai_stream_acceptance.py` 的Windows元数据初始化及本轮交付文档。夹具使用 `sysconfig.get_platform()` 绑定架构，并以 `sys.getwindowsversion()` 提供进程内版本读取，沿用既有受管runner做法。原有外网、Parser子进程与私有数据库审计继续生效。

### 原始失败及恢复

- 首次 `api-r1` 在SQLAlchemy导入时触发 `platform.machine()`，标准库退回 `cmd /c ver`，被子进程审计拒绝。失败回执记录Parser子进程尝试1次、模型及来源调用0、私有存储已清理。原堆栈及 `fixture-final.json` 保留。
- 首次重启经系统python shim执行时报告未配置版本，HTTP夹具尚未启动。随后使用项目既有Python解释器继续。
- `api-r2` 与首个Web服务在沙箱内输出就绪，loopback HTTP访问超时，端口查询未取得可达监听。中断前确认本轮进程身份，后续确认进程消失，保存数据库副本并只清理该夹具创建的私有目录。该次有序shutdown状态待确认。
- 改用受审执行权限后，`api-r3` 与独立Web可达，浏览器成功打开生产工作台。私有端口为8003与18002，使用新SQLite及独立构建目录。
- 最初UI查询填写245/40尺寸，与265/40合成记录不匹配，返回 `source_schema_validation_failed` 并展示本次历史回退授权。将查询更正为夹具尺寸后得到1条精确SKU。
- 浏览器取样中的原生dialog选择器、重绘后元素UID及失败账本计数断言先后更正。最终按 `AICompletion.state` 核对completed／failed，原操作错误及更正后结果保留于 `browser-records.json`。

### 实际浏览器与数据库结果

Web使用既有生产构建入口，退出0，PWA白名单19项。Provider提供合成Responses字节，经真实 `parse_response_stream`、应用服务、数据库、HTTP／SSE和React界面消费。

| 场景 | 已观察及核对 |
| --- | --- |
| 同意与准备 | 历史证据包准备后Provider次数0，AI请求0，发送按钮在同意前禁用 |
| held草稿 | Provider次数1、AI完成账本0行时，显示“生成中草稿”及待校验提示 |
| 合法终态 | release后完成账本completed，600 tokens，正式事实／推断／不确定性可见，草稿移除，脚本文本按文字显示 |
| 引用重开 | 点击核对f1，展开证据字段并将焦点放到相应品牌字段 |
| 刷新恢复 | 重读进度、刷新页面及重开AI面板，Provider与请求仍各1次，读取原有终态 |
| 无效引用 | 第二次合成调用落账failed，错误码 `ai_grounding_validation_failed`，answer及usage为空，草稿作废，含分析报告按钮缺席 |
| 失败重读 | 重读进度与历史终态后Provider仍2次，2条请求、2条完成账本分别为completed和failed |
| 证据保全 | 第二次查询后重新封存的快照／事实／原文指纹保持，真实外网、Parser、OpenAI及正常数据库使用均为0 |

最终私有checkpoint完整性为ok，completed和failed各1行，两个请求Provider均为 `openai_responses`。成功用量为500输入／100输出／600总量，失败记录保留未知用量状态。合成Provider实际调用2次，同步调用0，来源夹具调用3次，365个wire字节分片及10条应用流事件。

顶部模型状态区在终态后保留前次额度展示，点击“刷新记录与配置”后成功调用显示实际600 tokens。终态自动刷新可作为后续体验优化。真实模型语义、其余wire模式本轮浏览器覆盖、原生平台及完整V1继续开放。

### 受管回归与资源关闭

五模块回归122／122通过，runner退出0，775个输入稳定，资源关闭，失败／跳过／incomplete及非自检拒绝均为0。正常数据库启动false、真实Provider／接收端调用0、子进程0。回执为 `.artifacts/rspweb-r1/result.json`，SHA256 `41c187b0d5c1674f7114aa2a1c04384dc97f1c613a8cfa421e7ad6df8c70d8b6`。

API通过专用shutdown路由关闭，实际进程退出0，checkpoint保存2707456字节，私有存储已移除。Web以SIGINT收尾、退出1。两个验证端口监听0，相关API及Web进程0。构建自动修改的next-env.d.ts按预先备份恢复，402个受管前端输入与构建前逐字节一致。

最终独立核对为 `.artifacts/responses-web-20261112/verification.json`，SHA256 `59282aa246530cbcfe110a309960e95d9054d2c20d6b3ae00eb176f76f2c9df7`。该目录保留浏览器记录、各启动日志、失败回执、只读checkpoint核对和关闭证据。HANDOFF历史尾文继续为216248字节，SHA256 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`。

## Responses终态额度自动刷新及完整wire模式验收

### 原因与实现

前一阶段已观察到，分析完成且结果显示600 tokens，顶部模型状态保留受理时预留。`AIAnalysisDialog.submit` 在受理后读取额度，后续 `AIStreamProgress.onDetail` 仅更新分析记录。

修改 `apps/web/components/ai-analysis.tsx`，增加终态状态读取，并将初次、受理、手动及终态额度读取统一到序号仲裁。较新读取启动后，旧响应与旧错误按序号过滤。终态读取使用独立AbortController，随分析切换及组件卸载清理。错误沿用现有展示与手动刷新入口。实现计划见[终态额度计划](../../plans/2026-11-12-responses-terminal-status.md)。

### 实际页面验证

使用全新隔离浏览器上下文、独立生产Web及新私有API数据库。合成Responses事件通过生产解析器、HTTP／SSE、持久化及React界面消费。

held场景中，浏览器先取得26008 tokens预留响应，再刻意延迟向应用交付。释放Provider后，终态额度自动显示600 tokens。随后释放旧响应，界面继续显示600，Provider保持1次。该场景同时验证待校验草稿、终态草稿移除、脚本文本转义及外发同意门。

| wire模式 | 实际终态 | 错误码／用量 |
| --- | --- | --- |
| held | completed | 600 tokens |
| complete | completed | 600 tokens |
| incomplete | failed | ai_response_incomplete，600 tokens |
| truncated | outcome_unknown | ai_stream_interrupted，保留未知用量预留 |
| terminal_mismatch | failed | ai_stream_protocol_error，保留未知用量预留 |
| grounding_failure | failed | ai_grounding_validation_failed，保留未知用量预留 |
| refusal | failed | ai_refused，600 tokens，原始拒绝文本未显示 |
| uncertainty_only | completed | 600 tokens，claims为空，仅显示不确定性 |

每个终态均核对顶部额度与实际API一致，失败分析answer为空、草稿作废、含分析报告保存入口缺席。完整或仅不确定性结果保留各自正式展示。来源证据指纹持续保持。

额外执行一次held场景，在处理中关闭窗口，确认受理额度读取signal已取消。释放原Provider后，重开面板经原标识恢复completed及600 tokens，Provider累计9次、来源累计1次。该轮浏览器取样曾使用早于终态的快照定位重置按钮，工具报告元素缺失。更正为每场景先取最新快照后继续，实际AI请求数保持预期。原工具错误及后续记录保留。

### 持久化、构建及关闭

- 只读checkpoint完整性ok。9条AI请求、9条完成账本、9条流执行、45条应用流事件，状态分别为completed 4条、failed 4条、outcome_unknown 1条。
- 合成Provider调用9次，其中held执行两次。同步调用0、来源夹具调用1次、1715个wire分片。真实OpenAI、外网尝试、Parser子进程及正常数据库使用均为0。
- 最终额度81586 tokens，已知用量共3600 tokens，其余为保守预留。逐条账本核对状态、错误码、answer、usage及Provider均通过。
- 既有Web测试50／50通过，三端完整类型检查退出0，独立Web生产构建退出0，PWA白名单19项。浏览器控制台error／warn记录0。
- 构建后恢复next-env.d.ts，402个前端输入与构建前逐字节匹配。API经shutdown退出0、私有目录已清理，Web经SIGINT退出1。验证端口监听及相关进程均为0。
- 前一阶段122项后端回归的775个受管输入仍逐字节匹配。本轮采用独立Web及浏览器证据，沿用各阶段回执的独立范围。

本机最终核对为 `.artifacts/responses-terminal-20261112/verification.json`，SHA256 `56f12e06b351eacf5be979457ba6c86fe71b7d6ba9cc148283157b45168bff42`。产品文件SHA256为 `6ac582fc0c299704a425fb7990e320961594395411eda6ee621b1308aa55993d`。浏览器原始记录、数据库checkpoint、构建／类型／测试日志及资源关闭信息保留于同目录。

真实Responses语义、额度读取失败注入、原生运行及完整V1 Gate继续待验。后续优先推进用户选定的Responses主线及原规格剩余能力。

## 交付停点及Gemini排期复核

用户追问Gemini的来源。原规格第710行列有Google Gemini原生Adapter，其提前开发排期由此前Agent自行决定，正式实现提交为 `d5fded1`。用户选定的首个真实接入为OpenAI Responses API，当前网关配置对象及环境读取默认值均为 `openai_responses`。交接卡已将该选择、排期来源及后续Responses优先顺序写明。

交付前额度读取故障夹具已启动私有API并返回ready，浏览器故障注入尚未执行，生产Web尚未启动。读取夹具状态确认Provider未活动、来源／Provider调用均为0后，经既有shutdown入口关闭。原执行会话退出0，`fixture-final.json` 为stopped、私有存储清理成功。只读checkpoint完整性ok，8003及18002均无监听。关闭回执为本机 `.artifacts/responses-status-fault-20261112/closure.json`。该槽保留启动及关闭记录，额度读取故障验收继续待执行。

前序材料研究新增JRC作者论文候选《Wear of Passenger Car C1 Tyres Under Regulatory On-Road Testing Conditions》，DOI为 `10.3390/vehicles7030091`。该线索需继续复核原件、许可和试验条件。样本采用匿名代号，当前尚无可核对的品牌型号映射，捕获／TestEvent／SKU关联均为0。接手可沿既有材料捕获链继续研究。[出版页](https://www.mdpi.com/2624-8921/7/3/91)

本次变更为交接说明，产品源码沿用b1c3acb。已重新核对Process／User／Machine三个作用域，OpenAI模型／Key、Gemini模型／Key及EPREL Key均为空。后续验证优先为终态额度读取失败后的结果及错误展示、手动刷新恢复、过期错误仲裁和终态读取期间关闭取消。实际Responses语义、真实材料身份、生产部署及完整V1 Gate继续开放。

静态复核确认最新终态回执及9项关联文件哈希匹配，775个后端回归输入逐字节一致，15个本地文档链接有效。HANDOFF历史尾文保持216248字节及SHA256 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`。新增行个人路径／高置信度凭据模式检查零命中，差异检查通过。本机回执为 `.artifacts/handoff-review-20261112/validation.json`，执行范围为文档、已有回执及资源关闭复核。

## Responses额度读取故障浏览器验收

在aadc48d之后继续执行，产品代码沿用b1c3acb。复用独立生产构建，在新私有API／数据库和隔离浏览器上下文完成下列验证。浏览器fetch夹具只对 `GET /api/v1/ai/status` 注入503或控制返回时序，合成Responses字节继续经过生产解析器、应用服务、数据库、HTTP／SSE及实际React入口。

- 终态额度读取503时，已校验分析、引用及实际600 tokens用量保留，额度错误可见。手动刷新后错误清除，顶部额度恢复600，Provider仍为1次。
- 第二次调用的受理额度错误暂缓返回，较新终态成功先显示1200 tokens。释放旧503后，额度与无错误状态保持，Provider仍为2次。
- 第三次调用完成后暂缓终态额度读取。关闭窗口实际取消该读取的signal，释放迟到成功后面板保持关闭。重开按原标识恢复同一分析及1800 tokens，Provider仍为3次。
- 第四次调用暂缓终态额度错误，关闭后重开并读到2400 tokens，再释放旧503。当前结果、额度及无错误状态保持，Provider仍为4次。

最终四次明确提交对应4个completed、24条流事件、4次合成Provider及1次来源调用，实际账本累计2400 tokens。封存的来源证据指纹保持，输出脚本文本转义。14次额度读取均已返回，两个取消后的迟到响应已显式释放。控制台error／warn为0。

API经shutdown退出0，Web经SIGINT退出1，8003及18002均无监听，私有临时存储已清理。只读checkpoint完整性ok。402个前端及775个后端回归输入逐字节匹配。类型、单元测试及构建沿用各自历史执行范围。本轮真实OpenAI、外网尝试、Parser子进程及正常数据库使用均为0。

本机核对入口为 `.artifacts/responses-status-fault-20261112/verification.json`，SHA256 `6567b3c633a2287ac6ee14de2f4e300ec6765a1a577f959d3e7ea72b8a1f24e3`。该目录保存浏览器原始记录、注入夹具、checkpoint、日志及关闭凭据。

首次私有API启动遗漏现行 `TIRE_CORS_ORIGINS` 配置，查询返回403及“不允许此请求来源”。补齐本次loopback origin后，在新槽完成验证。两条浏览器断言曾期望1200 tokens采用紧凑格式，界面实际采用分组数字1,200，修正显示断言后通过。原始失败继续保留。真实Responses语义、原生运行及完整V1 Gate继续开放。

## 新专业材料PERS论文的实际捕获停点

新候选为Taryma、Woźniak、Ejsmont、Mioduszewski及Ronowski的《Tire/road noise and tire rolling resistance on the prototype PERS surface》，IOP Conference Series Materials Science and Engineering 421 (2018) 022035，DOI为 `10.1088/1757-899X/421/2/022035`。作者单位为Gdańsk University of Technology，大学托管PDF的印刷第1页明确采用CC BY 3.0，要求保留作者、题名、期刊及DOI。该许可依据支持现行通道的原件保存及工作区复核。[原件入口](https://sepor.mech.pg.gda.pl/dokumenty/KONMOT%202018%20-%20Tire%20road%20noise%20and%20tire%20rolling%20resistance%20on%20the%20prototype%20PERS%20surface.pdf)

论文表2列出研究胎号、厂商、型号、规格及载速标识，具有进一步身份核对线索。实验室测试条件包括ISO 18164、最大载荷的80%、210 kPa及不同速度／表面，具体数值多在图中。建立成绩及SKU关联仍需取得原件并逐项复核。

使用新隔离数据库，经真实管理员注册、来源策略读取、预览及捕获API执行一次直连。请求UUID为 `ea4eab2a-5ee2-47ca-894c-539f05886429`，明确落账failed及 `source_material_timeout`，document／receipt均为空。DNS仅观察到指定大学主机，子进程及真实Provider均为0。独立curl直连robots诊断的DNS用时约0.058秒，15.003秒后仍未完成TCP连接，HTTP状态为000。该源的失败证据保存在本机 `.artifacts/material-pers-2018-20261112-r1/`，原有KIT C2继续保持封存。

该候选新增的保存成功原件、TestEvent及SKU关联均为0。另一个同论文大学知识库入口返回Anubis页面，当前继续按实际可访问原始来源推进。完整V1及真实材料身份验收继续开放。

## 正文FTS与可恢复引用后端首步

工程提交为 `675f968`，完整顺序见[原文RAG计划](../../plans/2026-11-12-original-text-rag.md)。新增033、两张派生模型表及SQLite FTS5／PostgreSQL GIN全文索引，生产入口为 `POST /v1/knowledge/source-text/search` 和 `POST /v1/knowledge/source-text/resolve`。请求显式指定history，检索范围为最新正式HTML／文本快照，引用恢复可读取旧正式版本。

正文按HTML结构抽取，排除脚本／样式／模板／注释及显式隐藏元素。分块长度1200个Unicode码点、重叠120个。引用绑定快照、原始SHA256、抽取器版本及字符区间，并由同一抽取函数从原件重建。派生投影丢失后引用仍可恢复，部分分块或FTS行丢失可重建。保留对象读取失败、原文哈希或来源绑定损坏、摘录被修改均有对应反例。

### 回归与原始失败

首批新模块36／36。补充aria-hidden空属性及保留对象元信息损坏反例后，第二批39项中38通过、1失败，原始失败为 `source_text.py` 空属性值调用lower的AttributeError。修改为按空属性的实际值处理后通过。

最终 `.artifacts/srctxt-r5/result.json` 单批五模块204／204，包含41项新模块用例，其余覆盖知识检索、对象存储、并发／失败初始化及固定023旧库升级保全。收集、实际执行均为204，失败／跳过／incomplete均为0，runner退出0，778个输入稳定、资源关闭、非自检拒绝0。正常数据库启动false，真实Provider／接收端调用0。SHA256 `421915de17394261a562a3b02d477bc960b9729f7262d8397adf6072f513f5db`。早期各批保留原源码绑定与回执。

### 真实PostgreSQL及恢复

使用既有二进制分发及验收入口，在新的loopback PostgreSQL18.3集群执行。新增正文GIN检索、Unicode引用恢复和重启检查，并在实际恢复库再次核对原始引用及摘录。最终49项检查通过，实际dump／restore的149张模型表指纹及schema版本一致，备份690546字节。另保留10个证据对象、4个报告对象及3个Parser归档的恢复检查。

本机报告为 `.artifacts/postgres/pgverify-6d362e0ab1fb475698d0f237c2608f4b/report.json`，SHA256 `db4789c47a314582d2e0e38ad642e1eea45b17b6e5f9fedbf0e2dfff17860d59`。脚本退出0并停止集群，独立pg_ctl状态为exit3及no server running，55462无监听。关闭及源码核对回执在 `.artifacts/source-text-pg-20261112/`，778个受管输入仍逐字节一致，10个改动Python文件AST通过。

当前新增验收为合成原文上的生产API和实际数据库。后续继续共享SDK／Web、PDF逐页抽取、正文向量与融合／重排、正文证据包及真实Responses语义。浏览器、前端构建、原生平台及完整V1 Gate仍按各自当前验收范围推进。

### 交付前复核

本次交付复核重新核对上述两份报告SHA256、778个源码输入、10个改动Python文件AST及18个本地文档链接。HANDOFF历史尾文为216248字节，SHA256仍为 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`。待推送新增行个人路径／高置信度凭据模式零命中，工程与文档差异检查通过。复核回执为 `.artifacts/source-text-delivery-20261112/validation.json`，本次实际执行范围为文档、源码绑定及既有回执核对。

## 正文检索SDK与Web接入

共享协议新增正文搜索、分页、摘录及引用类型，SDK的 `searchSourceText` 与 `resolveSourceText` 通过既有HTTP传输调用两个history API并传递AbortSignal。Web沿用历史知识检索入口，在关键词及来源范围的结构化结果为空时补充正文，有命中时可手动补充。其他精确实体筛选保留在原结构化范围。引用查看直接使用服务端恢复的文本及Unicode码点位置。

SDK9／9、Web50／50、三端类型及独立生产构建通过。两模块受管回归67／67，780个输入稳定、资源关闭、非自检拒绝0。新测试入口已加入SDK聚合测试，受管子进程清单中package.json的精确哈希经审查同步。最初 `.artifacts/stweb-r1/` 因该文件的已审查变更被拒绝，保留启动失败回执，正式结果位于 `.artifacts/stweb-r2/result.json`，SHA256 `77c589c0c49cda6a653b26cd16fcf1a27db222624087a0c0abe768962ab805b4`。

生产Web配合新的私有API和合成正式快照，完成24项业务与仲裁检查，包含正文自动补充、手动检索、Unicode、转义、旧引用、原件损坏、稳定来源分页、精确筛选、来源限定，以及编辑／取消／关闭后的迟到成功和错误。1440、390及320像素均无横向溢出，窄屏实际点击引用恢复通过。400个前端输入在构建后逐字节恢复。浏览器观察到1条预期的损坏原件503控制台错误。

夹具初次启动的对象发布因沙箱NTFS硬链接返回WinError 5，升级权限后保留现有生产对象存储行为。第二槽构造合成快照时触发ORM只追加保护，随后采用现有损坏反例使用的SQL构造方式，在第三个新槽完成验收。浏览器断言中的请求索引及滚动条宽度假设已按实际观察修正，中间失败保留。生产源码验证范围按最终批次记录。

本机总回执为 `.artifacts/source-text-web-20261112/verification.json`，SHA256 `67baa05c803872de3ea3966a027ddc5eb2c321e79d999948a586588a224f50ae`，关联三个视口截图、实际API计数及资源关闭记录。API退出0，Web经SIGINT退出1，验证页面已关闭，8003及18002均无监听。来源调用、真实Provider、外网尝试和正常数据库使用均为0。后续继续PDF逐页抽取、正文向量与融合／重排、正文证据包及真实Responses语义，完整V1和原生平台验收持续开放。

## PDF正文工程复核与交接

新增固定内部Parser能力workspace-pdf-text@1，在现行受限进程内提取PDF文字层，保存逐页文字、哈希及明确的无字／部分有字／加密状态。034新增三张派生表及SQLite FTS5／PostgreSQL GIN初始化。生产API提供显式history索引、逐页读取、正文搜索和原件引用恢复，捕获材料复用现有凭证与许可绑定核对。原始凭证继续记录其原有事实状态。

共享SDK新增四个方法及7项合同测试，文档卡新增索引与逐页查看。pypdf从开发依赖移入生产依赖，并已离线同步uv锁文件。初次uv命令遇沙箱缓存拒绝访问，新空缓存缺少解析元数据，随后使用已有本机缓存离线完成更新。

九模块受管广批332项中331通过、1失败，PDF两模块36项均通过。失败位于十来源历史包测试的清单相等断言。新增内部PDF能力后，历史十项清单与当前十一项清单应核对共同范围及各自完整集合。修正该测试并同步受审源码哈希后，整个Parser包模块25／25通过，含历史包实际重放和进程回收。广批保留失败结论，后续专项记录其独立执行范围。

广批回执为 `.artifacts/pdfh-r1/result.json`，SHA256 `af5c872bba51431c05f35541fc097ceb6374a08ee7595a2ea1520efd311340f8`。最终专项为 `.artifacts/pdfh-r2/result.json`，SHA256 `c15b715ffd6a4cb858a2d4a613317f414bcfebb33f96f5696a6d30e57ada5d2a`。两个批次资源关闭、非自检拒绝0，最终787个输入稳定。广批之后的变更范围为Parser包测试及其哈希清单两文件。

SDK新PDF7项与HTML正文9项、Web50项、三端类型及独立生产构建通过。629个前端输入逐字节匹配，构建产生的next-env目录导入经核对后按原字节恢复。本轮使用合成材料，PDF知识检索结果界面、034真实PostgreSQL及PDF生产浏览器验收继续待执行。

交付静态核对发现Git自动CRLF转换会使18个受审文件与其源码哈希不符。按20个受管文件现有字节固定LF或CRLF，并对自动转换开启／关闭执行40项暂存内容过滤检查。源码、文档、增量隐私、历史尾文及最终交付核对位于 `.artifacts/pdf-handoff-20261112/`。OpenAI模型／Key、EPREL Key及Gemini Key的三个环境作用域均复核为空，首个真实Provider继续沿用OpenAI Responses。[当前交接卡](../../AGENT-HANDOFF-2026-11-12.md)

## PDF知识检索、真实PostgreSQL与生产浏览器续作

共享正文组件接入PDF结果和原件引用恢复，采用有来源区分的请求及结果类型。知识检索从服务端applied_filters判定文档范围，无筛选条件的关键词查询可自动补充PDF，有结构化命中时提供手动入口。文档卡显示名称、留存时间、元信息指纹、页码、哈希与Unicode码点区间，复用既有分页、取消及迟到响应仲裁。

103项相关API、SDK16项、Web50项、三端类型及独立生产构建通过。API回执为 `.artifacts/pdfs-r1/result.json`，SHA256 `ce74e243c01c01830cd98ecb2cbeaa434fb37a6a83f953a291339cdbe6de46db`。787个受管输入及629个前端输入逐字节匹配，资源关闭且非自检拒绝0。

真实PostgreSQL18.3执行51项检查通过，152张模型表实际dump／restore指纹一致，新增034、PDF GIN查询、应用重启、第二页读取及备份对象目录中的原件引用恢复。报告位于 `.artifacts/postgres/pgverify-fc411efb49894fee8a72dffaaf3ff0c1/report.json`，SHA256 `18e86f2b4443944f38ed4cc4f686acaba0eeb867015c2ac70b553bc26c8531f1`。集群正常停止后，独立pg_ctl状态为exit3，55464无监听。

PDF生产浏览器35项最终检查通过，覆盖实际文档表单上传、索引、14页查看、15条摘录分页、自动／手动搜索、元信息与Unicode位置、原件损坏及修复、清空派生行后的旧引用、品牌／来源／类型／精确SKU筛选、编辑／取消／关闭后的迟到成功或错误、索引停止等待与状态重读、无字／加密／损坏状态。1440、390、320像素视口通过横向溢出检查，两个窄屏的页码引用恢复通过。截图与原始尝试保存在 `.artifacts/pdf-search-20261112/`。

首个私有夹具在TestClient启动后注册中间件，启动返回RuntimeError，随后调整为先注册并用新槽继续。第一组结构化样本沿用了knowledge测试的原文哈希占位值，引发12次HTML正文503。按已定位的字节绑定补齐合成HTML样本后，单独完成HTML／PDF共同检索、两类原件引用、Unicode／转义与来源筛选5项兼容检查，相关请求错误和该组控制台error／warn均为0。原503及后续独立结果保留，生产源码验证绑定保持。

浏览器第一次来源可见性断言尚未展开details，展开后通过。一次批量翻页动作遇到上一状态读取中的禁用按钮，原始请求记录确认未发出第二页请求，待就绪后复验通过。关闭回执首次将空端口列表序列化为null项，修正后为空数组，原记录保留。最终35项检查及所有已记录尝试分别保存。

两个私有API退出0，两次生产Web经SIGINT退出1，两页隔离浏览器关闭，8003／18002／55464均无监听。来源抓取、真实Provider、外网尝试与正常数据库使用均为0。当前汇总入口为 `.artifacts/pdf-search-20261112/verification.json`，下一步按原文RAG计划第4–5步实施正文向量、融合／重排和正文证据包，真实材料、模型、平台及生产发布继续各自验收。

## 交接复核与正文向量预查补充

本次复核起点为 `a1c6da619a0172b97761517c8d44e68261a9e570`，本地HEAD、origin/main与实时远端main一致，工作区干净。沙箱内SSH查询因MSYS进程启动返回0xC0000022，升级执行权限后通过官方SSH 443直连取得远端SHA，SSH显式禁用ProxyCommand及ProxyJump。

用户追问Gemini来源，已核对原始规格第710行、正式提交d5fded1及网关默认值。Gemini提前开发由此前Agent自主排期，用户选定的首个真实生成接口继续为OpenAI Responses API。代码配置对象及环境读取默认openai_responses，进程环境中的TI_AI_PROVIDER可覆盖该默认值。交接卡补充显式选择及状态接口核对步骤。真实Google及OpenAI模型语义仍待验证。

正文向量预查发现，现有Embeddings计划、缓存及dense投影绑定结构化KnowledgeDocument和tire-structured-semantic@1。save_vectors固定写入该合同，外发前复核仅支持index／hybrid及严格payload。材料canonical_policy与共享类型均把provider_use、export限定为false，普通PDF的保存依据及车辆候选dependency授权也需要按通用正文用途继续核对。具体入口和接手行为已补充到[原文RAG计划](../../plans/2026-11-12-original-text-rag.md#正文向量接入预查)，正文向量的具体设计及实现继续待执行。

本轮执行文档链接、源码绑定、既有回执哈希、增量隐私及差异检查。787个API与629个前端输入逐字节匹配，三份关键回执SHA256匹配，77个本地文档链接有效。HANDOFF历史尾文保持216248字节及既有SHA256，新增行个人路径／高置信度凭据模式零命中。复核回执位于本机 `.artifacts/handoff-closeout-20261112-r1/validation.json`。103项API、51项PostgreSQL及152表恢复、35项PDF浏览器及5项兼容结果沿用已绑定的历史执行范围。完整V1、真实材料、模型、平台与生产发布继续验收。

## 正文向量用途、共享执行与真实PG验收（2026-11-13）

正式工程提交为 `985338f7bf89c6d0b5222f8c804c62332f07ea2a`。

续作自7a64b23，按[正文向量计划](../../plans/2026-11-12-text-embeddings.md)实现独立用途授权、035、original-text-semantic@1及正文向量计划。HTML／PDF均按原件引用恢复输入，经现行embedding-runs执行，复用个人同意、预算、幂等与只追加账本。缓存绑定完整接收端，授权提交可确认预览scope。撤销覆盖原件损坏、配置移除和过期许可元数据，调用中撤销时保留实际用量并拒绝回写。

PDF恢复复用现行受限Parser和页码／Unicode引用检查。新鲜持久化复核在工作线程执行，完成后才进入Provider等待。共享类型和三个SDK方法已接入，聚合测试增加对应专项，受审SDK脚本哈希已同步。Web历史结果显示正文合同状态，正文用途／索引交互面板及正文召回／融合重排与证据包继续推进。

### API与前端结果

六模块r4为239／239，SHA256 `a29c35265f403b7433bc82a5f2d66a3eec9579a403e740a0ed6b75fd967f10cc`，包含正文28、Embeddings29、HTML41、PDF24、初始化5及旧库升级112项。随后新增三项反例，r5为28／31，分别暴露过期元数据阻挡撤销、未核对调用方scope及同主机不同端点的缓存复用。修正后r6两模块60／60，含正文31及Embeddings29项，SHA256 `913f1842bdc1a38db9c2dc5c00ddcf6c104d04ecb00f08883728fdc9737e1943`。两批各有792个执行期间稳定的输入，资源关闭、非自检拒绝0，当前正文执行链以r6绑定为准。

r1为101／120，失败集中于审计调用重复传入action参数。r2为56／57，PDF外发前的同步校验在已有事件循环中再次调用asyncio.run，标准库runners.py第191行抛RuntimeError。改为在线程中完成该校验后通过。r3为237／239，两项旧库测试的当前尾表及版本清单需要精确加入035，保留旧表、旧行、资产及外键断言后，r4完整通过。原始各槽保留。

SDK正文专项5、HTML9、PDF7分别通过，三端最终类型及现有Web50项通过。631个前端输入已绑定本轮检查。生产构建与正文向量浏览器业务验收随后续完整UI实施继续执行，真实模型、专业材料及原生设备仍待验。

### 真实PostgreSQL与恢复

真实PostgreSQL18.3与pgvector最终54项通过，153张模型表实际dump／restore指纹一致。正文HTML及PDF通过正常API形成向量和账本，真实SQL余弦、权限撤销、035写保护及恢复后缓存读取通过。恢复校验从备份对象恢复PDF引用，并实际拒绝授权表UPDATE、DELETE和TRUNCATE。另覆盖12个证据对象、4个报告对象及3个Parser归档。

前三轮失败保留于pgverify-829ed64fef7f48d6b81e80083b0c9c5c、pgverify-499cc86d160640d19e6ed97d5e12c4d1和pgverify-624248ddc3b94d338cace4cf69de37d6。原始日志分别确认非超级用户不能创建vector扩展、不能为管理员所属扩展写注释，以及新增材料夹具晚于身份源表指纹冻结。恢复流程按归档目录完整分配1072项内容，管理员恢复2项扩展元数据，应用角色恢复1070项业务对象。新增材料验证移至身份冻结前，完整源表指纹断言通过。

最终报告为 `.artifacts/postgres/pgverify-0569be10ddbf4accb2421ff0628798e5/report.json`，SHA256 `c06d174362eb8aaa1aa515760d3bba994df3cc3467d540a8c6c212b01d7fefe0`。脚本退出0并停库，独立pg_ctl状态exit3、55466无监听，关闭记录在 `.artifacts/text-embeddings-20261112/closure.json`。模型使用固定合成向量，完整V1和真实语义质量继续验收。

交付前重新核对792个API输入、631个前端输入和20个受审子进程来源，当前字节匹配。14个改动Python文件AST、87个本地文档链接、增量隐私和差异检查通过。HANDOFF历史尾文保持216248字节及既有SHA256。交付复核入口为 `.artifacts/text-embeddings-20261112/delivery-validation.json`，新clone需取得本机回执或在新槽复验。

## 正文向量Web入口与共享执行验收

2026-11-13继续原文RAG第4步，新增 `text-embedding-purpose.tsx`，在HTML／PDF正文卡接入引用选择与用途入口。知识检索窗口保存最多32段引用，分页保留选择，条件变化或重新提交知识查询时清除。卡片复用现有选中样式，提供用途说明及含页码的可访问名称。

用途预览本地恢复原件，显示原文、原件哈希、Unicode区间、抽取版本、完整接收端和授权修订。管理员填写依据、公开性、可选到期时间并确认后，沿scope_hash／expected_revision登记用途。撤销复用已读scope，支持配置移除后的撤回。刷新失败使新授权等待重新核对，停止等待后可显式读取已提交结果。账户重验证重新建立窗口，旧操作的迟到成功与错误按原控制器和账户状态裁决。

现行 `VectorTools` 增加正文计划动作，复用 `textEmbeddingPlan`、`runEmbedding`、调用记录和历史读取。正文与结构化计划沿各自入口准备，执行共用单次确认、固定幂等标识、预算和账本。生成Provider主线沿用用户选定的OpenAI Responses。

### 验证结果

| 本轮范围 | 实际结果 |
| --- | --- |
| 相关API | 四模块125／125，792个输入稳定、资源关闭、非自检拒绝0 |
| SDK正文向量 | 5／5 |
| Web现有测试 | 50／50 |
| 三端类型 | Web／desktop／mobile最终检查均exit0 |
| 生产构建 | 两次独立目录构建均exit0，PWA白名单19项，next-env原字节恢复 |
| 浏览器主批 | 35项业务，加3个视口与4项已受理写／账户切换检查，共42项 |
| 末次构建复核 | 选择说明、页码可访问名称、选中样式、正文合同／缓存、独立确认及研究员权限6项 |
| 实际合成账本 | 2条请求、2条完成、2次合成模型调用、30 tokens及3块缓存 |
| 资源关闭 | API exit0、Web SIGINT exit1、浏览器页关闭，独立核对8003／18002均无监听 |

受管命令如下。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/txweb-r1 --targets apps/api/tests/test_text_embeddings.py apps/api/tests/test_embeddings.py apps/api/tests/test_source_text.py apps/api/tests/test_document_text.py
```

API结果为 `.artifacts/txweb-r1/result.json`，SHA256 `feaf0eeac4b02566b8c8d922ca9704ea433c31fba705522341f7874d6335dbc4`。浏览器与构建、最终类型／测试、关闭回执在 `.artifacts/text-embedding-web-20261113/`。浏览器主批的35项检查在移动仿真重载前逐项观察，其后转录为 `browser-prior-checks.json`，账户／布局及最终构建的工具原始返回分别保存在对应checks文件中。

浏览器使用隔离SQLite、自有合成HTML／PDF、合成Provider及模拟向量存储能力。生产API实际运行原件恢复、授权、计划、预算和账本。真实PostgreSQL／pgvector沿用前述54项独立报告。真实模型、专业材料、生产权限、原生平台与完整V1继续验收。

### 原始失败与恢复

原件写入先取得 `object_write_failed`，独立硬链接探针复现WinError 5，随后将隔离夹具移到宿主运行。第二槽在TestClient启动后添加中间件报错，按原始栈调整夹具为先注册路由和中间件、再启动应用，第三槽运行成功。沙箱Web就绪后宿主与浏览器均无法连接，独立核对无宿主监听，确认旧进程退出后在宿主启动同一生产构建。

浏览器断言中按钮空白匹配、React提交时序及已登录会话直接注册研究员产生过失败。后续断言按实际可用控件等待，并通过现行登出／注册入口切换到研究员。管理员写已受理、研究员身份和迟到响应的独立检查通过。PDF两页执行超过初始12秒观察时限，继续读取原窗口及账本取得完成结果，执行次数保持2。全部原始失败、旧槽和日志保留。

浏览器工具将直接文件输出判为工作区之外，截图通过工具图像返回检查后保存在本机忽略目录。一次大型命令触发MSIX启动器拒绝，最小PowerShell7探针正常，改用文件传递图像后保存成功。上述恢复均局限于本轮夹具和取证流程。

下一步实现正文向量召回、FTS融合及权威／地区／时效重排，再冻结原件引用进入证据包，贯通Responses、grounding、流式与报告。[当前交接卡](../../AGENT-HANDOFF-2026-11-12.md)
