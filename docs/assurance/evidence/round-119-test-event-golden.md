# R119 测试事件 Golden 工作台：定向后端与实际 UI 验证通过

2026-10-22，本轮完成现有测试事件详情中的独立预期、材料核对、异账户管理员审核、冻结集及真实记录差异消费者。定向后端验证通过，最终同一新 UI 批次 c54a 完成 39 项检查、11 次核心 POST 及自然关闭。旧 tire/vehicle Golden、Parser 发布合同、R71 身份桥语义及 R76 真人资格边界不变；这是合成材料上的工程链路验收，完整 V1 仍未完成。

## 已交付实现

- [计划与接口合同](../../plans/2026-10-22-test-event-golden.md)明确后端、前端和验证所有权；[产品源绑定](../../../.artifacts/r119-test-event-golden-20261022/product-source-pins.json)、[早期验证源快照](../../../.artifacts/r119-test-event-golden-20261022/verification-source-pins.json)及[修改前备份清单](../../../.artifacts/r119-test-event-golden-20261022/before/manifest.json)保留本轮范围。Root 另建[最终验证输入清单](../../../.artifacts/r119-test-event-golden-20261022/verification-source-pins-final.json)：11 项、1888 B、SHA-256 `3e2dd86c7a1c662a7b42c9eee72a778aa3b35ee0ecf1e709852164bf4f1cd1c7`，相对早期快照仅 QA 项变化，绑定 QA SHA `f40c158de5990af52423e77f8a3b7db0dcc9c6abec1e13a6d9087fcb0cd723d1`。旧清单原字节保留；c54a 的通过由该批终态回执独立证明，不倒灌旧批。
- 专用 `/v1/test-event-golden` 路由和 `027_test_event_golden` 追加迁移，新增 `test_event_golden_cases`、`test_event_golden_case_revisions`、`test_event_golden_case_reviews`、`test_event_golden_set_revisions` 四表。内容、审核与集合均追加修订并保留前驱指纹；SQLite 原生及 ORM 保护禁止覆盖、删除和替换。PostgreSQL 有对应 DDL，未实跑 PostgreSQL。
- 内容固定 TestEvent 修订及指纹、1–3 份 EvidenceDocument 原件及元数据、定位与独立权利声明、可选精确 R71 桥引用。成绩引用权限 `quote_test_results` 必须另行声明。严格独立预期保留原始字符串、小数尾零、负零、来源名次、单位、条件及空值边界。
- 写入使用稳定账户 ID、UUID 幂等键、精确修订与指纹 Fence；同账户换会话仍不能自审。管理员审核须绑定已保存内容，批准须重新核对全部原件；两账户仍不证明两个真人独立。
- 冻结 1–3 个已审核案例，固定内容和审核双指纹。事件、桥、内容或审核的修订与撤销不会自动恢复旧冻结资格；撤回集合可以用当前 Fence 和新有效引用显式追加冻结修订，旧修订保留历史。
- 评估只从真实持久记录读取 actual，复用事件只读比较函数，不接受客户端 actual、不伪造 HTTP 观察、不写事件/事实/桥/审核。可比较冻结事件/桥或当前版本，逐字段返回差异和当前失效原因，不跨事件排名、不自动绑定 SKU。
- 历史 GET 在原件损坏时保留已保存内容并显式标记 blocker；批准、冻结、评估重核失败则拒绝，不替换证据。最终输出始终保留 `human_truth_status=pending_external_review`、`wrong_merge_count=null`、`provider_use=false`、`export=false`。

## 独立审查已修正

独立后端审查提出并修正两项 P2：`not_linked` 也必须比较明确的 `expected_variant_id`，错目标不能因桥未关联而通过；不同逻辑标签落到同一明确 variant 或有效 identity key 的碰撞观察，与“足以证明两者不同”的资格分开，即使桥未审核或已陈旧也可报告观察到的碰撞。只有充分的已知正例才能证明不同；unknown 保持未定。

