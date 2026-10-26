# 第74轮：首个真实公开专业轮胎实验材料捕获

**首个公开许可专业材料已通过真实HTTPS及生产采集逻辑保存，在GUID私库完成20项API检查；这不是精确SKU Golden、性能推荐或完整V1验收。** 用户已授权agent自行决定选源，无需继续等待用户提供URL。本轮没有修改产品源码、正常来源配置或正常数据库。

## 材料与许可

论文为Wilkinson等（2023）的 *Shades of grey—tire characteristics and road surface influence tire and road wear particle (TRWP) abundance and physicochemical properties*，Frontiers in Environmental Science，Volume11，1258922，出版日2023-11-07，DOI `10.3389/fenvs.2023.1258922`。[官方引用页](https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2023.1258922/full)和[固定PDF](https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2023.1258922/pdf)在本轮策略中分别记录，未经过跳转。

官方单篇声明版权归作者，并以[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)开放；保留作者、题名、期刊、DOI及许可，转录另标改动，不暗示机构背书。[独立原件复核](../../../.artifacts/r74-pdf-review-8ef032fe57a44573b3c1f5e7cb771ad5/REPORT.md)确认15页PDF可读、未加密，首页版权及实际超链接指向CC BY4.0；目视第1/2/3/4/9/13页，覆盖版权、图1、表1–3与出版者声明。Figure1照片署名Mats Gustafsson/VTI及前文出处应保留；所读原件文面未见明确许可排除，不扩展为外部补充材料、引用论文或标志的整体许可。

策略仅支持保存原件、工作区重开和带署名的短标识引用，`provider_use:false/export:false`仍固定。政策文件仅由本轮进程加载；正常工作台默认专业来源目录仍空，没有隐式配置正常采集或把材料送模型。

## 实际捕获与验证

执行合同为[隔离PLAN](../../../.artifacts/r74-live-c726bf6f944a4e6fb094e7ec79188e23/PLAN.md)。此前baseline实际逐SHA核R73的940源码、26文档、136证据及4配置、348展开dirty一致；R73及以下历史回执保持不变。

- [原件](../../../.artifacts/r74-live-c726bf6f944a4e6fb094e7ec79188e23/review-original.pdf)：3,302,848B，SHA256 `33471a0b0d0a8c2f172b61b034a8300c65e3ff2372c79782562048133606f635`。保存HTTP transfer decoding后的identity实体，不声称TLS包/HTTP头帧原样归档。
- [冻结来源记录](../../../.artifacts/r74-live-c726bf6f944a4e6fb094e7ec79188e23/capture-response.json)：document ID `55bc1948-fa4f-4312-9635-de46a6eaa130`；生产transport实际公网DNS/TLS、robots200/862B/允许/2秒间隔、PDF200、无Content-Encoding、无跳转。传输起止2026-10-18T11:11:41.077272Z至11:11:50.016476Z。
- [实际执行回执](../../../.artifacts/r74-live-c726bf6f944a4e6fb094e7ec79188e23/verification.json)：20项检查全部通过，943项阶段输入首尾一致（940份工作区源码＋本轮runner/策略/PLAN）。数据库仅`s/e.db`；正常库/child/未知DNS/非公网连接/捕获窗口外公网共5项护栏均0。
- 真实ASGI API消费真实`MaterialSourceTransport`、公网resolver、TLS、文件对象仓库和SQLite，未mock fetch/DNS/HTTP/objects。Python SelectorEventLoop用于Windows可观察socket.connect审计；不是监听HTTP服务或浏览器验收，也不声称生产Windows Proactor环境全链验收。
- 预览不联网；同UUID重放沿用同receipt，改payload得409；历史请求、document凭证、原件下载均无额外公网DNS或connect。关闭首个app生命周期，再创建app并以同合成账户登录，冻结凭证和同SHA原件仍可读取。没有第二次真实捕获。

