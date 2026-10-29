# 3D Scan Post-Processor

Turns a raw 3D scan (for example an Artec Studio PLY export) of an object standing on a
scanning base into a clean, watertight, downsampled STL that can be imported into CAD
software such as SolidWorks.

It removes scan noise, cuts off the scanning base, closes the bottom with a flat face,
fills holes, downsamples the mesh and writes a closed solid STL. A desktop GUI and a
command-line tool are included.

## Windows installer (no Python needed)

1. Download `3DScanPostProcessor_Setup_<version>.exe` from the
   [Releases](../../releases) page.
2. Run it and follow the wizard. You can install for all users (needs admin rights) or
   just for yourself. It adds a Start menu entry, an optional desktop shortcut and an
   uninstaller (Settings > Apps).
3. Start **3D Scan Post-Processor** from the Start menu. Pick the input scan and the
   output STL, adjust the settings if needed, and click **Process**. When it finishes,
   **View result in 3D** opens the STL in a viewer.

The command-line tool is installed next to the GUI:

```
"C:\Program Files\3DScanPostProcessor\3DScanPostProcessorCLI.exe" scan.ply -o part.stl
```

(For a per-user install, the folder is
`%LOCALAPPDATA%\Programs\3DScanPostProcessor`.)

**Requirements:** 64-bit Windows 10 or 11. Large scans need a lot of memory: a
40-million-triangle scan peaks at about 15–20 GB of RAM, so 32 GB is recommended.

**Security warnings:** the installer is not code-signed yet.

- **SmartScreen** shows "Windows protected your PC". Click **More info** >
  **Run anyway**.
- **Smart App Control** (Windows 11), when it is on, blocks unsigned apps completely and
  offers no override. Run the program from source instead (see below).

## Pipeline

1. **Load**: fast binary PLY reader (40 M triangles in < 1 s); other formats go through trimesh.
2. **Align**: the scanning base plate's top face is found with RANSAC. The model is
   rotated so this plane is `Z = 0` and the object points up `+Z`.
3. **Noise removal**: floating clusters and single points are removed. These are
   connected components smaller than `--min-component` (a fraction of all faces).
4. **Base removal**: everything below `Z = --cut-offset` (default 1 mm) is cut away.
   Triangles that cross the cut are split exactly at the plane.
5. **Flat bottom**: the opening left by the cut is moved down onto the base plane
   (`Z = 0`) and closed with a flat triangulated cap. This keeps the object's full height.
6. **Hole filling**: every other hole is closed at full resolution. Each hole is meshed
   in 2D (Triangle), then the new points are placed by a bilaplacian (thin-plate) solve,
   so the patch follows the curvature of the surrounding surface.
7. **Downsampling**: quadric edge-collapse decimation to `--faces` triangles.
8. **Solid check and repair**: defects are cut out and re-filled until the mesh has no
   boundary and no non-manifold edges. Then the normals are oriented outward.
9. **Output**: a binary STL, plus `*_report.json` (watertight flag, volume, bounds,
   settings), `*_log.txt`, and before/after screenshots.

## Running from source

Setup (Python 3.12):

```
git clone <this repository>
cd <repository folder>
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

GUI:

```
.venv\Scripts\python scan_gui.py
```

Command line:

```
.venv\Scripts\python process_scan.py scan.ply
.venv\Scripts\python process_scan.py scan.ply -o output\part.stl --faces 400000
.venv\Scripts\python process_scan.py --view output\part.stl     # view an STL
.venv\Scripts\python process_scan.py scan.ply --show            # open a 3D viewer at the end
.venv\Scripts\python process_scan.py --help                     # all options
```

Useful options:

| option | meaning |
|---|---|
| `--faces N` | target triangle count (default 300000; this is the minimum accepted resolution, do not go lower) |
| `--min-component F` | debris threshold as a fraction of faces (default 0.001) |
| `--cut-offset MM` | cut height above the base plate (default 1.0). Raise it if the contact zone is noisy. |
| `--no-snap` | put the flat bottom at the cut height instead of on the base plane |
| `--base-plane A B C D` | give the base plane yourself if auto detection picks the wrong plane |
| `--no-base-removal` | for scans without a base plate |
| `--max-hole MM` | only fill holes up to this perimeter |
| `--keep-coords` | write the STL in the original scan coordinates |

## Importing into SolidWorks

File > Open > choose *Mesh Files (*.stl)*. Under **Options**, choose the import type:

- **Graphics body** or **Mesh body**: fast, and handles the 300k triangle output.
- **Solid body**: every triangle becomes a B-rep face, so a 300k mesh imports slowly.
  Do not lower `--faces` to speed it up: below 300k the resolution is not acceptable.

The unit is millimetres.

## Notes and limits

- Through-holes that end at the base (e.g. mounting holes) are closed by the flat
  bottom. If they could not be scanned to the bottom they come out as blind holes.
- Undercuts and deep areas the scanner could not see are closed with a smooth patch.
  Its shape is estimated from the surrounding surface.
- Peak memory for a 40 M triangle scan is about 15–20 GB, and a run takes about 2 minutes.

## Building the Windows installer

```
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

This builds `dist\3DScanPostProcessor\` with PyInstaller. The folder holds
`3DScanPostProcessor.exe` (the GUI) and `3DScanPostProcessorCLI.exe` (the command line; the GUI also
uses it). Inno Setup then packs that folder into
`dist\installer\3DScanPostProcessor_Setup_<version>.exe`.

The exes are not code-signed. Windows SmartScreen will show "Unknown publisher". On PCs
where **Smart App Control** is on, Windows blocks unsigned apps completely. To sign the
build, install a code-signing certificate and set `$env:SIGN_CERT_THUMBPRINT` before
running the script.

To publish a release, bump `AppVersion` in `installer\3DScanPostProcessor.iss`, build,
and attach the installer to a GitHub release:

```
gh release create v1.0.0 dist\installer\3DScanPostProcessor_Setup_1.0.0.exe --title "3D Scan Post-Processor 1.0.0"
```