前端静审另修正账户/事件变更后的拒绝与撤回可达性、带前缀幂等错误码匹配，以及负例身份桥下拉被过度筛选的问题。账户 epoch、卸载取消、固定请求正文/UUID、历史集合与当前 Fence 分离均已核对源码；此处静审不替代真实 UI 验收。**目前没有 case revise UI、丢响应同 UUID 重放、切账户迟到响应的真实 UI 证据**，不能用 API、SDK 或静审补称这些场景已通过。

## 已执行验证：按批次分账

| 范围 | 证据与实际结果 | 能支持的结论 |
| --- | --- | --- |
| R119 API 与迁移 | [r119api-5e9b](../../../.artifacts/r119api-5e9b/result.json)：27 passed、0 failed/skipped，selfcheck 通过，sources/resources 标记稳定，非预期拒绝 0 | 私有合成库上的定向 API、独立预期、材料完整性、审核、冻结、碰撞和迁移保护通过 |
| 历史具名回归首批 | [r119reg-973d](../../../.artifacts/r119reg-973d/result.json)：17 执行，13 passed、4 failed；4 个 `filesystem_mutation_outside` | 4 失败来自 query ownership 与 external fact migration 的旧硬编码目录，护栏正确拒绝越出本批 private |
| 4 个失败目标新批复验 | [r119reg2-a207](../../../.artifacts/r119reg2-a207/result.json)：4/4 passed、非预期拒绝 0、sources/resources 稳定 | 仅修正测试私槽映射后，这 4 个目标在新槽通过；旧失败未覆盖 |
| SDK 与类型 | [Root 观察记录](../../../.artifacts/r119-test-event-golden-20261022/sdk-root-observation.json)：`tsc -p packages/api-client/tests/tsconfig.test-event-golden.json` exit0；4 个 SDK 测试 passed | Root 实际执行；SDK 使用注入的合成 transport，不是 HTTP/UI/后端验收 |
| 当前 Web 生产构建 | [verification.json](../../../.artifacts/r118-material-workbench-20261021/web-build-b119d3e4f5a60728/verification.json)：passed，124640 B，SHA-256 `bc083e313d9352320d049c61b2c82d2d460f4e971710a8c678048bfe7d00492d` | 当前 R119 Web 源使用既有受审构建入口完成生产构建；路径沿用 R118 工具目录，不代表复用旧构建结果 |
| 实际 UI | [c54a 宿主终态](../../../.artifacts/r119uihost-c54a/receipt.json)及[浏览器结果](../../../.artifacts/r119browser-c54a/result.json)：同批 39 项检查、11 次核心 POST，整批 passed | 合成私库、真实产品 HTTP 与 headless 浏览器中的已列明工作流通过；五个旧失败另记 |

主验证的三个 API 批次共有 **44 个唯一 pytest 用例（含参数化）、48 条执行记录（27+17+4）**；这不是同一批次 48/48，也不是同一全套运行全绿。入口自检和先前诊断批次另记，不混入该统计。canonical runner 使用 API venv 的 Python 3.12.10，不能套用 R118 Python 3.14 的证据。

`resources_closed=true` 是 canonical runner 自身资源汇总口径，**不能据此声称每一个 SQLite DBAPI 句柄都已逐一观察到 close**。本轮未直接打开保留 SQLite 库补证。

## 最终同批 UI 证据：c54a

[浏览器结果](../../../.artifacts/r119browser-c54a/result.json)记录 39 个通过检查及 11 次核心 POST：创建案例、独立管理员审核、建立集合、集合撤回/重新冻结、冻结及当前版本评估、事件撤销后撤回审核与集合。案例内容的 `/cases/{id}/revisions` 没有在本轮浏览器流程执行，不能把集合修订当成案例修订证据。

流程实际取得并下载合成 PDF，核对完整 SHA，确认下载不会自动勾选人工阅读；通过独立管理员审核后，unknown 身份仍显示未定及真人资格待外部复核。随后实际修改事件单位和条件，当前目标显示差异，冻结目标保留历史值但标记当前失效；集合撤回修订 #4 后仍能读取冻结历史 #1。

