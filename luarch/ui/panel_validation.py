from __future__ import annotations

import bpy

from ..constants import ADDON_LABEL


class TBG_PT_validation(bpy.types.Panel):
    bl_label = "Validation"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ADDON_LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, _context):
        layout = self.layout
        layout.operator("tbg.preview_door", text="Preview Door")
        layout.operator("tbg.validate_building", text="Validate Selected")
