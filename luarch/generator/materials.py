from __future__ import annotations

import bpy
from .textures import (
    ATLAS_CELL_SIZE,
    ATLAS_COLUMNS,
    ATLAS_IMAGE_NAME,
    ATLAS_PADDING,
    ATLAS_RECTS_KEY,
    CACHE_MANIFEST_NAME,
    IMAGE_SIGNATURE_KEY,
    MATERIAL_SIGNATURE_KEY,
    _build_texture_atlas,
    _ensure_brick_image,
    _ensure_door_image,
    _ensure_solid_image,
    _ensure_tone_border_image,
    _signature_for,
    export_atlas_sidecar as _export_atlas_sidecar,
    resolve_export_atlas_image as _resolve_export_atlas_image,
)


BRICK_FAMILIES = {
    "LIGHT_BRICK": {
        "name": "TBG_Wall_LightBrick",
        "brick_a": (0.83, 0.78, 0.63, 1.0),
        "brick_b": (0.80, 0.75, 0.61, 1.0),
        "mortar": (0.67, 0.61, 0.52, 1.0),
        "scale": 0.38,
        "panel_base": (0.76, 0.73, 0.68, 1.0),
        "panel_accent": (0.78, 0.75, 0.71, 1.0),
        "panel_border": (0.63, 0.57, 0.50, 1.0),
        "trim_base": (0.64, 0.57, 0.49, 1.0),
        "trim_accent": (0.71, 0.64, 0.56, 1.0),
        "trim_border": (0.39, 0.31, 0.25, 1.0),
        "balcony_base": (0.74, 0.72, 0.70, 1.0),
        "balcony_accent": (0.67, 0.63, 0.59, 1.0),
        "balcony_border": (0.45, 0.40, 0.35, 1.0),
    },
    "RED_BRICK": {
        "name": "TBG_Wall_RedBrick",
        "brick_a": (0.64, 0.43, 0.34, 1.0),
        "brick_b": (0.60, 0.40, 0.31, 1.0),
        "mortar": (0.66, 0.58, 0.52, 1.0),
        "scale": 0.38,
        "panel_base": (0.69, 0.64, 0.61, 1.0),
        "panel_accent": (0.71, 0.66, 0.63, 1.0),
        "panel_border": (0.57, 0.49, 0.45, 1.0),
        "trim_base": (0.59, 0.50, 0.45, 1.0),
        "trim_accent": (0.66, 0.56, 0.50, 1.0),
        "trim_border": (0.39, 0.30, 0.27, 1.0),
        "balcony_base": (0.70, 0.65, 0.62, 1.0),
        "balcony_accent": (0.63, 0.57, 0.53, 1.0),
        "balcony_border": (0.44, 0.36, 0.33, 1.0),
    },
    "DESAT_BRICK": {
        "name": "TBG_Wall_DesatBrick",
        "brick_a": (0.73, 0.71, 0.66, 1.0),
        "brick_b": (0.70, 0.68, 0.63, 1.0),
        "mortar": (0.50, 0.52, 0.55, 1.0),
        "scale": 0.38,
        "panel_base": (0.70, 0.70, 0.71, 1.0),
        "panel_accent": (0.72, 0.72, 0.73, 1.0),
        "panel_border": (0.58, 0.58, 0.59, 1.0),
        "trim_base": (0.60, 0.60, 0.61, 1.0),
        "trim_accent": (0.67, 0.67, 0.68, 1.0),
        "trim_border": (0.41, 0.41, 0.42, 1.0),
        "balcony_base": (0.70, 0.70, 0.71, 1.0),
        "balcony_accent": (0.65, 0.65, 0.66, 1.0),
        "balcony_border": (0.45, 0.45, 0.46, 1.0),
    },
    "BROWN_BRICK": {
        "name": "TBG_Wall_BrownBrick",
        "brick_a": (0.45, 0.33, 0.24, 1.0),
        "brick_b": (0.40, 0.29, 0.20, 1.0),
        "mortar": (0.61, 0.55, 0.48, 1.0),
        "scale": 0.38,
        "panel_base": (0.57, 0.51, 0.46, 1.0),
        "panel_accent": (0.61, 0.55, 0.49, 1.0),
        "panel_border": (0.39, 0.32, 0.27, 1.0),
        "trim_base": (0.49, 0.41, 0.35, 1.0),
        "trim_accent": (0.56, 0.47, 0.40, 1.0),
        "trim_border": (0.28, 0.21, 0.17, 1.0),
        "balcony_base": (0.63, 0.58, 0.54, 1.0),
        "balcony_accent": (0.56, 0.50, 0.46, 1.0),
        "balcony_border": (0.36, 0.30, 0.27, 1.0),
    },
    "GREY_BRICK": {
        "name": "TBG_Wall_GreyBrick",
        "brick_a": (0.55, 0.55, 0.57, 1.0),
        "brick_b": (0.50, 0.50, 0.53, 1.0),
        "mortar": (0.71, 0.72, 0.74, 1.0),
        "scale": 0.38,
        "panel_base": (0.65, 0.66, 0.68, 1.0),
        "panel_accent": (0.69, 0.70, 0.72, 1.0),
        "panel_border": (0.46, 0.47, 0.49, 1.0),
        "trim_base": (0.53, 0.54, 0.57, 1.0),
        "trim_accent": (0.61, 0.62, 0.65, 1.0),
        "trim_border": (0.33, 0.34, 0.36, 1.0),
        "balcony_base": (0.64, 0.65, 0.67, 1.0),
        "balcony_accent": (0.58, 0.59, 0.61, 1.0),
        "balcony_border": (0.40, 0.40, 0.43, 1.0),
    },
    "DARK_BRICK": {
        "name": "TBG_Wall_DarkBrick",
        "brick_a": (0.29, 0.24, 0.21, 1.0),
        "brick_b": (0.24, 0.20, 0.18, 1.0),
        "mortar": (0.47, 0.44, 0.41, 1.0),
        "scale": 0.38,
        "panel_base": (0.41, 0.39, 0.38, 1.0),
        "panel_accent": (0.47, 0.45, 0.44, 1.0),
        "panel_border": (0.24, 0.22, 0.21, 1.0),
        "trim_base": (0.34, 0.31, 0.30, 1.0),
        "trim_accent": (0.41, 0.38, 0.37, 1.0),
        "trim_border": (0.18, 0.16, 0.15, 1.0),
        "balcony_base": (0.46, 0.45, 0.44, 1.0),
        "balcony_accent": (0.40, 0.39, 0.38, 1.0),
        "balcony_border": (0.24, 0.22, 0.21, 1.0),
    },
}

