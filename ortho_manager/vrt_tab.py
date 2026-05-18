import os
import json
import time
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QMessageBox, QGroupBox, QLineEdit, QProgressBar,
    QAbstractItemView, QComboBox, QApplication, QInputDialog, QSizePolicy,
    QCheckBox
)
from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMessageLog, Qgis,
    QgsFillSymbol, QgsSingleSymbolRenderer, QgsLinePatternFillSymbolLayer,
    QgsSimpleLineSymbolLayer, QgsLayerTreeLayer, QgsApplication
)

from .utils import DEFAULT_MIN_SCALE
from .tasks import BuildVrtAndGpkgTask, ExternalVrtEngineTask, find_external_vrt_engine_path

try:
    from osgeo import ogr
    ogr.UseExceptions()
    GDAL_OK = True
except ImportError:
    GDAL_OK = False

class TifListWindow(QWidget):
    def __init__(self, vrt_tab, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.vrt_tab = vrt_tab
        self.setWindowTitle("ファイル管理")
        self.resize(560, 420)
        self.setMinimumSize(360, 260)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        path_label = QLabel("VRT場所：")
        path_label.setStyleSheet("font-weight:bold;")
        layout.addWidget(path_label)
        self.vrt_path_edit = QLineEdit()
        self.vrt_path_edit.setPlaceholderText("VRTパス")
        self.vrt_path_edit.setReadOnly(True)
        self.vrt_path_edit.setStyleSheet("background:#f8f9fa; font-size:10px;")
        layout.addWidget(self.vrt_path_edit)

        header_row = QHBoxLayout()
        header_label = QLabel("ファイル管理")
        header_label.setStyleSheet("font-weight:bold;")
        self.btn_sort_added = QPushButton("追加順")
        self.btn_sort_added.setFixedWidth(58)
        self.btn_sort_added.clicked.connect(lambda: self.vrt_tab._set_tif_sort_mode("added"))
        self.btn_sort_name = QPushButton("名前順")
        self.btn_sort_name.setFixedWidth(58)
        self.btn_sort_name.clicked.connect(lambda: self.vrt_tab._set_tif_sort_mode("name"))
        header_row.addWidget(header_label)
        header_row.addStretch()
        header_row.addWidget(self.btn_sort_added)
        header_row.addWidget(self.btn_sort_name)
        layout.addLayout(header_row)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 ファイル名で検索")
        self.search_edit.textChanged.connect(self._filter_list)
        btn_cls = QPushButton("✕")
        btn_cls.setFixedWidth(28)
        btn_cls.clicked.connect(self._clear_search)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(btn_cls)
        layout.addLayout(search_row)

        self.tif_listwidget = QListWidget()
        self.tif_listwidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.tif_listwidget)

        self.count_label = QLabel("0 ファイル")
        layout.addWidget(self.count_label)

        self.chk_include_subfolders = QCheckBox("サブフォルダも読み込む")
        self.chk_include_subfolders.setChecked(bool(getattr(self.vrt_tab, "include_subfolders", False)))
        self.chk_include_subfolders.toggled.connect(self.vrt_tab._set_include_subfolders)
        layout.addWidget(self.chk_include_subfolders)

        add_row = QHBoxLayout()
        btn_folder = QPushButton("📂 フォルダ追加")
        btn_folder.clicked.connect(self.vrt_tab._add_from_folder)
        btn_folder.setStyleSheet(self.vrt_tab._btn_style("#3498db"))
        btn_files = QPushButton("🖼 ファイル追加")
        btn_files.clicked.connect(self.vrt_tab._add_files)
        btn_files.setStyleSheet(self.vrt_tab._btn_style("#2ecc71"))
        add_row.addWidget(btn_folder)
        add_row.addWidget(btn_files)
        layout.addLayout(add_row)

        action_row = QHBoxLayout()
        btn_select_map = QPushButton("🖱 マップから削除")
        btn_select_map.clicked.connect(self.vrt_tab._activate_overlay_and_select_tool)
        btn_select_map.setStyleSheet(self.vrt_tab._btn_style("#f39c12"))
        btn_remove = QPushButton("❌ 選択を削除")
        btn_remove.clicked.connect(self.vrt_tab._remove_selected)
        btn_remove.setStyleSheet(self.vrt_tab._btn_style("#e74c3c"))
        btn_clear = QPushButton("🗑 全削除")
        btn_clear.clicked.connect(self.vrt_tab._clear_list)
        btn_clear.setStyleSheet(self.vrt_tab._btn_style("#95a5a6"))
        for button in (btn_select_map, btn_remove, btn_clear):
            button.setFixedSize(124, 30)
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.close)
        action_row.addWidget(btn_select_map)
        action_row.addWidget(btn_remove)
        action_row.addWidget(btn_clear)
        action_row.addStretch()
        action_row.addWidget(btn_close)
        layout.addLayout(action_row)

        self.update_sort_buttons()
        self.reload_list()

    def closeEvent(self, event):
        self.vrt_tab.tif_list_window = None
        event.accept()

    def reload_list(self):
        self.update_path_display()
        self.tif_listwidget.clear()
        for path in self.vrt_tab._display_tif_list():
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, os.path.normpath(path))
            item.setToolTip(path)
            self.tif_listwidget.addItem(item)
        self.update_count()
        keyword = self.search_edit.text().strip()
        if keyword:
            self._filter_list(keyword)

    def update_count(self):
        self.count_label.setText(f"{len(self.vrt_tab.main_ui.tif_list)} ファイル")

    def update_path_display(self):
        if hasattr(self, "vrt_path_edit"):
            path = self.vrt_tab.main_ui.vrt_path
            self.vrt_path_edit.setText(path)
            self.vrt_path_edit.setToolTip(path)

    def update_sort_buttons(self):
        active_style = self.vrt_tab._btn_style("#2980b9")
        inactive_style = "QPushButton{background:#ecf0f1;color:#2c3e50;border:1px solid #bdc3c7;border-radius:4px;padding:5px;font-size:11px;}QPushButton:hover{background:#d5dbdb;}"
        self.btn_sort_added.setStyleSheet(active_style if self.vrt_tab.tif_sort_mode == "added" else inactive_style)
        self.btn_sort_name.setStyleSheet(active_style if self.vrt_tab.tif_sort_mode == "name" else inactive_style)

    def _filter_list(self, keyword):
        keyword = keyword.strip().lower()
        for i in range(self.tif_listwidget.count()):
            item = self.tif_listwidget.item(i)
            full_path = item.data(Qt.ItemDataRole.UserRole) or ""
            haystack = f"{item.text()} {full_path}".lower()
            item.setHidden(keyword != "" and keyword not in haystack)

    def _clear_search(self):
        self.search_edit.clear()
        for i in range(self.tif_listwidget.count()):
            self.tif_listwidget.item(i).setHidden(False)

