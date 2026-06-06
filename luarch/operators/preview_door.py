from __future__ import annotations

import bpy
from math import radians

from .. import metadata


class TBG_OT_preview_door(bpy.types.Operator):
    bl_idname = "tbg.preview_door"
    bl_label = "Preview Door"
    bl_description = "Toggle the main door between closed and preview-open states"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return metadata.resolve_root_from_object(obj) is not None

    def execute(self, context):
        root = metadata.resolve_root_from_object(context.active_object)
        if root is None:
            self.report({"ERROR"}, "No tactical building root found.")
            return {"CANCELLED"}

        doors = [child for child in root.children_recursive if child.get("tbg_is_door_leaf")]
        if not doors:
            self.report({"WARNING"}, "Selected building has no generated door leaf.")
            return {"CANCELLED"}

        angle = radians(90.0)
        for door in doors:
            current = float(door.rotation_euler.z)
            closed = float(door.get("tbg_closed_rotation_z", 0.0))
            open_angle = float(door.get("tbg_open_rotation_z", angle))
            door.rotation_euler.z = open_angle if abs(current - closed) < 1e-4 else closed

        self.report({"INFO"}, f"Toggled {len(doors)} door preview object(s).")
        return {"FINISHED"}