FLAT_FACADE_FAMILIES = {
    "SANDSTONE_FLAT": {
        "name": "TBG_Wall_SandstoneFlat",
        "color": (0.64, 0.60, 0.54, 1.0),
        "roughness": 0.94,
        "panel_base": (0.68, 0.64, 0.58, 1.0),
        "panel_accent": (0.72, 0.68, 0.62, 1.0),
        "panel_border": (0.49, 0.45, 0.39, 1.0),
        "trim_base": (0.53, 0.48, 0.43, 1.0),
        "trim_accent": (0.61, 0.56, 0.50, 1.0),
        "trim_border": (0.34, 0.30, 0.26, 1.0),
    },
    "CONCRETE_FLAT": {
        "name": "TBG_Wall_ConcreteFlat",
        "color": (0.60, 0.61, 0.63, 1.0),
        "roughness": 0.96,
        "panel_base": (0.66, 0.67, 0.69, 1.0),
        "panel_accent": (0.70, 0.71, 0.73, 1.0),
        "panel_border": (0.45, 0.46, 0.49, 1.0),
        "trim_base": (0.50, 0.51, 0.54, 1.0),
        "trim_accent": (0.57, 0.58, 0.61, 1.0),
        "trim_border": (0.30, 0.31, 0.34, 1.0),
    },
    "PLASTER_WARM": {
        "name": "TBG_Wall_PlasterWarm",
        "color": (0.76, 0.70, 0.63, 1.0),
        "roughness": 0.95,
        "panel_base": (0.79, 0.73, 0.66, 1.0),
        "panel_accent": (0.83, 0.77, 0.70, 1.0),
        "panel_border": (0.58, 0.51, 0.45, 1.0),
        "trim_base": (0.66, 0.58, 0.51, 1.0),
        "trim_accent": (0.73, 0.65, 0.58, 1.0),
        "trim_border": (0.42, 0.35, 0.30, 1.0),
    },
    "PLASTER_COOL": {
        "name": "TBG_Wall_PlasterCool",
        "color": (0.74, 0.77, 0.80, 1.0),
        "roughness": 0.95,
        "panel_base": (0.77, 0.80, 0.83, 1.0),
        "panel_accent": (0.82, 0.85, 0.88, 1.0),
        "panel_border": (0.54, 0.58, 0.61, 1.0),
        "trim_base": (0.62, 0.66, 0.69, 1.0),
        "trim_accent": (0.69, 0.73, 0.76, 1.0),
        "trim_border": (0.38, 0.42, 0.45, 1.0),
    },
    "TIMBER_WARM": {
        "name": "TBG_Wall_TimberWarm",
        "color": (0.63, 0.48, 0.32, 1.0),
        "roughness": 0.92,
        "panel_base": (0.67, 0.52, 0.35, 1.0),
        "panel_accent": (0.71, 0.56, 0.39, 1.0),
        "panel_border": (0.43, 0.31, 0.20, 1.0),
        "trim_base": (0.55, 0.41, 0.26, 1.0),
        "trim_accent": (0.62, 0.47, 0.31, 1.0),
        "trim_border": (0.31, 0.22, 0.14, 1.0),
    },
    "TIMBER_WEATHERED": {
        "name": "TBG_Wall_TimberWeathered",
        "color": (0.57, 0.53, 0.47, 1.0),
        "roughness": 0.95,
        "panel_base": (0.62, 0.58, 0.52, 1.0),
        "panel_accent": (0.66, 0.62, 0.56, 1.0),
        "panel_border": (0.42, 0.38, 0.33, 1.0),
        "trim_base": (0.50, 0.46, 0.40, 1.0),
        "trim_accent": (0.57, 0.53, 0.47, 1.0),
        "trim_border": (0.30, 0.27, 0.23, 1.0),
    },
    "PAINTED_WOOD": {
        "name": "TBG_Wall_PaintedWood",
        "color": (0.62, 0.69, 0.67, 1.0),
        "roughness": 0.94,
        "panel_base": (0.66, 0.73, 0.71, 1.0),
        "panel_accent": (0.71, 0.78, 0.76, 1.0),
        "panel_border": (0.45, 0.51, 0.49, 1.0),
        "trim_base": (0.53, 0.60, 0.58, 1.0),
        "trim_accent": (0.60, 0.67, 0.65, 1.0),
        "trim_border": (0.34, 0.39, 0.38, 1.0),
    },
}

_INTERIOR_WALL_COLOR = (0.58, 0.59, 0.61, 1.0)
_BASE_BALCONY_MATERIAL_KEY = "balcony"
INDUSTRIAL_CLADDING_MATERIAL_NAME = "TBG_IndustrialCladding"
WINDOW_FILL_MATERIAL_NAME = "TBG_WindowFill"
WINDOW_FILL_EXPECTED_COLOR = (0.63, 0.79, 0.95, 1.0)
INDUSTRIAL_CLADDING_ATLAS_KEY = "shutter"
OPENING_TRIM_SECTION_BUCKET_KEY = "tbg_opening_trim_section_bucket"
OPENING_TRIM_SECTION_BUCKET_DEFAULT = "Section_Openings_Trim"
OPENING_TRIM_SECTION_BUCKET_WALL = "Section_Openings_Trim_Wall"
OPENING_TRIM_SECTION_BUCKET_PANEL = "Section_Openings_Trim_Panel"

UV_IS_BRICK_KEY = "tbg_is_brick"
UV_REQUIRES_KEY = "tbg_requires_uv"
UV_BRICK_SCALE_KEY = "tbg_brick_uv_scale"
UV_REPEAT_KEY = "tbg_uv_repeat"
UV_PROJECTION_MODE_KEY = "tbg_uv_projection_mode"
UV_ISLAND_INSET_KEY = "tbg_uv_island_inset"
UV_U0_KEY = "tbg_uv_u0"
UV_V0_KEY = "tbg_uv_v0"
UV_U1_KEY = "tbg_uv_u1"
UV_V1_KEY = "tbg_uv_v1"
UV_PROJECTION_BOUNDS = "BOUNDS"
UV_PROJECTION_FACE_FIT = "FACE_FIT"

