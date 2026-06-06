from __future__ import annotations

import bpy

from .. import metadata
from ..services import selected_building_tuning
from ..services.validation import validate_root


class TBG_OT_validate_building(bpy.types.Operator):
    bl_idname = "tbg.validate_building"
    bl_label = "Validate Selected"
    bl_description = "Validate the selected tactical building root"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return metadata.resolve_root_from_object(obj) is not None

    def execute(self, context):
        root = metadata.resolve_root_from_object(context.active_object)
        try:
            root, finalized = selected_building_tuning.ensure_root_finalized(
                context,
                root,
                require_authoritative_payload=True,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Finalize before validation failed: {exc}")
            return {"CANCELLED"}
        if finalized:
            self.report({"INFO"}, f"Finalized dirty edit mode for {root.name} before validation.")
        issues = validate_root(root)
        if issues:
            for issue in issues:
                self.report({"WARNING"}, issue)
            return {"CANCELLED"}
        self.report({"INFO"}, f"{root.name} passed basic validation.")
        return {"FINISHED"}
