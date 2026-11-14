# 个人车库与保存比较验收

2026-11-15，实施基线f66c4c0。原规格将车库与保存比较列入个性化，并优先支持个人账户。本阶段复用036持久会话owner及不可变创建记录完成归属过滤。[实施计划](../../plans/2026-11-15-personal-garage-comparisons.md)

## 归属与兼容

- Garage由revision=1的actor_session_id确定创建者，保存比较由根记录actor_session_id确定创建者。同账户聚合其持久会话范围，后续编辑者沿原历史保留。
- 旧共享记录归创建者私有。该策略由agent根据现有不可变创建证据制定。新匿名资料沿036首次认领规则处理，历史未绑定会话沿036迁移状态读取。
- 列表、计数、分页、详情及全部修订入口校验本人范围。离线选择先过滤本人车库，再读取原件和计数，显式他人ID形成阻断省略项。
- 新车库离线context及member reason采用actor。Web、共享DTO、SDK、Rust和Java接收actor及历史local_workspace，已保存旧包继续按其冻结字节读取。
- Web沿AuthProvider的ready、ownerEpoch和ownerSignal管理车库、历史、编辑、轮胎分配、车型配置复制及比较窗口。身份重验时销毁旧状态并拒绝迟到响应。

数据库版本为036，179张模型表，PG合同包含180个关系。归属证据使用已有创建行和会话owner。

## 最终验证

| 验证 | 实际结果 |
| --- | --- |
| 受管API 12模块 | 269通过，0失败、跳过或不完整，867输入稳定 |
| Parser子进程 | 16次，全部exit 0且已回收 |
| 全前端工作区类型与Web生产构建 | 通过 |
| Web、桌面与移动端JS测试 | 分别68、22、24项通过 |
| Web离线合同 | 13项通过，使用仓库冻结旧原件并覆盖actor变体 |
| 当前API四领域离线包 | 8项HTTP检查通过，5个member、9个document、80,921字节，Web读取及garage reason一致 |
| Rust完整库测试 | 173通过、0失败、4项默认忽略 |
| Rust生产者原件专项 | 当前API包与仓库冻结旧包各1项通过，覆盖安装、重开、搜索及原字节 |
| Android生产验证器 | 已安装JDK21与API36编译验证器及直接依赖闭包通过 |
| 生产Web浏览器 | 正常登录、同账户恢复、跨账户隔离、编辑／历史窗口销毁、延迟列表／详情／保存结果，共13项通过 |
| 非拥有者PG18.3／TLS正常HTTP | 8项通过，创建、所有读写入口、显式他人导出、共同编辑形状、修订冲突、退出、恢复及重启 |
| 资源关闭 | 9条服务记录、11个进程ID、8个端口、两组PG临时口令和TLS私钥已核对 |

PG隔离库直接补入旧共同编辑形状，4个业务表的6条原行逐项保持一致。该验证覆盖历史数据形状和读取归属，实际旧部署库迁移及生产权限仍需部署验收。@4合同摘要为39744825954155e4f7da1072d43c1519837791027f80644dcd6b8c2bd11b8f7a，部署目标须根据自身catalog、源码及向量索引声明重建批准合同。

API的12模块覆盖garage、research、offline packs v1/v2、车型原件消费者、offline sync owner、auth、query ownership、offline updates、offline migration、reports及recall reports。当前API原始包摘要为0a8f7cb856e7e4535e56bfa9fa2bae45713222c5c778ac1604bbbde2219c7cd1。

## 原始失败与验证边界

- 红批3项复现跨账户读取／修改和车库导出。首批126项有122通过，3项旧共享预期已按个人需求更新，另1项Parser超时的原诊断保留。最终16次Parser正常退出，原间歇超时的OS根因继续待查。
- 第二批177项有127通过、50失败。对象存储硬链接发布的原始PermissionError为WinError 5，提升权限后的同内容探针成功，最终受管回归全部通过。生产存储实现沿已有原子发布机制运行。
- 首批Chrome的crashpad子进程启动失败。提升权限后的新隔离浏览器批次13项通过。Rust沙箱全量曾有3项文件操作失败，包含Windows错误650，隔离临时目录下提升权限复验后173项通过。
- Web离线旧加载器在ESM循环依赖中产生未完成顶层await，改为复用现有真实模块URL加载器。夹具改从仓库冻结Android assets读取。移动端测试补齐现有主题包装及身份事件预期，原失败回执保留。
- Gradle包装器下载停滞时已停止本轮进程。Android新增instrumentation测试仍待构建及设备执行，生产Java编译结果单列。Rust全量的4个默认忽略项涉及OS凭据写入和独立生产者夹具，四领域原件项已单独执行新旧包两次。
- 浏览器、PG及离线生产者采用合成轮胎和私人记录，真实模型调用为0。Native安装、真机跨账户、设备密钥、生产远端、多用户负载、WCAG与完整发布Gate继续待验。

## 回执索引

回执、原件、私有数据库、脚本和截图位于Git忽略的.artifacts目录。新clone须重新运行相关验证。

| 回执 | SHA-256 |
| --- | --- |
| personal-records-20261115-final/result.json | 373af4fd8886a4a177f8040eca4d83e97960f0769dcd1a08b26be4d1e06700f6 |
| personal-records-20261115/resource-audit.json | b5c828e98b87c367c140388e5b4e9354f8a212f2245cf6714ff10eb5eb7230a0 |
| PG最终report.json | 61cfbe61459af18a29c2ac4415f31547edaf496c5e20ef37229c1c661dbc53ff |
| Web最终report.json | 4f1f0b9206807cc22b7473b3ffee4beeee8d8dff35e9a89f149d78a88ef0b616 |

阶段入口与完整V1余项见[个人资料交接卡](../../AGENT-HANDOFF-2026-11-15-PERSONAL-RECORDS.md)。
