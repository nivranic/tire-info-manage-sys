# 固特异新加坡官方规格实施计划

## 目标与设计

沿原规格P0厂商范围，接入Goodyear新加坡Eagle F1 Asymmetric 6与SUV版。使用既有固定SourceSpec、受限Parser子进程、原文捕获、质量评估、在线优先与授权历史回退，技术栈为Python标准库HTMLParser、Pydantic、FastAPI和现有React工作台。[原规格](../requirements/2026-09-26-tire-intelligence-original.md)

本阶段按brainstorming确认合同，按writing-plans整理步骤，按executing-plans逐项实施。沿用既有main及用户的自主执行授权。

## 已核对的官方合同

固定页面包含一张逐行规格表和两张按轮辋排列的展示表。三张表逐项一致，普通版53条，SUV版15条。展示表通过rowspan压缩，SUV表还把22英寸规格放在21英寸列下，解析以逐行尺寸为依据。两份声明集合完整核对后，每条规格仅形成一次来源观察。[官方规格](https://www.goodyear.com.sg/tyres/goodyear-eagle-f1-asymmetric-6)

逐行保存型号、R／ZR尺寸、载重指数和存在的速度级别。三条速度栏为空，保持未知。仅明确XL形成增强载荷声明。`X (EDR)`、FP、EDR、RO、MO、星号、I*和(+)按来源原栏保存，技术与OE解释依正式依据继续核验。产品代码、GTIN、静音、缺气保用及未声明属性保持未知，身份使用现有source_scoped合同。

robots允许固定产品路径。条款授权组织内部非商业复制并要求保留版权声明，原始页面和通知完整留存于Git忽略目录，商业再分发许可继续待核。[robots](https://www.goodyear.com.sg/robots.txt) [官方条款](https://www.goodyear.com.sg/legal-disclaimer)

## 实施步骤

1. 新增 `apps/api/tests/test_goodyear.py` 的合成三表工装，覆盖两型号、缺失速度、未知代码与技术、原始标记、字段出处、三表差异、重复及损坏响应、全表校验后筛选、正常Parser子进程和遥测。在 `scripts/run_api_worker_regression.py` 登记目标，保存实现前失败。
2. 新增 `apps/api/tire_api/adapters/goodyear.py`。固定URL、标题、表头、两个型号分组及两份展示集合形成合同。校验三表、尺寸与轮辋、值域、重复、长度和行数，再做查询筛选。缺值按领域合同保存，新增字段保留准确XPath。
3. 接入 `adapters/registry.py`、`adapters/transport.py`、`parser_runtime.py`、`parser_child.py`、`parser_bundles.py` 和 `telemetry.py`。可信目录增加至14项，既有8至13项完整目录继续接受。扩展 `test_parser_bundles.py` 的旧安装重建、`test_parser_releases.py` 的首次部署保留验证及受影响的当前目录断言，再核对 `scripts/regression_children.py` 源码绑定。
4. 在 `apps/web/components/workbench.tsx` 补新加坡及原始标记的中文标签。运行来源、Parser兼容与部署、质量、传输和核心相关回归，再执行Web测试、三端类型及生产构建。
5. 独立SQLite通过正常API核对普通版、SUV版、交叉尺寸、缺失速度、原始标记、原文哈希、冻结Parser、重复查询和单次授权回退。正常生产Web核对来源与型号选择、未知身份、原文、1440／390／320视口及控制台，关闭自有服务后核对数据库与对象。更新当前交接入口和验收记录，验证后按已有授权提交并推送。

## 验证命令与回退

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/gysg-next --targets apps/api/tests/test_goodyear.py apps/api/tests/test_continental.py apps/api/tests/test_bridgestone.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_releases.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_telemetry.py apps/api/tests/test_quality.py
npm run test --workspace @tire/web
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
```

回归与构建输入执行期间保持稳定，输出使用新槽。源码或合同失败保留原始回执，定位后修正并使用新槽复验。既有Parser部署沿原修订执行，新增来源使用新包首次部署。来源可以通过既有管理入口停用，历史快照及原件沿现有读取合同保留。商业许可、精确SKU、长期稳定性、真人Golden、真实OpenAI语义与完整V1继续逐项验收。