_DEFAULT_UV_RECT = (0.0, 0.0, 1.0, 1.0)


def _normalized_uv_rect(uv_rect: tuple[float, float, float, float] | None) -> tuple[float, float, float, float]:
    if uv_rect is None:
        return _DEFAULT_UV_RECT
    u0, v0, u1, v1 = uv_rect
    return float(u0), float(v0), float(u1), float(v1)


def _normalized_uv_projection_mode(projection_mode: str) -> str:
    mode = str(projection_mode).upper()
    if mode in {UV_PROJECTION_BOUNDS, UV_PROJECTION_FACE_FIT}:
        return mode
    return UV_PROJECTION_BOUNDS


def _normalized_uv_island_inset(island_inset: float) -> float:
    return max(0.0, min(0.45, float(island_inset)))


def material_uv_settings(material) -> dict[str, object]:
    is_brick = bool(material.get(UV_IS_BRICK_KEY, False)) if material is not None else False
    return {
        "requires_uv": bool(material.get(UV_REQUIRES_KEY, False)) if material is not None else False,
        "is_brick": is_brick,
        "brick_scale": max(
            0.01,
            float(material.get(UV_BRICK_SCALE_KEY, 0.4 if is_brick else 1.0)),
        )
        if material is not None
        else 1.0,
        "repeat": bool(material.get(UV_REPEAT_KEY, False)) if material is not None else False,
        "projection_mode": _normalized_uv_projection_mode(
            material.get(UV_PROJECTION_MODE_KEY, UV_PROJECTION_BOUNDS) if material is not None else UV_PROJECTION_BOUNDS
        ),
        "island_inset": _normalized_uv_island_inset(
            material.get(UV_ISLAND_INSET_KEY, 0.0) if material is not None else 0.0
        ),
        "uv_rect": _normalized_uv_rect(
            (
                material.get(UV_U0_KEY, _DEFAULT_UV_RECT[0]),
                material.get(UV_V0_KEY, _DEFAULT_UV_RECT[1]),
                material.get(UV_U1_KEY, _DEFAULT_UV_RECT[2]),
                material.get(UV_V1_KEY, _DEFAULT_UV_RECT[3]),
            )
            if material is not None
            else None
        ),
    }


def apply_material_uv_metadata(
    material,
    *,
    uv_rect: tuple[float, float, float, float] | None = None,
    repeat: bool = False,
    is_brick: bool = False,
    brick_scale: float = 1.0,
    projection_mode: str = UV_PROJECTION_BOUNDS,
    island_inset: float = 0.0,
):
    normalized_rect = _normalized_uv_rect(uv_rect)
    material[UV_IS_BRICK_KEY] = bool(is_brick)
    material[UV_REQUIRES_KEY] = True
    material[UV_BRICK_SCALE_KEY] = float(brick_scale if is_brick else 1.0)
    material[UV_REPEAT_KEY] = bool(repeat)
    material[UV_PROJECTION_MODE_KEY] = _normalized_uv_projection_mode(projection_mode)
    material[UV_ISLAND_INSET_KEY] = _normalized_uv_island_inset(island_inset)
    material[UV_U0_KEY] = normalized_rect[0]
    material[UV_V0_KEY] = normalized_rect[1]
    material[UV_U1_KEY] = normalized_rect[2]
    material[UV_V1_KEY] = normalized_rect[3]


def _set_opening_trim_section_bucket(material, trim_section_bucket: str) -> None:
    material[OPENING_TRIM_SECTION_BUCKET_KEY] = str(trim_section_bucket or OPENING_TRIM_SECTION_BUCKET_DEFAULT)


def opening_trim_section_bucket(material) -> str:
    if material is None:
        return OPENING_TRIM_SECTION_BUCKET_DEFAULT
    return str(material.get(OPENING_TRIM_SECTION_BUCKET_KEY, OPENING_TRIM_SECTION_BUCKET_DEFAULT))


def _sync_material_image_nodes(material, image: bpy.types.Image | None) -> None:
    if material is None or image is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return
    for node in node_tree.nodes:
        if getattr(node, "type", "") == "TEX_IMAGE":
            node.image = image


def _clear_material_uv_metadata(material) -> None:
    if material is None:
        return
    material[UV_IS_BRICK_KEY] = False
    material[UV_REQUIRES_KEY] = False
    material[UV_BRICK_SCALE_KEY] = 1.0
    material[UV_REPEAT_KEY] = False
    material[UV_PROJECTION_MODE_KEY] = UV_PROJECTION_BOUNDS
    material[UV_ISLAND_INSET_KEY] = 0.0
    material[UV_U0_KEY] = _DEFAULT_UV_RECT[0]
    material[UV_V0_KEY] = _DEFAULT_UV_RECT[1]
    material[UV_U1_KEY] = _DEFAULT_UV_RECT[2]
    material[UV_V1_KEY] = _DEFAULT_UV_RECT[3]


def _ensure_solid_principled_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
    specular: float | None = None,
    trim_section_bucket: str = OPENING_TRIM_SECTION_BUCKET_DEFAULT,
    roblox_basepart_sim: bool = False,
):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)
    signature = _signature_for(
        "solid_principled",
        color,
        roughness,
        metallic,
        specular,
        bool(roblox_basepart_sim),
    )
    if (
        str(material.get(MATERIAL_SIGNATURE_KEY, "")) == signature
        and material.use_nodes
        and material.node_tree is not None
    ):
        material.diffuse_color = color
        _clear_material_uv_metadata(material)
        _set_opening_trim_section_bucket(material, trim_section_bucket)
        material["tbg_roblox_basepart_sim_preview"] = bool(roblox_basepart_sim)
        return material

    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300, 0)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (40, 0)
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    if specular is not None:
        if "Specular IOR Level" in principled.inputs:
            principled.inputs["Specular IOR Level"].default_value = specular
        elif "Specular" in principled.inputs:
            principled.inputs["Specular"].default_value = specular
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = color
    _clear_material_uv_metadata(material)
    _set_opening_trim_section_bucket(material, trim_section_bucket)
    material["tbg_roblox_basepart_sim_preview"] = bool(roblox_basepart_sim)
    material[MATERIAL_SIGNATURE_KEY] = signature
    return material


