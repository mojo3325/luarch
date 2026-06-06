from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from . import constants, presets
from .generator import specs


_SUPPRESSED_PRESET_CALLBACKS: set[int] = set()
_SUPPRESSED_SELECTED_CALLBACKS: set[int] = set()
_SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS: set[int] = set()


def _preset_items(_self, _context):
    return presets.enum_items()


_ROOF_MODE_ITEMS_VISIBLE = tuple(
    (mode, mode.replace("_", " ").title(), mode)
    for mode in specs.SUPPORTED_ROOF_MODES
    if mode != specs.ROOF_MODE_TERRACE
)
_MASSING_PROFILE_ITEMS = (
    ("BOX", "Box", "Full-volume box massing"),
    ("BASE_HEAVY", "Base Heavy", "Heavier base-level silhouette"),
    ("TOP_SETBACK", "Top Setback", "Top-setback massing profile"),
    ("BALCONY_FACE", "Balcony Face", "Facade-forward balcony read"),
    ("PILOTIS", "Pilotis", "Raised pilotis base expression"),
)
_FACADE_FAMILY_ITEMS = tuple(
    (family, family.replace("_", " ").title(), family)
    for family in (
        *constants.SUPPORTED_SPLIT_FACADE_FAMILIES,
        *tuple(
            family for family in specs.SUPPORTED_FLAT_FACADE_FAMILIES if family not in constants.SUPPORTED_SPLIT_FACADE_FAMILIES
        ),
    )
)


_STOOP_VARIANT_ITEMS = (
    ("STRAIGHT", "Straight", "Straight rectangular stoop"),
    ("ROUNDED", "Rounded", "Rounded outer-edge stoop"),
)

_STAIR_CORE_VARIANT_ITEMS = (
    ("DEFAULT", "Default", "Current safe enclosed stair presentation"),
    ("OPEN", "Open", "Open-riser stair with a slimmer support read"),
)


def suppress_preset_callback(settings):
    pointer = int(settings.as_pointer())
    _SUPPRESSED_PRESET_CALLBACKS.add(pointer)
    return pointer


def resume_preset_callback(settings_or_pointer):
    pointer = int(settings_or_pointer if isinstance(settings_or_pointer, int) else settings_or_pointer.as_pointer())
    _SUPPRESSED_PRESET_CALLBACKS.discard(pointer)


def suppress_selected_callback(settings):
    pointer = int(settings.as_pointer())
    _SUPPRESSED_SELECTED_CALLBACKS.add(pointer)
    return pointer


def resume_selected_callback(settings_or_pointer):
    pointer = int(settings_or_pointer if isinstance(settings_or_pointer, int) else settings_or_pointer.as_pointer())
    _SUPPRESSED_SELECTED_CALLBACKS.discard(pointer)


def suppress_terrace_autofit_callback(settings):
    pointer = int(settings.as_pointer())
    _SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS.add(pointer)
    return pointer


def resume_terrace_autofit_callback(settings_or_pointer):
    pointer = int(settings_or_pointer if isinstance(settings_or_pointer, int) else settings_or_pointer.as_pointer())
    _SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS.discard(pointer)


def _apply_preset_defaults(settings):
    preset = presets.get_preset(getattr(settings, "preset_id", ""))
    defaults = preset.get("defaults", {})
    normalized_defaults = specs.normalized_payload_from_mapping(
        {
            **defaults,
            "preset_id": getattr(settings, "preset_id", ""),
            "seed": getattr(settings, "seed", 0),
        }
    )
    if hasattr(settings, "stair_core_variant"):
        settings.stair_core_variant = "DEFAULT"
    if hasattr(settings, "front_stoop_variant"):
        settings.front_stoop_variant = "ROUNDED"
    if hasattr(settings, "rear_stoop_variant"):
        settings.rear_stoop_variant = "STRAIGHT"
    presets.apply_payload(settings, normalized_defaults, preserve_keys=("seed",))


def _on_preset_changed(self, _context):
    if int(self.as_pointer()) in _SUPPRESSED_PRESET_CALLBACKS:
        return
    _apply_preset_defaults(self)


def _on_selected_building_changed(self, context):
    pointer = int(self.as_pointer())
    if pointer in _SUPPRESSED_SELECTED_CALLBACKS or pointer in _SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS:
        return
    if context is None or getattr(context, "scene", None) is None:
        return
    from .services import selected_building_tuning

    selected_building_tuning.on_selected_proxy_changed(context.scene)


