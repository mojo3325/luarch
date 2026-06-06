from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from .. import constants


BUILDING_WORLD_SCALE = 3.0
DIMENSION_SPACE_SOURCE = "SOURCE"
DIMENSION_SPACE_WORLD = "WORLD"

MULTI_FLOOR_STAIR_WIDTH_MIN = 1.2
MULTI_FLOOR_CORE_WIDTH_MIN = 2.0
MULTI_FLOOR_CORE_DEPTH_MIN = 4.0
MULTI_FLOOR_DOOR_WIDTH_MIN = 1.2
MULTI_FLOOR_DOOR_HEIGHT_MIN = 2.2
GAMEPLAY_DOOR_JAMB_MIN = 0.7
CENTER_STAIR_ENTRY_LOBBY_MIN = 1.75
HOUSE_CENTER_STAIR_ENTRY_LOBBY_MIN = 2.0
CENTER_STAIR_DOOR_CLEARANCE = 0.48
HOUSE_CENTER_STAIR_DOOR_CLEARANCE = 0.62

FACADE_MODE_SPLIT = "SPLIT"
FACADE_MODE_UNIFORM_BRICK = "UNIFORM_BRICK"
FACADE_MODE_UNIFORM_FLAT = "UNIFORM_FLAT"
SUPPORTED_FACADE_MODES = (
    FACADE_MODE_SPLIT,
    FACADE_MODE_UNIFORM_BRICK,
    FACADE_MODE_UNIFORM_FLAT,
)

FACADE_BAND_PROFILE_TRIM_DEFAULT = "TRIM_DEFAULT"
FACADE_BAND_PROFILE_BRICK_REVEAL = "BRICK_REVEAL"
FACADE_BAND_PROFILE_CONCRETE_BAND = "CONCRETE_BAND"
FACADE_BAND_PROFILE_NONE = "NONE"
FACADE_BAND_PROFILE_HEAVY_CORNICE = "HEAVY_CORNICE"
SUPPORTED_FACADE_BAND_PROFILES = (
    FACADE_BAND_PROFILE_TRIM_DEFAULT,
    FACADE_BAND_PROFILE_BRICK_REVEAL,
    FACADE_BAND_PROFILE_CONCRETE_BAND,
    FACADE_BAND_PROFILE_NONE,
    FACADE_BAND_PROFILE_HEAVY_CORNICE,
)

FOUNDATION_PROFILE_PLAIN = "PLAIN"
FOUNDATION_PROFILE_HEAVY_BASE = "HEAVY_BASE"
FOUNDATION_PROFILE_STONE_BASE = "STONE_BASE"
FOUNDATION_PROFILE_EXPOSED_BRICK_BASE = "EXPOSED_BRICK_BASE"
SUPPORTED_FOUNDATION_PROFILES = (
    FOUNDATION_PROFILE_PLAIN,
    FOUNDATION_PROFILE_HEAVY_BASE,
    FOUNDATION_PROFILE_STONE_BASE,
    FOUNDATION_PROFILE_EXPOSED_BRICK_BASE,
)

DOOR_PROFILE_HINGED = "HINGED"
DOOR_PROFILE_ROLLER = "ROLLER"
SUPPORTED_DOOR_PROFILES = (
    DOOR_PROFILE_HINGED,
    DOOR_PROFILE_ROLLER,
)

STAIR_CORE_VARIANT_DEFAULT = "DEFAULT"
STAIR_CORE_VARIANT_OPEN = "OPEN"
SUPPORTED_STAIR_CORE_VARIANTS = (
    STAIR_CORE_VARIANT_DEFAULT,
    STAIR_CORE_VARIANT_OPEN,
)

STOOP_VARIANT_STRAIGHT = "STRAIGHT"
STOOP_VARIANT_ROUNDED = "ROUNDED"
SUPPORTED_STOOP_VARIANTS = (
    STOOP_VARIANT_STRAIGHT,
    STOOP_VARIANT_ROUNDED,
)

ROOF_MODE_FLAT = "FLAT"
ROOF_MODE_TERRACE = "TERRACE"
ROOF_MODE_GABLE = "GABLE"
ROOF_MODE_BARREL = "BARREL"
ROOF_MODE_SHED = "SHED"
ROOF_MODE_SAWTOOTH = "SAWTOOTH"
SUPPORTED_ROOF_MODES = (
    ROOF_MODE_FLAT,
    ROOF_MODE_TERRACE,
    ROOF_MODE_GABLE,
    ROOF_MODE_BARREL,
    ROOF_MODE_SHED,
    ROOF_MODE_SAWTOOTH,
)

