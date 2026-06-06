from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .. import export_contract

_OCCUPANCY_COORD_PRECISION = 4
_MIN_FRAGMENT_SPAN = 1e-4
_OVERLAP_EPSILON = 1e-6
_WALL_NORMAL_AXES = ("x", "y")
PACK_CELL_STUDS = 0.75
MIN_NON_THICKNESS_CELL_SPAN_STUDS = 0.35
OPENING_VISUAL_CLEARANCE_STUDS = 0.05
_BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36_token(index: int) -> str:
    value = int(index)
    if value <= 0:
        raise ValueError("Compact wall-cell ids require positive 1-based indexes.")
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits))


def _compact_group_id(index: int) -> str:
    return f"g{_base36_token(index)}"


def _compact_cell_id(index: int) -> str:
    return f"c{_base36_token(index)}"


def _round_coord(value: float) -> float:
    return round(float(value), _OCCUPANCY_COORD_PRECISION)


def _normalize_optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_required_text(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must not be empty.")
    return text


def _normalize_color(color: object) -> tuple[int, int, int] | None:
    if color is None:
        return None
    if isinstance(color, dict):
        channels = (color.get("r"), color.get("g"), color.get("b"))
    else:
        channels = tuple(color) if isinstance(color, (list, tuple)) else ()
    if len(channels) != 3:
        raise ValueError("display_color_rgb must contain exactly three channels.")
    normalized: list[int] = []
    for channel in channels:
        value = int(channel)
        if value < 0 or value > 255:
            raise ValueError("display_color_rgb channels must stay within 0..255.")
        normalized.append(value)
    return (normalized[0], normalized[1], normalized[2])


def _normalize_origin_float(value: object) -> float:
    if value is None:
        return 0.0
    return _round_coord(float(value))


def _normalize_wall_normal_axis(value: object) -> str:
    axis = str(value or "").strip().lower()
    if axis not in _WALL_NORMAL_AXES:
        raise ValueError("Atomic wall fragment normal_axis must be 'x' or 'y'.")
    return axis


def _run_axis_for_normal_axis(normal_axis: str) -> str:
    axis = _normalize_wall_normal_axis(normal_axis)
    return "y" if axis == "x" else "x"


def _normalize_staged_object_names(names: Iterable[object] | None) -> tuple[str, ...]:
    if names is None:
        return ()
    normalized: list[str] = []
    for name in names:
        label = str(name or "").strip()
        if label:
            normalized.append(label)
    return tuple(sorted(set(normalized)))


def _normalize_source_bucket(source_bucket: object) -> str:
    bucket = _normalize_required_text(source_bucket, label="source_bucket")
    if bucket not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
        allowed = ", ".join(sorted(export_contract.VOXEL_WALL_SOURCE_BUCKETS))
        raise ValueError(f"source_bucket must be one of: {allowed}.")
    return bucket


def _normalize_material_family(material_family: object) -> str:
    family = _normalize_required_text(material_family, label="material_family").upper()
    if family not in export_contract.VOXEL_WALL_MATERIAL_FAMILIES:
        allowed = ", ".join(sorted(export_contract.VOXEL_WALL_MATERIAL_FAMILIES))
        raise ValueError(f"material_family must be one of: {allowed}.")
    return family


def _normalize_visual_style(visual_style: object) -> str | None:
    normalized = _normalize_optional_text(visual_style)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if normalized not in export_contract.VOXEL_WALL_VISUAL_STYLES:
        allowed = ", ".join(sorted(export_contract.VOXEL_WALL_VISUAL_STYLES))
        raise ValueError(f"visual_style must be one of: {allowed}.")
    return normalized



def _texture_key_for_material(material_family: str, visual_style: str | None) -> str:
    family = str(material_family or "").strip().upper() or "UNKNOWN"
    style = str(visual_style or "SOLID").strip().upper() or "SOLID"
    return "wall_" + family.lower() + "_" + style.lower()


def _texture_projection_for_material(material_family: str, visual_style: str | None) -> str:
    family = str(material_family or "").strip().upper()
    if family in export_contract.TEXTURED_VOXEL_WALL_MATERIAL_FAMILIES and str(visual_style or "").strip():
        return export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
    return export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1


def _texture_studs_per_tile_for_material(material_family: str, visual_style: str | None) -> float:
    family = str(material_family or "").strip().upper()
    if family == "BRICK":
        return float(export_contract.BRICK_TEXTURE_STUDS_PER_TILE)
    return float(export_contract.DEFAULT_TEXTURE_STUDS_PER_TILE)


def _normalize_texture_projection(value: object, material_family: str, visual_style: str | None) -> str:
    text = str(value or "").strip().upper()
    if not text:
        text = _texture_projection_for_material(material_family, visual_style)
    if text not in export_contract.TEXTURE_PROJECTIONS:
        allowed = ", ".join(export_contract.TEXTURE_PROJECTIONS)
        raise ValueError(f"texture_projection must be one of: {allowed}.")
    return text


def _normalize_texture_period_contract(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        text = export_contract.TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE
    if text not in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS:
        allowed = ", ".join(export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS)
        raise ValueError(f"texture_image_period_contract must be one of: {allowed}.")
    return text


def _normalize_texture_face_axis_table_version(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        text = export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1
    if text != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1:
        raise ValueError("texture_face_axis_table_version must be TEXTURE_FACE_AXIS_TABLE_V1.")
    return text


def _normalize_positive_texture_period(value: object, material_family: str, visual_style: str | None) -> float:
    if value is None:
        value = _texture_studs_per_tile_for_material(material_family, visual_style)
    period = _round_coord(float(value))
    if period <= 0.0:
        raise ValueError("texture studs-per-tile values must be positive.")
    return period


def _normalize_color_modulation_policy(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        text = export_contract.COLOR_MODULATION_POLICY_NONE
    if text != export_contract.COLOR_MODULATION_POLICY_NONE:
        raise ValueError("color_modulation_policy must be NONE for V3 wall texture contracts.")
    return text


def _normalized_session_token(*parts: object) -> str:
    combined = "_".join(str(part or "").strip() for part in parts if str(part or "").strip())
    sanitized = "".join(char if char.isalnum() else "_" for char in combined)
    sanitized = sanitized.strip("_")
    return sanitized or "Occupancy"


def _sort_unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _positive_interval_overlap(left_min: float, left_max: float, right_min: float, right_max: float) -> bool:
    return min(left_max, right_max) - max(left_min, right_min) > _OVERLAP_EPSILON


def _metadata_sort_key(key: tuple[object, ...]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value) for value in key)


def _serialize_vector3(values: tuple[float, float, float]) -> dict[str, float]:
    return {
        "x": _round_coord(values[0]),
        "y": _round_coord(values[1]),
        "z": _round_coord(values[2]),
    }


def _serialize_color(color: tuple[int, int, int] | None) -> dict[str, int] | None:
    if color is None:
        return None
    return {"r": int(color[0]), "g": int(color[1]), "b": int(color[2])}


@dataclass(frozen=True)
class RootLocalWallBounds:
    x_min: float
    y_min: float
    z_min: float
    x_max: float
    y_max: float
    z_max: float

    def __post_init__(self) -> None:
        normalized = (
            _round_coord(self.x_min),
            _round_coord(self.y_min),
            _round_coord(self.z_min),
            _round_coord(self.x_max),
            _round_coord(self.y_max),
            _round_coord(self.z_max),
        )
        if normalized[3] - normalized[0] <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Atomic wall fragment width must be greater than zero.")
        if normalized[4] - normalized[1] <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Atomic wall fragment depth must be greater than zero.")
        if normalized[5] - normalized[2] <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Atomic wall fragment height must be greater than zero.")
        object.__setattr__(self, "x_min", normalized[0])
        object.__setattr__(self, "y_min", normalized[1])
        object.__setattr__(self, "z_min", normalized[2])
        object.__setattr__(self, "x_max", normalized[3])
        object.__setattr__(self, "y_max", normalized[4])
        object.__setattr__(self, "z_max", normalized[5])

    @classmethod
    def from_bounds(cls, bounds: Sequence[float]) -> "RootLocalWallBounds":
        values = tuple(float(value) for value in bounds)
        if len(values) != 6:
            raise ValueError("Root-local wall bounds must contain exactly 6 floats.")
        return cls(*values)

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.x_min, self.y_min, self.z_min, self.x_max, self.y_max, self.z_max)

    def sort_key(self) -> tuple[float, float, float, float, float, float]:
        return self.as_tuple()

    def min_studs(self) -> tuple[float, float, float]:
        return (self.x_min, self.y_min, self.z_min)

    def size_studs(self) -> tuple[float, float, float]:
        return (
            _round_coord(self.x_max - self.x_min),
            _round_coord(self.y_max - self.y_min),
            _round_coord(self.z_max - self.z_min),
        )

    def overlaps_positive_volume(self, other: "RootLocalWallBounds") -> bool:
        return (
            min(self.x_max, other.x_max) - max(self.x_min, other.x_min) > _OVERLAP_EPSILON
            and min(self.y_max, other.y_max) - max(self.y_min, other.y_min) > _OVERLAP_EPSILON
            and min(self.z_max, other.z_max) - max(self.z_min, other.z_min) > _OVERLAP_EPSILON
        )


@dataclass(frozen=True)
class AtomicWallFragment:
    bounds: RootLocalWallBounds
    source_bucket: str
    material_family: str
    normal_axis: str
    visual_style: str | None = None
    display_color_rgb: tuple[int, int, int] | None = None
    surface_u_origin_studs: float | None = None
    surface_v_origin_studs: float | None = None
    texture_key: str | None = None
    texture_projection: str | None = None
    texture_image_period_contract: str | None = None
    texture_face_axis_table_version: str | None = None
    studs_per_tile_u: float | None = None
    studs_per_tile_v: float | None = None
    color_modulation_policy: str | None = None
    source_name: str = ""
    staged_object_names: tuple[str, ...] = ()
    fragment_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_bucket", _normalize_source_bucket(self.source_bucket))
        object.__setattr__(self, "material_family", _normalize_material_family(self.material_family))
        object.__setattr__(self, "normal_axis", _normalize_wall_normal_axis(self.normal_axis))
        object.__setattr__(self, "visual_style", _normalize_visual_style(self.visual_style))
        object.__setattr__(self, "display_color_rgb", _normalize_color(self.display_color_rgb))
        object.__setattr__(self, "surface_u_origin_studs", _normalize_origin_float(self.surface_u_origin_studs))
        object.__setattr__(self, "surface_v_origin_studs", _normalize_origin_float(self.surface_v_origin_studs))
        texture_key = str(self.texture_key or _texture_key_for_material(self.material_family, self.visual_style)).strip()
        object.__setattr__(self, "texture_key", texture_key)
        object.__setattr__(self, "texture_projection", _normalize_texture_projection(self.texture_projection, self.material_family, self.visual_style))
        object.__setattr__(self, "texture_image_period_contract", _normalize_texture_period_contract(self.texture_image_period_contract))
        object.__setattr__(self, "texture_face_axis_table_version", _normalize_texture_face_axis_table_version(self.texture_face_axis_table_version))
        object.__setattr__(self, "studs_per_tile_u", _normalize_positive_texture_period(self.studs_per_tile_u, self.material_family, self.visual_style))
        object.__setattr__(self, "studs_per_tile_v", _normalize_positive_texture_period(self.studs_per_tile_v, self.material_family, self.visual_style))
        object.__setattr__(self, "color_modulation_policy", _normalize_color_modulation_policy(self.color_modulation_policy))
        object.__setattr__(self, "source_name", str(self.source_name or "").strip())
        object.__setattr__(self, "staged_object_names", _normalize_staged_object_names(self.staged_object_names))
        object.__setattr__(self, "fragment_id", str(self.fragment_id or "").strip())

    @classmethod
    def from_bounds(
        cls,
        bounds: Sequence[float],
        *,
        source_bucket: str,
        material_family: str,
        normal_axis: str,
        visual_style: str | None = None,
        display_color_rgb: Sequence[int] | dict[str, int] | None = None,
        surface_u_origin_studs: float | None = None,
        surface_v_origin_studs: float | None = None,
        texture_key: str | None = None,
        texture_projection: str | None = None,
        texture_image_period_contract: str | None = None,
        texture_face_axis_table_version: str | None = None,
        studs_per_tile_u: float | None = None,
        studs_per_tile_v: float | None = None,
        color_modulation_policy: str | None = None,
        source_name: str = "",
        staged_object_names: Iterable[str] | None = None,
        fragment_id: str = "",
    ) -> "AtomicWallFragment":
        return cls(
            bounds=RootLocalWallBounds.from_bounds(bounds),
            source_bucket=source_bucket,
            material_family=material_family,
            normal_axis=normal_axis,
            visual_style=visual_style,
            display_color_rgb=display_color_rgb,
            surface_u_origin_studs=surface_u_origin_studs,
            surface_v_origin_studs=surface_v_origin_studs,
            texture_key=texture_key,
            texture_projection=texture_projection,
            texture_image_period_contract=texture_image_period_contract,
            texture_face_axis_table_version=texture_face_axis_table_version,
            studs_per_tile_u=studs_per_tile_u,
            studs_per_tile_v=studs_per_tile_v,
            color_modulation_policy=color_modulation_policy,
            source_name=source_name,
            staged_object_names=tuple(staged_object_names or ()),
            fragment_id=fragment_id,
        )

    @classmethod
    def from_center_size(
        cls,
        *,
        center: Sequence[float],
        size: Sequence[float],
        source_bucket: str,
        material_family: str,
        normal_axis: str,
        visual_style: str | None = None,
        display_color_rgb: Sequence[int] | dict[str, int] | None = None,
        surface_u_origin_studs: float | None = None,
        surface_v_origin_studs: float | None = None,
        texture_key: str | None = None,
        texture_projection: str | None = None,
        texture_image_period_contract: str | None = None,
        texture_face_axis_table_version: str | None = None,
        studs_per_tile_u: float | None = None,
        studs_per_tile_v: float | None = None,
        color_modulation_policy: str | None = None,
        source_name: str = "",
        staged_object_names: Iterable[str] | None = None,
        fragment_id: str = "",
    ) -> "AtomicWallFragment":
        center_values = tuple(float(value) for value in center)
        size_values = tuple(float(value) for value in size)
        if len(center_values) != 3:
            raise ValueError("Atomic wall fragment center must contain exactly 3 floats.")
        if len(size_values) != 3:
            raise ValueError("Atomic wall fragment size must contain exactly 3 floats.")
        half_x = size_values[0] / 2.0
        half_y = size_values[1] / 2.0
        half_z = size_values[2] / 2.0
        return cls.from_bounds(
            (
                center_values[0] - half_x,
                center_values[1] - half_y,
                center_values[2] - half_z,
                center_values[0] + half_x,
                center_values[1] + half_y,
                center_values[2] + half_z,
            ),
            source_bucket=source_bucket,
            material_family=material_family,
            normal_axis=normal_axis,
            visual_style=visual_style,
            display_color_rgb=display_color_rgb,
            surface_u_origin_studs=surface_u_origin_studs,
            surface_v_origin_studs=surface_v_origin_studs,
            texture_key=texture_key,
            texture_projection=texture_projection,
            texture_image_period_contract=texture_image_period_contract,
            texture_face_axis_table_version=texture_face_axis_table_version,
            studs_per_tile_u=studs_per_tile_u,
            studs_per_tile_v=studs_per_tile_v,
            color_modulation_policy=color_modulation_policy,
            source_name=source_name,
            staged_object_names=staged_object_names,
            fragment_id=fragment_id,
        )

    def with_fragment_id(self, fragment_id: str) -> "AtomicWallFragment":
        return AtomicWallFragment(
            bounds=self.bounds,
            source_bucket=self.source_bucket,
            material_family=self.material_family,
            normal_axis=self.normal_axis,
            visual_style=self.visual_style,
            display_color_rgb=self.display_color_rgb,
            surface_u_origin_studs=self.surface_u_origin_studs,
            surface_v_origin_studs=self.surface_v_origin_studs,
            texture_key=self.texture_key,
            texture_projection=self.texture_projection,
            texture_image_period_contract=self.texture_image_period_contract,
            texture_face_axis_table_version=self.texture_face_axis_table_version,
            studs_per_tile_u=self.studs_per_tile_u,
            studs_per_tile_v=self.studs_per_tile_v,
            color_modulation_policy=self.color_modulation_policy,
            source_name=self.source_name,
            staged_object_names=self.staged_object_names,
            fragment_id=fragment_id,
        )

    def metadata_key(self) -> tuple[object, ...]:
        return (
            self.source_bucket,
            self.material_family,
            self.normal_axis,
            self.visual_style or "",
            self.display_color_rgb,
            self.surface_u_origin_studs,
            self.surface_v_origin_studs,
            self.texture_key,
            self.texture_projection,
            self.texture_image_period_contract,
            self.texture_face_axis_table_version,
            self.studs_per_tile_u,
            self.studs_per_tile_v,
            self.color_modulation_policy,
        )

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.metadata_key(),
            self.bounds.sort_key(),
            self.source_name,
            self.fragment_id,
            self.staged_object_names,
        )

    def to_debug_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "fragment_id": self.fragment_id,
            "source_bucket": self.source_bucket,
            "material_family": self.material_family,
            "normal_axis": self.normal_axis,
            "run_axis": self.run_axis,
            "bounds": list(self.bounds.as_tuple()),
            "staged_object_names": list(self.staged_object_names),
        }
        if self.visual_style is not None:
            payload["visual_style"] = self.visual_style
        if self.display_color_rgb is not None:
            payload["display_color_rgb"] = _serialize_color(self.display_color_rgb)
        if self.surface_u_origin_studs is not None:
            payload["surface_u_origin_studs"] = self.surface_u_origin_studs
        if self.surface_v_origin_studs is not None:
            payload["surface_v_origin_studs"] = self.surface_v_origin_studs
        if self.source_name:
            payload["source_name"] = self.source_name
        return payload

    @property
    def run_axis(self) -> str:
        return _run_axis_for_normal_axis(self.normal_axis)


