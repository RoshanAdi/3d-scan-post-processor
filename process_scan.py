"""Post-process a 3D scan (PLY) of an object on a scanning base into a watertight STL solid.

Steps: remove noise/debris -> remove the scanning base -> flat cap on the bottom ->
fill holes -> downsample -> watertight check/repair -> binary STL (+ screenshots, report).

Example:
    .venv\\Scripts\\python process_scan.py scan.ply
    .venv\\Scripts\\python process_scan.py scan.ply -o out\\part.stl --faces 400000 --show
    .venv\\Scripts\\python process_scan.py --view out\\part.stl
"""
import argparse
import os
import sys

from artec_post.pipeline import Settings, process


def view(path):
    import trimesh
    from artec_post.visualize import show
    m = trimesh.load(path, process=True)
    show(m.vertices, m.faces, path)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)  # stream the log live to the GUI
    if len(argv) == 2 and argv[0] == "--view":
        return view(argv[1])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="input scan (.ply, also .stl/.obj via trimesh)")
    ap.add_argument("-o", "--output", help="output STL (default: output/<name>.stl)")
    ap.add_argument("--faces", type=int, default=Settings.target_faces,
                    help="target triangle count after downsampling (default %(default)s)")
    ap.add_argument("--min-component", type=float, default=Settings.min_component_frac,
                    help="debris threshold: fraction of faces (default %(default)s)")
    ap.add_argument("--keep-all-components", action="store_true",
                    help="keep every component above the debris threshold, not only the largest")
    ap.add_argument("--no-base-removal", action="store_true", help="do not detect/remove the base plate")
    ap.add_argument("--base-plane", type=float, nargs=4, metavar=("A", "B", "C", "D"),
                    help="base plane a*x+b*y+c*z+d=0 in input coordinates (skips auto detection)")
    ap.add_argument("--plane-threshold", type=float, default=Settings.plane_threshold_mm,
                    help="RANSAC distance tolerance for the base plane in mm (default %(default)s)")
    ap.add_argument("--cut-offset", type=float, default=Settings.cut_offset_mm,
                    help="cut height above the base plane in mm (default %(default)s)")
    ap.add_argument("--no-snap", action="store_true",
                    help="put the flat bottom at the cut height instead of on the base plane")
    ap.add_argument("--max-hole", type=float, default=Settings.max_hole_perimeter_mm,
                    help="only fill holes with perimeter up to this (mm, default: all)")
    ap.add_argument("--keep-coords", action="store_true",
                    help="write the STL in the original scan coordinates (default: base on z=0, +Z up)")
    ap.add_argument("--no-screenshots", action="store_true")
    ap.add_argument("--save-intermediate", action="store_true", help="also save full-res filled PLY")
    ap.add_argument("--show", action="store_true", help="open an interactive 3D viewer at the end")
    a = ap.parse_args(argv)

    out = a.output or os.path.join("output", os.path.splitext(os.path.basename(a.input))[0] + ".stl")
    s = Settings(
        min_component_frac=a.min_component,
        keep_largest_only=not a.keep_all_components,
        remove_base=not a.no_base_removal,
        base_plane=a.base_plane,
        plane_threshold_mm=a.plane_threshold,
        cut_offset_mm=a.cut_offset,
        snap_bottom_to_plane=not a.no_snap,
        max_hole_perimeter_mm=a.max_hole,
        target_faces=a.faces,
        align_to_base=not a.keep_coords,
        screenshots=not a.no_screenshots,
        save_intermediate_ply=a.save_intermediate,
    )
    viewer = None
    if a.show:
        from artec_post.visualize import show
        viewer = lambda v, f: show(v, f, "result")
    res = process(a.input, out, s, viewer=viewer)
    ok = res.report["watertight"] and res.report["nonmanifold_edges"] == 0
    print("\nRESULT:", "watertight solid" if ok else "WARNING - not fully watertight", "->", out)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
