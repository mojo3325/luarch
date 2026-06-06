from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

from . import constants, export_contract, metadata
from .generator.building_layout import _spatial_plan, _spatial_plan_roof_opening_bounds
from .generator.building_roof import (
    _gable_ridge_rise,
    _is_hangar_frontage,
    _roof_longitudinal_axis,
    _roof_mode,
    _roof_surface_z,
    _sloped_roof_rect_with_terrace_clearance,
    _top_mass_rect,
)
from .generator.building_support import (
    object_local_bounds,
    root_local_matrix,
)


_LIGHT_PRESETS = {
    export_contract.LIGHT_ROLE_ROOM: {
        "color": (1.0, 236.0 / 255.0, 220.0 / 255.0),
        "brightness": 1.25,
        "range_scale": 0.72,
    },
    export_contract.LIGHT_ROLE_STAIR: {
        "color": (242.0 / 255.0, 245.0 / 255.0, 1.0),
        "brightness": 1.35,
        "range_scale": 0.78,
    },
    export_contract.LIGHT_ROLE_ENTRY: {
        "color": (1.0, 244.0 / 255.0, 228.0 / 255.0),
        "brightness": 1.45,
        "range_scale": 0.68,
    },
    export_contract.LIGHT_ROLE_ROOF_EXIT: {
        "color": (250.0 / 255.0, 246.0 / 255.0, 232.0 / 255.0),
        "brightness": 1.3,
        "range_scale": 0.74,
    },
}

_AUTHOR_ROOT_PART_SIZE = (0.25, 0.25, 0.25)
_LIGHT_ANCHOR_SIZE = (0.35, 0.35, 0.35)
_TRANSFORM_EPSILON = 1e-6
_BOUNDS_EPSILON = 1e-6
_BLENDER_TO_ROBLOX_BASIS = Matrix(
    (
        (-1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0),
    )
)
_ROBLOX_TO_BLENDER_BASIS = _BLENDER_TO_ROBLOX_BASIS.inverted()
_STRUCTURAL_SECTION_BUCKETS = frozenset(
    {
        "Section_Floors",
        "Section_Stairs_Flights",
        "Section_Stairs_Landings",
        "Section_Stairs_RoomShell",
        "Section_Walls_Exterior",
        "Section_Walls_ExteriorSurfaceTile",
        "Section_Walls_Interior",
        "Section_Walls_Canopy",
        "Section_Walls_Roof",
    }
)
_STRUCTURAL_SECTION_PREFIXES = ("Section_Openings_Balcony_",)
_TRAVERSAL_RUNTIME_ROLES = frozenset(
    {
        export_contract.ROLE_ENTRY_LANDING,
        export_contract.ROLE_ENTRY_WEDGE,
        export_contract.ROLE_FLOOR_BLOCKER,
        export_contract.ROLE_PODIUM_BLOCKER,
        export_contract.ROLE_ROOF_EXIT_PLATFORM,
        export_contract.ROLE_STAIR_LANDING,
        export_contract.ROLE_STAIR_RAMP,
    }
)


@dataclass(frozen=True)
class _PartTransform:
    position: tuple[float, float, float]
    rotation_rows: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    size: tuple[float, float, float]


class _RbxmxWriter:
    def __init__(self):
        self._referent_index = 1
        self.root = ET.Element(
            "roblox",
            {
                "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
                "version": "4",
            },
        )
        ET.SubElement(self.root, "External").text = "null"
        ET.SubElement(self.root, "External").text = "nil"

    def _new_item(self, parent, class_name: str):
        item = ET.SubElement(parent, "Item", {"class": class_name, "referent": f"RBX{self._referent_index:08d}"})
        self._referent_index += 1
        return item, ET.SubElement(item, "Properties")

    @staticmethod
    def _string(properties, name: str, value: str):
        node = ET.SubElement(properties, "string", {"name": name})
        node.text = value

    @staticmethod
    def _bool(properties, name: str, value: bool):
        node = ET.SubElement(properties, "bool", {"name": name})
        node.text = "true" if value else "false"

    @staticmethod
    def _float(properties, name: str, value: float):
        node = ET.SubElement(properties, "float", {"name": name})
        node.text = format(float(value), ".9g")

    @staticmethod
    def _double(properties, name: str, value: float):
        node = ET.SubElement(properties, "double", {"name": name})
        node.text = format(float(value), ".17g")

    @staticmethod
    def _int64(properties, name: str, value: int):
        node = ET.SubElement(properties, "int64", {"name": name})
        node.text = str(int(value))

    @staticmethod
    def _vector3(properties, name: str, value: tuple[float, float, float]):
        node = ET.SubElement(properties, "Vector3", {"name": name})
        ET.SubElement(node, "X").text = format(float(value[0]), ".9g")
        ET.SubElement(node, "Y").text = format(float(value[1]), ".9g")
        ET.SubElement(node, "Z").text = format(float(value[2]), ".9g")

    @staticmethod
    def _color3(properties, name: str, value: tuple[float, float, float]):
        node = ET.SubElement(properties, "Color3", {"name": name})
        ET.SubElement(node, "R").text = format(float(value[0]), ".9g")
        ET.SubElement(node, "G").text = format(float(value[1]), ".9g")
        ET.SubElement(node, "B").text = format(float(value[2]), ".9g")

    @staticmethod
    def _cframe(properties, name: str, position: tuple[float, float, float], rotation_rows):
        node = ET.SubElement(properties, "CoordinateFrame", {"name": name})
        ET.SubElement(node, "X").text = format(float(position[0]), ".9g")
        ET.SubElement(node, "Y").text = format(float(position[1]), ".9g")
        ET.SubElement(node, "Z").text = format(float(position[2]), ".9g")
        ET.SubElement(node, "R00").text = format(float(rotation_rows[0][0]), ".9g")
        ET.SubElement(node, "R01").text = format(float(rotation_rows[0][1]), ".9g")
        ET.SubElement(node, "R02").text = format(float(rotation_rows[0][2]), ".9g")
        ET.SubElement(node, "R10").text = format(float(rotation_rows[1][0]), ".9g")
        ET.SubElement(node, "R11").text = format(float(rotation_rows[1][1]), ".9g")
        ET.SubElement(node, "R12").text = format(float(rotation_rows[1][2]), ".9g")
        ET.SubElement(node, "R20").text = format(float(rotation_rows[2][0]), ".9g")
        ET.SubElement(node, "R21").text = format(float(rotation_rows[2][1]), ".9g")
        ET.SubElement(node, "R22").text = format(float(rotation_rows[2][2]), ".9g")

    def add_model(self, name: str):
        item, properties = self._new_item(self.root, "Model")
        self._string(properties, "Name", name)
        return item

    def add_folder(self, parent, name: str):
        item, properties = self._new_item(parent, "Folder")
        self._string(properties, "Name", name)
        return item

    def add_string_value(self, parent, name: str, value: str):
        item, properties = self._new_item(parent, "StringValue")
        self._string(properties, "Name", name)
        self._string(properties, "Value", value)
        return item

    def add_int_value(self, parent, name: str, value: int):
        item, properties = self._new_item(parent, "IntValue")
        self._string(properties, "Name", name)
        self._int64(properties, "Value", value)
        return item

    def add_number_value(self, parent, name: str, value: float):
        item, properties = self._new_item(parent, "NumberValue")
        self._string(properties, "Name", name)
        self._double(properties, "Value", value)
        return item

    def add_vector3_value(self, parent, name: str, value: tuple[float, float, float]):
        item, properties = self._new_item(parent, "Vector3Value")
        self._string(properties, "Name", name)
        self._vector3(properties, "Value", value)
        return item

    def add_part(
        self,
        parent,
        *,
        class_name: str,
        name: str,
        transform: _PartTransform,
        anchored: bool,
        transparency: float,
        can_collide: bool,
        can_query: bool,
        can_touch: bool,
        cast_shadow: bool,
        collision_group: str | None = None,
    ):
        item, properties = self._new_item(parent, class_name)
        self._string(properties, "Name", name)
        self._cframe(properties, "CFrame", transform.position, transform.rotation_rows)
        self._vector3(properties, "Size", transform.size)
        self._bool(properties, "Anchored", anchored)
        self._float(properties, "Transparency", transparency)
        self._bool(properties, "CanCollide", can_collide)
        self._bool(properties, "CanQuery", can_query)
        self._bool(properties, "CanTouch", can_touch)
        self._bool(properties, "CastShadow", cast_shadow)
        if collision_group:
            self._string(properties, "CollisionGroup", collision_group)
        return item

    def add_point_light(
        self,
        parent,
        *,
        color: tuple[float, float, float],
        brightness: float,
        range_value: float,
    ):
        item, properties = self._new_item(parent, "PointLight")
        self._string(properties, "Name", "PointLight")
        self._bool(properties, "Enabled", True)
        self._color3(properties, "Color", color)
        self._float(properties, "Brightness", brightness)
        self._float(properties, "Range", range_value)
        self._bool(properties, "Shadows", False)
        return item

    def write(self, filepath: Path):
        tree = ET.ElementTree(self.root)
        ET.indent(tree, space="\t")
        tree.write(filepath, encoding="utf-8", xml_declaration=False)


