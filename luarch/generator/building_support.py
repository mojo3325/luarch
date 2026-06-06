from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import dataclass, replace

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from .. import export_contract
from .materials import BRICK_FAMILIES, FLAT_FACADE_FAMILIES, INDUSTRIAL_CLADDING_MATERIAL_NAME

_ACTIVE_SECTION_SINK = None
_ACTIVE_OUTPUT_LEDGER = None
_COMPOSITE_PART_BOUNDS_KEY = "tbg_composite_part_bounds_json"
_VOXEL_WALL_MARKER_PAYLOAD_KEY = "tbg_voxel_wall_marker_payload_json"
_VOXEL_WALL_MARKER_ESTIMATED_PART_COUNT_KEY = "tbg_voxel_wall_estimated_part_count"
_VOXEL_WALL_BRICK_MATERIAL_NAMES = frozenset(
    str(config.get("name", "")).strip() for config in BRICK_FAMILIES.values() if str(config.get("name", "")).strip()
)
_VOXEL_WALL_TIMBER_SIDING_MATERIAL_NAMES = frozenset(
    {
        str(FLAT_FACADE_FAMILIES["TIMBER_WARM"]["name"]),
        str(FLAT_FACADE_FAMILIES["TIMBER_WEATHERED"]["name"]),
    }
)
_VOXEL_WALL_TIMBER_PAINTED_MATERIAL_NAMES = frozenset({str(FLAT_FACADE_FAMILIES["PAINTED_WOOD"]["name"])})
_VOXEL_WALL_PLASTER_MATERIAL_NAMES = frozenset(
    {
        str(FLAT_FACADE_FAMILIES["SANDSTONE_FLAT"]["name"]),
        str(FLAT_FACADE_FAMILIES["CONCRETE_FLAT"]["name"]),
        str(FLAT_FACADE_FAMILIES["PLASTER_WARM"]["name"]),
        str(FLAT_FACADE_FAMILIES["PLASTER_COOL"]["name"]),
    }
)


def _voxel_material_family_title(family_key: str) -> str:
    return str(family_key).title().replace("_", "")


def _build_canonical_voxel_wall_material_lookup() -> dict[str, tuple[str, str | None]]:
    lookup: dict[str, tuple[str, str | None]] = {
        "TBG_Wall": ("BRICK", "BRICK_MASONRY"),
        "TBG_InteriorWall": ("PLASTER", None),
        "TBG_Tile_InteriorWall": ("PLASTER", None),
        INDUSTRIAL_CLADDING_MATERIAL_NAME: ("METAL", None),
    }
    for family_key, family_config in BRICK_FAMILIES.items():
        family_title = _voxel_material_family_title(family_key)
        lookup[str(family_config["name"])] = ("BRICK", "BRICK_MASONRY")
        lookup[f"TBG_Panel_{family_title}"] = ("PLASTER", None)
        for material_name in (f"TBG_Trim_{family_title}", f"TBG_Balcony_{family_title}"):
            lookup[str(material_name)] = ("BRICK", "BRICK_MASONRY")
    for family_key, family_config in FLAT_FACADE_FAMILIES.items():
        family_title = _voxel_material_family_title(family_key)
        if family_key in {"TIMBER_WARM", "TIMBER_WEATHERED"}:
            material_family = "WOOD"
            visual_style = "TIMBER_SIDING"
        elif family_key == "PAINTED_WOOD":
            material_family = "WOOD"
            visual_style = "TIMBER_PAINTED"
        elif family_key == "CONCRETE_FLAT":
            material_family = "CONCRETE"
            visual_style = None
        else:
            material_family = "PLASTER"
            visual_style = None
        family_names = (
            str(family_config["name"]),
            f"TBG_Panel_{family_title}",
            f"TBG_Trim_{family_title}",
        )
        for material_name in family_names:
            lookup[str(material_name)] = (material_family, visual_style)
    return lookup


_CANONICAL_VOXEL_WALL_MATERIAL_LOOKUP = _build_canonical_voxel_wall_material_lookup()


def _texture_key_for_voxel_wall_material(material_family: str, visual_style: str | None) -> str:
    family = str(material_family or "").strip().upper() or "UNKNOWN"
    style = str(visual_style or "SOLID").strip().upper() or "SOLID"
    return "wall_" + family.lower() + "_" + style.lower()


def _texture_projection_for_voxel_wall_material(material_family: str, visual_style: str | None) -> str:
    family = str(material_family or "").strip().upper()
    if family in export_contract.TEXTURED_VOXEL_WALL_MATERIAL_FAMILIES and str(visual_style or "").strip():
        return export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
    return export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1


def _studs_per_tile_for_voxel_wall_material(material_family: str, visual_style: str | None) -> float:
    family = str(material_family or "").strip().upper()
    if family == "BRICK":
        return float(export_contract.BRICK_TEXTURE_STUDS_PER_TILE)
    if family == "WOOD":
        return float(export_contract.DEFAULT_TEXTURE_STUDS_PER_TILE)
    return float(export_contract.DEFAULT_TEXTURE_STUDS_PER_TILE)


def _voxel_wall_texture_contract_metadata(
    material_family: str,
    visual_style: str | None,
) -> dict[str, object]:
    period = _studs_per_tile_for_voxel_wall_material(material_family, visual_style)
    return {
        "texture_key": _texture_key_for_voxel_wall_material(material_family, visual_style),
        "texture_projection": _texture_projection_for_voxel_wall_material(material_family, visual_style),
        "texture_image_period_contract": export_contract.TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE,
        "texture_face_axis_table_version": export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1,
        "studs_per_tile_u": float(period),
        "studs_per_tile_v": float(period),
        "color_modulation_policy": export_contract.COLOR_MODULATION_POLICY_NONE,
    }


def _voxel_wall_material_metadata(
    *,
    material_family: str,
    visual_style: str | None,
    display_color_rgb: dict[str, int] | None,
) -> VoxelWallMaterialMetadata:
    texture_contract = _voxel_wall_texture_contract_metadata(material_family, visual_style)
    return VoxelWallMaterialMetadata(
        material_family=str(material_family),
        visual_style=str(visual_style) if visual_style else None,
        display_color_rgb=display_color_rgb,
        texture_key=str(texture_contract["texture_key"]),
        texture_projection=str(texture_contract["texture_projection"]),
        texture_image_period_contract=str(texture_contract["texture_image_period_contract"]),
        texture_face_axis_table_version=str(texture_contract["texture_face_axis_table_version"]),
        studs_per_tile_u=float(texture_contract["studs_per_tile_u"]),
        studs_per_tile_v=float(texture_contract["studs_per_tile_v"]),
        color_modulation_policy=str(texture_contract["color_modulation_policy"]),
    )


class VoxelWallOccupancyContractError(ValueError):
    pass


@dataclass(frozen=True)
class VoxelWallFrame:
    width_axis: str
    width_studs: float
    height_studs: float
    thickness_studs: float
    local_center: tuple[float, float, float]
    origin: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    z_axis: tuple[float, float, float]


@dataclass(frozen=True)
class VoxelWallOpening:
    kind: str
    source_name: str
    u_min: float
    u_max: float
    v_min: float
    v_max: float

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": str(self.kind),
            "source_name": str(self.source_name),
            "u_min": _round_voxel_wall_float(self.u_min),
            "u_max": _round_voxel_wall_float(self.u_max),
            "v_min": _round_voxel_wall_float(self.v_min),
            "v_max": _round_voxel_wall_float(self.v_max),
        }


@dataclass(frozen=True)
class VoxelWallMaterialMetadata:
    material_family: str
    visual_style: str | None
    display_color_rgb: dict[str, int] | None
    texture_key: str
    texture_projection: str
    texture_image_period_contract: str
    texture_face_axis_table_version: str
    studs_per_tile_u: float
    studs_per_tile_v: float
    color_modulation_policy: str


@dataclass(frozen=True)
class VoxelWallOpeningCandidate:
    kind: str
    source_name: str
    raw_bounds: tuple[float, float, float, float, float, float]
    target_roof_exit_shell: bool = False


@dataclass(frozen=True)
class VoxelWallSourceEntry:
    source_name: str
    source_bucket: str
    material_name: str
    material_family: str
    visual_style: str | None
    display_color_rgb: dict[str, int] | None
    bounds: tuple[float, float, float, float, float, float]
    roof_exit_shell: bool = False


