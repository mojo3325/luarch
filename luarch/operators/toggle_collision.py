from __future__ import annotations

import bpy

from .. import export_contract, metadata


def _collision_markers(root):
    if root is None:
        return []
    return [
        child
        for child in root.children_recursive
        if child.type == "MESH"
        and bool(child.get("tbg_runtime_marker"))
        and str(child.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_COLLISION
    ]


class TBG_OT_toggle_collision(bpy.types.Operator):
    bl_idname = "tbg.toggle_collision"
    bl_label = "Toggle Collision"
    bl_description = "Hide or show authored traversal collision markers for the selected tactical building"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return metadata.resolve_root_from_object(context.active_object) is not None

    def execute(self, context):
        root = metadata.resolve_root_from_object(context.active_object)
        if root is None:
            self.report({"ERROR"}, "No tactical building root found.")
            return {"CANCELLED"}

        markers = _collision_markers(root)
        if not markers:
            self.report({"WARNING"}, "Selected building has no authored traversal collision markers to toggle.")
            return {"CANCELLED"}

        should_hide = any(not obj.hide_viewport for obj in markers)
        for obj in markers:
            obj.hide_viewport = should_hide
            obj.hide_render = should_hide

        root["tbg_collision_hidden"] = should_hide
        state = "hidden" if should_hide else "shown"
        self.report({"INFO"}, f"{state.title()} {len(markers)} traversal collision marker(s).")
        return {"FINISHED"}