@dataclass(frozen=True)
class WallPlaneRectCut:
    kind: str
    run_min: float
    run_max: float
    z_min: float
    z_max: float
    clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS

    def __post_init__(self) -> None:
        kind = _normalize_required_text(self.kind, label="cut kind")
        clearance = max(0.0, float(self.clearance_studs))
        run_min = _round_coord(float(self.run_min) - clearance)
        run_max = _round_coord(float(self.run_max) + clearance)
        z_min = _round_coord(float(self.z_min) - clearance)
        z_max = _round_coord(float(self.z_max) + clearance)
        if run_max - run_min <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Wall-plane rectangular cut run span must be positive.")
        if z_max - z_min <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Wall-plane rectangular cut Z span must be positive.")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "run_min", run_min)
        object.__setattr__(self, "run_max", run_max)
        object.__setattr__(self, "z_min", z_min)
        object.__setattr__(self, "z_max", z_max)
        object.__setattr__(self, "clearance_studs", _round_coord(clearance))

    def overlaps_cell(self, run_min: float, run_max: float, z_min: float, z_max: float) -> bool:
        return _positive_interval_overlap(self.run_min, self.run_max, run_min, run_max) and _positive_interval_overlap(
            self.z_min,
            self.z_max,
            z_min,
            z_max,
        )


