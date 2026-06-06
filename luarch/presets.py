from __future__ import annotations

import json
import random
from pathlib import Path


_PRESETS: list[dict] = []
_PRESETS_BY_ID: dict[str, dict] = {}
_ENUM_ITEMS: list[tuple[str, str, str]] = []
_BLOCK_LOT_TYPE_KEY = "block_lot_type"
_HIDDEN_ENUM_PRESET_IDS = frozenset({"wood_rowhouse"})
# Stage 5 late requalification reviewed the corrective families and reopened none:
# single-building proof exists for several families, but representative block-smoke proof
# is still missing, so the rollout gate remains intentionally conservative.
MANUAL_ONLY_BLOCK_IDS = frozenset({
    "hangar",
    "market_hall",
    "motel",
    "under_construction",
    "warehouse",
})
PROOF_LOCKED_BLOCK_IDS = frozenset({
    "clinic",
    "depot",
    "pharmacy",
    "shop_unit",
    "utility_block",
    "wood_house",
    "wood_rowhouse",
})
_BLOCK_PAYLOAD_CLAMPS = {
    "apartment_midrise": {"floor_count": 5},
    "office_block": {"floor_count": 6, "width": 14.8, "depth": 11.0},
}


def _preset_path() -> Path:
    return Path(__file__).resolve().parent / "presets" / "buildings.json"


def ensure_loaded(force: bool = False) -> list[dict]:
    global _PRESETS, _PRESETS_BY_ID, _ENUM_ITEMS
    if _PRESETS and not force:
        return _PRESETS

    data = json.loads(_preset_path().read_text(encoding="utf-8"))
    _PRESETS = data.get("presets", [])
    _PRESETS_BY_ID = {preset["id"]: preset for preset in _PRESETS}
    enum_items: list[tuple[str, str, str]] = []
    for preset in _PRESETS:
        preset_id = preset["id"]
        if preset_id in _HIDDEN_ENUM_PRESET_IDS:
            continue
        label = preset.get("label", preset_id)
        description = preset.get("description", label)
        enum_items.append((preset_id, label, description))
    _ENUM_ITEMS = enum_items
    return _PRESETS


def enum_items() -> list[tuple[str, str, str]]:
    ensure_loaded()
    return list(_ENUM_ITEMS)


def all_ids() -> list[str]:
    ensure_loaded()
    return [preset["id"] for preset in _PRESETS]


def get_preset(preset_id: str) -> dict:
    ensure_loaded()
    return dict(_PRESETS_BY_ID.get(preset_id, _PRESETS[0] if _PRESETS else {}))


def preset_block_lot_type(preset_id: str) -> str:
    preset = get_preset(preset_id)
    return str(preset.get(_BLOCK_LOT_TYPE_KEY, "")).upper()


def _corrective_wave_block_allowed(preset_id: str) -> bool:
    return preset_id not in MANUAL_ONLY_BLOCK_IDS and preset_id not in PROOF_LOCKED_BLOCK_IDS


def block_eligible_ids(lot_type: str = "ANY") -> list[str]:
    ensure_loaded()
    target = str(lot_type or "ANY").upper()
    eligible: list[str] = []
    for preset in _PRESETS:
        preset_id = str(preset["id"])
        preset_lot_type = str(preset.get(_BLOCK_LOT_TYPE_KEY, "")).upper()
        if not preset_lot_type:
            continue
        if target != "ANY" and preset_lot_type != target:
            continue
        if not _corrective_wave_block_allowed(preset_id):
            continue
        eligible.append(preset_id)
    return eligible


def _weighted_option(rng: random.Random, options: list[dict]) -> dict:
    if not options:
        return {}
    total = sum(max(float(opt.get("weight", 0.0)), 0.0) for opt in options)
    if total <= 0.0:
        return dict(options[0])

    point = rng.uniform(0.0, total)
    acc = 0.0
    for option in options:
        acc += max(float(option.get("weight", 0.0)), 0.0)
        if point <= acc:
            return dict(option)
    return dict(options[-1])


def _choose_weighted(rng: random.Random, options: list[dict]):
    return _weighted_option(rng, options).get("value")


def _choose_weighted_mapping(rng: random.Random, options: list[dict]) -> dict:
    return _weighted_option(rng, options)


def _clamp_block_payload(payload: dict) -> dict:
    compacted = dict(payload)
    for key, clamp_value in _BLOCK_PAYLOAD_CLAMPS.get(str(compacted.get("preset_id", "")), {}).items():
        if key not in compacted:
            continue
        value = compacted[key]
        if isinstance(clamp_value, int):
            compacted[key] = min(int(value), int(clamp_value))
        elif isinstance(clamp_value, float):
            compacted[key] = min(float(value), float(clamp_value))
        else:
            compacted[key] = clamp_value
    return compacted


