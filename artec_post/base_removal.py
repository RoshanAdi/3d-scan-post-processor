"""Detect the scanning base (turntable / stand plate), cut it away and cap the opening flat."""
import numpy as np
import open3d as o3d
import triangle as tr
from matplotlib.path import Path

from .mesh_ops import remove_unreferenced, remove_degenerate, loop_perimeter


# ---------------------------------------------------------------- plane detection
def detect_base_plane(v, dist_thresh=0.3, sample=600_000, seed=0, log=print):
    """Find the dominant plane (top face of the base plate) with RANSAC.

    Returns (normal, d) with normal . x + d = 0, normal pointing towards the object
    (the side with most of the geometry).
    """
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(v), size=min(sample, len(v)), replace=False)
    pts = v[idx]
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    o3d.utility.random.seed(seed)
    model, inl = pc.segment_plane(distance_threshold=dist_thresh, ransac_n=3, num_iterations=3000)
    nrm = np.asarray(model[:3], float)
    d = float(model[3])
    # least-squares refinement on inliers
    P = pts[inl]
    c = P.mean(0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    n2 = vt[2]
    if n2 @ nrm < 0:
        n2 = -n2
    nrm, d = n2, -float(n2 @ c)
    s = pts @ nrm + d
    if (s > 5 * dist_thresh).sum() < (s < -5 * dist_thresh).sum():
        nrm, d = -nrm, -d
        s = -s
    log(f"  base plane: normal={np.round(nrm, 4)}, d={d:.3f}, inliers={len(inl) / len(pts):.1%} "
        f"of sample, object height above plane={s.max():.1f}, below={-s.min():.1f}")
    return nrm, d


def aligning_transform(normal, d):
    """4x4 rigid transform that maps the plane to z=0 with the normal to +Z."""
    z = normal / np.linalg.norm(normal)
    helper = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(helper, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ (-d * z)  # the plane point -d*z maps to the origin
    return T


def apply_transform(v, T):
    return v @ T[:3, :3].T + T[:3, 3]


# ---------------------------------------------------------------- cutting
def cut_below(v, f, z_cut):
    """Remove everything below z = z_cut, splitting straddling triangles exactly at the plane.

    Assumes the mesh is already aligned so the plane is horizontal. New vertices on the
    cut are shared between neighbouring faces (one per cut edge).
    """
    s = v[:, 2] - z_cut
    above = s > 0
    k = above[f].sum(1)
    keep = f[k == 3]
    mixed = f[(k == 1) | (k == 2)]
    km = above[mixed].sum(1)
    if len(mixed) == 0:
        return remove_unreferenced(v, keep)

    # rotate so the "odd" vertex (alone on its side) comes first, preserving winding
    odd_mask = np.where(km[:, None] == 1, above[mixed], ~above[mixed])
    first = np.argmax(odd_mask, axis=1)
    rot = (first[:, None] + np.arange(3)[None, :]) % 3
    tri = np.take_along_axis(mixed, rot, axis=1)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]

    # intersection vertex per undirected edge
    e = np.concatenate([np.column_stack([a, b]), np.column_stack([a, c])])
    es = np.sort(e, axis=1)
    key = es[:, 0] * len(v) + es[:, 1]
    uk, inv = np.unique(key, return_inverse=True)
    inv = inv.ravel()
    e0, e1 = uk // len(v), uk % len(v)
    t = s[e0] / (s[e0] - s[e1])
    pts = v[e0] + t[:, None] * (v[e1] - v[e0])
    pts[:, 2] = z_cut
    nid = len(v) + inv
    p_ab, p_ac = nid[:len(tri)], nid[len(tri):]

    one = km == 1  # a above: keep triangle (a, p_ab, p_ac)
    two = ~one     # a below: keep quad (p_ab, b, c, p_ac)
    new_f = [keep,
             np.column_stack([a[one], p_ab[one], p_ac[one]]),
             np.column_stack([p_ab[two], b[two], c[two]]),
             np.column_stack([p_ab[two], c[two], p_ac[two]])]
    v2 = np.vstack([v, pts])
    f2 = np.vstack(new_f)
    return remove_degenerate(v2, f2)


# ---------------------------------------------------------------- flat cap
def find_cut_loops(v, loops, z_cut, tol=1e-6, min_on_plane=0.5):
    """Loops whose vertices lie (mostly) on the cut plane, largest perimeter first."""
    out = []
    for lp in loops:
        on = np.abs(v[lp, 2] - z_cut) < tol
        if on.mean() >= min_on_plane:
            out.append(lp)
    out.sort(key=lambda lp: -loop_perimeter(v, lp))
    return out


def cap_planar(v, loops, z_plane, max_area=None):
    """Triangulate one or more nested planar loops (even-odd rule) as a flat cap.

    Loop vertices keep their ids; their z is set to z_plane. New interior points get
    z = z_plane. Returns (v, cap_faces) with winding opposite to the loops' half-edges.
    """
    v = v.copy()
    all_ids = np.concatenate(loops)
    v[all_ids, 2] = z_plane
    uniq, inv = np.unique(all_ids, return_inverse=True)
    inv = inv.ravel()
    xy = v[uniq, :2]
    segs, pos = [], 0
    for lp in loops:
        n = len(lp)
        li = inv[pos:pos + n]
        segs.append(np.column_stack([li, np.roll(li, -1)]))
        pos += n
    segs = np.vstack(segs)
    opts = "pYQ" + (f"q25a{max_area:.6f}" if max_area else "")
    out = tr.triangulate({"vertices": xy, "segments": segs}, opts)
    tv, tt = out["vertices"], out["triangles"].astype(np.int64)
    if len(tv) < len(xy) or not np.allclose(tv[:len(xy)], xy):
        raise RuntimeError("cap triangulation altered the boundary")
    # even-odd inside test of triangle centroids
    cen = tv[tt].mean(1)
    inside = np.zeros(len(tt), int)
    for lp in loops:
        inside += Path(v[lp, :2]).contains_points(cen).astype(int)
    tt = tt[inside % 2 == 1]
    # map to global ids
    n_new = len(tv) - len(xy)
    gid = np.concatenate([uniq, len(v) + np.arange(n_new)])
    newp = np.column_stack([tv[len(xy):], np.full(n_new, z_plane)])
    faces = gid[tt]
    # orientation: cap faces must traverse each loop edge opposite to the loop direction
    lp = loops[0]
    a, b = lp[0], lp[1]
    has_ab = np.any((faces == a) & (np.roll(faces, -1, axis=1) == b))
    if has_ab:
        faces = faces[:, ::-1]
    return np.vstack([v, newp]), faces
