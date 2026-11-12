# 专业材料核验与文献转录记录

记录日期为2026-11-13。文献转录阶段的工程基线为 `74b62a66d7e6abde52b5189f7b194a52142e5a05`，随后交接记录以 `b7b56f0` 发布。本次继续追溯原始报道并验证真实数据的页面展示，产品源码沿用既有实现。当前进度、发布Gate及接手顺序见[Agent交接卡](../../AGENT-HANDOFF-2026-11-13.md)。

## 此前文献转录阶段的来源与解释范围

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

## 文献转录阶段的收尾复核与后续

本次读取两批转录回执、PERS请求及探针结果，核对20条数值、事件／比较响应、11项检查、隔离计数、来源观察和历史HANDOFF尾文。本次61项回执与文档核对通过，其中核对17个本地链接，`git diff --check`通过。交付检查另外记录于 `.artifacts/handoff-material-review-20261113/`。浏览器、产品回归、构建、数据库验收及真实Provider结果沿用各自阶段记录。

1. 从参考文献17核对原始测试与权利，取得可留存的原始材料，建立稳定页码和原件引用。
2. 将可证明的产品代码、GTIN、地区及载速信息连接至精确SKU，完成外部真人审核与代表性Golden。
3. 用代表性材料评估检索、排序和回答质量。首个真实生成Provider按用户选择接入OpenAI Responses API，所需模型与专用Key继续由本机配置提供。
4. 按交接卡继续推进生产权限、平台E2E、读屏和完整发布Gate。完整V1持续开放。

## 原始报道追溯

本次直连取得汽车之家2016年原报道的两页HTML，均为HTTP 200，分别为209638及203978字节。页面署名张子仪，发布日期为2016-08-03。正文说明Auto Bild汽车画刊与汽车之家合作，测试地点位于德国汉诺威以北约25公里的马牌轮胎测试场，执行者为场地专业测试员。委托关系仍为unknown。[原报道第1页](https://www.autohome.com.cn/drive/201608/891160.html)

原表提供10款轮胎的载速标识和中国产地声明，包含5款V级、5款W级，其中路航为94W。两处源名差异需要保留双侧出处。原报道万力型号为 `HARMONICH220`，论文写作 `MARMONIC M220`。原报道耐克森型号为 `N’FERASU4`，论文写作 `N’FEAR SU4`。这些信息继续按参测对象记录，精确SKU关联待证。[原报道第1页](https://www.autohome.com.cn/drive/201608/891160.html)

第2页中的3张图经HTTPS直接取得并实际目视核对，其中干地制动距离和滚阻图共20条数值与论文表1相符。干地制动图标注100 km/h至0 km/h、dry asphalt，滚阻图使用无量纲CR[-]。原报道未提供足以核对的滚阻参比定义和速度，原始报道事件的协议按其自身声明填写。网页、图像的完整复用许可继续待核对。[原报道第2页](https://www.autohome.com.cn/drive/201608/891160-2.html)

原始材料与解析结果位于 `.artifacts/material-original-source-20261113-r1/`，包括 `direct-probe.json`、两页HTML、`extracted-article.json`、`chart-downloads.json`、三张图及 `reconciliation.json`。SAGE PDF及robots本次直连均返回URLError，原始PDF仍待留存。

## 原始报道API与页面验证

新的原始报道事件位于 `.artifacts/material-autohome-2016-20261113-r2/`，经正常创建、比较、知识检索及历史读取入口执行。事件保留原表型号、10条载速信息与20条数值，所有参与者为participant_only。事件ID为 `527cb31c-067b-434a-99be-b49f08c45e66`，指纹为 `f5d71e11827e0762ae2f3dab9777f7a04350cafd0bd3ffcb990d2f86c169f348`。

| 范围 | 本次结果 |
| --- | --- |
| 独立API批次 | 12项检查通过，含错误指标键422、正确同场比较、真实FTS和重启冻结读取 |
| 数据计数 | 1事件／1修订，TireVariant、Snapshot、FactVersion、Verification、EvidenceDocument及TestSkuLinkRevision均为0 |
| 页面实例 | 另建全新私库，经正常API创建相同指纹的事件，ID为 `44f25679-d562-49cc-ab9a-f896fbec5566` |
| 桌面页面 | 实际打开、选择10款并比较，两个表中的20条成绩与无名次逐项核对通过 |
| 390与320像素 | 每个视口保留20条成绩，页面宽度分别为390和320，表格使用640像素内部滚动区域 |
| 引用与身份 | 原表型号、载速、许可缺口及LOCAL SNAPSHOT可见，原图逗号小数与图像URL可重开 |
| 资源关闭 | 页面关闭，API退出并关闭数据库，Web进程停止，3个指定PID均缺席、两个端口无监听 |

页面验证复用此前 `.next-web-a11y-qa` 生产构建，Web及SDK运行时代码与该构建阶段一致，API使用本轮 `b7b56f0` 基线。浏览器通过真实loopback HTTP访问隔离SQLite中的转录记录。API的外网尝试、正常库使用和Parser子进程均为0，AI与Embeddings关闭。

页面观察、截图及关闭回执位于原始材料目录的 `originalMaterialBrowser*.json`、`browser-wide.png`、`browser-390.png`、`browser-320.png`、`browser-workspace-r2/` 和 `browser-closure.json`。已实际查看桌面及两份窄屏截图。长表使用容器内横向滚动，长证据展开后需要纵向滚动。本次页面范围为该真实场次，完整读屏、跨浏览器、原生设备和发布Gate继续待验。

### 本次失败与修正记录

- 首次API导入在比较工装中沿用了论文的 `rr_ratio` 指标键。第二批先重现该请求的422，再从实际事件定义读取指标键，12项检查通过。首批回执完整保留于 `material-autohome-2016-20261113-r1/`。
- 首次UI工装在TestClient启动后注册中间件，启动报错。修正注册顺序并使用全新私库启动，首批工装及错误日志保留。此前API未就绪时页面的5条500请求保留在网络观察中。
- 切换移动设备仿真产生了文档重载，初次窄屏探针读取到尚未重新打开的场次。重新按页面入口打开并比较后，两种宽度验证通过。失败探针与最终结果分别保存。
- 浏览器工具对指定文件路径返回拒绝，快照与截图改用工具返回内容，在工作区保存。关闭核验首版受PowerShell JSON日期自动解析影响，改用字符串日期读取后，PID及启动时间原值核对一致，再停止对应Web进程。诊断保留于 `closure-time-diagnostic.json`。

本阶段65项材料、运行回执及文档核对通过，17个本地链接有效，`git diff --check`通过。完整产品回归结果沿用前阶段记录。本阶段交付复核为 `delivery-validation.json`。

## 当前后续工作

1. 获取可证明参测版本的GTIN、制造商产品代码或侧壁标识，核对万力与耐克森的双侧源名，建立精确SKU证据关系并完成外部真人审核。
2. 核对原报道全文和图表的复用许可，取得可留存专业原件并建立正式原件引用。已取得的HTML与图像继续作为本机研究证据。
3. 在代表性真实材料上推进检索、排序和回答评估，首个真实生成接入沿OpenAI Responses API执行。所需专用模型／Key及EPREL Key继续待配置。
4. 继续推进P0来源覆盖、监控长期运行、生产权限、平台E2E、读屏及发布Gate。完整V1持续开放。
