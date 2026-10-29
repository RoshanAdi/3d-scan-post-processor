"""Basic mesh operations on plain (v, f) arrays: components, cleanup, boundary loops."""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components


def vertex_components(n_verts, f):
    """Connected-component label per vertex (via shared edges)."""
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]]])
    adj = sp.coo_matrix((np.ones(len(e), np.int8), (e[:, 0], e[:, 1])),
                        shape=(n_verts, n_verts)).tocsr()
    return connected_components(adj, directed=False)


def remove_unreferenced(v, f):
    used = np.zeros(len(v), bool)
    used[f.ravel()] = True
    remap = np.full(len(v), -1, np.int64)
    remap[used] = np.arange(used.sum())
    return v[used], remap[f]


def remove_degenerate(v, f):
    """Drop faces with repeated vertex indices or zero area, and duplicate faces."""
    ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])
    f = f[ok]
    area2 = np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
    f = f[area2 > 1e-12]
    _, idx = np.unique(np.sort(f, axis=1), axis=0, return_index=True)
    f = f[np.sort(idx)]
    return remove_unreferenced(v, f)


def merge_close_vertices(v, f, tol=1e-6):
    """Weld vertices that coincide (within tol), e.g. after plane cuts."""
    q = np.round(v / tol).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    return remove_degenerate(v[first], inv[f])


def remove_small_components(v, f, min_frac=0.001, keep_largest_only=False):
    """Remove floating debris: components with fewer than min_frac of all faces.

    Returns (v, f, n_removed_components, n_removed_faces).
    """
    nc, lab = vertex_components(len(v), f)
    flab = lab[f[:, 0]]
    counts = np.bincount(flab, minlength=nc)
    if keep_largest_only:
        keep_lab = np.zeros(nc, bool)
        keep_lab[np.argmax(counts)] = True
    else:
        keep_lab = counts >= max(1, min_frac * len(f))
    keep = keep_lab[flab]
    n_rem_c = int(nc - keep_lab.sum())
    n_rem_f = int((~keep).sum())
    v2, f2 = remove_unreferenced(v, f[keep])
    return v2, f2, n_rem_c, n_rem_f


def keep_largest_shell(v, f):
    """Keep the largest edge-connected set of faces (drops shells touching only at a vertex)."""
    _, inv, _ = edge_face_counts(f)
    nf, ne = len(f), int(inv.max()) + 1
    face_of = np.tile(np.arange(nf), 3)
    A = sp.coo_matrix((np.ones(len(inv), np.int8), (face_of, nf + inv)), shape=(nf + ne, nf + ne))
    _, lab = connected_components(A, directed=False)
    flab = lab[:nf]
    big = np.argmax(np.bincount(flab))
    return remove_unreferenced(v, f[flab == big])


def edge_face_counts(f):
    """Unique undirected edges and how many faces use each."""
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e.sort(axis=1)
    key = e[:, 0] * (int(f.max()) + 1) + e[:, 1]
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    return uk, inv.ravel(), cnt


def remove_nonmanifold_faces(v, f, max_iter=5):
    """Remove faces on edges shared by more than two faces (keeps the two largest)."""
    for _ in range(max_iter):
        _, inv, cnt = edge_face_counts(f)
        bad_e = cnt > 2
        if not bad_e.any():
            break
        face_of = np.tile(np.arange(len(f)), 3)
        on_bad = bad_e[inv]
        # for each bad edge drop all but two faces: drop the smallest-area ones
        area = np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
        be, bf = inv[on_bad], face_of[on_bad]
        order = np.lexsort((-area[bf], be))
        be, bf = be[order], bf[order]
        start = np.r_[True, be[1:] != be[:-1]]
        rank = np.arange(len(be)) - np.maximum.accumulate(np.where(start, np.arange(len(be)), 0))
        drop = np.unique(bf[rank >= 2])
        keep = np.ones(len(f), bool)
        keep[drop] = False
        f = f[keep]
    return remove_unreferenced(v, f)


def boundary_loops(f):
    """Ordered boundary loops (list of int64 arrays) of a triangle mesh.

    A boundary edge is an undirected edge used by exactly one face. Loops passing a vertex
    twice (pinch vertices) are split into simple loops. Loops with < 3 vertices are dropped.
    """
    he = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    _, inv, cnt = edge_face_counts(f)
    bhe = he[cnt[inv] == 1]
    if len(bhe) == 0:
        return []
    # adjacency from boundary half-edges: a -> list of b
    order = np.argsort(bhe[:, 0], kind="stable")
    src, dst = bhe[order, 0], bhe[order, 1]
    used = np.zeros(len(src), bool)
    first_of = dict(zip(*np.unique(src, return_index=True)))
    ends = np.searchsorted(src, src, side="right")

    def next_edge(a):
        i = first_of.get(a)
        if i is None:
            return -1
        j_end = ends[i]
        while i < j_end:
            if not used[i]:
                return i
            i += 1
        return -1

    loops = []
    for e0 in range(len(src)):
        if used[e0]:
            continue
        walk = [src[e0]]
        used[e0] = True
        cur = dst[e0]
        while cur != walk[0]:
            e = next_edge(cur)
            if e < 0:
                break  # open chain (non-manifold); give up on it
            used[e] = True
            walk.append(cur)
            cur = dst[e]
        else:
            loops.extend(_split_pinched(walk))
    return [np.asarray(lp, np.int64) for lp in loops if len(lp) >= 3]


def _split_pinched(walk):
    """Split a closed walk that repeats vertices into simple loops."""
    if len(set(walk)) == len(walk):
        return [walk]
    out, stack, pos = [], [], {}
    for vtx in walk:
        if vtx in pos:
            k = pos[vtx]
            loop = stack[k:]
            for u in loop[1:]:
                pos.pop(u, None)
            del stack[k + 1:]
            out.append(loop)
        else:
            pos[vtx] = len(stack)
            stack.append(vtx)
    if len(stack) >= 3:
        out.append(stack)
    return out


def loop_perimeter(v, loop):
    p = v[loop]
    return float(np.linalg.norm(p - np.roll(p, -1, axis=0), axis=1).sum())
