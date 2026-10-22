# 测试报告

本报告区分 Linux 当前实例、GitHub Windows 运行器和真实用户桌面三种验证。Linux 与 Windows 自动化 GUI 检查使用 Qt offscreen；它们运行真实桌面 Widgets，不能据此推断全局快捷键、多显示器或混合 DPI 已人工验收。

## 已完成验证

自动化测试覆盖首次窗口、导航、主题切换、异步任务异常隔离、五条剪贴板历史、自复制去重、HTML / 图片 / 文件列表、大小限制、暂停恢复、搜索与编辑自动保存、原始 OCR 保留、框选坐标缩放、Esc、标注撤销重做、PDF 提取、文件失效、SQLite 持久化、FTS 与中文回退、日期 / 标签 / 收藏 / 类型过滤、分页、删除引用保护、保留期、备份恢复和恶意路径拒绝。

真实离线 OCR 使用三个 wheel 内置 ONNX 模型，测试图片包含中文、英文、`0x09F0`、`int value = 42;` 与 `git status --short`。没有用预设文本替换识别结果。Python socket 连接在该测试中被禁止；另行通过系统调用跟踪检查本机运行网络访问。

模拟 Windows API 的测试只验证冲突处理和保留原热键的代码契约；这不等于真实 Windows 热键注册通过。基于 offscreen 的坐标测试验证了单屏 2x 像素换算；这不等于真实多屏 / 混合 DPI 截图通过。

2026-10-22 验证：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --junitxml=docs/test-results.xml` 已通过 65 项测试，零失败、零跳过，用时 15.21 秒。机器可读结果保存在 `test-results.xml`；`ruff check snapmind tests tools` 通过。包含文件选择 / 确认对话框期间新增任务的竞态回归测试，防止恢复或备份与新 OCR 任务并发；还验证了再次截图关闭旧预览，以及选区出现前的重复快捷键防护。

预览右侧直接显示实际识别结果，截图为 `screenshots/ocr-result.png`。首页、深色主题和知识详情的实际 Qt 渲染截图也保存在 `screenshots/`；其中示例数据只存在于临时测试目录，不会预置到正式用户数据库。

构建命令 `.venv/bin/python -m tools.build --target native` 成功生成 Linux onedir 便携验证包。已直接运行打包后的 `SnapMind --smoke`，以及 `SnapMind --verify-ocr <技术图片>`，验证独立二进制启动、内置模型识别和 SQLite 写入。模型校验通过，三个模型总计 16,189,007 字节。Linux ZIP 约 262 MiB，普通 ZIP 解压约 700 MiB（ZIP 中将 Linux 共享库链接展开为文件）；主要依赖占用来自 Qt、OpenCV、NumPy 计算库及 ONNX Runtime。Windows Actions 产物显示约 132 MB。

源码包中的 `package-validation-linux.json` 记录仓库外中文路径解压测试、移除 Python 开发环境变量后的二进制启动、实际 OCR、重启持久化、数据库完整性和二进制 SHA-256。`network-trace-linux.txt` 为同次已打包 OCR 的系统调用跟踪：未观察到 IP socket 或 connect 调用。该结果只对应所测流程，不代表所有第三方组件在任何配置下的网络行为。运行程序不包含任何在线 OCR、模型下载或账号逻辑。

## 性能测量

原始结果见 `benchmark-linux.json`。平台为 Linux x64、Python 3.12.14、Qt offscreen；1150×300 合成技术文字图片，10001 条持久化历史。不是 Windows 速度保证，也不是截图正确率基准。

已测窗口就绪约 0.232 秒，初始 RSS 90.8 MiB，2.03 秒空闲采样 CPU 约单核 0.98%；首次 OCR（含模型加载）1.521 秒，后续三次 0.687 / 0.656 / 0.672 秒，OCR 后 RSS 370.4 MiB。识别后立即进行 2.03 秒空闲采样，CPU 约单核 2.46%；这个短时样本不能用来声称长期空闲占用为零。OpenCV 和 ONNX 均限制为 2 个计算线程，OCR 不运行轮询循环。搜索五次中位数：`0x09F0` 4.789 ms，`09F` 4.097 ms，中文“寄存器”5.451 ms，无命中中文查询含近似回退 44.431 ms。环境负载、字体和输入图片都会影响数据。

## Windows 自动化验证与人工验收

2026-10-22，[GitHub Actions Windows 构建 #4](https://github.com/xuan511/learngit/actions/runs/39713524352) 成功，耗时 3 分 2 秒，提交 `5768368def0fb643b6b3fbeb2eb46655d89ffb84`。工作流的测试与打包步骤、诊断步骤及产物上传均为 success。Windows 脚本会在任何测试失败、打包失败、EXE 启动失败或识别结果未持久化时返回失败；此轮全部通过。

已完成 Windows 源码自动化测试、三个 ONNX 模型校验、PyInstaller onedir 构建、打包后 EXE 的 offscreen 窗口启动，以及使用内置模型识别技术图片并在数据库中验证 `0x09F0`。便携 ZIP 与 SHA-256 已上传到 **SnapMind-Windows-x64** Artifact。构建元数据记录于 `package-validation-windows.json`；下载需登录 GitHub。

以下项目仍需真实用户桌面人工验收：

- Windows 10 / 11 x64 原生 GUI 启动、关闭 / 最小化托盘、重复启动提示。
- 在其他应用前台时的三个全局快捷键、真实占用冲突提示、修改与恢复。
- 100% / 125% / 150% / 200% DPI、多显示器、负坐标显示器、单显示器范围捕获。
- Windows 真实剪贴板：浏览器 HTML、VS Code、资源管理器文件列表、图像、大内容、黑名单和前台权限失败。
- 从新解压的便携文件夹运行，无 Python，断网，中文路径，实际 OCR 模型加载。
- 快速连续框选、窗口焦点、线程结束退出、默认 PDF 阅读器、外部路径重新定位。
- 场景 A 到 E 按任务书人工验收；同目录所有依赖一并迁移到另一台兼容 Windows 机器。

Windows 包是在 GitHub 的 Windows 运行器构建，当前云端开发机仍是 Linux；未进行 Linux 到 Windows 的交叉编译。Windows 本机启动速度、内存及普通笔记本上的 OCR 性能尚未测量，前文性能数值仅来自 Linux。

## 已知限制

- Windows EXE 已通过运行器上的启动与离线 OCR 验证，普通 Windows 桌面的原生交互和全新机器迁移仍待人工验收；Linux 包仅用于 Linux 验证。
- 单次选区限定在一个显示器内，不拼接跨屏截图。
- PDF 仅提取可选文本，扫描页请截图 OCR；不解密加密 PDF。PDF 关联页码保存并显示，外部阅读器不自动跳页。
- 英文近似搜索最多扫描最近 1000 条，不保证全库模糊召回；精确 / 子串搜索覆盖全部数据库。
- “私密”不是加密，黑名单不是机密内容识别器；备份为明文。
- 标注以副本保存；原图与原 OCR 保留。
- 恢复保留的旧数据目录需要用户确认后自行删除；配置文件不随数据 ZIP 导出。
