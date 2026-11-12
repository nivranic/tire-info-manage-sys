# 2026-11-12 续作记录

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

## PostgreSQL实测停点

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