WINDOW_PROFILE_RESIDENTIAL = "RESIDENTIAL"
WINDOW_PROFILE_RESIDENTIAL_WIDE = "RESIDENTIAL_WIDE"
WINDOW_PROFILE_OFFICE = "OFFICE"
WINDOW_PROFILE_OFFICE_BAND = "OFFICE_BAND"
WINDOW_PROFILE_SMALL_SQUARE = "SMALL_SQUARE"
WINDOW_PROFILE_PANORAMIC = "PANORAMIC"
WINDOW_PROFILE_TALL_NARROW = "TALL_NARROW"
WINDOW_PROFILE_MULTI_PANE = "MULTI_PANE"
SUPPORTED_WINDOW_PROFILES = (
    WINDOW_PROFILE_RESIDENTIAL,
    WINDOW_PROFILE_RESIDENTIAL_WIDE,
    WINDOW_PROFILE_OFFICE,
    WINDOW_PROFILE_OFFICE_BAND,
    WINDOW_PROFILE_SMALL_SQUARE,
    WINDOW_PROFILE_PANORAMIC,
    WINDOW_PROFILE_TALL_NARROW,
    WINDOW_PROFILE_MULTI_PANE,
)

GROUND_FLOOR_OPEN_ENTRY = "OPEN_ENTRY"
GROUND_FLOOR_DEFENSIVE_BASE = "DEFENSIVE_BASE"
GROUND_FLOOR_MIXED_WINDOWS = "MIXED_WINDOWS"
GROUND_FLOOR_STOREFRONT = "STOREFRONT"
SUPPORTED_GROUND_FLOOR_TACTICAL_PROFILES = (
    GROUND_FLOOR_OPEN_ENTRY,
    GROUND_FLOOR_DEFENSIVE_BASE,
    GROUND_FLOOR_MIXED_WINDOWS,
    GROUND_FLOOR_STOREFRONT,
)

_ROOT_DIMENSION_KEYS = ("width", "depth", "floor_height", "wall_thickness", "slab_thickness", "parapet_height")
_STAIR_DIMENSION_KEYS = ("core_width", "core_depth", "stair_width")
_DOOR_DIMENSION_KEYS = ("width", "height", "thickness", "offset_x")
SUPPORTED_FLAT_FACADE_FAMILIES = (
    "SANDSTONE_FLAT",
    "CONCRETE_FLAT",
    "PLASTER_WARM",
    "PLASTER_COOL",
    "TIMBER_WARM",
    "TIMBER_WEATHERED",
    "PAINTED_WOOD",
)
_ROOMY_MULTI_FLOOR_ENVELOPES: dict[str, dict[str, float]] = {
    "house_small": {
        "outer_width_min": 8.8,
        "outer_depth_min": 8.8,
        "core_width_reserve": 2.0,
        "core_depth_reserve": 1.2,
    },
    "house_wide": {
        "outer_width_min": 10.6,
        "outer_depth_min": 8.2,
        "core_width_reserve": 1.95,
        "core_depth_reserve": 1.2,
    },
    "wood_house": {
        "outer_width_min": 10.2,
        "outer_depth_min": 8.4,
        "core_width_reserve": 2.05,
        "core_depth_reserve": 1.2,
    },
    "wood_rowhouse": {
        "outer_width_min": 8.6,
        "outer_depth_min": 7.8,
        "core_width_reserve": 1.7,
        "core_depth_reserve": 1.0,
    },
    "townhouse": {
        "outer_width_min": 9.0,
        "outer_depth_min": 8.2,
        "core_width_reserve": 1.8,
        "core_depth_reserve": 1.1,
    },
    "apartment_lowrise": {
        "outer_width_min": 9.6,
        "outer_depth_min": 8.2,
        "core_width_reserve": 1.7,
        "core_depth_reserve": 1.05,
    },
}
_COMPACT_RESIDENTIAL_ENVELOPES: dict[str, dict[str, float]] = {
    "wood_rowhouse": {
        "outer_width_min": 8.6,
        "outer_depth_min": 7.8,
        "core_width_reserve": 1.7,
        "core_depth_reserve": 1.0,
        "front_conflict_edge_relief": 0.22,
    },
    "townhouse": {
        "outer_width_min": 9.0,
        "outer_depth_min": 8.2,
        "core_width_reserve": 1.8,
        "core_depth_reserve": 1.1,
        "front_conflict_edge_relief": 0.18,
    },
    "apartment_lowrise": {
        "outer_width_min": 9.6,
        "outer_depth_min": 8.2,
        "core_width_reserve": 1.7,
        "core_depth_reserve": 1.05,
        "front_conflict_edge_relief": 0.16,
    },
}
_MULTI_FLOOR_PRESSURE_RELIEF_MINIMA = {
    preset_id: (float(contract["outer_width_min"]), float(contract["outer_depth_min"]))
    for preset_id, contract in _ROOMY_MULTI_FLOOR_ENVELOPES.items()
}
_SINGLE_FLOOR_BASELINE_MINIMA = {
    "house_small": (7.0, 5.0),
}
_CENTER_STAIR_SAFE_MINIMA = {
    "house_wide": (11.4, 8.6),
}
_WOOD_GABLE_PRESET_IDS = frozenset({"wood_rowhouse"})


class SpecContractError(ValueError):
    pass