@dataclass
class WallPlaneMask:
    plane_id: str
    normal_axis: str
    thickness_min: float
    thickness_max: float
    run_min: float
    run_max: float
    z_min: float
    z_max: float
    source_bucket: str
    material_family: str
    visual_style: str | None = None
    display_color_rgb: tuple[int, int, int] | None = None
    surface_u_origin_studs: float | None = None
    surface_v_origin_studs: float | None = None
    texture_key: str | None = None
    texture_projection: str | None = None
    texture_image_period_contract: str | None = None
    texture_face_axis_table_version: str | None = None
    studs_per_tile_u: float | None = None
    studs_per_tile_v: float | None = None
    color_modulation_policy: str | None = None
    source_name: str = ""
    staged_object_names: tuple[str, ...] = ()
    source_fragment_ids: tuple[str, ...] = ()
    authoring_mode: str = "plane_mask"
    cuts: list[WallPlaneRectCut] | None = None
    top_profile: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        normal_axis = _normalize_wall_normal_axis(self.normal_axis)
        thickness_min = _round_coord(float(self.thickness_min))
        thickness_max = _round_coord(float(self.thickness_max))
        run_min = _round_coord(float(self.run_min))
        run_max = _round_coord(float(self.run_max))
        z_min = _round_coord(float(self.z_min))
        z_max = _round_coord(float(self.z_max))
        if thickness_max - thickness_min <= _MIN_FRAGMENT_SPAN:
            raise ValueError("Wall-plane thickness span must be positive.")
        if run_max - run_min < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
            raise ValueError("Wall-plane run span is below the minimum packable span.")
        if z_max - z_min < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
            raise ValueError("Wall-plane Z span is below the minimum packable span.")
        self.plane_id = _normalize_required_text(self.plane_id, label="plane_id")
        self.normal_axis = normal_axis
        self.thickness_min = thickness_min
        self.thickness_max = thickness_max
        self.run_min = run_min
        self.run_max = run_max
        self.z_min = z_min
        self.z_max = z_max
        self.source_bucket = _normalize_source_bucket(self.source_bucket)
        self.material_family = _normalize_material_family(self.material_family)
        self.visual_style = _normalize_visual_style(self.visual_style)
        self.display_color_rgb = _normalize_color(self.display_color_rgb)
        self.surface_u_origin_studs = _normalize_origin_float(self.surface_u_origin_studs)
        self.surface_v_origin_studs = _normalize_origin_float(self.surface_v_origin_studs)
        self.texture_key = str(self.texture_key or _texture_key_for_material(self.material_family, self.visual_style)).strip()
        self.texture_projection = _normalize_texture_projection(self.texture_projection, self.material_family, self.visual_style)
        self.texture_image_period_contract = _normalize_texture_period_contract(self.texture_image_period_contract)
        self.texture_face_axis_table_version = _normalize_texture_face_axis_table_version(self.texture_face_axis_table_version)
        self.studs_per_tile_u = _normalize_positive_texture_period(self.studs_per_tile_u, self.material_family, self.visual_style)
        self.studs_per_tile_v = _normalize_positive_texture_period(self.studs_per_tile_v, self.material_family, self.visual_style)
        self.color_modulation_policy = _normalize_color_modulation_policy(self.color_modulation_policy)
        self.source_name = str(self.source_name or "").strip()
        self.staged_object_names = _normalize_staged_object_names(self.staged_object_names)
        self.source_fragment_ids = _sort_unique_strings(self.source_fragment_ids)
        self.authoring_mode = str(self.authoring_mode or "plane_mask").strip() or "plane_mask"
        self.cuts = list(self.cuts or [])
        if self.top_profile:
            self.set_top_profile(self.top_profile)

    @property
    def run_axis(self) -> str:
        return _run_axis_for_normal_axis(self.normal_axis)

    def metadata_key(self) -> tuple[object, ...]:
        return (
            self.source_bucket,
            self.material_family,
            self.normal_axis,
            self.visual_style or "",
            self.display_color_rgb,
            self.surface_u_origin_studs,
            self.surface_v_origin_studs,
            self.plane_id,
        )

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.metadata_key(),
            self.thickness_min,
            self.thickness_max,
            self.run_min,
            self.run_max,
            self.z_min,
            self.z_max,
            self.source_name,
            self.staged_object_names,
        )

    def add_rect_cut(
        self,
        kind: str,
        *,
        run_min: float,
        run_max: float,
        z_min: float,
        z_max: float,
        clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
    ) -> WallPlaneRectCut:
        cut = WallPlaneRectCut(
            kind=kind,
            run_min=run_min,
            run_max=run_max,
            z_min=z_min,
            z_max=z_max,
            clearance_studs=clearance_studs,
        )
        self.cuts.append(cut)
        return cut

    def set_top_profile(self, points: Iterable[Sequence[float]]) -> None:
        normalized: list[tuple[float, float]] = []
        for point in points:
            values = tuple(float(value) for value in point)
            if len(values) != 2:
                raise ValueError("Wall-plane top profile points must be (run, z_top) pairs.")
            normalized.append((_round_coord(values[0]), _round_coord(values[1])))
        if len(normalized) < 2:
            raise ValueError("Wall-plane top profile requires at least two points.")
        normalized.sort(key=lambda item: item[0])
        for left, right in zip(normalized, normalized[1:]):
            if right[0] - left[0] <= _MIN_FRAGMENT_SPAN:
                raise ValueError("Wall-plane top profile run points must be strictly increasing.")
        self.top_profile = tuple(normalized)

    def bounds_for_cell(self, run_min: float, run_max: float, z_min: float, z_max: float) -> RootLocalWallBounds:
        if self.normal_axis == "x":
            return RootLocalWallBounds(self.thickness_min, run_min, z_min, self.thickness_max, run_max, z_max)
        return RootLocalWallBounds(run_min, self.thickness_min, z_min, run_max, self.thickness_max, z_max)