@dataclass(frozen=True)
class VoxelWallCell:
    u0: float
    u1: float
    v0: float
    v1: float

    def to_payload(self) -> dict[str, float]:
        return {
            "u0": _round_voxel_wall_float(self.u0),
            "u1": _round_voxel_wall_float(self.u1),
            "v0": _round_voxel_wall_float(self.v0),
            "v1": _round_voxel_wall_float(self.v1),
        }


@dataclass(frozen=True)
class AuthoredVoxelWall:
    wall_id: str
    source_name: str
    source_bucket: str
    material_name: str
    material_family: str
    visual_style: str | None
    display_color_rgb: dict[str, int] | None
    surface_u_origin_studs: float
    surface_v_origin_studs: float
    frame: VoxelWallFrame
    openings: tuple[VoxelWallOpening, ...]
    cells: tuple[VoxelWallCell, ...]

    def to_payload(self) -> dict[str, object]:
        payload = {
            "wall_id": str(self.wall_id),
            "source_bucket": str(self.source_bucket),
            "material_family": str(self.material_family),
            "surface_u_origin_studs": _round_voxel_wall_float(self.surface_u_origin_studs),
            "surface_v_origin_studs": _round_voxel_wall_float(self.surface_v_origin_studs),
            "thickness_studs": _round_voxel_wall_float(self.frame.thickness_studs),
            "local_center": {
                "x": _round_voxel_wall_float(self.frame.local_center[0]),
                "y": _round_voxel_wall_float(self.frame.local_center[1]),
                "z": _round_voxel_wall_float(self.frame.local_center[2]),
            },
            "x_axis": {
                "x": _round_voxel_wall_float(self.frame.x_axis[0]),
                "y": _round_voxel_wall_float(self.frame.x_axis[1]),
                "z": _round_voxel_wall_float(self.frame.x_axis[2]),
            },
            "y_axis": {
                "x": _round_voxel_wall_float(self.frame.y_axis[0]),
                "y": _round_voxel_wall_float(self.frame.y_axis[1]),
                "z": _round_voxel_wall_float(self.frame.y_axis[2]),
            },
            "z_axis": {
                "x": _round_voxel_wall_float(self.frame.z_axis[0]),
                "y": _round_voxel_wall_float(self.frame.z_axis[1]),
                "z": _round_voxel_wall_float(self.frame.z_axis[2]),
            },
            "cells": [cell.to_payload() for cell in self.cells],
        }
        if isinstance(self.display_color_rgb, dict):
            payload["display_color_rgb"] = {
                "r": int(self.display_color_rgb.get("r", 0)),
                "g": int(self.display_color_rgb.get("g", 0)),
                "b": int(self.display_color_rgb.get("b", 0)),
            }
        if isinstance(self.visual_style, str) and self.visual_style.strip():
            payload["visual_style"] = str(self.visual_style)
        return payload


def _name(prefix: str, suffix: str) -> str:
    return f"{prefix}_{suffix}"


def _parent_to(obj, parent):
    obj.parent = parent
    obj.matrix_parent_inverse = Matrix.Identity(4)


@contextmanager
def section_sink_scope(section_sink):
    global _ACTIVE_SECTION_SINK
    previous_sink = _ACTIVE_SECTION_SINK
    _ACTIVE_SECTION_SINK = section_sink
    try:
        yield
    finally:
        _ACTIVE_SECTION_SINK = previous_sink


@contextmanager
def output_ledger_scope(output_ledger):
    global _ACTIVE_OUTPUT_LEDGER
    previous_ledger = _ACTIVE_OUTPUT_LEDGER
    _ACTIVE_OUTPUT_LEDGER = output_ledger
    try:
        yield
    finally:
        _ACTIVE_OUTPUT_LEDGER = previous_ledger


def _queue_output_object(obj):
    if obj is None:
        return None
    ledger = _ACTIVE_OUTPUT_LEDGER
    queue_object = getattr(ledger, "queue_authored_object", None) if ledger is not None else None
    if callable(queue_object):
        queue_object(obj)
    return obj


def _register_section_object(obj, bucket: str, *, merge_allowed: bool, hide_with_walls: bool):
    if obj is None:
        return None
    ledger = _ACTIVE_OUTPUT_LEDGER
    register_object = getattr(ledger, "register_section_object", None) if ledger is not None else None
    if callable(register_object):
        register_object(
            obj,
            bucket=str(bucket),
            merge_allowed=bool(merge_allowed),
            hide_with_walls=bool(hide_with_walls),
        )
    return obj


def _queue_section_object(obj):
    if obj is None:
        return None
    sink = _ACTIVE_SECTION_SINK
    queue_object = getattr(sink, "queue_section_object", None) if sink is not None else None
    if callable(queue_object):
        queue_object(obj)
    return obj


def _keep_floor_render_top_faces(obj):
    # Legacy polybudget shortcut.  It made floor slabs one-sided, so hangars
    # and interiors showed red backfaces / transparent ceilings from below.
    # Keep the hook as a no-op to preserve callers while authoring closed slabs.
    return obj


def _mark_section(obj, bucket: str, *, merge_allowed: bool = True, hide_with_walls: bool = False):
    if str(bucket) == "Section_Floors":
        obj = _keep_floor_render_top_faces(obj)
    marked = _mark_generated(
        obj,
        tbg_section_bucket=str(bucket),
        tbg_section_merge_allowed=bool(merge_allowed),
        tbg_hide_with_walls=bool(hide_with_walls),
    )
    _register_section_object(
        marked,
        bucket,
        merge_allowed=merge_allowed,
        hide_with_walls=hide_with_walls,
    )
    return _queue_section_object(marked)


def _mark_wall_section(obj, bucket: str):
    return _mark_section(obj, bucket, hide_with_walls=True)


def _mark_door_leaf(door, closed_rotation_z: float = 0.0, open_rotation_z: float | None = None):
    if door is None:
        return None
    door = _mark_generated(
        door,
        tbg_is_door_leaf=True,
        tbg_closed_rotation_z=closed_rotation_z,
    )
    if open_rotation_z is not None:
        door["tbg_open_rotation_z"] = open_rotation_z
    return _mark_section(door, "Section_Doors_Leaf", merge_allowed=False, hide_with_walls=False)


def root_local_matrix(obj, *, root_obj=None) -> Matrix:
    if obj is None:
        return Matrix.Identity(4)
    if root_obj is not None and obj == root_obj:
        return Matrix.Identity(4)
    if obj.parent is None:
        return Matrix.Identity(4) if root_obj is None else root_obj.matrix_world.inverted() @ obj.matrix_world

    chain: list[Matrix] = []
    current = obj
    while current is not None and current != root_obj:
        parent = current.parent
        if parent is None:
            if root_obj is None:
                break
            return root_obj.matrix_world.inverted() @ obj.matrix_world
        chain.append(current.matrix_basis.copy())
        current = parent
        if root_obj is None and current.parent is None:
            break

    matrix = Matrix.Identity(4)
    for local in reversed(chain):
        matrix = matrix @ local
    return matrix


def object_local_bounds(root_obj, obj) -> tuple[float, float, float, float, float, float]:
    local_matrix = root_local_matrix(obj, root_obj=root_obj)
    corners = [local_matrix @ Vector(corner) for corner in obj.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    zs = [corner.z for corner in corners]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _round_voxel_wall_float(value: float) -> float:
    return round(float(value), 6)


def derive_voxel_wall_frame(
    bounds: tuple[float, float, float, float, float, float],
) -> VoxelWallFrame | None:
    min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in bounds)
    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z
    if min(span_x, span_y, span_z) <= 1e-5:
        return None
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    center_z = (min_z + max_z) * 0.5
    if span_x >= span_y:
        return VoxelWallFrame(
            width_axis="X",
            width_studs=float(span_x),
            height_studs=float(span_z),
            thickness_studs=float(span_y),
            local_center=(center_x, center_y, center_z),
            origin=(min_x, center_y, min_z),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
            z_axis=(0.0, 0.0, 1.0),
        )
    return VoxelWallFrame(
        width_axis="Y",
        width_studs=float(span_y),
        height_studs=float(span_z),
        thickness_studs=float(span_x),
        local_center=(center_x, center_y, center_z),
        origin=(center_x, min_y, min_z),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(1.0, 0.0, 0.0),
        z_axis=(0.0, 0.0, 1.0),
    )


