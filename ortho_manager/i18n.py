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
        "ja": "📁 VRT管理",
        "en": "📁 VRT",
        "zh": "📁 VRT管理",
    },
    "tab.inspection": {
        "ja": "🔎 検査",
        "en": "🔎 Insp.",
        "zh": "🔎 检查",
    },
    "tab.export": {
        "ja": "📤 書き出し",
        "en": "📤 Export",
        "zh": "📤 导出",
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
        "ja": "新規検査",
        "en": "New",
        "zh": "新建",
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
        "ja": "新規検査を作成してください",
        "en": "Create new insp.",
        "zh": "请新建检查",
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
        "ja": "連続作成",
        "en": "Continuous",
        "zh": "连续创建",
    },
    "inspection.menu.shape_polygon": {
        "ja": "多角",
        "en": "Poly",
        "zh": "多边",
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
        "ja": "{round}回目検査",
        "en": "Round {round}",
        "zh": "第{round}次检查",
    },
    "inspection.menu.action.pan": {
        "ja": "パン",
        "en": "Pan",
        "zh": "平移",
    },
    "inspection.menu.action.select": {
        "ja": "選択",
        "en": "Select",
        "zh": "选择",
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
        "ja": "パンモードへ戻る",
        "en": "Pan mode",
        "zh": "返回平移",
    },
    "inspection.menu.tip.select": {
        "ja": "検査データを選択",
        "en": "Select data",
        "zh": "选择检查数据",
    },
    "inspection.menu.tip.layer_change": {
        "ja": "選択データを別レイヤへ移層",
        "en": "Move to layer",
        "zh": "移动到其他图层",
    },
    "inspection.menu.tip.delete": {
        "ja": "選択データを削除",
        "en": "Delete data",
        "zh": "删除选择数据",
    },
    "inspection.menu.tip.edit": {
        "ja": "頂点編集モード",
        "en": "Vertex edit",
        "zh": "节点编辑",
    },
    "inspection.menu.tip.move": {
        "ja": "選択データをドラッグ移動",
        "en": "Drag move",
        "zh": "拖动移动",
    },
    "inspection.menu.tip.merge": {
        "ja": "選択データを統合",
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
        "ja": "ファイル管理",
        "en": "Files",
        "zh": "文件",
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
    "vrt.btn.build": {
        "ja": "⚡ VRT生成・更新",
        "en": "⚡ Build/Update",
        "zh": "⚡ 生成/更新",
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
        pass
    return language


def tr(key, language=None):
    language = normalize_language(language or current_language())
    values = TRANSLATIONS.get(key, {})
    return values.get(language) or values.get(DEFAULT_LANGUAGE) or key
