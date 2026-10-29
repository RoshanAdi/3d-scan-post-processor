"""Hole filling: disk-parameterised Triangle meshing + bilaplacian (thin-plate) fairing.

For every boundary loop:
  1. map the loop to the unit circle by arc length,
  2. mesh the disk with Triangle (constrained Delaunay, min angle 30, no boundary splits),
  3. place new interior points in 3D by solving L^2 x = 0 with the hole boundary and the
     ring of original vertices around it fixed (C1-like continuity with the surface),
  4. append the patch with winding opposite to the boundary half-edges.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
import triangle as tr

from .mesh_ops import boundary_loops, loop_perimeter


class _VertexFaces:
    """CSR map vertex -> incident faces."""

    def __init__(self, n_verts, f):
        flat = f.ravel()
        order = np.argsort(flat, kind="stable")
        self.faces = (order // 3).astype(np.int64)
        self.ptr = np.zeros(n_verts + 1, np.int64)
        np.cumsum(np.bincount(flat, minlength=n_verts), out=self.ptr[1:])

    def of(self, verts):
        idx = [self.faces[self.ptr[a]:self.ptr[a + 1]] for a in verts]
        return np.unique(np.concatenate(idx)) if idx else np.zeros(0, np.int64)


def _disk_triangulation(v, loop):
    n = len(loop)
    p = v[loop]
    seg_len = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)
    per = seg_len.sum()
    cum = np.r_[0.0, np.cumsum(seg_len)[:-1]]
    s = 0.9 * cum / per + 0.1 * np.arange(n) / n
    uv = np.column_stack([np.cos(2 * np.pi * s), np.sin(2 * np.pi * s)])
    edge3d = max(seg_len.mean(), per / 120.0)
    edge2d = edge3d * 2 * np.pi / per
    area = 0.433 * edge2d ** 2
    seg = np.column_stack([np.arange(n), (np.arange(n) + 1) % n])
    try:
        out = tr.triangulate({"vertices": uv, "segments": seg}, f"pq30YQa{area:.10f}")
        tv, tt = out["vertices"], out["triangles"]
        if len(tv) < n or not np.allclose(tv[:n], uv) or len(tt) == 0:
            raise RuntimeError("Triangle changed the boundary")
    except Exception:
        # fallback: fan around a single centre point
        tv = np.vstack([uv, [[0.0, 0.0]]])
        tt = np.column_stack([np.arange(n), (np.arange(n) + 1) % n, np.full(n, n)])
    return tv, tt.astype(np.int64)


def _cot_weights_2d(uv, tris):
    """Cotangent weights (as sparse symmetric matrix) on a 2D triangulation."""
    rows, cols, vals = [], [], []
    for a, b, c in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        # angle at c, opposite edge (a, b)
        pa, pb, pc = uv[tris[:, a]], uv[tris[:, b]], uv[tris[:, c]]
        u, w = pa - pc, pb - pc
        cross = np.abs(u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0])
        cot = (u * w).sum(1) / np.maximum(cross, 1e-15)
        rows += [tris[:, a], tris[:, b]]
        cols += [tris[:, b], tris[:, a]]
        vals += [0.5 * cot, 0.5 * cot]
    n = len(uv)
    return sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                         shape=(n, n)).tocsr()


def fill_hole(v, f, loop, vf):
    """Return (new_points (m,3), new_faces (k,3) in global indices) for one loop."""
    n = len(loop)
    n_verts = len(v)
    if n == 3:
        return np.zeros((0, 3)), np.array([[loop[0], loop[2], loop[1]]], np.int64)
    uv, tt = _disk_triangulation(v, loop)
    m = len(uv) - n
    # global indices of patch vertices: loop ids, then new ids appended at the end
    gid = np.concatenate([loop, n_verts + np.arange(m)])
    patch_faces = gid[tt[:, ::-1]]  # reversed winding
    if m == 0:
        return np.zeros((0, 3)), patch_faces

    # ----- local system: boundary (0..n-1), interior (n..n+m-1), ring (n+m..)
    ring_faces = f[vf.of(loop)]
    ring_verts = np.setdiff1d(np.unique(ring_faces), loop)
    r = len(ring_verts)
    N = n + m + r
    local = {int(g): i for i, g in enumerate(loop)}
    for i, g in enumerate(ring_verts):
        local[int(g)] = n + m + i
    lf = np.vectorize(local.__getitem__, otypes=[np.int64])(ring_faces) if len(ring_faces) else np.zeros((0, 3), np.int64)

    # uniform adjacency over patch triangles + original ring faces
    all_t = np.vstack([tt, lf])
    e = np.concatenate([all_t[:, [0, 1]], all_t[:, [1, 2]], all_t[:, [2, 0]]])
    e = np.vstack([e, e[:, ::-1]])
    Wu = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(N, N)).tocsr()
    Wu.data[:] = 1.0

    # cotangent weights for interior rows (computed on the 2D disk)
    Wc = _cot_weights_2d(uv, tt)
    Wc.data = np.maximum(Wc.data, 1e-6)
    Wc = sp.csr_matrix((Wc.data, Wc.indices, Wc.indptr), shape=(n + m, n + m))
    Wc.resize((N, N))

    is_int = np.zeros(N, bool)
    is_int[n:n + m] = True
    Dint = sp.diags(is_int.astype(float))
    W = Dint @ Wc + sp.diags((~is_int).astype(float)) @ Wu
    deg = np.asarray(W.sum(1)).ravel()
    deg[deg == 0] = 1.0
    L = sp.identity(N, format="csr") - sp.diags(1.0 / deg) @ W
    M = (L @ L).tocsr()

    interior = np.arange(n, n + m)
    fixed = np.r_[np.arange(n), np.arange(n + m, N)]
    Xf = np.vstack([v[loop], v[ring_verts]]) if r else v[loop]
    A = M[interior][:, interior].tocsc()
    B = -(M[interior][:, fixed] @ Xf)
    X = spsolve(A, B)
    X = np.asarray(X).reshape(m, 3)
    if not np.all(np.isfinite(X)):
        # fallback: harmonic (membrane) solve with boundary only
        X = np.tile(v[loop].mean(0), (m, 1))
    return X, patch_faces


def fill_holes(v, f, max_perimeter=np.inf, skip_loops=(), log=print, loops=None):
    """Fill every boundary loop with perimeter <= max_perimeter.

    skip_loops: loops (vertex-id arrays) to leave open (compared as vertex sets).
    Returns (v, f, n_filled, n_skipped).
    """
    if loops is None:
        loops = boundary_loops(f)
    skip = {frozenset(map(int, s)) for s in skip_loops}
    vf = _VertexFaces(len(v), f)
    new_v, new_f = [v], [f]
    n_next = len(v)
    filled = skipped = 0
    for loop in loops:
        if frozenset(map(int, loop)) in skip:
            skipped += 1
            continue
        if loop_perimeter(v, loop) > max_perimeter:
            skipped += 1
            continue
        X, F = fill_hole(v, f, loop, vf)
        # renumber appended points so ids stay unique across holes
        if len(X):
            F = np.where(F >= len(v), F - len(v) + n_next, F)
            n_next += len(X)
            new_v.append(X)
        new_f.append(F)
        filled += 1
    return np.vstack(new_v), np.vstack(new_f), filled, skipped
