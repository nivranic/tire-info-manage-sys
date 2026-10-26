# R114：G2e owned 事实分页 HTTP/ASGI 与 SDK 有限验证通过

2026-10-21。G2e 分页依据 [.artifacts 合同 v3](../../../.artifacts/fact-page-contract-20261021/G2E-PAGE-CANDIDATE-v3.md)，SHA-256 f60702fabb3f44dff2af561c8c6808798989e2de5ed84a269676c5b6f76975f6。新增 GET /external/v1/tire-facts 与 SDK tireFacts；原单项 GET /external/v1/tire-facts/{variant_id} 和 tireFact 保留。独立 SDK 批次与 Python v2 进程内 ASGI/合成私库批次均在各自限定范围通过，Root 与独立审查已核对正式回执。R114 不是完整 V1、正常库、实际 PostgreSQL、真实许可或网络监听验收；provider/export=false。

## 分页合同与改动范围

必选 source_id、query_id、verification_id 各一次，limit 为 1–20、默认 20；cursor 为固定 owned Q/V/S Snapshot 窗口的服务端签名不透明令牌。它含精确 13 字段、首次签发起固定 900 秒，不能代替 fresh Bearer/key/owner/许可检查。初页不可用统一 404；经签名和绑定验证的续页若窗口、治理或许可变化，统一 409，过期亦 409；key 失效优先 401，缺 scope 为 403，非法参数或 cursor 为 422。窗口每页重建全部最多 256 个候选，合法 hidden 成员仍接受输入完整性与预算校验并进入闭包；不追 identity merge target、不泄露 hidden 数量/原因，也不返回部分页。全 SQL 结果行数不得超过保守计费行数，后者至多 8192；总历史、物化 JSON、投影及最终 1327104B 页容量分别受合同界限约束。服务端在同一个 SQLite BEGIN IMMEDIATE 内完成 fresh 核验、全候选、页与编码后提交；外层 60/min 预约是另一事务，不把整个 HTTP 流程说成单事务只读。

产品接线涉及 external_fact_reader/governance、query_ownership、identity_contract、专用 external_fact_cursor、external_fact_http/external_api；SDK 新增独立 page DTO、严格解码与 tireFacts 方法。没有 schema027、持久窗口表或正常服务迁移。本轮文档使用 [外部事实 API](../../EXTERNAL-FACT-API.md) 说明客户端选择器、重取与边界。

## SDK 独立正式批次

Root 唯一 SDK v2 回执：[receipt.json](../../../.artifacts/fact-page-sdk-verification-20261021/run-580092570d9b4cb1ae9c485aad8d4bfb/receipt.json)，14119B，SHA-256 ecb55227226ccc53427f2e664521c2bec9c3d924b64224ef6a3e8aa75f79cf68。脚本 verify-sdk-v2.ps1 SHA-256 de896e1ee8925b3bd494de65d94be91e8eac5ed954c6c00a60cc9d4eb9a84b1e；39 项 key pins SHA-256 a5ebc0b41ec72e1aded2473d28f608398227b4c986f73e61478048ec84be24aa，Root 当前 live 无漂移，但非完整传递依赖闭包。8 阶段全部 exit0、无 timeout/forced、child stopped：4 个类型检查，4 个合成 runtime；分页 189、单项 136、旧 external 59、inventory 47 检查。runtime stdout 分别 119/115/113/112B，stderr 各 183B 非空，Root 核对 16 份 stream 的长度与 SHA。SDK 只验证客户端合成响应合同，real_http=false、database=false；SDK v1 候选未执行，不记失败或通过。

## Python v1 完整失败批与 v2 独立成功批

