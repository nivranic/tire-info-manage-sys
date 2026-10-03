# NHTSA 轮胎召回录制样本

`campaign-23t001000.json` 是官方公开接口的完整录制响应，未改写为合成产品：

- URL：`https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=23T001000`
- 抓取时间：`2026-09-27T17:35:26.708802+00:00`，HTTP 200，application/json。
- 来源契约：`https://www.nhtsa.gov/nhtsa-datasets-and-apis#recalls`。
- 公告产品为 General Tire ALTIMAX RT43；样本不证明任何用户持有的轮胎受影响。
- 旧接口日期 `02/03/2023` 为日/月/年；与官方 FLAT_RCL_POST_2010 数据的 RCDATE `20230302` 交叉核对。`ModelYear=9999` 为未知或不适用，不能作为生产年份。

测试中的字段删除、错误Count、错误公告号、重排、空结果和网络失败均为显式合成扰动，不声称官方发生这些变化。大型官方数据集和研究过程保存在忽略目录 `.artifacts/recalls/research`，不作为应用内置召回数据库。

`search-xcellent.json` 和 `search-empty.json` 是官方站内轮胎搜索接口录制的单页响应：`https://api.nhtsa.gov/tires/bySearch`，固定 `dataSet=safetyIssues`、`data=recalls`、`max=10`、`offset=0`、`order=asc`、`sort=productName`。精确搜索词和本页范围保留在各文件的 `meta.pagination.currentUrl`。XCELLENT样本含公告26T008000、官方ISO日期、关联产品生产范围原文及附件URL；空页只代表这个搜索词当时的结果，不是安全证明。此接口是官方前端实际使用的契约，未宣称与datasets文档公开API同等稳定承诺。
