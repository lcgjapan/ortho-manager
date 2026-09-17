from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import re
from qgis.core import QgsSettings


LANGUAGE_SETTING_KEY = "OrthoManager/language"
DEFAULT_LANGUAGE = "ja"

LANGUAGES = {
    "ja": "日本語",
    "en": "English",
    "zh": "中文",
}

TRANSLATIONS = {
    "tab.vrt": {
        "ja": "📁 VRT",
        "en": "📁 VRT",
        "zh": "📁 VRT",
    },
    "tab.inspection": {
        "ja": "🔎 検査",
        "en": "🔎 Insp.",
        "zh": "🔎 检查",
    },
    "tab.export": {
        "ja": "📤 出力",
        "en": "📤 Export",
        "zh": "📤 导出",
    },
    "tab.tools": {
        "ja": "🧰 ツール",
        "en": "🧰 Tools",
        "zh": "🧰 工具",
    },
    "tab.settings": {
        "ja": "⚙",
        "en": "⚙",
        "zh": "⚙",
    },
    "tooltip.settings": {
        "ja": "設定",
        "en": "Settings",
        "zh": "设置",
    },
    "tools.title": {
        "ja": "ツール",
        "en": "Tools",
        "zh": "工具",
    },
    "tools.elevation_raster.name": {
        "ja": "標高ラスタ作成",
        "en": "Elevation Raster",
        "zh": "高程栅格生成",
    },
    "tools.elevation_raster.title": {
        "ja": "標高ラスタ作成",
        "en": "Elevation Raster",
        "zh": "高程栅格生成",
    },
    "tools.elevation_raster.note": {
        "ja": "LAS/LAZから標高ラスタGeoTIFFを作成します。VPC、標高付きベクタ、ブレークライン等は次段階で追加します。",
        "en": "Create elevation raster GeoTIFFs from LAS/LAZ. VPC, elevation vectors, breaklines, and other inputs will be added later.",
        "zh": "从 LAS/LAZ 生成高程栅格 GeoTIFF。VPC、带高程矢量、断裂线等会在下一阶段添加。",
    },
    "tools.elevation_raster.input_group": {
        "ja": "入力データ",
        "en": "Input Data",
        "zh": "输入数据",
    },
    "tools.elevation_raster.input_note": {
        "ja": "LAS/LAZ、VPC、標高付きベクタを扱う予定です。",
        "en": "Planned inputs: LAS/LAZ, VPC, and elevation vector data.",
        "zh": "计划支持 LAS/LAZ、VPC、带高程的矢量数据。",
    },
    "tools.elevation_raster.add_files": {
        "ja": "LAS/LAZ追加",
        "en": "Add LAS/LAZ",
        "zh": "添加LAS/LAZ",
    },
    "tools.elevation_raster.add_folder": {
        "ja": "フォルダ追加",
        "en": "Add Folder",
        "zh": "添加文件夹",
    },
    "tools.elevation_raster.remove_selected": {
        "ja": "選択削除",
        "en": "Remove Selected",
        "zh": "删除所选",
    },
    "tools.elevation_raster.clear_inputs": {
        "ja": "クリア",
        "en": "Clear",
        "zh": "清空",
    },
    "tools.elevation_raster.show_extent": {
        "ja": "範囲表示",
        "en": "Show Extent",
        "zh": "显示范围",
    },
    "tools.elevation_raster.clear_extent": {
        "ja": "範囲消去",
        "en": "Clear Extent",
        "zh": "清除范围",
    },
    "tools.elevation_raster.auto_extent": {
        "ja": "追加・削除時に範囲を自動表示",
        "en": "Auto show extents after changes",
        "zh": "添加/删除后自动显示范围",
    },
    "tools.elevation_raster.input_count": {
        "ja": "入力 {count} 件",
        "en": "{count} input(s)",
        "zh": "输入 {count} 个",
    },
    "tools.elevation_raster.output_group": {
        "ja": "出力設定",
        "en": "Output Settings",
        "zh": "输出设置",
    },
    "tools.elevation_raster.output_note": {
        "ja": "出力名、解像度、標高種別、GeoTIFF保存先を指定できるようにする予定です。",
        "en": "Planned settings: output name, resolution, elevation type, and GeoTIFF destination.",
        "zh": "计划支持输出名称、分辨率、高程类型、GeoTIFF保存位置。",
    },
    "tools.elevation_raster.output_browse": {
        "ja": "保存先",
        "en": "Browse",
        "zh": "保存位置",
    },
    "tools.elevation_raster.layer_name": {
        "ja": "レイヤ名",
        "en": "Layer",
        "zh": "图层名",
    },
    "tools.elevation_raster.resolution": {
        "ja": "解像度",
        "en": "Resolution",
        "zh": "分辨率",
    },
    "tools.elevation_raster.radius": {
        "ja": "補間距離",
        "en": "Interpolation distance",
        "zh": "插值距离",
    },
    "tools.elevation_raster.radius_auto": {
        "ja": "自動（解像度×2）",
        "en": "Auto (resolution x2)",
        "zh": "自动（分辨率×2）",
    },
    "tools.elevation_raster.output_type": {
        "ja": "標高値の算出方法",
        "en": "Elevation value method",
        "zh": "高程值计算方式",
    },
    "tools.elevation_raster.output_type_tin": {
        "ja": "点群Z値からTIN",
        "en": "TIN from point Z values",
        "zh": "由点群Z值生成TIN",
    },
    "tools.elevation_raster.output_type_max": {
        "ja": "最大値（DSM向け）",
        "en": "Max",
        "zh": "最大值",
    },
    "tools.elevation_raster.output_type_min": {
        "ja": "最小値（DEM向け）",
        "en": "Min",
        "zh": "最小值",
    },
    "tools.elevation_raster.output_type_mean": {
        "ja": "平均",
        "en": "Mean",
        "zh": "平均",
    },
    "tools.elevation_raster.tin_edge": {
        "ja": "補間距離",
        "en": "Interpolation distance",
        "zh": "插值距离",
    },
    "tools.elevation_raster.tin_edge_tooltip": {
        "ja": "TINで点同士を結ぶ最大距離です。小さいほど空白が残りやすく、大きいほど穴を埋めますが、離れた図郭同士もつながる可能性があります。",
        "en": "Maximum distance for connecting points in the TIN. Smaller values leave more blank areas; larger values fill holes but may connect distant tiles.",
        "zh": "TIN中点与点连接的最大距离。值越小越容易保留空白，值越大越容易填补空洞，但也可能连接相距较远的图幅。",
    },
    "tools.elevation_raster.tin_edge_unlimited": {
        "ja": "距離制限なし（非推奨）",
        "en": "No distance limit (not recommended)",
        "zh": "无距离限制（不推荐）",
    },
    "tools.elevation_raster.tin_edge_unlimited_tooltip": {
        "ja": "どれだけ離れていてもTINで結びます。処理が遅くなりやすく、離れた図郭間にも面が作られるため通常は使いません。",
        "en": "Connects points regardless of distance. This can be slow and may create surfaces between distant tiles, so it is usually not recommended.",
        "zh": "无论距离多远都会用TIN连接。处理容易变慢，也可能在相距较远的图幅之间生成面，通常不建议使用。",
    },
    "tools.elevation_raster.tin_edge_auto": {
        "ja": "自動（解像度×2）",
        "en": "Auto (resolution x2)",
        "zh": "自动（分辨率×2）",
    },
    "tools.elevation_raster.tin_edge_auto_tooltip": {
        "ja": "出力解像度の2倍を使います。0.5mなら1.0mです。通常はこの設定が安全です。",
        "en": "Uses twice the output resolution. For 0.5 m output, this is 1.0 m. This is the usual safe setting.",
        "zh": "使用输出分辨率的2倍。0.5m时为1.0m。通常这个设置较安全。",
    },
    "tools.elevation_raster.tin_edge_manual": {
        "ja": "手動",
        "en": "Manual",
        "zh": "手动",
    },
    "tools.elevation_raster.tin_edge_manual_tooltip": {
        "ja": "穴や欠測部を埋めたい場合に距離を指定します。離れた図郭同士をつなぎたくない場合は、図郭間の空白より小さい値にしてください。",
        "en": "Specify a distance when filling holes or missing areas. To avoid connecting separated tiles, use a value smaller than the gap between them.",
        "zh": "需要填补空洞或缺测区域时指定距离。若不想连接相距较远的图幅，请设为小于图幅间空白的值。",
    },
    "tools.elevation_raster.tin_edge_distance": {
        "ja": "距離",
        "en": "Distance",
        "zh": "距离",
    },
    "tools.elevation_raster.tin_edge_distance_tooltip": {
        "ja": "手動時の補間距離です。この距離を超える点同士はTINで結びません。",
        "en": "Manual interpolation distance. Points farther apart than this distance are not connected in the TIN.",
        "zh": "手动补间距离。超过该距离的点不会在TIN中连接。",
    },
    "tools.elevation_raster.fill_method": {
        "ja": "空白セル",
        "en": "Blank cells",
        "zh": "空白像元",
    },
    "tools.elevation_raster.fill_method_none": {
        "ja": "埋めない",
        "en": "Do not fill",
        "zh": "不填补",
    },
    "tools.elevation_raster.fill_method_nearest": {
        "ja": "最近傍で埋める",
        "en": "Fill with nearest",
        "zh": "最近邻填补",
    },
    "tools.elevation_raster.fill_distance": {
        "ja": "補間距離",
        "en": "Fill distance",
        "zh": "填补距离",
    },
    "tools.elevation_raster.fill_distance_auto": {
        "ja": "自動（解像度×2）",
        "en": "Auto (resolution x2)",
        "zh": "自动（分辨率×2）",
    },
    "tools.elevation_raster.auto_load": {
        "ja": "作成後にQGISへ読み込む",
        "en": "Load into QGIS after creation",
        "zh": "生成后加载到QGIS",
    },
    "tools.elevation_raster.apply_selected_style": {
        "ja": "選択ラスタを段彩＋陰影表示",
        "en": "Apply Color Relief + Hillshade",
        "zh": "所选栅格设为分层设色+阴影",
    },
    "tools.elevation_raster.apply_selected_style_tooltip": {
        "ja": "外部で作成した標高ラスタ用。QGISで選択中のラスタに段彩・陰影・なめらか表示を適用します。GeoTIFF本体のZ値は変更しません。",
        "en": "For externally created elevation rasters. Applies color relief, hillshade, and smooth display to the selected QGIS raster. GeoTIFF Z values are not changed.",
        "zh": "用于外部生成的高程栅格。对QGIS中选中的栅格应用分层设色、阴影和平滑显示。不会修改GeoTIFF本体的Z值。",
    },
    "tools.elevation_raster.run": {
        "ja": "作成",
        "en": "Create",
        "zh": "生成",
    },
    "tools.elevation_raster.cancel": {
        "ja": "中止",
        "en": "Cancel",
        "zh": "中止",
    },
    "tools.elevation_raster.run_disabled": {
        "ja": "次段階で追加",
        "en": "Coming Next",
        "zh": "下一阶段添加",
    },
    "tools.elevation_raster.dialog_add_files": {
        "ja": "LAS/LAZを選択",
        "en": "Select LAS/LAZ",
        "zh": "选择LAS/LAZ",
    },
    "tools.elevation_raster.dialog_add_folder": {
        "ja": "LAS/LAZフォルダを選択",
        "en": "Select LAS/LAZ Folder",
        "zh": "选择LAS/LAZ文件夹",
    },
    "tools.elevation_raster.dialog_output": {
        "ja": "出力GeoTIFFを指定",
        "en": "Select Output GeoTIFF",
        "zh": "指定输出GeoTIFF",
    },
    "tools.elevation_raster.default_output_name": {
        "ja": "標高ラスタ.tif",
        "en": "elevation_raster.tif",
        "zh": "高程栅格.tif",
    },
    "tools.elevation_raster.las_filter": {
        "ja": "点群 (*.las *.laz)",
        "en": "Point cloud (*.las *.laz)",
        "zh": "点云 (*.las *.laz)",
    },
    "tools.elevation_raster.tif_filter": {
        "ja": "GeoTIFF (*.tif *.tiff)",
        "en": "GeoTIFF (*.tif *.tiff)",
        "zh": "GeoTIFF (*.tif *.tiff)",
    },
    "tools.elevation_raster.warning_title": {
        "ja": "標高ラスタ作成",
        "en": "Elevation Raster",
        "zh": "高程栅格生成",
    },
    "tools.elevation_raster.error_no_input": {
        "ja": "入力LAS/LAZを追加してください。",
        "en": "Add input LAS/LAZ files.",
        "zh": "请添加输入LAS/LAZ。",
    },
    "tools.elevation_raster.error_no_output": {
        "ja": "出力GeoTIFFの保存先を指定してください。",
        "en": "Select an output GeoTIFF path.",
        "zh": "请指定输出GeoTIFF保存位置。",
    },
    "tools.elevation_raster.error_output_dir": {
        "ja": "出力先フォルダが見つかりません。",
        "en": "Output folder was not found.",
        "zh": "找不到输出文件夹。",
    },
    "tools.elevation_raster.error_load_failed": {
        "ja": "作成したGeoTIFFをQGISへ読み込めませんでした。",
        "en": "Created GeoTIFF could not be loaded into QGIS.",
        "zh": "生成的GeoTIFF无法加载到QGIS。",
    },
    "tools.elevation_raster.error_no_selected_raster": {
        "ja": "QGISで表示設定を適用するラスタレイヤを選択してください。",
        "en": "Select a raster layer in QGIS before applying the display style.",
        "zh": "请先在QGIS中选择要应用显示设置的栅格图层。",
    },
    "tools.elevation_raster.error_style_apply_failed": {
        "ja": "表示設定を適用できませんでした。\n{error}",
        "en": "Could not apply the display style.\n{error}",
        "zh": "无法应用显示设置。\n{error}",
    },
    "tools.elevation_raster.extent_crs_title": {
        "ja": "入力範囲の座標系を選択",
        "en": "Select CRS for Input Extents",
        "zh": "选择输入范围坐标系",
    },
    "tools.elevation_raster.extent_layer_name": {
        "ja": "標高ラスタ入力範囲",
        "en": "Elevation Raster Input Extents",
        "zh": "高程栅格输入范围",
    },
    "tools.elevation_raster.error_extent_failed": {
        "ja": "LAS/LAZの範囲を読み取れませんでした。",
        "en": "Could not read LAS/LAZ extents.",
        "zh": "无法读取LAS/LAZ范围。",
    },
    "tools.elevation_raster.extent_done": {
        "ja": "範囲表示 {count} 件",
        "en": "Displayed {count} extent(s)",
        "zh": "已显示 {count} 个范围",
    },
    "tools.elevation_raster.extent_skipped": {
        "ja": "読取失敗 {count} 件",
        "en": "{count} skipped",
        "zh": "{count} 个读取失败",
    },
    "tools.elevation_raster.status_running": {
        "ja": "作成中...",
        "en": "Creating...",
        "zh": "生成中...",
    },
    "tools.elevation_raster.status_canceling": {
        "ja": "中止中...",
        "en": "Canceling...",
        "zh": "正在中止...",
    },
    "tools.elevation_raster.status_canceled": {
        "ja": "中止しました",
        "en": "Canceled",
        "zh": "已中止",
    },
    "tools.elevation_raster.status_done": {
        "ja": "完了 {seconds:.1f}秒",
        "en": "Done {seconds:.1f}s",
        "zh": "完成 {seconds:.1f}秒",
    },
    "tools.elevation_raster.status_done_quality": {
        "ja": "完了 {seconds:.1f}秒 / NoData {nodata_percent:.1f}% / Z {min_z:.3f}〜{max_z:.3f}",
        "en": "Done {seconds:.1f}s / NoData {nodata_percent:.1f}% / Z {min_z:.3f}-{max_z:.3f}",
        "zh": "完成 {seconds:.1f}秒 / NoData {nodata_percent:.1f}% / Z {min_z:.3f}〜{max_z:.3f}",
    },
    "tools.elevation_raster.status_done_quality_no_valid": {
        "ja": "完了 {seconds:.1f}秒 / 有効セルなし",
        "en": "Done {seconds:.1f}s / no valid cells",
        "zh": "完成 {seconds:.1f}秒 / 没有有效像元",
    },
    "tools.elevation_raster.status_failed": {
        "ja": "作成失敗",
        "en": "Failed",
        "zh": "生成失败",
    },
    "tools.elevation_raster.status_style_applied": {
        "ja": "段彩＋陰影表示: {name}",
        "en": "Color relief + hillshade: {name}",
        "zh": "分层设色+阴影: {name}",
    },
    "tools.rrim.name": {
        "ja": "RRIM作成",
        "en": "RRIM",
        "zh": "RRIM生成",
    },
    "tools.rrim.title": {
        "ja": "RRIM作成",
        "en": "RRIM",
        "zh": "RRIM生成",
    },
    "tools.rrim.note": {
        "ja": "標高ラスタGeoTIFFから赤色立体図（Red Relief Image Map / RRIM）を作成します。",
        "en": "Create a Red Relief Image Map (RRIM) GeoTIFF from an elevation raster.",
        "zh": "从高程栅格GeoTIFF生成红色立体图（Red Relief Image Map / RRIM）。",
    },
    "tools.rrim.input_group": {
        "ja": "入力ラスタ",
        "en": "Input Raster",
        "zh": "输入栅格",
    },
    "tools.rrim.input_note": {
        "ja": "標高ラスタGeoTIFFを指定してください。",
        "en": "Select an elevation raster GeoTIFF.",
        "zh": "请选择高程栅格GeoTIFF。",
    },
    "tools.rrim.output_group": {
        "ja": "出力設定",
        "en": "Output Settings",
        "zh": "输出设置",
    },
    "tools.rrim.output_note": {
        "ja": "RRIM GeoTIFFの保存先と表現を指定します。",
        "en": "Set the output RRIM GeoTIFF path and expression.",
        "zh": "指定RRIM GeoTIFF保存位置和表现方式。",
    },
    "tools.rrim.input_browse": {
        "ja": "入力",
        "en": "Input",
        "zh": "输入",
    },
    "tools.rrim.current_layer": {
        "ja": "選択レイヤ",
        "en": "Current Layer",
        "zh": "当前图层",
    },
    "tools.rrim.output_browse": {
        "ja": "保存先",
        "en": "Save To",
        "zh": "保存到",
    },
    "tools.rrim.preset_label": {
        "ja": "表現",
        "en": "Expression",
        "zh": "表现",
    },
    "tools.rrim.preset_standard": {
        "ja": "標準",
        "en": "Standard",
        "zh": "标准",
    },
    "tools.rrim.preset_strong": {
        "ja": "強め",
        "en": "Strong",
        "zh": "较强",
    },
    "tools.rrim.preset_weak": {
        "ja": "弱め",
        "en": "Weak",
        "zh": "较弱",
    },
    "tools.rrim.load_to_qgis": {
        "ja": "作成後にQGISへ読み込む",
        "en": "Load into QGIS after creation",
        "zh": "生成后加载到QGIS",
    },
    "tools.rrim.run": {
        "ja": "作成",
        "en": "Create",
        "zh": "生成",
    },
    "tools.rrim.cancel": {
        "ja": "中止",
        "en": "Cancel",
        "zh": "中止",
    },
    "tools.rrim.status_ready": {
        "ja": "準備完了",
        "en": "Ready",
        "zh": "准备完成",
    },
    "tools.rrim.status_running": {
        "ja": "作成中...",
        "en": "Creating...",
        "zh": "生成中...",
    },
    "tools.rrim.status_canceling": {
        "ja": "中止中...",
        "en": "Canceling...",
        "zh": "正在中止...",
    },
    "tools.rrim.status_done": {
        "ja": "完了 {seconds:.1f}秒",
        "en": "Done {seconds:.1f}s",
        "zh": "完成 {seconds:.1f}秒",
    },
    "tools.rrim.status_failed": {
        "ja": "作成失敗",
        "en": "Failed",
        "zh": "生成失败",
    },
    "tools.rrim.warning_title": {
        "ja": "警告",
        "en": "Warning",
        "zh": "警告",
    },
    "tools.rrim.overwrite_title": {
        "ja": "上書き確認",
        "en": "Overwrite",
        "zh": "覆盖确认",
    },
    "tools.rrim.overwrite_message": {
        "ja": "既存ファイルを上書きしますか？\n{path}",
        "en": "Overwrite the existing file?\n{path}",
        "zh": "是否覆盖已有文件？\n{path}",
    },
    "tools.rrim.input_dialog_title": {
        "ja": "標高ラスタを選択",
        "en": "Select Elevation Raster",
        "zh": "选择高程栅格",
    },
    "tools.rrim.output_dialog_title": {
        "ja": "RRIM保存先を選択",
        "en": "Select RRIM Output",
        "zh": "选择RRIM保存位置",
    },
    "tools.rrim.input_filter": {
        "ja": "GeoTIFF (*.tif *.tiff);;すべてのファイル (*.*)",
        "en": "GeoTIFF (*.tif *.tiff);;All Files (*.*)",
        "zh": "GeoTIFF (*.tif *.tiff);;所有文件 (*.*)",
    },
    "tools.rrim.output_filter": {
        "ja": "GeoTIFF (*.tif *.tiff)",
        "en": "GeoTIFF (*.tif *.tiff)",
        "zh": "GeoTIFF (*.tif *.tiff)",
    },
    "tools.rrim.error_no_current_raster": {
        "ja": "現在選択中のラスタレイヤがありません。",
        "en": "No raster layer is currently selected.",
        "zh": "当前没有选择栅格图层。",
    },
    "tools.rrim.error_current_raster_path": {
        "ja": "選択レイヤの元ファイルを確認できません。",
        "en": "The selected layer source file could not be found.",
        "zh": "无法确认所选图层的源文件。",
    },
    "tools.rrim.error_input_required": {
        "ja": "入力ラスタを指定してください。",
        "en": "Select an input raster.",
        "zh": "请选择输入栅格。",
    },
    "tools.rrim.error_input_missing": {
        "ja": "入力ラスタが見つかりません。",
        "en": "Input raster was not found.",
        "zh": "找不到输入栅格。",
    },
    "tools.rrim.error_output_required": {
        "ja": "保存先を指定してください。",
        "en": "Select an output path.",
        "zh": "请指定保存位置。",
    },
    "tools.rrim.error_output_dir_missing": {
        "ja": "保存先フォルダが見つかりません。",
        "en": "Output folder was not found.",
        "zh": "找不到保存文件夹。",
    },
    "tools.rrim.error_same_path": {
        "ja": "入力ラスタと同じファイルには保存できません。",
        "en": "Output cannot be the same file as input.",
        "zh": "不能保存到与输入栅格相同的文件。",
    },
    "tools.rrim.error_load_failed": {
        "ja": "作成したRRIMをQGISへ読み込めませんでした。",
        "en": "The created RRIM could not be loaded into QGIS.",
        "zh": "生成的RRIM无法加载到QGIS。",
    },
    "settings.title": {
        "ja": "共通設定",
        "en": "Settings",
        "zh": "通用设置",
    },
    "settings.language_group": {
        "ja": "言語",
        "en": "Language",
        "zh": "语言",
    },
    "settings.language_label": {
        "ja": "表示言語",
        "en": "Lang.",
        "zh": "显示语言",
    },
    "settings.language_note": {
        "ja": "未翻訳の項目は日本語で表示します。",
        "en": "Untranslated: Japanese.",
        "zh": "未翻译的项目将以日语显示。",
    },
    "settings.future_group": {
        "ja": "今後追加する共通機能",
        "en": "Tools",
        "zh": "今后追加的通用功能",
    },
    "settings.future_note": {
        "ja": "ログ開始、ログリセット、キャッシュ共通設定などをここへ追加します。",
        "en": "Logs, reset, cache tools.",
        "zh": "日志开始、日志重置、缓存通用设置等功能会添加到这里。",
    },
    "settings.rating_group": {
        "ja": "評価のお願い",
        "en": "Rating",
        "zh": "评分请求",
    },
    "settings.rating_note": {
        "ja": "OrthoManager が役に立ったら、QGIS公式プラグインページで評価をいただけるとうれしいです！\nありがとうございます。",
        "en": "If OrthoManager is useful, a rating on the official QGIS plugin page would be appreciated.\nThank you!",
        "zh": "如果 OrthoManager 对您有帮助，欢迎在 QGIS 官方插件页面给予评价。\n谢谢！",
    },
    "settings.log_group": {
        "ja": "ログ",
        "en": "Log",
        "zh": "日志",
    },
    "settings.btn.log_start": {
        "ja": "ログ開始",
        "en": "Log Start",
        "zh": "日志开始",
    },
    "settings.tooltip.log_start": {
        "ja": "次のテストログの開始位置をQGISログに記録します",
        "en": "Mark the next test log start.",
        "zh": "在QGIS日志中记录下一次测试日志的开始位置",
    },
    "settings.status.log_start": {
        "ja": "ログ開始位置を記録しました",
        "en": "Log start marked",
        "zh": "已记录日志开始位置",
    },
    "settings.xyz_group": {
        "ja": "XYZ表示",
        "en": "XYZ Display",
        "zh": "XYZ显示",
    },
    "settings.xyz_checkbox": {
        "ja": "下部ステータスバーにZを表示",
        "en": "Show Z in the bottom status bar",
        "zh": "在底部状态栏显示Z",
    },
    "settings.tooltip.xyz_checkbox": {
        "ja": "マウス位置のラスタZとZ付きベクタZを表示します",
        "en": "Show raster Z and 3D vector Z at the mouse position.",
        "zh": "显示鼠标位置的栅格Z和三维矢量Z。",
    },
    "settings.xyz_note": {
        "ja": "DSM/DEMラスタは Z(R)、Z付きベクタは Z(V) として表示します。LAS点群の直接Z取得は今後の拡張候補です。",
        "en": "DSM/DEM rasters are shown as Z(R), and 3D vectors as Z(V). Direct LAS point cloud Z is planned for a later enhancement.",
        "zh": "DSM/DEM栅格显示为 Z(R)，带Z的矢量显示为 Z(V)。LAS点云的直接Z读取作为后续扩展。",
    },
    "settings.status.xyz_on": {
        "ja": "XYZ表示 ON",
        "en": "XYZ display ON",
        "zh": "XYZ显示 ON",
    },
    "settings.status.xyz_off": {
        "ja": "XYZ表示 OFF",
        "en": "XYZ display OFF",
        "zh": "XYZ显示 OFF",
    },
    "settings.hotkey_group": {
        "ja": "操作補助",
        "en": "Operation Assist",
        "zh": "操作辅助",
    },
    "settings.space_layer_checkbox": {
        "ja": "マップ上でもSpaceで選択レイヤ表示切替",
        "en": "Use Space on the map to toggle selected layer visibility",
        "zh": "在地图上也用Space切换所选图层显示",
    },
    "settings.tooltip.space_layer_checkbox": {
        "ja": "マップ操作中にSpaceキーで、レイヤパネルで選択中のレイヤまたはグループの表示ON/OFFを切り替えます",
        "en": "While the map has focus, Space toggles visibility for the selected layer or group in the layer panel.",
        "zh": "地图获得焦点时，按Space切换图层面板中所选图层或组的显示ON/OFF。",
    },
    "settings.space_layer_note": {
        "ja": "OFFにすると、QGIS標準のSpace操作に戻します。文字入力中や属性表では反応しません。",
        "en": "Turn this off to restore the standard QGIS Space behavior. It does not react while typing or in attribute tables.",
        "zh": "关闭后恢复QGIS标准Space操作。文字输入中和属性表中不会触发。",
    },
    "settings.status.space_layer_on": {
        "ja": "Space表示切替 ON",
        "en": "Space visibility toggle ON",
        "zh": "Space显示切换 ON",
    },
    "settings.status.space_layer_off": {
        "ja": "Space表示切替 OFF",
        "en": "Space visibility toggle OFF",
        "zh": "Space显示切换 OFF",
    },
    "status.language_changed": {
        "ja": "表示言語を変更しました",
        "en": "Display language changed",
        "zh": "显示语言已更改",
    },
    "status.ready": {
        "ja": "準備完了",
        "en": "Ready",
        "zh": "准备完成",
    },
    "inspection.group.management": {
        "ja": "検査管理",
        "en": "Insp.",
        "zh": "检查管理",
    },
    "inspection.path": {
        "ja": "検査GPKG: {path}",
        "en": "GPKG: {path}",
        "zh": "检查GPKG: {path}",
    },
    "inspection.path.none": {
        "ja": "未作成",
        "en": "None",
        "zh": "未创建",
    },
    "inspection.type.ortho": {
        "ja": "オルソ検査",
        "en": "Ortho",
        "zh": "正射检查",
    },
    "inspection.type.free": {
        "ja": "自由式検査",
        "en": "Free",
        "zh": "自由检查",
    },
    "inspection.btn.new": {
        "ja": "検査作成",
        "en": "Create",
        "zh": "创建检查",
    },
    "inspection.btn.load": {
        "ja": "検査読込",
        "en": "Load",
        "zh": "读取",
    },
    "inspection.btn.export": {
        "ja": "検査書出",
        "en": "Export",
        "zh": "导出",
    },
    "inspection.btn.on": {
        "ja": "検査ON",
        "en": "ON",
        "zh": "检查ON",
    },
    "inspection.group.rounds": {
        "ja": "検査回",
        "en": "Rounds",
        "zh": "检查轮次",
    },
    "inspection.btn.round_add": {
        "ja": "{round}回目追加",
        "en": "Add {round}",
        "zh": "添加第{round}次",
    },
    "inspection.guide.group": {
        "ja": "検査線作成",
        "en": "Guide lines",
        "zh": "检查线创建",
    },
    "inspection.guide.create": {
        "ja": "作成",
        "en": "Create",
        "zh": "创建",
    },
    "inspection.group.items": {
        "ja": "検査項目",
        "en": "Items",
        "zh": "检查项目",
    },
    "inspection.group.edit": {
        "ja": "編集",
        "en": "Edit",
        "zh": "编辑",
    },
    "inspection.btn.select_feature": {
        "ja": "地物選択",
        "en": "Select",
        "zh": "选择地物",
    },
    "inspection.btn.delete": {
        "ja": "削除",
        "en": "Del",
        "zh": "删除",
    },
    "inspection.btn.edit": {
        "ja": "編集",
        "en": "Edit",
        "zh": "编辑",
    },
    "inspection.btn.merge": {
        "ja": "統合",
        "en": "Merge",
        "zh": "合并",
    },
    "inspection.btn.shortcut": {
        "ja": "ショートカット設定",
        "en": "Keys",
        "zh": "快捷键",
    },
    "inspection.chk.delete_confirm": {
        "ja": "削除確認",
        "en": "Confirm Del",
        "zh": "删除确认",
    },
    "inspection.group.layers": {
        "ja": "レイヤ管理",
        "en": "Layers",
        "zh": "图层管理",
    },
    "inspection.btn.layer_add": {
        "ja": "レイヤ追加",
        "en": "Layer+",
        "zh": "添加图层",
    },
    "inspection.btn.vector_import": {
        "ja": "ベクタ取込",
        "en": "Import",
        "zh": "导入矢量",
    },
    "inspection.btn.qgis_import": {
        "ja": "QGISレイヤ取込",
        "en": "QGIS In",
        "zh": "导入QGIS",
    },
    "inspection.btn.layer_rename": {
        "ja": "レイヤ名変更",
        "en": "Rename",
        "zh": "改图层名",
    },
    "inspection.btn.color": {
        "ja": "色変更",
        "en": "Color",
        "zh": "改颜色",
    },
    "inspection.btn.layer_move": {
        "ja": "レイヤ移動",
        "en": "Move Lyr",
        "zh": "移动图层",
    },
    "inspection.btn.group_add": {
        "ja": "グループ追加",
        "en": "Group+",
        "zh": "添加组",
    },
    "inspection.btn.group_rename": {
        "ja": "グループ名変更",
        "en": "Grp Name",
        "zh": "改组名",
    },
    "inspection.btn.manual_delete": {
        "ja": "手動削除",
        "en": "Del Man.",
        "zh": "删除手动",
    },
    "inspection.btn.round_delete": {
        "ja": "検査回削除",
        "en": "Del Round",
        "zh": "删除轮次",
    },
    "inspection.btn.group_delete": {
        "ja": "グループ削除",
        "en": "Del Grp",
        "zh": "删除组",
    },
    "inspection.btn.type_delete.free": {
        "ja": "自由式削除",
        "en": "Del Free",
        "zh": "删除自由",
    },
    "inspection.btn.type_delete.ortho": {
        "ja": "ｵﾙｿ検査削除",
        "en": "Del Ortho",
        "zh": "删除正射",
    },
    "inspection.btn.empty_delete": {
        "ja": "空地物削除",
        "en": "Clean",
        "zh": "删除空地物",
    },
    "inspection.btn.organize": {
        "ja": "レイヤ整理",
        "en": "Arrange",
        "zh": "整理图层",
    },
    "inspection.items.select_prompt": {
        "ja": "右クリックで検査項目を選択してください",
        "en": "Right-click to select item.",
        "zh": "请右键选择检查项目",
    },
    "inspection.items.create_free": {
        "ja": "レイヤ追加から作成してください",
        "en": "Use Layer+.",
        "zh": "请从添加图层创建",
    },
    "inspection.items.create_ortho": {
        "ja": "検査を作成してください",
        "en": "Create inspection.",
        "zh": "请创建检查",
    },
    "inspection.menu.main": {
        "ja": "メイン",
        "en": "Main",
        "zh": "主菜单",
    },
    "inspection.menu.reselect": {
        "ja": "再選択",
        "en": "Re-sel",
        "zh": "重选",
    },
    "inspection.menu.cancel": {
        "ja": "やめる",
        "en": "Cancel",
        "zh": "取消",
    },
    "inspection.menu.continuous": {
        "ja": "連続",
        "en": "Cont.",
        "zh": "连续",
    },
    "inspection.menu.continuous_tooltip": {
        "ja": "連続作図のON/OFF",
        "en": "Toggle continuous drawing",
        "zh": "连续绘制开关",
    },
    "inspection.menu.shape_polygon": {
        "ja": "多角",
        "en": "Poly",
        "zh": "多边",
    },
    "inspection.menu.shape_fixed_angle_90": {
        "ja": "直角多角",
        "en": "90 Poly",
        "zh": "直角多边",
    },
    "inspection.menu.shape_rectangle": {
        "ja": "矩形",
        "en": "Rect",
        "zh": "矩形",
    },
    "inspection.menu.shape_ellipse": {
        "ja": "楕円",
        "en": "Oval",
        "zh": "椭圆",
    },
    "inspection.menu.shape_circle": {
        "ja": "正円",
        "en": "Circle",
        "zh": "正圆",
    },
    "inspection.menu.shape_polygon_tooltip": {
        "ja": "多角形を作成",
        "en": "Draw polygon",
        "zh": "创建多边形",
    },
    "inspection.menu.shape_fixed_angle_90_tooltip": {
        "ja": "90度の辺で直角多角形を作成",
        "en": "Draw a 90-degree polygon",
        "zh": "创建90度直角多边形",
    },
    "inspection.menu.shape_rectangle_tooltip": {
        "ja": "矩形を作成",
        "en": "Draw rectangle",
        "zh": "创建矩形",
    },
    "inspection.menu.shape_ellipse_tooltip": {
        "ja": "楕円を作成",
        "en": "Draw ellipse",
        "zh": "创建椭圆",
    },
    "inspection.menu.shape_circle_tooltip": {
        "ja": "正円を作成",
        "en": "Draw circle",
        "zh": "创建正圆",
    },
    "inspection.menu.add_layer": {
        "ja": "＋ レイヤ追加",
        "en": "+ Layer",
        "zh": "+ 图层",
    },
    "inspection.menu.add_group": {
        "ja": "＋ グループ追加",
        "en": "+ Group",
        "zh": "+ 分组",
    },
    "inspection.menu.manual_layers": {
        "ja": "手動レイヤ",
        "en": "Manual",
        "zh": "手动图层",
    },
    "inspection.menu.round_title": {
        "ja": "オルソ{round}回目検査",
        "en": "Round {round}",
        "zh": "第{round}次检查",
    },
    "inspection.menu.action.pan": {
        "ja": "パン",
        "en": "Pan",
        "zh": "平移",
    },
    "inspection.menu.action.select": {
        "ja": "矩形選",
        "en": "Rect",
        "zh": "矩形选",
    },
    "inspection.menu.action.select_polygon": {
        "ja": "多角選",
        "en": "Poly",
        "zh": "多角选",
    },
    "inspection.menu.action.layer_change": {
        "ja": "移層",
        "en": "Move L",
        "zh": "移层",
    },
    "inspection.menu.action.delete": {
        "ja": "削除",
        "en": "Del",
        "zh": "删除",
    },
    "inspection.menu.action.edit": {
        "ja": "編集",
        "en": "Edit",
        "zh": "编辑",
    },
    "inspection.menu.action.move": {
        "ja": "移動",
        "en": "Move",
        "zh": "移动",
    },
    "inspection.menu.action.merge": {
        "ja": "統合",
        "en": "Merge",
        "zh": "合并",
    },
    "inspection.menu.tip.pan": {
        "ja": "地図を移動",
        "en": "Pan mode",
        "zh": "返回平移",
    },
    "inspection.menu.tip.select": {
        "ja": "矩形で選択",
        "en": "Select by rectangle",
        "zh": "用矩形范围选择检查数据",
    },
    "inspection.menu.tip.select_polygon": {
        "ja": "多角形で選択",
        "en": "Select by polygon",
        "zh": "用多角形范围选择检查数据",
    },
    "inspection.menu.tip.layer_change": {
        "ja": "選択図形を別レイヤへ移層",
        "en": "Move to layer",
        "zh": "移动到其他图层",
    },
    "inspection.menu.tip.delete": {
        "ja": "選択図形を削除",
        "en": "Delete data",
        "zh": "删除选择数据",
    },
    "inspection.menu.tip.edit": {
        "ja": "選択図形を編集",
        "en": "Vertex edit",
        "zh": "节点编辑",
    },
    "inspection.menu.tip.move": {
        "ja": "選択図形を移動",
        "en": "Drag move",
        "zh": "拖动移动",
    },
    "inspection.menu.tip.merge": {
        "ja": "選択図形を統合",
        "en": "Merge data",
        "zh": "合并选择数据",
    },
    "inspection.menu.layer_rename": {
        "ja": "レイヤ名変更",
        "en": "Rename",
        "zh": "改图层名",
    },
    "inspection.menu.color": {
        "ja": "色変更",
        "en": "Color",
        "zh": "改颜色",
    },
    "inspection.menu.size": {
        "ja": "線・点サイズ変更",
        "en": "Size",
        "zh": "线/点大小",
    },
    "inspection.menu.group_rename": {
        "ja": "グループ名変更",
        "en": "Rename Grp",
        "zh": "改组名",
    },
    "inspection.menu.group_delete": {
        "ja": "グループ削除",
        "en": "Del Grp",
        "zh": "删除组",
    },
    "export.group.input": {
        "ja": "1. 入力データ設定",
        "en": "1. Input",
        "zh": "1. 输入数据",
    },
    "export.info.target": {
        "ja": "ℹ 出力対象はレイヤパネル表示順（ON）の全ラスタ",
        "en": "ℹ Output uses visible rasters in layer order",
        "zh": "ℹ 输出对象为图层面板中显示的全部栅格",
    },
    "export.chk.include_vector": {
        "ja": "表示中のベクタデータも画像に焼き付ける",
        "en": "Burn visible vectors",
        "zh": "将显示中的矢量也烧录到图像",
    },
    "export.group.bounds": {
        "ja": "2. 出力範囲（図郭）設定",
        "en": "2. Range",
        "zh": "2. 输出范围",
    },
    "export.label.zukaku": {
        "ja": "図郭レイヤ：",
        "en": "Grid:",
        "zh": "图郭图层:",
    },
    "export.btn.map_select": {
        "ja": "🖱 マップから選択 (ESCで解除)",
        "en": "🖱 Select on map (ESC)",
        "zh": "🖱 从地图选择(ESC)",
    },
    "export.label.id": {
        "ja": "図郭ID：",
        "en": "ID:",
        "zh": "图郭ID:",
    },
    "export.group.output": {
        "ja": "3. 出力設定",
        "en": "3. Output",
        "zh": "3. 输出设置",
    },
    "export.rb.split": {
        "ja": "図郭ごとに出力",
        "en": "By grid",
        "zh": "按图郭输出",
    },
    "export.rb.single": {
        "ja": "1ファイルで出力",
        "en": "Single file",
        "zh": "输出为一个文件",
    },
    "export.tooltip.single": {
        "ja": "選択図郭がある場合は選択図郭、ない場合は全図郭の外接矩形を1ファイルで出力します",
        "en": "Selected grids, or all-grid bounds, as one file.",
        "zh": "有选择图郭时输出选择范围，否则输出全部图郭外接矩形为一个文件",
    },
    "export.label.name": {
        "ja": "名前：",
        "en": "Name:",
        "zh": "名称:",
    },
    "export.label.outdir": {
        "ja": "出力フォルダ：",
        "en": "Folder:",
        "zh": "输出文件夹:",
    },
    "export.label.format": {
        "ja": "形式：",
        "en": "Fmt:",
        "zh": "格式:",
    },
    "export.format.tif_tfw": {
        "ja": "TIF＋TFW",
        "en": "TIF+TFW",
        "zh": "TIF+TFW",
    },
    "export.format.geotiff": {
        "ja": "GeoTIFF",
        "en": "GeoTIFF",
        "zh": "GeoTIFF",
    },
    "export.format.tfw_only": {
        "ja": "TFWのみ",
        "en": "TFW only",
        "zh": "仅TFW",
    },
    "export.format.jpg_jgw": {
        "ja": "JPG＋JGW",
        "en": "JPG+JGW",
        "zh": "JPG+JGW",
    },
    "export.format.ecw": {
        "ja": "ECW",
        "en": "ECW",
        "zh": "ECW",
    },
    "export.format.pdf": {
        "ja": "PDF",
        "en": "PDF",
        "zh": "PDF",
    },
    "export.label.resolution": {
        "ja": "解像度(m)：",
        "en": "Res:",
        "zh": "分辨率(m):",
    },
    "export.placeholder.source_res": {
        "ja": "元画像通り",
        "en": "Source",
        "zh": "按原图",
    },
    "export.label.bit": {
        "ja": "ビット：",
        "en": "Bit:",
        "zh": "位深:",
    },
    "export.label.resample": {
        "ja": "補間：",
        "en": "Int:",
        "zh": "插值:",
    },
    "export.group.options": {
        "ja": "4. 高度なオプション",
        "en": "4. Options",
        "zh": "4. 高级选项",
    },
    "export.chk.skip_empty": {
        "ja": "ラスタ実データがない図郭はスキップ",
        "en": "Skip empty grids",
        "zh": "跳过无栅格实数据图郭",
    },
    "export.tooltip.skip_empty": {
        "ja": "出力対象ラスタに実データがない図郭を出力せずにスキップします",
        "en": "Skip grids with no real raster data.",
        "zh": "跳过输出对象栅格没有实数据的图郭",
    },
    "export.chk.skip_solid": {
        "ja": "図郭内に同色の場合はスキップ：",
        "en": "Skip solid:",
        "zh": "同色时跳过:",
    },
    "export.chk.background": {
        "ja": "背景色処理",
        "en": "BG",
        "zh": "背景色处理",
    },
    "export.tooltip.background": {
        "ja": "ON: 選択した背景色を反映します / OFF: 背景処理を行いません",
        "en": "ON: use selected background / OFF: no background processing",
        "zh": "ON: 使用选择背景色 / OFF: 不进行背景处理",
    },
    "export.label.bg": {
        "ja": "背景色：",
        "en": "BG:",
        "zh": "背景色:",
    },
    "export.label.mode": {
        "ja": "モード：",
        "en": "Mode:",
        "zh": "模式:",
    },
    "export.label.workers": {
        "ja": "並列数：",
        "en": "Jobs:",
        "zh": "并行数:",
    },
    "export.btn.log_start": {
        "ja": "ログ開始",
        "en": "Log",
        "zh": "日志开始",
    },
    "export.tooltip.log_start": {
        "ja": "次のテストログの開始位置をQGISログに記録します",
        "en": "Mark the next test log start.",
        "zh": "在QGIS日志中记录下一次测试日志的开始位置",
    },
    "export.btn.run": {
        "ja": "🚀 書き出し実行",
        "en": "🚀 Export",
        "zh": "🚀 执行导出",
    },
    "export.color.white": {
        "ja": "白",
        "en": "White",
        "zh": "白",
    },
    "export.color.black": {
        "ja": "黒",
        "en": "Black",
        "zh": "黑",
    },
    "export.color.transparent": {
        "ja": "透明",
        "en": "Alpha",
        "zh": "透明",
    },
    "export.color.project": {
        "ja": "プロジェクト色",
        "en": "Project",
        "zh": "项目色",
    },
    "export.depth.24": {
        "ja": "24bit フルカラー (RGB: 透過なし)",
        "en": "24bit RGB",
        "zh": "24bit RGB",
    },
    "export.depth.32": {
        "ja": "32bit フルカラー (RGBA: 透過あり)",
        "en": "32bit RGBA",
        "zh": "32bit RGBA",
    },
    "export.depth.8": {
        "ja": "8bit (Byte)",
        "en": "8bit Byte",
        "zh": "8bit Byte",
    },
    "export.depth.u16": {
        "ja": "16bit 無符号 (UInt16)",
        "en": "16bit UInt",
        "zh": "16bit 无符号",
    },
    "export.depth.i16": {
        "ja": "16bit 有符号 (Int16)",
        "en": "16bit Int",
        "zh": "16bit 有符号",
    },
    "export.depth.f32": {
        "ja": "32bit 浮動小数点 (Float32)",
        "en": "32bit Float",
        "zh": "32bit 浮点",
    },
    "export.resample.nearest": {
        "ja": "最近傍法 (Nearest)",
        "en": "Nearest",
        "zh": "最近邻",
    },
    "export.resample.cubic": {
        "ja": "キュービック (Cubic)",
        "en": "Cubic",
        "zh": "三次卷积",
    },
    "export.resample.bilinear": {
        "ja": "バイリニア (Bilinear)",
        "en": "Bilinear",
        "zh": "双线性",
    },
    "export.mode.fast": {
        "ja": "標準高速",
        "en": "Fast",
        "zh": "标准高速",
    },
    "export.mode.standard": {
        "ja": "標準 2.18",
        "en": "Std 2.18",
        "zh": "标准 2.18",
    },
    "export.mode.warp": {
        "ja": "診断: Warp直接出力",
        "en": "Diag: Warp",
        "zh": "诊断: Warp直接输出",
    },
    "export.mode.warp_post": {
        "ja": "診断: Warp直接＋後処理",
        "en": "Diag: Warp+Post",
        "zh": "诊断: Warp+后处理",
    },
    "export.mode.shape": {
        "ja": "診断: 図郭形状そのまま",
        "en": "Diag: Shape",
        "zh": "诊断: 保持图郭形状",
    },
    "export.mode.rect": {
        "ja": "診断: 矩形最速",
        "en": "Diag: Rect",
        "zh": "诊断: 矩形最快",
    },
    "export.mode.vrt": {
        "ja": "診断: 選択VRT直接",
        "en": "Diag: VRT",
        "zh": "诊断: 选择VRT直接",
    },
    "vrt.group.vrt": {
        "ja": "VRT管理",
        "en": "VRT",
        "zh": "VRT管理",
    },
    "vrt.group.files": {
        "ja": "ファイル管理",
        "en": "Files",
        "zh": "文件管理",
    },
    "vrt.group.scale": {
        "ja": "表示縮尺設定",
        "en": "Scale",
        "zh": "显示比例",
    },
    "vrt.group.scale.with_target": {
        "ja": "{base}（対象: {target}）",
        "en": "{base} (Target: {target})",
        "zh": "{base}（对象：{target}）",
    },
    "vrt.scale.target.vrt": {
        "ja": "VRT",
        "en": "VRT",
        "zh": "VRT",
    },
    "vrt.scale.target.vpc": {
        "ja": "VPC",
        "en": "VPC",
        "zh": "VPC",
    },
    "vrt.btn.new": {
        "ja": "新規",
        "en": "New",
        "zh": "新建",
    },
    "vrt.btn.rename": {
        "ja": "名前変更",
        "en": "Rename",
        "zh": "改名",
    },
    "vrt.btn.load": {
        "ja": "VRT読込",
        "en": "Load",
        "zh": "读取",
    },
    "vrt.btn.delete": {
        "ja": "削除",
        "en": "Del",
        "zh": "删除",
    },
    "vrt.btn.organize": {
        "ja": "レイヤ整理",
        "en": "Arrange",
        "zh": "整理",
    },
    "vrt.btn.file_manager": {
        "ja": "ファイル一覧",
        "en": "File List",
        "zh": "文件列表",
    },
    "vrt.label.file_count": {
        "ja": "ファイル数：{count}ファイル",
        "en": "Files: {count}",
        "zh": "文件数：{count}",
    },
    "vrt.label.manual": {
        "ja": "手動  ",
        "en": "Manual",
        "zh": "手动",
    },
    "vrt.btn.apply": {
        "ja": "適用",
        "en": "Apply",
        "zh": "应用",
    },
    "vrt.btn.all": {
        "ja": "🌐 全表示",
        "en": "🌐 All",
        "zh": "🌐 全显",
    },
    "vrt.btn.view_cache": {
        "ja": "ﾋﾞｭｰｷｬｯｼｭ",
        "en": "View",
        "zh": "视图",
    },
    "vrt.btn.custom_cache": {
        "ja": "独自ｷｬｯｼｭ",
        "en": "Cache",
        "zh": "缓存",
    },
    "vrt.btn.screen_shield": {
        "ja": "画面ｼｰﾙﾄﾞ",
        "en": "Shield",
        "zh": "屏盾",
    },
    "vrt.btn.mouse_shield": {
        "ja": "ﾏｳｽｼｰﾙﾄﾞ",
        "en": "Mouse",
        "zh": "鼠盾",
    },
    "vrt.btn.mouse_shield_4x": {
        "ja": "ﾏｳｽ4x",
        "en": "Mouse 4x",
        "zh": "鼠盾4x",
    },
    "vrt.btn.mouse_shield_5x": {
        "ja": "ﾏｳｽ5x",
        "en": "Mouse 5x",
        "zh": "鼠盾5x",
    },
    "vrt.btn.mouse_shield_6x": {
        "ja": "ﾏｳｽ6x",
        "en": "Mouse 6x",
        "zh": "鼠盾6x",
    },
    "vrt.btn.build": {
        "ja": "⚡ VRT生成・更新",
        "en": "⚡ Build/Update",
        "zh": "⚡ 生成/更新",
    },
    "vpc.group": {
        "ja": "点群VPC",
        "en": "Point Cloud VPC",
        "zh": "点云VPC",
    },
    "vpc.btn.new": {
        "ja": "新規",
        "en": "New",
        "zh": "新建",
    },
    "vpc.btn.rename": {
        "ja": "名前変更",
        "en": "Rename",
        "zh": "改名",
    },
    "vpc.btn.load": {
        "ja": "VPC読込",
        "en": "Load",
        "zh": "读取",
    },
    "vpc.btn.delete": {
        "ja": "削除",
        "en": "Del",
        "zh": "删除",
    },
    "vpc.btn.organize": {
        "ja": "レイヤ整理",
        "en": "Arrange",
        "zh": "整理",
    },
    "vpc.btn.refresh_cache": {
        "ja": "キャッシュ更新",
        "en": "Refresh",
        "zh": "刷新缓存",
    },
    "vpc.btn.update": {
        "ja": "VPC更新",
        "en": "Update VPC",
        "zh": "更新VPC",
    },
    "vpc.btn.update.tooltip": {
        "ja": "VPCを再作成します。変更されたLAS/LAZのCOPCだけを更新します。\nQGIS内部キャッシュの影響で点群表示が乱れる場合は、QGISを再起動してください。",
        "en": "Rebuild the VPC and update COPC only for changed LAS/LAZ files.\nIf point-cloud display is disrupted by the QGIS internal cache, restart QGIS.",
        "zh": "重新创建VPC，仅更新已变更LAS/LAZ对应的COPC。\n如因QGIS内部缓存导致点云显示异常，请重启QGIS。",
    },
    "vpc.btn.source_list": {
        "ja": "点群一覧",
        "en": "Sources",
        "zh": "点云列表",
    },
    "vpc.btn.build": {
        "ja": "⚡ VPC作成・読込",
        "en": "⚡ Build/Load VPC",
        "zh": "⚡ 生成/读取VPC",
    },
    "vpc.label.file_count": {
        "ja": "点群数：{count}ファイル",
        "en": "Point clouds: {count}",
        "zh": "点云数：{count}",
    },
    "vpc.window.title": {
        "ja": "点群ファイル一覧",
        "en": "Point Cloud Sources",
        "zh": "点云文件列表",
    },
    "vpc.label.vpc_path": {
        "ja": "VPC:",
        "en": "VPC:",
        "zh": "VPC:",
    },
    "vpc.placeholder.vpc_path": {
        "ja": "VPCファイルの保存先",
        "en": "VPC output path",
        "zh": "VPC保存位置",
    },
    "vpc.placeholder.search": {
        "ja": "検索",
        "en": "Search",
        "zh": "搜索",
    },
    "vpc.checkbox.subfolders": {
        "ja": "サブフォルダも対象",
        "en": "Include subfolders",
        "zh": "包含子文件夹",
    },
    "vpc.btn.add_folder": {
        "ja": "フォルダ追加",
        "en": "Add Folder",
        "zh": "添加文件夹",
    },
    "vpc.btn.add_files": {
        "ja": "ファイル追加",
        "en": "Add Files",
        "zh": "添加文件",
    },
    "vpc.btn.map_remove": {
        "ja": "マップから削除",
        "en": "Map Remove",
        "zh": "从地图删除",
    },
    "vpc.btn.remove": {
        "ja": "選択削除",
        "en": "Remove",
        "zh": "删除所选",
    },
    "vpc.btn.clear": {
        "ja": "全削除",
        "en": "Clear",
        "zh": "全部删除",
    },
    "vpc.label.scale": {
        "ja": "VPC縮尺",
        "en": "VPC Scale",
        "zh": "VPC比例",
    },
    "vpc.btn.scale_apply": {
        "ja": "適用",
        "en": "Apply",
        "zh": "应用",
    },
    "vpc.btn.scale_all": {
        "ja": "全表示",
        "en": "All",
        "zh": "全显示",
    },
    "vrt.tooltip.view_cache.on": {
        "ja": "ビューキャッシュをONにします",
        "en": "Turn view cache on",
        "zh": "开启视图缓存",
    },
    "vrt.tooltip.view_cache.off": {
        "ja": "ビューキャッシュをOFFにします",
        "en": "Turn view cache off",
        "zh": "关闭视图缓存",
    },
    "vrt.tooltip.custom_cache.on": {
        "ja": "独自キャッシュをONにします",
        "en": "Turn custom cache on",
        "zh": "开启自定义缓存",
    },
    "vrt.tooltip.custom_cache.off": {
        "ja": "独自キャッシュをOFFにします",
        "en": "Turn custom cache off",
        "zh": "关闭自定义缓存",
    },
    "vrt.tooltip.screen_shield.on": {
        "ja": "画面シールドをONにします",
        "en": "Turn screen shield on",
        "zh": "开启屏幕盾",
    },
    "vrt.tooltip.screen_shield.off": {
        "ja": "画面シールドをOFFにします",
        "en": "Turn screen shield off",
        "zh": "关闭屏幕盾",
    },
    "vrt.tooltip.mouse_shield.on": {
        "ja": "マウスシールドをONにします",
        "en": "Turn mouse shield on",
        "zh": "开启鼠标盾",
    },
    "vrt.tooltip.mouse_shield.off": {
        "ja": "マウスシールドをOFFにします",
        "en": "Turn mouse shield off",
        "zh": "关闭鼠标盾",
    },
    "tif.window.title": {
        "ja": "ファイル管理",
        "en": "Files",
        "zh": "文件管理",
    },
    "tif.label.vrt_path": {
        "ja": "VRT場所：",
        "en": "VRT path:",
        "zh": "VRT位置：",
    },
    "tif.placeholder.vrt_path": {
        "ja": "VRTパス",
        "en": "VRT path",
        "zh": "VRT路径",
    },
    "tif.placeholder.search": {
        "ja": "🔍 ファイル名で検索",
        "en": "🔍 Search file",
        "zh": "🔍 搜索文件",
    },
    "tif.btn.sort_added": {
        "ja": "追加順",
        "en": "Added",
        "zh": "追加",
    },
    "tif.btn.sort_name": {
        "ja": "名前順",
        "en": "Name",
        "zh": "名称",
    },
    "tif.count": {
        "ja": "{count} ファイル",
        "en": "{count} files",
        "zh": "{count} 文件",
    },
    "tif.chk.subfolders": {
        "ja": "サブフォルダも読み込む",
        "en": "Subfolders",
        "zh": "含子文件夹",
    },
    "tif.btn.folder_add": {
        "ja": "📂 フォルダ追加",
        "en": "📂 Folder",
        "zh": "📂 文件夹",
    },
    "tif.btn.files_add": {
        "ja": "🖼 ファイル追加",
        "en": "🖼 Files",
        "zh": "🖼 文件",
    },
    "tif.btn.map_remove": {
        "ja": "🖱 マップから削除",
        "en": "🖱 Map Del",
        "zh": "🖱 图上删",
    },
    "tif.btn.remove_selected": {
        "ja": "❌ 選択を削除",
        "en": "❌ Del Sel",
        "zh": "❌ 删所选",
    },
    "tif.btn.clear": {
        "ja": "🗑 全削除",
        "en": "🗑 Clear",
        "zh": "🗑 全删",
    },
    "tif.btn.close": {
        "ja": "閉じる",
        "en": "Close",
        "zh": "关闭",
    },
}