def _ensure_brick_variant_sim_material(name: str, family_key: str):
    family = BRICK_FAMILIES[str(family_key)]
    brick_image = _ensure_brick_image(
        f"{name}_Image",
        brick_a=family["brick_a"],
        brick_b=family["brick_b"],
        mortar=family["mortar"],
    )
    material = _ensure_principled_material(
        name,
        family["brick_a"],
        roughness=0.94,
        specular=0.12,
        image=brick_image,
        uv_rect=(0.0, 0.0, 1.0, 1.0),
        repeat=True,
        brick_scale=float(family["scale"]),
        interpolation="Linear",
        uv_projection=UV_PROJECTION_BOUNDS,
    )
    material["tbg_roblox_basepart_sim_preview"] = True
    material["tbg_roblox_basepart_sim_pattern"] = "BRICK_MASONRY"
    material["tbg_roblox_basepart_sim_family"] = str(family_key)
    return material


def resolve_export_atlas_image(root_obj) -> bpy.types.Image | None:
    return _resolve_export_atlas_image(root_obj)


def export_atlas_sidecar(root_obj, export_fbx_path):
    return _export_atlas_sidecar(root_obj, export_fbx_path)


def _ensure_principled_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
    transmission: float = 0.0,
    specular: float | None = None,
    image: bpy.types.Image | None = None,
    backface_color: tuple[float, float, float, float] | None = None,
    uv_rect: tuple[float, float, float, float] | None = None,
    repeat: bool = False,
    brick_scale: float | None = None,
    interpolation: str = "Closest",
    uv_projection: str = "BOUNDS",
    uv_inset: float = 0.0,
    trim_section_bucket: str = OPENING_TRIM_SECTION_BUCKET_DEFAULT,
):
    color_image = image or _ensure_solid_image(f"{name}_Image", color=color)
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)
    signature = _signature_for(
        "principled",
        color,
        roughness,
        metallic,
        transmission,
        specular,
        str(color_image.get(IMAGE_SIGNATURE_KEY, "")) if color_image is not None else "",
        backface_color,
        uv_rect,
        repeat,
        brick_scale,
        interpolation,
        uv_projection,
        uv_inset,
    )
    if (
        str(material.get(MATERIAL_SIGNATURE_KEY, "")) == signature
        and material.use_nodes
        and material.node_tree is not None
    ):
        material.diffuse_color = color
        _sync_material_image_nodes(material, color_image)
        apply_material_uv_metadata(
            material,
            uv_rect=uv_rect,
            repeat=repeat,
            is_brick=brick_scale is not None,
            brick_scale=brick_scale or 1.0,
            projection_mode=uv_projection,
            island_inset=uv_inset,
        )
        _set_opening_trim_section_bucket(material, trim_section_bucket)
        return material
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (320, 0)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (60, 0)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    if specular is not None:
        if "Specular IOR Level" in principled.inputs:
            principled.inputs["Specular IOR Level"].default_value = specular
        elif "Specular" in principled.inputs:
            principled.inputs["Specular"].default_value = specular
    if "Transmission Weight" in principled.inputs:
        principled.inputs["Transmission Weight"].default_value = transmission
    elif "Transmission" in principled.inputs:
        principled.inputs["Transmission"].default_value = transmission

    image_tex = nodes.new(type="ShaderNodeTexImage")
    image_tex.location = (-420, 20)
    image_tex.image = color_image
    image_tex.interpolation = interpolation
    image_tex.extension = "REPEAT" if repeat else "EXTEND"
    tex_coord = nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-680, 20)
    links.new(tex_coord.outputs["UV"], image_tex.inputs["Vector"])

    if backface_color is not None:
        geometry = nodes.new(type="ShaderNodeNewGeometry")
        geometry.location = (-400, -140)
        mix = nodes.new(type="ShaderNodeMixRGB")
        mix.location = (-160, 20)
        mix.blend_type = "MIX"
        mix.inputs["Color1"].default_value = color
        mix.inputs["Color2"].default_value = backface_color
        links.new(geometry.outputs["Backfacing"], mix.inputs["Fac"])
        links.new(image_tex.outputs["Color"], mix.inputs["Color1"])
        links.new(mix.outputs["Color"], principled.inputs["Base Color"])
    else:
        links.new(image_tex.outputs["Color"], principled.inputs["Base Color"])
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = color
    apply_material_uv_metadata(
        material,
        uv_rect=uv_rect,
        repeat=repeat,
        is_brick=brick_scale is not None,
        brick_scale=brick_scale or 1.0,
        projection_mode=uv_projection,
        island_inset=uv_inset,
    )
    _set_opening_trim_section_bucket(material, trim_section_bucket)
    material[MATERIAL_SIGNATURE_KEY] = signature
    return material


def _ensure_brick_material(
    name: str,
    *,
    brick_a: tuple[float, float, float, float],
    brick_b: tuple[float, float, float, float],
    mortar: tuple[float, float, float, float],
    scale: float,
    image: bpy.types.Image | None = None,
    uv_rect: tuple[float, float, float, float] | None = None,
    trim_section_bucket: str = OPENING_TRIM_SECTION_BUCKET_DEFAULT,
):
    brick_image = image or _ensure_brick_image(
        f"{name}_Image",
        brick_a=brick_a,
        brick_b=brick_b,
        mortar=mortar,
    )
    return _ensure_principled_material(
        name,
        brick_a,
        roughness=0.94,
        specular=0.12,
        image=brick_image,
        uv_rect=uv_rect,
        repeat=True,
        brick_scale=scale,
        interpolation="Linear",
        trim_section_bucket=trim_section_bucket,
    )


def _ensure_tone_border_material(
    name: str,
    *,
    base: tuple[float, float, float, float],
    accent: tuple[float, float, float, float],
    border: tuple[float, float, float, float],
    roughness: float,
    specular: float = 0.08,
    image: bpy.types.Image | None = None,
    uv_rect: tuple[float, float, float, float] | None = None,
    uv_projection: str = "BOUNDS",
    uv_inset: float = 0.0,
    trim_section_bucket: str = OPENING_TRIM_SECTION_BUCKET_DEFAULT,
):
    image = image or _ensure_tone_border_image(
        f"{name}_Image",
        base=base,
        accent=accent,
        border=border,
    )
    return _ensure_principled_material(
        name,
        base,
        roughness=roughness,
        specular=specular,
        image=image,
        uv_rect=uv_rect,
        uv_projection=uv_projection,
        uv_inset=uv_inset,
        trim_section_bucket=trim_section_bucket,
    )