def _apply_payload_values(settings, payload: dict, *, exclude_keys: set[str] | None = None):
    excluded = exclude_keys or set()
    ordered_keys = list(payload.keys())
    facade_pair = [key for key in ("facade_mode", "facade_family") if key in payload and key not in excluded]
    if facade_pair:
        ordered_keys = [key for key in ordered_keys if key not in {"facade_mode", "facade_family"}]
        ordered_keys.extend([key for key in ("facade_mode", "facade_family") if key in facade_pair])
    for key in ordered_keys:
        value = payload[key]
        if key in excluded:
            continue
        if hasattr(settings, key):
            setattr(settings, key, value)


def _office_block_budget_clamp(payload: dict) -> dict:
    clamped = dict(payload)
    floor_count = int(clamped.get("floor_count", 0))
    width = float(clamped.get("width", 0.0))
    depth = float(clamped.get("depth", 0.0))
    balcony_mode = str(clamped.get("balcony_mode", "")).upper()
    strip_balcony = balcony_mode == "STRIP"
    massing_profile = str(clamped.get("massing_profile", "")).upper()
    facade_mode = str(clamped.get("facade_mode", "")).upper()
    facade_band_profile = str(clamped.get("facade_band_profile", "")).upper()
    envelope_area = width * depth

    if strip_balcony:
        clamped["balcony_mode"] = "SHORT"
    if floor_count >= 6 and (strip_balcony or massing_profile == "BASE_HEAVY" or envelope_area >= 140.0):
        clamped["floor_count"] = 5
        floor_count = 5
    elif floor_count >= 7:
        clamped["floor_count"] = 6
        floor_count = 6
    if floor_count >= 5 and facade_mode == "UNIFORM_BRICK":
        clamped["facade_mode"] = "SPLIT"
    if floor_count >= 5 and facade_band_profile == "BRICK_REVEAL":
        clamped["facade_band_profile"] = "TRIM_DEFAULT"
    if float(clamped.get("open_window_ratio", 0.0)) > 0.34:
        clamped["open_window_ratio"] = 0.34
    if float(clamped.get("wide_window_ratio", 0.0)) > 0.44:
        clamped["wide_window_ratio"] = 0.44
    return clamped


def clamp_invalid_risk_payload(payload: dict) -> dict:
    compacted = dict(payload)
    preset_id = str(compacted.get("preset_id", "")).lower()
    if preset_id == "office_block":
        compacted = _office_block_budget_clamp(compacted)
    return compacted


def build_randomized_payload(preset_id: str, seed: int) -> dict:
    preset = get_preset(preset_id)
    payload = dict(preset.get("defaults", {}))
    payload["preset_id"] = preset_id
    payload["seed"] = int(seed)

    rng = random.Random(int(seed))
    active_ranges = dict(preset.get("ranges", {}))
    archetypes = list(preset.get("archetypes", []))
    if archetypes:
        active_archetype = _choose_weighted_mapping(rng, archetypes)
        payload.update(active_archetype.get("defaults", {}))
        active_ranges.update(active_archetype.get("ranges", {}))

    for key, rule in active_ranges.items():
        if isinstance(rule, list) and len(rule) == 2 and all(isinstance(v, int) for v in rule):
            payload[key] = rng.randint(int(rule[0]), int(rule[1]))
        elif isinstance(rule, list) and len(rule) == 2 and all(isinstance(v, (int, float)) for v in rule):
            payload[key] = round(rng.uniform(float(rule[0]), float(rule[1])), 3)
        elif isinstance(rule, list) and rule:
            payload[key] = rng.choice(rule)
        elif isinstance(rule, dict) and "options" in rule:
            payload[key] = _choose_weighted(rng, list(rule["options"]))
    return clamp_invalid_risk_payload(payload)


def build_block_payload(preset_id: str, seed: int) -> dict:
    return _clamp_block_payload(build_randomized_payload(preset_id, seed))


def apply_payload(
    settings,
    payload: dict,
    *,
    include_preset_id: bool = False,
    preserve_keys: tuple[str, ...] = (),
):
    preserved_values = {
        key: getattr(settings, key)
        for key in preserve_keys
        if hasattr(settings, key)
    }
    excluded = set(preserve_keys)
    if not include_preset_id:
        excluded.add("preset_id")
    _apply_payload_values(settings, payload, exclude_keys=excluded)
    for key, value in preserved_values.items():
        setattr(settings, key, value)
