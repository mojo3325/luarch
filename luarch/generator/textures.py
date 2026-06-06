from __future__ import annotations

import bpy
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import struct
import zlib


ATLAS_CELL_SIZE = 512
ATLAS_COLUMNS = 5
ATLAS_PADDING = 12
ATLAS_IMAGE_NAME = "TBG_Atlas_Image"
IMAGE_SIGNATURE_KEY = "tbg_signature"
ATLAS_RECTS_KEY = "tbg_atlas_rects_json"
MATERIAL_SIGNATURE_KEY = "tbg_material_signature"
CACHE_MANIFEST_NAME = "tbg_cache.json"

_TEXTURE_CACHE_MANIFEST: dict[str, dict[str, int | str]] | None = None


def _texture_dir() -> Path:
    root = Path(bpy.utils.user_resource("DATAFILES", path="luarch", create=True))
    texture_dir = root / "textures"
    texture_dir.mkdir(parents=True, exist_ok=True)
    return texture_dir


def _cache_manifest_path() -> Path:
    return _texture_dir() / CACHE_MANIFEST_NAME


def _texture_cache_manifest() -> dict[str, dict[str, int | str]]:
    global _TEXTURE_CACHE_MANIFEST
    if _TEXTURE_CACHE_MANIFEST is not None:
        return _TEXTURE_CACHE_MANIFEST

    manifest: dict[str, dict[str, int | str]] = {}
    path = _cache_manifest_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            for filename, entry in payload.items():
                if not isinstance(filename, str) or not isinstance(entry, dict):
                    continue
                try:
                    signature = str(entry["signature"])
                    width = int(entry["width"])
                    height = int(entry["height"])
                except (KeyError, TypeError, ValueError):
                    continue
                if signature and width > 0 and height > 0:
                    manifest[filename] = {
                        "signature": signature,
                        "width": width,
                        "height": height,
                    }

    _TEXTURE_CACHE_MANIFEST = manifest
    return _TEXTURE_CACHE_MANIFEST


def _write_texture_cache_manifest(manifest: dict[str, dict[str, int | str]]) -> None:
    path = _cache_manifest_path()
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


def _update_texture_cache_manifest(filename: str, *, signature: str, width: int, height: int) -> None:
    manifest = _texture_cache_manifest()
    entry: dict[str, int | str] = {
        "signature": signature,
        "width": int(width),
        "height": int(height),
    }
    if manifest.get(filename) == entry:
        return
    manifest[filename] = entry
    _write_texture_cache_manifest(manifest)


def _signature_for(*parts) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


def _expected_pixel_count(width: int, height: int) -> int:
    return max(1, int(width)) * max(1, int(height)) * 4


def _normalized_rgba_pixels(pixels_source, expected_count: int) -> list[float]:
    pixels = list(pixels_source)
    if len(pixels) == expected_count:
        return pixels
    if len(pixels) > expected_count:
        return pixels[:expected_count]
    fill = pixels[-4:] if len(pixels) >= 4 else [0.0, 0.0, 0.0, 1.0]
    padded = list(pixels)
    missing = expected_count - len(padded)
    while missing > 0:
        chunk = fill[: min(4, missing)]
        padded.extend(chunk)
        missing -= len(chunk)
    return padded


def _generated_image_is_complete(
    image: bpy.types.Image | None,
    *,
    signature: str,
    width: int,
    height: int,
) -> bool:
    if image is None or str(image.get(IMAGE_SIGNATURE_KEY, "")) != signature:
        return False
    if int(image.size[0]) != width or int(image.size[1]) != height:
        return False
    return len(image.pixels) == _expected_pixel_count(width, height)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def _write_png_rgba(path: Path, width: int, height: int, pixels: list[float]) -> None:
    pixels = _normalized_rgba_pixels(pixels, _expected_pixel_count(width, height))
    rows = []
    for y in range(height):
        start = y * width * 4
        row = bytearray([0])
        for offset in range(start, start + width * 4, 4):
            rgba = [
                max(0, min(255, int(round(pixels[offset + channel] * 255.0))))
                for channel in range(4)
            ]
            row.extend(rgba)
        rows.append(bytes(row))
    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_chunk(b"IHDR", ihdr)
    payload += _png_chunk(b"IDAT", zlib.compress(raw, level=9))
    payload += _png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def _load_image_from_path(
    name: str,
    path: Path,
    *,
    signature: str,
    width: int,
    height: int,
) -> bpy.types.Image | None:
    image = bpy.data.images.get(name)
    if image is not None:
        bpy.data.images.remove(image)
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
    except Exception:
        return None
    image.name = name
    image.colorspace_settings.name = "sRGB"
    image.alpha_mode = "STRAIGHT"
    image[IMAGE_SIGNATURE_KEY] = signature
    if int(image.size[0]) != width or int(image.size[1]) != height:
        bpy.data.images.remove(image)
        return None
    return image


