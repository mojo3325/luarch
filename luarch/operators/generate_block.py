from __future__ import annotations

import bpy

from ..generator.block_layout import enqueue_block_generation


class TBG_OT_generate_block(bpy.types.Operator):
    bl_idname = "tbg.generate_block"
    bl_label = "Generate Block"
    bl_description = "Generate a grid block of multiple tactical building variants"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            plan = enqueue_block_generation(context)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Queued district generation for block {plan.identity.block_id}.")
        return {"FINISHED"}
