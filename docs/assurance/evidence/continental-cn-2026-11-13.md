# 马牌中国官方规格与重复核验验收

本轮从main的 `ba45d1157034849209017a434f8d80f32eec570e` 开始，接入中国官网SportContact SC7固定规格接口，补齐正常证据捕获及缺代码观察的重复核验。完整V1继续开放。[实施计划](../../plans/2026-11-13-continental-cn-source.md)

## 官方合同与身份

中国官网产品页静态HTML只有表头，其引用的getData.js和script.js确认同域GET接口及页面型号参数。实际响应为application/json、5408字节，SHA256为 `a0c1c4131d7d5dc2e513a59effeed59508cc6038ed24c97e82ee3d65adb9ae8e`。六个轮辋分组共有47条观察，覆盖18至23英寸。型号按中国页原名SportContact SC7保存。[官方产品页](https://www.continental-tires.cn/tires/sportcontact-sc7) [固定规格接口](https://www.continental-tires.cn/tpservice/Search/getTireData?tire=SportContact%20SC7)

robots为text/plain、508字节，允许该接口路径。法律声明约束作品及商标使用，商业采集与再分发许可继续待核。原始页面、脚本、响应和条款留在Git忽略目录。[官方声明](https://www.continental-tires.cn/legal-notice)

逐行保留R／ZR、载重速度、明确XL、FR及ContiSilent声明和JSON路径。FR的解释另核对官方2025技术手册印刷第6页。空白技术属性保持未知。`235/45R19 95Y` 两行分别为静音“是”和空白，两行独立保留。[官方标记说明](https://www.continental-tyres.co.uk/content/dam/conti-tires-cms/continental/market-content/gb/tyre-knowledge/Conti_Tyre_Databook_2025_EN_screen.pdf.coredownload.pdf)

接口未提供产品代码、GTIN和OE。47条记录沿用identity@2的source_scoped身份，精确SKU与跨来源等价继续待核。不同查询范围保留各自观察，完整API工作区因此有47条全表观察和2条尺寸查询观察，共49条版本及事实。

来源发现共13次直连请求，12次200、1次403，响应哈希逐项核对。美国站robots仍403。另已保存Goodyear新加坡的robots、产品页及条款，三张规格表的一致性、缺值和标记语义继续核对。

## 正常链路修正

固定JSON来源接入Registry、受限子进程、可信Parser包、传输与有界遥测，当前为10个轮胎区域来源、6个厂商品牌，另有NHTSA召回和小米车型。可信目录13项，包含12个业务来源及工作区PDF正文Parser。此前8至12项完整目录继续接受，新增来源首次部署保留既有部署修订。旧12项包由当前源码重建并执行，重建范围在回归工装中明确记录。

首次正常API在解析前返回evidence_capture_failed。复现确认 `captures.py` 的带参数URL校验原先仅支持NHTSA。新增固定目录校验绑定来源ID、已登记URL和响应类型，已有NHTSA合同经回归覆盖。

随后首次观察及静音双行通过，相同原文的重复200被field-loss质量门隔离。原始回执确认原文、哈希、Parser和逐行领域内容全部一致，缺产品代码导致稳定键缺失。`service.py` 现仅在当前冻结Parser选择、身份合同、URL、响应类型、原文字节及哈希、逐行领域投影一致时，复用既有assess_records比较完整观察。有代码行使用既有稳定键。原文或输出变化进入通用质量评估，实体继续source_scoped。两组正常API回归分别改变原文字节和解析输出，均取得隔离与采纳数据保留的结果。

Web复用原有查询卡及证据检查器，补适用车辆类别的中文标签。正常控件选择中国、SportContact SC7和235/45R19后，两个卡片分别显示静音声明和未知，并明确显示产品代码未知、来源范围身份。证据检查器展示JSON、官方链接、Parser版本及哈希。

## 实际验证

| 范围 | 结果与本机回执 |
| --- | --- |
| 捕获修正后的十二模块回归 | 414通过、7跳过，`.artifacts/ctcn-r2/result.json` |
| 重核验、质量、核心与审核专项 | 108通过、0跳过，`.artifacts/ctcn-r3/result.json` |
| 最终十八模块回归 | 568通过、7跳过、0失败，803输入稳定、资源关闭、非自检拒绝0，`.artifacts/ctcn-r4/result.json` |
| 真实正常API | 24项通过，3次真实官网查询及1次受控熔断／单次授权回退，`workspace-api-r4/result.json` |
| Web与类型 | Web55／55，Web／Desktop／Mobile类型均exit0 |
| 独立生产构建 | exit0，410输入稳定，生成文件原字节恢复，`.next-continental-cn-qa` |
| 正常生产Web | 59项检查通过，含来源选择、三种宽度、原文与两次重核验，控制台error／warn为0 |
| 关闭后数据库 | 26项通过，两库各172表，WAL归并前后逐表行指纹一致，完整性／外键及原件字节核对通过 |
| 资源关闭 | 项目浏览器页、API／Web监听和自有启动进程均已关闭 |

7项跳过来自5份Toyo／Hankook及2份Pirelli历史完整响应缺失，仓库摘录和合成用例仍执行。最终回归SHA256为 `62e0ee7d95a604575c2778eee1919e07e9fede7d53a79b142fc252f193ee5b92`。

浏览器实测三次官网200，私库为3条live、3份原文接收记录、1份快照及2条事实，两个记录ID持续一致。1440、390、320像素均无页面横向溢出，320截图已目视核对。该结果覆盖浏览器视口仿真，原生设备与完整WCAG继续待验。

最终API库SHA256为 `9bd667165ca1a1252d4fd0cb9a2b728e23dfc97bdec907dada37270c7176bbc6`，Web库为 `bfb83708dea9667f536c058d05e9b77596e3eb1e84464079a822cf865f33d749`。AI与Embedding请求均为0，Provider状态为openai_responses／ai_disabled。

最终交付核对150项通过，98处本地文档链接有效，803个后端输入和410个前端输入绑定当前源码。两套实际数据库各自的13项Parser目录及全部包文件哈希与当前源码一致。原规格、历史交接尾文、22个任务文件范围及新增内容的路径与凭据检查通过，汇总保存为 `delivery-validation.json`。

## 原始失败与修正

- 实现前25项失败保留于 `.artifacts/ctcn-red/`。初始八模块250通过／5跳过，随后补捕获、质量及召回回归。
- workspace-api-r1保留捕获拒绝，`capture-query-red.json`记录固定查询URL复现。workspace-api-r2已保存原文，验收shell误用.NET的X64名称，Parser按Windows架构合同拒绝。改验收进程变量为AMD64后通过环境探针，该修正作用于验收进程环境。
- workspace-api-r3保留重复200质量隔离及全部已采纳数据，`quality-revalidation-red.json`核对四项一致证据。修正后使用独立workspace-api-r4验收。
- 浏览器首批工装使用CN值匹配可见“中国”选项失败，随后按真实标签操作。首次卡片计数包含嵌套参数article，限定顶层卡片后通过。原失败JSON保留。浏览器工具的文件保存入口拒绝当前项目路径，回执改由授权的工作区文件工具保存。截图保留原始WebP字节。

本机总入口为 `.artifacts/p0-sources-20261113/`。正文、私库、截图和工具回执位于Git忽略范围。商业复用许可、精确产品代码、其他型号和P0来源、长期可用性、真实OpenAI质量、真人Golden、生产权限与完整平台发布验收继续推进。[当前交接卡](../../AGENT-HANDOFF-2026-11-13.md)
