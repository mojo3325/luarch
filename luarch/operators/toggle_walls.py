from __future__ import annotations

import bpy

from .. import metadata


def _section_meshes(root):
    return [child for child in root.children_recursive if child.type == "MESH" and child.get("tbg_section_bucket")]


def _hides_with_walls(obj) -> bool:
    return bool(obj.get("tbg_hide_with_walls"))


def _authored_wall_meshes(root):
    section_meshes = _section_meshes(root)
    if not section_meshes:
        return None
    return [child for child in section_meshes if _hides_with_walls(child)]

class TBG_OT_toggle_walls(bpy.types.Operator):
    bl_idname = "tbg.toggle_walls"
    bl_label = "Toggle Walls"
    bl_description = "Hide or show exterior shell meshes for the selected tactical building"
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

        walls = _authored_wall_meshes(root)
        if not walls:
            self.report({"WARNING"}, "Selected building has no exterior-shell section to toggle.")
            return {"CANCELLED"}

        should_hide = any(not obj.hide_viewport for obj in walls)
        for obj in walls:
            obj.hide_viewport = should_hide
            obj.hide_render = should_hide

        root["tbg_walls_hidden"] = should_hide
        state = "hidden" if should_hide else "shown"
        self.report({"INFO"}, f"{state.title()} {len(walls)} exterior-shell mesh object(s).")
        return {"FINISHED"}
