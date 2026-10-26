# 第83轮：首代 SU7 已复核 PDF 纯函数切片

日期：2026-10-19，Asia/Hong_Kong。**首批固定原件的纯函数及拒绝测试已正式集成；真实原件离线检查153/153通过，四模块、五个目标条目的24项回归通过。首代PDF捕获、隔离Parser、存储和消费整链仍未交付，完整V1未完成。**不同检查阶段分列，不相加为全量通过数。

## 已交付的范围

`parse_reviewed_pdf(raw: bytes, vehicle_id: str) -> dict`仅接受`xiaomi-su7-first-generation`、严格bytes、非空、≤8MiB、`%PDF-`签名以及已复核长度和SHA。首批S2原件3240150B，SHA256为`0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`。正式三文件逐字等于独立审过的draft-b：

| 正式文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/adapters/xiaomi_first_generation_pdf.py` | 7984 | `ace2340d066ea3196620961413715f784b0034174a3d304c9679ea86848b6c83` |
| `apps/api/tests/test_vehicle_pdf.py` | 2312 | `02e1e2cf0272f776e048441ac38f31517d04b08c99e6ca930ba8dd1cf851eee7` |
| `scripts/verify_reviewed_vehicle_pdf.py` | 13437 | `5aa4315ae37da23694195b1f36db719409ca07d5d272f30827ca923858154aff` |

这是绑定原件SHA的已复核映射，`parse_method=sha256_bound_reviewed_mapping`、`mapping_id=xiaomi-su7-first-generation-pdf@1`。不使用OCR或自动文本提取，不运行时读取artifact，也不代表首代当前配置全集。返回fresh dict/list；只声明方法和mapping，没有制造服务端六键`parse_provenance`。URL、MIME、source和purpose仍须未来可信caller校验。

坏PDF签名返回`vehicle_pdf_invalid`；未知长度或SHA修订返回`vehicle_pdf_revision_unreviewed`；类型、空输入和预算错误沿用`parser_input_*`。真实原件单字节变化、同长未知hash均拒绝，不能将新修订自动套入旧映射。

## 事实与未知项

输出3配置×5行共15个fitment，含不可用格。本地稳定行ID不是厂商产品码；S2第3页1272×1800页图、灰字描述区和行区locator及页图SHA已进入映射源码。W3 Pro bbox为`590,975,887,1161`。

| 行／系列 | 前／后规格 | SU7／Pro／Max | 条件与限制 |
| --- | --- | --- | --- |
| W1 19寸低风阻 e·Primacy | 245/45R19／同 | standard／standard／optional | 仅Max免费选装 |
| W2 19寸运动 TURANZA6 | 245/45R19／同 | unavailable／unavailable／standard | 保留原灰字“前后” |
| W3 20寸运动套装 Pilot Sport EV | 245/40R20／同 | optional／optional／unavailable | 前Brembo四活塞固定卡钳＋打孔通风盘 |
| W4 20寸运动 Pilot Sport EV | 245/40R20／265/40R20 | unavailable／unavailable／optional | Max独立行，不与W3混轴 |
| W5 21寸运动 P ZERO | 245/35R21／265/35R21 | unavailable／unavailable／optional | 不猜未印子款 |

CLTC脚注保留原胎系列顺序：SU7为700/628km，Pro为830/758km，Max为800/810/750/725km。它们是整车配置续航说明，不是轮胎性能评分。年款、完整SKU、LI/SI、OE、厂商产品码及matched variant等未知保持null/false，不推断安装安全。

## 实际验证分账

| 阶段 | 实际结果 | 证据资格 |
| --- | --- | --- |
| 独立草稿复核 | 97项只读AST/JSON静态核对 | 未参与纯函数编写，不计作产品测试；正式三文件保持所审字节 |
| 正式纯函数离线检查 | 153/153，exit0 | 直接加载已集成公开纯函数；使用真实、非UTF-8的S2原件，无mock或SHA替换；未启动pytest、网络、DB或child/bundle |
| 目标回归 | 24/24，四模块、五个目标条目，tool/runner/pytest均exit0 | setup/call/teardown各24通过；失败、跳过、incomplete、subtests及报告失败均0 |

目标24项恰为：新`test_vehicle_pdf.py`整文件20项拒绝测试；`test_vehicles.py`首代不复用当前代际与空库元数据两项；`test_parser_runtime.py::test_real_child_matches_fixed_pure_parser`指定小米JSON参数一项；`test_parser_bundles.py::test_real_nine_source_archive_runs_saved_tire_and_recall_and_rejects_pirelli`一项。最后两项分别为**既有JSON夹具的真实受管child**和**按旧协议重建的九源/eager可执行归档兼容例**；后者使用本地保存片段，不是真实保留的历史原件，两者都不是PDF child或新在线抓取。

149仅为完整注册manifest长度，未运行完整149模块。663输入首尾逐字相同，source-before/after SHA均为`945a7181acb87713f668133de63e8a75c8ca045e064c1ca2885c5b1955251698`。3个受管child全部exit0、live0；metrics active/retained0、resources_closed=true、R38未变。护栏自检和隐私检查通过，raw/known/other非selfcheck拒绝均0；这些是API/audit护栏证据，不是OS/native syscall保证。

相对R82的660输入，本轮为runner一文件变更、上述三文件新增、旧659不变、零移除，形成663输入；现有guard、child和旧测试未改。正常数据库未启动，真实Provider/receiver调用0；未提交推送。

## 精确证据入口

路径均相对于工作区；普通Git clone不自动携带本机`.artifacts`。

| 证据 | 固定入口／SHA256 |
| --- | --- |
| 正式集成与153检查 | `.artifacts/r83-pdf-integrated-5c6abba3b1674363a87bff19e865457e/verification-final.json`；`93082896a62570462942b07b349b66acf5c1a4efef7c253e46fe46554f026abf` |
| 离线检查与结构化结果 | 同根`offline-formal/verification.json`、`parsed.json`；分别`d5fdbb85af8fad267e20246d87ea6e581cb7dca0705e65f892bf8a5611d9625e`、`384fc13a079c05753c7c4f45160ca8c95cd4246076cd137d75a2d46430f600ea` |
| 目标24终态 | `.artifacts/r83-t-4c1b750e92fa/result.json`；`86d9e15a02e016fd51e2f19445b1c9c07594a55c840f5f1e844fd34142fe43ed` |
| 显式运行delta／safe汇总 | `.artifacts/r83-runner-052f8d92a4c7/runtime-delta.json`、`target-safe-summary.json`；分别`2457db9c7227db9c224fbb2e03329e9796f69c0f0b78ff8f954203f624b4be1c`、`e86ebab396c276b6e8bc120107898655ecd007e44d88c0c50a9077e3cc0ee3f3` |
| 独立草稿审 | `.artifacts/r83-parser-independent-4a94e5c76df24df18b2a2e710f84206e/REVIEW.md`、`review.json`、`seal.json`；review SHA为`d3798df5e99ee73ba0bee4f28a8079892303683e9fda9156ef48d629fe9a1805` |
| 原件／视觉矩阵 | `.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf`；矩阵`.artifacts/r81-su7-visual-review-7ce747a644e64296b051f815a0d7fe39/VISUAL_MATRIX.json` SHA为`947f339855fcb2c1c9b0e238ecb06bcb830cc32b7012365918f40df3a355740a` |

R82历史seal原字节保留：`.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/verification-final.json`，SHA`d65e83d6c1cc8723f12e18606ce3ee5f9f795c939aea5e3b5f29e38b2fb1fc7e`。R83新增文档另立绑定，不重写历史pins；机器总封存以新增回执及独立核验为准。

## 下一精确入口

沿用[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)§4，当前023，拟`024_vehicle_binary_raw`，实施先重新核编号。**修改生产模型前先冻结并独立核对023基线DDL、合成历史行、索引/触发器expected**；不能用修改后的`Base.metadata.create_all()`构造“旧库”，或从升级后schema学习expected。

随后按受管迁移、preflight与保全合同，只在私库验证nullable＋capture/CHECK、入向FK与逻辑引用、失败原子性及回滚；正常启动不得静默执行重建。无需重做R81 Phase0、视觉或联网发现，不再向用户索要Key或URL。

fetch接入、首代ready、真实生产capture、024、PDF child/bundle、binary存储、V2下载及消费者、Native和IAM均未实现或验收。许可仍pending，`provider_use/export=false`、首代`requires_source_verification`不变；完整V1各Gate继续各自验收。