[Root 独立终核](../../../.artifacts/r119-test-event-golden-20261022/terminal-verification.json)再次以文件读取核对[合成原件](../../../.artifacts/r119fixture-c54a/synthetic-source.pdf)与[浏览器 saveAs 下载文件](../../../.artifacts/r119browser-c54a/downloads/r119-synthetic-original.pdf)：二者均为 1952 B、SHA-256 `a1a8191d736ec608d58ca384afc185e30076e4228b0b7b42e5cb926dcfc1e950`。这是实际浏览器下载落盘的合成原件，不是真实专业测试来源。

390px 视口的差异表使用内部横向滚动，页面没有整体横向溢出。Root 已实际查看[移动端撤回集合](../../../.artifacts/r119browser-c54a/mobile-revoked-set-panel.png)、[当前差异面板](../../../.artifacts/r119browser-c54a/panel-current-difference.png)、[移动端差异](../../../.artifacts/r119browser-c54a/mobile-valid-frozen-difference.png)、[移动端历史](../../../.artifacts/r119browser-c54a/mobile-frozen-history-panel.png)四张截图。该批 `page_errors=[]`、`unexpected_origins=[]`、`cleanup_failures=[]`；Playwright 1.63.0 / Chromium 1243、headless、合成 fixture，不代表真实设备或真人验收。

[宿主回执](../../../.artifacts/r119uihost-c54a/receipt.json)为 passed/completed，API/Web/browser 三个父进程自然 0/0/0，`forced=[]`，端口关闭、产品源与 QA 源稳定；Root 执行会话自然 exit0。[Web 服务](../../../.artifacts/r118-material-workbench-20261021/web-service-d119f54ab281c54a/service.json)为 stopped，Node 自然 exit143，Job 观察 2/2、自然等待后 active=[]、forced cleanup=false、构建输入稳定。[fixture 终态](../../../.artifacts/r119fixture-c54a/stopped.json)为 shutdown_complete，外网/子进程/正常库尝试计数均 0，所列源首尾一致。这些是各自守卫和资源观察范围，不是操作系统隔离或全部 SQLite 句柄关闭证明。

Root 终核确认产品清单 14 项、最终验证清单 11 项与 live 文件全部匹配；5 个精确 owned PID 均缺席，两个端口独立探测均返回 Windows 10061 拒绝连接。终核没有打开 SQLite 数据库。

## 保留的失败与修正