私库保存合成账户的密码摘要及会话状态，属于私有数据；明文口令、认证响应、cookie及Set-Cookie不导出到报告/回执。两个TestClient生命周期均已退出，没有启动浏览器或监听服务，没有Provider或设备调用；R74早先研究页18另已关闭，原空白页12保留。

## 失败、修正和选源边界

- 先前JRC robots301到错误HTML、MDPI/NHTSA/NASA等受阻候选保持拒绝，没有改UA绕过、降级HTTP或放宽robots。开放Copernicus论文PDF约11740KB超过8MiB，排除；Zenodo候选MIME为octet-stream，未为它改PDF合同。见[独立选源研究](../../../.artifacts/r74-source-government-e688ba13c83f4235a8f0aad2e4a0e381/REPORT.md)。这些是有界候选结论，不推定全部公开来源不可访问。
- 沙盒原子硬链接WinError5，宿主同新隔离目录探针成功；完整验证以自动审批后的宿主执行，保留相同私库/DNS/子进程护栏和真实对象仓库。只选短私有路径，不削弱存储发布规则。
- [首次runner失败](../../../.artifacts/r74-live-e1351274cddf4801b38351e243034540/verification.json)在第1检查停止，未进入lifespan、DB connect或来源联网：SQLAlchemy显示URL把Windows `E:`编码为`E%3A`，字符串等值比较误判。只读诊断确认实际database路径正确，新GUID唯一改为SQLite backend及解析后绝对路径核对；[补修记录](../../../.artifacts/r74-live-c726bf6f944a4e6fb094e7ec79188e23/harness-correction.json)保留两源码SHA及旧失败。它是工装修正，不是产品数据库根因修复。
- 运行前独立静态审查另补UUID先落盘、503安全失败代码留证、DNS与public connect双观察/窗口限制、真实阶段里程碑和Windows SelectorLoop。没有因失败自动换UUID重抓。上述首次失败甚至尚未构造捕获请求；新阶段才产生首个真实捕获。

## 内容复核和后续

PDF的15页文本及6个关键渲染页已由独立agent对照，Root另目视首页和第3页。表1是9个商品名/研究代号；表2是样本与分析方法矩阵；表3是颗粒分类占比，不能当磨耗率、寿命、湿抓或滚阻。道路模拟器通常50km/h、4h、约200km、初始10°C，Summer A混凝土样本为60km/h、7h，例外条件必须保留。该文是轮胎/路面磨损颗粒原始实验，并非整胎综合性能横评。

独立[内容结论](../../../.artifacts/r74-pdf-review-8ef032fe57a44573b3c1f5e7cb771ad5/findings.json)及逐页原文/渲染由最终清单绑定。当前系统仍以`content_authenticity:unverified`、`source_reference_relation:operator_configured`、`unparsed_receipt/accepted_as_facts:false`保存，没有把论文事实自动采纳入TestEvent或为任何现有SKU建立关联。

首材料可用于轮胎磨耗/路面条件、实验方法和数值的来源对象核对；论文中的商品名或尺寸不足以建立namespace产品代码、GTIN、市场、OE及技术版本等精确身份。agent阅读不等于两名真人审定，两个合成账户也不能代替真人Golden。

下一工程优先级为[B本地同场只读连接层与专业Golden评估合同](../../../.artifacts/r74-next-11d9405781e247e4b0d385e88900e538/REPORT.md)：复用R69候选、R71当前有效桥和R65算法，同时保留原始来源值、排名与不足，不产生跨场综合排名。C仍需独立权利/同意/专用输出协议，不能借已审桥解除R70事实摘录门禁。

代表性精确SKU真实Golden、B/C、真实Responses语义质量、正常库020、PG、新原生设备、其余来源及全部V1 Gate仍开放。未commit/push/publish，原Goal保持active。最终工程结论以本轮清单及根外独立审计为准；哈希清单不替代完整工作树/证据/私有数据保全。
