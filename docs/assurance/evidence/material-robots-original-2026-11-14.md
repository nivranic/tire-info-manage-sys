# 许可 PDF 捕获与 robots 跳转验收

更新于2026-11-14，工程基线为 `5a56421`。本阶段完成精确声明的robots HTTPS跳转、冻结凭证与Web消费，并取得首份可恢复的专业研究PDF。[实施计划](../../plans/2026-11-14-material-robots-redirects.md)

## 实现

- 本地策略增加可选 `robots_redirect_urls`，最多3个精确公共HTTPS地址。空清单序列化时省略，旧策略和请求指纹兼容。
- robots逐跳验证声明地址、公网解析、TLS、循环、唯一Location及3跳上限，记录终点与完整链。200解析规则，404／410记录规则缺失，拒绝规则继续生效。既有无声明的3xx失败语义继续可读。
- 实际发生robots跳转时保存 `source-material-receipt@2`。保存后的重开、原UUID重放、PDF正文与引用入口均核对冻结策略、跳转链和原件摘要，既有@1回归通过。
- 共享类型及正常Web入口消费两种凭证，展示声明地址、实际终点与逐跳记录。下载完整计算SHA-256和字节数，未知跳转及版本降级在页面中被拒绝。
- 独立材料捕获总期限根据真实吞吐从20秒调整为45秒。连接4秒、读取8秒、8MiB上限、并发2和host节流继续执行。期限取消、会话关闭及容量释放经过回归。

## 真实原件

