from __future__ import annotations

EXPORT_CONTRACT_VERSION = "6.3.0"
EXPORT_CONTRACT_MARKER_PREFIX = "Meta_TBG_Contract__"
EXPORT_CONTRACT_MARKER_VERSION_TOKEN = EXPORT_CONTRACT_VERSION.replace(".", "_")

SIDECAR_MODEL_PREFIX = "__TBG_Sidecar__"
RUNTIME_FOLDER_NAME = "__TBG_Runtime"
CONTRACT_FOLDER_NAME = "__Contract"
AUTHOR_ROOT_NAME = "__AuthorRoot"
LIGHTS_FOLDER_NAME = "Lights"
TRAVERSAL_COLLISION_RUNTIME_FOLDER_NAME = "__TBG_TraversalCollision"
DESTRUCTION_SEED_FOLDER_NAME = "DestructionSeed"
DESTRUCTION_RUNTIME_FOLDER_NAME = "__TBG_Destruction"
DESTRUCTION_COLLISION_FOLDER_NAME = "Collision"
DESTRUCTION_PREVIEW_FOLDER_NAME = "PreviewCollision"
DESTRUCTION_DEBUG_FOLDER_NAME = "Debug"
DESTRUCTION_DIAGNOSTICS_FOLDER_NAME = "Diagnostics"

SEED_CONTRACT_VERSION = "3.0.0"
CANONICAL_LIVE_SMOKE_BLEND_PATH = "examples/live_smoke.blend"

# V3 wall-cell contract:
# - Blender-authored atomic wall cells are the future destructible wall truth.
# - Stable envelope names stay in place where that minimizes churn (`tbg_voxel_wall_occupancy_json`,
#   `VoxelWallOccupancyChunk_####`).
# - The word `occupancy` survives in transport/root key names as historical vocabulary only; the
#   payload semantics are authored wall cells, not V1 raster data or V2 merged cuboids.
VOXEL_SIZE_STUDS = 0.75
MAX_WALL_RUNTIME_PARTS = 4096

# Deprecated V2 cuboid constants retained only so the current live wrappers keep compiling until
# Stage 2 switches the serializer/wrappers atomically. Do not use them for new V3 authoring.
AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND = "AUTHORED_WALL_CUBOIDS"
AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION = "2.0.0"
AUTHORED_WALL_CUBOIDS_ROOT_KEY = "tbg_voxel_wall_occupancy_json"
AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND_KEY = "tbg_voxel_wall_occupancy_payload_kind"
AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION_KEY = "tbg_voxel_wall_occupancy_payload_version"
AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION_KEY = "tbg_voxel_wall_occupancy_export_contract_version"
AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION = "5.0.0"

AUTHORED_WALL_CELLS_PAYLOAD_KIND = "AUTHORED_WALL_CELLS"
AUTHORED_WALL_CELLS_PAYLOAD_VERSION = "3.0.0"
AUTHORED_WALL_CELLS_ROOT_KEY = AUTHORED_WALL_CUBOIDS_ROOT_KEY
AUTHORED_WALL_CELLS_PAYLOAD_KIND_KEY = AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND_KEY
AUTHORED_WALL_CELLS_PAYLOAD_VERSION_KEY = AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION_KEY
AUTHORED_WALL_CELLS_EXPORT_CONTRACT_VERSION_KEY = AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION_KEY
AUTHORED_WALL_CELLS_EXPORT_CONTRACT_VERSION = EXPORT_CONTRACT_VERSION

# Compatibility aliases retained so downstream Stage 2+ call sites can rewire incrementally without
# renaming the stable envelope on this stage. Payload-version aliases intentionally remain V2 until
# the live serializer is switched in Stage 2.
VOXEL_WALL_OCCUPANCY_ROOT_KEY = AUTHORED_WALL_CUBOIDS_ROOT_KEY
VOXEL_WALL_OCCUPANCY_PAYLOAD_VERSION_KEY = AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION_KEY
VOXEL_WALL_OCCUPANCY_EXPORT_CONTRACT_VERSION_KEY = AUTHORED_WALL_CUBOIDS_EXPORT_CONTRACT_VERSION_KEY
VOXEL_WALL_OCCUPANCY_PAYLOAD_VERSION = AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION

