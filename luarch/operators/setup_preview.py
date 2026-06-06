from __future__ import annotations

import bpy
from mathutils import Vector

from .. import export_contract, metadata
from ..generator.building_output import (
    clear_voxel_preview_cache,
    iter_voxel_preview_cache_objects,
)
from ..generator.building_support import composite_part_root_local_bounds
from ..services.validation import validate_root


PREVIEW_COLLECTION_NAME = "TBG_Preview"


def _ensure_preview_collection(scene):
    collection = bpy.data.collections.get(PREVIEW_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(PREVIEW_COLLECTION_NAME)
    if collection.name not in [child.name for child in scene.collection.children]:
        scene.collection.children.link(collection)
    return collection


def _ensure_light(collection, name: str, light_type: str):
    light_data = bpy.data.lights.get(name)
    if light_data is None:
        light_data = bpy.data.lights.new(name=name, type=light_type)
    else:
        light_data.type = light_type

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, light_data)
        collection.objects.link(obj)
    elif obj.name not in [item.name for item in collection.objects]:
        collection.objects.link(obj)
    obj.data = light_data
    obj.hide_select = True
    return obj


def _look_at(obj, target: Vector):
    direction = (target - obj.location)
    if direction.length <= 1e-5:
        return
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _ensure_world(scene):
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("TBG_PreviewWorld")
        scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    background = nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.84, 0.85, 0.87, 1.0)
        background.inputs["Strength"].default_value = 0.9
    return world


def _apply_material_preview(context):
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            shading = space.shading
            shading.type = "MATERIAL"
            for attr in ("use_scene_lights", "use_scene_world", "use_scene_lights_render", "use_scene_world_render"):
                if hasattr(shading, attr):
                    setattr(shading, attr, False)
            if hasattr(shading, "studio_light"):
                shading.studio_light = "forest.exr"
            if hasattr(shading, "studiolight_background_alpha"):
                shading.studiolight_background_alpha = 0.0
            if hasattr(shading, "studiolight_background_blur"):
                shading.studiolight_background_blur = 0.0


class TBG_OT_setup_preview(bpy.types.Operator):
    bl_idname = "tbg.setup_preview"
    bl_label = "Setup Preview"
    bl_description = "Configure material preview lighting for tactical building inspection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        target_root = metadata.resolve_root_from_object(context.active_object)
        target = Vector(target_root.location if target_root is not None else scene.cursor.location)

        collection = _ensure_preview_collection(scene)
        _ensure_world(scene)
        _apply_material_preview(context)

        sun = _ensure_light(collection, "TBG_PreviewSun", "SUN")
        sun.location = target + Vector((22.0, -28.0, 40.0))
        sun.data.energy = 3.2
        sun.data.angle = 0.18
        _look_at(sun, target + Vector((0.0, 0.0, 6.0)))

        fill = _ensure_light(collection, "TBG_PreviewFill", "AREA")
        fill.location = target + Vector((-20.0, -12.0, 14.0))
        fill.data.energy = 2500.0
        fill.data.shape = "RECTANGLE"
        fill.data.size = 14.0
        fill.data.size_y = 10.0
        _look_at(fill, target + Vector((0.0, 0.0, 5.0)))

        rim = _ensure_light(collection, "TBG_PreviewRim", "AREA")
        rim.location = target + Vector((18.0, 18.0, 16.0))
        rim.data.energy = 1400.0
        rim.data.shape = "RECTANGLE"
        rim.data.size = 12.0
        rim.data.size_y = 8.0
        _look_at(rim, target + Vector((0.0, 0.0, 5.0)))

        self.report({"INFO"}, "Configured material preview lighting.")
        return {"FINISHED"}


