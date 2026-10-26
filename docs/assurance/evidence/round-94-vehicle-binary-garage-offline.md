# 第94轮：车型二进制车库与离线用途闭包

2026-10-20。本轮完成车库来源复制、已复制资料读写和服务端离线新分发的窄用途门。最终取首批19＋第二批7＋第三批1＝**27个逻辑唯一目标的分批覆盖**（新18＋旧9），历史5个setup失败和1个call断言失败全部保留。完整V1仍未完成，按用户指令继续实施。

实施依据：[正式计划](../../plans/2026-10-20-vehicle-binary-garage-offline.md)、[私有提案](../../../.artifacts/vehicle-binary-garage-offline-4a8127c9df65/proposal.md)、[两项P1 addendum](../../../.artifacts/r94-garage-offline-review-sol-7d31b0a9e6f2/review.md)与[冻结候选独审](../../../.artifacts/r94-garage-offline-review-sol-7d31b0a9e6f2/candidate-review.md)。

## 改了什么

- **车库：**首次from-fitment先核完整consumer capsule和`local_structured`，只从已核payload选标准/选配fitment；新binary引用保存精确receipt三键。list/history、PUT、set_tire、state及no-op在返回资料或append/audit前核引用。个人profile允许编辑，但`basis=user_entry`不清除仍在的来源。旧无receipt引用不伪回填，纯手工及真实legacy保持原shape；JSON null按Python值判别。
- **离线准备：**在创建garage context、选择其轮胎/车型member和生成documents前核export；拒绝整个候选context及派生内容。显式ids/refs为blocking omission，默认范围可省略受限项并保留无关合法内容；返回计数与实际contexts一致。prepare保留201＋omission/can_confirm及原有planning元数据/审计，blocking计划不存内容对象或发布包。
- **旧冻结产物：**联合冻结PDF/S2/member身份与当前Snapshot的binary/固定首代身份判别。context-only旧包和无content_hash的blocked preview仍过门；有对象时先核对象及preview结构，再核双方用途。get_plan、首次confirm、download不能绕过。旧bytes/receipt/hash不改，不重解析或借最新receipt改写；descriptor及同key历史重放仍仅返回元数据。
- **兼容与投影：**source恰八键、vehicle最小投影、原件/documents全文排除及`raw_included=false`保持。真正legacy冻结分支不重读body或选择新receipt，晚body损坏保留原保证；garage-only缺源且无法自证legacy则身份未知并503。旧base只供内部diff/semantic digest，不返回/合并旧payload，允许新scope完全移除受限资料后准备合法替代包。

完整性/来源绑定为503 `vehicle_raw_integrity_failed`，冻结对象/结构损坏为503 `offline_frozen_object_unavailable`，本地结构与export用途分别为403固定码。真正HTTP拒绝不新增revision/audit/pack。`local_structured`与`local_original_read`独立，Provider/export仍由原helper硬拒；私有local-only fixture不授外部权利。服务器拒绝新分发不能撤销已经落设备且不再请求服务器的副本。

## 三批实际账

| 批次与actual | collected / protocol | setup | call | teardown | actual child |
| --- | ---: | --- | --- | --- | --- |
| [首批](../../../.artifacts/r94-t-780caf0d4b32/result.json) | 27 / 27 | 22通过、5失败 | 22通过 | 27通过 | 15：13 exit0、2 exit125 |
| [第二批](../../../.artifacts/r94-f-91e4c0d6a8b2/result.json) | 8 / 8 | 8通过 | 7通过、1断言失败 | 8通过 | 8：全部exit0 |
| [第三批精确单例](../../../.artifacts/r94-g-65a10ed82c49/result.json) | 1 / 1 | 1通过 | 1通过 | 1通过 | 1：exit0 |

首、二批runner3/pytest1，第三批runner0/pytest0、passed=true；均自然结束。累计36次collected/protocol、31次call（30通过、1历史断言失败），另有首批5个setup失败。最终互斥选首批排除第二批8例后的19例、第二批7例和第三批1例，共27唯一目标，所选实例均有完整三阶段。首19含旧9＋新10，后7＋1补齐新18；不是一次27全绿，也不是161模块全量回归。首批10 targets/3模块，第二批5个精确函数展开8例，第三批只选1精确case；161仅manifest总数。

