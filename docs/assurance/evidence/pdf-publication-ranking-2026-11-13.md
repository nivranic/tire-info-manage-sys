# PDF正文出版日期与时效排序

## 实现

成功捕获的材料策略已包含可选出版日期，原PDF正文检索统一使用 `publication_unknown`。本轮在原件、投影及捕获凭证校验后，复核对应冻结请求，将已有日期接入时效排序。[实施计划](../../plans/2026-11-13-pdf-publication-ranking.md)

存在日期的候选输出 `time_basis=policy_publication_date`，另含ISO日期、材料请求ID和策略指纹。日期精度为日，排序值取该日UTC零点。页面明确展示“材料策略声明出版日期”及两项凭证标识。排序依次使用来源类别、地区、RRF和时间。

日期来自该次捕获的冻结配置声明。来源真实性、权限和精确SKU身份依据对应凭证核对。当前策略目录的更新通过后续捕获形成新记录。缺少日期的PDF返回未知，HTML使用原件观察时间。

## 正常API回归

四模块受管回归156／156，无失败、跳过或incomplete。799个受管输入稳定，资源关闭、非自检拒绝0，正常数据库与真实Provider调用均为0。范围为正文混合检索、PDF索引、材料捕获和离线检索质量评估。

新增4个案例覆盖有日期和无日期的正常捕获、正文提取与索引、独立向量用途授权、混合检索、原文恢复、同分排序及分页。当前策略目录修改和移除后，冻结日期与历史回执均按原记录恢复。损坏捕获元信息在查询派发前按既有409完整性路径拒绝。

回执为 `.artifacts/pdfdate-green/result.json`，SHA256为 `2ad9e8bc8c17bf3919f35f33ed4ed74380a5f0ab6e7932430f8afa5ad2871916`。首次红批 `.artifacts/pdfdate-red/` 保留1通过、3失败，其中日期字段缺失占两例，另有一例测试误将既有409拒绝预期为503。该断言已按现有合同修正。

## PostgreSQL与备份恢复

隔离PostgreSQL 18.3／pgvector验收完成，既有综合验收58项及本轮日期专项7项分别通过。153张模型表经实际dump／restore核对指纹一致，备份761609字节。日期场景经正常捕获、正文索引、独立向量授权与混合检索进入真实FTS和余弦查询，两个候选的实际余弦距离均为0。同分排序专项使用受控FTS名次，余弦仍由真实PG计算。

恢复后核对冻结日期结果、请求与策略指纹、原文引用、当前日期投影和实际向量距离，恢复专项Provider派发为0。新增日期阶段合成Provider调用4次。源码和临时驱动输入均稳定。

最终集群报告为 `.artifacts/postgres/pgverify-6c96ddd5d7934e4299cc6d3bd6225c08/report.json`，SHA256为 `1a4e856cb14bedc5387a85d847e198b3e953aecbd8c74eb589d698a803d4fcbf`。日期专项为 `.artifacts/pdf-publication-20261113/postgres-date-checks.json`，SHA256为 `143d1d3643231f4143e30e134a95851ef55c7271514e703e0eea166edf10fe45`。材料和Provider采用合成输入，真实模型语义与代表性专业材料继续待验。

首轮临时驱动未把 `scripts` 加入导入路径，综合验收在 `recent_history_acceptance` 导入处失败，该集群已停止。修正范围为临时驱动，初批回执保留于 `.artifacts/pdf-publication-20261113/postgres-run-r1.json`、`postgres-date-checks-r1.json` 及对应集群报告。

第二轮通过新增日期的四项查询检查，在恢复阶段因驱动将日期checkpoint放在外层返回对象而失败。按既有验收器会取出内层checkpoint的合同修正后，第三轮全部通过。第二轮回执保留于同目录 `postgres-run-r2.json`、`postgres-date-checks-r2.json` 及对应集群报告。

## 前端验证

Web、Desktop及Mobile类型检查全部exit0，Web测试55／55。实际React正文结果组件使用合成响应，在1440、390及320像素下分别通过10项检查，合计30项。日期、请求ID、策略指纹和未知日期可见，选择操作生效，页面、容器及字段均通过横向溢出检查。该组件批次的API请求为0，控制台error／warn为0。

320像素截图已实际查看，日期可读，请求ID与长指纹换行显示。截图保存在本机Git忽略目录。组件打包使用当前源码，39项依赖固定并在服务关闭时复核稳定。该批属于实际React组件验证，整站生产构建与平台验收继续依据对应回执核验。

首轮组件夹具省略了生产页面的 `knowledge-content` 容器，缺少其继承的长文本换行样式，390及320像素检查失败。按实际DOM及CSS定位后补齐生产容器，第二批全部通过。首批失败和几何记录继续保留。

最初沙箱预览在浏览器及直连探针中超时，关闭后改用宿主本地预览并成功访问。

## 资源与回执

预览服务、测试页面已关闭，服务自身的关闭回执与系统监听表、进程表分别核对。关闭后的直连探针返回10035，系统快照确认本轮三个预览端口无监听、三个服务PID均缺席。三轮隔离PG集群的 `pg_ctl status` 均为3，验收端口无监听，见同目录 `postgres-closure.json`。

| 本机回执 | 范围 |
| --- | --- |
| `.artifacts/pdfdate-green/` | 156项受管回归、源码绑定、资源及拒绝统计 |
| `.artifacts/pdf-publication-20261113/frontend.json` | 三端类型及Web测试 |
| 同目录 `browser-final-1440.json`、`browser-final-390.json`、`browser-final-320.json` | 三种宽度的30项实际组件检查 |
| 同目录 `browser-pins.json`、`browser-server-closed.json` | 当前组件依赖与预览请求、关闭回执 |
| 同目录 `browser-320-final.png` | 已查看的320像素截图，59256字节，SHA256为 `6b7e0bf7cbbe4623d3bb58ad9551cd34cc7ade50afdd7ae7e226e0218a490a08` |
| 同目录 `closure-system.json` | 宿主系统监听表及进程表核对 |
| 同目录 `postgres-run.json`、`postgres-date-checks.json`、`postgres-closure.json` | 最终PG运行、日期专项与三轮集群关闭 |

原始材料、数据库、运行时和回执保留在Git忽略目录。接手者可从提交的计划及测试重新建立隔离验收环境。

交付复核68项及30个本地文档链接全部通过，包含当前源码绑定、API与PG结果、组件依赖、截图哈希、系统关闭状态、原失败记录、文档路径与凭据检查，以及历史交接尾文字节核对。入口为同目录 `validate_delivery.py`，结果为 `delivery-validation.json`。

## 待完成

原报道与论文转述的人工测试记录均使用 `manual_test` 来源类别，宽查询的来源优先关系继续待核对。需要建立有证据的来源角色，并扩大独立标注及代表性材料。真实Responses及Embeddings语义、精确SKU、真人Golden、生产权限、六类平台、完整WCAG与发布Gate继续验收。
