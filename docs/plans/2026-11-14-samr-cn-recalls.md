# 中国市场监管召回来源实施计划

## 目标与入口

接通原规格 P0 Safety 的中国市场监管召回来源，使用缺陷产品召回技术中心官方公开页面及页面声明的只读列表请求。沿现有 `main` 实施，复用 `SafeHttpClient`、robots、隔离 Parser、采集回执、来源治理、查询归属和显式回退授权。

本阶段交付在线检索、公告正文、不可变证据、历史读取、正常 API、共享类型、SDK 与 Web。后续继续自然监控、精确 SKU 绑定、AI 消费及生产验收。完整 V1 依据原规格逐项推进。[原始需求](../requirements/2026-09-26-tire-intelligence-original.md)

## 已观察的来源事实

- 官方栏目位于 `/zhxx/jdczh/jdczh/index.html`。旧公告路径现场返回 200 首页，解析需核对文章身份与正文区域。[官方栏目](https://www.samrdprc.org.cn/zhxx/jdczh/jdczh/index.html)
- 页面公开声明的列表请求位于 `/api-gateway/jpaas-publish-server/front/page/build/unit`。默认 HTML Accept 的两次对照均为 500，JSON Accept 与通配 Accept 均为 200。生产客户端的 JSON 请求显式提供 `Accept: application/json`。
- 正式安全 HTTP 客户端已读取默认列表、轮胎搜索第 1 至 4 页及两份公告，七次响应均为 200。默认列表声明 2325 条，轮胎搜索声明 47 条，每页 15 条。原站导航最多展示 60 页，结果需同时保留声明总数、本页范围和导航限制。
- 固铂与德安通公告原生路径年份均为 2021。页面 `DeployTime` 与显示发布日期为 2021 年，`PubDate` 为 2026 年。各字段单独保留。日期差异原因仍待来源说明。
- 本次 robots 为 404，依现有缺失规则处理。页面访问、内部证据保存、开放再分发及模型外发的许可依据分别核对，开放许可当前待核验。

## 设计与不变量

来源标识采用 `samr-cn-recalls`。检索请求使用关键字和页码，公告请求使用经过固定路径校验的原生文章引用。只接受官方 HTTPS 主机、栏目路径及已观察的类型参数。列表 JSON 的公开配置标识依据现场页面固定，响应中的文章链接逐项验证。

Parser 从 JSON 的 `data.html` 提取本页列表、分页声明及显示日期，从公告元数据与 `div#zoom` 提取原生 ID、标题、正文、原发布日期、PubDate 和来源声明。正文链接与图片只记录受校验的地址，附件及图片获取另行实施。原文与提取文本各自绑定哈希。公告整体适用性为 `not_assessed`，批次与日期条件保留原文。

扩展可信 Parser 完整目录至 18 项，并保留旧 17 项及更早封存包的执行兼容。查询字段、子进程分派、输出类型和源码摘要一并更新。先写合成反例，真实原件留在 Git 忽略目录。

新增独立快照与核验表。迁移使用既有拥有者入口和事务锁，PostgreSQL 运行角色依据当前模型补齐。API 变更后重建并审查匹配源码的批准空参考 `@4` 合同。原库兼容与非拥有者权限验收分别留证。

## 实施顺序

1. 实现 `adapters/samr.py`，覆盖严格查询、列表与公告解析、robots、限频、条件请求、预解析回执与失败证据。注册完整 Parser，补目录与历史包测试。
2. 实现 `samr_recalls.py`，登记模型和路由，接通正常在线查询、来源暂停、Parser 选择、失败授权与显式历史读取。扩展回退策略的来源类型绑定。
3. 运行正式受管回归，使用真实官方响应执行隔离 Parser 和正常 API 验证。检查原始日期、文章身份、分页、原文哈希、重复读取与失败状态。
4. 更新进度与交接，审查差异、凭据和本机路径，提交并通过直连推送，核对远端 SHA。
5. 继续 SDK、Web、后台监控、AI 引用、批次适用性和实际部署验收。

## 验证入口

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/<fresh-slot> --targets apps/api/tests/test_samr.py apps/api/tests/test_samr_recalls.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_adapter_import_behavior.py apps/api/tests/test_source_settings.py
git diff --check
```

验证记录保留原始失败、实际源码摘要和资源回收结果。来源研究原件位于 Git 忽略的 `.artifacts/samr-source-20261114/`。当前生产服务、真实模型、精确 SKU、自然监控及多平台消费验收继续逐项跟进。

## 本阶段结果

后续专用 DTO、SDK 和 Web 查询页面已接通。正常浏览器 31 项、SDK 8 项、既有 SDK 3 项、Web 59 项、三端及 native-client 类型检查与生产构建通过。浏览器经正常 HTTP 链路取得 6 次真实官方 live 结果，持续回退、来源代次、卸载及拒绝终态均有独立检查。后台监控与逐公告变化继续按后续顺序实施。[SDK 与工作台验收](../assurance/evidence/samr-cn-web-2026-11-14.md)

步骤 1 至 3 的后端链路已交付，最终 108 项受管回归、独立 HTTP/非拥有者 PG/TLS 专项 12 项、正常 ASGI 真实来源 27 项及三端类型检查通过。旧 17 项真实封存包执行通过。扩展批的子进程路径误判已定位并修正，原始失败和间歇 Parser 超时分别保留。四批临时集群的进程、端口和临时密码／私钥文件已核对。SDK、专用页面、后台监控、AI 消费和完整 V1 继续实施。[阶段验收](../assurance/evidence/samr-cn-source-2026-11-14.md)
