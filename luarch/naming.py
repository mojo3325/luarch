from __future__ import annotations

import bpy

from . import constants


def _next_numeric_id(names: list[str], prefix: str) -> str:
    numbers = []
    for name in names:
        if not name.startswith(prefix + "_"):
            continue
        suffix = name[len(prefix) + 1 :]
        if suffix.isdigit():
            numbers.append(int(suffix))
    next_num = max(numbers, default=0) + 1
    return f"{next_num:03d}"


def next_building_id(scene) -> str:
    del scene
    names = [collection.name for collection in bpy.data.collections]
    return _next_numeric_id(names, constants.ROOT_COLLECTION_PREFIX)


def next_block_id(scene) -> str:
    del scene
    names = [collection.name for collection in bpy.data.collections]
    return _next_numeric_id(names, constants.BLOCK_COLLECTION_PREFIX)


def root_collection_name(building_id: str) -> str:
    return f"{constants.ROOT_COLLECTION_PREFIX}_{building_id}"


def export_collection_name(building_id: str) -> str:
    return f"{constants.EXPORT_COLLECTION_PREFIX}_{building_id}"


def block_collection_name(block_id: str) -> str:
    return f"{constants.BLOCK_COLLECTION_PREFIX}_{block_id}"


def root_object_name(building_id: str) -> str:
    return f"{root_collection_name(building_id)}_ROOT"


def child_collection_name(building_id: str, suffix: str) -> str:
    return f"{root_collection_name(building_id)}_{suffix}"
