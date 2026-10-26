# 第68轮：来源更新后的人工处理适用性通知（2026-10-18）

本轮补齐第67轮明确保留的 `derived_manual_applicability` 缺口：来源采纳实际新增FactVersion后，将当时仍有效的人工覆盖或字段撤销变为待复核这一转换，保存为独立派生原行并产生相关私有通知。原人工决定保留，来源事实不被人工值覆盖。七类兴趣条件不变，支持域由八个增至九个。完整推荐、信息流、真实来源/平台矩阵及完整V1仍未完成；Goal保持active。未提交、推送、迁移正常库或发布。

## 实现与精确合同

[本轮计划与冻结合同](../../plans/2026-10-18-interest-manual-applicability.md)依据原规格第186–208、213、227–237行。本轮没有更改原始需求或第67轮封存回执。

| 合同项 | 最终值 |
|---|---|
| domain | `tire_curation_validity` |
| 原始evidence kind | `tire_curation_applicability_event` |
| action / before state / after state | `invalidate / applicable / needs_review` |
| changed_field | `curation_applicability` |
| model / table | `TireCurationApplicabilityEvent / tire_curation_applicability_events` |
| migration | `018_interest_manual_applicability` |

- 新适用性账本独立于ManualFactRevision：一条actual新fact对同variant/source至多一条派生记录，聚合同次受影响字段。`after_fact_id`唯一，`variant_id/source_id/revision`联合唯一；before/after fact和触发Verification有真实FK，ORM禁止更新或删除。018不修改旧行、不回填旧派生事件或通知，正常库未升级。
- 只有最新字段头为manual_override/revoke且base恰为旧fact才失效；clear、旧base、已needs_review、其他variant/source不纳入。整fact的其他业务字段改变也能使人工处理失效。query不构成overlay边界；普通304无新fact不失效，跨query的304若实际协调出新fact则会失效。仅正文/元数据/目录变化且无新fact不触发；目录review与overlay适用性仍是两套规则。
- `affected[]`冻结人工原行ID、人工修订号、field/action、before/after status及公共原行指纹；`manual_revision_watermark`冻结当次variant/source最大人工修订。派生revision单独递增，后续同时间人工动作不能改写旧事件，不伪造人工revoke或自动恢复覆盖。
- `binding.before/after`分别冻结snapshot、source、各自query、URL/raw_hash、身份合同、parsed_variants/member hash与locator、实际fact ID/version/hash、snapshot member版本及验证ID/status/time，并保留成员presence。前后query允许不同；合法304 actual v3/member v1分别校验。本次事件时间来自新fact/触发Verification，不能沿用旧snapshot观察时间。
- before为旧source facts叠加watermark内当时仍有效的各字段头；after为新source facts，受影响项待复核。零、显式null、缺席严格区分。changed_paths只列真实effective facts差异及 `curation_applicability/state`；新source值恰等于旧manual值时不伪造facts变化。原轮胎来源事件仍仅解释source差异。
- 原行reader复用 `GET /v1/interest-evidence/{kind}/{record_id}?mode=history`，新增kind返回 `interest-original-evidence@1`、`local_workspace/local_snapshot`及kind/id/entity/revision/fingerprint/record/evidence。公共digest来自重新读取的派生原行，并核对关联人工原行、watermark和两侧来源依据；缺失404 `interest_evidence_not_found`、不符409 `interest_evidence_mismatch`，不返回最新替代记录或通知副本。旧四类kind含义不变。
- 新账本、已采纳snapshot/fact/change/Verification、目录账本、兴趣事件及通知在原事务内；插入或通知失败一起回滚，不另commit。合法旧侧身份证明缺口允许保留indeterminate派生事件且不通知，不借当前身份补证，也不阻断原合法采纳。多来源不拼AND，旧车型关系不会因目录重入、SKU恢复或身份clear被新事件复活。
- 共享类型、SDK和三端共用面板已接入新域、新筛选字段和原行分支，区分人工修订与派生修订。原人工决定和前后完整来源原文按冻结引用重开；两侧query分别核对，actual/member版本分别校验。Auth ready、ownerEpoch、AbortSignal与完成时主体核对保持；代码防护不等于已完成全部迟到响应浏览器验收。
- 保存兴趣和history读取仍不补发、不创建账本、抓取或调度。能力表移除已交付derived缺口，来源拒收/隔离、仅验证元数据继续单列。同cookie session_scope资料归属政策沿用既有范围，不新增永久账户隔离承诺。

## 分阶段验证

各阶段按实读回执独立记录，不能相加或借旧轮次覆盖本轮源码。目录中的pytest.log与JUnit保留原结果；源码稳定只指各次明确列出的文件。

