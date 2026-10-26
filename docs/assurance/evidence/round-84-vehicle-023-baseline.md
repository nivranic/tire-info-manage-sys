# 第84轮 车型023合成私库基线与静态回放

日期：2026-10-19。**门1完成：由冻结当前023源码生成、含合成历史数据的私库基线已采集、独立静审、受管静态回放并原字节发布。**这不是正常库备份，也不是真实保留的历史生产库；正常库可能更旧，本轮没有观察、连接或升级它。门2的023→024迁移、回滚及产品二进制证据链尚未实现或验证，完整V1未完成。

## 分阶段结果

| 阶段 | 固定证据入口 | 真实结果与边界 |
| --- | --- | --- |
| 首次工具独审 | `.artifacts/r84-tools-review-f786cfc5dc294e0d98b8263cc7e866ce/review.json` | 旧builder工具审通过；不等于尚未生成的五fixture审查 |
| 首次freeze | `.artifacts/r84-f-ec1b6873adb4/result.json` | exit0、passed=true、153源码闭包稳定、DB连接0；旧identity及封源保留 |
| 首次capture | `.artifacts/r84-c-7592be617590/result.json` | **exit3、passed=false、AttributeError，未出staging**；1连接自行关闭，源码稳定，原失败不覆盖 |
| 最小工具delta审 | `.artifacts/r84-tools-delta-review-a8edc6c5482246bca45367782d33b703/review.json` | 仅审核下述三处工具修正；未改产品、Guard或预算 |
| 修正后新freeze | `.artifacts/r84-f-ac2eed0ebe85/result.json` | exit0、passed=true、153源码闭包稳定、DB连接0，使用新identity重新封源 |
| 修正后capture | `.artifacts/r84-c-8602b0153de5/result.json` | exit0、passed=true；74产品模块均来自封源，main未导入；2连接自行关闭、forced0，145资产 |
| 独立五fixture静审 | `.artifacts/r84-fixture-review-6aa62d0393304f8e9b734bc9d1c0b163/review.json` | passed=true；stdlib AST/SQL literal/JSON/base64/hash只读审核，没有DB连接、SQL执行或产品导入 |
| 仅静态fixture replay | `.artifacts/r84-r-ec8e9c697106/result.json`、`replay-equivalence.json` | exit0、passed=true、static_only=true；141表/145资产等价，产品/SQLAlchemy/main导入均0，1连接自行关闭、forced0 |
| 原字节发布 | `.artifacts/r84-publish-afaf145330914e169ac6839fbf924754/publication.json` | 恰五文件、此前目标不存在；发布前后source/target大小及SHA一致，无DB执行 |

首次capture根因：`OfflineScope`的garage/watchlist/recent默认include=True带入额外tire，`_blocked_plan → offline_evidence.resolve_scope → field_evidence.source_catalog`遇到没有`.sources()`的`registry={}`而失败。最小修正只有：三默认selector显式include=False且recent limit=0；只保留两个显式vehicle引用并将registry改None；独立历史断言核对三selector关闭。未删除offline簇，也未把失败重写为通过。

各运行分别核对153输入首尾稳定、资源关闭、非自检拒绝0及R38不变；capture/replay各8项护栏自检单列通过。153是源码闭包，不是测试数：140产品Python＋4字体资源＋2依赖文件＋2工具＋5既有harness文件。本轮没有跑149模块全量。

## 正式静态fixture

正式目录：`apps/api/tests/fixtures/vehicle_binary_023/`，以下五文件与`.artifacts/r84-c-8602b0153de5/staging/`及独立review逐字节相等。

`.gitattributes`仅为该目录追加`-text`以禁止Git行尾转换；实际`git check-attr`确认五文件均text=unset/eol=unspecified，五份大小/SHA仍与独审及发布一致。只读核验回执为`.artifacts/r84-attributes-392f7688e7094e1fa63a654bb56f2582/verification.json`（1751B/SHA256 `6f8e35125744b3f5c8d9cc6cac7c79d4a0cd3d260aa47651723152a50a512c51`）；属性文件为387B/SHA256 `9c83038f82b522d96b29c8493f53a7f85d5058e96966514f3d316b3864bea27d`，原334B保留，未重跑DB/replay。

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| `schema_023.sql` | 85777 | `10163a3c2e3f7179c11a6c40ef30fb85da424f902026d28e97c99cd6234007ab` |
| `seed_023.sql` | 137518 | `d00cf21e19e8f49b40f5c6d66301e6dec009b8e2b496b04f29c344421ccb2e80` |
| `expected_023.json` | 3034106 | `fb57f16c91deed5a4e3963b71ad1698d777659f79b95d52bd1ed5ca2754373f8` |
| `source-index.json` | 53664 | `9ca4e2e088ffd80fbab926cf4ba4c5972f82896d9a4bc5f7555716bb130f8d8e` |
| `README.md` | 1334 | `9b6e511d0401686f1aaee74370de12634bdf0ad38423671d21c5b14692097d93` |

最终工具：`scripts/run_vehicle_binary_023_gate.py`为27331B/SHA256 `7ca2a3b7174a1af24407c651e5f4cde631c1ea017c1bda4f29ceb4eb4420d529`；`scripts/build_vehicle_binary_023_fixture.py`为56624B/SHA256 `0a05a6ebbd97f2f04a6c3bd4f8a959a28a7618849b5a399463c08c22c3c155c3`。driver要求live source==frozen source且产品Python数为140，只是本轮capture/replay入口；024源码修改后，不能声称原driver命令仍可直接运行。

## 已核基线形状与历史语义