《Ultra Low Noise Poroelastic Road Surfaces》，Jerzy A. Ejsmont、Luc Goubert、Grzegorz Ronowski与Beata Świeczko-Żurek，Coatings 2016, 6(2), 18，DOI `10.3390/coatings6020018`，出版日期2016-04-08。第1页题名／作者／DOI与第15页CC BY 4.0声明已经文字层核对，第4页表格及第15页许可已渲染目视核对。作者机构为Technical University of Gdansk与Belgian Road Research Centre。[出版页](https://www.mdpi.com/2079-6412/6/2/18)

实际下载来自学术仓储副本。正常捕获接口返回201／succeeded，15页、6,136,722字节，完整SHA-256为 `00e7c08c6fe2dddee4444f22db86fcacb7b726b7aa69073f02291aac75a64be4`。robots从仓储 `/robots.txt` 经301到明确声明的 `https://www.semanticscholar.org/404`，实际终点为404。原件、正文引用和浏览器完整下载摘要一致。[实际仓储PDF](https://pdfs.semanticscholar.org/8c68/272f15924acd69b047bed8c7a837ce440182.pdf)

原件document ID为 `fc93cf95-89fd-409e-aff6-9b02668be495`，捕获请求ID为 `3cb68711-6035-4096-8fbc-30e818284932`。原件及各验收副本保存于Git忽略目录，成功原件按同一出版物计为1份。出版物署名、出处、DOI及许可信息随核验记录保存。[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

### 内容与身份

- 第4页表2有22行参测对象说明。`T1064/68`、`T1075/76`保留复合研究编号，Michelin PRIMACY HP等型号按原表记录，精确SKU／批次及外部真人审核继续待验。
- 原表Wanli尺寸为 `196/60R15`，卡车两行分别写Michelin M758与Bridgestone M758。第5页载荷写作 `2,4800 N`，第4页道路滚阻方法为4000 N，第11页结果条件为4002 N。上述原值与各自页码分别保留。
- 第4页噪声段落记录3200 N、capped 200 kPa。道路滚阻段落记录regulated 210 kPa，第5页乘用车实验室滚阻采用载重指数最大载荷80%及capped 210 kPa。方法、路面／鼓面和场次按各段声明分别处理。
- PDF部分页面文字层含重复段落，原件和页内码点引用保持原始抽取结果。检索权重、去重质量和测量值人工转录继续验收。
- 当前许可策略开放原件保存、工作区重开及标识短引文。Provider使用与报告导出用途在该策略中为false，相关用途审批、真实模型语义和人工Golden继续待验。

## 验证

| 范围 | 结果 |
| --- | --- |
| 最终正式受管回归 | 400／400通过，0跳过，865输入稳定，资源关闭 |
| 前一批正式受管回归 | 321／321通过，865输入稳定，资源关闭 |
| SDK | 来源材料合同16项通过，既有全SDK入口通过 |
| Web／类型／构建 | Web66项、全工作区类型检查、生产构建通过 |
| 真实PDF正常API | 10项通过，含原UUID重放、重开、15页索引、FTS、引用重新抽取和错误摘要拒绝 |
| 非拥有者PG／TLS | 5项通过，独立HTTP进程、实际Parser索引／引用、重启幂等及3条越权SQL拒绝 |
| 生产浏览器 | 两批各13项通过，实际原件副本、许可预览、PDF页码、完整文件下载及篡改拒绝 |
| 视口 | 1440／390／320均无横向溢出，最终390截图已查看 |

PG专项采用已捕获真实原件和真实传输回执的明确录制重放，记录1次夹具调用、0次实时下载。实际网络捕获发生在独立SQLite材料工作区。浏览器使用正常生产Next页面与HTTP API，对该材料库的独立副本进行验收。

## 原始失败

1. r1出版站robots返回403，r2出版方CDN的robots返回301且Location为HTTP地址，r3学术仓储robots返回301。后续仅为已核对的固定HTTPS跳转增加声明支持。
2. r4、r6、r7在20秒内超时，r6及r7分块记录分别收到6,069,978和2,768,154字节。调整45秒后r8仍超时，收到2,942,223字节。r9最终收到全部6,136,722字节，成功保存，正文读取约20.8秒，网络吞吐仍有波动。
3. r5私有观测钩子尝试替换只读的 `StreamReader.iter_chunked`，独立探针复现AttributeError。其原请求保持未确认，原进程退出后通过正式stop接口写入 `stopped_unconfirmed`，阻止迟到采纳。纠正的观测器通过只读代理转交原始字节。
4. 受管r1为256通过／65失败。沙箱独立硬链接探针复现PermissionError／WinError5。宿主同一入口r2为321／321通过，原始失败及探针保留。
5. 首批浏览器全部13项通过，但390截图滚动定位落在来源管理区。第二批补充布局稳定等待后重拍，13项和下载摘要再次通过，最终390截图可核对真实原件凭证。

## 部署合同与私有证据

API源码指纹为 `a30c4a710a4c7977c664e4d1b7cf4e8dc65fc6907d78f1b977560f1ea3adccf8`。本次空参考@4合同为 `50a00c964f79cf61ec80eb4f67f8b95cb4a14e7f4b2c7e7eefe323aadb84f5fe`，180个relation、179张模型表。与上阶段合同逐项比较，仅 `source_sha256` 发生变化，catalog及向量索引声明一致。非拥有者只读verify通过，实际部署按目标环境重新审查批准合同。[合同流程](../../POSTGRES-RUNTIME-SCHEMA.md)

捕获r1—r9位于 `.artifacts/material-coatings2016-20261114-r*/`，最终原件、页图、文字层与API核验保存在r9。正式回归位于 `.artifacts/material-robots-20261114-tests-r*/`，PG及浏览器运行脚本、下载副本和资源审计位于 `.artifacts/material-robots-20261114/`。本次PG集群为 `.artifacts/postgres/pgverify-24763f75a67a40478246786af001a988/`。以上文件均采用Git忽略规则保存。

本轮宿主资源核对12个进程ID与7个端口均已关闭，临时口令、TLS私钥和postmaster文件均已移除，相关进程命令行匹配为空。沙箱监听表与CIM探针返回拒绝访问，已保留失败回执并在宿主重做核对。正式受管入口另记录独立的子进程、SQLite及socket关闭。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/material-robots-20261114-tests-r1/result.json` | `13aba74c84e97cfbe741552dd3b77df2d765c23e5f7017c13e89cfc1cfab90cc` |
| `.artifacts/material-robots-20261114-tests-r2/result.json` | `b8f73fe75989f2f6628245eb6f8cc4ce0055730cb2e741ef1bc088b25a6f11f3` |
| `.artifacts/material-robots-20261114-tests-r3/result.json` | `6d61deccc0c5bcda025f39ba613acd8afe7d44d52e88384b45160c00b3f93cd1` |
| `.artifacts/material-coatings2016-20261114-r9/result.json` | `2970a12fd776f871cf3d58cd6dc7d4e15b21614aa1d4b3261c5b865a28a7c1bc` |
| `.artifacts/material-coatings2016-20261114-r9/text-api-review.json` | `a59bf6a757fbbc3232589eec3c32d9d75282ab7b7203b86dcaa0f7752d249637` |
| `.artifacts/material-coatings2016-20261114-r5/stopped.json` | `765143101299ca85ac7dcd6233e71d946026f9ac73f2fb46c9be2bc73c1ae139` |
| `.artifacts/material-robots-20261114/web/run-88b3c4e3-0370-48d0-89bb-790c18a67e91/report.json` | `a6bb8385eb4f1ffa52756def7207622649914666565976c6c317b0bee28263a0` |
| `.artifacts/postgres/pgverify-24763f75a67a40478246786af001a988/report.json` | `d21ec3681edd594cfa3ebc1b44d1524701952ffd7f5b1091a11d3ab56e592746` |
| `.artifacts/material-robots-20261114/resource-audit.json` | `d58ba8a0cb62d6ffaff00f1cc53b5f2395c15151f8fedf455632453490bee3cd` |

旧KIT C2封存请求继续保留原状态，完整V1的外部真人审核、精确SKU、真实Provider及其余发布Gate继续执行。
