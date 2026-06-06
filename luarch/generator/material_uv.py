from __future__ import annotations

import math

import bmesh
from mathutils import Vector

from .building_support import root_local_matrix
from .materials import material_uv_settings


BRICK_UV_SEAM_EPSILON = 1e-4
_SURFACE_TILE_UV_SPACE_KEY = "tbg_surface_tile_uv_space"
_SURFACE_TILE_UV_BOUNDS_KEY = "tbg_surface_tile_uv_bounds"
_SURFACE_TILE_UV_RUN_AXIS_KEY = "tbg_surface_tile_uv_run_axis"
_SURFACE_TILE_UV_SPACE_ROOT_SOURCE = "ROOT_SOURCE_SURFACE"


def _surface_tile_root_source_uv_context(obj) -> tuple[tuple[float, float, float, float, float, float], str] | None:
    if obj is None:
        return None
    if str(obj.get(_SURFACE_TILE_UV_SPACE_KEY, "")).strip().upper() != _SURFACE_TILE_UV_SPACE_ROOT_SOURCE:
        return None
    serialized_bounds = obj.get(_SURFACE_TILE_UV_BOUNDS_KEY)
    if not isinstance(serialized_bounds, (list, tuple)) or len(serialized_bounds) != 6:
        return None
    try:
        bounds = tuple(float(value) for value in serialized_bounds)
    except (TypeError, ValueError):
        return None
    run_axis = str(obj.get(_SURFACE_TILE_UV_RUN_AXIS_KEY, "")).strip().upper()
    if run_axis not in {"X", "Y"}:
        return None
    return bounds, run_axis


