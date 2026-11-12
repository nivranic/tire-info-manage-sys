# 出版物声明的生产Web验收与实拍补核

源码基线为a916bf9，当前需求与未完成项见[Agent交接卡](../../AGENT-HANDOFF-2026-11-13.md)。本轮使用完整Next生产构建、真实loopback HTTP及新隔离SQLite，沿页面执行两份已有来源转录的修订、历史、检索和比较。

## 构建

Web生产构建exit0，独立目录为.next-publication-web-qa，410个受检输入的构建前后SHA256一致。生成的next-env导入恢复原字节。PWA构建检查通过，19项精确资源白名单，版本为30cfff4bae63bde45d5d52d1。启动前按当前构建重新生成服务工作线程。PWA运行期离线能力继续按对应专项验收。

构建回执、日志和源码清单位于 `.artifacts/publication-web-20261113/`。生产Web通过项目已有API转发连接本轮API，页面和API响应均采用当前产品实现。

## 正常Web入口

79项交互与布局断言通过，范围如下。

- 从规格比较进入测试场次，分别为原报道和论文转录追加出版物角色声明，正常保存形成修订2。
- 从页面重开原报道修订1，确认该历史版本保持缺省声明，再恢复最新版。
- 从知识检索选择测试事件和205/55R16，返回两条修订2，原报道排在论文前，角色依据及事件指纹均可核对。
- 在1440、390与320精确视口检查两条检索结果、角色及字段宽度，页面和弹窗无横向溢出。
- 选择原报道全部10个参测对象，两个指标共20条原始数值逐项按指标与参测对象匹配，来源名次均显示未记录。三种视口保留20行，窄屏成绩表在自身容器内横向滚动。
- 通过页面补入实拍车辆与墙面材料日期声明，原报道形成修订3。输入高尔夫后由真实FTS返回该修订，出版物角色及指纹同步更新。

正常入口累计39个API请求均为成功响应，其中3次PUT来自页面修订。控制台error／warn为0。已实际查看320像素检索截图，声明、依据、来源链接可读，长指纹采用内部滚动与换行布局。截图为同目录browser-search-320.webp，SHA256为f30722ad7c492e5ebe666cab78839dd846e4ca38ce79e4358a2167fb9977dc31。

首版比较工装误用了不存在的.test-metric-result选择器，读到空集合。原始HTTP比较响应为200，实际DOM具有两个10行表格。按现有.test-event-comparison结构修正工装后，20组指标、参测对象与数值全部吻合。失败回执browser-comparison.json与最终回执browser-comparison-final.json分别保留。

## 原报道照片补核

从此前已取得的第1页图片清单直连取得7张JPEG，合计514668字节。随后取得其中2张在同一CDN的1024像素版本，合计216684字节。9次响应均为200，保存各自URL、字节数与SHA256，图片已逐张查看。原图与高分辨率版本的构图及标注已目视核对。[原报道第1页](https://www.autohome.com.cn/drive/201608/891160.html)

第3张照片的注释说明，两名专业测试员分别驾驶两台高尔夫开展不同项目。第4张照片说明每品牌11条胎，其中干地4条、湿地4条、滚阻1条、高速耐久1条、备用1条。第5张照片说明场地专业测试员参与，第6张照片说明场地具有天气与路温观测能力。各指标对应车辆、年款、配置、实际温度及委托关系继续待核验。[车辆照片](https://www2.autoimg.cn/newsdfs/g8/M08/E4/4E/620x0_1_autohomecar__wKgHz1eZzsuAGLNdAAsN4c29s08763.jpg)

第7张照片中墙面材料标注Contidrom及2016年6月11日至15日。此信息作为实拍材料上的日期范围写入条件说明，各指标实际执行日继续待核对，出版日期保留2016-08-03。高分辨率胎侧图可辨WANLI字样，精确版本所需标识组合仍待建立。[墙面材料照片](https://www3.autoimg.cn/newsdfs/g17/M12/E4/1B/1024x0_1_autohomecar__wKgH2Fegl_mAI13EAAc5LVK8oZM205.jpg)

原报道本轮修订3补充vehicle及conditions，原有20条数值、参测名称、指标定义及出版物角色保持原记录。论文转录保留修订2。原文与图像的完整复用许可、专业原件、精确SKU关联和外部真人审核继续待完成。[此前材料核验](material-review-2026-11-13.md)

## 数据与关闭

关闭后以只读SQLite连接执行25项核对，quick_check为ok。数据库为2事件、5修订，原始修订内容与各修订指纹核对一致，原报道修订3的变更范围限定为vehicle与conditions，论文与原报道的全部客观成绩保留。轮胎参数事实、来源快照、原件、SKU关联及AI／向量请求、完成账本和缓存均为0。

隔离API的实际Provider为openai_responses／ai_disabled，connection_verified为false，requests和accounted_tokens均为0，Embeddings为embeddings_disabled。API进程外网与子进程尝试均为0，正常数据库使用记录为false。材料下载由独立直连研究进程执行。

API通过自建关闭端点退出0，数据库关闭。生产Web按监听PID与命令行确认归属后停止，终止退出码为-1。浏览器自建页面已关闭，系统快照确认两个端口无监听、对应PID均已退出。

回执根目录为 `.artifacts/publication-web-20261113/`，包含build.json、browser-*.json、state-validation.json、closure-system.json及workspace-r1中的原始／当前事件和HTTP记录。照片及高分辨率原件分别位于source-photos与source-photo-details，均保留在Git忽略目录。

最终交付复核505项通过，包含410项当前源码字节绑定和40个本地文档链接，另核对构建、Web断言、数据库、实际Provider、图片字节及关闭状态。历史HANDOFF尾文保留原字节。入口为同目录validate_delivery.py，结果为delivery-validation.json。

## 剩余验收

继续扩大代表性来源、地区及精确版本质量标注，完成原件和完整许可、精确SKU、真人Golden、真实OpenAI Responses与Embeddings、生产权限、完整WCAG、原生平台和发布Gate。完整V1持续开放。
