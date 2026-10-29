"""End-to-end processing of an Artec scan into a watertight STL solid."""
import json
import os
import time
from dataclasses import dataclass, asdict, field

import numpy as np

from .mesh_io import load_mesh, write_stl, write_ply
from .mesh_ops import (remove_small_components, remove_degenerate, remove_nonmanifold_faces,
                       boundary_loops, loop_perimeter)
from .base_removal import (detect_base_plane, aligning_transform, apply_transform, cut_below,
                           find_cut_loops, cap_planar)
from .hole_filling import fill_holes
from .solidify import decimate, solid_report, orient_outward, make_watertight, flatten_bottom


@dataclass
class Settings:
    # noise / debris
    min_component_frac: float = 0.001   # drop components smaller than this fraction of faces
    keep_largest_only: bool = True      # finally keep only the biggest piece (the scanned object)
    # base (stand plate) removal
    remove_base: bool = True
    base_plane: list = None             # [a, b, c, d] to override auto detection (a*x+b*y+c*z+d=0)
    plane_threshold_mm: float = 0.3     # RANSAC inlier distance for the base plane
    cut_offset_mm: float = 1.0          # cut this far above the base plane (skips the noisy contact zone)
    snap_bottom_to_plane: bool = True   # move the cut edge down onto the base plane before capping
    # holes
    max_hole_perimeter_mm: float = float("inf")
    # downsampling
    target_faces: int = 300_000
    # output
    align_to_base: bool = True          # output with flat bottom on z=0 and +Z up
    screenshots: bool = True
    save_intermediate_ply: bool = False


@dataclass
class Result:
    stl_path: str
    report: dict
    screenshots: list = field(default_factory=list)
    log: list = field(default_factory=list)


def process(input_path, output_stl, settings=None, out_dir=None, log=print, viewer=None):
    s = settings or Settings()
    t0 = time.time()
    out_dir = out_dir or os.path.dirname(os.path.abspath(output_stl))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(output_stl))[0]
    lines = []

    def say(msg):
        msg = f"[{time.time() - t0:7.1f}s] {msg}"
        lines.append(msg)
        log(msg)

    # 1. load
    say(f"Loading {input_path}")
    v, f = load_mesh(input_path, log=say)
    say(f"  {len(v):,} vertices, {len(f):,} faces")
    v, f = remove_degenerate(v, f)

    # 2. align to the base plane
    T = np.eye(4)
    if s.remove_base or s.align_to_base:
        if s.base_plane is not None:
            p = np.asarray(s.base_plane, float)
            nrm, d = p[:3] / np.linalg.norm(p[:3]), p[3] / np.linalg.norm(p[:3])
            say(f"  using given base plane normal={nrm}, d={d:.3f}")
        else:
            say("Detecting base plane")
            nrm, d = detect_base_plane(v, s.plane_threshold_mm, log=say)
        T = aligning_transform(nrm, d)
        v = apply_transform(v, T)

    shots = []
    if s.screenshots:
        shots += _shots(v, f, os.path.join(out_dir, f"{stem}_0_input"), say)

    # 3. remove debris (floating noise clusters / single points)
    say("Removing noise / debris components")
    v, f, nc, nf = remove_small_components(v, f, s.min_component_frac)
    say(f"  removed {nc:,} small components ({nf:,} faces)")

    # 4. cut away the base
    z_cut = s.cut_offset_mm
    if s.remove_base:
        say(f"Cutting off the base below z={z_cut} mm (base top face at z=0)")
        n0 = len(f)
        v, f = cut_below(v, f, z_cut)
        say(f"  removed {n0 - len(f):,} faces")
    v, f, nc, nf = remove_small_components(v, f, s.min_component_frac,
                                           keep_largest_only=s.keep_largest_only)
    say(f"  after cut: removed {nc:,} disconnected pieces ({nf:,} faces); {len(f):,} faces left")
    v, f = remove_nonmanifold_faces(v, f)

    # 5. cap the bottom opening flat
    z_cap = None
    loops = boundary_loops(f)
    per = np.array([loop_perimeter(v, lp) for lp in loops]) if loops else np.zeros(0)
    say(f"Found {len(loops):,} boundary loops (holes); largest perimeters: "
        f"{np.round(np.sort(per)[::-1][:5], 1).tolist()} mm")
    if s.remove_base:
        bottom = find_cut_loops(v, loops, z_cut)
        if bottom:
            say(f"Capping bottom opening flat ({len(bottom)} loop(s), main perimeter "
                f"{loop_perimeter(v, bottom[0]):.1f} mm)")
            z_cap = 0.0 if s.snap_bottom_to_plane else z_cut
            # use only the main loop and loops lying inside it
            from matplotlib.path import Path
            outer = Path(v[bottom[0], :2])
            use = [bottom[0]] + [lp for lp in bottom[1:] if outer.contains_points(v[lp[:1], :2])[0]]
            v, cap = cap_planar(v, use, z_cap)
            f = np.vstack([f, cap])
            say(f"  cap: {len(cap):,} triangles at z={z_cap}")
        else:
            say("  WARNING: no opening found on the cut plane")

    # 6. fill holes (full resolution)
    say("Filling holes (full resolution)")
    v, f, nfill, nskip = fill_holes(v, f, s.max_hole_perimeter_mm, log=say)
    say(f"  filled {nfill:,} holes, skipped {nskip:,}; {len(f):,} faces")
    if s.save_intermediate_ply:
        write_ply(os.path.join(out_dir, f"{stem}_filled_fullres.ply"), v, f)

    # 7. downsample
    say(f"Downsampling to ~{s.target_faces:,} faces")
    v, f = decimate(v, f, s.target_faces)
    v, f, nc, nf = remove_small_components(v, f, s.min_component_frac,
                                           keep_largest_only=s.keep_largest_only)
    say(f"  {len(f):,} faces (removed {nc} loose pieces)")

    # 8. make a clean closed solid
    say("Making watertight solid")
    v, f = make_watertight(v, f, log=say)
    if z_cap is not None:
        v = flatten_bottom(v, f, z_cap)
    v, f = orient_outward(v, f)
    rep = solid_report(v, f)
    say("  " + json.dumps(rep))

    # 9. write
    if not s.align_to_base:
        v = apply_transform(v, np.linalg.inv(T))
    write_stl(output_stl, v, f)
    say(f"Wrote {output_stl} ({os.path.getsize(output_stl) / 1e6:.1f} MB)")
    if s.screenshots:
        vv = v if s.align_to_base else apply_transform(v, T)
        shots += _shots(vv, f, os.path.join(out_dir, f"{stem}_1_result"), say, views=("front", "side", "back", "bottom"))
    rep["settings"] = asdict(s)
    rep["transform_to_aligned"] = T.tolist()
    rep["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, f"{stem}_report.json"), "w") as fh:
        json.dump(rep, fh, indent=2)
    with open(os.path.join(out_dir, f"{stem}_log.txt"), "w") as fh:
        fh.write("\n".join(lines))
    if viewer:
        viewer(v, f)
    return Result(output_stl, rep, shots, lines)


def _shots(v, f, prefix, say, views=("front", "side", "bottom")):
    try:
        from .visualize import to_o3d, screenshots
        pv, pf = decimate(v, f, 400_000)
        files = screenshots(to_o3d(pv, pf), prefix, views=views)
        say(f"  screenshots: {', '.join(os.path.basename(x) for x in files)}")
        return files
    except Exception as exc:
        say(f"  (screenshots skipped: {exc})")
        return []