def gameplay_outer_minimums(preset_id: str, floor_count: int) -> tuple[float, float]:
    width_min = 0.0
    depth_min = 0.0
    single_floor_minima = _SINGLE_FLOOR_BASELINE_MINIMA.get(str(preset_id))
    if floor_count <= 1 and single_floor_minima is not None:
        width_min = max(width_min, float(single_floor_minima[0]))
        depth_min = max(depth_min, float(single_floor_minima[1]))
    if floor_count > 1:
        width_min = 7.8
        depth_min = 6.8
        pressure_relief = _MULTI_FLOOR_PRESSURE_RELIEF_MINIMA.get(str(preset_id))
        if pressure_relief is not None:
            width_min = max(width_min, float(pressure_relief[0]))
            depth_min = max(depth_min, float(pressure_relief[1]))
    if preset_id == "apartment_midrise" and floor_count >= 5:
        width_min = max(width_min, 10.5)
        depth_min = max(depth_min, 8.0)
    if preset_id == "office_block" and floor_count >= 5:
        width_min = max(width_min, 15.5)
        depth_min = max(depth_min, 11.5)
    return width_min, depth_min


def roomy_multi_floor_envelope(preset_id: str, floor_count: int) -> dict[str, float]:
    preset = str(preset_id or "").lower()
    if int(floor_count) <= 1:
        return {
            "outer_width_min": 0.0,
            "outer_depth_min": 0.0,
            "core_width_reserve": 1.1,
            "core_depth_reserve": 0.7,
        }
    contract = _ROOMY_MULTI_FLOOR_ENVELOPES.get(preset)
    if contract is None:
        return {
            "outer_width_min": 0.0,
            "outer_depth_min": 0.0,
            "core_width_reserve": 1.1,
            "core_depth_reserve": 0.7,
        }
    return dict(contract)


def compact_residential_envelope(preset_id: str, floor_count: int) -> dict[str, float]:
    preset = str(preset_id or "").lower()
    if int(floor_count) <= 1:
        return {
            "outer_width_min": 0.0,
            "outer_depth_min": 0.0,
            "core_width_reserve": 1.1,
            "core_depth_reserve": 0.7,
            "front_conflict_edge_relief": 0.0,
        }
    contract = _COMPACT_RESIDENTIAL_ENVELOPES.get(preset)
    if contract is None:
        return {
            "outer_width_min": 0.0,
            "outer_depth_min": 0.0,
            "core_width_reserve": 1.1,
            "core_depth_reserve": 0.7,
            "front_conflict_edge_relief": 0.0,
        }
    return dict(contract)


def minimum_expected_open_windows(spec, slot_count: int) -> int:
    if slot_count <= 0:
        return 0
    if bool(getattr(spec, "window_policy_manual_override", False)):
        return 0
    if spec.preset_id == "house_small" and int(spec.floor_count) == 1:
        return 0
    return min(slot_count, max(0, int(spec.combat_open_window_min)))


def normalized_entrance_profile(value: str) -> str:
    if value in {"STOOP", "STOOP_LOW"}:
        return "STOOP_LOW"
    if value in {"PODIUM", "PODIUM_HIGH"}:
        return "PODIUM_HIGH"
    return "FLUSH"


def normalized_balcony_mode(value: str) -> str:
    if value in {"SPARSE", "SHORT"}:
        return "SHORT"
    if value in {"STACKED", "STRIP"}:
        return "STRIP"
    return "NONE"


def normalized_facade_mode(value: str) -> str:
    mode = str(value or FACADE_MODE_SPLIT).upper()
    return mode if mode in SUPPORTED_FACADE_MODES else FACADE_MODE_SPLIT


def normalized_facade_band_profile(value: str) -> str:
    profile = str(value or FACADE_BAND_PROFILE_TRIM_DEFAULT).upper()
    return profile if profile in SUPPORTED_FACADE_BAND_PROFILES else FACADE_BAND_PROFILE_TRIM_DEFAULT


def normalized_foundation_profile(value: str) -> str:
    profile = str(value or FOUNDATION_PROFILE_PLAIN).upper()
    return profile if profile in SUPPORTED_FOUNDATION_PROFILES else FOUNDATION_PROFILE_PLAIN


def normalized_door_profile(value: str) -> str:
    profile = str(value or DOOR_PROFILE_HINGED).upper()
    return profile if profile in SUPPORTED_DOOR_PROFILES else DOOR_PROFILE_HINGED


def normalized_stair_core_variant(value: str) -> str:
    variant = str(value or STAIR_CORE_VARIANT_DEFAULT).upper()
    return variant if variant in SUPPORTED_STAIR_CORE_VARIANTS else STAIR_CORE_VARIANT_DEFAULT


def normalized_stoop_variant(value: str) -> str:
    variant = str(value or STOOP_VARIANT_STRAIGHT).upper()
    return variant if variant in SUPPORTED_STOOP_VARIANTS else STOOP_VARIANT_STRAIGHT


def default_front_stoop_variant(values: Mapping | dict | None = None) -> str:
    if values is None:
        return STOOP_VARIANT_ROUNDED
    entrance_profile = normalized_entrance_profile(values.get("entrance_profile", "FLUSH"))
    if entrance_profile in {"STOOP_LOW", "PODIUM_HIGH"}:
        return STOOP_VARIANT_ROUNDED
    return STOOP_VARIANT_STRAIGHT