# Stale V1 root-only companion metadata. These keys remain documented so later stages can reject or
# purge old roots, but they are no longer part of the fresh root metadata boundary.
LEGACY_V1_VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION_KEY = "tbg_voxel_wall_occupancy_seed_contract_version"
LEGACY_V1_VOXEL_WALL_OCCUPANCY_DESTRUCTION_MODE_KEY = "tbg_voxel_wall_occupancy_destruction_mode"

VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION = "5.0.0"
DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3 = "VOXEL_WALL_CELLS_V3"
VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION = VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION
DESTRUCTION_MODE_VOXEL_WALL_OCCUPANCY_V1 = "VOXEL_WALL_OCCUPANCY_V1"
DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT = "VoxelWallOccupancyChunkCount"
DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX = "VoxelWallOccupancyChunk_"
DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH = 4
MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS = 180000
MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS = 524288

# Legacy/stale marker-era rasterization transport retained only until downstream Stage 2/3 cutover
# removes its live consumers.
MAX_VOXEL_WALL_MARKERS = 256
MAX_OPENINGS_PER_MARKER = 64
MAX_TOTAL_OPENINGS = 1024
MAX_VOXEL_WALL_MARKERS_JSON_BYTES = 524288

AUTHORED_WALL_SOURCE_BUCKETS = (
    "Section_Walls_Exterior",
    "Section_Walls_ExteriorShell",
    "Section_Walls_Interior",
    "Section_Stairs_RoomShell",
)

STALE_VISUAL_ONLY_WALL_BUCKETS = (
    "Section_Walls_ExteriorSurfaceTile",
    "Section_Walls_Trim",
)

VOXEL_WALL_SOURCE_BUCKETS = AUTHORED_WALL_SOURCE_BUCKETS

VOXEL_WALL_MATERIAL_FAMILIES = (
    "BRICK",
    "CONCRETE",
    "PLASTER",
    "WOOD",
    "METAL",
)

VOXEL_WALL_VISUAL_STYLES = (
    "BRICK_MASONRY",
    "TIMBER_SIDING",
    "TIMBER_PAINTED",
)


TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 = "ROBLOX_PART_TEXTURE_V1"
TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1 = "MATERIAL_VARIANT_STYLE_V1"
TEXTURE_PROJECTION_SOLID_COLOR_V1 = "SOLID_COLOR_V1"
TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE = "REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE"
TEXTURE_FACE_AXIS_TABLE_VERSION_V1 = "TEXTURE_FACE_AXIS_TABLE_V1"
COLOR_MODULATION_POLICY_NONE = "NONE"

