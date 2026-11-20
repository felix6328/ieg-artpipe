# Phase A · 环境审计

检查日期 2026-11-20。Node.js 24.16.0、npm 11.13.0、Git 2.50.1。系统 `/usr/bin/python3` 为 3.9.6，仓库要求 Python 3.11+，使用已安装的 `~/.local/bin/python3.12`（3.12.15、SQLite 3.53.1）。

Blender 位于 `/Applications/Blender.app/Contents/MacOS/Blender`，版本 5.2.1 LTS（`9e2066aef7ef`）。直接后台探针在 Codex 沙盒中因 Metal 初始化崩溃（SIGSEGV），沙盒外相同命令退出 0 且 `bpy.app.background` 为真。系统软件无安装变更。正常本机终端可以直接运行。

| 格式 | 已注册导入 | 已注册导出 |
| --- | --- | --- |
| GLB / glTF | import_scene.gltf | export_scene.gltf |
| FBX | import_scene.fbx；另有 wm.fbx_import | export_scene.fbx |
| OBJ | wm.obj_import | wm.obj_export |

探针使用 `--background --factory-startup --disable-autoexec --python-exit-code 7`，通过 `dir(bpy.ops.*)` 查询。TokenHub 命名环境变量未发现。未读取凭证值。
