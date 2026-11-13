# 马牌中国官方规格接口接入计划

## 目标与设计

沿原规格第268行补齐Continental官方渠道，使用中国官网SC7页面实际引用的只读规格接口。在既有main实现，按brainstorming、writing-plans与executing-plans完成合同、实现和验证，文档采用writing-clearly-and-concisely整理。

静态产品页只包含表头。页面引用的getData.js明确使用GET调用同域 `/tpservice/Search/getTireData`，script.js把页面的SportContact SC7名称传入tire参数。固定JSON接口已直连取得47条规格，覆盖18至23英寸，包含同尺寸静音属性不同的两行。采用这一固定接口，复用既有SourceSpec、受限Parser子进程和证据链。HTML初始空表与通用搜索接口的合同分别留在本机研究记录。

robots允许该接口路径。法律声明涉及作品和商标的使用许可，本阶段采纳逐行规格事实，原始响应留在Git忽略目录，商业再分发许可继续待核。美国站robots本次仍403，该站保持访问失败状态。[中国官方产品页](https://www.continental-tires.cn/tires/sportcontact-sc7) [中国法律声明](https://www.continental-tires.cn/legal-notice)

## 数据合同

- 来源为 `continental-cn`，地区CN，型号SportContact SC7。唯一规格URL为 `https://www.continental-tires.cn/tpservice/Search/getTireData?tire=SportContact%20SC7`。
- 顶层按轮辋英寸分组，逐行包含size、level、load、protect、ems、silent、type和pattern。全量校验分组、字段、值域、重复行及500行上限，再按型号与尺寸筛选。
- 保存完整R／ZR尺寸、载重速度、明确XL、FR及原始技术标记，每个采纳字段保存JSON路径。静音的“是”映射ContiSilent。空白技术声明保持未知，接口新增技术值须经合同复核。
- 产品代码、GTIN、OE与未提供的技术属性保持未知。沿用identity@2的source_scoped身份，相同尺寸的不同技术行分别保留。精确SKU及跨来源等价继续待核。
- 固定URL白名单覆盖查询参数。附加参数、用户URL、同路径其他型号、跨域和非HTTPS均拒绝。

## 实施步骤

1. 在 `apps/api/tests/test_continental.py` 增加明确合成的规格与反例，覆盖未知身份、静音双行、全表先验、非法参数、真实Parser子进程和遥测。登记 `scripts/run_api_worker_regression.py`，保留实现前失败。
2. 新增 `apps/api/tire_api/adapters/continental.py`，接入 `adapters/registry.py`、`adapters/transport.py`、`parser_runtime.py`、`parser_child.py`、`parser_bundles.py` 和 `telemetry.py`。新可信目录13项，继续接受此前8至12项完整目录。正常API首轮证实带参数URL在 `captures.py` 被拒绝，补齐来源绑定的固定URL与响应类型核验，并覆盖其他来源、附加参数和错误类型。
3. 调整 `apps/api/tests/test_parser_bundles.py` 的历史安装工装，让重建的12项包执行自身旧源码，覆盖新增来源首次部署与旧部署修订保留。复核后更新 `scripts/regression_children.py` 中受影响的源码绑定。
4. 按需补共享Web事实标签，执行新来源、既有品牌、Parser包／部署与传输回归。实际联网使用新隔离SQLite、对象与Parser目录，通过正常API验证47条观察、两条静音差异、过滤、原文哈希、历史与单次授权回退。
5. 核对正常Web选择、来源限定身份、未知代码、原文和窄屏。更新验收记录与交接卡，审查后提交并推送，独立复核远端。

## 验证入口

正常API第三批已完成首次47条观察与静音双行，随后相同原文的重核验被field-loss质量门隔离。回执确认baseline和candidate均为2行，缺产品代码导致稳定键全部缺失。将在 `service.py` 复用 `assess_records`，仅在当前冻结Parser选择、身份合同、URL、响应类型、原文字节与哈希、逐行领域投影全部一致时，以完整行指纹比较缺代码观察。有代码行继续使用既有稳定键。原文或解析输出变化交由通用质量评估。质量比较结果与实体身份分别记录，实体继续使用source_scoped。

专项回归通过正常API和真实Parser子进程验证重复200复用快照及事实，再分别改变原文字节与解析输出，核对隔离结果和已采纳数据。原始质量隔离回执保留于workspace-api-r3。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/ctcn-r1 --targets apps/api/tests/test_continental.py apps/api/tests/test_bridgestone.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_releases.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_telemetry.py
npm run test --workspace @tire/web
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
```

输出使用新槽，回归与构建执行期间保持输入稳定。原始材料、失败回执和私库保留于 `.artifacts/p0-sources-20261113/` 及各受管输出目录。完整P0覆盖、长期可用性、精确SKU、真人Golden、真实OpenAI语义及全部发布Gate继续逐项验收。