@dataclass(frozen=True)
class CanonicalWallCell:
    cell_id: str
    group_id: str
    bounds: RootLocalWallBounds
    source_bucket: str
    material_family: str
    normal_axis: str
    run_axis: str
    visual_style: str | None = None
    display_color_rgb: tuple[int, int, int] | None = None
    surface_u_origin_studs: float | None = None
    surface_v_origin_studs: float | None = None
    texture_key: str | None = None
    texture_projection: str | None = None
    texture_image_period_contract: str | None = None
    texture_face_axis_table_version: str | None = None
    studs_per_tile_u: float | None = None
    studs_per_tile_v: float | None = None
    color_modulation_policy: str | None = None
    source_fragment_ids: tuple[str, ...] = ()
    staged_object_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalWallGroup:
    group_id: str
    source_bucket: str
    material_family: str
    normal_axis: str
    run_axis: str
    plane_run_min_studs: float
    plane_run_max_studs: float
    plane_z_min_studs: float
    plane_z_max_studs: float
    plane_thickness_min_studs: float
    plane_thickness_max_studs: float
    visual_style: str | None = None
    display_color_rgb: tuple[int, int, int] | None = None
    surface_u_origin_studs: float | None = None
    surface_v_origin_studs: float | None = None
    texture_key: str | None = None
    texture_projection: str | None = None
    texture_image_period_contract: str | None = None
    texture_face_axis_table_version: str | None = None
    studs_per_tile_u: float | None = None
    studs_per_tile_v: float | None = None
    color_modulation_policy: str | None = None
    cells: tuple[CanonicalWallCell, ...] = ()
    source_fragment_ids: tuple[str, ...] = ()
    staged_object_names: tuple[str, ...] = ()
    rect_cuts: tuple[WallPlaneRectCut, ...] = ()
    top_profile: tuple[tuple[float, float], ...] = ()
    authoring_mode: str = "plane_mask"


