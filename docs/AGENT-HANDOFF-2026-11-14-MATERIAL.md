# 许可原件与 robots 跳转 Agent 接手卡

更新于2026-11-14。本阶段已取得首份可恢复专业研究PDF，接通robots精确HTTPS跳转、@2传输凭证、正文引用与正常页面。完整V1持续实施，首个真实Provider为用户选择的OpenAI Responses API。[阶段验收](assurance/evidence/material-robots-original-2026-11-14.md)

## 需求与总进度

原规格按12个核心模块、10项发布Gate、13项SLO和15项待确认决策组织，各维度独立跟踪。12个模块均有工程实现，整体完成比例继续依赖发布验收。当前覆盖13个轮胎区域目录、9个厂商品牌、18项可信Parser和179张模型表。[原规格](requirements/2026-09-26-tire-intelligence-original.md) [全部需求与Gate](AGENT-HANDOFF-2026-11-14-PUBLISH.md)

| 模块 | 已有交付与当前主要缺口 |
| --- | --- |
| 轮胎查询 | 参数来源、组合筛选、在线优先及历史回退已有实现，P0来源／地区覆盖和EPREL正式凭据继续待验 |
| 精确版本识别 | 产品代码／GTIN／OE／地区身份、冲突和Golden工作台已有工程，代表性SKU／批次、真人Golden及错合并指标继续待验 |
| 车型适配 | SU7前后轴、车库、SKU证据桥及官方PDF工程已有实现，更多车型、完整OE事实和Native消费继续待验 |
| 比较 | 精确SKU比较、保存、同场测试与条件偏好已有实现，专业解释和真实推荐质量继续待验 |
| 测评数据库 | TestEvent、环境／指标／身份桥及真实原报道已有隔离验证，本阶段取得1份完整许可研究PDF，精确SKU正例和真人审核继续待验 |
| 信息监控 | Worker、参数差异、NHTSA、EU Safety Gate、中国召回、通知／SSE已有实现，自然长周期、通知SLO和任意网页／PDF差异继续待验 |
| 传统CRUD | 来源、规则、偏好、测试、账户、Provider、Key与费用规划已有实现，全实体覆盖、BYOK、真实账单和生产权限继续待验 |
| 证据浏览 | 快照／哈希／Parser、HTML／PDF正文和可恢复引用已有实现，本阶段补齐真实PDF与robots链，完整用途治理及生产对象存储继续待验 |
| 个性化 | 车库、关注、偏好、保存比较、非SKU兴趣已有实现，跨设备、长期运行和真实推荐质量继续待验 |
| AI研究 | grounding、同步／流式、报告、FTS／向量／融合检索与评估已有工程，真实OpenAI／Embeddings、语义质量和材料用途审批继续待验 |
| 对外能力 | REST、SSE、SDK、Webhook、Key、SQLite／PG受许可事实读取和许可CLI已有工程，公网接收端、吞吐、SDK产品化及完整WebSocket继续待验 |
| 管理后台 | Parser健康／发布回滚、隔离、失败任务、纠错和审计已有工程，生产IAM／Tenant／RLS、完整角色治理与灾备继续待验 |

非拥有者PG／TLS、迁移／verify及隔离备份恢复已有专项验收。Web／PWA、Desktop／Mobile共享前端已有工程，真实Native宿主／设备、六平台E2E、WCAG／读屏及其余发布Gate继续待验。

## 本阶段完成

