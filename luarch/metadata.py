from __future__ import annotations

import json

from . import constants, export_contract


class MetadataContractError(ValueError):
    pass


def _stable_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _string_field(root_obj, key: str) -> str:
    return str(root_obj.get(key, "")).strip()


def _read_json_dict(root_obj, key: str, *, label: str, strict: bool) -> dict:
    payload = root_obj.get(key, "")
    if not payload:
        if strict:
            raise MetadataContractError(f"{label} is missing from the selected root.")
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        if strict:
            raise MetadataContractError(f"{label} is not valid JSON: {exc.msg}.") from exc
        return {}
    if isinstance(data, dict):
        return data
    if strict:
        raise MetadataContractError(f"{label} must decode to a JSON object.")
    return {}


def version_metadata_fields() -> dict[str, str]:
    return {
        constants.LEGACY_VERSION_KEY: constants.ADDON_VERSION,
        constants.ADDON_VERSION_KEY: constants.ADDON_VERSION,
        constants.SUMMARY_SCHEMA_VERSION_KEY: constants.SUMMARY_SCHEMA_VERSION,
        constants.EXPORT_CONTRACT_VERSION_KEY: export_contract.EXPORT_CONTRACT_VERSION,
    }


def wall_cuboid_metadata_fields() -> dict[str, str]:
    return {
        export_contract.AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND_KEY: export_contract.AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND,
        export_contract.AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION_KEY: export_contract.AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION,
        export_contract.AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION_KEY: (
            export_contract.AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION
        ),
    }


def wall_cell_metadata_fields() -> dict[str, str]:
    return {
        export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND_KEY: export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND,
        export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION_KEY: export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION,
        export_contract.AUTHORED_WALL_CELLS_EXPORT_CONTRACT_VERSION_KEY: (
            export_contract.AUTHORED_WALL_CELLS_EXPORT_CONTRACT_VERSION
        ),
    }


def legacy_v1_wall_metadata_keys() -> tuple[str, ...]:
    return (
        export_contract.LEGACY_V1_VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION_KEY,
        export_contract.LEGACY_V1_VOXEL_WALL_OCCUPANCY_DESTRUCTION_MODE_KEY,
    )


def voxel_wall_occupancy_metadata_fields() -> dict[str, str]:
    # Compatibility seam: downstream call sites still use the old helper name, but the live
    # root boundary is now the V3 authored-cell metadata set.
    return wall_cell_metadata_fields()


def clear_legacy_v1_wall_metadata(root_obj) -> None:
    for key in legacy_v1_wall_metadata_keys():
        root_obj.pop(key, None)


def write_root_metadata(root_obj, root_collection, spec_dict: dict, building_id: str):
    spec_json = _stable_json(spec_dict)
    root_obj[constants.ROOT_OBJECT_KEY] = True
    root_obj[constants.BUILDING_ID_KEY] = building_id
    root_obj[constants.COLLECTION_NAME_KEY] = root_collection.name
    root_obj[constants.SPEC_JSON_KEY] = spec_json
    root_obj[constants.PRESET_KEY] = spec_dict.get("preset_id", "")
    root_obj[constants.SEED_KEY] = int(spec_dict.get("seed", 0))
    root_obj[constants.UNIT_MODE_KEY] = spec_dict.get("unit_mode", constants.UNIT_MODE_METERS)
    root_obj[constants.EXPORT_PROFILE_KEY] = spec_dict.get("export_profile", constants.EDITABLE_ONLY)
    for key, value in version_metadata_fields().items():
        root_obj[key] = value

    root_collection[constants.BUILDING_ID_KEY] = building_id
    root_collection[constants.SPEC_JSON_KEY] = spec_json
    root_collection[constants.PRESET_KEY] = spec_dict.get("preset_id", "")
    root_collection[constants.SEED_KEY] = int(spec_dict.get("seed", 0))
    root_collection[constants.UNIT_MODE_KEY] = spec_dict.get("unit_mode", constants.UNIT_MODE_METERS)
    root_collection[constants.EXPORT_PROFILE_KEY] = spec_dict.get("export_profile", constants.EDITABLE_ONLY)
    for key, value in version_metadata_fields().items():
        root_collection[key] = value


def write_generation_summary(root_obj, summary: dict):
    root_obj[constants.GENERATION_SUMMARY_KEY] = _stable_json(summary)


