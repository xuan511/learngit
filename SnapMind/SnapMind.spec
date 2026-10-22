# Build on the destination OS. PyInstaller does not cross-compile Windows EXEs.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

root=Path(SPECPATH)
ocr_data,ocr_bins,ocr_hidden=collect_all('rapidocr_onnxruntime')
data=ocr_data+[(str(root/'snapmind/models-manifest.json'),'snapmind')]
a=Analysis(
    [str(root/'run.py')],pathex=[str(root)],
    binaries=ocr_bins+collect_dynamic_libs('onnxruntime'),datas=data,
    hiddenimports=ocr_hidden+['PIL.Image','pypdf','onnxruntime.capi.onnxruntime_pybind11_state'],
    excludes=['tkinter','pytest','IPython','matplotlib','torch','pandas','scipy',
        'PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick',
        'PySide6.QtQml','PySide6.QtQuick','PySide6.QtMultimedia','PySide6.Qt3DCore',
        'PySide6.QtCharts','PySide6.QtDataVisualization','PyQt5','PyQt6','PySide2'],
    noarchive=False,
)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='SnapMind',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(root/'assets/snapmind.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='SnapMind')
