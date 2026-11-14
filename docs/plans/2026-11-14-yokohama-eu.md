# 横滨欧洲官方规格来源接入

原规格将Yokohama列为P0官方来源。本阶段按既有固定来源Adapter流程接入欧洲ADVAN Sport V107，正常查询继续执行robots、限频、公共DNS核对、正文捕获、隔离Parser、字段证据及来源范围身份。

## 来源核验

2026-11-14直连robots与规格页均为200，robots允许目标路径。桌面规格表共6张、114条，页内逐行给出尺寸、载重速度、合并XL/RF、OE说明、厂商EU标签声明及EPREL链接。完整页面保存在Git忽略槽。

加拿大规格页可访问，其条款要求内容复制取得书面同意。美国规格入口200，当前主要以规格图片呈现。日本robots地址200返回公司首页HTML。上述入口继续保留核验记录。

欧洲条款入口当前为销售合同GTC，页面没有提供开放再分发许可。本阶段沿用官方事实查询与本地证据链，外部事实读取继续受既有许可治理约束。[规格页](https://www.yokohama.eu/tyres/advan-sport-v107/)、[robots](https://www.yokohama.eu/robots.txt)、[条款](https://www.yokohama.eu/terms-conditions/)

## 字段与身份

- 保留R和ZR，外层服务描述括号与真正的速度级别(Y)分别解析。HL仅在原规格显式前缀存在时记录true。
- XL/RF保留合并原文。独立xl和run_flat继续为null，OE Info保留厂商原文，oe_mark继续为null。
- 厂商标签声明采用既有eu字段及manufacturer_official来源权威。EPREL ID与URL保留厂商提供的引用，监管读取与绑定需要后续独立核验。
- 厂商产品代码未知，身份采用既有source_scoped合同。逐字段定位到原表／行／列，整页通过验证后执行型号与几何尺寸筛选。

## 实施与验证

1. 新增确定性HTML表解析器，固定canonical、title、表头文本及图标列语义，拒绝异常结构、重复EPREL行与无效单位。
2. 接入既有registry、Parser目录、可信子进程、完整封存包目录及低基数遥测。
3. 新增合成字段及漂移反例，验证旧15项封存包在新宿主继续执行，新包包含16项Parser。
4. 经正式受管回归后执行显式在线canary与正常QueryService证据链验收，核对预算、引用和资源回收。

部署需要重新生成并批准绑定新API源码的@4运行合同。真实监管绑定、长期来源稳定性、人工Golden及完整V1 Gate继续验收。
