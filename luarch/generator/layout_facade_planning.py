from __future__ import annotations

import math

from .. import constants
from .building_layout import (
    REAR_ACCESS_PROFILE_NONE,
    REAR_ACCESS_PROFILE_OPEN_BAY,
    REAR_ACCESS_PROFILE_SERVICE_DOOR,
    REAR_ACCESS_PROFILE_SHELL_ONLY,
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    _adjacent_exterior_sides,
    _core_arrival_opening_center_x,
    _core_bounds,
    _dogleg_metrics,
    _pilotis_open_side,
    _resolve_front_entry_center_against_stair,
    _rear_entry_stair_conflict_span,
    _spatial_plan,
    _terrace_transition_contract,
    _stable_unit_float,
)
from .layout_constants import _STAGE1_IDENTITY_RESET_PRESETS
from .layout_constants import *
from .specs import (
    ROOF_MODE_FLAT,
    ROOF_MODE_GABLE,
    ROOF_MODE_SHED,
    ROOF_MODE_TERRACE,
    clamped_facade_completion as _clamped_facade_completion,
    normalized_balcony_mode as _normalized_balcony_mode,
    normalized_entrance_profile as _normalized_entrance_profile,
    normalized_facade_family as _normalized_facade_family,
    normalized_facade_mode as _normalized_facade_mode,
)

# Direct owner for facade-specific planning. Downstream consumers should import
# these helpers here, while `building_layout.py` stays limited to shared pure
# layout ownership.

_INDUSTRIAL_FAMILY_POLICY: dict[str, dict[str, str | bool]] = {
    "depot": {
        "role": "DEPOT",
        "floor_structure": "2_FLOOR_PLUS_ROOF",
        "rear_access_profile": REAR_ACCESS_PROFILE_OPEN_BAY,
        "frontage_variant": FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
        "roof_wave1": ROOF_MODE_FLAT,
        "top_terminal_mode_flat_like": "PLAYABLE_TOP_ROOM",
        "top_terminal_mode_sloped": "TOP_FLOOR_ONLY",
        "terminal_profile_flat_like": TERMINAL_PROFILE_FULL_ROOM,
        "terminal_profile_sloped": TERMINAL_PROFILE_STAIR_HEAD,
        "opening_rhythm": "MORE_FREQUENT_MEDIUM_WIDE",
        "frontage_truth": "MULTI_BAY_GARAGE",
    },
    "warehouse": {
        "role": "WAREHOUSE",
        "floor_structure": "1_FLOOR_PLUS_ROOF",
        "rear_access_profile": REAR_ACCESS_PROFILE_SERVICE_DOOR,
        "frontage_variant": FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
        "roof_wave1": ROOF_MODE_FLAT,
        "top_terminal_mode_flat_like": "PLAYABLE_TOP_ROOM",
        "top_terminal_mode_sloped": "TOP_FLOOR_ONLY",
        "terminal_profile_flat_like": TERMINAL_PROFILE_FULL_ROOM,
        "terminal_profile_sloped": TERMINAL_PROFILE_STAIR_HEAD,
        "opening_rhythm": "FEWER_LARGER",
        "frontage_truth": "SINGLE_LOADING_BAY",
    },
}

_EXTERIOR_OWNER_POLICY_BRICK_BY_MATERIAL = "BRICK_BY_MATERIAL"
_EXTERIOR_OWNER_POLICY_LOWER_BRICK_UPPER_WXS = "LOWER_BRICK_UPPER_WXS"
_EXTERIOR_OWNER_POLICY_WXS_ONLY = "WXS_ONLY"
_EXTERIOR_OWNER_POLICY_BY_PRESET: dict[str, str] = {
    "townhouse": _EXTERIOR_OWNER_POLICY_BRICK_BY_MATERIAL,
    "house_small": _EXTERIOR_OWNER_POLICY_BRICK_BY_MATERIAL,
    "apartment_lowrise": _EXTERIOR_OWNER_POLICY_LOWER_BRICK_UPPER_WXS,
    "apartment_midrise": _EXTERIOR_OWNER_POLICY_LOWER_BRICK_UPPER_WXS,
    "wood_house": _EXTERIOR_OWNER_POLICY_WXS_ONLY,
    "wood_rowhouse": _EXTERIOR_OWNER_POLICY_WXS_ONLY,
    "motel": _EXTERIOR_OWNER_POLICY_WXS_ONLY,
    "market_hall": _EXTERIOR_OWNER_POLICY_WXS_ONLY,
    "hangar": _EXTERIOR_OWNER_POLICY_WXS_ONLY,
}


def _exterior_owner_policy_for_preset_id(preset_id: str) -> str:
    normalized = str(preset_id or "").strip().lower()
    return _EXTERIOR_OWNER_POLICY_BY_PRESET.get(
        normalized,
        _EXTERIOR_OWNER_POLICY_BRICK_BY_MATERIAL,
    )


def _exterior_owner_policy(spec) -> str:
    return _exterior_owner_policy_for_preset_id(getattr(spec, "preset_id", ""))


def _industrial_family_policy(spec) -> dict[str, str | bool] | None:
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    policy = _INDUSTRIAL_FAMILY_POLICY.get(preset_id)
    return dict(policy) if policy is not None else None


def _frontage_variant(spec) -> str:
    industrial_policy = _industrial_family_policy(spec)
    if industrial_policy is not None:
        return str(industrial_policy["frontage_variant"])
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    if preset_id == "hangar":
        return FRONTAGE_TYPE_HANGAR
    if preset_id == "shop_unit":
        return FRONTAGE_TYPE_STOREFRONT_SHOP
    if preset_id == "pharmacy":
        return FRONTAGE_TYPE_STOREFRONT_PHARMACY
    if preset_id == "clinic":
        return FRONTAGE_TYPE_STOREFRONT_CLINIC
    if preset_id == "wood_house":
        return FRONTAGE_TYPE_TIMBER_HOUSE
    if preset_id == "wood_rowhouse":
        return FRONTAGE_TYPE_TIMBER_ROWHOUSE
    if preset_id == "market_hall":
        return FRONTAGE_TYPE_MARKET_HALL
    if str(getattr(spec, "ground_floor_tactical_profile", "")).upper() == GROUND_FLOOR_STOREFRONT:
        return FRONTAGE_TYPE_STOREFRONT_GENERIC
    facade_family = _normalized_facade_family(
        getattr(spec, "facade_family", ""),
        facade_mode=getattr(spec, "facade_mode", None),
    )
    if facade_family in {"TIMBER_WARM", "TIMBER_WEATHERED", "PAINTED_WOOD"}:
        return FRONTAGE_TYPE_TIMBER_GENERIC
    return FRONTAGE_TYPE_GENERIC


_TOP_TERMINAL_PROFILE_DEFAULT = {
    "flat_like": TERMINAL_PROFILE_FULL_ROOM,
    "sloped": TERMINAL_PROFILE_FULL_ROOM,
}
_TOP_TERMINAL_PROFILE_BY_PRESET: dict[str, dict[str, str]] = {
    "wood_rowhouse": {
        "flat_like": TERMINAL_PROFILE_ATTIC_OPEN,
    },
    "market_hall": {
        "flat_like": TERMINAL_PROFILE_ATTIC_OPEN,
    },
}


def _is_flat_like_roof_mode(roof_mode: str) -> bool:
    return str(roof_mode).upper() in {ROOF_MODE_FLAT, ROOF_MODE_TERRACE}


def _uses_sloped_playable_attic(spec, *, roof_mode: str) -> bool:
    return (
        int(getattr(spec, "floor_count", 0) or 0) >= 2
        and str(roof_mode).upper() in {ROOF_MODE_GABLE, ROOF_MODE_SHED}
    )


def _top_terminal_family_policy_mode(spec, *, roof_mode: str) -> str:
    if _uses_sloped_playable_attic(spec, roof_mode=roof_mode):
        return "PLAYABLE_TOP_ROOM"
    mode_key = "flat_like" if _is_flat_like_roof_mode(roof_mode) else "sloped"
    industrial_policy = _industrial_family_policy(spec)
    if industrial_policy is not None:
        return str(industrial_policy[f"top_terminal_mode_{mode_key}"])
    return "PLAYABLE_TOP_ROOM" if mode_key == "flat_like" else "TOP_FLOOR_ONLY"


def _top_terminal_family_terminal_profile(spec, *, roof_mode: str) -> str:
    if _uses_sloped_playable_attic(spec, roof_mode=roof_mode):
        return TERMINAL_PROFILE_ATTIC_OPEN
    mode_key = "flat_like" if _is_flat_like_roof_mode(roof_mode) else "sloped"
    industrial_policy = _industrial_family_policy(spec)
    if industrial_policy is not None:
        return str(industrial_policy[f"terminal_profile_{mode_key}"])
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    policy = _TOP_TERMINAL_PROFILE_BY_PRESET.get(preset_id, _TOP_TERMINAL_PROFILE_DEFAULT)
    return str(policy[mode_key])


def _rear_access_family_policy_profile(spec) -> str:
    industrial_policy = _industrial_family_policy(spec)
    if industrial_policy is not None:
        return str(industrial_policy["rear_access_profile"])
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    if preset_id == "under_construction":
        return REAR_ACCESS_PROFILE_SHELL_ONLY
    frontage_variant = _frontage_variant(spec)
    if frontage_variant in {FRONTAGE_TYPE_HANGAR, FRONTAGE_TYPE_MARKET_HALL}:
        return REAR_ACCESS_PROFILE_NONE
    return REAR_ACCESS_PROFILE_SERVICE_DOOR


def _is_storefront_frontage(spec) -> bool:
    return _frontage_variant(spec).startswith("STOREFRONT")


def _is_hangar_frontage(spec) -> bool:
    return _frontage_variant(spec) == FRONTAGE_TYPE_HANGAR


def _is_timber_frontage(spec) -> bool:
    return _frontage_variant(spec).startswith("TIMBER")


def _is_industrial_frontage(spec) -> bool:
    return _frontage_variant(spec).startswith("INDUSTRIAL")


def _is_market_hall_frontage(spec) -> bool:
    return _frontage_variant(spec) == FRONTAGE_TYPE_MARKET_HALL


def _entry_package_center_x(spec, envelope) -> float:
    return float(envelope.door_offset_x)


def _front_entry_visible_opening_width(opening_width: float) -> float:
    trim_half = max(0.09, min(WINDOW_TRIM_WIDTH, float(opening_width) * 0.12))
    return float(opening_width) + trim_half * 2.15


