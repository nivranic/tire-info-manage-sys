# 第81轮：真实来源核验与集成回归前置

日期：2026-10-19，Asia/Hong_Kong。完整 Goal 继续 active；本轮不是完整 V1、首代车型自动查询或当前全套测试完成证明。

## 本轮已交付

1. 实际恢复两份首代 SU7 官方历史 PDF，200 application/pdf、原字节分别 8260598B 和 3240150B，均 12 页；保存原件、SHA、页面图与请求回执。Root 和独立 agent 分别目视核对第三页五个轮毂选项×三配置可用性、前后轴尺寸、套装条件和脚注。
2. 纠正文本抽取盲区：默认 PDF 文本缺灰色尺寸/轮胎说明；搜索摘要还把标准版/Pro 20 寸行漏成仅前轴，实际原件为**前后 245/40 R20**。不依据搜索、缺失文本或新一代配置填空。原件内部导致文本遗漏的具体机制没有进一步法证，不将“图形/outline”推测写成已证根因。
3. `apps/api/tire_api/adapters/xiaomi.py` 的首代目录链接指向真实官方历史 PDF，说明自动采集及 PDF 证据链待接入。仍 `requires_source_verification`、`model_year=null`；`fetch/parse_config` 继续拒绝首代。两项既有回归通过，元数据额外断言确认当前代链接与首代禁用状态不变。
4. 公开核验 EPREL 正式条款及无凭据访问边界，完成注册号查询/质量对齐/许可生命周期架构发现。用户已明确没有 Key，继续独立工作，不再重复请求 Key；没有猜正式 wire 或改用网页私有 API。
5. 完成专业材料三候选有界审查，收尾 KIT/Zenodo/DVSA；没有新增精确 SKU 或真人 Golden 正例。完成首代二进制链路的 46 项源码输入发现，以及当前 148 测试模块的隔离回归前置方案。

## 实际证据与可复用入口

根目录为 `E:/Mix/project/tire-info-manage-sys`，下面 `.artifacts` 路径均相对于根目录，不是 Git clone 自动带走的文件。

| 范围 | 当前入口 | 限定结论 |
| --- | --- | --- |
| Root 公开原件/访问 | `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/SOURCE_REVIEW.md` | 真实 PDF 原件、原始 SHA、页图、robots/HTTP 及 EPREL 状态；仅本机研究 |
| 独立视觉 | `.artifacts/r81-su7-visual-review-7ce747a644e64296b051f815a0d7fe39/REPORT.md`、`VISUAL_MATRIX.json` | 两份第三页分别阅读，五行、十五格和脚注；pixel/normalized locator 与原图 SHA；不是整份 PDF 相同或当前配置全集 |
| 源码发现 | `.artifacts/r81-next-functional-audit-5aeff75d83e64c21b4f64a8fe9cb3ff6/AUDIT.md` | Michelin CN 已实现，首代和二进制是真缺口；旧报告中首代 metadata 共用当前链接的描述已由本轮极小修改替代 |
| 二进制合同 | `.artifacts/r81-su7-binary-architecture-828ba44b291848aabaac332656e0bd0a/PHASE0.md` | RawCapture/对象/现有 IPC bytes 可复用；child、车型持久化、历史/审批/重解析及关系/兴趣/AI/离线哈希消费者需闭合 |
| EPREL 架构 | `.artifacts/r81-eprel-architecture-b64d7f91a37644259d79d3e71068c747/ARCHITECTURE.md` | 正式 schema/Key 未取得；不能把注册号当厂商产品码。Root访问事实以新目录 `eprel-access.json` 为准 |
| 专业材料 | `.artifacts/r81-professional-source-270573786a384ab4b3501b94cbafcc2f/REPORT.md` | KIT 禁止 archive 未请求；Zenodo 只取两个小原始成员，MAT 未读；DVSA 仅汇总 |
| 两项目标回归 | `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/targets-d525283a7337438197434de0a0165887/result.json` | **2 passed**；源码首尾稳定，禁止外网/子进程/正常 DB 尝试各 0；内置 socketpair 2，未运行监听服务 |
| 全套前置 | `.artifacts/r81-regression-preflight-e2b74cb159a84700be60e279aa56b75f/PREFLIGHT.md` | 当前静态 146 API＋2 Worker；子进程/metrics 运行许可另需实施；不是全套结果 |

目标测试是 `test_first_generation_does_not_reuse_current_generation_data` 和 `test_vehicle_catalog_is_metadata_only_and_database_starts_empty`。现有 FastAPI/Starlette TestClient 弃用 warning 一项保留，不是本轮产品失败。没有为链接修改新增测试，也没有运行无关前端构建。

## 来源与身份边界

