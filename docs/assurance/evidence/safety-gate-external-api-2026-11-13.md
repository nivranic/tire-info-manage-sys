# Safety Gate外部受许可读取验收

日期：2026-11-13。起点为已发布的 `7714db8074727198f143941d63f9c42fb02d5ec3`。新增受许可告警Reader、GET端点、独立scope、固定窗口分页、共享类型／SDK和Web Key选择；查询归属与许可绑定沿用[上一交付点](safety-gate-external-foundation-2026-11-13.md)。

## 已实现

- 固定eu-safety-gate来源和服务端grant配置，只接受本人成功周报query_id及明确history模式。每页在新鲜受管SQLite事务中重验Bearer、账户、冻结归属、许可、批准绑定、原件／文档哈希、Parser及核验时间。
- 14个必需身份／证据字段、19个可选业务字段；unknown适用性保留为not_assessed。未许可字段省略，已许可未知值保留null，不返回XML、图片、私人规则、账户ID或审核原文。
- 游标绑定Key、owner承诺、路由、query、report、limit、证据、许可头及固定15分钟期限。续页重验不续期；旧scope不自动获得新权限，四scope Key继续兼容轮胎Reader与库存。
- 物化前限制字段字节、累计SQL行／存储／JSON节点；XML与document各限8MiB，累计存储32MiB，页面2MiB、limit1–20。初步Bearer认证也在加载Key前预检大小。SDK校验、请求冻结和取消覆盖正常传输与不响应的取消路径。
- Web新增scope默认未勾选，仍要求显式勾选授权，说明Key不自动取得材料许可；保持一次显示与正常撤销。

## 最终回执

| 范围 | 结果及入口 |
| --- | --- |
| 后端13模块 | 344／344，无跳过，823输入稳定、自有资源关闭、非自检拒绝0；`.artifacts/sg-external-final-r2/result.json` |
| 后端结果SHA256 | `e02009444da1ac2716730801d49aba7e46f58734f1a192412ec0d1dbe35adace` |
| SDK | 新增8组测试；既有外部API59项、单事实136项、轮胎分页189项、库存47项通过；专项类型通过 |
| 三端与Web | Web／Desktop／Mobile类型检查通过；Web55／55；417输入生产构建exit0且源码稳定、生成文件原字节恢复 |
| 正常HTTP | 28项通过，独立账户及正常查询／Key路由，官方历史周报75条告警按四页完整投影 |
| 正常SDK消费 | 真实loopback HTTP四次读取75条，逐页DTO、证据、原生ID及完整性校验通过 |
| 生产Web | 正常界面创建仅含Safety Gate scope的Key、显式确认、正常读取20条、关闭显示与撤销；撤销后401；Key不在URL或持久存储 |
| 精确布局 | 实际1440／390／320像素，页面和Key面板均无横向溢出，新增scope和许可提示可见 |
| 数据关闭 | 关闭前15项、关闭后11项通过；185表行指纹不变，原件、冻结归属／审计、许可原文保留，Parser Windows Job完成且子进程已回收 |
| 资源关闭 | 两把测试Key撤销、grant撤回；API／Web进程与8010／3070监听关闭；浏览器保留about:blank |

本机正常链路、构建、前端及关闭回执位于 `.artifacts/sg-external-20261113/`。回归是列明模块的专项验证，不是完整V1全量验收。

## 真实材料与权限依据

材料为此前直连取得的官方Report-2026-45 XML，report_id为10000331，164092字节、75条告警；SHA256为 `43dab5b90015ecb0792ee11ec6171bdcfa8eeb962e8014df9a0b7d8f28f0db2b`。原始XML文件本轮字节未变。

官方数据集JSON-LD为176588字节，SHA256为 `2fea9003a728284a4964e9824df3692a0ebab3b08a720898a5b6b203266d3730`。逐项核对weekly XML distribution的dct:license为欧盟CC0 URI，并以完整元数据作为受管许可原文，经隔离管理员预览／确认后批准具体快照和字段，验收后撤回。元数据由Agent核对，不能等同独立法律审核。

本轮重放保存的官方XML，运行真实隔离Parser及正常API写入，随后外部读取不再触发抓取。验收fixture普通查询返回live代表成功回放，不表示官网当时在线；真实来源请求、真实模型调用均为0。尚未执行实时官网重复核验、正式PostgreSQL外部Reader、公网部署、Native端或自然长期监控验收。

## 原始失败与修正

1. `.artifacts/sg-external-red-r1/`记录端点未实现的红批；首批新增HTTP模块29项通过，随后加入大响应、304和PG明确拒绝等用例。
2. 13模块首轮为342通过／2失败，位于 `.artifacts/sg-external-final-r1/`。原始断言定位到旧023迁移复核对完整初始化新增FTS表的遗漏；补上固定12表集合，保持023版本INSERT增量、旧DDL／旧行、幂等与失败回滚断言。专项2项通过，最终同范围344项通过；未改产品迁移逻辑。
3. 官方材料回放前两次失败为parser_isolation_unavailable。核验进程缺少两个架构环境变量，直接调用Parser环境检查可重现；OS与Python均确认64位。只给验收子进程补齐AMD64环境，并换新私库重验；未修改产品隔离器或放宽限制。旧库两次失败请求与0成功Verification保留，原始异常位于replay-error.txt。
4. SDK初次类型检查暴露unknown属性窄化及测试getter字面量类型问题，均修正后通过；运行合同8组通过。
5. 浏览器工具文件路径访问受其workspace配置限制，改由已授权的文件读取通道传入脚本；没有改全局配置。窗口resize最小只能得到501像素，未作为窄屏证据，随后用viewport emulation取得实际390／320像素。撤销负例产生的单条401控制台网络错误属预期。

## 下一步

完整V1继续开放。推进Safety Gate AI引用／Native消费、正式PG受管Reader、其他P0来源、真实精确SKU／真人Golden、自然长周期通知及生产权限／六平台／安全／性能／灾备Gate。OpenAI Responses仍为用户指定的首个真实AI接口，缺凭据时继续独立工作。使用方式见[外部API合同](../../EXTERNAL-API.md)，接手范围见[当前交接卡](../../AGENT-HANDOFF-CURRENT.md)。