@dataclass(frozen=True)
class OccupancyCanonicalization:
    fragments: tuple[AtomicWallFragment, ...]
    cells: tuple[CanonicalWallCell, ...]
    groups: tuple[CanonicalWallGroup, ...]
    is_placeholder: bool = False


def _resolve_candidate_cell_bounds(
    candidate: RootLocalWallBounds,
    candidate_plane: WallPlaneMask,
    accepted_cells: Sequence[CanonicalWallCell],
) -> RootLocalWallBounds | None:
    for accepted in accepted_cells:
        if not candidate.overlaps_positive_volume(accepted.bounds):
            continue
        raise ValueError(
            "Canonical authored wall cells overlap illegally: candidate bounds "
            f"{candidate.as_tuple()} from wall plane {candidate_plane.plane_id!r} "
            f"({candidate_plane.source_name!r}, staged={candidate_plane.staged_object_names!r}, "
            f"normal_axis={candidate_plane.normal_axis!r}) and {accepted.cell_id} bounds "
            f"{accepted.bounds.as_tuple()} from fragments {accepted.source_fragment_ids!r} "
            f"(staged={accepted.staged_object_names!r}, normal_axis={accepted.normal_axis!r}) share positive volume."
        )
    return candidate


def _pack_lattice_intervals(
    min_value: float,
    max_value: float,
    *,
    cell_size: float = PACK_CELL_STUDS,
    min_span: float = MIN_NON_THICKNESS_CELL_SPAN_STUDS,
) -> tuple[tuple[float, float], ...]:
    min_value = _round_coord(min_value)
    max_value = _round_coord(max_value)
    span = _round_coord(max_value - min_value)
    if span < min_span:
        raise ValueError("Wall-plane pack axis span is below the minimum packable span.")
    if cell_size <= _MIN_FRAGMENT_SPAN:
        raise ValueError("Wall-plane pack cell size must be positive.")
    intervals: list[tuple[float, float]] = []
    left = min_value
    while max_value - left > _MIN_FRAGMENT_SPAN:
        right = min(max_value, _round_coord(left + float(cell_size)))
        if max_value - right <= _MIN_FRAGMENT_SPAN:
            right = max_value
        if right - left > _MIN_FRAGMENT_SPAN:
            intervals.append((_round_coord(left), _round_coord(right)))
        left = right
    if len(intervals) >= 2 and _round_coord(intervals[-1][1] - intervals[-1][0]) < min_span:
        previous_min, _previous_max = intervals[-2]
        _last_min, last_max = intervals[-1]
        intervals[-2] = (previous_min, last_max)
        intervals.pop()
    for interval_min, interval_max in intervals:
        if _round_coord(interval_max - interval_min) < min_span:
            raise ValueError("Wall-plane pack emitted a run/Z micro-span.")
    return tuple(intervals)


def _top_profile_z_at(profile: tuple[tuple[float, float], ...], run_value: float) -> float | None:
    if not profile:
        return None
    run_value = _round_coord(run_value)
    if run_value < profile[0][0] - _OVERLAP_EPSILON or run_value > profile[-1][0] + _OVERLAP_EPSILON:
        return None
    for left, right in zip(profile, profile[1:]):
        if run_value > right[0] + _OVERLAP_EPSILON:
            continue
        width = right[0] - left[0]
        if width <= _MIN_FRAGMENT_SPAN:
            return min(left[1], right[1])
        t = min(1.0, max(0.0, (run_value - left[0]) / width))
        return _round_coord(left[1] + (right[1] - left[1]) * t)
    return profile[-1][1]


def _cell_is_above_top_profile(
    profile: tuple[tuple[float, float], ...],
    *,
    run_min: float,
    run_max: float,
    z_max: float,
) -> bool:
    if not profile:
        return False
    samples = (run_min, _round_coord((run_min + run_max) / 2.0), run_max)
    tops: list[float] = []
    for sample in samples:
        top = _top_profile_z_at(profile, sample)
        if top is None:
            return True
        tops.append(top)
    return z_max - min(tops) > _OVERLAP_EPSILON


def _critical_run_knots(plane: WallPlaneMask) -> tuple[float, ...]:
    knots: set[float] = {_round_coord(plane.run_min), _round_coord(plane.run_max)}
    for cut in plane.cuts or ():
        if not _positive_interval_overlap(plane.run_min, plane.run_max, cut.run_min, cut.run_max):
            continue
        knots.add(_round_coord(max(plane.run_min, cut.run_min)))
        knots.add(_round_coord(min(plane.run_max, cut.run_max)))
    for run, _z in plane.top_profile:
        if plane.run_min + _OVERLAP_EPSILON < run < plane.run_max - _OVERLAP_EPSILON:
            knots.add(_round_coord(run))
    return tuple(sorted(knots))


def _top_profile_cap_for_run_span(plane: WallPlaneMask, run_min: float, run_max: float) -> float | None:
    if not plane.top_profile:
        return plane.z_max
    samples = (run_min, _round_coord((run_min + run_max) / 2.0), run_max)
    caps: list[float] = []
    for sample in samples:
        cap = _top_profile_z_at(plane.top_profile, sample)
        if cap is None:
            return None
        caps.append(min(plane.z_max, cap))
    return _round_coord(min(caps))


