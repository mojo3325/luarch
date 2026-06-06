from __future__ import annotations

import bpy

from .. import constants, naming


def _has_child_link(parent_collection, collection) -> bool:
    return parent_collection.children.get(collection.name) is not None


def ensure_collection_link(parent_collection, collection):
    if not _has_child_link(parent_collection, collection):
        parent_collection.children.link(collection)
    return collection


def ensure_scene_collection(scene, collection):
    if not _has_child_link(scene.collection, collection):
        scene.collection.children.link(collection)
    return collection


def ensure_child_collection(parent_collection, name: str):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    return ensure_collection_link(parent_collection, collection)


def create_block_collection(scene, block_id: str):
    block = bpy.data.collections.get(naming.block_collection_name(block_id))
    if block is None:
        block = bpy.data.collections.new(naming.block_collection_name(block_id))
    ensure_scene_collection(scene, block)
    block["tbg_block_id"] = block_id
    return block


def resolve_root_collection(existing_root, building_id: str):
    if existing_root is not None:
        collection_name = str(existing_root.get(constants.COLLECTION_NAME_KEY, "")).strip()
        if collection_name:
            collection = bpy.data.collections.get(collection_name)
            if collection is not None:
                return collection
    return bpy.data.collections.get(naming.root_collection_name(building_id))


def _dedupe_collections(collections):
    unique = []
    seen_names = set()
    for collection in collections:
        if collection is None or collection.name in seen_names:
            continue
        seen_names.add(collection.name)
        unique.append(collection)
    return tuple(unique)


def create_building_hierarchy(
    scene,
    building_id: str,
    export_profile: str,
    *,
    parent_collection=None,
    existing_root=None,
):
    root_name = naming.root_collection_name(building_id)
    root = resolve_root_collection(existing_root, building_id)
    root_was_new = root is None
    if root is None:
        root = bpy.data.collections.new(root_name)

    if parent_collection is not None:
        ensure_collection_link(parent_collection, root)
    elif root_was_new:
        ensure_scene_collection(scene, root)

    structure = ensure_child_collection(root, naming.child_collection_name(building_id, "Structure"))
    core = ensure_child_collection(root, naming.child_collection_name(building_id, "Core"))
    doors = ensure_child_collection(root, naming.child_collection_name(building_id, "Doors"))
    roof = ensure_child_collection(root, naming.child_collection_name(building_id, "Roof"))
    helpers = ensure_child_collection(root, naming.child_collection_name(building_id, "Helpers"))
    managed_children = (structure, core, doors, roof, helpers)
    managed_child_names = {collection.name for collection in managed_children}
    managed_prefix = f"{root_name}_"
    stale_collections = [
        child
        for child in tuple(root.children)
        if child.name.startswith(managed_prefix) and child.name not in managed_child_names
    ]

    export_collection = None
    existing_export = bpy.data.collections.get(naming.export_collection_name(building_id))
    if export_profile == constants.EDITABLE_WITH_EXPORT:
        export_collection = existing_export
        export_was_new = export_collection is None
        if export_collection is None:
            export_collection = bpy.data.collections.new(naming.export_collection_name(building_id))
        if parent_collection is not None:
            ensure_collection_link(parent_collection, export_collection)
        elif export_was_new:
            ensure_scene_collection(scene, export_collection)
    elif existing_export is not None:
        stale_collections.append(existing_export)

    return {
        "root": root,
        "structure": structure,
        "core": core,
        "doors": doors,
        "roof": roof,
        "helpers": helpers,
        "export": export_collection,
        "managed_children": managed_children,
        "stale_collections": _dedupe_collections(stale_collections),
    }
