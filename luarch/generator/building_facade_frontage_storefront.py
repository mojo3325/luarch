from __future__ import annotations

from dataclasses import dataclass

from ..export_contract import ROLE_SHELL
from .building_facade_opening_slots import (
    build_custom_window_slot as _build_custom_window_slot,
    create_opening_box as _create_opening_box,
    slot_opening_profile as _slot_opening_profile,
)
from .building_facade_frontage_recipes import (
    build_front_entry_frame as _build_front_entry_frame,
    emit_front_wall_piece as _emit_front_wall_piece,
    frontage_trim_material as _frontage_trim_material,
    resolve_frontage_entry_pose as _resolve_frontage_entry_pose,
)
from .building_layout import (
    ENTRY_CANOPY_THICKNESS,
    FRONTAGE_TYPE_STOREFRONT_CLINIC,
    FRONTAGE_TYPE_STOREFRONT_PHARMACY,
    FRONTAGE_TYPE_STOREFRONT_SHOP,
    WINDOW_STATE_CLOSED,
    WINDOW_STATE_OPEN,
    _base_elevation,
    _orientation_rotation,
    _surface_coord,
)
from .building_support import (
    _mark_generated,
    _mark_section,
    _name,
)
from .runtime_markers import RuntimeMarkerEmitter, _emit_object_proxy_box
from .layout_facade_planning import _front_entry_envelope, _wall_material_for_floor, _window_verticals
from .building_occupancy import OccupancyAuthoringSession


@dataclass(frozen=True)
class _StorefrontAction:
    kind: str
    payload: dict[str, object]


def _mark_storefront_piece(obj, kind: str, *, slot_index: int | None = None):
    if obj is None:
        return None
    metadata = {
        "tbg_storefront_part": True,
        "tbg_storefront_part_kind": kind,
    }
    if slot_index is not None:
        metadata["tbg_storefront_slot"] = int(slot_index)
    return _mark_generated(obj, **metadata)