def _subtract_z_interval(
    intervals: tuple[tuple[float, float], ...],
    cut_min: float,
    cut_max: float,
) -> tuple[tuple[float, float], ...]:
    remaining: list[tuple[float, float]] = []
    for interval_min, interval_max in intervals:
        if not _positive_interval_overlap(interval_min, interval_max, cut_min, cut_max):
            remaining.append((interval_min, interval_max))
            continue
        if cut_min - interval_min > _OVERLAP_EPSILON:
            remaining.append((interval_min, _round_coord(min(interval_max, cut_min))))
        if interval_max - cut_max > _OVERLAP_EPSILON:
            remaining.append((_round_coord(max(interval_min, cut_max)), interval_max))
    return tuple(
        (left, right)
        for left, right in remaining
        if _round_coord(right - left) >= MIN_NON_THICKNESS_CELL_SPAN_STUDS
    )


def _solid_z_intervals_for_run_span(
    plane: WallPlaneMask,
    run_min: float,
    run_max: float,
) -> tuple[tuple[float, float], ...]:
    top_z = _top_profile_cap_for_run_span(plane, run_min, run_max)
    if top_z is None:
        return ()
    top_z = _round_coord(min(plane.z_max, top_z))
    if top_z - plane.z_min < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return ()
    intervals: tuple[tuple[float, float], ...] = ((_round_coord(plane.z_min), top_z),)
    for cut in plane.cuts or ():
        if not _positive_interval_overlap(run_min, run_max, cut.run_min, cut.run_max):
            continue
        intervals = _subtract_z_interval(intervals, cut.z_min, cut.z_max)
        if not intervals:
            break
    return intervals


def _micro_span_error(plane: WallPlaneMask, run_min: float, run_max: float) -> ValueError:
    return ValueError(
        "Wall-plane scanline pack produced an unpackable critical run segment: "
        f"plane_id={plane.plane_id!r}, source_bucket={plane.source_bucket!r}, "
        f"source_name={plane.source_name!r}, staged={plane.staged_object_names!r}, "
        f"run=({_round_coord(run_min)}, {_round_coord(run_max)}), "
        f"z_intervals={_solid_z_intervals_for_run_span(plane, run_min, run_max)!r}."
    )


def _is_cut_edge_residue_run_span(plane: WallPlaneMask, run_min: float, run_max: float) -> bool:
    """Return true only for sub-cell remnants trapped between a cut and the plane edge.

    These residues are produced when a canonical opening/cut, including its visual
    clearance, lands closer than the minimum wall-cell span to the end of a wall
    plane.  They are not packable runtime cells; interior slivers or edge slivers
    without a cut owner remain hard errors.
    """
    run_min = _round_coord(run_min)
    run_max = _round_coord(run_max)
    if _round_coord(run_max - run_min) >= MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return False
    touches_left_edge = abs(run_min - plane.run_min) <= _OVERLAP_EPSILON
    touches_right_edge = abs(run_max - plane.run_max) <= _OVERLAP_EPSILON
    if touches_left_edge == touches_right_edge:
        return False
    for cut in plane.cuts or ():
        if not _positive_interval_overlap(plane.z_min, plane.z_max, cut.z_min, cut.z_max):
            continue
        if touches_left_edge and abs(run_max - cut.run_min) <= _OVERLAP_EPSILON:
            return True
        if touches_right_edge and abs(run_min - cut.run_max) <= _OVERLAP_EPSILON:
            return True
    return False


def _packable_run_intervals(plane: WallPlaneMask) -> tuple[tuple[float, float], ...]:
    intervals: list[tuple[float, float]] = []
    critical_knots = _critical_run_knots(plane)
    for run_min, run_max in zip(critical_knots, critical_knots[1:]):
        run_min = _round_coord(run_min)
        run_max = _round_coord(run_max)
        if run_max - run_min <= _MIN_FRAGMENT_SPAN:
            continue
        if not _solid_z_intervals_for_run_span(plane, run_min, run_max):
            continue
        if _round_coord(run_max - run_min) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
            continue
        intervals.extend(_pack_lattice_intervals(run_min, run_max))
    return tuple(intervals)


def _pack_plane_cell_bounds(plane: WallPlaneMask) -> tuple[RootLocalWallBounds, ...]:
    cells: list[RootLocalWallBounds] = []
    for run_min, run_max in _packable_run_intervals(plane):
        if _round_coord(run_max - run_min) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
            raise _micro_span_error(plane, run_min, run_max)
        z_intervals = _solid_z_intervals_for_run_span(plane, run_min, run_max)
        for z_min, z_max in z_intervals:
            for packed_z_min, packed_z_max in _pack_lattice_intervals(z_min, z_max):
                if _round_coord(run_max - run_min) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                    raise ValueError("Wall-plane scanline pack emitted a run micro-span.")
                if _round_coord(packed_z_max - packed_z_min) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                    raise ValueError("Wall-plane scanline pack emitted a Z micro-span.")
                cells.append(plane.bounds_for_cell(run_min, run_max, packed_z_min, packed_z_max))
    return tuple(sorted(cells, key=lambda item: item.sort_key()))


def _raise_on_illegal_overlap(cells: Sequence[CanonicalWallCell]) -> None:
    ordered = tuple(sorted(cells, key=lambda cell: (cell.bounds.sort_key(), cell.cell_id)))
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if not left.bounds.overlaps_positive_volume(right.bounds):
                continue
            raise ValueError(
                "Canonical authored wall cells overlap illegally: "
                f"{left.cell_id} and {right.cell_id} share positive volume."
            )


