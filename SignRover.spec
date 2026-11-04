# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     collect_submodules)

# provider / client 都是运行时按社区动态 import 的，静态分析扫不到，
# 这里整包收集，新增社区时不用再手动补 hiddenimports
hidden = (collect_submodules('communities')
          + collect_submodules('device')
          + collect_submodules('core')
          + collect_submodules('app')
          # Qoder 登录态解密走 cryptography → cffi，cffi 的扩展模块
          # 在 onedir 下常被漏收（报 No module named '_cffi_backend'）
          + ['_cffi_backend', 'cffi', 'certifi'])

# cffi 的 .pyd 不在 collect_submodules 结果里，单独收动态库
binaries = collect_dynamic_libs('cffi')

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=[('tools/icon.ico', '.')] + collect_data_files('certifi'),
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SignRover',
    debug=False,
    icon='tools/icon.ico',
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
    name='SignRover',
)