def voxel_wall_opening_sort_key(opening: VoxelWallOpening) -> tuple[float, float, str, str]:
    return (
        float(opening.v_min),
        float(opening.u_min),
        str(opening.kind),
        str(opening.source_name),
    )


def quantize_voxel_wall_opening(
    frame: VoxelWallFrame,
    *,
    kind: str,
    source_name: str,
    raw_bounds: tuple[float, float, float, float, float, float],
) -> VoxelWallOpening | None:
    min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in raw_bounds)
    if frame.width_axis == "X":
        raw_u_min = min_x - float(frame.origin[0])
        raw_u_max = max_x - float(frame.origin[0])
    else:
        raw_u_min = min_y - float(frame.origin[1])
        raw_u_max = max_y - float(frame.origin[1])
    raw_v_min = min_z - float(frame.origin[2])
    raw_v_max = max_z - float(frame.origin[2])
    if raw_u_max <= 0.0 or raw_u_min >= frame.width_studs or raw_v_max <= 0.0 or raw_v_min >= frame.height_studs:
        return None
    voxel_size = float(export_contract.VOXEL_SIZE_STUDS)
    u_min = max(0.0, math.floor(raw_u_min / voxel_size) * voxel_size)
    u_max = min(frame.width_studs, math.ceil(raw_u_max / voxel_size) * voxel_size)
    v_min = max(0.0, math.floor(raw_v_min / voxel_size) * voxel_size)
    v_max = min(frame.height_studs, math.ceil(raw_v_max / voxel_size) * voxel_size)
    if u_max - u_min <= 1e-5 or v_max - v_min <= 1e-5:
        return None
    return VoxelWallOpening(
        kind=str(kind),
        source_name=str(source_name),
        u_min=u_min,
        u_max=u_max,
        v_min=v_min,
        v_max=v_max,
    )


def voxel_wall_marker_payload(
    *,
    name: str,
    source_bucket: str,
    material_family: str,
    display_color_rgb: dict[str, int] | None = None,
    visual_style: str | None = None,
    surface_u_origin_studs: float | None = None,
    surface_v_origin_studs: float | None = None,
    frame: VoxelWallFrame,
    openings: tuple[VoxelWallOpening, ...] | list[VoxelWallOpening],
) -> dict[str, object]:
    normalized_openings = tuple(sorted(tuple(openings), key=voxel_wall_opening_sort_key))
    payload = {
        "name": str(name),
        "source_bucket": str(source_bucket),
        "material_family": str(material_family),
        "voxel_size_studs": float(export_contract.VOXEL_SIZE_STUDS),
        "width_studs": _round_voxel_wall_float(frame.width_studs),
        "height_studs": _round_voxel_wall_float(frame.height_studs),
        "thickness_studs": _round_voxel_wall_float(frame.thickness_studs),
        "local_center": {
            "x": _round_voxel_wall_float(frame.local_center[0]),
            "y": _round_voxel_wall_float(frame.local_center[1]),
            "z": _round_voxel_wall_float(frame.local_center[2]),
        },
        "x_axis": {
            "x": _round_voxel_wall_float(frame.x_axis[0]),
            "y": _round_voxel_wall_float(frame.x_axis[1]),
            "z": _round_voxel_wall_float(frame.x_axis[2]),
        },
        "y_axis": {
            "x": _round_voxel_wall_float(frame.y_axis[0]),
            "y": _round_voxel_wall_float(frame.y_axis[1]),
            "z": _round_voxel_wall_float(frame.y_axis[2]),
        },
        "z_axis": {
            "x": _round_voxel_wall_float(frame.z_axis[0]),
            "y": _round_voxel_wall_float(frame.z_axis[1]),
            "z": _round_voxel_wall_float(frame.z_axis[2]),
        },
        "openings": [opening.to_payload() for opening in normalized_openings],
    }
    if isinstance(display_color_rgb, dict):
        payload["display_color_rgb"] = {
            "r": int(display_color_rgb.get("r", 0)),
            "g": int(display_color_rgb.get("g", 0)),
            "b": int(display_color_rgb.get("b", 0)),
        }
    if isinstance(visual_style, str) and visual_style.strip():
        payload["visual_style"] = str(visual_style)
    if surface_u_origin_studs is not None and math.isfinite(float(surface_u_origin_studs)):
        payload["surface_u_origin_studs"] = _round_voxel_wall_float(surface_u_origin_studs)
    if surface_v_origin_studs is not None and math.isfinite(float(surface_v_origin_studs)):
        payload["surface_v_origin_studs"] = _round_voxel_wall_float(surface_v_origin_studs)
    return payload


def resolve_voxel_wall_display_color_rgb(material_name: str) -> dict[str, int] | None:
    resolved_material_name = str(material_name or "").strip()
    if not resolved_material_name:
        return None
    material = bpy.data.materials.get(resolved_material_name)
    if material is None:
        return None
    diffuse_color = getattr(material, "diffuse_color", None)
    try:
        channels = tuple(float(diffuse_color[index]) for index in range(3))
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(channel) for channel in channels):
        return None
    return {
        "r": int(max(0, min(255, round(channels[0] * 255.0)))),
        "g": int(max(0, min(255, round(channels[1] * 255.0)))),
        "b": int(max(0, min(255, round(channels[2] * 255.0)))),
    }


def resolve_authored_voxel_wall_material_metadata(material_name: str) -> VoxelWallMaterialMetadata | None:
    """Migration-only material resolver used while section registry metadata catches up."""
    resolved_name = str(material_name or "").strip()
    if not resolved_name:
        return None
    material_key = resolved_name.lower()
    canonical_metadata = _CANONICAL_VOXEL_WALL_MATERIAL_LOOKUP.get(resolved_name)
    if canonical_metadata is not None:
        family, style = canonical_metadata
        return _voxel_wall_material_metadata(
            material_family=str(family),
            visual_style=str(style) if style else None,
            display_color_rgb=resolve_voxel_wall_display_color_rgb(resolved_name),
        )
    material = bpy.data.materials.get(resolved_name)
    if material is not None and bool(material.get("tbg_is_brick")):
        return _voxel_wall_material_metadata(
            material_family="BRICK",
            visual_style="BRICK_MASONRY",
            display_color_rgb=resolve_voxel_wall_display_color_rgb(resolved_name),
        )
    if resolved_name in _VOXEL_WALL_BRICK_MATERIAL_NAMES or material_key == "tbg_wall":
        family = "BRICK"
        style = "BRICK_MASONRY"
    elif (
        resolved_name in _VOXEL_WALL_TIMBER_SIDING_MATERIAL_NAMES
        or resolved_name in _VOXEL_WALL_TIMBER_PAINTED_MATERIAL_NAMES
        or any(token in material_key for token in ("wood", "timber", "plank", "board", "siding"))
    ):
        family = "WOOD"
        style = "TIMBER_PAINTED" if (
            resolved_name in _VOXEL_WALL_TIMBER_PAINTED_MATERIAL_NAMES or "paint" in material_key
        ) else "TIMBER_SIDING"
    elif resolved_name == INDUSTRIAL_CLADDING_MATERIAL_NAME or "metal" in material_key or "stair" in material_key:
        family = "METAL"
        style = None
    elif "concrete" in material_key or "roof" in material_key or "balcony" in material_key:
        family = "CONCRETE"
        style = None
    elif resolved_name in _VOXEL_WALL_PLASTER_MATERIAL_NAMES:
        family = "PLASTER"
        style = None
    else:
        return None
    return _voxel_wall_material_metadata(
        material_family=family,
        visual_style=style,
        display_color_rgb=resolve_voxel_wall_display_color_rgb(resolved_name),
    )


def voxel_wall_surface_phase_origin(frame: VoxelWallFrame) -> tuple[float, float]:
    if str(frame.width_axis) == "X":
        return float(frame.origin[0]), float(frame.origin[2])
    return float(frame.origin[1]), float(frame.origin[2])


def voxel_wall_opening_candidate_sort_key(
    candidate: VoxelWallOpeningCandidate,
) -> tuple[str, str, tuple[float, float, float, float, float, float]]:
    return (
        str(candidate.kind),
        str(candidate.source_name),
        tuple(float(value) for value in candidate.raw_bounds),
    )


def _summary_child_bounds(child) -> tuple[float, float, float, float, float, float] | None:
    bounds = getattr(child, "bounds", None)
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
        return None
    try:
        return tuple(float(value) for value in bounds)
    except (TypeError, ValueError):
        return None