class OccupancyAuthoringSession:
    """Canonical owner of authored wall-plane registration and V3 cell canonicalization."""

    def __init__(self, *, building_id: str = "", root_object_name: str = "") -> None:
        self._building_id = str(building_id or "").strip()
        self._root_object_name = str(root_object_name or "").strip()
        self._session_token = _normalized_session_token(self._building_id, self._root_object_name)
        self._fragments: list[AtomicWallFragment] = []
        self._planes: list[WallPlaneMask] = []
        self._next_fragment_index = 1
        self._next_plane_index = 1

    @property
    def building_id(self) -> str:
        return self._building_id

    @property
    def root_object_name(self) -> str:
        return self._root_object_name

    @property
    def fragment_count(self) -> int:
        return len(self._fragments)

    @property
    def plane_count(self) -> int:
        return len(self._planes)

    def is_empty(self) -> bool:
        return not self._fragments and not self._planes

    def clear(self) -> None:
        self._fragments.clear()
        self._planes.clear()
        self._next_fragment_index = 1
        self._next_plane_index = 1

    def register_fragment(self, fragment: AtomicWallFragment) -> AtomicWallFragment:
        raise RuntimeError(
            "register_fragment(...) is disabled for V3 gameplay wall authoring; "
            "use register_wall_plane(...) plus add_rect_cut(...)."
        )

    def register_box(
        self,
        bounds: Sequence[float],
        *,
        source_bucket: str,
        material_family: str,
        normal_axis: str,
        visual_style: str | None = None,
        display_color_rgb: Sequence[int] | dict[str, int] | None = None,
        surface_u_origin_studs: float | None = None,
        surface_v_origin_studs: float | None = None,
        texture_key: str | None = None,
        texture_projection: str | None = None,
        texture_image_period_contract: str | None = None,
        texture_face_axis_table_version: str | None = None,
        studs_per_tile_u: float | None = None,
        studs_per_tile_v: float | None = None,
        color_modulation_policy: str | None = None,
        source_name: str = "",
        staged_object_names: Iterable[str] | None = None,
        fragment_id: str = "",
    ) -> AtomicWallFragment:
        raise RuntimeError(
            "register_box(...) is disabled for V3 gameplay wall authoring; "
            "use register_wall_plane(...) plus add_rect_cut(...)."
        )

    def register_wall_plane(
        self,
        *,
        normal_axis: str,
        thickness_min: float,
        thickness_max: float,
        run_min: float,
        run_max: float,
        z_min: float,
        z_max: float,
        source_bucket: str,
        material_family: str,
        plane_id: str = "",
        visual_style: str | None = None,
        display_color_rgb: Sequence[int] | dict[str, int] | None = None,
        surface_u_origin_studs: float | None = None,
        surface_v_origin_studs: float | None = None,
        texture_key: str | None = None,
        texture_projection: str | None = None,
        texture_image_period_contract: str | None = None,
        texture_face_axis_table_version: str | None = None,
        studs_per_tile_u: float | None = None,
        studs_per_tile_v: float | None = None,
        color_modulation_policy: str | None = None,
        source_name: str = "",
        staged_object_names: Iterable[str] | None = None,
        source_fragment_ids: Iterable[str] | None = None,
    ) -> WallPlaneMask:
        """Register one rectangular/top-profile destructible wall plane.

        Plane-local run/Z packing is the V3 authoring truth. Fragment/box
        adapter authoring is disabled and may not create gameplay cells.
        """
        resolved_plane_id = str(plane_id or "").strip() or self._next_plane_id()
        plane = WallPlaneMask(
            plane_id=resolved_plane_id,
            normal_axis=normal_axis,
            thickness_min=thickness_min,
            thickness_max=thickness_max,
            run_min=run_min,
            run_max=run_max,
            z_min=z_min,
            z_max=z_max,
            source_bucket=source_bucket,
            material_family=material_family,
            visual_style=visual_style,
            display_color_rgb=_normalize_color(display_color_rgb),
            surface_u_origin_studs=surface_u_origin_studs,
            surface_v_origin_studs=surface_v_origin_studs,
            texture_key=texture_key,
            texture_projection=texture_projection,
            texture_image_period_contract=texture_image_period_contract,
            texture_face_axis_table_version=texture_face_axis_table_version,
            studs_per_tile_u=studs_per_tile_u,
            studs_per_tile_v=studs_per_tile_v,
            color_modulation_policy=color_modulation_policy,
            source_name=source_name,
            staged_object_names=tuple(staged_object_names or ()),
            source_fragment_ids=tuple(source_fragment_ids or ()),
            authoring_mode="plane_mask",
        )
        self._planes.append(plane)
        return plane

    def add_rect_cut(
        self,
        plane_id: str,
        *,
        kind: str,
        run_min: float,
        run_max: float,
        z_min: float,
        z_max: float,
        clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
    ) -> WallPlaneRectCut:
        return self._find_plane(plane_id).add_rect_cut(
            kind,
            run_min=run_min,
            run_max=run_max,
            z_min=z_min,
            z_max=z_max,
            clearance_studs=clearance_studs,
        )

    def set_top_profile(self, plane_id: str, points: Iterable[Sequence[float]]) -> None:
        self._find_plane(plane_id).set_top_profile(points)

    def iter_fragments(self) -> tuple[AtomicWallFragment, ...]:
        return tuple(self._fragments)

    def iter_wall_planes(self) -> tuple[WallPlaneMask, ...]:
        return tuple(self._planes)

    def iter_debug_fragment_payload(self) -> tuple[dict[str, object], ...]:
        return tuple(fragment.to_debug_dict() for fragment in self.iter_fragments())

    def pack(self) -> OccupancyCanonicalization:
        return self.canonicalize()

    def canonicalize(self) -> OccupancyCanonicalization:
        ordered_fragments = tuple(sorted(self._fragments, key=lambda fragment: fragment.sort_key()))
        ordered_planes = tuple(sorted(self._planes, key=lambda plane: plane.sort_key()))
        canonical_groups: list[CanonicalWallGroup] = []
        canonical_cells: list[CanonicalWallCell] = []
        cell_index = 1
        for group_index, plane in enumerate(ordered_planes, start=1):
            group_id = _compact_group_id(group_index)
            group_cells: list[CanonicalWallCell] = []
            for cell_bounds in _pack_plane_cell_bounds(plane):
                resolved_bounds = _resolve_candidate_cell_bounds(cell_bounds, plane, canonical_cells)
                if resolved_bounds is None:
                    continue
                cell_id = _compact_cell_id(cell_index)
                cell_index += 1
                cell = CanonicalWallCell(
                    cell_id=cell_id,
                    group_id=group_id,
                    bounds=resolved_bounds,
                    source_bucket=plane.source_bucket,
                    material_family=plane.material_family,
                    normal_axis=plane.normal_axis,
                    run_axis=plane.run_axis,
                    visual_style=plane.visual_style,
                    display_color_rgb=plane.display_color_rgb,
                    surface_u_origin_studs=plane.surface_u_origin_studs,
                    surface_v_origin_studs=plane.surface_v_origin_studs,
                    texture_key=plane.texture_key,
                    texture_projection=plane.texture_projection,
                    texture_image_period_contract=plane.texture_image_period_contract,
                    texture_face_axis_table_version=plane.texture_face_axis_table_version,
                    studs_per_tile_u=plane.studs_per_tile_u,
                    studs_per_tile_v=plane.studs_per_tile_v,
                    color_modulation_policy=plane.color_modulation_policy,
                    source_fragment_ids=plane.source_fragment_ids,
                    staged_object_names=plane.staged_object_names,
                )
                group_cells.append(cell)
                canonical_cells.append(cell)
            if not group_cells:
                continue
            canonical_groups.append(
                CanonicalWallGroup(
                    group_id=group_id,
                    source_bucket=plane.source_bucket,
                    material_family=plane.material_family,
                    normal_axis=plane.normal_axis,
                    run_axis=plane.run_axis,
                    plane_run_min_studs=plane.run_min,
                    plane_run_max_studs=plane.run_max,
                    plane_z_min_studs=plane.z_min,
                    plane_z_max_studs=plane.z_max,
                    plane_thickness_min_studs=plane.thickness_min,
                    plane_thickness_max_studs=plane.thickness_max,
                    visual_style=plane.visual_style,
                    display_color_rgb=plane.display_color_rgb,
                    surface_u_origin_studs=plane.surface_u_origin_studs,
                    surface_v_origin_studs=plane.surface_v_origin_studs,
                    texture_key=plane.texture_key,
                    texture_projection=plane.texture_projection,
                    texture_image_period_contract=plane.texture_image_period_contract,
                    texture_face_axis_table_version=plane.texture_face_axis_table_version,
                    studs_per_tile_u=plane.studs_per_tile_u,
                    studs_per_tile_v=plane.studs_per_tile_v,
                    color_modulation_policy=plane.color_modulation_policy,
                    cells=tuple(group_cells),
                    source_fragment_ids=plane.source_fragment_ids,
                    staged_object_names=plane.staged_object_names,
                    rect_cuts=tuple(plane.cuts or ()),
                    top_profile=tuple(plane.top_profile),
                    authoring_mode=plane.authoring_mode,
                )
            )

        _raise_on_illegal_overlap(canonical_cells)
        return OccupancyCanonicalization(
            fragments=ordered_fragments,
            cells=tuple(canonical_cells),
            groups=tuple(canonical_groups),
            is_placeholder=False,
        )

    def _next_fragment_id(self) -> str:
        fragment_id = f"{self._session_token}_Fragment_{self._next_fragment_index:04d}"
        self._next_fragment_index += 1
        return fragment_id

    def _next_plane_id(self) -> str:
        plane_id = f"{self._session_token}_Plane_{self._next_plane_index:04d}"
        self._next_plane_index += 1
        return plane_id

    def _find_plane(self, plane_id: str) -> WallPlaneMask:
        target = str(plane_id or "").strip()
        for plane in self._planes:
            if plane.plane_id == target:
                return plane
        raise KeyError(f"Unknown wall plane: {target!r}.")