def _on_selected_shape_changed(self, context):
    pointer = int(self.as_pointer())
    if pointer in _SUPPRESSED_SELECTED_CALLBACKS or pointer in _SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS:
        return
    if context is None or getattr(context, "scene", None) is None:
        return
    _sync_terrace_feasible_dimensions(self)
    from .services import selected_building_tuning

    selected_building_tuning.on_selected_proxy_changed(context.scene)


def _on_scene_building_changed(self, _context):
    pointer = int(self.as_pointer())
    if pointer in _SUPPRESSED_TERRACE_AUTOFIT_CALLBACKS:
        return
    _sync_terrace_feasible_dimensions(self)


def _sync_terrace_feasible_dimensions(settings) -> None:
    if str(getattr(settings, "massing_profile", "BOX") or "BOX").upper() != "TOP_SETBACK":
        return

    from .generator.building_layout import resolve_terrace_feasible_spec

    resolved = resolve_terrace_feasible_spec(
        specs.building_spec_from_settings(
            settings,
            building_id=None,
            origin=(0.0, 0.0, 0.0),
        )
    )
    width = float(getattr(resolved, "width", getattr(settings, "width", 0.0)))
    depth = float(getattr(resolved, "depth", getattr(settings, "depth", 0.0)))
    if abs(float(settings.width) - width) <= 1e-6 and abs(float(settings.depth) - depth) <= 1e-6:
        return

    pointer = suppress_terrace_autofit_callback(settings)
    try:
        if abs(float(settings.width) - width) > 1e-6:
            settings.width = width
        if abs(float(settings.depth) - depth) > 1e-6:
            settings.depth = depth
    finally:
        resume_terrace_autofit_callback(pointer)


def _terrace_enabled_get(self) -> bool:
    return str(getattr(self, "massing_profile", "BOX") or "BOX").upper() == "TOP_SETBACK"


def _terrace_enabled_set(self, value) -> None:
    current = str(getattr(self, "massing_profile", "BOX") or "BOX").upper()
    enabled = bool(value)
    if enabled and current != "TOP_SETBACK":
        self.massing_profile = "TOP_SETBACK"
        _sync_terrace_feasible_dimensions(self)
    elif enabled:
        _sync_terrace_feasible_dimensions(self)
    elif not enabled and current == "TOP_SETBACK":
        self.massing_profile = "BOX"


