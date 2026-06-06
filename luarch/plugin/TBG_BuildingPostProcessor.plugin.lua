-- Contract sync + policy

local ChangeHistoryService = game:GetService("ChangeHistoryService")
local CollectionService = game:GetService("CollectionService")
local HttpService = game:GetService("HttpService")
local MaterialService = game:GetService("MaterialService")
local PhysicsService = game:GetService("PhysicsService")
local Selection = game:GetService("Selection")

local TOOLBAR = plugin:CreateToolbar("LuArch")
local SETUP_BUTTON = TOOLBAR:CreateButton(
	"Setup Building",
	"Attach the selected TBG sidecar and build voxel-wall runtime in one idempotent step",
	"rbxasset://textures/StudioSharedUI/insert_new.png"
)

local DEFAULTS = {
	markerFolderName = "__TBG_SourceMarkers",
	runtimeFolderName = "__TBG_Runtime",
	runtimeTempFolderName = "__TBG_Runtime_Temp",
	sidecarModelPrefix = "__TBG_Sidecar__",
	contractFolderName = "__Contract",
	authorRootName = "__AuthorRoot",
	lightFolderName = "Lights",
	collisionGroupName = "TBG_RuntimeCollision",
	renderAnchorBasis = "RENDER_BOUNDS_CENTER",
	renderModelPrefix = "TBG_Building_",
	buildingIdAttribute = "TBG_BuildingId",
	runtimeContractAttribute = "TBG_RuntimeContractVersion",
	structureModeAttribute = "TBG_StructureMode",
}

-- Generated from export_contract.py via tools/sync_plugin_contract.py.
-- BEGIN TBG CONTRACT SYNC
local EXPECTED_EXPORT_CONTRACT_VERSION = "6.3.0"
local EXPORT_CONTRACT_MARKER_PREFIX = "Meta_TBG_Contract__"
local RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST = "DESTRUCTIBLE_PLUGIN_FIRST"
local TRAVERSAL_COLLISION_RUNTIME_FOLDER_NAME = "__TBG_TraversalCollision"
local CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON = "TraversalCollisionV1Json"
local TRAVERSAL_COLLISION_PAYLOAD_VERSION = "1.0.0"
local DESTRUCTION_SEED_FOLDER_NAME = "DestructionSeed"
local DESTRUCTION_RUNTIME_FOLDER_NAME = "__TBG_Destruction"
local DESTRUCTION_COLLISION_FOLDER_NAME = "Collision"
local DESTRUCTION_PREVIEW_FOLDER_NAME = "PreviewCollision"
local DESTRUCTION_DEBUG_FOLDER_NAME = "Debug"
local DESTRUCTION_DIAGNOSTICS_FOLDER_NAME = "Diagnostics"
local SEED_CONTRACT_VERSION = "3.0.0"
local AUTHORED_WALL_CUBOIDS_PAYLOAD_KIND = "AUTHORED_WALL_CUBOIDS"
local AUTHORED_WALL_CUBOIDS_PAYLOAD_VERSION = "2.0.0"
local AUTHORED_WALL_CELLS_PAYLOAD_KIND = "AUTHORED_WALL_CELLS"
local AUTHORED_WALL_CELLS_PAYLOAD_VERSION = "3.0.0"
local VOXEL_WALL_OCCUPANCY_SEED_CONTRACT_VERSION = "5.0.0"
local VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION = "5.0.0"
local VOXEL_WALL_OCCUPANCY_PAYLOAD_VERSION = "2.0.0"
local DESTRUCTION_MODE_VOXEL_WALL_OCCUPANCY_V1 = "VOXEL_WALL_OCCUPANCY_V1"
local DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3 = "VOXEL_WALL_CELLS_V3"
local DESTRUCTION_MODE_VOXEL_WALLS_V1 = "VOXEL_WALLS_V1"
local VOXEL_SIZE_STUDS = 0.75
local MAX_WALL_RUNTIME_PARTS = 4096
local DESTRUCTION_VALUE_VOXEL_WALL_OCCUPANCY_CHUNK_COUNT = "VoxelWallOccupancyChunkCount"
local VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX = "VoxelWallOccupancyChunk_"
local VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH = 4
local MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS = 180000
local MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS = 524288
local MAX_VOXEL_WALL_MARKERS = 256
local MAX_OPENINGS_PER_MARKER = 64
local MAX_TOTAL_OPENINGS = 1024
local MAX_VOXEL_WALL_MARKERS_JSON_BYTES = 524288
local CANONICAL_LIVE_SMOKE_BLEND_PATH = "examples/live_smoke.blend"
local TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 = "ROBLOX_PART_TEXTURE_V1"
local TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1 = "MATERIAL_VARIANT_STYLE_V1"
local TEXTURE_PROJECTION_SOLID_COLOR_V1 = "SOLID_COLOR_V1"
local TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE = "REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE"
local TEXTURE_FACE_AXIS_TABLE_VERSION_V1 = "TEXTURE_FACE_AXIS_TABLE_V1"
local COLOR_MODULATION_POLICY_NONE = "NONE"

local COMPOSITE_BOX_FACE_ORDER_V1 = {
	"-z",
	"+z",
	"-y",
	"+x",
	"+y",
	"-x",
}

local TEXTURE_PROJECTIONS = {
	"ROBLOX_PART_TEXTURE_V1",
	"MATERIAL_VARIANT_STYLE_V1",
	"SOLID_COLOR_V1",
}

local TEXTURE_IMAGE_PERIOD_CONTRACTS = {
	"REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE",
}

local LIGHT_ROLE_FAMILIES = {
	"ROOM",
	"STAIR",
	"ENTRY",
	"ROOF_EXIT",
}

local VOXEL_WALL_SOURCE_BUCKETS = {
	"Section_Walls_Exterior",
	"Section_Walls_ExteriorShell",
	"Section_Walls_Interior",
	"Section_Stairs_RoomShell",
}

local STALE_VISUAL_ONLY_WALL_BUCKETS = {
	"Section_Walls_ExteriorSurfaceTile",
	"Section_Walls_Trim",
}

local VOXEL_WALL_MATERIAL_FAMILIES = {
	"BRICK",
	"CONCRETE",
	"PLASTER",
	"WOOD",
	"METAL",
}

local VOXEL_WALL_VISUAL_STYLES = {
	"BRICK_MASONRY",
	"TIMBER_SIDING",
	"TIMBER_PAINTED",
}

local VOXEL_WALL_OPENING_KINDS = {
	"WINDOW_OPEN",
	"WINDOW_CLOSED",
	"DOOR",
	"BALCONY_ACCESS",
	"ATTIC_OPENING",
	"ROOF_ACCESS",
}

local COLLIDABLE_NON_DESTRUCTIBLE_BUCKETS = {
	"Section_Floors",
	"Section_Stairs_Flights",
	"Section_Stairs_Landings",
	"Section_Walls_Roof",
	"Section_Walls_Canopy",
	"Section_Openings_Balcony_*",
	"Section_Openings_WindowFill",
	"Section_Doors_Leaf",
}

local DESTRUCTION_SEED_VALUE_NAMES = {
	DestructionMode = "DestructionMode",
	SeedContractVersion = "SeedContractVersion",
	VoxelWallOccupancyChunkCount = "VoxelWallOccupancyChunkCount",
}
-- END TBG CONTRACT SYNC
local DESTRUCTION_RUNTIME_TEMP_FOLDER_NAME = "__TBG_Destruction_Temp"
local TRAVERSAL_COLLISION_RUNTIME_TEMP_FOLDER_NAME = "__TBG_TraversalCollision_Temp"

DEFAULTS.destructionSeedFolderName = DESTRUCTION_SEED_FOLDER_NAME
DEFAULTS.destructionRuntimeFolderName = DESTRUCTION_RUNTIME_FOLDER_NAME
DEFAULTS.destructionRuntimeTempFolderName = DESTRUCTION_RUNTIME_TEMP_FOLDER_NAME
DEFAULTS.destructionCollisionFolderName = DESTRUCTION_COLLISION_FOLDER_NAME
DEFAULTS.traversalCollisionFolderName = TRAVERSAL_COLLISION_RUNTIME_FOLDER_NAME
DEFAULTS.traversalCollisionTempFolderName = TRAVERSAL_COLLISION_RUNTIME_TEMP_FOLDER_NAME

local DESTRUCTIBLE_TAG = "Destructible"
local DIAGNOSTIC_PREVIEW_LIMIT = 6
local RENDER_BOUNDS_EPSILON = 0.05
local PRECHECK_ACTION_TEXT = "Run Blender Validate Selected, regenerate/re-export, then run the plugin again."
local SETUP_COMMAND_NAME = "setupSelectedBuilding"
local WINDOW_FILL_RENDER_MATERIAL = Enum.Material.SmoothPlastic
local WINDOW_FILL_RENDER_COLOR = Color3.fromRGB(161, 201, 242)
local MATERIAL_PROBE_BRICK_PREFIX = "TBG_MaterialProbe_BRICK_"

local COLLIDABLE_SECTION_ALIASES = {
	SRS = "COLLIDABLE_RENDER",
	WRF = "COLLIDABLE_RENDER",
	WCN = "COLLIDABLE_RENDER",
	OWF = "COLLIDABLE_RENDER",
	OBA = "COLLIDABLE_RENDER",
}

local TRAVERSAL_VISUAL_ONLY_SECTION_ALIASES = {
	FLR = true,
	STF = true,
	STL = true,
}

local SUPPORTED_TRAVERSAL_COLLISION_ROLES = {
	ENTRY_LANDING = true,
	ENTRY_WEDGE = true,
	FLOOR_BLOCKER = true,
	PODIUM_BLOCKER = true,
	ROOF_EXIT_PLATFORM = true,
	STAIR_LANDING = true,
	STAIR_RAMP = true,
}

local SUPPORTED_TRAVERSAL_COLLISION_SHAPES = {
	BOX = true,
	WEDGE = true,
}

local VISUAL_ONLY_SECTION_ALIASES = {
	OFR = true,
	DTR = true,
	DPR = true,
	SVP = true,
	SVH = true,
	WTR = true,
}

local STALE_DESTRUCTIBLE_SECTION_ALIASES = {
	WEX = true,
	WXS = true,
	WIN = true,
	OTW = true,
	OTP = true,
}

local SECTION_ALIAS_PATTERNS = {
	"FLR",
	"WIN",
	"SRS",
	"WRF",
	"WCN",
	"WTR",
	"STF",
	"STL",
	"SVP",
	"SVH",
	"DTR",
	"DPR",
	"DLF",
	"OFR",
	"OWF",
	"OTW",
	"OTP",
}

local LEGACY_DESTRUCTION_SEED_VALUE_NAMES = {
	CellSizeStuds = true,
	ChunkSizeCells = true,
	GridConfigJson = true,
	SolidSeedsJson = true,
	VoidSeedsJson = true,
	RoofSeedsJson = true,
}
local LEGACY_TRAVERSAL_VALUE_NAME = "Traversal" .. "SeedsJson"

local SUPPORTED_DESTRUCTION_SEED_VALUE_NAMES = {
	[DESTRUCTION_SEED_VALUE_NAMES.SeedContractVersion] = true,
	[DESTRUCTION_SEED_VALUE_NAMES.DestructionMode] = true,
	[DESTRUCTION_SEED_VALUE_NAMES.VoxelWallOccupancyChunkCount] = true,
}

local CONTRACT_VALUE_AUTHOR_ROOT_SCALE = "AuthorRootScale"

local VOXEL_WALL_APPEARANCE_BY_FAMILY = {
	BRICK = {
		material = Enum.Material.Brick,
		color = Color3.fromRGB(141, 88, 70),
		castShadow = true,
	},
	CONCRETE = {
		material = Enum.Material.Concrete,
		color = Color3.fromRGB(128, 128, 128),
		castShadow = true,
	},
	PLASTER = {
		material = Enum.Material.SmoothPlastic,
		color = Color3.fromRGB(214, 208, 196),
		castShadow = true,
	},
	WOOD = {
		material = Enum.Material.Wood,
		color = Color3.fromRGB(117, 87, 61),
		castShadow = true,
	},
	METAL = {
		material = Enum.Material.Metal,
		color = Color3.fromRGB(157, 164, 176),
		castShadow = true,
	},
}

local BRICK_FAMILY_DISPLAY_COLORS = {
	BROWN_BRICK = Color3.fromRGB(115, 84, 61),
	DARK_BRICK = Color3.fromRGB(74, 61, 54),
	DESAT_BRICK = Color3.fromRGB(186, 181, 168),
	GREY_BRICK = Color3.fromRGB(140, 140, 145),
	LIGHT_BRICK = Color3.fromRGB(212, 199, 161),
	RED_BRICK = Color3.fromRGB(163, 110, 87),
}

local VOXEL_WALL_APPEARANCE_BY_STYLE = {
	BRICK_MASONRY = {
		material = Enum.Material.Brick,
	},
	TIMBER_SIDING = {
		material = Enum.Material.WoodPlanks,
	},
	TIMBER_PAINTED = {
		material = Enum.Material.WoodPlanks,
	},
}