def serialize_authored_wall_cell_payload(
    canonicalization: OccupancyCanonicalization,
) -> dict[str, object]:
    if not isinstance(canonicalization, OccupancyCanonicalization):
        raise TypeError("serialize_authored_wall_cell_payload(...) expects OccupancyCanonicalization.")
    cells_payload: list[dict[str, object]] = []
    for cell in canonicalization.cells:
        cells_payload.append(
            {
                "cell_id": cell.cell_id,
                "group_id": cell.group_id,
                "normal_axis": cell.normal_axis,
                "run_axis": cell.run_axis,
                "min_studs": _serialize_vector3(cell.bounds.min_studs()),
                "size_studs": _serialize_vector3(cell.bounds.size_studs()),
            }
        )

    wall_groups_payload: list[dict[str, object]] = []
    for group in canonicalization.groups:
        group_payload: dict[str, object] = {
            "group_id": group.group_id,
            "source_bucket": group.source_bucket,
            "material_family": group.material_family,
            "normal_axis": group.normal_axis,
            "run_axis": group.run_axis,
            "authoring_mode": group.authoring_mode,
            "plane_run_min_studs": _round_coord(group.plane_run_min_studs),
            "plane_run_max_studs": _round_coord(group.plane_run_max_studs),
            "plane_z_min_studs": _round_coord(group.plane_z_min_studs),
            "plane_z_max_studs": _round_coord(group.plane_z_max_studs),
            "plane_thickness_min_studs": _round_coord(group.plane_thickness_min_studs),
            "plane_thickness_max_studs": _round_coord(group.plane_thickness_max_studs),
            "surface_u_origin_studs": group.surface_u_origin_studs,
            "surface_v_origin_studs": group.surface_v_origin_studs,
            "texture_key": str(group.texture_key or _texture_key_for_material(group.material_family, group.visual_style)),
            "texture_projection": str(group.texture_projection or _texture_projection_for_material(group.material_family, group.visual_style)),
            "texture_image_period_contract": str(group.texture_image_period_contract or export_contract.TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE),
            "texture_face_axis_table_version": str(group.texture_face_axis_table_version or export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1),
            "studs_per_tile_u": _round_coord(group.studs_per_tile_u if group.studs_per_tile_u is not None else _texture_studs_per_tile_for_material(group.material_family, group.visual_style)),
            "studs_per_tile_v": _round_coord(group.studs_per_tile_v if group.studs_per_tile_v is not None else _texture_studs_per_tile_for_material(group.material_family, group.visual_style)),
            "color_modulation_policy": str(group.color_modulation_policy or export_contract.COLOR_MODULATION_POLICY_NONE),
            "cell_count": len(group.cells),
            "source_count": len(group.cells),
            "source_fragment_ids": list(group.source_fragment_ids),
            "staged_object_names": list(group.staged_object_names),
        }
        if group.rect_cuts:
            group_payload["rect_cuts"] = [
                {
                    "kind": cut.kind,
                    "run_min": _round_coord(cut.run_min),
                    "run_max": _round_coord(cut.run_max),
                    "z_min": _round_coord(cut.z_min),
                    "z_max": _round_coord(cut.z_max),
                    "clearance_studs": _round_coord(cut.clearance_studs),
                }
                for cut in group.rect_cuts
            ]
        if group.top_profile:
            group_payload["top_profile"] = [
                {"run": _round_coord(run), "z": _round_coord(z)}
                for run, z in group.top_profile
            ]
        color_payload = _serialize_color(group.display_color_rgb)
        if color_payload is not None:
            group_payload["display_color_rgb"] = color_payload
        if group.visual_style is not None:
            group_payload["visual_style"] = group.visual_style
        wall_groups_payload.append(group_payload)

    return {
        "payload_kind": export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND,
        "payload_version": export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION,
        "cell_size_studs": float(PACK_CELL_STUDS),
        "authored_group_count": len(wall_groups_payload),
        "authored_cell_count": len(cells_payload),
        "wall_groups": wall_groups_payload,
        "cells": cells_payload,
    }


__all__ = (
    "AtomicWallFragment",
    "CanonicalWallCell",
    "CanonicalWallGroup",
    "MIN_NON_THICKNESS_CELL_SPAN_STUDS",
    "OPENING_VISUAL_CLEARANCE_STUDS",
    "OccupancyAuthoringSession",
    "OccupancyCanonicalization",
    "PACK_CELL_STUDS",
    "RootLocalWallBounds",
    "WallPlaneMask",
    "WallPlaneRectCut",
    "serialize_authored_wall_cell_payload",
)
