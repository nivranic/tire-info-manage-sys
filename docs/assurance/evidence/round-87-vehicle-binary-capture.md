# 第87轮 车型二进制捕获与拒绝原件journal

日期：2026-10-19。**显式binary准入、可信capture context预核、独立事务先提交原件及binary拒绝原件保留切片已实现并验证。**本轮扩展`captures.py`，复用R86原件核验helper；没有接入PDF child/adapter fetch、VehicleService写入、binary审批、全部消费者或V2 HTTP路由。首代fetch/ready仍未开放，完整PDF及V1 Gate继续开放。

沿用[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)、[R85 SQLite迁移切片](round-85-vehicle-binary-024-migration.md)及[R86原件helper](round-86-vehicle-raw-provenance.md)。正常数据库没有连接启动，本轮没有执行PG迁移、访问网络或调用真实Provider/receiver。

## 两次实际运行与最终覆盖

| 实际运行 | 结果 | 三阶段与范围 |
| --- | --- | --- |
| `.artifacts/r87-t-9f37c2a641d8/result.json` | 20379B / SHA256 `fb8a87a6ddc06a12c529f4075069707933ea6b54b7ad62fbcceb6630a6692076`；runner3 / pytest1；132通过、1失败、0skip/incomplete | 133 collected/protocol，132进入call；setup及teardown各132通过/1失败，call132通过 |
| `.artifacts/r87-u-4df160e8a0ea/result.json` | 19401B / SHA256 `fe2e4773b3910748718fc22c09a8f44a365e208f4f9d91a7eb875dd27d89417d`；runner/pytest0；61通过、0fail/skip/incomplete | 仅new binary module；61 collected/protocol/call，setup/call/teardown各61通过 |

首run原红保持，第二run没有覆盖它。最终覆盖仅选择首run的非binary72项和第二run的binary61项，合计133唯一分批目标；不是同一次133项全绿，不将两run的194个protocol当成194个独立测试，152仅runner注册manifest长度，未运行全152。

| 最终选择的模块／精确目标 | 首run | 最终选取 |
| --- | --- | ---: |
| `test_vehicle_binary_captures.py` | 60通过/1失败 | 第二run61通过 |
| `test_raw_captures.py` | 15通过 | 首run15 |
| `test_vehicle_raw.py` | 51通过 | 首run51 |
| `test_quality.py::test_quarantine_metadata_is_separate_from_explicit_audited_history` | 1通过 | 首run1 |
| `test_vehicle_quality.py::test_malformed_structure_rejects_before_baseline_and_preserves_raw` | 5通过 | 首run5 |

Root已独立复算两run安全报告/JUnit、三阶段计数和最终72＋61覆盖。safe reports省略参数id；按case index及脱敏nodeid对应协议，不要求参数化后的脱敏nodeid互异。两run各676输入首尾一致；第二run676与最终live一致，首run旧test由明确历史副本绑定、其余675与live一致；跨run仅该test短ids变化。R85分批313和R86的115不与本轮相加为当前全套结果。

## 首红、精确修正和证据边界

首run唯一失败为case4，位于三个body参数的第三个8MiB原bytes用例。safe report只记录setup和teardown的`ValueError`、`<frozen os>:720`，call未发生；没有保存原始异常正文、参数正文或captured sections。静态依赖链显示pytest将自动参数id展开并写入`PYTEST_CURRENT_TEST`，该定位与safe类型/位置吻合；这不是原runner已经输出该原因，也不倒填原异常正文。

修正前先保留明确历史副本`.artifacts/r87-idfix-c47cec530e4b/test_vehicle_binary_captures.before.py`，23636B / SHA256 `3d84f46f998b317800b599700550c3707404b1c19f626fe5172248411cef7a56`。唯一修改是在该parametrize增加79B短ids：`synthetic-binary-pdf`、`synthetic-ascii-pdf`、`synthetic-max-8mib-pdf`；8MiB输入及全部断言字节保持。独立精确逆去后逐byte恢复历史副本及原SHA；整模块AST去掉唯一ids关键字后等价。新module重跑case4的setup/call/teardown实际全过。

修正回执`.artifacts/r87-idfix-c47cec530e4b/change-verification.json`为2250B / SHA256 `24597c17de6d65fc7faa9969f9519e4a4a84547a5d994eee68362ad086ab31d8`；第二run元数据核验回执`managed-run-verification.json`为7455B / SHA256 `ada8cf1eecb0ddfad1b24f34c4d43b8e239d1a1cbb4241dc38b34ed895fcb989`。产品、Guard、ChildPolicy和预算没有因这项测试修正变化。

## 已核实现