COMPOSITE_BOX_FACE_ORDER_V1 = ("-z", "+z", "-y", "+x", "+y", "-x")
COMPOSITE_BOX_FACE_INDEX_BY_SIGNED_AXIS_V1 = {
    signed_axis: index for index, signed_axis in enumerate(COMPOSITE_BOX_FACE_ORDER_V1)
}
TEXTURE_FACE_AXIS_TABLE_V1 = {
    ("y", "+"): {
        "roblox_face": "Front",
        "composite_face_index": COMPOSITE_BOX_FACE_INDEX_BY_SIGNED_AXIS_V1["+y"],
        "u_axis": "x",
        "u_sign": 1,
        "v_axis": "z",
        "v_sign": 1,
    },
    ("y", "-"): {
        "roblox_face": "Back",
        "composite_face_index": COMPOSITE_BOX_FACE_INDEX_BY_SIGNED_AXIS_V1["-y"],
        "u_axis": "x",
        "u_sign": -1,
        "v_axis": "z",
        "v_sign": 1,
    },
    ("x", "+"): {
        "roblox_face": "Right",
        "composite_face_index": COMPOSITE_BOX_FACE_INDEX_BY_SIGNED_AXIS_V1["+x"],
        "u_axis": "y",
        "u_sign": -1,
        "v_axis": "z",
        "v_sign": 1,
    },
    ("x", "-"): {
        "roblox_face": "Left",
        "composite_face_index": COMPOSITE_BOX_FACE_INDEX_BY_SIGNED_AXIS_V1["-x"],
        "u_axis": "y",
        "u_sign": 1,
        "v_axis": "z",
        "v_sign": 1,
    },
}
TEXTURE_PROJECTIONS = (
    TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1,
    TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1,
    TEXTURE_PROJECTION_SOLID_COLOR_V1,
)
TEXTURE_IMAGE_PERIOD_CONTRACTS = (
    TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE,
)
TEXTURED_VOXEL_WALL_MATERIAL_FAMILIES = ("BRICK", "WOOD")
DEFAULT_TEXTURE_STUDS_PER_TILE = 2.5
# MaterialVariant has no per-Part UV offset. Keep brick repeats locked to the
# authored V3 cell grid so the dominant 0.75-stud wall cells display whole
# reset-safe tiles instead of arbitrary fragments of a larger masonry sheet.
BRICK_TEXTURE_STUDS_PER_TILE = VOXEL_SIZE_STUDS

VOXEL_WALL_OPENING_KINDS = (
    "WINDOW_OPEN",
    "WINDOW_CLOSED",
    "DOOR",
    "BALCONY_ACCESS",
    "ATTIC_OPENING",
    "ROOF_ACCESS",
)

COLLIDABLE_NON_DESTRUCTIBLE_BUCKETS = (
    "Section_Floors",
    "Section_Stairs_Flights",
    "Section_Stairs_Landings",
    "Section_Walls_Roof",
    "Section_Walls_Canopy",
    "Section_Openings_Balcony_*",
    "Section_Openings_WindowFill",
    "Section_Doors_Leaf",
)

CONTRACT_VALUE_BUILDING_ID = "BuildingId"
CONTRACT_VALUE_EXPORT_CONTRACT_VERSION = "ExportContractVersion"
CONTRACT_VALUE_RENDER_ANCHOR_BASIS = "RenderAnchorBasis"
CONTRACT_VALUE_RENDER_ANCHOR_TO_AUTHOR_ROOT = "RenderAnchorToAuthorRoot"
CONTRACT_VALUE_AUTHOR_ROOT_SCALE = "AuthorRootScale"
CONTRACT_VALUE_RENDER_BOUNDS_SIZE = "RenderBoundsSize"
CONTRACT_VALUE_RENDER_MESH_COUNT = "RenderMeshCount"
CONTRACT_VALUE_LIGHT_COUNT = "LightCount"

RENDER_ANCHOR_BASIS_BOUNDS_CENTER = "RENDER_BOUNDS_CENTER"
COLLISION_GROUP_NAME = "TBG_RuntimeCollision"
ATTRIBUTE_BUILDING_ID = "TBG_BuildingId"
ATTRIBUTE_RUNTIME_CONTRACT_VERSION = "TBG_RuntimeContractVersion"
ATTRIBUTE_STRUCTURE_MODE = "TBG_StructureMode"

RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST = "DESTRUCTIBLE_PLUGIN_FIRST"

CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON = "TraversalCollisionV1Json"
TRAVERSAL_COLLISION_PAYLOAD_VERSION = "1.0.0"

DESTRUCTION_VALUE_SEED_CONTRACT_VERSION = "SeedContractVersion"
DESTRUCTION_VALUE_DESTRUCTION_MODE = "DestructionMode"
DESTRUCTION_VALUE_VOXEL_WALL_MARKERS_JSON = "VoxelWallMarkersJson"
DESTRUCTION_MODE_VOXEL_WALLS_V1 = "VOXEL_WALLS_V1"

RUNTIME_KIND_COLLISION = "COLLISION"
RUNTIME_KIND_LIGHT = "LIGHT"
RUNTIME_SHAPE_BOX = "BOX"
RUNTIME_SHAPE_WEDGE = "WEDGE"