def _load_texture_image(
    name: str,
    filename: str,
    width: int,
    height: int,
    pixels: list[float] | Callable[[], list[float]],
    *,
    signature: str,
) -> bpy.types.Image:
    existing = bpy.data.images.get(name)
    if _generated_image_is_complete(existing, signature=signature, width=width, height=height):
        return existing
    path = _texture_dir() / filename
    cache_entry = _texture_cache_manifest().get(filename)
    if (
        isinstance(cache_entry, dict)
        and str(cache_entry.get("signature", "")) == signature
        and int(cache_entry.get("width", 0)) == width
        and int(cache_entry.get("height", 0)) == height
        and path.is_file()
    ):
        image = _load_image_from_path(name, path, signature=signature, width=width, height=height)
        if image is not None:
            return image

    resolved_pixels = pixels() if callable(pixels) else pixels
    _write_png_rgba(path, width, height, resolved_pixels)
    image = _load_image_from_path(name, path, signature=signature, width=width, height=height)
    if image is None:
        raise RuntimeError(f"Failed to load generated texture image '{name}' from '{path}'.")
    _update_texture_cache_manifest(filename, signature=signature, width=width, height=height)
    return image


def _is_atlas_image(image: bpy.types.Image | None) -> bool:
    if image is None:
        return False
    return image.name == ATLAS_IMAGE_NAME or bool(str(image.get(ATLAS_RECTS_KEY, "")))


def _iter_object_images(objects) -> list[bpy.types.Image]:
    images: list[bpy.types.Image] = []
    seen: set[str] = set()
    for obj in objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        for slot in getattr(obj, "material_slots", ()):
            material = getattr(slot, "material", None)
            if material is None or material.node_tree is None:
                continue
            for node in material.node_tree.nodes:
                image = getattr(node, "image", None) if getattr(node, "type", "") == "TEX_IMAGE" else None
                if image is None or image.name in seen:
                    continue
                seen.add(image.name)
                images.append(image)
    return images


def resolve_export_atlas_image(root_obj) -> bpy.types.Image | None:
    if root_obj is not None:
        export_objects = [root_obj, *list(root_obj.children_recursive)]
        for image in _iter_object_images(export_objects):
            if _is_atlas_image(image):
                return image
    fallback = bpy.data.images.get(ATLAS_IMAGE_NAME)
    return fallback if _is_atlas_image(fallback) else None


def export_atlas_sidecar(root_obj, export_fbx_path: str | Path) -> tuple[Path, bpy.types.Image]:
    atlas_image = resolve_export_atlas_image(root_obj)
    if atlas_image is None:
        raise RuntimeError("Quick export could not find the generated TBG atlas image on the selected building.")

    width = max(1, int(atlas_image.size[0]))
    height = max(1, int(atlas_image.size[1]))
    pixels = list(atlas_image.pixels)
    expected_pixels = width * height * 4
    if len(pixels) != expected_pixels:
        raise RuntimeError(
            "Quick export could not serialize the generated TBG atlas image because its pixel buffer is incomplete."
        )

    export_path = Path(export_fbx_path)
    sidecar_dir = export_path.with_suffix(".fbm")
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = sidecar_dir / f"{ATLAS_IMAGE_NAME}.png"
    _write_png_rgba(sidecar_path, width, height, pixels)
    return sidecar_path, atlas_image