def _emit_storefront_front_solid(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    start: float,
    end: float,
    center_z: float,
    height: float,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    width = end - start
    if width <= 0.12 or height <= 0.04:
        return None
    return _emit_front_wall_piece(
        prefix,
        suffix,
        spec,
        collection,
        parent,
        material,
        width=width,
        center_x=(start + end) / 2,
        center_z=center_z,
        height=height,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )


def _build_storefront_glazed_bay(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    materials_map,
    *,
    front_y: float,
    span_start: float,
    span_end: float,
    base_z: float,
    sill_h: float,
    opening_h: float,
    opening_width: float,
    slot_index: int,
    window_state: str = WINDOW_STATE_CLOSED,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    lintel_h = max(0.22, spec.floor_height - sill_h - opening_h)
    _emit_storefront_front_solid(
        prefix,
        f"{suffix}_Sill",
        spec,
        collection,
        parent,
        _wall_material_for_floor(materials_map, spec, 0),
        start=span_start,
        end=span_end,
        center_z=base_z + sill_h / 2,
        height=sill_h,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    _emit_storefront_front_solid(
        prefix,
        f"{suffix}_Lintel",
        spec,
        collection,
        parent,
        _wall_material_for_floor(materials_map, spec, 0),
        start=span_start,
        end=span_end,
        center_z=base_z + sill_h + opening_h + lintel_h / 2,
        height=lintel_h,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    _build_custom_window_slot(
        prefix,
        suffix,
        "X",
        "front",
        front_y,
        span_start,
        span_end,
        base_z,
        spec.floor_height,
        spec.wall_thickness,
        collection,
        parent,
        materials_map,
        spec,
        state=window_state,
        protect_opening=False,
        floor_index=0,
        slot_index=slot_index,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
        occupancy_author=occupancy_author,
        merge_allowed=False,
        extra_metadata={
            "tbg_storefront_window": True,
            "tbg_storefront_part": True,
            "tbg_storefront_part_kind": "Glazing",
            "tbg_storefront_slot": int(slot_index),
        },
        runtime_emitter=runtime_emitter,
    )


def _build_storefront_box(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    orientation: str,
    width: float,
    depth: float,
    height: float,
    along_coord: float,
    normal_coord: float,
    center_z: float,
    section: str,
    kind: str | None = None,
    merge_allowed: bool = False,
    generated_metadata: dict | None = None,
):
    part = _create_opening_box(
        _name(prefix, suffix),
        orientation,
        width,
        depth,
        height,
        along_coord,
        normal_coord,
        center_z,
        collection,
        parent,
        material,
    )
    part = _mark_generated(part, **(generated_metadata or {}))
    if kind is not None:
        part = _mark_storefront_piece(part, kind)
    return _mark_section(part, section, merge_allowed=merge_allowed)


def _build_storefront_canopy(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    front_y: float,
    width: float,
    depth: float,
    center_x: float,
    center_z: float,
    include_storefront_metadata: bool,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    generated_metadata: dict | None = None,
):
    canopy_thickness = 0.06 if suffix != "Storefront_Canopy" else ENTRY_CANOPY_THICKNESS
    canopy_y = _surface_coord(
        "front",
        front_y,
        spec.wall_thickness,
        depth,
        exterior=True,
        offset=0.06 if suffix == "Storefront_Canopy" else 0.08,
    )
    canopy = _create_opening_box(
        _name(prefix, suffix),
        "X",
        width,
        depth,
        canopy_thickness,
        center_x,
        canopy_y,
        center_z,
        collection,
        parent,
        material,
    )
    canopy = _mark_generated(canopy, tbg_entry_canopy=True, **(generated_metadata or {}))
    if include_storefront_metadata:
        canopy = _mark_storefront_piece(canopy, "Canopy")
    canopy = _mark_section(
        canopy,
        "Section_Walls_Canopy",
        merge_allowed=False,
        hide_with_walls=True,
    )
    if runtime_emitter is not None:
        _emit_object_proxy_box(
            runtime_emitter,
            canopy,
            metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0, "tbg_runtime_feature": "entry_canopy"},
        )
    if include_storefront_metadata or suffix.startswith("Pharmacy_") or suffix.startswith("Clinic_"):
        post_height = max(0.9, center_z - canopy_thickness / 2 - _base_elevation(spec))
        post_center_y = canopy_y + depth / 2 - 0.04
        post_offset_x = max(0.22, width / 2 - 0.08)
        for side_label, sign in (("L", -1.0), ("R", 1.0)):
            post = _create_opening_box(
                _name(prefix, f"{suffix}_Post_{side_label}"),
                "X",
                0.06,
                0.06,
                post_height,
                center_x + sign * post_offset_x,
                post_center_y,
                _base_elevation(spec) + post_height / 2,
                collection,
                parent,
                material,
            )
            post = _mark_generated(post, tbg_entry_canopy=True, **(generated_metadata or {}))
            if include_storefront_metadata:
                post = _mark_storefront_piece(post, "Canopy")
            _mark_section(post, "Section_Doors_Trim", merge_allowed=False)
    return canopy


def _resolve_box_material(materials_map, trim_material, material_slot: str):
    if material_slot == "facade_trim":
        return trim_material
    return materials_map[material_slot]


def _shop_storefront_payload(spec, envelope) -> tuple[_StorefrontAction, ...]:
    outer_margin = 0.24
    center_pier_width = max(0.22, min(0.3, spec.wall_thickness * 1.2))
    side_pier_width = max(0.26, min(0.34, spec.wall_thickness * 1.35))
    door_center_x = max(
        -spec.width / 2 + outer_margin + envelope.door_width / 2,
        min(spec.width / 2 - outer_margin - envelope.door_width / 2, envelope.door_offset_x),
    )
    door_left = door_center_x - envelope.door_width / 2
    door_right = door_center_x + envelope.door_width / 2
    display_on_left = door_center_x > 0.0
    if display_on_left:
        display_left = -spec.width / 2 + outer_margin
        display_right = door_left - center_pier_width
        side_solid = (door_right + side_pier_width, spec.width / 2 - outer_margin)
    else:
        display_left = door_right + center_pier_width
        display_right = spec.width / 2 - outer_margin
        side_solid = (-spec.width / 2 + outer_margin, door_left - side_pier_width)
    display_span = max(0.0, display_right - display_left)
    display_sill = 0.3
    display_height = max(1.28, min(1.56, spec.floor_height - display_sill - 0.62))
    sign_height = 0.5
    sign_depth = max(0.12, spec.wall_thickness * 0.34)
    canopy_depth = 0.18
    canopy_width = min(envelope.door_width + 0.22, 1.42)
    actions: list[_StorefrontAction] = []
    if display_span > 1.26:
        actions.append(
            _StorefrontAction(
                "glazed_bay",
                {
                    "suffix": "Shop_Display",
                    "span_start": display_left,
                    "span_end": display_right,
                    "sill_h": display_sill,
                    "opening_h": display_height,
                    "opening_width": display_span - 0.12,
                    "slot_index": 0,
                },
            )
        )
    actions.extend(
        (
            _StorefrontAction(
                "solid",
                {
                    "suffix": "Shop_Door_Lintel",
                    "start": door_left,
                    "end": door_right,
                    "center_z": _base_elevation(spec) + spec.door.height + max(0.24, spec.floor_height - spec.door.height) / 2,
                    "height": max(0.24, spec.floor_height - spec.door.height),
                },
            ),
            _StorefrontAction(
                "solid",
                {
                    "suffix": "Shop_SideSolid",
                    "start": side_solid[0],
                    "end": side_solid[1],
                    "center_z": _base_elevation(spec) + spec.floor_height / 2,
                    "height": spec.floor_height,
                },
            ),
            _StorefrontAction(
                "solid",
                {
                    "suffix": "Shop_CenterPier",
                    "start": display_right if display_on_left else door_right,
                    "end": door_left if display_on_left else display_left,
                    "center_z": _base_elevation(spec) + spec.floor_height / 2,
                    "height": spec.floor_height,
                },
            ),
            _StorefrontAction(
                "door_frame",
                {
                    "door_center_x": door_center_x,
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Shop_SignBand",
                    "material_slot": "facade_trim",
                    "width": min(spec.width * 0.5, max(1.84, display_span - 0.1)),
                    "depth": sign_depth,
                    "height": sign_height,
                    "along_coord": (display_left + display_right) / 2 if display_span > 1.26 else door_center_x,
                    "normal_coord": _surface_coord("front", -spec.depth / 2 + spec.wall_thickness / 2, spec.wall_thickness, sign_depth, exterior=True, offset=0.02),
                    "center_z": _base_elevation(spec) + spec.floor_height - sign_height / 2 - 0.12,
                    "section": "Section_Walls_Trim",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "canopy",
                {
                    "suffix": "Shop_DoorCanopy",
                    "material_slot": "facade_trim",
                    "width": canopy_width,
                    "depth": canopy_depth,
                    "center_x": door_center_x,
                    "center_z": _base_elevation(spec) + spec.door.height + 0.12,
                    "include_storefront_metadata": False,
                },
            ),
        )
    )
    return tuple(actions)


def _pharmacy_storefront_payload(spec, envelope) -> tuple[_StorefrontAction, ...]:
    outer_margin = 0.28
    display_gap = max(0.24, spec.wall_thickness * 1.05)
    door_center_x = 0.0
    door_left = door_center_x - envelope.door_width / 2
    door_right = door_center_x + envelope.door_width / 2
    display_width = min(
        spec.width * 0.22,
        max(1.18, (spec.width - envelope.door_width - outer_margin * 2 - display_gap * 2) / 2),
    )
    left_display = (door_left - display_gap - display_width, door_left - display_gap)
    right_display = (door_right + display_gap, door_right + display_gap + display_width)
    plinth_height = 0.12
    emblem_height = 0.62
    emblem_depth = max(0.16, spec.wall_thickness * 0.42)
    canopy_depth = 0.14
    base_z = _base_elevation(spec)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    actions: list[_StorefrontAction] = []
    for label, (start, end), slot_index in (("Left", left_display, 0), ("Right", right_display, 1)):
        slot_opening_width, slot_sill_h, slot_opening_h, _slot_top_h = _slot_opening_profile(
            spec,
            WINDOW_STATE_OPEN,
            end - start,
            spec.floor_height,
            side_key="front",
            floor_index=0,
            slot_index=slot_index,
        )
        actions.append(
            _StorefrontAction(
                "glazed_bay",
                {
                    "suffix": f"Pharmacy_Display_{label}",
                    "span_start": start,
                    "span_end": end,
                    "sill_h": slot_sill_h,
                    "opening_h": slot_opening_h,
                    "opening_width": slot_opening_width,
                    "slot_index": slot_index,
                    "window_state": WINDOW_STATE_OPEN,
                },
            )
        )
    for suffix, start, end in (
        ("Pharmacy_OuterLeft", -spec.width / 2, left_display[0]),
        ("Pharmacy_InnerLeft", left_display[1], door_left),
        ("Pharmacy_InnerRight", door_right, right_display[0]),
        ("Pharmacy_OuterRight", right_display[1], spec.width / 2),
    ):
        actions.append(
            _StorefrontAction(
                "solid",
                {
                    "suffix": suffix,
                    "start": start,
                    "end": end,
                    "center_z": base_z + spec.floor_height / 2,
                    "height": spec.floor_height,
                },
            )
        )
    actions.extend(
        (
            _StorefrontAction(
                "solid",
                {
                    "suffix": "Pharmacy_Door_Lintel",
                    "start": door_left,
                    "end": door_right,
                    "center_z": base_z + spec.door.height + max(0.18, spec.floor_height - spec.door.height) / 2,
                    "height": max(0.18, spec.floor_height - spec.door.height),
                },
            ),
            _StorefrontAction("door_frame", {"door_center_x": door_center_x}),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Pharmacy_EmblemBand",
                    "material_slot": "facade_trim",
                    "width": min(spec.width - outer_margin * 2, max(envelope.door_width + 1.92, spec.width * 0.54)),
                    "depth": emblem_depth,
                    "height": emblem_height,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, emblem_depth, exterior=True, offset=0.02),
                    "center_z": base_z + spec.floor_height - emblem_height / 2 - 0.14,
                    "section": "Section_Walls_Trim",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Pharmacy_Cross_Vertical",
                    "material_slot": "frame",
                    "width": 0.26,
                    "depth": emblem_depth * 0.78,
                    "height": 0.52,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, emblem_depth * 0.78, exterior=True, offset=0.08),
                    "center_z": base_z + spec.floor_height - emblem_height / 2 - 0.14,
                    "section": "Section_Doors_Prop",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Pharmacy_Cross_Horizontal",
                    "material_slot": "frame",
                    "width": 0.76,
                    "depth": emblem_depth * 0.78,
                    "height": 0.2,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, emblem_depth * 0.78, exterior=True, offset=0.08),
                    "center_z": base_z + spec.floor_height - emblem_height / 2 - 0.14,
                    "section": "Section_Doors_Prop",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "canopy",
                {
                    "suffix": "Pharmacy_DoorCanopy",
                    "material_slot": "facade_trim",
                    "width": max(envelope.door_width + 0.08, 1.04),
                    "depth": canopy_depth,
                    "center_x": door_center_x,
                    "center_z": base_z + spec.door.height + 0.1,
                    "include_storefront_metadata": False,
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Pharmacy_Plinth_L",
                    "material_slot": "facade_trim",
                    "width": max(0.18, left_display[0] - (-spec.width / 2 + outer_margin)),
                    "depth": 0.08,
                    "height": plinth_height,
                    "along_coord": (-spec.width / 2 + outer_margin + left_display[0]) / 2,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, 0.08, exterior=True, offset=0.02),
                    "center_z": base_z + plinth_height / 2,
                    "section": "Section_Walls_Trim",
                    "kind": None,
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Pharmacy_Plinth_R",
                    "material_slot": "facade_trim",
                    "width": max(0.18, spec.width / 2 - outer_margin - right_display[1]),
                    "depth": 0.08,
                    "height": plinth_height,
                    "along_coord": (right_display[1] + spec.width / 2 - outer_margin) / 2,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, 0.08, exterior=True, offset=0.02),
                    "center_z": base_z + plinth_height / 2,
                    "section": "Section_Walls_Trim",
                    "kind": None,
                },
            ),
        )
    )
    return tuple(actions)


