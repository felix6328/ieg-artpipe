# Phase A · 项目审计

会话目录仅有附件与空工作目录。定位到干净的 ArtPipe 仓库 `2026-11-18/do-you-know-fable5-2-with/work/ieg-artpipe`，基线提交 `b40bdcd`。历史任务明确记载 ArtPipe 继承 ArtGate 和 PipeSched。较早的 ArtGate 参考 checkout 不是干净工作树。将 ArtPipe 复制到本任务的交付目录，保留基线历史与原始 checkout。

| 审计项 | 基线 |
| --- | --- |
| 目录 | `artpipe/` 为 Web 和 CLI；`configs/` 为 YAML；`tests/` 为离线测试；`eval/`、`docs/research/` 和 `labels/` 为既有证据 |
| 前端 | Jinja2 服务端模板与 CSS，无 React 工程或实时查看器 |
| 后端 | FastAPI、Uvicorn、ArtPipe CLI |
| 数据库 | `data/artpipe.sqlite` 存上游目录、Git 修订、议题、评论、里程碑等 |
| 工作台 | 入库预检、Git 历史回放、风险雷达、里程碑、资产目录和参考复用 |
| QA | R1 重复贴图、R2 等级错用、R3 PNG 元数据、R4 贴图尺寸、R5 引用、R6 命名；内容抽查涵盖 Collada 面数 / UV |
| 版本 | 基于 Git revision/range 的上游版本对照，未建本地上传模型的版本链、处理队列和审核记录 |
| 研究 | `docs/research/调研报告.md`、`eval/replay.md`、`eval/head-precheck.md`、`eval/acceptance.md`、`eval/content-audit.md`；基于真实 0 A.D. 历史，继承既有样本口径 |
| 测试 | 从仓库根目录运行基线 `python -m pytest -q`，7 项通过 |
| 启动 | `scripts/run_app.sh` 启动 `artpipe.web:app`，默认绑定 `127.0.0.1:8765` |