def _family_title(family: str) -> str:
    return family.title().replace("_", "")


def _brick_role_params(family_config: dict, role: str) -> dict:
    if role == "wall":
        return {
            "brick_a": family_config["brick_a"],
            "brick_b": family_config["brick_b"],
            "mortar": family_config["mortar"],
            "scale": family_config["scale"],
        }
    return {
        "base": family_config[f"{role}_base"],
        "accent": family_config[f"{role}_accent"],
        "border": family_config[f"{role}_border"],
    }


def _flat_role_params(family_config: dict, role: str) -> dict:
    if role == "wall":
        return {
            "name": family_config["name"],
            "color": family_config["color"],
            "roughness": float(family_config.get("roughness", 0.92)),
        }
    family_title = family_config["name"].replace("TBG_Wall_", "")
    return {
        "name": f"TBG_{role.title()}_{family_title}",
        "base": family_config[f"{role}_base"],
        "accent": family_config[f"{role}_accent"],
        "border": family_config[f"{role}_border"],
    }


def _family_role_descriptor(family_kind: str, family: str, role: str) -> dict[str, object]:
    if family_kind == "brick":
        family_config = BRICK_FAMILIES[family]
        family_title = _family_title(family)
        params = _brick_role_params(family_config, role)
        if role == "wall":
            return {
                "tile_key": f"wall_{family.lower()}",
                "tile_name": f"TBG_Tile_Wall_{family_title}",
                "tile_kind": "brick",
                "tile_params": params,
                "repeat": True,
                "material_key": f"wall_{family.lower()}",
                "material_name": family_config["name"],
                "material_kind": "brick",
                "material_params": params,
            }
        return {
            "tile_key": f"{role}_{family.lower()}",
            "tile_name": f"TBG_Tile_{role.title()}_{family_title}",
            "tile_kind": "tone_border",
            "tile_params": params,
            "repeat": False,
            "material_key": f"{role}_{family.lower()}",
            "material_name": f"TBG_{role.title()}_{family_title}",
            "material_kind": "tone_border",
            "material_params": params,
        }

    family_config = FLAT_FACADE_FAMILIES[family]
    family_title = _family_title(family)
    params = _flat_role_params(family_config, role)
    if role == "wall":
        return {
            "tile_key": f"wall_{family.lower()}",
            "tile_name": f"TBG_Tile_{params['name']}",
            "tile_kind": "solid",
            "tile_params": params,
            "repeat": False,
            "material_key": f"wall_{family.lower()}",
            "material_name": params["name"],
            "material_kind": "principled",
            "material_params": params,
        }
    return {
        "tile_key": f"{role}_{family.lower()}",
        "tile_name": f"TBG_Tile_{role.title()}_{family_title}",
        "tile_kind": "tone_border",
        "tile_params": params,
        "repeat": False,
        "material_key": f"{role}_{family.lower()}",
        "material_name": params["name"],
        "material_kind": "tone_border",
        "material_params": params,
    }


def _append_tile(
    tile_specs: list[tuple[str, bpy.types.Image, bool, bool]],
    tile_key: str,
    image: bpy.types.Image,
    *,
    repeat: bool = False,
    preserve_aspect: bool = False,
) -> None:
    tile_specs.append((tile_key, image, repeat, preserve_aspect))


def _descriptor_row(
    *,
    material_key: str,
    material_kind: str,
    atlas_tile_key: str | None = None,
    material_name: str | None = None,
    material_params: dict[str, object] | None = None,
    tile_key: str | None = None,
    tile_kind: str | None = None,
    tile_name: str | None = None,
    tile_params: dict[str, object] | None = None,
    tile_repeat: bool = False,
    tile_preserve_aspect: bool = False,
    trim_section_bucket: str = OPENING_TRIM_SECTION_BUCKET_DEFAULT,
    backface_color: tuple[float, float, float, float] | None = None,
    uv_projection: str = UV_PROJECTION_BOUNDS,
    uv_inset: float = 0.0,
    alias_key: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "material_key": material_key,
        "material_kind": material_kind,
        "atlas_tile_key": atlas_tile_key,
        "trim_section_bucket": trim_section_bucket,
        "backface_color": backface_color,
        "uv_projection": uv_projection,
        "uv_inset": uv_inset,
        "alias_key": alias_key,
        "material_name": material_name,
        "material_params": material_params or {},
        "tile_key": tile_key,
        "tile_kind": tile_kind,
        "tile_name": tile_name,
        "tile_params": tile_params or {},
        "tile_repeat": tile_repeat,
        "tile_preserve_aspect": tile_preserve_aspect,
    }
    return row


