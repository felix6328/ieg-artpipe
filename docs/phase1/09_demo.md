# 3–5 分钟演示

启动服务，打开 [AssetGate](http://127.0.0.1:8765/workbench)。使用随本机交付生成的 `data/assetgate-fixtures/missing_uv.glb`。这是由 Blender 程序化生成的运输箱，几何真实可读取，缺 UV 是预设的测试条件。

如需重新生成，在 macOS 仓库根目录执行以下命令。Linux 使用已安装 Blender 的可执行文件替换首行。

```bash
BLENDER_BIN="${ASSETGATE_BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
"$BLENDER_BIN" --background --factory-startup --disable-autoexec --python-exit-code 7 \
  --python scripts/create_assetgate_fixtures.py -- "$PWD/data/assetgate-fixtures"
```

1. 在总览点「上传模型」，选择 `missing_uv.glb`。上传后等待后台 QA 和预览完成。
2. 在「概览」拖动模型、缩放、平移，切换网格、包围盒。查看三角面和有 UV 的网格数量。
3. 打开「QA 报告」，找到「UV 图层」的提醒，展开证据。
4. 打开「模型处理」，勾选 Smart UV Project，目标设为 GLB，点击「开始处理」。在「处理记录」中查看节点进度。
5. 新版本出现后查看「QA 报告」的处理前后两列。验证 UV 图层由提醒变为通过。用版本选择器切换 V1 和 V2，观察预览与报告。
6. 在「审核与导出」中填写审核人，检查 V2 后保存「通过」。点击「生成 ZIP」并下载。解压检查模型、Manifest、QA、节点记录、审核决定和版本链。

贴图与几何案例可继续上传以下样本。

| 样本 | 观察项 |
| --- | --- |
| `normal.glb` | 正常模型、有效 UV、可交互预览 |
| `no_geometry.glb` | 可导入场景但没有有效网格 |
| `missing_texture.zip` | 包内缺失 `mesh/albedo.png` |
| `over_budget.glb` | 三角面超出默认预算 |
| `multiple_meshes.glb` | 多个可见 Mesh Object |
| `with_texture.zip` | 32×32 外部 PNG，可转换并核对贴图 |