def normalized_roof_mode(value: str) -> str:
    mode = str(value or ROOF_MODE_FLAT).upper()
    return mode if mode in SUPPORTED_ROOF_MODES else ROOF_MODE_FLAT


def clamped_facade_completion(value) -> float:
    try:
        completion = float(value)
    except (TypeError, ValueError):
        completion = 1.0
    return max(0.0, min(1.0, completion))


def normalized_facade_family(value: str, facade_mode: str | None = None) -> str:
    family = str(value or "LIGHT_BRICK").upper()
    mode = normalized_facade_mode(facade_mode)
    if mode == FACADE_MODE_UNIFORM_FLAT:
        if family in SUPPORTED_FLAT_FACADE_FAMILIES:
            return family
        return SUPPORTED_FLAT_FACADE_FAMILIES[0]
    if family in SUPPORTED_FLAT_FACADE_FAMILIES:
        return "LIGHT_BRICK"
    if family in constants.SUPPORTED_SPLIT_FACADE_FAMILIES:
        return family
    return "LIGHT_BRICK"


def supported_facade_families(facade_mode: str | None = None) -> tuple[str, ...]:
    mode = normalized_facade_mode(facade_mode)
    if mode == FACADE_MODE_UNIFORM_FLAT:
        return SUPPORTED_FLAT_FACADE_FAMILIES
    return constants.SUPPORTED_SPLIT_FACADE_FAMILIES


def side_sign(value: str) -> float:
    return -1.0 if value in {"front", "left"} else 1.0


def center_stair_gameplay_requirements(
    preset_id: str,
    *,
    core_width: float,
    core_depth: float,
    door_width: float,
    wall_thickness: float,
) -> tuple[float, float, float]:
    entry_lobby = HOUSE_CENTER_STAIR_ENTRY_LOBBY_MIN if preset_id == "house_small" else CENTER_STAIR_ENTRY_LOBBY_MIN
    door_clearance = HOUSE_CENTER_STAIR_DOOR_CLEARANCE if preset_id == "house_small" else CENTER_STAIR_DOOR_CLEARANCE
    width_min = core_width + door_width * 2 + (door_clearance + GAMEPLAY_DOOR_JAMB_MIN) * 2
    depth_min = core_depth + wall_thickness * 2 + entry_lobby * 2
    required_abs_offset = core_width / 2 + door_width / 2 + door_clearance
    return width_min, depth_min, required_abs_offset


def normalized_payload_from_mapping(mapping: dict) -> dict:
    return _normalized_payload(_payload_from_mapping(mapping))


def _mapping_copy(mapping, *, label: str) -> dict:
    if not isinstance(mapping, Mapping):
        raise SpecContractError(f"{label} must be a mapping.")
    return dict(mapping)


def _float_field(mapping: Mapping, key: str, *, label: str):
    try:
        return float(mapping[key])
    except KeyError as exc:
        raise SpecContractError(f"{label} is missing '{key}'.") from exc
    except (TypeError, ValueError) as exc:
        raise SpecContractError(f"{label} field '{key}' must be numeric.") from exc


def _int_field(mapping: Mapping, key: str, *, label: str):
    try:
        return int(mapping[key])
    except KeyError as exc:
        raise SpecContractError(f"{label} is missing '{key}'.") from exc
    except (TypeError, ValueError) as exc:
        raise SpecContractError(f"{label} field '{key}' must be an integer.") from exc


def _bool_field(mapping: Mapping, key: str, *, label: str):
    try:
        return bool(mapping[key])
    except KeyError as exc:
        raise SpecContractError(f"{label} is missing '{key}'.") from exc


def _string_field(mapping: Mapping, key: str, *, label: str):
    try:
        value = str(mapping[key])
    except KeyError as exc:
        raise SpecContractError(f"{label} is missing '{key}'.") from exc
    if not value:
        raise SpecContractError(f"{label} field '{key}' cannot be empty.")
    return value


def _payload_from_nested_contract(mapping: Mapping) -> dict:
    payload = dict(mapping)
    stair = _mapping_copy(mapping.get("stair_core"), label="Stored spec stair_core")
    door = _mapping_copy(mapping.get("door"), label="Stored spec door")
    payload["world_scale"] = _payload_world_scale(payload)
    payload["dimension_space"] = _payload_dimension_space(payload, default=DIMENSION_SPACE_SOURCE)
    payload["stair_placement"] = _string_field(stair, "placement", label="Stored spec stair_core")
    payload["stair_core_enabled"] = _bool_field(stair, "enabled", label="Stored spec stair_core")
    payload["core_width"] = _float_field(stair, "core_width", label="Stored spec stair_core")
    payload["core_depth"] = _float_field(stair, "core_depth", label="Stored spec stair_core")
    payload["stair_width"] = _float_field(stair, "stair_width", label="Stored spec stair_core")
    payload["step_count"] = _int_field(stair, "step_count", label="Stored spec stair_core")
    payload["railing_enabled"] = _bool_field(stair, "railing_enabled", label="Stored spec stair_core")
    payload["stair_core_variant"] = str(stair.get("variant", STAIR_CORE_VARIANT_DEFAULT))
    payload["door_width"] = _float_field(door, "width", label="Stored spec door")
    payload["door_enabled"] = _bool_field(door, "enabled", label="Stored spec door")
    payload["door_height"] = _float_field(door, "height", label="Stored spec door")
    payload["door_thickness"] = _float_field(door, "thickness", label="Stored spec door")
    payload["door_offset_x"] = _float_field(door, "offset_x", label="Stored spec door")
    payload["door_hinge"] = _string_field(door, "hinge", label="Stored spec door")
    return payload