def write_final_section_registry(root_obj, registry: dict):
    root_obj[constants.FINAL_SECTION_REGISTRY_KEY] = _stable_json(registry)


def write_wall_cuboid_payload(root_obj, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise MetadataContractError("Stored authored wall cuboid payload must be a JSON object.")
    root_obj[export_contract.AUTHORED_WALL_CUBOIDS_ROOT_KEY] = _stable_json(payload)
    for key, value in wall_cuboid_metadata_fields().items():
        root_obj[key] = value
    clear_legacy_v1_wall_metadata(root_obj)


def read_wall_cuboid_payload(root_obj, strict: bool = False) -> dict:
    stale_keys = [key for key in legacy_v1_wall_metadata_keys() if _string_field(root_obj, key)]
    if strict and stale_keys and not root_obj.get(export_contract.AUTHORED_WALL_CUBOIDS_ROOT_KEY):
        formatted = ", ".join(sorted(stale_keys))
        raise MetadataContractError(
            f"Selected root carries only stale V1 wall metadata fields without a fresh cuboid payload: {formatted}."
        )
    payload = _read_json_dict(
        root_obj,
        export_contract.AUTHORED_WALL_CUBOIDS_ROOT_KEY,
        label="Stored authored wall cuboid payload",
        strict=strict,
    )
    if strict and stale_keys:
        formatted = ", ".join(sorted(stale_keys))
        raise MetadataContractError(
            f"Selected root still carries stale V1 wall metadata fields: {formatted}."
        )
    if not payload:
        return {}
    metadata_fields = wall_cuboid_metadata_fields()
    missing_keys = [key for key in metadata_fields if not _string_field(root_obj, key)]
    mismatches = [
        (
            key,
            _string_field(root_obj, key),
            expected,
        )
        for key, expected in metadata_fields.items()
        if _string_field(root_obj, key) not in {"", expected}
    ]
    if missing_keys and strict:
        formatted = ", ".join(sorted(missing_keys))
        raise MetadataContractError(
            f"Stored authored wall cuboid payload is missing contract metadata fields: {formatted}."
        )
    if mismatches and strict:
        formatted = ", ".join(
            f"{key}={actual!r} (expected {expected!r})" for key, actual, expected in mismatches
        )
        raise MetadataContractError(f"Stored authored wall cuboid payload has stale contract metadata: {formatted}.")
    return payload


def clear_wall_cuboid_payload(root_obj) -> None:
    root_obj.pop(export_contract.AUTHORED_WALL_CUBOIDS_ROOT_KEY, None)
    for key in wall_cuboid_metadata_fields():
        root_obj.pop(key, None)
    clear_legacy_v1_wall_metadata(root_obj)


def write_wall_cell_payload(root_obj, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise MetadataContractError("Stored authored wall cell payload must be a JSON object.")
    payload_kind = str(payload.get("payload_kind", ""))
    payload_version = str(payload.get("payload_version", ""))
    if payload_kind != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
        raise MetadataContractError(
            "Stored authored wall cell payload has invalid payload_kind "
            f"{payload_kind!r}; expected {export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND!r}."
        )
    if payload_version != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
        raise MetadataContractError(
            "Stored authored wall cell payload has invalid payload_version "
            f"{payload_version!r}; expected {export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION!r}."
        )
    root_obj[export_contract.AUTHORED_WALL_CELLS_ROOT_KEY] = _stable_json(payload)
    for key, value in wall_cell_metadata_fields().items():
        root_obj[key] = value
    clear_legacy_v1_wall_metadata(root_obj)


def read_wall_cell_payload(root_obj, strict: bool = False) -> dict:
    stale_keys = [key for key in legacy_v1_wall_metadata_keys() if _string_field(root_obj, key)]
    payload = _read_json_dict(
        root_obj,
        export_contract.AUTHORED_WALL_CELLS_ROOT_KEY,
        label="Stored authored wall cell payload",
        strict=strict,
    )
    if strict and stale_keys:
        formatted = ", ".join(sorted(stale_keys))
        raise MetadataContractError(
            f"Selected root still carries stale V1 wall metadata fields with a V3 cell payload: {formatted}."
        )
    if stale_keys:
        return {}
    if not payload:
        return {}
    metadata_fields = wall_cell_metadata_fields()
    missing_keys = [key for key in metadata_fields if not _string_field(root_obj, key)]
    mismatches = [
        (
            key,
            _string_field(root_obj, key),
            expected,
        )
        for key, expected in metadata_fields.items()
        if _string_field(root_obj, key) not in {"", expected}
    ]
    payload_mismatches = [
        ("payload_kind", str(payload.get("payload_kind", "")), export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND),
        ("payload_version", str(payload.get("payload_version", "")), export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION),
    ]
    payload_mismatches = [
        (key, actual, expected) for key, actual, expected in payload_mismatches if actual != expected
    ]
    if payload_mismatches and strict:
        formatted = ", ".join(
            f"{key}={actual!r} (expected {expected!r})" for key, actual, expected in payload_mismatches
        )
        raise MetadataContractError(f"Stored authored wall cell payload has invalid payload contract: {formatted}.")
    if payload_mismatches:
        return {}
    if missing_keys and strict:
        formatted = ", ".join(sorted(missing_keys))
        raise MetadataContractError(
            f"Stored authored wall cell payload is missing contract metadata fields: {formatted}."
        )
    if missing_keys:
        return {}
    if mismatches and strict:
        formatted = ", ".join(
            f"{key}={actual!r} (expected {expected!r})" for key, actual, expected in mismatches
        )
        raise MetadataContractError(f"Stored authored wall cell payload has stale contract metadata: {formatted}.")
    if mismatches:
        return {}
    return payload


def clear_wall_cell_payload(root_obj) -> None:
    root_obj.pop(export_contract.AUTHORED_WALL_CELLS_ROOT_KEY, None)
    for key in wall_cell_metadata_fields():
        root_obj.pop(key, None)
    clear_legacy_v1_wall_metadata(root_obj)


def write_voxel_wall_occupancy_payload(root_obj, payload: dict) -> None:
    write_wall_cell_payload(root_obj, payload)


def read_voxel_wall_occupancy_payload(root_obj, strict: bool = False) -> dict:
    return read_wall_cell_payload(root_obj, strict=strict)


def clear_voxel_wall_occupancy_payload(root_obj) -> None:
    clear_wall_cell_payload(root_obj)


def read_spec_dict(root_obj, *, strict: bool = False) -> dict:
    return _read_json_dict(root_obj, constants.SPEC_JSON_KEY, label="Stored spec metadata", strict=strict)


def read_effective_spec_dict(
    root_obj,
    *,
    strict: bool = False,
    allow_legacy_dirty: bool = False,
) -> dict:
    # Canonical stored spec is the default truth; legacy dirty spec is opt-in only.
    stored_spec = read_spec_dict(root_obj, strict=False)
    if allow_legacy_dirty and bool(root_obj is not None and root_obj.get("tbg_edit_mode_dirty")):
        edit_spec = _read_json_dict(
            root_obj,
            "tbg_edit_spec_json",
            label="Legacy dirty edit spec metadata",
            strict=False,
        )
        if edit_spec:
            return edit_spec
        if strict and not stored_spec:
            raise MetadataContractError("Legacy dirty edit spec metadata is empty on the selected root.")
    if stored_spec:
        return stored_spec
    if strict:
        return read_spec_dict(root_obj, strict=True)
    return {}


def read_generation_summary(root_obj, *, strict: bool = False) -> dict:
    return _read_json_dict(
        root_obj,
        constants.GENERATION_SUMMARY_KEY,
        label="Stored generation summary",
        strict=strict,
    )


def read_final_section_registry(root_obj, *, strict: bool = False) -> dict:
    return _read_json_dict(
        root_obj,
        constants.FINAL_SECTION_REGISTRY_KEY,
        label="Stored final section registry",
        strict=strict,
    )


def read_summary_schema_version(root_obj) -> str:
    return str(root_obj.get(constants.SUMMARY_SCHEMA_VERSION_KEY, ""))


def read_export_contract_version(root_obj) -> str:
    return str(root_obj.get(constants.EXPORT_CONTRACT_VERSION_KEY, ""))


def resolve_root_from_object(obj):
    current = obj
    while current:
        if current.get(constants.ROOT_OBJECT_KEY):
            return current
        current = current.parent
    return None


def is_root_object(obj) -> bool:
    return bool(obj and obj.get(constants.ROOT_OBJECT_KEY))
