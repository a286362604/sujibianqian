# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：pyinstaller build.spec
# 产物：dist/速记便签.exe（单文件，无控制台）

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('便签应用.html', '.'), ('icon.ico', '.')],
    # 🔴 图片功能依赖 Pillow：ImageTk（Tk 显示）/ ImageGrab（剪贴板粘贴）都是隐式依赖，
    #    显式写进来，避免打出来的 exe 缺模块导致「插图可用、粘贴图片失效」。
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageGrab'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # pywebview 支持多 GUI 后端，hook-qtpy 会把本机 PyQt5 整套打进包
        # （QtCore/QtWidgets/QtGui，+40MB 且显著拖慢冷启动）。Windows 上实际用的是
        # WebView2(winforms) 后端，Qt / GTK 后端一律排除。
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'qtpy',
        'gi', 'gtk',
        # 体积大且本项目完全用不到
        'numpy', 'matplotlib', 'scipy', 'pandas',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='速记便签',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
