ADDON_ID = "luarch"
ADDON_LABEL = "LuArch"
ADDON_VERSION = "0.2.0"
SUMMARY_SCHEMA_VERSION = "2.0.0"

ROOT_COLLECTION_PREFIX = "TBG_Building"
EXPORT_COLLECTION_PREFIX = "TBG_EXPORT"
BLOCK_COLLECTION_PREFIX = "TBG_Block"

ROOT_OBJECT_KEY = "tbg_is_root"
BUILDING_ID_KEY = "tbg_building_id"
COLLECTION_NAME_KEY = "tbg_collection_name"
EXPORT_COLLECTION_NAME_KEY = "tbg_export_collection_name"
SPEC_JSON_KEY = "tbg_spec_json"
LEGACY_VERSION_KEY = "tbg_version"
ADDON_VERSION_KEY = "tbg_addon_version"
SUMMARY_SCHEMA_VERSION_KEY = "tbg_summary_schema_version"
EXPORT_CONTRACT_VERSION_KEY = "tbg_export_contract_version"
PRESET_KEY = "tbg_preset_id"
SEED_KEY = "tbg_seed"
UNIT_MODE_KEY = "tbg_unit_mode"
EXPORT_PROFILE_KEY = "tbg_export_profile"
GENERATION_SUMMARY_KEY = "tbg_generation_summary_json"
FINAL_SECTION_REGISTRY_KEY = "tbg_final_section_registry_json"

SUMMARY_ADDON_VERSION_FIELD = "addon_version"
SUMMARY_SCHEMA_VERSION_FIELD = "summary_schema_version"
SUMMARY_EXPORT_CONTRACT_VERSION_FIELD = "export_contract_version"
VERSION_KEY = LEGACY_VERSION_KEY

DESTRUCTION_VALUE_DESTRUCTION_MODE = "DestructionMode"
DESTRUCTION_VALUE_VOXEL_WALL_MARKERS_JSON = "VoxelWallMarkersJson"
DESTRUCTION_MODE_VOXEL_WALLS_V1 = "VOXEL_WALLS_V1"

SUPPORTED_SPLIT_FACADE_FAMILIES = (
    "LIGHT_BRICK",
    "DESAT_BRICK",
    "RED_BRICK",
    "BROWN_BRICK",
    "GREY_BRICK",
    "DARK_BRICK",
)

EDITABLE_ONLY = "EDITABLE_ONLY"
EDITABLE_WITH_EXPORT = "EDITABLE_WITH_EXPORT"
EXPORT_PROFILE_ITEMS = (
    (EDITABLE_ONLY, "Editable Only", "Keep only editable collections"),
    (EDITABLE_WITH_EXPORT, "Editable + Export", "Create editable and export collections"),
)

UNIT_MODE_METERS = "METERS"
UNIT_MODE_ITEMS = (
    (UNIT_MODE_METERS, "Meters", "Canonical units are meters"),
)

STAIR_PLACEMENT_CENTER = "CENTER"
STAIR_PLACEMENT_FRONT_RIGHT = "FRONT_RIGHT"
STAIR_PLACEMENT_BACK_RIGHT = "BACK_RIGHT"
STAIR_PLACEMENT_BACK_LEFT = "BACK_LEFT"
STAIR_PLACEMENT_ITEMS = (
    (STAIR_PLACEMENT_CENTER, "Center", "Stair core in the middle"),
    (STAIR_PLACEMENT_FRONT_RIGHT, "Front Right", "Stair core near front-right corner"),
    (STAIR_PLACEMENT_BACK_RIGHT, "Back Right", "Stair core near back-right corner"),
    (STAIR_PLACEMENT_BACK_LEFT, "Back Left", "Stair core near back-left corner"),
)

HINGE_LEFT = "LEFT"
HINGE_RIGHT = "RIGHT"
HINGE_ITEMS = (
    (HINGE_LEFT, "Left", "Door hinges on the left edge"),
    (HINGE_RIGHT, "Right", "Door hinges on the right edge"),
)

LAYOUT_GRID = "GRID"
LAYOUT_ITEMS = (
    (LAYOUT_GRID, "Grid", "Grid-based block layout"),
)

BLOCK_LOT_TYPE_ANY = "ANY"
BLOCK_LOT_TYPE_RESIDENTIAL = "RESIDENTIAL"
BLOCK_LOT_TYPE_COMMERCIAL = "COMMERCIAL"
BLOCK_LOT_TYPE_INDUSTRIAL = "INDUSTRIAL"
BLOCK_LOT_TYPE_ITEMS = (
    (BLOCK_LOT_TYPE_ANY, "Any", "Use the mixed/default block pool"),
    (BLOCK_LOT_TYPE_RESIDENTIAL, "Residential", "Filter to residential block-eligible presets"),
    (BLOCK_LOT_TYPE_COMMERCIAL, "Commercial", "Filter to commercial block-eligible presets"),
    (BLOCK_LOT_TYPE_INDUSTRIAL, "Industrial", "Filter to industrial block-eligible presets"),
)

ROOT_EMPTY_SIZE = 0.5
INNER_MARGIN = 0.25
