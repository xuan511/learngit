# 第三方依赖与模型

SnapMind 自身代码使用 MIT 许可证。以下组件不要求购买商业授权；分发时必须遵循各自许可证。本项目不使用 GPL-only 的 QFluentWidgets 或 PyMuPDF。

| 组件 | 许可证 / 用途 | 上游 |
| --- | --- | --- |
| PySide6 / Qt 6.8.3 / Shiboken6 | LGPLv3；原生 Widgets、Gui、Core、Svg，动态链接 | https://code.qt.io/cgit/pyside/pyside-setup.git/ 与 https://code.qt.io/cgit/qt/qtbase.git/ |
| RapidOCR 1.4.4 | Apache-2.0；OCR 管线 | https://github.com/RapidAI/RapidOCR/tree/v1.4.4 |
| PaddleOCR PP-OCRv4 检测 / 识别模型，v2 分类模型 | Apache-2.0；随 RapidOCR wheel 提供 | https://github.com/PaddlePaddle/PaddleOCR/tree/release/2.7 |
| ONNX Runtime 1.20.1 | MIT；CPU 推理，禁用遥测 | https://github.com/microsoft/onnxruntime/tree/v1.20.1 |
| OpenCV 4.11 | Apache-2.0；图像预处理，wheel 内另含第三方声明 | https://github.com/opencv/opencv/tree/4.11.0 |
| Pillow 11.3 | MIT-CMU | https://github.com/python-pillow/Pillow |
| pypdf 5.9 | BSD-3-Clause；提取 PDF 文本 | https://github.com/py-pdf/pypdf |
| NumPy 1.26 | BSD-3-Clause 及 wheel 内第三方声明 | https://github.com/numpy/numpy |
| Shapely / GEOS | BSD-3-Clause / LGPL-2.1；OCR 几何计算 | https://github.com/shapely/shapely / https://libgeos.org/ |
| pyclipper | MIT（Clipper 上游 Boost Software License） | https://github.com/fonttools/pyclipper |
| Python | PSF；嵌入解释器 | https://www.python.org/downloads/source/ |
| PyInstaller | GPL-2.0-or-later，含 bootloader 分发例外；仅构建工具 | https://pyinstaller.org/en/stable/license.html |

完整、原样的依赖许可证和 wheel 附带的第三方通知在构建时收集到 `licenses/dependencies/`。RapidOCR 与 PaddleOCR 原始 Apache-2.0、Qt LGPLv3 / GPLv3 配套文本保存在 `licenses/`。`DEPENDENCIES.json` 记录该构建实际包含的依赖版本和元数据。

Qt / PySide 对应版本源代码：

- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
- https://download.qt.io/archive/qt/6.8/6.8.3/submodules/
- GEOS 对应源码见实际 wheel 中 `LICENSE_GEOS` 和 https://download.osgeo.org/geos/。

便携目录采用动态库分发，用户可替换兼容版本的 Qt / PySide / GEOS 动态库。允许为调试这些库的修改而进行逆向工程。不得移除许可证、通知或 LGPL 库替换能力。对外分发者需保留与实际构建对应的 LGPL 组件源码及获取方式，履行相应的源码提供义务；上述链接和声明不能替代分发者自身的合规义务。软件没有商业授权检查。

三个 OCR 模型合计 16,189,007 字节（约 15.44 MiB）。模型文件名、精确大小和 SHA-256 见 `models-manifest.json`；它们随便携包 `_internal/rapidocr_onnxruntime/models/` 分发，不在首次运行时联网下载。截图中的测试字体由操作系统提供，不把 Linux Noto 字体打入 Windows 软件。

界面 SVG 图标和应用图标由本项目绘制，使用项目 MIT 许可证。