def _front_entry_package_center_span(
    spec,
    *,
    envelope: FrontEntryEnvelope | None = None,
) -> tuple[float, float]:
    resolved_envelope = envelope if envelope is not None else _front_entry_envelope(spec)
    center_x = _entry_package_center_x(spec, resolved_envelope)
    span_width = _front_entry_visible_opening_width(resolved_envelope.door_width)
    return float(center_x), float(span_width)


def _resolve_front_entry_center_x(
    spec,
    *,
    door_width: float,
    preferred_center_x: float,
) -> float:
    resolved_center_x, _resolved_gap = _resolve_front_entry_center_against_stair(
        spec,
        door_width=float(door_width),
        preferred_center_x=float(preferred_center_x),
    )
    return float(resolved_center_x)


def _normalized_front_stoop_variant(spec) -> str:
    return str(getattr(spec, "front_stoop_variant", "ROUNDED") or "ROUNDED").strip().upper()


def _rounded_stair_width_growth(top_width: float, stair_run: float) -> float:
    clamped_top_width = max(0.0, float(top_width))
    clamped_stair_run = max(0.0, float(stair_run))
    return min(0.68, max(0.24, clamped_top_width * 0.16, clamped_stair_run * 0.18))


def _rounded_stair_nose_depth(stair_run: float) -> float:
    return min(0.16, max(0.06, max(0.0, float(stair_run)) * 0.08))


def _front_entry_package_support_profile(
    *,
    stoop_variant: str,
    landing_width: float,
    landing_depth: float,
    stair_run: float,
    step_count: int,
    threshold_z: float,
    landing_outer_edge_y: float,
    wall_face_y: float,
    outward_sign: float,
) -> dict[str, float]:
    sign = -1.0 if float(outward_sign) < 0.0 else 1.0
    support_half_width = max(0.0, float(landing_width) / 2)
    support_front_y = (
        float(landing_outer_edge_y) - sign * 0.18
        if float(landing_depth) > 0.0
        else float(wall_face_y) - sign * 0.18
    )
    support_base_z = max(0.0, float(threshold_z))
    threshold_y = float(landing_outer_edge_y) - sign * float(landing_depth)
    visible_front_y = float(landing_outer_edge_y)

    rounded_variant = (
        str(stoop_variant or "ROUNDED").upper() == "ROUNDED"
        and float(landing_depth) > 0.0
        and float(stair_run) > 0.0
        and int(step_count) > 0
    )
    if rounded_variant:
        rounded_top_width = float(landing_width) + 0.16
        rounded_base_width = rounded_top_width + _rounded_stair_width_growth(
            rounded_top_width,
            stair_run,
        )
        support_half_width = max(support_half_width, rounded_base_width / 2)
        visible_front_y = threshold_y + sign * (float(stair_run) + _rounded_stair_nose_depth(stair_run))
        support_offset = min(
            max(0.14, float(stair_run) * 0.18),
            max(0.16, float(stair_run) - 0.06),
        )
        support_target_y = threshold_y + sign * support_offset
        visible_margin_y = visible_front_y - sign * 0.04
        threshold_margin_y = threshold_y + sign * 0.04
        support_front_y = max(
            min(visible_margin_y, threshold_margin_y),
            min(max(visible_margin_y, threshold_margin_y), support_target_y),
        )
        if float(stair_run) > 1e-4:
            support_progress = max(
                0.0,
                min(1.0, abs(threshold_y - support_front_y) / float(stair_run)),
            )
            support_base_z = max(0.0, float(threshold_z) * (1.0 - support_progress))

    return {
        "support_half_width": float(support_half_width),
        "support_front_y": float(support_front_y),
        "visible_front_y": float(visible_front_y),
        "threshold_y": float(threshold_y),
        "support_base_z": float(support_base_z),
    }


def _entry_stoop_package_ledger(
    spec,
    *,
    envelope: FrontEntryEnvelope | None = None,
    facade_side: str = "front",
    package_center_x: float | None = None,
    opening_span: tuple[float, float] | None = None,
    stoop_variant: str | None = None,
) -> dict[str, float]:
    resolved_envelope = envelope if envelope is not None else _front_entry_envelope(spec)
    side_key = str(facade_side or "front").strip().lower()
    outward_sign = 1.0 if side_key == "back" else -1.0
    wall_face_y = spec.depth / 2 if outward_sign > 0.0 else -spec.depth / 2
    landing_outer_edge_y = (
        spec.depth / 2 + resolved_envelope.landing_depth - 0.04
        if outward_sign > 0.0
        else resolved_envelope.landing_front_y
    )
    resolved_center_x = (
        float(package_center_x)
        if package_center_x is not None
        else _entry_package_center_x(spec, resolved_envelope)
    )
    clip_left_x = -spec.width / 2
    clip_right_x = spec.width / 2
    if opening_span is not None:
        span_left_x = min(float(opening_span[0]), float(opening_span[1]))
        span_right_x = max(float(opening_span[0]), float(opening_span[1]))
        clip_left_x = max(clip_left_x, span_left_x)
        clip_right_x = min(clip_right_x, span_right_x)
    if clip_right_x - clip_left_x <= 1e-4:
        clip_left_x = -spec.width / 2
        clip_right_x = spec.width / 2
    resolved_center_x = min(max(resolved_center_x, clip_left_x), clip_right_x)

    if stoop_variant is None:
        default_variant = "STRAIGHT" if outward_sign > 0.0 else "ROUNDED"
        resolved_stoop_variant = str(
            getattr(spec, "rear_stoop_variant" if outward_sign > 0.0 else "front_stoop_variant", default_variant)
            or default_variant
        )
    else:
        resolved_stoop_variant = str(stoop_variant or "")
    support_profile = _front_entry_package_support_profile(
        stoop_variant=resolved_stoop_variant,
        landing_width=resolved_envelope.landing_width,
        landing_depth=resolved_envelope.landing_depth,
        stair_run=resolved_envelope.stair_run,
        step_count=resolved_envelope.step_count,
        threshold_z=resolved_envelope.threshold_z,
        landing_outer_edge_y=landing_outer_edge_y,
        wall_face_y=wall_face_y,
        outward_sign=outward_sign,
    )
    support_half_width = max(0.0, float(support_profile["support_half_width"]))
    desired_package_half = max(
        float(resolved_envelope.landing_width) / 2,
        support_half_width,
    )
    clip_half_width = max(
        0.0,
        min(resolved_center_x - clip_left_x, clip_right_x - resolved_center_x),
    )
    package_half_width = min(desired_package_half, clip_half_width)
    package_left_x = float(resolved_center_x - package_half_width)
    package_right_x = float(resolved_center_x + package_half_width)
    support_half_width = min(support_half_width, package_half_width)
    support_left_x = float(resolved_center_x - support_half_width)
    support_right_x = float(resolved_center_x + support_half_width)
    return {
        "center_x": float(resolved_center_x),
        "package_left_x": package_left_x,
        "package_right_x": package_right_x,
        "package_width": float(max(0.0, package_right_x - package_left_x)),
        "support_left_x": support_left_x,
        "support_right_x": support_right_x,
        "support_width": float(max(0.0, support_right_x - support_left_x)),
        "support_front_y": float(support_profile["support_front_y"]),
        "visible_front_y": float(support_profile["visible_front_y"]),
        "threshold_y": float(support_profile["threshold_y"]),
        "support_base_z": float(support_profile["support_base_z"]),
        "outward_sign": float(outward_sign),
    }


def _market_hall_support_window_side(spec) -> str:
    placement = str(getattr(getattr(spec, "stair_core", None), "placement", "")).upper()
    if placement == constants.STAIR_PLACEMENT_BACK_RIGHT:
        return "left"
    if placement == constants.STAIR_PLACEMENT_BACK_LEFT:
        return "right"
    return "back"


def _uses_wood_floor_material(spec) -> bool:
    return _is_timber_frontage(spec)


def _effective_door(spec):
    max_width = max(0.9, spec.width - DOOR_JAMB_MIN * 2)
    width = min(spec.door.width, max_width)
    min_offset = -spec.width / 2 + DOOR_JAMB_MIN + width / 2
    max_offset = spec.width / 2 - DOOR_JAMB_MIN - width / 2
    offset_x = min(max(spec.door.offset_x, min_offset), max_offset)
    variant = _frontage_variant(spec)
    if variant == FRONTAGE_TYPE_STOREFRONT_SHOP and max_offset > 0.0:
        sign = -1.0 if offset_x < -1e-4 else 1.0 if offset_x > 1e-4 else (
            -1.0 if _stable_unit_float(spec.seed, "storefront_shop_entry_side") < 0.5 else 1.0
        )
        minimum_bias = min(max_offset, max(0.82, width * 0.6, spec.width * 0.14))
        if abs(offset_x) < minimum_bias:
            offset_x = sign * minimum_bias
    elif variant in {
        FRONTAGE_TYPE_STOREFRONT_PHARMACY,
        FRONTAGE_TYPE_STOREFRONT_CLINIC,
        FRONTAGE_TYPE_MARKET_HALL,
    }:
        offset_x = 0.0
    offset_x = min(max(offset_x, min_offset), max_offset)
    return width, offset_x


def _effective_entrance_profile(spec) -> str:
    normalized = _normalized_entrance_profile(spec.entrance_profile)
    if normalized != ENTRANCE_FLUSH:
        return normalized
    if not bool(getattr(getattr(spec, "door", None), "enabled", True)):
        return ENTRANCE_FLUSH
    if str(getattr(spec, "preset_id", "")).lower() == "under_construction":
        return ENTRANCE_FLUSH
    frontage_variant = _frontage_variant(spec)
    if frontage_variant in {
        FRONTAGE_TYPE_STOREFRONT_SHOP,
        FRONTAGE_TYPE_STOREFRONT_PHARMACY,
        FRONTAGE_TYPE_STOREFRONT_CLINIC,
        FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
        FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
        FRONTAGE_TYPE_MARKET_HALL,
        FRONTAGE_TYPE_HANGAR,
    }:
        return ENTRANCE_FLUSH
    if spec.preset_id in {"apartment_midrise", "office_block"} or int(spec.floor_count) >= 3:
        return ENTRANCE_PODIUM_HIGH
    return ENTRANCE_STOOP_LOW


def _door_threshold_z(spec) -> float:
    entrance_profile = _effective_entrance_profile(spec)
    if entrance_profile == ENTRANCE_STOOP_LOW:
        return STOOP_LANDING_HEIGHT
    if entrance_profile == ENTRANCE_PODIUM_HIGH:
        return PODIUM_HEIGHT
    return 0.0