ROLE_BALCONY_ACCESS_OPENING = "BALCONY_ACCESS_OPENING"
ROLE_ATTIC_OPENING = "ATTIC_OPENING"
ROLE_BALCONY_FLOOR = "BALCONY_FLOOR"
ROLE_BALCONY_RAIL = "BALCONY_RAIL"
ROLE_ENTRY_LANDING = "ENTRY_LANDING"
ROLE_ENTRY_WEDGE = "ENTRY_WEDGE"
ROLE_FLOOR_BLOCKER = "FLOOR_BLOCKER"
ROLE_MAIN_ENTRY_DOOR = "MAIN_ENTRY_DOOR"
ROLE_OPEN_WINDOW_OPENING = "OPEN_WINDOW_OPENING"
ROLE_PARTITION = "PARTITION"
ROLE_PROP_BOX = "PROP_BOX"
ROLE_PODIUM_BLOCKER = "PODIUM_BLOCKER"
ROLE_ROOF_BLOCKER = "ROOF_BLOCKER"
ROLE_ROOF_EXIT_DOOR = "ROOF_EXIT_DOOR"
ROLE_ROOF_EXIT_PLATFORM = "ROOF_EXIT_PLATFORM"
ROLE_ROOF_EXIT_SHELL = "ROOF_EXIT_SHELL"
ROLE_SHELL = "SHELL"
ROLE_STAIR_LANDING = "STAIR_LANDING"
ROLE_STAIR_RAMP = "STAIR_RAMP"
ROLE_STAIR_STEP = "STAIR_STEP"
ROLE_STAIR_WEDGE = "STAIR_WEDGE"
ROLE_WINDOW_CLOSED = "WINDOW_CLOSED"
ROLE_WINDOW_SILL = "WINDOW_SILL"

LIGHT_ROLE_ROOM = "ROOM"
LIGHT_ROLE_STAIR = "STAIR"
LIGHT_ROLE_ENTRY = "ENTRY"
LIGHT_ROLE_ROOF_EXIT = "ROOF_EXIT"

LIGHT_ROLE_FAMILIES = (
    LIGHT_ROLE_ROOM,
    LIGHT_ROLE_STAIR,
    LIGHT_ROLE_ENTRY,
    LIGHT_ROLE_ROOF_EXIT,
)


def export_contract_marker_name(prefix: str) -> str:
    return f"{prefix}_{EXPORT_CONTRACT_MARKER_PREFIX}{EXPORT_CONTRACT_MARKER_VERSION_TOKEN}"


def parse_export_contract_marker_name(name: str) -> str | None:
    if EXPORT_CONTRACT_MARKER_PREFIX not in name:
        return None
    version_token = name.rsplit(EXPORT_CONTRACT_MARKER_PREFIX, 1)[-1]
    if not version_token:
        return None
    if any(not (char.isalnum() or char in {"_", "-"}) for char in version_token):
        return None
    return version_token.replace("_", ".")


def sidecar_model_name(building_id: str) -> str:
    return f"{SIDECAR_MODEL_PREFIX}{building_id}"


def voxel_wall_occupancy_chunk_name(index: int) -> str:
    if index < 1:
        raise ValueError("Voxel wall occupancy chunk indexes are 1-based.")
    return (
        f"{DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX}"
        f"{index:0{DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH}d}"
    )


def split_voxel_wall_occupancy_json(payload_json: str) -> tuple[str, ...]:
    normalized = str(payload_json or "")
    if not normalized:
        raise ValueError("Voxel wall occupancy JSON must not be empty.")
    if len(normalized) > MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS:
        raise ValueError(
            "Voxel wall occupancy JSON exceeds the total contract budget "
            f"({len(normalized)} > {MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS})."
        )
    chunk_limit = int(MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS)
    if chunk_limit <= 0:
        raise ValueError("Voxel wall occupancy chunk budget must be positive.")
    return tuple(
        normalized[index : index + chunk_limit]
        for index in range(0, len(normalized), chunk_limit)
    )