def _payload_from_mapping(mapping, *, require_nested_contract: bool = False) -> dict:
    payload = _mapping_copy(mapping, label="Building spec payload")
    has_nested_contract = "stair_core" in payload or "door" in payload
    if require_nested_contract:
        if "stair_core" not in payload or "door" not in payload:
            raise SpecContractError("Stored spec is missing canonical 'stair_core' or 'door' objects.")
        return _payload_from_nested_contract(payload)
    if has_nested_contract:
        return _payload_from_nested_contract(payload)
    payload["world_scale"] = _payload_world_scale(payload)
    payload["dimension_space"] = _payload_dimension_space(payload, default=DIMENSION_SPACE_SOURCE)
    return payload


def _payload_world_scale(values: dict) -> float:
    scale = float(values.get("world_scale", BUILDING_WORLD_SCALE))
    return scale if scale > 1e-6 else BUILDING_WORLD_SCALE


def _payload_dimension_space(values: dict, *, default: str) -> str:
    dimension_space = str(values.get("dimension_space", default)).upper()
    if dimension_space not in {DIMENSION_SPACE_SOURCE, DIMENSION_SPACE_WORLD}:
        return default
    return dimension_space


def _normalized_payload(values: dict) -> dict:
    normalized = dict(values)
    normalized["world_scale"] = _payload_world_scale(normalized)
    normalized["dimension_space"] = _payload_dimension_space(normalized, default=DIMENSION_SPACE_SOURCE)
    normalized["facade_mode"] = normalized_facade_mode(normalized.get("facade_mode", FACADE_MODE_SPLIT))
    normalized["facade_band_profile"] = normalized_facade_band_profile(
        normalized.get("facade_band_profile", FACADE_BAND_PROFILE_TRIM_DEFAULT)
    )
    normalized["foundation_profile"] = normalized_foundation_profile(
        normalized.get("foundation_profile", FOUNDATION_PROFILE_PLAIN)
    )
    normalized["door_profile"] = normalized_door_profile(normalized.get("door_profile", DOOR_PROFILE_HINGED))
    normalized["stair_core_variant"] = normalized_stair_core_variant(
        normalized.get("stair_core_variant", STAIR_CORE_VARIANT_DEFAULT)
    )
    normalized["front_stoop_variant"] = normalized_stoop_variant(
        normalized.get("front_stoop_variant", default_front_stoop_variant(normalized))
    )
    normalized["rear_stoop_variant"] = normalized_stoop_variant(
        normalized.get("rear_stoop_variant", STOOP_VARIANT_STRAIGHT)
    )
    normalized["roof_mode"] = normalized_roof_mode(normalized.get("roof_mode", ROOF_MODE_FLAT))
    normalized["facade_completion"] = clamped_facade_completion(normalized.get("facade_completion", 1.0))
    normalized["facade_family"] = normalized_facade_family(
        normalized.get("facade_family", "LIGHT_BRICK"),
        facade_mode=normalized["facade_mode"],
    )
    preset_id = str(normalized.get("preset_id", "apartment_midrise"))
    floor_count = int(normalized.get("floor_count", 3))
    if preset_id == "hangar":
        floor_count = 1
    roof_mode = str(normalized.get("roof_mode", ROOF_MODE_FLAT))
    width = float(normalized.get("width", 8.0))
    depth = float(normalized.get("depth", 6.0))
    massing_profile = str(normalized.get("massing_profile", "BOX")).upper()
    facade_mode = str(normalized.get("facade_mode", FACADE_MODE_SPLIT)).upper()
    facade_band_profile = str(normalized.get("facade_band_profile", FACADE_BAND_PROFILE_TRIM_DEFAULT)).upper()
    balcony_mode = str(normalized.get("balcony_mode", "NONE")).upper()
    envelope_area = width * depth
    if preset_id == "office_block":
        manual_window_override = bool(normalized.get("window_policy_manual_override", False))
        strip_balcony = balcony_mode == "STRIP"
        if strip_balcony:
            balcony_mode = "SHORT"
            normalized["balcony_mode"] = balcony_mode
        if floor_count >= 6 and (strip_balcony or massing_profile == "BASE_HEAVY" or envelope_area >= 140.0):
            floor_count = 5
        elif floor_count >= 7:
            floor_count = 6
        if floor_count >= 5 and facade_mode == "UNIFORM_BRICK":
            facade_mode = FACADE_MODE_SPLIT
            normalized["facade_mode"] = facade_mode
        if floor_count >= 5 and facade_band_profile == "BRICK_REVEAL":
            normalized["facade_band_profile"] = FACADE_BAND_PROFILE_TRIM_DEFAULT
        if not manual_window_override and float(normalized.get("open_window_ratio", 0.0)) > 0.34:
            normalized["open_window_ratio"] = 0.34
        if float(normalized.get("wide_window_ratio", 0.0)) > 0.44:
            normalized["wide_window_ratio"] = 0.44
    if preset_id in _WOOD_GABLE_PRESET_IDS:
        roof_mode = ROOF_MODE_GABLE
        normalized["roof_mode"] = roof_mode
    if roof_mode == ROOF_MODE_TERRACE and floor_count < 3 and preset_id != "motel":
        roof_mode = ROOF_MODE_FLAT
        normalized["roof_mode"] = roof_mode
    wall_thickness = float(normalized.get("wall_thickness", 0.2))
    stair_placement = str(normalized.get("stair_placement", "FRONT_RIGHT"))
    stair_width = float(normalized.get("stair_width", 1.8))
    core_width = float(normalized.get("core_width", 2.0))
    core_depth = float(normalized.get("core_depth", 3.8))
    door_width = float(normalized.get("door_width", 1.2))
    door_height = float(normalized.get("door_height", 2.2))
    door_offset_x = float(normalized.get("door_offset_x", -2.0))
    entrance_profile = normalized_entrance_profile(normalized.get("entrance_profile", "FLUSH"))
    if entrance_profile != "FLUSH":
        normalized["door_enabled"] = True

    outer_width_min, outer_depth_min = gameplay_outer_minimums(preset_id, floor_count)
    width = max(width, outer_width_min)
    depth = max(depth, outer_depth_min)

    if floor_count > 1:
        compact_envelope = compact_residential_envelope(preset_id, floor_count)
        stair_width = max(stair_width, MULTI_FLOOR_STAIR_WIDTH_MIN)
        core_width = max(core_width, MULTI_FLOOR_CORE_WIDTH_MIN)
        core_depth = max(core_depth, MULTI_FLOOR_CORE_DEPTH_MIN)
        door_width = max(door_width, MULTI_FLOOR_DOOR_WIDTH_MIN)
        door_height = max(door_height, MULTI_FLOOR_DOOR_HEIGHT_MIN)
        width = max(width, core_width + wall_thickness * 2 + 3.1)
        depth = max(depth, core_depth + wall_thickness * 2 + 2.1)
        center_safe_minima = _CENTER_STAIR_SAFE_MINIMA.get(preset_id)
        if stair_placement == constants.STAIR_PLACEMENT_CENTER and center_safe_minima is not None:
            if width < float(center_safe_minima[0]) or depth < float(center_safe_minima[1]):
                stair_placement = (
                    constants.STAIR_PLACEMENT_BACK_RIGHT
                    if door_offset_x <= 0.0
                    else constants.STAIR_PLACEMENT_BACK_LEFT
                )
        if stair_placement == "CENTER":
            center_width_min, center_depth_min, required_abs_offset = center_stair_gameplay_requirements(
                preset_id,
                core_width=core_width,
                core_depth=core_depth,
                door_width=door_width,
                wall_thickness=wall_thickness,
            )
            width = max(width, center_width_min)
            depth = max(depth, center_depth_min)
            max_offset = width / 2 - GAMEPLAY_DOOR_JAMB_MIN - door_width / 2
            if max_offset > 0.0:
                sign = -1.0 if door_offset_x <= 0.0 else 1.0
                door_offset_x = sign * min(max_offset, max(required_abs_offset, abs(door_offset_x)))
        if float(compact_envelope["outer_width_min"]) > 0.0:
            if stair_placement == constants.STAIR_PLACEMENT_FRONT_RIGHT and door_offset_x > 0.0:
                door_offset_x = -abs(door_offset_x)

    normalized["width"] = width
    normalized["depth"] = depth
    normalized["core_width"] = core_width
    normalized["core_depth"] = core_depth
    normalized["stair_width"] = stair_width
    normalized["stair_placement"] = stair_placement
    normalized["door_width"] = door_width
    normalized["door_height"] = door_height
    normalized["door_offset_x"] = door_offset_x
    normalized["floor_count"] = floor_count
    if floor_count > 1:
        normalized["stair_core_enabled"] = True
    return normalized


