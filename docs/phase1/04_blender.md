# Blender 接入

安装 Blender 桌面发行版后，设置 `ASSETGATE_BLENDER=/绝对路径/blender`，或将可执行文件加入 PATH。macOS 默认会尝试 `/Applications/Blender.app/Contents/MacOS/Blender`。若版本无法后台启动，先用同一用户的本机终端执行环境审计中的命令。

适配器在任务目录内复制输入、生成输出和运行日志。使用参数数组启动后台子进程，禁用用户脚本自动执行并使用工厂配置。模型输出、JSON、标准输出和错误输出分开记录。超时和取消会结束子进程组。支持在本机以串行方式运行。

Blender 启动后探测实际注册的操作符。OBJ 优先使用 `wm.obj_import/obj_export`，并识别旧构建的 `import_scene.obj/export_scene.obj`。FBX 使用带可限域贴图读取的 `import_scene.fbx`；缺失该操作符的构建会明确报不支持。受限贴图加载允许包内文件和嵌入资源，外部路径会记录到检查结果。