local MANAGED_ANCESTOR_NAMES = {
	[DEFAULTS.markerFolderName] = true,
	[DEFAULTS.runtimeFolderName] = true,
	[DEFAULTS.runtimeTempFolderName] = true,
	[DEFAULTS.destructionRuntimeFolderName] = true,
	[DEFAULTS.traversalCollisionFolderName] = true,
}

local function ensureFolder(parent, name)
	local folder = parent:FindFirstChild(name)
	if folder and folder:IsA("Folder") then
		return folder
	end
	if folder then
		folder:Destroy()
	end
	folder = Instance.new("Folder")
	folder.Name = name
	folder.Parent = parent
	return folder
end

local function ensureMaterialVariant(name, baseMaterial, colorMap, studsPerTile)
	local existing = MaterialService:FindFirstChild(name)
	if existing and existing:IsA("MaterialVariant") then
		if existing.BaseMaterial ~= baseMaterial then
			existing.BaseMaterial = baseMaterial
		end
		if colorMap and existing.ColorMap ~= colorMap then
			existing.ColorMap = colorMap
		end
		if studsPerTile then
			existing.StudsPerTile = studsPerTile
		end
		return existing
	end
	local variant = Instance.new("MaterialVariant")
	variant.Name = name
	variant.BaseMaterial = baseMaterial
	if colorMap then
		variant.ColorMap = colorMap
	end
	if studsPerTile then
		variant.StudsPerTile = studsPerTile
	end
	variant.Parent = MaterialService
	return variant
end

local function ensureVoxelWallMaterialVariants(materialProbeTextureIds)
	for _, appearance in pairs(VOXEL_WALL_APPEARANCE_BY_FAMILY) do
		if appearance.materialVariant then
			ensureMaterialVariant(appearance.materialVariant, appearance.material)
		end
	end
	for _, appearance in pairs(VOXEL_WALL_APPEARANCE_BY_STYLE) do
		if appearance.materialVariant then
			ensureMaterialVariant(appearance.materialVariant, appearance.material)
		end
	end
end

local function findTypedChild(parent, name, className)
	if not parent then
		return nil
	end
	local child = parent:FindFirstChild(name)
	if child and child:IsA(className) then
		return child
	end
	return nil
end

local function hasNamedAncestor(inst, names)
	local current = inst.Parent
	while current do
		if names[current.Name] then
			return true
		end
		current = current.Parent
	end
	return false
end

local function isManagedDescendant(inst)
	return hasNamedAncestor(inst, MANAGED_ANCESTOR_NAMES)
end

local function isSidecarModel(model)
	return model:IsA("Model") and string.sub(model.Name, 1, #DEFAULTS.sidecarModelPrefix) == DEFAULTS.sidecarModelPrefix
end

local function nearestModelAncestor(inst)
	local current = inst
	while current do
		if current:IsA("Model") then
			return current
		end
		current = current.Parent
	end
	return nil
end

local function resolveSelectedModel()
	local selected = Selection:Get()
	if #selected == 0 then
		return nil, "Select one imported render building model or one of its parts."
	end

	local resolved
	for _, inst in ipairs(selected) do
		local model = nearestModelAncestor(inst)
		if not model then
			return nil, "Select one imported render building model or one of its parts."
		end
		if resolved and resolved ~= model then
			return nil, "Selection spans more than one model."
		end
		resolved = model
	end

	return resolved
end

local function normalizeImportedName(name)
	local trimmed = string.match(tostring(name or ""), "^(.*)%.%d+$")
	if trimmed and trimmed ~= "" then
		return trimmed
	end
	return tostring(name or "")
end

local function normalizedRenderPartName(name)
	return normalizeImportedName(name)
end

local function isRuntimeMaterialProbeName(name)
	local normalizedName = normalizedRenderPartName(name)
	return string.sub(normalizedName, 1, #MATERIAL_PROBE_BRICK_PREFIX) == MATERIAL_PROBE_BRICK_PREFIX
end

local function expectedBuildingIdFromRenderModel(model)
	local attributeValue = model:GetAttribute(DEFAULTS.buildingIdAttribute)
	if typeof(attributeValue) == "string" and attributeValue ~= "" then
		return attributeValue, nil
	end

	local basename = normalizeImportedName(model.Name)
	if string.sub(basename, 1, #DEFAULTS.renderModelPrefix) ~= DEFAULTS.renderModelPrefix then
		return nil,
			("Selected render model '%s' does not map to a TBG BuildingId. Rename it back to %s<BuildingId> or re-import before attaching the sidecar."):format(
				model.Name,
				DEFAULTS.renderModelPrefix
			)
	end

	local buildingId = string.sub(basename, #DEFAULTS.renderModelPrefix + 1)
	if buildingId == "" then
		return nil,
			("Selected render model '%s' does not map to a TBG BuildingId. Rename it back to %s<BuildingId> or re-import before attaching the sidecar."):format(
				model.Name,
				DEFAULTS.renderModelPrefix
			)
	end

	return buildingId, nil
end

local function expectedRenderRootName(buildingId)
	return ("%s%s_ROOT"):format(DEFAULTS.renderModelPrefix, buildingId)
end

local function formatInstanceNames(instances)
	local names = {}
	for index, inst in ipairs(instances) do
		if index > DIAGNOSTIC_PREVIEW_LIMIT then
			break
		end
		table.insert(names, inst.Name)
	end
	if #instances > DIAGNOSTIC_PREVIEW_LIMIT then
		table.insert(names, ("... +%d more"):format(#instances - DIAGNOSTIC_PREVIEW_LIMIT))
	end
	return table.concat(names, ", ")
end

local function formatVector3(vector)
	return ("(%.3f, %.3f, %.3f)"):format(vector.X, vector.Y, vector.Z)
end

local function createDiagnostics(model)
	return {
		model = model,
		issues = {},
	}
end

local function addDiagnostic(diagnostics, category, message)
	table.insert(diagnostics.issues, {
		category = category,
		message = message,
	})
end

local function formatDiagnosticSummary(diagnostics)
	local lines = {
		("TBG preflight failed for %s"):format(diagnostics.model:GetFullName()),
	}
	for index, issue in ipairs(diagnostics.issues) do
		table.insert(lines, ("%d. [%s] %s"):format(index, issue.category, issue.message))
	end
	return table.concat(lines, "\n")
end

local function finalizeDiagnostics(diagnostics)
	if #diagnostics.issues <= 0 then
		return nil
	end
	diagnostics.blockerCount = #diagnostics.issues
	addDiagnostic(diagnostics, "action", PRECHECK_ACTION_TEXT)
	return diagnostics
end

local function formatDiagnosticStatus(diagnostics)
	local blockerCount = diagnostics.blockerCount or #diagnostics.issues
	local firstIssue = diagnostics.issues[1]
	if firstIssue then
		return ("Blocked: %s\nCheck Output for %d issue(s)."):format(firstIssue.message, blockerCount)
	end
	return "Blocked: contract preflight failed.\nCheck Output for the full diagnostic summary."
end

local function ensureCollisionGroup()
	local ok = pcall(function()
		PhysicsService:RegisterCollisionGroup(DEFAULTS.collisionGroupName)
	end)
	if not ok then
		pcall(function()
			PhysicsService:CreateCollisionGroup(DEFAULTS.collisionGroupName)
		end)
	end
end

local computeRenderBounds = function(model, renderMeshParts)
	local pivot = model:GetPivot()
	local minVector
	local maxVector

	for _, part in ipairs(renderMeshParts) do
		local half = part.Size * 0.5
		for _, sx in ipairs({ -1, 1 }) do
			for _, sy in ipairs({ -1, 1 }) do
				for _, sz in ipairs({ -1, 1 }) do
					local worldCorner =
						part.CFrame:PointToWorldSpace(Vector3.new(half.X * sx, half.Y * sy, half.Z * sz))
					local localCorner = pivot:PointToObjectSpace(worldCorner)
					if minVector == nil then
						minVector = localCorner
						maxVector = localCorner
					else
						minVector = Vector3.new(
							math.min(minVector.X, localCorner.X),
							math.min(minVector.Y, localCorner.Y),
							math.min(minVector.Z, localCorner.Z)
						)
						maxVector = Vector3.new(
							math.max(maxVector.X, localCorner.X),
							math.max(maxVector.Y, localCorner.Y),
							math.max(maxVector.Z, localCorner.Z)
						)
					end
				end
			end
		end
	end

	if minVector == nil or maxVector == nil then
		return nil, nil, pivot
	end

	local centerLocal = (minVector + maxVector) * 0.5
	local size = maxVector - minVector
	local centerWorld = pivot:PointToWorldSpace(centerLocal)
	local boundsCFrame = CFrame.fromMatrix(centerWorld, pivot.XVector, pivot.YVector, pivot.ZVector)
	return boundsCFrame, size, pivot
end

local function collectRenderSnapshot(model)
	local renderParts = {}
	local renderMeshParts = {}

	for _, desc in ipairs(model:GetDescendants()) do
		if desc:IsA("BasePart") and not isManagedDescendant(desc) then
			table.insert(renderParts, desc)
			if desc:IsA("MeshPart") and not isRuntimeMaterialProbeName(desc.Name) then
				table.insert(renderMeshParts, desc)
			end
		end
	end

	local renderBoundsCFrame, renderBoundsSize, renderPivot = computeRenderBounds(model, renderMeshParts)
	return {
		renderParts = renderParts,
		meshParts = renderMeshParts,
		meshCount = #renderMeshParts,
		boundsCFrame = renderBoundsCFrame,
		boundsSize = renderBoundsSize,
		pivot = renderPivot,
	}
end

local function collectLightSnapshot(lightFolder)
	local parts = {}
	for _, desc in ipairs(lightFolder:GetDescendants()) do
		if desc:IsA("BasePart") then
			table.insert(parts, desc)
		end
	end
	return {
		parts = parts,
		count = #parts,
	}
end

local function findRenderAuthorRoot(renderModel, buildingId)
	return findTypedChild(renderModel, expectedRenderRootName(buildingId), "Model")
end

local function convertBlenderLocalVectorToRoblox(vector)
	return Vector3.new(-vector.X, vector.Z, vector.Y)
end

local function isPositiveFiniteNumber(value)
	return typeof(value) == "number" and value > 0 and value < math.huge and value == value
end

local function makeStringSet(values)
	local set = {}
	for _, value in ipairs(values) do
		set[tostring(value)] = true
	end
	return set
end

local VOXEL_WALL_SOURCE_BUCKET_SET = makeStringSet(VOXEL_WALL_SOURCE_BUCKETS)
local VOXEL_WALL_MATERIAL_FAMILY_SET = makeStringSet(VOXEL_WALL_MATERIAL_FAMILIES)
local VOXEL_WALL_VISUAL_STYLE_SET = makeStringSet(VOXEL_WALL_VISUAL_STYLES)
local TEXTURE_PROJECTION_SET = makeStringSet(TEXTURE_PROJECTIONS)
local TEXTURE_IMAGE_PERIOD_CONTRACT_SET = makeStringSet(TEXTURE_IMAGE_PERIOD_CONTRACTS)

local function decodeJsonValue(raw, diagnostics, label)
	local ok, decoded = pcall(function()
		return HttpService:JSONDecode(raw)
	end)
	if ok then
		return decoded
	end
	addDiagnostic(diagnostics, "destruction contract", ("%s JSON decode failed: %s"):format(label, tostring(decoded)))
	return nil
end

local function isFiniteNumber(value)
	return typeof(value) == "number" and value == value and value > -math.huge and value < math.huge
end

local function scalarNumberField(payload, fieldName)
	local value = payload[fieldName]
	if isFiniteNumber(value) then
		return value
	end
	return nil
end

local function vectorFromMapping(vectorValue)
	if typeof(vectorValue) ~= "table" then
		return nil
	end
	local x = vectorValue.x or vectorValue[1]
	local y = vectorValue.y or vectorValue[2]
	local z = vectorValue.z or vectorValue[3]
	if not isFiniteNumber(x) or not isFiniteNumber(y) or not isFiniteNumber(z) then
		return nil
	end
	return Vector3.new(x, y, z)
end

local function color3FromRgbMapping(colorValue)
	if typeof(colorValue) ~= "table" then
		return nil
	end
	local r = colorValue.r
	local g = colorValue.g
	local b = colorValue.b
	if not isFiniteNumber(r) or not isFiniteNumber(g) or not isFiniteNumber(b) then
		return nil
	end
	if r < 0 or r > 255 or g < 0 or g > 255 or b < 0 or b > 255 then
		return nil
	end
	if r ~= math.floor(r) or g ~= math.floor(g) or b ~= math.floor(b) then
		return nil
	end
	return Color3.fromRGB(r, g, b)
end

local function voxelWallOccupancyChunkName(index)
	return string.format(
		"%s%0" .. tostring(VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH) .. "d",
		VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX,
		index
	)
end

local function isVoxelWallOccupancyChunkName(name)
	if string.sub(name, 1, #VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX) ~= VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX then
		return false
	end
	local suffix = string.sub(name, #VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX + 1)
	if #suffix ~= VOXEL_WALL_OCCUPANCY_CHUNK_INDEX_WIDTH or string.match(suffix, "^%d+$") == nil then
		return false
	end
	return tonumber(suffix) ~= nil and tonumber(suffix) >= 1
end

local readRequiredValue

local function isNonEmptyString(value)
	return typeof(value) == "string" and value ~= ""
end

local function exactInteger(value)
	return isFiniteNumber(value) and value == math.floor(value)
end

local function validatePayloadVersion(payload, diagnostics)
	local payloadKind = tostring(payload.payload_kind or "")
	local payloadVersion = tostring(payload.payload_version or "")
	if payloadKind ~= AUTHORED_WALL_CELLS_PAYLOAD_KIND then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("V3 wall payload kind mismatch: found '%s', expected '%s'. Stale V1/V2 sidecars must be re-exported from Blender."):format(
				payloadKind,
				AUTHORED_WALL_CELLS_PAYLOAD_KIND
			)
		)
	end
	if payloadVersion ~= AUTHORED_WALL_CELLS_PAYLOAD_VERSION then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("V3 wall payload version mismatch: found '%s', expected '%s'. Re-export from Blender."):format(
				payloadVersion,
				AUTHORED_WALL_CELLS_PAYLOAD_VERSION
			)
		)
	end
	local cellSizeStuds = scalarNumberField(payload, "cell_size_studs")
	if cellSizeStuds ~= VOXEL_SIZE_STUDS then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("V3 wall payload must use cell_size_studs=%.2f; found %s. Re-export from Blender."):format(
				VOXEL_SIZE_STUDS,
				tostring(payload.cell_size_studs)
			)
		)
	end
end

local function rejectStaleWallShapes(payload, diagnostics)
	local staleKeys = {
		"walls",
		"authored_cuboid_count",
		"cuboid_count",
		"local_center",
		"x_axis",
		"y_axis",
		"z_axis",
	}
	for _, key in ipairs(staleKeys) do
		if payload[key] ~= nil then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("Stale V1/V2 wall payload field '%s' is not supported by the V3 Studio plugin. Re-export from Blender."):format(
					key
				)
			)
		end
	end
	if typeof(payload.walls) == "table" then
		for wallIndex, wallPayload in ipairs(payload.walls) do
			if typeof(wallPayload) == "table" and wallPayload["cells"] ~= nil then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("Stale V1/V2 nested wall.cells detected at walls[%d]. V3 uses top-level cells[]."):format(
						wallIndex
					)
				)
				break
			end
		end
	end
end

local function expectedRunAxis(normalAxis)
	if normalAxis == "x" then
		return "y"
	elseif normalAxis == "y" then
		return "x"
	end
	return nil
end

local function validateFiniteField(payload, fieldName, label, diagnostics)
	local value = scalarNumberField(payload, fieldName)
	if value == nil then
		addDiagnostic(diagnostics, "destruction contract", ("%s has malformed %s."):format(label, fieldName))
	end
	return value
end

local function validatePositiveExtent(payload, minField, maxField, label, diagnostics)
	if payload[minField] == nil and payload[maxField] == nil then
		return nil, nil
	end
	local minValue = validateFiniteField(payload, minField, label, diagnostics)
	local maxValue = validateFiniteField(payload, maxField, label, diagnostics)
	if minValue ~= nil and maxValue ~= nil and not (minValue < maxValue) then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("%s must have positive %s..%s extent."):format(label, minField, maxField)
		)
	end
	return minValue, maxValue
end

local function validateV3WallGroups(groupsPayload, diagnostics)
	if typeof(groupsPayload) ~= "table" then
		addDiagnostic(diagnostics, "destruction contract", "AUTHORED_WALL_CELLS payload is missing wall_groups[].")
		return {}, {}, {}
	end
	if #groupsPayload <= 0 then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			"AUTHORED_WALL_CELLS payload must contain at least one wall group."
		)
		return {}, {}, {}
	end

	local groupsById = {}
	local orderedGroups = {}
	local seenGroupIds = {}
	for groupIndex, groupPayload in ipairs(groupsPayload) do
		if typeof(groupPayload) ~= "table" then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("wall_groups[%d] must be an object."):format(groupIndex)
			)
			continue
		end
		local groupId = tostring(groupPayload.group_id or "")
		local groupLabel = groupId ~= "" and ("V3 wall group '%s'"):format(groupId)
			or ("V3 wall group #%d"):format(groupIndex)
		local issueCountBefore = #diagnostics.issues
		if not isNonEmptyString(groupPayload.group_id) then
			addDiagnostic(diagnostics, "destruction contract", ("%s is missing group_id."):format(groupLabel))
		elseif seenGroupIds[groupId] then
			addDiagnostic(diagnostics, "destruction contract", ("Duplicate V3 wall group_id '%s'."):format(groupId))
		end
		seenGroupIds[groupId] = true

		local sourceBucket = tostring(groupPayload.source_bucket or "")
		if not VOXEL_WALL_SOURCE_BUCKET_SET[sourceBucket] then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported source_bucket '%s'."):format(groupLabel, sourceBucket)
			)
		end
		local materialFamily = tostring(groupPayload.material_family or "")
		if not VOXEL_WALL_MATERIAL_FAMILY_SET[materialFamily] then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported material_family '%s'."):format(groupLabel, materialFamily)
			)
		end
		local visualStyle = nil
		if groupPayload.visual_style ~= nil then
			visualStyle = tostring(groupPayload.visual_style or "")
			if visualStyle == "" or not VOXEL_WALL_VISUAL_STYLE_SET[visualStyle] then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("%s has unsupported visual_style '%s'."):format(groupLabel, tostring(groupPayload.visual_style))
				)
				visualStyle = nil
			end
		end
		local displayColor = nil
		if groupPayload.display_color_rgb ~= nil then
			displayColor = color3FromRgbMapping(groupPayload.display_color_rgb)
			if not displayColor then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("%s has malformed display_color_rgb; expected integer {r,g,b} in 0..255."):format(groupLabel)
				)
			end
		end

		local normalAxis = tostring(groupPayload.normal_axis or "")
		local runAxis = tostring(groupPayload.run_axis or "")
		local expectedRun = expectedRunAxis(normalAxis)
		if expectedRun == nil then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported normal_axis '%s'."):format(groupLabel, normalAxis)
			)
		elseif runAxis ~= expectedRun then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has run_axis '%s'; expected '%s' for normal_axis '%s'."):format(
					groupLabel,
					runAxis,
					expectedRun,
					normalAxis
				)
			)
		end

		validatePositiveExtent(groupPayload, "plane_run_min_studs", "plane_run_max_studs", groupLabel, diagnostics)
		validatePositiveExtent(groupPayload, "plane_z_min_studs", "plane_z_max_studs", groupLabel, diagnostics)
		validatePositiveExtent(
			groupPayload,
			"plane_thickness_min_studs",
			"plane_thickness_max_studs",
			groupLabel,
			diagnostics
		)

		local cellCount = groupPayload.cell_count
		if not exactInteger(cellCount) or cellCount <= 0 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s must have positive integer cell_count."):format(groupLabel)
			)
		end
		local textureKey = tostring(groupPayload.texture_key or "")
		if textureKey == "" then
			addDiagnostic(diagnostics, "destruction contract", ("%s is missing texture_key."):format(groupLabel))
		end
		local textureProjection = tostring(groupPayload.texture_projection or "")
		if not TEXTURE_PROJECTION_SET[textureProjection] then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported texture_projection '%s'."):format(groupLabel, textureProjection)
			)
		elseif textureProjection == TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s uses retired ROBLOX_PART_TEXTURE_V1; regenerate/export with 6.2.0 material-style wall cells."):format(
					groupLabel
				)
			)
		end
		local expectedTextureProjection = TEXTURE_PROJECTION_SOLID_COLOR_V1
		if (materialFamily == "BRICK" or materialFamily == "WOOD") and visualStyle ~= nil then
			expectedTextureProjection = TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
		end
		if TEXTURE_PROJECTION_SET[textureProjection] and textureProjection ~= expectedTextureProjection then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s texture_projection '%s' drifted from expected '%s'."):format(
					groupLabel,
					textureProjection,
					expectedTextureProjection
				)
			)
		end
		local imagePeriodContract = tostring(groupPayload.texture_image_period_contract or "")
		if not TEXTURE_IMAGE_PERIOD_CONTRACT_SET[imagePeriodContract] then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported texture_image_period_contract '%s'."):format(groupLabel, imagePeriodContract)
			)
		end
		local faceAxisVersion = tostring(groupPayload.texture_face_axis_table_version or "")
		if faceAxisVersion ~= TEXTURE_FACE_AXIS_TABLE_VERSION_V1 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has texture_face_axis_table_version '%s'; expected '%s'."):format(
					groupLabel,
					faceAxisVersion,
					TEXTURE_FACE_AXIS_TABLE_VERSION_V1
				)
			)
		end
		local colorModulationPolicy = tostring(groupPayload.color_modulation_policy or "")
		if colorModulationPolicy ~= COLOR_MODULATION_POLICY_NONE then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has color_modulation_policy '%s'; expected NONE."):format(groupLabel, colorModulationPolicy)
			)
		end
		local studsPerTileU = validateFiniteField(groupPayload, "studs_per_tile_u", groupLabel, diagnostics)
		local studsPerTileV = validateFiniteField(groupPayload, "studs_per_tile_v", groupLabel, diagnostics)
		if studsPerTileU ~= nil and studsPerTileU <= 0 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s must have positive studs_per_tile_u."):format(groupLabel)
			)
		end
		if studsPerTileV ~= nil and studsPerTileV <= 0 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s must have positive studs_per_tile_v."):format(groupLabel)
			)
		end
		local surfaceUOriginStuds = validateFiniteField(groupPayload, "surface_u_origin_studs", groupLabel, diagnostics)
		local surfaceVOriginStuds = validateFiniteField(groupPayload, "surface_v_origin_studs", groupLabel, diagnostics)

		if #diagnostics.issues == issueCountBefore and groupId ~= "" then
			local group = {
				groupId = groupId,
				sourceBucket = sourceBucket,
				materialFamily = materialFamily,
				displayColor = displayColor,
				visualStyle = visualStyle,
				normalAxis = normalAxis,
				runAxis = runAxis,
				cellCount = cellCount,
				textureKey = textureKey,
				textureProjection = textureProjection,
				textureImagePeriodContract = imagePeriodContract,
				textureFaceAxisTableVersion = faceAxisVersion,
				colorModulationPolicy = colorModulationPolicy,
				studsPerTileU = studsPerTileU,
				studsPerTileV = studsPerTileV,
				surfaceUOriginStuds = surfaceUOriginStuds,
				surfaceVOriginStuds = surfaceVOriginStuds,
			}
			groupsById[groupId] = group
			table.insert(orderedGroups, group)
		end
	end
	return groupsById, orderedGroups, seenGroupIds