def _spec_from_payload(payload: dict, *, building_id: str | None, origin: tuple[float, float, float]):
    floor_count = int(payload.get("floor_count", 3))
    stair_core_enabled = bool(payload.get("stair_core_enabled", floor_count > 1))
    if floor_count > 1:
        stair_core_enabled = True
    world_scale = _payload_world_scale(payload)
    dimension_space = _payload_dimension_space(payload, default=DIMENSION_SPACE_SOURCE)
    scale = 1.0 / world_scale if dimension_space == DIMENSION_SPACE_WORLD else 1.0
    return BuildingSpec(
        building_id=building_id or payload.get("building_id"),
        preset_id=payload.get("preset_id", "apartment_midrise"),
        seed=int(payload.get("seed", 0)),
        unit_mode=payload.get("unit_mode", "METERS"),
        export_profile=payload.get("export_profile", "EDITABLE_ONLY"),
        facade_family=payload.get("facade_family", "LIGHT_BRICK"),
        facade_mode=payload.get("facade_mode", FACADE_MODE_SPLIT),
        facade_band_profile=payload.get("facade_band_profile", FACADE_BAND_PROFILE_TRIM_DEFAULT),
        window_profile=payload.get("window_profile", "RESIDENTIAL"),
        entrance_profile=payload.get("entrance_profile", "FLUSH"),
        balcony_mode=payload.get("balcony_mode", "NONE"),
        open_window_ratio=float(payload.get("open_window_ratio", 0.62)),
        combat_open_window_min=int(payload.get("combat_open_window_min", 1)),
        window_policy_manual_override=bool(payload.get("window_policy_manual_override", False)),
        wide_window_ratio=float(payload.get("wide_window_ratio", 0.2)),
        tactical_facade_profile=payload.get("tactical_facade_profile", "DEFAULT"),
        massing_profile=payload.get("massing_profile", "BOX"),
        ground_floor_tactical_profile=payload.get("ground_floor_tactical_profile", "MIXED_WINDOWS"),
        foundation_profile=payload.get("foundation_profile", FOUNDATION_PROFILE_PLAIN),
        facade_ac_ratio=float(payload.get("facade_ac_ratio", 0.0)),
        door_profile=payload.get("door_profile", DOOR_PROFILE_HINGED),
        roof_mode=payload.get("roof_mode", ROOF_MODE_FLAT),
        roof_prop_profile=payload.get("roof_prop_profile", "NONE"),
        stair_window_mode=payload.get("stair_window_mode", "NONE"),
        service_profile=payload.get("service_profile", "STANDARD"),
        facade_completion=float(payload.get("facade_completion", 1.0)),
        width=float(payload.get("width", 8.0)) * scale,
        depth=float(payload.get("depth", 6.0)) * scale,
        floor_count=floor_count,
        floor_height=float(payload.get("floor_height", 3.0)) * scale,
        wall_thickness=float(payload.get("wall_thickness", 0.2)) * scale,
        slab_thickness=float(payload.get("slab_thickness", 0.15)) * scale,
        parapet_height=float(payload.get("parapet_height", 0.8)) * scale,
        origin=tuple(float(v) for v in origin),
        world_scale=world_scale,
        stair_core=StairCoreSpec(
            enabled=stair_core_enabled,
            placement=payload.get("stair_placement", "FRONT_RIGHT"),
            core_width=float(payload.get("core_width", 2.0)) * scale,
            core_depth=float(payload.get("core_depth", 3.8)) * scale,
            stair_width=float(payload.get("stair_width", 1.8)) * scale,
            step_count=int(payload.get("step_count", 16)),
            railing_enabled=bool(payload.get("railing_enabled", False)),
            variant=payload.get("stair_core_variant", STAIR_CORE_VARIANT_DEFAULT),
        ),
        door=DoorSpec(
            enabled=bool(payload.get("door_enabled", True)),
            width=float(payload.get("door_width", 1.2)) * scale,
            height=float(payload.get("door_height", 2.2)) * scale,
            thickness=float(payload.get("door_thickness", 0.06)) * scale,
            offset_x=float(payload.get("door_offset_x", -2.0)) * scale,
            hinge=payload.get("door_hinge", "LEFT"),
        ),
        front_stoop_variant=payload.get("front_stoop_variant", default_front_stoop_variant(payload)),
        rear_stoop_variant=payload.get("rear_stoop_variant", STOOP_VARIANT_STRAIGHT),
    )


