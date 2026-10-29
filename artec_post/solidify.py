"""Downsampling and final watertight-solid checks/repairs."""
import numpy as np
import fast_simplification
import trimesh

from .mesh_ops import (remove_degenerate, merge_close_vertices, edge_face_counts,
                       remove_small_components, remove_nonmanifold_faces, keep_largest_shell)
from .hole_filling import fill_holes
from .mesh_io import face_normals


def decimate(v, f, target_faces):
    """Quadric edge-collapse decimation to roughly target_faces triangles."""
    if len(f) <= target_faces:
        return v, f
    red = 1.0 - target_faces / len(f)
    pv, pf = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), red)
    return remove_degenerate(pv.astype(np.float64), pf.astype(np.int64))


def solid_report(v, f):
    m = trimesh.Trimesh(v, f, process=False)
    edges = np.sort(m.edges, axis=1)
    _, cnt = np.unique(edges, axis=0, return_counts=True)
    rep = {
        "vertices": len(v),
        "faces": len(f),
        "boundary_edges": int((cnt == 1).sum()),
        "nonmanifold_edges": int((cnt > 2).sum()),
        "watertight": bool(m.is_watertight),
        "winding_consistent": bool(m.is_winding_consistent),
        "volume_mm3": float(m.volume) if m.is_watertight else None,
        "euler_number": int(m.euler_number),
        "bounds_mm": m.bounds.round(3).tolist(),
    }
    try:
        import manifold3d
        mm = manifold3d.Manifold(manifold3d.Mesh(vert_properties=v.astype(np.float32),
                                                 tri_verts=f.astype(np.uint32)))
        rep["manifold3d_status"] = str(mm.status()).split(".")[-1]
    except Exception as exc:  # manifold3d is optional
        rep["manifold3d_status"] = f"n/a ({exc.__class__.__name__})"
    return rep


def orient_outward(v, f):
    """Make winding consistent and normals point outward (positive volume)."""
    m = trimesh.Trimesh(v, f, process=False)
    if not m.is_winding_consistent:
        trimesh.repair.fix_winding(m)
    if m.is_watertight and m.volume < 0:
        m.invert()
    return np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)


def flatten_bottom(v, f, z_plane=0.0, tol=0.5, max_tilt_deg=10.0):
    """Make the bottom exactly planar again after decimation.

    Vertices of downward-facing faces lying within tol of z_plane are snapped onto the
    plane, and no vertex is allowed below it.
    """
    v = v.copy()
    n = face_normals(v, f)
    cen_z = v[f].mean(1)[:, 2]
    down = (n[:, 2] < -np.cos(np.radians(max_tilt_deg))) & (np.abs(cen_z - z_plane) < tol)
    ids = np.unique(f[down])
    ids = ids[np.abs(v[ids, 2] - z_plane) < tol]
    v[ids, 2] = z_plane
    v[:, 2] = np.maximum(v[:, 2], z_plane)
    return v


def weld(v, f, tol=1e-5):
    return merge_close_vertices(v, f, tol)


def bad_edge_vertices(f, n_verts):
    """Mask of vertices on boundary (1 face) or non-manifold (>2 faces) edges."""
    uk, _, cnt = edge_face_counts(f)
    N = int(f.max()) + 1
    ks = uk[cnt != 2]
    bad = np.zeros(n_verts, bool)
    bad[ks // N] = True
    bad[ks % N] = True
    return bad


def make_watertight(v, f, log=print, max_iter=8):
    """Repeatedly cut out the neighbourhood of every defect and re-fill it.

    Defects are boundary edges and non-manifold edges. The removed neighbourhood grows
    with each iteration (1, 2, 3 ... rings) so stubborn spots get a bigger, cleaner hole.
    """
    for it in range(max_iter):
        v, f = weld(v, f)
        v, f = remove_degenerate(v, f)
        v, f = keep_largest_shell(v, f)
        bad = bad_edge_vertices(f, len(v))
        if not bad.any():
            return v, f
        n_bad = int(bad.sum())
        rings = it + 1
        for _ in range(rings):
            bad[f[bad[f].any(1)].ravel()] = True
        f = f[~bad[f].any(1)]
        v, f, _, _ = remove_small_components(v, f, keep_largest_only=True)
        v, f = remove_nonmanifold_faces(v, f)
        v, f, nfill, _ = fill_holes(v, f, np.inf, log=log)
        log(f"  repair pass {it + 1}: {n_bad} defect vertices, removed {rings}-ring, filled {nfill} holes")
    return v, f