end

local function cellsOverlapPositiveVolume(a, b)
	local epsilon = 1e-6
	return a.minStuds.X < b.maxStuds.X - epsilon
		and b.minStuds.X < a.maxStuds.X - epsilon
		and a.minStuds.Y < b.maxStuds.Y - epsilon
		and b.minStuds.Y < a.maxStuds.Y - epsilon
		and a.minStuds.Z < b.maxStuds.Z - epsilon
		and b.minStuds.Z < a.maxStuds.Z - epsilon
end

local function validateV3WallCells(cellsPayload, groupsById, diagnostics)
	if typeof(cellsPayload) ~= "table" then
		addDiagnostic(diagnostics, "destruction contract", "AUTHORED_WALL_CELLS payload is missing top-level cells[].")
		return {}, {}, {}
	end
	if #cellsPayload <= 0 then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			"AUTHORED_WALL_CELLS payload must contain at least one cell."
		)
		return {}, {}, {}
	end
	if #cellsPayload > MAX_WALL_RUNTIME_PARTS then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("AUTHORED_WALL_CELLS exceeds runtime wall-part budget (%d > %d)."):format(
				#cellsPayload,
				MAX_WALL_RUNTIME_PARTS
			)
		)
		return {}, {}, {}
	end

	local cellsByGroupId = {}
	local orderedCells = {}
	local seenCellIds = {}
	for cellIndex, cellPayload in ipairs(cellsPayload) do
		if typeof(cellPayload) ~= "table" then
			addDiagnostic(diagnostics, "destruction contract", ("cells[%d] must be an object."):format(cellIndex))
			continue
		end
		local cellId = tostring(cellPayload.cell_id or "")
		local cellLabel = cellId ~= "" and ("V3 wall cell '%s'"):format(cellId)
			or ("V3 wall cell #%d"):format(cellIndex)
		local issueCountBefore = #diagnostics.issues
		if not isNonEmptyString(cellPayload.cell_id) then
			addDiagnostic(diagnostics, "destruction contract", ("%s is missing cell_id."):format(cellLabel))
		elseif seenCellIds[cellId] then
			addDiagnostic(diagnostics, "destruction contract", ("Duplicate V3 wall cell_id '%s'."):format(cellId))
		end
		seenCellIds[cellId] = true

		local groupId = tostring(cellPayload.group_id or "")
		local group = groupsById[groupId]
		if not group then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s references unknown group_id '%s'."):format(cellLabel, groupId)
			)
		end
		local normalAxis = tostring(cellPayload.normal_axis or "")
		local runAxis = tostring(cellPayload.run_axis or "")
		if normalAxis == "z" then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has invalid vertical normal_axis 'z'."):format(cellLabel)
			)
		elseif expectedRunAxis(normalAxis) == nil then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has unsupported normal_axis '%s'."):format(cellLabel, normalAxis)
			)
		end
		if group then
			if normalAxis ~= group.normalAxis then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("%s normal_axis does not match group '%s'."):format(cellLabel, groupId)
				)
			end
			if runAxis ~= group.runAxis then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("%s run_axis does not match group '%s'."):format(cellLabel, groupId)
				)
			end
		elseif runAxis ~= expectedRunAxis(normalAxis) then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s has invalid run_axis '%s'."):format(cellLabel, runAxis)
			)
		end
		local minStuds = vectorFromMapping(cellPayload.min_studs)
		if not minStuds then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s min_studs must be a finite {x,y,z} object."):format(cellLabel)
			)
		end
		local sizeStuds = vectorFromMapping(cellPayload.size_studs)
		if not sizeStuds then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s size_studs must be a finite {x,y,z} object."):format(cellLabel)
			)
		elseif sizeStuds.X <= 0 or sizeStuds.Y <= 0 or sizeStuds.Z <= 0 then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("%s size_studs components must be strictly positive."):format(cellLabel)
			)
		end

		if #diagnostics.issues == issueCountBefore and group and minStuds and sizeStuds and cellId ~= "" then
			local cell = {
				cellId = cellId,
				groupId = groupId,
				normalAxis = normalAxis,
				runAxis = runAxis,
				minStuds = minStuds,
				sizeStuds = sizeStuds,
				maxStuds = minStuds + sizeStuds,
			}
			cellsByGroupId[groupId] = cellsByGroupId[groupId] or {}
			table.insert(cellsByGroupId[groupId], cell)
			table.insert(orderedCells, cell)
		end
	end

	for groupId, group in pairs(groupsById) do
		local cells = cellsByGroupId[groupId] or {}
		if #cells ~= group.cellCount then
			addDiagnostic(
				diagnostics,
				"destruction contract",
				("V3 wall group '%s' cell_count mismatch: metadata=%d actual=%d."):format(
					groupId,
					group.cellCount,
					#cells
				)
			)
		end
	end
	for i = 1, #orderedCells do
		for j = i + 1, #orderedCells do
			if cellsOverlapPositiveVolume(orderedCells[i], orderedCells[j]) then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("V3 wall cells '%s' and '%s' overlap with positive volume. Face-touch is allowed; volume overlap is not."):format(
						orderedCells[i].cellId,
						orderedCells[j].cellId
					)
				)
			end
		end
	end
	return cellsByGroupId, orderedCells, seenCellIds
