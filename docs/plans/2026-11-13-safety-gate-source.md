# EU Safety Gate 官方安全来源接入计划

## 目标与设计

沿既有main接通原规格P0 Safety来源，支持官方英文周报索引与指定周报的在线核验、原始证据、隔离Parser、明确历史读取和单次授权回退。使用brainstorming、writing-plans及executing-plans流程。完整V1继续按原始规格推进。

官方索引给出周报原生ID、reference、日期和详情URL。查询分别表达reports与report，指定周报绑定report_id及reference。周号按官方原值校验，日期按原文解析。当前2026年第19号周报发布日期为2026-05-15，该日期ISO周号为20，系统保留原生19。

告警使用官方详情URL中的alert_id及原始caseNumber。英文文本、生产日期、批号、型号及条码保留原值，空值保持未知，applicability为not_assessed。先校验整份响应再展示与筛选，单份周报的查询覆盖绑定周报身份。索引与周报分别保留独立快照及核验记录。

## 官方材料与许可

已取得1124项周报索引、2026年第45号75条告警及第19号35条告警。后者含Goodyear商用翻新轮胎告警SR/01396/26，官方发布日为2026-05-12，完整序列号和措施原文进入证据。

官方数据集JSON-LD将XML分发d932935c-3916-4421-a6a4-91efe196ef4b列为CC0，将周报网页分发1c42bf60-98c1-4728-b8da-e3f152783068列为COM_REUSE。当前接入使用XML分发，保存来源和许可元信息出处，页面保留署名。图片仅保留来源URL。当前免责声明PDF返回403，旧webgate地址重定向至官方sorry页面，原始失败保留。后续完整商业和再分发范围继续核对具体合同。[官方元信息](https://data.europa.eu/api/hub/repo/datasets/rapex-rapid-alert-system-non-food.jsonld)

## 实施步骤

1. 新增`apps/api/tests/test_safety_gate.py`，覆盖索引完整性、官方周号、完整告警、空值、重复身份、XML实体与结构变化、查询URL和隔离Parser。
2. 新增`apps/api/tire_api/adapters/safety_gate.py`，使用现有SafeHttpClient、RobotsPolicy和可信Parser发布链。固定官方主机与路径，保留限速、超时、熔断及304验证。
3. 扩展`parser_runtime.py`、`parser_child.py`、`parser_bundles.py`及`captures.py`，登记来源并保持历史可信包目录有效。XML捕获约束到新来源及其精确查询URL。
4. 新增`apps/api/tire_api/safety_gate.py`，通过正常应用路由保存不可变快照和核验，复用QueryRun、来源管理、摄取锁、审计及FallbackConsent。在线失败时等待显式单次授权，明确history入口按所选周报读取。
5. 在共享SDK、类型与现有安全公告工作区接入查询、覆盖说明、原件及历史状态。来源变更、窗口关闭及会话失效时丢弃迟到响应。
6. 运行相关受管回归、三端类型与Web构建，以隔离数据库执行真实官网→API→正常Web验收，再关闭自有资源。
7. 更新验收与交接卡，检查源码绑定、历史文档与隐私，审查正式提交后推送并独立核对远端。

## 验收与后续范围

回归必须覆盖原NHTSA正常入口及历史可信包。真实API需核对两份周报、轮胎告警、未知适用性、原文哈希、重复核验、失败前零历史采纳及一次性授权。页面核对索引选择、原值、证据恢复及1440／390／320视口。

本阶段建立周报证据查询。按告警的跨周修订、长周期监控、持久回退策略、Native消费和安全告警AI继续沿完整V1实施，分别建立验收证据。生产部署、完整许可治理和发布Gate按原规格继续验收。
