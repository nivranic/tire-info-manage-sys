# 中国市场监管召回来源阶段验收

## 范围

本阶段接通 `samr-cn-recalls` 的官方公开检索页和公告正文，新增正常查询、不可变快照、核验、显式历史及回退授权。来源覆盖官方汽车召回栏目，轮胎关键字结果包含相关汽车公告。具体 SKU 与实物召回适用性继续核验。[实施计划](../../plans/2026-11-14-samr-cn-recalls.md)

## 来源事实与设计选择

1. 官方栏目页面声明列表 GET 地址及公开配置标识。正式客户端使用 JSON Accept，沿既有公网 DNS 验证、TLS、重定向校验、响应体上限及 robots 规则。JSON Accept 和通配 Accept 的对照为 200，默认 HTML Accept 两次为 500。首次脚本的 URL 比较失败来自 aiohttp 的规范化表现，正式查询 URL 采用同一规范化形式。
2. 默认列表现场声明 2325 条，轮胎关键字检索声明 47 条。研究阶段读取四页，记录数依次为 15、15、15、2。Parser 保留声明总数和原站最多 60 页导航限制。页码合同采用原站展示范围，此项为本阶段实现选择。
3. 已取得固铂、德安通两份官方公告。原生文章 ID 与栏目路径绑定，页面标题、域名、站点 ID、栏目 ID、`Url`、`server` 和正文区域一并核对。旧链接返回首页时进入失败状态。
4. 两份历史公告的显示发布日期和 `DeployTime` 为 2021 年，`PubDate` 为 2026 年。输出分别保存 `published_date`、`publication_date_raw`、`deployed_at_raw`、`pub_date_raw` 及完整所选元数据，日期差异原因待来源说明。
5. 公告原文中的批次、缺陷和措施保留文本。图片及附件记录原始引用、受校验地址及 `not_fetched` 状态。适用性为 `not_assessed`。开放再分发许可待核验，AI 模型外发沿单独授权流程。

官方材料入口如下。

