# PyInstaller spec: builds 3DScanPostProcessor.exe (GUI) and 3DScanPostProcessorCLI.exe (console)
# into one folder that shares the bundled libraries.
#   .venv\Scripts\pyinstaller 3d_scan_post_processor.spec --noconfirm
from PyInstaller.utils.hooks import collect_all

datas, binaries, hidden = [], [], []
for pkg in ("open3d", "triangle", "fast_simplification", "manifold3d", "trimesh"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += ["scipy.sparse.csgraph", "scipy.sparse.linalg", "networkx", "matplotlib.path"]
excludes = ["torch", "tensorflow", "IPython", "jupyter", "notebook", "ipywidgets", "PyQt5", "PySide6"]

gui_a = Analysis(["scan_gui.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=excludes)
cli_a = Analysis(["process_scan.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=excludes)

gui_pyz = PYZ(gui_a.pure)
cli_pyz = PYZ(cli_a.pure)

gui_exe = EXE(gui_pyz, gui_a.scripts, [], exclude_binaries=True, name="3DScanPostProcessor",
              console=False, upx=False)
cli_exe = EXE(cli_pyz, cli_a.scripts, [], exclude_binaries=True, name="3DScanPostProcessorCLI",
              console=True, upx=False)

coll = COLLECT(gui_exe, gui_a.binaries, gui_a.datas,
               cli_exe, cli_a.binaries, cli_a.datas,
               upx=False, name="3DScanPostProcessor")
