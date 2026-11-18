# ArtPipe 费用与资源

Git 元数据和 XML 按需读取。模型原件从 0 A.D. 公共仓库下载到有上限的本机缓存，缩略图在本地 CPU 生成。中文检索的 OpenCLIP 权重首次下载，索引之后的查询在本机完成。

风险雷达默认关键词基线。运行可选模型时，费用按接口 usage 返回的输入和输出 token、项目配置中的单价估算。可重用同一份输入哈希对应的缓存。单次运行预算上限见 `configs/precheck.yaml`。

调用和费用证据见 [Issue #8414 演示](eval/radar-8414-model.md) 与 [风险雷达对照评测](eval/radar.md)。