def _uniform_world_scale(root_obj) -> float:
    scale = tuple(float(value) for value in root_obj.matrix_world.to_scale())
    if max(scale) - min(scale) > _TRANSFORM_EPSILON:
        raise RuntimeError("RBXMX sidecar export requires a uniformly scaled root.")
    return float(sum(scale) / 3.0)


def _mesh_children(root_obj):
    return [child for child in root_obj.children_recursive if child.type == "MESH"]


def _is_hidden_helper_mesh(child) -> bool:
    return bool(
        child.hide_viewport
        and child.hide_render
        and not str(child.get("tbg_section_bucket", "")).strip()
    )


def runtime_render_meshes(root_obj):
    return [
        child
        for child in _mesh_children(root_obj)
        if not child.get("tbg_runtime_marker")
        and export_contract.parse_export_contract_marker_name(child.name) is None
        and not child.get("tbg_contract_marker")
        and not child.get("tbg_voxel_wall_marker")
        and not child.get("tbg_voxel_preview")
        and str(child.get("tbg_section_bucket", "") or "") not in export_contract.VOXEL_WALL_SOURCE_BUCKETS
        and not _is_hidden_helper_mesh(child)
    ]


def export_root_hierarchy_objects(root_obj):
    return [root_obj, *runtime_render_meshes(root_obj)]


def root_local_fbx_basis_matrix(root_obj) -> Matrix:
    matrix = root_obj.matrix_world.copy()
    matrix.translation = Vector((0.0, 0.0, 0.0))
    return matrix


def _runtime_markers(root_obj):
    return [child for child in _mesh_children(root_obj) if child.get("tbg_runtime_marker")]


def _voxel_wall_occupancy_payload(root_obj) -> dict[str, object]:
    try:
        payload = metadata.read_voxel_wall_occupancy_payload(root_obj, strict=True)
    except metadata.MetadataContractError as exc:
        raise RuntimeError(f"RBXMX sidecar export requires canonical voxel wall occupancy payload: {exc}") from exc
    if not payload:
        raise RuntimeError("RBXMX sidecar export requires canonical voxel wall occupancy payload.")
    _voxel_wall_occupancy_summary(payload)
    return payload


def _voxel_wall_occupancy_summary(payload: dict[str, object]) -> tuple[int, int]:
    payload_kind = payload.get("payload_kind")
    if payload_kind != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
        raise RuntimeError(
            "RBXMX sidecar export requires V3 wall-cell payload kind "
            f"{export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND!r}."
        )
    payload_version = payload.get("payload_version")
    if payload_version != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
        raise RuntimeError(
            "RBXMX sidecar export requires V3 wall-cell payload version "
            f"{export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION!r}."
        )
    for legacy_key in ("wa" + "lls", "authored_" + "cu" + "boid_count"):
        if legacy_key in payload:
            raise RuntimeError("RBXMX sidecar export rejected legacy wall occupancy keys in the V3 payload.")

    cells_payload = payload.get("cells")
    groups_payload = payload.get("wall_groups")
    if not isinstance(cells_payload, list) or not cells_payload:
        raise RuntimeError("RBXMX sidecar export requires at least one authored wall cell.")
    if not isinstance(groups_payload, list) or not groups_payload:
        raise RuntimeError("RBXMX sidecar export requires V3 wall_groups.")

    authored_cell_count = payload.get("authored_cell_count")
    authored_group_count = payload.get("authored_group_count")
    if not isinstance(authored_cell_count, int) or isinstance(authored_cell_count, bool):
        raise RuntimeError("RBXMX sidecar export requires integer authored_cell_count.")
    if authored_cell_count != len(cells_payload):
        raise RuntimeError(
            "RBXMX sidecar export rejected authored_cell_count mismatch "
            f"({authored_cell_count} != {len(cells_payload)})."
        )
    if authored_cell_count <= 0 or authored_cell_count > export_contract.MAX_WALL_RUNTIME_PARTS:
        raise RuntimeError(
            "RBXMX sidecar export rejected wall-cell count outside runtime budget "
            f"({authored_cell_count} > {export_contract.MAX_WALL_RUNTIME_PARTS})."
        )
    if not isinstance(authored_group_count, int) or isinstance(authored_group_count, bool):
        raise RuntimeError("RBXMX sidecar export requires integer authored_group_count.")
    if authored_group_count != len(groups_payload):
        raise RuntimeError(
            "RBXMX sidecar export rejected authored_group_count mismatch "
            f"({authored_group_count} != {len(groups_payload)})."
        )

    _validate_wall_cell_membership(cells_payload, groups_payload)
    _validate_wall_cell_bounds(cells_payload)
    return int(authored_cell_count), int(authored_group_count)


