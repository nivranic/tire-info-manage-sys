# 来源材料未确认请求停止采纳 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 本人可明确停止一条结果未确认的材料请求继续采纳；同一请求的迟到执行不能再登记原件或成功／失败终态，网络结果继续保持未知，不重抓来源。

**Architecture:** 原请求／结果账本旁新增不可变停止意图表。停止操作、成功采纳和失败落账在原 ingestion lock 内仲裁；只读状态复用原 UUID lookup 和历史，不增加查询旁路，不将超时或进程退出推为失败。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite／PostgreSQL迁移、共享 TypeScript DTO／SDK、现有 React 材料面板及受管私槽验证。

---

## 授权、依据与现状

沿用户完整V1持续实施、由当前agent继续及材料自主判断授权，使用brainstorming与writing-plans收敛。本计划在写入时尚未实施；随后Root独审冻结后直接执行，不重复询问权限／执行方式。不commit/push/reset/stash/clean，不另建worktree，不改未知dirty。正常与全部保留SQLite不打开，不启动默认API。没有EPREL Key继续独立工作。原C2 UUID9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0仍封存未确认，本片不迁移／重开其私槽、不POST、不换UUID重发。

原规格的原始证据优先、追加历史、失败任务管理及幂等要求（`docs/requirements/2026-09-26-tire-intelligence-original.md` 第42、73、188、646行）与最新HANDOFF第23行登记的未确认处理缺口是依据；原文未逐字列出本功能名，不能写成原文逐字要求。

两个ultra explorer已核：现有六个SDK方法与本人历史／原UUID GET、模块内未确认payload保留和ownerEpoch重挂都已存在。新工作不是补建恢复查询。`source_materials.py:124` 的processing_unconfirmed只是request存在／outcome不存在，20秒预算只包fetch，不能判定后续对象写入／提交是否仍在执行。现有同UUID同payload POST本来就只重放，不会继续执行。一般异常保留未知是有效合同，不能删除旧反例。

方案比较：只增加诊断文案不能处理操作者明确不再采纳的意图；直接补failed会混淆传输结果未知且仍须防迟到写入；采用独立停止意图及原锁内采纳屏障。停止只结束未来采纳资格，不证明socket已终止，也不证明已取得原件被删除。对象store.put可能已留下无引用对象；不清理、不把这些对象登记成document。停止不授权以新UUID重抓。

## 冻结合同

### 状态与停止记录

新增`SourceMaterialStop`／`source_material_stops`，主键和FK均为request_id，一条请求最多一条停止记录。保存原request fingerprint、实际actor_user_id／actor_session_id、规范请求payload及hash、operator、reason、stopped_at与完整记录fingerprint。ORM和SQLite UPDATE/DELETE/REPLACE保护；不能更新原request/outcome或补假捕获结果。

规范停止payload为`{expected_request_id,operator,reason}`，未知键拒绝，operator沿现有plain有界署名校验，reason为1–500字符有界单段说明，expected_request_id为规范UUID。停止URL中的原idempotency_key也须规范UUID。私有actor/session只用于服务端核对，不出公共view。

无outcome、无stop沿用processing_unconfirmed；无outcome、有完整stop显示新增`stopped_unconfirmed`。后者的completed_at/failure_code/document/receipt均为null；停止不冒充捕获终态。公共`stop`仅此状态非null：`{schema:'source-material-stop@1',request_id,idempotency_key,operator,reason,stopped_at}`。旧三态返回stop:null，旧DTO缺省按null兼容。成功receipt字节／hash语义不改。所有读取核stop原请求指纹／owner／payload／hash／时间；stop和outcome同时存在必须固定503 source_material_integrity_failed，不静默选择一方。

### 停止API与仲裁

新增`POST /v1/source-materials/requests/{idempotency_key}/stop`，200返回`{request:RequestView,effect:'stopped'|'already_stopped'|'already_terminal'}`。管理员守卫先于body错误，实际owner与管理员资格在取得原ingestion lock后重读；其他账户按404，未知owner拒绝，不用operator署名冒充认证主体。

查找本人原key并核expected_request_id、冻结request完整性。已有可信outcome返回already_terminal且零写入；已有stop同payload返回already_stopped，异payload固定409 source_material_stop_conflict。仅仍无结果且无stop才追加stop与署名原因审计并commit，返回stopped。当前policy目录删除／变更、TLS、对象库不可访问都不阻止停止；它只核冻结request元数据。停止提交回执丢失时固定503 source_material_stop_commit_unconfirmed，客户端只查原UUID，不自动重POST。

capture在fetch/store之后取得原锁、refresh并核真实身份／原request后，**在register_object、EvidenceDocument、outcome或received审计之前**读取stop。stop已胜出则返回其只读view且零DB采纳；不拿新body补原停止记录。失败finalizer rollback后也须在同锁内refresh／核request及stop，停止已胜出则不补failed outcome或failed审计。已成功／失败方先取得终态则停止不插入。数据库异常保持原失败边界，不能吞掉重试或禁用完整性检查。

### 迁移与兼容

新增031_source_material_stops，仅新建停止表、索引／三触发器及ledger。upgrade增加include_source_material_stops=True，并遵循现有历史门。R135旧030精确切片显式关闭新门，旧断言不扩成当前整库。新031历史夹具可复用已有护栏前驱链到030，再补字面020材料父表／旧request与failed／succeeded内容、索引和触发器；不以当前全量create_all冒充旧库。验证旧JSON／BLOB／fingerprint／DDL及全部旧行保留，重复迁移、ledger插入失败回滚、新鲜初始化。PG仅DDL编译时明确没有活PG验收。

