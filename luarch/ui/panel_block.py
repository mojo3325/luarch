from __future__ import annotations

import bpy

from ..constants import ADDON_LABEL


class TBG_PT_block(bpy.types.Panel):
    bl_label = "District"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ADDON_LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.tbg_block

        box = layout.box()
        box.label(text="Grid")
        box.prop(settings, "rows")
        box.prop(settings, "columns")
        box.prop(settings, "spacing_x")
        box.prop(settings, "spacing_y")
        box.prop(settings, "seed")

        layout.label(text="Uses 3D Cursor as district origin")
        layout.operator("tbg.generate_block", text="Generate District")