141表、601 schema对象、57 trigger、145资产、88显式seed行。601对象为regular table135＋virtual1＋shadow5＋index156＋autoindex247＋trigger57；34表非空包含两张FTS shadow，显式seed为88行/32表，不将自动shadow内容当显式seed。资产为4 objects＋141 bundles。

独立冻结AST比对134 ORM表、1181列nullable/PK、169 FK约束/170列部分（含device consent复合FK）、151声明索引；57 trigger均与测试侧独立`_TRIGGER_CONTRACT`精确核对失败策略、谓词与RAISE理由。FTS一虚表及五shadow保留inventory，不盲执行autoindex/shadow DDL。两张vehicle表body仍NOT NULL，无024 encoding/reference列。

指向`vehicle_snapshots`的入向FK恰为quarantine.previous_snapshot_id、verification.snapshot_id、wheel_fitments.snapshot_id三条；无指向`vehicle_quarantines`的SQL FK。车型仅有ORM immutable guard，没有数据库immutable trigger；不能在下一轮凭空假定存在。

合成历史覆盖旧JSON raw/hash、同raw多receipt、不同raw同fact、已消费quarantine approval、新capture同bytes及Parser拒绝不accepted。garage保留B，reparse latest baseline是accepted-loss(C)，evaluation same-raw reference为B。仅有一条合成历史bootstrap登记revision1、数据库字段state=active；未调用bootstrap/activate命令、未启动normal app，没有Parser执行/selection、重解析/评估完成或人工review。

fitment relation为pending_review并核生产只读preview；interest payload为生产只读投影。offline完整blocked preview仅两个显式vehicle引用：B accepted，quarantine被当作accepted引用时拒绝；没有OfflinePack。credentials、Parser executions/selections、reparse/evaluation completions/reviews保持空。

expected由封存当前023源码在修改生产模型前采集并冻结，不是从升级后schema学习旧库。replay只加载静态SQL/JSON/embedded assets，在新私库得到相同inventory SHA256 `c11e29f173f1e5fc314a394bc61ef904eca8c86443f5cfaf2b2c39fe5fc2baa2`；这是静态基线回放等价，不是迁移通过。

## 收据与封存边界

核心收据SHA256：首次工具审`6d52d9ae0c39a4c95259f3cd4425c0a8a8475707b7d66d093ce23681c910a934`；delta审`3892bcf9eef8aa6a6146185f9d1cc2bb9fc2cef5b0f22afa8f57fb5d358520fd`；五fixture审`454178b9c280a3fb592f1afb9f7d684739b1e56e21612d76ef5543fcdf4b8954`。

运行result SHA256依阶段为：首freeze `ea1dafd029a26887df687d20850fb0ef3dae535b46c489ddb48e21f4c5eb5e87`；首capture失败`2ee9e877637e71a16711170170f91ba9b3aa712c133a46118e6e17a74282aafa`；新freeze `745477e8f561c0f3d1e6b95d318bc6d28d4533fd02f007b5429a35f95d7e9ddd`；新capture `5e63de5fcb96e4d88f26e375a1d3db1eb1f7fcc4a970948495831884144c18ea`；replay `0ff9dabc64256d3336e45d782d8fbf6c6b054961d4a7af39bf4878bee53b16ea`。

replay-equivalence为197B/SHA256 `4fb6eb470ba833b759fada149f8033da949e9a213304030fcc056bc1bdc29443`；publication为1708B/SHA256 `d56a175597e532f1fadfdaec6288769f162b71d5d7a1e3fcb50d5eeef54fbc75`。首freeze source-index为`b4a7b7d4dac869ae7dd4900372eefb9907d979e23c6df7f1669cc5ae9f190bb5`，新freeze为`9584fd7a6d67b0813c77dbc13844848ef325d7cfc81e1b8366913bdab196cdf7`。

identity原样保留：未用于freeze的`.artifacts/r84-identity-3e9c94e2e6b5/dirty-identity.json`；首freeze使用`.artifacts/r84-identity-2751decf5e41/dirty-identity.json`（SHA256 `5ce8ac87ef7ed93e3bbc4235f8bd1382ad8d49c9d6846cacc86a938240fe09f7`）；修正后使用`.artifacts/r84-identity-6c56b7cb9d4e/dirty-identity.json`（SHA256 `f724bc26f3efcdc3c8ff28c43f4181d3a01b2dba39b785331ca39d68848245e3`）。两freeze、两capture及replay的source-before/source-after各自绑定对应源码；旧阶段不被新阶段替代。R83及更早seal原字节不改，本轮四文档另立绑定；机器总封存以新生成回执及独立核验为准。

本轮受管运行回执均normal_database_started=false、real_network_or_provider_calls=0，正常库、实网、Provider/receiver新调用为0；Guard证据限于Python API/audit边界，不声称OS/native syscall保证。未提交或推送。

## 下一精确入口

**门1不重做，门2待实现。**沿用[冻结PDF合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)§4，先核迁移编号、保全/preflight及局部重建/回滚方案，再实施拟`024_vehicle_binary_raw`。未来迁移测试必须只加载上述正式静态fixture，不依赖`.artifacts`或新的`Base.metadata`；该入口与迁移/回滚当前均未实现或验证。需覆盖nullable＋encoding/capture/CHECK、三入向FK/逻辑引用、历史raw/hash与对象、失败原子性及回滚，不从升级后schema学习旧expected。

024、统一原件读取helper、真实PDF采集/隔离Parser/存储/消费者/API/Native/PG等仍未做；fetch/ready未开放。许可pending、`provider_use/export=false`及首代`requires_source_verification`保持。真实专业精确SKU/外部真人Golden、完整专业性能C/真实Responses、P0来源和完整V1各Gate继续独立验收；不重做R81发现，不再索要Key或URL。