`tests/version_registry.py`尾增031；独立历史trigger registry补停止三条；source_material_%旧6条改为精确旧6＋新3集合。旧vehicle_binary迁移测试目前静态漏列030，若覆盖时需记录原缺口并核030列delta／031表delta，不能冒称全部由031引入。

### SDK和实际界面

共享DTO增加停止请求／记录／结果和新状态，SDK只增加停止方法，复用原lookup。响应未闭合或stop错request/key、未知state、停止时夹带document/receipt／捕获完成时间，均拒绝显示停止结论或下载。

材料结果区只对本人processing_unconfirmed提供“停止采纳此请求”。确认区显示固定原UUID、署名与原因，解释“停止后不会再登记这次请求的原件；网络结果仍未确认，可能已留下无引用对象”。不提供新UUID重抓或自动恢复下载按钮。操作身份、取消、错误、finally与未知结果沿原ownerEpoch/controller门；停止响应丢失保留key并引导原UUID GET，不自动重复POST。已停止状态显示停止时间／署名／原因，原已成功／失败状态维持。完整页重载仍从本人历史找回。

## 任务、所有权与执行顺序

实施者不是独自在库；只改分配文件，不回滚他人编辑，额外旧文件修改先补before字节。基线目录`.artifacts/r136-source-material-stop-20261025/before`，R135完整HANDOFF备份207804B／18d0a1e38243dd481acd106dd377c1911fb523b941cd0ef7aae6406a45439bc7。

### Task 1：迁移、停止账本与状态核验（后端owner）

**Files:** `apps/api/tire_api/{source_material_models,source_materials,migrations}.py`、`apps/api/tests/{test_source_materials,test_source_materials_review,version_registry,historical_migration_support,test_source_quality_interest_migration}.py`；新`test_source_material_stop_migration.py`，必要时定向旧迁移断言。先写停止与迁移反例，由Root受管新私槽保存红批，后实现模型／状态及031，保存新绿批。Root仅注册新测试模块到原runner，必要的精确pin更新须独审，不改实际guard。

### Task 2：真实停止路由与迟到采纳屏障（后端owner）

先写私有实际API用例，再实现最小仲裁：本人／非管理员／跨账户404；expected id／重复异payload冲突；policy已删仍可停止；无对象读取／联网／Provider；stop row或request损坏503；stop+outcome双存在503；列表／详情／同UUID replay一致。注入停止INSERT或audit失败，核原请求无stop且无部分提交。提交后丢ack，再GET得到稳定停止记录，不能把保留未知当成功。

确定性并发至少覆盖：stop先提交→迟到成功、正常失败、取消路径都不登记object/document/outcome或received/failed audit；终态先提交→stop返回already_terminal、零停止行；两writer同停止→唯一行及一次审计。成功body可以已store.put，需区别物理对象与DB采纳。旧未知异常、请求／结果不可变、正常成功／失败与跨会话lookup反例保留。

### Task 3：共享类型／SDK／界面（前端owner）

**Files:** `packages/domain-types/src/{source-materials,index}.ts`、`packages/api-client/src/index.ts`、现有`packages/api-client/tests/source-materials.mts`／配置、`apps/web/components/source-materials.tsx`／必要CSS。先读apps/web/AGENTS及Next对应文档；不改普通上传／人工摘录／比较工作台。SDK按原tsconfig直接编译执行，不为别名改package.json。测新POST精确payload/编码ID/Abort/固定403404409503、一次transport与旧六方法兼容；再做Web／desktop／mobile noEmit。界面运行时核验在实际读取边界消费，不能只在测试重写无用validator。

### Task 4：Root实际验证与独审

Python固定项目venv3.12.10。仅原`scripts/run_api_worker_regression.py`，新短槽如`.artifacts/r136-red-a`、`.artifacts/r136-api-a`，保留ChildPolicy／审计／Job。示例：

```powershell
& apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/r136-api-a --targets apps/api/tests/test_source_materials.py apps/api/tests/test_source_materials_review.py apps/api/tests/test_source_material_stop_migration.py
```

默认沙箱hardlink限制已有证据，按既有require_escalated私槽边界执行，不改ACL／guard。新增模块注册后先runner自检。相关回归纳入documents／material transport／现有原件权限、schema startup、R135030迁移与当前Parser／Golden接点，依实际触达选target，不把旧294当新源码全绿。新鲜库／历史切片／真实部署升级分别记账。

生产Web构建复用现有冻结／监督／生成恢复链。新私库fixture用真实失败捕获留下processing_unconfirmed，由UI本人历史查询→确认停止→GET持久化重开→同UUID replay零抓取。再验停止提交丢响应后的GET、账户切换／迟到响应、403／404／503失败关闭及390／320布局；后端并发测试另证迟到采纳，不能用路由fulfill冒称React收到忽略AbortSignal的body。Root实际看截图、核自有PID／双端口与所有Job关闭。前后源pin绑定后才独审收尾。

### Task 5：报告、交接与回退（Root）

正式报告区分首次红批、夹具／工装失败、最终逐批执行、静审、截图与资源证据；不把独立批／参数向量相加冒称单次全量。HANDOFF新前缀保原207804B尾文。明确旧C2仍processing_unconfirmed且PDF未得、旧槽未打开；真实来源、专业精确SKU、真人Golden、真实模型、部署整库／PG、原生设备、完整WCAG／PWA仍未完成，完整V1保持active。

回退不能删停止记录或重新允许已停止请求采纳。可隐藏创建停止动作，但现有停止记录必须持续读取并在所有成功／失败采纳入口继续生效；不得回退为不了解031的新旧二进制混跑，不drop表、不回写原请求／结果。无后台自动到期、重试或补发。
