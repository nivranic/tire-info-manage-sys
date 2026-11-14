# 横滨欧洲规格来源验收

日期为2026-11-14，实施基线为 `0e67752410c01f9c7e60721790c13b50b1e1f89b`。本阶段补充原规格P0来源Yokohama，采用固定欧洲ADVAN Sport V107页面，复用既有在线优先、条件核验、原件捕获、Parser封存和字段证据链。[实施方案](../../plans/2026-11-14-yokohama-eu.md)

## 来源与字段

直连欧洲robots及规格页均取得200，目标路径允许抓取。原页1,056,050字节，桌面6张规格表共114条记录，其中3条具有显式HL前缀。114条记录的EPREL链接各自唯一。页面正文SHA-256为 `08c163d5d8917a583ba7cd54a9b6278b7d1be59688664f970c79a988e216ff25`。[官方规格页](https://www.yokohama.eu/tyres/advan-sport-v107/)、[robots](https://www.yokohama.eu/robots.txt)

解析保留R／ZR、载重、Y／(Y)、显式HL和逐字段表／行／列定位。厂商原文XL/RF、OE Info、雪地及冰地标记分别保存，独立xl、run_flat及oe_mark为null。厂商产品代码未知，身份采用既有source_scoped合同。EPREL ID与链接来自厂商页面，EU标签字段按manufacturer_official权威处理，监管读取与绑定继续待验。

本轮另外核验了加拿大、美国和日本入口。加拿大页200，条款要求内容复制事先取得书面同意。美国robots404、产品页200，当前规格主要以图片呈现。日本robots地址200返回公司首页HTML。欧洲条款入口为销售合同GTC，开放再分发许可继续待核对，外部事实消费沿既有许可治理流程执行。[欧洲条款](https://www.yokohama.eu/terms-conditions/)

## 代码与兼容

- `adapters/yokohama.py` 固定canonical、title、表头文本与图标列语义，逐行核对尺寸、服务描述、噪声单位与EPREL链接，整页通过后才执行查询筛选。
- 新来源接入registry、Parser目录及可信子进程。当前12个轮胎区域目录、8个厂商品牌，Parser目录16项，来源管理目录16项。
- 完整封存包合同增加16项目录，既有8到15项完整目录继续有独立兼容检查。新来源包必须包含对应解析器文件。
- 查询层复用telemetry现有固定来源校验，覆盖横滨及此前遗漏的品牌归属。未知来源继续按已有unknown值处理，任意URL和内容不进入遥测。

## 实际入口结果

| 入口 | 已观察结果 |
| --- | --- |
| 正式在线canary | `--source yokohama-eu --model "ADVAN Sport V107" --size 225/40R18 --revalidate`，首次及重复读取均ok，1条匹配，隔离Parser退出0并回收 |
| 正常ASGI HTTP | 新隔离SQLite、原API注册与live-query入口，live后取得live_verified_304，1份快照、1个版本、2次核验，证据重开和原始哈希核对通过 |
| 实际HTTP进程 | 新隔离PG18／TLS、非拥有者运行账户、批准@4合同和实际uvicorn，正常来源管理与live-query入口取得live及live_verified_304 |
| 版本与原件 | 两次PG查询保持同一variant ID、snapshot ID、原始观察时间及Parser部署修订1，历史证据重开及完整正文哈希核对通过 |
| Parser执行 | PG首次查询的真实Windows Job回执完成、reaped=true、exit_code=0、stderr为空，304完成记录为not_modified |
| PG基础检查 | 12项全部通过，166张模型表、1份已有原件及198个Parser资产文件独立恢复核对通过 |

PG基础进程部分使用既有Hankook录制模式，租约到期沿既有隔离夹具装配。最后一项扩展使用真实横滨HTTPS及实际PG业务。当前真实模型、Native设备和公网部署继续待验。

## 回归与原始失败

14个相关模块共328项分批收尾，323项通过，5项可选真实来源夹具回放跳过。本轮受管输入共845项。完整批次为322通过、1失败、5跳过，唯一剩余失败为回归子进程护栏未登记新增横滨导入参数。补入既有模板的固定参数后，导入边界与横滨模块专项34项全部通过，非自检拒绝0，资源关闭。

两批公共输入差异仅为 `scripts/regression_children.py`。实际PG批次与最终API源码摘要一致，统一断言另行核对该绑定，原失败保留。

首批在源码固定摘要检查处拒绝启动，随后按已审查的Parser子进程、运行时及测试内容更新已有摘要。第二批144／145通过，来源管理测试仍固定断言11项。第三批233项中220通过、8失败、5跳过，失败涉及新遥测测试使用空查询，以及旧导入测试固定8个规格来源／10个公开来源。已用明确的现行目录及有效合成查询修正夹具，旧回执保留。

首次私有HTTP验收将合法live_verified_304限制为live而失败。生产返回已保留，修正私有验收后13项通过。正常查询入口另观察到来源归属为unknown，已复用已有telemetry固定校验并增加回归，实际API新批次验证归属为yokohama-eu。

五项可选已保存真实来源夹具的回放保留跳过状态。真实来源由上述显式canary、ASGI与独立PG／HTTP批次验收。

## 收尾与回执

12个受管服务记录及15个进程ID已核对，7个端口可重新绑定，PG停止，postmaster.pid、初始化口令、TLS私钥及Parser临时目录已清除。句柄核验途中观察到PID重用，后续系统活动进程快照中本轮15个ID均已消失，原退出回执和快照分别留存。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/postgres/pgverify-1a9418bd475c45a5b58f40ea5ef82031/report.json` | `47b7bc1cfc06b8e08c708bd2df51d319e77d5be8ecb997cc9cab08295c2592c9` |
| `.artifacts/yokohama-source-20261114/http-r2/report.json` | `71005f9bbe871e5393f77458fbc92453c287913bd91b3310238a997b0c7da3d9` |
| `regression-r4/result.json` | `1a9d499e192339e12240124e2f4981c0413bfdff1a0570cfdbf2cdf2e3f06dfe` |
| `regression-r5/result.json` | `f42c4fe4ed475edda2ef2a72d204831c1df964326894236a37ffdf6d6dfa19b2` |
| `assertions.json` | `299b1c1870ef774ffc1822ccd6f701fb2dea0dd8c1825c142c6f763b53e47086` |

表中短路径相对于 `.artifacts/yokohama-source-20261114/`。私有 `assertions.py` 绑定回归输入差异、真实查询、原件哈希、API源码合同与资源关闭。新clone需要依照正式来源canary、正常HTTP入口及隔离PG wrapper重新建立验收。

## 部署与接续

新API源码SHA-256为 `b14a29364b6b86fb29170d7ffa2245f4ee49b0d2d4f586bfc795835a490b8de3`。本批空参考@4合同SHA-256为 `ac5f25e56f7a12af4e4c09cefa4dc37b5edc38c3042c9448c8b464ff8c8bca1a`。部署依照既有空参考生成、审查与批准流程建立匹配合同。

长期站点稳定性、源字段语义补充、精确SKU独立绑定、人工Golden、开放再分发许可、其他P0来源、生产性能、真实OpenAI Responses／Embeddings及平台Gate继续推进。
