# ArtPipe 四分钟演示

## 第一段 · 美术审核

1. 在入库预检页打开「#6738 修复前」。选中竹子贴图，指出 PNG 与 DDS 在同一路径下重名，报告能定位到这批文件需要合并前确认的项。
2. 点「#6738 修复后」，看五条命中归零。打开历史回放，查 `bamboo`。对照引入和修复提交，区分单一格式文件的年龄和两种格式同时存在的时长。
3. 切换到「当前版本」，打开错等级部件文件，查看引用方、变体文件和网格路径。需要精确到批次时填入基准与目标版本。

```bash
.venv/bin/python -m artpipe check --rev 'eafacb6e2^' --rules R1
.venv/bin/python -m artpipe check --rev eafacb6e2 --rules R1
.venv/bin/python -m artpipe check --rev HEAD --rules R2,R5
```

## 第二段 · 制作会

打开「风险雷达」，输入 8414。点开对应原评论，从依赖出现看到解除，再到返工、重叠贡献和授权。停滞由最后活动日期算出。指出每条证据如何帮助制作人在会上找到需要确认的人。

```bash
.venv/bin/python -m artpipe ingest --issue 8414
.venv/bin/python -m artpipe radar --issue 8414
FB_ENV_FILE='<本机总配置路径>' .venv/bin/python -m artpipe radar --issue 8414 --model --format json --output data/radar-8414.json
```

## 第三段 · 复用原型

进入「资产复用」，搜索「找攻城锤的整体模型」，选「攻城器械」。对比缩略图、面数和上游文件。用更低的三角面数上限再搜一次，演示团队如何用结构条件收窄候选。

```bash
.venv/bin/python scripts/search_assets.py '找攻城锤的整体模型' --category siege --visual
```

[工作台](http://127.0.0.1:8765/) · [上游 Issue #8414](https://gitea.wildfiregames.com/0ad/0ad/issues/8414)
