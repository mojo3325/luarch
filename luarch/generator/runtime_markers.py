from __future__ import annotations

import bpy
from mathutils import Euler, Vector

from .. import export_contract
from .building_support import _assign_material, _create_box, _mark_generated, _name, _parent_to, _ramp_mesh


RUNTIME_KIND_COLLISION = export_contract.RUNTIME_KIND_COLLISION
RUNTIME_SHAPE_BOX = export_contract.RUNTIME_SHAPE_BOX
RUNTIME_SHAPE_WEDGE = export_contract.RUNTIME_SHAPE_WEDGE
ROLE_PROP_BOX = export_contract.ROLE_PROP_BOX


class RuntimeMarkerEmitter:
    def __init__(self, prefix: str, collection, parent, material):
        self.prefix = prefix
        self.collection = collection
        self.parent = parent
        self.material = material
        self._box_index = 0
        self._wedge_index = 0

    def _next_name(self, primitive: str, role: str) -> str:
        if primitive == "PrimWedge":
            self._wedge_index += 1
            index = self._wedge_index
        else:
            self._box_index += 1
            index = self._box_index
        return _name(self.prefix, f"Meta_Collision_{primitive}__{role}__{index:04d}")

    def emit_box(
        self,
        *,
        role: str,
        size: tuple[float, float, float],
        location: tuple[float, float, float],
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        source_name: str = "",
        collidable: bool = True,
        metadata_values: dict | None = None,
    ):
        obj = _create_runtime_marker_box(
            self._next_name("PrimBox", role),
            size,
            location,
            self.collection,
            self.parent,
            self.material,
            kind=RUNTIME_KIND_COLLISION,
            role=role,
            rotation=rotation,
            source_name=source_name,
        )
        return _mark_generated(obj, tbg_runtime_collidable=bool(collidable), **(metadata_values or {}))

    def emit_wedge(
        self,
        *,
        role: str,
        width: float,
        depth: float,
        height: float,
        location: tuple[float, float, float],
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        source_name: str = "",
        metadata_values: dict | None = None,
    ):
        obj = _create_runtime_marker_wedge(
            self._next_name("PrimWedge", role),
            width,
            depth,
            height,
            location,
            self.collection,
            self.parent,
            self.material,
            rotation=rotation,
            role=role,
            source_name=source_name,
        )
        return _mark_generated(obj, **(metadata_values or {}))

    def emit_composite_boxes(
        self,
        *,
        parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
        base_location: tuple[float, float, float],
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        role: str | None = None,
        roles: list[str] | tuple[str, ...] | None = None,
        source_name: str = "",
        collidable: bool = True,
        metadata_values: dict | None = None,
        per_part_metadata: list[dict] | None = None,
    ):
        rot_matrix = Euler(rotation, "XYZ").to_matrix()
        base = Vector(base_location)
        emitted = []
        for index, (size, local_center) in enumerate(parts):
            part_role = role if roles is None else roles[index]
            part_metadata = dict(metadata_values or {})
            if per_part_metadata is not None and index < len(per_part_metadata):
                part_metadata.update(per_part_metadata[index])
            center = base + rot_matrix @ Vector(local_center)
            emitted.append(
                self.emit_box(
                    role=part_role,
                    size=size,
                    location=(float(center.x), float(center.y), float(center.z)),
                    rotation=rotation,
                    source_name=source_name,
                    collidable=collidable,
                    metadata_values=part_metadata,
                )
            )
        return emitted


def _emit_object_proxy_box(
    runtime_emitter: RuntimeMarkerEmitter | None,
    obj,
    *,
    role: str = ROLE_PROP_BOX,
    source_name: str = "",
    metadata_values: dict | None = None,
    collidable: bool = True,
):
    if runtime_emitter is None or obj is None:
        return None
    bbox_corners = [Vector(corner) for corner in obj.bound_box]
    if not bbox_corners:
        return None
    min_corner = Vector(
        (
            min(corner.x for corner in bbox_corners),
            min(corner.y for corner in bbox_corners),
            min(corner.z for corner in bbox_corners),
        )
    )
    max_corner = Vector(
        (
            max(corner.x for corner in bbox_corners),
            max(corner.y for corner in bbox_corners),
            max(corner.z for corner in bbox_corners),
        )
    )
    local_center = (min_corner + max_corner) / 2
    local_size = max_corner - min_corner
    local_scale = Vector((abs(float(obj.scale.x)), abs(float(obj.scale.y)), abs(float(obj.scale.z))))
    scaled_center = Vector(
        (
            local_center.x * local_scale.x,
            local_center.y * local_scale.y,
            local_center.z * local_scale.z,
        )
    )
    center = Vector(obj.location) + Euler(tuple(float(value) for value in obj.rotation_euler), "XYZ").to_matrix() @ scaled_center
    size = tuple(
        max(0.05, float(local_size[index] * local_scale[index]))
        for index in range(3)
    )
    location = tuple(float(value) for value in center)
    rotation = tuple(float(value) for value in obj.rotation_euler)
    return runtime_emitter.emit_box(
        role=role,
        size=size,
        location=location,
        rotation=rotation,
        source_name=source_name or obj.name,
        collidable=collidable,
        metadata_values=metadata_values,
    )


def _mark_runtime_marker(
    obj,
    *,
    kind: str,
    role: str,
    shape: str = "BOX",
    source_name: str = "",
):
    obj = _mark_generated(
        obj,
        tbg_runtime_marker=True,
        tbg_runtime_kind=kind,
        tbg_runtime_role=role,
        tbg_runtime_shape=shape,
        tbg_runtime_source_name=source_name,
    )
    if obj is None:
        return None
    obj.display_type = "WIRE"
    obj.hide_viewport = True
    obj.hide_render = True
    if hasattr(obj, "show_in_front"):
        obj.show_in_front = True
    return obj


def _create_runtime_marker_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    *,
    kind: str,
    role: str,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    source_name: str = "",
):
    obj = _create_box(name, size, location, collection, parent, material, rotation=rotation)
    return _mark_runtime_marker(obj, kind=kind, role=role, shape=RUNTIME_SHAPE_BOX, source_name=source_name)


def _create_runtime_marker_wedge(
    name: str,
    width: float,
    depth: float,
    height: float,
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    role: str,
    source_name: str = "",
):
    if min(width, depth, height) <= 1e-4:
        return None
    mesh = _ramp_mesh(name, width, depth, height)
    if any(abs(value) > 1e-6 for value in rotation):
        rot_matrix = Euler(rotation, "XYZ").to_matrix().to_4x4()
        mesh.transform(rot_matrix)
        mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(location)
    _assign_material(obj, material)
    return _mark_runtime_marker(obj, kind=RUNTIME_KIND_COLLISION, role=role, shape=RUNTIME_SHAPE_WEDGE, source_name=source_name)
