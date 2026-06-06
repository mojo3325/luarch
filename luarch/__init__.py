from __future__ import annotations

import importlib

bl_info = {
    "name": "LuArch",
    "author": "Yehor Ustenko",
    "version": (0, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > LuArch",
    "description": "Generate editable low-poly tactical buildings and block layouts from presets",
    "category": "Object",
}

import bpy

from . import constants
from . import export_contract
from . import presets, properties
from . import export_rbxmx
from .generator import building as building_runtime
from .generator import building_output
from .generator import building_support
from .generator import building_facade
from .generator import building_facade_openings
from .generator import building_facade_opening_slots
from .generator import building_facade_frontage
from .generator import building_facade_frontage_industrial
from .generator import building_facade_frontage_recipes
from .generator import building_facade_frontage_storefront
from .generator import building_roof
from .generator import building_roof_exit
from .generator import layout_facade_planning
from .operators.generate_block import TBG_OT_generate_block
from .operators.generate_building import TBG_OT_generate_building
from .operators.delete_building import TBG_OT_delete_building
from .operators.apply_selected_building import TBG_OT_apply_selected_building
from .operators.preview_door import TBG_OT_preview_door
from .operators.quick_export_building import TBG_OT_pick_export_directory, TBG_OT_quick_export_building
from .operators.randomize_building import TBG_OT_randomize_building
from .operators.regenerate_building import TBG_OT_regenerate_building
from .operators.setup_preview import TBG_OT_preview_voxels, TBG_OT_setup_preview
from .operators.toggle_collision import TBG_OT_toggle_collision
from .operators.toggle_walls import TBG_OT_toggle_walls
from .operators.validate_building import TBG_OT_validate_building
from .services import build_scheduler
from .properties import TBG_PG_BlockSettings, TBG_PG_BuildingSettings, TBG_PG_SelectedBuildingSettings
from .services import selected_building_tuning
from .services import validation
from .services import validation_facts
from .services import validation_rules
from .services import validation_rules_service_roof
from .ui.panel_block import TBG_PT_block
from .ui.panel_building import TBG_PT_building


CLASSES = (
    TBG_PG_BuildingSettings,
    TBG_PG_SelectedBuildingSettings,
    TBG_PG_BlockSettings,
    TBG_OT_generate_building,
    TBG_OT_regenerate_building,
    TBG_OT_delete_building,
    TBG_OT_apply_selected_building,
    TBG_OT_randomize_building,
    TBG_OT_generate_block,
    TBG_OT_preview_door,
    TBG_OT_pick_export_directory,
    TBG_OT_quick_export_building,
    TBG_OT_setup_preview,
    TBG_OT_preview_voxels,
    TBG_OT_toggle_collision,
    TBG_OT_toggle_walls,
    TBG_OT_validate_building,
    TBG_PT_building,
    TBG_PT_block,
)


def register():
    presets.ensure_loaded()
    importlib.reload(constants)
    importlib.reload(export_contract)
    importlib.reload(layout_facade_planning)
    importlib.reload(building_facade_opening_slots)
    importlib.reload(building_facade_openings)
    importlib.reload(building_facade_frontage_recipes)
    importlib.reload(building_facade_frontage_storefront)
    importlib.reload(building_facade_frontage_industrial)
    importlib.reload(building_facade_frontage)
    importlib.reload(building_facade)
    importlib.reload(building_roof_exit)
    importlib.reload(building_roof)
    importlib.reload(building_support)
    importlib.reload(building_output)
    importlib.reload(export_rbxmx)
    importlib.reload(building_runtime)
    importlib.reload(validation_rules_service_roof)
    importlib.reload(validation_facts)
    importlib.reload(validation_rules)
    importlib.reload(validation)
    building_runtime.reset_exact_spec_reuse_runtime_state()
    building_runtime.reset_plan_memo_runtime_state()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    properties.register_scene_properties()
    build_scheduler.register()
    selected_building_tuning.register()


def unregister():
    selected_building_tuning.unregister()
    build_scheduler.unregister()
    properties.unregister_scene_properties()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