def _static_material_descriptors() -> list[dict[str, object]]:
    light_brick = BRICK_FAMILIES["LIGHT_BRICK"]
    return [
        _descriptor_row(
            material_key="wall",
            material_kind="brick",
            atlas_tile_key="wall",
            material_name="TBG_Wall",
            material_params={
                "brick_a": light_brick["brick_a"],
                "brick_b": light_brick["brick_b"],
                "mortar": light_brick["mortar"],
                "scale": light_brick["scale"],
            },
            tile_key="wall",
            tile_kind="brick",
            tile_name="TBG_Tile_Wall",
            tile_params={
                "brick_a": light_brick["brick_a"],
                "brick_b": light_brick["brick_b"],
                "mortar": light_brick["mortar"],
            },
            tile_repeat=True,
            trim_section_bucket=OPENING_TRIM_SECTION_BUCKET_WALL,
        ),
        *(
            _descriptor_row(
                material_key=material_key,
                material_kind="solid_principled" if tile_key is None else "principled",
                atlas_tile_key=tile_key,
                material_name=material_name,
                material_params={
                    "color": tile_params.get("color", tile_params.get("base")),
                    "roughness": roughness,
                    "metallic": metallic,
                    "transmission": transmission,
                    "specular": specular,
                },
                tile_key=tile_key,
                tile_kind=tile_kind,
                tile_name=tile_name,
                tile_params=tile_params,
                tile_preserve_aspect=preserve_aspect,
            )
            for material_key, tile_key, material_name, tile_name, tile_kind, tile_params, roughness, metallic, transmission, specular, preserve_aspect in (
                (
                    "interior_wall",
                    "interior_wall",
                    "TBG_InteriorWall",
                    "TBG_Tile_InteriorWall",
                    "solid",
                    {"color": _INTERIOR_WALL_COLOR},
                    0.96,
                    0.0,
                    0.0,
                    None,
                    False,
                ),
                (
                    "floor",
                    "floor",
                    "TBG_Floor",
                    "TBG_Tile_Floor",
                    "solid",
                    {"color": (0.32, 0.32, 0.34, 1.0)},
                    0.95,
                    0.0,
                    0.0,
                    None,
                    False,
                ),
                (
                    "roof",
                    "roof",
                    "TBG_Roof",
                    "TBG_Tile_Roof",
                    "solid",
                    {"color": (0.28, 0.29, 0.31, 1.0)},
                    0.88,
                    0.0,
                    0.0,
                    None,
                    False,
                ),
                (
                    "stair",
                    "stair",
                    "TBG_Stair",
                    "TBG_Tile_Stair",
                    "solid",
                    {"color": (0.29, 0.24, 0.20, 1.0)},
                    0.36,
                    0.74,
                    0.0,
                    None,
                    False,
                ),
                (
                    "door",
                    "door",
                    "TBG_Door",
                    "TBG_Tile_Door",
                    "door",
                    {
                        "base": (0.33, 0.20, 0.12, 1.0),
                        "panel": (0.50, 0.51, 0.53, 1.0),
                        "outline": (0.22, 0.18, 0.15, 1.0),
                        "handle": (0.74, 0.75, 0.77, 1.0),
                    },
                    0.9,
                    0.0,
                    0.0,
                    0.08,
                    True,
                ),
                (
                    "window_fill",
                    None,
                    WINDOW_FILL_MATERIAL_NAME,
                    "TBG_Tile_WindowFill",
                    None,
                    {"color": WINDOW_FILL_EXPECTED_COLOR},
                    0.95,
                    0.0,
                    0.0,
                    0.04,
                    False,
                ),
                (
                    "glass",
                    "glass",
                    "TBG_Glass",
                    "TBG_Tile_Glass",
                    "solid",
                    {"color": (0.52, 0.68, 0.9, 1.0)},
                    0.2,
                    0.0,
                    0.04,
                    0.16,
                    False,
                ),
                (
                    "shutter",
                    "shutter",
                    "TBG_Shutter",
                    "TBG_Tile_Shutter",
                    "solid",
                    {"color": (0.41, 0.29, 0.21, 1.0)},
                    0.66,
                    0.0,
                    0.0,
                    None,
                    False,
                ),
                (
                    "prop",
                    "prop",
                    "TBG_Prop",
                    "TBG_Tile_Prop",
                    "solid",
                    {"color": (0.44, 0.46, 0.49, 1.0)},
                    0.58,
                    0.32,
                    0.0,
                    None,
                    False,
                ),
                (
                    "helper",
                    "helper",
                    "TBG_Helper",
                    "TBG_Tile_Helper",
                    "solid",
                    {"color": (0.12, 0.13, 0.14, 1.0)},
                    0.64,
                    0.0,
                    0.0,
                    None,
                    False,
                ),
            )
        ),
        _descriptor_row(
            material_key="trim",
            material_kind="tone_border",
            atlas_tile_key="trim",
            material_name="TBG_Trim",
            material_params={
                "base": (0.60, 0.52, 0.46, 1.0),
                "accent": (0.68, 0.60, 0.54, 1.0),
                "border": (0.36, 0.29, 0.24, 1.0),
                "roughness": 0.9,
                "specular": 0.08,
            },
            tile_key="trim",
            tile_kind="tone_border",
            tile_name="TBG_Tile_Trim",
            tile_params={
                "base": (0.60, 0.52, 0.46, 1.0),
                "accent": (0.68, 0.60, 0.54, 1.0),
                "border": (0.36, 0.29, 0.24, 1.0),
            },
        ),
        _descriptor_row(
            material_key="wood_floor",
            material_kind="tone_border",
            atlas_tile_key="wood_floor",
            material_name="TBG_WoodFloor",
            material_params={
                "base": (0.54, 0.39, 0.24, 1.0),
                "accent": (0.62, 0.46, 0.29, 1.0),
                "border": (0.33, 0.22, 0.13, 1.0),
                "roughness": 0.84,
                "specular": 0.07,
            },
            tile_key="wood_floor",
            tile_kind="tone_border",
            tile_name="TBG_Tile_WoodFloor",
            tile_params={
                "base": (0.54, 0.39, 0.24, 1.0),
                "accent": (0.62, 0.46, 0.29, 1.0),
                "border": (0.33, 0.22, 0.13, 1.0),
            },
        ),
        _descriptor_row(
            material_key="frame",
            material_kind="tone_border",
            atlas_tile_key="frame",
            material_name="TBG_Frame",
            material_params={
                "base": (0.58, 0.53, 0.48, 1.0),
                "accent": (0.64, 0.59, 0.54, 1.0),
                "border": (0.40, 0.35, 0.31, 1.0),
                "roughness": 0.84,
                "specular": 0.07,
            },
            tile_key="frame",
            tile_kind="tone_border",
            tile_name="TBG_Tile_Frame",
            tile_params={
                "base": (0.46, 0.34, 0.24, 1.0),
                "accent": (0.53, 0.40, 0.30, 1.0),
                "border": (0.24, 0.17, 0.12, 1.0),
            },
            uv_projection=UV_PROJECTION_FACE_FIT,
            uv_inset=0.12,
        ),
        _descriptor_row(
            material_key=_BASE_BALCONY_MATERIAL_KEY,
            material_kind="tone_border",
            atlas_tile_key=_BASE_BALCONY_MATERIAL_KEY,
            material_name="TBG_Balcony",
            material_params={
                "base": (0.70, 0.70, 0.70, 1.0),
                "accent": (0.67, 0.67, 0.67, 1.0),
                "border": (0.45, 0.45, 0.45, 1.0),
                "roughness": 0.82,
            },
            tile_key=_BASE_BALCONY_MATERIAL_KEY,
            tile_kind="tone_border",
            tile_name="TBG_Tile_Balcony",
            tile_params={
                "base": (0.70, 0.70, 0.70, 1.0),
                "accent": (0.67, 0.67, 0.67, 1.0),
                "border": (0.45, 0.45, 0.45, 1.0),
            },
        ),
        _descriptor_row(
            material_key="industrial_cladding",
            material_kind="principled",
            atlas_tile_key=INDUSTRIAL_CLADDING_ATLAS_KEY,
            material_name=INDUSTRIAL_CLADDING_MATERIAL_NAME,
            material_params={
                "color": (0.34, 0.38, 0.41, 1.0),
                "roughness": 0.52,
                "metallic": 0.24,
                "specular": 0.14,
            },
        ),
    ]


