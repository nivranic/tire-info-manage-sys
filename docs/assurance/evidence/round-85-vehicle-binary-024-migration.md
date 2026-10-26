# 第85轮 车型023→024私库迁移与回滚

日期：2026-10-19。**门2的SQLite受控迁移/回滚切片已实现并在合成历史私库验证。**`024_vehicle_binary_raw`已加入版本链；普通启动遇到需要重建的旧库会在`create_all`前拒绝，显式私库入口才执行重建。PostgreSQL旧库受控迁移仍未实现，也没有私PG实例验收；整个PDF功能及完整V1 Gate保持开放。正常数据库没有连接、启动或升级。

沿用[第84轮基线](round-84-vehicle-023-baseline.md)与[冻结合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)§2/§4。正式前驱只从`apps/api/tests/fixtures/vehicle_binary_023/`五个静态文件加载：它们来自冻结当前023源码和合成历史私库，不是正常库备份，也不是真实保留的历史生产库。不用新`Base.metadata`制造旧库，不从升级后schema学习旧expected。

## 四阶段真实结果

| 阶段 | 固定回执 | 实际结果 |
| --- | --- | --- |
| g2a首次五模块 | `.artifacts/r85-g2a-6e429b7c1fd0/result.json` | 202唯一条目：141通过、61失败；其中60为setup失败，call为141通过/1失败；pytest1、runner3，原红保留 |
| g2b迁移及R38精确节点 | `.artifacts/r85-g2b-87ac310e6d4f/result.json` | 迁移83项＋R38精确节点1项，共84/84通过；setup/call/teardown各84通过，pytest/runner0 |
| g2c必要十一模块 | `.artifacts/r85-g2c-f2e8a013b64c/result.json` | 230项：228通过、2失败；setup/teardown各230通过，call228通过/2失败，pytest1、runner3，原红保留 |
| g2d两处fixture修正后reparse | `.artifacts/r85-g2d-e5ab47c1f902/result.json` | reparse34/34通过；setup/call/teardown各34通过，pytest/runner0 |

g2a的60个setup失败发生于静态fixture资产写入，尚未调用迁移；后续只读诊断定位Windows私根过长（最长264字符）。修正仅把前驱根缩短为`tmp_path_factory.mktemp('v') / 'f'`，不改145资产字节或Guard。另一个R38 call失败在原runner仅保留通用错误；后续源码静查发现DDL把新列放在旧表级PK/FK之后，SQLite语法不允许。修复将两新列插在首个表级约束前，保留原列/约束顺序及suffix；实际语法回归和g2b证明修复后行为，不把静态推论倒填为首红观察到的具体错误码。

g2c两失败均为旧reparse负向fixture先被新增本地`byte_count = length(raw_body)` CHECK拒绝。仅改两处合法损坏构造：`capture_bytes`同时设`raw_body=b'x'`和`byte_count=1`，保留旧hash/对象；legacy损坏改为等长字节，保留旧hash。原503、durable failed、candidate为空、Parser不调用、幂等及不回退DB断言全部保留。g2d验证修正后的34项，不改判g2c原红。

最终绿色证据**分批**覆盖12个独立模块、313个唯一目标：迁移83＋g2c除reparse的10模块196＋g2d reparse34。g2b的R38精确节点已包含在identity22项内，不重复计数。196项为vehicles29、raw captures15、startup5、external API29、external review73、identity22、008迁移10、009迁移4、010迁移3、013迁移6。Root已从互不重叠模块的safe reports独立重算313及setup/call/teardown全通过。**这不是同一轮全suite；150仅为runner注册manifest长度，本轮没有运行全150模块。**

## 已验证的SQLite行为

- 两张车型表`body`可空，新增编码、非唯一capture引用索引、`ON DELETE RESTRICT`外键及限定UTF-8/binary形状的CHECK；RawCapture/RejectedObservation新增编码，RawCapture另有byte_count与实际长度及8 MiB上限约束。binary正例只用合成字节验证存储约束，不是正式PDF采集链。
- 受控独占连接在事务外关闭并核实SQLite FK，再以`BEGIN IMMEDIATE`重建；保留旧列/行/ID、原索引/触发器/视图、三条入向FK和逻辑引用、历史raw/hash、审批binding及145对象/Parser资产。完成后核完整性与FK，最后在事务外恢复并核实FK开启。
- 四个注入失败点及复制/替换阶段真实SQL错误均回滚schema/data/版本；新空库正常创建、当前形状幂等、仅旧版本账本补记，旧物理形状的普通启动及并发普通启动均拒绝静默重建。
- 迁移后两种车型模型的ORM update/delete仍拒绝；真实`consume_approval`在时间、binding及其他前提有效时仍拒绝重用原已消费approval，原use与库存不变。车型只追加保护仍来自ORM钩子，不宣称存在原本没有的车型数据库immutable trigger。
- 私库CLI `migrate-vehicle-binary`要求显式`--private-database`、全新`--backup-file`及`--offline-confirmed`，迁移分支独立于正常app创建；备份独占创建、不覆盖已有文件，要求全部写入方停止。DB备份不替代对象/bundle一致保全。无binary时演练完整备份恢复；已有任一binary历史时拒绝文本回退，不提供自动down migration，也不删除或伪造二进制证据。

