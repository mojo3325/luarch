from __future__ import annotations

import bpy

from .. import metadata
from ..generator.building import build_building
from ..generator.specs import building_spec_from_mapping, building_spec_from_settings
from ..services import build_scheduler, cleanup


def rebuild_existing_root(
    context,
    root,
    *,
    settings=None,
    spec_dict: dict | None = None,
    edit_mode: bool = False,
    clear_lanes: set[str] | None = None,
    emit_lanes: set[str] | None = None,
):
    if root is None:
        raise ValueError("Existing root is required for regeneration.")
    if settings is None and spec_dict is None:
        raise ValueError("Regeneration requires either settings or a stored spec mapping.")

    original_location = root.location.copy()
    original_rotation = root.rotation_euler.copy()
    if settings is not None:
        spec = building_spec_from_settings(
            settings,
            building_id=root.get("tbg_building_id"),
            origin=tuple(root.location),
        )
    else:
        spec = building_spec_from_mapping(
            spec_dict or {},
            building_id=root.get("tbg_building_id"),
            origin=tuple(root.location),
        )
    if not edit_mode:
        cleanup.clear_transient_wall_helpers(root)
        cleanup.prune_empty_generated_collections()
    try:
        build_building(
            context,
            spec,
            existing_root=root,
            edit_mode=edit_mode,
            clear_lanes=clear_lanes,
            emit_lanes=emit_lanes,
        )
    finally:
        if not edit_mode:
            cleanup.prune_empty_generated_collections()
    root.location = original_location
    root.rotation_euler = original_rotation
    context.view_layer.update()
    return root


class TBG_OT_regenerate_building(bpy.types.Operator):
    bl_idname = "tbg.regenerate_building"
    bl_label = "Reset Selected from Stored Spec"
    bl_description = "Rebuild the selected tactical building from stored canonical metadata"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return metadata.resolve_root_from_object(obj) is not None

    def execute(self, context):
        from ..services import selected_building_tuning

        root = metadata.resolve_root_from_object(context.active_object)
        try:
            root, finalized = selected_building_tuning.ensure_root_finalized(context, root)
        except Exception as exc:
            self.report({"ERROR"}, f"Finalize before regeneration failed: {exc}")
            return {"CANCELLED"}
        if finalized:
            self.report({"INFO"}, f"Finalized dirty edit mode for {root.name} before regeneration.")

        try:
            spec_dict = metadata.read_spec_dict(root, strict=True)
        except metadata.MetadataContractError as exc:
            self.report({"ERROR"}, f"Selected root has no stored building spec: {exc}")
            return {"CANCELLED"}

        regenerated: dict[str, object] = {}

        def _regenerate_job():
            rebuilt_root = rebuild_existing_root(context, root, spec_dict=spec_dict)
            selected_building_tuning.select_and_bind_root(context, rebuilt_root)
            regenerated["root"] = rebuilt_root
            return True, f"Reset {root.name} from stored spec."

        job_id = build_scheduler.enqueue_job(
            label=f"regenerate:{root.name}",
            execute=_regenerate_job,
        )
        success, message = build_scheduler.flush(force_ready=True)
        if not success:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        status, status_message = build_scheduler.job_status(job_id)
        if status == "failed":
            self.report({"ERROR"}, status_message or "Regenerate job failed.")
            return {"CANCELLED"}
        if status == "cancelled":
            self.report({"ERROR"}, status_message or "Regenerate job was cancelled.")
            return {"CANCELLED"}
        if regenerated.get("root") is None:
            self.report({"ERROR"}, "Regenerate job did not produce a root.")
            return {"CANCELLED"}
        self.report({"INFO"}, status_message or f"Reset {root.name} from stored spec.")
        return {"FINISHED"}