@dataclass
class StairCoreSpec:
    enabled: bool
    placement: str
    core_width: float
    core_depth: float
    stair_width: float
    step_count: int
    railing_enabled: bool
    variant: str


@dataclass
class DoorSpec:
    enabled: bool
    width: float
    height: float
    thickness: float
    offset_x: float
    hinge: str


@dataclass
class BuildingSpec:
    building_id: str | None
    preset_id: str
    seed: int
    unit_mode: str
    export_profile: str
    facade_family: str
    facade_mode: str
    facade_band_profile: str
    window_profile: str
    entrance_profile: str
    balcony_mode: str
    open_window_ratio: float
    combat_open_window_min: int
    window_policy_manual_override: bool
    wide_window_ratio: float
    tactical_facade_profile: str
    massing_profile: str
    ground_floor_tactical_profile: str
    foundation_profile: str
    facade_ac_ratio: float
    door_profile: str
    roof_mode: str
    roof_prop_profile: str
    stair_window_mode: str
    service_profile: str
    facade_completion: float
    width: float
    depth: float
    floor_count: int
    floor_height: float
    wall_thickness: float
    slab_thickness: float
    parapet_height: float
    origin: tuple[float, float, float]
    world_scale: float
    stair_core: StairCoreSpec
    door: DoorSpec
    front_stoop_variant: str
    rear_stoop_variant: str

    def to_dict(self) -> dict:
        data = asdict(self)
        scale = self.world_scale if self.world_scale > 1e-6 else 1.0
        data["world_scale"] = scale
        data["dimension_space"] = DIMENSION_SPACE_SOURCE
        return data


