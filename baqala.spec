# -*- mode: python ; coding: utf-8 -*-
# بناء: pyinstaller --noconfirm baqala.spec   →  dist\BaqalaPOS\BaqalaPOS.exe
import os

icon = "assets/app.ico" if os.path.exists("assets/app.ico") else None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("baqala/assets/fonts", "baqala/assets/fonts")],
    hiddenimports=["PyQt5.QtPrintSupport"],
    excludes=["tkinter", "PyQt5.QtWebEngineWidgets", "PyQt5.QtQml", "PyQt5.QtQuick", "PyQt5.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BaqalaPOS", console=False, icon=icon, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BaqalaPOS")
