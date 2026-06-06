from __future__ import annotations

import bpy

from .. import constants, metadata, naming
from ..generator.building_output import clear_voxel_preview_cache, iter_voxel_wall_marker_objects


_GENERATED_COLLECTION_PREFIXES = (
    constants.ROOT_COLLECTION_PREFIX,
    constants.EXPORT_COLLECTION_PREFIX,
    constants.BLOCK_COLLECTION_PREFIX,
)
_MANAGED_BUILDING_LANES = frozenset(("structure", "core", "doors", "roof", "helpers"))
_FACADE_SCOPE_BUCKETS = frozenset(
    (
        "Section_Walls_Exterior",
        "Section_Walls_ExteriorSurfaceTile",
        "Section_Walls_Interior",
        "Section_Walls_Trim",
        "Section_Doors_Trim",
    )
)
_STRUCTURE_BASE_SCOPE_BUCKETS = frozenset(("Section_Floors",))
_ROOF_SCOPE_BUCKETS = frozenset(("Section_Walls_Roof",))
_DOOR_SCOPE_BUCKETS = frozenset(("Section_Doors_Leaf", "Section_Doors_Prop"))
_VOXEL_WALL_MARKER_PAYLOAD_KEY = "tbg_voxel_wall_marker_payload_json"
_VOXEL_WALL_MARKER_ESTIMATED_PART_COUNT_KEY = "tbg_voxel_wall_estimated_part_count"


def _normalize_scope_names(scope_names) -> set[str]:
    if scope_names is None:
        return set()
    return {str(name).strip().lower() for name in scope_names if str(name).strip()}


def _bucket_name(obj) -> str:
    return str(obj.get("tbg_section_bucket", "") or "").strip()


def _infer_preview_scope(obj, *, lane_name: str | None = None) -> str:
    explicit_scope = str(obj.get("tbg_preview_scope", "") or "").strip().lower()
    if explicit_scope:
        return explicit_scope
    bucket = _bucket_name(obj)
    inferred = ""
    if bucket.startswith("Section_Openings_") or bucket in _FACADE_SCOPE_BUCKETS:
        inferred = "facade"
    elif bucket.startswith("Section_Stairs_"):
        inferred = "core"
    elif bucket in _STRUCTURE_BASE_SCOPE_BUCKETS:
        inferred = "structure_base"
    elif bucket in _ROOF_SCOPE_BUCKETS:
        inferred = "roof"
    elif bucket in _DOOR_SCOPE_BUCKETS:
        inferred = "doors"
    elif lane_name in {"structure", "core", "roof", "doors"} and not bucket:
        inferred = str(lane_name)
    if inferred:
        obj["tbg_preview_scope"] = inferred
    return inferred


def _root_object_lane_membership(obj) -> set[str]:
    bucket = _bucket_name(obj)
    if not bucket:
        return set()
    if bucket.startswith("Section_Stairs_"):
        return {"core"}
    if bucket.startswith("Section_Openings_"):
        return {"structure"}
    if bucket in _FACADE_SCOPE_BUCKETS or bucket in _STRUCTURE_BASE_SCOPE_BUCKETS:
        return {"structure"}
    if bucket in _ROOF_SCOPE_BUCKETS:
        return {"roof"}
    if bucket in _DOOR_SCOPE_BUCKETS:
        return {"doors"}
    if bucket in {"Section_Services_Prop", "Section_Services_Helper"}:
        return {"structure", "roof"}
    return set()


def clear_collection_objects(collection, *, keep_objects: set[str] | None = None):
    keep_objects = keep_objects or set()
    for obj in list(collection.objects):
        if obj.name in keep_objects:
            continue
        bpy.data.objects.remove(obj, do_unlink=True)


def _remove_collection(collection):
    clear_collection_objects(collection)
    bpy.data.collections.remove(collection)


