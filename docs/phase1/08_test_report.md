# Phase G · 测试报告

验证日期 2026-11-20。本机使用 macOS、Python 3.12.15、Blender 5.2.1 LTS 和 Chrome。真实样本由 `scripts/create_assetgate_fixtures.py` 程序化生成，其缺陷是确定的测试条件。

## 执行方式

默认测试运行 ArtPipe 基线、文件校验、规则和队列测试。测试夹具中的 Mock Adapter 会标记 `MOCK`，覆盖失败、重试、取消、恢复和 STALE。产品运行只接入真实 Blender。

```bash
.venv/bin/python -m pytest -q
ASSETGATE_REAL_TESTS=1 .venv/bin/python -m pytest -q
npm --prefix frontend run build
```

浏览器测试需生成样本，并用隔离存储启动本地服务。[样本生成命令](09_demo.md)

```bash
ASSETGATE_STORAGE="$(mktemp -d)" ARTPIPE_PORT=18765 scripts/run_app.sh
```

另开终端，从仓库根目录运行以下命令。Linux 可以指定已安装的 Chromium，也可通过 Playwright 安装测试浏览器。

```bash
ASSETGATE_URL=http://127.0.0.1:18765 \
  ASSETGATE_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  npm --prefix frontend run test:browser -- "$PWD/data/assetgate-fixtures/missing_uv.glb"
```

真实 Blender 集成应在本机终端运行。若机器缺少 Blender 或后台模式不可用，真实用例为 **BLOCKED**，默认测试仍可运行。当前 Codex 沙盒中的 Metal 初始化失败，真实验收在沙盒外完成。

## 实测结果

| 验证 | 结果 |
| --- | --- |
| 默认 Python 测试 | **26 通过，16 跳过**。含 7 项 ArtPipe 基线用例、上传与路径校验、QA、Mock 工作流和子进程超时/取消 |
| 含真实 Blender 的完整套件 | **42 通过**。其中 16 项启用真实 Blender，覆盖操作符探测、六类样本、四种格式往返、四种带贴图资产包和失败后重新执行 |
| 前端构建 | TypeScript 类型检查和生产 bundle 均通过 |
| Chrome 网页端到端 | 上传真实 GLB，加载 WebGL 2，操作相机、切换网格和包围盒，运行 Smart UV，对照 V1/V2 QA，审核并下载 ZIP。另检查任务队列、窄屏布局和既有入库预检入口 |

| 样本 | 真实 Blender 结果 |
| --- | --- |
| 正常 GLB | UV 图层通过，生成可加载的 GLB 预览 |
| 缺 UV 的 GLB | 初检提醒；处理为 GLB、glTF、FBX 或 OBJ 后再导入，UV 图层通过 |
| 无有效几何 | 导入成功，三角面检查阻断 |
| 缺外部贴图的 OBJ ZIP | QA 找到 `mesh/albedo.png` 缺失，引用检查阻断 |
| 超过面数预算 | 三角面检查阻断 |
| 多 Mesh 的 GLB | 识别多个 Mesh Object |
| 含贴图的 OBJ ZIP | 四种目标格式重新导入后保留 32×32 贴图。GLB/FBX 保留嵌入数据，glTF/OBJ 的 ZIP 保留 PNG，并核对 Manifest 逐文件哈希 |

OBJ 回归最初发现 Blender 生成 MTL 后未复制打包贴图。修复后由适配器物化贴图并生成可解析的包内相对路径，相关真实用例通过。Unreal Engine 导入验证为 **NOT_CHECKED**。
