# PyInstaller spec. Build with packaging/build_release.py, not directly: it sets
# R7_RELEASE_NAME and R7_VERSION_FILE from r7convert.__version__.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent
NAME = os.environ["R7_RELEASE_NAME"]
VERSION_FILE = os.environ["R7_VERSION_FILE"]

a = Analysis(
    [str(ROOT / "packaging" / "app.py")],
    pathex=[str(ROOT)],
    binaries=collect_dynamic_libs("OpenImageIO"),
    datas=[(str(ROOT / "assets" / "icon.ico"), "assets")],
    hiddenimports=["OpenImageIO"],
    excludes=["unittest", "pydoc", "doctest", "lib2to3", "test", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=VERSION_FILE,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