def clear_generated_building(hierarchy, root_object=None):
    keep = {root_object.name} if root_object is not None else set()
    clear_collection_objects(hierarchy["root"], keep_objects=keep)
    for collection in hierarchy["managed_children"]:
        clear_collection_objects(collection)
    for collection in hierarchy["stale_collections"]:
        if bpy.data.collections.get(collection.name) is None:
            continue
        _remove_collection(collection)
    export_collection = hierarchy.get("export")
    if export_collection is not None:
        clear_collection_objects(export_collection)


def clear_generated_building_lanes(
    hierarchy,
    lane_names,
    *,
    scope_names=None,
    clear_export_collection: bool = False,
):
    lanes = {str(name).strip().lower() for name in (lane_names or ()) if str(name).strip()}
    if not lanes:
        return
    scopes = _normalize_scope_names(scope_names)
    unknown = lanes - _MANAGED_BUILDING_LANES
    if unknown:
        raise ValueError(f"Unknown building lanes for cleanup: {', '.join(sorted(unknown))}")

    root_collection = hierarchy.get("root")
    if root_collection is not None:
        for obj in list(root_collection.objects):
            if obj.type != "MESH":
                continue
            if not obj.get("tbg_section_bucket"):
                continue
            lane_membership = _root_object_lane_membership(obj)
            if not lane_membership.intersection(lanes):
                continue
            if scopes:
                object_scope = _infer_preview_scope(obj)
                if object_scope not in scopes:
                    continue
            bpy.data.objects.remove(obj, do_unlink=True)

    for lane_name in sorted(lanes):
        collection = hierarchy.get(lane_name)
        if collection is None:
            continue
        if lane_name == "helpers":
            clear_collection_objects(collection)
            continue
        if not scopes:
            clear_collection_objects(collection)
            continue
        for obj in list(collection.objects):
            object_scope = _infer_preview_scope(obj, lane_name=lane_name)
            if object_scope not in scopes:
                continue
            bpy.data.objects.remove(obj, do_unlink=True)

    for collection in hierarchy["stale_collections"]:
        if bpy.data.collections.get(collection.name) is None:
            continue
        _remove_collection(collection)

    if clear_export_collection:
        export_collection = hierarchy.get("export")
        if export_collection is not None:
            clear_collection_objects(export_collection)


def clear_transient_wall_helpers(root_obj) -> dict[str, int]:
    if root_obj is None:
        return {"preview_cache": 0, "wall_markers": 0, "scrubbed_props": 0}

    cleared_preview = int(clear_voxel_preview_cache(root_obj))
    cleared_markers = 0
    scrubbed_props = 0
    stale_meshes: list[bpy.types.Mesh] = []

    for helper_obj in tuple(iter_voxel_wall_marker_objects(root_obj)):
        if helper_obj is None or helper_obj.name not in bpy.data.objects:
            continue
        mesh_data = helper_obj.data if helper_obj.type == "MESH" else None
        bpy.data.objects.remove(helper_obj, do_unlink=True)
        if isinstance(mesh_data, bpy.types.Mesh):
            stale_meshes.append(mesh_data)
        cleared_markers += 1

    for child in tuple(getattr(root_obj, "children_recursive", ())):
        if child is None or child.name not in bpy.data.objects:
            continue
        if _VOXEL_WALL_MARKER_PAYLOAD_KEY in child:
            del child[_VOXEL_WALL_MARKER_PAYLOAD_KEY]
            scrubbed_props += 1
        if _VOXEL_WALL_MARKER_ESTIMATED_PART_COUNT_KEY in child:
            del child[_VOXEL_WALL_MARKER_ESTIMATED_PART_COUNT_KEY]
            scrubbed_props += 1

    for mesh_data in stale_meshes:
        if mesh_data.name in bpy.data.meshes and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)

    return {
        "preview_cache": int(cleared_preview),
        "wall_markers": int(cleared_markers),
        "scrubbed_props": int(scrubbed_props),
    }


