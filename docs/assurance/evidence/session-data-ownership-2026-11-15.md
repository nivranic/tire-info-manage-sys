# 会话资料归属与登录轮换验收

本阶段基线为已发布b393b25。前阶段正常浏览器及数据库核对复现报告随会话换人转移。本阶段将持久资料owner与有效登录绑定分别保存，新增036迁移，修正报告／AI状态和私人通知恢复路径。方案和实现顺序见[实施计划](../../plans/2026-11-15-session-data-ownership.md)。

## 已实施

local_sessions新增owner_user_id与anonymous_claimable，当前179张模型表。登录、注册和已登录退出轮换Cookie，旧凭据失效。session_scope按持久owner聚合退休会话中的既有资料，current_user核对当前有效登录。在线及CLI重置口令、过期清理和删户保留owner。

新匿名会话可首次认领一次。036对旧明确user_id回填owner，旧无绑定资料保留且关闭自动认领。已发生的历史错绑需要独立证据恢复原属，该回填策略由agent根据可恢复信息制定。删除账户后历史owner仍保存在会话锚点，数据保留行为沿本机资料生命周期执行。

报告和AI沿AuthProvider的ready／ownerEpoch／ownerSignal，在身份重验时清除旧私有状态，取消请求并拒绝迟到结果。报告保存内存恢复按账户分区，AI恢复指针按账户存入sessionStorage。匿名指针仅保存在当前代次内存，刷新后可从服务端历史核对已受理调用。旧无归属浏览器指针停止自动采用。

私人通知从原规则会话取得持久owner，核对同账户存在有效登录后进入其授权Webhook订阅。同账户重新登录可继续投递，另一账户登录不会恢复其投递资格。订阅的其他用途与投递检查继续按既有合同执行。

## 验证结果

| 范围 | 观察结果 |
| --- | --- |
| 最终受管18模块r7 | 413项通过、1项跳过，0失败／不完整，867输入稳定、资源关闭、非自检拒绝0 |
| 此前扩大回归r3b | 485／485通过，涵盖AI／流式、离线owner、外部Key和接口、Webhook及车型离线读取 |
| 账户／报告／Webhook专项r5 | 238／238通过，含CLI口令恢复后的资料归属 |
| Web测试 | 68／68通过 |
| 类型检查 | Web、Desktop、Mobile及Native Client通过 |
| 生产Web构建 | Next构建通过，PWA生成19项壳资源 |
| 生产浏览器 | 最终25项通过，三种格式下载及摘要核对、1440／390／320布局、换号和跨标签页重验通过 |
| 最终非拥有者PG／TLS | 12项通过，4条越权SQL拒绝，正常HTTP进程完成PDF／AI／报告、Cookie轮换、口令重置及重启恢复 |
| 真实035旧PG升级 | 正式b393b25原始API源码创建旧库，180个关系中42条原行和旧列保留，升级至036、重复执行及@4合同匹配通过 |

最终受管记录中，Round38原始备份专用测试因指定只读备份不存在而跳过。该历史备份复验继续待验。真实035实验使用独立合成资料库，范围另行记录。

浏览器通过正常生产页面和HTTP入口，使用DOM事件驱动检索、录入、分析、报告及账户操作，额外保持身份读取未完成以检查旧报告先隐藏。PG使用独立非拥有者运行角色、TLS和显式verify合同。两者均使用项目生成的合成PDF／成绩及合成Responses，真实Provider调用为0。Rust／Android实机、生产远端、真实OpenAI／Embeddings、EPREL及完整V1验收继续待验。

## 失败与纠正

1. r1启动被已审查子进程源码摘要变化阻止。审查测试及CLI改动后更新REVIEWED的原始字节摘要，正式护栏继续生效。r1b在旧实现下复现新增账户归属用例失败。
2. r2包含5个报告相关失败，普通宿主同入口r2e只剩新增用例的导出断言。该用例把URL已有revision参数覆盖，实际请求缺少必填参数；修正请求后通过。沙箱原件存储边界沿此前已有WinError5证据处理，r2原失败保留。
3. r3启动因包含未登记测试模块被拒绝，随后使用正式清单r3b完成485项。该轮启动未写入结果文件，原始工具回执保留。
4. 新增两个私有通知正例复现同账户轮换登录后Webhook停投，失败位于投递数量断言。修正持久owner与有效账户登录的配合后，原账户恢复和另一账户隔离正反例通过。
5. 首批浏览器在报告与AI隔离通过后，因把车库误按私有资料断言而失败。复核原有local_workspace协议后纠正脚本并撤除针对车库的页面改动。最终25项通过，车库与保存比较的账户私有化列入后续范围。
6. r4及r6保留历史迁移断言失败。独立探针确认pre009／010／016当前形状夹具缺少12个既有页面／PDF FTS关系，固定023夹具的全链尾部还缺少13个已有SAMR表及036声明。补齐FTS前置、固定新增表清单、两列和索引的精确断言，旧列、业务行、原件和失败回滚继续逐项检查。固定023夹具原文件摘要核对一致。