def _read_strict_wall_cell_payload(root_obj):
    if bool(root_obj.get("tbg_edit_mode_dirty")):
        raise metadata.MetadataContractError(
            "Wall cell verifier is read-only; finalize or regenerate the dirty root first."
        )
    payload = metadata.read_voxel_wall_occupancy_payload(root_obj, strict=True)
    if payload.get("payload_kind") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
        raise metadata.MetadataContractError("Stored wall payload is not AUTHORED_WALL_CELLS.")
    if payload.get("payload_version") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
        raise metadata.MetadataContractError(
            f"Stored wall payload is not version {export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION}."
        )
    cells = payload.get("cells")
    authored_cell_count = payload.get("authored_cell_count")
    if (
        not isinstance(cells, list)
        or not isinstance(authored_cell_count, int)
        or isinstance(authored_cell_count, bool)
        or authored_cell_count <= 0
        or authored_cell_count != len(cells)
    ):
        raise metadata.MetadataContractError("Stored wall payload has invalid authored cell count.")
    return payload


def _visible_wall_cell_counts(root_obj) -> tuple[int, int, int]:
    visible_object_count = 0
    visible_composite_cell_count = 0
    visible_scalar_cell_count = 0
    for child in tuple(getattr(root_obj, "children_recursive", ())):
        if child is None or child.name not in bpy.data.objects or child.type != "MESH":
            continue
        if str(child.get("tbg_section_bucket", "") or "") not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            continue
        if str(child.get("tbg_wall_emit_owner", "") or "") != "occupancy_v3":
            continue
        if str(child.get("tbg_wall_payload_kind", "") or "") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
            continue
        if str(child.get("tbg_wall_payload_version", "") or "") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
            continue
        visible_object_count += 1
        visible_composite_cell_count += len(composite_part_root_local_bounds(root_obj, child))
        try:
            visible_scalar_cell_count += int(child.get("tbg_wall_cell_count", 0) or 0)
        except (TypeError, ValueError):
            pass
    return visible_object_count, visible_composite_cell_count, visible_scalar_cell_count


class TBG_OT_preview_voxels(bpy.types.Operator):
    bl_idname = "tbg.preview_voxels"
    bl_label = "Verify Wall Cells"
    bl_description = "Verify stored wall cells against existing visible V3 wall meshes and clear stale preview helpers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return metadata.resolve_root_from_object(context.active_object) is not None

    def execute(self, context):
        root_obj = metadata.resolve_root_from_object(context.active_object)
        if root_obj is None:
            self.report({"ERROR"}, "Select a generated building root first.")
            return {"CANCELLED"}

        stale_helper_count = len(iter_voxel_preview_cache_objects(root_obj))
        cleared_helper_count = clear_voxel_preview_cache(root_obj)
        try:
            occupancy_payload = _read_strict_wall_cell_payload(root_obj)
        except Exception as exc:
            self.report(
                {"ERROR"},
                f"Wall cell verification failed after clearing {cleared_helper_count} stale preview helper(s): {exc}",
            )
            return {"CANCELLED"}

        payload_cell_count = int(occupancy_payload.get("authored_cell_count", 0))
        visible_object_count, visible_composite_cell_count, visible_scalar_cell_count = _visible_wall_cell_counts(root_obj)
        counts_match = (
            visible_composite_cell_count == payload_cell_count
            and visible_scalar_cell_count == payload_cell_count
            and visible_object_count > 0
        )
        if not counts_match:
            self.report(
                {"ERROR"},
                f"Wall cell verification drift: "
                f"payload={payload_cell_count}, visible_composite={visible_composite_cell_count}, "
                f"visible_scalar={visible_scalar_cell_count}, visible_objects={visible_object_count}, "
                f"stale_helpers_cleared={cleared_helper_count}/{stale_helper_count}.",
            )
            return {"CANCELLED"}

        validation_issues = validate_root(root_obj)
        if validation_issues:
            self.report(
                {"ERROR"},
                f"Wall cell verification failed validation after count match: "
                f"{len(validation_issues)} issue(s); first: {validation_issues[0]}",
            )
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Wall cell verification matched and validation passed: "
            f"payload={payload_cell_count}, visible_composite={visible_composite_cell_count}, "
            f"visible_scalar={visible_scalar_cell_count}, visible_objects={visible_object_count}, "
            f"stale_helpers_cleared={cleared_helper_count}/{stale_helper_count}.",
        )
        return {"FINISHED"}