def building_spec_from_settings(settings, *, building_id: str | None, origin: tuple[float, float, float]):
    payload = _normalized_payload(
        {
            "building_id": building_id,
            "preset_id": settings.preset_id,
            "seed": int(settings.seed),
            "unit_mode": settings.unit_mode,
            "export_profile": settings.export_profile,
            "facade_family": getattr(settings, "facade_family", "LIGHT_BRICK"),
            "facade_mode": getattr(settings, "facade_mode", FACADE_MODE_SPLIT),
            "facade_band_profile": getattr(settings, "facade_band_profile", FACADE_BAND_PROFILE_TRIM_DEFAULT),
            "window_profile": getattr(settings, "window_profile", "RESIDENTIAL"),
            "entrance_profile": getattr(settings, "entrance_profile", "FLUSH"),
            "balcony_mode": getattr(settings, "balcony_mode", "NONE"),
            "open_window_ratio": float(getattr(settings, "open_window_ratio", 0.62)),
            "combat_open_window_min": int(getattr(settings, "combat_open_window_min", 1)),
            "window_policy_manual_override": bool(getattr(settings, "window_policy_manual_override", False)),
            "wide_window_ratio": float(getattr(settings, "wide_window_ratio", 0.2)),
            "tactical_facade_profile": getattr(settings, "tactical_facade_profile", "DEFAULT"),
            "massing_profile": getattr(settings, "massing_profile", "BOX"),
            "ground_floor_tactical_profile": getattr(settings, "ground_floor_tactical_profile", "MIXED_WINDOWS"),
            "foundation_profile": getattr(settings, "foundation_profile", FOUNDATION_PROFILE_PLAIN),
            "facade_ac_ratio": float(getattr(settings, "facade_ac_ratio", 0.0)),
            "door_profile": getattr(settings, "door_profile", DOOR_PROFILE_HINGED),
            "roof_mode": getattr(settings, "roof_mode", ROOF_MODE_FLAT),
            "roof_prop_profile": getattr(settings, "roof_prop_profile", "NONE"),
            "stair_window_mode": getattr(settings, "stair_window_mode", "NONE"),
            "service_profile": getattr(settings, "service_profile", "STANDARD"),
            "facade_completion": float(getattr(settings, "facade_completion", 1.0)),
            "world_scale": BUILDING_WORLD_SCALE,
            "dimension_space": DIMENSION_SPACE_SOURCE,
            "width": float(settings.width),
            "depth": float(settings.depth),
            "floor_count": int(settings.floor_count),
            "floor_height": float(settings.floor_height),
            "wall_thickness": float(settings.wall_thickness),
            "slab_thickness": float(settings.slab_thickness),
            "parapet_height": float(settings.parapet_height),
            "stair_core_enabled": bool(getattr(settings, "stair_core_enabled", True)),
            "stair_placement": settings.stair_placement,
            "core_width": float(settings.core_width),
            "core_depth": float(settings.core_depth),
            "stair_width": float(settings.stair_width),
            "step_count": int(settings.step_count),
            "railing_enabled": bool(settings.railing_enabled),
            "stair_core_variant": getattr(settings, "stair_core_variant", STAIR_CORE_VARIANT_DEFAULT),
            "door_enabled": bool(getattr(settings, "door_enabled", True)),
            "door_width": float(settings.door_width),
            "door_height": float(settings.door_height),
            "door_thickness": float(settings.door_thickness),
            "door_offset_x": float(settings.door_offset_x),
            "door_hinge": settings.door_hinge,
            "front_stoop_variant": getattr(
                settings,
                "front_stoop_variant",
                default_front_stoop_variant({"entrance_profile": getattr(settings, "entrance_profile", "FLUSH")}),
            ),
            "rear_stoop_variant": getattr(settings, "rear_stoop_variant", STOOP_VARIANT_STRAIGHT),
        }
    )
    return _spec_from_payload(payload, building_id=building_id, origin=origin)


def building_spec_from_mapping(mapping: dict, *, building_id: str | None, origin: tuple[float, float, float]):
    payload = _payload_from_mapping(mapping)
    return _spec_from_payload(_normalized_payload(payload), building_id=building_id, origin=origin)


def stored_building_spec_from_mapping(mapping: dict, *, building_id: str | None, origin: tuple[float, float, float]):
    payload = _payload_from_mapping(mapping, require_nested_contract=True)
    return _spec_from_payload(_normalized_payload(payload), building_id=building_id, origin=origin)
