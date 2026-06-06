from __future__ import annotations

import os
from pathlib import Path

import bpy
from bpy.props import StringProperty

from .. import constants, export_contract, export_rbxmx, metadata, naming
from ..generator import materials as generator_materials
from ..services import selected_building_tuning
from ..services.validation import (
    export_blocking_validation_issues,
    validate_root,
    validation_requires_regeneration,
)


def _normalize_export_directory(directory: str) -> Path | None:
    if not str(directory).strip():
        return None
    resolved = bpy.path.abspath(directory).strip()
    if not resolved:
        return None
    return Path(resolved).expanduser().resolve(strict=False)


def _directory_property_value(directory: Path) -> str:
    return os.path.join(str(directory), "")


def _stored_export_directory(settings) -> Path | None:
    return _normalize_export_directory(getattr(settings, "quick_export_directory", ""))


def _directory_picker_start(settings) -> str:
    current_directory = _stored_export_directory(settings)
    if current_directory is not None:
        return _directory_property_value(current_directory)
    blend_directory = _normalize_export_directory("//")
    if blend_directory is not None:
        return _directory_property_value(blend_directory)
    return _directory_property_value(Path.home())


def _export_basename(root_obj) -> str:
    building_id = str(root_obj.get(constants.BUILDING_ID_KEY, "")).strip()
    if building_id:
        return naming.root_collection_name(building_id)
    collection_name = str(root_obj.get(constants.COLLECTION_NAME_KEY, "")).strip()
    if collection_name:
        return collection_name
    return bpy.path.clean_name(root_obj.name) or "TBG_Building"


def _restore_selection(view_layer, selected_objects, active_object):
    for obj in view_layer.objects:
        obj.select_set(False)
    for obj in selected_objects:
        if obj.name not in bpy.data.objects:
            continue
        try:
            obj.select_set(True)
        except RuntimeError:
            continue
    if active_object is not None and active_object.name in bpy.data.objects:
        view_layer.objects.active = active_object


def _focus_root_selection(context, root_obj):
    view_layer = context.view_layer
    for obj in view_layer.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            continue
    if root_obj is not None and root_obj.name in bpy.data.objects:
        root_obj.select_set(True)
        view_layer.objects.active = root_obj


def _report_validation_block(operator, context, root_obj, issues: list[str], warning_issues: list[str]):
    _focus_root_selection(context, root_obj)
    if validation_requires_regeneration(issues):
        operator.report(
            {"ERROR"},
            f"Quick export blocked for {root_obj.name}: this building is stale for export contract "
            f"{export_contract.EXPORT_CONTRACT_VERSION}. Regenerate Selected, then export the FBX + RBXMX sidecar again.",
        )
    else:
        operator.report(
            {"ERROR"},
            f"Quick export blocked for {root_obj.name}: validation failed. Fix the reported issues or regenerate it, then export the FBX + RBXMX sidecar again.",
        )
    visible_issue_count = 6
    for issue in issues[:visible_issue_count]:
        operator.report({"WARNING"}, issue)
    hidden_issue_count = len(issues) - visible_issue_count
    if hidden_issue_count > 0:
        operator.report(
            {"WARNING"},
            f"{hidden_issue_count} more validation issue(s). Run Validate Selected for the full list.",
        )
    if warning_issues:
        operator.report(
            {"WARNING"},
            f"{len(warning_issues)} validation warning(s) were treated as non-blocking policy warnings.",
        )


def _report_validation_warnings(operator, warning_issues: list[str]):
    if not warning_issues:
        return
    operator.report(
        {"WARNING"},
        f"Continuing export with {len(warning_issues)} non-blocking validation warning(s).",
    )
    visible_issue_count = 6
    for issue in warning_issues[:visible_issue_count]:
        operator.report({"WARNING"}, issue)
    hidden_issue_count = len(warning_issues) - visible_issue_count
    if hidden_issue_count > 0:
        operator.report(
            {"WARNING"},
            f"{hidden_issue_count} more warning issue(s). Run Validate Selected for the full list.",
        )