def _finite_positive_vector_dict(value: object, *, key: str, positive: bool) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        raise RuntimeError(f"RBXMX sidecar export requires {key} vector dictionaries on every wall cell.")
    try:
        vector = (float(value["x"]), float(value["y"]), float(value["z"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"RBXMX sidecar export requires finite x/y/z values in {key}.") from exc
    if not all(math.isfinite(component) for component in vector):
        raise RuntimeError(f"RBXMX sidecar export rejected non-finite {key}.")
    if positive and not all(component > 0.0 for component in vector):
        raise RuntimeError(f"RBXMX sidecar export rejected non-positive {key}.")
    return vector


def _validate_wall_cell_membership(cells_payload: list[object], groups_payload: list[object]) -> None:
    cell_ids: set[str] = set()
    group_member_counts: dict[str, int] = {}
    for cell in cells_payload:
        if not isinstance(cell, dict):
            raise RuntimeError("RBXMX sidecar export requires every wall cell entry to be an object.")
        cell_id = str(cell.get("cell_id", "")).strip()
        group_id = str(cell.get("group_id", "")).strip()
        if not cell_id or not group_id:
            raise RuntimeError("RBXMX sidecar export requires cell_id and group_id on every wall cell.")
        if cell_id in cell_ids:
            raise RuntimeError(f"RBXMX sidecar export rejected duplicate wall cell id {cell_id!r}.")
        cell_ids.add(cell_id)
        group_member_counts[group_id] = group_member_counts.get(group_id, 0) + 1

    group_ids: set[str] = set()
    for group in groups_payload:
        if not isinstance(group, dict):
            raise RuntimeError("RBXMX sidecar export requires every wall group entry to be an object.")
        group_id = str(group.get("group_id", "")).strip()
        if not group_id:
            raise RuntimeError("RBXMX sidecar export requires group_id on every wall group.")
        if group_id in group_ids:
            raise RuntimeError(f"RBXMX sidecar export rejected duplicate wall group id {group_id!r}.")
        group_ids.add(group_id)

        group_cell_count = group.get("cell_count")
        if not isinstance(group_cell_count, int) or isinstance(group_cell_count, bool):
            raise RuntimeError("RBXMX sidecar export requires integer wall_groups[].cell_count.")
        if group_cell_count != group_member_counts.get(group_id, 0):
            raise RuntimeError("RBXMX sidecar export rejected wall group cell_count/member mismatch.")
        texture_key = str(group.get("texture_key", "") or "").strip()
        if not texture_key:
            raise RuntimeError("RBXMX sidecar export requires wall_groups[].texture_key.")
        projection = str(group.get("texture_projection", "") or "").strip().upper()
        if projection not in export_contract.TEXTURE_PROJECTIONS:
            raise RuntimeError("RBXMX sidecar export rejected invalid wall_groups[].texture_projection.")
        period_contract = str(group.get("texture_image_period_contract", "") or "").strip().upper()
        if period_contract not in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS:
            raise RuntimeError("RBXMX sidecar export rejected invalid wall_groups[].texture_image_period_contract.")
        table_version = str(group.get("texture_face_axis_table_version", "") or "").strip().upper()
        if table_version != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1:
            raise RuntimeError("RBXMX sidecar export rejected invalid wall_groups[].texture_face_axis_table_version.")
        color_policy = str(group.get("color_modulation_policy", "") or "").strip().upper()
        if color_policy != export_contract.COLOR_MODULATION_POLICY_NONE:
            raise RuntimeError("RBXMX sidecar export rejected invalid wall_groups[].color_modulation_policy.")
        for period_key in ("studs_per_tile_u", "studs_per_tile_v"):
            try:
                period_value = float(group[period_key])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"RBXMX sidecar export requires finite positive wall_groups[].{period_key}.") from exc
            if not math.isfinite(period_value) or period_value <= 0.0:
                raise RuntimeError(f"RBXMX sidecar export rejected non-positive wall_groups[].{period_key}.")
    unknown_groups = tuple(sorted(set(group_member_counts).difference(group_ids)))
    if unknown_groups:
        raise RuntimeError("RBXMX sidecar export rejected cells that reference unknown wall groups.")


def _validate_wall_cell_bounds(cells_payload: list[object]) -> None:
    bounds: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
    for cell in cells_payload:
        assert isinstance(cell, dict)
        cell_id = str(cell.get("cell_id", "")).strip()
        normal_axis = str(cell.get("normal_axis", "") or "").strip().lower()
        run_axis = str(cell.get("run_axis", "") or "").strip().lower()
        if normal_axis not in {"x", "y"}:
            raise RuntimeError(
                f"RBXMX sidecar export rejected wall cell {cell_id!r} with invalid normal_axis {normal_axis!r}."
            )
        expected_run_axis = "y" if normal_axis == "x" else "x"
        if run_axis != expected_run_axis:
            raise RuntimeError(
                f"RBXMX sidecar export rejected wall cell {cell_id!r} with run_axis {run_axis!r}; "
                f"expected {expected_run_axis!r}."
            )
        cell_min = _finite_positive_vector_dict(cell.get("min_studs"), key="min_studs", positive=False)
        cell_size = _finite_positive_vector_dict(cell.get("size_studs"), key="size_studs", positive=True)
        normal_index = 0 if normal_axis == "x" else 1
        if cell_size[normal_index] <= _BOUNDS_EPSILON or cell_size[2] <= _BOUNDS_EPSILON:
            raise RuntimeError(f"RBXMX sidecar export rejected non-vertical wall cell {cell_id!r}.")
        bounds.append((cell_id, cell_min, cell_size))

    for left_index, (left_id, left_min, left_size) in enumerate(bounds):
        for right_id, right_min, right_size in bounds[left_index + 1 :]:
            overlap_x = min(left_min[0] + left_size[0], right_min[0] + right_size[0]) - max(left_min[0], right_min[0])
            overlap_y = min(left_min[1] + left_size[1], right_min[1] + right_size[1]) - max(left_min[1], right_min[1])
            overlap_z = min(left_min[2] + left_size[2], right_min[2] + right_size[2]) - max(left_min[2], right_min[2])
            if overlap_x > _BOUNDS_EPSILON and overlap_y > _BOUNDS_EPSILON and overlap_z > _BOUNDS_EPSILON:
                raise RuntimeError(
                    "RBXMX sidecar export rejected positive-volume wall-cell overlap "
                    f"between {left_id!r} and {right_id!r}."
                )


def _voxel_wall_occupancy_chunks(payload: dict[str, object]) -> tuple[str, ...]:
    payload_json = _stable_json(payload)
    try:
        return export_contract.split_voxel_wall_occupancy_json(payload_json)
    except ValueError as exc:
        raise RuntimeError(f"RBXMX sidecar export occupancy chunking failed: {exc}") from exc


def _convert_vector_to_roblox(vector: Vector) -> Vector:
    return _BLENDER_TO_ROBLOX_BASIS @ vector


def _convert_size_to_roblox(size: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        float(size[0]),
        float(size[2]),
        float(size[1]),
    )


def _local_mesh_size(obj, scale: float) -> tuple[float, float, float]:
    xs = [float(corner[0]) for corner in obj.bound_box]
    ys = [float(corner[1]) for corner in obj.bound_box]
    zs = [float(corner[2]) for corner in obj.bound_box]
    return _convert_size_to_roblox(
        (
            (max(xs) - min(xs)) * scale,
            (max(ys) - min(ys)) * scale,
            (max(zs) - min(zs)) * scale,
        )
    )


def _evaluated_local_vertex_bounds(root_obj, obj, depsgraph) -> tuple[float, float, float, float, float, float] | None:
    root_inv = root_obj.matrix_world.inverted()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        if mesh is None or not mesh.vertices:
            return None
        coords = [root_inv @ (obj_eval.matrix_world @ vertex.co) for vertex in mesh.vertices]
    finally:
        obj_eval.to_mesh_clear()
    xs = [coord.x for coord in coords]
    ys = [coord.y for coord in coords]
    zs = [coord.z for coord in coords]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _matrix_rotation_rows(rotation: Matrix) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    roblox_rotation = _BLENDER_TO_ROBLOX_BASIS @ rotation @ _ROBLOX_TO_BLENDER_BASIS
    return (
        (
            float(roblox_rotation[0][0]),
            float(roblox_rotation[0][1]),
            float(roblox_rotation[0][2]),
        ),
        (
            float(roblox_rotation[1][0]),
            float(roblox_rotation[1][1]),
            float(roblox_rotation[1][2]),
        ),
        (
            float(roblox_rotation[2][0]),
            float(roblox_rotation[2][1]),
            float(roblox_rotation[2][2]),
        ),
    )


def _matrix_rotation_axes(rotation: Matrix) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    roblox_rotation = _BLENDER_TO_ROBLOX_BASIS @ rotation @ _ROBLOX_TO_BLENDER_BASIS
    return (
        (
            float(roblox_rotation[0][0]),
            float(roblox_rotation[1][0]),
            float(roblox_rotation[2][0]),
        ),
        (
            float(roblox_rotation[0][1]),
            float(roblox_rotation[1][1]),
            float(roblox_rotation[2][1]),
        ),
        (
            float(roblox_rotation[0][2]),
            float(roblox_rotation[1][2]),
            float(roblox_rotation[2][2]),
        ),
    )


def _wedge_rotation_rows(marker, local_matrix: Matrix):
    role = str(marker.get("tbg_runtime_role", ""))
    if role == export_contract.ROLE_STAIR_WEDGE:
        direction = float(marker.get("tbg_runtime_direction", 1.0))
        angle = math.pi if direction < 0.0 else 0.0
        rotation = Euler((0.0, 0.0, angle), "XYZ").to_matrix()
        return _matrix_rotation_rows(rotation)
    return _matrix_rotation_rows(local_matrix.to_quaternion().to_matrix())


def _scaled_local_transform(root_obj, marker, scale: float) -> _PartTransform:
    local_matrix = root_local_matrix(marker, root_obj=root_obj)
    translation = _convert_vector_to_roblox(local_matrix.to_translation() * scale)
    shape = str(marker.get("tbg_runtime_shape", export_contract.RUNTIME_SHAPE_BOX))
    if shape == export_contract.RUNTIME_SHAPE_WEDGE:
        rotation_rows = _wedge_rotation_rows(marker, local_matrix)
    else:
        rotation_rows = _matrix_rotation_rows(local_matrix.to_quaternion().to_matrix())
    return _PartTransform(
        position=(float(translation.x), float(translation.y), float(translation.z)),
        rotation_rows=rotation_rows,
        size=_local_mesh_size(marker, scale),
    )


def _render_bounds(root_obj, render_meshes, scale: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not render_meshes:
        raise RuntimeError("RBXMX sidecar export requires at least one render mesh.")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bounds = [_evaluated_local_vertex_bounds(root_obj, mesh, depsgraph) for mesh in render_meshes]
    bounds = [item for item in bounds if item is not None]
    if not bounds:
        raise RuntimeError("RBXMX sidecar export requires evaluated render mesh geometry.")
    xs = [value for bounds_item in bounds for value in bounds_item[:2]]
    ys = [value for bounds_item in bounds for value in bounds_item[2:4]]
    zs = [value for bounds_item in bounds for value in bounds_item[4:6]]
    center = (
        (min(xs) + max(xs)) * 0.5 * scale,
        (min(ys) + max(ys)) * 0.5 * scale,
        (min(zs) + max(zs)) * 0.5 * scale,
    )
    center_vector = _convert_vector_to_roblox(Vector(center))
    size = _convert_size_to_roblox(
        (
            (max(xs) - min(xs)) * scale,
            (max(ys) - min(ys)) * scale,
            (max(zs) - min(zs)) * scale,
        )
    )
    return (float(center_vector.x), float(center_vector.y), float(center_vector.z)), size


def _runtime_name(name: str) -> str:
    return name.replace("Meta_", "Runtime_", 1) if name.startswith("Meta_") else name


def _author_root_transform() -> _PartTransform:
    return _PartTransform(
        position=(0.0, 0.0, 0.0),
        rotation_rows=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        size=_AUTHOR_ROOT_PART_SIZE,
    )


def _light_anchor_transform(root_obj, marker, scale: float, preset: dict[str, float | tuple[float, float, float]]) -> tuple[_PartTransform, float]:
    marker_transform = _scaled_local_transform(root_obj, marker, scale)
    marker_size = marker_transform.size
    anchor_transform = _PartTransform(
        position=marker_transform.position,
        rotation_rows=marker_transform.rotation_rows,
        size=_LIGHT_ANCHOR_SIZE,
    )
    range_value = min(18.0, max(7.0, max(marker_size[0], marker_size[1]) * float(preset["range_scale"])))
    return anchor_transform, range_value


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _round_float(value: float) -> float:
    return round(float(value), 6)


def _bounds_to_roblox(bounds: tuple[float, float, float, float, float, float], scale: float) -> list[float]:
    min_x, max_x, min_y, max_y, min_z, max_z = bounds
    corners = (
        Vector((x, y, z))
        for x in (min_x, max_x)
        for y in (min_y, max_y)
        for z in (min_z, max_z)
    )
    converted = [_convert_vector_to_roblox(corner * scale) for corner in corners]
    xs = [coord.x for coord in converted]
    ys = [coord.y for coord in converted]
    zs = [coord.z for coord in converted]
    return [
        _round_float(min(xs)),
        _round_float(max(xs)),
        _round_float(min(ys)),
        _round_float(max(ys)),
        _round_float(min(zs)),
        _round_float(max(zs)),
    ]


def _vector_payload(values: tuple[float, float, float]) -> list[float]:
    return [_round_float(values[0]), _round_float(values[1]), _round_float(values[2])]


def _is_structural_section_bucket(bucket: str) -> bool:
    if bucket in _STRUCTURAL_SECTION_BUCKETS:
        return True
    return any(bucket.startswith(prefix) for prefix in _STRUCTURAL_SECTION_PREFIXES)


def _structural_seed_kind(
    *,
    bucket: str,
    roof_exit_shell: bool,
    top_room_floor: bool,
    stair_flight: bool,
    entrance_part: str,
) -> str:
    if roof_exit_shell:
        return "ROOF_ROOM_SHELL"
    if top_room_floor:
        return "ROOF_ROOM_FLOOR"
    if stair_flight or bucket == "Section_Stairs_Flights":
        return "STAIR_RAMP"
    if str(entrance_part or "").lower() == "step":
        return "ENTRY_RAMP"
    if bucket == "Section_Floors":
        return "FLOOR"
    if bucket == "Section_Stairs_Landings":
        return "LANDING"
    if bucket == "Section_Stairs_RoomShell":
        return "STAIR_ROOM_SHELL"
    if bucket == "Section_Walls_Canopy":
        return "ENTRY_CANOPY"
    if bucket == "Section_Walls_Roof":
        return "ROOF_SHELL"
    if bucket in {"Section_Walls_Exterior", "Section_Walls_ExteriorSurfaceTile", "Section_Walls_Interior"}:
        return "WALL_SHELL"
    if bucket.startswith("Section_Openings_Balcony_"):
        return "BALCONY_FLOOR"
    return "DECORATIVE"


def _destruction_grid_payload(
    *,
    render_bounds_size: tuple[float, float, float],
    render_anchor_to_author_root: tuple[float, float, float],
) -> dict[str, object]:
    return {
        "cell_size_studs": _round_float(export_contract.CELL_SIZE_STUDS),
        "chunk_size_cells": int(export_contract.CHUNK_SIZE_CELLS),
        "chunk_size_studs": _round_float(export_contract.CHUNK_SIZE_STUDS),
        "coordinate_space": "AUTHOR_ROOT_LOCAL_ROBLOX_STUDS",
        "render_anchor_basis": export_contract.RENDER_ANCHOR_BASIS_BOUNDS_CENTER,
        "render_anchor_to_author_root": [_round_float(value) for value in render_anchor_to_author_root],
        "render_bounds_size": [_round_float(value) for value in render_bounds_size],
    }


def _build_structural_mesh_ledger(
    *,
    section_registry: dict,
    render_meshes,
    scale: float,
) -> list[dict[str, object]]:
    def _iter_section_fragments(section: dict) -> list[dict[str, object]]:
        section_name = str(section.get("name", "") or "")
        section_bounds = section.get("bounds")
        fragments = section.get("source_fragments")
        normalized: list[dict[str, object]] = []
        seen_signatures: set[tuple[str, tuple[float, float, float, float, float, float], bool, bool]] = set()
        if isinstance(fragments, list):
            for index, fragment in enumerate(fragments, start=1):
                if not isinstance(fragment, dict):
                    continue
                fragment_bounds = fragment.get("bounds")
                if not isinstance(fragment_bounds, (list, tuple)) or len(fragment_bounds) != 6:
                    continue
                source_name = str(fragment.get("source_name", "") or f"{section_name}__Fragment_{index:03d}")
                bounds = tuple(float(item) for item in fragment_bounds)
                roof_exit_shell = bool(fragment.get("roof_exit_shell", False))
                top_room_floor = bool(fragment.get("top_room_floor", False))
                signature = (source_name, bounds, roof_exit_shell, top_room_floor)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                normalized.append(
                    {
                        "source_name": source_name,
                        "bounds": bounds,
                        "roof_exit_shell": roof_exit_shell,
                        "top_room_floor": top_room_floor,
                        "stair_flight": bool(fragment.get("stair_flight", False)),
                        "stair_direction": (
                            float(fragment.get("stair_direction"))
                            if fragment.get("stair_direction") is not None
                            else None
                        ),
                        "entrance_part": str(fragment.get("entrance_part", "") or ""),
                        "facade_side": str(fragment.get("facade_side", "") or ""),
                    }
                )
        if normalized:
            return normalized
        if isinstance(section_bounds, (list, tuple)) and len(section_bounds) == 6:
            return [
                {
                    "source_name": section_name,
                    "bounds": tuple(float(item) for item in section_bounds),
                    "roof_exit_shell": bool(section.get("roof_exit_shell", False)),
                    "top_room_floor": bool(section.get("top_room_floor", False)),
                    "stair_flight": False,
                    "stair_direction": None,
                    "entrance_part": "",
                    "facade_side": "",
                }
            ]
        return []

    render_mesh_names = {str(mesh.name) for mesh in render_meshes}
    sections = list(section_registry.get("sections") or [])
    ledger: list[dict[str, object]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        bucket = str(section.get("bucket", "") or "")
        mesh_name = str(section.get("name", "") or "")
        material_name = str(section.get("material_name", "") or "")
        structural = _is_structural_section_bucket(bucket)
        for fragment_index, fragment in enumerate(_iter_section_fragments(section), start=1):
            roof_exit_shell = bool(fragment.get("roof_exit_shell", False))
            top_room_floor = bool(fragment.get("top_room_floor", False))
            stair_flight = bool(fragment.get("stair_flight", False))
            stair_direction = (
                float(fragment.get("stair_direction"))
                if fragment.get("stair_direction") is not None
                else None
            )
            entrance_part = str(fragment.get("entrance_part", "") or "")
            facade_side = str(fragment.get("facade_side", "") or "")
            ledger.append(
                {
                    "mesh_name": str(fragment.get("source_name", "") or mesh_name),
                    "render_section_name": mesh_name,
                    "mesh_present": mesh_name in render_mesh_names,
                    "bucket": bucket,
                    "material_name": material_name,
                    "merge_allowed": bool(section.get("merge_allowed", True)),
                    "hide_with_walls": bool(section.get("hide_with_walls", False)),
                    "source_count": int(section.get("source_count", 0) or 0),
                    "fragment_index": fragment_index,
                    "structural": structural,
                    "seed_kind": _structural_seed_kind(
                        bucket=bucket,
                        roof_exit_shell=roof_exit_shell,
                        top_room_floor=top_room_floor,
                        stair_flight=stair_flight,
                        entrance_part=entrance_part,
                    ),
                    "roof_exit_shell": roof_exit_shell,
                    "top_room_floor": top_room_floor,
                    "stair_flight": stair_flight,
                    "stair_direction": stair_direction,
                    "entrance_part": entrance_part,
                    "facade_side": facade_side,
                    "bounds": _bounds_to_roblox(tuple(float(item) for item in fragment["bounds"]), scale),
                }
            )
    return ledger


def _build_solid_seeds(structural_mesh_ledger: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "mesh_name": str(entry["mesh_name"]),
            "seed_kind": str(entry["seed_kind"]),
            "bucket": str(entry["bucket"]),
            "material_name": str(entry["material_name"]),
            "bounds": list(entry["bounds"]) if isinstance(entry.get("bounds"), list) else None,
            "roof_exit_shell": bool(entry["roof_exit_shell"]),
            "top_room_floor": bool(entry["top_room_floor"]),
            "stair_flight": bool(entry.get("stair_flight", False)),
            "stair_direction": (
                float(entry["stair_direction"]) if entry.get("stair_direction") is not None else None
            ),
            "entrance_part": str(entry.get("entrance_part", "") or ""),
            "facade_side": str(entry.get("facade_side", "") or ""),
        }
        for entry in structural_mesh_ledger
        if bool(entry.get("structural"))
    ]


def _expand_window_opening_bounds(
    bounds: tuple[float, float, float, float, float, float],
    *,
    side: str,
    wall_thickness_local: float,
) -> tuple[float, float, float, float, float, float]:
    min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in bounds)
    frame_margin = max(0.04, wall_thickness_local * 0.18)
    opening_depth = max(max_y - min_y, 0.34, wall_thickness_local * 2.2)
    vertical_margin = 0.04
    side_key = str(side or "").lower()
    if side_key in {"front", "back"}:
        center_y = (min_y + max_y) * 0.5
        half_depth = opening_depth * 0.5
        min_x -= frame_margin
        max_x += frame_margin
        min_y = center_y - half_depth
        max_y = center_y + half_depth
    elif side_key in {"left", "right"}:
        center_x = (min_x + max_x) * 0.5
        half_depth = opening_depth * 0.5
        min_y -= frame_margin
        max_y += frame_margin
        min_x = center_x - half_depth
        max_x = center_x + half_depth
    else:
        min_x -= frame_margin
        max_x += frame_margin
        min_y -= frame_margin
        max_y += frame_margin
    min_z -= vertical_margin
    max_z += vertical_margin
    return (min_x, max_x, min_y, max_y, min_z, max_z)


def _window_opening_marker_index(root_obj, spec, scale: float) -> dict[tuple[str, int, int], dict[str, object]]:
    index: dict[tuple[str, int, int], dict[str, object]] = {}
    wall_thickness_local = max(0.14, float(getattr(spec, "wall_thickness", 0.0)))
    for marker in _mesh_children(root_obj):
        if not bool(marker.get("tbg_window_marker")) or not bool(marker.get("tbg_window_open")):
            continue
        side = str(marker.get("tbg_window_side", "") or "")
        floor = int(marker.get("tbg_window_floor", -1))
        slot = int(marker.get("tbg_facade_slot", marker.get("tbg_window_slot", -1)))
        if not side or floor < 0 or slot < 0:
            continue
        index[(side, floor, slot)] = {
            "source_name": str(marker.name),
            "bounds": _bounds_to_roblox(
                _expand_window_opening_bounds(
                    object_local_bounds(root_obj, marker),
                    side=side,
                    wall_thickness_local=wall_thickness_local,
                ),
                scale,
            ),
        }
    return index


def _window_opening_void_seeds(root_obj, scale: float) -> list[dict[str, object]]:
    seeds: list[dict[str, object]] = []
    role_to_void_kind = {
        export_contract.ROLE_ATTIC_OPENING: "ATTIC_OPENING",
        export_contract.ROLE_BALCONY_ACCESS_OPENING: "BALCONY_ACCESS",
        export_contract.ROLE_OPEN_WINDOW_OPENING: "OPEN_WINDOW",
    }
    for marker in sorted(_runtime_markers(root_obj), key=lambda item: item.name):
        role = str(marker.get("tbg_runtime_role", "") or "")
        void_kind = role_to_void_kind.get(role)
        if void_kind is None:
            continue
        side = str(marker.get("tbg_runtime_side", "") or "")
        floor = int(marker.get("tbg_runtime_floor", -1))
        slot = int(marker.get("tbg_runtime_slot", -1))
        seed: dict[str, object] = {
            "void_kind": void_kind,
            "source_name": str(marker.get("tbg_runtime_source_name", "") or marker.name),
            "side": side,
            "floor": floor,
            "slot": slot,
            "span_key": str(marker.get("tbg_runtime_span_key", "") or ""),
            "bounds": _bounds_to_roblox(object_local_bounds(root_obj, marker), scale),
        }
        opening_size = _local_mesh_size(marker, scale)
        seed["opening_width_studs"] = _round_float(float(max(opening_size[0], opening_size[2])))
        seed["opening_height_studs"] = _round_float(float(opening_size[1]))
        seeds.append(seed)
    return seeds


def _build_traversal_seeds(root_obj, scale: float) -> list[dict[str, object]]:
    seeds: list[dict[str, object]] = []
    for marker in sorted(_runtime_markers(root_obj), key=lambda item: item.name):
        if str(marker.get("tbg_runtime_kind", "")) != export_contract.RUNTIME_KIND_COLLISION:
            continue
        role = str(marker.get("tbg_runtime_role", "") or "")
        if role not in _TRAVERSAL_RUNTIME_ROLES:
            continue
        local_matrix = root_local_matrix(marker, root_obj=root_obj)
        x_axis, y_axis, z_axis = _matrix_rotation_axes(local_matrix.to_quaternion().to_matrix())
        transform = _scaled_local_transform(root_obj, marker, scale)
        seed: dict[str, object] = {
            "role": role,
            "shape_type": str(marker.get("tbg_runtime_shape", export_contract.RUNTIME_SHAPE_BOX) or export_contract.RUNTIME_SHAPE_BOX),
            "name": str(marker.name),
            "source_name": str(marker.get("tbg_runtime_source_name", "") or marker.name),
            "bounds": _bounds_to_roblox(object_local_bounds(root_obj, marker), scale),
            "local_center": _vector_payload(transform.position),
            "size": _vector_payload(transform.size),
            "x_axis": _vector_payload(x_axis),
            "y_axis": _vector_payload(y_axis),
            "z_axis": _vector_payload(z_axis),
        }
        for attr_name, key_name in (
            ("tbg_runtime_floor", "floor"),
            ("tbg_runtime_direction", "direction"),
            ("tbg_runtime_step_index", "step_index"),
            ("tbg_runtime_top_z", "top_z"),
        ):
            value = marker.get(attr_name)
            if value is not None:
                seed[key_name] = _round_float(float(value)) if isinstance(value, float) else int(value)
        label = str(marker.get("tbg_runtime_label", "") or "")
        if label:
            seed["label"] = label
        seeds.append(seed)
    return seeds


def _build_traversal_collision_payload(root_obj, scale: float) -> dict[str, object]:
    return {
        "schema_version": export_contract.TRAVERSAL_COLLISION_PAYLOAD_VERSION,
        "seeds": _build_traversal_seeds(root_obj, scale),
    }


def _expand_door_opening_bounds(
    bounds: tuple[float, float, float, float, float, float],
    *,
    side: str,
    wall_thickness_local: float,
) -> tuple[float, float, float, float, float, float]:
    min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in bounds)
    frame_margin = max(0.06, wall_thickness_local * 0.28)
    opening_depth = max(max_y - min_y, 0.42, wall_thickness_local * 2.6)
    opening_width = max(max_x - min_x, wall_thickness_local * 0.9)
    side_key = str(side or "").lower()
    if side_key in {"front", "back"}:
        center_y = (min_y + max_y) * 0.5
        half_depth = opening_depth * 0.5
        min_x -= frame_margin
        max_x += frame_margin
        min_y = center_y - half_depth
        max_y = center_y + half_depth
    elif side_key in {"left", "right"}:
        center_x = (min_x + max_x) * 0.5
        half_depth = opening_depth * 0.5
        min_y -= frame_margin
        max_y += frame_margin
        min_x = center_x - half_depth
        max_x = center_x + half_depth
    else:
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        min_x = center_x - opening_width * 0.5 - frame_margin
        max_x = center_x + opening_width * 0.5 + frame_margin
        min_y = center_y - opening_depth * 0.5
        max_y = center_y + opening_depth * 0.5
    return (min_x, max_x, min_y, max_y, min_z, max_z)


