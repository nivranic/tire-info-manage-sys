# 第88轮 车型PDF隔离child与版本兼容

日期：2026-10-19。**共享Xiaomi Parser 1.1.0的首代PDF隔离child、selected sealed mapping派发及旧包兼容切片已实现并验证。**真实历史S2原bytes已实际执行隔离child并核returned receipt。adapter在线fetch、VehicleService写入及binary治理/消费者/V2/ready接线继续待做；本轮没有把离线执行提升为新在线capture或正式车型事实采纳。

依据[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)§3.2，承接[R87独立capture journal](round-87-vehicle-binary-capture.md)。正常库未连接启动，真实网络/Provider/receiver调用0；共享测试fixture的产品导入处于受管边界内，不声明实际run零app import。

## 唯一实际run

回执`.artifacts/r88-t-830e72a96c1f/result.json`：22515B / SHA256 `020beacf14f7e8a087349accfa820d2b7a639f13d380eb7b31a3bf4ff5c9abc5`。tool、runner、pytest均exit0；155 collected/protocol/call，155通过、0失败/跳过/incomplete，setup/call/teardown各155通过。Root已独立复算安全reports/JUnit、目标分账及全部源码live pins。

| 实际目标 | 通过 |
| --- | ---: |
| `test_vehicle_pdf_runtime.py` | 17 |
| `test_parser_runtime.py` | 38 |
| `test_parser_bundles.py` | 24 |
| `test_vehicle_pdf.py` | 20 |
| `test_vehicle_raw.py` | 51 |
| `test_vehicles.py` 两个既有代际/轴位精确目标 | 2 |
| `test_parser_releases.py` ABA及暂停保留原件/真实receipt两个精确目标 | 2 |
| `test_source_settings.py` 管理guard精确目标 | 1 |

共10个target条目、8个模块，其中五个整模块及五个精确目标。**153仅注册manifest长度，未运行全153。**新module的11函数静态展开17项先完成独立审查，随后17项才实际收集并通过；R87分批133与更早结果不与本轮相加为当前全套。

677输入首尾逐byte相同，全部live大小/SHA匹配；相对R87源码恰四生产文件＋runner＋children六变、新test一增、零删，其他670不变。文档与显式S2采样不属于这677个源码输入。

## 已核版本与sealed来源机制

- 共享`xiaomi.PARSER_VERSION`由`xiaomi-param-comparison@1.0.1`递增为`@1.1.0`；fetch实现及首代目录状态未改。host的精确版本集合只含1.1.0，不以文件存在或任意更高semver开放PDF。
- child先核closed IPC、manifest/tree、descriptor、原bytes容量及input_hash，再依据source＋精确首代query分派。PDF另核descriptor版本在host集合、selected sealed Xiaomi模块版本相等，随后只从该execution tree导入映射；SourceOnlyLoader/import检查及前后tree核验保持。旧1.0.1即使包含mapping也受控拒绝PDF。
- 其余全部文本分支继续严格UTF-8；JSON输入及旧包JSON行为保持。IPC字段、base64容器、raw input_hash、GO、8MiB输入/12MiB协议、8秒/CPU/内存、Windows Job、kill/reap未放宽。
- `checked_manifest`仅对精确新能力版本要求mapping文件，不破旧catalog；`_specs`新增依赖声明，但`source_catalog`只取其前两项。实际封存hash来自全`.py`树，旧1.0.1本就可能含mapping，不能据此认定它支持PDF。
- 只新增`vehicle_pdf_invalid`与`vehicle_pdf_revision_unreviewed`两项child/host safe码；未列mapping诊断失败关闭，不把任意`.code`或原始异常正文外传。

## 样本及receipt资格

新17项覆盖真实非UTF-8 S2经selected sealed child、原JSON、旧包mapping有/无、缺mapping、无效签名/未知修订、未列诊断、sealed模块版本错配、未复核patch/major版本、其他文本严格UTF-8、sealed mapping缺失/改动无fallback，以及mapping A/B/A。actual receipt核独立pid、exit/reap、bundle/parser/execution身份、deployment_revision、实际原bytes input_hash及原limits；输出不补造服务端parse_provenance。