end

local function decodeV3WallCells(seedFolder, diagnostics)
	local seedVersionValue =
		readRequiredValue(seedFolder, DESTRUCTION_SEED_VALUE_NAMES.SeedContractVersion, "StringValue", diagnostics)
	local destructionModeValue =
		readRequiredValue(seedFolder, DESTRUCTION_SEED_VALUE_NAMES.DestructionMode, "StringValue", diagnostics)
	local chunkCountValue = readRequiredValue(
		seedFolder,
		DESTRUCTION_SEED_VALUE_NAMES.VoxelWallOccupancyChunkCount,
		"IntValue",
		diagnostics
	)
	if #diagnostics.issues > 0 then
		return nil
	end

	if seedVersionValue.Value ~= VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("SeedContractVersion mismatch: found %s, expected %s. Re-export from Blender."):format(
				tostring(seedVersionValue.Value),
				VOXEL_WALL_CELLS_SEED_CONTRACT_VERSION
			)
		)
	end
	if destructionModeValue.Value ~= DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3 then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("DestructionMode mismatch: found %s, expected %s. Stale V1/V2 sidecars are rejected; re-export from Blender."):format(
				tostring(destructionModeValue.Value),
				DESTRUCTION_MODE_VOXEL_WALL_CELLS_V3
			)
		)
	end
	local chunkCount = chunkCountValue.Value
	if chunkCount < 1 then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("VoxelWallOccupancyChunkCount must be positive, found %d."):format(chunkCount)
		)
	end
	for _, child in ipairs(seedFolder:GetChildren()) do
		if child:IsA("StringValue") and isVoxelWallOccupancyChunkName(child.Name) then
			local chunkIndex = tonumber(string.sub(child.Name, #VOXEL_WALL_OCCUPANCY_CHUNK_PREFIX + 1))
			if chunkIndex and chunkIndex > chunkCount then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("Unexpected occupancy chunk '%s' beyond VoxelWallOccupancyChunkCount=%d."):format(
						child.Name,
						chunkCount
					)
				)
			end
		end
	end
	if #diagnostics.issues > 0 then
		return nil
	end

	local chunkValues = table.create(chunkCount)
	local reconstructedLength = 0
	for chunkIndex = 1, chunkCount do
		local chunkName = voxelWallOccupancyChunkName(chunkIndex)
		local chunkValue = readRequiredValue(seedFolder, chunkName, "StringValue", diagnostics)
		if chunkValue then
			local chunkLength = #chunkValue.Value
			if chunkLength > MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("%s exceeds per-chunk budget (%d > %d)."):format(
						chunkName,
						chunkLength,
						MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS
					)
				)
			end
			reconstructedLength = reconstructedLength + chunkLength
			chunkValues[chunkIndex] = chunkValue.Value
		end
	end
	if reconstructedLength > MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("Reconstructed V3 wall-cell JSON exceeds total budget (%d > %d)."):format(
				reconstructedLength,
				MAX_VOXEL_WALL_OCCUPANCY_JSON_CHARS
			)
		)
	end
	if #diagnostics.issues > 0 then
		return nil
	end

	local payload = decodeJsonValue(table.concat(chunkValues), diagnostics, "AuthoredWallCellsJson")
	if typeof(payload) ~= "table" then
		addDiagnostic(diagnostics, "destruction contract", "AuthoredWallCellsJson must decode to a JSON object.")
		return nil
	end
	validatePayloadVersion(payload, diagnostics)
	rejectStaleWallShapes(payload, diagnostics)
	local groupsById, orderedGroups = validateV3WallGroups(payload.wall_groups, diagnostics)
	local cellsByGroupId, orderedCells = validateV3WallCells(payload.cells, groupsById, diagnostics)

	local authoredGroupCount = payload.authored_group_count
	if authoredGroupCount ~= nil and (not exactInteger(authoredGroupCount) or authoredGroupCount ~= #orderedGroups) then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("authored_group_count mismatch: payload=%s decoded=%d."):format(
				tostring(authoredGroupCount),
				#orderedGroups
			)
		)
	end
	local authoredCellCount = payload.authored_cell_count
	if authoredCellCount ~= nil and (not exactInteger(authoredCellCount) or authoredCellCount ~= #orderedCells) then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			("authored_cell_count mismatch: payload=%s decoded=%d."):format(tostring(authoredCellCount), #orderedCells)
		)
	end
	if #orderedCells <= 0 then
		addDiagnostic(
			diagnostics,
			"destruction contract",
			"AUTHORED_WALL_CELLS payload contains zero authored runtime wall cells."
		)
	end
	if #diagnostics.issues > 0 then
		return nil
	end

	return {
		folder = seedFolder,
		seedVersion = seedVersionValue.Value,
		destructionMode = destructionModeValue.Value,
		payload = payload,
		groupsById = groupsById,
		orderedGroups = orderedGroups,
		cellsByGroupId = cellsByGroupId,
		orderedCells = orderedCells,
		authoredGroupCount = #orderedGroups,
		authoredCellCount = #orderedCells,
		chunkCount = chunkCount,
		reconstructedLength = reconstructedLength,
	}
end

readRequiredValue = function(folder, name, className, diagnostics)
	local valueObject = findTypedChild(folder, name, className)
	if valueObject then
		return valueObject
	end
	addDiagnostic(
		diagnostics,
		"destruction contract",
		("Runtime destruction seed is missing %s (%s). Re-export from Blender."):format(name, className)
	)
	return nil
end

local function readDestructionSeedFolder(seedFolder, diagnostics)
	if not seedFolder then
		addDiagnostic(diagnostics, "destruction contract", "__TBG_Runtime is missing DestructionSeed.")
		return nil
	end

	for _, child in ipairs(seedFolder:GetChildren()) do
		if child:IsA("ValueBase") then
			if LEGACY_DESTRUCTION_SEED_VALUE_NAMES[child.Name] or child.Name == LEGACY_TRAVERSAL_VALUE_NAME then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("Stale DestructionSeed value '%s' detected. Re-export this building from Blender; legacy authored-bricks/traversal sidecars are no longer supported."):format(
						child.Name
					)
				)
			elseif child.Name == "VoxelWallMarkersJson" then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					"Stale DestructionSeed value 'VoxelWallMarkersJson' detected. Re-export this building from Blender with V3 wall-cell transport."
				)
			elseif
				not SUPPORTED_DESTRUCTION_SEED_VALUE_NAMES[child.Name] and not isVoxelWallOccupancyChunkName(child.Name)
			then
				addDiagnostic(
					diagnostics,
					"destruction contract",
					("Unexpected DestructionSeed value '%s'. Fresh V3 wall-cell exports support only SeedContractVersion, DestructionMode, VoxelWallOccupancyChunkCount, and ordered VoxelWallOccupancyChunk_#### values."):format(
						child.Name
					)
				)
			end
		end
	end
	if #diagnostics.issues > 0 then
		return nil
	end
	return decodeV3WallCells(seedFolder, diagnostics)
end

local function readDestructionSeed(runtimeFolder, diagnostics)
	local seedFolder = findTypedChild(runtimeFolder, DEFAULTS.destructionSeedFolderName, "Folder")
	return readDestructionSeedFolder(seedFolder, diagnostics)
end

local function traversalVectorField(seed, fieldName, diagnostics, seedIndex, positive)
	local vector = vectorFromMapping(seed[fieldName])
	if not vector then
		addDiagnostic(
			diagnostics,
			"traversal contract",
			("TraversalCollisionV1 seed #%d has invalid vector field '%s'."):format(seedIndex, fieldName)
		)
		return nil
	end
	if positive and (vector.X <= 0 or vector.Y <= 0 or vector.Z <= 0) then
		addDiagnostic(
			diagnostics,
			"traversal contract",
			("TraversalCollisionV1 seed #%d has non-positive size %s."):format(seedIndex, formatVector3(vector))
		)
		return nil
	end
	return vector
end

local function decodeTraversalCollisionPayload(contractFolder, diagnostics)
	local payloadValue = findTypedChild(contractFolder, CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON, "StringValue")
	if not payloadValue then
		addDiagnostic(
			diagnostics,
			"traversal contract",
			("Runtime contract is missing StringValue %s. Re-export and re-import the 6.3.0+ sidecar."):format(
				CONTRACT_VALUE_TRAVERSAL_COLLISION_JSON
			)
		)
		return nil
	end

	local ok, payload = pcall(function()
		return HttpService:JSONDecode(payloadValue.Value)
	end)
	if not ok or typeof(payload) ~= "table" then
		addDiagnostic(
			diagnostics,
			"traversal contract",
			("TraversalCollisionV1Json JSON decode failed: %s"):format(tostring(payload))
		)
		return nil
	end
	if tostring(payload.schema_version or "") ~= TRAVERSAL_COLLISION_PAYLOAD_VERSION then
		addDiagnostic(
			diagnostics,
			"traversal contract",
			("TraversalCollisionV1 schema mismatch: found '%s', expected '%s'. Re-export from Blender."):format(
				tostring(payload.schema_version),
				TRAVERSAL_COLLISION_PAYLOAD_VERSION
			)
		)
	end
	if typeof(payload.seeds) ~= "table" then
		addDiagnostic(diagnostics, "traversal contract", "TraversalCollisionV1 payload must contain a seeds array.")
		return nil
	end

	local seeds = {}
	for index, seed in ipairs(payload.seeds) do
		if typeof(seed) ~= "table" then
			addDiagnostic(
				diagnostics,
				"traversal contract",
				("TraversalCollisionV1 seed #%d must be a JSON object."):format(index)
			)
			continue
		end

		local role = tostring(seed.role or "")
		local shapeType = tostring(seed.shape_type or "")
		if not SUPPORTED_TRAVERSAL_COLLISION_ROLES[role] then
			addDiagnostic(
				diagnostics,
				"traversal contract",
				("TraversalCollisionV1 seed #%d has unsupported role '%s'."):format(index, role)
			)
		end
		if not SUPPORTED_TRAVERSAL_COLLISION_SHAPES[shapeType] then
			addDiagnostic(
				diagnostics,
				"traversal contract",
				("TraversalCollisionV1 seed #%d has unsupported shape_type '%s'."):format(index, shapeType)
			)
		end

		local localCenter = traversalVectorField(seed, "local_center", diagnostics, index, false)
		local size = traversalVectorField(seed, "size", diagnostics, index, true)
		local xAxis = traversalVectorField(seed, "x_axis", diagnostics, index, false)
		local yAxis = traversalVectorField(seed, "y_axis", diagnostics, index, false)
		local zAxis = traversalVectorField(seed, "z_axis", diagnostics, index, false)
		if
			SUPPORTED_TRAVERSAL_COLLISION_ROLES[role]
			and SUPPORTED_TRAVERSAL_COLLISION_SHAPES[shapeType]
			and localCenter
			and size
			and xAxis
			and yAxis
			and zAxis
		then
			table.insert(seeds, {
				role = role,
				shapeType = shapeType,
				name = tostring(seed.name or ("Traversal_%04d"):format(index)),
				sourceName = tostring(seed.source_name or seed.name or ""),
				localCenter = localCenter,
				size = size,
				xAxis = xAxis,
				yAxis = yAxis,
				zAxis = zAxis,
			})
		end
	end
	if #diagnostics.issues > 0 then
		return nil
	end

	return {
		seeds = seeds,
		count = #seeds,
	}
