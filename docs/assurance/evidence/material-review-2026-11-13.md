# 专业材料核验与文献转录记录

记录日期为2026-11-13。工程基线为 `74b62a66d7e6abde52b5189f7b194a52142e5a05`，当前进度、发布Gate及接手顺序见[Agent交接卡](../../AGENT-HANDOFF-2026-11-13.md)。本次收尾复核既有运行回执并更新交接文档，产品源码沿用该基线。

## 文献来源与解释范围

Chen Liang等的 *Evaluation and improvement of tire rolling resistance and grip performance based on test and simulation* 刊于2020年卷期，DOI为 `10.1177/1687814020981173`。网页工具返回14页PDF的抽取文本及HTML表1，文章声明CC BY 4.0。本次人工转录保留题名、作者、出处、许可与改动说明。表1转述参考文献17，原始测试机构和原数据权利继续核对。[出版页](https://journals.sagepub.com/doi/full/10.1177/1687814020981173)

表1列出10款205/55R16轮胎。本次记录滚阻参比比值与干地制动距离，共20条数值。依据文中描述，滚阻为80 km/h测量值与参比胎测量值之比，单位为 `1`，干地制动为100 km/h至停车，单位为 `m`。参比胎、原测试车辆、胎压、载荷、温度、地点及日期保留未知。240 kPa与4821 N属于另一个接地变形实验，该实验条件单独处理。[出版页](https://journals.sagepub.com/doi/full/10.1177/1687814020981173)

型号采用HTML表1拼写，包括 `MARMONIC M220` 与 `N’FEAR SU4`。行号用于定位，`source_rank` 均为null。网页首发日期与2020年卷期冲突，`publication_date` 为null。精确SKU、GTIN、产品代码及载速仍待证明。[出版页](https://journals.sagepub.com/doi/full/10.1177/1687814020981173)

参考文献17为Zhang ZY的 *Tire performance tests in Germany*，2016。下一步从原报道核对测试主体、参比胎、协议、成绩和参测身份。[参考文献原链接](https://www.autohome.com.cn/drive/201608/891160-2.html)

## 隔离库中的正式API链路

有效批次位于Git忽略目录 `.artifacts/material-sage-table1-20261113-r2/`。通过 `POST /v1/test-events` 创建1条待审核事件，10个参与者均为 `participant_only`。随后经正常比较和知识检索入口核对，再重建应用生命周期、重新登录并读取冻结修订。应用采用进程内TestClient与显式隔离SQLite，AI及Embeddings关闭。

| 检查范围 | 原运行回执结果 |
| --- | --- |
| 账户与创建 | 注册通过，事件创建HTTP 201 |
| 原值与身份 | 10个参与者、20条精确小数、待审核状态与participant_only通过 |
| 同场比较 | HTTP 200，测量值、无名次及same_event_only通过 |
| 真实FTS | Primacy检索返回该事件 |
| 隔离与完整性 | 单事件／单修订计数和SQLite quick_check通过 |
| 生命周期恢复 | 重新登录及冻结修订一致性通过 |

原批次共11项检查通过，`passed=true`、`database_closed=true`，记录两次数据库打开及DNS尝试0次。事件ID为 `fa1d272f-9254-4e2a-8bee-15d1227911da`，指纹为 `7daf2550d344898e7ee6f85c4267701ea7b93a68815114adc567591624e062fa`。

结果记录 `test_events=1`、`test_event_revisions=1`。TireVariant、Snapshot、FactVersion、Verification、EvidenceDocument及TestSkuLinkRevision计数均为0。数据保存在本机隔离库，真人审核和精确SKU关联各为0，原始PDF字节尚待留存。正常数据库使用记录为false。

可复核文件包括 `event-payload.json`、`event-response.json`、`comparison-response.json`、`result.json` 与 `import.log`。原网页工具观察另存为 `source-tool-observation.json`，PDF截图尝试失败，页面视觉核验继续待验。上述原始回执和隔离数据库采用现有Git忽略规则保存。

首批 `.artifacts/material-sage-table1-20261113-r1/` 在创建、比较及FTS后，因工装使用错误表名 `tire_test_events` 触发KeyError。第二批改用模型 `__tablename__` 读取计数，并对quick_check连接使用上下文关闭。两个批次的证据分别保留。

## PERS捕获与替代来源

PERS新批次位于 `.artifacts/material-pers-2018-20261113-r2/`，使用既有生产捕获API和独立私库。幂等UUID为 `90276487-1cea-4f6c-953a-648268d5d61f`，HTTP返回201，业务终态为 `failed`，错误为 `source_material_timeout`，document与receipt均为null。DNS观察仅记录大学主机，子进程计数为0。许可配置来自先前核验的CC BY 3.0声明。[PERS论文](https://doi.org/10.1088/1757-899X/421/2/022035)

直连探针记录MDPI PDF与两个出版商CDN候选均返回403，大学robots请求超时。JRC官方书目页返回200，保存55972字节HTML，测试编号到型号的明确映射继续待核。PERS表2中两个Primacy HP样本保留各自研究编号。[JRC书目页](https://publications.jrc.ec.europa.eu/repository/handle/JRC143043)

PERS失败及替代来源回执包括 `capture-response.json`、`result.json`、`direct_probe.json`、`cdn-probe.json` 和 `jrc-entry.html`。旧KIT C2封存记录继续按[交接卡操作约束](../../AGENT-HANDOFF-2026-11-13.md#操作约束)执行。

## 本次收尾复核与后续

本次读取两批转录回执、PERS请求及探针结果，核对20条数值、事件／比较响应、11项检查、隔离计数、来源观察和历史HANDOFF尾文。本次61项回执与文档核对通过，其中核对17个本地链接，`git diff --check`通过。交付检查另外记录于 `.artifacts/handoff-material-review-20261113/`。浏览器、产品回归、构建、数据库验收及真实Provider结果沿用各自阶段记录。

1. 从参考文献17核对原始测试与权利，取得可留存的原始材料，建立稳定页码和原件引用。
2. 将可证明的产品代码、GTIN、地区及载速信息连接至精确SKU，完成外部真人审核与代表性Golden。
3. 用代表性材料评估检索、排序和回答质量。首个真实生成Provider按用户选择接入OpenAI Responses API，所需模型与专用Key继续由本机配置提供。
4. 按交接卡继续推进生产权限、平台E2E、读屏和完整发布Gate。完整V1持续开放。
