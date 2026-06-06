from __future__ import annotations

import bpy

from ..services import selected_building_tuning


class TBG_OT_apply_selected_building(bpy.types.Operator):
    bl_idname = "tbg.apply_selected_building"
    bl_label = "Commit Selected Edits"
    bl_description = "Commit pending selected-building edits into canonical metadata/runtime/export state"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return selected_building_tuning.has_bound_root(context.scene)

    def execute(self, context):
        success, message = selected_building_tuning.apply_selected_building(context.scene, context=context)
        if not success:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}
