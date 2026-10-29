"""Visualisation helpers: interactive viewer and off-screen screenshots (Open3D)."""
import numpy as np
import open3d as o3d


def to_o3d(v, f, color=(0.75, 0.75, 0.78)):
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.asarray(v, np.float64)),
                                  o3d.utility.Vector3iVector(np.asarray(f, np.int32)))
    m.compute_vertex_normals()
    if color is not None:
        m.paint_uniform_color(color)
    return m


def _view_dirs():
    # (front, up) pairs; the object's long axis is assumed to be +Z after alignment
    return {
        "front": ([0, -1, 0.25], [0, 0, 1]),
        "side": ([1, 0, 0.25], [0, 0, 1]),
        "back": ([0, 1, 0.25], [0, 0, 1]),
        "bottom": ([0.2, -0.3, -1], [0, 1, 0]),
        "top": ([0.2, -0.3, 1], [0, 1, 0]),
    }


def screenshots(geoms, prefix, views=("front", "side", "bottom"), size=(900, 1100),
                zoom=0.95, show_wire=False):
    """Render geometries off-screen and save one PNG per view. Returns file names."""
    if not isinstance(geoms, (list, tuple)):
        geoms = [geoms]
    vis = o3d.visualization.Visualizer()
    vis.create_window(width=size[0], height=size[1], visible=False)
    for g in geoms:
        vis.add_geometry(g)
    opt = vis.get_render_option()
    opt.mesh_show_back_face = True
    opt.mesh_show_wireframe = show_wire
    opt.background_color = np.array([1.0, 1.0, 1.0])
    opt.point_size = 2.0
    ctr = vis.get_view_control()
    out = []
    dirs = _view_dirs()
    for name in views:
        front, up = dirs[name]
        ctr.set_front(front)
        ctr.set_up(up)
        ctr.set_lookat(np.mean([g.get_center() for g in geoms], axis=0))
        ctr.set_zoom(zoom)
        vis.poll_events()
        vis.update_renderer()
        fn = f"{prefix}_{name}.png"
        vis.capture_screen_image(fn, do_render=True)
        out.append(fn)
    vis.destroy_window()
    return out


def show(v, f, title="mesh", extra=None):
    """Open an interactive Open3D window."""
    geoms = [to_o3d(v, f)]
    if extra:
        geoms += list(extra)
    o3d.visualization.draw_geometries(geoms, window_name=title, mesh_show_back_face=True)