def _average_image_color(image: bpy.types.Image) -> tuple[float, float, float, float]:
    expected = _expected_pixel_count(image.size[0], image.size[1])
    pixels = _normalized_rgba_pixels(image.pixels, expected)
    count = max(1, len(pixels) // 4)
    rgba = [0.0, 0.0, 0.0, 0.0]
    for index in range(0, len(pixels), 4):
        rgba[0] += pixels[index]
        rgba[1] += pixels[index + 1]
        rgba[2] += pixels[index + 2]
        rgba[3] += pixels[index + 3]
    return tuple(channel / count for channel in rgba)


def _fill_rect(
    pixels: list[float],
    atlas_width: int,
    atlas_height: int,
    x0: int,
    y0: int,
    width: int,
    height: int,
    color: tuple[float, float, float, float],
) -> None:
    x1 = min(atlas_width, x0 + width)
    y1 = min(atlas_height, y0 + height)
    for py in range(max(0, y0), max(0, y1)):
        row = py * atlas_width * 4
        for px in range(max(0, x0), max(0, x1)):
            idx = row + px * 4
            pixels[idx : idx + 4] = color


def _blit_resampled(
    pixels: list[float],
    atlas_width: int,
    atlas_height: int,
    x0: int,
    y0: int,
    width: int,
    height: int,
    image: bpy.types.Image,
) -> None:
    src_width = max(1, int(image.size[0]))
    src_height = max(1, int(image.size[1]))
    src_pixels = _normalized_rgba_pixels(image.pixels, _expected_pixel_count(src_width, src_height))
    for py in range(height):
        src_y = min(src_height - 1, int(((py + 0.5) / max(1, height)) * src_height))
        row = (y0 + py) * atlas_width * 4
        src_row = src_y * src_width * 4
        for px in range(width):
            src_x = min(src_width - 1, int(((px + 0.5) / max(1, width)) * src_width))
            dst_idx = row + (x0 + px) * 4
            src_idx = src_row + src_x * 4
            pixels[dst_idx : dst_idx + 4] = src_pixels[src_idx : src_idx + 4]


def _blit_repeat_tile(
    pixels: list[float],
    atlas_width: int,
    atlas_height: int,
    cell_x: int,
    cell_y: int,
    image: bpy.types.Image,
    *,
    inset: int,
) -> None:
    src_width = max(1, int(image.size[0]))
    src_height = max(1, int(image.size[1]))
    src_pixels = _normalized_rgba_pixels(image.pixels, _expected_pixel_count(src_width, src_height))
    inner_size = max(1, ATLAS_CELL_SIZE - inset * 2)
    for py in range(ATLAS_CELL_SIZE):
        local_v = ((py - inset) + 0.5) / inner_size
        src_y = int((local_v % 1.0) * src_height) % src_height
        dst_row = (cell_y + py) * atlas_width * 4
        src_row = src_y * src_width * 4
        for px in range(ATLAS_CELL_SIZE):
            local_u = ((px - inset) + 0.5) / inner_size
            src_x = int((local_u % 1.0) * src_width) % src_width
            dst_idx = dst_row + (cell_x + px) * 4
            src_idx = src_row + src_x * 4
            pixels[dst_idx : dst_idx + 4] = src_pixels[src_idx : src_idx + 4]


def _fit_image_rect(
    image: bpy.types.Image,
    *,
    repeat: bool,
    preserve_aspect: bool,
) -> tuple[int, int, int, int]:
    if repeat:
        inner_width = max(1, ATLAS_CELL_SIZE - ATLAS_PADDING * 2)
        inner_height = max(1, ATLAS_CELL_SIZE - ATLAS_PADDING * 2)
        return ATLAS_PADDING, ATLAS_PADDING, inner_width, inner_height
    inner_width = max(1, ATLAS_CELL_SIZE - ATLAS_PADDING * 2)
    inner_height = max(1, ATLAS_CELL_SIZE - ATLAS_PADDING * 2)
    if not preserve_aspect:
        return ATLAS_PADDING, ATLAS_PADDING, inner_width, inner_height
    src_width = max(1, int(image.size[0]))
    src_height = max(1, int(image.size[1]))
    scale = min(inner_width / src_width, inner_height / src_height)
    fitted_width = max(1, int(round(src_width * scale)))
    fitted_height = max(1, int(round(src_height * scale)))
    offset_x = ATLAS_PADDING + (inner_width - fitted_width) // 2
    offset_y = ATLAS_PADDING + (inner_height - fitted_height) // 2
    return offset_x, offset_y, fitted_width, fitted_height


def _atlas_layout(
    tiles: list[tuple[str, bpy.types.Image, bool, bool]],
) -> tuple[int, int, list[tuple[str, bpy.types.Image, bool, int, int, int, int, int, int]], dict[str, tuple[float, float, float, float]]]:
    rows = max(1, (len(tiles) + ATLAS_COLUMNS - 1) // ATLAS_COLUMNS)
    atlas_width = ATLAS_COLUMNS * ATLAS_CELL_SIZE
    atlas_height = rows * ATLAS_CELL_SIZE
    placements: list[tuple[str, bpy.types.Image, bool, int, int, int, int, int, int]] = []
    rects: dict[str, tuple[float, float, float, float]] = {}

    for index, (tile_key, image, repeat, preserve_aspect) in enumerate(tiles):
        cell_x = (index % ATLAS_COLUMNS) * ATLAS_CELL_SIZE
        cell_y = (index // ATLAS_COLUMNS) * ATLAS_CELL_SIZE
        offset_x, offset_y, width, height = _fit_image_rect(image, repeat=repeat, preserve_aspect=preserve_aspect)
        dst_x = cell_x + offset_x
        dst_y = cell_y + offset_y
        placements.append((tile_key, image, repeat, cell_x, cell_y, dst_x, dst_y, width, height))
        rects[tile_key] = (
            dst_x / atlas_width,
            1.0 - ((dst_y + height) / atlas_height),
            (dst_x + width) / atlas_width,
            1.0 - (dst_y / atlas_height),
        )
    return atlas_width, atlas_height, placements, rects


def _build_texture_atlas(
    name: str,
    tiles: list[tuple[str, bpy.types.Image, bool, bool]],
) -> tuple[bpy.types.Image, dict[str, tuple[float, float, float, float]]]:
    atlas_width, atlas_height, placements, rects = _atlas_layout(tiles)
    signature = _signature_for(
        "atlas",
        ATLAS_CELL_SIZE,
        ATLAS_COLUMNS,
        ATLAS_PADDING,
        [
            (
                tile_key,
                str(image.get(IMAGE_SIGNATURE_KEY, "")),
                int(image.size[0]),
                int(image.size[1]),
                bool(repeat),
                bool(preserve_aspect),
            )
            for tile_key, image, repeat, preserve_aspect in tiles
        ],
    )
    existing = bpy.data.images.get(name)
    if _generated_image_is_complete(existing, signature=signature, width=atlas_width, height=atlas_height):
        payload = str(existing.get(ATLAS_RECTS_KEY, ""))
        if payload:
            try:
                stored = json.loads(payload)
                return existing, {key: tuple(value) for key, value in stored.items()}
            except Exception:
                pass

    def build_pixels() -> list[float]:
        pixels = [0.0] * (atlas_width * atlas_height * 4)
        for _tile_key, image, repeat, cell_x, cell_y, dst_x, dst_y, width, height in placements:
            background = _average_image_color(image)
            _fill_rect(pixels, atlas_width, atlas_height, cell_x, cell_y, ATLAS_CELL_SIZE, ATLAS_CELL_SIZE, background)
            if repeat:
                _blit_repeat_tile(
                    pixels,
                    atlas_width,
                    atlas_height,
                    cell_x,
                    cell_y,
                    image,
                    inset=ATLAS_PADDING,
                )
            else:
                _blit_resampled(pixels, atlas_width, atlas_height, dst_x, dst_y, width, height, image)
        return pixels

    atlas_image = _load_texture_image(
        name,
        f"{name}.png",
        atlas_width,
        atlas_height,
        build_pixels,
        signature=signature,
    )
    atlas_image[ATLAS_RECTS_KEY] = json.dumps(rects, sort_keys=True, separators=(",", ":"))
    return atlas_image, rects


def _hash01(*values: int) -> float:
    acc = 2166136261
    for value in values:
        acc ^= int(value) & 0xFFFFFFFF
        acc = (acc * 16777619) & 0xFFFFFFFF
    return acc / 4294967295.0


def _mix_color(a, b, fac: float):
    fac = max(0.0, min(1.0, fac))
    return tuple(a[idx] * (1.0 - fac) + b[idx] * fac for idx in range(4))


def _shade_color(color, offset: float):
    shaded = []
    for idx, channel in enumerate(color):
        if idx == 3:
            shaded.append(channel)
            continue
        shaded.append(max(0.0, min(1.0, channel + offset)))
    return tuple(shaded)


def _ensure_brick_image(
    name: str,
    *,
    brick_a: tuple[float, float, float, float],
    brick_b: tuple[float, float, float, float],
    mortar: tuple[float, float, float, float],
):
    signature = _signature_for("brick_cell_safe_v6_uniform_modules", brick_a, brick_b, mortar)
    width = 256
    height = 256
    mortar_px = 4
    row_count = 5
    row_h = height / row_count
    brick_w = 96.0
    mortar_soft_color = _mix_color(mortar, brick_a, 0.18)

    def build_pixels() -> list[float]:
        palette = (
            _shade_color(brick_a, -0.012),
            brick_a,
            brick_b,
            _mix_color(brick_a, brick_b, 0.4),
        )
        pixels = [0.0] * (width * height * 4)
        for y in range(height):
            row = min(row_count - 1, int(y / row_h))
            row_top = row * row_h
            y_in = (y + 0.5) - row_top
            # Keep a subtle horizontal bed joint at both tile edges. It prevents
            # stacked reset cells from visually merging into one tall brick, but
            # stays thinner/lower contrast than the old voxel-grid frame.
            horizontal_mortar = y_in <= mortar_px or y_in >= row_h - mortar_px
            stagger = brick_w * 0.5 if row % 2 else 0.0
            for x in range(width):
                # Roblox MaterialVariant restarts the tile on every BasePart.
                # Vertical edge borders stay brick-colored; only internal joints
                # are drawn so horizontal neighbors do not get a square frame.
                local_x = ((x + 0.5 + stagger) % brick_w)
                vertical_mortar = local_x <= mortar_px and x > mortar_px and x < width - mortar_px
                mortar_hit = horizontal_mortar or vertical_mortar
                if mortar_hit:
                    color = mortar_soft_color if horizontal_mortar and (y < mortar_px or y >= height - mortar_px) else mortar
                else:
                    col = int((x + 0.5 + stagger) // brick_w)
                    palette_idx = min(
                        len(palette) - 1,
                        int(_hash01(row, col, 13) * len(palette)),
                    )
                    row_drift = (_hash01(row, col, 23) - 0.5) * 0.01
                    color = _shade_color(palette[palette_idx], row_drift)
                idx = (y * width + x) * 4
                pixels[idx : idx + 4] = color
        return pixels

    return _load_texture_image(name, f"{name}.png", width, height, build_pixels, signature=signature)


def _ensure_tone_border_image(
    name: str,
    *,
    base: tuple[float, float, float, float],
    accent: tuple[float, float, float, float],
    border: tuple[float, float, float, float],
):
    signature = _signature_for("tone_border", base, accent, border)
    width = 96
    height = 96

    def build_pixels() -> list[float]:
        border_px = 7
        accent_ring = border_px + 12
        panel_ring = border_px + 28
        pixels = [0.0] * (width * height * 4)
        for y in range(height):
            for x in range(width):
                edge = min(x, y, width - 1 - x, height - 1 - y)
                if edge < border_px:
                    color = _mix_color(border, accent, 0.28)
                elif edge < accent_ring:
                    color = _mix_color(accent, base, 0.35)
                else:
                    if edge < panel_ring:
                        color = _mix_color(base, accent, 0.18)
                    else:
                        drift = (_hash01(x // 24, y // 24, 37) - 0.5) * 0.008
                        drift += (_hash01(x // 48, y // 48, 71) - 0.5) * 0.004
                        color = _shade_color(base, drift)
                idx = (y * width + x) * 4
                pixels[idx : idx + 4] = color
        return pixels

    return _load_texture_image(name, f"{name}.png", width, height, build_pixels, signature=signature)


def _ensure_door_image(
    name: str,
    *,
    base: tuple[float, float, float, float],
    panel: tuple[float, float, float, float],
    outline: tuple[float, float, float, float],
    handle: tuple[float, float, float, float],
):
    signature = _signature_for("door", base, panel, outline, handle)
    width = 128
    height = 256
    panel_left = 22
    panel_right = 106
    panel_bottom = 24
    panel_top = 224
    outline_px = 4
    handle_left = 92
    handle_right = 102
    handle_bottom = 102
    handle_top = 144
    grip_left = 84
    grip_right = 98
    grip_bottom = 120
    grip_top = 126

    def build_pixels() -> list[float]:
        pixels = list(base) * (width * height)
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 4
                color = base
                if panel_left <= x < panel_right and panel_bottom <= y < panel_top:
                    on_panel_edge = (
                        x < panel_left + outline_px
                        or x >= panel_right - outline_px
                        or y < panel_bottom + outline_px
                        or y >= panel_top - outline_px
                    )
                    color = outline if on_panel_edge else panel
                if handle_left <= x < handle_right and handle_bottom <= y < handle_top:
                    color = outline
                if grip_left <= x < grip_right and grip_bottom <= y < grip_top:
                    color = handle
                pixels[idx : idx + 4] = color
        return pixels

    return _load_texture_image(name, f"{name}.png", width, height, build_pixels, signature=signature)


def _ensure_solid_image(
    name: str,
    *,
    color: tuple[float, float, float, float],
):
    signature = _signature_for("solid", color)
    width = 8
    height = 8
    return _load_texture_image(
        name,
        f"{name}.png",
        width,
        height,
        lambda: list(color) * (width * height),
        signature=signature,
    )
