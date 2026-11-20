# 前端工作台

`/workbench` 复用 ArtPipe 的 FastAPI、页面模板、导航和静态文件服务。React 与 TypeScript 管理本地工作台交互，Three.js 读取 Blender 导出的 GLB。既有入库预检、历史回放、风险雷达、里程碑、资产目录和参考复用可从侧栏访问。

在仓库根目录运行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build` 构建。运行时无需 Node 服务或 CDN。浏览器需要 WebGL 2 才能绘制模型。用户可旋转、缩放、平移、切换网格及包围盒，并在版本选择器切换原始和处理后模型。QA 报告对照父版本的规则状态与实测值。

阶段验证完成 TypeScript 类型检查、前端构建以及 Python 测试套件。真实浏览器端到端验收记录在测试报告。