end

local function readTraversalCollision(runtimeFolder, diagnostics)
	local contractFolder = findTypedChild(runtimeFolder, DEFAULTS.contractFolderName, "Folder")
	if not contractFolder then
		addDiagnostic(diagnostics, "traversal contract", "__TBG_Runtime is missing __Contract.")
		return nil
	end
	return decodeTraversalCollisionPayload(contractFolder, diagnostics)
end

local function isNamedDoorLeafName(normalizedName)
	return string.match(normalizedName, "_Door_Main$") ~= nil
		or string.match(normalizedName, "_Door_Rear$") ~= nil
		or string.match(normalizedName, "_Door_RoofExit$") ~= nil
end

local function isNamedWindowFillName(normalizedName)
	return string.match(normalizedName, "_Window_%d+_Fill$") ~= nil
		or string.match(normalizedName, "_StairWindow_%d+_Fill$") ~= nil
end

local function isNamedOpeningFrameName(normalizedName)
	return string.match(normalizedName, "_Window_%d+_Frame$") ~= nil
		or string.match(normalizedName, "_OpenWindow_%d+_Frame$") ~= nil
		or string.match(normalizedName, "_StairWindow_%d+_Frame$") ~= nil
		or string.match(normalizedName, "_Mullion_") ~= nil
		or string.match(normalizedName, "_Door_Main_Frame$") ~= nil
		or string.match(normalizedName, "_Door_Rear_Frame$") ~= nil
		or string.match(normalizedName, "_Door_RoofExit_Frame$") ~= nil
		or string.match(normalizedName, "_RoofExit_[%w_]+_Lintel$") ~= nil
end