- [召回栏目](https://www.samrdprc.org.cn/zhxx/jdczh/jdczh/index.html)
- [固铂轮胎公告](https://www.samrdprc.org.cn/zhxx/jdczh/jdczh/art/2021/art_67891d6e00464b6ebe96cad1ba9c35e2.html)
- [德安通轮胎公告](https://www.samrdprc.org.cn/zhxx/jdczh/jdczh/art/2021/art_45e1ea99e96f40bc8c1838bafa199b4a.html)

## 工程入口

| 范围 | 本次落点 |
| --- | --- |
| 来源与 Parser | `adapters/samr.py`、`parser_runtime.py`、`parser_child.py`、`parser_bundles.py` |
| 正常查询 | `POST /v1/samr-recalls/query` |
| 显式历史 | `GET /v1/samr-recalls/history`，必需 `mode=history` |
| 历史原文 | `GET /v1/samr-recalls/evidence/{snapshot_id}`，必需 `mode=history` |
| 快照与核验 | `samr_recall_snapshots`、`samr_recall_verifications`，复用拥有者迁移和来源采集事务锁 |
| 来源治理 | 登记目录、启停代次、采集回执、查询归属、Parser 固定选择及执行记录 |
| 回退 | `samr_recall_search`、`samr_recall_notice` 各自绑定来源和会话，复用持续策略及单次同意 |
| PostgreSQL | 模型表扩展为 168 张，新增两表的运行权限为 SELECT/INSERT，逐列更新及删除仍按既有运行角色合同 |
| 客户端 | 共享回退类型和既有策略组件的查询类型、来源匹配已补齐，中国召回专用 SDK 与页面继续实施 |

检索请求形态如下。

```json
{"query":{"operation":"search","keyword":"轮胎","page":"1"},"fallback_policy":"never"}
```

公告请求使用检索返回的原生 `reference`，操作为 `notice`。保留来源原生文章 ID 和中国地区语义。

监管查询沿既有合同将成功 `QueryRun.state` 记为 `live`。304 在响应 `data_state`、核验行和 `ParserExecution.state=not_modified` 中体现，此时执行回执为空。原快照观察时间保持原值，新的核验单独追加。

## 已观察验证

| 验证 | 结果 |
| --- | --- |
| 研究直读 | 安全客户端七次 200，覆盖默认列表、轮胎四页及两份正文 |
| 正常 ASGI 与真实来源 | 最终 27 项通过，四次 live、一次 live_verified_304，原件哈希与日期核对通过 |
| ASGI 证据数量 | 4 份快照、5 次核验、4 份原始采集回执、5 条 Parser 执行状态 |
| 历史真实 17 项包 | 当前宿主执行此前 Dunlop 阶段封存包通过，两个 Material Code 保持独立，子进程已回收 |
| 三端类型检查 | Web、Desktop、Mobile 的完整 TypeScript 检查均通过 |
| 静态与交付检查 | 30 个变更 Python 文件语法、14 个新增相对链接、差异空白及新增内容隐私扫描通过，原始需求保持原值 |
| 扩展受管回归 | 18 模块 464 项执行，463 通过、1 失败，851 项输入稳定、资源关闭、非自检拒绝 0 |
| 最终受管回归 | 修正子进程路径比较后，5 模块 108/108 通过，跳过与不完整均为 0，851 项输入稳定、资源关闭、非自检拒绝 0 |
| 独立 HTTP / PG / TLS | 最终 12 项通过，四次 live、一次 live_verified_304，168 张模型表、原生身份、日期、历史哈希和追加权限通过 |

### 原始失败保留

- 首批受管回归 89 项中 80 项通过、9 项失败。原件写入诊断观察到 `FileNotFoundError`，errno 2、WinError 3。来源采集分类与测试会话初始化随后补齐。
- 第二批在普通宿主权限使用正式受管入口，88/89 通过。剩余失败为私有测试将既有来源设置创建的 201 断言为 200，已依据路由合同修正。
- 首批 ASGI 五次真实查询成功，最后的私有脚本断言错误地要求 304 具有子进程回执。保留原失败报告，最终批次按现行合同取得 27 项通过。
- 首批独立 PG 前 11 项通过，中国召回四次 live 和一次 304 已观察。最后的私有脚本使用了轮胎专属成功任务状态断言，已依据监管查询合同修正并复验。
- 直接在沙箱核验历史包时，宿主 `platform.machine()` 返回空值而产生 `parser_bundle_environment_incompatible`。普通宿主权限取得 `amd64`，原环境校验及封存包执行通过。
- 扩展批唯一失败为服务崩溃回执用例，随后单独纳入第四批仍失败。直接运行同一合成用例退出码为 73，原子进程边界下退出码为 1。原始拒绝栈定位到 Parser 封存目录的 `os.mkdir`，目标为私有目录的 `\\?\` 等价路径。修正子进程护栏后，最终 108 项通过，包含真实退出回执、等价路径、工作区外路径及设备路径反例。
- 核验嵌套 JSON 时复现解码后的 HTML 可包含控制字符。已在 HTML 入口核对 UTF-8 及控制字符，并增加 NUL、其他控制字符和孤立 surrogate 反例，纳入最终回归。
- 第三批 PG 的两页检索为 live，随后一份公告出现 `parser_timeout`。该批资源完整关闭，现有 8 秒 Parser 限制继续使用，间歇超时原因仍待取证。

## 同机回执

原件和执行产物位于 Git 忽略的 `.artifacts/samr-source-20261114/` 与对应临时 PostgreSQL 验证槽。源码、合成、真实来源、本机数据库和生产验收分别使用相应回执。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/samr-source-20261114/regression-r3/result.json` | `30de262e246ad99fbec8094bddc175956adbd277a51a9c4cba58abff1a9a32f1` |
| `.artifacts/samr-source-20261114/regression-r5/result.json` | `b078282f0d8f6f506a47a411ee71c1ce1bd0f2577f6f679c733ac863d95e1879` |
| `.artifacts/samr-source-20261114/api-live-de1437d7e743485d8f8a02131da53b05/report.json` | `32925f3aa0f477c7019190af4af481038c92ffeea9179171aa811e25eed00d2a` |
| `.artifacts/samr-source-20261114/actual-archive-r1.json` | `7496facb62db970b9372511691e7d8281284d375d912fb85de95efff9921b7d4` |
| `.artifacts/postgres/pgverify-5ce77c2cbe194f85a99927bf1893886a/report.json` | `a8d335bea573d300cb1da9689918fcd67b9526e5fb12fbd454266293f769e9c4` |
| `.artifacts/samr-source-20261114/close-assertions.json` | `be7582ff054ed2e9969c7919dde40446696f0efbf3a14c467f200ad55d6b8751` |

最终 API 包源码 SHA-256 为 `59d1834b6433b46c03278dc64b5aa2bc2df34d1f04f163bcb5363db2b2474b08`，部署使用与实际源码及环境匹配的批准空参考 `@4` 合同。

最终本机合同 SHA-256 为 `22d3fed526078237f302deaa585f90237a2d0119dbdbf4053f69b7306055c694`。四批临时 PG 共 48 个服务记录、58 个进程 ID、28 个端口完成关闭核对，临时密码文件、私钥、postmaster PID 文件及 Parser 临时目录均已检查。来源研究 Chrome 的本次私有 profile 对应进程已独立核对为空。

## 继续验收

中国召回专用共享类型、SDK、Web 界面、后台监控、历史变更通知、精确 SKU 与批次绑定、AI 引用、开放再分发许可、生产部署及长期 SLO 继续实施。真实 OpenAI Responses 与 Embeddings 依凭据和独立语义验收推进。完整 V1 的 12 模块、10 Gate、13 SLO 和 15 决策沿总交接表逐项跟踪。
