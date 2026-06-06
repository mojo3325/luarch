from __future__ import annotations

import bpy

from .. import metadata
from ..services import cleanup


class TBG_OT_delete_building(bpy.types.Operator):
    bl_idname = "tbg.delete_building"
    bl_label = "Delete Selected Building"
    bl_description = "Delete the full tactical building hierarchy for the selected root or child object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return metadata.resolve_root_from_object(context.active_object) is not None

    def execute(self, context):
        from ..services import selected_building_tuning

        root = metadata.resolve_root_from_object(context.active_object)
        if root is None:
            self.report({"ERROR"}, "No tactical building root found for deletion.")
            return {"CANCELLED"}

        root_name = str(root.name)
        try:
            removed = cleanup.delete_generated_building_hierarchy(root)
        except Exception as exc:
            self.report({"ERROR"}, f"Delete failed for {root_name}: {exc}")
            return {"CANCELLED"}

        selected_building_tuning.refresh_selected_building_binding(context)
        self.report(
            {"INFO"},
            (
                f"Deleted {root_name}: "
                f"{removed.get('removed_objects', 0)} objects, "
                f"{removed.get('removed_collections', 0)} collections."
            ),
        )
        return {"FINISHED"}