def _door_leaf_void_seeds(root_obj, spec, scale: float) -> list[dict[str, object]]:
    door_leaves = [
        child
        for child in _mesh_children(root_obj)
        if bool(child.get("tbg_is_door_leaf"))
    ]
    seeds: list[dict[str, object]] = []
    wall_thickness_local = max(0.14, float(getattr(spec, "wall_thickness", 0.0)))
    for child in sorted(door_leaves, key=lambda item: item.name):
        side = str(child.get("tbg_facade_side", "") or "")
        seeds.append(
            {
                "void_kind": "ROOF_EXIT_DOOR" if bool(child.get("tbg_roof_exit_door")) else "DOOR_OPENING",
                "source_name": str(child.name),
                "side": side,
                "bounds": _bounds_to_roblox(
                    _expand_door_opening_bounds(
                        object_local_bounds(root_obj, child),
                        side=side,
                        wall_thickness_local=wall_thickness_local,
                    ),
                    scale,
                ),
            }
        )
    return seeds


def _roof_access_void_seed(spec, scale: float) -> dict[str, object] | None:
    spatial_plan = _spatial_plan(spec)
    opening_bounds = _spatial_plan_roof_opening_bounds(spatial_plan)
    if opening_bounds is None:
        return None
    roof_room = getattr(spatial_plan, "roof_room", None)
    return {
        "void_kind": "ROOF_ACCESS_OPENING",
        "source_name": "SpatialPlanRoofOpening",
        "terminal_profile": str(getattr(roof_room, "terminal_profile", "") or ""),
        "bounds": _bounds_to_roblox(opening_bounds, scale),
    }