**首批失败原因仍unknown。** 五项停在新测试的live断言，原始错误码未保留；观察到的2个exit125不足以替五项补造具体原因。第二批只新增一次runtime调用的安全原语诊断，没有重试、延长8秒runtime或放宽Guard/ChildPolicy。8份诊断均为一次调用、error_code=none、pid_present、exit0、reaped和is_live；后续成功不代表已诊断或根治首批失败。

**第二批只修测试断言。** explicit export测试误把preview预计算`content_sha256`当成持久化对象；旧R93与当前生产表达式同为`None if over_bytes else content_sha256`，persist函数AST原样。只修该case，核plan.row.content_hash为None、EvidenceObject计数及行不增、未发布且confirm409；其他14测试函数、fixture和TRACKED不变。第三精确单例通过，安全诊断也是一次调用、无错误、exit0/reaped/live。三生产、runner、正式计划均未因红项更改。

## 源码、资源与历史保全

每批nodeids/reports/JUnit及阶段计数一致，687源码首尾同，第三批687与最终live同。相对R93恰4变＋1增、682保持、零删；跨三run只有新测试两次变化：首版36404B、诊断版39179B、最终39588B。原版本及失败run整份保留，见[实现基线/原字节](../../../.artifacts/r94-impl-fbf06d45f62c/baseline.json)、[首批保全](../../../.artifacts/r94-parser-diagnostic-fixture-b2a379c737e2/preservation.json)与[第二批保全](../../../.artifacts/r94-explicit-plan-assertion-a91bde2616a9/preservation.json)；精确pins交机器清单复核。

合计24个actual child＝22 exit0＋2历史exit125，每批live0、resources_closed=true、metrics0、非selfcheck拒绝0、正常DBfalse、真实Provider/receiver0。三批独立after进程采样均为0；Guard证据限于Python审计/wrapper边界。第二、三批[8份](../../../.artifacts/r94-meta-f-91e4c0d6a8b2/safe-parser-observations.json)及[1份](../../../.artifacts/r94-meta-g-65a10ed82c49/safe-parser-observations.json)安全诊断只保存原语和pid_present，不保存实际pid/argv/环境/原件正文。

S2在源码清单外，三批各有独立before/after采样，均同历史3240150B原件；这与fixture每次pre-use核验分别列证。R38独立采样和runner保全均保持25374720B历史pin，未打开该数据库。独立meta位于`.artifacts/r94-meta-780caf0d4b32/`、`r94-meta-f-91e4c0d6a8b2/`、`r94-meta-g-65a10ed82c49/`。

三入口先[整文件保全](../../../.artifacts/r94-impl-fbf06d45f62c/entry-baseline.json)再只顶部追加，完整R93及更早suffix逐原字节保留。R93最终v2和旧seal均保持原大小/SHA，见[核对记录](../../../.artifacts/r94-impl-fbf06d45f62c/r93-seal-preservation.json)，未重封旧状态。本轮[机器seal入口](../../../.artifacts/r94-close-d7c49021e6a8/verification-final.json)以实际生成和独立核验为准，此文不预填其hash或验收状态。

## 剩余Gate与下一步

真实材料是历史S2在私库离线重放和隔离actual child/receipt；mapping、deployment、directory、local-only许可为合成fixture，不等于在线capture、正式来源许可或外部真人Golden。首代fetch/ready关闭、requires_source_verification及生产原件/结构化pending保持，Provider/export仍false。未改vehicle_raw、SDK、Native、模型、迁移、Guard/ChildPolicy或旧REVIEWED SHA，未提交推送。

下一为[SDK受管入口提案](../../../.artifacts/sdk-raw-evidence-managed-entry-83b5d6f392c042ca/proposal.md)与[R95独审](../../../.artifacts/r95-sdk-entry-review-8065222857c740c0aba8fbe08ce69098/review.md)，目前仅已审建议，未实施/运行。须刷新旧提案的`.mts`与runner pins并经独立Gate取得真实SDK运行证据。SDK/UI/Native保存前fence、PG/正常库保全升级、正式许可、完整PDF及V1验收仍开放；完整V1仍未完成，按用户指令继续实施。