local function brickMaterialProbeFamily(normalizedName)
	if string.sub(normalizedName, 1, #MATERIAL_PROBE_BRICK_PREFIX) ~= MATERIAL_PROBE_BRICK_PREFIX then
		return nil
	end
	local family = string.sub(normalizedName, #MATERIAL_PROBE_BRICK_PREFIX + 1)
	return BRICK_FAMILY_DISPLAY_COLORS[family] and family or nil
end

local function extractSectionAlias(normalizedName)
	if string.find(normalizedName, "_OBA_", 1, true) then
		return "OBA"
	end
	if string.find(normalizedName, "_WXS_", 1, true) then
		return "WXS"
	end
	if string.find(normalizedName, "_WEX_", 1, true) then
		return "WEX"
	end
	for _, alias in ipairs(SECTION_ALIAS_PATTERNS) do
		if string.find(normalizedName, "_" .. alias .. "_", 1, true) then
			return alias
		end
	end
	return nil
end

local function hasGameplayRelevantRenderTags(part)
	local attr = part.GetAttribute
	if typeof(attr) ~= "function" then
		return false
	end
	return part:GetAttribute("tbg_entrance_part") ~= nil
		or part:GetAttribute("tbg_foundation_podium") ~= nil
		or part:GetAttribute("tbg_is_door_leaf") ~= nil
		or part:GetAttribute("tbg_roof_exit_platform") ~= nil
		or part:GetAttribute("tbg_balcony_part") ~= nil
		or part:GetAttribute("tbg_balcony_access") ~= nil
end

local function classifyRenderPart(part)
	local normalizedName = normalizedRenderPartName(part.Name)
	local alias = extractSectionAlias(normalizedName)
	if isNamedDoorLeafName(normalizedName) then
		return {
			kind = "DOOR_LEAF",
			mode = "DOOR_LEAF",
			normalizedName = normalizedName,
		}
	end
	if
		string.find(normalizedName, "_WEX_BRK_X", 1, true) ~= nil
		or string.find(normalizedName, "_WEX_SFT_S", 1, true) ~= nil
	then
		return {
			kind = "STALE_DESTRUCTIBLE_RENDER",
			normalizedName = normalizedName,
		}
	end
	if alias and STALE_DESTRUCTIBLE_SECTION_ALIASES[alias] then
		return {
			kind = "STALE_DESTRUCTIBLE_RENDER",
			alias = alias,
			normalizedName = normalizedName,
		}
	end
	if alias == "DLF" then
		return {
			kind = "DOOR_LEAF",
			alias = alias,
			mode = "DOOR_LEAF",
			normalizedName = normalizedName,
		}
	end
	if string.find(string.lower(normalizedName), "hangarbayfill", 1, true) ~= nil then
		return {
			kind = "COLLIDABLE_SECTION",
			alias = "OWF",
			mode = COLLIDABLE_SECTION_ALIASES.OWF,
			normalizedName = normalizedName,
		}
	end
	if isNamedWindowFillName(normalizedName) then
		return {
			kind = "COLLIDABLE_SECTION",
			alias = "OWF",
			mode = COLLIDABLE_SECTION_ALIASES.OWF,
			normalizedName = normalizedName,
		}
	end
	if isNamedOpeningFrameName(normalizedName) then
		return {
			kind = "VISUAL_ONLY_SECTION",
			alias = "OFR",
			normalizedName = normalizedName,
		}
	end
	local probeFamily = brickMaterialProbeFamily(normalizedName)
	if probeFamily then
		return {
			kind = "MATERIAL_PROBE",
			family = probeFamily,
			normalizedName = normalizedName,
		}
	end
	if not alias then
		return {
			kind = "UNKNOWN",
			hasGameplayTag = hasGameplayRelevantRenderTags(part),
			normalizedName = normalizedName,
		}
	end
	if TRAVERSAL_VISUAL_ONLY_SECTION_ALIASES[alias] then
		return {
			kind = "TRAVERSAL_VISUAL_ONLY_SECTION",
			alias = alias,
			normalizedName = normalizedName,
		}
	end
	if COLLIDABLE_SECTION_ALIASES[alias] then
		return {
			kind = "COLLIDABLE_SECTION",
			alias = alias,
			mode = COLLIDABLE_SECTION_ALIASES[alias],
			normalizedName = normalizedName,
		}
	end
	if VISUAL_ONLY_SECTION_ALIASES[alias] then
		return {
			kind = "VISUAL_ONLY_SECTION",
			alias = alias,
			normalizedName = normalizedName,
		}
	end
	return {
		kind = "UNKNOWN",
		alias = alias,
		hasGameplayTag = hasGameplayRelevantRenderTags(part),
		normalizedName = normalizedName,
	}
end

local function collectRenderFacts(renderModel)
	local snapshot = collectRenderSnapshot(renderModel)
	local classifiedParts = {}
	local counts = {
		doorLeafCount = 0,
		collidableSectionCount = 0,
		traversalVisualOnlySectionCount = 0,
		visualOnlySectionCount = 0,
		staleDestructibleCount = 0,
		materialProbeCount = 0,
		unknownGameplayCount = 0,
		unknownCount = 0,
	}
	local staleSamples = {}
	local unknownGameplaySamples = {}
	local unknownSamples = {}

	for _, part in ipairs(snapshot.renderParts) do
		local policy = classifyRenderPart(part)
		table.insert(classifiedParts, {
			part = part,
			policy = policy,
		})
		if policy.kind == "DOOR_LEAF" then
			counts.doorLeafCount = counts.doorLeafCount + 1
		elseif policy.kind == "COLLIDABLE_SECTION" then
			counts.collidableSectionCount = counts.collidableSectionCount + 1
		elseif policy.kind == "TRAVERSAL_VISUAL_ONLY_SECTION" then
			counts.traversalVisualOnlySectionCount = counts.traversalVisualOnlySectionCount + 1
		elseif policy.kind == "VISUAL_ONLY_SECTION" then
			counts.visualOnlySectionCount = counts.visualOnlySectionCount + 1
		elseif policy.kind == "STALE_DESTRUCTIBLE_RENDER" then
			counts.staleDestructibleCount = counts.staleDestructibleCount + 1
			if #staleSamples < DIAGNOSTIC_PREVIEW_LIMIT then
				table.insert(staleSamples, policy.normalizedName)
			end
		elseif policy.kind == "MATERIAL_PROBE" then
			counts.materialProbeCount = counts.materialProbeCount + 1
		else
			counts.unknownCount = counts.unknownCount + 1
			if policy.hasGameplayTag then
				counts.unknownGameplayCount = counts.unknownGameplayCount + 1
				if #unknownGameplaySamples < DIAGNOSTIC_PREVIEW_LIMIT then
					table.insert(unknownGameplaySamples, policy.normalizedName)
				end
			end
			if #unknownSamples < DIAGNOSTIC_PREVIEW_LIMIT then
				table.insert(unknownSamples, policy.normalizedName)
			end
		end
	end

	snapshot.classifiedParts = classifiedParts
	snapshot.doorLeafCount = counts.doorLeafCount
	snapshot.collidableSectionCount = counts.collidableSectionCount
	snapshot.traversalVisualOnlySectionCount = counts.traversalVisualOnlySectionCount
	snapshot.visualOnlySectionCount = counts.visualOnlySectionCount
	snapshot.staleDestructibleCount = counts.staleDestructibleCount
	snapshot.materialProbeCount = counts.materialProbeCount
	snapshot.unknownGameplayCount = counts.unknownGameplayCount
	snapshot.unknownCount = counts.unknownCount
	snapshot.staleDestructibleSamples = staleSamples
	snapshot.unknownGameplaySamples = unknownGameplaySamples
	snapshot.unknownSamples = unknownSamples
	return snapshot
end

local function addRenderFactDiagnostics(renderFacts, diagnostics)
	if renderFacts.staleDestructibleCount > 0 then
		addDiagnostic(
			diagnostics,
			"render contract",
			("Imported render model still contains %d destructible wall render mesh(es): %s. Fresh occupancy-authoritative FBX must stay wall-free for destructible buckets."):format(
				renderFacts.staleDestructibleCount,
				table.concat(renderFacts.staleDestructibleSamples, ", ")
			)
		)
	end
	if renderFacts.unknownGameplayCount > 0 then
		addDiagnostic(
			diagnostics,
			"render contract",
			("Unexpected gameplay-tagged render mesh naming detected on %d part(s): %s. Unknown gameplay-relevant buckets must block setup."):format(
				renderFacts.unknownGameplayCount,
				table.concat(renderFacts.unknownGameplaySamples, ", ")
			)
		)
	end
	if renderFacts.unknownCount > 0 then
		addDiagnostic(
			diagnostics,
			"render contract",
			("Unsupported render part naming detected on %d part(s): %s. Setup keys off stable object names/section aliases only, so re-export or fix the imported asset before running Setup Building."):format(
				renderFacts.unknownCount,
				table.concat(renderFacts.unknownSamples, ", ")
			)
		)
	end
end

local function createBlockedPreflight(statusText, renderModel, buildingId, sidecarModel, diagnostics)
	return {
		ok = false,
		statusText = statusText,
		renderModel = renderModel,
		buildingId = buildingId,
		sidecarModel = sidecarModel,
		diagnostics = diagnostics,
		attach = nil,
	}
end

local function createReadyPreflight(attach)
	return {
		ok = true,
		statusText = ("Ready: %s\nPath: sidecar attach (%s)"):format(
			attach.renderModel:GetFullName(),
			attach.buildingId
		),
		renderModel = attach.renderModel,
		buildingId = attach.buildingId,
		sidecarModel = attach.sidecarModel,
		diagnostics = nil,
		attach = attach,
	}
end

local function findSidecarByBuildingId(buildingId)
	local matches = {}
	for _, desc in ipairs(game:GetDescendants()) do
		if desc:IsA("Model") and isSidecarModel(desc) then
			local contractFolder = findTypedChild(desc, DEFAULTS.contractFolderName, "Folder")
			local valueObject = findTypedChild(contractFolder, "BuildingId", "StringValue")
			if valueObject and valueObject.Value == buildingId then
				table.insert(matches, desc)
			end
		end
	end

	table.sort(matches, function(a, b)
		return a:GetFullName() < b:GetFullName()
	end)

	if #matches == 0 then
		return nil,
			("No RBXMX sidecar for BuildingId '%s' is currently inserted. Import %s%s.rbxmx, then run the plugin again."):format(
				buildingId,
				DEFAULTS.renderModelPrefix,
				buildingId
			)
	end

	if #matches > 1 then
		return nil,
			("Multiple sidecars were found for BuildingId '%s': %s. Keep exactly one inserted sidecar, then try again."):format(
				buildingId,
				formatInstanceNames(matches)
			)
	end

	return matches[1], nil
end

local function getRequiredChild(parent, name, className, diagnostics, category, message)
	local child = findTypedChild(parent, name, className)
	if child then
		return child
	end
	addDiagnostic(diagnostics, category, message)
	return nil
end

local function addPreflightCountDiagnostics(diagnostics, renderFacts, lightCount)
	addDiagnostic(diagnostics, "counts", ("Render meshes found: %d"):format(renderFacts.meshCount))
	addDiagnostic(
		diagnostics,
		"counts",
		("Collidable render sections found: %d"):format(renderFacts.collidableSectionCount)
	)
	addDiagnostic(
		diagnostics,
		"counts",
		("Traversal visual-only render sections found: %d"):format(renderFacts.traversalVisualOnlySectionCount)
	)
	addDiagnostic(
		diagnostics,
		"counts",
		("Visual-only render sections found: %d"):format(renderFacts.visualOnlySectionCount)
	)
	addDiagnostic(diagnostics, "counts", ("Light payload anchors found: %d"):format(lightCount))
end

local function buildAttachPreflight(renderModel, buildingId, sidecarModel, renderFacts)
	local diagnostics = createDiagnostics(renderModel)

	local sidecarPath = sidecarModel and sidecarModel:GetFullName() or "<missing>"
	local contractFolder = getRequiredChild(
		sidecarModel,
		DEFAULTS.contractFolderName,
		"Folder",
		diagnostics,
		"contract",
		("Sidecar %s is missing the __Contract folder."):format(sidecarPath)
	)
	local authorRoot = getRequiredChild(
		sidecarModel,
		DEFAULTS.authorRootName,
		"BasePart",
		diagnostics,
		"alignment",
		("Sidecar %s is missing __AuthorRoot."):format(sidecarPath)
	)
	local lightFolder = getRequiredChild(
		sidecarModel,
		DEFAULTS.lightFolderName,
		"Folder",
		diagnostics,
		"contract",
		("Sidecar %s is missing Lights."):format(sidecarPath)
	)
	local destructionSeedFolder = getRequiredChild(
		sidecarModel,
		DEFAULTS.destructionSeedFolderName,
		"Folder",
		diagnostics,
		"contract",
		("Sidecar %s is missing DestructionSeed."):format(sidecarPath)
	)
	local lightSnapshot = lightFolder and collectLightSnapshot(lightFolder) or {
		parts = {},
		count = 0,
	}

	local contractBuildingId = getRequiredChild(
		contractFolder,
		"BuildingId",
		"StringValue",
		diagnostics,
		"contract",
		"Sidecar contract is missing StringValue BuildingId."
	)
	local contractVersion = getRequiredChild(
		contractFolder,
		"ExportContractVersion",
		"StringValue",
		diagnostics,
		"contract",
		"Sidecar contract is missing StringValue ExportContractVersion."
	)
	local renderAnchorBasis = getRequiredChild(
		contractFolder,
		"RenderAnchorBasis",
		"StringValue",
		diagnostics,
		"alignment",
		"Sidecar contract is missing StringValue RenderAnchorBasis."
	)
	local renderAnchorToAuthorRoot = getRequiredChild(
		contractFolder,
		"RenderAnchorToAuthorRoot",
		"Vector3Value",
		diagnostics,
		"alignment",
		"Sidecar contract is missing Vector3Value RenderAnchorToAuthorRoot."
	)
	local authorRootScaleValue = getRequiredChild(
		contractFolder,
		CONTRACT_VALUE_AUTHOR_ROOT_SCALE,
		"NumberValue",
		diagnostics,
		"alignment",
		"Sidecar contract is missing NumberValue AuthorRootScale. Re-export the FBX + RBXMX sidecar with export contract 6.3.0+ before running Setup Building."
	)
	local renderBoundsSizeValue = getRequiredChild(
		contractFolder,
		"RenderBoundsSize",
		"Vector3Value",
		diagnostics,
		"alignment",
		"Sidecar contract is missing Vector3Value RenderBoundsSize."
	)
	local renderMeshCountValue = getRequiredChild(
		contractFolder,
		"RenderMeshCount",
		"IntValue",
		diagnostics,
		"contract",
		"Sidecar contract is missing IntValue RenderMeshCount."
	)
	local lightCountValue = getRequiredChild(
		contractFolder,
		"LightCount",
		"IntValue",
		diagnostics,
		"contract",
		"Sidecar contract is missing IntValue LightCount."
	)

	addRenderFactDiagnostics(renderFacts, diagnostics)

	if contractBuildingId and contractBuildingId.Value ~= buildingId then
		addDiagnostic(
			diagnostics,
			"building mismatch",
			("Selected render model resolves to BuildingId '%s' but the sidecar contract says '%s'."):format(
				buildingId,
				contractBuildingId.Value
			)
		)
	end

	local exportContractVersion = contractVersion and contractVersion.Value or EXPECTED_EXPORT_CONTRACT_VERSION
	if contractVersion and exportContractVersion ~= EXPECTED_EXPORT_CONTRACT_VERSION then
		addDiagnostic(
			diagnostics,
			"version mismatch",
			("Sidecar contract version mismatch: found %s, expected %s."):format(
				exportContractVersion,
				EXPECTED_EXPORT_CONTRACT_VERSION
			)
		)
	end

	if renderAnchorBasis and renderAnchorBasis.Value ~= DEFAULTS.renderAnchorBasis then
		addDiagnostic(
			diagnostics,
			"alignment",
			("RenderAnchorBasis mismatch: found %s, expected %s."):format(
				renderAnchorBasis.Value,
				DEFAULTS.renderAnchorBasis
			)
		)
	end
	if authorRootScaleValue and not isPositiveFiniteNumber(authorRootScaleValue.Value) then
		addDiagnostic(
			diagnostics,
			"alignment",
			("AuthorRootScale must be a positive finite number, got %s."):format(tostring(authorRootScaleValue.Value))
		)
	end

	if lightFolder then
		local missingLightFolders = {}
		for _, role in ipairs(LIGHT_ROLE_FAMILIES) do
			local roleFolder = lightFolder:FindFirstChild(role)
			if not (roleFolder and roleFolder:IsA("Folder")) then
				table.insert(missingLightFolders, role)
			end
		end
		if #missingLightFolders > 0 then
			addDiagnostic(
				diagnostics,
				"contract",
				"Sidecar light folders are incomplete. Missing: " .. table.concat(missingLightFolders, ", ")
			)
		end
	end

	local lightCount = lightSnapshot.count
	local renderMeshCountMatchesContract = false
	local renderBoundsMismatch = false
	local authorRootMismatch = false
	if lightCountValue and lightCount ~= lightCountValue.Value then
		addDiagnostic(
			diagnostics,
			"contract",
			("LightCount mismatch: contract=%d, actual=%d."):format(lightCountValue.Value, lightCount)
		)
	end

	if renderMeshCountValue and renderFacts.meshCount ~= renderMeshCountValue.Value then
		addDiagnostic(
			diagnostics,
			"alignment",
			("RenderMeshCount mismatch: contract=%d, selected render model has %d MeshParts."):format(
				renderMeshCountValue.Value,
				renderFacts.meshCount
			)
		)
	elseif renderMeshCountValue then
		renderMeshCountMatchesContract = true
	end

	if renderBoundsSizeValue and renderFacts.boundsSize then
		local delta = renderFacts.boundsSize - renderBoundsSizeValue.Value
		if
			math.abs(delta.X) > RENDER_BOUNDS_EPSILON
			or math.abs(delta.Y) > RENDER_BOUNDS_EPSILON
			or math.abs(delta.Z) > RENDER_BOUNDS_EPSILON
		then
			addDiagnostic(
				diagnostics,
				"alignment",
				("Render bounds mismatch. expected=%s actual=%s delta=%s"):format(
					formatVector3(renderBoundsSizeValue.Value),
					formatVector3(renderFacts.boundsSize),
					formatVector3(delta)
				)
			)
			renderBoundsMismatch = true
		end
	end

	local renderAuthorRoot = findRenderAuthorRoot(renderModel, buildingId)
	local targetAuthorRoot
	if not renderAuthorRoot then
		addDiagnostic(
			diagnostics,
			"alignment",
			("Imported render model is missing expected inner root '%s'. Re-import the FBX before attaching the sidecar."):format(
				expectedRenderRootName(buildingId)
			)
		)
	elseif renderFacts.boundsCFrame and renderAnchorToAuthorRoot then
		targetAuthorRoot = CFrame.fromMatrix(
			renderFacts.boundsCFrame.Position,
			renderFacts.pivot.XVector,
			renderFacts.pivot.YVector,
			renderFacts.pivot.ZVector
		) * CFrame.new(renderAnchorToAuthorRoot.Value)
		local authorRootDelta = renderAuthorRoot:GetPivot().Position - targetAuthorRoot.Position
		if
			math.abs(authorRootDelta.X) > RENDER_BOUNDS_EPSILON
			or math.abs(authorRootDelta.Y) > RENDER_BOUNDS_EPSILON
			or math.abs(authorRootDelta.Z) > RENDER_BOUNDS_EPSILON
		then
			addDiagnostic(
				diagnostics,
				"alignment",
				("Author-root mismatch. expected=%s actual=%s delta=%s"):format(
					formatVector3(targetAuthorRoot.Position),
					formatVector3(renderAuthorRoot:GetPivot().Position),
					formatVector3(authorRootDelta)
				)
			)
			authorRootMismatch = true
		end
	end

	if renderMeshCountMatchesContract and (renderBoundsMismatch or authorRootMismatch) then
		addDiagnostic(
			diagnostics,
			"action",
			("The selected RBXMX sidecar for BuildingId '%s' is stale versus the render model. Delete the old %s%s sidecar, import the newest %s%s.rbxmx that belongs to the current FBX, then run the plugin again."):format(
				buildingId,
				DEFAULTS.sidecarModelPrefix,
				buildingId,
				DEFAULTS.renderModelPrefix,
				buildingId
			)
		)
	end

	if lightCount <= 0 then
		addDiagnostic(diagnostics, "contract", "Sidecar light payload is empty.")
	end

	local seedData = nil
	local traversalData = nil
	if #diagnostics.issues <= 0 and destructionSeedFolder then
		seedData = readDestructionSeedFolder(destructionSeedFolder, diagnostics)
	end
	if #diagnostics.issues <= 0 and contractFolder then
		traversalData = decodeTraversalCollisionPayload(contractFolder, diagnostics)
	end

	if #diagnostics.issues > 0 then
		addPreflightCountDiagnostics(diagnostics, renderFacts, lightCount)
		return nil, finalizeDiagnostics(diagnostics)
	end

	return {
		renderModel = renderModel,
		buildingId = buildingId,
		sidecarModel = sidecarModel,
		contractFolder = contractFolder,
		authorRoot = authorRoot,
		lightFolder = lightFolder,
		destructionSeedFolder = destructionSeedFolder,
		targetAuthorRoot = targetAuthorRoot or renderAuthorRoot:GetPivot(),
		renderMeshCount = renderFacts.meshCount,
		renderBoundsSize = renderFacts.boundsSize,
		authorRootScale = authorRootScaleValue and authorRootScaleValue.Value or 1,
		lightCount = lightCount,
		exportContractVersion = exportContractVersion,
		seedData = seedData,
		traversalData = traversalData,
	},
		nil
end

local function preflightSelectedAttach()
	local renderModel, selectionError = resolveSelectedModel()
	if not renderModel then
		return createBlockedPreflight(selectionError)
	end

	if isSidecarModel(renderModel) then
		return createBlockedPreflight(
			"Select the imported render building model, not the temporary sidecar model.",
			renderModel
		)
	end
	local renderFacts = collectRenderFacts(renderModel)
	if renderFacts.meshCount <= 0 then
		return createBlockedPreflight(
			"Selected model has zero render MeshParts. Select the imported render building model.",
			renderModel
		)
	end

	local buildingId, idError = expectedBuildingIdFromRenderModel(renderModel)
	if not buildingId then
		return createBlockedPreflight(idError, renderModel)
	end

	local sidecarModel, sidecarError = findSidecarByBuildingId(buildingId)
	if not sidecarModel then
		return createBlockedPreflight(sidecarError, renderModel, buildingId)
	end

	local attach, diagnostics = buildAttachPreflight(renderModel, buildingId, sidecarModel, renderFacts)
	if not attach then
		return createBlockedPreflight(
			formatDiagnosticStatus(diagnostics),
			renderModel,
			buildingId,
			sidecarModel,
			diagnostics
		)
	end

	return createReadyPreflight(attach)
end

local function attachPreparedSidecar(preflight)
	local attach = preflight.attach
	if not attach then
		return nil
	end

	local ok, result = pcall(function()
		attach.sidecarModel.WorldPivot = attach.authorRoot.CFrame
		attach.sidecarModel:PivotTo(attach.targetAuthorRoot)

		local runtimeFolder = Instance.new("Folder")
		runtimeFolder.Name = DEFAULTS.runtimeFolderName
		attach.contractFolder.Parent = runtimeFolder
		attach.lightFolder.Parent = runtimeFolder
		attach.destructionSeedFolder.Parent = runtimeFolder

		local existingRuntime = attach.renderModel:FindFirstChild(DEFAULTS.runtimeFolderName)
		if existingRuntime then
			existingRuntime:Destroy()
		end
		runtimeFolder.Parent = attach.renderModel

		attach.authorRoot:Destroy()
		attach.sidecarModel:Destroy()

		attach.renderModel:SetAttribute(DEFAULTS.buildingIdAttribute, attach.buildingId)
		attach.renderModel:SetAttribute(DEFAULTS.runtimeContractAttribute, attach.exportContractVersion)
		attach.renderModel:SetAttribute(DEFAULTS.structureModeAttribute, nil)

		return {
			buildingId = attach.buildingId,
			model = attach.renderModel:GetFullName(),
			lights = attach.lightCount,
			exportContractVersion = attach.exportContractVersion,
			renderMeshCount = attach.renderMeshCount,
			renderBoundsSize = attach.renderBoundsSize,
			authorRootScale = attach.authorRootScale,
			seedData = attach.seedData,
			traversalData = attach.traversalData,
		}
	end)

	if not ok then
		error(result)
	end

	return result
end

local function ensureRuntimeForSetup(renderModel)
	local runtimeFolder = findTypedChild(renderModel, DEFAULTS.runtimeFolderName, "Folder")
	local seedFolder = runtimeFolder and findTypedChild(runtimeFolder, DEFAULTS.destructionSeedFolderName, "Folder")
	if runtimeFolder and seedFolder then
		return runtimeFolder, nil, nil
	end

	local preflight = preflightSelectedAttach()
	if not preflight.ok then
		return nil, preflight.statusText
	end
	local ok, attachResult = pcall(function()
		return attachPreparedSidecar(preflight)
	end)
	if not ok then
		return nil, ("Runtime attach failed before voxel-wall setup: %s"):format(tostring(attachResult))
	end
	local attachedRuntime = findTypedChild(renderModel, DEFAULTS.runtimeFolderName, "Folder")
	if not attachedRuntime then
		return nil, "Runtime attach did not produce __TBG_Runtime."
	end
	return attachedRuntime, nil, attachResult
end

local function configureVisualOnlyRenderPart(part, mode)
	CollectionService:RemoveTag(part, DESTRUCTIBLE_TAG)
	part.Anchored = true
	part.CastShadow = true
	part.CanCollide = false
	part.CanTouch = false
	part.CanQuery = false
	part:SetAttribute("TBG_RenderCollisionMode", mode or "VISUAL_ONLY")
end

local function configureCollidableRenderPart(part, mode)
	CollectionService:RemoveTag(part, DESTRUCTIBLE_TAG)
	part.Anchored = true
	part.CastShadow = true
	part.CanCollide = true
	part.CanTouch = false
	part.CanQuery = true
	part:SetAttribute("TBG_RenderCollisionMode", mode or "COLLIDABLE_RENDER")
end

local function configureWindowFillRenderPart(part)
	part.Material = WINDOW_FILL_RENDER_MATERIAL
	part.MaterialVariant = ""
	part.Color = WINDOW_FILL_RENDER_COLOR
	part:SetAttribute("TBG_WindowFillMaterialTruth", "TBG_WindowFill")
	configureCollidableRenderPart(part, "COLLIDABLE_RENDER")
end

local function configureDoorLeafRenderPart(part)
	configureCollidableRenderPart(part, "DOOR_LEAF")
	part.CollisionFidelity = Enum.CollisionFidelity.Box
end

local function collectMaterialProbeTextureIds(renderFacts)
	local textureIds = {}
	for _, entry in ipairs(renderFacts.classifiedParts) do
		local part = entry.part
		local policy = entry.policy
		if policy.kind == "MATERIAL_PROBE" and part:IsA("MeshPart") then
			local textureId = tostring(part.TextureID or "")
			if textureId ~= "" then
				textureIds[policy.family] = textureId
			end
		end
	end
	return textureIds
end

local function sanitizeRenderCollision(renderFacts)
	local renderSanitized = 0
	for _, entry in ipairs(renderFacts.classifiedParts) do
		local part = entry.part
		local policy = entry.policy
		if policy.kind == "DOOR_LEAF" then
			configureDoorLeafRenderPart(part)
		elseif policy.kind == "COLLIDABLE_SECTION" then
			if policy.alias == "OWF" then
				configureWindowFillRenderPart(part)
			else
				configureCollidableRenderPart(part, policy.mode or "COLLIDABLE_RENDER")
			end
		elseif policy.kind == "TRAVERSAL_VISUAL_ONLY_SECTION" then
			configureVisualOnlyRenderPart(part, "TRAVERSAL_VISUAL_ONLY")
		elseif policy.kind == "VISUAL_ONLY_SECTION" then
			configureVisualOnlyRenderPart(part, "VISUAL_ONLY")
		elseif policy.kind == "MATERIAL_PROBE" then
			part:Destroy()
		elseif policy.kind == "UNKNOWN" and not policy.hasGameplayTag then
			configureVisualOnlyRenderPart(part, "VISUAL_ONLY")
		else
			error(
				("Unexpected render collision policy for '%s' (%s)."):format(part:GetFullName(), tostring(policy.kind))
			)
		end
		renderSanitized = renderSanitized + 1
	end
	return {
		renderSanitized = renderSanitized,
	}
end

local function squaredColorDistance(a, b)
	local dr = a.R - b.R
	local dg = a.G - b.G
	local db = a.B - b.B
	return dr * dr + dg * dg + db * db
end

local function nearestBrickFamily(displayColor)
	local target = displayColor or BRICK_FAMILY_DISPLAY_COLORS.LIGHT_BRICK
	local bestFamily = "LIGHT_BRICK"
	local bestDistance = math.huge
	for family, color in pairs(BRICK_FAMILY_DISPLAY_COLORS) do
		local distance = squaredColorDistance(target, color)
		if distance < bestDistance then
			bestFamily = family
			bestDistance = distance
		end
	end
	return bestFamily
end

local function resolveVoxelWallAppearance(
	materialFamily,
	displayColor,
	visualStyle,
	materialProbeTextureIds,
	studsPerTile
)
	if tostring(materialFamily or "") == "BRICK" and tostring(visualStyle or "") == "BRICK_MASONRY" then
		local family = nearestBrickFamily(displayColor)
		local colorMap = materialProbeTextureIds and materialProbeTextureIds[family]
		if not colorMap or colorMap == "" then
			error(
				("Missing runtime brick material probe for %s. Re-export the FBX with TBG_MaterialProbe_BRICK_* probes so Studio can build the real TBG brick MaterialVariant."):format(
					family
				)
			)
		end
		local variantName = ("TBG_BrickMasonry_%s"):format(family)
		ensureMaterialVariant(variantName, Enum.Material.Brick, colorMap, studsPerTile)
		return {
			material = Enum.Material.Brick,
			materialVariant = variantName,
			color = Color3.new(1, 1, 1),
			castShadow = true,
		}
	end

	local appearance = VOXEL_WALL_APPEARANCE_BY_FAMILY[tostring(materialFamily or "")]
	if appearance then
		local styleAppearance = VOXEL_WALL_APPEARANCE_BY_STYLE[tostring(visualStyle or "")]
		local resolvedMaterial = styleAppearance and styleAppearance.material or appearance.material
		local resolvedMaterialVariant = styleAppearance and styleAppearance.materialVariant
			or appearance.materialVariant
		local resolvedColor = displayColor or (styleAppearance and styleAppearance.color) or appearance.color
		return {
			material = resolvedMaterial,
			materialVariant = resolvedMaterialVariant,
			color = resolvedColor,
			castShadow = appearance.castShadow,
		}
	end
	error(
		("Unsupported voxel wall material family '%s' during runtime materialization."):format(tostring(materialFamily))
	)
end

local function createConfiguredPart(
	parent,
	name,
	materialFamily,
	displayColor,
	visualStyle,
	materialProbeTextureIds,
	studsPerTile
)
	local appearance =
		resolveVoxelWallAppearance(materialFamily, displayColor, visualStyle, materialProbeTextureIds, studsPerTile)
	local part = Instance.new("Part")
	part.Name = name
	part.Shape = Enum.PartType.Block
	part.Anchored = true
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Material = appearance.material
	part.MaterialVariant = tostring(appearance.materialVariant or "")
	part.Color = appearance.color
	part.Transparency = 0
	part.CanCollide = true
	part.CanTouch = false
	part.CanQuery = true
	part.CastShadow = appearance.castShadow
	part.CollisionGroup = DEFAULTS.collisionGroupName
	part.Parent = parent
	return part
end

local function createVoxelWallHeader(parent, group, index)
	local header = Instance.new("Folder")
	header.Name = tostring(group.groupId or ("Group_%04d"):format(index))
	header:SetAttribute("TBG_VoxelWall", true)
	header:SetAttribute("TBG_VoxelWallId", group.groupId)
	header:SetAttribute("TBG_VoxelWallSourceBucket", group.sourceBucket)
	header:SetAttribute("TBG_VoxelWallMaterialFamily", group.materialFamily)
	if group.visualStyle ~= nil then
		header:SetAttribute("TBG_VoxelWallVisualStyle", group.visualStyle)
	end
	header:SetAttribute("TBG_VoxelWallTextureKey", group.textureKey)
	header:SetAttribute("TBG_VoxelWallTextureProjection", group.textureProjection)
	header:SetAttribute("TBG_VoxelWallStudsPerTileU", group.studsPerTileU)
	header:SetAttribute("TBG_VoxelWallStudsPerTileV", group.studsPerTileV)
	header:SetAttribute("TBG_VoxelWallSurfaceUOriginStuds", group.surfaceUOriginStuds)
	header:SetAttribute("TBG_VoxelWallSurfaceVOriginStuds", group.surfaceVOriginStuds)
	header.Parent = parent
	return header
end

local function addV3WallCellTextures(part, group, cell)
	if
		group.textureProjection == TEXTURE_PROJECTION_SOLID_COLOR_V1
		or group.textureProjection == TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
	then
		return 0
	end
	if group.textureProjection == TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 then
		error("ROBLOX_PART_TEXTURE_V1 is retired for V3 runtime walls; regenerate/export with 6.2.0.")
	end
	error(("Unsupported V3 texture_projection '%s'."):format(tostring(group.textureProjection)))
end

local function encodeV3CellBounds(cell)
	return HttpService:JSONEncode({
		min = {
			x = cell.minStuds.X,
			y = cell.minStuds.Y,
			z = cell.minStuds.Z,
		},
		size = {
			x = cell.sizeStuds.X,
			y = cell.sizeStuds.Y,
			z = cell.sizeStuds.Z,
		},
		normal_axis = cell.normalAxis,
		run_axis = cell.runAxis,
	})
end

local function materializeV3WallCell(parent, basePivot, authorRootScale, group, cell, materialProbeTextureIds)
	local part = createConfiguredPart(
		parent,
		("Cell_%s"):format(cell.cellId),
		group.materialFamily,
		group.displayColor,
		group.visualStyle,
		materialProbeTextureIds,
		group.studsPerTileU * authorRootScale
	)
	local scaledMinStuds = cell.minStuds * authorRootScale
	local scaledSizeStuds = cell.sizeStuds * authorRootScale
	local centerStuds = scaledMinStuds + scaledSizeStuds * 0.5
	local localCenter = convertBlenderLocalVectorToRoblox(centerStuds)
	part.Size = Vector3.new(scaledSizeStuds.X, scaledSizeStuds.Z, scaledSizeStuds.Y)
	part.CFrame = basePivot * CFrame.new(localCenter)
	part:SetAttribute("TBG_VoxelWallCell", true)
	part:SetAttribute("TBG_VoxelWallCellId", cell.cellId)
	part:SetAttribute("TBG_VoxelWallId", group.groupId)
	part:SetAttribute("TBG_VoxelWallMaterialFamily", group.materialFamily)
	part:SetAttribute("TBG_VoxelWallTextureKey", group.textureKey)
	part:SetAttribute("TBG_RenderCollisionMode", "DESTRUCTIBLE_WALL")
	part:SetAttribute("TBG_VoxelWallCellBoundsJson", encodeV3CellBounds(cell))
	part:SetAttribute("TBG_AuthorRootScale", authorRootScale)
	CollectionService:AddTag(part, DESTRUCTIBLE_TAG)
	local textureCount = addV3WallCellTextures(part, group, cell)
	return part, textureCount
end

local function readRuntimeAuthorRootScale(runtimeFolder, diagnostics)
	local contractFolder = findTypedChild(runtimeFolder, DEFAULTS.contractFolderName, "Folder")
	local scaleValue = findTypedChild(contractFolder, CONTRACT_VALUE_AUTHOR_ROOT_SCALE, "NumberValue")
	if not scaleValue then
		addDiagnostic(
			diagnostics,
			"alignment",
			"Runtime contract is missing NumberValue AuthorRootScale. Re-attach a 6.2.0+ sidecar before building V3 runtime walls."
		)
		return nil
	end
	if not isPositiveFiniteNumber(scaleValue.Value) then
		addDiagnostic(
			diagnostics,
			"alignment",
			("AuthorRootScale must be a positive finite number, got %s."):format(tostring(scaleValue.Value))
		)
		return nil
	end
	return scaleValue.Value
end

local function buildDestructionRuntime(
	renderModel,
	buildingId,
	runtimeFolder,
	renderFacts,
	preparedSeedData,
	preparedAuthorRootScale
)
	local diagnostics = createDiagnostics(renderModel)
	addRenderFactDiagnostics(renderFacts, diagnostics)
	local seedData = preparedSeedData or readDestructionSeed(runtimeFolder, diagnostics)
	local authorRootScale = preparedAuthorRootScale or readRuntimeAuthorRootScale(runtimeFolder, diagnostics)
	if not seedData or not authorRootScale or #diagnostics.issues > 0 then
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end

	local renderAuthorRoot = findRenderAuthorRoot(renderModel, buildingId)
	if not renderAuthorRoot then
		addDiagnostic(
			diagnostics,
			"alignment",
			("Imported render model is missing expected inner root '%s'. Re-import the FBX before running Setup Building."):format(
				expectedRenderRootName(buildingId)
			)
		)
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end
	local basePivot = renderAuthorRoot:GetPivot()
	local materialProbeTextureIds = collectMaterialProbeTextureIds(renderFacts)
	ensureCollisionGroup()
	ensureVoxelWallMaterialVariants(materialProbeTextureIds)
	local tempDestruction = runtimeFolder:FindFirstChild(DEFAULTS.destructionRuntimeTempFolderName)
	if tempDestruction then
		tempDestruction:Destroy()
	end
	tempDestruction = Instance.new("Folder")
	tempDestruction.Name = DEFAULTS.destructionRuntimeTempFolderName
	tempDestruction.Parent = runtimeFolder
	local collisionFolder = ensureFolder(tempDestruction, DEFAULTS.destructionCollisionFolderName)
	local createdCount = 0
	local textureChildCount = 0
	local ok, buildError = pcall(function()
		for groupIndex, group in ipairs(seedData.orderedGroups) do
			local groupFolder = createVoxelWallHeader(collisionFolder, group, groupIndex)
			for _, cell in ipairs(seedData.cellsByGroupId[group.groupId] or {}) do
				local _, cellTextureCount =
					materializeV3WallCell(groupFolder, basePivot, authorRootScale, group, cell, materialProbeTextureIds)
				textureChildCount = textureChildCount + cellTextureCount
				createdCount = createdCount + 1
			end
		end
	end)
	if not ok then
		tempDestruction:Destroy()
		error(buildError)
	end
	if createdCount ~= seedData.authoredCellCount then
		addDiagnostic(
			diagnostics,
			"destruction runtime",
			("Temp build parity check failed: authored=%d created=%d."):format(seedData.authoredCellCount, createdCount)
		)
		tempDestruction:Destroy()
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end
	local textureDescendantCount = 0
	for _, descendant in ipairs(collisionFolder:GetDescendants()) do
		if descendant:IsA("Texture") then
			textureDescendantCount = textureDescendantCount + 1
		end
	end
	if textureChildCount ~= 0 or textureDescendantCount ~= 0 then
		addDiagnostic(
			diagnostics,
			"destruction runtime",
			("V3 runtime walls must be zero-Texture: reported=%d descendants=%d."):format(
				textureChildCount,
				textureDescendantCount
			)
		)
		tempDestruction:Destroy()
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end

	local staleDestruction = findTypedChild(runtimeFolder, DEFAULTS.destructionRuntimeFolderName, "Folder")
	if staleDestruction then
		staleDestruction:Destroy()
	end
	tempDestruction.Name = DEFAULTS.destructionRuntimeFolderName

	renderModel:SetAttribute(DEFAULTS.structureModeAttribute, RUNTIME_MODE_DESTRUCTIBLE_PLUGIN_FIRST)
	return {
		authoredGroupCount = seedData.authoredGroupCount,
		authoredCellCount = seedData.authoredCellCount,
		createdCount = createdCount,
		textureChildCount = textureChildCount,
		chunkCount = seedData.chunkCount,
		removedStaleDestruction = staleDestruction ~= nil,
	},
		nil
end

local function createTraversalCollisionPart(parent, basePivot, seed, index)
	local className = seed.shapeType == "WEDGE" and "WedgePart" or "Part"
	local part = Instance.new(className)
	part.Name = ("RuntimeCollision_%s_%04d"):format(seed.role, index)
	part.Anchored = true
	part.Transparency = 1
	part.CanCollide = true
	part.CanTouch = false
	part.CanQuery = true
	part.CastShadow = false
	part.Size = seed.size
	part.CFrame = basePivot * CFrame.fromMatrix(seed.localCenter, seed.xAxis, seed.yAxis, seed.zAxis)
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.CollisionGroup = DEFAULTS.collisionGroupName
	part:SetAttribute("TBG_RenderCollisionMode", "TRAVERSAL_COLLISION")
	part:SetAttribute("TBG_TraversalRole", seed.role)
	part:SetAttribute("TBG_TraversalShape", seed.shapeType)
	part:SetAttribute("TBG_TraversalSourceName", seed.sourceName)
	part.Parent = parent
	return part
end

local function buildTraversalCollisionRuntime(
	renderModel,
	buildingId,
	runtimeFolder,
	renderFacts,
	preparedTraversalData
)
	local diagnostics = createDiagnostics(renderModel)
	addRenderFactDiagnostics(renderFacts, diagnostics)
	local traversalData = preparedTraversalData or readTraversalCollision(runtimeFolder, diagnostics)
	if not traversalData or #diagnostics.issues > 0 then
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end
	if renderFacts.traversalVisualOnlySectionCount > 0 and traversalData.count <= 0 then
		addDiagnostic(
			diagnostics,
			"traversal runtime",
			"Render floors/stairs are visual-only, but TraversalCollisionV1 has zero runtime collision seeds."
		)
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end

	local renderAuthorRoot = findRenderAuthorRoot(renderModel, buildingId)
	if not renderAuthorRoot then
		addDiagnostic(
			diagnostics,
			"alignment",
			("Imported render model is missing expected inner root '%s'. Re-import the FBX before running Setup Building."):format(
				expectedRenderRootName(buildingId)
			)
		)
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end

	ensureCollisionGroup()
	local basePivot = renderAuthorRoot:GetPivot()
	local tempTraversal = runtimeFolder:FindFirstChild(DEFAULTS.traversalCollisionTempFolderName)
	if tempTraversal then
		tempTraversal:Destroy()
	end
	tempTraversal = Instance.new("Folder")
	tempTraversal.Name = DEFAULTS.traversalCollisionTempFolderName
	tempTraversal.Parent = runtimeFolder

	local createdCount = 0
	local ok, buildError = pcall(function()
		for index, seed in ipairs(traversalData.seeds) do
			createTraversalCollisionPart(tempTraversal, basePivot, seed, index)
			createdCount = createdCount + 1
		end
	end)
	if not ok then
		tempTraversal:Destroy()
		error(buildError)
	end
	if createdCount ~= traversalData.count then
		addDiagnostic(
			diagnostics,
			"traversal runtime",
			("Temp traversal build parity check failed: authored=%d created=%d."):format(
				traversalData.count,
				createdCount
			)
		)
		tempTraversal:Destroy()
		return nil, finalizeDiagnostics(diagnostics) or diagnostics
	end

	local staleTraversal = findTypedChild(runtimeFolder, DEFAULTS.traversalCollisionFolderName, "Folder")
	if staleTraversal then
		staleTraversal:Destroy()
	end
	tempTraversal.Name = DEFAULTS.traversalCollisionFolderName

	return {
		createdCount = createdCount,
		removedStaleTraversal = staleTraversal ~= nil,
	}, nil
end

do
	local api = {}

	api.setupSelectedBuilding = function()
		local renderModel, selectionError = resolveSelectedModel()
		if not renderModel then
			return { ok = false, message = selectionError }
		end
		if isSidecarModel(renderModel) then
			return {
				ok = false,
				message = "Select the imported render building model, not the temporary sidecar model.",
			}
		end
		local buildingId, idError = expectedBuildingIdFromRenderModel(renderModel)
		if not buildingId then
			return { ok = false, message = idError }
		end

		ChangeHistoryService:SetWaypoint("TBG Setup Building Pre")
		local runtimeFolder, runtimeError, attachResult = ensureRuntimeForSetup(renderModel)
		if not runtimeFolder then
			return { ok = false, message = runtimeError }
		end

		local renderFacts = collectRenderFacts(renderModel)
		local ok, result, diagnostics = pcall(function()
			local setupResult, setupDiagnostics = buildDestructionRuntime(
				renderModel,
				buildingId,
				runtimeFolder,
				renderFacts,
				attachResult and attachResult.seedData or nil,
				attachResult and attachResult.authorRootScale or nil
			)
			return setupResult, setupDiagnostics
		end)
		if not ok then
			ChangeHistoryService:SetWaypoint("TBG Setup Building Post")
			warn("[TBG Runtime] Setup failure:", result)
			return {
				ok = false,
				message = "Setup failed.\nCheck Output for the full error.",
				error = tostring(result),
			}
		end
		if diagnostics and #diagnostics.issues > 0 then
			warn("[TBG Runtime] " .. formatDiagnosticSummary(diagnostics))
		end
		if not result then
			ChangeHistoryService:SetWaypoint("TBG Setup Building Post")
			return {
				ok = false,
				message = "Setup blocked.\nCheck Output for diagnostics.",
				diagnostics = diagnostics,
			}
		end

		local traversalOk, traversalResult, traversalDiagnostics = pcall(function()
			local setupResult, setupDiagnostics = buildTraversalCollisionRuntime(
				renderModel,
				buildingId,
				runtimeFolder,
				renderFacts,
				attachResult and attachResult.traversalData or nil
			)
			return setupResult, setupDiagnostics
		end)
		if not traversalOk then
			ChangeHistoryService:SetWaypoint("TBG Setup Building Post")
			warn("[TBG Runtime] Traversal setup failure:", traversalResult)
			return {
				ok = false,
				message = "Traversal setup failed.\nCheck Output for the full error.",
				error = tostring(traversalResult),
			}
		end
		if traversalDiagnostics and #traversalDiagnostics.issues > 0 then
			warn("[TBG Runtime] " .. formatDiagnosticSummary(traversalDiagnostics))
		end
		if not traversalResult then
			ChangeHistoryService:SetWaypoint("TBG Setup Building Post")
			return {
				ok = false,
				message = "Traversal setup blocked.\nCheck Output for diagnostics.",
				diagnostics = traversalDiagnostics,
			}
		end

		local sanitizeSummary = sanitizeRenderCollision(renderFacts)
		result.renderSanitized = sanitizeSummary.renderSanitized
		result.traversalCollisionCount = traversalResult.createdCount
		local lightFolder = findTypedChild(runtimeFolder, DEFAULTS.lightFolderName, "Folder")
		local lightCount = lightFolder and collectLightSnapshot(lightFolder).count or 0
		local runtimeStatus = attachResult and "attached" or "reused"
		local successMessage = string.format(
			"Setup ready: %s\nBuildingId: %s | Runtime: %s | Lights: %d | Authored Groups: %d | Authored Cells: %d | Wall-Cell Chunks: %d | Traversal Collision: %d",
			renderModel.Name,
			buildingId,
			runtimeStatus,
			lightCount,
			result.authoredGroupCount,
			result.authoredCellCount,
			result.chunkCount,
			result.traversalCollisionCount
		)
		print(
			string.format(
				"[TBG Runtime] setup complete | model=%s buildingId=%s runtime=%s lights=%d groups=%d authored=%d created=%d traversal=%d textures=%d chunks=%d",
				renderModel:GetFullName(),
				buildingId,
				runtimeStatus,
				lightCount,
				result.authoredGroupCount,
				result.authoredCellCount,
				result.createdCount,
				result.traversalCollisionCount,
				result.textureChildCount or 0,
				result.chunkCount
			)
		)
		ChangeHistoryService:SetWaypoint("TBG Setup Building Post")
		return {
			ok = true,
			message = successMessage,
			result = result,
			attachResult = attachResult,
		}
	end

	api.processSelectedBuilding = function()
		local warningMessage = string.format(
			"[TBG Runtime] %s() is deprecated; use %s() / Setup Building instead.",
			"processSelectedBuilding",
			SETUP_COMMAND_NAME
		)
		warn(warningMessage)
		local result = api.setupSelectedBuilding()
		result.deprecation = warningMessage
		return result
	end

	api.convertSelectedBuildingToDestructible = function()
		local warningMessage = string.format(
			"[TBG Runtime] %s() is deprecated; use %s() / Setup Building instead.",
			"convertSelectedBuildingToDestructible",
			SETUP_COMMAND_NAME
		)
		warn(warningMessage)
		local result = api.setupSelectedBuilding()
		result.deprecation = warningMessage
		return result
	end

	_G.TBG_BuildingPostProcessor = api

	SETUP_BUTTON.Click:Connect(function()
		local result = api.setupSelectedBuilding()
		if result.ok then
			print(("[TBG Runtime] Setup: %s"):format(tostring(result.message)))
			return
		end
		if result.diagnostics then
			warn("[TBG Runtime] " .. formatDiagnosticSummary(result.diagnostics))
		end
		if result.error then
			warn(("[TBG Runtime] Setup error: %s"):format(tostring(result.error)))
		end
		warn(("[TBG Runtime] Setup blocked: %s"):format(tostring(result.message)))
	end)
end