def purge_legacy_wall_authority(root_obj) -> dict[str, int]:
    if root_obj is None:
        return {"preview_cache": 0, "wall_markers": 0, "scrubbed_props": 0, "cleared_payload": 0, "invalidated_exact_spec_entries": 0}

    cleared = clear_transient_wall_helpers(root_obj)
    had_payload = int(bool(metadata.read_voxel_wall_occupancy_payload(root_obj, strict=False)))
    metadata.clear_voxel_wall_occupancy_payload(root_obj)

    from ..generator import building as building_runtime

    invalidated_entries = int(building_runtime.invalidate_exact_spec_reuse_entries())
    return {
        **cleared,
        "cleared_payload": int(had_payload),
        "invalidated_exact_spec_entries": int(invalidated_entries),
    }


def prune_empty_generated_collections():
    removed_any = False
    while True:
        removed_in_pass = False
        for collection in list(bpy.data.collections):
            if not collection.name.startswith(_GENERATED_COLLECTION_PREFIXES):
                continue
            if collection.objects or collection.children:
                continue
            bpy.data.collections.remove(collection)
            removed_in_pass = True
            removed_any = True
        if not removed_in_pass:
            break
    return removed_any


def _remove_collection_tree(collection, *, removed_names: set[str]):
    if collection is None:
        return
    collection_name = str(getattr(collection, "name", "") or "")
    if not collection_name or collection_name in removed_names:
        return
    existing = bpy.data.collections.get(collection_name)
    if existing is None:
        removed_names.add(collection_name)
        return
    for child in tuple(existing.children):
        _remove_collection_tree(child, removed_names=removed_names)
    clear_collection_objects(existing)
    if bpy.data.collections.get(collection_name) is not None:
        bpy.data.collections.remove(existing)
    removed_names.add(collection_name)


def delete_generated_building_hierarchy(root_object):
    if root_object is None:
        raise ValueError("Delete requires a valid building root object.")

    building_id = str(root_object.get(constants.BUILDING_ID_KEY, "") or "").strip()
    root_collection_name = str(root_object.get(constants.COLLECTION_NAME_KEY, "") or "").strip()
    export_collection_name = str(root_object.get(constants.EXPORT_COLLECTION_NAME_KEY, "") or "").strip()
    root_collection = bpy.data.collections.get(root_collection_name) if root_collection_name else None
    export_collection = bpy.data.collections.get(export_collection_name) if export_collection_name else None

    if root_collection is None:
        for collection in tuple(getattr(root_object, "users_collection", ())):
            if collection.name.startswith(constants.ROOT_COLLECTION_PREFIX):
                root_collection = collection
                break

    objects_to_remove = []
    if bpy.data.objects.get(root_object.name) is not None:
        objects_to_remove.append(root_object)
    objects_to_remove.extend(
        child
        for child in tuple(getattr(root_object, "children_recursive", ()))
        if bpy.data.objects.get(child.name) is not None
    )
    seen_names: set[str] = set()
    removed_objects = 0
    for obj in objects_to_remove:
        obj_name = str(getattr(obj, "name", "") or "")
        if not obj_name or obj_name in seen_names:
            continue
        seen_names.add(obj_name)
        existing = bpy.data.objects.get(obj_name)
        if existing is None:
            continue
        bpy.data.objects.remove(existing, do_unlink=True)
        removed_objects += 1

    removed_collections: set[str] = set()
    if root_collection is not None:
        _remove_collection_tree(root_collection, removed_names=removed_collections)

    if export_collection is None and building_id:
        export_collection = bpy.data.collections.get(naming.export_collection_name(building_id))
    if export_collection is not None:
        _remove_collection_tree(export_collection, removed_names=removed_collections)

    if building_id:
        root_name = naming.root_collection_name(building_id)
        export_name = naming.export_collection_name(building_id)
        managed_prefix = f"{root_name}_"
        for collection in list(bpy.data.collections):
            name = str(collection.name)
            if name == root_name or name == export_name or name.startswith(managed_prefix):
                _remove_collection_tree(collection, removed_names=removed_collections)

    prune_empty_generated_collections()
    return {
        "removed_objects": removed_objects,
        "removed_collections": len(removed_collections),
    }