def _apply_material_uv(obj, material):
    mesh = getattr(obj, "data", None)
    if obj is None or mesh is None or not hasattr(mesh, "uv_layers"):
        return
    uv_settings = material_uv_settings(material)
    if not uv_settings["requires_uv"]:
        return
    uv_layer = mesh.uv_layers.get("TBG_UV")
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="TBG_UV")
    mesh.uv_layers.active = uv_layer
    xs = [vert.co.x for vert in mesh.vertices] or [0.0]
    ys = [vert.co.y for vert in mesh.vertices] or [0.0]
    zs = [vert.co.z for vert in mesh.vertices] or [0.0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    span_x = max(1e-4, max_x - min_x)
    span_y = max(1e-4, max_y - min_y)
    span_z = max(1e-4, max_z - min_z)

    is_brick = bool(uv_settings["is_brick"])
    scale = float(uv_settings["brick_scale"]) if is_brick else 1.0
    surface_tile_uv_context = None if is_brick else _surface_tile_root_source_uv_context(obj)
    uv_repeat = bool(uv_settings["repeat"])
    u0, v0, u1, v1 = uv_settings["uv_rect"]
    uv_projection_mode = str(uv_settings["projection_mode"])
    uv_island_inset = float(uv_settings["island_inset"])
    span_u = max(1e-6, u1 - u0)
    span_v = max(1e-6, v1 - v0)
    root_local = root_local_matrix(obj)
    root_normal = root_local.to_3x3()
    if surface_tile_uv_context is not None:
        (source_x0, source_x1, source_y0, source_y1, source_z0, source_z1), source_run_axis = surface_tile_uv_context
        source_span_x = max(1e-4, source_x1 - source_x0)
        source_span_y = max(1e-4, source_y1 - source_y0)
        source_span_z = max(1e-4, source_z1 - source_z0)
    for poly in mesh.polygons:
        normal = poly.normal
        if is_brick or surface_tile_uv_context is not None:
            transformed = root_normal @ poly.normal
            if transformed.length > 1e-8:
                normal = transformed.normalized()
        ax, ay, az = abs(normal.x), abs(normal.y), abs(normal.z)
        raw_coords: list[tuple[int, float, float]] = []
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if is_brick:
                co = root_local @ co
                if az >= ax and az >= ay:
                    u = co.x * scale
                    v = co.y * scale
                elif ax >= ay:
                    u = co.y * scale
                    v = co.z * scale
                else:
                    u = co.x * scale
                    v = co.z * scale
            elif surface_tile_uv_context is not None:
                co = root_local @ co
                if source_run_axis == "X":
                    if az >= ax and az >= ay:
                        u = (co.x - source_x0) / source_span_x
                        v = (co.y - source_y0) / source_span_y
                    elif ax >= ay:
                        u = (co.y - source_y0) / source_span_y
                        v = (co.z - source_z0) / source_span_z
                    else:
                        u = (co.x - source_x0) / source_span_x
                        v = (co.z - source_z0) / source_span_z
                else:
                    if az >= ax and az >= ay:
                        u = (co.y - source_y0) / source_span_y
                        v = (co.x - source_x0) / source_span_x
                    elif ax >= ay:
                        u = (co.y - source_y0) / source_span_y
                        v = (co.z - source_z0) / source_span_z
                    else:
                        u = (co.x - source_x0) / source_span_x
                        v = (co.z - source_z0) / source_span_z
            else:
                if az >= ax and az >= ay:
                    u = (co.x - min_x) / span_x
                    v = (co.y - min_y) / span_y
                elif ax >= ay:
                    u = (co.y - min_y) / span_y
                    v = (co.z - min_z) / span_z
                else:
                    u = (co.x - min_x) / span_x
                    v = (co.z - min_z) / span_z
            raw_coords.append((loop_index, u, v))

        if is_brick and raw_coords:
            min_raw_u = min(item[1] for item in raw_coords)
            min_raw_v = min(item[2] for item in raw_coords)
            base_u = math.floor(min_raw_u + BRICK_UV_SEAM_EPSILON)
            base_v = math.floor(min_raw_v + BRICK_UV_SEAM_EPSILON)
            normalized_coords = [
                (
                    loop_index,
                    max(0.0, min(1.0, raw_u - base_u)),
                    max(0.0, min(1.0, raw_v - base_v)),
                )
                for loop_index, raw_u, raw_v in raw_coords
            ]
        else:
            normalized_coords = []
            for loop_index, raw_u, raw_v in raw_coords:
                if uv_repeat:
                    u = raw_u % 1.0
                    v = raw_v % 1.0
                else:
                    u = max(0.0, min(1.0, raw_u))
                    v = max(0.0, min(1.0, raw_v))
                normalized_coords.append((loop_index, u, v))

        if (
            not is_brick
            and surface_tile_uv_context is None
            and uv_projection_mode == "FACE_FIT"
            and normalized_coords
        ):
            face_min_u = min(item[1] for item in normalized_coords)
            face_max_u = max(item[1] for item in normalized_coords)
            face_min_v = min(item[2] for item in normalized_coords)
            face_max_v = max(item[2] for item in normalized_coords)
            face_span_u = max(1e-6, face_max_u - face_min_u)
            face_span_v = max(1e-6, face_max_v - face_min_v)
            normalized_coords = [
                (
                    loop_index,
                    max(0.0, min(1.0, (u - face_min_u) / face_span_u)),
                    max(0.0, min(1.0, (v - face_min_v) / face_span_v)),
                )
                for loop_index, u, v in normalized_coords
            ]

        for loop_index, u, v in normalized_coords:
            if uv_island_inset > 0.0:
                usable_span = max(0.0, 1.0 - uv_island_inset * 2.0)
                u = uv_island_inset + u * usable_span
                v = uv_island_inset + v * usable_span
            uv_layer.data[loop_index].uv = (u0 + u * span_u, v0 + v * span_v)

    if is_brick:
        obj["tbg_brick_uv_space"] = "ROOT_LOCAL"
        obj["tbg_brick_uv_scale"] = float(uv_settings["brick_scale"])


def _root_local_mesh_bounds(obj) -> tuple[float, float, float, float, float, float] | None:
    mesh = getattr(obj, "data", None)
    if obj is None or mesh is None or not getattr(mesh, "vertices", None):
        return None
    root_local = root_local_matrix(obj)
    coords = [root_local @ vert.co for vert in mesh.vertices]
    xs = [co.x for co in coords]
    ys = [co.y for co in coords]
    zs = [co.z for co in coords]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _brick_seam_positions(min_value: float, max_value: float, scale: float) -> list[float]:
    if max_value - min_value <= BRICK_UV_SEAM_EPSILON:
        return []
    start = math.floor(min_value * scale) + 1
    end = math.ceil(max_value * scale) - 1
    positions = []
    for seam_idx in range(start, end + 1):
        position = seam_idx / scale
        if min_value + BRICK_UV_SEAM_EPSILON < position < max_value - BRICK_UV_SEAM_EPSILON:
            positions.append(position)
    return positions


def _bisect_mesh_on_root_plane(obj, axis_index: int, coordinate: float):
    mesh = getattr(obj, "data", None)
    if obj is None or mesh is None:
        return
    bm = bmesh.new()
    bm.from_mesh(mesh)
    if not bm.faces:
        bm.free()
        return
    root_local = root_local_matrix(obj)
    root_to_object = root_local.inverted()
    plane_co_root = Vector((0.0, 0.0, 0.0))
    plane_no_root = Vector((0.0, 0.0, 0.0))
    plane_co_root[axis_index] = coordinate
    plane_no_root[axis_index] = 1.0
    plane_co_obj = root_to_object @ plane_co_root
    plane_no_obj = (root_to_object.to_3x3() @ plane_no_root).normalized()
    bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=plane_co_obj,
        plane_no=plane_no_obj,
        dist=1e-6,
        clear_outer=False,
        clear_inner=False,
    )
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def _retile_brick_section(obj, material):
    uv_settings = material_uv_settings(material)
    if obj is None or material is None or not uv_settings["is_brick"]:
        return
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)
    scale = float(uv_settings["brick_scale"])
    bounds = _root_local_mesh_bounds(obj)
    seam_positions: list[tuple[int, float]] = []
    if bounds is not None:
        min_x, max_x, min_y, max_y, min_z, max_z = bounds
        seam_positions.extend((0, value) for value in _brick_seam_positions(min_x, max_x, scale))
        seam_positions.extend((1, value) for value in _brick_seam_positions(min_y, max_y, scale))
        seam_positions.extend((2, value) for value in _brick_seam_positions(min_z, max_z, scale))
        for axis_index, coordinate in seam_positions:
            _bisect_mesh_on_root_plane(obj, axis_index, coordinate)
    _apply_material_uv(obj, material)
    obj["tbg_brick_uv_space"] = "ROOT_LOCAL"
    obj["tbg_brick_uv_scale"] = float(uv_settings["brick_scale"])
    obj["tbg_brick_seam_cut_count"] = len(seam_positions)
    obj["tbg_brick_seam_safe"] = True


def _brick_section_requires_retile(obj, material) -> bool:
    uv_settings = material_uv_settings(material)
    if obj is None or material is None or not uv_settings["is_brick"]:
        return False
    if not bool(obj.get("tbg_brick_seam_safe", False)):
        return True
    if "tbg_brick_seam_cut_count" not in obj.keys():
        return True
    if str(obj.get("tbg_brick_uv_space", "")) != "ROOT_LOCAL":
        return True
    expected_scale = float(uv_settings["brick_scale"])
    try:
        stored_scale = float(obj.get("tbg_brick_uv_scale"))
    except (TypeError, ValueError):
        return True
    return abs(stored_scale - expected_scale) > 1e-6