官方早期参数表第三页明确区分 19 寸同前后轴、20 寸 SU7/Pro 同轴套装、Max 20/21 寸前后异配。仅完整证明这些已核原件中的配置关系，载重、速度、XL/OE/技术版本/厂商代码/GTIN 和完整 SKU 均未知。文件名 328、2024 权益文案不等于已声明年款或发布日期，保持年款未知；CLTC 是表中的整车续航注释，不是独立整胎性能测试。

原件来自[小米官方 PDF](https://s1.xiaomiev.com/activity-outer-assets/0328/env/SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf)。实际 robots 404 按现有缺失策略处理，公开下载不等于开放版权许可。当前仅本机核阅，没有生产 capture、Git 原件 corpus、外发 Provider 或再分发许可提升。

EPREL 一手依据为[官方说明](https://energy-efficient-products.ec.europa.eu/eprel_en)和[API 条款](https://ec.europa.eu/assets/move-ener/eprel/EPREL%20Public/Public%20API%20Term%20and%20Conditions/API_TERMS_AND_CONDITIONS_EN.pdf)。新直接请求记录 robots 200 text/html、候选文档入口 403，不能推导允许采集或已取得正式 schema。条款要求署名和本地副本落实更正/限制/删除，现有追加历史/来源暂停不能直接满足；此缺口与 Key 都未关闭。

KIT、Zenodo 和 DVSA 的许可/访问分别记录，不互相继承。Zenodo README 110905B、矩阵 21689B；矩阵仅 `Proc_mtx!A1:H306` 八个工况字段，Root另读 README 原文和图像。没有把研究编号当 MPN，没有把汇总结果归因任意品牌。

## 执行路线

[正式分阶段计划](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-19-official-vehicle-pdf.md)已经给出实际入口、存储选择、迁移与反例门。优先完成当前回归的收集诊断，再实现精确子进程/动态 metrics 的全套工装；首代采用显式 nullable 文本＋capture 引用，生产启用前闭合原字节、来源特定复核 Parser、审批/重解析/历史下载及下游核验。离线保持 `raw_included=false`，不扩已有 Host DTO。

正常应用/数据库未启动，无新迁移，无真实 Provider/receiver 调用，未提交或推送，所有未知 dirty 改动保留。R80及以前的封存保持原字节；本轮新清单是续作绑定，不要求旧清单等于当前新增文件集合，也不替代工作区/原件/私库备份。

全模块收集工装**未执行测试体**；本轮另有上文两项目标测试，分开记录。收集数量不能转换为通过数量。真实专业精确 SKU/外部真人 Golden、完整专业性能 C/真实 Responses、其他 P0、生产 PG/TLS/IAM、六平台与 WCAG 等原始发布 Gate 继续各自验收。

## 当前全模块收集：通过收集，保留护栏原红判定

最终诊断目录 `.artifacts/r81-collect-448308d57903424b97d6ab14fecc3809/`：pytest exit **0**，**4063 个唯一 nodeid**（146 API 模块 4040 项＋2 Worker 模块 23 项），228 个 collection report 全 passed。581 项输入在运行前后 SHA 一致，test protocol 和测试体执行为 **0**；collection 数据库连接为 0，未进入应用 lifespan。

护栏自检 12 项通过，9 次故意拒绝单列。collection 仍记录一次 network_bind 拒绝：动态调用栈为 `test_object_store.py:9 → boto3 → s3transfer → botocore.compat → urllib3.util.connection → _has_ipv6:127`，属于导入时本机 IPv6 能力探测，在真实 bind 前被拒绝并由依赖捕获。没有预设依赖结果、修改依赖或放宽监听许可。

原始 `result.json` 因严格判据保持 **passed=false、runner exit3**；pytest 收集 exit0 与这个判据是不同结果。Root 接受的派生限定分类是“收集通过，已知依赖探测被拒1，其他意外拒绝0”，供下一步设计运行工装，不称网络尝试0或全套通过。最终分类与封存见该目录 `classification.json`、`REPORT.md`；原红回执保留。

前四次分别保留在四个独立 `r81-collect-*` 目录：前两次是 SQLite authorizer 自检时序/参数分类问题，第三次是 pytest 默认日志写 NUL 被拒（collect0），第四次已收4063但尚未定位该依赖探测。第五次只增加无参数调用栈诊断。前两次仅落盘 source-before/bootstrap 和工装，没有生成完整 selfcheck/result/launcher 回执；其异常与退出码由独立 attempt-history 注明来自实际工具输出，不伪称原目录存在完整日志。所有尝试均未运行测试体，没有把工装错误标成产品失败，也没有通过删除拒绝计数制造成功。

本轮机器清单入口：`.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/verification-final.json`，以实际生成与独立复核为准；清单排除私库、账户和凭据，不是完整工作区或原件备份。

这只证明当前环境下可在 Python audit 边界内完成收集；不是 OS syscall 网络/文件沙箱保证。受管 Parser/CLI/Node 子进程、动态 metrics、R38 只读历史例外和完整测试执行仍须新工装实施，不能直接用本 collector 跑全套。
