# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui.py'],
    pathex=['.\\.venv\\Lib\\site-packages\\'],
    binaries=[
        ('.\\.venv\\Lib\\site-packages\\paddle\\libs\\mklml.dll', '.'),
        ('.\\.venv\\Lib\\site-packages\\paddle\\libs\\libiomp5md.dll', '.')
    ],
    datas=[
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\tools', 'paddleocr/tools'),
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\ppocr', 'paddleocr/ppocr'),
        ('.\\.venv\\Lib\\site-packages\\paddleocr\\ppstructure', 'paddleocr/ppstructure'),
         # 添加 Cython Utility 文件
        ('.\\.venv\\Lib\\site-packages\\Cython\\Utility\\*', 'Cython/Utility'),
    ],
hiddenimports=['paddleocr.tools', 'ppocr', 'shapely', 'pyclipper', 'skimage', 'skimage.morphology', 'imgaug', 'albumentations', 'lmdb', 'docx'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
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
