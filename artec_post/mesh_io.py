"""Reading PLY scans and writing STL files.

Mesh representation everywhere: v = float64 (N, 3) vertex positions,
f = int64 (M, 3) triangle vertex indices.
"""
import numpy as np

_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}


def _parse_header(fh):
    lines = []
    while True:
        line = fh.readline()
        if not line:
            raise ValueError("Unexpected end of file while reading PLY header")
        line = line.decode("ascii", errors="replace").strip()
        lines.append(line)
        if line == "end_header":
            break
    if lines[0] != "ply":
        raise ValueError("Not a PLY file")
    fmt = None
    elements = []  # list of [name, count, props]; props = list of (name, type) or (name, ('list', ctype, itype))
    for line in lines[1:]:
        tok = line.split()
        if not tok:
            continue
        if tok[0] == "format":
            fmt = tok[1]
        elif tok[0] == "element":
            elements.append([tok[1], int(tok[2]), []])
        elif tok[0] == "property":
            if tok[1] == "list":
                elements[-1][2].append((tok[4], ("list", tok[2], tok[3])))
            else:
                elements[-1][2].append((tok[2], tok[1]))
    return fmt, elements


def _read_ply_fast(path):
    """Fast reader for binary little-endian triangle PLY (Artec Studio export)."""
    with open(path, "rb") as fh:
        fmt, elements = _parse_header(fh)
        if fmt != "binary_little_endian":
            raise NotImplementedError(fmt)
        v = f = None
        for name, count, props in elements:
            if name == "vertex":
                dt = np.dtype([(p, "<" + _PLY_TYPES[t]) for p, t in props])
                data = np.fromfile(fh, dtype=dt, count=count)
                v = np.column_stack([data["x"], data["y"], data["z"]]).astype(np.float64)
                del data
            elif name == "face":
                if len(props) != 1 or props[0][1][0] != "list":
                    raise NotImplementedError("face element with extra properties")
                _, ctype, itype = props[0][1]
                dt = np.dtype([("n", "<" + _PLY_TYPES[ctype]),
                               ("i", "<" + _PLY_TYPES[itype], (3,))])
                data = np.fromfile(fh, dtype=dt, count=count)
                if not np.all(data["n"] == 3):
                    raise NotImplementedError("non-triangle faces")
                f = data["i"].astype(np.int64)
                del data
            else:
                raise NotImplementedError("element " + name)
    if v is None or f is None:
        raise ValueError("PLY has no vertex/face data")
    return v, f


def load_mesh(path, log=print):
    """Load a triangle mesh. Uses the fast binary reader, falls back to trimesh."""
    try:
        v, f = _read_ply_fast(path)
    except (NotImplementedError, ValueError) as exc:
        log(f"  fast PLY reader not applicable ({exc}); using trimesh")
        import trimesh
        m = trimesh.load(path, force="mesh", process=False)
        v = np.asarray(m.vertices, dtype=np.float64)
        f = np.asarray(m.faces, dtype=np.int64)
    return v, f


def face_normals(v, f):
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return n / ln


def write_stl(path, v, f, header=b"artec_post binary STL"):
    """Write a binary STL (80-byte header, uint32 count, 50 bytes per triangle)."""
    dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec = np.zeros(len(f), dtype=dt)
    rec["n"] = face_normals(v, f)
    rec["v"] = v[f]
    with open(path, "wb") as fh:
        fh.write(header[:80].ljust(80, b" "))
        fh.write(np.uint32(len(f)).tobytes())
        rec.tofile(fh)


def write_ply(path, v, f):
    """Write a binary little-endian triangle PLY."""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(v)}\nproperty float x\nproperty float y\nproperty float z\n"
        f"element face {len(f)}\nproperty list uchar int vertex_indices\nend_header\n"
    ).encode("ascii")
    fd = np.dtype([("n", "u1"), ("i", "<i4", (3,))])
    fr = np.empty(len(f), dtype=fd)
    fr["n"] = 3
    fr["i"] = f
    with open(path, "wb") as fh:
        fh.write(header)
        v.astype("<f4").tofile(fh)
        fr.tofile(fh)
