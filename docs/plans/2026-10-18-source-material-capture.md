# Licensed Source Material Capture Implementation Plan（R72）

**Goal:** 实现固定来源策略的 PDF 原件捕获，保存实际 HTTPS 响应实体字节、许可声明和不可变传输凭证，并从现有原件界面完整重开，服务真实专业测试对象与精确 SKU Golden。

**Architecture:** 可信本地配置的不可变进程策略快照；请求预留与终态两张追加表；网络期间不持数据库事务/摄取锁。成功的对象、既有 EvidenceDocument 与传输凭证原子登记。与 R71 人工声明及 R70 事实摘录合同分开，不提升身份/性能证据等级。

**Tech Stack:** FastAPI、SQLAlchemy、aiohttp、PublicResolver/RobotsPolicy、SQLite 私库；TypeScript SDK 与三端共享 React 界面。

状态：实施合同冻结，尚未验收。继续用户原 Goal，使用 brainstorming / writing-plans 收敛后在当前工作树执行；不提交、推送、reset/clean/stash 或启动正常库。基线 `.artifacts/r72-source-capture-a0f445f16990410b99bc68ef75bf1b77/baseline.json` 已核 R71 的892源码、293展开dirty、20文档、111证据和4配置原字节。

## 1. 需求依据与方案选择

原规格要求专业来源证据、原始文档/引用、合法许可、可追溯与代表性人工 Golden。现有 captures.py 将已解码文本再次编码UTF-8，不能称HTTP原始实体字节；research.py实际管理保存比较和偏好。R71只能证明供审PDF上的人工转录工作流，不能证明实际取得来源。

选择专用的有许可PDF捕获路径，复用现有对象仓库、文档和安全DNS基础。另两方案是扩展所有旧parser采集器（影响广且不能补专业材料许可）和接受任意URL（不能保证固定来源范围）；本轮均不采用。旧文本捕获保持其原语义。

真实专业材料尚未指定；已向用户询问URL与许可依据。默认没有可捕获来源，不能填入未经确认的网站、伪造专业Golden，或把合成验证写成真实来源接入。

## 2. 固定来源与许可合同

新增 `material_source_policy.py`。只从 `TI_SOURCE_MATERIAL_POLICIES_FILE` 指向的可信本地JSON加载；默认空。文件≤256KiB、最多16项、严格未知字段/重复键/重复ID/类型检查，配置错误fail closed且不回显原配置/路径。app创建时加载不可变快照，不热重载；变更或撤销策略需重启，旧pending绝不恢复联网。

文件schema固定`source-material-policies@1`，每项：

- `policy_id`：1–80 ASCII slug；`title`、`publisher`：1–160有界文本；`edition`（≤80文本或null）、`published_at`（ISO日期或null），未知明确保留null。
- `source_reference_url`：引用页；`download_url`：实际初始PDF地址；`redirect_urls`：0–3个精确允许目标。引用页与下载地址关系是操作者配置声明，不是系统核验结果。
- 全部URL仅公网HTTPS域名/443，不含凭据、query、fragment、控制字符、反斜杠或混淆authority。禁止IP直连和本地名，实际连接仍严格公网DNS验证；不通过拒绝后归一化来接受不同地址。
- `rights`：`rights_holder`、`basis`、`license_url`（合法HTTPS引用或null）、严格布尔`store_original:true`、`workspace_reopen:true`、`quote_identifiers:true`、`provider_use:false`、`export:false`。许可URL仅引用，不额外请求；配置声明不等于平台授予许可或系统认证版权。
- `policy_fingerprint`由服务器对完整规范策略计算，所有请求引用精确指纹；浏览器不能提供下载URL或改写许可字段。

## 3. 网络与字节合同

新增 `material_source_transport.py`，复用PublicResolver/RobotsPolicy但不改旧transport，以免改变已冻结parser digest。