def _family_material_descriptors() -> list[dict[str, object]]:
    descriptors: list[dict[str, object]] = []
    for role in ("wall", "panel", "trim", "balcony"):
        for family in BRICK_FAMILIES:
            descriptor = _family_role_descriptor("brick", family, role)
            if role == "balcony":
                descriptors.append(
                    _descriptor_row(
                        material_key=descriptor["material_key"],
                        material_kind="alias",
                        alias_key=_BASE_BALCONY_MATERIAL_KEY,
                        tile_key=descriptor["tile_key"],
                        tile_kind=descriptor["tile_kind"],
                        tile_name=descriptor["tile_name"],
                        tile_params=descriptor["tile_params"],
                        tile_repeat=bool(descriptor["repeat"]),
                        atlas_tile_key=descriptor["tile_key"],
                    )
                )
                continue
            material_params = dict(descriptor["material_params"])
            trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_DEFAULT
            if role == "wall":
                trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_WALL
            elif role == "panel":
                material_params["roughness"] = 0.94
                material_params["specular"] = 0.06
                trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_PANEL
            else:
                material_params["roughness"] = 0.9
                material_params["specular"] = 0.08
            descriptors.append(
                _descriptor_row(
                    material_key=descriptor["material_key"],
                    material_kind=descriptor["material_kind"],
                    atlas_tile_key=descriptor["tile_key"],
                    material_name=descriptor["material_name"],
                    material_params=material_params,
                    tile_key=descriptor["tile_key"],
                    tile_kind=descriptor["tile_kind"],
                    tile_name=descriptor["tile_name"],
                    tile_params=descriptor["tile_params"],
                    tile_repeat=bool(descriptor["repeat"]),
                    trim_section_bucket=trim_section_bucket,
                    backface_color=descriptor.get("backface_color"),
                )
            )

    for role in ("wall", "panel", "trim"):
        for family in FLAT_FACADE_FAMILIES:
            descriptor = _family_role_descriptor("flat", family, role)
            material_params = dict(descriptor["material_params"])
            trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_DEFAULT
            if role == "wall":
                trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_WALL
            elif role == "panel":
                material_params["roughness"] = 0.94
                material_params["specular"] = 0.06
                trim_section_bucket = OPENING_TRIM_SECTION_BUCKET_PANEL
            else:
                material_params["roughness"] = 0.9
                material_params["specular"] = 0.08
            descriptors.append(
                _descriptor_row(
                    material_key=descriptor["material_key"],
                    material_kind=descriptor["material_kind"],
                    atlas_tile_key=descriptor["tile_key"],
                    material_name=descriptor["material_name"],
                    material_params=material_params,
                    tile_key=descriptor["tile_key"],
                    tile_kind=descriptor["tile_kind"],
                    tile_name=descriptor["tile_name"],
                    tile_params=descriptor["tile_params"],
                    tile_repeat=bool(descriptor["repeat"]),
                    trim_section_bucket=trim_section_bucket,
                    backface_color=descriptor.get("backface_color"),
                )
            )
    return descriptors


def _material_descriptors() -> list[dict[str, object]]:
    return [*_static_material_descriptors(), *_family_material_descriptors()]


def _preview_shade_color(color: tuple[float, float, float, float], offset: float) -> tuple[float, float, float, float]:
    return tuple(
        color[index] if index == 3 else max(0.0, min(1.0, float(color[index]) + float(offset)))
        for index in range(4)
    )


