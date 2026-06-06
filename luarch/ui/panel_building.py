from __future__ import annotations

import bpy

from .. import export_contract, metadata
from ..constants import ADDON_LABEL
from ..services import selected_building_tuning



class TBG_PT_building(bpy.types.Panel):
    bl_label = "Single Building"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ADDON_LABEL

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.tbg_building
        selected_settings = context.scene.tbg_selected_building
        root = metadata.resolve_root_from_object(context.active_object)
        walls_hidden = bool(root and root.get("tbg_walls_hidden"))
        collision_markers = (
            [
                child
                for child in root.children_recursive
                if child.type == "MESH"
                and bool(child.get("tbg_runtime_marker"))
                and str(child.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_COLLISION
            ]
            if root is not None
            else []
        )
        collision_hidden = bool(collision_markers) and all(child.hide_viewport for child in collision_markers)

        col = layout.column(align=True)
        col.prop(settings, "preset_id", text="Building Type")
        col.prop(settings, "seed", text="Variation Seed")

        box = layout.box()
        box.label(text="Shape")
        box.prop(settings, "width", text="Width")
        box.prop(settings, "depth", text="Depth")
        box.prop(settings, "floor_count", text="Floors")
        box.prop(settings, "terrace_enabled", text="Terrace")
        box.prop(settings, "massing_profile", text="Massing")

        if settings.floor_count > 1:
            box = layout.box()
            box.label(text="Stairs")
            box.prop(settings, "stair_placement", text="Core Position")
            box.prop(settings, "railing_enabled", text="Add Railings")

        box = layout.box()
        box.label(text="Door")
        box.prop(settings, "door_hinge", text="Hinge Side")

        box = layout.box()
        box.label(text="Stoops")
        box.prop(settings, "front_stoop_variant", text="Front")
        box.prop(settings, "rear_stoop_variant", text="Rear")

        row = layout.row(align=True)
        row.operator("tbg.randomize_building", text="Randomize")
        row.operator("tbg.generate_building", text="Generate")

        selected_box = layout.box()
        selected_box.label(text="Selected Building Tuning")
        selected_box.label(text=selected_building_tuning.binding_status(context.scene))
        bound_root_name = selected_building_tuning.bound_root_name(context.scene)
        if bound_root_name:
            selected_box.label(text=f"Bound Root: {bound_root_name}")
            selected_box.label(text=f"Preset: {selected_building_tuning.selected_preset_label(context.scene)}")
            selected_box.label(text=f"State: {selected_building_tuning.bound_root_state_label(context.scene)}")
            if selected_building_tuning.is_rebuild_pending(context.scene):
                selected_box.label(text="Pending coalesced edit rebuild (queued)")
            shape_box = selected_box.box()
            shape_box.label(text="Shape")
            shape_box.prop(selected_settings, "width", text="Width")
            shape_box.prop(selected_settings, "depth", text="Depth")
            shape_box.prop(selected_settings, "floor_count", text="Floors")
            shape_box.prop(selected_settings, "terrace_enabled", text="Terrace")
            shape_box.prop(selected_settings, "massing_profile", text="Massing")
            if selected_settings.floor_count > 1:
                stair_box = selected_box.box()
                stair_box.label(text="Stairs")
                stair_box.prop(selected_settings, "stair_placement", text="Core Position")
                stair_box.prop(selected_settings, "stair_core_variant", text="Variant")
                stair_box.prop(selected_settings, "railing_enabled", text="Railings")
            look_box = selected_box.box()
            look_box.label(text="Look")
            look_box.prop(selected_settings, "facade_family", text="Facade")
            look_box.prop(selected_settings, "roof_mode", text="Roof")
            openings_box = selected_box.box()
            openings_box.label(text="Openings")
            openings_box.prop(selected_settings, "open_window_ratio", text="Open Window Ratio")
            openings_box.prop(selected_settings, "combat_open_window_min", text="Minimum Open")
            stoop_capability = selected_building_tuning.bound_stoop_edit_applicability(context.scene)
            front_stoop_capability = dict(stoop_capability.get("front", {}))
            rear_stoop_capability = dict(stoop_capability.get("rear", {}))
            entry_box = selected_box.box()
            entry_box.label(text="Entry")
            entry_box.prop(selected_settings, "door_hinge", text="Door Hinge")
            front_stoop_row = entry_box.row()
            front_stoop_row.enabled = bool(front_stoop_capability.get("applicable", False))
            front_stoop_row.prop(selected_settings, "front_stoop_variant", text="Front Stoop")
            rear_stoop_row = entry_box.row()
            rear_stoop_row.enabled = bool(rear_stoop_capability.get("applicable", False))
            rear_stoop_row.prop(selected_settings, "rear_stoop_variant", text="Rear Stoop")
            front_reason = str(front_stoop_capability.get("reason", "")).strip()
            if not bool(front_stoop_capability.get("applicable", False)) and front_reason:
                entry_box.label(text=f"Front stoop unavailable: {front_reason}")
            rear_reason = str(rear_stoop_capability.get("reason", "")).strip()
            if not bool(rear_stoop_capability.get("applicable", False)) and rear_reason:
                entry_box.label(text=f"Rear stoop unavailable: {rear_reason}")
            maintenance_box = selected_box.box()
            maintenance_box.label(text="Maintenance")
            commit_text = (
                "Commit Pending Preview"
                if selected_building_tuning.is_rebuild_pending(context.scene)
                else "Commit Selected Edits"
            )
            commit_row = maintenance_box.row()
            commit_row.enabled = (
                selected_building_tuning.is_rebuild_pending(context.scene)
                or selected_building_tuning.is_bound_root_dirty(context.scene)
            )
            commit_row.operator("tbg.apply_selected_building", text=commit_text)
            maintenance_box.operator("tbg.regenerate_building", text="Reset From Stored Spec")
        else:
            hint = selected_box.column(align=True)
            hint.enabled = False
            hint.prop(selected_settings, "width", text="Width")
            hint.prop(selected_settings, "depth", text="Depth")

        if walls_hidden:
            warn = layout.box()
            warn.alert = True
            warn.label(text="Selected building has wall sections hidden.")

        row = layout.row(align=True)
        row.operator("tbg.preview_door", text="Preview Door")
        row.operator("tbg.toggle_walls", text="Show Walls" if walls_hidden else "Hide Walls")
        row.operator("tbg.toggle_collision", text="Show Collision" if collision_hidden else "Hide Collision")
        authority_box = layout.box()
        authority_box.label(text="Wall Authority")
        status_row = authority_box.row()
        status_row.enabled = False
        status_row.label(text="Destructible wall truth: authored cells")
        authority_box.operator("tbg.preview_voxels", text="Verify Wall Cells", icon="CHECKMARK")

        layout.operator("tbg.setup_preview", text="Setup Preview")
        layout.operator("tbg.validate_building", text="Validate Selected")
        layout.operator("tbg.delete_building", text="Delete Selected Building", icon="TRASH")

        box = layout.box()
        box.label(text="Quick Export")
        box.prop(settings, "quick_export_directory", text="Folder")
        button_text = "Choose Folder + Export" if not settings.quick_export_directory.strip() else "Quick Export Selected"
        box.operator("tbg.quick_export_building", text=button_text, icon="EXPORT")
