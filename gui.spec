# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui.py'],
    pathex=['.\\.venv\\Lib\\site-packages\\'],
    binaries=[
        ('.\\.venv\\Lib\\site-packages\\paddle\\libs\\mklml.dll', '.'),
    ],
    datas=[
        ('data', 'data'),
        ('icon', 'icon'),
        ('plugins', 'plugins'),
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\tools', 'paddleocr/tools'),
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\ppocr', 'paddleocr/ppocr'),
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\ppstructure', 'paddleocr/ppstructure'),
    ],
    hiddenimports=[
        # PaddleOCR imports these modules dynamically.
        'paddleocr.tools', 'ppocr', 'shapely', 'pyclipper', 'skimage',
        'skimage.morphology', 'imgaug', 'lmdb',
        'requests', 'urllib3', 'chardet', 'idna', 'certifi',
        'win32api',
        'plugin_platform.worker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # These packages are optional features or development-only dependencies.
    # Excluding them avoids pulling in large model/LLM stacks that gui.py does
    # not use.  OCR, OpenCV, PaddlePaddle and SciPy remain included.
    excludes=[
        'torch', 'torchvision', 'torchaudio', 'ultralytics',
        'matplotlib', 'matplotlib.backends',
        'langchain', 'langchain_community', 'openai',
        'speech_recognition', 'pyaudio',
        # Cython is only needed to build PaddleOCR's optional training
        # utilities; the frozen application runs precompiled extensions.
        'Cython',
        # Table/PDF export support is not part of this app; OCR uses only the
        # text pipeline and does not need lxml/docx/BeautifulSoup.
        'lxml', 'docx', 'bs4',
        # The application uses Qt Widgets only; these optional Qt modules
        # pull in the Quick/QML and OpenGL software-rendering stack.
        'PyQt5.QtQuick', 'PyQt5.QtQml', 'PyQt5.QtQmlModels',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PyInstaller's PyQt hook collects every Qt runtime DLL.  Search Cat uses
# QWidget/QImage/QPixmap and does not create Qt Quick/OpenGL scenes, so the
# software renderer and unused fallback platform plugins are unnecessary.
# Keeping this filter in the spec makes the size reduction reproducible.
_unused_runtime_files = {
    'PyQt5/Qt5/bin/opengl32sw.dll',
    'PyQt5/Qt5/bin/libGLESv2.dll',
    'PyQt5/Qt5/bin/Qt5Quick.dll',
    'PyQt5/Qt5/bin/Qt5Qml.dll',
    'PyQt5/Qt5/bin/Qt5QmlModels.dll',
    'PyQt5/Qt5/bin/d3dcompiler_47.dll',
    'PyQt5/Qt5/plugins/platforms/qoffscreen.dll',
    'PyQt5/Qt5/plugins/platforms/qminimal.dll',
    'PyQt5/Qt5/plugins/platforms/qwebgl.dll',
    # OpenCV's FFmpeg bridge is only used for video I/O.  Search Cat captures
    # screenshots and processes still images, so cv2 imports without it.
    'cv2/opencv_videoio_ffmpeg4100_64.dll',
    'PyQt5/Qt5/bin/Qt5Network.dll',
    'PyQt5/Qt5/bin/Qt5DBus.dll',
    'PyQt5/Qt5/bin/Qt5Svg.dll',
}
a.binaries = [entry for entry in a.binaries if entry[0].replace('\\', '/') not in _unused_runtime_files]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='gui',
)