1. [首次启动拒绝](../../../.artifacts/r119-test-event-golden-20261022/selfcheck-b3754b9d8af646f38d2c58f0be84ed68/runner-failure.json)发生在 child 源绑定验证；Root 核对了已有 package pin 漂移并按当前真实源校正，未移除校验。随后[独立自检批次](../../../.artifacts/r119-test-event-golden-20261022/selfcheck-9ca405a18bf34bd99bdc6b28c0adc090/result.json)通过。
2. [受限首批 API](../../../.artifacts/r119-test-event-golden-20261022/api-dc9c66fc1cf74fdd926d81b228822259/result.json)为 5 passed、22 failed，22 项未进入测试调用；[q1](../../../.artifacts/r119q1-8a91/result.json)、[q2](../../../.artifacts/r119q2-6c72/result.json)单例尝试也失败，原始失败回执保留。Root 工具观察确认受限环境 hardlink 返回 Windows 错误 5；之后在沙箱外沿用同一 canonical guard 执行，[q3](../../../.artifacts/r119q3-94ce/result.json)和正式 27 项批次通过。不能将沙箱外执行描述成操作系统沙箱验证，也不能把旧失败改写为通过。
3. 历史回归 4 个 mkdir 被拒绝后，仅为两个旧测试 fixture 加入 `R119_TEST_STORAGE_ROOT` 显式入口；runner 清除继承的 `R119_*`，固定到本次 fresh `private/r119`，分别使用 `query-ownership` 与 `external-fact` 子目录。未设置时旧默认路径不变；没有改模块常量猴补、放宽 guard 或新建执行外壳。
4. UI 首批 [r119uihost-2c81](../../../.artifacts/r119uihost-2c81/receipt.json) / [浏览器结果](../../../.artifacts/r119browser-2c81/result.json)因集合操作 label 子串匹配产生 strict violation。第二批 [r119uihost-7b94](../../../.artifacts/r119uihost-7b94/receipt.json) / [浏览器结果](../../../.artifacts/r119browser-7b94/result.json)改成 exact 匹配后，又因 select option 文字参与 label 全串匹配而等待超时。
5. UI 第三批 [r119uihost-a6d2](../../../.artifacts/r119uihost-a6d2/receipt.json) / [浏览器结果](../../../.artifacts/r119browser-a6d2/result.json)已有 25 项先行检查，覆盖桌面和 390px 当前差异、冻结历史、集合撤回/重新冻结及事件撤销后的审核撤回；随后 QA 点击集合卡片后未等待动态详情可见就直接 count，误判唯一匹配数为 0。Root 只为 QA 增加可见等待，未改产品。
6. UI 第四批 [r119uihost-f290](../../../.artifacts/r119uihost-f290/receipt.json) / [浏览器结果](../../../.artifacts/r119browser-f290/result.json)已有 26 项先行检查；最终事件撤销令 workspace 重建、集合署名清空，QA 没有重新填写必填署名，点击禁用的提交按钮超时。这是该批失败事实，不能把此前已过检查拼为完整通过。
7. UI 第五批 [r119uihost-8e31](../../../.artifacts/r119uihost-8e31/receipt.json) / [浏览器结果](../../../.artifacts/r119browser-8e31/result.json)已有 29 项先行检查，最终集合撤回修订 #4 和历史 #1 已实际执行；随后 mobile readback 重入已展开的事件卡片，QA `open()` 仍按“核对本场成绩”按钮定位，而已展开按钮实际为“关闭场次”，因此定位失败、整批失败。产品列表包含 revoked 记录，不能归因为撤销事件不在默认列表。API/Web/browser 自然 0/0/3，`forced=[]`，端口关闭、产品与 QA 源稳定；该批 QA SHA 为 `def22faa251268b0b5ffd8d83475f4e3b21cd0e6eb8737625bb989ffd4c691da`。Root 随后修正 QA 对已展开事件卡片的重入定位和 `/api/v1` 精确路径比较，再执行全新 c54a。

第二个 UI 批次已有 17 项先行检查，涉及真实产品 HTTP 建立案例、独立 PDF 下载 SHA 核对、独立管理员审核、冻结指纹及 unknown 的未定显示；该批 API/Web/browser 自然退出码 0/0/3，`forced=[]`，端口关闭、产品源及 QA 源稳定。上述五个 UI 批次均已失败结束并保留；各自已过的 17/25/26/29 等检查不相加，**不构成完整 UI 验收**。最终通过结论仅来自同一全新 c54a 的完整 39 项，不以绿批改写旧失败。

## 未验范围及接手要求

- case revise UI、丢响应同 UUID 重放、切账户迟到响应没有本轮真实 UI 证据。后续若声明这些场景通过，须新增对应实际验证，不能复用 API/SDK/静审或集合修订结果补称。
- 早期及最终验证源清单分别保留，不把新 pin 倒灌旧失败批。同步 `docs/HANDOFF.md` 时，**R118 及更早正文必须原字节保留**，不通过重排或换行规范化重写尾文。
- 保留失败回执、既有 dirty 与历史账本；本轮未 commit/push。需要重跑时只用受审入口和全新私槽，不打开正常库或已保留验证库。

本轮全部供审 PDF、预期及桥测试均属于工程验收范围；不证明代表性真实 SKU、专业测量真实性、真人 Golden、来源许可真实性、真实 Provider/Responses、正常库升级、真实 PostgreSQL、原生宿主/设备或完整 V1。原 R74 材料仍不能因本功能升格为精确 SKU 正例；无需再次索要已确认缺失的 EPREL Key。