| 阶段 | 实际结果 | 回执与范围 |
|---|---|---|
| R67修改前核验 | 854源码、233展开dirty、11文档、178证据、194链接、15风险owner通过，staged/unmerged均0 | [r67-before-r68.json](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/r67-before-r68.json)；原需求字节一致，旧回执只绑定改动前快照 |
| 后端预实现 | 3失败，0通过 | [before](../../../.artifacts/review-r68-backend-ef09aa88b542438da38e1397103b9577/before-1d756a5e40174ce38b312d1a98ac89b6/verification.json)；新selector未接 |
| 后端首集成 | 3失败，0通过 | [integrated](../../../.artifacts/review-r68-backend-ef09aa88b542438da38e1397103b9577/integrated-a4bc99336c5c47a4acb3abf49c122a5d/verification.json)；fixture前后query对应不同query-local SKU，详见下文 |
| 后端同scope工装修正 | 3通过 | [same-scope](../../../.artifacts/review-r68-backend-ef09aa88b542438da38e1397103b9577/same-scope-2f3d3d4a947e463db8a21ee2f9f6b172/verification.json)；仅修正fixture查询 |
| 后端受影响回归 | 69通过，0失败/错误/跳过 | [regression](../../../.artifacts/review-r68-backend-ef09aa88b542438da38e1397103b9577/regression-4aa889ae42ba4f53af2840168775ac08/verification.json)；new3、curation、interest_events、interest_review、interest_migration及core旧Verification重建节点；18具名文件稳定（14产品、4测试） |
| 独立早期合同红灯 | 1失败、22 deselected | [early](../../../.artifacts/review-r68-applicability-7354fd9fe11943449cc8df22ad25bcdf/early-e60e6aa246354f4087adc4f349f836ec/verification.json)；new changed_field尚未接入，创建兴趣422 |
| 独立首批 | 23通过 | [first](../../../.artifacts/review-r68-applicability-7354fd9fe11943449cc8df22ad25bcdf/first-1af07f97e2bd4eacaf396704aa1a68d2/verification.json)；尚无后加的三类旧关系链与future-only用例 |
| 独立新增目标 | 4通过、23 deselected | [chain](../../../.artifacts/review-r68-applicability-7354fd9fe11943449cc8df22ad25bcdf/chain-9ebd5d9f261244f78e29a61923e1cdf0/verification.json) |
| 独立最终封存 | 27通过，0失败/错误/跳过 | [sealed](../../../.artifacts/review-r68-applicability-7354fd9fe11943449cc8df22ad25bcdf/sealed-fc351583c2a84f3fb5712dfe519a4a91/verification.json)、[独立报告](../../../.artifacts/review-r68-applicability-7354fd9fe11943449cc8df22ad25bcdf/R68-REVIEW.md)；31具名产品/测试/helper/runner文件SHA与长度稳定，写报告时再次核对无漂移 |
| SDK兴趣合同 | exit0 | [sdk](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/sdk-verification.json)；公共类型/注入合成transport探针，不是后端集成 |
| 工作区类型检查 | exit0 | [types](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/types-verification.json)；现有workspace脚本 |
| Web前端生产构建 | exit0 | [web](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/web-verification.json)；不是PWA运行时更新验收 |
| Desktop前端生产构建 | exit0 | [desktop](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/desktop-verification.json)；TypeScript/Vite资产，不是Tauri安装包 |
| Mobile前端生产构建 | exit0 | [mobile](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/mobile-verification.json)；TypeScript/Vite资产，不是Android/iOS验收 |
| 私有API最终流程 | 83/83断言通过，done=true | [browser-api-final.json](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-api-final.json)；实际生产API/QueryService，输入为合成来源 |
| Chrome桌面最终UI | 30/30断言通过，done=true | [desktop-final](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-ui-desktop-final.json)；1440×1000，无整页横向溢出 |
| Chrome手机视口最终UI | 30/30断言通过，done=true | [mobile-final](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-ui-mobile-final.json)；390×844，无整页横向溢出，不是原生设备 |

[前端总回执](../../../.artifacts/runtime/manual-applicability-frontend-7e7aa04d059f458485adcb9d90a75f8f/verification.json)为passed、issues0，五阶段均exit0、16项相关源hash无漂移且封存时复核一致；本轮实际修改4个前端/合同文件，记录22项制品和13项证据文件（含before.json）。Web静态页5/5，PWA生成17项allowlist资源。生产构建阶段7个生成文件逐项核对恢复原字节（含原本相同者），不是7处产品修复，也不证明用户已取得PWA更新。五阶段、制品或证据文件数量均不是业务测试数量；16项不是全仓覆盖。Desktop/Mobile保留既有大于500kB chunk及独立artifact输出目录不清空提示，不将编译等同浏览器或原生验收。

独立27项覆盖整fact/多字段头、等值只报状态、0/null/缺席/revoke、无新fact304和元数据、目录规则独立、clear/旧头/重新核验、跨来源AND、跨query304 actual/member分离、并列时间watermark、两类事务故障、合法旧证据缺口、三类旧车型链、future-only/历史只读、四类原行及关联材料篡改、018全旧行/schema保留/幂等/DDL回滚、真实SQLite唯一/FK/ORM追加保护和PG表/索引DDL编译。PG没有实际连接或运行。

## 私有API与浏览器验收