def _render_export_objects(root_obj):
    return export_rbxmx.export_root_hierarchy_objects(root_obj)


def _brick_probe_material(family_key: str):
    family = generator_materials.BRICK_FAMILIES[str(family_key)]
    display_color = tuple(int(round(float(channel) * 255.0)) for channel in family["brick_a"][:3])
    return generator_materials.ensure_v3_wall_texture_preview_material(
        texture_key=f"wall_brick_{str(family_key).lower()}_masonry",
        material_family="BRICK",
        visual_style="BRICK_MASONRY",
        display_color_rgb=display_color,
    )


def _create_runtime_material_probe_objects(root_obj) -> list[bpy.types.Object]:
    probes: list[bpy.types.Object] = []
    for index, family_key in enumerate(sorted(generator_materials.BRICK_FAMILIES)):
        mesh = bpy.data.meshes.new(f"TBG_MaterialProbe_BRICK_{family_key}_Mesh")
        x0 = index * 0.02
        vertices = ((x0, 0.0, 0.0), (x0 + 0.01, 0.0, 0.0), (x0 + 0.01, 0.01, 0.0), (x0, 0.01, 0.0))
        mesh.from_pydata(vertices, (), ((0, 1, 2, 3),))
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop_index, uv in enumerate(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
            uv_layer.data[loop_index].uv = uv
        mesh.materials.append(_brick_probe_material(str(family_key)))
        obj = bpy.data.objects.new(f"TBG_MaterialProbe_BRICK_{family_key}", mesh)
        obj.parent = root_obj
        obj["tbg_runtime_material_probe"] = True
        obj["tbg_runtime_material_probe_family"] = str(family_key)
        bpy.context.collection.objects.link(obj)
        probes.append(obj)
    return probes


def _delete_runtime_material_probe_objects(probes: list[bpy.types.Object]) -> None:
    for obj in probes:
        if obj.name in bpy.data.objects:
            mesh = obj.data if isinstance(obj.data, bpy.types.Mesh) else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)


def _voxel_wall_export_counts(sidecar_result: dict[str, object]) -> tuple[int, int]:
    authored_cell_count = sidecar_result.get("authored_cell_count")
    occupancy_chunk_count = sidecar_result.get("occupancy_chunk_count")
    if not isinstance(authored_cell_count, int) or not isinstance(occupancy_chunk_count, int):
        raise RuntimeError("Quick export received an invalid V3 wall-cell sidecar summary.")
    return int(authored_cell_count), int(occupancy_chunk_count)


def _export_root_hierarchy(context, root_obj, filepath: str):
    view_layer = context.view_layer
    active_before = view_layer.objects.active
    selected_before = list(context.selected_objects)
    mode_before = getattr(active_before, "mode", "OBJECT") if active_before is not None else "OBJECT"
    material_probes: list[bpy.types.Object] = []
    export_objects = _render_export_objects(root_obj)
    root_matrix_before = root_obj.matrix_world.copy()

    if active_before is not None and mode_before != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    try:
        material_probes = _create_runtime_material_probe_objects(root_obj)
        export_objects = (*export_objects, *material_probes)
        # FBX render hierarchy must use root-local translation basis so Studio preflight matches RBXMX.
        root_obj.matrix_world = export_rbxmx.root_local_fbx_basis_matrix(root_obj)
        view_layer.update()
        for obj in view_layer.objects:
            obj.select_set(False)
        for obj in export_objects:
            if obj.name not in bpy.data.objects:
                continue
            obj.select_set(True)
        view_layer.objects.active = root_obj
        result = bpy.ops.export_scene.fbx(
            filepath=filepath,
            check_existing=False,
            use_selection=True,
            use_visible=False,
            object_types={"EMPTY", "MESH"},
            bake_anim=False,
            path_mode="COPY",
        )
        if "FINISHED" not in result:
            raise RuntimeError("FBX export did not finish.")
    finally:
        _delete_runtime_material_probe_objects(material_probes)
        if root_obj.name in bpy.data.objects:
            root_obj.matrix_world = root_matrix_before
            view_layer.update()
        _restore_selection(view_layer, selected_before, active_before)
        if active_before is not None and active_before.name in bpy.data.objects and mode_before != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode=mode_before)
            except RuntimeError:
                pass