旧九源样本是从当前私有安装重建，并将唯一Xiaomi版本逆回1.0.1后核整文件SHA `ca9bc74fca9b28c832306bdba9a0b2fe4532623f292572ee5918e29e13b8d997`；它不是保留的历史原包。新module校验真实child返回receipt；既有raw helper 51项仍包含合成completed receipt，不能把这些历史身份反例全部改称真实PDF执行或生产采纳。所有parametrize使用短ids，无bytes展开id或skip。

S2是既有R81研究原件，3240150B / SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`，不是本轮新在线响应。测试每次load先核大小/SHA并确认非UTF-8，缺原件直接失败。另有明确采样回执，Root已独立核其时间包围completed运行，且前后均同原pin：

| 显式采样回执 | UTC | bytes / SHA256 |
| --- | --- | --- |
| `.artifacts/r88-meta-830e72a96c1f/s2-before.json` | `2026-10-19T03:09:04.5043161Z` | 298 / `b973a0a26841337cfd996407bd68c136bd3b9f16a23bd1d7274f743010f7ebbf` |
| `.artifacts/r88-meta-830e72a96c1f/s2-after.json` | `2026-10-19T03:19:21.9831797Z` | 298 / `6ec5035c6c98b73b0b87a1c851982b6e1b157d066dd5bc21635bfa24c1a319f6` |

显式before/after、测试pre-use核验和677源码稳定是三种独立证据，不混称同一清单观测。

## 当前绑定、静审与资源

| 当前文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/parser_child.py` | 11715 | `830b9f38c0504faf4c16cc2f4f7c455abab9de75ca3b73983596268ade85e788` |
| `apps/api/tire_api/parser_runtime.py` | 20979 | `3258853b27d2c4348717fa2b54ff057b136cf5e1fe751a5eadf2daf0e5e7e566` |
| `apps/api/tire_api/parser_bundles.py` | 14980 | `30ff4d9485ed82b6515bbe201b9a61634c6e4b413c89771f8709c0069bfc366d` |
| `apps/api/tire_api/adapters/xiaomi.py` | 16207 | `aa98d55517398b5a7f8eb4fa1164fb9cc173b878dd5d8733ae90c97a13092051` |
| `apps/api/tests/test_vehicle_pdf_runtime.py` | 11354 | `a71ecb1ff36b7f34f00388910c7ba91d43a555798d7b10e569e3987ac3c644e4` |
| `scripts/run_api_worker_regression.py` | 42464 | `75723783ed6a05747609be29b718442b51f4ce2fa4dc226a7e2c055144839fc9` |
| `scripts/regression_children.py` | 27470 | `c45982002e0c289529b03a371ce5b7696666d4239b82323d6e35b5837b7a4f7d` |

独立全diff/标准库AST及pins静审在run前通过。runner仅新增模块登记和两处计数文字，逆回精确恢复R87；children只替换已审child/runtime两SHA，逆回恢复R87，整ChildPolicy策略/模板/类别/权限/预算及Guard不变。五份baseline archive匹配R87；`.artifacts/r88-impl-f51dbd134553/static-verification.json`保留原test pin，`docstring-verification.json`仅以header限定文字逆差关联最终test，测试AST与17项不变，不覆盖前一回执。

74 aggregate child退出分布为0×61、61×1、125×9、1×2、3221225540×1，包含既有fault/timeout/probe测试，不能称74全exit0。live child0、metrics0、资源关闭；报告失败及所有非selfcheck拒绝0，真实Provider/receiver0、正常DBfalse。R38不变依据受管备份前后元数据；封存不打开数据库，Python Guard不等于OS/native syscall保证。

## 封存与下一精确入口

本轮9个既有文件变更、2个新增、零删除，机器入口`.artifacts/r88-close-c4e29baf7316/verification-final.json`以实际生成及Root独立复算为准。继承R87明确目录并另立新绑定，不声明检查任意工作区文件；R87报告/seal、冻结合同、五个023 fixture及更早历史原字节保留。

下一步R89：VehicleService原bytes写入及冻结provenance治理，并使旧vehicle/VehicleQuarantine详情遇binary明确409；随后继续审批/重解析/发布治理、全部消费者、V2 API/SDK/UI/Native。adapter fetch、首代ready未开放，许可pending、`provider_use/export=false`、`requires_source_verification`保持。PG旧库受控迁移/活PG、正常库保全升级、真实专业精确SKU/外部真人Golden、完整专业性能C/真实Responses及完整V1各Gate仍独立开放。未提交推送，不再索要EPREL Key或URL。