def normalize_language(language):
    if language in LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def current_language():
    try:
        value = QgsSettings().value(LANGUAGE_SETTING_KEY, DEFAULT_LANGUAGE)
    except Exception:
        value = DEFAULT_LANGUAGE
    return normalize_language(str(value))


def set_current_language(language):
    language = normalize_language(language)
    try:
        QgsSettings().setValue(LANGUAGE_SETTING_KEY, language)
    except Exception:
        _om_record_ignored_exception(__name__, 1782)
    return language


def tr(key, language=None):
    language = normalize_language(language or current_language())
    values = TRANSLATIONS.get(key, {})
    return values.get(language) or values.get(DEFAULT_LANGUAGE) or key

TEXT_EXACT_TRANSLATIONS = {
    "ログ開始位置を記録しました": {"en": "Log start position recorded", "zh": "已记录日志开始位置"},
    "書き出し中": {"en": "Exporting", "zh": "正在导出"},
    "キャンセル確認": {"en": "Confirm Cancel", "zh": "确认取消"},
    "警告": {"en": "Warning", "zh": "警告"},
    "エラー": {"en": "Error", "zh": "错误"},
    "情報": {"en": "Information", "zh": "信息"},
    "確認": {"en": "Confirm", "zh": "确认"},
    "完了": {"en": "Complete", "zh": "完成"},
    "キャンセル": {"en": "Cancel", "zh": "取消"},
    "検査書出": {"en": "Export Inspection", "zh": "导出检查"},
    "検査メモ": {"en": "Inspection Memo", "zh": "检查备注"},
    "検査ショートカット設定": {"en": "Inspection Shortcut Settings", "zh": "检查快捷键设置"},
    "地図座標基準": {"en": "Map Coordinate Basis", "zh": "地图坐标基准"},
    "直前辺基準": {"en": "Previous Edge Basis", "zh": "前一边基准"},
    "ベクタ取込": {"en": "Import Vector", "zh": "导入矢量"},
    "QGISレイヤ取込": {"en": "Import QGIS Layer", "zh": "导入QGIS图层"},
    "形式:": {"en": "Format:", "zh": "格式："},
    "出力方法:": {"en": "Output method:", "zh": "输出方式："},
    "書き出す検査レイヤ:": {"en": "Inspection layers to export:", "zh": "要导出的检查图层："},
    "レイヤごとにSHP作成": {"en": "Create one SHP per layer", "zh": "每个图层创建一个SHP"},
    "同じ図形タイプなら1つのSHPにまとめる": {"en": "Merge into one SHP when geometry types match", "zh": "图形类型相同时合并为一个SHP"},
    "Enter: OK / Ctrl+Enter: 改行": {"en": "Enter: OK / Ctrl+Enter: New line", "zh": "Enter：确定 / Ctrl+Enter：换行"},
    "検査ONでOrthoManagerの検査マップ操作中だけ有効です。": {"en": "Enabled only while using OrthoManager inspection map tools with Inspection ON.", "zh": "仅在检查ON并使用OrthoManager检查地图操作时有效。"},
    "指定角度単位": {"en": "Angle Step", "zh": "指定角度单位"},
    "角度補正基準": {"en": "Angle Snap Basis", "zh": "角度修正基准"},
    "空欄にすると未設定になります。": {"en": "Leave blank to unset.", "zh": "留空则为未设置。"},
    "クリア": {"en": "Clear", "zh": "清除"},
    "グループ名:": {"en": "Group name:", "zh": "组名："},
    "DXFファイル名を使う": {"en": "Use DXF file name", "zh": "使用DXF文件名"},
    "手動入力": {"en": "Manual input", "zh": "手动输入"},
    "補助キー設定": {"en": "Helper Key Settings", "zh": "辅助键设置"},
    "ショートカット重複": {"en": "Duplicate Shortcut", "zh": "快捷键重复"},
    "ショートカットを押してください": {"en": "Press shortcut keys", "zh": "请按快捷键"},
    "デフォルトに戻す": {"en": "Restore Defaults", "zh": "恢复默认"},
    "パン": {"en": "Pan", "zh": "平移"},
    "矩形選": {"en": "Rectangle Select", "zh": "矩形选择"},
    "多角選": {"en": "Polygon Select", "zh": "多边形选择"},
    "移層": {"en": "Move to Layer", "zh": "移层"},
    "削除": {"en": "Delete", "zh": "删除"},
    "編集": {"en": "Edit", "zh": "编辑"},
    "移動": {"en": "Move", "zh": "移动"},
    "統合": {"en": "Merge", "zh": "合并"},
    "連続": {"en": "Continuous", "zh": "连续"},
    "多角": {"en": "Polygon", "zh": "多边形"},
    "直角多角": {"en": "Right-angle Polygon", "zh": "直角多边形"},
    "矩形": {"en": "Rectangle", "zh": "矩形"},
    "楕円": {"en": "Ellipse", "zh": "椭圆"},
    "正円": {"en": "Circle", "zh": "正圆"},
    "ライン": {"en": "Line", "zh": "线"},
    "点": {"en": "Point", "zh": "点"},
    "ライン/多角/直角多角: 辺長コピーキー": {"en": "Line/Polygon/Right-angle: Length Copy Key", "zh": "线/多边形/直角多边形：边长复制键"},
    "ライン/多角/直角多角: 参照点キー": {"en": "Line/Polygon/Right-angle: Reference Point Key", "zh": "线/多边形/直角多边形：参考点键"},
    "ライン/多角: 平行方向コピーキー": {"en": "Line/Polygon: Parallel Direction Copy Key", "zh": "线/多边形：平行方向复制键"},
    "ライン/多角: 角度コピーキー": {"en": "Line/Polygon: Angle Copy Key", "zh": "线/多边形：角度复制键"},
    "検査メッシュ作成": {"en": "Create Inspection Mesh", "zh": "创建检查网格"},
    "検査線作成": {"en": "Create Inspection Lines", "zh": "创建检查线"},
    "図郭ポリゴンレイヤを選択してください。": {"en": "Select a map sheet polygon layer.", "zh": "请选择图幅多边形图层。"},
    "図郭IDフィールドを選択してください。": {"en": "Select a map sheet ID field.", "zh": "请选择图幅ID字段。"},
    "横・縦の分割数を正しく入力してください。": {"en": "Enter valid horizontal and vertical split counts.", "zh": "请输入正确的横向和纵向分割数。"},
    "横・縦の分割数は999以下にしてください。": {"en": "Horizontal and vertical split counts must be 999 or less.", "zh": "横向和纵向分割数必须为999以下。"},
    "検査GPKGを開けません。": {"en": "Cannot open the inspection GPKG.", "zh": "无法打开检查GPKG。"},
    "検査レイヤをコピー（独立データ）": {"en": "Copy Inspection Layer (Independent Data)", "zh": "复制检查图层（独立数据）"},
    "検査グループをコピー（独立データ）": {"en": "Copy Inspection Group (Independent Data)", "zh": "复制检查组（独立数据）"},
    "このレイヤの地物を全選択": {"en": "Select All Features in This Layer", "zh": "全选此图层中的要素"},
    "このグループ内の地物を全選択": {"en": "Select All Features in This Group", "zh": "全选此组中的要素"},
    "全選択": {"en": "Select All", "zh": "全选"},
    "コピー後のグループ名:": {"en": "Copied group name:", "zh": "复制后的组名："},
    "コピーする選択地物がありません": {"en": "No selected features to copy", "zh": "没有可复制的选中要素"},
    "貼り付けるコピー地物がありません": {"en": "No copied features to paste", "zh": "没有可粘贴的复制要素"},
    "地物を貼り付けできませんでした": {"en": "Could not paste features", "zh": "无法粘贴要素"},
    "検査範囲ポリゴンを使う": {"en": "Use Inspection Area Polygon", "zh": "使用检查范围多边形"},
    "図郭ポリゴンから作る": {"en": "Create from Map Sheet Polygon", "zh": "从图幅多边形创建"},
    "作成": {"en": "Create", "zh": "创建"},
    "移層確認": {"en": "Confirm Move", "zh": "确认移层"},
    "未設定": {"en": "Not set", "zh": "未设置"},
    "プロジェクト座標系": {"en": "Project CRS", "zh": "工程坐标系"},
    "検査": {"en": "Inspection", "zh": "检查"},
    "レイヤ名:": {"en": "Layer name:", "zh": "图层名："},
    "形状選択": {"en": "Select Shape", "zh": "选择形状"},
    "形状:": {"en": "Shape:", "zh": "形状："},
    "新しいレイヤ名:": {"en": "New layer name:", "zh": "新图层名："},
    "対象レイヤ:": {"en": "Target layer:", "zh": "目标图层："},
    "線・点サイズ変更": {"en": "Change Line/Point Size", "zh": "更改线/点大小"},
    "移動先:": {"en": "Destination:", "zh": "移动目标："},
    "新しいグループ名:": {"en": "New group name:", "zh": "新组名："},
    "削除する検査回:": {"en": "Inspection round to delete:", "zh": "要删除的检查轮次："},
    "統合後の保存先レイヤ:": {"en": "Destination layer after merge:", "zh": "合并后的保存图层："},
    "幅(m)": {"en": "Width (m)", "zh": "宽度(m)"},
    "メッシュ": {"en": "Mesh", "zh": "网格"},
    "横": {"en": "Cols", "zh": "横"},
    "縦": {"en": "Rows", "zh": "纵"},
    "先に検査を作成してください。": {"en": "Create an inspection first.", "zh": "请先创建检查。"},
    "検査GPKG": {"en": "Inspection GPKG", "zh": "检查GPKG"},
    "検査作成": {"en": "Create Inspection", "zh": "创建检查"},
    "GDAL/OGRエラー": {"en": "GDAL/OGR Error", "zh": "GDAL/OGR错误"},
    "手動削除": {"en": "Manual Delete", "zh": "手动删除"},
    "完全削除": {"en": "Permanent Delete", "zh": "彻底删除"},
    "移層": {"en": "Move Layer", "zh": "移层"},
    "選択解除": {"en": "Clear Selection", "zh": "取消选择"},
    "復帰できません": {"en": "Cannot Restore", "zh": "无法恢复"},
    "復帰できませんでした": {"en": "Restore failed", "zh": "恢复失败"},
    "移動できません": {"en": "Cannot Move", "zh": "无法移动"},
    "削除できません": {"en": "Cannot Delete", "zh": "无法删除"},
    "統合できません": {"en": "Cannot Merge", "zh": "无法合并"},
    "追加失敗": {"en": "Add Failed", "zh": "添加失败"},
    "SHP書き出し": {"en": "Export SHP", "zh": "导出SHP"},
    "DXF（R12）書き出し": {"en": "Export DXF (R12)", "zh": "导出DXF（R12）"},
    "DXF（AutoCAD 2000系）書き出し": {"en": "Export DXF (AutoCAD 2000)", "zh": "导出DXF（AutoCAD 2000系）"},
    "検査線作成中": {"en": "Creating inspection lines", "zh": "正在创建检查线"},
    "検査メッシュ作成中": {"en": "Creating inspection mesh", "zh": "正在创建检查网格"},
    "VRT名前変更": {"en": "Rename VRT", "zh": "重命名VRT"},
    "新しいVRT名:": {"en": "New VRT name:", "zh": "新VRT名："},
    "同じファイルは追加済みです": {"en": "The same file has already been added", "zh": "相同文件已添加"},
    "同名画像を追加できません": {"en": "Cannot add images with duplicate names", "zh": "不能添加同名影像"},
    "リストを全てクリアしますか？": {"en": "Clear the entire list?", "zh": "是否清空整个列表？"},
    "正しい数値を入力してください（例: 3000）": {"en": "Enter a valid number (example: 3000)", "zh": "请输入正确的数值（例：3000）"},
    "VRTが選択されていません。": {"en": "No VRT is selected.", "zh": "未选择VRT。"},
    "OrthoManagerを閉じますか？": {"en": "Close OrthoManager?", "zh": "是否关闭OrthoManager？"},
    "定型検査セット作成": {"en": "Create Standard Inspection Set", "zh": "创建定型检查套件"},
    "キャンセル処理中...\n実行中の処理を停止し、未完成ファイルを削除しています。": {"en": "Cancelling...\nStopping the running process and deleting unfinished files.", "zh": "正在取消...\n正在停止执行中的处理并删除未完成文件。"},
}