def _finite_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _window_opening_candidate_from_summary(child) -> VoxelWallOpeningCandidate | None:
    if not bool(child.get("tbg_window_marker")):
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    opening_width = float(child.get("tbg_window_opening_width", 0.0) or 0.0)
    opening_height = float(child.get("tbg_window_opening_height", 0.0) or 0.0)
    if opening_width <= 1e-5 or opening_height <= 1e-5:
        return None
    side_key = str(child.get("tbg_window_side", "") or "").lower()
    center_x = (bounds[0] + bounds[1]) * 0.5
    center_y = (bounds[2] + bounds[3]) * 0.5
    center_z = (bounds[4] + bounds[5]) * 0.5
    stamped_cut = (
        _finite_float(child.get("tbg_wall_cut_run_min")),
        _finite_float(child.get("tbg_wall_cut_run_max")),
        _finite_float(child.get("tbg_wall_cut_z_min")),
        _finite_float(child.get("tbg_wall_cut_z_max")),
    )
    if all(value is not None for value in stamped_cut):
        cut_run_min, cut_run_max, cut_z_min, cut_z_max = (float(value) for value in stamped_cut if value is not None)
        if cut_run_max <= cut_run_min or cut_z_max <= cut_z_min:
            return None
        if side_key in {"front", "back"}:
            raw_bounds = (
                cut_run_min,
                cut_run_max,
                bounds[2],
                bounds[3],
                cut_z_min,
                cut_z_max,
            )
        elif side_key in {"left", "right"}:
            raw_bounds = (
                bounds[0],
                bounds[1],
                cut_run_min,
                cut_run_max,
                cut_z_min,
                cut_z_max,
            )
        else:
            return None
    elif side_key in {"front", "back"}:
        raw_bounds = (
            center_x - opening_width / 2,
            center_x + opening_width / 2,
            bounds[2],
            bounds[3],
            center_z - opening_height / 2,
            center_z + opening_height / 2,
        )
    elif side_key in {"left", "right"}:
        raw_bounds = (
            bounds[0],
            bounds[1],
            center_y - opening_width / 2,
            center_y + opening_width / 2,
            center_z - opening_height / 2,
            center_z + opening_height / 2,
        )
    else:
        return None
    if bool(child.get("tbg_balcony_access")):
        kind = "BALCONY_ACCESS"
    elif bool(child.get("tbg_window_open")):
        kind = "WINDOW_OPEN"
    else:
        kind = "WINDOW_CLOSED"
    return VoxelWallOpeningCandidate(
        kind=kind,
        source_name=str(getattr(child, "name", "") or "WindowOpening"),
        raw_bounds=raw_bounds,
    )


def _door_opening_candidate_from_summary(child) -> VoxelWallOpeningCandidate | None:
    if not bool(child.get("tbg_is_door_leaf")):
        return None
    if bool(child.get("tbg_roof_exit_door")) or "Door_RoofExit" in str(getattr(child, "name", "")):
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    return VoxelWallOpeningCandidate(
        kind="DOOR",
        source_name=str(getattr(child, "name", "") or "DoorOpening"),
        raw_bounds=bounds,
    )


def _attic_opening_candidate_from_summary(child) -> VoxelWallOpeningCandidate | None:
    if not bool(child.get("tbg_runtime_marker")):
        return None
    if str(child.get("tbg_runtime_role", "") or "") != export_contract.ROLE_ATTIC_OPENING:
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    return VoxelWallOpeningCandidate(
        kind="ATTIC_OPENING",
        source_name=str(child.get("tbg_runtime_source_name", "") or getattr(child, "name", "") or "AtticOpening"),
        raw_bounds=bounds,
    )


