# 第72轮：固定许可策略的专业材料原件捕获

**结论：固定来源 PDF 捕获的后端、SDK、共享界面及私有 HTTP/React 工作流已实现并取得限定验证。真实专业材料、适用许可、代表性 Golden、B/C 与完整 V1 仍未完成。未提交、推送或发布。**

本轮从 R71 的有限人工证据桥继续，新增原件取得通道；不重做人工桥，不改变旧来源 transport/captures/parser，不解除 R70 含测试 AI 包的服务器事实摘录限制。开始前已核对 R71 的892源码、293展开 dirty、20文档、111证据与4配置。原需求仓内副本与用户指定原件保持字节一致。

[冻结实施合同（验收前原字节）](../../plans/2026-10-18-source-material-capture.md)是独立反例的22个冻结输入之一，全文保持运行时字节，顶部“尚未验收”记录的是冻结时阶段。当前终态以本报告、最新交接卡及最终清单为准；不改旧报告或重写旧回执来追认验收。

## 实际交付

- 新增 `material_source_policy.py`、`material_source_transport.py`、`source_material_models.py`、`source_materials.py`，必要的应用/模型/迁移注册以及 **020_source_materials**。正常数据库未执行020。DTO、SDK和 `source-materials.tsx/.css` 接入既有原件面板，成功后刷新文档列表供 R71 使用。
- `TI_SOURCE_MATERIAL_POLICIES_FILE` 指向可信本地 JSON，启动时读取一次，默认空、不热更新。配置顶层是 `{schema:"source-material-policies@1", policies:[...]}`，API目录响应才使用 `items`。每项冻结引用页、初始 PDF 和最多3个精确跳转地址、出版者/版本/日期及权利声明。保存原件、工作区重开、身份短引文要求 true；Provider/export 保持 false。见[配置说明](../../SOURCE-MATERIAL-POLICY.md)和[空配置示例](../../source-material-policies.example.json)。
- 仅固定公网 HTTPS/DNS/TLS，无凭据/query/fragment，不继承代理/Cookie；逐host检查 robots。身份编码 `Accept-Encoding: identity`、`auto_decompress=False`，拒绝重复/不支持的编码及 MIME 歧义；不启用 aiohttp 隐式重试。只接完整200/PDF及最多8MiB，总20秒、连接4秒/读取8秒、应用最多2并发、逐host至少2秒。保存的是 transfer decoding 后且未内容解压的实体字节，不是线路帧。
- 请求预留和唯一终态分为两张追加表，以稳定 `user.id + UUID` 幂等。网络期间无DB锁；同UUID只查询已有状态，不重新联网，未确认不能解释成后台仍活。发布前重核原账户/管理员权限，成功时原子登记对象、新 EvidenceDocument 与凭证。
- 按 **document_id** 关联来源凭证；相同字节的旧人工上传不会被补认来源。文档 `source_url` 是配置引用页，实际 initial/final URL 与跳转另行记录；引用页与 PDF 的关系属于配置声明。合法200空 robots 用空 SHA/size0记录，不注册0B对象；404/410用null hash区分。读取校验原件、robots与冻结记录，损坏明确拒绝。
- 界面展示许可、引用页/实际地址、原件SHA/大小及未核验边界；预览/确认、捕获、响应丢失找回、换账户隔离、校验后下载与精确历史可用。捕获不认证出版物、许可或内容，不自动建立SKU声明/审核、不升级R71等级。

## 实际验证（各阶段分别计数）

证据根：`.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77`。以下是各自实际执行的结果，不能相加为全量测试或独立业务场景数。