TEXT_PHRASE_TRANSLATIONS = {
    "en": [
        ("DXF（AutoCAD 2000系）", "DXF (AutoCAD 2000)"), ("DXF（R12）", "DXF (R12)"),
        ("DGN V8/2004以降", "DGN V8/2004 or later"), ("DGN V7", "DGN V7"),
        ("AutoCAD 2000系", "AutoCAD 2000"), ("R12", "R12"), ("Level分け", "level split"),
        ("OrthoManager", "OrthoManager"), ("QGIS", "QGIS"), ("GDAL/OGR", "GDAL/OGR"), ("GPKG", "GPKG"), ("SHP", "SHP"), ("DXF", "DXF"), ("VRT", "VRT"), ("DGN", "DGN"), ("TIF", "TIF"),
        ("検査メッシュ", "inspection mesh"), ("検査線", "inspection line"), ("検査グループ", "inspection group"), ("検査レイヤ", "inspection layer"), ("検査ショートカット", "inspection shortcut"),
        ("検査範囲ポリゴン", "inspection area polygon"), ("図郭ポリゴンレイヤ", "map sheet polygon layer"), ("図郭ポリゴン", "map sheet polygon"), ("図郭フィーチャ", "map sheet feature"),
        ("図郭IDフィールド", "map sheet ID field"), ("図郭ID", "map sheet ID"), ("図郭", "map sheet"),
        ("検査データ", "inspection data"), ("検査図形", "inspection feature"), ("検査地物", "inspection feature"), ("検査項目", "inspection item"), ("検査回", "inspection round"), ("検査", "inspection"),
        ("自由式検査", "free-form inspection"), ("自由式", "free-form"), ("オルソ", "ortho"), ("作業範囲", "work area"),
        ("レイヤパネル", "layer panel"), ("レイヤ", "layer"), ("グループ", "group"), ("ゴミ箱", "trash"), ("メッシュ", "mesh"),
        ("ポリゴン", "polygon"), ("ライン", "line"), ("ベクタ", "vector"), ("ラスタ", "raster"), ("フィーチャ", "feature"), ("地物", "feature"), ("図形", "feature"),
        ("ジオメトリ", "geometry"), ("座標系", "CRS"), ("プロジェクト", "project"), ("マップ", "map"), ("ファイル", "file"), ("フォルダ", "folder"),
        ("キャッシュ", "cache"), ("ビュー", "view"), ("シールド", "shield"), ("マウス", "mouse"), ("ログ", "log"), ("ショートカット", "shortcut"), ("補助キー", "helper key"),
        ("角度補正基準", "angle snap basis"), ("指定角度単位", "angle step"), ("地図座標基準", "map coordinate basis"), ("直前辺基準", "previous edge basis"),
        ("平面直角座標系", "projected coordinate system"), ("メートル単位", "meter unit"), ("楕円", "ellipse"), ("正円", "circle"), ("直角多角", "right-angle polygon"), ("矩形選", "rectangle select"), ("矩形", "rectangle"), ("多角選", "polygon select"), ("多角", "polygon"),
        ("平行方向コピー", "parallel direction copy"), ("平行方向", "parallel direction"), ("参照点", "reference point"), ("直前辺", "previous edge"), ("延長線上", "on the extension line"),
        ("辺長コピー", "length copy"), ("辺長", "edge length"), ("コピー角度", "copied angle"), ("角度コピー", "angle copy"), ("角度", "angle"), ("コピー", "copy"), ("貼り付け", "paste"),
        ("全選択", "select all"), ("選択解除", "clear selection"), ("選択中", "selected"), ("選択", "select"), ("移層", "move to layer"), ("移動先", "destination"), ("移動元", "source"), ("移動", "move"),
        ("復帰先", "restore destination"), ("復帰中", "restoring"), ("復帰", "restore"), ("削除対象", "delete target"), ("削除", "delete"), ("統合後", "after merge"), ("統合", "merge"), ("編集対象", "edit target"), ("編集", "edit"),
        ("書き出し", "export"), ("読み込み", "load"), ("読み込む", "load"), ("読込", "load"), ("取り込み", "import"), ("取り込む", "import"), ("取込", "import"),
        ("作成", "create"), ("追加", "add"), ("変更", "change"), ("名前変更", "rename"), ("整理", "organize"), ("保存", "save"), ("生成", "generate"), ("更新", "update"), ("解除", "clear"),
        ("開始", "start"), ("終了", "finish"), ("完了", "complete"), ("中止", "stop"), ("キャンセル", "cancel"), ("スキップ", "skip"), ("上書き", "overwrite"), ("確認", "confirm"),
        ("警告", "warning"), ("エラー", "error"), ("情報", "information"), ("対象", "target"), ("出力", "output"), ("入力", "input"), ("形式", "format"), ("方法", "method"), ("場所", "location"), ("範囲", "area"),
        ("出力フォルダ", "output folder"), ("入力ラスタ", "input raster"), ("透過情報", "transparency information"), ("透過設定", "transparency setting"), ("透明", "transparent"), ("背景", "background"),
        ("ビット設定", "bit setting"), ("画像", "image"), ("写真", "photo"), ("枚数", "number of photos"), ("描画", "rendering"), ("時間", "time"), ("中身", "contents"),
        ("関連ファイル", "related file"), ("一時ファイル", "temporary file"), ("管理情報", "management information"), ("物理レイヤ名", "physical layer name"),
        ("数値", "number"), ("幅(m)", "width (m)"), ("幅", "width"), ("横", "cols"), ("縦", "rows"), ("新しい", "new"), ("元の", "original"), ("元", "source"),
        ("一番下", "bottom"), ("一番上", "top"), ("上", "above"), ("下", "below"), ("隙間", "gap"), ("直下", "directly under"),
        ("先に", "first"), ("同じ", "same"), ("一部", "some"), ("すべて", "all"), ("全て", "all"), ("全", "all"), ("空", "empty"), ("未設定", "not set"), ("有効", "valid"), ("正しい", "valid"),
        ("手動追加", "manually added"), ("手動", "manual"), ("標準", "standard"), ("関連", "related"), ("同名", "same-name"), ("同じ名前", "same name"), ("同じ場所", "same location"),
        ("重複頂点", "overlapping vertex"), ("重複", "duplicate"), ("ロック中", "locked"), ("完全ロック", "full lock"), ("選択ロック", "selection lock"), ("編集中", "editing"),
        ("作成中", "creating"), ("実行中", "running"), ("処理中", "processing"), ("バックグラウンド", "background"), ("外部", "external"), ("独自", "custom"),
        ("読み込めない", "cannot load"), ("読み込めません", "cannot load"), ("取り込めません", "cannot import"), ("書き出せません", "cannot export"), ("開けません", "cannot open"), ("見つかりません", "not found"),
        ("ありませんでした", "was not found"), ("ありません", "not found"), ("できませんでした", "failed"), ("できません", "cannot"), ("できなかった", "could not"), ("失敗しました", "failed"),
        ("指定してください", "please specify"), ("選択してください", "please select"), ("入力してください", "please enter"), ("設定してください", "please set"), ("再実行してください", "please run again"),
        ("使えません", "cannot be used"), ("含まれています", "is included"), ("含まれていました", "was included"), ("含む", "contains"), ("残ります", "will remain"), ("残しています", "is kept"),
        ("切り替えます", "will switch"), ("切り替え", "switch"), ("切替", "switch"), ("戻しました", "returned"), ("戻しています", "returning"), ("戻せませんでした", "could not undo"), ("戻す", "undo"),
        ("記録しました", "recorded"), ("受け付けました", "accepted"), ("停止しています", "stopping"), ("更新中", "updating"), ("生成中", "generating"), ("読み込み中", "loading"), ("書き出し中", "exporting"),
        ("作成しています", "creating"), ("操作しないでください", "do not operate"), ("クリックしてください", "please click"), ("クリック", "click"), ("ドラッグ", "drag"),
        ("よろしいでしょうか", "is that OK"), ("しますか", "?"), ("しました", "done"), ("しています", "in progress"), ("されていません", "is not selected"), ("されています", "is selected"), ("されません", "will not be"),
        ("できる", "can"), ("できない", "cannot"), ("なる", "becomes"), ("選んで", "choose"), ("使う", "use"), ("まま", "as-is"), ("ごと", "per"), ("より大きい", "greater than"),
        ("未完成", "unfinished"), ("即座", "immediately"), ("可能", "possible"), ("不正", "invalid"), ("単一", "single"), ("複数", "multiple"), ("分岐", "branch"), ("端点", "endpoints"),
        ("つながっている", "connected"), ("離れている", "separated"), ("重なっている", "overlapping"), ("接している", "touching"), ("混在している", "mixed"),

        ("1つ", "one"), ("データ", "data"), ("ライブラリ", "library"), ("ロック", "lock"), ("キー", "key"), ("単独", "single"), ("付き", "with"), ("など", "etc."),
        ("登録", "registered"), ("存在", "exists"), ("表示", "display"), ("画面", "screen"), ("操作", "operation"), ("処理", "process"), ("準備", "preparing"), ("エンジン", "engine"),
        ("並び替え", "reorder"), ("合成処理", "merge process"), ("構築", "build"), ("マスター", "master"), ("新規", "new"), ("成功", "success"), ("発生", "occurred"),
        ("縮尺制限なし", "no scale limit"), ("縮尺", "scale"), ("制限", "limit"), ("適用", "apply"), ("右クリック", "right-click"), ("右", "right"), ("ボタン", "button"), ("配置", "layout"),
        ("グレー", "gray"), ("パンモード", "pan mode"), ("パン", "pan"), ("オーバーレイ", "overlay"), ("ドライバ", "driver"), ("環境", "environment"), ("自体", "itself"),
        ("既に", "already"), ("すでに", "already"), ("既存", "existing"), ("別名", "different name"), ("値", "value"), ("該当", "matching"), ("リスト", "list"),
        ("誤削除", "accidental deletion"), ("混乱", "confusion"), ("破損", "corruption"), ("防ぐ", "prevent"), ("修正", "fix"), ("取得", "get"), ("無効", "invalid"),
        ("必要", "required"), ("以上", "or more"), ("以下", "or less"), ("行目", "row"), ("番目", "column"), ("倍率", "scale"),
        ("まとめられません", "cannot be merged"), ("まとめる", "merge"), ("まとめ", "merge"), ("読み込める", "can import"), ("取り込める", "can import"),
        ("続けて", "continue"), ("持つ", "has"), ("失われます", "will be lost"), ("反応しにくく", "may respond slowly"), ("一時的", "temporarily"),
        ("作成する", "create"), ("削除する", "delete"), ("変更する", "change"), ("復帰する", "restore"), ("移動する", "move"), ("コピーする", "copy"),
        ("した", ""), ("します", ""), ("しません", "not"), ("し", ""), ("です", ""), ("でした", ""), ("ます", ""), ("ません", "not"),
        ("名前", "name"), ("状態", "state"), ("種類", "type"), ("形状タイプ", "geometry type"), ("形状", "shape"), ("件", "item(s)"), ("枚", "photo(s)"), ("回目", "round"),
        ("ください", "please"), ("ため", "because"), ("から", "from"), ("まで", "until"), ("または", "or"), ("だけ", "only"), ("として", "as"), ("には", "for"), ("では", "in"), ("なら", "if"),
        ("より", "than"), ("この", "this"), ("現在", "current"), ("後", "after"), ("前", "before"), ("内", "inside"), ("外", "outside"), ("先", "destination"),
        ("を", ""), ("が", ""), ("に", ""), ("は", ""), ("の", ""), ("で", ""), ("と", ""), ("へ", ""), ("や", "and"), ("か", ""),
        ("、", ", "), ("。", "."), ("：", ":"), ("（", " ("), ("）", ")"), ("「", "\""), ("」", "\""), ("『", "\""), ("』", "\""), ("※", "Note:"),
    ],
    "zh": [
        ("DXF（AutoCAD 2000系）", "DXF（AutoCAD 2000系）"), ("DXF（R12）", "DXF（R12）"), ("DGN V8/2004以降", "DGN V8/2004以后"), ("Level分け", "Level分层"),
        ("検査メッシュ", "检查网格"), ("検査線", "检查线"), ("検査グループ", "检查组"), ("検査レイヤ", "检查图层"), ("検査ショートカット", "检查快捷键"),
        ("検査範囲ポリゴン", "检查范围多边形"), ("図郭ポリゴンレイヤ", "图幅多边形图层"), ("図郭ポリゴン", "图幅多边形"), ("図郭フィーチャ", "图幅要素"),
        ("図郭IDフィールド", "图幅ID字段"), ("図郭ID", "图幅ID"), ("図郭", "图幅"), ("検査データ", "检查数据"), ("検査図形", "检查图形"), ("検査地物", "检查要素"),
        ("検査項目", "检查项目"), ("検査回", "检查轮次"), ("検査", "检查"), ("自由式検査", "自由式检查"), ("自由式", "自由式"), ("オルソ", "正射"), ("作業範囲", "作业范围"),
        ("レイヤパネル", "图层面板"), ("レイヤ", "图层"), ("グループ", "组"), ("ゴミ箱", "回收站"), ("メッシュ", "网格"), ("ポリゴン", "多边形"), ("ライン", "线"),
        ("ベクタ", "矢量"), ("ラスタ", "栅格"), ("フィーチャ", "要素"), ("地物", "要素"), ("図形", "图形"), ("ジオメトリ", "几何"), ("座標系", "坐标系"),
        ("プロジェクト", "工程"), ("マップ", "地图"), ("ファイル", "文件"), ("フォルダ", "文件夹"), ("キャッシュ", "缓存"), ("ビュー", "视图"), ("シールド", "屏蔽"),
        ("マウス", "鼠标"), ("ログ", "日志"), ("ショートカット", "快捷键"), ("補助キー", "辅助键"), ("角度補正基準", "角度修正基准"), ("指定角度単位", "指定角度单位"),
        ("地図座標基準", "地图坐标基准"), ("直前辺基準", "前一边基准"), ("平面直角座標系", "平面直角坐标系"), ("メートル単位", "米单位"),
        ("楕円", "椭圆"), ("正円", "正圆"), ("直角多角", "直角多边形"), ("矩形選", "矩形选择"), ("矩形", "矩形"), ("多角選", "多边形选择"), ("多角", "多边形"),
        ("平行方向コピー", "平行方向复制"), ("平行方向", "平行方向"), ("参照点", "参考点"), ("直前辺", "前一边"), ("延長線上", "延长线上"),
        ("辺長コピー", "边长复制"), ("辺長", "边长"), ("コピー角度", "复制角度"), ("角度コピー", "角度复制"), ("角度", "角度"), ("コピー", "复制"), ("貼り付け", "粘贴"),
        ("全選択", "全选"), ("選択解除", "取消选择"), ("選択中", "选择中"), ("選択", "选择"), ("移層", "移层"), ("移動先", "移动目标"), ("移動元", "移动源"), ("移動", "移动"),
        ("復帰先", "恢复目标"), ("復帰中", "恢复中"), ("復帰", "恢复"), ("削除対象", "删除对象"), ("削除", "删除"), ("統合後", "合并后"), ("統合", "合并"), ("編集対象", "编辑对象"), ("編集", "编辑"),
        ("書き出し", "导出"), ("読み込み", "读取"), ("読み込む", "读取"), ("読込", "读取"), ("取り込み", "导入"), ("取り込む", "导入"), ("取込", "导入"),
        ("作成", "创建"), ("追加", "添加"), ("変更", "更改"), ("名前変更", "重命名"), ("整理", "整理"), ("保存", "保存"), ("生成", "生成"), ("更新", "更新"), ("解除", "解除"),
        ("開始", "开始"), ("終了", "结束"), ("完了", "完成"), ("中止", "停止"), ("キャンセル", "取消"), ("スキップ", "跳过"), ("上書き", "覆盖"), ("確認", "确认"),
        ("警告", "警告"), ("エラー", "错误"), ("情報", "信息"), ("対象", "对象"), ("出力", "输出"), ("入力", "输入"), ("形式", "格式"), ("方法", "方式"), ("場所", "位置"), ("範囲", "范围"),
        ("出力フォルダ", "输出文件夹"), ("入力ラスタ", "输入栅格"), ("透過情報", "透明信息"), ("透過設定", "透明设置"), ("透明", "透明"), ("背景", "背景"),
        ("ビット設定", "bit设置"), ("画像", "影像"), ("写真", "照片"), ("枚数", "张数"), ("描画", "绘制"), ("時間", "时间"), ("中身", "内容"),
        ("関連ファイル", "相关文件"), ("一時ファイル", "临时文件"), ("管理情報", "管理信息"), ("物理レイヤ名", "物理图层名"),
        ("数値", "数值"), ("幅(m)", "宽度(m)"), ("横", "横"), ("縦", "纵"), ("新しい", "新的"), ("元の", "原来的"), ("元", "原"),
        ("一番下", "最下方"), ("一番上", "最上方"), ("上", "上方"), ("下", "下方"), ("隙間", "空隙"), ("直下", "正下方"),
        ("先に", "请先"), ("同じ", "相同"), ("一部", "部分"), ("すべて", "全部"), ("全て", "全部"), ("全", "全部"), ("空", "空"), ("未設定", "未设置"), ("有効", "有效"), ("正しい", "正确"),
        ("手動追加", "手动添加"), ("手動", "手动"), ("標準", "标准"), ("関連", "相关"), ("同名", "同名"), ("同じ名前", "相同名称"), ("同じ場所", "相同位置"),
        ("重複頂点", "重复顶点"), ("重複", "重复"), ("ロック中", "锁定中"), ("完全ロック", "完全锁定"), ("選択ロック", "选择锁定"), ("編集中", "编辑中"),
        ("作成中", "创建中"), ("実行中", "执行中"), ("処理中", "处理中"), ("バックグラウンド", "后台"), ("外部", "外部"), ("独自", "自定义"),
        ("読み込めない", "无法读取"), ("読み込めません", "无法读取"), ("取り込めません", "无法导入"), ("書き出せません", "无法导出"), ("開けません", "无法打开"), ("見つかりません", "未找到"),
        ("ありませんでした", "没有"), ("ありません", "没有"), ("できませんでした", "失败"), ("できません", "不能"), ("できなかった", "无法"), ("失敗しました", "失败"),
        ("指定してください", "请指定"), ("選択してください", "请选择"), ("入力してください", "请输入"), ("設定してください", "请设置"), ("再実行してください", "请重新执行"),
        ("使えません", "不能使用"), ("含まれています", "包含"), ("含まれていました", "包含"), ("含む", "包含"), ("残ります", "会保留"), ("残しています", "已保留"),
        ("切り替えます", "切换"), ("切り替え", "切换"), ("切替", "切换"), ("戻しました", "已返回"), ("戻しています", "正在返回"), ("戻せませんでした", "无法撤销"), ("戻す", "撤销"),
        ("記録しました", "已记录"), ("受け付けました", "已接受"), ("停止しています", "正在停止"), ("更新中", "更新中"), ("生成中", "生成中"), ("読み込み中", "读取中"), ("書き出し中", "导出中"),
        ("作成しています", "正在创建"), ("操作しないでください", "请不要操作"), ("クリックしてください", "请点击"), ("クリック", "点击"), ("ドラッグ", "拖动"),
        ("よろしいでしょうか", "可以吗"), ("しますか", "吗？"), ("しました", "完成"), ("しています", "处理中"), ("されていません", "未选择"), ("されています", "已选择"), ("されません", "不会"),
        ("できる", "可以"), ("できない", "不能"), ("なる", "成为"), ("選んで", "选择"), ("使う", "使用"), ("まま", "保持"), ("ごと", "每个"), ("より大きい", "大于"),
        ("未完成", "未完成"), ("即座", "立即"), ("可能", "可能"), ("不正", "无效"), ("単一", "单一"), ("複数", "多个"), ("分岐", "分支"), ("端点", "端点"),
        ("つながっている", "连接的"), ("離れている", "分离的"), ("重なっている", "重叠的"), ("接している", "接触的"), ("混在している", "混合"),

        ("1つ", "一个"), ("データ", "数据"), ("ライブラリ", "库"), ("ロック", "锁定"), ("キー", "键"), ("単独", "单独"), ("付き", "带"), ("など", "等"),
        ("登録", "注册"), ("存在", "存在"), ("表示", "显示"), ("画面", "画面"), ("操作", "操作"), ("処理", "处理"), ("準備", "准备"), ("エンジン", "引擎"),
        ("並び替え", "排序"), ("合成処理", "合成处理"), ("構築", "构建"), ("マスター", "主"), ("新規", "新建"), ("成功", "成功"), ("発生", "发生"),
        ("縮尺制限なし", "无比例尺限制"), ("縮尺", "比例尺"), ("制限", "限制"), ("適用", "应用"), ("右クリック", "右键"), ("右", "右"), ("ボタン", "按钮"), ("配置", "配置"),
        ("グレー", "灰色"), ("パンモード", "平移模式"), ("パン", "平移"), ("オーバーレイ", "叠加"), ("ドライバ", "驱动"), ("環境", "环境"), ("自体", "本身"),
        ("既に", "已经"), ("すでに", "已经"), ("既存", "既有"), ("別名", "其他名称"), ("値", "值"), ("該当", "对应"), ("リスト", "列表"),
        ("誤削除", "误删"), ("混乱", "混乱"), ("破損", "损坏"), ("防ぐ", "防止"), ("修正", "修正"), ("取得", "获取"), ("無効", "无效"),
        ("必要", "需要"), ("以上", "以上"), ("以下", "以下"), ("行目", "行"), ("番目", "列"), ("倍率", "倍率"),
        ("まとめられません", "不能合并"), ("まとめる", "合并"), ("まとめ", "合并"), ("読み込める", "可读取"), ("取り込める", "可导入"),
        ("続けて", "继续"), ("持つ", "具有"), ("失われます", "会丢失"), ("反応しにくく", "可能反应变慢"), ("一時的", "临时"),
        ("作成する", "创建"), ("削除する", "删除"), ("変更する", "更改"), ("復帰する", "恢复"), ("移動する", "移动"), ("コピーする", "复制"),
        ("した", ""), ("します", ""), ("しません", "不"), ("し", ""), ("です", ""), ("でした", ""), ("ます", ""), ("ません", "不"),
        ("名前", "名称"), ("状態", "状态"), ("種類", "类型"), ("形状タイプ", "图形类型"), ("形状", "形状"), ("件", "件"), ("枚", "张"), ("回目", "次"),
        ("ください", "请"), ("ため", "因为"), ("から", "从"), ("まで", "到"), ("または", "或者"), ("だけ", "仅"), ("として", "作为"), ("には", "对"), ("では", "在"), ("なら", "如果"),
        ("より", "比"), ("この", "此"), ("現在", "当前"), ("後", "后"), ("前", "前"), ("内", "内"), ("外", "外"), ("先", "目标"),
        ("を", ""), ("が", ""), ("に", ""), ("は", ""), ("の", ""), ("で", ""), ("と", "和"), ("へ", "到"), ("や", "和"), ("か", ""),
        ("、", "，"), ("。", "。"), ("：", "："), ("（", "（"), ("）", "）"), ("「", "“"), ("」", "”"), ("『", "“"), ("』", "”"), ("※", "※"),
    ],
}


_EN_JAPANESE_RE = re.compile(r"[ぁ-んァ-ン一-龯]+")
_ZH_KANA_RE = re.compile(r"[ぁ-んァ-ン]+")


def tr_text(text, language=None):
    language = normalize_language(language or current_language())
    if language == DEFAULT_LANGUAGE:
        return text
    value = str(text)
    exact = TEXT_EXACT_TRANSLATIONS.get(value)
    if exact:
        translated = exact.get(language)
        if translated:
            return translated
    phrases = sorted(TEXT_PHRASE_TRANSLATIONS.get(language, []), key=lambda item: len(item[0]), reverse=True)
    for source, target in phrases:
        value = value.replace(source, target)
    if language == "en":
        value = _EN_JAPANESE_RE.sub("", value)
    elif language == "zh":
        value = _ZH_KANA_RE.sub("", value)
    return value