class TBG_PG_BuildingSettings(PropertyGroup):
    preset_id: EnumProperty(
        name="Preset",
        items=_preset_items,
        update=_on_preset_changed,
    )
    seed: IntProperty(name="Seed", default=1001, min=0)
    unit_mode: EnumProperty(name="Unit Mode", items=constants.UNIT_MODE_ITEMS, default=constants.UNIT_MODE_METERS)
    export_profile: EnumProperty(
        name="Export Profile",
        items=constants.EXPORT_PROFILE_ITEMS,
        default=constants.EDITABLE_ONLY,
    )
    width: FloatProperty(name="Width", default=8.0, min=2.0, soft_max=40.0, precision=3, update=_on_scene_building_changed)
    depth: FloatProperty(name="Depth", default=6.0, min=2.0, soft_max=40.0, precision=3, update=_on_scene_building_changed)
    floor_count: IntProperty(name="Floors", default=3, min=1, soft_max=20, update=_on_scene_building_changed)
    floor_height: FloatProperty(name="Floor Height", default=3.0, min=2.0, soft_max=6.0, precision=3)
    wall_thickness: FloatProperty(name="Wall Thickness", default=0.2, min=0.05, soft_max=1.0, precision=3)
    slab_thickness: FloatProperty(name="Slab Thickness", default=0.15, min=0.05, soft_max=0.6, precision=3)
    parapet_height: FloatProperty(name="Parapet Height", default=0.8, min=0.0, soft_max=2.0, precision=3)
    stair_core_enabled: BoolProperty(name="Enable Stair Core", default=True)
    stair_placement: EnumProperty(
        name="Stair Placement",
        items=constants.STAIR_PLACEMENT_ITEMS,
        default=constants.STAIR_PLACEMENT_FRONT_RIGHT,
    )
    core_width: FloatProperty(name="Core Width", default=2.0, min=1.2, soft_max=8.0, precision=3)
    core_depth: FloatProperty(name="Core Depth", default=3.8, min=1.6, soft_max=10.0, precision=3)
    stair_width: FloatProperty(name="Stair Width", default=1.8, min=0.8, soft_max=4.0, precision=3)
    step_count: IntProperty(name="Steps / Floor", default=16, min=4, soft_max=32)
    railing_enabled: BoolProperty(name="Railings", default=False)
    stair_core_variant: StringProperty(default="DEFAULT", options={"HIDDEN"})
    door_enabled: BoolProperty(name="Main Door", default=True)
    door_width: FloatProperty(name="Door Width", default=1.2, min=0.6, soft_max=3.0, precision=3)
    door_height: FloatProperty(name="Door Height", default=2.2, min=1.6, soft_max=4.0, precision=3)
    door_thickness: FloatProperty(name="Door Thickness", default=0.06, min=0.02, soft_max=0.2, precision=3)
    door_offset_x: FloatProperty(name="Door Offset X", default=-2.0, soft_min=-20.0, soft_max=20.0, precision=3)
    door_hinge: EnumProperty(name="Door Hinge", items=constants.HINGE_ITEMS, default=constants.HINGE_LEFT)
    front_stoop_variant: EnumProperty(name="Front Stoop", items=_STOOP_VARIANT_ITEMS, default="ROUNDED")
    rear_stoop_variant: EnumProperty(name="Rear Stoop", items=_STOOP_VARIANT_ITEMS, default="STRAIGHT")
    facade_family: StringProperty(default="LIGHT_BRICK", options={"HIDDEN"})
    facade_mode: StringProperty(default="SPLIT", options={"HIDDEN"})
    facade_band_profile: StringProperty(default="TRIM_DEFAULT", options={"HIDDEN"})
    window_profile: StringProperty(default="RESIDENTIAL", options={"HIDDEN"})
    entrance_profile: StringProperty(default="FLUSH", options={"HIDDEN"})
    balcony_mode: StringProperty(default="NONE", options={"HIDDEN"})
    open_window_ratio: FloatProperty(default=0.62, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    combat_open_window_min: IntProperty(default=1, min=0, soft_max=8, options={"HIDDEN"})
    wide_window_ratio: FloatProperty(default=0.2, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    tactical_facade_profile: StringProperty(default="DEFAULT", options={"HIDDEN"})
    terrace_enabled: BoolProperty(
        name="Terrace",
        description="Enable the terrace top floor module",
        get=_terrace_enabled_get,
        set=_terrace_enabled_set,
    )
    massing_profile: EnumProperty(name="Massing", items=_MASSING_PROFILE_ITEMS, default="BOX", update=_on_scene_building_changed)
    ground_floor_tactical_profile: StringProperty(default="MIXED_WINDOWS", options={"HIDDEN"})
    foundation_profile: StringProperty(default="PLAIN", options={"HIDDEN"})
    facade_ac_ratio: FloatProperty(default=0.0, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    door_profile: StringProperty(default="HINGED", options={"HIDDEN"})
    roof_mode: StringProperty(default="FLAT", options={"HIDDEN"})
    roof_prop_profile: StringProperty(default="NONE", options={"HIDDEN"})
    stair_window_mode: StringProperty(default="NONE", options={"HIDDEN"})
    service_profile: StringProperty(default="STANDARD", options={"HIDDEN"})
    facade_completion: FloatProperty(default=1.0, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    quick_export_directory: StringProperty(name="Quick Export Folder", subtype="DIR_PATH", default="")


class TBG_PG_SelectedBuildingSettings(PropertyGroup):
    preset_id: StringProperty(default="", options={"HIDDEN"})
    seed: IntProperty(default=0, min=0, options={"HIDDEN"})
    unit_mode: StringProperty(default=constants.UNIT_MODE_METERS, options={"HIDDEN"})
    export_profile: StringProperty(default=constants.EDITABLE_ONLY, options={"HIDDEN"})
    width: FloatProperty(name="Width", default=8.0, min=2.0, soft_max=40.0, precision=3, update=_on_selected_shape_changed)
    depth: FloatProperty(name="Depth", default=6.0, min=2.0, soft_max=40.0, precision=3, update=_on_selected_shape_changed)
    floor_count: IntProperty(name="Floors", default=3, min=1, soft_max=20, update=_on_selected_shape_changed)
    floor_height: FloatProperty(default=3.0, min=2.0, soft_max=6.0, precision=3, options={"HIDDEN"})
    wall_thickness: FloatProperty(default=0.2, min=0.05, soft_max=1.0, precision=3, options={"HIDDEN"})
    slab_thickness: FloatProperty(default=0.15, min=0.05, soft_max=0.6, precision=3, options={"HIDDEN"})
    parapet_height: FloatProperty(default=0.8, min=0.0, soft_max=2.0, precision=3, options={"HIDDEN"}, update=_on_selected_building_changed)
    stair_core_enabled: BoolProperty(default=True, options={"HIDDEN"})
    stair_placement: EnumProperty(
        name="Stair Placement",
        items=constants.STAIR_PLACEMENT_ITEMS,
        default=constants.STAIR_PLACEMENT_FRONT_RIGHT,
        update=_on_selected_building_changed,
    )
    core_width: FloatProperty(default=2.0, min=1.2, soft_max=8.0, precision=3, options={"HIDDEN"})
    core_depth: FloatProperty(default=3.8, min=1.6, soft_max=10.0, precision=3, options={"HIDDEN"})
    stair_width: FloatProperty(default=1.8, min=0.8, soft_max=4.0, precision=3, options={"HIDDEN"})
    step_count: IntProperty(default=16, min=4, soft_max=32, options={"HIDDEN"})
    railing_enabled: BoolProperty(name="Railings", default=False, update=_on_selected_building_changed)
    stair_core_variant: EnumProperty(
        name="Stair Variant",
        items=_STAIR_CORE_VARIANT_ITEMS,
        default="DEFAULT",
        update=_on_selected_building_changed,
    )
    door_enabled: BoolProperty(default=True, options={"HIDDEN"})
    door_width: FloatProperty(default=1.2, min=0.6, soft_max=3.0, precision=3, options={"HIDDEN"})
    door_height: FloatProperty(default=2.2, min=1.6, soft_max=4.0, precision=3, options={"HIDDEN"})
    door_thickness: FloatProperty(default=0.06, min=0.02, soft_max=0.2, precision=3, options={"HIDDEN"})
    door_offset_x: FloatProperty(default=-2.0, soft_min=-20.0, soft_max=20.0, precision=3, options={"HIDDEN"})
    door_hinge: EnumProperty(
        name="Door Hinge",
        items=constants.HINGE_ITEMS,
        default=constants.HINGE_LEFT,
        update=_on_selected_building_changed,
    )
    front_stoop_variant: EnumProperty(
        name="Front Stoop",
        items=_STOOP_VARIANT_ITEMS,
        default="ROUNDED",
        update=_on_selected_building_changed,
    )
    rear_stoop_variant: EnumProperty(
        name="Rear Stoop",
        items=_STOOP_VARIANT_ITEMS,
        default="STRAIGHT",
        update=_on_selected_building_changed,
    )
    facade_family: EnumProperty(
        name="Facade Family",
        items=_FACADE_FAMILY_ITEMS,
        default="LIGHT_BRICK",
        update=_on_selected_building_changed,
    )
    facade_mode: StringProperty(default="SPLIT", options={"HIDDEN"})
    facade_band_profile: StringProperty(default="TRIM_DEFAULT", options={"HIDDEN"})
    window_profile: StringProperty(default="RESIDENTIAL", options={"HIDDEN"})
    entrance_profile: StringProperty(default="FLUSH", options={"HIDDEN"})
    balcony_mode: StringProperty(default="NONE", options={"HIDDEN"})
    open_window_ratio: FloatProperty(
        name="Open Window Ratio",
        default=0.62,
        min=0.0,
        max=1.0,
        precision=3,
        subtype="FACTOR",
        update=_on_selected_building_changed,
    )
    combat_open_window_min: IntProperty(
        name="Minimum Open Windows",
        default=1,
        min=0,
        soft_max=8,
        update=_on_selected_building_changed,
    )
    wide_window_ratio: FloatProperty(default=0.2, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    tactical_facade_profile: StringProperty(default="DEFAULT", options={"HIDDEN"})
    terrace_enabled: BoolProperty(
        name="Terrace",
        description="Enable the terrace top floor module",
        get=_terrace_enabled_get,
        set=_terrace_enabled_set,
    )
    massing_profile: EnumProperty(
        name="Massing",
        items=_MASSING_PROFILE_ITEMS,
        default="BOX",
        update=_on_selected_shape_changed,
    )
    ground_floor_tactical_profile: StringProperty(default="MIXED_WINDOWS", options={"HIDDEN"})
    foundation_profile: StringProperty(default="PLAIN", options={"HIDDEN"})
    facade_ac_ratio: FloatProperty(default=0.0, min=0.0, max=1.0, precision=3, options={"HIDDEN"})
    door_profile: StringProperty(default="HINGED", options={"HIDDEN"})
    roof_mode: EnumProperty(
        name="Roof",
        items=_ROOF_MODE_ITEMS_VISIBLE,
        default="FLAT",
        update=_on_selected_building_changed,
    )
    roof_prop_profile: StringProperty(default="NONE", options={"HIDDEN"})
    stair_window_mode: StringProperty(default="NONE", options={"HIDDEN"})
    service_profile: StringProperty(default="STANDARD", options={"HIDDEN"})
    facade_completion: FloatProperty(default=1.0, min=0.0, max=1.0, precision=3, options={"HIDDEN"})


class TBG_PG_BlockSettings(PropertyGroup):
    layout_mode: EnumProperty(name="Layout", items=constants.LAYOUT_ITEMS, default=constants.LAYOUT_GRID)
    lot_type: EnumProperty(
        name="Lot Type",
        items=constants.BLOCK_LOT_TYPE_ITEMS,
        default=constants.BLOCK_LOT_TYPE_ANY,
    )
    rows: IntProperty(name="Rows", default=2, min=1, soft_max=20)
    columns: IntProperty(name="Columns", default=2, min=1, soft_max=20)
    origin_x: FloatProperty(name="Origin X", default=48.0, soft_min=-500.0, soft_max=500.0, precision=3)
    origin_y: FloatProperty(name="Origin Y", default=0.0, soft_min=-500.0, soft_max=500.0, precision=3)
    origin_z: FloatProperty(name="Origin Z", default=0.0, soft_min=-500.0, soft_max=500.0, precision=3)
    spacing_x: FloatProperty(name="Spacing X", default=16.0, min=1.0, soft_max=100.0, precision=3)
    spacing_y: FloatProperty(name="Spacing Y", default=16.0, min=1.0, soft_max=100.0, precision=3)
    seed: IntProperty(name="Block Seed", default=5001, min=0)
    allowed_presets: StringProperty(
        name="Allowed Presets",
        default="",
        description="Comma-separated preset ids used by the block generator; empty uses the full eligible lot-type pool",
    )


def register_scene_properties():
    bpy.types.Scene.tbg_building = PointerProperty(type=TBG_PG_BuildingSettings)
    bpy.types.Scene.tbg_selected_building = PointerProperty(type=TBG_PG_SelectedBuildingSettings)
    bpy.types.Scene.tbg_selected_root_bound = BoolProperty(default=False, options={"HIDDEN"})
    bpy.types.Scene.tbg_selected_root_name = StringProperty(default="", options={"HIDDEN"})
    bpy.types.Scene.tbg_selected_root_building_id = StringProperty(default="", options={"HIDDEN"})
    bpy.types.Scene.tbg_selected_root_status = StringProperty(default="No TBG building selected.", options={"HIDDEN"})
    bpy.types.Scene.tbg_block = PointerProperty(type=TBG_PG_BlockSettings)


def unregister_scene_properties():
    if hasattr(bpy.types.Scene, "tbg_block"):
        del bpy.types.Scene.tbg_block
    if hasattr(bpy.types.Scene, "tbg_selected_root_status"):
        del bpy.types.Scene.tbg_selected_root_status
    if hasattr(bpy.types.Scene, "tbg_selected_root_building_id"):
        del bpy.types.Scene.tbg_selected_root_building_id
    if hasattr(bpy.types.Scene, "tbg_selected_root_name"):
        del bpy.types.Scene.tbg_selected_root_name
    if hasattr(bpy.types.Scene, "tbg_selected_root_bound"):
        del bpy.types.Scene.tbg_selected_root_bound
    if hasattr(bpy.types.Scene, "tbg_selected_building"):
        del bpy.types.Scene.tbg_selected_building
    if hasattr(bpy.types.Scene, "tbg_building"):
        del bpy.types.Scene.tbg_building