def _rgba_from_display_color(display_color_rgb: tuple[int, int, int] | dict[str, int] | None, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if isinstance(display_color_rgb, dict):
        channels = (display_color_rgb.get("r"), display_color_rgb.get("g"), display_color_rgb.get("b"))
    elif isinstance(display_color_rgb, (list, tuple)) and len(display_color_rgb) >= 3:
        channels = (display_color_rgb[0], display_color_rgb[1], display_color_rgb[2])
    else:
        return fallback
    try:
        return (
            max(0.0, min(1.0, float(channels[0]) / 255.0)),
            max(0.0, min(1.0, float(channels[1]) / 255.0)),
            max(0.0, min(1.0, float(channels[2]) / 255.0)),
            1.0,
        )
    except (TypeError, ValueError):
        return fallback


def _brick_family_key_from_display_color(
    display_color_rgb: tuple[int, int, int] | dict[str, int] | None,
) -> str:
    target = _rgba_from_display_color(display_color_rgb, BRICK_FAMILIES["LIGHT_BRICK"]["brick_a"])
    return min(
        BRICK_FAMILIES,
        key=lambda family_key: sum(
            (float(BRICK_FAMILIES[family_key]["brick_a"][index]) - target[index]) ** 2
            for index in range(3)
        ),
    )


def ensure_v3_wall_texture_preview_material(
    *,
    texture_key: str,
    material_family: str,
    visual_style: str | None,
    display_color_rgb: tuple[int, int, int] | dict[str, int] | None = None,
) -> bpy.types.Material:
    sanitized_key = "".join(char if char.isalnum() else "_" for char in str(texture_key or "wall_unknown")).strip("_")
    family = str(material_family or "").strip().upper()
    style = str(visual_style or "").strip().upper()
    if family == "BRICK" and style == "BRICK_MASONRY":
        brick_family_key = _brick_family_key_from_display_color(display_color_rgb)
        family_title = _family_title(brick_family_key)
        material_name = f"TBG_RBX_BasePartSim_Brick_{family_title}"
        return _ensure_brick_variant_sim_material(material_name, brick_family_key)

    color_suffix = ""
    if display_color_rgb is not None:
        if isinstance(display_color_rgb, dict):
            channels = (display_color_rgb.get("r"), display_color_rgb.get("g"), display_color_rgb.get("b"))
        else:
            channels = tuple(display_color_rgb[:3]) if isinstance(display_color_rgb, (list, tuple)) else ()
        if len(channels) >= 3:
            try:
                color_suffix = "_{:03d}_{:03d}_{:03d}".format(
                    max(0, min(255, int(round(float(channels[0]))))),
                    max(0, min(255, int(round(float(channels[1]))))),
                    max(0, min(255, int(round(float(channels[2]))))),
                )
            except (TypeError, ValueError):
                color_suffix = ""
    material_name = f"TBG_RBX_BasePartSim_{sanitized_key}{color_suffix}"
    if family == "WOOD":
        base = _rgba_from_display_color(display_color_rgb, (0.55, 0.42, 0.30, 1.0))
        return _ensure_solid_principled_material(
            material_name,
            _preview_shade_color(base, -0.01),
            roughness=0.86,
            specular=0.06,
            roblox_basepart_sim=True,
        )
    base = _rgba_from_display_color(display_color_rgb, (0.62, 0.62, 0.62, 1.0))
    return _ensure_solid_principled_material(
        material_name,
        base,
        roughness=0.9,
        specular=0.06,
        roblox_basepart_sim=True,
    )


def _descriptor_tile_image(descriptor: dict[str, object]) -> bpy.types.Image | None:
    tile_kind = descriptor["tile_kind"]
    if tile_kind is None:
        return None
    tile_name = str(descriptor["tile_name"])
    tile_params = descriptor["tile_params"]
    if tile_kind == "brick":
        return _ensure_brick_image(
            tile_name,
            brick_a=tile_params["brick_a"],
            brick_b=tile_params["brick_b"],
            mortar=tile_params["mortar"],
        )
    if tile_kind == "solid":
        return _ensure_solid_image(tile_name, color=tile_params["color"])
    if tile_kind == "door":
        return _ensure_door_image(
            tile_name,
            base=tile_params["base"],
            panel=tile_params["panel"],
            outline=tile_params["outline"],
            handle=tile_params["handle"],
        )
    if tile_kind == "tone_border":
        return _ensure_tone_border_image(
            tile_name,
            base=tile_params["base"],
            accent=tile_params["accent"],
            border=tile_params["border"],
        )
    raise RuntimeError(f"Unsupported tile descriptor kind: {tile_kind}")


def _append_descriptor_tiles(
    tile_specs: list[tuple[str, bpy.types.Image, bool, bool]],
    descriptors: list[dict[str, object]],
) -> None:
    seen_tile_keys: set[str] = set()
    for descriptor in descriptors:
        tile_key = descriptor["tile_key"]
        if tile_key is None or tile_key in seen_tile_keys:
            continue
        image = _descriptor_tile_image(descriptor)
        if image is None:
            continue
        _append_tile(
            tile_specs,
            tile_key,
            image,
            repeat=bool(descriptor["tile_repeat"]),
            preserve_aspect=bool(descriptor["tile_preserve_aspect"]),
        )
        seen_tile_keys.add(tile_key)


def _build_materials_from_descriptors(
    descriptors: list[dict[str, object]],
    atlas_image: bpy.types.Image,
    atlas_rects: dict[str, tuple[float, float, float, float]],
) -> dict[str, bpy.types.Material]:
    materials_map: dict[str, bpy.types.Material] = {}
    for descriptor in descriptors:
        material_key = str(descriptor["material_key"])
        material_kind = str(descriptor["material_kind"])
        if material_kind == "alias":
            materials_map[material_key] = materials_map[str(descriptor["alias_key"])]
            continue
        material_params = descriptor["material_params"]
        trim_section_bucket = str(descriptor["trim_section_bucket"])
        if material_kind == "solid_principled":
            materials_map[material_key] = _ensure_solid_principled_material(
                str(descriptor["material_name"]),
                material_params["color"],
                roughness=float(material_params["roughness"]),
                metallic=float(material_params.get("metallic", 0.0)),
                specular=material_params.get("specular"),
                trim_section_bucket=trim_section_bucket,
                roblox_basepart_sim=True,
            )
            continue
        atlas_tile_key = str(descriptor["atlas_tile_key"])
        uv_rect = atlas_rects[atlas_tile_key]
        if material_kind == "brick":
            materials_map[material_key] = _ensure_brick_material(
                str(descriptor["material_name"]),
                brick_a=material_params["brick_a"],
                brick_b=material_params["brick_b"],
                mortar=material_params["mortar"],
                scale=material_params["scale"],
                image=atlas_image,
                uv_rect=uv_rect,
                trim_section_bucket=trim_section_bucket,
            )
            continue
        if material_kind == "tone_border":
            materials_map[material_key] = _ensure_tone_border_material(
                str(descriptor["material_name"]),
                base=material_params["base"],
                accent=material_params["accent"],
                border=material_params["border"],
                roughness=float(material_params["roughness"]),
                specular=float(material_params.get("specular", 0.08)),
                image=atlas_image,
                uv_rect=uv_rect,
                uv_projection=str(descriptor["uv_projection"]),
                uv_inset=float(descriptor["uv_inset"]),
                trim_section_bucket=trim_section_bucket,
            )
            continue
        if material_kind == "principled":
            materials_map[material_key] = _ensure_principled_material(
                str(descriptor["material_name"]),
                material_params["color"],
                roughness=float(material_params["roughness"]),
                metallic=float(material_params.get("metallic", 0.0)),
                transmission=float(material_params.get("transmission", 0.0)),
                specular=material_params.get("specular"),
                image=atlas_image,
                backface_color=descriptor.get("backface_color"),
                uv_rect=uv_rect,
                uv_projection=str(descriptor["uv_projection"]),
                uv_inset=float(descriptor["uv_inset"]),
                trim_section_bucket=trim_section_bucket,
            )
            continue
        raise RuntimeError(f"Unsupported material descriptor kind: {material_kind}")
    return materials_map


def ensure_blockout_materials():
    descriptors = _material_descriptors()
    tile_specs: list[tuple[str, bpy.types.Image, bool, bool]] = []
    _append_descriptor_tiles(tile_specs, descriptors)
    atlas_image, atlas_rects = _build_texture_atlas(ATLAS_IMAGE_NAME, tile_specs)
    materials_map = _build_materials_from_descriptors(descriptors, atlas_image, atlas_rects)
    materials_map[_BASE_BALCONY_MATERIAL_KEY]["tbg_preserve_join_uv"] = True
    return materials_map