- 仅GET；TLS正常证书/SNI校验；不继承代理、不用cookies/auth、不调用浏览器或子进程；每次实际socket解析都经公网校验，无第二次未校验lookup。
- `Accept-Encoding: identity`且aiohttp `auto_decompress=False`；非空/非identity Content-Encoding拒绝。保存的bytes是HTTP transfer decoding后、没有内容编码的实体body；不宣称保留TLS/HTTP头帧或chunk framing。
- 只收完整200、application/pdf、`%PDF-`、1–8MiB；Content-Length提前校验并在流读取时再限额；中断/超时不发布部分PDF。
- 请求总预算20秒、连接4秒/读取8秒、全应用最多2个捕获在途；单host间隔至少2秒并尊重robots更大间隔，忙/限速直接明确失败，不无限排队。
- 单次请求不自动重试；除显式外层循环外，也关闭并反例验证当前aiohttp版本默认的幂等连接失败重试，force_close本身不作为禁重试证明。
- 每个实际host先查对应robots.txt，≤64KiB。200使用原RobotsPolicy判定；404/410明确记缺失；其余错误fail closed。固定目标、每次重定向均检查精确allowlist和该host robots；最多3跳，循环/未知目标/不许可目标拒绝。
- 凭证冻结初始/最终实际URL、完整有界跳转链、各robots URL/status/body hash/size/判定/间隔、起止时间、PDF hash/size/MIME/encoding。成功非空robots原bytes也作对象保存并在凭证读时校验；合法200空robots用空bytes的SHA256与size0在凭证中完整表示并重建空规则，不因通用对象仓库不收空对象而拒绝来源；404/410缺失仍用null hash区分。不把响应未知headers/cookies写入记录。
- 不做PDF语义抽取、真伪认证，不调用模型/外部解析器；既有Parser8秒/2并发/CPU5秒/384MiB预算不变。

## 4. 追加账本与权限

新增 `source_material_models.py`：请求预留表与唯一终态表；020迁移、非Web初始化导入、测试版本registry同步。ORM及SQLite UPDATE/DELETE/REPLACE保护、metadata after_create与显式迁移幂等一致，PG仅在有实际运行时才声称PG验收。

请求唯一键`(actor_user_id,idempotency_key)`；UUID及完整规范payload hash绑定稳定user.id，operator只是有界署名。预留冻结策略/许可、会话、请求时间。终态唯一`request_id`，成功冻结document_id/原文hash/metadata hash/传输凭证和fingerprint，失败只存固定安全code。

新请求先校验管理员/精确当前策略并在短事务内预留，提交后才联网。幂等查找先于当前策略查找：同key同payload只返回既有状态、不同payload409，同账户异会话可找回；其他账户不能读该私有请求。并发loser只读，不联网。请求有预留但无终态显示`processing_unconfirmed`，不声称仍有活进程，也不自动重试。重新捕获必须显式新UUID，新document和receipt，允许共用内容寻址对象；不得按raw_hash给旧上传文档补来源标记。

网络结束后重新核稳定账户/管理员资格，再原子登记EvidenceObject、EvidenceDocument和成功终态；文档source_url明确取配置的source_reference_url，实际下载URL独立保存。对象发布先于数据库提交，失败最多留下未引用对象，不能返回成功。取消尽力记安全失败；提交结果未知必须lookup，不自动重新联网。历史按冻结策略重建，与当前目录是否仍有该policy无关。

凭证读严格重验所有相关对象/原文/文档元信息/请求与终态fingerprint；损坏503，不返回当前版或数据库副本。既有手工上传EvidenceDocument的metadata与R71桥hash不改；新增独立凭证只按document_id查找，传输记录不提升R71的operator_supplied/unverified、conditional_reviewed_transcription上限或R70事实摘录门禁。

## 5. API 与客户端合同

路由前缀`/v1/source-materials`：

