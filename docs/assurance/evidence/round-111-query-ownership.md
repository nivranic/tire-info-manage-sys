# R111：可信新查询的不可转移owner回执

2026-10-21。v3独立新run的32主测试、38 subtests全部通过，Root与终态独审接受工程归属及合成SQLite范围。V1仍active，provider/export=false；完整外读功能尚未完成。

## 产品与验证范围

新增8列owner回执、服务器actor捕获与新query原子创建。owner/session只存不可变快照，无User/session FK；query/audit引用RESTRICT。SQLite原生UPDATE/DELETE/冲突INSERT与ORM guard保护历史；PG交付含TRUNCATE的DDL，归属写读未启用，原PG内部查询照常无回执、外读拒绝。

仅可信新HTTP在线入口捕获服务器session；锁内重核当前User、session绑定及expiry，网络前同事务提交QueryRun+既有审计+owner回执。匿名/后台/consent已有run/历史不补绑，旧auth不改。require_query_owner只核owner/query/audit/User，不认证key、许可或正式Verification/Snapshot。

27个owner向量覆盖真实auth endpoint直接调用的换绑/logout/sweep/删户、同名新户不继承、匿名与历史拒绝、坏绑定、原生/ORM不可变、pending写、真实双Session锁与026精确升级/幂等/回滚。两项真实QueryService.execute保留observe和lock_ingestion：一项在来源paused前停、fetch=0；另一项仅到受控fake unavailable，另一连接核三写durable、服务无事务并取得BEGIN IMMEDIATE，未执行真实网络或Parser。这不是HTTP/middleware/cookie验收。

三INSERT及before_commit故障由另一连接核零行；after_commit普通Exception及QueryOwnershipError核三行已durable并返回commit_unconfirmed，同ID重放不重复。两个P2已补：重放另核fallback_policy、提交开始后的Exception含QueryOwnershipError统一安全码。BaseException取消/中断语义保留，KeyboardInterrupt/SystemExit未测试、不宣称转换。

旧10文件仅必要注册/签名及精确迁移兼容。5个compat向量为025到026两项和固定023/声明变体的024隔离三项；pure024 upgrade(include_vehicle_binary=False)的134/130边界不动，显式当前尾部精确增加025+026，不用宽subset。固定五fixture、旧receipt保持。旧vehicle正常启动pytest仅静审未运行，旧G1a/治理向量未重跑；不把本轮与旧22/旧3拼一批。

## 三次运行分别保留

- v1：Root96e2ae→320b4d exit1，bootstrap前置RuntimeError，0主/0sub、32均未启动；1323首尾不变，自然child1。[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/query-ownership-verification-20261021/run-0abd925d69c24e7f995321f680dabf36/receipt.json) SHA fe4ac6b1903a292a84688e08f4d91cd00f3a2117d402c8ad5c1f08484dc79cbe。不补具体失败分项或实际链。
- v2：Root6718e4→cff66b exit1，32主中29通过，38sub通过、3个legacy AuditDenied；32fresh/0remain、1329首尾不变。[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/query-ownership-verification-20261021/run-3488d3b791c448eb86622df13406312d/receipt.json) SHA 6efc76dda2e96d6a452313d4e1272280fb0fea72be1af2ce5e7948b74630971b。限定system wrapper未恢复影响aiohttp，不能记全批通过。
- v3：Root8abaff/session72096→2ca98d exit0。[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/query-ownership-verification-20261021/run-8d8af3973afc4080ae98061fa1e7a5a5/receipt.json) SHA c83cbcfe7e7227bb232fc6f07de1f2df352284ff62eddd5e52021b7b89c60ae4。产品和新测试自v1未变；新工装恢复原system并核既有缓存，不回写两次失败。

## v3实际证据与限制

Root9760ea独核32=27owner+5compat，38sub全部成功，fail/error/skip/issues均0。expected/started是同一32唯一集合，started/completed同序；不称三列逐序相同。33fresh/0remain，现场t无目录。自然child0，无timeout/forced，stdout18242B/stderr0。

[pins](E:/Mix/project/tire-info-manage-sys/.artifacts/query-ownership-verification-20261021/key-pins-v3.json) SHA 1b3cc2b2648b88a88660ac98df1e967fadd98b6dafc928ffae4a830654e710b2：1334关键输入首尾及Root live匹配，非完整closure、不含HANDOFF；文档应用后另核。终态独审bcca18只读receipt及现场t接受，没有重跑或重复1334全量hash。

19个bootstrap判据真；预载builtin Winreg对象/全属性保持，三个受控consumer不获模块，_wmi/psutil absent；原system及缓存四判据真。7个精确probe各1；files4=NUL3+proc1预期拒绝，其余denied0；SQLite连接275、hostname1。保留精确环境探测适配、局部SQLite插桩、NUL错误翻译、AMD64/SYSTEMROOT/PYDANTIC_DISABLE_PLUGINS受控环境及独立依赖准备，不能当作自然WMI或正常应用恢复。

Python hook不是OS sandbox，cached import盲点、hook前native/registry活动未知、capture无硬内存限仍保留；未证明全部系统资源关闭。实际PG仅DDL编译/静态guard，真实HTTP、正常库、材料/法律许可、Provider、设备及完整V1均未验收，未commit/push。

下一步在同一owned事务内合并当前许可、owner与正式Verification→QueryRun→Snapshot校验，再接G2a与外部路由/SDK；不从当前session猜补历史归属。HANDOFF原118471B、SHA c120a472a80a998aa927e00e39009f006e3c0b30afb7486706cbc1dd9ca56378须逐字节保留为suffix，CreateNew before、非空原子backup与独立读回分别保全；R109/R110历史报告不改。
