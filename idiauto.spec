# PyInstaller spec para idiAuto (Textual + Playwright)
# Uso:
#   pyinstaller idiauto.spec --noconfirm
# El binario queda en dist/idiauto (Linux) o dist/idiauto.exe (Windows).

import os
import glob
import sys
from PyInstaller.utils.hooks import (
    collect_submodules, collect_data_files, copy_metadata, collect_all,
)

hidden = []
hidden += collect_submodules("textual")
hidden += collect_submodules("playwright")
hidden += collect_submodules("keyring")
hidden += collect_submodules("keyring.backends")
hidden += ["html2text", "secretstorage", "jeepney", "win32ctypes"]

# collect_all incluye datas + binaries + hiddenimports de un paquete
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")
tx_datas, tx_binaries, tx_hidden = collect_all("textual")

datas = []
datas += pw_datas
datas += tx_datas
datas += copy_metadata("textual")
datas += copy_metadata("playwright")
datas += copy_metadata("keyring")

binaries = []
binaries += pw_binaries
binaries += tx_binaries

# Incluir el directorio driver completo preservando estructura.
try:
    import playwright
    pw_root = os.path.dirname(playwright.__file__)
    driver_dir = os.path.join(pw_root, "driver")
    if os.path.isdir(driver_dir):
        datas.append((driver_dir, "playwright/driver"))
        n = sum(len(f) for _, _, f in os.walk(driver_dir))
        print(f"[spec] Incluyendo playwright/driver ({n} archivos)")
    else:
        print(f"[spec] WARN: driver_dir no existe: {driver_dir}")
except Exception as e:
    print(f"[spec] WARN playwright driver: {e}")

# Incluir chromium headless + ffmpeg pre-descargados.
# Solo bundle del headless_shell porque la app usa headless=True.
try:
    browsers_cache = os.path.expanduser("~/.cache/ms-playwright")
    if os.path.isdir(browsers_cache):
        for entry in sorted(os.listdir(browsers_cache)):
            if entry.startswith("chromium_headless_shell-") \
               or entry.startswith("ffmpeg-"):
                src = os.path.join(browsers_cache, entry)
                datas.append((src, f"ms-playwright/{entry}"))
                print(f"[spec] Incluyendo navegador: {entry}")
    else:
        print(f"[spec] WARN: {browsers_cache} no existe. "
              f"Ejecuta: playwright install chromium")
except Exception as e:
    print(f"[spec] WARN browsers: {e}")

hidden += pw_hidden + tx_hidden

a = Analysis(
    ["tui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="idiauto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
