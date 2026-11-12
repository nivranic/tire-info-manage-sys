# 2026-11-12 续作记录

> 最新PostgreSQL完整运行47项检查通过，补齐029–032对应业务的事务、历史、并发停止及恢复验证。147张模型表恢复指纹一致，七模块受管回归204／204通过。前次45项与11项回归保留历史范围。最新结果、原失败及剩余范围见本文末节。

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
