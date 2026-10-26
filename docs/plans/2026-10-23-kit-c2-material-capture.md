# R132 KIT C2 单次真实材料捕获与原页核验

2026-10-23。承接已收尾的 R131，继续完整 V1。用户已授权 agent 自行选择公开材料与保存依据，并明确无 EPREL Key、继续独立工作。本项不依赖 EPREL 或模型密钥。

## 目标与依据

取得 *Dynamic measurement of the fluid pressure in the tire contact area on wet roads* 的 KITopen 原件，沿既有产品路由留下单次捕获、原 UUID 查询、下载字节与来源凭证；成功后核原页许可、作者、DOI、尺寸、方法及可准确转录的直接实测值。结果可以是有证据的来源失败；不自动换源重试。

固定引用页 `https://publikationen.bibliothek.kit.edu/1000123313`；唯一 PDF 入口 `https://publikationen.bibliothek.kit.edu/1000123313/86536961`。许可研究见 `.artifacts/material-c2-research-20261021/C2-RESEARCH.md`：Springer DOI `10.1007/s41104-020-00056-z` 标 CC BY 4.0，KIT 声明出版社版本。保留作者、许可链接、来源、无改动说明及 Continental 资助关系；PDF 内第三方例外仍需取件后检查。

BB/SB/CR 为实验花纹，候选尺寸245/45 R18不等于完整商品身份。不得推成 Continental 商品、精确 SKU、独立委托测评、商品排名或真人 Golden。若原文只有曲线且无可准确摘录数值，记录缺口，不估读造成绩。当前策略只允许原件保存、工作区重开和标识引用，Provider/export=false；本项不创建 TestEvent、SKU link 或 Golden。

## 已知失败与入口选择

旧 C2 固定批 `.artifacts/material-c2-execution-20261021/run-01981026e6f14b67b956ee1318f75dd0` 已 exit3，停在导入前 child guard，capture POST/原 UUID GET均0、network未观察。不能称站点拒绝，不能覆盖、回填或原样重跑。

R115/R118 已证实固定 Python3.14.8 与依赖在受控入口可运行；这依赖审定 import/WMI/NUL fallback，不证明自然 WMI 修复。复用 R115 `run_lazy_app_v4.py` 的真实导入、lifespan 和进程内 ASGI 方式，R114 `run_fact_page_tests_v2.py` 的 Guard 与 `selfpipe_capability_v2.py` 原字节保留。3.14依赖缺 httpx/httpcore，不为了 TestClient 新装依赖或混入3.12扩展。

R118 整体 runner 的空材料目录、拒绝全部出站及只注册 POST 不适用于此项。只参考其 helper 重绑；制作新固定批薄入口，显式 `create_app` 新私库及真实 `MaterialSourceTransport`，不启动默认 app、Uvicorn 或 Web 服务。

## 实施范围与分工

- Worker 独占 `.artifacts/material-c2-resume-20261023/` 的新 runner、launcher、策略副本和冻结准备；Root 负责本计划、冻结审定、唯一正式执行、原页阅读及最终报告。独立 ultra reviewer 审查能力差异和最终证据。
- 新 UUID、新目录、新私槽，数据库名沿 Guard 合同 `fact-page.sqlite`；仅本批新私库可读写。原 C2/R74及正常/保留数据库不打开；旧工装与产品代码不改，不commit/push/reset/stash/clean。
- 冻结实际当前产品、runtime/deps、复用 helper/Guard/selfpipe 与新工装/策略的输入。不照搬旧产品数或哈希；漂移须停下核实，不能自动接受。
- Launcher 使用 PS7、隐藏子进程、清洁环境，不继承密钥、代理或用户配置；只在内存处理临时注册密码和会话，不输出 Cookie/Set-Cookie/密码。精确超时与退出回执保留。
- 原 Guard 能力委托点只扩展 KIT 固定主机 DNS及已验证公网443 TLS；子进程、其他外网、正常库继续拒绝。保留产品 PublicResolver、robots、TLS、PDF类型/字节上限及20秒总期限。拒绝 robots不可用、不允许的跳转或非PDF；空redirect列表只是禁止跳转，不声称已观测零跳转。Python Guard不是OS sandbox。
- 静读发现真实 `FileObjectStore.put` 以临时文件加 `os.link` 原子发布PDF/robots，而旧 Guard 一律拒绝 hardlink。新批仅为这个真实调用点增加私槽对象目录内、摘要匹配、目标不存在的精确发布能力；其他link/rename及文件拒绝原样保留。原 Guard 文件不改，内存适配与调用/路径/字节约束须独审后才可执行。
- ASGI消费者仅增加固定业务所需 GET/POST、JSON请求及有界PDF响应，保留完整响应结束检查与内存会话；capture等待覆盖产品20秒期限，其他响应有限时/大小。

## 单次执行与验收

1. 静态核对新入口与旧业务顺序、策略及能力差异；AST/PowerShell解析不导入产品。独审无阻断后冻结新输入并执行一次。
2. 新私库真实注册 → policies → preview → 一次 capture POST → 同 UUID history GET。响应丢失或失败仍只查询原 UUID，不追加 POST或换 UUID重发同一次执行。
3. 失败保留原结果、错误代码与允许的有限诊断，不伪造成功状态或正式下载原件；可能存在未引用对象，不删除失败现场。前置失败、原 UUID 查询404或未确认状态均如实记录。成功则经产品 content 路由取件，核PDF标记、MIME、长度、SHA及receipt、原 UUID和document对应，再重开document receipt。
4. 记录lifespan/DB关闭、来源网络观测、自然退出、输入稳定及清理结果。汇总终态不冒充全部OS资源证明；失败或中断保留原件，不拼批为绿。
5. 成功后用PDF文本提取及原页渲染核作者/DOI/版权、第三方例外、物理/印刷页码、尺寸、试验条件、方法与匿名身份。仅离线审阅，不把自动提取标为已认证事实或真人审核，不调用模型。
6. 写正式报告与HANDOFF新摘要，保留旧交接字节尾文；明确实际原件取得/离线审阅与精确SKU、TestEvent录入及真人Golden的界限。

## 完成范围

本项不包含全套UI重跑、真实AI、EPREL、正常库迁移、PostgreSQL、原生设备及完整V1完成。R131已过检查不重跑。若捕获因实际来源策略失败，记录实际终态与下一可独立工作，不绕robots、身份或代理限制。
