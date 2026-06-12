INSPECTION_PROJECT_KEY = "OrthoManager"
INSPECTION_PROJECT_ENTRY = "inspection"
INSPECTION_GROUP = "🔎 検査"
FREE_INSPECTION_GROUP = INSPECTION_GROUP
INSPECTION_PROP_PREFIX = "OrthoManager/inspection/"
INSPECTION_TYPE_ORTHO = "ortho"
INSPECTION_TYPE_FREE = "free"
INSPECTION_TYPES = (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE)
FREE_GROUP_PATH_SEPARATOR = "/"
INSPECTION_GPKG_META_TABLE = "om_metadata"
INSPECTION_GPKG_TYPE_KEY = "inspection_type"
INSPECTION_GPKG_STATE_KEY = "inspection_state_v1"
INSPECTION_GPKG_STATE_VERSION = 1
GEOM_TYPE_LABELS = {"polygon": "ポリゴン", "line": "ライン", "point": "点"}
SHP_EXPORT_PER_LAYER = "shp_per_layer"
SHP_EXPORT_MERGED = "shp_merged"
DXF_EXPORT_ONE_FILE = "dxf_one_file"
DXF_EXPORT_PER_LAYER = "dxf_per_layer"
TEST_DXF_EXPORT_ONE_FILE = "ac2000_dxf_one_file"
TEST_DXF_EXPORT_PER_LAYER = "ac2000_dxf_per_layer"
DGN_EXPORT_ONE_FILE = "dgn_one_file"
DGN_EXPORT_PER_LAYER = "dgn_per_layer"
DGN_LEGACY_EXPORT_ONE_FILE = "dgn_legacy_one_file"
DGN_LEGACY_EXPORT_PER_LAYER = "dgn_legacy_per_layer"
CONTEXT_ACTION_ORDER_KEY = "OrthoManager/inspection/context_action_order"
CONTEXT_ACTION_BUTTON_WIDTH = 54
CONTEXT_ACTION_DEFAULT_ORDER = ["pan", "select", "select_polygon", "layer_change", "restore", "delete", "edit", "move", "merge"]
TRASH_LAYER_SOURCES = {
    "polygon": "_om_trash_polygon",
    "line": "_om_trash_line",
    "point": "_om_trash_point",
}
TRASH_GROUP_NAME = "🗑 OrthoManagerゴミ箱"
INSPECTION_SHORTCUTS_KEY_PREFIX = "OrthoManager/inspection/shortcuts/"
INSPECTION_DELETE_CONFIRM_KEY = "OrthoManager/inspection/delete_confirm"
INSPECTION_LAYER_CHANGE_CONFIRM_KEY = "OrthoManager/inspection/layer_change_confirm"
INSPECTION_LAST_GPKG_DIR_KEY = "OrthoManager/inspection/last_gpkg_dir"
INSPECTION_ANGLE_SNAP_DEGREES_KEY = "OrthoManager/inspection/angle_snap_degrees"
INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES = 45
INSPECTION_ANGLE_SNAP_ALLOWED_DEGREES = (0, 90, 45, 30, 15)
INSPECTION_ANGLE_SNAP_BASIS_KEY = "OrthoManager/inspection/angle_snap_basis"
INSPECTION_ANGLE_SNAP_BASIS_MAP = "map"
INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE = "previous_edge"
INSPECTION_ANGLE_SNAP_BASIS_DEFAULT = INSPECTION_ANGLE_SNAP_BASIS_MAP
INSPECTION_ANGLE_SNAP_BASIS_ALLOWED = (
    INSPECTION_ANGLE_SNAP_BASIS_MAP,
    INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE,
)
INSPECTION_SHORTCUT_DEFINITIONS = [
    ("pan", "パン", ""),
    ("select", "矩形選", ""),
    ("select_polygon", "多角選", ""),
    ("layer_change", "移層", ""),
    ("delete", "削除", "Del"),
    ("edit", "編集", ""),
    ("move", "移動", ""),
    ("merge", "統合", ""),
    ("continuous", "連続", ""),
    ("shape_polygon", "多角", ""),
    ("shape_fixed_angle_90", "直角多角", ""),
    ("shape_rectangle", "矩形", ""),
    ("shape_ellipse", "楕円", ""),
    ("shape_circle", "正円", ""),
    ("shape_line", "ライン", ""),
    ("shape_point", "点", ""),
    ("fixed_angle_90_length_copy", "ライン/多角/直角多角: 辺長コピーキー", "C"),
    ("fixed_angle_90_reference", "ライン/多角/直角多角: 参照点キー", "X"),
    ("parallel_direction_copy", "ライン/多角: 平行方向コピーキー", "Z"),
    ("angle_copy", "ライン/多角: 角度コピーキー", "V"),
]
INSPECTION_HOLD_SHORTCUT_KEYS = {
    "fixed_angle_90_length_copy",
    "fixed_angle_90_reference",
    "parallel_direction_copy",
    "angle_copy",
}


ROUND_ITEMS = {
    1: [
        ("01", "歪み", "ff0000"),
        ("02", "ズレ", "ff00ff"),
        ("03", "ハレーション", "ff8000"),
        ("04", "伸び", "00ff00"),
        ("05", "BLズレ", "ffff00"),
        ("06", "BL交差", "808000"),
        ("07", "GCPズレ", "00ffff"),
        ("08", "その他", "8000ff"),
        ("09", "隣接地区接合", "8080ff"),
    ],
    2: [
        ("21", "修正漏れ", "ff0000"),
        ("22", "修正不可", "0000ff"),
        ("23", "とりあえずOK", "808080"),
        ("24", "修正OK", "c0c0c0"),
        ("25", "再修正", "ff0000"),
    ],
    3: [
        ("31", "修正漏れ", "ff0000"),
        ("32", "修正不可", "0000ff"),
        ("33", "とりあえずOK", "808080"),
        ("34", "修正OK", "c0c0c0"),
        ("35", "再修正", "ff0000"),
    ],
    4: [
        ("41", "修正漏れ", "ff0000"),
        ("42", "修正不可", "0000ff"),
        ("43", "とりあえずOK", "808080"),
        ("44", "修正OK", "c0c0c0"),
        ("45", "再修正", "ff0000"),
    ],
}

ORTHO_ROUND_GROUP_NAMES = {round_no: f"オルソ{round_no}回目検査" for round_no in ROUND_ITEMS}
ORTHO_MODULE_GROUP_NAMES = set(ORTHO_ROUND_GROUP_NAMES.values())
LEGACY_ORTHO_MODULE_GROUP_NAMES = {f"{round_no}回目検査" for round_no in ROUND_ITEMS}
