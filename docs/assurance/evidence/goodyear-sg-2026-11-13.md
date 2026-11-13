# 固特异新加坡官方规格与正常查询验收

本阶段从main的 `d7b343244e4d130e66bbf5e1bedf8eeea11cbab9` 开始，扩展原规格P0厂商来源。固定Adapter接入Eagle F1 Asymmetric 6及SUV版，沿既有证据捕获、隔离Parser、在线优先和单次授权回退。完整V1继续开放。[实施计划](../../plans/2026-11-13-goodyear-sg-source.md)

## 官方合同与身份

官方页面为text/html、109567字节，原始SHA256为 `3c74558407037b142546c04e1dada821520ea31547631dfa520669a70dd03101`。一张逐行表与两张按轮辋展示的表逐项一致，分别有53条普通版和15条SUV声明。原页面的组rowspan和展示列存在排版差异，解析逐行核对尺寸及轮辋，再校验三表集合。[官方规格](https://www.goodyear.com.sg/tyres/goodyear-eagle-f1-asymmetric-6)

三条普通版声明的速度栏为空，尺寸分别为245/45R19、275/40R19和255/45R20。SUV版255/55R20的载荷原文为 `X (EDR)`，增强载荷保持未知。明确XL、原始速度栏及载荷栏分别保存，每项采纳字段附XPath。FP、EDR、RO、MO、星号、I*和(+)的技术或OE解释继续核验正式依据。

产品代码、GTIN和未声明的OE、缺气保用及静音技术保持未知。68条记录使用identity@2的source_scoped身份。正常API另保存同尺寸跨型号的两条观察，查询范围身份独立，因此隔离库合计70个版本及事实。

robots为93字节，允许固定产品路径。官方条款授权组织内部非商业复制，要求副本保留版权与专有通知。原始页面、完整通知、robots及条款保存在Git忽略范围，商业采集与再分发许可继续待核。[robots](https://www.goodyear.com.sg/robots.txt) [官方条款](https://www.goodyear.com.sg/legal-disclaimer)

## 工程接入

固定来源为 `goodyear-sg`，地区SG。两个型号共用官方页面，完整三表校验后按型号和尺寸筛选。附加参数、跨域和非HTTPS地址沿既有URL合同拒绝。注册、传输归属、受限Parser子进程、可信包及有界遥测已接入，Web补新加坡及两个原始栏位的中文标签。

当前11个轮胎区域来源覆盖7个厂商品牌，另有NHTSA召回和小米车型来源。可信Parser目录14项，包含13个业务来源和工作区PDF正文Parser。历史8至13项完整目录继续接受，旧13项安装在测试临时目录中重建、封包并执行。新增来源首次部署保留既有部署修订。

## 已取得的验证

| 范围 | 结果与本机回执 |
| --- | --- |
| 实现前回归 | 新来源21项失败，`.artifacts/gysg-red/result.json` |
| 初始沙箱八模块回归 | 183通过、19失败，805输入稳定、资源关闭，`.artifacts/gysg-r1/` |
| 初始沙箱补充回归 | 17个失败调用阶段后在召回工装等待中停滞，已核对进程并停止，`.artifacts/gysg-r2/` |
| 授权通道精确反例复核 | 旧13项包执行、原文捕获和召回3项通过，`.artifacts/gysg-probe/result.json` |
| 最终十九模块回归 | 591通过、7跳过、0失败，805输入稳定、资源关闭、非自检拒绝0，`.artifacts/gysg-r3/result.json` |
| 真实正常API | 29项通过，4次官网查询及受控熔断／单次授权回退，`workspace-api-r2/result.json` |
| Web与类型 | Web55／55，Web／Desktop／Mobile类型均exit0 |
| 独立生产构建 | exit0，410输入稳定、生成文件原字节恢复，`.next-goodyear-sg-qa` |
| 正常生产Web | 50项通过，覆盖两型号、缺失速度、原始X标记、来源身份、原文与三种宽度，控制台error／warn为0 |
| 关闭后数据库 | 28项通过，两库各172表，WAL归并前后逐表行指纹一致，完整性／外键及对象字节核对通过 |
| 资源释放 | 自有API／Web监听和启动进程均已退出，项目页面已导航至about:blank |

正常Web完成三次真实官网200。普通版缺速度、SUV版原始X标记及重复普通版查询保留各自状态，重复查询复用原ID、快照与事实。1440、390及320像素均无页面横向溢出，320像素原始WebP已目视核对。浏览器视口验收与原生设备、读屏及完整WCAG分别跟踪。

API库SHA256为 `fee1dabb6352bbad7355b4c20bd25dd2548c6631cdffc51860f3e80eda7c9fe2`，Web库为 `f8abfe5e941928807112e493bfb2635f1a8cdabee40a087a4734ab39b0ef64e4`。API为70条事实、3份快照、4份捕获与5次查询。Web为2条事实、2份快照、3份捕获与3次live查询。两库AI与Embedding记录均0，Provider为openai_responses／ai_disabled。

7项跳过来自5份Toyo／Hankook及2份Pirelli历史完整响应缺失，仓库摘录与合成用例仍执行。最终回归SHA256为 `ba43b07feec8cddab88c5da559fc4b3afd8fe57da1a3ba8ab47790c600da2e5e`。三作用域的OpenAI模型／Key及EPREL Key存在性均复核为空，回执仅保存布尔值。

最终交付156项核对通过，包含102处本地文档链接、805个后端输入、410个前端输入、两套实际14项Parser包与当前源码绑定、原规格及历史交接尾文保留。21个任务文件的新增内容路径与凭据检查通过，汇总为 `delivery-validation.json`。

## 原始失败与范围

- 首轮API在原件存储阶段返回evidence_capture_failed。原始独立存储探针定位到 `object_store.py` 的原子os.link操作，Windows沙箱返回PermissionError／WinError5。通过授权执行通道使用新隔离库完成正常API。原件存储沿用既有原子发布实现，原失败保留于workspace-api-r1及storage-probe-r1.json。
- 初始沙箱回归同时出现捕获、历史Parser包和内核限制相关失败，原结果及安全类型／文件／行号回执保留。三个精确失败用例在授权执行通道全部通过。gysg-r2的召回并发工装在初次采纳失败后等待后台事件，核对唯一runner／启动器父子对及无子进程后停止，保留未完成状态与终止回执。
- 初次端口核对被沙箱的CIM访问限制拒绝，随后在授权执行通道核对空闲端口、启动PID、实际命令行及父子关系。关闭回执记录自有进程和8005／3065监听均缺席。
- 离线工装首版误把文本换行规范化后的哈希标成raw_sha256。修正工装分别记录原始字节与解码文本哈希，官方原件哈希按捕获回执核对，保留official-response-parse.json及r2记录。
- 交付检查首次在最终回归结果生成前启动，返回FileNotFoundError。最终回归退出0后已重跑完整交付检查并通过。
- 浏览器工具拒绝关闭最后一页，已将自建项目页导航至about:blank，隔离上下文保留该空白页。

后续P0探查核对Dunlop日本站robots入口。初次按text/plain合同取得unsupported_content_type，单次低频诊断取得HTTP200、text/html、21990字节，标题为“お探しのページが見つかりません”。有效robots规则继续待取得，产品页请求数为0。回执位于 `.artifacts/p0-dunlop-20261113/`，SHA256为 `95ba85618a684951a29d1c0bc3e1a7b5979b1ebfee4d96af5012211317ada84e`。

本机入口为 `.artifacts/p0-goodyear-20261113/`。原始材料、截图、私库和工具回执位于Git忽略目录。商业许可、标记正式释义、精确SKU、其他P0渠道、长期在线稳定性、真人Golden、真实OpenAI语义和完整发布Gate继续推进。[当前交接卡](../../AGENT-HANDOFF-2026-11-13.md)