def _clinic_storefront_payload(spec, envelope) -> tuple[_StorefrontAction, ...]:
    outer_margin = 0.34
    door_center_x = 0.0
    door_left = door_center_x - envelope.door_width / 2
    door_right = door_center_x + envelope.door_width / 2
    door_gap = max(0.28, spec.wall_thickness * 1.28)
    service_window_width = min(1.34, max(1.02, spec.width * 0.11))
    service_window_sill, service_window_height, _top_h = _window_verticals(spec.floor_height, spec.window_profile)
    band_height = 0.42
    band_depth = max(0.1, spec.wall_thickness * 0.26)
    canopy_depth = 0.14
    canopy_width = max(envelope.door_width + 0.36, 1.48)
    plinth_height = 0.12
    left_window = (door_left - door_gap - service_window_width, door_left - door_gap)
    right_window = (door_right + door_gap, door_right + door_gap + service_window_width)
    base_z = _base_elevation(spec)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    actions: list[_StorefrontAction] = []
    for suffix, start, end in (
        ("Clinic_OuterLeft", -spec.width / 2, left_window[0]),
        ("Clinic_InnerLeft", left_window[1], door_left),
        ("Clinic_InnerRight", door_right, right_window[0]),
        ("Clinic_OuterRight", right_window[1], spec.width / 2),
    ):
        actions.append(
            _StorefrontAction(
                "solid",
                {
                    "suffix": suffix,
                    "start": start,
                    "end": end,
                    "center_z": base_z + spec.floor_height / 2,
                    "height": spec.floor_height,
                },
            )
        )
    actions.append(
        _StorefrontAction(
            "solid",
            {
                "suffix": "Clinic_Door_Lintel",
                "start": door_left,
                "end": door_right,
                "center_z": base_z + spec.door.height + max(0.22, spec.floor_height - spec.door.height) / 2,
                "height": max(0.22, spec.floor_height - spec.door.height),
            },
        )
    )
    for label, (start, end), slot_index in (("Left", left_window, 0), ("Right", right_window, 1)):
        actions.append(
            _StorefrontAction(
                "glazed_bay",
                {
                    "suffix": f"Clinic_ServiceWindow_{label}",
                    "span_start": start,
                    "span_end": end,
                    "sill_h": service_window_sill,
                    "opening_h": service_window_height,
                    "opening_width": (end - start) - 0.06,
                    "slot_index": slot_index,
                    "window_state": WINDOW_STATE_OPEN,
                },
            )
        )
    actions.extend(
        (
            _StorefrontAction(
                "box",
                {
                    "suffix": "Clinic_IdentityBand",
                    "material_slot": "facade_trim",
                    "width": min(spec.width - outer_margin * 2, max(envelope.door_width + 2.12, spec.width * 0.48)),
                    "depth": band_depth,
                    "height": band_height,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, band_depth, exterior=True, offset=0.02),
                    "center_z": base_z + spec.floor_height - band_height / 2 - 0.14,
                    "section": "Section_Walls_Trim",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Clinic_MedicalGlyph_V",
                    "material_slot": "frame",
                    "width": 0.16,
                    "depth": band_depth * 0.72,
                    "height": 0.34,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, band_depth * 0.72, exterior=True, offset=0.06),
                    "center_z": base_z + spec.floor_height - band_height / 2 - 0.14,
                    "section": "Section_Doors_Prop",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Clinic_MedicalGlyph_H",
                    "material_slot": "frame",
                    "width": 0.42,
                    "depth": band_depth * 0.72,
                    "height": 0.12,
                    "along_coord": door_center_x,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, band_depth * 0.72, exterior=True, offset=0.06),
                    "center_z": base_z + spec.floor_height - band_height / 2 - 0.14,
                    "section": "Section_Doors_Prop",
                    "kind": "Signage",
                },
            ),
            _StorefrontAction(
                "canopy",
                {
                    "suffix": "Clinic_EntryCanopy",
                    "material_slot": "facade_trim",
                    "width": canopy_width,
                    "depth": canopy_depth,
                    "center_x": door_center_x,
                    "center_z": base_z + spec.door.height + 0.1,
                    "include_storefront_metadata": True,
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Clinic_Plith_L",
                    "material_slot": "facade_trim",
                    "width": max(0.18, left_window[0] - (-spec.width / 2 + outer_margin)),
                    "depth": 0.08,
                    "height": plinth_height,
                    "along_coord": (-spec.width / 2 + outer_margin + left_window[0]) / 2,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, 0.08, exterior=True, offset=0.02),
                    "center_z": base_z + plinth_height / 2,
                    "section": "Section_Walls_Trim",
                    "kind": None,
                },
            ),
            _StorefrontAction(
                "box",
                {
                    "suffix": "Clinic_Plith_R",
                    "material_slot": "facade_trim",
                    "width": max(0.18, spec.width / 2 - outer_margin - right_window[1]),
                    "depth": 0.08,
                    "height": plinth_height,
                    "along_coord": (right_window[1] + spec.width / 2 - outer_margin) / 2,
                    "normal_coord": _surface_coord("front", front_y, spec.wall_thickness, 0.08, exterior=True, offset=0.02),
                    "center_z": base_z + plinth_height / 2,
                    "section": "Section_Walls_Trim",
                    "kind": None,
                },
            ),
            _StorefrontAction("door_frame", {"door_center_x": door_center_x}),
        )
    )
    return tuple(actions)


