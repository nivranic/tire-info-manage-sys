# 测试成绩 PDF 原件引用阶段验收

本阶段以已发布 `8f5a604` 为基线。成绩短摘录通过现有隔离PDF抽取核对原件区间，引用、修订、比较、AI和报告保存完整绑定。成绩仍沿人工转录与精确SKU证据桥流程使用。原件、数据库、脚本、截图和完整回执位于Git忽略目录。

## 功能与验证

| 检查 | 本阶段观察结果 |
| --- | --- |
| 最终成绩／AI／报告／SKU／Golden／偏好回归 | r6共315／315通过，867输入稳定，资源关闭 |
| 既有AI、流式、报告、PDF与正文用途 | r5共122／122通过，来源输入稳定，资源关闭 |
| Web纯函数及既有测试 | 68／68通过，新增 malformed PDF引用反例 |
| 共享前端类型 | Web、Desktop、Mobile和Native Client类型检查通过 |
| 生产Web构建 | Next生产构建通过，PWA生成19项允许缓存的壳资源 |
| SDK | 正文引用7项、成绩PDF精确传输5项及既有偏好合同脚本通过，采用注入传输 |
| 非拥有者PG／TLS正常HTTP进程 | 9项通过，4条越权SQL拒绝，独立API重启后原件、冻结报告及下载可恢复 |
| 正常生产浏览器 | 首批完整流程15项通过，三格式下载及摘要核对通过，1440／390／320均无横向溢出 |
| 账户切换扩展浏览器 | 17项通过后，报告归属隔离检查失败，见下文 |

保存检查覆盖旧记录／显式null指纹兼容、错误文档／指纹／SHA／抽取版本／页码／码点／chunk拒绝、改写短摘录拒绝、解析期间并发修订及历史保留。AI检查覆盖用途缺失前拒绝预留、派发前撤回、同步／流式、派发后撤回／修订／原件损坏／标记删除、实际用量保留、报告导出单独授权和撤回后拒绝旧下载。

PG和浏览器均使用项目生成的合成PDF、明确合成成绩与合成Responses。浏览器通过正常账户登录、编辑器检索选择、错误摘录提交、保存、追加修订、历史重开、同场比较、原件恢复、用途登记、流式分析、保存报告及三种下载入口操作。真实OpenAI、真实专业成绩及生产部署继续待验。

## 新发现的已有账户归属缺陷

扩展浏览器在同一浏览器退出 `pdf_browser`，通过正常页面注册 `pdf_other` 并重新打开报告库。页面仍列出前一账户创建的合成报告，数据库核对显示报告原有 `actor_session_id` 已归入第二账户。

`auth.py`的logout将当前 `local_sessions.user_id`置空，随后login／register通过 `bind_session`重绑同一行。报告以 `actor_session_id`归属，`session_scope`按当前绑定用户聚合，因此历史报告随会话行转移。该行为来自本阶段基线，API账户代码在本阶段保持基线版本。

此项按P1候选记录，账户隔离验收失败，AuthZ与无未处理P0／P1发布Gate继续开放。接续需联合核对匿名资料归属、退出后的凭据失效、过期会话回收及同账户多会话聚合，再完成修正与回归。重建原件组件的前端代次只覆盖页面状态更新，报告持久归属还需独立修复。

相关原始记录位于 `.artifacts/test-measurement-pdf-20261114/web/run-67bed896-8891-4596-95f3-f9c28cbd80cd/`，包含正常业务流程、三视口、账户切换失败和只读数据库复核。该批整体为失败，前17项分别保留通过记录。

## 失败与纠正