- `validated_observation`只有显式`body_encoding=binary`才走新分支，且要求可信首代source/query、固定PDF URL、精确`application/pdf`、真正bytes、%PDF签名及1..8MiB。Parser版本和三键identity也须合法；单参数旧UTF-8返回原六键，旧MIME/URL和hash行为保持。
- `before_parse_recorder`固定原QueryRun上下文并深拷query。binary要求caller事务已关闭，只接受Engine及精确QueuePool/NullPool，拒绝memory/shared-cache与未知pool；独立journal核原run/session/query_key、原Selection/版本/identity及无已有capture，全部先于object.put。
- 原bytes经ObjectStore及EvidenceObject、RawCapture、CaptureObject写入，flush后用R86完整capture checker核DB副本、hash/长度、权威对象与原Selection；随后Audit和capture在独立journal提交。后续caller rollback不抹去已提交原件；失败只抛固定`evidence_capture_failed`，不声称失败时对象必为零孤儿。
- binary拒绝保留先用独立只读journal确认原run及一致capture已经提交，再仅把RejectedObservation/Audit加入caller事务。缺capture、未提交capture、错body/对象/签名均失败，不补建capture或object，不提交或回滚caller工作。合法unknown修订可保留原件；不要求completed执行，不据此产生Snapshot/Verification/accepted facts。
- 固定安全PDF失败码仅新增`vehicle_pdf_invalid`和`vehicle_pdf_revision_unreviewed`；未列诊断收敛为`parser_failed`，不保留任意异常文本。
- 旧`checked_capture_bytes`遇binary返回409 `binary_evidence_format_required`；旧quarantine详情仅对binary RejectedObservation同样409。该范围没有覆盖所有binary旧端点；Snapshot/VehicleQuarantine等消费者仍须后续接线，内部metadata的content_path不表示下载路由已交付。

独立静审、指定venv的隔离标准库AST及精确字节核验均通过。独立审查阶段没有产品import、pytest、SQL或网络操作；实际测试只来自上列两个受管run。

## 样本资格、绑定与资源

新binary journal测试使用合成unknown PDF bytes，真实写入本run私有ObjectStore/私库；不是受复核S2正例、新在线响应或正式映射事实。首run既有`vehicle_raw`回归使用历史S2原件，其3240150B / SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f`沿用Root已核R86基线；首run每次使用前核验，首run后再次核到同pin。没有额外的首run开跑前瞬间观测，S2也不属于676个源码输入；第二run只使用合成unknown样本。既有真实私bundle封存/登记与合成completed receipt不能证明PDF child实际执行。

| 当前源码 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/captures.py` | 15854 | `5dbbbb36f6357857c4059a0b8b889c93373ff09e1d12a3cf307ebc32249f118f` |
| `apps/api/tire_api/quality.py` | 21080 | `b7fbf5c50765284598e8f5e4d6d0afce60a29d8e516584dba46724f39c49ebc3` |
| `apps/api/tire_api/vehicle_raw.py` | 20143 | `dda0bfa5769841a0a5206ac357aaee90c7541d3ac8c5150e36132119514e1548` |
| `apps/api/tests/test_vehicle_binary_captures.py` | 23715 | `e7b8b58ff4ed68662b944d941a7733e2722d88fb9e41cee86e4c7dafc7c0b573` |
| `scripts/run_api_worker_regression.py` | 42414 | `c3cd51791e8d9ca26b739e4af120b09b47e9cff4352b62a4a8910a0386728c73` |

Runner仅增加一个manifest模块及两处计数/帮助文字；精确逆回可恢复R86 runner原SHA。两run报告失败/非selfcheck拒绝均0，资源关闭、活动监听与live child均0；首run两个既有受管故障child分别exit73/61，第二run没有child，不构成PDF child验收。R38不变依据受管run的备份前后元数据，封存不打开数据库。`normal_database_started=false`、真实Provider/receiver调用0；Python Guard不等于OS/native syscall保证。

## 当前封存入口与下一步

R86旧seal`.artifacts/r86-close-02ef9aa715ba4ecd808f9ee2815c5982/verification-final.json`保持730680B / SHA256 `098e4af9bb877edad164e6e69532127af6376e677467c89d8b6dedd7f2ed9bf1`；R86及更早报告、冻结合同与五个023静态fixture保留历史原字节。本轮三生产文件、runner和三现有文档为7个既有变更，新test与本报告为2个新增，零删除；新文档另立绑定，不改旧报告或seal。

机器封存入口为`.artifacts/r87-close-2a72b08a333b4c4b86edae0096d7177a/verification-final.json`，以实际生成回执及Root独立复算为准；其检查范围是继承的明确目录及本轮明确新增，不声明扫描任意工作区文件，不读取private库或凭据。

下一精确入口为合同§3.2 PDF child/bundle固定派发与版本，然后接车型写入及冻结provenance治理、binary质量/审批/重解析/发布、全部消费者、V2 API/SDK/UI/Native。本切片不重做。首代仍`requires_source_verification`，许可pending、`provider_use/export=false`、fetch/ready未开放。PG旧库受控迁移/活PG、正常库保全与升级、真实专业精确SKU/外部真人Golden、完整专业性能C/真实Responses及完整V1各Gate独立继续。未提交推送，不再索要EPREL Key或URL。