def _lua_literal(value: str | int | float | bool) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _render_lua_table(values: list[str]) -> str:
    lines = ["{"]
    for value in values:
        lines.append(f"\t{_lua_literal(value)},")
    lines.append("}")
    return "\n".join(lines)


def _render_lua_string_map(values: dict[str, str]) -> str:
    lines = ["{"]
    for key in sorted(values):
        lines.append(f"\t{key} = {_lua_literal(values[key])},")
    lines.append("}")
    return "\n".join(lines)


def render_plugin_contract_block() -> str:
    lines = [
        "-- BEGIN TBG CONTRACT SYNC",
        f'local EXPECTED_EXPORT_CONTRACT_VERSION = {_lua_literal(EXPORT_CONTRACT_VERSION)}',
        f'local EXPORT_CONTRACT_MARKER_PREFIX = {_lua_literal(EXPORT_CONTRACT_MARKER_PREFIX)}',
        f'local RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST = {_lua_literal(RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST)}',
        f'local TRAVERSAL_COLLISION_RUNTIME_FOLDER_NAME = {_lua_literal(TRAVERSAL_COLLISION_RUNTIME_FOLDER_NAME)}',
        f'local CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON = {_lua_literal(CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON)}',
        f'local TRAVERSAL_COLLISION_PAYLOAD_VERSION = {_lua_literal(TRAVERSAL_COLLISION_PAYLOAD_VERSION)}',
        f'local DESTRUCTION_SEED_FOLDER_NAME = {_lua_literal(DESTRUCTION_SEED_FOLDER_NAME)}',
        f'local DESTRUCTION_RUNTIME_FOLDER_NAME = {_lua_literal(DESTRUCTION_RUNTIME_FOLDER_NAME)}',
        f'local DESTRUCTION_COLLISION_FOLDER_NAME = {_lua_literal(DESTRUCTION_COLLISION_FOLDER_NAME)}',
        f'local DESTRUCTION_PREVIEW_FOLDER_NAME = {_lua_literal(DESTRUCTION_PREVIEW_FOLDER_NAME)}',
        f'local DESTRUCTION_DEBUG_FOLDER_NAME = {_lua_literal(DESTRUCTION_DEBUG_FOLDER_NAME)}',
        f'local DESTRUCTION_DIAGNOSTICS_FOLDER_NAME = {_lua_literal(DESTRUCTION_DIAGNOSTICS_FOLDER_NAME)}',
        f'local SEED_CONTRACT_VERSION = {_lua_literal(SEED_CONTRACT_VERSION)}',
        f'local AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND = {_lua_literal(AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND)}',
        f'local AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION = {_lua_literal(AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION)}',
        f'local AUTHORED_WALL_CELLS_PAYLOAD_KIND = {_lua_literal(AUTHORED_WALL_CELLS_PAYLOAD_KIND)}',
        f'local AUTHORED_WALL_CELLS_PAYLOAD_VERSION = {_lua_literal(AUTHORED_WALL_CELLS_PAYLOAD_VERSION)}',
        f'local VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION = {_lua_literal(VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION)}',
        f'local VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION = {_lua_literal(VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION)}',
        f'local VOXEL_WALL_OCCUPANCY_PAYLOAD_VERSION = {_lua_literal(VOXEL_WALL_OCCUPANCY_PAYLOAD_VERSION)}',
        f'local DESTRUCTION_MODE_VOXEL_WALL_OCCUPANCY_V1 = {_lua_literal(DESTRUCTION_MODE_VOXEL_WALL_OCCUPANCY_V1)}',
        f'local DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3 = {_lua_literal(DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3)}',
        f'local DESTRUCTION_MODE_VOXEL_WALLS_V1 = {_lua_literal(DESTRUCTION_MODE_VOXEL_WALLS_V1)}',
        f'local VOXEL_SIZE_STUDS = {_lua_literal(VOXEL_SIZE_STUDS)}',
        f'local MAX_WALL_RUNTIME_PARTS = {_lua_literal(MAX_WALL_RUNTIME_PARTS)}',
        f'local DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT = {_lua_literal(DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT)}',
        f'local VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX = {_lua_literal(DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX)}',
        f'local VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH = {_lua_literal(DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH)}',
        f'local MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS = {_lua_literal(MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS)}',
        f'local MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS = {_lua_literal(MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS)}',
        f'local MAX_VOXEL_WALL_MARKERS = {_lua_literal(MAX_VOXEL_WALL_MARKERS)}',
        f'local MAX_OPENINGS_PER_MARKER = {_lua_literal(MAX_OPENINGS_PER_MARKER)}',
        f'local MAX_TOTAL_OPENINGS = {_lua_literal(MAX_TOTAL_OPENINGS)}',
        f'local MAX_VOXEL_WALL_MARKERS_JSON_BYTES = {_lua_literal(MAX_VOXEL_WALL_MARKERS_JSON_BYTES)}',
        f'local CANONICAL_LIVE_SMOKE_BLEND_PATH = {_lua_literal(CANONICAL_LIVE_SMOKE_BLEND_PATH)}',
        f'local TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 = {_lua_literal(TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1)}',
        f'local TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1 = {_lua_literal(TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1)}',
        f'local TEXTURE_PROJECTION_SOLID_COLOR_V1 = {_lua_literal(TEXTURE_PROJECTION_SOLID_COLOR_V1)}',
        f'local TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE = {_lua_literal(TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE)}',
        f'local TEXTURE_FACE_AXIS_TABLE_VERSION_V1 = {_lua_literal(TEXTURE_FACE_AXIS_TABLE_VERSION_V1)}',
        f'local COLOR_MODULATION_POLICY_NONE = {_lua_literal(COLOR_MODULATION_POLICY_NONE)}',
        "",
        "local COMPOSITE_BOX_FACE_ORDER_V1 = " + _render_lua_table(list(COMPOSITE_BOX_FACE_ORDER_V1)),
        "",
        "local TEXTURE_PROJECTIONS = " + _render_lua_table(list(TEXTURE_PROJECTIONS)),
        "",
        "local TEXTURE_IMAGE_PERIOD_CONTRACTS = " + _render_lua_table(list(TEXTURE_IMAGE_PERIOD_CONTRACTS)),
        "",
        "local LIGHT_ROLE_FAMILIES = " + _render_lua_table(list(LIGHT_ROLE_FAMILIES)),
        "",
        "local VOXEL_WALL_SOURCE_BUCKETS = " + _render_lua_table(list(VOXEL_WALL_SOURCE_BUCKETS)),
        "",
        "local STALE_VISUAL_ONLY_WALL_BUCKETS = " + _render_lua_table(list(STALE_VISUAL_ONLY_WALL_BUCKETS)),
        "",
        "local VOXEL_WALL_MATERIAL_FAMILIES = " + _render_lua_table(list(VOXEL_WALL_MATERIAL_FAMILIES)),
        "",
        "local VOXEL_WALL_VISUAL_STYLES = " + _render_lua_table(list(VOXEL_WALL_VISUAL_STYLES)),
        "",
        "local VOXEL_WALL_OPENING_KINDS = " + _render_lua_table(list(VOXEL_WALL_OPENING_KINDS)),
        "",
        "local COLLIDABLE_NON_DESTRUCTIBLE_BUCKETS = "
        + _render_lua_table(list(COLLIDABLE_NON_DESTRUCTIBLE_BUCKETS)),
        "",
        "local DESTRUCTION_SEED_VALUE_NAMES = "
        + _render_lua_string_map(
            {
                "SeedContractVersion": DESTRUCTION_VALUE_SEED_CONTRACT_VERSION,
                "DestructionMode": DESTRUCTION_VALUE_DESTRUCTION_MODE,
                "VoxelWallOccupancyChunkCount": DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT,
            }
        ),
        "-- END TBG CONTRACT SYNC",
    ]
    return "\n".join(lines) + "\n"