def _storefront_actions(spec, envelope) -> tuple[_StorefrontAction, ...]:
    storefront_variant = envelope.frontage_variant
    if storefront_variant == FRONTAGE_TYPE_STOREFRONT_SHOP:
        return _shop_storefront_payload(spec, envelope)
    if storefront_variant == FRONTAGE_TYPE_STOREFRONT_PHARMACY:
        return _pharmacy_storefront_payload(spec, envelope)
    if storefront_variant == FRONTAGE_TYPE_STOREFRONT_CLINIC:
        return _clinic_storefront_payload(spec, envelope)
    raise RuntimeError(f"Unsupported storefront frontage variant: {storefront_variant}")


def build_storefront_front_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    ground_floor_facts,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    _ = ground_floor_facts
    envelope = _front_entry_envelope(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    trim_material = _frontage_trim_material(materials_map, spec)
    frame_material = materials_map["frame"]
    base_z = _base_elevation(spec)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    _door_center_x, door_frame_y = _resolve_frontage_entry_pose(spec)

    for action in _storefront_actions(spec, envelope):
        payload = action.payload
        if action.kind == "glazed_bay":
            _build_storefront_glazed_bay(
                prefix,
                str(payload["suffix"]),
                spec,
                collection,
                parent,
                materials_map,
                front_y=front_y,
                span_start=float(payload["span_start"]),
                span_end=float(payload["span_end"]),
                base_z=base_z,
                sill_h=float(payload["sill_h"]),
                opening_h=float(payload["opening_h"]),
                opening_width=float(payload["opening_width"]),
                slot_index=int(payload["slot_index"]),
                window_state=str(payload.get("window_state", WINDOW_STATE_CLOSED)),
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
            continue
        if action.kind == "solid":
            _emit_storefront_front_solid(
                prefix,
                str(payload["suffix"]),
                spec,
                collection,
                parent,
                wall_material,
                start=float(payload["start"]),
                end=float(payload["end"]),
                center_z=float(payload["center_z"]),
                height=float(payload["height"]),
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
            continue
        if action.kind == "door_frame":
            _build_front_entry_frame(
                prefix,
                "Door_Main",
                spec,
                collection,
                parent,
                frame_material,
                wall_pos=door_frame_y,
                door_center_x=float(payload["door_center_x"]),
                door_width=envelope.door_width,
                base_z=base_z,
                door_height=spec.door.height,
                merge_allowed=False,
                stamp_outer_bounds=False,
            )
            continue
        if action.kind == "box":
            _build_storefront_box(
                prefix,
                str(payload["suffix"]),
                spec,
                collection,
                parent,
                _resolve_box_material(materials_map, trim_material, str(payload["material_slot"])),
                orientation="X",
                width=float(payload["width"]),
                depth=float(payload["depth"]),
                height=float(payload["height"]),
                along_coord=float(payload["along_coord"]),
                normal_coord=float(payload["normal_coord"]),
                center_z=float(payload["center_z"]),
                section=str(payload["section"]),
                kind=payload.get("kind"),
                merge_allowed=bool(payload.get("merge_allowed", False)),
                generated_metadata=payload.get("generated_metadata"),
            )
            continue
        if action.kind == "canopy":
            _build_storefront_canopy(
                prefix,
                str(payload["suffix"]),
                spec,
                collection,
                parent,
                _resolve_box_material(materials_map, trim_material, str(payload["material_slot"])),
                front_y=front_y,
                width=float(payload["width"]),
                depth=float(payload["depth"]),
                center_x=float(payload["center_x"]),
                center_z=float(payload["center_z"]),
                include_storefront_metadata=bool(payload["include_storefront_metadata"]),
                generated_metadata=payload.get("generated_metadata"),
            )
            continue
        raise RuntimeError(f"Unsupported storefront action kind: {action.kind}")