Root使用独立SQLite/objects/bundles和四行合成目录，通过实际治理写入与QueryService完成首次450→300的两个人工头聚合失效、0→0只报适用性状态、其他字段触发、重新人工核验后再失效、clear排除、普通304/仅正文无新fact不失效，以及跨query304实际fact7/member5的失效。旧人工450原行与旧派生原行在后续来源更新后保持精确；R/ZR与未审车型不能猜配，新兴趣/历史读取不补发。API脚本与[83项回执](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-api-final.json)分别保存，不是83个独立业务场景。

两种视口各自运行同一组核心流程：检查三类代表性派生事件的冻结条件/effective facts、独立派生修订与原人工修订，显式重开原人工450，以及三事件before/after共六侧完整来源原文；当前来源已更新为334，旧材料仍按冻结引用显示。跨query及actual/member版本分别展示；等值事件不制造UTQG差异。Root查看了[桌面图](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/desktop-applicability-dialog.png)、[手机明细图](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/mobile-applicability-dialog.png)和[手机顶部图](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/mobile-applicability-dialog-top.png)，[布局/目视记录](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-ui-layout-visual-review.json)保留测量与审阅范围。两视口不是60个独立场景，也不是原生宿主、完整账户切换或迟到响应运行时矩阵。

## 失败与工装保留

预实现后端3红及独立早期1红均保留，反映新合同尚未接完，不应改称已实现代码的新业务缺陷。后端首集成fixture先用model+size创建，再用size-only刷新；未声明namespace的旧编码按query-local规则正确分成不同SKU，因此既不失效也没有可注入失败的通知。只把fixture改为同查询scope后3项通过，没有放宽身份规则、改写产品纠错语义或取消回滚要求。最终独立组没有发现需要再次修改产品的问题。

本轮API/UI断言没有失败。首次Next开发入口误写为 `apps/web/node_modules/next/dist/bin/next`，ready前报MODULE_NOT_FOUND，未获得live session handle；[原日志](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/web-dev-host.log)保留，**没有记录该次exit code**。改为解析monorepo根node_modules入口后成功，[成功日志](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/web-dev-host-2.log)另存；这是工装路径修正，不是产品失败或产品根因修复。手机模拟会重载文档，Root在最终运行前重新注入public frozen references；截图内联返回后按原字节落盘，没有使用browser filePath覆盖。

## 资源停止与配置恢复

[最终fixture](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/runtime-host-1/fixture-final.json)记录10次tire operation、6兴趣/6修订、31事件、29通知、8目录记录、4适用性记录及6条原人工修订。4条派生记录和29条通知只是合成流程累计表行数，不是独立场景数。API fixture记录external network/parser child/Provider/normal DB attempts均0，`normal_database_used=false`。

[runtime-closeout.json](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/runtime-closeout.json)记录API shutdown HTTP200且实测exit0；成功启动的Next开发进程主动Ctrl+C后exit1。[宿主端口复核](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/host-ports-stopped.json)确认8958/3370均无监听，测试页13关闭，保留运行前已存在的空白页12。私有fixture存储留在本机，排除于交接allowlist。

浏览器开发阶段next-env、tsconfig、sw三个生成配置按备份SHA/长度核对恢复，[恢复回执](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/browser-generated-restored.json)逐项保留。此范围与生产构建阶段7生成文件恢复分开记账，不能相加为10个独立修复。[Root目标检查](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/root-targeted-checks.json)记录API/UI脚本语法与fixture AST检查通过、scoped diff exit0、生成配置无残留diff；[差异检查日志](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/root-diff-check.log)保留。

## 证据边界与后续

后端各阶段外网、child、正常库尝试均0，最终69组loopback61；独立最终组相应尝试均0、loopback24。loopback为Windows asyncio/TestClient运行时自唤醒，计数仅覆盖对应runner护栏下的测试执行；API fixture零计数也只覆盖该API进程，不表示整个浏览器、Next或工作站无外联。私有SQLite、objects、bundles在导入前设置，AI/Embeddings关闭。故意raw SQL篡改只作用于各项私有测试数据库。Parser墙钟8秒、并发2、CPU5秒、384MiB没有放宽。

正常数据库/对象、真实来源/模型、完整API/Worker回归、PG运行、原生安装包/设备/凭据权限/生命周期、PWA离线更新、生产迁移/签名/发布及全部V1 Gate没有由上述限定证据验收。旧R67文件和清单继续保留历史身份，不用于冒充变化后的当前快照。

本轮主清单入口：[verification-final.json](../../../.artifacts/r68-manual-applicability-8f4317b509ec402c9555f52c758d4f50/verification-final.json)。清单生成与独立核验由Root另行记录；本文分项结论来自上述实读回执，不声称已独立核验最终主清单。机器清单不是完整工作区归档、私有数据备份或产品Gate替代品。后续继续其他相关事件/跨域治理、完整推荐/信息流、代表性专业样本与Golden、来源/平台矩阵和生产发布Gate，完整Goal保持active。
