#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy
from mathutils import Vector

from luarch import presets
from luarch.generator.building import build_building
from luarch.generator.specs import building_spec_from_mapping


MEDIA_DIR = ROOT / "docs" / "media"
HERO_WIDE_PATH = MEDIA_DIR / "hero-wide.png"
GALLERY_GRID_PATH = MEDIA_DIR / "gallery-grid-3x3.png"


HERO_PRESETS = (
    "house_small",
    "house_wide",
    "wood_house",
    "wood_rowhouse",
    "townhouse",
    "apartment_lowrise",
    "apartment_midrise",
    "depot",
    "market_hall",
    "warehouse",
    "hangar",
    "depot",
    "house_small",
    "house_wide",
    "wood_house",
    "townhouse",
)

INTERIOR_CARDS = (
    ("Townhouse Cutaway", "townhouse", 2100, "gallery-interior-townhouse.png"),
    ("Rowhouse Stairs", "wood_rowhouse", 2137, "gallery-interior-rowhouse.png"),
    ("Lowrise Core", "apartment_lowrise", 2174, "gallery-interior-lowrise.png"),
    ("Midrise Core", "apartment_midrise", 2211, "gallery-interior-midrise.png"),
    ("Wood House Interior", "wood_house", 2248, "gallery-interior-wood-house.png"),
    ("Wide House Interior", "house_wide", 2285, "gallery-interior-wide-house.png"),
    ("Townhouse Variant", "townhouse", 2322, "gallery-interior-townhouse-variant.png"),
    ("Apartment Variant", "apartment_lowrise", 2359, "gallery-interior-apartment-variant.png"),
    ("Rowhouse Variant", "wood_rowhouse", 2396, "gallery-interior-rowhouse-variant.png"),
)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in list(bpy.data.collections):
        if not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)


def generate_buildings(preset_ids: tuple[str, ...], *, spacing_x: float, spacing_y: float) -> list[object]:
    presets.ensure_loaded(force=True)
    roots: list[object] = []
    columns = 4
    rows = math.ceil(len(preset_ids) / columns)
    start_x = -spacing_x * (columns - 1) * 0.5
    start_y = spacing_y * (rows - 1) * 0.5
    for index, preset_id in enumerate(preset_ids):
        row = index // 4
        col = index % 4
        seed = 1200 + index * 37
        payload = presets.build_randomized_payload(preset_id, seed)
        if preset_id == "hangar":
            payload["width"] = max(float(payload.get("width", 16.0)), 18.0)
            payload["depth"] = max(float(payload.get("depth", 14.0)), 18.0)
        origin = (start_x + col * spacing_x, start_y - row * spacing_y, 0.0)
        before = set(bpy.data.objects)
        spec = building_spec_from_mapping(payload, building_id=f"{index + 1:03d}", origin=origin)
        try:
            root = build_building(bpy.context, spec, suppress_viewport_emit=True)
        except Exception as exc:
            for obj in [obj for obj in bpy.data.objects if obj not in before]:
                bpy.data.objects.remove(obj, do_unlink=True)
            print(f"Skipping preset {preset_id}: {exc}")
            continue
        roots.append(root)
    return roots


def generate_building(preset_id: str, *, seed: int, building_id: str = "001") -> object:
    presets.ensure_loaded(force=True)
    payload = presets.build_randomized_payload(preset_id, seed)
    if preset_id == "hangar":
        payload["width"] = max(float(payload.get("width", 16.0)), 18.0)
        payload["depth"] = max(float(payload.get("depth", 14.0)), 18.0)
    spec = building_spec_from_mapping(payload, building_id=building_id, origin=(0.0, 0.0, 0.0))
    return build_building(bpy.context, spec, suppress_viewport_emit=True)


def mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def hide_wall_sections(root) -> None:
    for obj in root.children_recursive:
        if obj.type == "MESH" and obj.get("tbg_hide_with_walls"):
            obj.hide_viewport = True
            obj.hide_render = True
    root["tbg_walls_hidden"] = True


def bounds_for(objects):
    points = []
    for obj in objects:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    if not points:
        return Vector((-10, -10, 0)), Vector((10, 10, 10))
    return (
        Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
        Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))),
    )


