# 中文资产检索评测

当前目录 500 个网格，术语表 197 条。88 条中文查询，0 条待人工复核（provisional）。
相关资产基于从真实资产名和用途整理的候选标签。文件名基线直接匹配原始文字，词法方案增加中文术语映射。同一意图的两种问法放在相同划分中。开发集选择视觉权重，测试集仅用于报告。

| 划分 | 检索 | Recall@10 | nDCG@10 | MRR@10 |
| --- | --- | ---: | ---: | ---: |
| dev | filename | 0.000 | 0.000 | 0.000 |
| dev | lexical | 0.575 | 0.385 | 0.325 |
| dev | hybrid_equal | 0.475 | 0.257 | 0.189 |
| dev | dev_selected | 0.575 | 0.385 | 0.325 |
| test | filename | 0.000 | 0.000 | 0.000 |
| test | lexical | 0.569 | 0.481 | 0.459 |
| test | hybrid_equal | 0.437 | 0.302 | 0.272 |
| test | dev_selected | 0.569 | 0.481 | 0.459 |

## 仅人工复核且有相关资产的查询

没有相关资产的查询不计入召回率、nDCG 与 MRR。

| 划分 | 查询数 | 检索 | Recall@10 | nDCG@10 | MRR@10 |
| --- | ---: | --- | ---: | ---: | ---: |
| dev | 20 | filename | 0.000 | 0.000 | 0.000 |
| dev | 20 | lexical | 0.575 | 0.385 | 0.325 |
| dev | 20 | hybrid_equal | 0.475 | 0.257 | 0.189 |
| dev | 20 | dev_selected | 0.575 | 0.385 | 0.325 |
| test | 68 | filename | 0.000 | 0.000 | 0.000 |
| test | 68 | lexical | 0.569 | 0.481 | 0.459 |
| test | 68 | hybrid_equal | 0.437 | 0.302 | 0.272 |
| test | 68 | dev_selected | 0.569 | 0.481 | 0.459 |

开发集 nDCG 选择的视觉 RRF 权重为 0，词法权重为 1。候选权重与开发集 nDCG@10 为 0: 0.385，0.1: 0.370，0.25: 0.350，0.5: 0.312，0.75: 0.288，1: 0.257。

## 未命中例

- 找汉代铁匠作坊的圆轮模型 → `meshes/props/han_dockprops.dae`
- 汉代弯刀 → `meshes/props/han_dockprops.dae`
- 找汉朝曲刃短兵器 → `meshes/structural/han_wall_short.dae`
- 找罗马野驴式的抛石器 → `meshes/structural/roman_cc.dae`
- 连射式弩炮 → `meshes/props/siege_artillery/oxybeles_01.dae`
- 竹制城防资产 → `无`
- 找竹木搭出来的可围合门塔 → `无`
- 找有顶层承托石像的台座 → `无`
- 汉代武备存放建筑和组件 → `meshes/props/han_dockprops.dae`
- 汉代可作战的轮式车原型 → `meshes/props/han_dockprops.dae`
- 汉船停泊建筑里的小道具 → `meshes/structural/han_outpost.dae`
- 汉朝辟邪雕像 → `meshes/structural/cult/snake_sculpture.dae`