def _roof_access_opening_candidate(spatial_plan, *, wall_thickness: float) -> VoxelWallOpeningCandidate | None:
    roof_room = getattr(spatial_plan, "roof_room", None)
    if roof_room is None or not bool(getattr(spatial_plan, "roof_access_enabled", False)):
        return None
    terminal_profile = str(getattr(roof_room, "terminal_profile", "") or "").upper()
    if terminal_profile == "ATTIC_OPEN":
        return None
    shell_x0, shell_x1, shell_y0, shell_y1 = (float(value) for value in roof_room.footprint)
    shell_cx = (shell_x0 + shell_x1) * 0.5
    shell_cy = (shell_y0 + shell_y1) * 0.5
    door_width = float(getattr(roof_room, "door_width", 0.0) or 0.0)
    door_height = float(getattr(roof_room, "door_height", 0.0) or 0.0)
    thickness = max(0.01, float(wall_thickness))
    if door_width <= 1e-5 or door_height <= 1e-5:
        return None
    wall_side = str(getattr(roof_room, "door_wall", "") or "").lower()
    if wall_side == "back":
        bounds = (
            shell_cx - door_width / 2,
            shell_cx + door_width / 2,
            shell_y1 - thickness,
            shell_y1,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "front":
        bounds = (
            shell_cx - door_width / 2,
            shell_cx + door_width / 2,
            shell_y0,
            shell_y0 + thickness,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "left":
        bounds = (
            shell_x0,
            shell_x0 + thickness,
            shell_cy - door_width / 2,
            shell_cy + door_width / 2,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "right":
        bounds = (
            shell_x1 - thickness,
            shell_x1,
            shell_cy - door_width / 2,
            shell_cy + door_width / 2,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    else:
        return None
    return VoxelWallOpeningCandidate(
        kind="ROOF_ACCESS",
        source_name="RoofAccess",
        raw_bounds=bounds,
        target_roof_exit_shell=True,
    )


def collect_voxel_wall_opening_candidates(
    summary_children: tuple[object, ...] | list[object],
    *,
    spatial_plan,
    wall_thickness: float,
) -> tuple[VoxelWallOpeningCandidate, ...]:
    candidates: list[VoxelWallOpeningCandidate] = []
    for child in tuple(summary_children):
        for builder in (
            _window_opening_candidate_from_summary,
            _door_opening_candidate_from_summary,
            _attic_opening_candidate_from_summary,
        ):
            candidate = builder(child)
            if candidate is not None:
                candidates.append(candidate)
                break
    roof_access_candidate = _roof_access_opening_candidate(spatial_plan, wall_thickness=wall_thickness)
    if roof_access_candidate is not None:
        candidates.append(roof_access_candidate)
    return tuple(sorted(candidates, key=voxel_wall_opening_candidate_sort_key))


def opening_candidate_targets_voxel_wall_source_entry(
    opening_candidate: VoxelWallOpeningCandidate,
    source_entry: VoxelWallSourceEntry,
) -> bool:
    if str(opening_candidate.kind) != "ROOF_ACCESS":
        return True
    return bool(source_entry.roof_exit_shell)


def _normalized_display_color_rgb(raw_color) -> dict[str, int] | None:
    if not isinstance(raw_color, dict):
        return None
    try:
        return {
            "r": int(raw_color.get("r", 0)),
            "g": int(raw_color.get("g", 0)),
            "b": int(raw_color.get("b", 0)),
        }
    except (TypeError, ValueError):
        return None


def _voxel_wall_source_entry_sort_key(entry: VoxelWallSourceEntry) -> tuple[object, ...]:
    color = entry.display_color_rgb or {}
    return (
        str(entry.source_bucket),
        str(entry.material_family),
        str(entry.visual_style or ""),
        int(color.get("r", 0)),
        int(color.get("g", 0)),
        int(color.get("b", 0)),
        tuple(float(value) for value in entry.bounds),
        str(entry.source_name),
    )


def _resolved_voxel_wall_source_bounds(
    *,
    source_name: str,
    fragment: dict,
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    fragment_part_bounds = fragment.get("part_bounds")
    resolved_part_bounds: list[tuple[float, float, float, float, float, float]] = []
    if fragment_part_bounds is not None:
        if not isinstance(fragment_part_bounds, (list, tuple)):
            raise VoxelWallOccupancyContractError(
                f"Voxel wall source '{source_name}' has invalid part_bounds."
            )
        for bounds in fragment_part_bounds:
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
                raise VoxelWallOccupancyContractError(
                    f"Voxel wall source '{source_name}' has invalid part_bounds."
                )
            try:
                resolved_part_bounds.append(tuple(float(value) for value in bounds))
            except (TypeError, ValueError) as exc:
                raise VoxelWallOccupancyContractError(
                    f"Voxel wall source '{source_name}' has invalid part_bounds."
                ) from exc
    if resolved_part_bounds:
        return tuple(resolved_part_bounds)
    bounds = fragment.get("bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
        raise VoxelWallOccupancyContractError(
            f"Voxel wall source '{source_name}' is missing authoritative bounds."
        )
    try:
        return (tuple(float(value) for value in bounds),)
    except (TypeError, ValueError) as exc:
        raise VoxelWallOccupancyContractError(
            f"Voxel wall source '{source_name}' has invalid bounds."
        ) from exc


def iter_voxel_wall_source_entries(section_registry: dict) -> tuple[VoxelWallSourceEntry, ...]:
    sections = tuple(section_registry.get("sections") or ()) if isinstance(section_registry, dict) else ()
    entries: list[VoxelWallSourceEntry] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        bucket = str(section.get("bucket", "") or "")
        if bucket not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            continue
        material_name = str(section.get("material_name", "") or "")
        source_fragments = section.get("source_fragments")
        has_fragment_items = isinstance(source_fragments, list) and bool(source_fragments)
        if not has_fragment_items and bool(section.get("roof_exit_shell")):
            continue
        fragment_items = source_fragments if has_fragment_items else [section]
        for fragment in fragment_items:
            if not isinstance(fragment, dict):
                continue
            source_name = str(fragment.get("source_name", "") or section.get("name", "") or bucket)
            material_family = str(fragment.get("material_family") or section.get("material_family") or "").strip()
            if material_family not in export_contract.VOXEL_WALL_MATERIAL_FAMILIES:
                raise VoxelWallOccupancyContractError(
                    f"Voxel wall source '{source_name}' is missing canonical material_family metadata."
                )
            visual_style = str(fragment.get("visual_style") or section.get("visual_style") or "").strip() or None
            if visual_style is not None and visual_style not in export_contract.VOXEL_WALL_VISUAL_STYLES:
                raise VoxelWallOccupancyContractError(
                    f"Voxel wall source '{source_name}' has unsupported visual_style '{visual_style}'."
                )

            fragment_roof_exit_shell = bool(fragment.get("roof_exit_shell"))
            display_color_rgb = _normalized_display_color_rgb(
                fragment.get("display_color_rgb", section.get("display_color_rgb"))
            )
            for resolved_bounds in _resolved_voxel_wall_source_bounds(
                source_name=source_name,
                fragment=fragment,
            ):
                if fragment_roof_exit_shell:
                    continue
                entries.append(
                    VoxelWallSourceEntry(
                        source_name=source_name,
                        source_bucket=bucket,
                        material_name=material_name,
                        material_family=material_family,
                        visual_style=visual_style,
                        display_color_rgb=display_color_rgb,
                        bounds=resolved_bounds,
                        roof_exit_shell=fragment_roof_exit_shell,
                    )
                )
    return tuple(sorted(entries, key=_voxel_wall_source_entry_sort_key))


def iterate_exact_voxel_wall_cells(
    frame: VoxelWallFrame,
    openings: tuple[VoxelWallOpening, ...] | list[VoxelWallOpening],
) -> tuple[VoxelWallCell, ...]:
    voxel_size = float(export_contract.VOXEL_SIZE_STUDS)
    epsilon = 1e-6
    cell_u_count = int(math.ceil(float(frame.width_studs) / voxel_size))
    cell_v_count = int(math.ceil(float(frame.height_studs) / voxel_size))
    surviving: list[VoxelWallCell] = []
    for v_index in range(cell_v_count):
        cell_v0 = float(v_index) * voxel_size
        cell_v1 = min(float(frame.height_studs), cell_v0 + voxel_size)
        if (cell_v1 - cell_v0) <= epsilon:
            continue
        for u_index in range(cell_u_count):
            cell_u0 = float(u_index) * voxel_size
            cell_u1 = min(float(frame.width_studs), cell_u0 + voxel_size)
            if (cell_u1 - cell_u0) <= epsilon:
                continue
            blocked = False
            for opening in openings:
                if cell_u0 < float(opening.u_max) and cell_u1 > float(opening.u_min) and cell_v0 < float(opening.v_max) and cell_v1 > float(opening.v_min):
                    blocked = True
                    break
            if not blocked:
                surviving.append(VoxelWallCell(u0=cell_u0, u1=cell_u1, v0=cell_v0, v1=cell_v1))
    return tuple(surviving)


def _voxel_wall_cell_world_signature(frame: VoxelWallFrame, cell: VoxelWallCell) -> tuple[float, float, float]:
    origin = Vector(frame.origin)
    center = origin + Vector(frame.x_axis) * ((cell.u0 + cell.u1) * 0.5) + Vector(frame.z_axis) * ((cell.v0 + cell.v1) * 0.5)
    return (
        _round_voxel_wall_float(center.x),
        _round_voxel_wall_float(center.y),
        _round_voxel_wall_float(center.z),
    )


def _authored_voxel_wall_sort_key(wall: AuthoredVoxelWall) -> tuple[object, ...]:
    color = wall.display_color_rgb or {}
    return (
        str(wall.source_bucket),
        str(wall.material_family),
        str(wall.visual_style or ""),
        int(color.get("r", 0)),
        int(color.get("g", 0)),
        int(color.get("b", 0)),
        _round_voxel_wall_float(wall.frame.local_center[0]),
        _round_voxel_wall_float(wall.frame.local_center[1]),
        _round_voxel_wall_float(wall.frame.local_center[2]),
        str(wall.source_name),
    )


def build_authored_voxel_walls(
    *,
    building_id: str,
    section_registry: dict,
    summary_children: tuple[object, ...] | list[object],
    spatial_plan,
    wall_thickness: float,
) -> tuple[AuthoredVoxelWall, ...]:
    opening_candidates = collect_voxel_wall_opening_candidates(
        summary_children,
        spatial_plan=spatial_plan,
        wall_thickness=wall_thickness,
    )
    drafted_walls: list[AuthoredVoxelWall] = []
    seen_cell_signatures: set[tuple[float, float, float]] = set()
    for source_entry in iter_voxel_wall_source_entries(section_registry):
        frame = derive_voxel_wall_frame(tuple(float(value) for value in source_entry.bounds))
        if frame is None:
            continue
        openings: list[VoxelWallOpening] = []
        for opening_candidate in opening_candidates:
            if not opening_candidate_targets_voxel_wall_source_entry(opening_candidate, source_entry):
                continue
            opening = quantize_voxel_wall_opening(
                frame,
                kind=str(opening_candidate.kind),
                source_name=str(opening_candidate.source_name),
                raw_bounds=opening_candidate.raw_bounds,
            )
            if opening is not None:
                openings.append(opening)
        openings_tuple = tuple(sorted(openings, key=voxel_wall_opening_sort_key))
        cells = iterate_exact_voxel_wall_cells(frame, openings_tuple)
        if not cells:
            continue
        for cell in cells:
            signature = _voxel_wall_cell_world_signature(frame, cell)
            if signature in seen_cell_signatures:
                raise VoxelWallOccupancyContractError(
                    f"Duplicate authored voxel wall cell detected at {signature}."
                )
            seen_cell_signatures.add(signature)
        surface_u_origin_studs, surface_v_origin_studs = voxel_wall_surface_phase_origin(frame)
        drafted_walls.append(
            AuthoredVoxelWall(
                wall_id="",
                source_name=source_entry.source_name,
                source_bucket=source_entry.source_bucket,
                material_name=source_entry.material_name,
                material_family=source_entry.material_family,
                visual_style=source_entry.visual_style,
                display_color_rgb=source_entry.display_color_rgb,
                surface_u_origin_studs=surface_u_origin_studs,
                surface_v_origin_studs=surface_v_origin_studs,
                frame=frame,
                openings=openings_tuple,
                cells=cells,
            )
        )
    sorted_walls = sorted(drafted_walls, key=_authored_voxel_wall_sort_key)
    return tuple(
        replace(wall, wall_id=f"{str(building_id)}_Wall_{index:04d}")
        for index, wall in enumerate(sorted_walls, start=1)
    )


def total_authored_voxel_wall_cell_count(walls: tuple[AuthoredVoxelWall, ...] | list[AuthoredVoxelWall]) -> int:
    return sum(len(tuple(wall.cells)) for wall in tuple(walls))


def build_voxel_wall_occupancy_payload(
    *,
    building_id: str,
    section_registry: dict,
    summary_children: tuple[object, ...] | list[object],
    spatial_plan,
    wall_thickness: float,
) -> dict[str, object]:
    walls = build_authored_voxel_walls(
        building_id=building_id,
        section_registry=section_registry,
        summary_children=summary_children,
        spatial_plan=spatial_plan,
        wall_thickness=wall_thickness,
    )
    return {
        "voxel_size_studs": float(export_contract.VOXEL_SIZE_STUDS),
        "walls": [wall.to_payload() for wall in walls],
    }


def _voxel_wall_frame_cell_keys(frame: VoxelWallFrame) -> frozenset[tuple[float, float, float]]:
    voxel_size = float(export_contract.VOXEL_SIZE_STUDS)
    epsilon = 1e-6
    center = Vector(frame.local_center)
    x_axis_vec = Vector(frame.x_axis)
    z_axis_vec = Vector(frame.z_axis)
    origin = center - x_axis_vec * (float(frame.width_studs) * 0.5) - z_axis_vec * (float(frame.height_studs) * 0.5)
    cell_keys: set[tuple[float, float, float]] = set()
    cell_u_count = int(math.ceil(float(frame.width_studs) / voxel_size))
    cell_v_count = int(math.ceil(float(frame.height_studs) / voxel_size))
    for v_index in range(cell_v_count):
        cell_v0 = float(v_index) * voxel_size
        cell_v1 = min(float(frame.height_studs), cell_v0 + voxel_size)
        if (cell_v1 - cell_v0) <= epsilon:
            continue
        cell_v_mid = (cell_v0 + cell_v1) * 0.5
        for u_index in range(cell_u_count):
            cell_u0 = float(u_index) * voxel_size
            cell_u1 = min(float(frame.width_studs), cell_u0 + voxel_size)
            if (cell_u1 - cell_u0) <= epsilon:
                continue
            cell_u_mid = (cell_u0 + cell_u1) * 0.5
            center_point = origin + x_axis_vec * cell_u_mid + z_axis_vec * cell_v_mid
            cell_keys.add(
                (
                    _round_voxel_wall_float(center_point.x),
                    _round_voxel_wall_float(center_point.y),
                    _round_voxel_wall_float(center_point.z),
                )
            )
    return frozenset(cell_keys)


def merge_coplanar_voxel_wall_source_entries(
    entries: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    bucket_precedence = {
        bucket_name: index
        for index, bucket_name in enumerate(tuple(export_contract.VOXEL_WALL_SOURCE_BUCKETS))
    }
    grouped_entries: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for raw_entry in tuple(entries):
        if not isinstance(raw_entry, dict):
            continue
        bounds = raw_entry.get("bounds")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
            continue
        try:
            resolved_bounds = tuple(float(value) for value in bounds)
        except (TypeError, ValueError):
            continue
        frame = derive_voxel_wall_frame(resolved_bounds)
        if frame is None:
            continue
        if str(frame.width_axis) == "X":
            plane_coordinate = _round_voxel_wall_float(frame.local_center[1])
        else:
            plane_coordinate = _round_voxel_wall_float(frame.local_center[0])
        group_key = (
            str(frame.width_axis),
            plane_coordinate,
            _round_voxel_wall_float(frame.thickness_studs),
        )
        normalized_entry = dict(raw_entry)
        normalized_entry["bounds"] = resolved_bounds
        grouped_entries.setdefault(group_key, []).append(normalized_entry)

    merged_entries: list[dict[str, object]] = []
    for group_key in sorted(grouped_entries):
        pending = list(
            sorted(
                grouped_entries[group_key],
                key=lambda item: (
                    bucket_precedence.get(str(item.get("bucket", "") or ""), len(bucket_precedence)),
                    str(item.get("material_name", "") or ""),
                    str(item.get("visual_style", "") or ""),
                    tuple(float(value) for value in item["bounds"]),
                    str(item.get("source_name", "") or ""),
                ),
            )
        )
        merged_group: list[dict[str, object]] = []
        while pending:
            current = pending.pop(0)
            current_bounds = tuple(float(value) for value in current["bounds"])
            current_frame = derive_voxel_wall_frame(current_bounds)
            if current_frame is None:
                continue
            current_u0, current_u1 = voxel_wall_surface_phase_origin(current_frame)[0], voxel_wall_surface_phase_origin(current_frame)[0] + float(current_frame.width_studs)
            current_v0 = float(current_frame.origin[2])
            current_v1 = float(current_frame.origin[2]) + float(current_frame.height_studs)
            current_cell_keys = _voxel_wall_frame_cell_keys(current_frame)
            merged_names = [str(current.get("source_name", "") or "")]
            changed = True
            while changed:
                changed = False
                next_pending: list[dict[str, object]] = []
                for candidate in pending:
                    candidate_bounds = tuple(float(value) for value in candidate["bounds"])
                    candidate_frame = derive_voxel_wall_frame(candidate_bounds)
                    if candidate_frame is None:
                        next_pending.append(candidate)
                        continue
                    candidate_u0 = voxel_wall_surface_phase_origin(candidate_frame)[0]
                    candidate_u1 = candidate_u0 + float(candidate_frame.width_studs)
                    candidate_v0 = float(candidate_frame.origin[2])
                    candidate_v1 = float(candidate_frame.origin[2]) + float(candidate_frame.height_studs)
                    candidate_cell_keys = _voxel_wall_frame_cell_keys(candidate_frame)
                    overlaps_u = candidate_u0 <= current_u1 + 1e-6 and candidate_u1 >= current_u0 - 1e-6
                    overlaps_v = candidate_v0 <= current_v1 + 1e-6 and candidate_v1 >= current_v0 - 1e-6
                    same_visual_signature = (
                        str(candidate.get("bucket", "") or "") == str(current.get("bucket", "") or "")
                        and str(candidate.get("material_name", "") or "") == str(current.get("material_name", "") or "")
                        and str(candidate.get("visual_style", "") or "") == str(current.get("visual_style", "") or "")
                        and candidate.get("display_color_rgb") == current.get("display_color_rgb")
                    )
                    if current_cell_keys.intersection(candidate_cell_keys) or (same_visual_signature and overlaps_u and overlaps_v):
                        changed = True
                        current_u0 = min(current_u0, candidate_u0)
                        current_u1 = max(current_u1, candidate_u1)
                        current_v0 = min(current_v0, candidate_v0)
                        current_v1 = max(current_v1, candidate_v1)
                        if str(group_key[0]) == "X":
                            current_bounds = (
                                current_u0,
                                current_u1,
                                float(group_key[1]) - (float(group_key[2]) * 0.5),
                                float(group_key[1]) + (float(group_key[2]) * 0.5),
                                current_v0,
                                current_v1,
                            )
                        else:
                            current_bounds = (
                                float(group_key[1]) - (float(group_key[2]) * 0.5),
                                float(group_key[1]) + (float(group_key[2]) * 0.5),
                                current_u0,
                                current_u1,
                                current_v0,
                                current_v1,
                            )
                        current_frame = derive_voxel_wall_frame(current_bounds)
                        if current_frame is not None:
                            current_cell_keys = _voxel_wall_frame_cell_keys(current_frame)
                        merged_names.append(str(candidate.get("source_name", "") or ""))
                        continue
                    next_pending.append(candidate)
                pending = next_pending
            width_axis = str(group_key[0])
            plane_coordinate = float(group_key[1])
            thickness_studs = float(group_key[2])
            if width_axis == "X":
                merged_bounds = (
                    current_u0,
                    current_u1,
                    plane_coordinate - (thickness_studs * 0.5),
                    plane_coordinate + (thickness_studs * 0.5),
                    current_v0,
                    current_v1,
                )
            else:
                merged_bounds = (
                    plane_coordinate - (thickness_studs * 0.5),
                    plane_coordinate + (thickness_studs * 0.5),
                    current_u0,
                    current_u1,
                    current_v0,
                    current_v1,
                )
            merged_entry = dict(current)
            merged_entry["bounds"] = tuple(_round_voxel_wall_float(value) for value in merged_bounds)
            merged_entry["source_name"] = "+".join(sorted({name for name in merged_names if name}))
            merged_group.append(merged_entry)
        merged_entries.extend(
            sorted(
                merged_group,
                key=lambda item: (
                    bucket_precedence.get(str(item.get("bucket", "") or ""), len(bucket_precedence)),
                    str(item.get("bucket", "") or ""),
                    str(item.get("material_name", "") or ""),
                    str(item.get("source_name", "") or ""),
                    tuple(float(value) for value in item["bounds"]),
                ),
            )
        )
    return tuple(merged_entries)


def planned_voxel_wall_marker_payload(
    *,
    name: str,
    source_bucket: str,
    material_family: str,
    display_color_rgb: dict[str, int] | None = None,
    visual_style: str | None = None,
    surface_u_origin_studs: float | None = None,
    surface_v_origin_studs: float | None = None,
    frame: VoxelWallFrame,
    openings: tuple[VoxelWallOpening, ...] | list[VoxelWallOpening],
) -> tuple[dict[str, object], int]:
    payload = voxel_wall_marker_payload(
        name=name,
        source_bucket=source_bucket,
        material_family=material_family,
        display_color_rgb=display_color_rgb,
        visual_style=visual_style,
        surface_u_origin_studs=surface_u_origin_studs,
        surface_v_origin_studs=surface_v_origin_studs,
        frame=frame,
        openings=openings,
    )
    estimated_part_count = estimate_voxel_wall_marker_part_count(payload)
    return payload, int(estimated_part_count)


def estimate_voxel_wall_marker_part_count(payload: dict[str, object]) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        width_studs = float(payload.get("width_studs", 0.0) or 0.0)
        height_studs = float(payload.get("height_studs", 0.0) or 0.0)
        voxel_size = float(payload.get("voxel_size_studs", export_contract.VOXEL_SIZE_STUDS) or 0.0)
    except (TypeError, ValueError):
        return 0
    if width_studs <= 0.0 or height_studs <= 0.0 or voxel_size <= 0.0:
        return 0
    openings_payload = payload.get("openings")
    openings = tuple(openings_payload) if isinstance(openings_payload, (list, tuple)) else ()
    cell_u_count = int(math.ceil(width_studs / voxel_size))
    cell_v_count = int(math.ceil(height_studs / voxel_size))
    surviving = 0
    for v_index in range(cell_v_count):
        cell_v0 = float(v_index) * voxel_size
        cell_v1 = min(height_studs, cell_v0 + voxel_size)
        for u_index in range(cell_u_count):
            cell_u0 = float(u_index) * voxel_size
            cell_u1 = min(width_studs, cell_u0 + voxel_size)
            blocked = False
            for opening in openings:
                if not isinstance(opening, dict):
                    continue
                try:
                    u_min = float(opening.get("u_min", 0.0))
                    u_max = float(opening.get("u_max", 0.0))
                    v_min = float(opening.get("v_min", 0.0))
                    v_max = float(opening.get("v_max", 0.0))
                except (TypeError, ValueError):
                    continue
                if cell_u0 < u_max and cell_u1 > u_min and cell_v0 < v_max and cell_v1 > v_min:
                    blocked = True
                    break
            if not blocked:
                surviving += 1
    return int(surviving)


def write_voxel_wall_marker_payload(
    obj,
    payload: dict[str, object],
    *,
    estimated_part_count: int | None = None,
) -> int:
    if obj is None:
        return 0
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    resolved_part_count = (
        estimate_voxel_wall_marker_part_count(payload)
        if estimated_part_count is None
        else int(estimated_part_count)
    )
    obj[_VOXEL_WALL_MARKER_PAYLOAD_KEY] = serialized
    obj[_VOXEL_WALL_MARKER_ESTIMATED_PART_COUNT_KEY] = int(resolved_part_count)
    return int(resolved_part_count)


def read_voxel_wall_marker_payload(obj) -> dict[str, object] | None:
    if obj is None:
        return None
    payload = obj.get(_VOXEL_WALL_MARKER_PAYLOAD_KEY)
    if not isinstance(payload, str) or not payload.strip():
        return None
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _bounds_corners(bounds: tuple[float, float, float, float, float, float]) -> tuple[tuple[float, float, float], ...]:
    x0, x1, y0, y1, z0, z1 = bounds
    return (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )


def _part_bounds_from_size_center(
    size: tuple[float, float, float],
    center: tuple[float, float, float],
) -> tuple[float, float, float, float, float, float]:
    sx, sy, sz = (float(value) for value in size)
    cx, cy, cz = (float(value) for value in center)
    return (
        cx - sx / 2,
        cx + sx / 2,
        cy - sy / 2,
        cy + sy / 2,
        cz - sz / 2,
        cz + sz / 2,
    )


def _normalized_part_bounds(
    bounds: tuple[float, float, float, float, float, float],
    *,
    precision: int,
) -> tuple[float, float, float, float, float, float] | None:
    normalized = tuple(round(float(value), precision) for value in bounds)
    if (
        normalized[1] - normalized[0] <= 1e-6
        or normalized[3] - normalized[2] <= 1e-6
        or normalized[5] - normalized[4] <= 1e-6
    ):
        return None
    return normalized


def composite_part_local_bounds(obj) -> tuple[tuple[float, float, float, float, float, float], ...]:
    if obj is None:
        return ()
    raw_payload = obj.get(_COMPOSITE_PART_BOUNDS_KEY)
    if not raw_payload:
        return ()
    try:
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, (list, tuple)):
        return ()
    bounds_items: list[tuple[float, float, float, float, float, float]] = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) != 6:
            continue
        try:
            bounds = tuple(float(value) for value in item)
        except (TypeError, ValueError):
            continue
        normalized = _normalized_part_bounds(bounds, precision=6)
        if normalized is not None:
            bounds_items.append(normalized)
    return tuple(bounds_items)


def composite_part_root_local_bounds(root_obj, obj) -> tuple[tuple[float, float, float, float, float, float], ...]:
    part_bounds = composite_part_local_bounds(obj)
    if not part_bounds:
        return ()
    local_matrix = root_local_matrix(obj, root_obj=root_obj)
    transformed_bounds: list[tuple[float, float, float, float, float, float]] = []
    for bounds in part_bounds:
        corners = [local_matrix @ Vector(corner) for corner in _bounds_corners(bounds)]
        xs = [corner.x for corner in corners]
        ys = [corner.y for corner in corners]
        zs = [corner.z for corner in corners]
        normalized = _normalized_part_bounds(
            (
                min(xs),
                max(xs),
                min(ys),
                max(ys),
                min(zs),
                max(zs),
            ),
            precision=4,
        )
        if normalized is not None:
            transformed_bounds.append(normalized)
    return tuple(transformed_bounds)


def _store_composite_part_bounds(obj, parts) -> None:
    if obj is None:
        return
    serialized_bounds = []
    for size, center in parts:
        normalized = _normalized_part_bounds(_part_bounds_from_size_center(size, center), precision=6)
        if normalized is not None:
            serialized_bounds.append(list(normalized))
    if serialized_bounds:
        obj[_COMPOSITE_PART_BOUNDS_KEY] = json.dumps(serialized_bounds, separators=(",", ":"))


def _assign_material(obj, material):
    from .material_uv import _apply_material_uv

    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)
    _apply_material_uv(obj, material)


def _assign_material_slot_only(obj, material):
    mesh = getattr(obj, "data", None)
    if obj is None or mesh is None or material is None:
        return
    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)


def _mark_generated(obj, **metadata_values):
    if obj is None:
        return None
    for key, value in metadata_values.items():
        obj[key] = value
    return _queue_output_object(obj)


def _mark_service_object(obj, anchor, role: str, *, flavor: bool = False):
    return _mark_section(
        _mark_generated(
            obj,
            tbg_roof_service=True,
            tbg_service_anchor_id=anchor.anchor_id,
            tbg_service_anchor_side=anchor.wall_side,
            tbg_service_anchor_kind=anchor.kind,
            tbg_service_role=role,
            tbg_roof_flavor=bool(flavor),
        ),
        "Section_Services_Prop",
    )


def _mark_service_detail(obj, anchor):
    return _mark_section(
        _mark_generated(
            obj,
            tbg_service_detail=True,
            tbg_service_anchor_id=anchor.anchor_id,
            tbg_service_anchor_side=anchor.wall_side,
            tbg_service_anchor_kind=anchor.kind,
        ),
        "Section_Services_Helper",
    )


def _mesh_from_pydata(name: str, verts, faces, *, recalc_normals: bool = False):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    if recalc_normals:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
    mesh.update()
    return mesh


def _box_mesh(name: str, size: tuple[float, float, float], *, origin_mode: str = "CENTER"):
    sx, sy, sz = size
    if origin_mode == "HINGE_LEFT":
        x0, x1 = 0.0, sx
        z0, z1 = -sz / 2, sz / 2
    elif origin_mode == "HINGE_RIGHT":
        x0, x1 = -sx, 0.0
        z0, z1 = -sz / 2, sz / 2
    else:
        x0, x1 = -sx / 2, sx / 2
        z0, z1 = -sz / 2, sz / 2

    y0, y1 = -sy / 2, sy / 2
    verts = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return _mesh_from_pydata(name, verts, faces)


def _box_geometry(size: tuple[float, float, float], center: tuple[float, float, float]):
    sx, sy, sz = size
    cx, cy, cz = center
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    verts = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def _composite_box_mesh(name: str, parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]]):
    verts = []
    faces = []
    for size, center in parts:
        part_verts, part_faces = _box_geometry(size, center)
        offset = len(verts)
        verts.extend(part_verts)
        faces.extend(tuple(idx + offset for idx in face) for face in part_faces)
    return _mesh_from_pydata(name, verts, faces, recalc_normals=True)


def _cylinder_mesh(name: str, radius: float, depth: float, *, sides: int = 10):
    verts = []
    faces = []
    half_depth = depth / 2
    for ring_y in (-half_depth, half_depth):
        for idx in range(sides):
            angle = math.tau * idx / sides
            verts.append((math.cos(angle) * radius, ring_y, math.sin(angle) * radius))

    bottom_center = len(verts)
    verts.append((0.0, -half_depth, 0.0))
    top_center = len(verts)
    verts.append((0.0, half_depth, 0.0))

    for idx in range(sides):
        nxt = (idx + 1) % sides
        faces.append((idx, nxt, sides + nxt, sides + idx))
        faces.append((bottom_center, nxt, idx))
        faces.append((top_center, sides + idx, sides + nxt))

    return _mesh_from_pydata(name, verts, faces)


def _ramp_mesh(name: str, width: float, depth: float, height: float):
    half_w = width / 2
    half_d = depth / 2
    half_h = height / 2
    verts = [
        (-half_w, -half_d, -half_h),
        (half_w, -half_d, -half_h),
        (half_w, half_d, -half_h),
        (-half_w, half_d, -half_h),
        (-half_w, half_d, half_h),
        (half_w, half_d, half_h),
    ]
    faces = [
        (0, 1, 2, 3),
        (0, 3, 4),
        (1, 5, 2),
        (0, 1, 5, 4),
        (3, 2, 5, 4),
    ]
    return _mesh_from_pydata(name, verts, faces, recalc_normals=True)


def _frame_mesh(
    name: str,
    outer_width: float,
    depth: float,
    outer_height: float,
    inner_width: float,
    inner_height: float,
    *,
    visible_positive_depth: bool,
    inner_center_z_offset: float = 0.0,
    include_inner_returns: bool = True,
    double_sided: bool = False,
):
    outer_w = outer_width / 2
    outer_h = outer_height / 2
    inner_w = min(inner_width / 2, outer_w - 0.01)
    inner_h = min(inner_height / 2, outer_h - 0.01)
    inner_z0 = inner_center_z_offset - inner_h
    inner_z1 = inner_center_z_offset + inner_h
    front = -depth / 2
    back = depth / 2

    verts = [
        (-outer_w, front, -outer_h),
        (outer_w, front, -outer_h),
        (outer_w, front, outer_h),
        (-outer_w, front, outer_h),
        (-outer_w, back, -outer_h),
        (outer_w, back, -outer_h),
        (outer_w, back, outer_h),
        (-outer_w, back, outer_h),
        (-inner_w, front, inner_z0),
        (inner_w, front, inner_z0),
        (inner_w, front, inner_z1),
        (-inner_w, front, inner_z1),
        (-inner_w, back, inner_z0),
        (inner_w, back, inner_z0),
        (inner_w, back, inner_z1),
        (-inner_w, back, inner_z1),
    ]
    front_ring_faces = [
        (0, 1, 9, 8),
        (1, 2, 10, 9),
        (2, 3, 11, 10),
        (3, 0, 8, 11),
    ]
    back_ring_faces = [
        (4, 12, 13, 5),
        (5, 13, 14, 6),
        (6, 14, 15, 7),
        (7, 15, 12, 4),
    ]
    inner_return_faces = [
        (8, 9, 13, 12),
        (9, 10, 14, 13),
        (10, 11, 15, 14),
        (11, 8, 12, 15),
    ]
    # A frame is a physical low-poly gasket, not a one-sided decorative ring.
    # Keep both front/back rings and close the outer perimeter so validation and
    # export see a watertight solid instead of a hollow shell with boundary edges.
    outer_perimeter_faces = [
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    faces = [*(front_ring_faces + back_ring_faces + outer_perimeter_faces)]
    # Inner returns are part of the gasket seal.  Older office-style callers
    # could omit them, which made a visually open/sharp frame; keep the
    # argument for API compatibility but always close the inner perimeter.
    _ = include_inner_returns
    faces.extend(inner_return_faces)
    return _mesh_from_pydata(name, verts, faces, recalc_normals=True)


def _solid_stepped_flight_mesh(name: str, width: float, tread: float, step_count: int, step_rise: float):
    run_total = tread * max(step_count, 1)
    start_edge = -run_total / 2
    profile = [(start_edge, 0.0), (start_edge, step_rise)]
    for idx in range(step_count):
        edge_y = start_edge + (idx + 1) * tread
        edge_z = (idx + 1) * step_rise
        profile.append((edge_y, edge_z))
        if idx < step_count - 1:
            profile.append((edge_y, edge_z + step_rise))
    profile.append((start_edge + run_total, 0.0))

    left_x = -width / 2
    right_x = width / 2
    verts = [(left_x, y, z) for y, z in profile] + [(right_x, y, z) for y, z in profile]
    count = len(profile)
    faces = []
    for idx in range(count):
        nxt = (idx + 1) % count
        faces.append((idx, nxt, count + nxt, count + idx))
    faces.append(tuple(range(count)))
    faces.append(tuple(range(count * 2 - 1, count - 1, -1)))

    return _mesh_from_pydata(name, verts, faces, recalc_normals=True)


def _stepped_flight_mesh(name: str, width: float, tread: float, step_count: int, step_rise: float, step_t: float):
    run_total = tread * max(step_count, 1)
    start_edge = -run_total / 2
    tread_thickness = min(max(0.03, step_t), max(0.03, step_rise))
    riser_thickness = min(0.045, max(0.018, tread * 0.2))
    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []

    for idx in range(max(step_count, 1)):
        tread_center_y = start_edge + idx * tread + tread / 2
        tread_top_z = (idx + 1) * step_rise
        tread_center_z = tread_top_z - tread_thickness / 2
        parts.append(((width, tread, tread_thickness), (0.0, tread_center_y, tread_center_z)))

        if idx < step_count - 1:
            riser_height = max(0.0, step_rise - tread_thickness)
            if riser_height > 1e-4:
                riser_center_y = start_edge + (idx + 1) * tread - riser_thickness / 2
                riser_center_z = tread_top_z + riser_height / 2
                parts.append(((width, riser_thickness, riser_height), (0.0, riser_center_y, riser_center_z)))

    mesh = _composite_box_mesh(name, parts)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)
    return mesh


def _create_box(
    name,
    size,
    location,
    collection,
    parent,
    material,
    *,
    rotation=(0.0, 0.0, 0.0),
    origin_mode="CENTER",
):
    if min(size) <= 1e-4:
        return None

    mesh = _box_mesh(name, size, origin_mode=origin_mode)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    _assign_material(obj, material)
    return obj


def _create_cylinder(name, radius, depth, location, collection, parent, material, *, rotation=(0.0, 0.0, 0.0), sides=10):
    mesh = _cylinder_mesh(name, radius, depth, sides=sides)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    _assign_material(obj, material)
    return obj


def _create_composite_box_object(name, parts, location, collection, parent, material, *, rotation=(0.0, 0.0, 0.0)):
    mesh = _composite_box_mesh(name, parts)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    _assign_material(obj, material)
    _store_composite_part_bounds(obj, parts)
    return obj


def _apply_uniform_world_scale(root_obj, scale: float):
    if root_obj is None or abs(scale - 1.0) <= 1e-6:
        return
    root_obj.scale = Vector((scale, scale, scale))
