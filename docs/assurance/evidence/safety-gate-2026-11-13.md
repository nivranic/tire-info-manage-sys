# EU Safety Gate官方周报与安全告警证据验收

本阶段从main的 `3abdc0952bd5c200e1f6b86ae3897cb284f152ca` 开始，接通原规格P0 Safety来源。正常API与生产Web支持英文周报索引、所选周报、原始XML、明确历史读取和单次授权回退。完整V1持续active。[实施计划](../../plans/2026-11-13-safety-gate-source.md)

## 官方材料与许可依据

官方robots允许固定XML入口。索引包含1124份周报，已核对2005、2019和2026年的四份完整周报。官方元信息的XML分发 `d932935c-3916-4421-a6a4-91efe196ef4b` 声明CC0，周报网页分发 `1c42bf60-98c1-4728-b8da-e3f152783068` 声明COM_REUSE。响应与快照保存XML分发身份、许可URI、元信息地址及署名。[周报索引](https://ec.europa.eu/safety-gate-alerts/api/download/weeklyReport/list/xml/en) [官方元信息](https://data.europa.eu/api/hub/repo/datasets/rapex-rapid-alert-system-non-food.jsonld)

元信息原始JSON-LD为176588字节，SHA256为 `2fea9003a728284a4964e9824df3692a0ebab3b08a720898a5b6b203266d3730`。当前免责声明PDF入口返回403，旧webgate地址返回307并指向官方sorry页面，原访问结果保留。具体商业、再分发与其他材料范围继续核对对应合同。本阶段保存并展示官方XML，图片地址作为来源字段保留。[免责声明入口](https://api.tech.ec.europa.eu/justools-content/buckets/saga/folder/menu/filename/New_disclaimer_EN.pdf)

| 官方reference | 原生report_id | 周报发布日期 | 完整告警条数 | 已核对内容 |
| --- | --- | --- | --- | --- |
| Report-2005-1 | 149 | 2006-01-20 | 8 | 负数告警及图片ID、较早DTO与缺失字段 |
| Report-2019-050 | 3712 | 2019-12-13 | 40 | 三位周号、缺图片节点及历史撤回补充声明 |
| Report-2026-19 | 10000305 | 2026-05-15 | 35 | Goodyear商用翻新轮胎告警SR/01396/26 |
| Report-2026-45 | 10000331 | 2026-11-13 | 75 | 当前完整周报及空值 |

SR/01396/26的原生告警ID为10098848，告警发布日期为2026-05-12。原文记录Goodyear商用翻新轮胎及五个受影响序列号，型号、生产字符串、风险和措施均按英文原值保存。具体SKU及实物适用性为 `not_assessed`。[官方告警](https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/10098848)

## 正常业务链路

- `POST /v1/safety-gate/query` 分别查询reports与report，指定周报绑定report_id和reference。先核对整份XML的结构、顺序和身份，再提供完整结果。
- 周报编号、告警编号与发布日期分别保存。索引有9条周报年份与发布日期年份不同的记录，周号存在1、01和050等历史格式。负数告警及图片ID保持原值。
- 复用SafeHttpClient、robots、限速、熔断、隔离Parser、发布选择与执行记录。可信Parser目录增至15项，历史8至14项完整目录继续接受并执行。
- 新增两个只追加模型表，复用QueryRun、原件对象、来源管理代次、摄取锁与FallbackConsent。304核对在线验证器、原件及Parser身份，晚到304继续核对当前头。
- 在线失败返回空document与空provenance，单次授权绑定本人会话、来源及完整查询。明确history和evidence入口读取对应已保存证据。
- 共享SDK及Web安全公告工作区支持索引选择、当前周报内筛选与分页、英文原值、日期、适用性、原件和历史状态。关闭窗口、切换方式及来源代次变化会使旧请求失效。

官方端点出现两种XML序列化，分别采用CDATA／xsi:nil及转义文本／空节点。两份Report-2026-19原件的SHA256为 `7c084f273d718306752c86d288c61e076388b246d1218b0fd6c55dda1f47eacf` 与 `c9a9623e34d52ca728c811bff466948afca1f5cc0275368493ba67cf49b6d9fd`，规范化文档一致。原件字节变化分别形成快照，完全相同的原件和Parser身份重复核验复用快照。

## 已取得的验证

| 范围 | 结果与本机回执 |
| --- | --- |
| 十一模块受管回归 | 262通过、0失败、0跳过，809输入稳定、资源关闭、非自检拒绝0，`.artifacts/sg-r6/result.json` |
| 正常HTTP API与真实官网 | 52项通过，成功批次6次真实查询，包含索引与四份周报，`actual-api-result-final.json` |
| 生产Web与真实官网 | 60项通过，2次明确在线查询、原件SHA256、分页、历史及迟到原件取消，`browser-*.json` |
| 三种精确视口 | 1440／390／320像素下页面、弹窗和面板均无横向溢出，320像素截图已目视核对 |
| Web与类型 | Web55／55，Web／Desktop／Mobile类型均exit0，`frontend-validation.json` |
| 独立生产构建 | exit0，412输入稳定、生成文件原字节恢复，`.next-safety-gate-qa` |
| 关闭后数据库 | 34项通过，174表的列与逐表行指纹在WAL归并前后保持一致，原件对象与快照逐项核对，`closed-state.json` |
| 旧库副本升级 | 9项通过，旧172表及原行保留，仅增加2表至174，4份旧原件有效，原14项目录的Parser部署保留，新增来源为15项目录的修订1，`upgrade-validation.json` |
| 资源释放 | 自有API／Web及启动进程、8005／3065监听均缺席，项目页已释放至about:blank，`closure.json` |
| 交付静态复核 | 178项通过，重新绑定809个后端输入、412个构建输入、实际Parser包、原件与关闭后库，核对105个本地链接、31个交付文件及历史文档，`delivery-validation.json` |

本机验收根目录为 `.artifacts/p0-safety-gate-20261113/`，早期官方下载位于 `.artifacts/p0-official-20261113/`。关闭后的主验收库包含10次查询、9份捕获、1份拒绝观察、7份快照及8次成功核验。此前两次失败查询保留consent_required，采纳为0。轮胎事实、美国召回、AI请求及Embedding请求均为0，AI状态为openai_responses／ai_disabled。

主验收库SHA256为 `80db16f9e4d5ed57c531a680f7ab69c6867648c087d62748a933990a0870b96f`。升级验证使用此前关闭的固特异验收库副本，源库原字节保持一致。实际生产部署和PostgreSQL专项继续按具体发布目标验收。

交付时再次只读核对自有进程及8005／3065监听均缺席，OpenAI模型／Key与三个约定EPREL Key变量在Process／User／Machine作用域均为空。交接卡已补齐Safety Gate受管回归命令，并压缩可复制的接手指令。回归结果SHA256为 `9d5865520dd11b4aa80d38dc3ecf9bd9c9b51ee72b393766b911ede1c374098a`。

暂存的180个Parser包文件与本机已验收源码逐项核对，23个既有文件具有Git文本换行归一化差异，所有文件归一化后的字节均一致。原始回执和包哈希绑定当前工作区字节，新clone需封装自身Parser包并建立对应验收回执。核对记录为 `staged-source-binding.json`。

## 原始失败与修正记录

- 初次保护性启动因本轮已修改源码的受审哈希未更新而拒绝。核对三个源码变更后更新绑定，全部保护规则保留，记录在sg-r1。
- sg-r2取得28通过／1失败，定位到现有Recall Parser默认要求list输出。新增来源的完整文档使用dict，现已按固定source_id补齐监督器合同。
- sg-r3取得144通过／4失败，涉及旧包重建工装仍使用当前15项目录，以及三处旧当前目录断言。修正工装与断言后继续保留历史包执行。
- sg-r4在收集阶段发现新增参数组缺少对应ID。sg-r5取得199通过／1失败，定位到厂商测试仍将当前目录写为14项。三家厂商的当前目录断言已更新，最终sg-r6通过。
- 首次真实HTTP查询因upstream_timeout返回待授权状态。第二次取得原件后在Parser创建前失败，安全异常栈定位到验收启动环境缺少Windows架构变量。自有启动器使用系统API读取的X64／AMD64启动新进程后，真实来源链通过。
- 真实查询复核初版断言假定同一周报的原件字节固定。取得两种官方序列化后，改为核对规范化文档一致及原件变化对应独立快照，原件与原断言记录保留。
- Web首版启动方式在相对模块解析处退出，改用正常apps/web工作目录后正常启动。浏览器工具的文件输出受其工作区配置拒绝，已通过现有文件工具保存返回结果。
- 1440像素初始测量将页面宽度1425与innerWidth1440的滚动条差值判为失败。复核实际clientWidth1425后，以scrollWidth≤clientWidth核对，三个宽度均通过。原失败测量保留。
- 交付复核首轮误查sg-r1的最终结果文件，实际启动保护回执为runner-failure.json。核对原始ChildDenied后按启动回执验证。沙箱CIM读取拒绝的回执保留，授权执行通道的只读进程与端口复核通过。
- 暂存源码初查要求Git blob与本机包的原始哈希全部相等，取得23个差异。逐字节复核确认差异来自既有文本换行规约，归一化比较180个文件全部通过，原检查失败保留。

## 后续完整范围

逐告警跨周修订与事件、Safety Gate长周期监控、持久回退策略、外部Key权限、AI引用与Native消费继续实施。更多轮胎样本、完整许可治理、生产PostgreSQL／IAM、读屏、六类平台、13项SLO及10项发布Gate继续验收。[当前交接卡](../../AGENT-HANDOFF-2026-11-13.md)