def _brick_story_count(spec) -> int:
    if spec is None or int(spec.floor_count) <= 0:
        return 0
    facade_mode = _normalized_facade_mode(getattr(spec, "facade_mode", "SPLIT"))
    if facade_mode == "UNIFORM_BRICK":
        return int(spec.floor_count)
    if facade_mode == "UNIFORM_FLAT":
        return 0
    if int(spec.floor_count) == 1:
        return 1
    second_story_roll = _stable_unit_float(
        spec.seed,
        "brick_second_story",
        spec.preset_id,
        _normalized_facade_family(spec.facade_family),
    )
    return min(int(spec.floor_count), 2 if second_story_roll < 0.62 else 1)


def _completed_facade_floor_count(spec) -> int:
    if spec is None:
        return 0
    floor_count = max(0, int(getattr(spec, "floor_count", 0)))
    if floor_count <= 0:
        return 0
    completion = _clamped_facade_completion(getattr(spec, "facade_completion", 1.0))
    return max(0, min(floor_count, int(math.floor(completion * floor_count + 0.5))))


def _is_panel_floor(spec, floor_index: int) -> bool:
    return floor_index >= _brick_story_count(spec)


def _is_office_window_profile(window_profile: str) -> bool:
    return window_profile in {WINDOW_PROFILE_OFFICE, WINDOW_PROFILE_OFFICE_BAND}


def _is_small_square_window_profile(window_profile: str) -> bool:
    return window_profile == WINDOW_PROFILE_SMALL_SQUARE


def _is_panoramic_window_profile(window_profile: str) -> bool:
    return window_profile == WINDOW_PROFILE_PANORAMIC


def _is_tall_narrow_window_profile(window_profile: str) -> bool:
    return window_profile == WINDOW_PROFILE_TALL_NARROW


def _is_multi_pane_window_profile(window_profile: str) -> bool:
    return window_profile == WINDOW_PROFILE_MULTI_PANE


def _is_residential_wide(window_profile: str) -> bool:
    return window_profile == WINDOW_PROFILE_RESIDENTIAL_WIDE