def _build_void_seeds(
    *,
    root_obj,
    summary: dict,
    spec,
    scale: float,
) -> list[dict[str, object]]:
    seeds: list[dict[str, object]] = []
    seeds.extend(_window_opening_void_seeds(root_obj, scale))
    seeds.extend(_door_leaf_void_seeds(root_obj, spec, scale))
    roof_access_seed = _roof_access_void_seed(spec, scale)
    if roof_access_seed is not None:
        seeds.append(roof_access_seed)
    return seeds


def _roof_profile_points(*points: tuple[float, float], scale: float) -> list[dict[str, float]]:
    return [
        {
            "lateral_studs": _round_float(lateral * scale),
            "height_studs": _round_float(height * scale),
        }
        for lateral, height in points
    ]


def _build_roof_seeds(spec, scale: float) -> list[dict[str, object]]:
    roof_mode = str(_roof_mode(spec) or "").upper()
    roof_surface_z = float(_roof_surface_z(spec))
    spatial_plan, roof_rect, _full_rect = _top_mass_rect(spec)
    roof_opening_bounds = _spatial_plan_roof_opening_bounds(spatial_plan)
    roof_seed_base: dict[str, object] = {
        "roof_mode": roof_mode,
        "roof_surface_height_studs": _round_float(roof_surface_z * scale),
        "footprint_bounds": _bounds_to_roblox(
            (
                float(roof_rect[0]),
                float(roof_rect[1]),
                float(roof_rect[2]),
                float(roof_rect[3]),
                roof_surface_z,
                roof_surface_z + float(spec.slab_thickness),
            ),
            scale,
        ),
        "roof_opening_bounds": (
            _bounds_to_roblox(roof_opening_bounds, scale) if roof_opening_bounds is not None else None
        ),
    }

    if roof_mode in {"FLAT", "TERRACE"}:
        return [
            {
                **roof_seed_base,
                "seed_kind": "FLAT_SLAB",
                "slab_thickness_studs": _round_float(float(spec.slab_thickness) * scale),
                "parapet_height_studs": _round_float(float(spec.parapet_height) * scale),
            }
        ]

    if roof_mode == "GABLE":
        roof_rect = _sloped_roof_rect_with_terrace_clearance(roof_rect, spatial_plan=spatial_plan)
        roof_x0, roof_x1, roof_y0, roof_y1 = (float(value) for value in roof_rect)
        roof_width = max(0.01, roof_x1 - roof_x0)
        roof_depth = max(0.01, roof_y1 - roof_y0)
        hangar_frontage = _is_hangar_frontage(spec)
        axis = "Y" if hangar_frontage else _roof_longitudinal_axis(spec)
        roof_shell_t = min(0.28, max(0.14, float(spec.slab_thickness) * (1.2 if hangar_frontage else 1.15)))
        overhang = 0.02 if hangar_frontage else min(0.4, max(0.22, min(roof_width, roof_depth) * 0.035))
        slope_span = roof_depth if axis == "X" else roof_width
        ridge_rise = _gable_ridge_rise(spec, slope_span=slope_span, hangar_frontage=hangar_frontage)
        slope_run = slope_span / 2 + overhang
        profile = (
            (-slope_span / 2, roof_surface_z),
            (0.0, roof_surface_z + ridge_rise),
            (slope_span / 2, roof_surface_z),
        )
        return [
            {
                **roof_seed_base,
                "seed_kind": "GABLE_SHELL",
                "footprint_bounds": _bounds_to_roblox(
                    (roof_x0, roof_x1, roof_y0, roof_y1, roof_surface_z, roof_surface_z + ridge_rise + roof_shell_t),
                    scale,
                ),
                "ridge_runs_along_axis": "X" if axis == "X" else "Z",
                "gable_end_sides": ["left", "right"] if axis == "X" else ["front", "back"],
                "slope_span_studs": _round_float(slope_span * scale),
                "slope_run_studs": _round_float(slope_run * scale),
                "ridge_rise_studs": _round_float(ridge_rise * scale),
                "shell_thickness_studs": _round_float(roof_shell_t * scale),
                "roof_profile": _roof_profile_points(*profile, scale=scale),
            }
        ]

    if roof_mode == "SHED":
        roof_rect = _sloped_roof_rect_with_terrace_clearance(roof_rect, spatial_plan=spatial_plan)
        roof_x0, roof_x1, roof_y0, roof_y1 = (float(value) for value in roof_rect)
        roof_width = max(0.01, roof_x1 - roof_x0)
        roof_depth = max(0.01, roof_y1 - roof_y0)
        industrial_frontage = str(getattr(spec, "preset_id", "")).lower() in {"depot", "warehouse"}
        axis = _roof_longitudinal_axis(spec)
        roof_shell_t = min(
            0.28 if industrial_frontage else 0.24,
            max(0.14 if industrial_frontage else 0.12, float(spec.slab_thickness) * (1.24 if industrial_frontage else 1.15)),
        )
        slope_span = roof_depth if axis == "X" else roof_width
        rise = (
            max(1.16, min(float(spec.floor_height) * 0.98, slope_span * 0.34 + float(spec.parapet_height) * 0.46))
            if industrial_frontage
            else max(0.9, min(float(spec.floor_height) * 0.85, slope_span * 0.24 + float(spec.parapet_height) * 0.35))
        )
        profile = (
            (-slope_span / 2, roof_surface_z),
            (slope_span / 2, roof_surface_z + rise),
        )
        return [
            {
                **roof_seed_base,
                "seed_kind": "SHED_SHELL",
                "footprint_bounds": _bounds_to_roblox(
                    (roof_x0, roof_x1, roof_y0, roof_y1, roof_surface_z, roof_surface_z + rise + roof_shell_t),
                    scale,
                ),
                "slope_span_studs": _round_float(slope_span * scale),
                "rise_studs": _round_float(rise * scale),
                "shell_thickness_studs": _round_float(roof_shell_t * scale),
                "high_side": "back" if axis == "X" else "right",
                "low_side": "front" if axis == "X" else "left",
                "slope_profile": _roof_profile_points(*profile, scale=scale),
            }
        ]

    return [
        {
            **roof_seed_base,
            "seed_kind": "UNSUPPORTED_ROOF_MODE",
        }
    ]