v1 唯一 run 的 [receipt.json](../../../.artifacts/fact-page-verification-20261021/run-38d2ce91551e4d6cb13a56db9c4d5ec9/receipt.json) 为 93888B、SHA-256 a6c3af79930e9821502caf7f5f17aefd4e5644fb57d61b0502198ac698e79aaa；1335 key pins SHA-256 aaea07b3d7c79906e4360c1464a5fab4435e8bf4a5dfcc318f31c7fde71d1696，保留原样。66 主测试均开始和完成，其中 48 pass、1 fail、17 error，57 subtest pass；整批 failed，自然 child exit1，无 timeout/forced。17 error 均为私库 seed 的成员数量变化触发 quality 隔离 import 被 Guard 拒绝；1 fail 是旧 HTTP 副本仍断言分页根路径不存在。局部 72 requests/responses、2 非空 page200、10 非空 fact200、1484 SQLite 与 59 fresh/0 remain 不能拼成通过。

v2 只在新工装副本修合法 R/ZR 查询 seed、关联 foreign query、分页根路径缺参数预期 422、批次标识及 SQLite fixture 名称；产品/SDK和旧 v1 源、pins、失败回执未修改。Root 唯一 e40291/session36302→3fd9f7 exit0，正式 [receipt.json](../../../.artifacts/fact-page-verification-20261021/run-03c03c4b6c24494982717be3d0df54a4/receipt.json) 37776B、SHA-256 9e6c2321bf4ba916135bcd536bfeb9bc5a6830aa33d435c5cf736b8004731925。freeze4a9fab exit0；key-pins-v2.json 451285B、1345 唯一项、SHA-256 0c227fd89b73bff7254dfd91d5d56ac41b8a04745ded3436d97faf165c150fe9。Root 与独立审查均核对 1345 项首尾/live 零漂移、v1 全部 1335 项被 v2 覆盖且当前零漂移；两批仍分别记账，pins 均非完整 import closure。

v2 的 66 主/57 subtest 全 pass，fail/error/skip/issues 均 0；pins expected、receipt expected/started/completed 四个 ID 序列同序且各 66 唯一。66 项包括分页核心 7、分页 HTTP 20、旧 R112 reader 向量新副本 25、旧 R113 HTTP 向量新副本 14；旧 R112/R113 原测试文件未导入，不声称旧全 suite 重跑。124 ASGI requests=responses、23 次非空 page200/85 items、10 次非空 fact200、102931 响应体字节，HTTP 管理成功 0。1755 SQLite 连接、59 fresh/0 remain、现场临时目录为空；stdout29127B/stderr0，自然 child exit0，无 timeout/forced。19 bootstrap 判据全真、7 个环境 probe 各一次、files 仅 4 次预期拒绝，其它 denied=0；受审 selfpipe 实际为单次 stdlib_loopback_fallback，window1/new socket2/bind1/connect1，关闭与五项诊断全真。Root 5bf1fc 及独立审查实际终核 ACCEPT，不等于另一次运行。

## 验证边界、保全与后续

Python 只覆盖进程内 FastAPI external middleware、路由、owned reader 与合成私有 SQLite；direct service/query/governance fixture 不是 HTTP 管理验收，http_management_successes=0。registry/fetch 受控合成，未验证真实材料、法律许可或 Parser。无 TCP/HTTP 监听、完整 main.create_app/lifespan/CORS/全部 middleware、正常数据库启动及迁移、实际 PG、浏览器、Provider、设备或完整 V1。Python hook 不是 OS sandbox，native/cached 活动盲点与 capture 无硬内存限延续；selfpipe 使用受审真实 loopback socket，不能称零 socket。R112 v2 service.transport_cache OperationalError 根因仍未知、未修复。

原 HANDOFF 为 125724B、SHA-256 9cfbd70539ff498b63044d178dbc30066a02e3f2e34d979682dcbb9115abe638；文档候选把它完整作为新前缀后的原字节尾文，并以 CreateNew 保存原文件。正式应用须单独校验候选、原文及 File.Replace 生成的非空真实 backup，不把文档回读算成产品验证。回滚分页时只撤除新列表入口/SDK 与 page 接线，保留单项接口、既有 025/026、key 撤销和许可历史。V1 继续 active，provider/export=false；本报告不代表 commit/push。