def _window_verticals(floor_height: float, window_profile: str):
    if _is_office_window_profile(window_profile):
        sill_h = min(0.9, max(0.72, floor_height * 0.28))
        window_h = min(1.04, max(0.82, floor_height * 0.31))
        top_h = max(0.52, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    if _is_panoramic_window_profile(window_profile):
        sill_h = min(0.25, max(0.15, floor_height * 0.07))
        window_h = min(2.2, max(1.8, floor_height * 0.68))
        top_h = max(0.3, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    if _is_tall_narrow_window_profile(window_profile):
        sill_h = min(0.94, max(0.82, floor_height * 0.3))
        window_h = min(1.18, max(1.08, floor_height * 0.39))
        top_h = max(0.34, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    if _is_small_square_window_profile(window_profile):
        sill_h = min(1.18, max(0.98, floor_height * 0.36))
        window_h = min(0.7, max(0.56, floor_height * 0.22))
        top_h = max(0.4, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    if _is_multi_pane_window_profile(window_profile):
        sill_h = min(0.88, max(0.7, floor_height * 0.24))
        window_h = min(1.38, max(1.08, floor_height * 0.36))
        top_h = max(0.42, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    if _is_residential_wide(window_profile):
        sill_h = min(0.84, max(0.68, floor_height * 0.24))
        window_h = min(1.18, max(0.92, floor_height * 0.33))
        top_h = max(0.44, floor_height - sill_h - window_h)
        return sill_h, window_h, top_h

    sill_h = min(WINDOW_SILL_MAX, max(WINDOW_SILL_MIN, floor_height * 0.28))
    window_h = min(WINDOW_HEIGHT_DEFAULT, max(1.2, floor_height - sill_h - WINDOW_TOP_MIN))
    top_h = max(WINDOW_TOP_MIN, floor_height - sill_h - window_h)
    return sill_h, window_h, top_h


def _front_entry_envelope(spec) -> FrontEntryEnvelope:
    door_width, door_offset_x = _effective_door(spec)
    door_offset_x = _resolve_front_entry_center_x(
        spec,
        door_width=door_width,
        preferred_center_x=door_offset_x,
    )
    entrance_profile = _effective_entrance_profile(spec)
    threshold_z = _door_threshold_z(spec)
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    door_enabled = bool(getattr(getattr(spec, "door", None), "enabled", True))
    frontage_variant = _frontage_variant(spec)
    storefront_frontage = frontage_variant.startswith("STOREFRONT")
    timber_frontage = frontage_variant.startswith("TIMBER")
    industrial_frontage = frontage_variant.startswith("INDUSTRIAL")
    market_hall_frontage = frontage_variant == FRONTAGE_TYPE_MARKET_HALL
    deferred_placeholder_frontage = preset_id == "motel"
    doorless_shell = preset_id == "under_construction" or not door_enabled
    front_stoop_variant = _normalized_front_stoop_variant(spec)

    def _center_available_width(side_inset: float) -> float:
        clamped_inset = max(0.0, float(side_inset))
        available_half_width = max(
            0.0,
            min(
                door_offset_x - (-spec.width / 2 + clamped_inset),
                (spec.width / 2 - clamped_inset) - door_offset_x,
            ),
        )
        return available_half_width * 2

    if storefront_frontage or market_hall_frontage:
        threshold_z = 0.0
    if doorless_shell:
        threshold_z = 0.0
    canopy_width = min(
        spec.width - 0.42,
        door_width + (2.1 if spec.ground_floor_tactical_profile == GROUND_FLOOR_OPEN_ENTRY else 1.55),
    )

    landing_width = min(spec.width - 0.36, door_width + 0.92)
    landing_depth = 0.0
    landing_height = 0.0
    step_count = 0
    stair_run = 0.0
    front_cut_depth = 0.78
    front_extent = spec.depth / 2 + GROUND_PLINTH_DEPTH
    frontage_width = landing_width
    recess_depth = 0.0
    cover_depth = 1.08 if spec.ground_floor_tactical_profile == GROUND_FLOOR_OPEN_ENTRY else 0.72
    canopy_brace_half_span = min(max(door_width * 0.62 + 0.38, landing_width / 2 + 0.18), spec.width / 2 - 0.26)

    if entrance_profile == ENTRANCE_STOOP_LOW:
        landing_width = min(spec.width - 0.42, door_width + 1.18)
        landing_depth = STOOP_DEPTH + 0.42
        landing_height = threshold_z
        step_count = STOOP_STEP_COUNT
        stair_run = max(1.06, landing_depth - 0.22)
    elif entrance_profile == ENTRANCE_PODIUM_HIGH:
        landing_width = min(spec.width - 0.28, door_width + 1.46)
        landing_depth = STOOP_DEPTH + 0.94
        landing_height = threshold_z
        step_count = PODIUM_STEP_COUNT
        stair_run = max(1.56, landing_depth - 0.18)

    if storefront_frontage:
        if frontage_variant == FRONTAGE_TYPE_STOREFRONT_SHOP:
            frontage_width = min(spec.width - 0.62, max(door_width + 1.84, spec.width * 0.34))
            recess_depth = min(1.14, max(0.82, spec.depth * 0.162))
            cover_depth = min(1.16, max(0.86, recess_depth + 0.1))
            canopy_width = min(spec.width - 0.36, max(door_width + 1.18, frontage_width * 0.74))
        elif frontage_variant == FRONTAGE_TYPE_STOREFRONT_PHARMACY:
            frontage_width = min(spec.width - 0.56, max(door_width + 2.18, spec.width * 0.42))
            recess_depth = min(0.96, max(0.72, spec.depth * 0.136))
            cover_depth = min(1.22, max(0.96, recess_depth + 0.22))
            canopy_width = min(spec.width - 0.24, max(frontage_width + 1.42, spec.width * 0.82))
        else:
            frontage_width = min(spec.width - 0.82, max(door_width + 1.72, spec.width * 0.32))
            recess_depth = 0.0
            cover_depth = min(0.44, max(0.22, spec.wall_thickness * 1.1))
            canopy_width = min(spec.width - 0.7, max(door_width + 0.42, frontage_width))
        front_cut_depth = max(front_cut_depth, recess_depth + 0.22)
        front_extent = max(front_extent, spec.depth / 2 + cover_depth + 0.14)
    elif timber_frontage:
        rowhouse_frontage = frontage_variant == FRONTAGE_TYPE_TIMBER_ROWHOUSE
        frontage_side_inset = 0.2 if rowhouse_frontage else 0.26
        believable_frontage_width = _center_available_width(frontage_side_inset)
        frontage_width_target = max(
            landing_width + (0.08 if rowhouse_frontage else 0.2),
            door_width + (2.34 if rowhouse_frontage else 2.18),
            spec.width * (0.84 if rowhouse_frontage else 0.58),
        )
        frontage_width_cap = min(spec.width - (0.22 if rowhouse_frontage else 0.3), believable_frontage_width)
        frontage_width_floor = min(frontage_width_cap, door_width + (1.12 if rowhouse_frontage else 1.02))
        frontage_width = max(frontage_width_floor, min(frontage_width_cap, frontage_width_target))
        landing_width = frontage_width
        landing_depth = min(
            1.72 if rowhouse_frontage else 2.18,
            max(
                1.42 if rowhouse_frontage else 1.86,
                spec.depth * (0.19 if rowhouse_frontage else 0.24),
            ),
        )
        landing_height = threshold_z
        if threshold_z > 0.0:
            step_count = max(step_count, PODIUM_STEP_COUNT if entrance_profile == ENTRANCE_PODIUM_HIGH else STOOP_STEP_COUNT)
            stair_run = max(0.98 if rowhouse_frontage else 1.12, landing_depth - (0.16 if rowhouse_frontage else 0.2))
        cover_depth = landing_depth + (0.18 if rowhouse_frontage else 0.32)
        canopy_width_cap = min(spec.width - 0.14, _center_available_width(0.14 if rowhouse_frontage else 0.18))
        canopy_width_target = max(
            door_width + (0.9 if rowhouse_frontage else 1.0),
            landing_width + (0.2 if rowhouse_frontage else 0.32),
        )
        canopy_width = min(canopy_width_cap, canopy_width_target)
    elif industrial_frontage:
        if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
            frontage_ratio = 0.87
            frontage_extra = 2.92
            recess_ratio = 0.15
            recess_min = 0.96
            recess_max = 1.22
            cover_min = 1.34
            cover_max = 1.62
            canopy_ratio = 0.92
            canopy_extra = 0.62
        else:
            frontage_ratio = 0.91
            frontage_extra = 3.36
            recess_ratio = 0.17
            recess_min = 1.08
            recess_max = 1.38
            cover_min = 1.48
            cover_max = 1.86
            canopy_ratio = 0.95
            canopy_extra = 0.78
        frontage_width = min(spec.width - 0.16, max(door_width + frontage_extra, spec.width * frontage_ratio))
        recess_depth = min(recess_max, max(recess_min, spec.depth * recess_ratio))
        cover_depth = min(cover_max, max(cover_min, recess_depth + 0.36))
        canopy_width = min(spec.width - 0.12, max(frontage_width + canopy_extra, spec.width * canopy_ratio))
        front_cut_depth = max(front_cut_depth, recess_depth + 0.36)
        front_extent = max(front_extent, spec.depth / 2 + cover_depth + 0.18)
    elif market_hall_frontage:
        frontage_width = min(spec.width - 0.1, max(door_width + 3.5, spec.width * 0.9))
        recess_depth = min(0.98, max(0.58, spec.depth * 0.1))
        cover_depth = min(2.34, max(1.68, recess_depth + 0.62, spec.depth * 0.27))
        canopy_width = min(spec.width - 0.04, max(frontage_width + 0.54, spec.width * 0.97))
        front_cut_depth = max(front_cut_depth, cover_depth + 0.24)
        front_extent = max(front_extent, spec.depth / 2 + cover_depth + 0.24)
    elif deferred_placeholder_frontage:
        frontage_width = min(spec.width - 0.28, max(door_width + 0.36, landing_width))
        recess_depth = 0.0
        cover_depth = min(cover_depth, max(0.0, spec.wall_thickness * 0.5))
        canopy_width = min(spec.width - 0.24, max(door_width + 0.34, frontage_width))
        canopy_brace_half_span = min(
            canopy_brace_half_span,
            max(door_width / 2 + 0.12, door_width * 0.52),
        )

    if doorless_shell:
        landing_width = 0.0
        landing_depth = 0.0
        landing_height = 0.0
        step_count = 0
        stair_run = 0.0
        front_cut_depth = 0.0
        frontage_width = 0.0
        recess_depth = 0.0
        cover_depth = 0.0
        canopy_width = 0.0
        canopy_brace_half_span = 0.0

    landing_center_y = -spec.depth / 2 - landing_depth / 2 + 0.04 if landing_depth > 0.0 else -spec.depth / 2 + 0.04
    landing_front_y = landing_center_y - landing_depth / 2
    if landing_depth > 0.0:
        front_cut_depth = max(front_cut_depth, landing_depth + stair_run + 0.14)
        front_extent = max(front_extent, spec.depth / 2 - 0.04 + landing_depth + stair_run + 0.06)
        if front_stoop_variant == "ROUNDED":
            rounded_nose_extra = _rounded_stair_nose_depth(stair_run)
            front_cut_depth = max(front_cut_depth, landing_depth + stair_run + rounded_nose_extra)
            front_extent = max(front_extent, spec.depth / 2 - 0.04 + landing_depth + stair_run + rounded_nose_extra)
    elif spec.ground_floor_tactical_profile == GROUND_FLOOR_OPEN_ENTRY:
        front_extent = max(front_extent, spec.depth / 2 + 1.08)
    plinth_clear_half = max(door_width / 2 + 0.78, landing_width / 2 + 0.34)
    if doorless_shell:
        plinth_clear_half = 0.0
    if preset_id not in _STAGE1_IDENTITY_RESET_PRESETS:
        canopy_brace_half_span = min(max(door_width * 0.62 + 0.38, landing_width / 2 + 0.18), spec.width / 2 - 0.26)
    entry_exclusion_half = min(
        spec.width / 2 - 0.2,
        max(plinth_clear_half, canopy_width / 2 + ENTRY_CLEARANCE_MARGIN, landing_width / 2 + ENTRY_CLEARANCE_MARGIN),
    )

    if storefront_frontage:
        entry_exclusion_half = min(
            spec.width / 2 - 0.18,
            max(
                entry_exclusion_half,
                frontage_width / 2 + 0.18,
                canopy_width / 2 + 0.16,
            ),
        )
    elif timber_frontage:
        entry_exclusion_half = min(
            spec.width / 2 - 0.14,
            max(
                entry_exclusion_half,
                landing_width / 2 + 0.28,
                canopy_width / 2 + 0.18,
            ),
        )
    elif industrial_frontage or market_hall_frontage:
        entry_exclusion_half = min(
            spec.width / 2 - 0.1,
            max(
                entry_exclusion_half,
                frontage_width / 2 + 0.18,
                canopy_width / 2 + 0.12,
            ),
        )
    elif deferred_placeholder_frontage:
        entry_exclusion_half = min(
            spec.width / 2 - 0.12,
            max(
                plinth_clear_half,
                door_width / 2 + ENTRY_CLEARANCE_MARGIN,
                landing_width / 2 + 0.12,
            ),
        )
    if doorless_shell:
        entry_exclusion_half = 0.0

    package_support = _front_entry_package_support_profile(
        stoop_variant=front_stoop_variant,
        landing_width=landing_width,
        landing_depth=landing_depth,
        stair_run=stair_run,
        step_count=step_count,
        threshold_z=threshold_z,
        landing_outer_edge_y=landing_front_y,
        wall_face_y=-spec.depth / 2,
        outward_sign=-1.0,
    )
    footprint_half_width = max(
        landing_width / 2,
        frontage_width / 2,
        (canopy_width / 2 if timber_frontage or industrial_frontage or market_hall_frontage else 0.0),
        float(package_support["support_half_width"]),
    )
    leftmost = min(-spec.width / 2, door_offset_x - footprint_half_width - 0.08)
    rightmost = max(spec.width / 2, door_offset_x + footprint_half_width + 0.08)
    return FrontEntryEnvelope(
        door_width=door_width,
        door_offset_x=door_offset_x,
        door_left=door_offset_x - door_width / 2,
        door_right=door_offset_x + door_width / 2,
        threshold_z=threshold_z,
        landing_width=landing_width,
        landing_depth=landing_depth,
        landing_height=landing_height,
        landing_front_y=landing_front_y,
        landing_center_y=landing_center_y,
        stair_run=stair_run,
        step_count=step_count,
        plinth_exclusion_left=door_offset_x - plinth_clear_half,
        plinth_exclusion_right=door_offset_x + plinth_clear_half,
        front_cut_depth=front_cut_depth,
        front_footprint_extent=front_extent,
        frontage_variant=frontage_variant,
        frontage_width=frontage_width,
        recess_depth=recess_depth,
        cover_depth=cover_depth,
        canopy_brace_half_span=canopy_brace_half_span,
        footprint_left_extent=abs(leftmost),
        footprint_right_extent=abs(rightmost),
        canopy_width=canopy_width,
        entry_exclusion_left=door_offset_x - entry_exclusion_half,
        entry_exclusion_right=door_offset_x + entry_exclusion_half,
    )


def _front_entry_visible_package_support(
    spec,
    *,
    envelope: FrontEntryEnvelope | None = None,
) -> dict[str, float]:
    resolved_envelope = envelope if envelope is not None else _front_entry_envelope(spec)
    package_support = _entry_stoop_package_ledger(
        spec,
        envelope=resolved_envelope,
        facade_side="front",
        stoop_variant=_normalized_front_stoop_variant(spec),
    )
    support_width = float(package_support["support_width"])
    return {
        "center_x": float(package_support["center_x"]),
        "left_x": float(package_support["support_left_x"]),
        "right_x": float(package_support["support_right_x"]),
        "visible_width": float(max(0.0, support_width)),
        "support_half_width": float(max(0.0, support_width) / 2),
        "support_front_y": float(package_support["support_front_y"]),
        "visible_front_y": float(package_support["visible_front_y"]),
        "threshold_y": float(package_support["threshold_y"]),
        "support_base_z": float(package_support["support_base_z"]),
        "package_left_x": float(package_support["package_left_x"]),
        "package_right_x": float(package_support["package_right_x"]),
        "package_width": float(package_support["package_width"]),
        "support_left_x": float(package_support["support_left_x"]),
        "support_right_x": float(package_support["support_right_x"]),
        "support_width": float(package_support["support_width"]),
    }


def _raised_entry_package(envelope: FrontEntryEnvelope) -> bool:
    return (
        float(envelope.threshold_z) > 1e-4
        and float(envelope.landing_depth) > 1e-4
        and int(envelope.step_count) > 0
    )


def entry_stoop_edit_applicability(spec) -> dict[str, dict[str, str | bool]]:
    envelope = _front_entry_envelope(spec)
    spatial_plan = _spatial_plan(spec)
    front_applicable = _raised_entry_package(envelope)
    rear_access = bool(spatial_plan.rear_access)

    front_reason = "" if front_applicable else "front entry resolves to FLUSH/zero stoop package"
    if not rear_access:
        rear_reason = "rear access is disabled by the resolved spatial plan"
    elif not front_applicable:
        rear_reason = "rear entry resolves to FLUSH/zero stoop package"
    else:
        rear_reason = ""

    return {
        "front": {
            "applicable": bool(front_applicable),
            "reason": front_reason,
        },
        "rear": {
            "applicable": bool(rear_access and front_applicable),
            "reason": rear_reason,
        },
    }


def _facade_floor_active(spec, floor_index: int) -> bool:
    return 0 <= int(floor_index) < _completed_facade_floor_count(spec)


def _wall_material(materials_map, facade_family: str, *, facade_mode: str | None = None):
    family = _normalized_facade_family(facade_family, facade_mode=facade_mode)
    key = f"wall_{family.lower()}"
    return materials_map.get(key, materials_map["wall"])


def _panel_material(materials_map, facade_family: str, *, facade_mode: str | None = None):
    family = _normalized_facade_family(facade_family, facade_mode=facade_mode)
    key = f"panel_{family.lower()}"
    return materials_map.get(key, _wall_material(materials_map, family, facade_mode=facade_mode))


def _trim_material(materials_map, facade_family: str, *, facade_mode: str | None = None):
    family = _normalized_facade_family(facade_family, facade_mode=facade_mode)
    key = f"trim_{family.lower()}"
    return materials_map.get(key, materials_map["trim"])


def _balcony_material(materials_map, facade_family: str, *, facade_mode: str | None = None):
    _family = _normalized_facade_family(facade_family, facade_mode=facade_mode)
    return materials_map["balcony"]


def _wall_material_for_floor(materials_map, spec, floor_index: int):
    facade_mode = _normalized_facade_mode(getattr(spec, "facade_mode", "SPLIT"))
    if facade_mode != "SPLIT":
        return _wall_material(materials_map, spec.facade_family, facade_mode=facade_mode)
    if _is_panel_floor(spec, floor_index):
        return _panel_material(materials_map, spec.facade_family, facade_mode=facade_mode)
    return _wall_material(materials_map, spec.facade_family, facade_mode=facade_mode)


def _window_ratio_for_face(spec, side_key: str, floor_index: int) -> float:
    ratio = max(0.0, min(1.0, float(spec.open_window_ratio)))
    if bool(getattr(spec, "window_policy_manual_override", False)):
        return ratio
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    frontage_variant = _frontage_variant(spec) if (_is_storefront_frontage(spec) or _is_industrial_frontage(spec) or _is_market_hall_frontage(spec)) else None
    if preset_id == "under_construction":
        if floor_index == 0:
            if side_key in {"front", "back"}:
                return min(0.78, max(0.56, ratio + 0.26))
            return min(0.68, max(0.44, ratio + 0.16))
        if side_key in {"front", "back"}:
            return min(0.84, max(0.62, ratio + 0.3))
        return min(0.72, max(0.48, ratio + 0.2))
    if _is_industrial_frontage(spec):
        if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
            if floor_index == 0:
                return min(0.42, max(0.22, ratio * (0.92 if side_key in {"front", "back"} else 0.58)))
            return min(0.28, max(0.12, ratio * (0.58 if side_key in {"front", "back"} else 0.42)))
        if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
            if floor_index == 0:
                return min(0.54, max(0.28, ratio * (1.08 if side_key in {"front", "back"} else 0.72)))
            return min(0.46, max(0.22, ratio * (1.0 if side_key in {"front", "back"} else 0.76)))
        return 0.0
    if _is_market_hall_frontage(spec):
        if floor_index == 0:
            if side_key == "front":
                return 0.0
            if side_key == "back":
                return min(0.38, max(0.18, ratio * 0.84))
            return min(0.24, max(0.1, ratio * 0.48))
        if side_key == "front":
            return min(0.42, max(0.24, ratio * 0.92))
        if side_key == "back":
            return min(0.48, max(0.28, ratio * 1.02))
        return min(0.3, max(0.14, ratio * 0.58))
    frontage_variant = _frontage_variant(spec) if _is_storefront_frontage(spec) else frontage_variant
    if _is_panel_floor(spec, floor_index):
        ratio = min(0.28, max(0.08, ratio * (0.52 if _is_office_window_profile(spec.window_profile) else 0.58)))
        if side_key in {"left", "right"}:
            ratio = min(ratio, 0.14 if _is_office_window_profile(spec.window_profile) else 0.12)
        if side_key in {"front", "back"}:
            ratio = max(ratio, 0.12)
        if side_key in _selected_balcony_sides(spec):
            ratio = min(0.32, ratio + 0.06)
        return ratio
    if floor_index == 0:
        if spec.ground_floor_tactical_profile == GROUND_FLOOR_DEFENSIVE_BASE:
            ratio = min(ratio, 0.48)
        elif spec.ground_floor_tactical_profile == GROUND_FLOOR_STOREFRONT:
            if side_key == "front":
                ratio = min(0.92, max(0.72, ratio + 0.16))
            elif frontage_variant == FRONTAGE_TYPE_STOREFRONT_PHARMACY:
                ratio = min(0.56, max(0.36, ratio + 0.14))
            else:
                ratio = min(0.62, max(0.28, ratio - 0.03))
        elif spec.ground_floor_tactical_profile == GROUND_FLOOR_OPEN_ENTRY:
            ratio = min(0.8, ratio + 0.08)
        else:
            ratio = min(0.76, ratio + 0.02)
        if side_key in {"left", "right"}:
            ratio = max(0.38, ratio - 0.05)
    else:
        if spec.tactical_facade_profile in {"OFFICE_COMBAT", "PANEL", "TENEMENT"}:
            ratio = min(0.82, ratio + 0.04)
        if spec.tactical_facade_profile == "BRUTALIST":
            ratio = max(0.5, ratio - 0.05)
        if _is_office_window_profile(spec.window_profile):
            ratio = min(0.84, ratio + 0.05)
        if side_key in _selected_balcony_sides(spec):
            ratio = min(0.84, ratio + 0.04)
        if frontage_variant is not None and side_key == "front":
            if frontage_variant == FRONTAGE_TYPE_STOREFRONT_CLINIC:
                ratio = min(ratio, 0.22)
            elif frontage_variant == FRONTAGE_TYPE_STOREFRONT_PHARMACY:
                ratio = min(ratio, 0.3)
            else:
                ratio = min(ratio, 0.38)
    return ratio


def _combat_open_window_bucket_targets(spec) -> dict[tuple[str, int], int]:
    requested_min = max(0, int(getattr(spec, "combat_open_window_min", 0)))
    if requested_min <= 0:
        return {}
    manual_override = bool(getattr(spec, "window_policy_manual_override", False))
    if not manual_override and spec.preset_id == "house_small" and int(spec.floor_count) == 1:
        return {}
    if not manual_override and _is_industrial_frontage(spec):
        return {}

    spatial_plan = _spatial_plan(spec)
    front_layout, back_layout, side_layout, masks = _facade_window_layouts(spec, spatial_plan)
    side_layouts = {
        "front": front_layout,
        "back": back_layout,
        "left": side_layout,
        "right": side_layout,
    }
    is_storefront = _is_storefront_frontage(spec)
    buckets: list[tuple[tuple[str, int], int]] = []
    for floor_index, floor_plan in enumerate(spatial_plan.floors):
        if not _facade_floor_active(spec, floor_index):
            continue
        if floor_index > 0 and not bool(getattr(floor_plan, "is_traversable", True)):
            continue
        for side_key in ("front", "back", "left", "right"):
            if _pilotis_open_side(spec, side_key, floor_index):
                continue
            if is_storefront and floor_index == 0:
                continue
            layout_count = int(side_layouts[side_key][0])
            usable_slots = max(0, layout_count - len(masks[side_key]))
            if usable_slots <= 0:
                continue
            buckets.append(((side_key, floor_index), usable_slots))

    if not buckets:
        return {}

    total_capacity = sum(capacity for _bucket_key, capacity in buckets)
    if total_capacity <= 0:
        return {}
    target_open = min(requested_min, total_capacity)
    if target_open <= 0:
        return {}

    targets: dict[tuple[str, int], int] = {}
    assigned = 0
    remainder_candidates: list[tuple[float, int, str, tuple[str, int], int]] = []
    for bucket_key, capacity in buckets:
        share = min(capacity, (target_open * capacity) // total_capacity)
        targets[bucket_key] = share
        assigned += share
        side_key, floor_index = bucket_key
        remainder_candidates.append(
            (
                _stable_unit_float(spec.seed, "combat_open_window_bucket_target", side_key, floor_index),
                int(floor_index),
                str(side_key),
                bucket_key,
                int(capacity),
            )
        )

    remainder = target_open - assigned
    if remainder > 0:
        for _score, _floor_index, _side_key, bucket_key, capacity in sorted(remainder_candidates):
            if remainder <= 0:
                break
            current = targets.get(bucket_key, 0)
            if current >= capacity:
                continue
            targets[bucket_key] = current + 1
            remainder -= 1

    return targets


def _window_open_score(spec, side_key: str, floor_index: int, slot_index: int, count: int) -> float:
    center = (count - 1) / 2
    score = _stable_unit_float(spec.seed, "window_open_rank", side_key, floor_index, slot_index)
    score += abs(slot_index - center) * (0.16 if side_key in {"front", "back"} else 0.22)
    if spec.tactical_facade_profile in {"OFFICE_COMBAT", "PANEL"}:
        score -= max(0.0, 0.08 - abs(slot_index - center) * 0.02)
    return score


def _select_balcony_access_slot(
    spec,
    side_key: str,
    floor_index: int,
    leader_idx: int,
    count: int,
    reserved: set[int],
    masked_slots: set[int],
) -> int | None:
    candidates = [
        idx
        for idx in (leader_idx - 1, leader_idx + 1, leader_idx - 2, leader_idx + 2)
        if 0 <= idx < count and idx not in reserved and idx not in masked_slots
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda idx: _window_open_score(spec, side_key, floor_index, idx, count),
    )


def _reserve_terrace_exit_opening(
    spec,
    *,
    spatial_plan,
    side_key: str,
    floor_index: int,
    count: int,
    masked_slots: set[int],
    planned_states: dict[int, str],
    protected_openings: dict[int, int],
    exit_already_assigned: bool,
    slot_intervals: tuple[tuple[int, float, float], ...] = (),
) -> tuple[bool, int | None]:
    if exit_already_assigned:
        return True, None
    transition_floor_index = getattr(spatial_plan, "transition_floor_index", None)
    if transition_floor_index is None or int(floor_index) != int(transition_floor_index):
        return False, None
    terrace_open_sides = set(getattr(spatial_plan, "terrace_open_sides", tuple()) or tuple())
    if side_key not in terrace_open_sides:
        return False, None
    if int(count) <= 0:
        return False, None

    usable_slots = [idx for idx in range(int(count)) if idx not in masked_slots]
    if not usable_slots:
        return False, None

    center = (int(count) - 1) / 2
    open_candidates = [
        idx
        for idx in usable_slots
        if planned_states.get(idx) == WINDOW_STATE_OPEN
    ]
    neutral_candidates = [
        idx
        for idx in usable_slots
        if planned_states.get(idx) not in {WINDOW_STATE_BALCONY, WINDOW_STATE_MASK, WINDOW_STATE_STAIR}
    ]
    candidates = open_candidates or neutral_candidates or usable_slots
    interval_by_idx = {
        int(slot_index): (float(slot_min), float(slot_max))
        for slot_index, slot_min, slot_max in slot_intervals
    }
    target_along = None
    if bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        metrics = _dogleg_metrics(spec)
        if side_key in {"front", "back"}:
            target_along = float(_core_arrival_opening_center_x(spec, metrics))
        elif side_key in {"left", "right"}:
            target_along = float(metrics.arrival_landing_y)
    selected_slot = min(
        candidates,
        key=lambda slot_index: (
            abs((((interval_by_idx.get(int(slot_index), (0.0, 0.0))[0] + interval_by_idx.get(int(slot_index), (0.0, 0.0))[1]) / 2.0) - target_along))
            if target_along is not None and int(slot_index) in interval_by_idx
            else abs(slot_index - center),
            abs(slot_index - center),
            slot_index,
        ),
    )

    planned_states[int(selected_slot)] = WINDOW_STATE_BALCONY
    protected_openings[int(selected_slot)] = int(selected_slot)
    return True, int(selected_slot)


def _selected_balcony_sides(spec) -> set[str]:
    balcony_mode = _normalized_balcony_mode(spec.balcony_mode)
    if balcony_mode == BALCONY_MODE_NONE or spec.floor_count < 2:
        return set()
    if _is_industrial_frontage(spec):
        return set()
    if spec.massing_profile == MASSING_PROFILE_BALCONY_FACE:
        primary = "front"
    else:
        primary = "front" if _stable_unit_float(spec.seed, "balcony_side") < 0.58 else "back"
    adjacent = _adjacent_exterior_sides(spec)
    if primary == "front" and "FRONT" in adjacent and "BACK" not in adjacent:
        primary = "back"
    elif primary == "back" and "BACK" in adjacent and "FRONT" not in adjacent:
        primary = "front"
    sides = {primary}
    dual_roll = _stable_unit_float(spec.seed, "balcony_dual_side")
    if balcony_mode == BALCONY_MODE_STRIP and spec.width >= 10.0 and dual_roll > 0.56:
        sides.add("back" if primary == "front" else "front")
    elif spec.tactical_facade_profile in {"OFFICE_COMBAT", "PANEL"} and spec.width >= 11.5 and dual_roll > 0.72:
        sides.add("back" if primary == "front" else "front")
    return sides


def _balcony_plans_for_side(
    spec,
    side_key: str,
    layout,
    masked_slots: set[int],
    *,
    allow_unselected_side: bool = False,
) -> list[BalconyPlan]:
    selected_sides = _selected_balcony_sides(spec)
    if side_key not in selected_sides and not allow_unselected_side:
        return []

    count = layout[0]
    available = [idx for idx in range(count) if idx not in masked_slots]
    if side_key == "front":
        entry = _front_entry_envelope(spec)
        available = [
            idx
            for idx, slot_min, slot_max in _slot_intervals(spec.width, layout[0], layout[1], layout[2])
            if idx in available and max(slot_min, entry.entry_exclusion_left) >= min(slot_max, entry.entry_exclusion_right)
        ]
    if not available:
        return []

    balcony_mode = _normalized_balcony_mode(spec.balcony_mode)
    center = (count - 1) / 2
    scored = sorted(
        available,
        key=lambda idx: abs(idx - center) * 0.34 + _stable_unit_float(spec.seed, "balcony_rank", side_key, idx),
    )
    desired = 1
    if balcony_mode == BALCONY_MODE_STRIP and len(available) >= 4 and spec.width >= 9.0:
        desired = 2 if spec.width >= 12.0 else 1
    elif balcony_mode == BALCONY_MODE_SHORT and spec.width >= 10.0 and spec.massing_profile == MASSING_PROFILE_BALCONY_FACE:
        desired = 2

    used: set[int] = set()
    plans: list[BalconyPlan] = []
    for idx in scored:
        if idx in used:
            continue
        style = "SHORT"
        members = [idx]
        wants_strip = balcony_mode == BALCONY_MODE_STRIP and len(available) >= 3 and (
            spec.preset_id != "house_small" or spec.floor_count >= 2
        )
        if wants_strip:
            span_target = 3 if spec.width >= 11.2 or _is_office_window_profile(spec.window_profile) else 2
            extension_order = [idx - 1, idx + 1, idx - 2, idx + 2]
            if _stable_unit_float(spec.seed, "balcony_strip_bias", side_key, idx) > 0.5:
                extension_order = [idx + 1, idx - 1, idx + 2, idx - 2]
            for candidate in extension_order:
                if candidate in available and candidate not in used:
                    members.append(candidate)
                if len(members) >= span_target:
                    break
            if len(members) >= 2:
                style = "STRIP"
        member_tuple = tuple(sorted(set(members)))
        plans.append(BalconyPlan(leader_idx=idx, member_indices=member_tuple, style=style))
        used.update(member_tuple)
        if len(plans) >= desired:
            break
    return plans


def _window_layout(length: float, preferred_count: int, min_width: float, max_width: float, min_pier: float):
    count = max(1, preferred_count)
    while count > 1:
        width = min(max_width, max(min_width, length / (count * 2.25)))
        pier = (length - count * width) / (count + 1)
        if pier >= min_pier:
            return count, width, pier
        count -= 1
    width = min(max_width, max(min_width, length * 0.22))
    pier = max(min_pier, (length - width) / 2)
    return 1, width, pier


def _facade_window_layouts(spec, spatial_plan):
    wall_t = spec.wall_thickness
    side_span = max(0.01, spec.depth - wall_t * 2.0)

    if _is_industrial_frontage(spec):
        frontage_variant = _frontage_variant(spec)
        if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
            front_layout = _window_layout(spec.width, max(1, int(round(spec.width / 9.4))), 0.78, 1.04, 1.14)
            back_layout = _window_layout(spec.width, max(1, int(round(spec.width / 8.2))), 0.72, 0.98, 1.12)
            side_layout = _window_layout(side_span, max(1, int(round(side_span / 8.8))), 1.06, 1.34, 1.06)
        else:
            front_layout = _window_layout(spec.width, max(1, int(round(spec.width / 10.8))), 0.8, 1.08, 1.24)
            back_layout = _window_layout(spec.width, max(1, int(round(spec.width / 9.2))), 0.72, 0.96, 1.18)
            side_layout = _window_layout(side_span, max(1, int(round(side_span / 9.0))), 1.08, 1.42, 1.12)
    elif _is_market_hall_frontage(spec):
        front_pref = 2 if spec.width < 13.4 else 3
        back_pref = 1 if spec.width < 14.6 else 2
        front_layout = _window_layout(spec.width, front_pref, 0.82, 1.14, 1.82)
        back_layout = _window_layout(spec.width, back_pref, 0.78, 1.02, 1.64)
        side_layout = _window_layout(side_span, 1, 0.72, 0.86, 1.42)
    elif _is_office_window_profile(spec.window_profile):
        front_pref = max(1, int(round(spec.width / 6.4)))
        back_pref = max(1, int(round(spec.width / 6.4)))
        side_pref = max(1, int(round(side_span / 8.0)))
        if spec.preset_id == "office_block" and int(spec.floor_count) >= 7:
            front_pref = min(front_pref, 2)
            back_pref = min(back_pref, 2)
            side_pref = 1
            if int(spec.floor_count) >= 8 and float(spec.width) >= 18.0:
                balcony_sides = _selected_balcony_sides(spec)
                if "front" not in balcony_sides:
                    front_pref = 1
                if "back" not in balcony_sides:
                    back_pref = 1
        front_layout = _window_layout(spec.width, front_pref, 1.95, 3.2, 0.56)
        back_layout = _window_layout(spec.width, back_pref, 1.95, 3.2, 0.56)
        side_layout = _window_layout(side_span, side_pref, 1.55, 2.6, 0.52)
    elif _is_panoramic_window_profile(spec.window_profile):
        front_pref = max(1, int(round(spec.width / 4.8)))
        back_pref = max(1, int(round(spec.width / 4.8)))
        side_pref = max(1, int(round(side_span / 5.1)))
        front_layout = _window_layout(spec.width, front_pref, 1.6, 2.4, 0.38)
        back_layout = _window_layout(spec.width, back_pref, 1.6, 2.4, 0.38)
        side_layout = _window_layout(side_span, side_pref, 1.35, 1.95, 0.34)
    elif _is_tall_narrow_window_profile(spec.window_profile):
        if str(getattr(spec, "preset_id", "")).lower() == "townhouse":
            front_pref = max(2, min(3, int(round(spec.width / 4.0))))
        else:
            front_pref = max(2, int(round(spec.width / 2.2)))
        back_pref = max(2, int(round(spec.width / 2.2)))
        side_pref = max(1, int(round(side_span / 2.5)))
        front_layout = _window_layout(spec.width, front_pref, 0.7, 1.0, 0.3)
        back_layout = _window_layout(spec.width, back_pref, 0.7, 1.0, 0.3)
        side_layout = _window_layout(side_span, side_pref, 0.65, 0.92, 0.28)
    elif _is_small_square_window_profile(spec.window_profile):
        front_pref = max(2, int(round(spec.width / 1.9)))
        back_pref = max(2, int(round(spec.width / 1.9)))
        side_pref = max(1, int(round(side_span / 2.05)))
        front_layout = _window_layout(spec.width, front_pref, 0.48, 0.62, 0.28)
        back_layout = _window_layout(spec.width, back_pref, 0.48, 0.62, 0.28)
        side_layout = _window_layout(side_span, side_pref, 0.46, 0.58, 0.26)
    elif _is_multi_pane_window_profile(spec.window_profile):
        front_pref = max(2, int(round(spec.width / 2.6)))
        back_pref = max(2, int(round(spec.width / 2.6)))
        side_pref = max(1, int(round(side_span / 3.0)))
        front_layout = _window_layout(spec.width, front_pref, 0.92, 1.3, 0.36)
        back_layout = _window_layout(spec.width, back_pref, 0.92, 1.3, 0.36)
        side_layout = _window_layout(side_span, side_pref, 0.82, 1.08, 0.3)
    elif _is_residential_wide(spec.window_profile):
        front_pref = max(2, int(round(spec.width / 3.6)))
        back_pref = max(2, int(round(spec.width / 3.6)))
        side_pref = max(1, int(round(side_span / 4.0)))
        front_layout = _window_layout(spec.width, front_pref, 1.45, 2.2, 0.42)
        back_layout = _window_layout(spec.width, back_pref, 1.45, 2.2, 0.42)
        side_layout = _window_layout(side_span, side_pref, 1.15, 1.85, 0.36)
    else:
        front_pref = max(2, int(round(spec.width / 2.8)))
        back_pref = max(2, int(round(spec.width / 2.8)))
        side_pref = max(1, int(round(side_span / 3.2)))
        front_layout = _window_layout(spec.width, front_pref, 0.95, 1.4, 0.38)
        back_layout = _window_layout(spec.width, back_pref, 0.95, 1.4, 0.38)
        side_layout = _window_layout(side_span, side_pref, 0.8, 1.1, 0.32)

    masks = _window_masks(spec, spatial_plan, front_layout, back_layout, side_layout)
    return front_layout, back_layout, side_layout, masks


def _slot_intervals(length: float, count: int, window_width: float, pier_width: float):
    slots = []
    start = -length / 2 + pier_width
    step = window_width + pier_width
    for idx in range(count):
        center = start + idx * step + window_width / 2
        slots.append((idx, center - window_width / 2, center + window_width / 2))
    return slots


def _merge_partition_keepout_spans(spans: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    normalized = sorted(
        (
            (min(float(start), float(end)), max(float(start), float(end)))
            for start, end in spans
            if max(float(start), float(end)) - min(float(start), float(end)) > 1e-4
        ),
        key=lambda item: item[0],
    )
    if not normalized:
        return tuple()
    merged: list[tuple[float, float]] = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1e-4:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return tuple((round(start, 4), round(end, 4)) for start, end in merged)


def _rear_entry_partition_keepout_span(
    spec,
    spatial_plan,
    *,
    face_length: float | None = None,
) -> tuple[float, float] | None:
    width = float(face_length if face_length is not None else spec.width)
    rear_opening_span = _rear_entry_opening_span(spec, spatial_plan, face_length=width)
    if rear_opening_span is None:
        return None
    rear_corridor_padding = max(0.08, float(spec.wall_thickness) / 2 + 0.06)
    return (
        round(float(rear_opening_span[0]) - rear_corridor_padding, 4),
        round(float(rear_opening_span[1]) + rear_corridor_padding, 4),
    )


def _office_partition_keepout_contract(
    spec,
    spatial_plan,
    *,
    face_length: float | None = None,
) -> dict[str, tuple[tuple[float, float], ...] | tuple[float, float] | None]:
    empty_contract: dict[str, tuple[tuple[float, float], ...] | tuple[float, float] | None] = {
        "window_approach_spans": tuple(),
        "balcony_access_spans": tuple(),
        "rear_corridor_span": None,
        "blocked_spans": tuple(),
    }
    if str(getattr(spec, "preset_id", "")).lower() != "office_block":
        return empty_contract
    width = float(face_length if face_length is not None else spec.width)
    if width <= 0.12:
        return empty_contract

    front_layout, back_layout, _side_layout, masks = _facade_window_layouts(spec, spatial_plan)
    approach_padding = max(0.16, float(spec.wall_thickness) * 0.72)
    balcony_padding = max(0.22, float(spec.wall_thickness) * 0.95)
    access_padding = max(0.14, float(spec.wall_thickness) * 0.6)

    window_keepouts_raw: list[tuple[float, float]] = []
    balcony_keepouts_raw: list[tuple[float, float]] = []
    for side_key, layout in (("front", front_layout), ("back", back_layout)):
        slot_intervals = _slot_intervals(width, layout[0], layout[1], layout[2])
        interval_by_idx = {
            int(slot_index): (float(slot_min), float(slot_max))
            for slot_index, slot_min, slot_max in slot_intervals
        }
        masked = set(masks[side_key])
        for slot_index, slot_min, slot_max in slot_intervals:
            if int(slot_index) in masked:
                continue
            window_keepouts_raw.append((float(slot_min) - approach_padding, float(slot_max) + approach_padding))

        balcony_plans = _balcony_plans_for_side(spec, side_key, layout, masks[side_key])
        reserved_access_slots: set[int] = set()
        for plan in balcony_plans:
            member_intervals = [interval_by_idx[idx] for idx in plan.member_indices if idx in interval_by_idx]
            if member_intervals:
                balcony_keepouts_raw.append(
                    (
                        min(item[0] for item in member_intervals) - balcony_padding,
                        max(item[1] for item in member_intervals) + balcony_padding,
                    )
                )
            for member_idx in plan.member_indices:
                for offset in (-1, 1):
                    candidate = int(member_idx) + offset
                    if candidate in reserved_access_slots or candidate in masked or candidate not in interval_by_idx:
                        continue
                    reserved_access_slots.add(candidate)
                    slot_min, slot_max = interval_by_idx[candidate]
                    balcony_keepouts_raw.append((slot_min - access_padding, slot_max + access_padding))

    window_keepouts = _merge_partition_keepout_spans(window_keepouts_raw)
    balcony_keepouts = _merge_partition_keepout_spans(balcony_keepouts_raw)
    rear_corridor_span = _rear_entry_partition_keepout_span(
        spec,
        spatial_plan,
        face_length=width,
    )

    merged_blocks_raw = [*window_keepouts, *balcony_keepouts]
    if rear_corridor_span is not None:
        merged_blocks_raw.append(rear_corridor_span)
    blocked_spans = _merge_partition_keepout_spans(merged_blocks_raw)
    return {
        "window_approach_spans": window_keepouts,
        "balcony_access_spans": balcony_keepouts,
        "rear_corridor_span": rear_corridor_span,
        "blocked_spans": blocked_spans,
    }


def _pilotis_column_positions(spec, side_key: str) -> list[tuple[float, float, float]]:
    if side_key in {"front", "back"}:
        length = max(0.01, float(spec.width))
    else:
        length = max(0.01, float(spec.depth) - float(spec.wall_thickness) * 2.0)

    market_hall_frontage = _is_market_hall_frontage(spec)
    column_width = max(float(spec.wall_thickness) * 1.15, 0.22)
    if market_hall_frontage:
        column_width = min(0.42, max(column_width, 0.32))
        min_bay = 2.48 if side_key == "front" else 2.18
        max_bay = 4.1 if side_key == "front" else 3.28
    else:
        column_width = min(0.34, max(column_width, 0.24))
        min_bay = 2.4
        max_bay = 3.8 if side_key in {"front", "back"} else 3.2

    edge_inset = max(column_width / 2 + 0.14, float(spec.wall_thickness) * 0.6)
    grid_min = -length / 2 + edge_inset
    grid_max = length / 2 - edge_inset
    if grid_max <= grid_min + 1e-4:
        half = min(length / 2, column_width / 2)
        return [(0.0, -half, half)]

    clear_span = grid_max - grid_min
    if market_hall_frontage:
        target_bay = min(max_bay, max(min_bay, length / (3.55 if side_key == "front" else 3.0)))
    else:
        target_bay = min(max_bay, max(min_bay, length / 3.2))
    bay_count = max(2, int(round(clear_span / max(min_bay, target_bay))))
    min_bays = max(2, int(math.ceil(clear_span / max_bay)))
    max_bays = max(2, int(math.floor(clear_span / min_bay)))
    bay_count = max(min_bays, min(max_bays, bay_count))
    if market_hall_frontage and side_key == "front":
        bay_count = max(3, bay_count)
    if not market_hall_frontage and side_key in {"left", "right"} and length < 7.2:
        bay_count = min(bay_count, 3)

    step = clear_span / max(1, bay_count)
    columns: list[tuple[float, float, float]] = []
    for index in range(bay_count + 1):
        center = grid_min + step * index
        span_start = max(-length / 2, center - column_width / 2)
        span_end = min(length / 2, center + column_width / 2)
        if columns and span_start <= columns[-1][2] + 0.04:
            continue
        columns.append(((span_start + span_end) / 2, span_start, span_end))

    if not columns:
        half = min(length / 2, column_width / 2)
        return [(0.0, -half, half)]
    return columns


def _solid_facade_spans(length: float, layout, masked_slots: set[int], *, opening_margin: float = 0.14) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    cursor = -length / 2
    for idx, slot_min, slot_max in _slot_intervals(length, layout[0], layout[1], layout[2]):
        if idx in masked_slots:
            continue
        opening_min = max(-length / 2, slot_min - opening_margin)
        opening_max = min(length / 2, slot_max + opening_margin)
        if opening_min > cursor + 1e-4:
            spans.append((cursor, opening_min))
        cursor = max(cursor, opening_max)
    if cursor < length / 2 - 1e-4:
        spans.append((cursor, length / 2))
    return [span for span in spans if span[1] - span[0] >= max(0.18, WALL_PIPE_WIDTH + 0.04)]


def _masked_slot_indices(length: float, layout, blocked_range: tuple[float, float] | None):
    if blocked_range is None:
        return set()

    count, window_width, pier_width = layout
    blocked_min = blocked_range[0] - WINDOW_BUFFER
    blocked_max = blocked_range[1] + WINDOW_BUFFER
    masked = set()
    for idx, slot_min, slot_max in _slot_intervals(length, count, window_width, pier_width):
        if slot_max > blocked_min and slot_min < blocked_max:
            masked.add(idx)
    return masked


def _window_masks(spec, spatial_plan, front_layout, back_layout, side_layout):
    masks = {"front": set(), "back": set(), "left": set(), "right": set()}
    if spatial_plan.rear_access:
        envelope = _front_entry_envelope(spec)
        masks["back"] = _masked_slot_indices(
            spec.width,
            back_layout,
            (envelope.entry_exclusion_left, envelope.entry_exclusion_right),
        )
    if not spec.stair_core.enabled:
        return masks

    x0, x1, y0, y1, _cx, _cy = _core_bounds(spec)
    adjacent = _adjacent_exterior_sides(spec)
    if "FRONT" in adjacent:
        masks["front"] = _masked_slot_indices(spec.width, front_layout, (x0, x1))
    if "BACK" in adjacent:
        masks["back"].update(_masked_slot_indices(spec.width, back_layout, (x0, x1)))
    if "LEFT" in adjacent:
        masks["left"] = _masked_slot_indices(spec.depth, side_layout, (y0, y1))
    if "RIGHT" in adjacent:
        masks["right"] = _masked_slot_indices(spec.depth, side_layout, (y0, y1))
    return masks


def _rear_entry_opening_contract(
    spec,
    spatial_plan,
    *,
    face_length: float | None = None,
) -> dict[str, float] | None:
    rear_access_profile = str(
        getattr(
            spatial_plan,
            "rear_access_profile",
            REAR_ACCESS_PROFILE_SERVICE_DOOR,
        )
    )
    if rear_access_profile == REAR_ACCESS_PROFILE_NONE or not spatial_plan.rear_access:
        return None
    length = float(face_length if face_length is not None else spec.width)
    if length <= 0.12:
        return None

    envelope = _front_entry_envelope(spec)
    edge_margin = max(0.02, min(0.08, float(spec.wall_thickness) * 0.3))
    max_opening_width = max(0.0, length - edge_margin * 2)
    if rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY:
        target_open_bay_width = max(4.4, min(length * 0.54, length - 1.2))
        opening_width = min(max_opening_width, max(0.0, target_open_bay_width))
    elif rear_access_profile == REAR_ACCESS_PROFILE_SHELL_ONLY:
        target_shell_width = max(1.6, min(length * 0.42, length - 0.86))
        opening_width = min(max_opening_width, max(0.0, target_shell_width))
    else:
        opening_width = min(max_opening_width, max(0.0, float(envelope.door_width) + 0.08))
    if opening_width <= 0.04:
        return None

    half_opening = opening_width / 2
    center_min = -length / 2 + edge_margin + half_opening
    center_max = length / 2 - edge_margin - half_opening
    if center_min > center_max + 1e-6:
        return None

    requested_center = float(envelope.door_offset_x)
    opening_center = min(max(requested_center, center_min), center_max)
    conflict_span = _rear_entry_stair_conflict_span(spec)
    if conflict_span is not None:
        conflict_min = float(conflict_span[0])
        conflict_max = float(conflict_span[1])
        span_min = opening_center - half_opening
        span_max = opening_center + half_opening
        if span_max > conflict_min and span_min < conflict_max:
            candidates: list[tuple[float, float]] = []
            left_center = conflict_min - half_opening - 0.01
            right_center = conflict_max + half_opening + 0.01
            if left_center >= center_min:
                candidates.append((abs(left_center - requested_center), left_center))
            if right_center <= center_max:
                candidates.append((abs(right_center - requested_center), right_center))
            if candidates:
                candidates.sort(key=lambda item: item[0])
                opening_center = candidates[0][1]

    span_left = float(opening_center - half_opening)
    span_right = float(opening_center + half_opening)
    span_width = max(0.0, span_right - span_left)
    opening_width = max(0.0, span_width - 0.04)
    return {
        "span_left": span_left,
        "span_right": span_right,
        "span_width": span_width,
        "opening_center_x": float((span_left + span_right) / 2),
        "opening_width": float(opening_width),
    }


def _rear_entry_opening_span(
    spec,
    spatial_plan,
    *,
    face_length: float | None = None,
) -> tuple[float, float] | None:
    contract = _rear_entry_opening_contract(
        spec,
        spatial_plan,
        face_length=face_length,
    )
    if contract is None:
        return None
    return (float(contract["span_left"]), float(contract["span_right"]))


def _stair_window_slots(spec, masks: dict[str, set[int]]) -> dict[str, int]:
    if (
        not spec.stair_core.enabled
        or spec.stair_window_mode != "EXPOSED"
        or spec.stair_core.placement == constants.STAIR_PLACEMENT_CENTER
    ):
        return {}

    slots = {}
    for side_key, masked in masks.items():
        ordered = sorted(masked)
        if ordered:
            slots[side_key] = ordered[len(ordered) // 2]
    return slots


def _balcony_lookup(plans: list[BalconyPlan]) -> tuple[dict[int, BalconyPlan], dict[int, int]]:
    leaders = {plan.leader_idx: plan for plan in plans}
    members = {}
    for plan in plans:
        for member_idx in plan.member_indices:
            members[member_idx] = plan.leader_idx
    return leaders, members


def _mandatory_ac_slot(spec, side_key: str, floor_index: int, count: int, masked_slots: set[int], blocked_slots: set[int]) -> int | None:
    if count <= 0:
        return None
    if side_key == "front" and spec.floor_count <= 2:
        return None
    if _is_office_window_profile(spec.window_profile):
        allowed_floors = {
            max(0, spec.floor_count // 2),
            spec.floor_count - 1,
        }
    elif spec.preset_id == "house_small":
        allowed_floors = {spec.floor_count - 1}
    else:
        allowed_floors = {
            min(spec.floor_count - 1, 1),
            spec.floor_count - 1,
        }
    if floor_index not in allowed_floors:
        return None
    eligible = [
        idx
        for idx in range(count)
        if idx not in masked_slots and idx not in blocked_slots
    ]
    if not eligible:
        return None
    if _is_office_window_profile(spec.window_profile):
        if side_key not in {"back", "left", "right"}:
            return None
        edge_order = sorted(eligible, key=lambda idx: abs(idx - (count - 1)))
        return edge_order[0]
    if side_key not in {"back", "left", "right"}:
        return None
    return eligible[len(eligible) // 2]


def _lower_facade_height_limit(spec) -> float:
    sill_h, _window_h, _top_h = _window_verticals(spec.floor_height, spec.window_profile)
    return max(0.28, sill_h - LOWER_FACADE_SIGHT_CLEARANCE)


def _planned_window_states(
    spec,
    side_key: str,
    floor_index: int,
    count: int,
    masked_slots: set[int],
    stair_slot: int | None,
    balcony_plans: list[BalconyPlan] | None,
) -> tuple[dict[int, str], dict[int, int]]:
    states: dict[int, str] = {}
    protected_openings: dict[int, int] = {}
    balcony_leaders, balcony_members = _balcony_lookup(balcony_plans or [])
    manual_office_override = bool(getattr(spec, "window_policy_manual_override", False)) and str(
        getattr(spec, "preset_id", "")
    ).lower() == "office_block"

    for idx in range(count):
        if idx in masked_slots:
            states[idx] = WINDOW_STATE_STAIR if stair_slot == idx else WINDOW_STATE_MASK
        elif floor_index > 0 and idx in balcony_members:
            if balcony_members[idx] == idx:
                states[idx] = WINDOW_STATE_BALCONY
            else:
                states[idx] = WINDOW_STATE_OPEN
                protected_openings[idx] = balcony_members[idx]

    usable_slots = [idx for idx in range(count) if idx not in masked_slots]
    if not usable_slots:
        return states, protected_openings

    reserved = set(states)
    for plan in balcony_leaders.values():
        access_idx = _select_balcony_access_slot(spec, side_key, floor_index, plan.leader_idx, count, reserved, masked_slots)
        if access_idx is not None:
            protected_openings[access_idx] = plan.leader_idx
            reserved.add(access_idx)

    forced_open = {
        idx
        for idx, state in states.items()
        if state in {WINDOW_STATE_OPEN, WINDOW_STATE_BALCONY}
    }
    forced_open.update(protected_openings)
    forced_open = {idx for idx in forced_open if idx in usable_slots}

    target_ratio = max(0.0, min(1.0, _window_ratio_for_face(spec, side_key, floor_index)))
    target_open_float = len(usable_slots) * target_ratio
    target_open = int(target_open_float)
    fractional_open = target_open_float - target_open
    if fractional_open > 1e-6 and _stable_unit_float(spec.seed, "window_quota_fraction", side_key, floor_index, count) < fractional_open:
        target_open += 1
    if _is_industrial_frontage(spec):
        frontage_variant = _frontage_variant(spec)
        if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
            target_open = max(
                len(forced_open),
                min(len(usable_slots), 2 if side_key in {"front", "back"} else 1),
            )
        elif frontage_variant != FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
            target_open = len(forced_open)
        else:
            target_open = max(
                len(forced_open),
                min(len(usable_slots), 2 if side_key in {"front", "back"} else 1),
            )
    if _is_panel_floor(spec, floor_index) and not manual_office_override:
        upper_cap = max(
            len(forced_open),
            1 if side_key in {"front", "back"} else 0,
            int(math.ceil(len(usable_slots) * 0.32)),
        )
        target_open = min(target_open, upper_cap)
    if _is_market_hall_frontage(spec):
        support_side = _market_hall_support_window_side(spec)
        if floor_index == 0:
            if side_key == "back":
                target_open = max(len(forced_open), min(len(usable_slots), 2))
            elif side_key == support_side:
                target_open = max(len(forced_open), min(len(usable_slots), 1))
            else:
                target_open = len(forced_open)
        elif side_key == support_side:
            target_open = max(len(forced_open), min(len(usable_slots), 2))
        elif side_key in {"front", "back"}:
            target_open = max(len(forced_open), min(len(usable_slots), 2))
        else:
            target_open = len(forced_open)
    if (
        manual_office_override
        and _is_panel_floor(spec, floor_index)
        and target_ratio >= 0.67
        and len(usable_slots) == 2
    ):
        target_open = max(target_open, 2)
    target_open = max(len(forced_open), min(len(usable_slots), target_open))
    if count <= 2 and side_key != "front":
        if manual_office_override and _is_panel_floor(spec, floor_index):
            pass
        elif _is_market_hall_frontage(spec) and floor_index > 0 and side_key == _market_hall_support_window_side(spec):
            pass
        else:
            target_open = min(target_open, len(forced_open))
    bucket_targets = _combat_open_window_bucket_targets(spec)
    bucket_target_open = int(bucket_targets.get((side_key, floor_index), 0))
    if bucket_target_open > 0:
        target_open = max(target_open, min(len(usable_slots), bucket_target_open))
    target_open = max(len(forced_open), min(len(usable_slots), target_open))

    remaining_candidates = [
        idx
        for idx in usable_slots
        if idx not in states and idx not in forced_open
    ]
    selected_open = set(forced_open)
    for idx in sorted(
        remaining_candidates,
        key=lambda slot_idx: _window_open_score(spec, side_key, floor_index, slot_idx, count),
    ):
        if len(selected_open) >= target_open:
            break
        selected_open.add(idx)

    for idx in usable_slots:
        if idx in states and states[idx] in {WINDOW_STATE_MASK, WINDOW_STATE_STAIR, WINDOW_STATE_BALCONY}:
            continue
        states[idx] = WINDOW_STATE_OPEN if idx in selected_open else WINDOW_STATE_CLOSED
    return states, protected_openings


def _balcony_floor_enabled(spec, floor_index: int) -> bool:
    if floor_index <= 0:
        return False
    transition_floor_index, _upper_shell_rect, _terrace_open_sides = _terrace_transition_contract(spec)
    if transition_floor_index is not None and int(floor_index) >= int(transition_floor_index):
        return False
    if _limited_upper_combat_variant(spec) and floor_index >= 2:
        return False
    if spec.preset_id == "office_block" or spec.window_profile == WINDOW_PROFILE_OFFICE_BAND:
        return floor_index % 2 == 1 or floor_index == spec.floor_count - 1
    return True


def _limited_upper_combat_variant(spec) -> bool:
    return (
        spec.floor_count >= 5
        and spec.preset_id in {"apartment_midrise", "office_block"}
        and _stable_unit_float(spec.seed, "limited_upper_combat", spec.preset_id) < 0.42
    )


def _side_shell_metrics(rect: tuple[float, float, float, float], side_key: str, wall_t: float) -> tuple[float, float]:
    x0, x1, y0, y1 = rect
    if side_key == "front":
        return max(0.01, x1 - x0), y0 + wall_t / 2
    if side_key == "back":
        return max(0.01, x1 - x0), y1 - wall_t / 2
    if side_key == "left":
        return max(0.01, y1 - y0 - wall_t * 2.0), x0 + wall_t / 2
    return max(0.01, y1 - y0 - wall_t * 2.0), x1 - wall_t / 2