def export_runtime_sidecar(root_obj, filepath: str | Path) -> dict[str, object]:
    if root_obj is None:
        raise RuntimeError("RBXMX sidecar export requires a Tactical Building root.")

    building_id = str(root_obj.get(constants.BUILDING_ID_KEY, "")).strip()
    if not building_id:
        raise RuntimeError("RBXMX sidecar export requires tbg_building_id on the root.")

    bpy.context.view_layer.update()
    scale = _uniform_world_scale(root_obj)
    render_meshes = runtime_render_meshes(root_obj)
    runtime_markers = _runtime_markers(root_obj)
    voxel_wall_payload = _voxel_wall_occupancy_payload(root_obj)
    voxel_wall_chunks = _voxel_wall_occupancy_chunks(voxel_wall_payload)
    traversal_collision_payload = _build_traversal_collision_payload(root_obj, scale)
    authored_cell_count, authored_group_count = _voxel_wall_occupancy_summary(voxel_wall_payload)
    light_markers = [
        marker for marker in runtime_markers if str(marker.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_LIGHT
    ]

    if not light_markers:
        raise RuntimeError("RBXMX sidecar export requires authored light markers.")
    if not authored_cell_count or not authored_group_count:
        raise RuntimeError("RBXMX sidecar export requires canonical authored voxel occupancy.")

    render_anchor_center, render_bounds_size = _render_bounds(root_obj, render_meshes, scale)
    render_anchor_to_author_root = tuple(-value for value in render_anchor_center)

    writer = _RbxmxWriter()
    sidecar_model = writer.add_model(export_contract.sidecar_model_name(building_id))
    contract_folder = writer.add_folder(sidecar_model, export_contract.CONTRACT_FOLDER_NAME)
    author_root = writer.add_part(
        sidecar_model,
        class_name="Part",
        name=export_contract.AUTHOR_ROOT_NAME,
        transform=_author_root_transform(),
        anchored=True,
        transparency=1.0,
        can_collide=False,
        can_query=False,
        can_touch=False,
        cast_shadow=False,
    )
    del author_root
    light_folder = writer.add_folder(sidecar_model, export_contract.LIGHTS_FOLDER_NAME)
    destruction_seed_folder = writer.add_folder(sidecar_model, export_contract.DESTRUCTION_SEED_FOLDER_NAME)

    writer.add_string_value(contract_folder, export_contract.CONTRACT_VALUE_BUILDING_ID, building_id)
    writer.add_string_value(
        contract_folder,
        export_contract.CONTRACT_VALUE_EXPORT_CONTRACT_VERSION,
        export_contract.EXPORT_CONTRACT_VERSION,
    )
    writer.add_string_value(
        contract_folder,
        export_contract.CONTRACT_VALUE_RENDER_ANCHOR_BASIS,
        export_contract.RENDER_ANCHOR_BASIS_BOUNDS_CENTER,
    )
    writer.add_vector3_value(
        contract_folder,
        export_contract.CONTRACT_VALUE_RENDER_ANCHOR_TO_AUTHOR_ROOT,
        render_anchor_to_author_root,
    )
    writer.add_number_value(contract_folder, export_contract.CONTRACT_VALUE_AUTHOR_ROOT_SCALE, scale)
    writer.add_vector3_value(contract_folder, export_contract.CONTRACT_VALUE_RENDER_BOUNDS_SIZE, render_bounds_size)
    writer.add_int_value(contract_folder, export_contract.CONTRACT_VALUE_RENDER_MESH_COUNT, len(render_meshes))
    writer.add_int_value(contract_folder, export_contract.CONTRACT_VALUE_LIGHT_COUNT, len(light_markers))
    writer.add_string_value(
        contract_folder,
        export_contract.CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON,
        _stable_json(traversal_collision_payload),
    )

    writer.add_string_value(
        destruction_seed_folder,
        export_contract.DESTRUCTION_VALUE_SEED_CONTRACT_VERSION,
        export_contract.VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION,
    )
    writer.add_string_value(
        destruction_seed_folder,
        export_contract.DESTRUCTION_VALUE_DESTRUCTION_MODE,
        export_contract.DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3,
    )
    writer.add_int_value(
        destruction_seed_folder,
        export_contract.DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT,
        len(voxel_wall_chunks),
    )
    for chunk_index, chunk_value in enumerate(voxel_wall_chunks, start=1):
        writer.add_string_value(
            destruction_seed_folder,
            export_contract.voxel_wall_occupancy_chunk_name(chunk_index),
            chunk_value,
        )

    light_role_folders = {
        role: writer.add_folder(light_folder, role)
        for role in export_contract.LIGHT_ROLE_FAMILIES
    }
    for marker in sorted(light_markers, key=lambda item: item.name):
        role = str(marker.get("tbg_runtime_role", ""))
        preset = _LIGHT_PRESETS.get(role)
        if preset is None:
            raise RuntimeError(f"RBXMX sidecar export encountered unsupported light role '{role}' on {marker.name}.")
        anchor_transform, range_value = _light_anchor_transform(root_obj, marker, scale, preset)
        anchor = writer.add_part(
            light_role_folders[role],
            class_name="Part",
            name=_runtime_name(marker.name),
            transform=anchor_transform,
            anchored=True,
            transparency=1.0,
            can_collide=False,
            can_query=False,
            can_touch=False,
            cast_shadow=False,
        )
        writer.add_point_light(
            anchor,
            color=preset["color"],
            brightness=float(preset["brightness"]),
            range_value=range_value,
        )

    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer.write(output_path)
    return {
        "building_id": building_id,
        "filepath": str(output_path),
        "render_mesh_count": len(render_meshes),
        "light_count": len(light_markers),
        "render_bounds_size": render_bounds_size,
        "render_anchor_to_author_root": render_anchor_to_author_root,
        "destruction_runtime_mode": export_contract.RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST,
        "destruction_seed_contract_version": export_contract.VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION,
        "destruction_mode": export_contract.DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3,
        "authored_cell_count": authored_cell_count,
        "authored_group_count": authored_group_count,
        "occupancy_chunk_count": len(voxel_wall_chunks),
        "traversal_collision_count": len(traversal_collision_payload["seeds"]),
        "plugin_cutover_pending": True,
    }