1. 本地策略增加可选 `robots_redirect_urls`，上限3项。实际逐跳验证精确地址、公网解析、TLS、循环、唯一Location与总期限。
2. 实际robots跳转采用 `source-material-receipt@2`，既有@1和策略指纹兼容。原件、正文、引用及原UUID重放继续验证冻结策略与完整摘要。
3. 独立材料捕获总期限依据实测从20秒调整为45秒，连接4秒、读取8秒、8MiB上限、并发和节流保留既有参数。
4. Web正常入口展示策略许可、声明与实际robots链，核对完整SHA后下载原件，拒绝未知链及凭证版本降级。
5. 真实取得《Ultra Low Noise Poroelastic Road Surfaces》，DOI `10.3390/coatings6020018`，15页、6,136,722字节，第15页明确CC BY 4.0。完整摘要为 `00e7c08c6fe2dddee4444f22db86fcacb7b726b7aa69073f02291aac75a64be4`。
6. 正文正常API10项、非拥有者PG／TLS5项、来源SDK16项、生产浏览器两批各13项通过。Web66项、全工作区类型与生产构建通过，最终受管回归400／400通过，865输入稳定，资源关闭。

实际下载来自Semantic Scholar仓储副本。作者、题名、DOI、出版日期、原表及许可已由agent核对，系统凭证继续保存内容未核验与精确SKU待核对状态。第4页22行参测对象中的 `T1064/68` 等研究编号及 `196/60R15` 等原值保留。4000／4002 N与 `2,4800 N` 等条件差异、部分页文字层重复需要继续复核。[出版页](https://www.mdpi.com/2079-6412/6/2/18)

## 验证与资源

PG专项使用明确录制的真实原件／传输回执，实际网络捕获发生在独立SQLite工作区。浏览器通过正常生产页面和HTTP API核对该材料库副本，1440／390／320均无横向溢出，完整下载摘要一致。本轮12个进程ID、7个端口和临时秘密均已核对关闭。原件、数据库、截图与脚本仅保存在Git忽略目录。

当前API源码为 `a30c4a710a4c7977c664e4d1b7cf4e8dc65fc6907d78f1b977560f1ea3adccf8`，@4合同为 `50a00c964f79cf61ec80eb4f67f8b95cb4a14e7f4b2c7e7eefe323aadb84f5fe`。180 relations、179张模型表，catalog及向量索引声明与上一阶段一致，非拥有者verify通过。实际部署按目标环境审查批准合同。[详细回执、失败与资源关闭](assurance/evidence/material-robots-original-2026-11-14.md)

## 剩余需求与接续顺序

1. 以真实原件和可恢复页码引用推进参测对象与条件核对。将研究编号、型号和精确SKU分别记录，保留原文疑点，开展真人审核和代表性Golden。
2. 按实际复用需求审查材料的AI、Embeddings与导出用途。当前捕获策略中Provider和导出均为false，相关用途通过现有权限入口处理。
3. 继续来源自然长周期、真实变化、通知lag与恢复，按原规格≤5分钟通知目标收集证据。
4. 凭据可用时优先验收真实OpenAI Responses与Embeddings。EPREL正式Key继续缺失，推进可独立执行的工程。
5. 继续Parser间歇超时原始日志与文件打开耗时定位。该研究PDF正常索引及引用重新抽取已通过，历史性能问题继续待查。
6. 接续公网Webhook、生产权限与远端部署、真实Native／设备、多平台E2E、读屏、性能、灾备及其余发布Gate。[完整未完成项](AGENT-HANDOFF-2026-11-14-PUBLISH.md)

## 接手执行

```text
git status --short --branch
git log -8 --oneline --decorate
git log --oneline origin/main..HEAD
git ls-remote origin refs/heads/main
```

本阶段基线为 `5a56421`，最终提交、发布与实时远端以Git和交付消息核对。沿既有main工作，新分支／worktree及代理另需明确授权。用户已授权持续自主实施、材料选择、提交、push和交接。旧KIT C2封存请求保持原操作边界，失败材料和r5停止记录分别保留。

> 继续实施胎迹完整V1。先读本卡、阶段验收、PUBLISH需求总表及原规格。复用已捕获许可PDF、正常正文引用与有效回执，推进参测身份、条件、真人Golden、材料用途和发布Gate。首个真实Provider使用OpenAI Responses API，凭据缺失时继续独立工程。源码变动后重建并审查@4合同，保留真实网络、录制PG及页面副本各自验收范围，交付时核对全部资源、提交与实时远端。