## 部署合同与资源

最终API源码摘要为38de5e1d35ed970c62be40f36701f1b66790ea680db325280b486d7a91b35e84。PG18空参考postgres-runtime-schema@4合同摘要为95dd5a6ec32e7849e43a98cedce9e5cc9972d554fd6d5043e8e4fe30336357cd，含180个关系及179张模型表。实际部署按目标主版本、catalog、源码和向量索引声明生成并审查合同。

最终PG回执来自.artifacts/postgres/pgverify-98c7dedb08d44579a124f77f0388bb78，前批来自pgverify-7b96b03faf43451b9f7d0884ba2e456c。最终浏览器回执为.artifacts/session-ownership-20261115/web/run-51e862ef-3584-47d2-b704-ee7ec7739b3e/report.json，首批失败位于同目录另一run。原始源码归档、私有脚本、数据库、原件、下载、截图及全部结果均位于Git忽略目录。

两批PG及两批浏览器共14条服务记录、20个进程ID、11个端口均已核对关闭，限定进程匹配为空，临时口令及TLS私钥已移除。最终受管运行的5个子进程均已回收，资源关闭、867项输入稳定、非自检拒绝0，正常数据库启动与真实Provider／接收端调用均为0。

## 回执摘要

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/session-ownership-20261115-r7/result.json` | `257f34be3582cf6d09825dbd74870ade21f155c15834860c04ca2d4c5e8f2a45` |
| `.artifacts/session-ownership-20261115-r3b/result.json` | `5f4eb74fa85761dded0774513f27870669cd24d560ce1c192f4188ee26078c74` |
| `.artifacts/session-ownership-20261115-r5/result.json` | `5b1a172328b56d8d19ba2e7ad3d14bb7c3f166fb47ff4f18a77df2b023dc627b` |
| `.artifacts/session-ownership-20261115-r4/result.json` | `56465cca547243d897c4455369af21fb254199bc4cfa38692a24f7b47f5b5c82` |
| `.artifacts/session-ownership-20261115-r6/result.json` | `f367e59a978d448036aee84f176b5db1c5d87f9b61db43f78c567ffdcad6a6c9` |
| `.artifacts/session-ownership-20261115-webhook-red/result.json` | `a9988ce03bd27bbc856c42b87eff421049109c91f490555eeaf238582df758a9` |
| `.artifacts/postgres/pgverify-98c7dedb08d44579a124f77f0388bb78/report.json` | `1a09d00b1884c9513e9fd92352c170fb547d631435262a2b7f1dab7d13b376d0` |
| `.artifacts/session-ownership-20261115/web/run-51e862ef-3584-47d2-b704-ee7ec7739b3e/report.json` | `d91e580c79162c818bad108d8fc6cbb14c9dfb930a9c9a90eb845b19faebf2e3` |
| `.artifacts/session-ownership-20261115/web/run-91efc9d4-2053-4373-b918-a110baa2dde7/report.json` | `2ac126396264cc657d4c935332a6229f089eeb12356b98df938d592e9546aff3` |
| `.artifacts/session-ownership-20261115/resource-audit.json` | `d159dd9503e57b3b456898f34f6583c52335717ec047ac2d58e36abfed285dcf` |

本阶段已修正已复现的会话资料转移路径，整体AuthZ、生产IAM／Tenant／RLS、真人Golden、真实模型、Native／设备及发布SLO继续逐项验收。当前12模块、10项Gate、13项SLO和15项决策的接续入口见[本阶段交接卡](../../AGENT-HANDOFF-2026-11-15-ACCOUNT-OWNERSHIP.md)。
