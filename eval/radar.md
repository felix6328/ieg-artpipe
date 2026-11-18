# 阻塞雷达评测

60 条公开评论。0 条 provisional，60 条人工复核。
样本包含关键词候选、容易误报的近似表达和随机对照。标签按评论与事件类别评估，停滞由时间戳计算，排除在文本分类指标之外。

| 方案 | 真阳性 | 假阳性 | 假阴性 | 精确率 | 召回率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 关键词 | 9 | 1 | 5 | 90.0% | 64.3% |
| LLM | 4 | 3 | 10 | 57.1% | 28.6% |
| 并集 | 10 | 4 | 4 | 71.4% | 71.4% |

## 仅人工复核样本（60 条）

| 方案 | 真阳性 | 假阳性 | 假阴性 | 精确率 | 召回率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 关键词 | 9 | 1 | 5 | 90.0% | 64.3% |
| LLM | 4 | 3 | 10 | 57.1% | 28.6% |
| 并集 | 10 | 4 | 4 | 71.4% | 71.4% |

模型候选中 1/8 条因引用验证被拒绝（12.5%）。本轮实际请求 0 次，命中缓存 3 次。费用估算 ¥0.0000，每 100 条评论 ¥0.0000。

## 预测与复核标签的分歧

- [评论 70244](https://gitea.wildfiregames.com/0ad/0ad/issues/4440#issuecomment-70244) · 参照 无 · 结果 question_unanswered
- [评论 127842](https://gitea.wildfiregames.com/0ad/0ad/issues/8414#issuecomment-127842) · 参照 无 · 结果 dependency
- [评论 79691](https://gitea.wildfiregames.com/0ad/0ad/issues/5174#issuecomment-79691) · 参照 rework · 结果 无
- [评论 51822](https://gitea.wildfiregames.com/0ad/0ad/issues/3377#issuecomment-51822) · 参照 无 · 结果 question_unanswered
- [评论 11394](https://gitea.wildfiregames.com/0ad/0ad/issues/854#issuecomment-11394) · 参照 dependency · 结果 无
- [评论 17625](https://gitea.wildfiregames.com/0ad/0ad/issues/1267#issuecomment-17625) · 参照 question_unanswered · 结果 无
- [评论 16937](https://gitea.wildfiregames.com/0ad/0ad/issues/1217#issuecomment-16937) · 参照 无 · 结果 rework
- [评论 95755](https://gitea.wildfiregames.com/0ad/0ad/issues/6556#issuecomment-95755) · 参照 rework · 结果 无
