# PyInstaller yapilandirmasi.
#
# onedir kullaniliyor, onefile DEGIL: onefile her acilista yuzlerce megabayti
# gecici klasore aciyor ve uygulama saniyelerce gecikmeli basliyor. Kurulumlu
# bir masaustu uygulamasinda bunu odemeye gerek yok.
#
# Modeller pakete GIRMIYOR (large-v3 tek basina 3 GB). Ilk calistirmada
# %LOCALAPPDATA%\Transkript\models altina iniyor.
#
# Calistirma:
#     pyinstaller packaging/palaskript.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

# Uygulamanin ihtiyac duydugu varliklar. assets/installer yalnizca kurulum
# sihirbazi icin, uygulamanin icinde ise yaramiyor; disarida birakiliyor.
# assets/ ICINDEKI HER SEY paketleniyor, tek tek listelenmiyor. Onceki surumde
# liste elle tutuluyordu ve kalp gorselleri unutulmustu: uygulama calisti ama
# altbilgideki kalp gorunmedi. Yeni bir varlik eklenince kimsenin listeyi
# guncellemeyi hatirlamasi gerekmemeli.
#
# assets/installer disarida: yalnizca kurulum sihirbazi kullaniyor, uygulamanin
# icinde ise yaramiyor ve ~2 MB yer kapliyor.
datas = [
    (str(path), f"assets/{path.parent.relative_to(ROOT / 'assets')}".rstrip("/."))
    for path in (ROOT / "assets").rglob("*")
    if path.is_file() and "installer" not in path.relative_to(ROOT / "assets").parts
]
binaries = []
hiddenimports = collect_submodules("palaskript")

# Bu paketler veri dosyalari ve yerel kutuphaneler tasiyor; PyInstaller'in
# otomatik analizi hepsini bulamiyor.
for package in ("ctranslate2", "av", "onnxruntime", "faster_whisper", "tokenizers", "yt_dlp"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:  # noqa: BLE001 - paket yoksa atla, hata analizde cikar
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# Kullanilmayan Qt modulleri paketi gereksiz sisiriyor.
excluded_qt = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

excludes = excluded_qt + [
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "notebook",
    "tkinter",
    "pytest",
    "torch",
    "transformers",
]

a = Analysis(
    [str(ROOT / "run_palaskript.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Palaskript",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Pencereli uygulama: konsol penceresi acilmasin.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Palaskript",
)