| 范围 | 实际结果与入口 |
|---|---|
| 后端目标回归 | **156 passed，0 fail/error/skip，exit0**；38输入运行前后及当前一致，外联/子进程/正常库尝试0。[报告](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/backend/REPORT.md)、[最终回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/backend/final-headers-host-b17a23a990d14db6876b2588de689afe/verification.json) |
| 非Web初始化/迁移 | fresh进程未import main；私有019→020、两表六触发器、20版本重复初始化与旧marker保留；PG仅DDL编译。[回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/backend/nonweb-final-8940238b3f07458687c6afcb1966f5a9/verification.json) |
| 独立安全反例 | **148 passed，0 fail/error/skip，exit0**；22输入稳定，外联/子进程/正常库尝试0。包含真实aiohttp 3.14.3请求循环与HTTP解析器的单次尝试、重复/冲突/非法Content-Length及TE+CL拒绝。[独立报告](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/review/REVIEW.md)、[审计回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/review/independent-review.json) |
| SDK/公共类型/UI | SDK **12/12**；公共类型及专用UI noEmit通过，8 owner源稳定。[交付](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/frontend/FRONTEND-DELIVERY.md)、[回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/frontend/FRONTEND-VERIFICATION.json) |
| 工作区/前端构建 | workspace typecheck、Web/Desktop/Mobile前端构建四阶段exit0，296相关源稳定；7生成文件按原字节恢复。[构建回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/frontend-build/verification.json) |
| 默认空来源 | 真实私有HTTP/React **9条断言**通过，空目录无捕获表单、无来源请求或新文档。[终态](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-empty/empty-ui-final.json) |
| 真实私有HTTP | **43条断言**通过；固定来源/确认/权限、原字节与凭证、幂等、失败不重抓、同hash旧上传无凭证、R71复用不提升等级。[API终态](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/api-qa-final.json) |
| 桌面React | 实际 **1442×934，27条断言**通过：已提交HTTP后注入丢响应→换账户清私有pending→回原账户恢复UUID→GET找回，仅新增一个文档、不重抓；列表刷新、历史；同长度坏SHA拒绝Blob下载，恢复后完整校验并发起下载。[UI终态](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/ui-qa-final.json) |
| 窄屏React | 实际 **390×844、320×740各12条**布局/已有凭证读取断言通过；无整页横溢出、可见控件≥44px。不是手机完整捕获E2E或原生设备验收。[390](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/mobile-390-result.json)、[320](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/mobile-320-result.json) |

真实的是生产 HTTP 端点、React 和生产来源 transport 控制流；上游为内存 aiohttp session 的受控响应。未真实访问公网专业来源、DNS/TLS、许可或专业 Golden。合成 PDF 可打开，浏览器原生截图已目视检查，无落盘截图文件。最终私有夹具 documents=3（2次捕获、1次人工上传）、requests=4/outcomes=4（两成功、两失败），facts/snapshots/event revision各1，厂商事实未改、guard及Provider调用0。见[夹具终态](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/fixture-final.json)。

## 实际发现、修正与失败保留

- 独立反例证明重复 `Content-Encoding: identity` / `gzip` 可绕过首值检查；产品现读取全部编码头并拒绝重复编码/MIME，红例及最终156/148两组回归通过。真实aiohttp请求循环还验证了禁用隐式连接失败重试，断连仅一次发送。
- 沙盒阻止不可变对象 `os.link`，保留失败；同护栏私库宿主执行通过，未削弱对象仓库校验。后端曾使用不存在的测试文件名、独立runner参数ID过长/误用session表、真实parser夹具参数遗漏等，均保留原失败并修正工装。源在运行中变化的154/143通过阶段不作为冻结终态。
- 浏览器首次请求390宽度实际为501；随后emulate重载清除了测试window变量，一次读取前提失败。保存原始结果及说明，恢复合成文档标识后从实际lookup重开，最终精确390/320通过。未将501结果冒称390，未为此改产品。

## 资源、保全与接手

原Root已实际观察两私有API HTTP shutdown200及session exit0；Next经Ctrl+C退出，Python wrapper KeyboardInterrupt exit1，不能写作exit0。宿主回执显示8972/3373无监听；测试页17关闭、原空白页12保留。3运行配置按字节恢复，7构建文件另有恢复回执；GUID私库及对象根保留取证。见[进程记录](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/process-history.json)、[端口记录](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-final/host-ports-stopped.json)、[配置恢复](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/runtime-config/restoration.json)。

[聚合回执](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/completion.json)已静态核对所有阶段当前输入与结果、恢复和资源终态、R71的111历史证据原字节。独立[关闭复核](../../../.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/closure-review/REPORT.md)另完成38项证据一致性检查，没有重跑产品、浏览器或端口探测，明确进程/页面关闭属于Root观察。当前机器清单入口为本轮根 `verification-final.json`；由其实际生成与根外独立审计决定封存，不覆盖原清单。SHA清单仅标识字节，不是文件归档或私库备份。

**后续顺序：**取得用户指定的真实专业材料引用页/PDF及适用许可，配置固定策略后验证一次真实来源捕获；人工建立 TestEvent↔精确SKU 的代表性 Golden，保留委托/执行/发布者、未知/冲突与原场次条件；在证据支持下分别冻结 B 同场条件化解释与 C 专用AI推荐。缺少样本不取消这些需求，也不能把当前工程通道记为 A 的全部完成。

正常库020保全/迁移、PG运行、新原生设备、真实Provider、完整当前API/Worker全量与其余V1发布Gate本轮均未验收。原Goal保持active。最新接手入口为[交接卡](../../HANDOFF-2026-10-18.md)。