新增DDL回归以手写旧DDL验证quoted列名、literal逗号、嵌套CHECK、伪constraint注释及原PK/FK/UNIQUE/CHECK，实际SQLite CREATE和旧列行复制成功。PostgreSQL仅模型DDL编译、受限CHECK表达式解析及不支持入口拒绝有证据；quoted标识符保留大小写，unquoted正常折叠。**这些不能替代活PG或PG旧库迁移实测。**

## 源码及边界绑定

四阶段各自673个源码输入首尾稳定，报告失败与非selfcheck拒绝均0，资源已关闭；normal_database_started=false、real_provider_or_receiver_calls=0。g2d一个受管Parser child exit0/live0；这不是PDF child验收。每阶段R38只读原件前后均为25374720B/SHA256 `a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4`。Python Guard只证明其API/audit边界，不声明OS/native syscall保证。

Root逐项独立核四阶段result及其673输入首尾；g2b/g2c与最终live的唯一授权源码差异是`test_reparse.py`由24672B/SHA256 `d838464d9072a947f153e56bba6fb3df3a9166cb08f556bf25e731345666b5d6`变为下表新pin，g2d673输入全部与最终live匹配。不要求前阶段旧测试SHA被改写成新SHA。相对R84的1835显式输入，最终14既有文件改变、4新增、零删除，其余1821原字节不变；包括三个既有文档顶部更新及本报告新增。R84报告、五fixture、冻结合同及旧seal均保持历史原字节。

| 最终关键文件 | bytes | SHA256 |
| --- | ---: | --- |
| `apps/api/tire_api/db.py` | 30487 | `c3705ebdc4fff1881034c6866486404519004f3ed3c305f9813b990caa4dd55f` |
| `apps/api/tire_api/vehicles.py` | 31146 | `9fbe4861df94afe54e5adf965b7b2c2abccdbd0cfc5ca574a49a948a6f6e3f51` |
| `apps/api/tire_api/migrations.py` | 21780 | `5345c2e3005490ea6cd196819cbeb72119ecce954b211dc1435d9ee17f36065f` |
| `apps/api/tire_api/manage.py` | 4539 | `78d8598a3ce35e07b682415fb250a8c21583ddd363248c95ab8bd817c2c71bfd` |
| `apps/api/tire_api/vehicle_binary_migration.py` | 40500 | `7bc81d7536b15722282e190f960a43576d3e58be373692645d191ff5466ddf80` |
| `apps/api/tests/test_vehicle_binary_migration.py` | 37016 | `2b6c087e2e6ecdb16a57dd63db0f3a2933989a60a82e048783856162d4865fef` |
| `apps/api/tests/vehicle_binary_fixture.py` | 14065 | `d3f1cc2acd874cf36b82a6ddbcf27e9e951121bb9977a2b385b6afd604971952` |
| `apps/api/tests/test_reparse.py` | 24983 | `f3f23c75454d2885a089f3f8d07eabd45b1c164f9cd63ac1e20da6f9d7a6514c` |

四个result按g2a/b/c/d顺序为：20179B/`be857855e0024cd36937991ce61d812687e79c4ab80133e880a69a92dfaccf2f`；19517B/`451c767a943578e0e53ef694c560b6732089a7d683d11bad9cd8178d47916782`；21245B/`f9c982c91be07c92aa6d08b84ecd8dcced935f3edf2e1567c1ec76b3cdb6cf03`；19591B/`3906db8ad18b0684b08b7850c94374e2948d58af054630ad8c648d93cb0f4cf0`。source-before/source-after及精简汇总用于当前绑定，不修改历史运行回执，不新增封存等待门。

## 下一精确入口

SQLite切片不重做。继续合同§2.3/§2.4的统一车型原件helper与冻结parse_provenance，再接真实生产capture、PDF child/bundle、写入治理、消费者、V2下载/API/SDK/UI及Native闭包；这些尚未接入。PG旧库受控迁移/私PG、正常库保全与迁移另行验收。首代fetch/ready未开放，许可pending、`provider_use/export=false`、`requires_source_verification`保持。

真实专业精确SKU/外部真人Golden、完整专业性能C/真实Responses、P0来源及完整V1各Gate继续开放。本轮未新做网络研究、正常库操作或真实Provider/receiver调用；未提交或推送。不再索要EPREL Key或URL。