class TBG_OT_pick_export_directory(bpy.types.Operator):
    bl_idname = "tbg.pick_export_directory"
    bl_label = "Choose Export Folder"
    bl_description = "Choose the folder used by the Tactical Building quick export"
    bl_options = {"REGISTER"}

    directory: StringProperty(name="Export Folder", subtype="DIR_PATH")

    def invoke(self, context, _event):
        self.directory = _directory_picker_start(context.scene.tbg_building)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        export_directory = _normalize_export_directory(self.directory)
        if export_directory is None:
            self.report({"ERROR"}, "Choose a valid export folder.")
            return {"CANCELLED"}
        export_directory.mkdir(parents=True, exist_ok=True)
        context.scene.tbg_building.quick_export_directory = _directory_property_value(export_directory)
        self.report({"INFO"}, f"Quick export folder set to {export_directory}")
        return {"FINISHED"}


class TBG_OT_quick_export_building(bpy.types.Operator):
    bl_idname = "tbg.quick_export_building"
    bl_label = "Quick Export Selected"
    bl_description = "Validate and export the selected tactical building root to render-only FBX plus RBXMX sidecar"
    bl_options = {"REGISTER"}

    directory: StringProperty(name="Export Folder", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return metadata.resolve_root_from_object(context.active_object) is not None

    def invoke(self, context, _event):
        if _stored_export_directory(context.scene.tbg_building) is not None:
            return self.execute(context)
        self.directory = _directory_picker_start(context.scene.tbg_building)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.tbg_building
        export_directory = _normalize_export_directory(self.directory) or _stored_export_directory(settings)
        if export_directory is None:
            self.report({"ERROR"}, "Choose a quick export folder first.")
            return {"CANCELLED"}

        export_directory.mkdir(parents=True, exist_ok=True)
        settings.quick_export_directory = _directory_property_value(export_directory)

        root_obj = metadata.resolve_root_from_object(context.active_object)
        if root_obj is None:
            self.report({"ERROR"}, "Select a Tactical Building root or one of its children before exporting.")
            return {"CANCELLED"}
        try:
            root_obj, finalized = selected_building_tuning.ensure_root_finalized(
                context,
                root_obj,
                require_authoritative_payload=True,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Finalize before export failed: {exc}")
            return {"CANCELLED"}
        if finalized:
            self.report({"INFO"}, f"Finalized dirty edit mode for {root_obj.name} before export.")

        issues = validate_root(root_obj)
        blocking_issues = export_blocking_validation_issues(issues)
        warning_issues = [issue for issue in issues if issue not in blocking_issues]
        if blocking_issues:
            _report_validation_block(self, context, root_obj, blocking_issues, warning_issues)
            return {"CANCELLED"}
        _report_validation_warnings(self, warning_issues)

        basename = _export_basename(root_obj)
        filepath = export_directory / f"{basename}.fbx"
        sidecar_path = export_directory / f"{basename}.rbxmx"
        try:
            sidecar_result = export_rbxmx.export_runtime_sidecar(root_obj, sidecar_path)
            _export_root_hierarchy(context, root_obj, str(filepath))
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        authored_cell_count, occupancy_chunk_count = _voxel_wall_export_counts(sidecar_result)

        self.report(
            {"INFO"},
            f"Exported {root_obj.name} to {filepath} and {sidecar_path} "
            f"(authored cells={authored_cell_count}, occupancy chunks={occupancy_chunk_count}; "
            "V3 sidecar exported, Studio plugin cutover pending)",
        )
        return {"FINISHED"}