def look_at(obj, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure_scene() -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.25
    scene.view_settings.gamma = 1.0
    scene.world = scene.world or bpy.data.worlds.new("LuArchWorld")
    scene.world.color = (0.18, 0.19, 0.21)

    light_data = bpy.data.lights.new("LuArch_Key_Area", "AREA")
    light = bpy.data.objects.new("LuArch_Key_Area", light_data)
    bpy.context.scene.collection.objects.link(light)
    light.location = (0, -70, 95)
    light_data.energy = 4200
    light_data.size = 95

    sun_data = bpy.data.lights.new("LuArch_Sun", "SUN")
    sun = bpy.data.objects.new("LuArch_Sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0, math.radians(34))
    sun_data.energy = 2.2


def render_to(path: Path, *, resolution: tuple[int, int], ortho_scale: float, location: tuple[float, float, float], target: Vector) -> None:
    camera_data = bpy.data.cameras.new(f"{path.stem}_Camera")
    camera = bpy.data.objects.new(f"{path.stem}_Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = Vector(location)
    look_at(camera, target)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = ortho_scale
    camera_data.clip_end = 2000

    scene = bpy.context.scene
    scene.camera = camera
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print(path)


def render_hero() -> None:
    bpy.context.view_layer.update()
    objects = mesh_objects()
    bounds_min, bounds_max = bounds_for(objects)
    center = (bounds_min + bounds_max) * 0.5
    size = bounds_max - bounds_min
    span = max(size.x, size.y, size.z, 1.0)

    render_to(
        HERO_WIDE_PATH,
        resolution=(1800, 850),
        ortho_scale=max(size.x, size.y) * 0.92,
        location=(center.x + span * 0.56, center.y - span * 0.92, center.z + span * 0.74),
        target=center + Vector((0, 0, size.z * 0.12)),
    )


def render_interior_card(path: Path) -> None:
    bpy.context.view_layer.update()
    objects = [obj for obj in mesh_objects() if not obj.hide_render and not obj.hide_viewport]
    bounds_min, bounds_max = bounds_for(objects)
    center = (bounds_min + bounds_max) * 0.5
    size = bounds_max - bounds_min
    span = max(size.x, size.y, size.z, 1.0)
    render_to(
        path,
        resolution=(900, 675),
        ortho_scale=max(size.x, size.y, size.z * 1.15) * 1.28,
        location=(center.x + span * 0.72, center.y - span * 0.92, center.z + span * 0.84),
        target=center + Vector((0, 0, size.z * 0.18)),
    )


def chrome_path() -> str:
    configured = os.environ.get("CHROME_PATH")
    if configured:
        return configured
    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def write_gallery_grid(cards: list[tuple[str, Path]], path: Path) -> None:
    card_markup = []
    for label, image_path in cards:
        card_markup.append(
            f'<figure><img src="{image_path.resolve().as_uri()}" alt="{label}"><figcaption>{label}</figcaption></figure>'
        )
    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0;
    background: #202123;
    width: 1800px;
    height: 1640px;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
.grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    padding: 42px;
}}
figure {{
    margin: 0;
    background: #2b2d30;
    border: 1px solid #3b3d42;
    border-radius: 18px;
    overflow: hidden;
    box-shadow: 0 18px 42px rgba(0,0,0,0.28);
}}
img {{
    display: block;
    width: 100%;
    height: auto;
}}
figcaption {{
    color: #f0f3f6;
    font-size: 31px;
    font-weight: 650;
    padding: 18px 24px 22px;
    letter-spacing: 0.2px;
}}
</style>
</head>
<body><main class="grid">{''.join(card_markup)}</main></body>
</html>"""
    html_path = Path(tempfile.gettempdir()) / "luarch-gallery-grid.html"
    html_path.write_text(html, encoding="utf-8")
    subprocess.run(
        [
            chrome_path(),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--window-size=1800,1640",
            f"--screenshot={path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
    )
    print(path)


def main() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    clear_scene()
    configure_scene()
    generate_buildings(HERO_PRESETS, spacing_x=54.0, spacing_y=48.0)
    render_hero()

    with tempfile.TemporaryDirectory(prefix="luarch-media-") as tmp:
        tmp_dir = Path(tmp)
        rendered_cards: list[tuple[str, Path]] = []
        for index, (label, preset_id, seed, filename) in enumerate(INTERIOR_CARDS, start=1):
            clear_scene()
            configure_scene()
            root = generate_building(preset_id, seed=seed, building_id=f"I{index:02d}")
            hide_wall_sections(root)
            card_path = tmp_dir / filename
            render_interior_card(card_path)
            rendered_cards.append((label, card_path))
        write_gallery_grid(rendered_cards, GALLERY_GRID_PATH)


if __name__ == "__main__":
    main()
