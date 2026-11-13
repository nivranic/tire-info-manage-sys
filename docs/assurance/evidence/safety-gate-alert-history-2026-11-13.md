# Safety Gate逐告警版本与变化事件验收

本阶段从main的 `495bda2ea745c2b47d9cd6613e386ab247e6d7fb` 继续原规格P0安全来源及证据化监控，接通逐告警内容版本、跨周观察、变化事件、固定历史分页与正常生产Web。完整V1目标继续active。[实施计划](../../plans/2026-11-13-safety-gate-alert-history.md)

## 正常业务合同

- 官方原生alert_id作为来源内身份，历史负数ID与同caseNumber的不同ID分别保存。
- 新增 `safety_gate_alert_revisions`、`safety_gate_alert_observations`、`safety_gate_alert_changes` 三张只追加表，复用现有摄取锁与成功采纳事务。
- 内容指纹排除周报内order，原始order继续保存在原件与快照。相同内容复用内容版本，每份不同快照建立对应观察。旧内容再次出现时可复用原版本，并建立新的变化事件。
- 先选取同一周报的最新采纳观察，再按这些观察中的最大周报发布日期确定已保存材料的来源时间范围。同日不同周报内容相异时保留冲突，恢复一致时追加恢复事件。
- 较早周报进入历史观察，告警缺席时保留上次观察及未知适用性。周报日期更正采用该周报最新观察中的日期。
- 明确历史入口会为已有已接受周报补建派生记录并追加审计。原快照、原件、旧行和原来源Parser部署保留，可信Parser目录仍为15项。
- `GET /v1/safety-gate/alerts/{alert_id}/history` 要求mode=history，支持limit为1至50、offset及through_sequence。后续页按相同观察序号范围读取。
- 每份历史观察核对原始XML、规范化内容、指纹、告警位置、周报身份及变化事件。Web支持字段前后值、版本原件、冲突状态和分页，复用现有取消链。

## 已取得的验证

| 范围 | 结果与本机回执 |
| --- | --- |
| 最终十二模块受管回归 | 287通过、0失败、0跳过，811输入稳定、资源关闭、非自检拒绝0，`.artifacts/sg-alert-r7/result.json` |
| 日期更正后的专项 | 两模块56通过，`.artifacts/sg-alert-r6/result.json` |
| 真实官网与正常HTTP API | 31项通过，1次实际官网周报查询，`api-acceptance.json` |
| 最终源码HTTP重核 | 13项通过，历史、固定分页及原件响应与修正前逐项一致，零新增官网请求，`final-http-acceptance.json` |
| 真实材料生产Web | 45项通过，覆盖官方告警历史、原件SHA256、1440／390／320视口及关闭后迟到响应，`browser-real-*.json` |
| 合成变化生产Web | 26项通过，13次观察、同日冲突、字段前后值、10＋3行分页及固定序号范围，`browser-synthetic-*.json` |
| PostgreSQL专项 | 17项通过，非超级用户应用角色、日期更正、字段变化、冲突及实际dump／restore，158张模型表和schema版本指纹一致 |
| Web及类型 | Web55／55，Web／Desktop／Mobile类型全部exit0，`.artifacts/sg-alert-frontend/result.json` |
| 独立生产构建 | exit0，412个输入稳定，生成文件原字节恢复，`.next-safety-gate-alerts-qa` |
| 旧库副本升级 | 174→177表，仅增加三张派生表，原表列与原行指纹保留，`upgrade.json` |
| 关闭后真实材料库 | 两份库各16项通过，各177表、228次观察及10份原件逐项绑定，WAL归并前后列与行指纹一致，`real-closed.json`、`final-http-closed.json` |
| 关闭后合成库 | 9项通过，13次观察、14份原件及14次种子查询核对，`synthetic-closed.json` |
| 资源释放 | 本次API、Web与隔离PostgreSQL端口及自有进程均缺席，项目页释放至about:blank，仿真已重置，`closure.json` |
| 交付静态复核 | 181项通过，811个后端输入、412个构建输入、最终HTTP源码绑定、109个本地链接、15个交付文件及历史文档均已核对，`delivery-validation.json` |

本机主要回执位于 `.artifacts/sg-alert-20261113/`。最终受管回归SHA256为 `36e42102e9014500fa8069f30a85c0f5bf3e20e02d2c81bbc0e4925dad7e2578`。最终PostgreSQL报告由 `pg-run.json` 定位，首轮16项结果保留于 `pg-run-r1.json` 对应目录。真实材料与合成材料两个浏览器批次的console error／warn均为0。320像素真实材料截图已目视核对，33316字节。

生产Web首先通过原有转发连接真实材料旧库副本，随后连接独立合成私库，使用同一已构建前端。两批界面均通过正常应用路由和实际HTTP读取，原件只在Git忽略范围保存。

真实Goodyear告警SR/01396/26的原生ID为10098848。三份原件观察复用内容版本1，形成一次首次观察事件。周报发布日为2026-05-15，告警发布日为2026-05-12，原始序列号及未知适用性继续保留。真实API新增一次官方核验，原件与快照复用，核验记录新增一次。[官方告警](https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/10098848)

真实材料库包含158个内容版本、228次观察、158个首次观察事件、7份周报／索引快照和9次成功核验。两份关闭后数据库SHA256分别为 `ede42ee21c33983aeef0129ea2ff9639c02e61c7269c79ee124ae290eeb0cb9f` 与 `3d3892a1d1f844e187dc5d94cf4c4bb8637d2c04b02bd00588c36134ac63d4cd`。合成库SHA256为 `ea4621dfccd8d6a95cbebbaa998e0c5877ad4da8589ab5b141e91681a3ecd5d6`。前一阶段原库的SHA256继续为 `80db16f9e4d5ed57c531a680f7ab69c6867648c087d62748a933990a0870b96f`。

## 原始失败与修正

- sg-alert-r1在新模块落地前收集失败，原回执保留。
- sg-alert-r2在沙箱中遭遇原件对象写入失败。安全诊断定位ObjectStoreError，独立os.link探针取得PermissionError／WinError 5。原有对象发布合同保留，授权执行通道的同代码回归通过。
- Web首次启动已报告Ready并监听3066，浏览器和直连HTTP均超时。核实PID和真实命令行后关闭自有进程，相同命令在授权执行通道恢复可访问性，源码与网络配置沿用原值。
- 合成界面首轮在DataTree的onToggle更新前读取嵌套字段，取得两项失败。按组件的逐层展开行为等待后，字段前后值和12项主检查通过，原始 `browser-synthetic-diff.json` 保留。
- 复核补出同一周报发布日期向前更正的反例，sg-alert-r5为0通过／1失败。原查询先选择全历史最大日期，现已改为先取各周报最新观察。专项56项及PostgreSQL17项通过，最终HTTP13项确认既有真实响应一致，两份真实材料库的228次观察分别完成新代码重核。

## 待完成的完整范围

Safety Gate长周期调度、变化通知、持久回退策略、外部Key权限、AI引用和Native消费继续实施。当前模型调用均为0，OpenAI模型／Key及三个约定EPREL Key变量在Process／User／Machine作用域复核为空。首个真实生成接入继续采用用户选定的OpenAI Responses API。

真实精确SKU与外部真人Golden、代表性检索质量、生产PostgreSQL／IAM、全部六类平台、读屏与完整WCAG、性能、灾备和发布Gate继续验收。新clone需准备依赖与相应材料、重新封装Parser并建立自身回执。[当前交接卡](../../AGENT-HANDOFF-2026-11-13.md)