1. `GET /policies`：workspace目录、完整公开策略与fingerprint、默认空状态和边界提示，不联网。
2. `POST /preview`：管理员；`{policy_id,expected_policy_fingerprint}`，返回policy/can_capture/blockers/notice，不联网。
3. `POST /captures`：管理员先于body解析守卫；`{policy_id,expected_policy_fingerprint,idempotency_key,operator,rights_confirmed:true}`。返回RequestView及`replayed`。
4. `GET /requests?mode=history&offset=…`：登录者自己的请求历史，分页。
5. `GET /requests/{idempotency_key}?mode=history`：稳定账户lookup，未知404，与当前policy无关。
6. `GET /documents/{document_id}?mode=history`：工作区成功来源凭证；纯上传没有则404，已存在但损坏503。

`RequestView`至少包含`idempotency_key`、`state`（processing_unconfirmed/succeeded/failed）、`policy`、`policy_fingerprint`、`requested_at`、`completed_at`、`failure_code`、`document`、`receipt`、notice；未完成/失败的document与receipt为null。成功receipt固定schema`source-material-receipt@1`，包括第3/4节冻结字段、`transport_verification:https_transport_observed`、`content_authenticity:unverified`、`source_reference_relation:operator_configured`。字段最终以同名TypeScript DTO和后端序列化严格对齐。

新增 `packages/domain-types/src/source-materials.ts` 和SDK方法/消费测试。新增三端共享 `source-materials.tsx`/CSS，在 `evidence-documents.tsx` 原件面板接入：选择固定来源、展示引用页/下载地址/许可与限制→人工确认→预览→捕获→SHA/size下载→独立凭证/历史重开。research.py/研究比较界面不承担原件捕获。默认空来源解释如何配置，不显示可输入任意URL的表单。

UI在同稳定账户保留原payload/UUID，丢响应只lookup并允许同UUID查询；换账户清理可见状态，不能沿用旧payload。明确pending未确认与失败；显式新捕获才换UUID。原件下载逐字节校验SHA/size，不冒充阅读确认或来源真伪。成功后刷新现有原件列表，使新document可被R71人工桥选择。

## 6. 文件所有权与验证

- 后端owner：上述4个新Python模块、main/db/migrations/version_registry最小注册、`test_source_materials.py`和私库runner。先红例后实现；反例覆盖策略/权限/精确URL/编码/大小/robots/跳转/响应中断/幂等/并发/丢响应/角色变化/不可变SQL/对象损坏/迁移幂等。
- 前端owner：新DTO/SDK消费测试/新组件与CSS/evidence-documents接入（必要时workbench最小注册）；不触碰后端或R71桥代码。
- 独立review owner：新增独立反例文件和R72/review目录，检查真实生产transport边界与账本，不修改owner文件或复用同一断言造全量。
- Root：计划、基线、工作区typecheck/相关构建、私有HTTP/真实React验收、配置恢复/服务退出、报告/交接/风险和最终清单。所有owner并行协作，保留未知dirty，不回滚他人修改。

测试必须清理宿主TI/DB配置后再import，显式GUID私有SQLite/对象根；正常库、外联和子进程护栏，source transport用受控内存responses验证真实client逻辑，不能启动本地服务器绕过公网限制。真实HTTP/浏览器验证可用项目合成PDF和注入受控transport，但必须区分真实生产transport单测与没有真实公网来源的私有工作流。

最小相关回归覆盖documents、source_access/robots、R71桥、迁移与现有研究UI；workspace类型、SDK公开消费和三端前端构建；如没有真实材料URL/许可则不能声称真实专业材料或Golden验收。失败原样保留，阶段计数不累加为一个全量。构建/运行生成文件按原字节恢复，关闭自有服务/页面，历史R71清单不改写。

## 7. 完成边界与回退

本轮工程通过也不关闭来源许可/真实来源样本、代表性对象↔精确SKU人工Golden、B条件化性能解释、C专用AI推荐与其余V1 Gate。尚待用户具体材料，不用fixture代替；正常库020保全/迁移与原生设备仍分开。

回退按本轮差异人工处理，不reset/clean整树；新追加记录作为历史保留，不删库/删表或改写旧原件。清单只标识字节，不是归档/备份。
