from __future__ import annotations

import random

import bpy

from .. import presets, properties
from ..generator.building_layout import resolve_terrace_feasible_spec
from ..generator.specs import building_spec_from_settings, normalized_payload_from_mapping


class TBG_OT_randomize_building(bpy.types.Operator):
    bl_idname = "tbg.randomize_building"
    bl_label = "Randomize Settings"
    bl_description = "Apply deterministic randomized values from the selected preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.tbg_building
        pointer = properties.suppress_preset_callback(settings)
        try:
            settings.seed = int(random.SystemRandom().randrange(1, 2_147_483_647))
            payload = normalized_payload_from_mapping(presets.build_randomized_payload(settings.preset_id, settings.seed))
            presets.apply_payload(settings, payload, preserve_keys=("massing_profile",))
            resolved = resolve_terrace_feasible_spec(
                building_spec_from_settings(
                    settings,
                    building_id=None,
                    origin=(0.0, 0.0, 0.0),
                )
            )
            settings.width = float(resolved.width)
            settings.depth = float(resolved.depth)
        finally:
            properties.resume_preset_callback(pointer)
        self.report({"INFO"}, f"Applied randomized preset '{settings.preset_id}' with seed {settings.seed}")
        return {"FINISHED"}