1. r1成绩保存43项、r2首次AI专项8项通过。r3的237项中235项通过，两项新增流式测试在旧5秒辅助等待处失败。事件时间线保留accepted、started与draft，测试结束关闭应用后记录interrupted。新增用例等待改为90秒，生产owner期限保持既有值，r4对应两项通过。
2. r4扩展315项中314项通过，唯一失败为pre019当前形状夹具。最小探针观察全链初始化新增12个页面／PDF FTS关系及2个目标表，旧断言只预期目标两表。夹具补齐现有两个FTS初始化器，最终r6复验结果见回执。
3. PG首批通过原件索引和保存，驱动提交完全相同的修订，被既有无变化409拒绝。驱动改为真实条件变更后，全新独立集群9项通过。
4. 浏览器私有驱动先后纠正注册成功码200、用途切换后旧dialog节点、末尾探针跨端口及保存后详情未加载时提前断言。业务源码沿原实现验收，首批完整15项通过，后续账户检查保留真实失败。
5. 初次交付扫描覆盖历史HANDOFF整文，识别出历史本机路径。最终扫描只核对新增差异和新文件，既有历史内容按原Git正文保留。

## 部署合同

本阶段API源码摘要为 `bc2a64542a304cbd36a29cafa3dfd4e1e2bdc692c0852642fb9715ef47a3b1f8`，本机PG18空参考 `postgres-runtime-schema@4` 合同摘要为 `e344ee0e2fe39d3fcef30c98c9c47c0daa24bc1e784ea8029ccf748bb1237b87`。合同包含180 relations、179张模型表，本阶段引用保存在既有JSON中。实际部署按目标主版本、catalog、源码和向量索引声明重新生成并审查合同。

PG通过批次为 `.artifacts/postgres/pgverify-d50169e9d5f744d19b65a360df02d63f/`。运行进程只取得非拥有者权限与明确合同，成功观察TLS连接、原件解析、具体用途登记、报告导出及重启恢复。真实Provider调用为0，合成Provider调用为1。

## 原始回执

最终受管两批315／315与122／122通过，867输入稳定。六批浏览器与两组PG共19条服务记录、30个进程ID、11个端口及临时密码／私钥均已核对关闭，相关进程匹配为空。受管运行目录为 `.artifacts/test-measurement-pdf-20261114-r1/` 至r6，私有浏览器、SDK、PG驱动和审查记录位于 `.artifacts/test-measurement-pdf-20261114/`。首批完整浏览器为 `web/run-8d72d6ff-8fba-48b5-bf7d-55f3e95bf5cf/`。



| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/test-measurement-pdf-20261114-r6/result.json` | `9dc3dd4e00ede31281d1a8c473b34269f271428b1b3db5cd9f2b8e4177d0250a` |
| `.artifacts/test-measurement-pdf-20261114-r5/result.json` | `c890a52d469f993413ed25b8816aac40172df80847553c8a81caed4d58395e5d` |
| `.artifacts/postgres/pgverify-d50169e9d5f744d19b65a360df02d63f/report.json` | `d9e7014cf2c0ea58fc9fa7577ab1a61837648361798fa1393686c266d4710a22` |
| `.artifacts/test-measurement-pdf-20261114/web/run-8d72d6ff-8fba-48b5-bf7d-55f3e95bf5cf/report.json` | `c8500558479662690443b790e00dd15bc3260ffe3dd2f38b91c7e735c503ee8e` |
| `.artifacts/test-measurement-pdf-20261114/web/run-67bed896-8891-4596-95f3-f9c28cbd80cd/report.json` | `02784379ff57c6b930679225cfd9f535aad83bf73a7818c9a4c960ead10cf82d` |
| `.artifacts/test-measurement-pdf-20261114/web/run-67bed896-8891-4596-95f3-f9c28cbd80cd/owner-database-check.json` | `c7abad751b9fdf90d7a7d1965c327ef6d0c4c7c11ad4676a3f9c420489f94c31` |
| `.artifacts/test-measurement-pdf-20261114/resource-audit.json` | `11bb39ad88a358e3993b9670705c1496d1749e243ed0387b944b4b08bc1bf4a4` |

## 发布与接续

本阶段沿既有main交付，推送前审查上游到HEAD的正式提交序列，发布后独立核对远端及工作区。GitHub实际发布方式和最终提交以交付消息及本地回执核对。完整V1继续执行，优先处理上述账户归属缺陷，再接续真实成绩、SKU／真人Golden、材料用途、真实OpenAI／Embeddings、EPREL、自然长周期、Native／设备与其余发布Gate。[Agent接手卡](../../AGENT-HANDOFF-2026-11-14-TEST-PDF.md)