class VrtTabWidget(QWidget):
    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui  # main_uiはOrthoManagerDockWidgetを指す
        self.scale_btns = {}
        self.previous_map_tool = None  # マップから削除ボタンを押す前のツールを記憶する変数
        self.tif_sort_mode = "added"
        self.tif_list_window = None
        self.include_subfolders = False
        self._build_ui()

    def _btn_style(self, color):
        return f"QPushButton{{background:{color};color:white;border:none;border-radius:4px;padding:5px;font-size:11px;}}QPushButton:hover{{background:{color}CC;}}"

    def _btn_style_big(self, color):
        return f"QPushButton{{background:{color};color:white;border:none;border-radius:5px;padding:7px;font-size:12px;font-weight:bold;}}QPushButton:hover{{background:{color}CC;}}"

    def _scale_btn_style(self, is_active):
        if is_active:
            return "QPushButton{background:#27ae60;color:white;border:none;border-radius:3px;font-size:10px;font-weight:bold;padding:2px;}QPushButton:hover{background:#2ecc71;}"
        else:
            return "QPushButton{background:#ecf0f1;color:#2c3e50;border:1px solid #bdc3c7;border-radius:3px;font-size:10px;padding:2px;}QPushButton:hover{background:#bdc3c7;}"

    def _view_cache_btn_style(self, is_active):
        if is_active:
            return "QPushButton{background:#16a085;color:white;border:none;border-radius:3px;font-size:10px;font-weight:bold;padding:2px;}QPushButton:hover{background:#1abc9c;}"
        return "QPushButton{background:#f7f9fa;color:#2c3e50;border:1px solid #95a5a6;border-radius:3px;font-size:10px;padding:2px;}QPushButton:hover{background:#dfe6e9;}"

    def update_view_cache_button(self, enabled):
        if not hasattr(self, "btn_view_cache"):
            return
        was_blocked = self.btn_view_cache.blockSignals(True)
        self.btn_view_cache.setChecked(bool(enabled))
        self.btn_view_cache.setStyleSheet(self._view_cache_btn_style(bool(enabled)))
        self.btn_view_cache.setToolTip("ビューキャッシュをOFFにします" if enabled else "ビューキャッシュをONにします")
        self.btn_view_cache.blockSignals(was_blocked)

    def _focus_map_canvas_after_toggle(self):
        try:
            canvas = self.main_ui.iface.mapCanvas()
            if canvas:
                canvas.setFocus()
                if canvas.viewport():
                    canvas.viewport().setFocus()
        except Exception:
            pass

    def _toggle_view_cache(self, checked):
        self.main_ui.apply_view_cache_enabled(bool(checked), save=True, show_status=True)
        self._focus_map_canvas_after_toggle()
    def _custom_cache_btn_style(self, is_active):
        if is_active:
            return "QPushButton{background:#8e44ad;color:white;border:none;border-radius:3px;font-size:10px;font-weight:bold;padding:2px;}QPushButton:hover{background:#9b59b6;}"
        return "QPushButton{background:#f7f9fa;color:#2c3e50;border:1px solid #95a5a6;border-radius:3px;font-size:10px;padding:2px;}QPushButton:hover{background:#dfe6e9;}"

    def update_custom_cache_button(self, enabled):
        if not hasattr(self, "btn_custom_cache"):
            return
        was_blocked = self.btn_custom_cache.blockSignals(True)
        self.btn_custom_cache.setChecked(bool(enabled))
        self.btn_custom_cache.setStyleSheet(self._custom_cache_btn_style(bool(enabled)))
        self.btn_custom_cache.setToolTip("独自キャッシュをOFFにします" if enabled else "独自キャッシュをONにします")
        self.btn_custom_cache.blockSignals(was_blocked)

    def _toggle_custom_cache(self, checked):
        self.main_ui.apply_custom_cache_enabled(bool(checked), save=True, show_status=True)
        self._focus_map_canvas_after_toggle()

    def _screen_shield_btn_style(self, is_active):
        if is_active:
            return "QPushButton{background:#16a085;color:white;border:none;border-radius:3px;font-size:10px;font-weight:bold;padding:2px;}QPushButton:hover{background:#1abc9c;}"
        return "QPushButton{background:#f7f9fa;color:#2c3e50;border:1px solid #95a5a6;border-radius:3px;font-size:10px;padding:2px;}QPushButton:hover{background:#dfe6e9;}"

    def update_screen_shield_button(self, enabled):
        if not hasattr(self, "btn_screen_shield"):
            return
        was_blocked = self.btn_screen_shield.blockSignals(True)
        self.btn_screen_shield.setChecked(bool(enabled))
        self.btn_screen_shield.setStyleSheet(self._screen_shield_btn_style(bool(enabled)))
        self.btn_screen_shield.setToolTip("画面シールドをOFFにします" if enabled else "画面シールドをONにします")
        self.btn_screen_shield.blockSignals(was_blocked)

    def _toggle_screen_shield(self, checked):
        self.main_ui.apply_screen_shield_enabled(bool(checked), save=True, show_status=True)
        self._focus_map_canvas_after_toggle()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 1. VRT管理グループ
        grp_vrt = QGroupBox("VRT管理")
        grp_vrt_layout = QVBoxLayout(grp_vrt)

        combo_row = QHBoxLayout()
        self.vrt_combo = QComboBox()
        self.vrt_combo.setMinimumWidth(0)
        self.vrt_combo.setMaximumWidth(260)
        self.vrt_combo.setMinimumContentsLength(12)
        self.vrt_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        try:
            self.vrt_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        except Exception:
            pass
        self.vrt_combo.currentIndexChanged.connect(self._switch_vrt)
        combo_row.addWidget(self.vrt_combo)
        grp_vrt_layout.addLayout(combo_row)

        vrt_btn_row = QHBoxLayout()
        vrt_btn_row.setSpacing(4)
        btn_new = QPushButton("新規")
        btn_new.setFixedWidth(52)
        btn_new.clicked.connect(self._new_vrt)
        btn_new.setStyleSheet(self._btn_style("#27ae60"))
        self.btn_rename = QPushButton("名前変更")
        self.btn_rename.setFixedWidth(70)
        self.btn_rename.clicked.connect(self._rename_vrt)
        self.btn_rename.setStyleSheet(self._btn_style("#2980b9"))
        self.btn_rename.setEnabled(False)
        btn_load = QPushButton("VRT読込")
        btn_load.setFixedWidth(66)
        btn_load.clicked.connect(self._load_existing_vrt)
        btn_load.setStyleSheet(self._btn_style("#8e44ad"))
        btn_del = QPushButton("削除")
        btn_del.setFixedWidth(50)
        btn_del.clicked.connect(self._delete_vrt)
        btn_del.setStyleSheet(self._btn_style("#e74c3c"))
        btn_organize = QPushButton("レイヤ整理")
        btn_organize.setFixedWidth(78)
        btn_organize.clicked.connect(self._organize_vrt_layers)
        btn_organize.setStyleSheet(self._btn_style("#7f8c8d"))
        vrt_btn_row.addWidget(btn_new)
        vrt_btn_row.addWidget(self.btn_rename)
        vrt_btn_row.addWidget(btn_load)
        vrt_btn_row.addWidget(btn_del)
        vrt_btn_row.addStretch()
        grp_vrt_layout.addLayout(vrt_btn_row)

        vrt_btn_row2 = QHBoxLayout()
        vrt_btn_row2.setSpacing(4)
        vrt_btn_row2.addWidget(btn_organize)
        vrt_btn_row2.addStretch()
        grp_vrt_layout.addLayout(vrt_btn_row2)

        layout.addWidget(grp_vrt)

        # 2. ファイル管理グループ
        grp_file = QGroupBox("ファイル管理")
        grp_file_layout = QHBoxLayout(grp_file)
        grp_file_layout.setContentsMargins(6, 6, 6, 6)
        self.count_label = QLabel("ファイル数：0ファイル")
        self.count_label.setStyleSheet("font-weight:bold;")
        btn_show_tif_list = QPushButton("ファイル管理")
        btn_show_tif_list.setFixedWidth(86)
        btn_show_tif_list.clicked.connect(self._open_tif_list_window)
        btn_show_tif_list.setStyleSheet(self._btn_style("#34495e"))
        grp_file_layout.addWidget(self.count_label)
        grp_file_layout.addStretch()
        grp_file_layout.addWidget(btn_show_tif_list)
        layout.addWidget(grp_file)

        # 3. 表示縮尺設定グループ
        grp_scale = QGroupBox("表示縮尺設定")
        grp_scale_layout = QVBoxLayout(grp_scale)
        grp_scale_layout.setContentsMargins(4, 4, 4, 4)
        PRESET_SCALES = [500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]

        scale_row1 = QHBoxLayout()
        for val in PRESET_SCALES[:4]:
            btn = QPushButton(f"1:{val:,}")
            btn.setFixedHeight(24)
            btn.setStyleSheet(self._scale_btn_style(False))
            btn.clicked.connect(lambda checked, v=val: self._apply_scale_preset(v))
            self.scale_btns[val] = btn
            scale_row1.addWidget(btn)
        grp_scale_layout.addLayout(scale_row1)

        scale_row2 = QHBoxLayout()
        for val in PRESET_SCALES[4:]:
            btn = QPushButton(f"1:{val:,}")
            btn.setFixedHeight(24)
            btn.setStyleSheet(self._scale_btn_style(False))
            btn.clicked.connect(lambda checked, v=val: self._apply_scale_preset(v))
            self.scale_btns[val] = btn
            scale_row2.addWidget(btn)
        grp_scale_layout.addLayout(scale_row2)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(2)
        manual_prefix_label = QLabel("手動  ")
        manual_prefix_label.setFixedWidth(44)
        manual_scale_label = QLabel("1:")
        manual_scale_label.setFixedWidth(14)
        manual_row.addWidget(manual_prefix_label)
        manual_row.addWidget(manual_scale_label)
        self.scale_manual_edit = QLineEdit()
        self.scale_manual_edit.setFixedWidth(72)
        btn_manual_apply = QPushButton("適用")
        btn_manual_apply.setFixedWidth(42)
        btn_manual_apply.setStyleSheet(self._btn_style("#2980b9"))
        btn_manual_apply.clicked.connect(self._apply_scale_manual)
        manual_row.addWidget(self.scale_manual_edit)
        manual_row.addWidget(btn_manual_apply)
        btn_all = QPushButton("🌐 全表示")
        btn_all.setFixedWidth(78)
        btn_all.setFixedHeight(24)
        btn_all.setStyleSheet(self._btn_style("#e67e22"))
        btn_all.clicked.connect(self._apply_scale_all)
        self.scale_btns[0] = btn_all
        manual_row.addWidget(btn_all)
        manual_row.addStretch()
        grp_scale_layout.addLayout(manual_row)

        cache_row = QHBoxLayout()
        cache_row.setSpacing(6)
        self.btn_view_cache = QPushButton("ﾋﾞｭｰｷｬｯｼｭ")
        self.btn_view_cache.setCheckable(True)
        self.btn_view_cache.setFixedWidth(78)
        self.btn_view_cache.setFixedHeight(24)
        self.btn_view_cache.clicked.connect(self._toggle_view_cache)
        cache_row.addWidget(self.btn_view_cache)
        self.btn_custom_cache = QPushButton("独自ｷｬｯｼｭ")
        self.btn_custom_cache.setCheckable(True)
        self.btn_custom_cache.setFixedWidth(78)
        self.btn_custom_cache.setFixedHeight(24)
        self.btn_custom_cache.clicked.connect(self._toggle_custom_cache)
        cache_row.addWidget(self.btn_custom_cache)
        self.btn_screen_shield = QPushButton("画面ｼｰﾙﾄﾞ")
        self.btn_screen_shield.setCheckable(True)
        self.btn_screen_shield.setFixedWidth(78)
        self.btn_screen_shield.setFixedHeight(24)
        self.btn_screen_shield.clicked.connect(self._toggle_screen_shield)
        cache_row.addWidget(self.btn_screen_shield)
        cache_row.addStretch()
        grp_scale_layout.addLayout(cache_row)

        self.update_view_cache_button(getattr(self.main_ui, "view_cache_enabled", False))
        self.update_custom_cache_button(getattr(self.main_ui, "custom_cache_enabled", False))
        self.update_screen_shield_button(getattr(self.main_ui, "screen_shield_enabled", False))
        layout.addWidget(grp_scale)
        self._update_tif_sort_buttons()

        self.btn_build = QPushButton("⚡ VRT生成・更新", self)
        self.btn_build.clicked.connect(self._build_and_load_vrt)
        self.btn_build.setStyleSheet(self._btn_style_big("#8e44ad"))
        self.btn_build.setVisible(False)

        self.vrt_progress_bar = QProgressBar()
        self.vrt_progress_bar.setValue(0)
        self.vrt_progress_bar.setVisible(False)
        self.vrt_progress_bar.setFixedHeight(12)
        layout.addWidget(self.vrt_progress_bar)

        layout.addStretch()

    # --- UI更新・同期メソッド ---
    def populate_vrt_combo(self):
        self.vrt_combo.blockSignals(True)
        self.vrt_combo.clear()
        for name in self.main_ui.vrt_registry:
            self._add_vrt_combo_item(name)
        if self.main_ui.current_vrt_name:
            self.set_current_vrt_name(self.main_ui.current_vrt_name)
        self.vrt_combo.blockSignals(False)
        self._update_vrt_combo_tooltip()
        self._refresh_vrt_action_buttons()

    def _refresh_vrt_action_buttons(self):
        if hasattr(self, "btn_rename"):
            if not self.main_ui.current_vrt_name:
                current_name = self.current_vrt_combo_name()
                if current_name:
                    self.main_ui.current_vrt_name = current_name
                elif self.main_ui.vrt_registry:
                    first_name = list(self.main_ui.vrt_registry.keys())[0]
                    self.main_ui.current_vrt_name = first_name
                    self.set_current_vrt_name(first_name)
            self.btn_rename.setEnabled(bool(self.main_ui.current_vrt_name or self.main_ui.vrt_registry))

    def _update_vrt_combo_tooltip(self):
        if not hasattr(self, "vrt_combo"):
            return
        current = self.current_vrt_combo_name()
        self.vrt_combo.setToolTip(current)
        for i in range(self.vrt_combo.count()):
            full_name = self.vrt_combo.itemData(i, Qt.ItemDataRole.UserRole) or self.vrt_combo.itemText(i)
            self.vrt_combo.setItemText(i, self._combo_display_text(full_name))
            self.vrt_combo.setItemData(i, full_name, Qt.ItemDataRole.ToolTipRole)

    def _combo_display_text(self, full_name):
        width = self.vrt_combo.width() if self.vrt_combo.width() > 40 else 230
        return self.vrt_combo.fontMetrics().elidedText(
            full_name,
            Qt.TextElideMode.ElideMiddle,
            max(80, min(width, self.vrt_combo.maximumWidth()) - 30),
        )

    def _add_vrt_combo_item(self, full_name):
        was_blocked = self.vrt_combo.blockSignals(True)
        self.vrt_combo.addItem(self._combo_display_text(full_name))
        idx = self.vrt_combo.count() - 1
        self.vrt_combo.setItemData(idx, full_name, Qt.ItemDataRole.UserRole)
        self.vrt_combo.setItemData(idx, full_name, Qt.ItemDataRole.ToolTipRole)
        self.vrt_combo.blockSignals(was_blocked)

    def current_vrt_combo_name(self):
        idx = self.vrt_combo.currentIndex()
        if idx < 0:
            return ""
        return self.vrt_combo.itemData(idx, Qt.ItemDataRole.UserRole) or self.vrt_combo.currentText()

    def set_current_vrt_name(self, name):
        idx = self.vrt_combo.findData(name, Qt.ItemDataRole.UserRole)
        if idx >= 0:
            self.vrt_combo.setCurrentIndex(idx)
        else:
            self.vrt_combo.setCurrentText(name)

    def _open_tif_list_window(self):
        if self.tif_list_window is None:
            try:
                parent = self.main_ui.iface.mainWindow()
            except Exception:
                parent = self
            self.tif_list_window = TifListWindow(self, parent)
        self.tif_list_window.reload_list()
        self.tif_list_window.show()
        self.tif_list_window.raise_()
        self.tif_list_window.activateWindow()

    def _set_include_subfolders(self, checked):
        self.include_subfolders = bool(checked)
        QgsMessageLog.logMessage(
            f"VRT_FOLDER_OPTION include_subfolders={self.include_subfolders}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

    def reload_tif_listwidget(self):
        self.update_count()
        if self.tif_list_window is not None:
            self.tif_list_window.reload_list()

    def update_count(self):
        text = f"ファイル数：{len(self.main_ui.tif_list)}ファイル"
        if hasattr(self, "count_label"):
            self.count_label.setText(text)
        if self.tif_list_window is not None:
            self.tif_list_window.update_count()

    def _display_tif_list(self):
        tif_list = list(self.main_ui.tif_list)
        if self.tif_sort_mode == "name":
            return sorted(tif_list, key=lambda p: (os.path.basename(p).lower(), os.path.normcase(p)))
        return tif_list

    def _set_tif_sort_mode(self, mode):
        if mode not in ("added", "name"):
            return
        self.tif_sort_mode = mode
        self._update_tif_sort_buttons()
        self.reload_tif_listwidget()

    def _update_tif_sort_buttons(self):
        if self.tif_list_window is not None:
            self.tif_list_window.update_sort_buttons()

    def _filter_list(self, keyword):
        if self.tif_list_window is not None:
            self.tif_list_window._filter_list(keyword)

    def _clear_search(self):
        if self.tif_list_window is not None:
            self.tif_list_window._clear_search()

    def update_path_display(self):
        if self.tif_list_window is not None:
            self.tif_list_window.update_path_display()

    def update_scale_btn_highlight(self, active_scale):
        preset_scales = [v for v in self.scale_btns.keys() if v != 0]
        matched = active_scale in preset_scales
        for val, btn in self.scale_btns.items():
            if val == 0:
                is_active = (active_scale == 0)
                if is_active:
                    btn.setStyleSheet(self._btn_style("#27ae60"))
                else:
                    btn.setStyleSheet(self._btn_style("#e67e22"))
            else:
                btn.setStyleSheet(self._scale_btn_style(val == active_scale))
        if not matched and active_scale != 0:
            self.scale_manual_edit.setText(str(active_scale))
        else:
            self.scale_manual_edit.clear()

    def sync_scale_highlight_from_current_vrt(self):
        name = self.main_ui.current_vrt_name
        vrt_layer = self.main_ui._get_vrt_layer(name) if name else None
        if vrt_layer and vrt_layer.hasScaleBasedVisibility():
            self.update_scale_btn_highlight(int(vrt_layer.minimumScale()))
        else:
            self.update_scale_btn_highlight(0)

    def _activate_overlay_and_select_tool(self):
        """オーバーレイレイヤをアクティブにし、QGISの選択ツールをオンにする"""
        name = self.main_ui.current_vrt_name
        if not name: 
            QMessageBox.warning(self, "警告", "VRTが選択されていません。")
            return
            
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if overlay_layer:
            # 現在のマップツールを記憶（パンツールなど）
            canvas = self.main_ui.iface.mapCanvas()
            self.previous_map_tool = canvas.mapTool()

            # レイヤパネルでオーバーレイを選択状態にする
            self.main_ui.iface.setActiveLayer(overlay_layer)
            # マップキャンバスの「シングルクリック選択」ツールを起動
            try:
                self.main_ui.iface.actionSelect().trigger()
                self.main_ui._set_status("🖱 マップ上で削除したい図郭（ポリゴン）をクリックして選択してください。")
            except Exception as e:
                QgsMessageLog.logMessage(f"選択ツールの起動に失敗しました: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
        else:
            QMessageBox.information(self, "情報", "このVRTにはオーバーレイ（図郭）レイヤがありません。")

    # --- イベントハンドラ ---
    def _switch_vrt(self, index):
        name = self.current_vrt_combo_name()
        if not name or name == self.main_ui.current_vrt_name:
            self.vrt_combo.setToolTip(name)
            self._refresh_vrt_action_buttons()
            return
        self.main_ui.current_vrt_name = name
        self.reload_tif_listwidget()
        self.update_path_display()
        vrt_layer = self.main_ui._get_vrt_layer(name)
        if vrt_layer:
            if vrt_layer.hasScaleBasedVisibility():
                self.update_scale_btn_highlight(int(vrt_layer.minimumScale()))
            else:
                self.update_scale_btn_highlight(0)
        else:
            self.update_scale_btn_highlight(0)
        self.vrt_combo.setToolTip(name)
        self._update_vrt_combo_tooltip()
        self._refresh_vrt_action_buttons()
        self.main_ui._set_status(f"🔄 VRT切り替え: {name}（{len(self.main_ui.tif_list)} ファイル）")
        self.main_ui._schedule_custom_cache_prefetch()

    def _new_vrt(self):
        path, _ = QFileDialog.getSaveFileName(self, "新しいVRTの保存先", "", "VRT Files (*.vrt)")
        if not path: return
        if not path.lower().endswith(".vrt"): path += ".vrt"
        name = self.main_ui.format_vrt_display_name(os.path.splitext(os.path.basename(path))[0])
        if name in self.main_ui.vrt_registry:
            QMessageBox.warning(self, "警告", f"「{name}」はすでに登録されています")
            return
        self.main_ui.vrt_registry[name] = {
            "path": path,
            "tif_list": [],
            "group_crs_authid": "",
            "initial_crs_pending": True,
        }
        self._add_vrt_combo_item(name)
        self.main_ui.current_vrt_name = name
        self.set_current_vrt_name(name)
        self._update_vrt_combo_tooltip()
        self.reload_tif_listwidget()
        self.update_path_display()
        self._refresh_vrt_action_buttons()
        self.main_ui._set_status(f"✅ 新規VRT: {name}")
        self.main_ui._show_map_center_alert("フォルダ追加 または ファイル追加で\nラスタファイルを追加してください")
        QTimer.singleShot(0, self._open_tif_list_window)

    def _rename_vrt(self):
        old_name = self.main_ui.current_vrt_name
        if not old_name:
            return

        old_base_name = self.main_ui.strip_vrt_display_prefix(old_name)
        new_base_name, ok = QInputDialog.getText(self, "VRT名前変更", "新しいVRT名:", text=old_base_name)
        if not ok:
            return
        new_base_name = self.main_ui.strip_vrt_display_prefix(new_base_name)
        if new_base_name.lower().endswith(".vrt"):
            new_base_name = os.path.splitext(new_base_name)[0]

        new_name = self.main_ui.format_vrt_display_name(new_base_name)
        ok_name, message = self.main_ui.validate_vrt_base_name(new_base_name)
        if not ok_name:
            QMessageBox.warning(self, "警告", message)
            return
        if new_name in self.main_ui.vrt_registry and new_name != old_name:
            QMessageBox.warning(self, "警告", f"「{new_name}」はすでに登録されています")
            return
        if new_name == old_name:
            return

        ok, reason, detail = self.main_ui.rename_vrt_entry(old_name, new_name)
        if not ok:
            if reason == "file_exists":
                names = "\n".join(os.path.basename(p) for p in detail)
                QMessageBox.warning(self, "警告", f"同じ名前の関連ファイルがすでに存在します。\n\n{names}")
            elif reason == "invalid":
                QMessageBox.warning(self, "警告", str(detail))
            elif reason == "rename_failed":
                QMessageBox.warning(self, "警告", f"関連ファイル名の変更に失敗しました。\n\n{detail}")
            elif reason == "duplicate":
                QMessageBox.warning(self, "警告", f"「{new_name}」はすでに登録されています")
            else:
                QMessageBox.warning(self, "警告", "VRT名の変更に失敗しました")
            return

        self.populate_vrt_combo()
        self.set_current_vrt_name(new_name)
        self.reload_tif_listwidget()
        self.update_path_display()
        self.main_ui.iface.mapCanvas().refresh()
        self.main_ui._set_status(f"✏️ VRT名を変更しました: {old_name} → {new_name}")

    def _delete_vrt(self):
        if not self.main_ui.current_vrt_name: return
        reply = QMessageBox.question(self, "確認", f"「{self.main_ui.current_vrt_name}」を削除しますか？\n※VRTファイル自体は削除されません", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        self.main_ui._disconnect_scale_signal(self.main_ui.current_vrt_name)
        self.main_ui._remove_vrt_group(self.main_ui.current_vrt_name)
        idx = self.vrt_combo.currentIndex()
        del self.main_ui.vrt_registry[self.main_ui.current_vrt_name]
        self.main_ui.current_vrt_name = ""
        self.vrt_combo.removeItem(idx)
        self._update_vrt_combo_tooltip()
        self._refresh_vrt_action_buttons()
        self.main_ui.iface.mapCanvas().refresh()
        self.main_ui._set_status("🗑 VRTを削除しました")

    def _load_existing_vrt(self):
        path, _ = QFileDialog.getOpenFileName(self, "VRTファイルを選択", "", "VRT Files (*.vrt)")
        if not path: return
        name = self.main_ui.format_vrt_display_name(os.path.splitext(os.path.basename(path))[0])
        tif_list = self.main_ui._get_tif_list_from_vrt(path)

        group_crs_authid = self.main_ui._load_group_crs_authid_from_json(path)

        if name in self.main_ui.vrt_registry:
            reply = QMessageBox.question(self, "確認", f"「{name}」はすでに登録されています。上書きしますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes: return
            self.main_ui._remove_vrt_group(name)
            self.main_ui.vrt_registry[name] = {
                "path": path,
                "tif_list": tif_list,
                "group_crs_authid": group_crs_authid,
                "initial_crs_pending": False,
            }
        else:
            self.main_ui.vrt_registry[name] = {
                "path": path,
                "tif_list": tif_list,
                "group_crs_authid": group_crs_authid,
                "initial_crs_pending": False,
            }
            self._add_vrt_combo_item(name)

        self.main_ui.current_vrt_name = name
        self.set_current_vrt_name(name)
        self._update_vrt_combo_tooltip()
        self.reload_tif_listwidget()
        self.update_path_display()
        saved_crs, saved_overlay_crs = self.main_ui._load_crs_json(path)
        self.main_ui._load_vrt_with_overlay(path, name, apply_default_style=False, saved_crs=saved_crs, saved_overlay_crs=saved_overlay_crs, rebuild_gpkg=False)
        self.main_ui._set_status(f"✅ VRT読み込み完了: {name}（{len(tif_list)} ファイル）")

    # --- TIFリスト操作 ---
    def _build_after_tif_add_if_needed(self, added_count):
        if added_count <= 0:
            return
        if hasattr(self, "btn_build") and not self.btn_build.isEnabled():
            self.main_ui._set_status("⏳ VRT生成中のため、追加後の自動生成をスキップしました")
            return
        QTimer.singleShot(0, self._build_and_load_vrt)

    def _warn_same_path_skipped(self, count):
        if count <= 0:
            return
        parent = self.tif_list_window if self.tif_list_window is not None else self
        QMessageBox.warning(
            parent,
            "同じファイルは追加済みです",
            f"同じファイルが既に追加されています。\n\n追加済みのため、{count} 件は追加しませんでした。",
        )

    def _add_from_folder(self):
        if not self.main_ui.current_vrt_name: return
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if not folder: return
        found = []
        include_subfolders = bool(getattr(self, "include_subfolders", False))
        if include_subfolders:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith((".tif", ".tiff")):
                        found.append(os.path.normpath(os.path.abspath(os.path.join(root, f))))
        else:
            try:
                for f in os.listdir(folder):
                    p = os.path.join(folder, f)
                    if os.path.isfile(p) and f.lower().endswith((".tif", ".tiff")):
                        found.append(os.path.normpath(os.path.abspath(p)))
            except Exception as e:
                QMessageBox.warning(self, "警告", f"フォルダの読み込みに失敗しました。\n\n{e}")
                return
        QgsMessageLog.logMessage(
            f"VRT_ADD_FOLDER folder={folder} include_subfolders={include_subfolders} found={len(found)}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        added, skipped_same_path, skipped_same_name = 0, 0, 0
        for p in found:
            ok, reason, _existing_path = self.main_ui.validate_tif_path_for_add(p)
            if ok:
                self.main_ui.tif_list.append(p)
                added += 1
            else:
                if reason == "same_path":
                    skipped_same_path += 1
                else:
                    skipped_same_name += 1
        self.reload_tif_listwidget()
        msg = f"✅ {added} ファイルを追加"
        if skipped_same_path: msg += f"　⚠ 同じファイル {skipped_same_path} 件"
        if skipped_same_name: msg += f"　⚠ 同名TIF {skipped_same_name} 件禁止"
        self.main_ui._set_status(msg)
        if skipped_same_name:
            QMessageBox.warning(
                self,
                "同名TIFを追加できません",
                f"同じTIF名のファイルが {skipped_same_name} 件見つかりました。\n\n"
                "OrthoManager v2.8では、誤削除やVRT管理の混乱を防ぐため、"
                "別フォルダでも同じTIF名は追加できません。"
            )
        self._warn_same_path_skipped(skipped_same_path)
        self._build_after_tif_add_if_needed(added)

    def _add_files(self):
        if not self.main_ui.current_vrt_name: return
        files, _ = QFileDialog.getOpenFileNames(self, "TIFファイルを選択", "", "GeoTIFF (*.tif *.tiff)")
        added, skipped_same_path, skipped_same_name = 0, 0, 0
        for path in files:
            p = os.path.normpath(os.path.abspath(path))
            ok, reason, _existing_path = self.main_ui.validate_tif_path_for_add(p)
            if ok:
                self.main_ui.tif_list.append(p)
                added += 1
            else:
                if reason == "same_path":
                    skipped_same_path += 1
                else:
                    skipped_same_name += 1
        self.reload_tif_listwidget()
        msg = f"✅ {added} ファイルを追加"
        if skipped_same_path: msg += f"　⚠ 同じファイル {skipped_same_path} 件"
        if skipped_same_name: msg += f"　⚠ 同名TIF {skipped_same_name} 件禁止"
        self.main_ui._set_status(msg)
        if skipped_same_name:
            QMessageBox.warning(
                self,
                "同名TIFを追加できません",
                f"同じTIF名のファイルが {skipped_same_name} 件含まれていました。\n\n"
                "OrthoManager v2.8では、誤削除やVRT管理の混乱を防ぐため、"
                "別フォルダでも同じTIF名は追加できません。"
            )
        self._warn_same_path_skipped(skipped_same_path)
        self._build_after_tif_add_if_needed(added)

    def _remove_selected(self):
        name = self.main_ui.current_vrt_name
        if not name: return

        to_remove_paths = set()

        # 1. TIF一覧ウィンドウから選択されたものを取得
        selected_items = []
        if self.tif_list_window is not None:
            selected_items = self.tif_list_window.tif_listwidget.selectedItems()
        sel_paths_from_list = {
            os.path.normpath(item.data(Qt.ItemDataRole.UserRole))
            for item in selected_items
            if item.data(Qt.ItemDataRole.UserRole)
        }
        if sel_paths_from_list:
            to_remove_paths.update(sel_paths_from_list)
        else:
            sel_names_from_list = {item.text() for item in selected_items}
            for p in self.main_ui.tif_list:
                if os.path.basename(p) in sel_names_from_list:
                    to_remove_paths.add(os.path.normpath(p))

        # 2. マップ上のオーバーレイレイヤから選択された地物を取得
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if overlay_layer:
            for feat in overlay_layer.selectedFeatures():
                loc = feat.attribute("location")
                if loc:
                    to_remove_paths.add(os.path.normpath(loc))

        if not to_remove_paths:
            QMessageBox.information(self, "情報", "削除対象がありません。\nリストから選択するか、「🖱 マップから削除」ボタンで対象の枠（ポリゴン）をクリックして選択してください。")
            return

        # 削除・即時更新の確認
        reply = QMessageBox.question(self, "確認", f"{len(to_remove_paths)} 件の画像をVRTから削除し、即座に更新しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        new_tif_list = [
            p for p in self.main_ui.tif_list if os.path.normpath(p) not in to_remove_paths
        ]

        ok, err_msg = self.main_ui.update_vrt_contents_after_tif_removal(
            name,
            paths_to_remove=to_remove_paths,
            clear_all=False,
        )
        if not ok:
            QMessageBox.warning(self, "警告", f"VRTの中身更新に失敗しました。\n\n{err_msg}")
            return

        # リストの実体から削除
        self.main_ui.vrt_registry[name]["tif_list"] = new_tif_list

        # リストウィジェットの再描画
        self.reload_tif_listwidget()
        
        # マップの選択状態を解除
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if overlay_layer:
            try:
                overlay_layer.removeSelection()
            except Exception:
                pass

        # マップツールの復元 (パンなどの元の状態に戻す)
        if self.previous_map_tool:
            self.main_ui.iface.mapCanvas().setMapTool(self.previous_map_tool)
            self.previous_map_tool = None
        else:
            # 万が一取得できていなかった場合のフォールバック（地図移動ツール）
            try:
                self.main_ui.iface.actionPan().trigger()
            except:
                pass

        self.main_ui._set_status(f"🗑 {len(to_remove_paths)} ファイルをVRTから削除しました")

    def _clear_list(self):
        reply = QMessageBox.question(self, "確認", "リストを全てクリアしますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            name = self.main_ui.current_vrt_name
            if not name:
                return
            ok, err_msg = self.main_ui.update_vrt_contents_after_tif_removal(
                name,
                paths_to_remove=None,
                clear_all=True,
            )
            if not ok:
                QMessageBox.warning(self, "警告", f"VRTの中身更新に失敗しました。\n\n{err_msg}")
                return
            self.main_ui.vrt_registry[name]["tif_list"] = []
            self.reload_tif_listwidget()
            self.main_ui._set_status("🗑 リストをクリアし、VRTの中身を空にしました")

    # --- 縮尺設定 ---
    def _layer_tree_nodes_for_layer(self, layer_id):
        nodes = []
        root = QgsProject.instance().layerTreeRoot()

        def collect(parent):
            for child in list(parent.children()):
                if isinstance(child, QgsLayerTreeLayer):
                    try:
                        if child.layerId() == layer_id:
                            nodes.append(child)
                    except Exception:
                        pass
                elif hasattr(child, "children"):
                    collect(child)

        collect(root)
        return nodes

    def _ensure_vrt_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        group = self.main_ui._find_vrt_group(name)
        display_name = self.main_ui.format_vrt_display_name(name)
        if group is None:
            insert_index = self.main_ui._vrt_group_insert_index(name)
            if insert_index is None:
                insert_index = 0
            insert_index = max(0, min(insert_index, len(root.children())))
            group = root.insertGroup(insert_index, display_name)
        if group.name() != display_name:
            group.setName(display_name)
        group.setExpanded(False)
        return group

    def _move_layer_to_vrt_group(self, layer, group, index):
        if layer is None or group is None:
            return False
        if QgsProject.instance().mapLayer(layer.id()) is None:
            QgsProject.instance().addMapLayer(layer, False)
        nodes = self._layer_tree_nodes_for_layer(layer.id())
        group_nodes = [node for node in nodes if node.parent() == group]
        if group_nodes:
            keep_node = group_nodes[0]
            for node in list(nodes):
                if node is keep_node:
                    continue
                parent = node.parent()
                if parent is not None:
                    try:
                        parent.removeChildNode(node)
                    except Exception:
                        pass
            return True
        if nodes:
            source_node = nodes[0]
            source_parent = source_node.parent()
            try:
                clone = source_node.clone()
                index = max(0, min(index, len(group.children())))
                group.insertChildNode(index, clone)
                for node in list(nodes):
                    parent = node.parent()
                    if parent is not None:
                        try:
                            parent.removeChildNode(node)
                        except Exception:
                            pass
                return True
            except Exception as exc:
                QgsMessageLog.logMessage(f"VRTレイヤ整理エラー: {layer.name()}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                return False
        try:
            index = max(0, min(index, len(group.children())))
            group.insertLayer(index, layer)
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"VRTレイヤ整理エラー: {layer.name()}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def _organize_vrt_layers(self):
        name = self.main_ui.current_vrt_name
        if not name:
            QMessageBox.warning(self, "警告", "VRTが選択されていません。")
            return
        vrt_layer = self.main_ui._get_vrt_layer(name)
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if not vrt_layer and not overlay_layer:
            QMessageBox.information(self, "情報", "整理できるVRTレイヤがありません。")
            return
        group = self._ensure_vrt_group(name)
        allowed_ids = {layer.id() for layer in (overlay_layer, vrt_layer) if layer}
        removed_extra = 0
        root = QgsProject.instance().layerTreeRoot()
        for child in list(group.children()):
            if isinstance(child, QgsLayerTreeLayer) and child.layerId() not in allowed_ids:
                try:
                    clone = child.clone()
                    insert_index = len(root.children())
                    try:
                        insert_index = root.children().index(group) + 1
                    except Exception:
                        pass
                    root.insertChildNode(insert_index, clone)
                    group.removeChildNode(child)
                    removed_extra += 1
                except Exception as exc:
                    QgsMessageLog.logMessage(f"VRTレイヤ整理: 余計なレイヤの移動失敗: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        index = 0
        moved = 0
        if overlay_layer and self._move_layer_to_vrt_group(overlay_layer, group, index):
            moved += 1
            index += 1
        if vrt_layer and self._move_layer_to_vrt_group(vrt_layer, group, index):
            moved += 1
        self.main_ui.iface.layerTreeView().refreshLayerSymbology(None)
        self.main_ui.iface.mapCanvas().refresh()
        self.main_ui._set_status(f"✅ レイヤ整理: {self.main_ui.strip_vrt_display_prefix(name)} (戻し{moved}件 / 外出し{removed_extra}件)")
    def _apply_scale_preset(self, scale_value):
        name = self.main_ui.current_vrt_name
        if not name: return
        vrt_layer = self.main_ui._get_vrt_layer(name)
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if not vrt_layer: return
        vrt_p = self.main_ui.vrt_path
        
        self.main_ui._set_scale_to_layers(vrt_layer, overlay_layer, scale_value)
        self.update_scale_btn_highlight(scale_value)
        if vrt_p and os.path.exists(vrt_p):
            self.main_ui._save_qml(vrt_layer, vrt_p, overlay_layer)
        self.main_ui._set_status(f"✅ 縮尺 1:{scale_value:,} を適用・保存")

    def _apply_scale_manual(self):
        try:
            val = int(self.scale_manual_edit.text().strip().replace(',', ''))
            if val <= 0: raise ValueError
        except ValueError:
            QMessageBox.warning(self, "警告", "正しい数値を入力してください（例: 3000）")
            return
        self._apply_scale_preset(val)

    def _apply_scale_all(self):
        name = self.main_ui.current_vrt_name
        vrt_layer = self.main_ui._get_vrt_layer(name)
        overlay_layer = self.main_ui._get_overlay_layer(name)
        if not vrt_layer: return
        vrt_p = self.main_ui.vrt_path
        
        # 100枚以上の場合の警告アラート
        tif_count = len(self.main_ui.tif_list)
        if tif_count >= 100:
            reply = QMessageBox.question(
                self, 
                "確認", 
                f"{tif_count} 枚の写真を全表示してもよろしいでしょうか？\n枚数が多いため、描画に時間がかかる場合があります。", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # VRTレイヤは縮尺制限を解除（常に表示される）
        vrt_layer.setScaleBasedVisibility(False)
        vrt_layer.triggerRepaint()
        
        if overlay_layer:
            # QGISの仕様で setMinimumScale(0) の「0」は「無制限（常に表示）」になってしまうため、
            # 最小も最大も 0.1 (絶対に表示されない値) にして、レイヤパネル上でグレーアウトさせます。
            overlay_layer.setScaleBasedVisibility(True)
            overlay_layer.setMinimumScale(0.1)
            overlay_layer.setMaximumScale(0.1)
            overlay_layer.triggerRepaint()
            
        self.main_ui.iface.mapCanvas().refresh()
        self.update_scale_btn_highlight(0)
        if vrt_p and os.path.exists(vrt_p):
            self.main_ui._save_qml(vrt_layer, vrt_p, overlay_layer)
        self.main_ui._set_status("✅ 全表示（縮尺制限なし）を適用・保存")

    # --- ビルド(VRT構築)タスク ---
    def _build_and_load_vrt(self):
        if not GDAL_OK: return
        if not self.main_ui.current_vrt_name: return
        self._vrt_build_ui_start = time.perf_counter()

        if not self.main_ui.tif_list:
            ok, err_msg = self.main_ui.update_vrt_contents_after_tif_removal(
                self.main_ui.current_vrt_name,
                paths_to_remove=None,
                clear_all=True,
            )
            if ok:
                self.reload_tif_listwidget()
                self.main_ui._set_status("🗑 TIFなし：VRTの中身を空にしました")
            else:
                self.main_ui._set_status(f"❌ VRT空更新エラー: {err_msg}")
                QMessageBox.warning(self, "警告", f"VRTの中身更新に失敗しました。\n\n{err_msg}")
            return

        self.btn_build.setEnabled(False)
        self.vrt_progress_bar.setVisible(True)
        self.vrt_progress_bar.setValue(0)
        self.main_ui._set_status("⏳ バックグラウンド処理の準備中...")

        vrt_path = self.main_ui.vrt_path
        layer_name = self.main_ui.current_vrt_name
        QgsMessageLog.logMessage(
            f"VRT_BUILD_DIAG_START layer={layer_name} tif_count={len(self.main_ui.tif_list)} path={vrt_path}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        overlay_layer = self.main_ui._get_overlay_layer(layer_name)
        existing_vrt_layer = self.main_ui._get_vrt_layer(layer_name)
        saved_crs = None
        saved_overlay_crs = None
        saved_group_crs = self.main_ui._group_crs_from_registry(layer_name)
        if not saved_group_crs.isValid():
            saved_group_crs = self.main_ui._group_crs_from_tree(layer_name)
        if saved_group_crs.isValid():
            entry = self.main_ui.vrt_registry.get(layer_name, {})
            if isinstance(entry, dict):
                entry["group_crs_authid"] = saved_group_crs.authid()

        if existing_vrt_layer:
            saved_crs = existing_vrt_layer.crs()
            if os.path.exists(vrt_path):
                try: existing_vrt_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + ".qml")
                except: pass
        if overlay_layer:
            saved_overlay_crs = overlay_layer.crs()
            if os.path.exists(vrt_path):
                try: overlay_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + "_overlay.qml")
                except: pass

        vrt_qml = os.path.splitext(vrt_path)[0] + ".qml"
        overlay_qml = os.path.splitext(vrt_path)[0] + "_overlay.qml"
        is_update = os.path.exists(vrt_qml) or os.path.exists(overlay_qml)
        gpkg_path = os.path.splitext(vrt_path)[0] + "_tiles.gpkg"
        insert_index = self.main_ui._vrt_group_insert_index(layer_name)

        self.main_ui._disconnect_scale_signal(layer_name)
        self.main_ui._remove_vrt_group(layer_name)
        QApplication.processEvents()
        
        QTimer.singleShot(100, lambda: self._start_build_task(vrt_path, layer_name, saved_crs, saved_overlay_crs, is_update, gpkg_path, insert_index))

    def _start_build_task(self, vrt_path, layer_name, saved_crs, saved_overlay_crs, is_update, gpkg_path, insert_index):
        if not self.main_ui.tif_list:
            ok, err_msg = self.main_ui.update_vrt_contents_after_tif_removal(
                layer_name,
                paths_to_remove=None,
                clear_all=True,
            )
            if ok:
                self.main_ui._set_status("🗑 TIFなし：VRTの中身を空にしました")
            else:
                self.main_ui._set_status(f"❌ VRT空更新エラー: {err_msg}")
                QMessageBox.warning(self, "警告", f"VRTの中身更新に失敗しました。\n\n{err_msg}")
            self.btn_build.setEnabled(True)
            self.vrt_progress_bar.setVisible(False)
            return

        self.main_ui._set_status("⏳ バックグラウンドで生成中（画面操作は可能です）...")
        
        engine_path = find_external_vrt_engine_path()
        if engine_path:
            QgsMessageLog.logMessage(
                f"VRT_ENGINE_MODE external path={engine_path}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            self.build_task = ExternalVrtEngineTask(self.main_ui.tif_list, vrt_path, gpkg_path, True, engine_path)
        else:
            QgsMessageLog.logMessage(
                "VRT_ENGINE_MODE internal fallback",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            self.build_task = BuildVrtAndGpkgTask(self.main_ui.tif_list, vrt_path, gpkg_path, True)
        self.build_task.signals.completed.connect(
            lambda result, err, t_vrt, t_gpkg, timing: self._on_build_task_completed(
                result, err, vrt_path, layer_name, saved_crs, saved_overlay_crs, is_update, t_vrt, t_gpkg, insert_index, timing
            )
        )
        self.build_task.progressChanged.connect(lambda v: self.vrt_progress_bar.setValue(int(v)))
        QgsApplication.taskManager().addTask(self.build_task)

    def _on_build_task_completed(self, result, err_msg, vrt_path, layer_name, saved_crs, saved_overlay_crs, is_update, temp_vrt, temp_gpkg, insert_index, timing=None):
        timing = timing or {}
        self.btn_build.setEnabled(True)
        self.vrt_progress_bar.setVisible(False)

        if not result:
            self.main_ui._set_status(f"❌ 生成エラー: {err_msg}")
            QMessageBox.critical(self, "エラー", f"VRT/GPKGの生成に失敗しました:\n{err_msg}")
            for t_file in [temp_vrt, temp_gpkg]:
                 if t_file and os.path.exists(t_file):
                      try: os.remove(t_file)
                      except: pass
            return

        import shutil
        move_start = time.perf_counter()
        try:
            if os.path.exists(temp_vrt):
                shutil.move(temp_vrt, vrt_path)
            if os.path.exists(temp_gpkg):
                gpkg_path = os.path.splitext(vrt_path)[0] + "_tiles.gpkg"
                shutil.move(temp_gpkg, gpkg_path)
        except Exception as e:
            self.main_ui._set_status(f"❌ ファイル移動エラー: {e}")
            QMessageBox.critical(self, "エラー", f"一時ファイルの適用に失敗しました:\n{e}")
            return
        move_sec = time.perf_counter() - move_start

        if not (saved_crs and saved_crs.isValid()):
            saved_crs, saved_overlay_crs = self.main_ui._load_crs_json(vrt_path)

        load_start = time.perf_counter()
        self.main_ui._load_vrt_with_overlay(vrt_path, layer_name,
                                    apply_default_style=not is_update,
                                    saved_crs=saved_crs,
                                    saved_overlay_crs=saved_overlay_crs,
                                    rebuild_gpkg=False,
                                    insert_index=insert_index)
        load_sec = time.perf_counter() - load_start
        crs_start = time.perf_counter()
        self.main_ui._handle_group_crs_after_vrt_update(layer_name)
        crs_total_sec = time.perf_counter() - crs_start
        crs_sec = float(getattr(self.main_ui, "_last_group_crs_apply_sec", crs_total_sec))
        crs_dialog_sec = float(getattr(self.main_ui, "_last_group_crs_dialog_sec", 0.0))

        total_sec = float(timing.get("task_total_sec", 0.0)) + move_sec + load_sec + crs_sec
        ui_total_sec = time.perf_counter() - getattr(self, "_vrt_build_ui_start", time.perf_counter())
        QgsMessageLog.logMessage(
            "VRT_BUILD_DIAG_SUMMARY "
            f"layer={layer_name} tif_count={int(timing.get('tif_count', len(self.main_ui.tif_list)))} "
            f"total_sec={total_sec:.2f} ui_total_sec={ui_total_sec:.2f} "
            f"task_total_sec={float(timing.get('task_total_sec', 0.0)):.2f} "
            f"mode={str(timing.get('vrt_update_mode', 'VRT更新')).replace(' ', '_')} "
            f"vrt_update_sec={float(timing.get('vrt_update_sec', 0.0)):.2f} "
            f"gpkg_sec={float(timing.get('gpkg_sec', 0.0)):.2f} "
            f"move_sec={move_sec:.2f} qgis_reload_sec={load_sec:.2f} crs_apply_sec={crs_sec:.2f} "
            f"crs_dialog_wait_sec={crs_dialog_sec:.2f} crs_total_elapsed_sec={crs_total_sec:.2f} crs_dialog_excluded=True "
            f"pam_disabled={bool(timing.get('pam_disabled', False))}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        QgsMessageLog.logMessage(
            "VRT生成時間: "
            f"総計={total_sec:.2f}s / "
            f"タスク={float(timing.get('task_total_sec', 0.0)):.2f}s / "
            f"{timing.get('vrt_update_mode', 'VRT更新')}={float(timing.get('vrt_update_sec', 0.0)):.2f}s / "
            f"GPKG同期={float(timing.get('gpkg_sec', 0.0)):.2f}s / "
            f"一時ファイル移動={move_sec:.2f}s / "
            f"QGISレイヤ再読込={load_sec:.2f}s / "
            f"CRS適用={crs_sec:.2f}s（選択待ち除外） / "
            f"aux.xml抑制={'ON' if timing.get('pam_disabled', False) else 'OFF'} / "
            f"TIF={int(timing.get('tif_count', len(self.main_ui.tif_list)))}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )















