# 报告导出的嵌入字体

`TireEvidenceSC-Regular.ttf` 是 Noto Sans SC 的静态 400 字重派生字体，仅修改字重实例与字体名称，保留全部原始字符覆盖。按随附的 SIL Open Font License 1.1 分发；PDF 中由 ReportLab 嵌入实际使用的字形子集。

上游为 Google Fonts 官方仓库 `google/fonts`，固定提交 `a85815a42757630ce188fdad368c2dfc444d4773`。源文件、许可证、生成字体的 SHA-256 与工具版本记录在 `provenance.json`。源字体 Copyright 2014-2021 Adobe，保留名称为 `Source`；本派生字体另命名为 `Tire Evidence SC`。

重新生成时，先从 `provenance.json` 的固定官方 `source_url` 下载到临时路径，再从仓库根运行：

```text
uv run --project apps/api --extra dev python apps/api/tire_api/assets/fonts/build_font.py --input <下载的字体路径>
```

构建脚本先核验源文件与许可证哈希，使用锁文件中的 fontTools 版本生成静态实例，保留原始时间戳并记录产物哈希。未使用 Windows 系统字体。运行时只读取包内固定路径，不接受请求提供的字体路径，不下载字体；如果字体缺失、损坏或不覆盖报告中的字符，PDF 导出明确失败，不静默显示缺字框。
