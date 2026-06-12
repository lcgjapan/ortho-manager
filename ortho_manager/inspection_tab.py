import math
import os
import re
import sqlite3
import time
import json

from qgis.PyQt.QtCore import QObject, Qt, QDateTime, QEvent, QRect, QTimer, QVariant
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap, QKeySequence, QShortcut, QBrush, QKeyEvent
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QScrollArea, QInputDialog, QColorDialog, QMenu,
    QWidgetAction, QSizePolicy, QRubberBand, QButtonGroup, QTextEdit, QApplication, QLineEdit,
    QKeySequenceEdit, QPlainTextEdit
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsMessageLog, Qgis, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
    QgsSingleSymbolRenderer, QgsFeatureRequest, QgsRectangle,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling, QgsSettings,
    QgsLayerTreeLayer, QgsField
)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker, QgsSnapIndicator
from .i18n import tr, tr_text
from .inspection_guide_lines import GUIDE_ROLE_AREA, GUIDE_ROLE_DONE, GUIDE_ROLE_LINE, InspectionGuideLineBuilder
from .inspection_constants import *
from .inspection_dialogs import (
    InspectionExportDialog,
    InspectionShortcutDialog,
    MemoDialog,
    QgisLayerImportDialog,
    VectorImportOptionsDialog,
)
from .inspection_context_menu import InspectionContextMenuMixin
from .inspection_editing import InspectionEditingMixin
from .inspection_layer_tree_copy import InspectionLayerTreeCopyMixin
from .inspection_map_tool import (
    InspectionActionMenuButton,
    InspectionGroupMenuButton,
    InspectionLayerMenuButton,
    InspectionMapTool,
)
try:
    from qgis.gui import QgsProjectionSelectionDialog
except Exception:
    QgsProjectionSelectionDialog = None

try:
    from osgeo import gdal, ogr, osr
    ogr.UseExceptions()
    OGR_OK = True
except Exception:
    OGR_OK = False


def _safe_layer_name(text):
    text = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
    return text[:80] if text else "inspection"


def _base_name(code, name):
    return f"{code}_{name}" if code else name



class InspectionTabWidget(InspectionLayerTreeCopyMixin, InspectionEditingMixin, InspectionContextMenuMixin, QWidget):
    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui
        self.iface = main_ui.iface
        self.gpkg_path = ""
        self.gpkg_paths = {inspection_type: "" for inspection_type in INSPECTION_TYPES}
        self.layers = {}
        self.trash_layer_ids = {}
        self.active_inspection_type = INSPECTION_TYPE_FREE
        self.last_free_geom_type = "line"
        self.free_groups = []
        self.active_free_group_name = ""
        self.active_layer_id = ""
        self.active_geom_type = "polygon"
        self.active_color = "ff0000"
        self.operation_mode = "create"
        self.last_selection_mode = "select"
        self.create_return_mode = "pan"
        self.map_tool = None
        self.buttons_by_source = {}
        self.round_buttons = {}
        self.inspection_enabled = False
        self.continuous_capture_enabled = False
        self.active_capture_shape = "polygon"
        self.context_filter_canvas = None
        self.current_context_menu = None
        self.right_button_guard_active = False
        self.suppress_next_context_menu = False
        self.round_menu_expanded = {}
        self.free_group_menu_expanded = {}
        self._original_selection_colors = {}
        self.selection_highlight_items = []
        self.paste_flash_highlight_items = []
        self.drag_highlight_button = None
        self.drag_highlight_target = ""
        self.drag_source_button = None
        self.drag_preview_label = None
        self.action_drag_highlight_button = None
        self.action_drag_highlight_target = ""
        self.action_drag_source_button = None
        self.action_drag_preview_label = None
        self.group_drag_highlight_button = None
        self._guide_refresh_pending = False
        self.group_drag_highlight_target = ""
        self.group_drag_source_button = None
        self.group_drag_preview_label = None
        self.guide_layer_ids = []
        self.feature_move_targets = []
        self.feature_move_preview_bands = []
        self.feature_move_undo_stack = []
        self._layers_needing_edit_refresh = set()
        self._refresh_counts_pending = False
        self._gpkg_management_sync_pending = False
        self._gpkg_management_sync_blocked = False
        self._layer_lock_rebuild_pending = False
        self._layer_tree_copy_manager = None
        self._edit_preview_width_overridden = False
        self._original_digitizing_line_width = None
        self._original_digitizing_line_width_had_key = False
        self.edit_overlap_candidates = []
        self.edit_overlap_index = -1
        self.edit_overlap_point = None
        self.edit_overlap_vertex_candidates = []
        self.edit_overlap_vertex_index = -1
        self.edit_overlap_vertex_marker = None
        self.edit_overlap_vertex_preview_band = None
        self.edit_overlap_anchor_point = None
        self.edit_overlap_anchor_candidates = []
        self.edit_overlap_anchor_index = -1
        self.ignore_next_direct_overlap_release = False
        self.just_finished_direct_overlap_vertex_edit = False
        self.suspend_edit_hover_prepare = False
        self._build_ui()
        self.install_layer_tree_copy_menu()
        self.refresh_texts()

    def _btn_style(self, color, active=False):
        border = "2px solid #222" if active else "1px solid #bdc3c7"
        return (
            f"QPushButton{{background:#{color};color:black;border:{border};"
            "border-radius:4px;padding:3px;font-size:10px;text-align:left;}}"
            "QPushButton:hover{border:2px solid #2c3e50;background:#f8f9fa;}"
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        self.top_group = QGroupBox()
        top_layout = QVBoxLayout(self.top_group)
        path_row = QHBoxLayout()
        self.path_label = QLabel()
        self.path_label.setWordWrap(False)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        path_row.addWidget(self.path_label)
        top_layout.addLayout(path_row)

        row = QGridLayout()
        self.btn_new = QPushButton()
        self.btn_new.clicked.connect(self.create_new_inspection)
        self.btn_load = QPushButton()
        self.btn_load.clicked.connect(self.load_inspection_file)
        self.btn_export = QPushButton()
        self.btn_export.clicked.connect(self.export_inspection)
        self.btn_on = QPushButton()
        self.btn_on.setCheckable(True)
        self.btn_on.toggled.connect(self.toggle_inspection)
        for button in (self.btn_new, self.btn_load, self.btn_export, self.btn_on):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row.addWidget(self.btn_new, 0, 0)
        row.addWidget(self.btn_load, 0, 1)
        row.addWidget(self.btn_export, 1, 0)
        row.addWidget(self.btn_on, 1, 1)
        top_layout.addLayout(row)
        layout.addWidget(self.top_group)

        self.module_box = QGroupBox()
        module_layout = QHBoxLayout(self.module_box)
        module_layout.setContentsMargins(8, 8, 8, 8)
        module_layout.setSpacing(6)
        self.module_combo = QComboBox()
        self.populate_module_combo()
        self.module_combo.currentIndexChanged.connect(lambda *_: self.refresh_ui())
        self.module_create_btn = QPushButton()
        self.module_create_btn.clicked.connect(self.create_inspection_module)
        self.module_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.module_create_btn.setMinimumWidth(72)
        module_layout.addWidget(self.module_combo)
        module_layout.addWidget(self.module_create_btn)
        layout.addWidget(self.module_box)

        self.rounds_box = QGroupBox()
        rounds_layout = QHBoxLayout(self.rounds_box)
        for round_no in (2, 3, 4):
            button = QPushButton()
            button.clicked.connect(lambda _=False, r=round_no: self.add_round(r))
            self.round_buttons[round_no] = button
            rounds_layout.addWidget(button)

        self.guide_box = QGroupBox()
        guide_layout = QGridLayout(self.guide_box)
        guide_layout.setColumnStretch(1, 1)
        self.guide_mode_combo = QComboBox()
        self.guide_mode_combo.addItem(tr_text("検査範囲ポリゴンを使う"), "area")
        self.guide_mode_combo.addItem(tr_text("図郭ポリゴンから作る"), "tile")
        self.guide_mode_combo.currentIndexChanged.connect(self.refresh_guide_layer_combo)
        self.guide_layer_combo = QComboBox()
        self.guide_layer_combo.currentIndexChanged.connect(self.refresh_guide_id_field_combo)
        self.guide_width_combo = QComboBox()
        for width in (100, 125, 150, 200):
            self.guide_width_combo.addItem(f"{width}m", width)
        self.guide_width_combo.currentIndexChanged.connect(self.apply_guide_width_preset)
        self.guide_width_edit = QLineEdit("100")
        self.guide_width_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.guide_width_edit.setFixedWidth(72)
        self.guide_create_btn = QPushButton()
        self.guide_create_btn.clicked.connect(self.create_guide_lines)
        guide_layout.addWidget(self.guide_mode_combo, 0, 0)
        guide_layout.addWidget(self.guide_layer_combo, 0, 1)
        width_row = QWidget()
        width_layout = QHBoxLayout(width_row)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.setSpacing(6)
        self.guide_width_label = QLabel(tr_text("幅(m)"))
        width_layout.addWidget(self.guide_width_label)
        width_layout.addWidget(self.guide_width_combo)
        width_layout.addWidget(self.guide_width_edit)
        width_layout.addWidget(self.guide_create_btn)
        width_layout.addStretch()
        guide_layout.addWidget(width_row, 1, 0, 1, 2)

        mesh_row = QWidget()
        mesh_layout = QHBoxLayout(mesh_row)
        mesh_layout.setContentsMargins(0, 0, 0, 0)
        mesh_layout.setSpacing(4)
        self.guide_mesh_label = QLabel(tr_text("メッシュ"))
        self.guide_mesh_cols_label = QLabel(tr_text("横"))
        mesh_layout.addWidget(self.guide_mesh_label)
        mesh_layout.addWidget(self.guide_mesh_cols_label)
        self.guide_mesh_cols_edit = QLineEdit("7")
        self.guide_mesh_cols_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.guide_mesh_cols_edit.setFixedWidth(34)
        mesh_layout.addWidget(self.guide_mesh_cols_edit)
        self.guide_mesh_rows_label = QLabel(tr_text("縦"))
        mesh_layout.addWidget(self.guide_mesh_rows_label)
        self.guide_mesh_rows_edit = QLineEdit("3")
        self.guide_mesh_rows_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.guide_mesh_rows_edit.setFixedWidth(34)
        mesh_layout.addWidget(self.guide_mesh_rows_edit)
        mesh_layout.addWidget(QLabel("ID"))
        self.guide_id_field_combo = QComboBox()
        self.guide_id_field_combo.setMinimumWidth(80)
        mesh_layout.addWidget(self.guide_id_field_combo, 1)
        self.guide_mesh_create_btn = QPushButton(tr_text("作成"))
        self.guide_mesh_create_btn.setFixedWidth(46)
        self.guide_mesh_create_btn.clicked.connect(self.create_guide_mesh)
        mesh_layout.addWidget(self.guide_mesh_create_btn)
        guide_layout.addWidget(mesh_row, 2, 0, 1, 2)
        layout.addWidget(self.guide_box)

        self.items_box = QGroupBox()
        self.items_layout = QGridLayout(self.items_box)
        self.items_layout.setSpacing(4)
        layout.addWidget(self.items_box)

        self.action_box = QGroupBox()
        action_layout = QGridLayout(self.action_box)
        self.btn_select = QPushButton()
        self.btn_select.clicked.connect(self.start_select)
        self.btn_delete = QPushButton()
        self.btn_delete.clicked.connect(self.start_delete)
        self.btn_edit = QPushButton()
        self.btn_edit.clicked.connect(self.start_edit)
        self.btn_merge = QPushButton()
        self.btn_merge.clicked.connect(self.start_merge)
        self.btn_shortcut_settings = QPushButton()
        self.btn_shortcut_settings.clicked.connect(self.open_inspection_shortcut_dialog)
        self.chk_delete_confirm = QCheckBox()
        self.chk_delete_confirm.setChecked(self.delete_confirm_enabled())
        self.chk_delete_confirm.toggled.connect(self.set_delete_confirm_enabled)
        self.chk_layer_change_confirm = QCheckBox()
        self.chk_layer_change_confirm.setChecked(self.layer_change_confirm_enabled())
        self.chk_layer_change_confirm.toggled.connect(self.set_layer_change_confirm_enabled)
        for button in (self.btn_select, self.btn_delete, self.btn_edit, self.btn_merge, self.btn_shortcut_settings):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        action_layout.addWidget(self.btn_select, 0, 0)
        action_layout.addWidget(self.btn_delete, 0, 1)
        action_layout.addWidget(self.btn_edit, 1, 0)
        action_layout.addWidget(self.btn_merge, 1, 1)
        action_layout.addWidget(self.btn_shortcut_settings, 2, 0, 1, 2)
        action_layout.addWidget(self.chk_delete_confirm, 3, 0)
        action_layout.addWidget(self.chk_layer_change_confirm, 3, 1)
        layout.addWidget(self.action_box)

        self.maintenance_box = QGroupBox()
        maintenance_layout = QGridLayout(self.maintenance_box)
        self.btn_add_layer = QPushButton()
        self.btn_add_layer.clicked.connect(self.add_manual_layer)
        self.btn_import_vector = QPushButton()
        self.btn_import_vector.clicked.connect(self.import_vector_layers)
        self.btn_import_qgis_layer = QPushButton()
        self.btn_import_qgis_layer.clicked.connect(self.import_qgis_project_layers)
        self.btn_rename_item = QPushButton()
        self.btn_rename_item.clicked.connect(self.rename_inspection_item)
        self.btn_color_item = QPushButton()
        self.btn_color_item.clicked.connect(self.change_inspection_color)
        self.btn_move_manual = QPushButton()
        self.btn_move_manual.clicked.connect(self.move_manual_layer_round)
        self.btn_add_group = QPushButton()
        self.btn_add_group.clicked.connect(self.add_free_group)
        self.btn_rename_group = QPushButton()
        self.btn_rename_group.clicked.connect(self.rename_free_group)
        self.btn_delete_manual = QPushButton()
        self.btn_delete_manual.clicked.connect(self.delete_manual_layer)
        self.btn_delete_round = QPushButton()
        self.btn_delete_round.clicked.connect(self.delete_ortho_round)
        self.btn_delete_free_group = QPushButton()
        self.btn_delete_free_group.clicked.connect(self.delete_free_group)
        self.btn_delete_inspection_type = QPushButton()
        self.btn_delete_inspection_type.clicked.connect(self.delete_current_inspection_type)
        self.btn_clean_empty = QPushButton()
        self.btn_clean_empty.clicked.connect(self.delete_empty_geometry_features)
        self.btn_organize_layers = QPushButton()
        self.btn_organize_layers.clicked.connect(self.organize_inspection_layers)
        for button in (
            self.btn_add_layer, self.btn_import_vector, self.btn_import_qgis_layer, self.btn_rename_item, self.btn_color_item,
            self.btn_move_manual, self.btn_delete_manual, self.btn_clean_empty,
            self.btn_organize_layers, self.btn_add_group, self.btn_rename_group,
            self.btn_delete_round, self.btn_delete_free_group, self.btn_delete_inspection_type,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        maintenance_layout.addWidget(self.btn_add_layer, 0, 0)
        maintenance_layout.addWidget(self.btn_import_vector, 0, 1)
        maintenance_layout.addWidget(self.btn_import_qgis_layer, 0, 2)
        maintenance_layout.addWidget(self.btn_rename_item, 1, 0)
        maintenance_layout.addWidget(self.btn_color_item, 1, 1)
        maintenance_layout.addWidget(self.btn_move_manual, 1, 2)
        maintenance_layout.addWidget(self.btn_delete_manual, 2, 0)
        maintenance_layout.addWidget(self.btn_clean_empty, 2, 1)
        maintenance_layout.addWidget(self.btn_add_group, 2, 2)
        maintenance_layout.addWidget(self.btn_rename_group, 2, 2)
        maintenance_layout.addWidget(self.btn_delete_round, 3, 0)
        maintenance_layout.addWidget(self.btn_delete_free_group, 3, 0)
        maintenance_layout.addWidget(self.btn_delete_inspection_type, 3, 1)
        maintenance_layout.addWidget(self.btn_organize_layers, 3, 2)
        layout.addWidget(self.maintenance_box)
        layout.addWidget(self.rounds_box)
        layout.addStretch()
        self.inspection_qshortcuts = []
        self.refresh_inspection_qshortcuts()
        self.connect_guide_layer_refresh_signals()
        self.refresh_ui()

    def refresh_texts(self):
        if not hasattr(self, "top_group"):
            return
        self.top_group.setTitle(tr("inspection.group.management"))
        self.btn_new.setText(tr("inspection.btn.new"))
        self.btn_load.setText(tr("inspection.btn.load"))
        self.btn_export.setText(tr("inspection.btn.export"))
        self.btn_on.setText(tr("inspection.btn.on"))
        self.module_box.setTitle(tr_text("定型検査セット作成"))
        self.module_create_btn.setText(tr_text("作成"))
        self.rounds_box.setTitle(tr("inspection.group.rounds"))
        for round_no, button in self.round_buttons.items():
            button.setText(tr("inspection.btn.round_add").format(round=round_no))
        self.guide_box.setTitle(tr("inspection.guide.group"))
        self.guide_mode_combo.setItemText(0, tr_text("検査範囲ポリゴンを使う"))
        self.guide_mode_combo.setItemText(1, tr_text("図郭ポリゴンから作る"))
        self.guide_width_label.setText(tr_text("幅(m)"))
        self.guide_create_btn.setText(tr("inspection.guide.create"))
        self.guide_mesh_label.setText(tr_text("メッシュ"))
        self.guide_mesh_cols_label.setText(tr_text("横"))
        self.guide_mesh_rows_label.setText(tr_text("縦"))
        self.guide_mesh_create_btn.setText(tr_text("作成"))
        self.items_box.setTitle(tr("inspection.group.items"))
        self.action_box.setTitle(tr("inspection.group.edit"))
        self.btn_select.setText(tr("inspection.btn.select_feature"))
        self.btn_delete.setText(tr("inspection.btn.delete"))
        self.btn_edit.setText(tr("inspection.btn.edit"))
        self.btn_merge.setText(tr("inspection.btn.merge"))
        self.btn_shortcut_settings.setText(tr("inspection.btn.shortcut"))
        self.chk_delete_confirm.setText(tr("inspection.chk.delete_confirm"))
        self.chk_layer_change_confirm.setText(tr_text("移層確認"))
        self.maintenance_box.setTitle(tr("inspection.group.layers"))
        self.btn_add_layer.setText(tr("inspection.btn.layer_add"))
        self.btn_import_vector.setText(tr("inspection.btn.vector_import"))
        self.btn_import_qgis_layer.setText(tr("inspection.btn.qgis_import"))
        self.btn_rename_item.setText(tr("inspection.btn.layer_rename"))
        self.btn_color_item.setText(tr("inspection.btn.color"))
        self.btn_move_manual.setText(tr("inspection.btn.layer_move"))
        self.btn_add_group.setText(tr("inspection.btn.group_add"))
        self.btn_rename_group.setText(tr("inspection.btn.group_rename"))
        self.btn_delete_manual.setText(tr("inspection.btn.manual_delete"))
        self.btn_delete_round.setText(tr("inspection.btn.round_delete"))
        self.btn_delete_free_group.setText(tr("inspection.btn.group_delete"))
        self.btn_clean_empty.setText(tr("inspection.btn.empty_delete"))
        self.btn_organize_layers.setText(tr("inspection.btn.organize"))
        self._refresh_delete_inspection_type_text()
        self.refresh_ui()

    def populate_module_combo(self):
        self.module_combo.clear()
        self.add_module_header("オルソ検査用")
        for round_no in sorted(ROUND_ITEMS.keys()):
            self.add_module_item(f"  └ {self.round_title(round_no)}", {"kind": "ortho_round", "round_no": round_no})
        self.add_module_header("LP検査用")
        self.module_combo.addItem(tr_text("未設定"), {"kind": "disabled"})
        item = self.module_combo.model().item(self.module_combo.count() - 1)
        if item is not None:
            item.setEnabled(False)
            item.setForeground(QBrush(QColor("#8a8a8a")))
        self.module_combo.setCurrentIndex(1 if self.module_combo.count() > 1 else 0)

    def add_module_header(self, text):
        self.module_combo.addItem(text, {"kind": "header"})
        item = self.module_combo.model().item(self.module_combo.count() - 1)
        if item is None:
            return
        item.setEnabled(False)
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(QColor("#202020")))

    def add_module_item(self, text, data):
        self.module_combo.addItem(text, data)
        item = self.module_combo.model().item(self.module_combo.count() - 1)
        if item is not None:
            item.setForeground(QBrush(QColor("#0645ad")))

    def selected_module_data(self):
        data = self.module_combo.currentData() if hasattr(self, "module_combo") else None
        return data if isinstance(data, dict) else {}

    def selected_module_round_no(self):
        data = self.selected_module_data()
        if data.get("kind") != "ortho_round":
            return 0
        try:
            return int(data.get("round_no", 0) or 0)
        except Exception:
            return 0

    def refresh_guide_layer_combo(self):
        if not hasattr(self, "guide_layer_combo"):
            return
        self._guide_refresh_pending = False
        current_id = self.guide_layer_combo.currentData()
        self.guide_layer_combo.blockSignals(True)
        self.guide_layer_combo.clear()
        self.guide_layer_ids = []
        for layer in InspectionGuideLineBuilder(self).polygon_layer_candidates():
            self.guide_layer_combo.addItem(layer.name(), layer.id())
            self.guide_layer_ids.append(layer.id())
        if current_id:
            index = self.guide_layer_combo.findData(current_id)
            if index >= 0:
                self.guide_layer_combo.setCurrentIndex(index)
        self.guide_layer_combo.blockSignals(False)
        self.guide_create_btn.setEnabled(bool(self.guide_layer_ids))
        self.refresh_guide_id_field_combo()

    def refresh_guide_id_field_combo(self, *args):
        if not hasattr(self, "guide_id_field_combo"):
            return
        current = self.guide_id_field_combo.currentData()
        self.guide_id_field_combo.blockSignals(True)
        self.guide_id_field_combo.clear()
        layer = self.selected_guide_source_layer()
        if layer:
            try:
                preferred = ("NAME", "name", "ID", "id", "図郭名", "図郭ID", "tile_id", "map_name")
                fields = list(layer.fields())
                ordered = []
                for key in preferred:
                    for field in fields:
                        if field.name() == key and field.name() not in ordered:
                            ordered.append(field.name())
                for field in fields:
                    if field.name() not in ordered:
                        ordered.append(field.name())
                for name in ordered:
                    self.guide_id_field_combo.addItem(name, name)
            except Exception:
                pass
        index = self.guide_id_field_combo.findData(current)
        if index >= 0:
            self.guide_id_field_combo.setCurrentIndex(index)
        self.guide_id_field_combo.blockSignals(False)
        enabled = bool(layer and self.guide_id_field_combo.count())
        self.guide_id_field_combo.setEnabled(enabled)
        if hasattr(self, "guide_mesh_create_btn"):
            self.guide_mesh_create_btn.setEnabled(enabled)

    def schedule_guide_layer_combo_refresh(self, *args):
        if self._guide_refresh_pending:
            return
        self._guide_refresh_pending = True
        QTimer.singleShot(0, self.refresh_guide_layer_combo)

    def connect_guide_layer_refresh_signals(self):
        project = QgsProject.instance()
        try:
            project.layersAdded.connect(self.schedule_guide_layer_combo_refresh)
        except Exception:
            pass
        try:
            project.layersRemoved.connect(self.schedule_guide_layer_combo_refresh)
        except Exception:
            pass

    def disconnect_guide_layer_refresh_signals(self):
        project = QgsProject.instance()
        try:
            project.layersAdded.disconnect(self.schedule_guide_layer_combo_refresh)
        except Exception:
            pass
        try:
            project.layersRemoved.disconnect(self.schedule_guide_layer_combo_refresh)
        except Exception:
            pass

    def selected_guide_source_layer(self):
        layer_id = self.guide_layer_combo.currentData() if hasattr(self, "guide_layer_combo") else ""
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def selected_guide_id_field(self):
        if not hasattr(self, "guide_id_field_combo"):
            return ""
        return self.guide_id_field_combo.currentData() or ""

    def guide_mesh_split_values(self):
        try:
            cols = int(self.guide_mesh_cols_edit.text().strip())
        except Exception:
            cols = 0
        try:
            rows = int(self.guide_mesh_rows_edit.text().strip())
        except Exception:
            rows = 0
        return cols, rows

    def set_guide_width(self, width):
        self.guide_width_edit.setText(str(width))

    def apply_guide_width_preset(self, *args):
        if not hasattr(self, "guide_width_combo"):
            return
        width = self.guide_width_combo.currentData()
        if width:
            self.set_guide_width(width)

    def guide_width_value(self):
        text = self.guide_width_edit.text().strip().replace("ｍ", "").replace("m", "")
        try:
            return float(text)
        except Exception:
            return 0.0

    def create_guide_lines(self):
        self.refresh_guide_layer_combo()
        if not self.inspection_gpkg_path(self.active_inspection_type) or not self.inspection_root_groups(self.active_inspection_type):
            QMessageBox.information(self, tr_text("検査線作成"), tr_text("先に検査を作成してください。"))
            self.set_status(tr_text("検査線作成: 先に検査を作成してください"))
            return
        source_layer = self.selected_guide_source_layer()
        mode = self.guide_mode_combo.currentData() or "area"
        width_m = self.guide_width_value()
        message_item = None
        if source_layer and width_m > 0:
            try:
                message_item = self.iface.messageBar().pushMessage(
                    tr_text("検査線作成中"),
                    tr_text("検査線を作成しています。完了まで操作しないでください。"),
                    level=Qgis.MessageLevel.Warning,
                    duration=0,
                )
            except Exception:
                message_item = None
            QApplication.processEvents()
        try:
            InspectionGuideLineBuilder(self).create(source_layer, mode, width_m)
            self.write_gpkg_management_state()
        finally:
            self.clear_message_bar_item(message_item, "検査線作成中")

    def create_guide_mesh(self):
        self.refresh_guide_id_field_combo()
        if not self.inspection_gpkg_path(self.active_inspection_type) or not self.inspection_root_groups(self.active_inspection_type):
            QMessageBox.information(self, tr_text("検査メッシュ作成"), tr_text("先に検査を作成してください。"))
            self.set_status(tr_text("検査メッシュ作成: 先に検査を作成してください"))
            return
        source_layer = self.selected_guide_source_layer()
        id_field = self.selected_guide_id_field()
        cols, rows = self.guide_mesh_split_values()
        message_item = None
        if source_layer and id_field and cols > 0 and rows > 0:
            try:
                message_item = self.iface.messageBar().pushMessage(
                    tr_text("検査メッシュ作成中"),
                    tr_text("検査メッシュを作成しています。完了まで操作しないでください。"),
                    level=Qgis.MessageLevel.Warning,
                    duration=0,
                )
            except Exception:
                message_item = None
            QApplication.processEvents()
        try:
            InspectionGuideLineBuilder(self).create_mesh(source_layer, id_field, cols, rows)
            self.write_gpkg_management_state()
        finally:
            self.clear_message_bar_item(message_item, "検査メッシュ作成中")

    def _refresh_delete_inspection_type_text(self):
        key = "inspection.btn.type_delete.free" if self.is_free_inspection() else "inspection.btn.type_delete.ortho"
        self.btn_delete_inspection_type.setText(tr(key))

    def set_status(self, text):
        if hasattr(self.main_ui, "_set_status"):
            self.main_ui._set_status(text)
        else:
            QgsMessageLog.logMessage(text, "OrthoManager", Qgis.MessageLevel.Info)

    def clear_message_bar_item(self, message_item=None, title_text=""):
        bar = None
        try:
            bar = self.iface.messageBar()
        except Exception:
            bar = None
        if not bar:
            return
        if message_item is not None:
            try:
                bar.popWidget(message_item)
                return
            except Exception:
                try:
                    if hasattr(message_item, "close"):
                        message_item.close()
                except Exception:
                    pass
        try:
            if hasattr(bar, "clearWidgets"):
                bar.clearWidgets()
                return
        except Exception:
            pass
        if not title_text:
            return
        try:
            for child in bar.findChildren(QWidget):
                try:
                    if title_text in child.text():
                        child.close()
                except Exception:
                    pass
        except Exception:
            pass

    def project_home(self):
        project = QgsProject.instance()
        home = project.homePath()
        if home:
            return home
        path = project.fileName()
        if path:
            return os.path.dirname(path)
        return ""

    def inspection_type_label(self, inspection_type=None):
        return "検査"

    def normalize_file_path(self, path):
        if not path:
            return ""
        try:
            return os.path.normcase(os.path.abspath(os.fspath(path)))
        except Exception:
            return os.path.normcase(str(path))

    def same_file_path(self, left, right):
        return bool(left and right and self.normalize_file_path(left) == self.normalize_file_path(right))

    def layer_source_path(self, layer):
        if not layer:
            return ""
        prop_path = layer.customProperty(INSPECTION_PROP_PREFIX + "gpkg_path", "")
        if prop_path:
            return prop_path
        try:
            uri = layer.dataProvider().dataSourceUri()
            return str(uri).split("|", 1)[0]
        except Exception:
            return ""

    def inspection_gpkg_path(self, inspection_type=None):
        return self.gpkg_path or self.gpkg_paths.get(INSPECTION_TYPE_FREE, "") or self.gpkg_paths.get(INSPECTION_TYPE_ORTHO, "") or ""

    def set_inspection_gpkg_path(self, inspection_type, path):
        path = path or ""
        self.gpkg_path = path
        for key in INSPECTION_TYPES:
            self.gpkg_paths[key] = path

    def sync_active_gpkg_path(self):
        path = self.inspection_gpkg_path()
        self.gpkg_path = path
        for key in INSPECTION_TYPES:
            self.gpkg_paths[key] = path
        return self.gpkg_path

    def default_gpkg_path(self, inspection_type=None):
        home = self.default_inspection_gpkg_dir()
        project = QgsProject.instance()
        base = os.path.splitext(os.path.basename(project.fileName() or ""))[0]
        if not base:
            base = "ortho_project"
        return os.path.join(home, f"{base}_inspection.gpkg")

    def default_inspection_gpkg_dir(self):
        for folder in (
            self.last_inspection_gpkg_dir(),
            self.project_home(),
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.expanduser("~"),
        ):
            folder = str(folder or "").strip()
            if folder and os.path.isdir(folder):
                return folder
        return os.getcwd()

    def last_inspection_gpkg_dir(self):
        try:
            folder = str(QgsSettings().value(INSPECTION_LAST_GPKG_DIR_KEY, "") or "").strip()
        except Exception:
            folder = ""
        return folder if folder and os.path.isdir(folder) else ""

    def remember_inspection_gpkg_dir(self, path):
        folder = path if os.path.isdir(path) else os.path.dirname(path or "")
        if not folder:
            return
        try:
            QgsSettings().setValue(INSPECTION_LAST_GPKG_DIR_KEY, folder)
        except Exception:
            pass

    def unique_gpkg_path_in_folder(self, folder, preferred_name):
        preferred_name = preferred_name or "ortho_project_inspection.gpkg"
        base, ext = os.path.splitext(preferred_name)
        if not ext:
            ext = ".gpkg"
        path = os.path.join(folder, base + ext)
        if not os.path.exists(path):
            return path
        counter = 2
        while True:
            candidate = os.path.join(folder, f"{base}_{counter}{ext}")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def initial_new_gpkg_path(self):
        default_path = self.available_new_gpkg_path()
        remembered = self.last_inspection_gpkg_dir()
        if remembered:
            return self.unique_gpkg_path_in_folder(remembered, os.path.basename(default_path))
        return default_path

    def ensure_gpkg_path(self, inspection_type=None):
        current = self.inspection_gpkg_path()
        if current:
            self.set_inspection_gpkg_path(self.active_inspection_type, current)
            return current
        path, _ = QFileDialog.getSaveFileName(
            self,
            "検査GPKGの保存先",
            self.default_gpkg_path(),
            "GeoPackage (*.gpkg)",
        )
        if not path:
            return ""
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        if not self.prepare_inspection_gpkg_for_type(path, self.active_inspection_type, allow_assign=True):
            return ""
        self.remember_inspection_gpkg_dir(path)
        self.set_inspection_gpkg_path(self.active_inspection_type, path)
        return path

    def inspection_gpkg_type(self, path):
        if not path or not os.path.exists(path):
            return ""
        con = None
        try:
            con = sqlite3.connect(path)
            table_exists = con.execute(
                "select 1 from sqlite_master where type='table' and name=?",
                (INSPECTION_GPKG_META_TABLE,),
            ).fetchone()
            if not table_exists:
                return ""
            row = con.execute(
                "select value from om_metadata where key=?",
                (INSPECTION_GPKG_TYPE_KEY,),
            ).fetchone()
            value = str(row[0] or "") if row else ""
            return value if value in INSPECTION_TYPES else ""
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査GPKG種別読込エラー: {path} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return ""
        finally:
            if con is not None:
                con.close()

    def write_inspection_gpkg_type(self, path, inspection_type):
        if not path or not os.path.exists(path):
            return False
        con = None
        try:
            con = sqlite3.connect(path)
            con.execute("create table if not exists om_metadata (key text primary key, value text)")
            con.execute(
                "insert or replace into om_metadata (key, value) values (?, ?)",
                (INSPECTION_GPKG_TYPE_KEY, "inspection"),
            )
            con.commit()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査GPKG種別保存エラー: {path} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False
        finally:
            if con is not None:
                con.close()

    def schedule_gpkg_management_sync(self, delay_ms=250):
        if self._gpkg_management_sync_blocked:
            return
        if not self.gpkg_path or not os.path.exists(self.gpkg_path):
            return
        if self._gpkg_management_sync_pending:
            return
        self._gpkg_management_sync_pending = True
        QTimer.singleShot(delay_ms, self.flush_gpkg_management_sync)

    def flush_gpkg_management_sync(self):
        self._gpkg_management_sync_pending = False
        if self._gpkg_management_sync_blocked:
            return
        self.write_gpkg_management_state()

    def read_gpkg_management_state(self, path=None):
        path = path or self.gpkg_path
        if not path or not os.path.exists(path):
            return None
        con = None
        try:
            con = sqlite3.connect(path)
            table_exists = con.execute(
                "select 1 from sqlite_master where type='table' and name=?",
                (INSPECTION_GPKG_META_TABLE,),
            ).fetchone()
            if not table_exists:
                return None
            row = con.execute(
                "select value from om_metadata where key=?",
                (INSPECTION_GPKG_STATE_KEY,),
            ).fetchone()
            if not row or not row[0]:
                return None
            state = json.loads(row[0])
            return state if isinstance(state, dict) else None
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査GPKG管理情報読込エラー: {path} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        finally:
            if con is not None:
                con.close()

    def write_gpkg_management_state(self):
        if self._gpkg_management_sync_blocked:
            return False
        path = self.gpkg_path
        if not path or not os.path.exists(path):
            return False
        con = None
        try:
            state = self.inspection_gpkg_management_state()
            con = sqlite3.connect(path)
            con.execute("create table if not exists om_metadata (key text primary key, value text)")
            con.execute(
                "insert or replace into om_metadata (key, value) values (?, ?)",
                (INSPECTION_GPKG_TYPE_KEY, "inspection"),
            )
            con.execute(
                "insert or replace into om_metadata (key, value) values (?, ?)",
                (INSPECTION_GPKG_STATE_KEY, json.dumps(state, ensure_ascii=False, separators=(",", ":"))),
            )
            con.commit()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査GPKG管理情報保存エラー: {path} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False
        finally:
            if con is not None:
                con.close()

    def inspection_gpkg_management_state(self):
        try:
            self.sync_free_layer_groups_from_layer_tree()
        except Exception:
            pass
        seen_ids = set()
        layers = []
        for root_group in self.inspection_root_groups():
            layers.extend(self.layer_descriptors_from_tree(root_group, seen_ids))
        for layer in self.inspection_layers():
            if layer.id() in seen_ids:
                continue
            descriptor = self.layer_descriptor(layer)
            if self.gpkg_path:
                descriptor["gpkg_path"] = self.gpkg_path
            layers.append(descriptor)
            seen_ids.add(layer.id())
        return {
            "schema_version": INSPECTION_GPKG_STATE_VERSION,
            "saved_at": QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate),
            "gpkg_path": self.gpkg_path,
            "last_free_geom_type": self.last_free_geom_type,
            "active_free_group_name": self.active_free_group_name,
            "free_groups": self.free_group_names(),
            "free_root_order": self.free_root_order_state(),
            "layers": layers,
        }

    def layer_descriptors_from_tree(self, group, seen_ids):
        result = []
        try:
            children = list(group.children())
        except Exception:
            return result
        for child in children:
            layer = None
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if layer and isinstance(layer, QgsVectorLayer):
                source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                if source and layer.id() not in seen_ids:
                    descriptor = self.layer_descriptor(layer)
                    if (
                        self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE
                        and descriptor.get("guide_role", "") not in (GUIDE_ROLE_AREA, GUIDE_ROLE_DONE, GUIDE_ROLE_LINE)
                    ):
                        preferred_parent, preferred_group = self.preferred_free_layer_parent_for_save(layer)
                        if preferred_parent is not None and not self.same_layer_tree_group(group, preferred_parent):
                            continue
                        descriptor["group_name"] = preferred_group
                        self.set_layer_group_name(layer, preferred_group)
                    if self.gpkg_path:
                        descriptor["gpkg_path"] = self.gpkg_path
                    result.append(descriptor)
                    seen_ids.add(layer.id())
                continue
            result.extend(self.layer_descriptors_from_tree(child, seen_ids))
        return result

    def load_layers_from_gpkg_management(self, show_warning=False):
        state = self.read_gpkg_management_state()
        if not state:
            if show_warning:
                QMessageBox.warning(
                    self,
                    tr_text("検査GPKG読込"),
                    tr_text("この検査GPKGにはOrthoManagerの管理情報がありません。\n"
                    "v3.71以降で作成した検査GPKGを選択してください。"),
                )
            return False
        layers = state.get("layers", [])
        if not isinstance(layers, list):
            if show_warning:
                QMessageBox.warning(self, tr_text("検査GPKG読込"), tr_text("検査GPKGの管理情報が壊れています。"))
            return False
        saved_free_groups = [
            self.normalize_free_group_path(name)
            for name in state.get("free_groups", [])
            if self.normalize_free_group_path(name)
        ]
        if saved_free_groups and layers and not any(
            self.normalize_free_group_path(descriptor.get("group_name", ""))
            for descriptor in layers
            if isinstance(descriptor, dict)
        ):
            QgsMessageLog.logMessage(
                "INSPECTION_GPKG_GROUP_MEMBERSHIP_MISSING "
                f"path={self.gpkg_path} free_groups={len(saved_free_groups)} layers={len(layers)}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        self._gpkg_management_sync_blocked = True
        try:
            self.last_free_geom_type = state.get("last_free_geom_type", "line") or "line"
            self.active_free_group_name = self.normalize_free_group_path(state.get("active_free_group_name", ""))
            self.free_groups = saved_free_groups
            self.ensure_inspection_root_group()
            for group_name in self.free_group_names():
                self.ensure_free_group(group_name)
            for descriptor in layers:
                if not isinstance(descriptor, dict):
                    continue
                source_name = descriptor.get("source_name", "")
                if not source_name:
                    continue
                descriptor = dict(descriptor)
                descriptor["gpkg_path"] = self.gpkg_path
                self.load_layer(source_name, descriptor)
            self.restore_free_root_order(state.get("free_root_order", []))
            if OGR_OK:
                ds = self.open_inspection_gpkg_readonly(self.gpkg_path)
                if ds:
                    for source_name in TRASH_LAYER_SOURCES.values():
                        if ds.GetLayerByName(source_name):
                            self.load_trash_layer(source_name, visible=False)
                    ds = None
            return True
        finally:
            self._gpkg_management_sync_blocked = False

    def prepare_inspection_gpkg_for_type(self, path, inspection_type, allow_assign=False):
        if not path:
            return False
        driver = ogr.GetDriverByName("GPKG") if OGR_OK else None
        if driver is None:
            return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        ds = self.open_or_create_inspection_gpkg(path, driver)
        if ds is None:
            QMessageBox.critical(self, tr_text("検査GPKG"), tr_text("検査GPKGを開けません。"))
            return False
        ds = None
        self.write_inspection_gpkg_type(path, inspection_type)
        return True

    def choose_new_inspection_gpkg_path(self, inspection_type):
        while True:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "検査GPKGの作成先",
                self.initial_new_gpkg_path(),
                "GeoPackage (*.gpkg)",
            )
            if not path:
                return ""
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            if os.path.exists(path):
                result = QMessageBox.information(
                    self,
                    tr_text("検査作成"),
                    tr_text("既存の検査GPKGは検査作成では使用できません。\n\n"
                    "既存GPKGを使う場合は「検査読込」を使用してください。\n"
                    "新しい検査を始める場合は、別名で新しいGPKGを作成してください。"),
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Ok,
                )
                if result == QMessageBox.StandardButton.Ok:
                    continue
                return ""
            if self.prepare_inspection_gpkg_for_type(path, inspection_type, allow_assign=True):
                self.remember_inspection_gpkg_dir(path)
                return path

    def available_new_gpkg_path(self):
        path = self.default_gpkg_path()
        if not path or not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        if not ext:
            ext = ".gpkg"
        counter = 2
        while True:
            candidate = f"{base}_{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def confirm_create_new_inspection(self):
        if not self.inspection_gpkg_path() and not self.inspection_root_groups():
            return True
        return QMessageBox.question(
            self,
            tr_text("検査作成"),
            tr_text("現在の検査から新しい検査へ切り替えます。\n\n"
            "現在の検査データは元のGPKGに残ります。\n"
            "QGIS上の現在の検査レイヤと検査グループだけを閉じて、"
            "新しい空の検査GPKGを作成します。\n\n"
            "新しい検査を作成しますか？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def remove_inspection_root_groups_from_project(self, inspection_type=None):
        root = QgsProject.instance().layerTreeRoot()
        for group in list(self.inspection_root_groups(inspection_type)):
            try:
                if group.findLayers():
                    continue
                parent = group.parent() or root
                parent.removeChildNode(group)
            except Exception:
                pass

    def project_crs_metric_problem(self):
        try:
            crs = QgsProject.instance().crs()
        except Exception:
            crs = None
        if not crs or not crs.isValid():
            return "プロジェクト座標系が未設定です。"
        try:
            if crs.isGeographic():
                return "プロジェクト座標系が緯度経度座標系です。"
        except Exception:
            pass
        return ""

    def ensure_project_metric_crs_for_inspection(self):
        problem = self.project_crs_metric_problem()
        if not problem:
            return True
        QMessageBox.warning(
            self,
            tr_text("プロジェクト座標系"),
            tr_text(problem
            + "\n\n検査データはプロジェクト座標系で作成されます。"
            + "\n先にQGISのプロジェクト座標系を、平面直角座標系などのメートル単位の座標系に設定してください。"),
        )
        return False

    def set_inspection_type(self, inspection_type):
        inspection_type = INSPECTION_TYPE_FREE
        if self.active_inspection_type == inspection_type:
            self.sync_active_gpkg_path()
            self.refresh_ui()
            return
        self.finish_edit_for_mode_switch()
        self.active_inspection_type = inspection_type
        self.sync_active_gpkg_path()
        self.trash_layer_ids.clear()
        self.active_layer_id = ""
        self.refresh_ui()
        self.set_status(tr_text("検査"))

    def set_inspection_type_from_tab(self, index):
        self.set_inspection_type(INSPECTION_TYPE_FREE)

    def is_free_inspection(self):
        return True

    def active_inspection_label(self):
        return self.inspection_type_label()

    def create_new_inspection(self):
        if not self.ensure_project_metric_crs_for_inspection():
            return
        if not self.confirm_create_new_inspection():
            return
        inspection_type = self.active_inspection_type
        path = self.choose_new_inspection_gpkg_path(inspection_type)
        if not path:
            return
        self.move_unmanaged_layers_out_of_inspection_group()
        self.clear_inspection_type_state(inspection_type, remove_layers=True, clear_path=False)
        self.remove_inspection_root_groups_from_project(inspection_type)
        self.set_inspection_gpkg_path(inspection_type, path)
        self.ensure_inspection_root_group()
        self.organize_inspection_layers(silent=True)
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(tr_text("✅ 検査を作成しました"))

    def load_inspection_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "検査GPKGを読み込み", "", "GeoPackage (*.gpkg)")
        if not path:
            return
        inspection_type = self.active_inspection_type
        if not self.prepare_inspection_gpkg_for_type(path, inspection_type, allow_assign=True):
            return
        self.clear_inspection_type_state(inspection_type, remove_layers=True, clear_path=False)
        self.set_inspection_gpkg_path(inspection_type, path)
        self.load_layers_from_gpkg()
        self.refresh_ui()
        self.set_status(tr_text("✅ 検査GPKGを読み込みました"))

    def create_inspection_module(self):
        round_no = self.selected_module_round_no()
        if not round_no:
            QMessageBox.information(self, tr_text("検査グループ作成"), tr_text("作成する検査グループを選択してください。"))
            return
        self.add_round(round_no)

    def add_round(self, round_no):
        if not OGR_OK:
            QMessageBox.critical(self, tr_text("GDAL/OGRエラー"), tr_text("GDAL/OGRを読み込めないため検査レイヤを作成できません。"))
            return
        if not self.ensure_project_metric_crs_for_inspection():
            return
        if not self.inspection_gpkg_path() or not self.inspection_root_groups():
            QMessageBox.information(self, tr_text("検査グループ作成"), tr_text("先に検査を作成してください。"))
            self.set_status(tr_text("検査グループ作成: 先に検査を作成してください"))
            return
        if round_no in self.standard_rounds():
            QMessageBox.information(self, tr_text("検査グループ作成"), tr_text(f"{self.round_title(round_no)}は既に作成されています。"))
            return
        path = self.ensure_gpkg_path()
        if not path:
            return
        for code, name, color in ROUND_ITEMS.get(round_no, []):
            source = self.create_inspection_layer(round_no, code, name, color, "polygon", custom=False, inspection_type=INSPECTION_TYPE_ORTHO)
            descriptor = {
                "round_no": round_no,
                "code": code,
                "name": name,
                "color": color,
                "geom_type": "polygon",
                "stroke_width": self.default_stroke_width("polygon"),
                "point_size": self.default_point_size(),
                "source_name": source,
                "inspection_type": INSPECTION_TYPE_ORTHO,
                "group_name": "",
                "custom": False,
                "gpkg_path": path,
            }
            self.load_layer(source, descriptor)
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ 検査グループ作成: {self.round_title(round_no)}"))

    def add_manual_layer(self, insert_above_source=None, free_group_name=None):
        if not isinstance(insert_above_source, str):
            insert_above_source = None
        if not self.ensure_project_metric_crs_for_inspection():
            return
        if not self.ensure_gpkg_path():
            return
        target_layer = self.layer_by_source(insert_above_source) if insert_above_source else None
        round_no = 0
        group_name = ""
        inspection_type = self.active_inspection_type
        if target_layer:
            inspection_type = self.layer_inspection_type(target_layer)
            round_no = int(target_layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0) if inspection_type == INSPECTION_TYPE_ORTHO else 0
            group_name = target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") if inspection_type == INSPECTION_TYPE_FREE else ""
        elif free_group_name is not None and self.is_free_inspection():
            inspection_type = INSPECTION_TYPE_FREE
            group_name = str(free_group_name or "").strip()
        elif inspection_type == INSPECTION_TYPE_FREE:
            active_group = str(self.active_free_group_name or "").strip()
            group_name = active_group if active_group in self.free_group_names() else ""
        name, ok = QInputDialog.getText(self, tr_text("検査レイヤ追加"), tr_text("レイヤ名:"))
        if not ok or not name.strip():
            return
        geom_items = ["ポリゴン", "ライン", "点"]
        default_geom_index = 0
        if inspection_type == INSPECTION_TYPE_FREE:
            default_geom_index = {"polygon": 0, "line": 1, "point": 2}.get(self.last_free_geom_type, 1)
        geom, ok = QInputDialog.getItem(self, tr_text("形状選択"), tr_text("形状:"), geom_items, default_geom_index, False)
        if not ok:
            return
        color = QColorDialog.getColor(QColor("#ff0000"), self, "表示色")
        if not color.isValid():
            return
        color_text = color.name().replace("#", "")
        geom_type = {"ポリゴン": "polygon", "ライン": "line", "点": "point"}.get(geom, "polygon")
        if inspection_type == INSPECTION_TYPE_FREE:
            self.last_free_geom_type = geom_type
        layer_name = name.strip()
        source = self.create_inspection_layer(round_no, "", layer_name, color_text, geom_type, custom=True, inspection_type=inspection_type)
        descriptor = {
            "round_no": round_no,
            "code": "",
            "name": layer_name,
            "color": color_text,
            "geom_type": geom_type,
            "stroke_width": self.default_stroke_width(geom_type),
            "point_size": self.default_point_size(),
            "source_name": source,
            "inspection_type": inspection_type,
            "group_name": group_name,
            "custom": True,
            "gpkg_path": self.inspection_gpkg_path(inspection_type),
        }
        QgsMessageLog.logMessage(
            f"INSPECTION_ADD_MANUAL_LAYER inspection_type={inspection_type} group={group_name} source={source}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        layer = self.load_layer(source, descriptor)
        if layer:
            self.active_layer_id = layer.id()
            if inspection_type == INSPECTION_TYPE_FREE:
                self.active_free_group_name = group_name
            if target_layer:
                self.place_layer_before(layer, target_layer)
        self.write_gpkg_management_state()
        self.refresh_ui()

    def import_qgis_project_layers(self, insert_above_source=None):
        self.log_import_code_marker("QGIS_LAYER_IMPORT")
        if not isinstance(insert_above_source, str):
            insert_above_source = None
        if not OGR_OK:
            QMessageBox.critical(self, tr_text("QGISレイヤ取込"), tr_text("GDAL/OGRを読み込めないためQGISレイヤを取り込めません。"))
            return
        if not self.ensure_project_metric_crs_for_inspection():
            return
        if not self.ensure_gpkg_path():
            return

        candidates = self.qgis_layer_import_candidates()
        if not candidates:
            QMessageBox.information(self, tr_text("QGISレイヤ取込"), tr_text("取り込めるQGISベクタレイヤがありません。"))
            return
        dialog = QgisLayerImportDialog(candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_ids = set(dialog.selected_layer_ids())
        source_layers = [layer for layer in candidates if layer.id() in selected_ids]
        if not source_layers:
            QMessageBox.information(self, tr_text("QGISレイヤ取込"), tr_text("取り込むレイヤを選択してください。"))
            return

        target_layer = self.layer_by_source(insert_above_source) if insert_above_source else self.active_layer()
        inspection_type = self.active_inspection_type
        fallback_group_name = ""
        if target_layer and self.layer_inspection_type(target_layer) == INSPECTION_TYPE_FREE:
            fallback_group_name = target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")

        try:
            descriptors, source_by_name, feature_count, skipped_count, errors = self._import_qgis_layers_to_gpkg(
                source_layers, inspection_type, fallback_group_name
            )
        except Exception as exc:
            QMessageBox.critical(self, tr_text("QGISレイヤ取込"), tr_text(f"QGISレイヤを取り込めませんでした。\n{exc}"))
            QgsMessageLog.logMessage(f"INSPECTION_QGIS_LAYER_IMPORT_FAILED error={exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return

        created_layers = []
        for descriptor in descriptors:
            layer = self.load_layer(descriptor.get("source_name", ""), descriptor)
            if layer:
                src_layer = source_by_name.get(descriptor.get("source_name", ""))
                if src_layer:
                    self.copy_qgis_layer_style(src_layer, layer)
                created_layers.append(layer)
        for layer in created_layers:
            self.move_layer_node_to_inspection_group(layer)
            QgsMessageLog.logMessage(
                f"INSPECTION_QGIS_LAYER_IMPORT_PLACED layer={self.display_layer_name(layer)} "
                f"group={layer.customProperty(INSPECTION_PROP_PREFIX + 'group_name', '')}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        if created_layers:
            self.active_layer_id = created_layers[0].id()
        self.write_gpkg_management_state()
        self.refresh_ui()

        message = f"✅ QGISレイヤ取込: {len(created_layers)} レイヤ / {feature_count} 地物"
        if skipped_count:
            message += f" / 未対応 {skipped_count}"
        self.set_status(message)
        if errors:
            preview = "\n".join(errors[:8])
            if len(errors) > 8:
                preview += f"\n...ほか {len(errors) - 8} 件"
            QMessageBox.warning(self, tr_text("QGISレイヤ取込"), tr_text(f"一部取り込めませんでした。\n{preview}"))

        if created_layers:
            box = QMessageBox(self)
            box.setWindowTitle(tr_text("QGISレイヤ取込"))
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(tr_text("取り込み前のQGISレイヤをレイヤパネルから外しますか？"))
            box.setInformativeText("元ファイル自体は削除しません。")
            remove_button = box.addButton("元レイヤを外す", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("そのまま残す", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(remove_button)
            box.exec()
            if box.clickedButton() == remove_button:
                source_groups = self.source_layer_parent_groups(source_layers)
                for source_layer in source_layers:
                    try:
                        QgsProject.instance().removeMapLayer(source_layer.id())
                    except Exception as exc:
                        QgsMessageLog.logMessage(f"QGIS取込元レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                self.remove_empty_source_groups(source_groups)

    def qgis_layer_import_candidates(self):
        result = []
        seen = set()
        try:
            nodes = QgsProject.instance().layerTreeRoot().findLayers()
        except Exception:
            nodes = []
        for node in nodes:
            try:
                layer = node.layer()
            except Exception:
                layer = None
            if self.is_qgis_layer_import_candidate(layer) and layer.id() not in seen:
                result.append(layer)
                seen.add(layer.id())
        if not result:
            for layer in QgsProject.instance().mapLayers().values():
                if self.is_qgis_layer_import_candidate(layer) and layer.id() not in seen:
                    result.append(layer)
                    seen.add(layer.id())
        return result

    def is_qgis_layer_import_candidate(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        if layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""):
            return False
        if self.is_vrt_overlay_layer(layer):
            return False
        return self.qgis_layer_geom_type(layer) in GEOM_TYPE_LABELS

    def is_vrt_overlay_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        name = layer.name()
        try:
            registry = getattr(self.main_ui, "vrt_registry", {}) or {}
            overlay_names = set()
            for vrt_name in registry.keys():
                if hasattr(self.main_ui, "overlay_layer_name"):
                    overlay_names.add(self.main_ui.overlay_layer_name(vrt_name))
            if name in overlay_names:
                return True
        except Exception:
            pass
        try:
            source = layer.source().lower()
        except Exception:
            source = ""
        return name.endswith("_overlay") and "_tiles.gpkg" in source

    def qgis_layer_geom_type(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return ""
        if layer.geometryType() == Qgis.GeometryType.Polygon:
            return "polygon"
        if layer.geometryType() == Qgis.GeometryType.Line:
            return "line"
        if layer.geometryType() == Qgis.GeometryType.Point:
            return "point"
        return ""

    def log_import_code_marker(self, action):
        try:
            mtime = os.path.getmtime(__file__)
        except Exception:
            mtime = 0
        QgsMessageLog.logMessage(
            f"INSPECTION_IMPORT_CODE_MARKER action={action} marker=fix5 file={__file__} mtime={mtime}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

    def source_layer_parent_groups(self, layers):
        groups = []
        for layer in layers or []:
            try:
                nodes = self.layer_tree_nodes_for_layer(layer.id())
            except Exception:
                nodes = []
            for parent, _node in nodes:
                if parent and parent not in groups and self.is_external_source_group(parent):
                    groups.append(parent)
        return groups

    def is_external_source_group(self, group):
        try:
            name = str(group.name() or "").strip()
            if not name:
                return False
            if name in (INSPECTION_GROUP, FREE_INSPECTION_GROUP):
                return False
            return group.parent() is not None
        except Exception:
            return False

    def qgis_layer_source_group_name(self, layer):
        try:
            nodes = self.layer_tree_nodes_for_layer(layer.id())
        except Exception:
            nodes = []
        for parent, _node in nodes:
            if self.is_external_source_group(parent):
                return str(parent.name() or "").strip()
        return ""

    def remove_empty_source_groups(self, groups):
        for group in list(groups or []):
            current = group
            while current and self.is_external_source_group(current):
                try:
                    parent = current.parent()
                    if parent is None or current.children():
                        break
                    parent.removeChildNode(current)
                    current = parent
                except Exception as exc:
                    QgsMessageLog.logMessage(f"QGIS取込元グループ整理エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    break

    def is_empty_inspection_gpkg_file(self, path):
        if not path or not os.path.exists(path):
            return False
        con = None
        try:
            con = sqlite3.connect(path)
            table_names = {
                str(row[0])
                for row in con.execute("select name from sqlite_master where type='table'").fetchall()
            }
            if "gpkg_contents" not in table_names:
                return False
            contents_count = con.execute("select count(*) from gpkg_contents").fetchone()[0]
            user_tables = [
                name for name in table_names
                if not name.startswith("sqlite_")
                and not name.startswith("gpkg_")
                and not name.startswith("rtree_")
            ]
            return contents_count == 0 and not user_tables
        except Exception:
            return False
        finally:
            if con is not None:
                con.close()

    def backup_empty_unreadable_gpkg(self, path):
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        backup_path = f"{path}.empty_unreadable_{timestamp}.bak"
        number = 2
        while os.path.exists(backup_path):
            backup_path = f"{path}.empty_unreadable_{timestamp}_{number}.bak"
            number += 1
        os.replace(path, backup_path)
        return backup_path

    def open_inspection_gpkg_readonly(self, path):
        try:
            ds = ogr.Open(path, 0)
        except Exception as exc:
            if self.is_empty_inspection_gpkg_file(path):
                QgsMessageLog.logMessage(
                    f"空の検査GPKGのため読込をスキップします: {path}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                return None
            QgsMessageLog.logMessage(f"検査GPKG読込エラー: {path} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        if ds is None:
            if self.is_empty_inspection_gpkg_file(path):
                QgsMessageLog.logMessage(
                    f"空の検査GPKGのため読込をスキップします: {path}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            else:
                QgsMessageLog.logMessage(f"検査GPKGを開けません: {path}", "OrthoManager", Qgis.MessageLevel.Warning)
        return ds

    def open_or_create_inspection_gpkg(self, path, driver):
        if os.path.exists(path):
            open_error = None
            try:
                ds = ogr.Open(path, 1)
            except Exception as exc:
                ds = None
                open_error = exc
            if ds is not None:
                return ds
            if self.is_empty_inspection_gpkg_file(path):
                backup_path = self.backup_empty_unreadable_gpkg(path)
                QgsMessageLog.logMessage(
                    f"空の検査GPKGを退避して作り直します: {backup_path}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                return driver.CreateDataSource(path)
            if open_error is not None:
                raise RuntimeError(f"検査GPKGを開けません: {path} / {open_error}")
            raise RuntimeError(f"検査GPKGを開けません: {path}")
        return driver.CreateDataSource(path)

    def _import_qgis_layers_to_gpkg(self, source_layers, inspection_type, fallback_group_name):
        driver = ogr.GetDriverByName("GPKG")
        gpkg_path = self.ensure_gpkg_path(inspection_type)
        target_ds = self.open_or_create_inspection_gpkg(gpkg_path, driver)
        if target_ds is None:
            raise RuntimeError(f"検査GPKGを開けません: {gpkg_path}")
        descriptors = []
        source_by_name = {}
        feature_count = 0
        skipped_count = 0
        errors = []
        try:
            for src_layer in source_layers:
                try:
                    group_name = fallback_group_name
                    source_group_name = self.qgis_layer_source_group_name(src_layer)
                    if source_group_name:
                        group_name = source_group_name
                    descriptor, written, skipped, layer_errors = self._import_single_qgis_layer_to_gpkg(
                        target_ds, src_layer, inspection_type, group_name
                    )
                    descriptors.append(descriptor)
                    source_by_name[descriptor.get("source_name", "")] = src_layer
                    feature_count += written
                    skipped_count += skipped
                    errors.extend(layer_errors)
                except Exception as exc:
                    skipped_count += max(0, src_layer.featureCount())
                    errors.append(f"{src_layer.name()}: {exc}")
        finally:
            target_ds = None
        QgsMessageLog.logMessage(
            f"INSPECTION_QGIS_LAYER_IMPORT layers={len(descriptors)} features={feature_count} skipped={skipped_count}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return descriptors, source_by_name, feature_count, skipped_count, errors

    def _import_single_qgis_layer_to_gpkg(self, target_ds, src_layer, inspection_type, group_name, prefer_attribute_color=False):
        geom_type = self.qgis_layer_geom_type(src_layer)
        if geom_type not in GEOM_TYPE_LABELS:
            raise RuntimeError("ポリゴン/ライン/点以外のレイヤです")
        field_map = self._qgis_source_field_map(src_layer)
        display_name = _safe_layer_name(src_layer.name())
        prefix = "inspection" if inspection_type == INSPECTION_TYPE_FREE else "manual"
        source_base = f"{prefix}_{geom_type}_{display_name}"
        source_name = self.unique_source_layer_name(source_base, target_ds)
        color_text = self.qgis_layer_color(src_layer, prefer_attribute=prefer_attribute_color)
        stroke_width, point_size = self.qgis_layer_size_values(src_layer, geom_type)
        self.create_inspection_layer(
            0, "", display_name, color_text, geom_type, custom=True,
            inspection_type=inspection_type, extra_fields=field_map,
            source_name_override=source_name, multi_geometry=True, dataset=target_ds,
        )
        target_layer = target_ds.GetLayerByName(source_name)
        if target_layer is None:
            raise RuntimeError(f"取込先レイヤを作成できません: {display_name}")
        descriptor = {
            "round_no": 0,
            "code": "",
            "name": display_name,
            "color": color_text,
            "geom_type": geom_type,
            "stroke_width": stroke_width,
            "point_size": point_size,
            "source_name": source_name,
            "inspection_type": inspection_type,
            "group_name": group_name,
            "custom": True,
            "imported": True,
            "preserve_style": True,
        }
        target_info = {
            "layer": target_layer,
            "defn": target_layer.GetLayerDefn(),
            "descriptor": descriptor,
            "field_map": field_map,
        }
        transform = self.qgis_layer_coordinate_transform(src_layer)
        written = 0
        skipped = 0
        errors = []
        total = max(0, src_layer.featureCount())
        started = time.perf_counter()
        transaction_started = self._begin_ogr_layer_transaction(target_layer)
        QgsMessageLog.logMessage(
            f"INSPECTION_IMPORT_BULK_START layer={display_name} features={total} transaction={transaction_started}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        try:
            for feature in src_layer.getFeatures():
                try:
                    geom = feature.geometry()
                    if not geom or geom.isEmpty():
                        skipped += 1
                        continue
                    geom = QgsGeometry(geom)
                    if transform is not None:
                        geom.transform(transform)
                    if self._write_qgis_import_feature(target_info, feature, geom, geom_type):
                        written += 1
                    else:
                        skipped += 1
                    if written and written % 5000 == 0:
                        QgsMessageLog.logMessage(
                            f"INSPECTION_IMPORT_BULK_PROGRESS layer={display_name} written={written} skipped={skipped} total={total}",
                            "OrthoManager",
                            Qgis.MessageLevel.Info,
                        )
                except Exception as exc:
                    skipped += 1
                    errors.append(f"{src_layer.name()} / {geom_type}: {exc}")
            if transaction_started:
                self._commit_ogr_layer_transaction(target_layer)
        except Exception:
            if transaction_started:
                self._rollback_ogr_layer_transaction(target_layer)
            raise
        elapsed = time.perf_counter() - started
        QgsMessageLog.logMessage(
            f"INSPECTION_IMPORT_BULK_DONE layer={display_name} written={written} skipped={skipped} sec={elapsed:.2f}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return descriptor, written, skipped, errors

    def import_vector_layers(self, insert_above_source=None):
        self.log_import_code_marker("VECTOR_IMPORT")
        if not isinstance(insert_above_source, str):
            insert_above_source = None
        if not OGR_OK:
            QMessageBox.critical(self, tr_text("ベクタ取込"), tr_text("GDAL/OGRを読み込めないためDXF/SHPを取り込めません。"))
            return
        if not self.ensure_project_metric_crs_for_inspection():
            return
        if not self.ensure_gpkg_path():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "DXF/SHPを検査グループに読み込み",
            self.project_home(),
            "ベクタファイル (*.dxf *.shp);;DXF (*.dxf);;Shapefile (*.shp)",
        )
        paths = [path for path in (self._as_file_path(path) for path in paths) if os.path.splitext(path)[1].lower() in (".dxf", ".shp")]
        if not paths:
            return

        target_layer = self.layer_by_source(insert_above_source) if insert_above_source else None
        inspection_type = self.active_inspection_type
        round_no = 0
        inherited_group = ""
        if target_layer:
            inspection_type = self.layer_inspection_type(target_layer)
            round_no = int(target_layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0) if inspection_type == INSPECTION_TYPE_ORTHO else 0
            inherited_group = target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")

        dialog = VectorImportOptionsDialog(paths, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.options()
        group_name = options.get("group_name", "") if options.get("use_group") else inherited_group
        if options.get("use_group") and not group_name:
            QMessageBox.information(self, tr_text("ベクタ取込"), tr_text("グループ名を入力してください。"))
            return

        try:
            descriptors, feature_count, skipped_count, errors = self._import_vector_files(
                paths, inspection_type, round_no, group_name
            )
        except Exception as exc:
            QMessageBox.critical(self, tr_text("ベクタ取込"), tr_text(f"DXF/SHPを取り込めませんでした。\n{exc}"))
            QgsMessageLog.logMessage(f"INSPECTION_VECTOR_IMPORT_FAILED error={exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return

        created_layers = []
        for descriptor in descriptors:
            layer = self.load_layer(descriptor.get("source_name", ""), descriptor)
            if layer:
                created_layers.append(layer)
        for layer in created_layers:
            self.move_layer_node_to_inspection_group(layer)
            QgsMessageLog.logMessage(
                f"INSPECTION_VECTOR_IMPORT_PLACED layer={self.display_layer_name(layer)} "
                f"group={layer.customProperty(INSPECTION_PROP_PREFIX + 'group_name', '')}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        if target_layer and created_layers and not group_name:
            for layer in reversed(created_layers):
                self.place_layer_before(layer, target_layer)
        if created_layers:
            self.active_layer_id = created_layers[0].id()
        self.refresh_ui()
        message = f"✅ ベクタ取込: {len(created_layers)} レイヤ / {feature_count} 地物"
        if skipped_count:
            message += f" / 未対応 {skipped_count}"
        self.set_status(message)
        if errors:
            for error in errors[:30]:
                QgsMessageLog.logMessage(f"INSPECTION_VECTOR_IMPORT_DETAIL {error}", "OrthoManager", Qgis.MessageLevel.Warning)
            preview = "\n".join(errors[:8])
            if len(errors) > 8:
                preview += f"\n...ほか {len(errors) - 8} 件"
            QMessageBox.warning(self, tr_text("ベクタ取込"), tr_text(f"一部取り込めませんでした。\n{preview}"))

    def _as_file_path(self, value):
        try:
            if hasattr(value, "toLocalFile"):
                value = value.toLocalFile()
        except Exception:
            pass
        try:
            return os.fspath(value)
        except Exception:
            return str(value)

    def _import_vector_files(self, paths, inspection_type, round_no, group_name):
        driver = ogr.GetDriverByName("GPKG")
        gpkg_path = self.ensure_gpkg_path(inspection_type)
        target_ds = self.open_or_create_inspection_gpkg(gpkg_path, driver)
        if target_ds is None:
            raise RuntimeError(f"検査GPKGを開けません: {gpkg_path}")
        target_cache = {}
        descriptors = []
        feature_count = 0
        skipped_count = 0
        errors = []
        try:
            for raw_path in paths:
                path = self._as_file_path(raw_path)
                is_dxf = os.path.splitext(path)[1].lower() == ".dxf"
                if not is_dxf:
                    descriptor, written, skipped, layer_errors = self._import_shp_with_qgis_layer(
                        target_ds, path, inspection_type, group_name
                    )
                    if descriptor:
                        descriptors.append(descriptor)
                    feature_count += written
                    skipped_count += skipped
                    errors.extend(layer_errors)
                    continue
                src_ds = ogr.Open(path, 0)
                if src_ds is None:
                    errors.append(f"{os.path.basename(path)}: 開けません")
                    continue
                crs_cache = {}
                for layer_index in range(src_ds.GetLayerCount()):
                    src_layer = src_ds.GetLayerByIndex(layer_index)
                    if src_layer is None:
                        continue
                    field_map = self._import_source_field_map(src_layer.GetLayerDefn())
                    transform = self._import_coordinate_transform(src_layer, path, crs_cache)
                    src_layer.ResetReading()
                    for src_feature in src_layer:
                        geom = src_feature.GetGeometryRef()
                        if geom is None or geom.IsEmpty():
                            skipped_count += 1
                            continue
                        parts = self._import_geometry_parts(geom)
                        if not parts:
                            skipped_count += 1
                            errors.append(
                                f"{os.path.basename(path)} / {src_layer.GetName()} / "
                                f"未対応形状: raw={geom.GetGeometryType()} flat={self._ogr_flatten_type(geom.GetGeometryType())} "
                                f"name={geom.GetGeometryName()}"
                            )
                            continue
                        for geom_type, part_geom in parts:
                            try:
                                part_geom = part_geom.Clone()
                                if transform is not None:
                                    part_geom.Transform(transform)
                                target_info = self._import_target_info(
                                    target_cache, descriptors, target_ds, path, src_layer,
                                    src_feature, field_map, geom_type, is_dxf,
                                    inspection_type, round_no, group_name,
                                )
                                if self._write_import_feature(target_info, src_feature, part_geom, geom_type):
                                    feature_count += 1
                                else:
                                    skipped_count += 1
                            except Exception as exc:
                                skipped_count += 1
                                errors.append(f"{os.path.basename(path)} / {src_layer.GetName()} / {geom_type}: {exc}")
                src_ds = None
        finally:
            target_ds = None
        QgsMessageLog.logMessage(
            f"INSPECTION_VECTOR_IMPORT layers={len(descriptors)} features={feature_count} skipped={skipped_count}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return descriptors, feature_count, skipped_count, errors

    def _import_shp_with_qgis_layer(self, target_ds, path, inspection_type, group_name):
        layer_name = os.path.splitext(os.path.basename(path))[0]
        src_layer = QgsVectorLayer(path, layer_name, "ogr")
        if not src_layer.isValid():
            return None, 0, 0, [f"{os.path.basename(path)}: QGISレイヤとして開けません"]
        self.ensure_qgis_layer_crs(src_layer, path)
        descriptor, written, skipped, layer_errors = self._import_single_qgis_layer_to_gpkg(
            target_ds, src_layer, inspection_type, group_name, prefer_attribute_color=True
        )
        if skipped or layer_errors:
            QgsMessageLog.logMessage(
                f"INSPECTION_VECTOR_IMPORT_SHP_QGIS file={os.path.basename(path)} features={written} skipped={skipped}",
                "OrthoManager",
                Qgis.MessageLevel.Warning if skipped else Qgis.MessageLevel.Info,
            )
        return descriptor, written, skipped, layer_errors

    def ensure_qgis_layer_crs(self, layer, path):
        try:
            crs = layer.crs()
            if crs and crs.isValid():
                return
        except Exception:
            pass
        if QgsProjectionSelectionDialog is None:
            return
        try:
            dialog = QgsProjectionSelectionDialog(self)
            dialog.setWindowTitle(tr_text("取込ファイルの座標系"))
            project_crs = QgsProject.instance().crs()
            if project_crs and project_crs.isValid():
                try:
                    dialog.setCrs(project_crs)
                except Exception:
                    pass
            if dialog.exec() != QDialog.DialogCode.Accepted:
                raise RuntimeError(f"座標系が未設定です: {os.path.basename(path)}")
            selected_crs = dialog.crs()
            if selected_crs and selected_crs.isValid():
                layer.setCrs(selected_crs)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"座標系選択に失敗しました: {os.path.basename(path)} / {exc}")

    def _import_target_info(
        self, cache, descriptors, target_ds, path, src_layer, src_feature, field_map,
        geom_type, is_dxf, inspection_type, round_no, group_name,
    ):
        display_name = self._import_display_name(path, src_layer, src_feature, geom_type, is_dxf)
        key = (os.path.normcase(path), src_layer.GetName(), display_name, geom_type)
        if key in cache:
            return cache[key]
        prefix = "inspection" if inspection_type == INSPECTION_TYPE_FREE else "manual"
        source_base = f"{prefix}_{geom_type}_{display_name}"
        source_name = self.unique_source_layer_name(source_base, target_ds)
        color_text = self._import_feature_color(src_feature)
        self.create_inspection_layer(
            round_no, "", display_name, color_text, geom_type, custom=True,
            inspection_type=inspection_type, extra_fields=field_map,
            source_name_override=source_name, multi_geometry=True, dataset=target_ds,
        )
        target_layer = target_ds.GetLayerByName(source_name)
        if target_layer is None:
            raise RuntimeError(f"取込先レイヤを作成できません: {display_name}")
        descriptor = {
            "round_no": round_no,
            "code": "",
            "name": display_name,
            "color": color_text,
            "geom_type": geom_type,
            "stroke_width": self.default_stroke_width(geom_type),
            "point_size": self.default_point_size(),
            "source_name": source_name,
            "inspection_type": inspection_type,
            "group_name": group_name,
            "custom": True,
            "imported": True,
        }
        descriptors.append(descriptor)
        info = {"layer": target_layer, "defn": target_layer.GetLayerDefn(), "descriptor": descriptor, "field_map": field_map}
        cache[key] = info
        return info

    def _write_import_feature(self, target_info, src_feature, geom, geom_type):
        target_layer = target_info["layer"]
        defn = target_info["defn"]
        descriptor = target_info["descriptor"]
        out = ogr.Feature(defn)
        out.SetGeometry(self._coerce_import_geometry(geom, geom_type))
        now = self.now_text()
        values = {
            "memo": self._import_feature_memo(src_feature),
            "round_no": descriptor.get("round_no", 0),
            "item_code": descriptor.get("code", ""),
            "item_name": descriptor.get("name", ""),
            "geom_type": descriptor.get("geom_type", geom_type),
            "created_at": now,
            "updated_at": now,
        }
        for name, value in values.items():
            self._set_ogr_field(out, defn, name, value)
        for item in target_info["field_map"]:
            try:
                value = src_feature.GetField(item["src_index"])
            except Exception:
                value = None
            if value is not None:
                self._set_ogr_field(out, defn, item["dst_name"], value)
        self.create_ogr_feature(target_layer, out)
        out = None
        return True

    def _write_qgis_import_feature(self, target_info, src_feature, geom, geom_type):
        target_layer = target_info["layer"]
        defn = target_info["defn"]
        descriptor = target_info["descriptor"]
        ogr_geom = self._qgis_geometry_to_ogr(geom)
        if ogr_geom is None:
            raise RuntimeError("ジオメトリを変換できません")
        out = ogr.Feature(defn)
        out.SetGeometry(self._coerce_import_geometry(ogr_geom, geom_type))
        now = self.now_text()
        values = {
            "memo": self._qgis_feature_memo(src_feature),
            "round_no": descriptor.get("round_no", 0),
            "item_code": descriptor.get("code", ""),
            "item_name": descriptor.get("name", ""),
            "geom_type": descriptor.get("geom_type", geom_type),
            "created_at": now,
            "updated_at": now,
        }
        for name, value in values.items():
            self._set_ogr_field(out, defn, name, value)
        for item in target_info["field_map"]:
            try:
                value = src_feature.attribute(item["src_index"])
            except Exception:
                value = None
            if value is not None:
                self._set_ogr_field(out, defn, item["dst_name"], value)
        self.create_ogr_feature(target_layer, out)
        out = None
        return True

    def _qgis_geometry_to_ogr(self, geom):
        try:
            ogr_geom = ogr.CreateGeometryFromWkb(bytes(geom.asWkb()))
            if ogr_geom is not None:
                return ogr_geom
        except Exception:
            pass
        try:
            return ogr.CreateGeometryFromWkt(geom.asWkt())
        except Exception:
            return None

    def _begin_ogr_layer_transaction(self, layer):
        try:
            return layer.StartTransaction() == 0
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"INSPECTION_IMPORT_TRANSACTION_START_SKIPPED layer={layer.GetName()} error={exc}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return False

    def _commit_ogr_layer_transaction(self, layer):
        try:
            result = layer.CommitTransaction()
        except Exception as exc:
            raise RuntimeError(f"GPKG一括保存に失敗しました: {layer.GetName()} / {exc}")
        if result != 0:
            raise RuntimeError(f"GPKG一括保存に失敗しました: {layer.GetName()} / result={result}")

    def _rollback_ogr_layer_transaction(self, layer):
        try:
            layer.RollbackTransaction()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"INSPECTION_IMPORT_TRANSACTION_ROLLBACK_FAILED layer={layer.GetName()} error={exc}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def create_ogr_feature(self, target_layer, feature):
        try:
            result = target_layer.CreateFeature(feature)
        except Exception as exc:
            raise RuntimeError(str(exc))
        if result != 0:
            error = ""
            try:
                error = gdal.GetLastErrorMsg()
            except Exception:
                error = ""
            raise RuntimeError(error or f"CreateFeature result={result}")

    def _import_display_name(self, path, src_layer, src_feature, geom_type, is_dxf):
        file_base = os.path.splitext(os.path.basename(path))[0]
        geom_label = GEOM_TYPE_LABELS.get(geom_type, geom_type)
        if is_dxf:
            cad_layer = self._import_feature_layer_name(src_feature, "")
            base = cad_layer or src_layer.GetName() or file_base
            return _safe_layer_name(f"{base}（{geom_label}）")
        src_name = src_layer.GetName() or file_base
        base = file_base if src_name == file_base else f"{file_base}_{src_name}"
        return _safe_layer_name(f"{base}（{geom_label}）")

    def _import_source_field_map(self, src_defn):
        reserved = self.import_reserved_field_names()
        used = set(reserved)
        result = []
        for idx in range(src_defn.GetFieldCount()):
            src_fd = src_defn.GetFieldDefn(idx)
            src_name = src_fd.GetName()
            dst_name = self._unique_import_field_name(src_name, used)
            used.add(dst_name.lower())
            fd = ogr.FieldDefn(dst_name, src_fd.GetType())
            try:
                width = src_fd.GetWidth()
                if width:
                    fd.SetWidth(min(width, 254) if src_fd.GetType() == ogr.OFTString else width)
                precision = src_fd.GetPrecision()
                if precision:
                    fd.SetPrecision(precision)
            except Exception:
                pass
            result.append({"src_index": idx, "src_name": src_name, "dst_name": dst_name, "field_defn": fd})
        return result

    def _qgis_source_field_map(self, layer):
        reserved = self.import_reserved_field_names()
        used = set(reserved)
        result = []
        for idx, src_field in enumerate(layer.fields()):
            src_name = src_field.name()
            dst_name = self._unique_import_field_name(src_name, used)
            used.add(dst_name.lower())
            fd = ogr.FieldDefn(dst_name, ogr.OFTString)
            fd.SetWidth(254)
            result.append({"src_index": idx, "src_name": src_name, "dst_name": dst_name, "field_defn": fd})
        return result

    def import_reserved_field_names(self):
        return {
            "fid", "ogc_fid", "id",
            "geom", "geometry", "the_geom",
            "memo", "round_no", "item_code", "item_name", "geom_type",
            "created_at", "updated_at",
        }

    def _unique_import_field_name(self, name, used):
        base = re.sub(r"[^\w]+", "_", str(name or "field"), flags=re.UNICODE).strip("_")
        if not base:
            base = "field"
        used_lower = {str(value).lower() for value in used}
        if base.lower() in used_lower:
            base = f"src_{base}"
        base = base[:60]
        candidate = base
        number = 2
        while candidate.lower() in used_lower:
            suffix = f"_{number}"
            candidate = (base[: 60 - len(suffix)] + suffix) if len(base) + len(suffix) > 60 else base + suffix
            number += 1
        return candidate

    def _import_feature_memo(self, src_feature):
        candidates = ("memo", "メモ", "備考", "comment", "Comment", "note", "Note", "Text", "TEXT", "文字")
        for name in candidates:
            value = self._import_feature_field_text(src_feature, name)
            if value:
                return value[:254]
        try:
            style = src_feature.GetStyleString() or ""
        except Exception:
            style = ""
        match = re.search(r't:"((?:\\"|[^"])*)"', style)
        if match:
            return match.group(1).replace('\\"', '"')[:254]
        return ""

    def _qgis_feature_memo(self, feature):
        candidates = ("memo", "メモ", "備考", "comment", "Comment", "note", "Note", "Text", "TEXT", "文字", "NAME", "Name", "name")
        for name in candidates:
            value = self._qgis_feature_field_text(feature, name)
            if value:
                return value[:254]
        return ""

    def _import_feature_color(self, src_feature, default="ff0000"):
        try:
            style = src_feature.GetStyleString() or ""
        except Exception:
            style = ""
        for pattern in (r"[,(]c:#([0-9A-Fa-f]{6})", r"[,(]fc:#([0-9A-Fa-f]{6})", r"#([0-9A-Fa-f]{6})"):
            match = re.search(pattern, style)
            if match:
                return match.group(1).lower()
        for name in (
            "LINE_COLOR", "LineColor", "line_color", "BORDER_COL", "BORDER_COLOR",
            "FILL_COLOR", "FONT_COLOR", "color", "Color", "COLOR", "colour",
            "Colour", "COLOUR", "stroke", "Stroke",
        ):
            value = self._import_feature_field_text(src_feature, name)
            color = self._normalize_import_color(value)
            if color:
                return color
        cad_color = self._import_feature_field_text(src_feature, "Color")
        color = self._cad_index_to_hex(cad_color)
        return color or default

    def _normalize_import_color(self, value):
        text = str(value or "").strip()
        if not text:
            return ""
        match = re.search(r"RGB\s*\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)", text, re.IGNORECASE)
        if match:
            try:
                nums = [max(0, min(255, int(float(match.group(i))))) for i in (1, 2, 3)]
                return "".join(f"{num:02x}" for num in nums)
            except Exception:
                pass
        match = re.search(r"#?([0-9A-Fa-f]{6})", text)
        if match:
            return match.group(1).lower()
        if "," in text:
            parts = [p.strip() for p in text.split(",")]
            if len(parts) >= 3:
                try:
                    nums = [max(0, min(255, int(float(part)))) for part in parts[:3]]
                    return "".join(f"{num:02x}" for num in nums)
                except Exception:
                    pass
        return self._cad_index_to_hex(text)

    def _cad_index_to_hex(self, value):
        try:
            idx = int(float(str(value).strip()))
        except Exception:
            return ""
        palette = {
            1: "ff0000", 2: "ffff00", 3: "00ff00", 4: "00ffff",
            5: "0000ff", 6: "ff00ff", 7: "ffffff", 8: "808080",
            9: "c0c0c0",
        }
        return palette.get(idx, "")

    def _import_feature_layer_name(self, src_feature, default=""):
        for name in ("Layer", "layer", "LAYER"):
            value = self._import_feature_field_text(src_feature, name)
            if value:
                return value
        return default

    def _import_feature_field_text(self, src_feature, name):
        try:
            defn = src_feature.GetDefnRef()
            index = defn.GetFieldIndex(name)
            if index < 0:
                return ""
            value = src_feature.GetField(index)
            return str(value).strip() if value is not None else ""
        except Exception:
            return ""

    def _qgis_feature_field_text(self, feature, name):
        try:
            idx = feature.fields().indexOf(name)
            if idx < 0:
                return ""
            value = feature.attribute(idx)
            return str(value).strip() if value is not None else ""
        except Exception:
            return ""

    def qgis_layer_color(self, layer, prefer_attribute=False):
        if prefer_attribute:
            try:
                feature = next(layer.getFeatures())
                for name in ("LINE_COLOR", "BORDER_COL", "BORDER_COLOR", "FILL_COLOR", "FONT_COLOR", "COLOR", "Color", "color"):
                    color = self._normalize_import_color(self._qgis_feature_field_text(feature, name))
                    if color:
                        return color
            except Exception:
                pass
        try:
            renderer = layer.renderer()
            symbol = renderer.symbol() if renderer and hasattr(renderer, "symbol") else None
            if symbol:
                color = symbol.color()
                if color and color.isValid():
                    return color.name().replace("#", "")
        except Exception:
            pass
        try:
            feature = next(layer.getFeatures())
            for name in ("LINE_COLOR", "BORDER_COL", "FILL_COLOR", "FONT_COLOR", "COLOR", "Color", "color"):
                color = self._normalize_import_color(self._qgis_feature_field_text(feature, name))
                if color:
                    return color
        except Exception:
            pass
        return "ff0000"

    def qgis_layer_size_values(self, layer, geom_type):
        stroke_width = self.default_stroke_width(geom_type)
        point_size = self.default_point_size()
        try:
            renderer = layer.renderer()
            symbol = renderer.symbol() if renderer and hasattr(renderer, "symbol") else None
            if symbol:
                if geom_type == "point" and hasattr(symbol, "size"):
                    point_size = float(symbol.size())
                elif geom_type == "line" and hasattr(symbol, "width"):
                    stroke_width = float(symbol.width())
                elif geom_type == "polygon" and symbol.symbolLayerCount() > 0:
                    symbol_layer = symbol.symbolLayer(0)
                    if hasattr(symbol_layer, "strokeWidth"):
                        stroke_width = float(symbol_layer.strokeWidth())
        except Exception:
            pass
        return self.format_size_text(stroke_width), self.format_size_text(point_size)

    def qgis_layer_coordinate_transform(self, layer):
        try:
            src_crs = layer.crs()
            dst_crs = QgsProject.instance().crs()
            if src_crs and dst_crs and src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                return QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        except Exception:
            pass
        return None

    def copy_qgis_layer_style(self, src_layer, target_layer):
        try:
            renderer = src_layer.renderer()
            if renderer and hasattr(renderer, "clone"):
                target_layer.setRenderer(renderer.clone())
        except Exception as exc:
            QgsMessageLog.logMessage(f"QGISレイヤスタイル取込エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        try:
            labeling = src_layer.labeling()
            if labeling and hasattr(labeling, "clone"):
                target_layer.setLabeling(labeling.clone())
                target_layer.setLabelsEnabled(src_layer.labelsEnabled())
        except Exception:
            pass
        target_layer.triggerRepaint()

    def _ogr_flatten_type(self, geom_type):
        try:
            return ogr.wkbFlatten(geom_type)
        except Exception:
            pass
        try:
            return ogr.GT_Flatten(geom_type)
        except Exception:
            pass
        try:
            value = int(geom_type)
            value = value & 0x7FFFFFFF
            if value >= 1000:
                value = value % 1000
            return value
        except Exception:
            return geom_type

    def _import_geometry_parts(self, geom):
        flat = self._ogr_flatten_type(geom.GetGeometryType())
        if flat in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
            return [("polygon", geom)]
        if flat in (ogr.wkbLineString, ogr.wkbMultiLineString):
            return [("line", geom)]
        if flat in (ogr.wkbPoint, ogr.wkbMultiPoint):
            return [("point", geom)]
        if flat == ogr.wkbGeometryCollection:
            parts = []
            for idx in range(geom.GetGeometryCount()):
                child = geom.GetGeometryRef(idx)
                if child:
                    parts.extend(self._import_geometry_parts(child))
            return parts
        return []

    def _coerce_import_geometry(self, geom, geom_type):
        flat = self._ogr_flatten_type(geom.GetGeometryType())
        if geom_type == "polygon" and flat != ogr.wkbMultiPolygon:
            try:
                return ogr.ForceToMultiPolygon(geom)
            except Exception:
                if flat == ogr.wkbPolygon:
                    multi = ogr.Geometry(ogr.wkbMultiPolygon)
                    multi.AddGeometry(geom)
                    return multi
        if geom_type == "line" and flat != ogr.wkbMultiLineString:
            try:
                return ogr.ForceToMultiLineString(geom)
            except Exception:
                if flat == ogr.wkbLineString:
                    multi = ogr.Geometry(ogr.wkbMultiLineString)
                    multi.AddGeometry(geom)
                    return multi
        if geom_type == "point" and flat != ogr.wkbMultiPoint:
            try:
                return ogr.ForceToMultiPoint(geom)
            except Exception:
                if flat == ogr.wkbPoint:
                    multi = ogr.Geometry(ogr.wkbMultiPoint)
                    multi.AddGeometry(geom)
                    return multi
        return geom

    def _import_coordinate_transform(self, src_layer, path, crs_cache):
        try:
            src_srs = src_layer.GetSpatialRef()
            if src_srs is None:
                src_srs = self._prompt_import_source_srs(path, src_layer.GetName(), crs_cache)
            dst_srs = self._ogr_project_srs()
            if src_srs is not None and dst_srs is not None and not bool(src_srs.IsSame(dst_srs)):
                return osr.CoordinateTransformation(src_srs, dst_srs)
        except Exception:
            pass
        return None

    def _prompt_import_source_srs(self, path, layer_name, crs_cache):
        cache_key = os.path.normcase(path)
        if cache_key in crs_cache:
            return crs_cache[cache_key]
        if QgsProjectionSelectionDialog is None:
            crs_cache[cache_key] = None
            return None
        try:
            dialog = QgsProjectionSelectionDialog(self)
            dialog.setWindowTitle(tr_text("取込ファイルの座標系"))
            project_crs = QgsProject.instance().crs()
            if project_crs and project_crs.isValid():
                try:
                    dialog.setCrs(project_crs)
                except Exception:
                    pass
            if dialog.exec() != QDialog.DialogCode.Accepted:
                raise RuntimeError(f"座標系が未設定です: {os.path.basename(path)}")
            crs = dialog.crs()
            if not crs or not crs.isValid():
                raise RuntimeError(f"座標系が未設定です: {os.path.basename(path)}")
            srs = osr.SpatialReference()
            if crs.postgisSrid() > 0:
                srs.ImportFromEPSG(crs.postgisSrid())
            else:
                wkt = crs.toWkt()
                if not wkt:
                    raise RuntimeError(f"座標系を読み取れません: {os.path.basename(path)}")
                srs.ImportFromWkt(wkt)
            crs_cache[cache_key] = srs
            QgsMessageLog.logMessage(
                f"INSPECTION_VECTOR_IMPORT_CRS file={os.path.basename(path)} layer={layer_name} crs={crs.authid()}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return srs
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"座標系選択に失敗しました: {os.path.basename(path)} / {exc}")

    def rename_inspection_item(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.ordered_inspection_layers()
        if not layers:
            QMessageBox.information(self, tr_text("レイヤ名変更"), tr_text("変更できる検査レイヤがありません。"))
            return
        if layer is None:
            labels = [self.display_layer_name(layer) for layer in layers]
            current_layer = self.active_layer()
            current_index = 0
            if current_layer:
                for idx, layer in enumerate(layers):
                    if layer.id() == current_layer.id():
                        current_index = idx
                        break
            label, ok = QInputDialog.getItem(self, tr_text("レイヤ名変更"), tr_text("変更するレイヤ:"), labels, current_index, False)
            if not ok:
                return
            layer = layers[labels.index(label)]
        old_name = layer.customProperty(INSPECTION_PROP_PREFIX + "name", self.layer_base_name(layer))
        new_name, ok = QInputDialog.getText(self, tr_text("レイヤ名変更"), tr_text("新しいレイヤ名:"), text=str(old_name))
        new_name = new_name.strip() if ok else ""
        if not new_name:
            return
        if self.block_locked_layers([layer], "レイヤ名変更できません", "レイヤ属性を更新"):
            return
        if QMessageBox.question(
            self,
            tr_text("レイヤ名変更"),
            tr_text(f"「{self.display_layer_name(layer)}」を「{new_name}」へ変更しますか？\nGPKG内の物理レイヤ名は変更しません。"),
        ) != QMessageBox.StandardButton.Yes:
            return
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "name", new_name)
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["name"] = new_name
        idx_name = layer.fields().indexOf("item_name")
        idx_updated = layer.fields().indexOf("updated_at")
        changes = {}
        if idx_name >= 0:
            for feature in layer.getFeatures():
                row = {idx_name: new_name}
                if idx_updated >= 0:
                    row[idx_updated] = self.now_text()
                changes[feature.id()] = row
        if changes:
            layer.dataProvider().changeAttributeValues(changes)
        self.update_layer_display_name(layer)
        layer.triggerRepaint()
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ レイヤ名変更: {new_name}"))

    def is_manual_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source.startswith("manual_") or source.startswith("inspection_"):
            return True
        value = layer.customProperty(INSPECTION_PROP_PREFIX + "custom", False)
        if value is True:
            return True
        return str(value).lower() in ("true", "1", "yes")

    def manual_layers(self):
        return [layer for layer in self.ordered_inspection_layers() if self.is_manual_layer(layer)]

    def layer_by_source(self, source_name):
        if not source_name:
            return None
        for layer in self.current_inspection_layers():
            if layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") == source_name:
                return layer
        return None

    def standard_rounds(self):
        rounds = set()
        for layer in self.current_inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_ORTHO:
                continue
            if self.is_manual_layer(layer):
                continue
            round_no = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
            if round_no in ROUND_ITEMS:
                rounds.add(round_no)
        return rounds

    def choose_layer_dialog(self, title, layers, current_layer=None):
        if not layers:
            return None
        labels = [self.display_layer_name(layer) for layer in layers]
        current_index = 0
        if current_layer:
            for idx, layer in enumerate(layers):
                if layer.id() == current_layer.id():
                    current_index = idx
                    break
        label, ok = QInputDialog.getItem(self, title, tr_text("対象レイヤ:"), labels, current_index, False)
        if not ok:
            return None
        return layers[labels.index(label)]

    def change_inspection_color(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.ordered_inspection_layers()
        if not layers:
            QMessageBox.information(self, tr_text("色変更"), tr_text("色変更できる検査レイヤがありません。"))
            return
        if layer is None:
            layer = self.choose_layer_dialog("色変更", layers, self.active_layer())
            if not layer:
                return
        old_color = QColor(f"#{layer.customProperty(INSPECTION_PROP_PREFIX + 'color', 'ff0000')}")
        color = QColorDialog.getColor(old_color, self, "検査レイヤ色")
        if not color.isValid():
            return
        color_text = color.name().replace("#", "")
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "color", color_text)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "preserve_style", False)
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["color"] = color_text
            self.layers[source]["preserve_style"] = False
        self.apply_style(layer, self.layer_descriptor(layer))
        layer.triggerRepaint()
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ 色変更: {self.display_layer_name(layer)}"))

    def change_layer_size(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.ordered_inspection_layers()
        if not layers:
            QMessageBox.information(self, tr_text("線・点サイズ変更"), tr_text("変更できる検査レイヤがありません。"))
            return
        if layer is None:
            layer = self.choose_layer_dialog("線・点サイズ変更", layers, self.active_layer())
            if not layer:
                return
        geom_type = layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        key = "point_size" if geom_type == "point" else "stroke_width"
        default_value = self.default_point_size() if geom_type == "point" else self.default_stroke_width(geom_type)
        current_value = self.layer_size_value(layer, key, default_value)
        choices = ["0.4", "0.6", "0.8", "1.0", "1.5", "2.0"]
        current_text = self.format_size_text(current_value)
        if current_text not in choices:
            choices.append(current_text)
        label = "点サイズ:" if geom_type == "point" else "線の太さ:"
        value_text, ok = QInputDialog.getItem(
            self,
            tr_text("線・点サイズ変更"),
            f"{self.display_layer_name(layer)}\n{label}",
            choices,
            choices.index(current_text),
            True,
        )
        if not ok:
            return
        try:
            value = float(str(value_text).strip())
        except Exception:
            QMessageBox.warning(self, tr_text("線・点サイズ変更"), tr_text("数値を入力してください。"))
            return
        if value <= 0:
            QMessageBox.warning(self, tr_text("線・点サイズ変更"), tr_text("0より大きい数値を入力してください。"))
            return
        value_text = self.format_size_text(value)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + key, value_text)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "preserve_style", False)
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source][key] = value_text
            self.layers[source]["preserve_style"] = False
        self.apply_style(layer, self.layer_descriptor(layer))
        layer.triggerRepaint()
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(f"✅ {label} {value_text}: {self.display_layer_name(layer)}")

    def move_manual_layer_round(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.manual_layers()
        if not layers:
            QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("移動できる手動追加レイヤがありません。"))
            return
        if layer is None:
            labels = [self.display_layer_name(layer) for layer in layers]
            current_layer = self.active_layer()
            current_layer_index = 0
            if current_layer:
                for idx, candidate in enumerate(layers):
                    if candidate.id() == current_layer.id():
                        current_layer_index = idx
                        break
            label, ok = QInputDialog.getItem(
                self,
                tr_text("レイヤ移動"),
                tr_text("移動するレイヤ:\nレイヤ追加したレイヤのみ対象になります。"),
                labels,
                current_layer_index,
                False,
            )
            if not ok:
                return
            layer = layers[labels.index(label)]
        if not layer or not self.is_manual_layer(layer):
            QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("レイヤ追加したレイヤのみ対象になります。"))
            return
        existing_rounds = sorted(self.standard_rounds())
        choices = [("追加レイヤ", 0)] + [(self.round_title(round_no), round_no) for round_no in existing_rounds]
        if len(choices) <= 1:
            QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("移動先の検査回がまだ作成されていません。"))
            return
        current_round = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        current_index = 0
        for index, (_label, round_no) in enumerate(choices):
            if round_no == current_round:
                current_index = index
                break
        labels = [label for label, _round_no in choices]
        choice, ok = QInputDialog.getItem(self, tr_text("レイヤ移動"), tr_text("移動先:"), labels, current_index, False)
        if not ok:
            return
        new_round = dict(choices).get(choice, 0)
        if QMessageBox.question(
            self,
            tr_text("レイヤ移動"),
            tr_text(f"「{self.display_layer_name(layer)}」を「{choice}」へ移動しますか？"),
        ) != QMessageBox.StandardButton.Yes:
            return
        self.set_layer_round(layer, new_round)
        self.move_layer_node_to_round_group(layer, new_round)
        self.refresh_counts()
        self.set_status(tr_text(f"✅ レイヤ移動: {choice}"))

    def free_group_names(self):
        names = []

        def add_name(value):
            normalized = self.normalize_free_group_path(value)
            if not normalized:
                return
            parts = self.free_group_path_parts(normalized)
            for idx in range(1, len(parts) + 1):
                path = FREE_GROUP_PATH_SEPARATOR.join(parts[:idx])
                if path and path not in names:
                    names.append(path)

        for name in self.free_groups:
            add_name(name)
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            add_name(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
        return self.sort_free_group_paths(names)

    def sort_free_group_paths(self, names):
        order = {name: index for index, name in enumerate(names)}

        def key(name):
            parts = self.free_group_path_parts(name)
            path = ""
            result = []
            for part in parts:
                path = self.child_free_group_path(path, part)
                result.append((order.get(path, 10_000), part))
            return tuple(result)

        return sorted(names, key=key)

    def normalize_free_group_path(self, group_name):
        text = str(group_name or "").replace("\\", FREE_GROUP_PATH_SEPARATOR)
        parts = [part.strip() for part in text.split(FREE_GROUP_PATH_SEPARATOR) if part.strip()]
        return FREE_GROUP_PATH_SEPARATOR.join(parts)

    def free_group_path_parts(self, group_name):
        normalized = self.normalize_free_group_path(group_name)
        return [part for part in normalized.split(FREE_GROUP_PATH_SEPARATOR) if part] if normalized else []

    def free_group_parent_path(self, group_name):
        parts = self.free_group_path_parts(group_name)
        return FREE_GROUP_PATH_SEPARATOR.join(parts[:-1])

    def free_group_leaf_name(self, group_name):
        parts = self.free_group_path_parts(group_name)
        return parts[-1] if parts else ""

    def child_free_group_path(self, parent_group_name, child_name):
        parent = self.normalize_free_group_path(parent_group_name)
        child = str(child_name or "").strip()
        return self.normalize_free_group_path(f"{parent}{FREE_GROUP_PATH_SEPARATOR}{child}" if parent else child)

    def add_free_group(self, parent_group_name=None):
        if not self.is_free_inspection():
            return
        if not self.ensure_gpkg_path():
            return
        parent_group_name = self.normalize_free_group_path(parent_group_name)
        if parent_group_name is None:
            parent_group_name = ""
        if parent_group_name == "" and parent_group_name is not None:
            selected_parent = self.selected_free_group_path()
            if selected_parent:
                parent_group_name = selected_parent
        title = "子グループ追加" if parent_group_name else "グループ追加"
        label = f"{self.free_group_title(parent_group_name)} の子グループ名:" if parent_group_name else "グループ名:"
        name, ok = QInputDialog.getText(self, title, label)
        if not ok or not name.strip():
            return
        name = name.strip()
        if FREE_GROUP_PATH_SEPARATOR in name or "\\" in name:
            QMessageBox.information(self, title, tr_text("グループ名に / や \\ は使えません。"))
            return
        group_path = self.child_free_group_path(parent_group_name, name)
        if group_path in self.free_group_names():
            QMessageBox.information(self, title, tr_text("同じ場所に同じ名前のグループが既にあります。"))
            return
        self.ensure_free_group(group_path)
        self.active_free_group_name = group_path
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(f"✅ {title}: {self.free_group_title(group_path)}")

    def rename_free_group(self, old_name=None):
        if not self.is_free_inspection():
            return
        groups = self.free_group_names()
        old_name = self.normalize_free_group_path(old_name)
        if old_name == "":
            QMessageBox.information(self, tr_text("グループ名変更"), tr_text("自由式検査直下のレイヤはグループではありません。"))
            return
        elif not groups:
            QMessageBox.information(self, tr_text("グループ名変更"), tr_text("変更できる自由式グループがありません。"))
            return
        elif old_name not in groups:
            choices = [self.free_group_title(group) for group in groups]
            old_label, ok = QInputDialog.getItem(self, tr_text("グループ名変更"), tr_text("対象グループ:"), choices, 0, False)
            if not ok:
                return
            old_name = groups[choices.index(old_label)]
        old_title = self.free_group_title(old_name)
        new_name, ok = QInputDialog.getText(self, tr_text("グループ名変更"), tr_text("新しいグループ名:"), QLineEdit.EchoMode.Normal, self.free_group_leaf_name(old_name))
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if FREE_GROUP_PATH_SEPARATOR in new_name or "\\" in new_name:
            QMessageBox.information(self, tr_text("グループ名変更"), tr_text("グループ名に / や \\ は使えません。"))
            return
        parent_path = self.free_group_parent_path(old_name)
        new_path = self.child_free_group_path(parent_path, new_name)
        if new_path != old_name and new_path in groups:
            QMessageBox.information(self, tr_text("グループ名変更"), tr_text("同じ名前のグループが既にあります。"))
            return
        self.free_groups = [
            new_path + name[len(old_name):] if name == old_name or name.startswith(old_name + FREE_GROUP_PATH_SEPARATOR) else name
            for name in self.free_groups
        ]
        active_group = self.normalize_free_group_path(self.active_free_group_name)
        if active_group == old_name or active_group.startswith(old_name + FREE_GROUP_PATH_SEPARATOR):
            self.active_free_group_name = new_path + active_group[len(old_name):]
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            group_name = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
            if group_name == old_name or group_name.startswith(old_name + FREE_GROUP_PATH_SEPARATOR):
                self.set_layer_group_name(layer, new_path + group_name[len(old_name):])
        group = self.find_free_group_node(old_name)
        if group is not None:
            try:
                group.setName(new_name)
            except Exception:
                pass
        self.write_gpkg_management_state()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ グループ名変更: {old_title} → {self.free_group_title(new_path)}"))

    def move_free_group(self, source_group=None):
        if not self.is_free_inspection():
            return
        groups = self.free_group_names()
        source_group = self.normalize_free_group_path(source_group)
        if not groups:
            QMessageBox.information(self, tr_text("グループ移動"), tr_text("移動できる自由式グループがありません。"))
            return
        if not source_group:
            choices = [self.free_group_title(group) for group in groups]
            label, ok = QInputDialog.getItem(self, tr_text("グループ移動"), tr_text("移動するグループ:"), choices, 0, False)
            if not ok:
                return
            source_group = groups[choices.index(label)]
        if source_group not in groups:
            QMessageBox.information(self, tr_text("グループ移動"), tr_text("移動するグループが見つかりません。"))
            return
        leaf_name = self.free_group_leaf_name(source_group)
        parent_path = self.free_group_parent_path(source_group)
        destinations = [("", "検査直下")]
        for group in groups:
            if group == source_group or group.startswith(source_group + FREE_GROUP_PATH_SEPARATOR):
                continue
            destinations.append((group, self.free_group_title(group)))
        labels = [label for _path, label in destinations]
        current_index = 0
        for idx, (path, _label) in enumerate(destinations):
            if path == parent_path:
                current_index = idx
                break
        label, ok = QInputDialog.getItem(self, tr_text("グループ移動"), tr_text("移動先:"), labels, current_index, False)
        if not ok:
            return
        target_parent = destinations[labels.index(label)][0]
        new_path = self.child_free_group_path(target_parent, leaf_name)
        if new_path == source_group:
            return
        if new_path in groups:
            QMessageBox.information(self, tr_text("グループ移動"), tr_text("移動先に同じ名前のグループが既にあります。"))
            return
        old_title = self.free_group_title(source_group)
        new_title = self.free_group_title(new_path)
        if QMessageBox.question(self, tr_text("グループ移動"), tr_text(f"「{old_title}」を「{self.free_group_title(target_parent)}」へ移動しますか？")) != QMessageBox.StandardButton.Yes:
            return
        self.move_free_group_tree_node(source_group, target_parent)
        self.free_groups = [
            new_path + name[len(source_group):] if name == source_group or name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR) else name
            for name in self.free_groups
        ]
        active_group = self.normalize_free_group_path(self.active_free_group_name)
        if active_group == source_group or active_group.startswith(source_group + FREE_GROUP_PATH_SEPARATOR):
            self.active_free_group_name = new_path + active_group[len(source_group):]
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            group_name = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
            if group_name == source_group or group_name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR):
                updated = new_path + group_name[len(source_group):]
                layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", updated)
                source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                if source in self.layers:
                    self.layers[source]["group_name"] = updated
        QApplication.processEvents()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ グループ移動: {old_title} → {new_title}"))

    def move_free_group_tree_node(self, source_group, target_parent):
        source_node = self.find_free_group_node(source_group)
        if source_node is None:
            self.ensure_free_group(source_group)
            source_node = self.find_free_group_node(source_group)
        target_parent_node = self.ensure_free_group(target_parent)
        if source_node is None or target_parent_node is None:
            return False
        try:
            old_parent = source_node.parent()
            clone = source_node.clone()
            children = list(target_parent_node.children())
            target_parent_node.insertChildNode(len(children), clone)
            if old_parent is not None:
                old_parent.removeChildNode(source_node)
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"自由式グループ移動エラー: {source_group} -> {target_parent}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def apply_free_group_path_change(self, source_group, new_path):
        source_group = self.normalize_free_group_path(source_group)
        new_path = self.normalize_free_group_path(new_path)
        if not source_group or not new_path:
            return False
        self.free_groups = [
            new_path + name[len(source_group):]
            if name == source_group or name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR)
            else name
            for name in self.free_groups
        ]
        active_group = self.normalize_free_group_path(self.active_free_group_name)
        if active_group == source_group or active_group.startswith(source_group + FREE_GROUP_PATH_SEPARATOR):
            self.active_free_group_name = new_path + active_group[len(source_group):]
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            group_name = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
            if group_name == source_group or group_name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR):
                updated = new_path + group_name[len(source_group):]
                layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", updated)
                source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                if source in self.layers:
                    self.layers[source]["group_name"] = updated
        return True

    def free_group_subtree_paths(self, source_group, groups=None):
        source_group = self.normalize_free_group_path(source_group)
        groups = groups or self.free_group_names()
        return [
            name for name in groups
            if name == source_group or name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR)
        ]

    def free_root_child_positions(self, root_group_names, direct_layers):
        root_group_names = set(root_group_names or [])
        direct_sources = {
            layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            for layer in direct_layers or []
        }
        group_positions = {}
        layer_positions = {}
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        try:
            children = list(root_group.children())
        except Exception:
            return group_positions, layer_positions
        for index, child in enumerate(children):
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if layer:
                source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                group_name = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
                if source in direct_sources and not group_name:
                    layer_positions[source] = index
                continue
            try:
                name = child.name()
            except Exception:
                name = ""
            if name in root_group_names and name not in group_positions:
                group_positions[name] = index
        return group_positions, layer_positions

    def free_root_child_count(self):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        try:
            return len(list(root_group.children()))
        except Exception:
            return 0

    def preferred_free_layer_parent_for_save(self, layer):
        nodes = self.layer_tree_nodes_for_layer(layer.id()) if layer else []
        if not nodes:
            return None, ""
        candidates = []
        for parent, _node in nodes:
            candidates.append((parent, self.free_group_path_from_node(parent)))
        current = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
        if current:
            for parent, group_name in candidates:
                if group_name == current:
                    return parent, group_name
        for parent, group_name in candidates:
            if group_name:
                return parent, group_name
        return candidates[0]

    def free_root_order_state(self):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        result = []
        seen_groups = set()
        seen_layers = set()
        try:
            children = list(root_group.children())
        except Exception:
            return result
        for child in children:
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if layer and self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE:
                preferred_parent, preferred_group = self.preferred_free_layer_parent_for_save(layer)
                if preferred_group or (preferred_parent is not None and not self.same_layer_tree_group(root_group, preferred_parent)):
                    continue
                source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                if source and source not in seen_layers:
                    result.append({"type": "layer", "source_name": source})
                    seen_layers.add(source)
                continue
            group_name = self.free_group_path_from_node(child)
            if not group_name or self.free_group_parent_path(group_name) or group_name in seen_groups:
                continue
            result.append({"type": "group", "name": group_name})
            seen_groups.add(group_name)
        return result

    def restore_free_root_order(self, order):
        if not isinstance(order, list):
            return
        index = 0
        for item in order:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type", "")
            if item_type == "group":
                group_name = self.normalize_free_group_path(item.get("name", ""))
                if not group_name or self.free_group_parent_path(group_name):
                    continue
                if self.place_free_group_at_root_index(group_name, index):
                    index += 1
                continue
            if item_type == "layer":
                source_name = item.get("source_name", "")
                layer = self.layer_by_source(source_name)
                if layer is None or self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                    continue
                if self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")):
                    continue
                if self.place_layer_at_free_root_index(layer, index):
                    index += 1

    def sync_free_groups_from_layer_tree(self):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        ordered = []

        def add_path(path):
            path = self.normalize_free_group_path(path)
            if path and path not in ordered:
                ordered.append(path)

        def walk(parent, parent_path=""):
            try:
                children = list(parent.children())
            except Exception:
                return
            for child in children:
                try:
                    child.layer()
                    is_layer = True
                except Exception:
                    is_layer = False
                if is_layer:
                    continue
                try:
                    name = str(child.name() or "").strip()
                except Exception:
                    name = ""
                if not name:
                    continue
                path = self.child_free_group_path(parent_path, name)
                first = self.free_group_path_parts(path)[0] if self.free_group_path_parts(path) else ""
                if first in ORTHO_MODULE_GROUP_NAMES:
                    continue
                add_path(path)
                walk(child, path)

        walk(root_group)
        for name in self.free_group_names():
            add_path(name)
        self.free_groups = ordered

    def sync_free_layer_groups_from_layer_tree(self):
        changed = 0
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            _parent, parent_path = self.preferred_free_layer_parent_for_save(layer)
            current = self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
            if current != parent_path:
                self.set_layer_group_name(layer, parent_path)
                changed += 1
        self.sync_free_groups_from_layer_tree()
        return changed

    def reorder_free_group_paths_for_drop(self, moved_paths, target_group, position):
        target_group = self.normalize_free_group_path(target_group)
        position = position if position in ("before", "after", "inside", "root_top") else "after"
        moved_set = set(moved_paths)
        groups = [name for name in self.free_group_names() if name not in moved_set]
        if position == "root_top":
            groups[0:0] = moved_paths
        elif position == "inside" or not target_group:
            insert_index = len(groups)
            if target_group:
                for index, name in enumerate(groups):
                    if name == target_group or name.startswith(target_group + FREE_GROUP_PATH_SEPARATOR):
                        insert_index = index + 1
            groups[insert_index:insert_index] = moved_paths
        elif target_group in groups:
            target_index = groups.index(target_group)
            if position == "after":
                while (
                    target_index + 1 < len(groups)
                    and groups[target_index + 1].startswith(target_group + FREE_GROUP_PATH_SEPARATOR)
                ):
                    target_index += 1
                target_index += 1
            groups[target_index:target_index] = moved_paths
        else:
            groups.extend(moved_paths)
        self.free_groups = groups

    def reorder_free_group_paths_for_layer_drop(self, moved_paths, target_layer, position):
        if not moved_paths or target_layer is None:
            return
        position = position if position in ("before_layer", "after_layer") else "after_layer"
        moved_set = set(moved_paths)
        groups = [name for name in self.free_group_names() if name not in moved_set]
        target_parent = self.normalize_free_group_path(target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
        target_nodes = self.layer_tree_nodes_for_layer(target_layer.id())
        target_parent_node = None
        target_node = None
        for parent, node in target_nodes:
            parent_path = self.free_group_path_from_node(parent)
            if parent_path == target_parent:
                target_parent_node = parent
                target_node = node
                break
        if target_parent_node is None and target_nodes:
            target_parent_node, target_node = target_nodes[0]
            target_parent = self.free_group_path_from_node(target_parent_node)
        anchor_group = ""
        try:
            children = list(target_parent_node.children())
            target_index = children.index(target_node)
        except Exception:
            children = []
            target_index = -1
        if target_index >= 0:
            for index, child in enumerate(children):
                try:
                    child.layer()
                    is_layer = True
                except Exception:
                    is_layer = False
                if is_layer:
                    continue
                group_path = self.free_group_path_from_node(child)
                if not group_path or group_path in moved_set:
                    continue
                if self.free_group_parent_path(group_path) != target_parent:
                    continue
                if index > target_index or (position == "before_layer" and index >= target_index):
                    anchor_group = group_path
                    break
        if anchor_group and anchor_group in groups:
            insert_index = groups.index(anchor_group)
        elif target_parent and target_parent in groups:
            insert_index = groups.index(target_parent) + 1
            while (
                insert_index < len(groups)
                and groups[insert_index].startswith(target_parent + FREE_GROUP_PATH_SEPARATOR)
            ):
                insert_index += 1
        else:
            insert_index = len(groups)
        groups[insert_index:insert_index] = moved_paths
        self.free_groups = groups

    def set_layer_group_name(self, layer, group_name):
        group_name = self.normalize_free_group_path(group_name)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", group_name)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "inspection_type", INSPECTION_TYPE_FREE)
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["group_name"] = group_name
            self.layers[source]["inspection_type"] = INSPECTION_TYPE_FREE
        if group_name:
            self.ensure_free_group(group_name)
        self.schedule_gpkg_management_sync()

    def delete_manual_layer(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.manual_layers()
        if not layers:
            QMessageBox.information(self, tr_text("手動削除"), tr_text("削除できる手動追加レイヤがありません。"))
            return
        if layer is None:
            layer = self.choose_layer_dialog("手動削除", layers, self.active_layer())
            if not layer:
                return
        if not self.is_manual_layer(layer):
            QMessageBox.information(self, tr_text("手動削除"), tr_text("手動追加レイヤだけ削除できます。"))
            return
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if QMessageBox.question(
            self,
            tr_text("手動レイヤ削除"),
            tr_text(f"手動追加レイヤ「{self.display_layer_name(layer)}」を削除しますか？\nQGIS上のレイヤとGPKG内の該当レイヤを削除します。"),
        ) != QMessageBox.StandardButton.Yes:
            return
        layer_id = layer.id()
        self.force_removed_layer_canvas_refresh(layer)
        QgsProject.instance().removeMapLayer(layer_id)
        self.force_removed_layer_canvas_refresh()
        self.layers.pop(source, None)
        if self.active_layer_id == layer_id:
            self.active_layer_id = ""
        QApplication.processEvents()
        deleted = self.delete_gpkg_layer(source)
        self.refresh_ui()
        if deleted:
            self.set_status(tr_text(f"🗑 手動レイヤ削除: {source}"))
        else:
            QMessageBox.warning(self, tr_text("手動レイヤ削除"), tr_text("QGIS上のレイヤは削除しましたが、GPKG内レイヤの削除に失敗しました。QGIS再起動後に再実行してください。"))

    def delete_gpkg_layer(self, source_name, gpkg_path=None):
        gpkg_path = gpkg_path or self.gpkg_path
        if not OGR_OK or not gpkg_path or not os.path.exists(gpkg_path):
            return False
        try:
            ds = ogr.Open(gpkg_path, 1)
            if ds is None:
                return False
            for idx in range(ds.GetLayerCount()):
                ogr_layer = ds.GetLayerByIndex(idx)
                if ogr_layer and ogr_layer.GetName() == source_name:
                    ds.DeleteLayer(idx)
                    ds = None
                    return True
            ds = None
        except Exception as exc:
            QgsMessageLog.logMessage(f"手動検査レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False
        return False

    def gpkg_layer_exists(self, source_name, gpkg_path=None):
        gpkg_path = gpkg_path or self.gpkg_path
        if not OGR_OK or not gpkg_path or not os.path.exists(gpkg_path):
            return False
        ds = None
        try:
            ds = ogr.Open(gpkg_path, 0)
            return bool(ds and ds.GetLayerByName(source_name))
        except Exception:
            return False
        finally:
            ds = None

    def delete_layers_physically(self, layers):
        if not layers:
            return []
        project = QgsProject.instance()
        sources = []
        for layer in layers:
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if source:
                sources.append((source, self.layer_source_path(layer) or self.inspection_gpkg_path(self.layer_inspection_type(layer))))
            try:
                self.force_removed_layer_canvas_refresh(layer)
                project.removeMapLayer(layer.id())
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        QApplication.processEvents()
        self.force_removed_layer_canvas_refresh()
        failed = []
        for source, gpkg_path in sources:
            self.layers.pop(source, None)
            if not self.delete_gpkg_layer(source, gpkg_path):
                failed.append(source)
        if self.active_layer_id and not project.mapLayer(self.active_layer_id):
            self.active_layer_id = ""
        return failed

    def force_removed_layer_canvas_refresh(self, layer=None):
        def refresh_once():
            try:
                if layer:
                    layer.triggerRepaint()
            except Exception:
                pass
            try:
                canvas = self.iface.mapCanvas()
                cache = canvas.cache()
                if cache and layer:
                    cache.invalidateCacheForLayer(layer)
                if hasattr(canvas, "refreshAllLayers"):
                    canvas.refreshAllLayers()
                else:
                    canvas.refresh()
            except Exception:
                pass
            try:
                if hasattr(self.main_ui, "invalidate_interaction_image_caches"):
                    self.main_ui.invalidate_interaction_image_caches()
            except Exception:
                pass
        refresh_once()
        QTimer.singleShot(80, refresh_once)

    def remove_direct_group(self, group_name):
        root = QgsProject.instance().layerTreeRoot()
        removed = 0
        for group in self.direct_child_groups(root, group_name):
            try:
                root.removeChildNode(group)
                removed += 1
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査グループ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        return removed

    def delete_current_trash_layers_physically(self):
        failed = []
        for layer in list(self.trash_layers()):
            try:
                self.force_removed_layer_canvas_refresh(layer)
                QgsProject.instance().removeMapLayer(layer.id())
            except Exception as exc:
                QgsMessageLog.logMessage(f"ゴミ箱レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        for source in TRASH_LAYER_SOURCES.values():
            if self.gpkg_layer_exists(source, self.gpkg_path) and not self.delete_gpkg_layer(source, self.gpkg_path):
                failed.append(source)
        self.trash_layer_ids.clear()
        return failed

    def delete_current_inspection_type(self):
        is_free = self.is_free_inspection()
        root_group_name = FREE_INSPECTION_GROUP if is_free else INSPECTION_GROUP
        title = "自由式検査削除" if is_free else "オルソ検査削除"
        layers = self.current_inspection_layers()
        root = QgsProject.instance().layerTreeRoot()
        group_exists = root.findGroup(root_group_name) is not None
        if not layers and not group_exists:
            QMessageBox.information(self, title, tr_text("削除できる検査グループまたは検査レイヤがありません。"))
            return
        if is_free:
            message = (
                "自由式検査グループ内の全レイヤをGPKGから完全削除します。\n"
                "自由式検査GPKG内のゴミ箱レイヤも削除します。\n"
                "空の自由式検査グループだけがある場合は、グループだけ削除します。\n"
                "削除した地物は元に戻せません。\n"
                "削除後は自由式検査で新しいレイヤを追加できます。\n\n"
                "続行しますか？"
            )
        else:
            message = (
                "オルソ検査グループ内の全検査回・全レイヤをGPKGから完全削除します。\n"
                "オルソ検査GPKG内のゴミ箱レイヤも削除します。\n"
                "空のオルソ検査グループだけがある場合は、グループだけ削除します。\n"
                "削除した地物は元に戻せません。\n"
            "削除後は検査作成で1回目から作成し直せます。\n\n"
                "続行しますか？"
            )
        if QMessageBox.question(self, title, message) != QMessageBox.StandardButton.Yes:
            return
        failed = self.delete_layers_physically(layers) if layers else []
        failed.extend(self.delete_current_trash_layers_physically())
        if is_free:
            self.free_groups.clear()
        self.remove_direct_group(root_group_name)
        self.refresh_ui()
        if failed:
            QMessageBox.warning(self, title, tr_text("一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed)))
        else:
            self.set_status(tr_text(f"✅ {title}: {len(layers)} レイヤ"))
    def delete_ortho_round(self):
        rounds = sorted(self.standard_rounds())
        if not rounds:
            QMessageBox.information(self, tr_text("検査回削除"), tr_text("削除できる検査回がありません。"))
            return
        choices = [self.round_title(round_no) for round_no in rounds]
        choice, ok = QInputDialog.getItem(self, tr_text("検査回削除"), tr_text("削除する検査回:"), choices, 0, False)
        if not ok:
            return
        round_no = next((round_no for round_no in rounds if self.round_title(round_no) == choice), 0)
        if not round_no:
            return
        layers = [
            layer for layer in self.inspection_layers()
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_ORTHO
            and int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0) == round_no
        ]
        if not layers:
            QMessageBox.information(self, tr_text("検査回削除"), tr_text("削除対象レイヤがありません。"))
            return
        message = (
            f"{choice}の標準レイヤと、その検査回内の手動追加レイヤをGPKGから完全削除します。\n"
            "削除した地物は元に戻せません。\n"
            f"削除後は「{self.round_title(round_no)}」を再作成できます。\n\n"
            "続行しますか？"
        )
        if QMessageBox.question(self, tr_text("検査回削除"), message) != QMessageBox.StandardButton.Yes:
            return
        failed = self.delete_layers_physically(layers)
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_ORTHO)
        for group in self.direct_child_groups(root_group, choice):
            try:
                root_group.removeChildNode(group)
            except Exception:
                pass
        self.refresh_ui()
        if failed:
            QMessageBox.warning(self, tr_text("検査回削除"), tr_text("一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed)))
        else:
            self.set_status(tr_text(f"✅ 検査回削除: {choice}"))

    def delete_free_group(self, group_name=None):
        groups = self.free_group_names()
        group_name = self.normalize_free_group_path(group_name)
        if group_name == "":
            QMessageBox.information(self, tr_text("グループ削除"), tr_text("自由式検査直下はグループではありません。レイヤは手動削除してください。"))
            return
        elif not groups:
            QMessageBox.information(self, tr_text("グループ削除"), tr_text("削除できる自由式グループがありません。"))
            return
        elif group_name not in groups:
            choices = [self.free_group_title(group) for group in groups]
            group_label, ok = QInputDialog.getItem(self, tr_text("グループ削除"), tr_text("削除するグループ:"), choices, 0, False)
            if not ok:
                return
            group_name = groups[choices.index(group_label)]
        delete_groups = {
            name for name in self.free_group_names()
            if name == group_name or name.startswith(group_name + FREE_GROUP_PATH_SEPARATOR)
        }
        layers = [
            layer for layer in self.inspection_layers()
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE
            and self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")) in delete_groups
        ]
        group_title = self.free_group_title(group_name)
        message = (
            f"グループ「{group_title}」と子グループ内のレイヤをGPKGから完全削除します。\n"
            "削除した地物は元に戻せません。\n"
            "空グループの場合はグループ表示だけ削除します。\n\n"
            "続行しますか？"
        )
        if QMessageBox.question(self, tr_text("グループ削除"), message) != QMessageBox.StandardButton.Yes:
            return
        failed = self.delete_layers_physically(layers)
        active_group = self.normalize_free_group_path(self.active_free_group_name)
        if active_group == group_name or active_group.startswith(group_name + FREE_GROUP_PATH_SEPARATOR):
            self.active_free_group_name = ""
        self.free_groups = [
            name for name in self.free_groups
            if name not in delete_groups and not name.startswith(group_name + FREE_GROUP_PATH_SEPARATOR)
        ]
        group = self.find_free_group_node(group_name)
        if group is not None:
            try:
                parent = group.parent()
                if parent is not None:
                    parent.removeChildNode(group)
            except Exception:
                pass
        self.write_gpkg_management_state()
        self.refresh_ui()
        if failed:
            QMessageBox.warning(self, tr_text("グループ削除"), tr_text("一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed)))
        else:
            self.set_status(tr_text(f"✅ グループ削除: {group_title}"))

    def delete_empty_geometry_features(self):
        targets = []
        for layer in self.inspection_layers():
            ids = []
            for feature in layer.getFeatures():
                geom = feature.geometry()
                empty = False
                if geom is None:
                    empty = True
                else:
                    try:
                        empty = geom.isNull() or geom.isEmpty()
                    except Exception:
                        try:
                            empty = geom.isEmpty()
                        except Exception:
                            empty = False
                if empty:
                    ids.append(feature.id())
            if ids:
                targets.append((layer, ids))
        total = sum(len(ids) for _layer, ids in targets)
        if total == 0:
            QMessageBox.information(self, tr_text("空地物削除"), tr_text("ジオメトリなしの検査地物はありません。"))
            return
        if QMessageBox.question(self, tr_text("空地物削除"), tr_text(f"ジオメトリなしの検査地物 {total} 件を削除しますか？")) != QMessageBox.StandardButton.Yes:
            return
        for layer, ids in targets:
            layer.dataProvider().deleteFeatures(ids)
            layer.removeSelection()
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        self.refresh_counts()
        self.set_status(tr_text(f"🧹 空地物削除: {total} 件"))

    def organize_inspection_layers(self, silent=False):
        self.ensure_inspection_root_group()
        unmanaged_moved = self.move_unmanaged_layers_out_of_inspection_group()
        removed_duplicates = self.remove_duplicate_loaded_inspection_layers()
        free_synced = self.sync_free_layer_groups_from_layer_tree()
        moved = 0
        for layer in self.inspection_layers():
            if not self.is_standard_ortho_module_layer(layer):
                continue
            if self.move_layer_node_to_inspection_group(layer):
                moved += 1
        removed_empty_groups = self.remove_nested_empty_module_groups()
        reordered = self.reorder_ortho_round_groups()
        reordered_groups = self.reorder_ortho_module_groups()
        self.refresh_counts()
        self.schedule_gpkg_management_sync()
        self.schedule_layer_lock_indicator_rebuild()
        if not silent:
            extra = f" / 重複削除:{removed_duplicates}" if removed_duplicates else ""
            if free_synced:
                extra += f" / 所属同期:{free_synced}"
            if removed_empty_groups:
                extra += f" / 空グループ削除:{removed_empty_groups}"
            if unmanaged_moved:
                extra += f" / 未管理外出し:{unmanaged_moved}"
            if reordered:
                extra += f" / 順番復元:{reordered}"
            if reordered_groups:
                extra += f" / グループ順:{reordered_groups}"
            self.set_status(tr_text(f"✅ レイヤ整理: {moved} レイヤ{extra}"))

    def move_unmanaged_layers_out_of_inspection_group(self):
        root = QgsProject.instance().layerTreeRoot()
        root_group_names = {self.root_group_name_for_type(inspection_type) for inspection_type in INSPECTION_TYPES}
        moved = 0
        for inspection_group in list(self.inspection_root_groups()):
            parent = inspection_group.parent()
            if parent is None:
                parent = root
            moved += self._move_unmanaged_layers_out_of_group(inspection_group, parent, root_group_names)
        moved += self.restore_unmanaged_vector_layers_without_tree_node(root)
        return moved

    def _move_unmanaged_layers_out_of_group(self, group, target_parent, root_group_names):
        moved = 0
        try:
            children = list(group.children())
        except Exception:
            return moved
        for child in children:
            layer = None
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if layer is not None:
                if self.is_managed_inspection_layer(layer) or self.is_trash_layer(layer):
                    continue
                try:
                    new_node = QgsLayerTreeLayer(layer)
                    self.copy_layer_tree_visibility(layer, new_node)
                    target_parent.addChildNode(new_node)
                    if group.removeChildNode(child):
                        moved += 1
                except Exception as exc:
                    QgsMessageLog.logMessage(f"未管理レイヤ外出しエラー: {layer.name()} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                continue
            try:
                name = str(child.name() or "")
            except Exception:
                name = ""
            if name in root_group_names:
                continue
            moved += self._move_unmanaged_layers_out_of_group(child, target_parent, root_group_names)
        return moved

    def restore_unmanaged_vector_layers_without_tree_node(self, target_parent):
        restored = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if self.is_managed_inspection_layer(layer) or self.is_trash_layer(layer):
                continue
            if self.layer_tree_nodes_for_layer(layer.id()):
                continue
            try:
                target_parent.addLayer(layer)
                restored += 1
            except Exception as exc:
                QgsMessageLog.logMessage(f"未管理レイヤ再表示エラー: {layer.name()} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        return restored

    def is_managed_inspection_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        try:
            return bool(layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""))
        except Exception:
            return False

    def is_standard_ortho_module_layer(self, layer):
        if not layer or self.layer_inspection_type(layer) != INSPECTION_TYPE_ORTHO:
            return False
        if self.is_manual_layer(layer):
            return False
        try:
            round_no = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        except Exception:
            round_no = 0
        return round_no in ROUND_ITEMS

    def reorder_ortho_round_groups(self):
        root_groups = self.inspection_root_groups(INSPECTION_TYPE_ORTHO)
        if not root_groups:
            return 0
        total = 0
        for root_group in root_groups:
            for round_no in sorted(ROUND_ITEMS.keys()):
                group_name = self.round_title(round_no)
                for round_group in self.direct_child_groups(root_group, group_name):
                    total += self.reorder_ortho_round_group(round_group, round_no)
        return total

    def reorder_ortho_module_groups(self):
        root_groups = self.inspection_root_groups(INSPECTION_TYPE_ORTHO)
        if not root_groups:
            return 0
        moved = 0
        for root_group in root_groups:
            moved += self.reorder_direct_groups(root_group, [self.round_title(round_no) for round_no in sorted(ROUND_ITEMS.keys())])
        return moved

    def reorder_direct_groups(self, parent_group, group_names):
        group_names = [name for name in group_names if name]
        if not parent_group or not group_names:
            return 0
        nodes = []
        for name in group_names:
            groups = self.direct_child_groups(parent_group, name)
            if groups:
                nodes.append(groups[0])
        if len(nodes) < 2:
            return 0
        try:
            children = list(parent_group.children())
        except Exception:
            return 0
        existing_indices = []
        for node in nodes:
            try:
                existing_indices.append(children.index(node))
            except Exception:
                pass
        if not existing_indices:
            return 0
        insert_index = min(existing_indices)
        moved = 0
        for name in group_names:
            groups = self.direct_child_groups(parent_group, name)
            if not groups:
                continue
            group = groups[0]
            try:
                children = list(parent_group.children())
                current_index = children.index(group)
            except Exception:
                continue
            if current_index != insert_index:
                try:
                    clone = group.clone()
                    parent_group.insertChildNode(insert_index, clone)
                    parent_group.removeChildNode(group)
                    moved += 1
                except Exception as exc:
                    QgsMessageLog.logMessage(f"検査グループ順番復元エラー: {name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    continue
            insert_index += 1
        return moved

    def reorder_ortho_round_group(self, round_group, round_no):
        code_order = {code: index for index, (code, _name, _color) in enumerate(ROUND_ITEMS.get(round_no, []))}
        if not code_order:
            return 0
        children = list(round_group.children())
        layer_rows = []
        for current_index, child in enumerate(children):
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if not layer or self.layer_inspection_type(layer) != INSPECTION_TYPE_ORTHO:
                continue
            try:
                layer_round = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
            except Exception:
                layer_round = 0
            if layer_round != round_no:
                continue
            code = str(layer.customProperty(INSPECTION_PROP_PREFIX + "code", "") or "")
            order_index = code_order.get(code, 1000 + current_index)
            layer_rows.append((order_index, current_index, layer))
        if len(layer_rows) < 2:
            return 0
        desired = [layer for _order, _index, layer in sorted(layer_rows, key=lambda row: (row[0], row[1]))]
        current = [layer for _order, _index, layer in sorted(layer_rows, key=lambda row: row[1])]
        if [layer.id() for layer in desired] == [layer.id() for layer in current]:
            return 0
        moved = 0
        for index, layer in enumerate(desired):
            if self.place_layer_at_group_index(layer, round_group, index):
                moved += 1
        return moved

    def remove_nested_empty_inspection_groups(self):
        removed = 0
        for inspection_type in INSPECTION_TYPES:
            for root_group in self.inspection_root_groups(inspection_type):
                removed += self.remove_nested_empty_groups_under(root_group, is_root=True)
        return removed

    def remove_nested_empty_module_groups(self):
        removed = 0
        for root_group in self.inspection_root_groups(INSPECTION_TYPE_ORTHO):
            removed += self.remove_nested_empty_module_groups_under(root_group, parent_is_root=True)
        return removed

    def remove_nested_empty_module_groups_under(self, group, parent_is_root=False):
        removed = 0
        try:
            children = list(group.children())
        except Exception:
            return 0
        for child in children:
            try:
                child_layer = child.layer()
            except Exception:
                child_layer = None
            if child_layer:
                continue
            removed += self.remove_nested_empty_module_groups_under(child, parent_is_root=False)
            try:
                child_count_after = len(child.children())
            except Exception:
                child_count_after = 0
            try:
                child_name = child.name()
            except Exception:
                child_name = ""
            module_names = ORTHO_MODULE_GROUP_NAMES | LEGACY_ORTHO_MODULE_GROUP_NAMES
            if child_count_after != 0 or child_name not in module_names:
                continue
            if parent_is_root and child_name not in LEGACY_ORTHO_MODULE_GROUP_NAMES:
                continue
            try:
                group.removeChildNode(child)
                removed += 1
            except Exception as exc:
                QgsMessageLog.logMessage(f"空検査グループ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        return removed

    def remove_nested_empty_groups_under(self, group, is_root=False):
        removed = 0
        try:
            children = list(group.children())
        except Exception:
            return 0
        for child in children:
            try:
                child_layer = child.layer()
            except Exception:
                child_layer = None
            if child_layer:
                continue
            try:
                child_count_before = len(child.children())
            except Exception:
                child_count_before = 0
            removed += self.remove_nested_empty_groups_under(child, is_root=False)
            try:
                child_count_after = len(child.children())
            except Exception:
                child_count_after = child_count_before
            if not is_root and child_count_after == 0:
                try:
                    group.removeChildNode(child)
                    removed += 1
                except Exception as exc:
                    QgsMessageLog.logMessage(f"空検査グループ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        return removed

    def move_layer_node_to_round_group(self, layer, round_no):
        target_group = self.ensure_round_group(round_no)
        return self.move_layer_node_to_group(layer, target_group)

    def move_layer_node_to_inspection_group(self, layer):
        target_group = self.ensure_layer_tree_group_for_layer(layer)
        group_name = str(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") or "").strip()
        if group_name:
            return self.place_layer_at_group_bottom(layer, target_group)
        return self.move_layer_node_to_group(layer, target_group)

    def move_layer_node_to_group(self, layer, target_group):
        nodes = self.layer_tree_nodes_for_layer(layer.id())
        if len(nodes) == 1 and self.same_layer_tree_group(nodes[0][0], target_group):
            return False
        return self.place_layer_at_group_bottom(layer, target_group)

    def set_layer_round(self, layer, new_round):
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "round_no", new_round)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "inspection_type", INSPECTION_TYPE_ORTHO)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", "")
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["round_no"] = new_round
            self.layers[source]["inspection_type"] = INSPECTION_TYPE_ORTHO
            self.layers[source]["group_name"] = ""
        idx_round = layer.fields().indexOf("round_no")
        idx_updated = layer.fields().indexOf("updated_at")
        changes = {}
        if idx_round >= 0:
            for feature in layer.getFeatures():
                row = {idx_round: new_round}
                if idx_updated >= 0:
                    row[idx_updated] = self.now_text()
                changes[feature.id()] = row
        if changes:
            layer.dataProvider().changeAttributeValues(changes)

    def place_layer_at_group_index(self, layer, target_group, index=None):
        if layer is None or target_group is None:
            return False
        try:
            layer_id = layer.id()
            project_layer = QgsProject.instance().mapLayer(layer_id)
            if project_layer is None:
                QgsMessageLog.logMessage(
                    f"検査レイヤ移動スキップ: レイヤがプロジェクトにありません ({layer_id})",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                return False
            children = list(target_group.children())
            if index is None:
                index = len(children)
            index = max(0, min(int(index), len(children)))
            keep_node = self.insert_or_move_layer_tree_node(layer, target_group, index)
            if keep_node is None:
                raise RuntimeError("QGISレイヤツリーへの挿入に失敗しました")
            QApplication.processEvents()
            if self.group_has_layer_node(target_group, layer_id):
                self.remove_layer_tree_nodes_except(layer_id, keep_node)
                QApplication.processEvents()
            if not self.group_has_layer_node(target_group, layer_id):
                children = list(target_group.children())
                retry_index = max(0, min(index, len(children)))
                keep_node = self.insert_or_move_layer_tree_node(layer, target_group, retry_index, force_new=True)
                if keep_node is None:
                    raise RuntimeError("QGISレイヤツリーへの再挿入に失敗しました")
                QApplication.processEvents()
                if self.group_has_layer_node(target_group, layer_id):
                    self.remove_layer_tree_nodes_except(layer_id, keep_node)
                    QApplication.processEvents()
            placed = self.group_has_layer_node(target_group, layer_id)
            log_layer = QgsProject.instance().mapLayer(layer_id)
            layer_name = log_layer.name() if log_layer is not None else layer_id
            QgsMessageLog.logMessage(
                "INSPECTION_LAYER_TREE_PLACE "
                f"layer={layer_name} target={'/'.join(self.layer_tree_group_path(target_group))} "
                f"placed={placed} nodes={len(self.layer_tree_nodes_for_layer(layer_id))}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            if placed:
                self.schedule_layer_lock_indicator_rebuild()
            return placed
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤ配置エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def insert_or_move_layer_tree_node(self, layer, target_group, index, force_new=False):
        if layer is None or target_group is None:
            return None
        try:
            children = list(target_group.children())
        except Exception:
            children = []
        index = max(0, min(int(index), len(children)))
        node = QgsLayerTreeLayer(layer)
        self.copy_layer_tree_visibility(layer, node)
        target_group.insertChildNode(index, node)
        return node

    def copy_layer_tree_visibility(self, layer, target_node):
        try:
            nodes = self.layer_tree_nodes_for_layer(layer.id())
        except Exception:
            nodes = []
        for _parent, node in nodes:
            try:
                target_node.setItemVisibilityChecked(node.itemVisibilityChecked())
                return
            except Exception:
                pass

    def take_layer_tree_node_for_reinsert(self, parent, node, target_group, index):
        if parent is None or node is None:
            return None
        adjusted_index = index
        try:
            if self.same_layer_tree_group(parent, target_group):
                siblings = list(parent.children())
                current_index = siblings.index(node)
                if current_index < adjusted_index:
                    adjusted_index -= 1
        except Exception:
            pass
        try:
            if not parent.takeChild(node):
                return None
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤノード取り外しエラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        try:
            children = list(target_group.children())
            adjusted_index = max(0, min(int(adjusted_index), len(children)))
            target_group.insertChildNode(adjusted_index, node)
            return node
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤノード再挿入エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            try:
                parent.addChildNode(node)
            except Exception:
                pass
            return None

    def clone_layer_tree_node_for_insert(self, node, target_group, index):
        if node is None or target_group is None:
            return None
        try:
            clone = node.clone()
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤノード複製エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        if not clone:
            return None
        try:
            children = list(target_group.children())
            index = max(0, min(int(index), len(children)))
            target_group.insertChildNode(index, clone)
            return clone
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤノード複製挿入エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None

    def place_layer_before(self, layer, target_layer):
        if not layer or not target_layer or layer.id() == target_layer.id():
            return False
        target_nodes = self.layer_tree_nodes_for_layer(target_layer.id())
        if not target_nodes:
            return self.move_layer_node_to_inspection_group(layer)
        target_group, target_node = target_nodes[0]
        try:
            children = list(target_group.children())
            target_index = children.index(target_node)
            return self.place_layer_at_group_index(layer, target_group, target_index)
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤ並び替えエラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_layer_after(self, layer, target_layer):
        if not layer or not target_layer or layer.id() == target_layer.id():
            return False
        target_nodes = self.layer_tree_nodes_for_layer(target_layer.id())
        if not target_nodes:
            return self.move_layer_node_to_inspection_group(layer)
        target_group, target_node = target_nodes[0]
        try:
            children = list(target_group.children())
            target_index = children.index(target_node)
            return self.place_layer_at_group_index(layer, target_group, target_index + 1)
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査レイヤ下側並び替えエラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_layer_at_round_bottom(self, layer, round_no):
        if not layer:
            return False
        target_group = self.ensure_round_group(round_no)
        return self.place_layer_at_group_bottom(layer, target_group)

    def place_layer_at_group_bottom(self, layer, target_group):
        index = None
        try:
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE and self.free_group_path_from_node(target_group):
                index = self.free_group_direct_layer_insert_index(target_group)
        except Exception:
            index = None
        return self.place_layer_at_group_index(layer, target_group, index)

    def place_layer_after_free_root_group(self, layer, group_name):
        group_name = self.normalize_free_group_path(group_name)
        if not layer or not group_name or self.free_group_parent_path(group_name):
            return False
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        target_node = self.find_free_group_node(group_name)
        if target_node is None:
            return False
        try:
            if not self.same_layer_tree_group(target_node.parent(), root_group):
                return False
            children = list(root_group.children())
            target_index = children.index(target_node)
        except Exception:
            return False
        return self.place_layer_at_group_index(layer, root_group, target_index + 1)

    def place_layer_before_free_root_group(self, layer, group_name):
        group_name = self.normalize_free_group_path(group_name)
        if not layer or not group_name or self.free_group_parent_path(group_name):
            return False
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        target_node = self.find_free_group_node(group_name)
        if target_node is None:
            return False
        try:
            if not self.same_layer_tree_group(target_node.parent(), root_group):
                return False
            children = list(root_group.children())
            target_index = children.index(target_node)
        except Exception:
            return False
        return self.place_layer_at_group_index(layer, root_group, target_index)

    def place_free_root_group_at_top(self, group_name):
        group_name = self.normalize_free_group_path(group_name)
        if not group_name or self.free_group_parent_path(group_name):
            return False
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        group_node = self.find_free_group_node(group_name)
        if root_group is None or group_node is None:
            return False
        try:
            if not self.same_layer_tree_group(group_node.parent(), root_group):
                return False
            children = list(root_group.children())
            current_index = children.index(group_node)
            if current_index == 0:
                return True
            clone = group_node.clone()
            root_group.insertChildNode(0, clone)
            root_group.removeChildNode(group_node)
            QApplication.processEvents()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"自由式グループ先頭移動エラー: {group_name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_free_group_at_layer_position(self, group_name, target_layer, after=False):
        group_name = self.normalize_free_group_path(group_name)
        if not group_name or target_layer is None:
            return False
        group_node = self.find_free_group_node(group_name)
        if group_node is None:
            return False
        target_parent_path = self.normalize_free_group_path(target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
        target_nodes = self.layer_tree_nodes_for_layer(target_layer.id())
        target_parent = None
        target_node = None
        for parent, node in target_nodes:
            if self.free_group_path_from_node(parent) == target_parent_path:
                target_parent = parent
                target_node = node
                break
        if target_parent is None and target_nodes:
            target_parent, target_node = target_nodes[0]
        if target_parent is None or target_node is None:
            return False
        try:
            children = list(target_parent.children())
            target_index = children.index(target_node)
            insert_index = target_index + (1 if after else 0)
            clone = group_node.clone()
            target_parent.insertChildNode(insert_index, clone)
            old_parent = group_node.parent()
            if old_parent is not None:
                old_parent.removeChildNode(group_node)
            QApplication.processEvents()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"自由式グループレイヤ位置移動エラー: {group_name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_free_group_at_group_position(self, group_name, target_group_name, after=False):
        group_name = self.normalize_free_group_path(group_name)
        target_group_name = self.normalize_free_group_path(target_group_name)
        if not group_name or not target_group_name:
            return False
        group_node = self.find_free_group_node(group_name)
        target_node = self.find_free_group_node(target_group_name)
        if group_node is None or target_node is None:
            return False
        target_parent = target_node.parent()
        if target_parent is None:
            return False
        try:
            children = list(target_parent.children())
            target_index = children.index(target_node)
            insert_index = target_index + (1 if after else 0)
            clone = group_node.clone()
            target_parent.insertChildNode(insert_index, clone)
            old_parent = group_node.parent()
            if old_parent is not None:
                old_parent.removeChildNode(group_node)
            QApplication.processEvents()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"自由式グループ位置移動エラー: {group_name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_free_group_at_root_index(self, group_name, index):
        group_name = self.normalize_free_group_path(group_name)
        if not group_name or self.free_group_parent_path(group_name):
            return False
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        group_node = self.find_free_group_node(group_name)
        if root_group is None or group_node is None:
            return False
        try:
            if not self.same_layer_tree_group(group_node.parent(), root_group):
                return False
            children = list(root_group.children())
            index = max(0, min(int(index), len(children)))
            clone = group_node.clone()
            root_group.insertChildNode(index, clone)
            root_group.removeChildNode(group_node)
            QApplication.processEvents()
            return True
        except Exception as exc:
            QgsMessageLog.logMessage(f"自由式グループ隙間移動エラー: {group_name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False

    def place_layer_at_free_root_index(self, layer, index):
        if layer is None:
            return False
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        try:
            children = list(root_group.children())
            index = max(0, min(int(index), len(children)))
        except Exception:
            index = 0
        return self.place_layer_at_group_index(layer, root_group, index)

    def free_group_direct_layer_insert_index(self, group):
        try:
            children = list(group.children())
        except Exception:
            return None
        insert_index = len(children)
        for index, child in enumerate(children):
            try:
                child.layer()
                is_layer = True
            except Exception:
                is_layer = False
            if not is_layer:
                insert_index = index
                break
        return insert_index

    def remove_layer_tree_nodes_except(self, layer_id, keep_node):
        root = QgsProject.instance().layerTreeRoot()
        removed = 0
        keep_marker_key = "_ortho_manager_keep_node"
        keep_marker_value = f"{layer_id}_{id(keep_node)}"
        try:
            keep_node.setCustomProperty(keep_marker_key, keep_marker_value)
        except Exception:
            keep_marker_value = ""

        def is_keep_node(child):
            if child is keep_node:
                return True
            try:
                if child == keep_node:
                    return True
            except Exception:
                pass
            if keep_marker_value:
                try:
                    return child.customProperty(keep_marker_key, "") == keep_marker_value
                except Exception:
                    return False
            return False

        def walk(parent):
            nonlocal removed
            try:
                children = list(parent.children())
            except Exception:
                return
            for child in children:
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer and layer.id() == layer_id and not is_keep_node(child):
                    try:
                        parent.takeChild(child)
                        removed += 1
                    except Exception as exc:
                        QgsMessageLog.logMessage(f"検査レイヤ重複ノード削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    continue
                walk(child)

        walk(root)
        try:
            keep_node.setCustomProperty(keep_marker_key, "")
        except Exception:
            pass
        return removed

    def layer_tree_node_in_group(self, group, layer_id):
        try:
            children = list(group.children())
        except Exception:
            return None
        for child in children:
            try:
                layer = child.layer()
            except Exception:
                layer = None
            if layer and layer.id() == layer_id:
                return child
        return None

    def group_has_layer_node(self, group, layer_id):
        return self.layer_tree_node_in_group(group, layer_id) is not None

    def remove_duplicate_layer_tree_nodes(self, layer_id, target_group):
        root = QgsProject.instance().layerTreeRoot()
        removed = 0
        target_path = self.layer_tree_group_path(target_group)
        kept_in_target = False

        def walk(parent):
            nonlocal removed, kept_in_target
            try:
                children = list(parent.children())
            except Exception:
                return
            is_target_group = self.same_layer_tree_group(parent, target_group) or self.layer_tree_group_path(parent) == target_path
            for index in range(len(children) - 1, -1, -1):
                child = children[index]
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer and layer.id() == layer_id:
                    if is_target_group and not kept_in_target:
                        kept_in_target = True
                    else:
                        try:
                            parent.takeChild(child)
                            removed += 1
                        except Exception as exc:
                            QgsMessageLog.logMessage(f"検査レイヤ重複ノード削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    continue
                walk(child)

        walk(root)
        return removed

    def same_layer_tree_group(self, left, right):
        if left is right:
            return True
        try:
            return left == right
        except Exception:
            return False

    def layer_tree_group_path(self, group):
        names = []
        current = group
        while current:
            try:
                names.append(current.name())
                current = current.parent()
            except Exception:
                break
        return tuple(reversed(names))

    def layer_tree_nodes_for_layer(self, layer_id):
        root = QgsProject.instance().layerTreeRoot()
        found = []

        def walk(parent):
            try:
                children = list(parent.children())
            except Exception:
                return
            for child in children:
                layer = None
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer and layer.id() == layer_id:
                    found.append((parent, child))
                    continue
                walk(child)

        walk(root)
        return found

    def layer_tree_node_visible(self, node):
        try:
            return bool(node.isVisible())
        except Exception:
            pass
        current = node
        while current is not None:
            try:
                if hasattr(current, "itemVisibilityChecked") and not current.itemVisibilityChecked():
                    return False
            except Exception:
                pass
            try:
                current = current.parent()
            except Exception:
                break
        return True

    def layer_has_visible_tree_node(self, layer_id):
        nodes = self.layer_tree_nodes_for_layer(layer_id)
        if not nodes:
            return True
        return any(self.layer_tree_node_visible(node) for _parent, node in nodes)

    def create_inspection_layer(
        self, round_no, code, name, color, geom_type, custom=False, inspection_type=None,
        extra_fields=None, source_name_override=None, multi_geometry=False, dataset=None,
    ):
        if not self.ensure_project_metric_crs_for_inspection():
            raise RuntimeError("プロジェクト座標系が未設定または緯度経度座標系です")
        inspection_type = inspection_type if inspection_type in INSPECTION_TYPES else self.active_inspection_type
        path = self.ensure_gpkg_path(inspection_type)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        driver = ogr.GetDriverByName("GPKG")
        ds = dataset or self.open_or_create_inspection_gpkg(path, driver)
        if ds is None:
            raise RuntimeError(f"GPKGを作成できません: {path}")
        source_name = source_name_override or self.source_layer_name(round_no, code, name, geom_type, custom, inspection_type)
        if ds.GetLayerByName(source_name):
            if dataset is None:
                ds = None
            return source_name
        srs = self._ogr_project_srs()
        if multi_geometry:
            ogr_type = {"polygon": ogr.wkbMultiPolygon, "line": ogr.wkbMultiLineString, "point": ogr.wkbMultiPoint}[geom_type]
        else:
            ogr_type = {"polygon": ogr.wkbPolygon, "line": ogr.wkbLineString, "point": ogr.wkbPoint}[geom_type]
        layer = ds.CreateLayer(source_name, srs, ogr_type)
        created_names = set()
        for field_name, field_type, width in [
            ("memo", ogr.OFTString, 254),
            ("round_no", ogr.OFTInteger, 0),
            ("item_code", ogr.OFTString, 16),
            ("item_name", ogr.OFTString, 80),
            ("geom_type", ogr.OFTString, 16),
            ("created_at", ogr.OFTString, 32),
            ("updated_at", ogr.OFTString, 32),
        ]:
            field = ogr.FieldDefn(field_name, field_type)
            if width:
                field.SetWidth(width)
            layer.CreateField(field)
            created_names.add(field_name.lower())
        for item in extra_fields or []:
            field_defn = item.get("field_defn") if isinstance(item, dict) else None
            if field_defn is None:
                continue
            field_name = field_defn.GetName()
            field_key = str(field_name or "").lower()
            if not field_key or field_key in created_names:
                continue
            layer.CreateField(field_defn)
            created_names.add(field_key)
        if dataset is None:
            ds = None
        return source_name

    def _ogr_project_srs(self):
        srs = osr.SpatialReference()
        crs = QgsProject.instance().crs()
        if crs and crs.isValid():
            if crs.postgisSrid() > 0:
                try:
                    srs.ImportFromEPSG(crs.postgisSrid())
                    return srs
                except Exception:
                    pass
            try:
                wkt = crs.toWkt()
                if wkt:
                    srs.ImportFromWkt(wkt)
                    return srs
            except Exception:
                return None
        return None

    def source_layer_name(self, round_no, code, name, geom_type, custom, inspection_type=None):
        base = _base_name(code, name)
        if custom:
            if inspection_type == INSPECTION_TYPE_FREE:
                return _safe_layer_name(f"inspection_{geom_type}_{base}")
            return _safe_layer_name(f"manual_{geom_type}_{base}")
        suffix = "" if geom_type == "polygon" else f"_{geom_type}"
        return _safe_layer_name(f"r{round_no}_{base}{suffix}")

    def unique_source_layer_name(self, source_base, dataset=None):
        base = _safe_layer_name(source_base)
        used = set(self.layers.keys())
        ds = dataset
        close_ds = False
        try:
            if ds is None and self.gpkg_path and os.path.exists(self.gpkg_path):
                ds = self.open_inspection_gpkg_readonly(self.gpkg_path)
                close_ds = True
            if ds is not None:
                for idx in range(ds.GetLayerCount()):
                    layer = ds.GetLayerByIndex(idx)
                    if layer:
                        used.add(layer.GetName())
        finally:
            if close_ds:
                ds = None
        if base not in used:
            return base
        number = 2
        while True:
            suffix = f"_{number}"
            candidate = _safe_layer_name(base[: 80 - len(suffix)] + suffix)
            if candidate not in used:
                return candidate
            number += 1

    def load_layers_from_gpkg(self):
        self.sync_active_gpkg_path()
        if not self.gpkg_path or not os.path.exists(self.gpkg_path):
            return
        if not OGR_OK:
            return
        if self.load_layers_from_gpkg_management(show_warning=True):
            return
        return
        ds = self.open_inspection_gpkg_readonly(self.gpkg_path)
        if not ds:
            return
        descriptors = self._descriptors_from_existing_layers()
        for idx in range(ds.GetLayerCount()):
            ogr_layer = ds.GetLayerByIndex(idx)
            source_name = ogr_layer.GetName()
            if not self._is_inspection_source(source_name):
                continue
            descriptor = descriptors.get(source_name) or self._descriptor_from_source(source_name, ogr_layer)
            descriptor["gpkg_path"] = self.gpkg_path
            self.load_layer(source_name, descriptor)
        for source_name in TRASH_LAYER_SOURCES.values():
            if ds.GetLayerByName(source_name):
                self.load_trash_layer(source_name, visible=False)
        ds = None
        self.organize_inspection_layers(silent=True)

    def _is_inspection_source(self, source_name):
        if source_name in TRASH_LAYER_SOURCES.values():
            return False
        return source_name.startswith("r") or source_name.startswith("manual_") or source_name.startswith("inspection_")

    def _descriptors_from_existing_layers(self):
        result = {}
        for layer in self.inspection_layers():
            if self.gpkg_path and not self.same_file_path(self.layer_source_path(layer), self.gpkg_path):
                continue
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if not source:
                continue
            result[source] = self.layer_descriptor(layer)
        return result

    def _descriptor_from_source(self, source_name, ogr_layer):
        geom = ogr_layer.GetGeomType()
        geom_type = "polygon"
        if geom in (ogr.wkbLineString, ogr.wkbMultiLineString):
            geom_type = "line"
        elif geom in (ogr.wkbPoint, ogr.wkbMultiPoint):
            geom_type = "point"
        m = re.match(r"r(\d+)_(\d+?)_(.+?)(?:_(line|point))?$", source_name)
        if m:
            round_no = int(m.group(1))
            code = m.group(2)
            name = m.group(3)
            color = self.default_color_for_code(code)
            return {
                "round_no": round_no, "code": code, "name": name, "color": color,
                "geom_type": geom_type, "stroke_width": self.default_stroke_width(geom_type),
                "point_size": self.default_point_size(), "source_name": source_name,
                "inspection_type": INSPECTION_TYPE_ORTHO, "group_name": "", "custom": False
            }
        name = source_name
        inspection_type = INSPECTION_TYPE_ORTHO
        if source_name.startswith("manual_"):
            parts = source_name.split("_", 2)
            if len(parts) == 3:
                geom_type = parts[1]
                name = parts[2]
        elif source_name.startswith("inspection_"):
            inspection_type = INSPECTION_TYPE_FREE
            parts = source_name.split("_", 2)
            if len(parts) == 3:
                geom_type = parts[1]
                name = parts[2]
        guide_role = ""
        labels_enabled = True
        color = "ff0000"
        stroke_width = self.default_stroke_width(geom_type)
        if geom_type == "polygon":
            if name == "検査線" or name.startswith("検査線_"):
                guide_role = GUIDE_ROLE_LINE
                labels_enabled = False
                color = "000000"
                stroke_width = 0.4
            elif name == "検査済" or name.startswith("検査済_"):
                guide_role = GUIDE_ROLE_DONE
                labels_enabled = False
                color = "000000"
                stroke_width = 0.4
            elif name == "検査範囲" or name.startswith("検査範囲_") or name == "作業範囲" or name.startswith("作業範囲_"):
                guide_role = GUIDE_ROLE_AREA
                labels_enabled = False
                color = "0080ff"
                stroke_width = 0.6
        return {
            "round_no": 0, "code": "", "name": name, "color": color,
            "geom_type": geom_type, "stroke_width": stroke_width,
            "point_size": self.default_point_size(), "source_name": source_name,
            "inspection_type": inspection_type, "group_name": "", "custom": True,
            "guide_role": guide_role, "labels_enabled": labels_enabled
        }

    def default_color_for_code(self, code):
        for items in ROUND_ITEMS.values():
            for item_code, _name, color in items:
                if item_code == code:
                    return color
        return "ff0000"

    def load_layer(self, source_name, descriptor):
        descriptor = dict(descriptor or {})
        inspection_type = self.descriptor_inspection_type(descriptor)
        gpkg_path = descriptor.get("gpkg_path") or self.inspection_gpkg_path(inspection_type)
        if not gpkg_path:
            gpkg_path = self.gpkg_path
        descriptor["gpkg_path"] = gpkg_path
        if source_name in self.layers:
            layer = QgsProject.instance().mapLayer(self.layers[source_name].get("layer_id", ""))
            if layer and self.same_file_path(self.layer_source_path(layer), gpkg_path):
                self.apply_layer_metadata(layer, descriptor)
                self.layers[source_name] = {**descriptor, "layer_id": layer.id()}
                self.place_layer_for_descriptor(layer, descriptor)
                return layer
        layer = self.find_loaded_layer_by_source(source_name, gpkg_path)
        if layer:
            self.apply_layer_metadata(layer, descriptor)
            self.layers[source_name] = {**descriptor, "layer_id": layer.id()}
            self.place_layer_for_descriptor(layer, descriptor)
            return layer
        uri = f"{gpkg_path}|layername={source_name}"
        layer = QgsVectorLayer(uri, descriptor.get("name", source_name), "ogr")
        if not layer.isValid():
            QgsMessageLog.logMessage(f"検査レイヤ読込失敗: {source_name}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        QgsProject.instance().addMapLayer(layer, False)
        self.apply_layer_metadata(layer, descriptor)
        placed = self.place_layer_for_descriptor(layer, descriptor)
        if not placed:
            try:
                QgsProject.instance().layerTreeRoot().addLayer(layer)
                self.move_layer_node_to_inspection_group(layer)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査レイヤ配置フォールバックエラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        self.layers[source_name] = {**descriptor, "layer_id": layer.id()}
        try:
            layer.featureAdded.connect(lambda _fid, l=layer: self.refresh_counts())
            layer.featureDeleted.connect(lambda _fid, l=layer: self.refresh_counts())
            layer.geometryChanged.connect(lambda *_args: self.refresh_counts())
        except Exception:
            pass
        return layer

    def load_trash_layer(self, source_name, visible=False):
        self.cleanup_duplicate_trash_layers(source_name)
        if source_name in self.trash_layer_ids:
            layer = QgsProject.instance().mapLayer(self.trash_layer_ids.get(source_name, ""))
            if layer:
                self.apply_trash_layer_metadata(layer, source_name)
                self.ensure_trash_qgs_fields(layer)
                self.set_layer_tree_visibility(layer, visible)
                return layer
        layer = QgsProject.instance().mapLayer(self.trash_layer_ids.get(source_name, ""))
        if not layer:
            layer = self.existing_trash_layer(source_name)
        if not layer:
            uri = f"{self.gpkg_path}|layername={source_name}"
            geom_type = self.trash_geom_type_from_source(source_name)
            layer = QgsVectorLayer(uri, self.trash_layer_display_name(source_name, geom_type=geom_type), "ogr")
        if not layer or not layer.isValid():
            return None
        if not QgsProject.instance().mapLayer(layer.id()):
            QgsProject.instance().addMapLayer(layer, False)
            try:
                group = self.ensure_direct_group(QgsProject.instance().layerTreeRoot(), TRASH_GROUP_NAME)
                group.addLayer(layer)
            except Exception:
                try:
                    QgsProject.instance().layerTreeRoot().addLayer(layer)
                except Exception:
                    pass
        self.apply_trash_layer_metadata(layer, source_name)
        self.ensure_trash_qgs_fields(layer)
        self.trash_layer_ids[source_name] = layer.id()
        self.set_layer_tree_visibility(layer, visible)
        return layer

    def apply_trash_layer_metadata(self, layer, source_name):
        geom_type = self.trash_geom_type_from_source(source_name)
        layer.setName(self.trash_layer_display_name(source_name, layer=layer, geom_type=geom_type))
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "trash", True)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "source_name", source_name)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "geom_type", geom_type)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "inspection_type", self.active_inspection_type)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "gpkg_path", self.gpkg_path)
        self.apply_trash_style(layer)

    def trash_layer_display_name(self, source_name, layer=None, geom_type=None):
        geom_type = geom_type or self.trash_geom_type_from_source(source_name)
        label = GEOM_TYPE_LABELS.get(geom_type, geom_type)
        count_text = ""
        if layer is not None and layer.isValid():
            try:
                count = layer.featureCount()
                if count is None or count < 0:
                    count = sum(1 for _feature in layer.getFeatures())
                count_text = f" ({count})"
            except Exception:
                count_text = ""
        return f"ゴミ箱_{label}{count_text}"

    def existing_trash_layer(self, source_name):
        layers = self.project_trash_layers(source_name)
        return layers[0] if layers else None

    def project_trash_layers(self, source_name):
        layers = []
        active_path = self.gpkg_path
        for layer in QgsProject.instance().mapLayers().values():
            try:
                if not isinstance(layer, QgsVectorLayer):
                    continue
                prop_source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                prop_trash = bool(layer.customProperty(INSPECTION_PROP_PREFIX + "trash", False))
                uri = layer.dataProvider().dataSourceUri()
                uri_matches = f"layername={source_name}" in uri or f"layername='{source_name}'" in uri
                if (prop_trash and prop_source == source_name) or uri_matches:
                    if not active_path or self.same_file_path(self.layer_source_path(layer), active_path):
                        layers.append(layer)
            except Exception:
                continue
        return layers

    def is_project_trash_layer_for_close(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        if self.is_trash_layer(layer):
            return True
        try:
            if str(layer.name()).startswith("ゴミ箱_"):
                return True
        except Exception:
            pass
        try:
            uri = layer.dataProvider().dataSourceUri()
        except Exception:
            uri = ""
        return any(
            f"layername={source}" in uri or f"layername='{source}'" in uri
            for source in TRASH_LAYER_SOURCES.values()
        )

    def close_project_trash_layers_and_group(self):
        project = QgsProject.instance()
        removed_any = False
        for layer in list(project.mapLayers().values()):
            if not self.is_project_trash_layer_for_close(layer):
                continue
            try:
                self.force_removed_layer_canvas_refresh(layer)
                project.removeMapLayer(layer.id())
                removed_any = True
            except Exception as exc:
                QgsMessageLog.logMessage(f"ゴミ箱レイヤを閉じる処理エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        root = project.layerTreeRoot()
        for group in list(self.direct_child_groups(root, TRASH_GROUP_NAME)):
            try:
                root.removeChildNode(group)
                removed_any = True
            except Exception as exc:
                QgsMessageLog.logMessage(f"ゴミ箱グループを閉じる処理エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        self.trash_layer_ids.clear()
        if removed_any:
            QApplication.processEvents()
            self.force_removed_layer_canvas_refresh()
        return removed_any

    def cleanup_duplicate_trash_layers(self, source_name):
        layers = self.project_trash_layers(source_name)
        if not layers:
            return
        keep = None
        remembered = QgsProject.instance().mapLayer(self.trash_layer_ids.get(source_name, ""))
        if remembered in layers:
            keep = remembered
        if keep is None:
            keep = layers[0]
        for layer in layers:
            if layer.id() == keep.id():
                continue
            try:
                QgsProject.instance().removeMapLayer(layer.id())
                QgsMessageLog.logMessage(
                    f"RESTORE_TRASH_DUPLICATE_LAYER_REMOVED source={source_name} layer={layer.name()}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"RESTORE_TRASH_DUPLICATE_LAYER_REMOVE_FAILED source={source_name} error={exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
        self.trash_layer_ids[source_name] = keep.id()
        self.apply_trash_layer_metadata(keep, source_name)

    def apply_trash_style(self, layer):
        geom_type = self.layer_geom_type_key(layer)
        grey = QColor("#808080")
        if geom_type == "polygon":
            symbol = QgsFillSymbol.createSimple({
                "color": "128,128,128,55",
                "outline_color": grey.name(),
                "outline_width": "0.7",
            })
        elif geom_type == "line":
            symbol = QgsLineSymbol.createSimple({"color": grey.name(), "width": "0.8"})
        else:
            symbol = QgsMarkerSymbol.createSimple({"color": grey.name(), "size": "2.8", "outline_color": "#404040"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def trash_geom_type_from_source(self, source_name):
        for geom_type, source in TRASH_LAYER_SOURCES.items():
            if source == source_name:
                return geom_type
        return "polygon"

    def ensure_trash_layer(self, geom_type, visible=False):
        geom_type = geom_type if geom_type in TRASH_LAYER_SOURCES else "polygon"
        source_name = TRASH_LAYER_SOURCES[geom_type]
        if not OGR_OK:
            return None
        path = self.ensure_gpkg_path()
        if not path:
            return None
        driver = ogr.GetDriverByName("GPKG")
        ds = self.open_or_create_inspection_gpkg(path, driver)
        if ds is None:
            return None
        try:
            layer = ds.GetLayerByName(source_name)
            if layer is None:
                layer = self.create_trash_ogr_layer(ds, source_name, geom_type)
            else:
                self.ensure_trash_ogr_fields(layer)
        finally:
            ds = None
        return self.load_trash_layer(source_name, visible=visible)

    def trash_field_specs(self):
        return [
            ("orig_source", 160),
            ("orig_layer_name", 160),
            ("orig_color", 16),
            ("orig_geom_type", 16),
            ("orig_round_no", 16),
            ("orig_code", 32),
            ("orig_item_name", 160),
            ("orig_inspection_type", 32),
            ("orig_group_name", 160),
            ("orig_layer_id", 128),
            ("orig_layer_source_path", 1024),
            ("orig_provider_uri", 2048),
            ("orig_attrs", 8000),
            ("deleted_at", 32),
        ]

    def ensure_trash_ogr_fields(self, layer):
        if layer is None:
            return
        try:
            defn = layer.GetLayerDefn()
            existing = {defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
        except Exception:
            existing = set()
        for field_name, width in self.trash_field_specs():
            if field_name in existing:
                continue
            field = ogr.FieldDefn(field_name, ogr.OFTString)
            field.SetWidth(width)
            try:
                layer.CreateField(field)
                existing.add(field_name)
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"TRASH_FIELD_ADD_FAILED field={field_name} error={exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

    def ensure_trash_qgs_fields(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return
        missing = []
        fields = layer.fields()
        for field_name, width in self.trash_field_specs():
            if fields.indexOf(field_name) >= 0:
                continue
            missing.append(QgsField(field_name, QVariant.String, len=width))
        if not missing:
            return
        try:
            if layer.dataProvider().addAttributes(missing):
                layer.updateFields()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"TRASH_QGS_FIELD_ADD_FAILED layer={layer.name()} error={exc}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def create_trash_ogr_layer(self, ds, source_name, geom_type):
        srs = self._ogr_project_srs()
        ogr_type = {"polygon": ogr.wkbMultiPolygon, "line": ogr.wkbMultiLineString, "point": ogr.wkbMultiPoint}[geom_type]
        layer = ds.CreateLayer(source_name, srs, ogr_type)
        self.ensure_trash_ogr_fields(layer)
        return layer

    def feature_attrs_json(self, feature):
        values = {}
        try:
            fields = feature.fields()
        except Exception:
            fields = []
        for field in fields:
            name = field.name()
            try:
                value = feature[name]
            except Exception:
                value = None
            if value is None:
                values[name] = ""
            elif isinstance(value, (str, int, float, bool)):
                values[name] = value
            else:
                values[name] = str(value)
        try:
            return json.dumps(values, ensure_ascii=False)
        except Exception:
            return "{}"

    def set_feature_attrs_from_json(self, feature, attrs_text, skip_indexes=None, skip_names=None, coerce_types=False):
        try:
            values = json.loads(attrs_text or "{}")
        except Exception:
            values = {}
        if not isinstance(values, dict):
            values = {}
        skip_indexes = set(skip_indexes or [])
        skip_names = {str(name or "").lower() for name in (skip_names or [])}
        fields = feature.fields()
        for name, value in values.items():
            idx = fields.indexOf(name)
            if idx < 0 or idx in skip_indexes or str(name or "").lower() in skip_names:
                continue
            try:
                if coerce_types:
                    value = self.coerce_feature_attribute_value(fields[idx], value)
                feature.setAttribute(idx, value)
            except Exception:
                pass

    def variant_type_values(self, *names):
        values = set()
        for name in names:
            try:
                values.add(getattr(QVariant, name))
            except Exception:
                pass
        return values

    def coerce_feature_attribute_value(self, field, value):
        if value == "":
            return None
        try:
            field_type = field.type()
        except Exception:
            return value
        int_types = self.variant_type_values("Int", "UInt", "LongLong", "ULongLong")
        float_types = self.variant_type_values("Double")
        bool_types = self.variant_type_values("Bool")
        string_types = self.variant_type_values("String")
        try:
            if field_type in int_types:
                return int(value)
            if field_type in float_types:
                return float(value)
            if field_type in bool_types:
                if isinstance(value, bool):
                    return value
                text = str(value).strip().lower()
                return text in ("1", "true", "yes", "y", "on")
            if field_type in string_types and value is not None:
                return str(value)
        except Exception:
            return None
        return value

    def restore_skip_attribute_indexes(self, layer):
        indexes = set()
        names = {"fid", "fid_1", "ogc_fid"}
        try:
            provider = layer.dataProvider()
            if hasattr(provider, "pkAttributeIndexes"):
                indexes.update(int(idx) for idx in provider.pkAttributeIndexes())
        except Exception:
            pass
        try:
            fields = layer.fields()
            for idx, field in enumerate(fields):
                name = str(field.name() or "").lower()
                if name in names:
                    indexes.add(idx)
        except Exception:
            pass
        return indexes

    def set_restore_feature_attrs_from_json(self, feature, attrs_text, target_layer):
        self.set_feature_attrs_from_json(
            feature,
            attrs_text,
            skip_indexes=self.restore_skip_attribute_indexes(target_layer),
            skip_names={"fid", "fid_1", "ogc_fid"},
            coerce_types=True,
        )

    def provider_error_text(self, layer):
        texts = []
        try:
            provider = layer.dataProvider()
        except Exception:
            provider = None
        if provider is not None:
            for attr in ("errors", "lastError"):
                try:
                    value = getattr(provider, attr)()
                except Exception:
                    value = ""
                if isinstance(value, (list, tuple)):
                    texts.extend(str(item) for item in value if item)
                elif value:
                    texts.append(str(value))
        try:
            if hasattr(layer, "commitErrors"):
                texts.extend(str(item) for item in layer.commitErrors() if item)
        except Exception:
            pass
        return "; ".join(dict.fromkeys(texts))

    def set_layer_tree_visibility(self, layer, visible):
        try:
            for _parent, node in self.layer_tree_nodes_for_layer(layer.id()):
                node.setItemVisibilityChecked(bool(visible))
        except Exception:
            pass

    def find_loaded_layer_by_source(self, source_name, gpkg_path=None):
        for layer in self.inspection_layers():
            if layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") != source_name:
                continue
            if gpkg_path and not self.same_file_path(self.layer_source_path(layer), gpkg_path):
                continue
            if not gpkg_path or self.same_file_path(self.layer_source_path(layer), gpkg_path):
                return layer
        return None

    def ensure_round_group(self, round_no):
        main = self.ensure_inspection_root_group(INSPECTION_TYPE_ORTHO)
        group_name = self.round_title(round_no) if round_no else "追加レイヤ"
        group = self.ensure_direct_group(main, group_name)
        return group

    def ensure_free_group(self, group_name):
        main = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        parts = self.free_group_path_parts(group_name)
        if not parts:
            return main
        current = main
        for idx, part in enumerate(parts):
            current = self.ensure_direct_group(current, part)
            path = FREE_GROUP_PATH_SEPARATOR.join(parts[:idx + 1])
            if path and path not in self.free_groups:
                self.free_groups.append(path)
        return current

    def ensure_named_inspection_group(self, inspection_type, group_name):
        group_name = self.normalize_free_group_path(group_name) if inspection_type == INSPECTION_TYPE_FREE else str(group_name or "").strip()
        if not group_name:
            return None
        if inspection_type == INSPECTION_TYPE_FREE:
            return self.ensure_free_group(group_name)
        main = self.ensure_inspection_root_group(inspection_type)
        return self.ensure_direct_group(main, group_name)

    def ensure_group_for_descriptor(self, descriptor):
        inspection_type = self.descriptor_inspection_type(descriptor)
        group_name = str(descriptor.get("group_name", "") or "").strip()
        if inspection_type == INSPECTION_TYPE_FREE:
            return self.ensure_free_group(group_name)
        if group_name:
            group = self.ensure_named_inspection_group(inspection_type, group_name)
            if group is not None:
                return group
        return self.ensure_round_group(descriptor.get("round_no", 0))

    def place_layer_for_descriptor(self, layer, descriptor):
        descriptor = dict(descriptor or {})
        group = self.ensure_group_for_descriptor(descriptor)
        group_name = str(descriptor.get("group_name", "") or "").strip()
        inspection_type = self.descriptor_inspection_type(descriptor)
        QgsMessageLog.logMessage(
            "INSPECTION_LAYER_DESCRIPTOR_TARGET "
            f"layer={layer.name()} inspection_type={inspection_type} group={group_name} "
            f"target={'/'.join(self.layer_tree_group_path(group))}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return self.place_layer_at_group_bottom(layer, group)

    def ensure_layer_tree_group_for_layer(self, layer):
        inspection_type = self.layer_inspection_type(layer)
        group_name = str(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") or "").strip()
        if group_name:
            group = self.ensure_named_inspection_group(inspection_type, group_name)
            if group is not None:
                return group
        if inspection_type == INSPECTION_TYPE_FREE:
            return self.ensure_free_group("")
        round_no = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        return self.ensure_round_group(round_no)

    def root_group_name_for_type(self, inspection_type):
        return INSPECTION_GROUP

    def ensure_inspection_root_group(self, inspection_type=None):
        if inspection_type not in INSPECTION_TYPES:
            inspection_type = self.active_inspection_type
        root = QgsProject.instance().layerTreeRoot()
        return self.ensure_direct_group(root, self.root_group_name_for_type(inspection_type))

    def inspection_root_groups(self, inspection_type=None):
        if inspection_type not in INSPECTION_TYPES:
            inspection_type = self.active_inspection_type
        root = QgsProject.instance().layerTreeRoot()
        groups = []
        for group in self.direct_child_groups(root, self.root_group_name_for_type(inspection_type)):
            if group not in groups:
                groups.append(group)
        return groups

    def direct_child_groups(self, parent, name):
        groups = []
        try:
            children = list(parent.children())
        except Exception:
            return groups
        for child in children:
            try:
                child.children()
                is_group = True
            except Exception:
                is_group = False
            try:
                if is_group and child.name() == name:
                    groups.append(child)
            except Exception:
                pass
        return groups

    def ensure_direct_group(self, parent, name):
        if parent is None:
            return None
        groups = self.direct_child_groups(parent, name)
        if not groups:
            try:
                created = parent.addGroup(name)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査グループ作成エラー: {name} / {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                return None
            if created is not None:
                return created
            groups = self.direct_child_groups(parent, name)
            if not groups:
                QgsMessageLog.logMessage(f"検査グループ作成後の再取得失敗: {name}", "OrthoManager", Qgis.MessageLevel.Warning)
                return None
        keep = groups[0]
        for duplicate in groups[1:]:
            self.merge_layer_tree_group(keep, duplicate)
        return keep

    def merge_layer_tree_group(self, keep_group, duplicate_group):
        try:
            for child in list(duplicate_group.children()):
                try:
                    if duplicate_group.takeChild(child):
                        keep_group.addChildNode(child)
                    else:
                        keep_group.addChildNode(child.clone())
                except Exception:
                    keep_group.addChildNode(child.clone())
            parent = duplicate_group.parent()
            if parent is not None:
                parent.removeChildNode(duplicate_group)
        except Exception as exc:
            QgsMessageLog.logMessage(f"検査グループ統合エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)

    def apply_layer_metadata(self, layer, descriptor):
        descriptor = dict(descriptor)
        geom_type = descriptor.get("geom_type", "polygon")
        if not descriptor.get("stroke_width"):
            descriptor["stroke_width"] = self.default_stroke_width(geom_type)
        if not descriptor.get("point_size"):
            descriptor["point_size"] = self.default_point_size()
        descriptor["inspection_type"] = self.descriptor_inspection_type(descriptor)
        descriptor.setdefault("group_name", "")
        descriptor.setdefault("guide_role", "")
        if descriptor.get("guide_role", "") in (GUIDE_ROLE_AREA, GUIDE_ROLE_DONE, GUIDE_ROLE_LINE):
            descriptor["group_name"] = ""
        descriptor.setdefault("labels_enabled", True)
        descriptor.setdefault("gpkg_path", self.inspection_gpkg_path(descriptor["inspection_type"]))
        source_name = descriptor.get("source_name", "")
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "source_name", source_name)
        for key in (
            "round_no", "code", "name", "color", "geom_type", "custom", "stroke_width",
            "point_size", "inspection_type", "group_name", "preserve_style",
            "guide_role", "labels_enabled", "gpkg_path",
        ):
            layer.setCustomProperty(INSPECTION_PROP_PREFIX + key, descriptor.get(key, ""))
        if not self.layer_preserve_style(layer):
            self.apply_style(layer, descriptor)
        self.update_layer_display_name(layer)

    def apply_style(self, layer, descriptor):
        color = QColor(f"#{descriptor.get('color', 'ff0000')}")
        geom_type = descriptor.get("geom_type", "polygon")
        stroke_width = self.size_from_descriptor(descriptor, "stroke_width", self.default_stroke_width(geom_type))
        point_size = self.size_from_descriptor(descriptor, "point_size", self.default_point_size())
        guide_role = descriptor.get("guide_role", "")
        if guide_role == GUIDE_ROLE_DONE:
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,128",
                "outline_color": "0,0,0,0",
                "outline_width": "0",
            })
        elif guide_role == GUIDE_ROLE_LINE:
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,0",
                "style": "no",
                "outline_color": "#000000",
                "outline_width": "0.4",
            })
        elif guide_role == GUIDE_ROLE_AREA:
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,0",
                "style": "no",
                "outline_color": color.name(),
                "outline_width": self.format_size_text(stroke_width),
            })
        elif geom_type == "polygon":
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,0",
                "style": "no",
                "outline_color": color.name(),
                "outline_width": self.format_size_text(stroke_width),
            })
        elif geom_type == "line":
            symbol = QgsLineSymbol.createSimple({"color": color.name(), "width": self.format_size_text(stroke_width)})
        else:
            symbol = QgsMarkerSymbol.createSimple({"color": color.name(), "size": self.format_size_text(point_size), "outline_color": "#202020"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        self.apply_memo_labels(layer, color)
        labels_enabled = descriptor.get("labels_enabled", True)
        if str(labels_enabled).lower() in ("false", "0", "no", ""):
            layer.setLabelsEnabled(False)

    def default_stroke_width(self, geom_type):
        return 0.8 if geom_type == "line" else 0.6

    def default_point_size(self):
        return 2.6

    def format_size_text(self, value):
        try:
            return f"{float(value):g}"
        except Exception:
            return "0.6"

    def size_from_descriptor(self, descriptor, key, default_value):
        try:
            value = float(descriptor.get(key, default_value))
            return value if value > 0 else default_value
        except Exception:
            return default_value

    def layer_size_value(self, layer, key, default_value):
        try:
            value = float(layer.customProperty(INSPECTION_PROP_PREFIX + key, default_value) or default_value)
            return value if value > 0 else default_value
        except Exception:
            return default_value

    def preview_rubber_band_width(self, layer=None):
        geom_key = self.active_geom_type
        if layer:
            geom_key = self.layer_geom_type_key(layer)
        if geom_key == "point":
            size = self.default_point_size()
            if layer:
                size = self.layer_size_value(layer, "point_size", self.default_point_size())
            return max(4, min(18, int(round(float(size) * 3.0))))
        stroke_width = self.default_stroke_width(geom_key)
        if layer:
            stroke_width = self.layer_size_value(layer, "stroke_width", self.default_stroke_width(geom_key))
        return max(2, min(14, int(round(float(stroke_width) * 4.0))))

    def apply_edit_preview_width(self, layer):
        try:
            settings = QgsSettings()
            if not self._edit_preview_width_overridden:
                self._original_digitizing_line_width_had_key = settings.contains("digitizing/line-width")
                self._original_digitizing_line_width = settings.value("digitizing/line-width", 1)
                self._edit_preview_width_overridden = True
            settings.setValue("digitizing/line-width", self.preview_rubber_band_width(layer))
            settings.sync()
        except Exception:
            pass

    def restore_edit_preview_width(self):
        if not self._edit_preview_width_overridden:
            return
        try:
            settings = QgsSettings()
            if self._original_digitizing_line_width_had_key:
                settings.setValue("digitizing/line-width", self._original_digitizing_line_width)
            else:
                settings.remove("digitizing/line-width")
            settings.sync()
        except Exception:
            pass
        self._edit_preview_width_overridden = False
        self._original_digitizing_line_width = None
        self._original_digitizing_line_width_had_key = False

    def apply_memo_labels(self, layer, color):
        try:
            settings = QgsPalLayerSettings()
            settings.fieldName = "memo"
            settings.enabled = True
            text_format = QgsTextFormat()
            text_format.setSize(10)
            try:
                text_format.setColor(color)
            except Exception:
                pass
            settings.setFormat(text_format)
            if layer.geometryType() == Qgis.GeometryType.Line:
                settings.placement = Qgis.LabelPlacement.Line
                try:
                    line_settings = settings.lineSettings()
                    line_settings.setPlacementFlags(
                        Qgis.LabelLinePlacementFlag.OnLine
                        | Qgis.LabelLinePlacementFlag.AboveLine
                        | Qgis.LabelLinePlacementFlag.BelowLine
                    )
                    settings.setLineSettings(line_settings)
                except Exception:
                    pass
            layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
            layer.setLabelsEnabled(True)
        except Exception:
            pass

    def layer_descriptor(self, layer):
        inspection_type = self.layer_inspection_type(layer)
        group_name = layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")
        guide_role = layer.customProperty(INSPECTION_PROP_PREFIX + "guide_role", "")
        if guide_role in (GUIDE_ROLE_AREA, GUIDE_ROLE_DONE, GUIDE_ROLE_LINE):
            group_name = ""
        return {
            "source_name": layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""),
            "round_no": int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0),
            "code": layer.customProperty(INSPECTION_PROP_PREFIX + "code", ""),
            "name": layer.customProperty(INSPECTION_PROP_PREFIX + "name", ""),
            "color": layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000"),
            "geom_type": layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon"),
            "stroke_width": layer.customProperty(INSPECTION_PROP_PREFIX + "stroke_width", self.default_stroke_width(layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon"))),
            "point_size": layer.customProperty(INSPECTION_PROP_PREFIX + "point_size", self.default_point_size()),
            "inspection_type": inspection_type,
            "group_name": group_name,
            "custom": bool(layer.customProperty(INSPECTION_PROP_PREFIX + "custom", False)),
            "preserve_style": self.layer_preserve_style(layer),
            "guide_role": guide_role,
            "labels_enabled": layer.customProperty(INSPECTION_PROP_PREFIX + "labels_enabled", True),
            "gpkg_path": self.layer_source_path(layer) or self.inspection_gpkg_path(inspection_type),
        }

    def layer_preserve_style(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        value = layer.customProperty(INSPECTION_PROP_PREFIX + "preserve_style", False)
        if value is True:
            return True
        return str(value).lower() in ("true", "1", "yes")

    def layer_inspection_type(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return INSPECTION_TYPE_ORTHO
        value = layer.customProperty(INSPECTION_PROP_PREFIX + "inspection_type", "")
        if value in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE):
            return value
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if str(source).startswith("inspection_"):
            return INSPECTION_TYPE_FREE
        return INSPECTION_TYPE_ORTHO

    def descriptor_inspection_type(self, descriptor):
        value = descriptor.get("inspection_type", "")
        if value in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE):
            return value
        source = descriptor.get("source_name", "")
        return INSPECTION_TYPE_FREE if str(source).startswith("inspection_") else INSPECTION_TYPE_ORTHO

    def layer_base_name(self, layer):
        code = layer.customProperty(INSPECTION_PROP_PREFIX + "code", "")
        name = layer.customProperty(INSPECTION_PROP_PREFIX + "name", layer.name())
        return _base_name(code, name)

    def update_layer_display_name(self, layer):
        base = self.layer_base_name(layer)
        try:
            count = layer.featureCount()
        except Exception:
            count = 0
        layer.setName(f"{base}（{count}）")

    def refresh_counts(self):
        self._refresh_counts_pending = False
        for layer in self.inspection_layers():
            self.update_layer_display_name(layer)
        self.refresh_ui()

    def schedule_refresh_counts(self, delay_ms=80):
        if self._refresh_counts_pending:
            return
        self._refresh_counts_pending = True
        QTimer.singleShot(delay_ms, self.refresh_counts)

    def refresh_vector_layer_after_data_change(self, layer, reload_data=True, mark_edit_refresh=True):
        if not layer:
            return
        if mark_edit_refresh:
            try:
                self._layers_needing_edit_refresh.add(layer.id())
            except Exception:
                pass
        provider = None
        try:
            provider = layer.dataProvider()
        except Exception:
            provider = None
        if reload_data and provider:
            try:
                provider.reloadData()
            except Exception:
                pass
        try:
            layer.updateExtents(True)
        except Exception:
            try:
                layer.updateExtents()
            except Exception:
                pass
        try:
            layer.invalidateWgs84Extent()
        except Exception:
            pass
        try:
            if self.is_trash_layer(layer):
                source_name = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                if source_name:
                    self.apply_trash_layer_metadata(layer, source_name)
        except Exception:
            pass
        try:
            layer.triggerRepaint()
        except Exception:
            pass
        try:
            canvas = self.iface.mapCanvas()
            cache = canvas.cache()
            if cache:
                cache.invalidateCacheForLayer(layer)
            canvas.refresh()
        except Exception:
            pass
        try:
            if hasattr(self.main_ui, "invalidate_interaction_image_caches"):
                self.main_ui.invalidate_interaction_image_caches()
        except Exception:
            pass
        QTimer.singleShot(0, lambda l=layer: self.refresh_vector_layer_later(l))

    def close_edit_buffer_before_provider_change(self, layer):
        if not layer:
            return True, ""
        try:
            if not layer.isEditable():
                return True, ""
        except Exception:
            return True, ""
        try:
            if layer.commitChanges():
                return True, ""
            errors = "; ".join(layer.commitErrors())
            try:
                layer.rollBack()
            except Exception:
                pass
            return False, errors or "編集バッファを保存できませんでした"
        except Exception as exc:
            try:
                layer.rollBack()
            except Exception:
                pass
            return False, str(exc)

    def refresh_pending_data_change_layers(self):
        pending_ids = list(getattr(self, "_layers_needing_edit_refresh", set()) or [])
        if not pending_ids:
            return
        project = QgsProject.instance()
        for layer_id in pending_ids:
            layer = project.mapLayer(layer_id)
            if not isinstance(layer, QgsVectorLayer):
                self._layers_needing_edit_refresh.discard(layer_id)
                continue
            try:
                if layer.isEditable():
                    continue
            except Exception:
                pass
            self.refresh_vector_layer_after_data_change(layer, reload_data=True, mark_edit_refresh=False)
            try:
                self._layers_needing_edit_refresh.discard(layer_id)
            except Exception:
                pass

    def refresh_vector_layer_later(self, layer):
        if not layer:
            return
        try:
            layer.updateExtents(True)
        except Exception:
            try:
                layer.updateExtents()
            except Exception:
                pass
        try:
            layer.triggerRepaint()
        except Exception:
            pass
        try:
            self.iface.mapCanvas().refresh()
        except Exception:
            pass

    def refresh_ui(self):
        self.sync_active_gpkg_path()
        path_text = self.gpkg_path or tr("inspection.path.none")
        self.path_label.setText(tr_text(f"検査GPKG: {path_text}"))
        self.path_label.setToolTip(self.gpkg_path)
        self.rounds_box.setVisible(False)
        self.refresh_guide_layer_combo()
        self._rebuild_item_buttons()
        existing_rounds = self.standard_rounds()
        root_group_exists = bool(self.inspection_root_groups())
        selected_round = self.selected_module_round_no()
        self.module_create_btn.setEnabled(bool(self.gpkg_path and root_group_exists and selected_round and selected_round not in existing_rounds))
        for round_no, button in self.round_buttons.items():
            button.setEnabled(False)
        has_layers = bool(self.current_inspection_layers())
        has_manual_layers = bool(self.manual_layers())
        self.btn_import_qgis_layer.setEnabled(True)
        self.btn_rename_item.setEnabled(has_layers)
        self.btn_color_item.setEnabled(has_layers)
        self.btn_move_manual.setEnabled(has_manual_layers)
        self.btn_move_manual.setVisible(False)
        self.btn_add_group.setVisible(True)
        self.btn_rename_group.setVisible(False)
        self.btn_delete_free_group.setVisible(False)
        self.btn_delete_round.setVisible(False)
        self.btn_add_group.setEnabled(bool(self.gpkg_path))
        self.btn_rename_group.setEnabled(False)
        self.btn_delete_free_group.setEnabled(False)
        self.btn_delete_round.setEnabled(False)
        self._refresh_delete_inspection_type_text()
        self.btn_delete_inspection_type.setVisible(False)
        self.btn_delete_inspection_type.setEnabled(False)
        self.btn_delete_manual.setEnabled(has_manual_layers)
        self.btn_clean_empty.setEnabled(has_layers)
        self.btn_organize_layers.setEnabled(has_layers)

    def _rebuild_item_buttons(self):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.buttons_by_source.clear()
        layers = []
        for layer in self.ordered_inspection_layers():
            geom_type = self.layer_descriptor(layer).get("geom_type")
            if self.is_free_inspection() or geom_type == "polygon":
                layers.append(layer)
        active = self.active_layer()
        layer_ids = {layer.id() for layer in layers}
        if active and active.id() in layer_ids:
            desc = self.layer_descriptor(active)
            source = desc.get("source_name")
            label = self.layer_base_name(active)
            button = QPushButton(label)
            button.setToolTip(label)
            button.setMinimumWidth(0)
            button.setMaximumWidth(170)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, s=source: self.activate_layer_by_source(s))
            button.setStyleSheet(self._btn_style(desc.get("color", "ff0000"), active=True))
            self.items_layout.addWidget(button, 0, 0)
            self.buttons_by_source[source] = button
        elif layers:
            label = QLabel(tr("inspection.items.select_prompt"))
            label.setWordWrap(True)
            self.items_layout.addWidget(label, 0, 0)
        else:
            message = tr("inspection.items.create_free") if self.is_free_inspection() else tr("inspection.items.create_ortho")
            self.items_layout.addWidget(QLabel(message), 0, 0)

    def raw_inspection_layers(self):
        result = []
        for layer in QgsProject.instance().mapLayers().values():
            if (
                isinstance(layer, QgsVectorLayer)
                and layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                and not self.is_trash_layer(layer)
            ):
                result.append(layer)
        return result

    def is_trash_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in TRASH_LAYER_SOURCES.values():
            return True
        value = layer.customProperty(INSPECTION_PROP_PREFIX + "trash", False)
        return value is True or str(value).lower() in ("true", "1", "yes")

    def trash_layers(self):
        layers = []
        seen_ids = set()
        active_path = self.gpkg_path

        def add_layer(layer):
            if not layer or layer.id() in seen_ids:
                return
            if active_path and not self.same_file_path(self.layer_source_path(layer), active_path):
                return
            layers.append(layer)
            seen_ids.add(layer.id())

        for source in TRASH_LAYER_SOURCES.values():
            layer = QgsProject.instance().mapLayer(self.trash_layer_ids.get(source, ""))
            add_layer(layer)
            for layer in self.project_trash_layers(source):
                add_layer(layer)
        for layer in QgsProject.instance().mapLayers().values():
            if self.is_trash_layer(layer):
                add_layer(layer)
        return layers

    def inspection_layers(self):
        result = []
        seen_sources = set()
        for layer in self.raw_inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            key = (source, self.normalize_file_path(self.layer_source_path(layer)))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            result.append(layer)
        return result

    def current_inspection_layers(self):
        active_path = self.gpkg_path
        return [
            layer for layer in self.inspection_layers()
            if not active_path or self.same_file_path(self.layer_source_path(layer), active_path)
        ]

    def remove_duplicate_loaded_inspection_layers(self):
        by_source = {}
        remove_ids = []
        for layer in self.raw_inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if not source:
                continue
            key = (source, self.normalize_file_path(self.layer_source_path(layer)))
            preferred_id = self.layers.get(source, {}).get("layer_id", "")
            if key not in by_source:
                by_source[key] = layer
                continue
            keep_layer = by_source[key]
            if preferred_id and layer.id() == preferred_id:
                remove_ids.append(keep_layer.id())
                by_source[key] = layer
            else:
                remove_ids.append(layer.id())
        for layer_id in remove_ids:
            try:
                QgsProject.instance().removeMapLayer(layer_id)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査重複レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        for (source, _path), layer in by_source.items():
            self.layers[source] = {**self.layer_descriptor(layer), "layer_id": layer.id()}
        return len(remove_ids)

    def ordered_inspection_layers(self):
        layer_by_id = {layer.id(): layer for layer in self.current_inspection_layers()}
        ordered = []
        seen_ids = set()
        seen_sources = set()
        root = QgsProject.instance().layerTreeRoot()
        groups = self.inspection_root_groups()

        def walk(node):
            try:
                children = node.children()
            except Exception:
                return
            for child in children:
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer and layer.id() in layer_by_id:
                    source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                    if layer.id() not in seen_ids and source not in seen_sources:
                        ordered.append(layer)
                        seen_ids.add(layer.id())
                        seen_sources.add(source)
                    continue
                walk(child)

        for group in groups:
            walk(group)
        rest = [
            layer for layer in self.current_inspection_layers()
            if layer.id() not in seen_ids
            and layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") not in seen_sources
        ]
        rest.sort(key=lambda l: (
            self.layer_inspection_type(l),
            int(l.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0),
            l.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""),
            self.layer_base_name(l),
        ))
        return ordered + rest

    def selectable_inspection_layers(self):
        layers = []
        for layer in self.ordered_inspection_layers():
            if not layer.isValid():
                continue
            try:
                if not self.layer_has_visible_tree_node(layer.id()):
                    continue
            except Exception:
                pass
            if self.is_layer_selection_locked(layer):
                try:
                    layer.removeSelection()
                except Exception:
                    pass
                continue
            layers.append(layer)
        return layers

    def visible_vector_layers(self):
        return self.selectable_inspection_layers()

    def active_layer(self):
        return QgsProject.instance().mapLayer(self.active_layer_id) if self.active_layer_id else None

    def activate_layer_by_source(self, source_name):
        layer = None
        for lyr in self.ordered_inspection_layers():
            if lyr.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") == source_name:
                layer = lyr
                break
        if not layer:
            return
        if self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon"):
            self.move_selected_to_layer(layer)
            return
        self.remember_create_return_mode()
        self.finish_edit_for_mode_switch()
        self.active_layer_id = layer.id()
        self.active_geom_type = layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.operation_mode = "create"
        self.iface.setActiveLayer(layer)
        self.ensure_map_tool()
        self.refresh_ui()
        self.set_status(tr_text(f"検査入力: {self.layer_base_name(layer)}"))

    def toggle_inspection(self, enabled):
        self.inspection_enabled = enabled
        if enabled:
            self.install_context_filter()
            self.apply_inspection_selection_color()
            self.switch_to_pan()
            self.btn_on.setText(tr("inspection.btn.on"))
            self.btn_on.setStyleSheet("QPushButton{background:#27ae60;color:white;font-weight:bold;}")
        else:
            self.remove_context_filter()
            self.finish_edit_for_mode_switch()
            self.restore_selection_color()
            self.btn_on.setStyleSheet("")
            self.reset_inspection_map_tool_to_qgis_pan()

    def reset_inspection_map_tool_to_qgis_pan(self):
        self.clear_feature_move_preview()
        self.feature_move_targets = []
        self.feature_move_undo_stack = []
        if self.operation_mode == "restore":
            self.clear_trash_selection()
            self.set_trash_layers_visible(False)
        self.clear_inspection_selection()
        self.operation_mode = "pan"
        self.create_return_mode = "pan"
        try:
            canvas = self.iface.mapCanvas()
            viewport = canvas.viewport()
            if viewport:
                viewport.unsetCursor()
            if self.map_tool and canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
            self.iface.actionPan().trigger()
            canvas.setFocus()
            if viewport:
                viewport.setFocus()
        except Exception:
            try:
                if self.map_tool and self.iface.mapCanvas().mapTool() == self.map_tool:
                    self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass
            self.map_tool = None
        self.refresh_ui()
        self.set_status(tr_text("検査OFF: 地図移動へ戻しました"))

    def ensure_map_tool(self):
        canvas = self.iface.mapCanvas()
        self.apply_inspection_selection_color()
        if not self.map_tool:
            self.map_tool = InspectionMapTool(canvas, self)
        if canvas.mapTool() != self.map_tool:
            canvas.setMapTool(self.map_tool)
        self.update_map_cursor()
        canvas.setFocus()
        if canvas.viewport():
            canvas.viewport().setFocus()

    def ensure_map_tool_soon(self):
        self.ensure_map_tool()
        QTimer.singleShot(0, self.ensure_map_tool)
        QTimer.singleShot(80, self.ensure_map_tool)

    def update_map_cursor(self):
        if not self.map_tool:
            return
        cursor = Qt.CursorShape.CrossCursor
        if self.operation_mode == "move":
            self.apply_map_cursor(self.move_cursor())
            return
        if self.operation_mode in ("delete", "merge", "layer_change"):
            cursor = Qt.CursorShape.PointingHandCursor
        elif self.operation_mode in ("layer_change_select", "layer_change_select_polygon"):
            self.apply_map_cursor(self.yellow_select_cursor())
            return
        elif self.operation_mode == "restore":
            self.apply_map_cursor(self.yellow_select_cursor())
            return
        elif self.operation_mode == "edit":
            self.apply_map_cursor(self.red_edit_cursor())
            return
        elif self.operation_mode == "select":
            self.apply_map_cursor(self.yellow_select_cursor())
            return
        self.apply_map_cursor(QCursor(cursor))

    def apply_map_cursor(self, cursor):
        if self.map_tool:
            try:
                self.map_tool.setCursor(cursor)
            except Exception:
                pass
        try:
            viewport = self.iface.mapCanvas().viewport()
            if viewport:
                viewport.setCursor(cursor)
        except Exception:
            pass

    def inspection_canvases(self):
        canvases = []
        try:
            canvases.extend(list(self.iface.mapCanvases()))
        except Exception:
            pass
        try:
            main_canvas = self.iface.mapCanvas()
            if main_canvas and all(id(canvas) != id(main_canvas) for canvas in canvases):
                canvases.append(main_canvas)
        except Exception:
            pass
        return canvases

    def apply_inspection_selection_color(self):
        color = QColor("#ffd400")
        color.setAlpha(70)
        for canvas in self.inspection_canvases():
            key = id(canvas)
            try:
                if key not in self._original_selection_colors:
                    self._original_selection_colors[key] = (canvas, QColor(canvas.selectionColor()))
                canvas.setSelectionColor(color)
            except Exception:
                pass

    def restore_selection_color(self):
        for canvas, color in list(self._original_selection_colors.values()):
            try:
                canvas.setSelectionColor(color)
            except Exception:
                pass
        self._original_selection_colors.clear()
        self.clear_selection_highlight()
        self.clear_paste_flash_highlight()

    def clear_selection_highlight(self):
        try:
            scene = self.iface.mapCanvas().scene()
        except Exception:
            scene = None
        for item in self.selection_highlight_items:
            try:
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self.selection_highlight_items = []

    def clear_paste_flash_highlight(self):
        try:
            scene = self.iface.mapCanvas().scene()
        except Exception:
            scene = None
        for item in self.paste_flash_highlight_items:
            try:
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self.paste_flash_highlight_items = []

    def flash_pasted_features(self, added_by_layer, duration_ms=2200):
        self.clear_paste_flash_highlight()
        if not self.inspection_enabled:
            return
        canvas = self.iface.mapCanvas()
        flash_color = QColor("#00d9ff")
        flash_color.setAlpha(255)
        fill_color = QColor(flash_color)
        fill_color.setAlpha(45)
        for layer, ids in added_by_layer:
            ids = [fid for fid in ids if fid is not None and fid >= 0]
            if not ids:
                continue
            request = QgsFeatureRequest().setFilterFids(ids)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                if layer.geometryType() in (Qgis.GeometryType.Line, Qgis.GeometryType.Polygon):
                    band = QgsRubberBand(canvas, layer.geometryType())
                    try:
                        band.setStrokeColor(flash_color)
                        band.setFillColor(fill_color if layer.geometryType() == Qgis.GeometryType.Polygon else QColor(0, 0, 0, 0))
                    except Exception:
                        band.setColor(flash_color)
                    band.setWidth(8 if layer.geometryType() == Qgis.GeometryType.Line else 5)
                    try:
                        band.setToGeometry(geom, layer)
                    except Exception:
                        continue
                    try:
                        band.setZValue(1200)
                    except Exception:
                        pass
                    band.show()
                    self.paste_flash_highlight_items.append(band)
                elif layer.geometryType() == Qgis.GeometryType.Point:
                    points = geom.asMultiPoint() if geom.isMultipart() else [geom.asPoint()]
                    for point in points:
                        marker = QgsVertexMarker(canvas)
                        marker.setCenter(QgsPointXY(point))
                        marker.setColor(flash_color)
                        marker.setIconSize(18)
                        marker.setPenWidth(6)
                        try:
                            marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
                        except Exception:
                            try:
                                marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
                            except Exception:
                                pass
                        try:
                            marker.setZValue(1200)
                        except Exception:
                            pass
                        self.paste_flash_highlight_items.append(marker)
        if self.paste_flash_highlight_items:
            QTimer.singleShot(duration_ms, self.clear_paste_flash_highlight)

    def refresh_selection_highlight(self):
        self.clear_selection_highlight()
        if not self.inspection_enabled:
            return
        canvas = self.iface.mapCanvas()
        yellow = QColor("#ffd400")
        yellow.setAlpha(255)
        for layer in self.selectable_inspection_layers():
            if layer.geometryType() not in (Qgis.GeometryType.Line, Qgis.GeometryType.Point):
                continue
            ids = list(layer.selectedFeatureIds())
            if not ids:
                continue
            request = QgsFeatureRequest().setFilterFids(ids)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                if layer.geometryType() == Qgis.GeometryType.Line:
                    band = QgsRubberBand(canvas, Qgis.GeometryType.Line)
                    band.setStrokeColor(yellow)
                    band.setWidth(5)
                    try:
                        band.setToGeometry(geom, layer)
                    except Exception:
                        continue
                    band.show()
                    self.selection_highlight_items.append(band)
                else:
                    points = geom.asMultiPoint() if geom.isMultipart() else [geom.asPoint()]
                    for point in points:
                        marker = QgsVertexMarker(canvas)
                        marker.setCenter(QgsPointXY(point))
                        marker.setColor(yellow)
                        marker.setIconSize(11)
                        marker.setPenWidth(5)
                        try:
                            marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
                        except Exception:
                            try:
                                marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
                            except Exception:
                                pass
                        try:
                            marker.setZValue(1100)
                        except Exception:
                            pass
                        self.selection_highlight_items.append(marker)

    def yellow_select_cursor(self):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#202020"), 4))
        painter.drawLine(12, 1, 12, 23)
        painter.drawLine(1, 12, 23, 12)
        painter.setPen(QPen(QColor("#ffd400"), 2))
        painter.drawLine(12, 1, 12, 23)
        painter.drawLine(1, 12, 23, 12)
        painter.end()
        return QCursor(pixmap, 12, 12)

    def red_edit_cursor(self):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#202020"), 4))
        painter.drawLine(12, 1, 12, 23)
        painter.drawLine(1, 12, 23, 12)
        painter.setPen(QPen(QColor("#ff2020"), 2))
        painter.drawLine(12, 1, 12, 23)
        painter.drawLine(1, 12, 23, 12)
        painter.end()
        return QCursor(pixmap, 12, 12)

    def move_cursor(self):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#202020"), 4))
        painter.drawLine(12, 2, 12, 22)
        painter.drawLine(2, 12, 22, 12)
        painter.drawLine(12, 2, 8, 6)
        painter.drawLine(12, 2, 16, 6)
        painter.drawLine(12, 22, 8, 18)
        painter.drawLine(12, 22, 16, 18)
        painter.drawLine(2, 12, 6, 8)
        painter.drawLine(2, 12, 6, 16)
        painter.drawLine(22, 12, 18, 8)
        painter.drawLine(22, 12, 18, 16)
        painter.setPen(QPen(QColor("#ffd400"), 2))
        painter.drawLine(12, 2, 12, 22)
        painter.drawLine(2, 12, 22, 12)
        painter.drawLine(12, 2, 8, 6)
        painter.drawLine(12, 2, 16, 6)
        painter.drawLine(12, 22, 8, 18)
        painter.drawLine(12, 22, 16, 18)
        painter.drawLine(2, 12, 6, 8)
        painter.drawLine(2, 12, 6, 16)
        painter.drawLine(22, 12, 18, 8)
        painter.drawLine(22, 12, 18, 16)
        painter.end()
        return QCursor(pixmap, 12, 12)

    def switch_to_pan(self):
        if self.operation_mode == "edit":
            self.finish_edit_mode(defer_pan=True, return_to_selection_after=False)
            return
        self.clear_feature_move_preview()
        self.feature_move_targets = []
        self.feature_move_undo_stack = []
        if self.operation_mode == "restore":
            self.clear_trash_selection()
            self.set_trash_layers_visible(False)
        self.clear_inspection_selection()
        self.operation_mode = "pan"
        try:
            viewport = self.iface.mapCanvas().viewport()
            if viewport:
                viewport.unsetCursor()
        except Exception:
            pass
        try:
            self.iface.actionPan().trigger()
        except Exception:
            try:
                canvas = self.iface.mapCanvas()
                if self.map_tool and canvas.mapTool() == self.map_tool:
                    canvas.unsetMapTool(self.map_tool)
            except Exception:
                pass
        self.refresh_ui()
        self.set_status(tr_text("パンモード"))

    def switch_to_pan_if_still_create(self):
        if self.operation_mode in ("create", "pan_pending"):
            self.switch_to_pan()

    def remember_create_return_mode(self):
        if self.operation_mode == "pan":
            self.create_return_mode = "pan"
        elif self.operation_mode == "select_polygon":
            self.create_return_mode = "select_polygon"
            self.last_selection_mode = "select_polygon"
        elif self.operation_mode == "select":
            self.create_return_mode = "select"
            self.last_selection_mode = "select"

    def return_to_pre_create_mode_if_still_create(self):
        if self.operation_mode not in ("create", "pan_pending"):
            return
        if self.create_return_mode in ("select", "select_polygon"):
            self.return_to_last_selection_mode()
        else:
            self.switch_to_pan()

    def finish_edit_for_mode_switch(self):
        self.clear_feature_move_preview()
        self.feature_move_targets = []
        self.clear_edit_overlap_candidates()
        self.clear_direct_overlap_vertex_edit()
        if self.operation_mode == "edit":
            self.finish_edit_mode(switch_to_pan_after=False)
            self.operation_mode = "pan_pending"
            self.clear_inspection_selection()
            return True
        return False

    def install_context_filter(self):
        canvas = self.iface.mapCanvas()
        viewport = canvas.viewport()
        if not viewport:
            return
        if self.context_filter_canvas and self.context_filter_canvas != viewport:
            self.remove_context_filter()
        if self.context_filter_canvas != viewport:
            viewport.installEventFilter(self)
            self.context_filter_canvas = viewport

    def remove_context_filter(self):
        if self.context_filter_canvas:
            try:
                self.context_filter_canvas.removeEventFilter(self)
            except Exception:
                pass
            self.context_filter_canvas = None

    def eventFilter(self, obj, event):
        source = "CANVAS_FILTER" if obj == self.context_filter_canvas else "APP_FILTER"
        if self.handle_feature_clipboard_event_filter_key(event, source=source):
            return True
        if self.inspection_enabled and obj == self.context_filter_canvas:
            if self.suppress_next_context_menu and event.type() == QEvent.Type.ContextMenu:
                self.suppress_next_context_menu = False
                try:
                    event.accept()
                except Exception:
                    pass
                return True
            if self.operation_mode == "move" and event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonRelease,
            ):
                try:
                    if self.iface.mapCanvas().mapTool() != self.map_tool:
                        self.ensure_map_tool()
                    else:
                        self.update_map_cursor()
                except Exception:
                    pass
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                self.right_button_guard_active = True
                if self.operation_mode == "move":
                    try:
                        event.accept()
                    except Exception:
                        pass
                    if self.map_tool:
                        self.map_tool._clear_move_state()
                    self.return_to_last_selection_mode("移動終了")
                    return True
                if self.operation_mode in ("select_polygon", "layer_change_select_polygon") and self.map_tool and self.map_tool.select_polygon_points:
                    try:
                        event.accept()
                    except Exception:
                        pass
                    self.suppress_next_context_menu = True
                    self.map_tool._finish_select_polygon()
                    return True
                if self.operation_mode == "create" and self.map_tool and self.map_tool.points:
                    try:
                        event.accept()
                    except Exception:
                        pass
                    self.map_tool._finish_capture()
                    return True
                if self.operation_mode == "edit":
                    try:
                        event.accept()
                    except Exception:
                        pass
                    point = self.map_point_from_mouse_event(event)
                    if point and self.switch_direct_overlap_vertex_candidate_at(point):
                        return True
                    self.finish_edit_mode(defer_pan=True)
                    return True
                self.suppress_next_context_menu = False
                try:
                    global_pos = event.globalPosition().toPoint()
                except Exception:
                    try:
                        global_pos = event.globalPos()
                    except Exception:
                        global_pos = obj.mapToGlobal(event.pos())
                self.show_context_menu(global_pos)
                return True
            if self.right_button_guard_active:
                if event.type() == QEvent.Type.MouseMove:
                    try:
                        if event.buttons() & Qt.MouseButton.RightButton:
                            event.accept()
                            return True
                    except Exception:
                        pass
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
                    self.right_button_guard_active = False
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
            if self.operation_mode == "edit":
                if (
                    event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                    and self.just_finished_direct_overlap_vertex_edit
                ):
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    point = self.map_point_from_mouse_event(event)
                    if point:
                        self.suspend_edit_hover_prepare = False
                        self.remember_edit_overlap_anchor_at(point)
                if (
                    event.type() == QEvent.Type.MouseMove
                    and self.has_direct_overlap_vertex_edit()
                    and self.map_tool
                    and self.map_tool.edit_vertex_start_point
                ):
                    point = self.direct_overlap_point_from_mouse_event(event, use_snap=True)
                    if point:
                        self.map_tool.edit_vertex_dragging = True
                        self.update_direct_overlap_vertex_preview(point)
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                if (
                    event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                    and self.has_direct_overlap_vertex_edit()
                    and self.map_tool
                    and self.map_tool.edit_vertex_start_point
                ):
                    if self.ignore_next_direct_overlap_release:
                        self.ignore_next_direct_overlap_release = False
                        try:
                            event.accept()
                        except Exception:
                            pass
                        return True
                    try:
                        end_pixel = event.position().toPoint()
                    except Exception:
                        end_pixel = event.pos()
                    start_pixel = self.map_tool.edit_vertex_start_pixel
                    moved = False
                    try:
                        moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
                    except Exception:
                        moved = self.map_tool.edit_vertex_dragging
                    point = self.direct_overlap_point_from_mouse_event(event, use_snap=True)
                    self.map_tool._clear_direct_vertex_state()
                    if moved and point:
                        self.finish_direct_overlap_vertex_move(point)
                    else:
                        self.clear_direct_overlap_vertex_preview()
                    self.clear_direct_overlap_vertex_edit()
                    self.clear_edit_overlap_anchor()
                    self.stop_qgis_vertex_tool_for_direct_overlap()
                    self.just_finished_direct_overlap_vertex_edit = True
                    self.suspend_edit_hover_prepare = False
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                if event.type() == QEvent.Type.MouseMove:
                    if self.just_finished_direct_overlap_vertex_edit:
                        self.just_finished_direct_overlap_vertex_edit = False
                    if self.suspend_edit_hover_prepare:
                        self.update_map_cursor()
                        return super().eventFilter(obj, event)
                    try:
                        if event.buttons() & Qt.MouseButton.LeftButton:
                            self.update_map_cursor()
                            return super().eventFilter(obj, event)
                    except Exception:
                        pass
                    if not self.has_direct_overlap_vertex_edit():
                        point = self.map_point_from_mouse_event(event)
                        if point:
                            self.prepare_edit_layer_at(point, activate_tool=True, quiet=True)
                    self.update_map_cursor()
            elif self.operation_mode == "move" and event.type() == QEvent.Type.MouseMove:
                self.update_map_cursor()
        return super().eventFilter(obj, event)

    def map_point_from_mouse_event(self, event):
        try:
            pos = event.position().toPoint()
        except Exception:
            pos = event.pos()
        try:
            return self.iface.mapCanvas().getCoordinateTransform().toMapCoordinates(pos.x(), pos.y())
        except Exception:
            return None

    def direct_overlap_point_from_mouse_event(self, event, use_snap=True):
        if self.map_tool:
            try:
                return self.map_tool._event_map_point(event, use_snap=use_snap)
            except Exception:
                pass
        return self.map_point_from_mouse_event(event)

    def close_current_context_menu(self, keep_menu=None):
        menu = getattr(self, "current_context_menu", None)
        if not menu or menu is keep_menu:
            return
        self.current_context_menu = None
        try:
            menu.close()
        except Exception:
            pass
        try:
            menu.deleteLater()
        except Exception:
            pass

    def clear_current_context_menu(self, menu):
        if getattr(self, "current_context_menu", None) is menu:
            self.current_context_menu = None
        try:
            menu.deleteLater()
        except Exception:
            pass

    def show_context_menu(self, global_pos):
        self.close_current_context_menu()
        menu = QMenu()
        self.current_context_menu = menu
        try:
            menu.aboutToHide.connect(lambda m=menu: self.clear_current_context_menu(m))
        except Exception:
            pass
        self.populate_context_menu(menu, global_pos)
        menu.exec(global_pos)
        return

    def delete_confirm_enabled(self):
        try:
            value = QgsSettings().value(INSPECTION_DELETE_CONFIRM_KEY, True)
        except Exception:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off", "")

    def set_delete_confirm_enabled(self, enabled):
        try:
            QgsSettings().setValue(INSPECTION_DELETE_CONFIRM_KEY, bool(enabled))
        except Exception:
            pass

    def confirm_delete_if_needed(self, title, message):
        if not self.delete_confirm_enabled():
            return True
        return QMessageBox.question(self, title, message) == QMessageBox.StandardButton.Yes

    def layer_change_confirm_enabled(self):
        try:
            value = QgsSettings().value(INSPECTION_LAYER_CHANGE_CONFIRM_KEY, True)
        except Exception:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off", "")

    def set_layer_change_confirm_enabled(self, enabled):
        try:
            QgsSettings().setValue(INSPECTION_LAYER_CHANGE_CONFIRM_KEY, bool(enabled))
        except Exception:
            pass

    def confirm_layer_change_if_needed(self, target_layer, total_count):
        if not self.layer_change_confirm_enabled():
            return True
        return QMessageBox.question(
            self,
            tr_text("移層"),
            tr_text(f"選択中の {total_count} 件を「{self.layer_base_name(target_layer)}」へ移層しますか？"),
        ) == QMessageBox.StandardButton.Yes

    def inspection_shortcut_defaults(self):
        return {key: default_value for key, _label, default_value in INSPECTION_SHORTCUT_DEFINITIONS}

    def normalize_shortcut_text(self, text):
        text = str(text or "").strip()
        if "," in text:
            text = text.split(",", 1)[0].strip()
        replacements = {
            "Delete": "Del",
            "Del.": "Del",
            "Return": "Enter",
            "PgUp": "PageUp",
            "PgDown": "PageDown",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.replace(" ", "").lower()

    def valid_hold_shortcut_text(self, text):
        norm = self.normalize_shortcut_text(text)
        if not norm or "+" in norm:
            return False
        blocked = {
            "ctrl",
            "control",
            "shift",
            "alt",
            "meta",
            "esc",
            "escape",
            "backspace",
            "del",
            "delete",
            "space",
            "enter",
            "return",
            "tab",
        }
        return norm not in blocked

    def hold_shortcut_key_from_event(self, event):
        event_text = self.shortcut_text_from_event(event)
        if not event_text:
            return ""
        event_norm = self.normalize_shortcut_text(event_text)
        for key in INSPECTION_HOLD_SHORTCUT_KEYS:
            value = self.inspection_shortcuts().get(key, "")
            if value and self.normalize_shortcut_text(value) == event_norm:
                return key
        return ""

    def inspection_shortcuts(self):
        settings = QgsSettings()
        shortcuts = self.inspection_shortcut_defaults()
        for key in shortcuts:
            try:
                value = settings.value(INSPECTION_SHORTCUTS_KEY_PREFIX + key, shortcuts[key])
            except Exception:
                value = shortcuts[key]
            if key == "parallel_direction_copy" and self.normalize_shortcut_text(value) in ("s", "f"):
                value = "Z"
                try:
                    settings.setValue(INSPECTION_SHORTCUTS_KEY_PREFIX + key, value)
                except Exception:
                    pass
            shortcuts[key] = str(value or "").strip()
        return shortcuts
    def inspection_angle_snap_degrees(self):
        try:
            value = QgsSettings().value(INSPECTION_ANGLE_SNAP_DEGREES_KEY, INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES)
            degrees = int(value)
        except Exception:
            degrees = INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES
        if degrees not in INSPECTION_ANGLE_SNAP_ALLOWED_DEGREES:
            return INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES
        return degrees

    def save_inspection_angle_snap_degrees(self, degrees):
        try:
            degrees = int(degrees)
        except Exception:
            degrees = INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES
        if degrees not in INSPECTION_ANGLE_SNAP_ALLOWED_DEGREES:
            degrees = INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES
        try:
            QgsSettings().setValue(INSPECTION_ANGLE_SNAP_DEGREES_KEY, degrees)
        except Exception:
            pass

    def inspection_angle_snap_basis(self):
        try:
            basis = str(QgsSettings().value(INSPECTION_ANGLE_SNAP_BASIS_KEY, INSPECTION_ANGLE_SNAP_BASIS_DEFAULT) or "")
        except Exception:
            basis = INSPECTION_ANGLE_SNAP_BASIS_DEFAULT
        if basis not in INSPECTION_ANGLE_SNAP_BASIS_ALLOWED:
            return INSPECTION_ANGLE_SNAP_BASIS_DEFAULT
        return basis

    def save_inspection_angle_snap_basis(self, basis):
        if basis not in INSPECTION_ANGLE_SNAP_BASIS_ALLOWED:
            basis = INSPECTION_ANGLE_SNAP_BASIS_DEFAULT
        try:
            QgsSettings().setValue(INSPECTION_ANGLE_SNAP_BASIS_KEY, basis)
        except Exception:
            pass

    def save_inspection_shortcuts(self, shortcuts):
        settings = QgsSettings()
        for key, _label, default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            try:
                settings.setValue(INSPECTION_SHORTCUTS_KEY_PREFIX + key, shortcuts.get(key, default_value) or "")
            except Exception:
                pass

    def open_inspection_shortcut_dialog(self):
        dialog = InspectionShortcutDialog(self, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if values is None:
            return
        self.save_inspection_shortcuts(values)
        self.save_inspection_angle_snap_degrees(dialog.angle_snap_degrees())
        self.save_inspection_angle_snap_basis(dialog.angle_snap_basis())
        self.refresh_inspection_qshortcuts()
        self.set_status(tr_text("✅ 検査ショートカットを保存しました"))

    def shortcut_focus_allows_run(self):
        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QKeySequenceEdit)):
            return False
        return True

    def refresh_inspection_qshortcuts(self):
        for shortcut in getattr(self, "inspection_qshortcuts", []):
            try:
                shortcut.setEnabled(False)
                shortcut.deleteLater()
            except Exception:
                pass
        self.inspection_qshortcuts = []
        for key, value in self.inspection_shortcuts().items():
            if key in INSPECTION_HOLD_SHORTCUT_KEYS:
                continue
            if not value:
                continue
            sequence = QKeySequence(value)
            if sequence.isEmpty():
                continue
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda k=key: self.run_qshortcut(k))
            self.inspection_qshortcuts.append(shortcut)

    def run_qshortcut(self, key):
        if not self.inspection_enabled or not self.shortcut_focus_allows_run():
            return False
        return self.run_inspection_shortcut(key)
    def shortcut_text_from_event(self, event):
        key = event.key()
        modifier_keys = {
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }
        if key in modifier_keys:
            return ""
        key_text = ""
        try:
            typed = event.text()
        except Exception:
            typed = ""
        if typed and typed.strip() and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            key_text = typed.strip().upper()
        if not key_text:
            key_text = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText).strip()
        if not key_text:
            return ""
        modifiers = event.modifiers()
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("Meta")
        parts.append(key_text)
        return "+".join(parts)

    def handle_shortcut_key(self, event):
        if not self.inspection_enabled:
            return False
        event_text = self.shortcut_text_from_event(event)
        if not event_text:
            return False
        event_norm = self.normalize_shortcut_text(event_text)
        for key, value in self.inspection_shortcuts().items():
            if key in INSPECTION_HOLD_SHORTCUT_KEYS:
                continue
            if value and self.normalize_shortcut_text(value) == event_norm:
                return self.run_inspection_shortcut(key)
        return False

    def run_inspection_shortcut(self, key):
        if key == "delete" and self.operation_mode == "edit":
            self.forward_qgis_vertex_tool_key(Qt.Key.Key_Delete)
            return True
        actions = {
            "pan": self.switch_to_pan,
            "select": self.start_select,
            "select_polygon": self.start_select_polygon,
            "layer_change": self.start_layer_change,
            "restore": self.start_restore_mode,
            "delete": self.start_delete,
            "edit": self.start_edit,
            "move": self.start_move,
            "merge": self.start_merge,
        }
        if key in actions:
            actions[key]()
            return True
        if key == "continuous":
            self.set_continuous_capture(not self.continuous_capture_enabled)
            state = "ON" if self.continuous_capture_enabled else "OFF"
            self.set_status(tr_text(f"連続: {state}"))
            return True
        shape_map = {
            "shape_polygon": ("polygon", "polygon", "多角"),
            "shape_fixed_angle_90": ("polygon", "fixed_angle_90", "直角多角"),
            "shape_rectangle": ("polygon", "rectangle", "矩形"),
            "shape_ellipse": ("polygon", "ellipse", "楕円"),
            "shape_circle": ("polygon", "circle", "正円"),
            "shape_line": ("line", None, "ライン"),
            "shape_point": ("point", None, "点"),
        }
        if key in shape_map:
            geom_key, shape, label = shape_map[key]
            return self.activate_shape_shortcut(geom_key, shape, label)
        return False

    def activate_shape_shortcut(self, geom_key, shape, label):
        layer = self.active_layer()
        if not layer:
            self.set_status(tr_text("検査項目を選択してください"))
            return True
        layer_geom = self.layer_geom_type_key(layer)
        if layer_geom != geom_key:
            layer_label = GEOM_TYPE_LABELS.get(layer_geom, "不明")
            target_label = GEOM_TYPE_LABELS.get(geom_key, label)
            self.set_status(tr_text(f"この検査項目は{layer_label}です。{target_label}入力には切り替えられません"))
            return True
        self.finish_edit_for_mode_switch()
        self.active_geom_type = geom_key
        if shape:
            self.active_capture_shape = shape
        self.operation_mode = "create"
        self.iface.setActiveLayer(layer)
        self.ensure_map_tool()
        self.set_status(tr_text(f"検査入力: {self.layer_base_name(layer)} / {label}"))
        return True
    def start_layer_change(self):
        self.finish_edit_for_mode_switch()
        if not self.selected_vector_targets():
            self.restart_layer_change_selection()
            return
        self.operation_mode = "layer_change"
        self.ensure_map_tool()
        self.set_status(tr_text("移層: 右クリックメニューから移動先項目を選択してください"))
        QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))

    def restart_layer_change_selection(self):
        self.finish_edit_for_mode_switch()
        if self.map_tool:
            self.map_tool._clear_select_band()
            self.map_tool._clear_select_polygon()
        if self.last_selection_mode == "select_polygon":
            self.operation_mode = "layer_change_select_polygon"
            self.ensure_map_tool()
            self.set_status(tr_text("移層: 多角選で移動対象を再選択してください"))
            return
        self.operation_mode = "layer_change_select"
        self.ensure_map_tool()
        self.set_status(tr_text("移層: 移動対象を再選択してください"))

    def cancel_layer_change(self):
        self.switch_to_pan()

    def start_restore_mode(self):
        self.finish_edit_for_mode_switch()
        has_trash = False
        for geom_type in TRASH_LAYER_SOURCES:
            layer = self.ensure_trash_layer(geom_type, visible=True)
            if layer and layer.featureCount() > 0:
                has_trash = True
        if not has_trash:
            self.set_status(tr_text("復帰: ゴミ箱に図形がありません"))
            return
        self.operation_mode = "restore"
        self.ensure_map_tool()
        self.update_map_cursor()
        self.set_status(tr_text("復帰: グレー表示のゴミ箱図形を選択してください"))

    def cancel_restore_mode(self):
        self.clear_trash_selection()
        self.set_trash_layers_visible(False)
        self.return_to_last_selection_mode("復帰モードを終了しました")

    def set_trash_layers_visible(self, visible):
        for layer in self.trash_layers():
            self.set_layer_tree_visibility(layer, visible)
            try:
                layer.triggerRepaint()
            except Exception:
                pass
        try:
            self.iface.mapCanvas().refresh()
        except Exception:
            pass

    def clear_trash_selection(self):
        for layer in self.trash_layers():
            try:
                layer.removeSelection()
            except Exception:
                pass

    def start_select(self):
        self.finish_edit_for_mode_switch()
        if self.map_tool:
            self.map_tool._clear_select_polygon()
        self.last_selection_mode = "select"
        self.operation_mode = "select"
        self.ensure_map_tool()
        self.set_status(tr_text("矩形選: クリック、またはドラッグで範囲選択してください"))

    def start_select_polygon(self):
        self.finish_edit_for_mode_switch()
        if self.map_tool:
            self.map_tool._clear_select_band()
        self.last_selection_mode = "select_polygon"
        self.operation_mode = "select_polygon"
        self.ensure_map_tool()
        self.set_status(tr_text("多角選: 左クリックで頂点追加、右クリックで確定"))

    def return_to_last_selection_mode(self, status_text=""):
        if self.last_selection_mode == "select_polygon":
            self.operation_mode = "select_polygon"
            self.ensure_map_tool()
            self.set_status(status_text or tr_text("多角選: 左クリックで頂点追加、右クリックで確定"))
            return
        self.operation_mode = "select"
        self.ensure_map_tool()
        self.set_status(status_text or tr_text("矩形選: クリック、またはドラッグで範囲選択してください"))

    def start_delete(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon"):
            self.set_status(tr_text("移層中です。パンで解除してください"))
            return
        if self.delete_selected_features():
            return
        self.set_status(tr_text("先に地物選択で削除対象を選択してください"))

    def start_move(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon"):
            self.set_status(tr_text("移層中です。パンで解除してください"))
            return
        if self.operation_mode != "move":
            self.feature_move_undo_stack = []
        self.operation_mode = "move"
        self.ensure_map_tool_soon()
        if self.selected_vector_targets():
            self.set_status(tr_text("移動: 選択データをドラッグしてください"))
        else:
            self.set_status(tr_text("移動: 動かしたい検査データをクリックしてドラッグしてください"))


    def start_merge(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon"):
            self.set_status(tr_text("移層中です。パンで解除してください"))
            return
        if self.merge_selected_features():
            return
        self.set_status(tr_text("先に地物選択で統合対象を選択してください"))

    def _search_rect(self, point, tolerance_factor=8):
        canvas = self.iface.mapCanvas()
        tol = canvas.mapUnitsPerPixel() * tolerance_factor
        return QgsRectangle(point.x() - tol, point.y() - tol, point.x() + tol, point.y() + tol)

    def rectangle_from_points(self, point_a, point_b):
        return QgsRectangle(
            min(point_a.x(), point_b.x()),
            min(point_a.y(), point_b.y()),
            max(point_a.x(), point_b.x()),
            max(point_a.y(), point_b.y()),
        )

    def geometry_from_shape(self, shape, point_a, point_b, center_mode=False):
        if shape == "rectangle":
            rect = self.rectangle_from_points(point_a, point_b)
            pts = [
                QgsPointXY(rect.xMinimum(), rect.yMinimum()),
                QgsPointXY(rect.xMaximum(), rect.yMinimum()),
                QgsPointXY(rect.xMaximum(), rect.yMaximum()),
                QgsPointXY(rect.xMinimum(), rect.yMaximum()),
                QgsPointXY(rect.xMinimum(), rect.yMinimum()),
            ]
            return QgsGeometry.fromPolygonXY([pts])
        if shape in ("ellipse", "circle"):
            x1, y1 = point_a.x(), point_a.y()
            x2, y2 = point_b.x(), point_b.y()
            if center_mode:
                cx, cy = x1, y1
                if shape == "circle":
                    radius = math.hypot(x2 - x1, y2 - y1)
                    rx = radius
                    ry = radius
                else:
                    rx = abs(x2 - x1)
                    ry = abs(y2 - y1)
            else:
                if shape == "circle":
                    side = min(abs(x2 - x1), abs(y2 - y1))
                    x2 = x1 + (side if x2 >= x1 else -side)
                    y2 = y1 + (side if y2 >= y1 else -side)
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                rx = abs(x2 - x1) / 2.0
                ry = abs(y2 - y1) / 2.0
            if rx <= 0 or ry <= 0:
                return None
            pts = []
            for idx in range(49):
                angle = 2.0 * math.pi * idx / 48.0
                pts.append(QgsPointXY(cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
            return QgsGeometry.fromPolygonXY([pts])
        return None

    def find_feature_at(self, point, allow_polygon_fill=False, tolerance_factor=8):
        self.refresh_pending_data_change_layers()
        rect = self._search_rect(point, tolerance_factor=tolerance_factor)
        rect_geom = QgsGeometry.fromRect(rect)
        point_geom = QgsGeometry.fromPointXY(point)
        tolerance = max(rect.width(), rect.height()) / 2.0
        candidates = []
        for layer in reversed(self.selectable_inspection_layers()):
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom:
                    continue
                if layer.geometryType() == Qgis.GeometryType.Polygon:
                    if allow_polygon_fill and (geom.contains(point_geom) or geom.intersects(rect_geom)):
                        try:
                            area = geom.area()
                        except Exception:
                            area = 0
                        candidates.append((area, layer, feature))
                        continue
                    if self.polygon_edges_hit_rect(geom, rect_geom):
                        return layer, feature
                elif geom.intersects(rect_geom):
                    return layer, feature
                else:
                    try:
                        if geom.distance(point_geom) <= tolerance:
                            return layer, feature
                    except Exception:
                        pass
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1], candidates[0][2]
        return None, None






















    def geometry_hits_selection_rect(self, layer, geom, rect_geom):
        if not geom:
            return False
        if layer.geometryType() == Qgis.GeometryType.Polygon:
            return self.polygon_edges_hit_rect(geom, rect_geom)
        return geom.intersects(rect_geom)

    def polygon_edges_hit_rect(self, geom, rect_geom):
        rings_list = []
        try:
            polygon = geom.asPolygon()
            if polygon:
                rings_list.append(polygon)
        except Exception:
            pass
        try:
            multi = geom.asMultiPolygon()
            if multi:
                rings_list.extend(multi)
        except Exception:
            pass
        for polygon in rings_list:
            for ring in polygon:
                if len(ring) < 2:
                    continue
                last_index = len(ring) - 1
                for idx in range(len(ring)):
                    next_idx = idx + 1 if idx < last_index else 0
                    if idx == last_index and ring[idx] == ring[0]:
                        continue
                    edge = QgsGeometry.fromPolylineXY([QgsPointXY(ring[idx]), QgsPointXY(ring[next_idx])])
                    if edge.intersects(rect_geom):
                        return True
        return False

    def select_feature_at(self, point, modifiers=Qt.KeyboardModifier.NoModifier):
        layer, feature = self.find_feature_at(point, allow_polygon_fill=True)
        if not layer:
            if not (modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
                self.clear_inspection_selection()
            if self.operation_mode in ("layer_change_select", "layer_change_select_polygon"):
                self.set_status(tr_text("移層: 移動する検査図形を選択してください"))
            else:
                self.set_status(tr_text("選択解除"))
            self.refresh_selection_highlight()
            return False
        current = set(layer.selectedFeatureIds())
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            current.discard(feature.id())
            layer.selectByIds(list(current))
        else:
            if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
                self.clear_inspection_selection()
                current = set()
            current.add(feature.id())
        layer.selectByIds(list(current))
        self.refresh_selection_highlight()
        self.iface.setActiveLayer(layer)
        if self.operation_mode in ("layer_change_select", "layer_change_select_polygon"):
            self.update_map_cursor()
            self.set_status(tr_text("移層: 選択中。右クリックで変更先を選択してください"))
        else:
            self.set_status(tr_text(f"選択: {self.display_layer_name(layer)}"))
        return True

    def select_features_in_rect(self, rect, modifiers=Qt.KeyboardModifier.NoModifier):
        rect_geom = QgsGeometry.fromRect(rect)
        total = 0
        selected_layers = []
        for layer in self.selectable_inspection_layers():
            ids = []
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                geom = feature.geometry()
                if self.geometry_hits_selection_rect(layer, geom, rect_geom):
                    ids.append(feature.id())
            current = set(layer.selectedFeatureIds())
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                current.difference_update(ids)
            elif modifiers & Qt.KeyboardModifier.ShiftModifier:
                current.update(ids)
            else:
                current = set(ids)
            layer.selectByIds(list(current))
            if current:
                total += len(current)
                selected_layers.append(layer)
        if len(selected_layers) == 1:
            self.iface.setActiveLayer(selected_layers[0])
        elif selected_layers:
            self.iface.setActiveLayer(selected_layers[0])
        self.refresh_selection_highlight()
        if total:
            if self.operation_mode in ("layer_change_select", "layer_change_select_polygon"):
                self.update_map_cursor()
                self.set_status(tr_text(f"移層: {total} 件選択中。右クリックで変更先を選択してください"))
            else:
                self.set_status(tr_text(f"選択: {total} 件"))
        else:
            if self.operation_mode in ("layer_change_select", "layer_change_select_polygon"):
                self.set_status(tr_text("移層: 移動する検査図形を選択してください"))
            else:
                self.set_status(tr_text("選択解除"))
        return total > 0

    def select_features_in_geometry(self, selection_geom, modifiers=Qt.KeyboardModifier.NoModifier):
        if not selection_geom or selection_geom.isEmpty():
            self.set_status(tr_text("多角選: 範囲が無効です"))
            return False
        total = 0
        selected_layers = []
        try:
            rect = selection_geom.boundingBox()
        except Exception:
            rect = QgsRectangle()
        for layer in self.selectable_inspection_layers():
            ids = []
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if geom and geom.intersects(selection_geom):
                    ids.append(feature.id())
            current = set(layer.selectedFeatureIds())
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                current.difference_update(ids)
            elif modifiers & Qt.KeyboardModifier.ShiftModifier:
                current.update(ids)
            else:
                current = set(ids)
            layer.selectByIds(list(current))
            if current:
                total += len(current)
                selected_layers.append(layer)
        if selected_layers:
            self.iface.setActiveLayer(selected_layers[0])
        self.refresh_selection_highlight()
        if self.operation_mode == "layer_change_select_polygon":
            self.update_map_cursor()
            if total:
                self.set_status(tr_text(f"移層: {total} 件選択中。右クリックで変更先を選択してください"))
            else:
                self.set_status(tr_text("移層: 移動する検査図形を選択してください"))
        else:
            self.set_status(tr_text(f"多角選: {total} 件") if total else tr_text("多角選: 選択解除"))
        return total > 0

    def clear_inspection_selection(self):
        for layer in self.selectable_inspection_layers():
            try:
                layer.removeSelection()
            except Exception:
                pass
        self.clear_selection_highlight()

    def restore_feature_move_selection(self, targets):
        restored_targets = []
        for layer, ids in targets:
            ids = list(ids or [])
            if not layer or not ids:
                continue
            try:
                layer.selectByIds(ids)
                restored_targets.append((layer, ids))
            except Exception:
                pass
        if restored_targets:
            self.feature_move_targets = restored_targets
        self.refresh_selection_highlight()
        if self.operation_mode == "move":
            self.ensure_map_tool_soon()

    def selected_trash_targets(self):
        targets = []
        for layer in self.trash_layers():
            try:
                ids = layer.selectedFeatureIds()
            except Exception:
                ids = []
            if ids:
                targets.append((layer, list(ids)))
        return targets

    def select_trash_feature_at(self, point, modifiers=Qt.KeyboardModifier.NoModifier):
        found_layer, found_feature = self.find_trash_feature_at(point)
        if not found_layer:
            if not (modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
                self.clear_trash_selection()
                self.clear_inspection_selection()
            self.set_status(tr_text("復帰: ゴミ箱図形を選択してください"))
            return False
        current = set(found_layer.selectedFeatureIds())
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            current.discard(found_feature.id())
        else:
            if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
                self.clear_trash_selection()
                self.clear_inspection_selection()
                current = set()
            current.add(found_feature.id())
        found_layer.selectByIds(list(current))
        self.set_status(tr_text(f"復帰: {sum(len(ids) for _layer, ids in self.selected_trash_targets())} 件選択中。右クリックで操作してください"))
        return True

    def select_trash_features_in_rect(self, rect, modifiers=Qt.KeyboardModifier.NoModifier):
        rect_geom = QgsGeometry.fromRect(rect)
        total = 0
        replace_selection = not (modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        if replace_selection:
            self.clear_inspection_selection()
        for layer in self.trash_layers():
            if not layer or not layer.isValid():
                continue
            ids = []
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                geom = feature.geometry()
                if geom and not geom.isEmpty() and geom.intersects(rect_geom):
                    ids.append(feature.id())
            current = set(layer.selectedFeatureIds())
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                current.difference_update(ids)
            elif modifiers & Qt.KeyboardModifier.ShiftModifier:
                current.update(ids)
            else:
                current = set(ids)
            layer.selectByIds(list(current))
            total += len(current)
        if not total:
            if replace_selection:
                self.clear_trash_selection()
            self.set_status(tr_text("復帰: ゴミ箱図形を選択してください"))
            return False
        self.set_status(tr_text(f"復帰: {total} 件選択中。右クリックで操作してください"))
        return True

    def find_trash_feature_at(self, point, tolerance_factor=14):
        self.refresh_pending_data_change_layers()
        rect = self._search_rect(point, tolerance_factor=tolerance_factor)
        rect_geom = QgsGeometry.fromRect(rect)
        point_geom = QgsGeometry.fromPointXY(point)
        tolerance = max(rect.width(), rect.height()) / 2.0
        polygon_candidates = []
        for layer in reversed(self.trash_layers()):
            if not layer or not layer.isValid():
                continue
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                geom_type = self.layer_geom_type_key(layer)
                if geom_type == "polygon":
                    try:
                        if geom.contains(point_geom):
                            polygon_candidates.append((layer, feature))
                            continue
                    except Exception:
                        pass
                    try:
                        if geom.intersects(rect_geom):
                            return layer, feature
                    except Exception:
                        pass
                else:
                    try:
                        if geom.distance(point_geom) <= tolerance or geom.intersects(rect_geom):
                            return layer, feature
                    except Exception:
                        try:
                            if geom.intersects(rect_geom):
                                return layer, feature
                        except Exception:
                            pass
        if polygon_candidates:
            return polygon_candidates[0]
        return None, None

    def target_layer_for_trash_feature(self, trash_feature):
        try:
            source = trash_feature["orig_source"]
        except Exception:
            source = ""
        layer = self.find_loaded_layer_by_source(str(source or ""))
        if layer:
            return layer
        layer_id = self.layers.get(str(source or ""), {}).get("layer_id", "")
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and not self.is_trash_layer(layer):
                return layer
        return self.find_native_restore_layer_for_trash_feature(trash_feature)

    def vector_layer_provider_uri(self, layer):
        try:
            return str(layer.dataProvider().dataSourceUri() or "")
        except Exception:
            return ""

    def native_restore_layer_candidates(self, geom_type):
        candidates = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or self.is_trash_layer(layer):
                continue
            try:
                if not layer.isValid():
                    continue
            except Exception:
                pass
            try:
                if self.layer_geom_type_key(layer) != geom_type:
                    continue
            except Exception:
                continue
            candidates.append(layer)
        return candidates

    def layer_is_in_inspection_tree(self, layer):
        if not layer:
            return False
        root_names = {self.root_group_name_for_type(inspection_type) for inspection_type in INSPECTION_TYPES}
        for parent, _node in self.layer_tree_nodes_for_layer(layer.id()):
            current = parent
            while current is not None:
                try:
                    if current.name() in root_names:
                        return True
                    current = current.parent()
                except Exception:
                    break
        return False

    def choose_native_restore_layer(self, candidates, layer_name=""):
        candidates = [layer for layer in candidates if layer]
        if layer_name:
            named = []
            for layer in candidates:
                names = {str(layer.name() or ""), str(self.layer_base_name(layer) or "")}
                if layer_name in names:
                    named.append(layer)
            if named:
                candidates = named
        in_tree = [layer for layer in candidates if self.layer_is_in_inspection_tree(layer)]
        if len(in_tree) == 1:
            return in_tree[0]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def find_native_restore_layer_for_trash_feature(self, trash_feature):
        geom_type = self.trash_feature_text(trash_feature, "orig_geom_type", "polygon")
        layer_name = self.trash_feature_text(trash_feature, "orig_layer_name")
        layer_id = self.trash_feature_text(trash_feature, "orig_layer_id")
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if (
                isinstance(layer, QgsVectorLayer)
                and not self.is_trash_layer(layer)
                and self.layer_geom_type_key(layer) == geom_type
            ):
                return layer

        provider_uri = self.trash_feature_text(trash_feature, "orig_provider_uri")
        source_path = self.trash_feature_text(trash_feature, "orig_layer_source_path")
        candidates = self.native_restore_layer_candidates(geom_type)
        if provider_uri:
            layer = self.choose_native_restore_layer(
                [candidate for candidate in candidates if self.vector_layer_provider_uri(candidate) == provider_uri],
                layer_name,
            )
            if layer:
                return layer
        if source_path:
            layer = self.choose_native_restore_layer(
                [candidate for candidate in candidates if self.same_file_path(self.layer_source_path(candidate), source_path)],
                layer_name,
            )
            if layer:
                return layer
        if layer_name:
            return self.choose_native_restore_layer(candidates, layer_name)
        return None

    def restore_selected_trash_features(self):
        targets = self.selected_trash_targets()
        if not targets:
            self.set_status(tr_text("復帰: 復帰するゴミ箱図形を選択してください"))
            return False
        total_selected = sum(len(ids) for _layer, ids in targets)
        started = time.perf_counter()
        self.set_status(tr_text(f"復帰中: {total_selected} 件を元レイヤへ戻しています..."))
        QgsMessageLog.logMessage(f"RESTORE_TRASH_START selected={total_selected}", "OrthoManager", Qgis.MessageLevel.Info)
        message_item = None
        try:
            message_item = self.iface.messageBar().pushMessage(
                tr_text("復帰中"),
                tr_text(f"{total_selected} 件を元レイヤへ戻しています。完了まで操作しないでください。"),
                level=Qgis.MessageLevel.Warning,
                duration=0,
            )
        except Exception:
            message_item = None
        QApplication.processEvents()
        restored = 0
        missing = []
        missing_records = []
        self._missing_restore_cancelled = False
        restored_targets = []
        add_batches = {}
        trash_delete_batches = {}
        for trash_layer, ids in targets:
            for trash_feature in trash_layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                target_layer = self.target_layer_for_trash_feature(trash_feature)
                if not target_layer:
                    try:
                        missing_name = trash_feature["orig_layer_name"]
                    except Exception:
                        missing_name = "元レイヤ"
                    missing.append(str(missing_name or "元レイヤ"))
                    missing_records.append((trash_layer, QgsFeature(trash_feature)))
                    continue
                new_feature = QgsFeature(target_layer.fields())
                geom = trash_feature.geometry()
                if geom:
                    new_feature.setGeometry(QgsGeometry(geom))
                try:
                    self.set_restore_feature_attrs_from_json(new_feature, trash_feature["orig_attrs"], target_layer)
                except Exception:
                    pass
                target_id = target_layer.id()
                if target_id not in add_batches:
                    add_batches[target_id] = {"layer": target_layer, "features": [], "trash": []}
                add_batches[target_id]["features"].append(new_feature)
                add_batches[target_id]["trash"].append((trash_layer, trash_feature.id()))
        if missing_records:
            restored_missing = self.prepare_missing_trash_restore_batches(missing_records)
            for trash_layer, trash_feature, target_layer in restored_missing:
                new_feature = QgsFeature(target_layer.fields())
                geom = trash_feature.geometry()
                if geom:
                    new_feature.setGeometry(QgsGeometry(geom))
                try:
                    self.set_restore_feature_attrs_from_json(new_feature, trash_feature["orig_attrs"], target_layer)
                except Exception:
                    pass
                target_id = target_layer.id()
                if target_id not in add_batches:
                    add_batches[target_id] = {"layer": target_layer, "features": [], "trash": []}
                add_batches[target_id]["features"].append(new_feature)
                add_batches[target_id]["trash"].append((trash_layer, trash_feature.id()))
            if restored_missing:
                restored_keys = {
                    (trash_layer.id(), trash_feature.id())
                    for trash_layer, trash_feature, _target_layer in restored_missing
                }
                missing = [
                    name for name, (trash_layer, trash_feature) in zip(missing, missing_records)
                    if (trash_layer.id(), trash_feature.id()) not in restored_keys
                ]
        refreshed_layers = []
        for batch in add_batches.values():
            target_layer = batch["layer"]
            features = batch["features"]
            if not target_layer or not features:
                continue
            safe, error = self.close_edit_buffer_before_provider_change(target_layer)
            if not safe:
                QMessageBox.warning(self, tr_text("復帰できません"), tr_text(f"復帰先レイヤを保存できませんでした。\n{error}"))
                continue
            ok, added = target_layer.dataProvider().addFeatures(features)
            if not ok:
                error_text = self.provider_error_text(target_layer)
                QgsMessageLog.logMessage(
                    f"RESTORE_TRASH_ADD_FAILED layer={self.display_layer_name(target_layer)} "
                    f"count={len(features)} error={error_text}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                continue
            added_ids = [f.id() for f in added if f.id() is not None and f.id() >= 0]
            if added_ids:
                restored_targets.append((target_layer, added_ids))
            restored += len(features)
            refreshed_layers.append(target_layer)
            for trash_layer, trash_id in batch["trash"]:
                trash_layer_id = trash_layer.id()
                if trash_layer_id not in trash_delete_batches:
                    trash_delete_batches[trash_layer_id] = {"layer": trash_layer, "ids": []}
                trash_delete_batches[trash_layer_id]["ids"].append(trash_id)
        for batch in trash_delete_batches.values():
            trash_layer = batch["layer"]
            trash_ids = batch["ids"]
            if not trash_layer or not trash_ids:
                continue
            trash_layer.dataProvider().deleteFeatures(trash_ids)
            refreshed_layers.append(trash_layer)
        refreshed_ids = set()
        for layer in refreshed_layers:
            if not layer or layer.id() in refreshed_ids:
                continue
            refreshed_ids.add(layer.id())
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        if missing:
            unique = []
            for name in missing:
                if name not in unique:
                    unique.append(name)
            if not self._missing_restore_cancelled:
                QMessageBox.information(
                    self,
                    tr_text("元レイヤがありません"),
                    tr_text("元のレイヤが見つからないため、一部の図形は復帰しませんでした。\n"
                    + "\n".join(unique[:8])
                    + "\n\n新規復帰レイヤを作成できなかったため、復帰できませんでした。"),
                )
        if restored_targets:
            self.clear_trash_selection()
            self.clear_inspection_selection()
            merged_targets = {}
            for layer, ids in restored_targets:
                if not layer:
                    continue
                layer_id = layer.id()
                if layer_id not in merged_targets:
                    merged_targets[layer_id] = [layer, set()]
                merged_targets[layer_id][1].update(ids)
            for layer, ids in merged_targets.values():
                try:
                    layer.selectByIds(list(ids))
                except Exception:
                    pass
            self.refresh_selection_highlight()
        self.refresh_counts()
        elapsed = time.perf_counter() - started
        QgsMessageLog.logMessage(
            f"RESTORE_TRASH_DONE restored={restored} selected={total_selected} sec={elapsed:.2f}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        self.clear_message_bar_item(message_item, "復帰中")
        if restored:
            self.set_status(tr_text(f"復帰: {restored} 件を元に戻しました"))
        elif self._missing_restore_cancelled:
            self.set_status(tr_text("復帰をキャンセルしました"))
        else:
            self.set_status(tr_text("復帰できませんでした"))
        return restored > 0

    def prepare_missing_trash_restore_batches(self, missing_records):
        if not missing_records:
            return []
        count = len(missing_records)
        names = []
        for _trash_layer, trash_feature in missing_records:
            name = self.trash_feature_text(trash_feature, "orig_layer_name", "元レイヤ")
            if name not in names:
                names.append(name)
        reply = QMessageBox.question(
            self,
            tr_text("元レイヤがありません"),
            tr_text("元レイヤが見つからない図形があります。\n"
            f"{count} 件を新規復帰レイヤへ復帰しますか？\n\n"
            + "\n".join(names[:8])),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._missing_restore_cancelled = True
            return []
        grouped = {}
        for trash_layer, trash_feature in missing_records:
            key = self.trash_restore_group_key(trash_feature)
            grouped.setdefault(key, []).append((trash_layer, trash_feature))
        restored = []
        for records in grouped.values():
            target_layer = self.create_restore_target_layer(records)
            if not target_layer:
                continue
            for trash_layer, trash_feature in records:
                restored.append((trash_layer, trash_feature, target_layer))
        return restored

    def trash_feature_text(self, trash_feature, field_name, default=""):
        try:
            value = trash_feature[field_name]
        except Exception:
            value = default
        return str(value or default or "").strip()

    def trash_restore_group_key(self, trash_feature):
        return (
            self.trash_feature_text(trash_feature, "orig_source"),
            self.trash_feature_text(trash_feature, "orig_layer_name", "復帰レイヤ"),
            self.trash_feature_text(trash_feature, "orig_geom_type", "polygon"),
            self.trash_feature_text(trash_feature, "orig_inspection_type", INSPECTION_TYPE_ORTHO),
            self.trash_feature_text(trash_feature, "orig_group_name"),
            self.trash_feature_text(trash_feature, "orig_color", "ff0000"),
            self.trash_feature_text(trash_feature, "orig_round_no", "0"),
            self.trash_feature_text(trash_feature, "orig_code"),
            self.trash_feature_text(trash_feature, "orig_item_name"),
        )

    def create_restore_target_layer(self, records):
        if not records:
            return None
        _trash_layer, first_feature = records[0]
        geom_type = self.trash_feature_text(first_feature, "orig_geom_type", "polygon")
        if geom_type not in GEOM_TYPE_LABELS:
            geom_type = "polygon"
        inspection_type = self.trash_feature_text(first_feature, "orig_inspection_type", INSPECTION_TYPE_ORTHO)
        if inspection_type not in INSPECTION_TYPES:
            inspection_type = INSPECTION_TYPE_ORTHO
        group_name = self.trash_feature_text(first_feature, "orig_group_name")
        color = self.trash_feature_text(first_feature, "orig_color", "ff0000") or "ff0000"
        try:
            round_no = int(self.trash_feature_text(first_feature, "orig_round_no", "0") or 0)
        except Exception:
            round_no = 0
        code = self.trash_feature_text(first_feature, "orig_code")
        base_name = self.trash_feature_text(first_feature, "orig_layer_name", "復帰レイヤ")
        display_name = self.unique_restore_layer_display_name(f"{base_name}_復帰")
        prefix = "inspection" if inspection_type == INSPECTION_TYPE_FREE else "manual"
        source_base = f"{prefix}_{geom_type}_{display_name}"
        extra_fields = self.restore_extra_fields_from_trash_records(records)
        try:
            driver = ogr.GetDriverByName("GPKG")
            restore_path = self.ensure_gpkg_path(inspection_type)
            ds = self.open_or_create_inspection_gpkg(restore_path, driver)
            if ds is None:
                return None
            source_name = self.unique_source_layer_name(source_base, ds)
            self.create_inspection_layer(
                round_no, code, display_name, color, geom_type, custom=True,
                inspection_type=inspection_type, extra_fields=extra_fields,
                source_name_override=source_name, multi_geometry=True, dataset=ds,
            )
        except Exception as exc:
            QgsMessageLog.logMessage(f"復帰先レイヤ作成エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        finally:
            try:
                ds = None
            except Exception:
                pass
        descriptor = {
            "round_no": round_no,
            "code": code,
            "name": display_name,
            "color": color,
            "geom_type": geom_type,
            "stroke_width": self.default_stroke_width(geom_type),
            "point_size": self.default_point_size(),
            "source_name": source_name,
            "inspection_type": inspection_type,
            "group_name": group_name,
            "custom": True,
        }
        layer = self.load_layer(source_name, descriptor)
        if layer:
            QgsMessageLog.logMessage(
                f"RESTORE_TRASH_CREATED_TARGET layer={display_name} source={source_name} count={len(records)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        return layer

    def unique_restore_layer_display_name(self, base_name):
        base = str(base_name or "復帰レイヤ").strip() or "復帰レイヤ"
        used = set()
        for layer in self.inspection_layers():
            try:
                used.add(self.layer_base_name(layer))
            except Exception:
                used.add(layer.name())
        if base not in used:
            return base
        number = 2
        while True:
            candidate = f"{base}_{number}"
            if candidate not in used:
                return candidate
            number += 1

    def restore_extra_fields_from_trash_records(self, records):
        standard = {
            "fid", "fid_1", "ogc_fid", "id", "geom", "geometry",
            "memo", "round_no", "item_code", "item_name", "geom_type", "created_at", "updated_at",
        }
        names = []
        seen = set(standard)
        for _trash_layer, trash_feature in records:
            try:
                values = json.loads(trash_feature["orig_attrs"] or "{}")
            except Exception:
                values = {}
            if not isinstance(values, dict):
                continue
            for name in values.keys():
                field_name = str(name or "").strip()
                key = field_name.lower()
                if not field_name or key in seen:
                    continue
                seen.add(key)
                names.append(field_name)
        extra_fields = []
        for field_name in names:
            field = ogr.FieldDefn(field_name, ogr.OFTString)
            field.SetWidth(8000)
            extra_fields.append({"field_defn": field})
        return extra_fields

    def permanently_delete_selected_trash_features(self):
        targets = self.selected_trash_targets()
        total = sum(len(ids) for _layer, ids in targets)
        if not total:
            self.set_status(tr_text("完全削除: ゴミ箱図形を選択してください"))
            return False
        reply = QMessageBox.question(
            self,
            tr_text("完全削除"),
            tr_text(f"選択中の {total} 件をゴミ箱から完全削除します。\nこの操作後は復帰できません。よろしいですか？"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        deleted = 0
        for layer, ids in targets:
            if layer.dataProvider().deleteFeatures(ids):
                deleted += len(ids)
                self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        self.clear_trash_selection()
        self.set_status(tr_text(f"完全削除: {deleted} 件"))
        return deleted > 0

    def delete_feature_at(self, point):
        layer, feature = self.find_feature_at(point)
        if not layer:
            self.set_status(tr_text("削除対象が見つかりません"))
            return
        if not self.confirm_delete_if_needed("検査図形を削除", "選択した検査図形を削除しますか？"):
            return
        self._delete_features(layer, [feature.id()])
        self.operation_mode = "create"



    def toggle_merge_feature_at(self, point):
        layer, feature = self.find_feature_at(point)
        if not layer:
            self.set_status(tr_text("統合対象が見つかりません"))
            return
        if layer.geometryType() not in (Qgis.GeometryType.Polygon, Qgis.GeometryType.Line):
            QMessageBox.warning(self, tr_text("統合できません"), tr_text("統合はポリゴンまたはラインだけ対象です。"))
            return
        for other in self.current_inspection_layers():
            if other.id() != layer.id() and other.geometryType() != layer.geometryType():
                other.removeSelection()
        selected = set(layer.selectedFeatureIds())
        if feature.id() in selected:
            selected.remove(feature.id())
        else:
            selected.add(feature.id())
        layer.selectByIds(list(selected))
        self.refresh_selection_highlight()
        if len(selected) >= 2:
            self.merge_selected_features(layer)
            self.operation_mode = "create"

    def edit_memo_at(self, point):
        layer, feature = self.find_feature_at(point, allow_polygon_fill=True)
        if not layer:
            return
        if self.block_locked_layers([layer], "メモ編集できません", "メモを編集"):
            return
        idx = layer.fields().indexOf("memo")
        old = feature["memo"] if idx >= 0 else ""
        dialog = MemoDialog(old or "", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text = dialog.text()
        provider = layer.dataProvider()
        changes = {idx: text, layer.fields().indexOf("updated_at"): self.now_text()}
        provider.changeAttributeValues({feature.id(): changes})
        self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        layer.setLabelsEnabled(True)
        self.refresh_counts()

    def add_geometry_feature(self, layer, geometry):
        if self.block_locked_layers([layer], "追加できません", "新しい図形を追加"):
            return
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geometry)
        now = self.now_text()
        desc = self.layer_descriptor(layer)
        values = {
            "memo": "",
            "round_no": desc.get("round_no", 0),
            "item_code": desc.get("code", ""),
            "item_name": desc.get("name", ""),
            "geom_type": desc.get("geom_type", "polygon"),
            "created_at": now,
            "updated_at": now,
        }
        for name, value in values.items():
            idx = layer.fields().indexOf(name)
            if idx >= 0:
                feature.setAttribute(idx, value)
        ok, _features = layer.dataProvider().addFeatures([feature])
        if ok:
            if not self.continuous_capture_enabled:
                self.operation_mode = "pan_pending"
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
            self.set_status(tr_text(f"✅ 検査図形を追加: {self.layer_base_name(layer)}"))
            if not self.continuous_capture_enabled:
                QTimer.singleShot(0, self.return_to_pre_create_mode_if_still_create)
            self.schedule_refresh_counts()
        else:
            QMessageBox.warning(self, tr_text("追加失敗"), tr_text("検査図形を追加できませんでした。"))

    def now_text(self):
        return QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate)

    def selected_vector_targets(self):
        return [(l, list(l.selectedFeatureIds())) for l in self.selectable_inspection_layers() if l.selectedFeatureIds()]

    def find_selected_feature_at(self, point, targets=None, allow_polygon_fill=False, tolerance_factor=8):
        self.refresh_pending_data_change_layers()
        rect = self._search_rect(point, tolerance_factor=tolerance_factor)
        rect_geom = QgsGeometry.fromRect(rect)
        point_geom = QgsGeometry.fromPointXY(point)
        tolerance = max(rect.width(), rect.height()) / 2.0
        candidates = []
        selected_targets = targets if targets is not None else self.selected_vector_targets()
        for layer, ids in reversed(selected_targets):
            if not layer or not ids:
                continue
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                geom = feature.geometry()
                if not geom:
                    continue
                if layer.geometryType() == Qgis.GeometryType.Polygon:
                    if allow_polygon_fill and (geom.contains(point_geom) or geom.intersects(rect_geom)):
                        try:
                            area = geom.area()
                        except Exception:
                            area = 0
                        candidates.append((area, layer, feature))
                        continue
                    if self.polygon_edges_hit_rect(geom, rect_geom):
                        return layer, feature
                elif geom.intersects(rect_geom):
                    return layer, feature
                else:
                    try:
                        if geom.distance(point_geom) <= tolerance:
                            return layer, feature
                    except Exception:
                        pass
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1], candidates[0][2]
        return None, None

    def begin_feature_move_at(self, point, anchor_point=None):
        targets = self.selected_vector_targets()
        clicked_layer, clicked_feature = self.find_feature_at(point, allow_polygon_fill=True, tolerance_factor=12)
        if targets:
            selected_layer, _selected_feature = self.find_selected_feature_at(
                anchor_point if anchor_point is not None else point,
                targets=targets,
                allow_polygon_fill=True,
                tolerance_factor=12,
            )
            if not selected_layer:
                selected_layer, _selected_feature = self.find_selected_feature_at(
                    point,
                    targets=targets,
                    allow_polygon_fill=True,
                    tolerance_factor=12,
                )
            if not selected_layer and clicked_layer and clicked_feature:
                self.clear_inspection_selection()
                clicked_layer.selectByIds([clicked_feature.id()])
                self.iface.setActiveLayer(clicked_layer)
                targets = [(clicked_layer, [clicked_feature.id()])]
        elif clicked_layer and clicked_feature:
            self.clear_inspection_selection()
            clicked_layer.selectByIds([clicked_feature.id()])
            self.iface.setActiveLayer(clicked_layer)
            targets = [(clicked_layer, [clicked_feature.id()])]
        else:
            self.set_status(tr_text("移動対象が見つかりません"))
            return False
        self.feature_move_targets = [(layer, list(ids)) for layer, ids in targets if layer and ids]
        if self.block_locked_layers([layer for layer, _ids in self.feature_move_targets], "移動できません", "図形を移動"):
            self.feature_move_targets = []
            return False
        total = sum(len(ids) for _layer, ids in self.feature_move_targets)
        if not total:
            self.set_status(tr_text("移動対象が選択されていません"))
            return False
        move_anchor = anchor_point if anchor_point is not None else point
        self.update_feature_move_preview(move_anchor, move_anchor)
        self.set_status(tr_text(f"移動: {total} 件をドラッグ中"))
        return True

    def clear_feature_move_preview(self):
        for band in self.feature_move_preview_bands:
            try:
                self.iface.mapCanvas().scene().removeItem(band)
            except Exception:
                try:
                    band.hide()
                    band.deleteLater()
                except Exception:
                    pass
        self.feature_move_preview_bands = []

    def layer_delta_from_map_points(self, layer, start_point, end_point):
        start = QgsPointXY(start_point)
        end = QgsPointXY(end_point)
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
                transform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                start = transform.transform(start)
                end = transform.transform(end)
        except Exception:
            pass
        return end.x() - start.x(), end.y() - start.y()

    def update_feature_move_preview(self, start_point, end_point):
        self.clear_feature_move_preview()
        canvas = self.iface.mapCanvas()
        for layer, ids in self.feature_move_targets:
            dx, dy = self.layer_delta_from_map_points(layer, start_point, end_point)
            color = QColor(f"#{layer.customProperty(INSPECTION_PROP_PREFIX + 'color', 'ff0000')}")
            stroke_color = QColor(color)
            stroke_color.setAlpha(230)
            fill_color = QColor(color)
            fill_color.setAlpha(35 if layer.geometryType() == Qgis.GeometryType.Polygon else 0)
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                geom = QgsGeometry(feature.geometry())
                if not geom:
                    continue
                try:
                    geom.translate(dx, dy)
                except Exception:
                    continue
                band = QgsRubberBand(canvas, layer.geometryType())
                try:
                    band.setStrokeColor(stroke_color)
                    band.setFillColor(fill_color)
                    if layer.geometryType() == Qgis.GeometryType.Polygon:
                        band.setBrushStyle(Qt.BrushStyle.SolidPattern)
                except Exception:
                    band.setColor(stroke_color)
                band.setWidth(self.preview_rubber_band_width(layer))
                try:
                    band.setToGeometry(geom, layer)
                except Exception:
                    continue
                band.show()
                self.feature_move_preview_bands.append(band)

    def finish_feature_move(self, start_point, end_point):
        targets = self.feature_move_targets or self.selected_vector_targets()
        if not targets:
            self.clear_feature_move_preview()
            self.set_status(tr_text("移動対象が選択されていません"))
            return False
        if self.block_locked_layers([layer for layer, _ids in targets], "移動できません", "図形を移動"):
            self.clear_feature_move_preview()
            self.feature_move_targets = []
            return False
        now = self.now_text()
        moved = 0
        failed_layers = []
        undo_entries = []
        moved_targets = []
        for layer, ids in targets:
            dx, dy = self.layer_delta_from_map_points(layer, start_point, end_point)
            if abs(dx) + abs(dy) <= 0:
                continue
            safe, error = self.close_edit_buffer_before_provider_change(layer)
            if not safe:
                failed_layers.append(f"{self.display_layer_name(layer)}（{error}）")
                continue
            geometry_changes = {}
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                geom = QgsGeometry(feature.geometry())
                if not geom:
                    continue
                try:
                    geom.translate(dx, dy)
                except Exception:
                    continue
                undo_entries.append((layer, feature.id(), QgsGeometry(feature.geometry())))
                geometry_changes[feature.id()] = geom
            if not geometry_changes:
                continue
            provider = layer.dataProvider()
            if not provider.changeGeometryValues(geometry_changes):
                undo_entries = [entry for entry in undo_entries if entry[0] != layer or entry[1] not in geometry_changes]
                failed_layers.append(self.display_layer_name(layer))
                continue
            updated_idx = layer.fields().indexOf("updated_at")
            if updated_idx >= 0:
                provider.changeAttributeValues({fid: {updated_idx: now} for fid in geometry_changes.keys()})
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
            moved += len(geometry_changes)
            moved_targets.append((layer, list(geometry_changes.keys())))
        self.clear_feature_move_preview()
        self.refresh_counts()
        if moved:
            self.feature_move_undo_stack.append(undo_entries)
            self.operation_mode = "move"
            self.restore_feature_move_selection(moved_targets)
            QTimer.singleShot(0, lambda targets=moved_targets: self.restore_feature_move_selection(targets))
        else:
            self.refresh_selection_highlight()
        if failed_layers:
            QMessageBox.warning(self, tr_text("移動できません"), tr_text("一部レイヤを移動できませんでした。\n" + "\n".join(failed_layers[:8])))
        if moved:
            self.set_status(tr_text(f"✅ 移動: {moved} 件 / 続けて移動できます（右クリックで終了）"))
            return True
        self.set_status(tr_text("移動できませんでした"))
        return False

    def undo_last_feature_move(self):
        if not self.feature_move_undo_stack:
            entries = []
        else:
            entries = list(self.feature_move_undo_stack.pop() or [])
        if not entries:
            self.set_status(tr_text("戻す移動がありません"))
            return False
        layers = []
        for layer, _fid, _geom in entries:
            if layer and all(id(layer) != id(existing) for existing in layers):
                layers.append(layer)
        if self.block_locked_layers(layers, "戻せません", "図形の移動を戻す"):
            self.feature_move_undo_stack.append(entries)
            return False
        restored = 0
        restored_targets = []
        for layer in layers:
            safe, error = self.close_edit_buffer_before_provider_change(layer)
            if not safe:
                continue
            changes = {
                fid: QgsGeometry(geom)
                for entry_layer, fid, geom in entries
                if entry_layer == layer and geom
            }
            if not changes:
                continue
            if layer.dataProvider().changeGeometryValues(changes):
                self.refresh_vector_layer_after_data_change(layer, reload_data=True)
                restored += len(changes)
                restored_targets.append((layer, list(changes.keys())))
        if not restored:
            self.feature_move_undo_stack.append(entries)
            self.set_status(tr_text("移動を戻せませんでした"))
            return False
        self.clear_feature_move_preview()
        self.refresh_counts()
        self.operation_mode = "move"
        self.restore_feature_move_selection(restored_targets)
        QTimer.singleShot(0, lambda targets=restored_targets: self.restore_feature_move_selection(targets))
        self.set_status(tr_text(f"↶ 移動を戻しました: {restored} 件"))
        return True

    def move_selected_to_layer(self, target_layer):
        targets = self.selected_vector_targets()
        if not targets:
            self.set_status(tr_text("移動対象が選択されていません"))
            if self.last_selection_mode == "select_polygon":
                self.operation_mode = "layer_change_select_polygon"
            else:
                self.operation_mode = "layer_change_select"
            self.ensure_map_tool()
            return False
        if any(layer.geometryType() != target_layer.geometryType() for layer, _ids in targets):
            QMessageBox.warning(self, tr_text("移層できません"), tr_text("形状タイプが違うレイヤへは移動できません。"))
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))
            return True
        involved_layers = [layer for layer, _ids in targets] + [target_layer]
        if self.block_locked_layers(involved_layers, "移層できません", "図形を移層"):
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            return True
        total = sum(len(ids) for _layer, ids in targets)
        if not self.confirm_layer_change_if_needed(target_layer, total):
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            self.set_status(tr_text("移層: 右クリックメニューから移動先項目を選択してください"))
            QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))
            return True
        desc = self.layer_descriptor(target_layer)
        source_moves = []
        now = self.now_text()
        safe, error = self.close_edit_buffer_before_provider_change(target_layer)
        if not safe:
            QMessageBox.warning(self, tr_text("移層できません"), tr_text(f"移動先レイヤを保存できませんでした。\n{error}"))
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            return True
        for layer, ids in targets:
            if layer.id() == target_layer.id():
                continue
            safe, error = self.close_edit_buffer_before_provider_change(layer)
            if not safe:
                QMessageBox.warning(self, tr_text("移層できません"), tr_text(f"移動元レイヤを保存できませんでした。\n{error}"))
                self.operation_mode = "layer_change"
                self.ensure_map_tool()
                return True
            layer_features = []
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                new_feature = QgsFeature(target_layer.fields())
                geom = QgsGeometry(feature.geometry())
                if layer.crs().isValid() and target_layer.crs().isValid() and layer.crs() != target_layer.crs():
                    try:
                        transform = QgsCoordinateTransform(layer.crs(), target_layer.crs(), QgsProject.instance())
                        geom.transform(transform)
                    except Exception:
                        pass
                new_feature.setGeometry(geom)
                values = {
                    "memo": feature["memo"] if feature.fields().indexOf("memo") >= 0 else "",
                    "round_no": desc.get("round_no", 0),
                    "item_code": desc.get("code", ""),
                    "item_name": desc.get("name", ""),
                    "geom_type": desc.get("geom_type", "polygon"),
                    "created_at": feature["created_at"] if feature.fields().indexOf("created_at") >= 0 else now,
                    "updated_at": now,
                }
                for name, value in values.items():
                    idx = target_layer.fields().indexOf(name)
                    if idx >= 0:
                        new_feature.setAttribute(idx, value)
                layer_features.append(new_feature)
            if layer_features:
                source_moves.append((layer, ids, layer_features))
        for layer, ids, layer_features in source_moves:
            add_ok, added_features = target_layer.dataProvider().addFeatures(layer_features)
            if not add_ok:
                QMessageBox.warning(self, tr_text("移層できません"), tr_text("移動先レイヤへ図形を追加できませんでした。"))
                self.operation_mode = "layer_change"
                self.ensure_map_tool()
                return True
            added_feature_ids = [feature.id() for feature in added_features if feature.id() is not None and feature.id() >= 0]
            delete_ok = layer.dataProvider().deleteFeatures(ids)
            if not delete_ok:
                if added_feature_ids:
                    target_layer.dataProvider().deleteFeatures(added_feature_ids)
                    self.refresh_vector_layer_after_data_change(target_layer, reload_data=True)
                QMessageBox.warning(
                    self,
                    tr_text("移層できません"),
                    tr_text("移動元レイヤから図形を削除できなかったため、移動先への追加を取り消しました。"),
                )
                self.operation_mode = "layer_change"
                self.ensure_map_tool()
                return True
            layer.removeSelection()
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        self.clear_selection_highlight()
        self.refresh_vector_layer_after_data_change(target_layer, reload_data=True)
        self.active_layer_id = target_layer.id()
        self.active_geom_type = target_layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = target_layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.iface.setActiveLayer(target_layer)
        self.refresh_counts()
        self.return_to_last_selection_mode()
        self.set_status(tr_text(f"✅ 移層: {self.layer_base_name(target_layer)}"))
        return True

    def delete_selected_features(self):
        targets = self.selected_vector_targets()
        if not targets:
            return False
        if self.block_locked_layers([layer for layer, _ids in targets], "削除できません", "図形を削除"):
            return True
        count = sum(len(ids) for _layer, ids in targets)
        if not self.confirm_delete_if_needed("地物を削除", f"選択中の {count} 件を削除しますか？"):
            return True
        for layer, ids in targets:
            self._delete_features(layer, ids)
        return True

    def _delete_features(self, layer, ids):
        safe, error = self.close_edit_buffer_before_provider_change(layer)
        if not safe:
            QMessageBox.warning(self, tr_text("削除できません"), tr_text(f"レイヤを保存できませんでした。\n{error}"))
            return
        ids = list(ids or [])
        if not ids:
            return
        features = list(layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)))
        if not self.move_features_to_trash(layer, features):
            return
        layer.dataProvider().deleteFeatures(ids)
        layer.removeSelection()
        self.refresh_selection_highlight()
        self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        self.force_vector_delete_canvas_refresh(layer)
        self.refresh_counts()
        self.set_status(tr_text(f"🗑 {len(ids)} 件をゴミ箱へ移動しました"))

    def force_vector_delete_canvas_refresh(self, layer):
        def refresh_once():
            try:
                self.refresh_vector_layer_after_data_change(layer, reload_data=True, mark_edit_refresh=False)
            except Exception:
                pass
            try:
                canvas = self.iface.mapCanvas()
                if hasattr(canvas, "refreshAllLayers"):
                    canvas.refreshAllLayers()
                else:
                    canvas.refresh()
            except Exception:
                pass
        refresh_once()
        QTimer.singleShot(80, refresh_once)

    def move_features_to_trash(self, source_layer, features):
        geom_type = self.layer_geom_type_key(source_layer)
        trash_layer = self.ensure_trash_layer(geom_type, visible=False)
        if not trash_layer:
            QMessageBox.warning(self, tr_text("削除できません"), tr_text("ゴミ箱レイヤを作成できませんでした。"))
            return False
        provider = trash_layer.dataProvider()
        desc = self.layer_descriptor(source_layer)
        deleted_at = self.now_text()
        trash_features = []
        for src_feature in features:
            geom = src_feature.geometry()
            if not geom or geom.isEmpty():
                continue
            feature = QgsFeature(trash_layer.fields())
            feature.setGeometry(QgsGeometry(geom))
            values = {
                "orig_source": desc.get("source_name", ""),
                "orig_layer_name": self.layer_base_name(source_layer),
                "orig_color": desc.get("color", "ff0000"),
                "orig_geom_type": geom_type,
                "orig_round_no": str(desc.get("round_no", 0)),
                "orig_code": desc.get("code", ""),
                "orig_item_name": desc.get("name", ""),
                "orig_inspection_type": desc.get("inspection_type", ""),
                "orig_group_name": desc.get("group_name", ""),
                "orig_layer_id": source_layer.id(),
                "orig_layer_source_path": self.layer_source_path(source_layer),
                "orig_provider_uri": self.vector_layer_provider_uri(source_layer),
                "orig_attrs": self.feature_attrs_json(src_feature),
                "deleted_at": deleted_at,
            }
            for name, value in values.items():
                idx = trash_layer.fields().indexOf(name)
                if idx >= 0:
                    feature.setAttribute(idx, value)
            trash_features.append(feature)
        if not trash_features:
            QMessageBox.warning(self, tr_text("削除できません"), tr_text("ゴミ箱へ移動する図形がありません。"))
            return False
        ok, _added = provider.addFeatures(trash_features)
        if not ok:
            QMessageBox.warning(self, tr_text("削除できません"), tr_text("ゴミ箱レイヤへ保存できませんでした。"))
            return False
        self.refresh_vector_layer_after_data_change(trash_layer, reload_data=True)
        return True












    def merge_selected_features(self, forced_layer=None):
        targets = [(forced_layer, list(forced_layer.selectedFeatureIds()))] if forced_layer else self.selected_vector_targets()
        targets = [(layer, ids) for layer, ids in targets if layer and ids]
        if self.block_locked_layers([layer for layer, _ids in targets], "統合できません", "図形を統合"):
            return True
        total_count = sum(len(ids) for _layer, ids in targets)
        if total_count < 2:
            return False
        geometry_types = {layer.geometryType() for layer, _ids in targets}
        if len(geometry_types) != 1 or next(iter(geometry_types)) not in (Qgis.GeometryType.Polygon, Qgis.GeometryType.Line):
            QMessageBox.warning(self, tr_text("統合できません"), tr_text("統合は同じ種類のポリゴンまたはラインだけ対象です。"))
            return True
        geometry_type = next(iter(geometry_types))
        is_line_merge = geometry_type == Qgis.GeometryType.Line
        feature_label = "ライン" if is_line_merge else "ポリゴン"
        target_layer = self.choose_merge_target_layer([layer for layer, _ids in targets], geometry_type)
        if not target_layer:
            return True
        if self.block_locked_layers([target_layer], "統合できません", "統合後図形を保存"):
            return True
        features, geoms = self.collect_merge_features(targets, target_layer)
        if len(features) != total_count or len(geoms) != total_count:
            QMessageBox.warning(self, tr_text("統合できません"), tr_text(f"選択した{feature_label}を正しく取得できませんでした。"))
            return True
        if is_line_merge:
            geom = self.build_single_line_merge_geometry(geoms)
            if not geom:
                QMessageBox.warning(
                    self,
                    tr_text("統合できません"),
                    tr_text("端点がつながっているラインだけ統合できます。\n離れているライン、分岐するライン、複数線になる形状は保存しません。"),
                )
                return True
        elif not self.merge_geometries_have_area_overlap(geoms):
            QMessageBox.warning(
                self,
                tr_text("統合できません"),
                tr_text("面で重なっているポリゴンだけ統合できます。\n離れている、または辺だけ接しているポリゴンは統合できません。"),
            )
            return True
        else:
            geom = self.build_single_merge_geometry(geoms)
            if not geom:
                QMessageBox.warning(
                    self,
                    tr_text("統合できません"),
                    tr_text("統合後の形状が単一ポリゴンになりませんでした。\n離れた形状や不正な形状は保存しません。"),
                )
                return True
        if QMessageBox.question(
            self,
            tr_text(f"{feature_label}統合"),
            tr_text(f"{total_count} 件の{feature_label}を統合し、統合後レイヤ「{self.display_layer_name(target_layer)}」へ保存しますか？"),
        ) != QMessageBox.StandardButton.Yes:
            return True
        new_feature = self.build_merge_feature(target_layer, features, geom)
        if not self.apply_merge_edits(target_layer, targets, new_feature, feature_label):
            return True
        for layer, _ids in targets:
            layer.removeSelection()
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
        self.refresh_vector_layer_after_data_change(target_layer, reload_data=True)
        self.active_layer_id = target_layer.id()
        self.active_geom_type = target_layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = target_layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.iface.setActiveLayer(target_layer)
        self.refresh_counts()
        self.set_status(tr_text(f"✅ {feature_label}を統合しました"))
        return True

    def build_merge_feature(self, target_layer, features, geom):
        feature = QgsFeature(target_layer.fields())
        feature.setGeometry(geom)
        now = self.now_text()
        desc = self.layer_descriptor(target_layer)
        first_feature = features[0][1] if features else None
        values = {
            "memo": first_feature["memo"] if first_feature and first_feature.fields().indexOf("memo") >= 0 else "",
            "round_no": desc.get("round_no", 0),
            "item_code": desc.get("code", ""),
            "item_name": desc.get("name", ""),
            "geom_type": desc.get("geom_type", "polygon"),
            "created_at": first_feature["created_at"] if first_feature and first_feature.fields().indexOf("created_at") >= 0 else now,
            "updated_at": now,
        }
        for name, value in values.items():
            idx = target_layer.fields().indexOf(name)
            if idx >= 0:
                feature.setAttribute(idx, value)
        return feature

    def apply_merge_edits(self, target_layer, targets, new_feature, feature_label="ポリゴン"):
        involved = []
        for layer, _ids in [(target_layer, [])] + targets:
            if layer and all(existing.id() != layer.id() for existing in involved):
                involved.append(layer)
        if self.block_locked_layers(involved, "統合できません", "図形を統合"):
            return False
        started = []
        commanded = []
        try:
            for layer in involved:
                if not layer.isEditable():
                    if not layer.startEditing():
                        QMessageBox.warning(self, tr_text("統合できません"), tr_text(f"レイヤを編集状態にできませんでした。\n{self.display_layer_name(layer)}"))
                        return False
                    started.append(layer)
                layer.beginEditCommand(f"{feature_label}統合")
                commanded.append(layer)
            if not target_layer.addFeature(new_feature):
                QMessageBox.warning(self, tr_text("統合できません"), tr_text(f"統合後{feature_label}を保存できませんでした。元の{feature_label}は残しています。"))
                return False
            for layer, ids in targets:
                if ids and not layer.deleteFeatures(ids):
                    QMessageBox.warning(self, tr_text("統合できません"), tr_text(f"元{feature_label}を削除できませんでした。\n{self.display_layer_name(layer)}"))
                    return False
            for layer in commanded:
                layer.endEditCommand()
            commanded = []
            commit_errors = []
            for layer in involved:
                if layer.isEditable() and not layer.commitChanges():
                    errors = "; ".join(layer.commitErrors())
                    commit_errors.append(f"{self.display_layer_name(layer)}: {errors}")
            if commit_errors:
                QMessageBox.warning(
                    self,
                    tr_text("統合保存エラー"),
                    tr_text("統合の保存でエラーが出ました。\n" + "\n".join(commit_errors)),
                )
                return False
            return True
        finally:
            for layer in reversed(commanded):
                try:
                    layer.destroyEditCommand()
                except Exception:
                    pass
            for layer in started:
                try:
                    if layer.isEditable():
                        layer.rollBack()
                except Exception:
                    pass

    def collect_merge_features(self, targets, target_layer):
        features = []
        geoms = []
        for layer, ids in targets:
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                geom = QgsGeometry(feature.geometry())
                if geom.isEmpty():
                    continue
                try:
                    if not geom.isGeosValid():
                        geom = geom.makeValid()
                except Exception:
                    pass
                if layer.crs().isValid() and target_layer.crs().isValid() and layer.crs() != target_layer.crs():
                    try:
                        transform = QgsCoordinateTransform(layer.crs(), target_layer.crs(), QgsProject.instance())
                        geom.transform(transform)
                    except Exception as exc:
                        QgsMessageLog.logMessage(f"統合用CRS変換失敗: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                features.append((layer, feature))
                geoms.append(geom)
        return features, geoms

    def merge_geometries_have_area_overlap(self, geoms):
        count = len(geoms)
        if count < 2:
            return False
        links = {i: set() for i in range(count)}
        for i in range(count):
            for j in range(i + 1, count):
                if self.geometry_overlap_area(geoms[i], geoms[j]) > 0:
                    links[i].add(j)
                    links[j].add(i)
        seen = set()
        stack = [0]
        while stack:
            idx = stack.pop()
            if idx in seen:
                continue
            seen.add(idx)
            stack.extend(links[idx] - seen)
        return len(seen) == count

    def geometry_overlap_area(self, geom_a, geom_b):
        try:
            if not geom_a.boundingBox().intersects(geom_b.boundingBox()):
                return 0.0
            if not geom_a.intersects(geom_b):
                return 0.0
            intersection = geom_a.intersection(geom_b)
            if intersection.isEmpty():
                return 0.0
            return max(0.0, intersection.area())
        except Exception:
            return 0.0

    def build_single_merge_geometry(self, geoms):
        try:
            geom = QgsGeometry.unaryUnion(geoms)
        except Exception:
            geom = None
            for source_geom in geoms:
                geom = QgsGeometry(source_geom) if geom is None else geom.combine(source_geom)
        if not geom or geom.isEmpty() or geom.type() != Qgis.GeometryType.Polygon:
            return None
        try:
            if not geom.isGeosValid():
                geom = geom.makeValid()
        except Exception:
            try:
                geom = geom.makeValid()
            except Exception:
                return None
        if not geom or geom.isEmpty() or geom.type() != Qgis.GeometryType.Polygon:
            return None
        try:
            if geom.isMultipart():
                return None
            polygon = geom.asPolygon()
            if not polygon or not polygon[0]:
                return None
            single = QgsGeometry.fromPolygonXY(polygon)
            if single.isEmpty() or single.type() != Qgis.GeometryType.Polygon or single.isMultipart():
                return None
            try:
                if not single.isGeosValid():
                    single = single.makeValid()
            except Exception:
                single = single.makeValid()
            if single.isEmpty() or single.type() != Qgis.GeometryType.Polygon or single.isMultipart():
                return None
            if not single.asPolygon() or not single.asPolygon()[0]:
                return None
        except Exception:
            return None
        return single

    def build_single_line_merge_geometry(self, geoms):
        try:
            geom = QgsGeometry.unaryUnion(geoms)
        except Exception:
            geom = None
            for source_geom in geoms:
                geom = QgsGeometry(source_geom) if geom is None else geom.combine(source_geom)
        if not geom or geom.isEmpty():
            return None
        try:
            merged = geom.mergeLines()
        except Exception:
            merged = geom
        if not merged or merged.isEmpty() or merged.type() != Qgis.GeometryType.Line:
            return None
        try:
            if merged.isMultipart():
                parts = merged.asMultiPolyline()
                if len(parts) != 1:
                    return None
                points = parts[0]
            else:
                points = merged.asPolyline()
        except Exception:
            return None
        if not points or len(points) < 2:
            return None
        single = QgsGeometry.fromPolylineXY(points)
        if not single or single.isEmpty() or single.type() != Qgis.GeometryType.Line or single.isMultipart():
            return None
        return single

    def choose_merge_target_layer(self, selected_layers, geometry_type=Qgis.GeometryType.Polygon):
        unique_selected = {layer.id(): layer for layer in selected_layers}
        if len(unique_selected) == 1:
            return list(unique_selected.values())[0]
        candidate_layers = [
            layer for layer in self.selectable_inspection_layers()
            if layer.geometryType() == geometry_type and not self.is_layer_locked(layer)
        ]
        if not candidate_layers:
            return None
        labels = [self.display_layer_name(layer) for layer in candidate_layers]
        label, ok = QInputDialog.getItem(self, tr_text("統合後レイヤ選択"), tr_text("統合後の保存先レイヤ:"), labels, 0, False)
        if not ok:
            return None
        return candidate_layers[labels.index(label)]

    def display_layer_name(self, layer):
        if layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""):
            return self.layer_base_name(layer)
        return layer.name()

    def export_inspection(self):
        layers = [layer for layer in self.current_inspection_layers() if layer.featureCount() > 0]
        if not layers:
            QMessageBox.information(self, tr_text("検査書出"), tr_text("書き出す検査データがありません。"))
            return
        dialog = InspectionExportDialog(self, layers, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_layers()
        if not selected:
            QMessageBox.information(self, tr_text("検査書出"), tr_text("データがあるレイヤが選択されていません。"))
            return
        mode = dialog.selected_output_mode()
        selected_format = dialog.selected_format()
        if selected_format == "SHP":
            folder = QFileDialog.getExistingDirectory(self, "SHP書き出し先フォルダ")
            if folder:
                self.export_shp(selected, folder, mode)
        elif selected_format == "DXF（R12）":
            if mode == DXF_EXPORT_PER_LAYER:
                folder = QFileDialog.getExistingDirectory(self, "DXF（R12）書き出し先フォルダ")
                if folder:
                    self.export_dxf_per_layer(selected, folder)
            else:
                path, _ = QFileDialog.getSaveFileName(self, "DXF（R12）書き出し先", "", "DXF (*.dxf)")
                if path:
                    if not path.lower().endswith(".dxf"):
                        path += ".dxf"
                    self.export_dxf(selected, path)
        elif selected_format == "DXF（AutoCAD 2000系）":
            if mode == TEST_DXF_EXPORT_PER_LAYER:
                folder = QFileDialog.getExistingDirectory(self, "DXF（AutoCAD 2000系）書き出し先フォルダ")
                if folder:
                    self.export_test_dxf_per_layer(selected, folder)
            else:
                path, _ = QFileDialog.getSaveFileName(self, "DXF（AutoCAD 2000系）書き出し先", "", "DXF (*.dxf)")
                if path:
                    if not path.lower().endswith(".dxf"):
                        path += ".dxf"
                    self.export_test_dxf(selected, path)
        else:
            if mode == DGN_LEGACY_EXPORT_PER_LAYER:
                folder = QFileDialog.getExistingDirectory(self, "DGN V7書き出し先フォルダ")
                if folder:
                    self.export_dgn_per_layer(selected, folder, legacy=True)
            else:
                path, _ = QFileDialog.getSaveFileName(self, "DGN V7書き出し先", "", "DGN (*.dgn)")
                if path:
                    if not path.lower().endswith(".dgn"):
                        path += ".dgn"
                    self.export_dgn(selected, path, legacy=True)

    def layer_geom_type_key(self, layer):
        geom_type = layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "") if layer else ""
        if geom_type in GEOM_TYPE_LABELS:
            return geom_type
        if layer and layer.geometryType() == Qgis.GeometryType.Line:
            return "line"
        if layer and layer.geometryType() == Qgis.GeometryType.Point:
            return "point"
        return "polygon"

    def layer_geom_type_label(self, layer):
        return GEOM_TYPE_LABELS.get(self.layer_geom_type_key(layer), "ポリゴン")

    def selected_geom_type_keys(self, layers):
        return {self.layer_geom_type_key(layer) for layer in layers}

    def export_shp(self, layers, folder, mode=SHP_EXPORT_PER_LAYER):
        os.makedirs(folder, exist_ok=True)
        if mode == SHP_EXPORT_MERGED:
            self.export_shp_merged(layers, folder)
            return
        errors = []
        for layer in layers:
            out_path = os.path.join(folder, _safe_layer_name(self.layer_base_name(layer)) + ".shp")
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "ESRI Shapefile"
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            err, msg, _new_file, _new_layer = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, out_path, QgsProject.instance().transformContext(), options
            )
            if err != QgsVectorFileWriter.WriterError.NoError:
                errors.append(f"{layer.name()}: {msg}")
        if errors:
            QMessageBox.warning(self, tr_text("SHP書き出し"), "\n".join(errors))
        else:
            self.set_status(tr_text(f"✅ SHP書き出し完了: {len(layers)} レイヤ"))

    def export_shp_merged(self, layers, folder):
        if not OGR_OK:
            QMessageBox.critical(self, tr_text("SHP書き出し"), tr_text("GDAL/OGRを読み込めないためSHPを書き出せません。"))
            return
        geom_types = self.selected_geom_type_keys(layers)
        if len(geom_types) != 1:
            labels = "、".join(GEOM_TYPE_LABELS.get(key, key) for key in sorted(geom_types))
            QMessageBox.warning(
                self,
                tr_text("SHP書き出し"),
                tr_text(f"1つのSHPには同じ図形タイプだけ出力できます。\n選択データには {labels} が混在しているため、1つのSHPにまとめられません。\n「レイヤごとにSHP作成」を選んでください。"),
            )
            return
        geom_type = next(iter(geom_types))
        suffix = {"polygon": "polygon", "line": "line", "point": "point"}.get(geom_type, "polygon")
        out_path = os.path.join(folder, f"inspection_{suffix}.shp")
        self._delete_shapefile_set(out_path)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.CreateDataSource(out_path)
        if ds is None:
            QMessageBox.critical(self, tr_text("SHP書き出し"), tr_text("SHPを作成できませんでした。"))
            return
        ogr_type = {"polygon": ogr.wkbPolygon, "line": ogr.wkbLineString, "point": ogr.wkbPoint}.get(geom_type, ogr.wkbPolygon)
        ogr_layer = ds.CreateLayer(os.path.splitext(os.path.basename(out_path))[0], self._ogr_srs_from_layer(layers[0]), ogr_type, options=["ENCODING=UTF-8"])
        for field_name, field_type, width in [
            ("layer_name", ogr.OFTString, 120),
            ("memo", ogr.OFTString, 254),
            ("round_no", ogr.OFTInteger, 0),
            ("item_code", ogr.OFTString, 32),
            ("item_name", ogr.OFTString, 120),
            ("geom_type", ogr.OFTString, 16),
            ("created_at", ogr.OFTString, 32),
            ("updated_at", ogr.OFTString, 32),
        ]:
            field = ogr.FieldDefn(field_name, field_type)
            if width:
                field.SetWidth(width)
            ogr_layer.CreateField(field)
        defn = ogr_layer.GetLayerDefn()
        errors = []
        count = 0
        for layer in layers:
            descriptor = self.layer_descriptor(layer)
            for feature in layer.getFeatures():
                try:
                    geom = feature.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    out = ogr.Feature(defn)
                    out.SetGeometry(ogr.CreateGeometryFromWkt(geom.asWkt()))
                    out.SetField("layer_name", self.layer_base_name(layer))
                    out.SetField("memo", self._feature_text(feature, "memo"))
                    out.SetField("round_no", int(descriptor.get("round_no", 0) or 0))
                    out.SetField("item_code", str(descriptor.get("code", "") or self._feature_text(feature, "item_code")))
                    out.SetField("item_name", str(descriptor.get("name", "") or self._feature_text(feature, "item_name")))
                    out.SetField("geom_type", self.layer_geom_type_key(layer))
                    out.SetField("created_at", self._feature_text(feature, "created_at"))
                    out.SetField("updated_at", self._feature_text(feature, "updated_at"))
                    ogr_layer.CreateFeature(out)
                    out = None
                    count += 1
                except Exception as exc:
                    errors.append(f"{self.layer_base_name(layer)}: {exc}")
        ds = None
        if errors:
            QMessageBox.warning(self, tr_text("SHP書き出し"), "\n".join(errors[:20]))
        else:
            self.set_status(tr_text(f"✅ SHP書き出し完了: 1 ファイル（{count} 件）"))

    def _delete_shapefile_set(self, shp_path):
        base, _ext = os.path.splitext(shp_path)
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".fix"):
            path = base + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def export_dxf(self, layers, path):
        if self._write_legacy_dxf(layers, path):
            self.set_status(tr_text(f"✅ DXF（R12）書き出し完了: 1 ファイル（{len(layers)} レイヤ）"))

    def export_dxf_per_layer(self, layers, folder):
        os.makedirs(folder, exist_ok=True)
        errors = []
        written = 0
        for layer in layers:
            path = os.path.join(folder, _safe_layer_name(self.layer_base_name(layer)) + ".dxf")
            if self._write_legacy_dxf([layer], path):
                written += 1
            else:
                errors.append(self.layer_base_name(layer))
        if errors:
            QMessageBox.warning(self, tr_text("DXF（R12）書き出し"), tr_text("書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20])))
        else:
            self.set_status(tr_text(f"✅ DXF（R12）書き出し完了: {written} ファイル"))




    def export_test_dxf(self, layers, path):
        if self._write_test_dxf(layers, path):
            self.set_status(tr_text(f"✅ DXF（AutoCAD 2000系）書き出し完了: 1 ファイル（{len(layers)} レイヤ）"))

    def export_test_dxf_per_layer(self, layers, folder):
        os.makedirs(folder, exist_ok=True)
        errors = []
        written = 0
        for layer in layers:
            path = os.path.join(folder, _safe_layer_name(self.layer_base_name(layer)) + "_ac2000.dxf")
            if self._write_test_dxf([layer], path):
                written += 1
            else:
                errors.append(self.layer_base_name(layer))
        if errors:
            QMessageBox.warning(self, tr_text("DXF（AutoCAD 2000系）書き出し"), tr_text("書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20])))
        else:
            self.set_status(tr_text(f"✅ DXF（AutoCAD 2000系）書き出し完了: {written} ファイル"))

    def _write_test_dxf(self, layers, path):
        return self._write_ogr_dxf(layers, path)

    def _write_ogr_dxf(self, layers, path):
        title = "DXF（AutoCAD 2000系）書き出し"
        if not OGR_OK:
            QMessageBox.critical(self, title, tr_text("GDAL/OGRを読み込めないためDXFを書き出せません。"))
            return False
        driver = ogr.GetDriverByName("DXF")
        if driver is None:
            QMessageBox.critical(self, title, tr_text("このQGIS環境ではDXF書き出しドライバが使えません。"))
            return False
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                try:
                    driver.DeleteDataSource(path)
                except Exception:
                    pass
        old_encoding = gdal.GetConfigOption("DXF_ENCODING")
        old_hatch = gdal.GetConfigOption("DXF_WRITE_HATCH")
        try:
            gdal.SetConfigOption("DXF_ENCODING", "CP932")
            gdal.SetConfigOption("DXF_WRITE_HATCH", "TRUE")
            ds = driver.CreateDataSource(path)
            if ds is None:
                QMessageBox.critical(self, title, tr_text("DXFを作成できませんでした。"))
                return False
            srs = self._ogr_srs_from_layer(layers[0]) if layers else None
            ogr_layer = ds.CreateLayer("entities", srs, ogr.wkbUnknown)
            if ogr_layer is None:
                raise RuntimeError("DXF entities レイヤを作成できませんでした。")
            self._ensure_dxf_ogr_fields(ogr_layer)
            defn = ogr_layer.GetLayerDefn()
            for layer in layers:
                self._export_layer_to_dxf_ogr_layer(ogr_layer, defn, layer)
            ds = None
            self._patch_dxf_codepage(path)
            return True
        except Exception as exc:
            QMessageBox.critical(self, title, tr_text(f"DXFを書き出せませんでした。\n{exc}"))
            return False
        finally:
            gdal.SetConfigOption("DXF_ENCODING", old_encoding)
            gdal.SetConfigOption("DXF_WRITE_HATCH", old_hatch)

    def _ensure_dxf_ogr_fields(self, ogr_layer):
        for name, width in [("Layer", 128), ("Linetype", 64), ("Text", 254)]:
            defn = ogr_layer.GetLayerDefn()
            if defn.GetFieldIndex(name) >= 0:
                continue
            field = ogr.FieldDefn(name, ogr.OFTString)
            if width:
                field.SetWidth(width)
            ogr_layer.CreateField(field)
        defn = ogr_layer.GetLayerDefn()
        if defn.GetFieldIndex("Layer") < 0:
            raise RuntimeError("DXFのLayerフィールドを作成できませんでした。")

    def _export_layer_to_dxf_ogr_layer(self, ogr_layer, defn, layer):
        color = str(layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000") or "ff0000").replace("#", "")
        color_index = self._cad_color_index(color)
        geom_type = self.layer_geom_type_key(layer)
        cad_layer_name = str(self.layer_base_name(layer) or layer.name()).replace("\r", " ").replace("\n", " ")
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            out = ogr.Feature(defn)
            self._set_ogr_field(out, defn, "Layer", cad_layer_name)
            self._set_ogr_field(out, defn, "Linetype", "Continuous")
            out.SetGeometry(ogr.CreateGeometryFromWkt(geom.asWkt()))
            out.SetStyleString(self._dxf_geometry_style(layer, geom_type, color))
            ogr_layer.CreateFeature(out)
            out = None
            memo = self._feature_text(feature, "memo").strip()
            if memo:
                label_geom = self._memo_label_geometry(geom, geom_type)
                if label_geom and not label_geom.isEmpty():
                    text_feature = ogr.Feature(defn)
                    self._set_ogr_field(text_feature, defn, "Layer", cad_layer_name)
                    self._set_ogr_field(text_feature, defn, "Linetype", "Continuous")
                    self._set_ogr_field(text_feature, defn, "Text", memo[:250])
                    text_feature.SetGeometry(ogr.CreateGeometryFromWkt(label_geom.asWkt()))
                    text = self._dxf_style_text(memo)
                    text_feature.SetStyleString(f'LABEL(f:"MS Gothic",s:2.5g,t:"{text}",c:#{color},p:5)')
                    ogr_layer.CreateFeature(text_feature)
                    text_feature = None

    def _set_ogr_field(self, feature, defn, name, value):
        idx = defn.GetFieldIndex(name)
        if idx >= 0:
            feature.SetField(idx, str(value))

    def _patch_dxf_codepage(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("cp932", errors="replace")
            text = text.replace("ANSI_1252", "ANSI_932", 1)
            text = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), text)
            with open(path, "w", encoding="cp932", errors="replace", newline="") as f:
                f.write(text)
        except Exception:
            pass

    def _write_legacy_dxf(self, layers, path):
        return self._write_direct_dxf(
            layers,
            path,
            acadver="AC1009",
            codepage="ANSI_932",
            encoding="cp932",
            error_title="DXF（R12）書き出し",
        )

    def _write_direct_dxf(self, layers, path, acadver, codepage, encoding, error_title):
        try:
            layer_defs = []
            for index, layer in enumerate(layers, start=1):
                name = _safe_layer_name(self.layer_base_name(layer))
                color = str(layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000") or "ff0000").replace("#", "")
                layer_defs.append((name, self._cad_color_index(color), layer))
            lines = []
            self._append_dxf_header(lines, layer_defs, acadver=acadver, codepage=codepage)
            for dxf_layer_name, color_index, layer in layer_defs:
                geom_type = self.layer_geom_type_key(layer)
                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    for entity_type, points, closed in self._dxf_entities_from_geometry(geom, geom_type):
                        if entity_type == "point":
                            self._append_dxf_point(lines, dxf_layer_name, color_index, points[0])
                        else:
                            self._append_dxf_polyline(lines, dxf_layer_name, color_index, points, closed)
                    memo = self._feature_text(feature, "memo").strip()
                    if memo:
                        label_geom = self._memo_label_geometry(geom, geom_type)
                        if label_geom and not label_geom.isEmpty():
                            label_point = self._point_from_geometry(label_geom)
                            if label_point:
                                self._append_dxf_text(lines, dxf_layer_name, color_index, label_point, memo)
            self._append_dxf_footer(lines)
            with open(path, "w", encoding=encoding, errors="replace", newline="\r\n") as f:
                f.write("\n".join(lines))
                f.write("\n")
            return True
        except Exception as exc:
            QMessageBox.critical(self, error_title, tr_text(f"DXFを書き出せませんでした。\n{exc}"))
            return False


    def _dxf_bounds(self, layers):
        minx = miny = maxx = maxy = None
        for layer in layers:
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                rect = geom.boundingBox()
                if rect.isEmpty():
                    continue
                values = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
                if minx is None:
                    minx, miny, maxx, maxy = values
                else:
                    minx = min(minx, values[0])
                    miny = min(miny, values[1])
                    maxx = max(maxx, values[2])
                    maxy = max(maxy, values[3])
        if minx is None:
            return (0.0, 0.0, 100.0, 100.0)
        if minx == maxx:
            maxx = minx + 1.0
        if miny == maxy:
            maxy = miny + 1.0
        return (float(minx), float(miny), float(maxx), float(maxy))

    def _append_test_dxf_header(self, lines, layer_defs, bounds):
        minx, miny, maxx, maxy = bounds
        center_x = (minx + maxx) / 2.0
        center_y = (miny + maxy) / 2.0
        view_height = max(maxy - miny, 1.0)
        lines.extend([
            "0", "SECTION", "2", "HEADER",
            "9", "$ACADVER", "1", "AC1009",
            "9", "$DWGCODEPAGE", "3", "ANSI_932",
            "9", "$INSBASE", "10", "0.0", "20", "0.0", "30", "0.0",
            "9", "$EXTMIN", "10", self._dxf_num(minx), "20", self._dxf_num(miny), "30", "0.0",
            "9", "$EXTMAX", "10", self._dxf_num(maxx), "20", self._dxf_num(maxy), "30", "0.0",
            "0", "ENDSEC",
            "0", "SECTION", "2", "TABLES",
            "0", "TABLE", "2", "VPORT", "70", "1",
            "0", "VPORT", "2", "*ACTIVE", "70", "0", "10", "0.0", "20", "0.0", "11", "1.0", "21", "1.0",
            "12", self._dxf_num(center_x), "22", self._dxf_num(center_y), "40", self._dxf_num(view_height),
            "0", "ENDTAB",
            "0", "TABLE", "2", "LTYPE", "70", "1",
            "0", "LTYPE", "2", "CONTINUOUS", "70", "0", "3", "Solid line", "72", "65", "73", "0", "40", "0.0",
            "0", "ENDTAB",
            "0", "TABLE", "2", "STYLE", "70", "1",
            "0", "STYLE", "2", "STANDARD", "70", "0", "40", "0.0", "41", "1.0", "50", "0.0", "71", "0", "42", "2.5", "3", "msgothic.ttc", "4", "",
            "0", "ENDTAB",
            "0", "TABLE", "2", "LAYER", "70", str(max(1, len(layer_defs))),
        ])
        for name, color_index, _layer in layer_defs:
            lines.extend(["0", "LAYER", "2", name, "70", "0", "62", str(color_index), "6", "CONTINUOUS"])
        lines.extend([
            "0", "ENDTAB",
            "0", "ENDSEC",
            "0", "SECTION", "2", "BLOCKS",
            "0", "BLOCK", "8", "0", "2", "*Model_Space", "70", "0", "10", "0.0", "20", "0.0", "30", "0.0", "3", "*Model_Space", "1", "",
            "0", "ENDBLK",
            "0", "BLOCK", "8", "0", "2", "*Paper_Space", "70", "0", "10", "0.0", "20", "0.0", "30", "0.0", "3", "*Paper_Space", "1", "",
            "0", "ENDBLK",
            "0", "ENDSEC",
            "0", "SECTION", "2", "ENTITIES",
        ])

    def _append_test_dxf_segments(self, lines, layer_name, color_index, points, closed=False):
        if len(points) < 2:
            return
        draw_points = list(points)
        if closed and len(draw_points) >= 2:
            first_x, first_y = self._xy_from_point(draw_points[0])
            last_x, last_y = self._xy_from_point(draw_points[-1])
            if abs(first_x - last_x) > 0.0000001 or abs(first_y - last_y) > 0.0000001:
                draw_points.append(draw_points[0])
        for start, end in zip(draw_points, draw_points[1:]):
            self._append_test_dxf_line(lines, layer_name, color_index, start, end)

    def _append_test_dxf_line(self, lines, layer_name, color_index, start, end):
        x1, y1 = self._xy_from_point(start)
        x2, y2 = self._xy_from_point(end)
        lines.extend([
            "0", "LINE", "8", layer_name, "62", str(color_index),
            "10", self._dxf_num(x1), "20", self._dxf_num(y1), "30", "0.0",
            "11", self._dxf_num(x2), "21", self._dxf_num(y2), "31", "0.0",
        ])

    def _append_test_dxf_text(self, lines, layer_name, color_index, point, text):
        x, y = self._xy_from_point(point)
        clean_text = str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")[:250]
        lines.extend([
            "0", "TEXT", "8", layer_name, "62", str(color_index),
            "10", self._dxf_num(x), "20", self._dxf_num(y), "30", "0.0",
            "40", "2.5", "1", clean_text, "7", "STANDARD", "50", "0.0",
        ])

    def _append_dxf_header(self, lines, layer_defs, acadver="AC1009", codepage="ANSI_932"):
        lines.extend(["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", acadver, "9", "$DWGCODEPAGE", "3", codepage, "0", "ENDSEC"])
        lines.extend(["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(max(1, len(layer_defs)))])
        for name, color_index, _layer in layer_defs:
            lines.extend(["0", "LAYER", "2", name, "70", "0", "62", str(color_index), "6", "CONTINUOUS"])
        lines.extend(["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"])

    def _append_dxf_footer(self, lines):
        lines.extend(["0", "ENDSEC", "0", "EOF"])

    def _append_dxf_polyline(self, lines, layer_name, color_index, points, closed=False):
        if len(points) < 2:
            return
        lines.extend(["0", "POLYLINE", "8", layer_name, "62", str(color_index), "66", "1", "70", "1" if closed else "0"])
        for point in points:
            x, y = self._xy_from_point(point)
            lines.extend(["0", "VERTEX", "8", layer_name, "10", self._dxf_num(x), "20", self._dxf_num(y), "30", "0.0"])
        lines.extend(["0", "SEQEND", "8", layer_name])

    def _append_dxf_point(self, lines, layer_name, color_index, point):
        x, y = self._xy_from_point(point)
        lines.extend(["0", "POINT", "8", layer_name, "62", str(color_index), "10", self._dxf_num(x), "20", self._dxf_num(y), "30", "0.0"])

    def _append_dxf_text(self, lines, layer_name, color_index, point, text):
        x, y = self._xy_from_point(point)
        clean_text = str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")[:250]
        lines.extend(["0", "TEXT", "8", layer_name, "62", str(color_index), "10", self._dxf_num(x), "20", self._dxf_num(y), "30", "0.0", "40", "2.5", "1", clean_text, "50", "0.0"])

    def _dxf_entities_from_geometry(self, geometry, geom_type):
        entities = []
        try:
            if geom_type == "point":
                if geometry.isMultipart():
                    for point in geometry.asMultiPoint():
                        entities.append(("point", [point], False))
                else:
                    entities.append(("point", [geometry.asPoint()], False))
            elif geom_type == "line":
                lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
                for line in lines:
                    if len(line) >= 2:
                        entities.append(("polyline", line, False))
            else:
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
                for polygon in polygons:
                    if polygon and len(polygon[0]) >= 3:
                        entities.append(("polyline", polygon[0], True))
        except Exception:
            pass
        return entities

    def _point_from_geometry(self, geometry):
        try:
            if geometry.type() == Qgis.GeometryType.Point:
                if geometry.isMultipart():
                    points = geometry.asMultiPoint()
                    return points[0] if points else None
                return geometry.asPoint()
            centroid = geometry.centroid()
            return centroid.asPoint() if centroid and not centroid.isEmpty() else None
        except Exception:
            return None

    def _xy_from_point(self, point):
        return float(point.x()), float(point.y())

    def _dxf_num(self, value):
        return f"{float(value):.8f}".rstrip("0").rstrip(".") or "0"

    def _cad_color_index(self, color):
        color = str(color or "ff0000").replace("#", "")
        try:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
        except Exception:
            return 1
        palette = {
            1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
            5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128),
        }
        return min(palette, key=lambda idx: (r - palette[idx][0]) ** 2 + (g - palette[idx][1]) ** 2 + (b - palette[idx][2]) ** 2)

    def export_dgn(self, layers, path, legacy=False):
        if self._write_dgn(layers, path, legacy=legacy):
            label = "DGN V7" if legacy else "DGN V8/2004以降"
            self.set_status(tr_text(f"✅ {label}書き出し完了: 1 ファイル（{len(layers)} レイヤ）"))

    def export_dgn_per_layer(self, layers, folder, legacy=False):
        os.makedirs(folder, exist_ok=True)
        errors = []
        written = 0
        suffix = "_v7" if legacy else "_v8"
        for layer in layers:
            path = os.path.join(folder, _safe_layer_name(self.layer_base_name(layer)) + suffix + ".dgn")
            if self._write_dgn([layer], path, legacy=legacy):
                written += 1
            else:
                errors.append(self.layer_base_name(layer))
        label = "DGN V7" if legacy else "DGN V8/2004以降"
        if errors:
            QMessageBox.warning(self, tr_text(f"{label}書き出し"), tr_text("書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20])))
        else:
            self.set_status(tr_text(f"✅ {label}書き出し完了: {written} ファイル"))

    def _write_dgn(self, layers, path, legacy=False):
        label = "DGN V7" if legacy else "DGN V8/2004以降"
        if not OGR_OK:
            QMessageBox.critical(self, tr_text(f"{label}書き出し"), tr_text("GDAL/OGRを読み込めないためDGNを書き出せません。"))
            return False
        driver_name = "DGN" if legacy else "DGNv8"
        driver = ogr.GetDriverByName(driver_name)
        if driver is None:
            if legacy:
                QMessageBox.critical(self, tr_text("DGN V7書き出し"), tr_text("このQGIS環境ではDGN V7書き出しドライバが使えません。"))
            else:
                QMessageBox.critical(
                    self,
                    tr_text("DGN V8/2004以降 書き出し"),
                    tr_text("このQGIS環境にはDGN V8/2004以降を書き出すDGNv8ドライバがありません。\n"
                    "標準のQGIS/GDALではDGN V7だけが作成可能です。\n"
                    "DXF（R12）またはDGN V7を使ってください。"),
                )
            return False
        if os.path.exists(path):
            try:
                driver.DeleteDataSource(path)
            except Exception:
                os.remove(path)
        options = ["3D=NO", "ENCODING=CP932"] if legacy else ["APPLICATION=OrthoManager"]
        try:
            ds = driver.CreateDataSource(path, options=options)
            if ds is None:
                QMessageBox.critical(self, tr_text(f"{label}書き出し"), tr_text(f"{label}を作成できませんでした。"))
                return False
            if legacy:
                srs = self._ogr_srs_from_layer(layers[0]) if layers else None
                ogr_layer = ds.CreateLayer("elements", srs, ogr.wkbUnknown)
                defn = ogr_layer.GetLayerDefn()
                for level, layer in enumerate(layers, start=1):
                    self._export_layer_to_dgn_ogr_layer(ogr_layer, defn, layer, level)
            else:
                for level, layer in enumerate(layers, start=1):
                    layer_name = _safe_layer_name(self.layer_base_name(layer)) or f"level_{level}"
                    srs = self._ogr_srs_from_layer(layer)
                    ogr_layer = ds.CreateLayer(layer_name, srs, ogr.wkbUnknown, options=["DIM=2"])
                    if ogr_layer is None:
                        raise RuntimeError(f"DGN V8レイヤを作成できませんでした: {layer_name}")
                    defn = ogr_layer.GetLayerDefn()
                    self._export_layer_to_dgn_ogr_layer(ogr_layer, defn, layer, level)
            ds = None
            return True
        except Exception as exc:
            QMessageBox.critical(self, tr_text(f"{label}書き出し"), tr_text(f"{label}を書き出せませんでした。\n{exc}"))
            return False

    def _export_layer_to_dgn_ogr_layer(self, ogr_layer, defn, layer, level):
        color = str(layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000") or "ff0000").replace("#", "")
        color_index = self._cad_color_index(color)
        geom_type = self.layer_geom_type_key(layer)
        level = max(1, min(63, int(level)))
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            out = ogr.Feature(defn)
            self._set_dgn_common_fields(out, defn, level, color_index, layer, geom_type)
            out.SetGeometry(ogr.CreateGeometryFromWkt(geom.asWkt()))
            out.SetStyleString(self._dxf_geometry_style(layer, geom_type, color))
            ogr_layer.CreateFeature(out)
            out = None
            memo = self._feature_text(feature, "memo").strip()
            if memo:
                label_geom = self._memo_label_geometry(geom, geom_type)
                if label_geom and not label_geom.isEmpty():
                    text_feature = ogr.Feature(defn)
                    self._set_dgn_common_fields(text_feature, defn, level, color_index, layer, geom_type)
                    if defn.GetFieldIndex("Text") >= 0:
                        text_feature.SetField("Text", memo[:250])
                    text_feature.SetGeometry(ogr.CreateGeometryFromWkt(label_geom.asWkt()))
                    text = self._dxf_style_text(memo)
                    text_feature.SetStyleString(f'LABEL(f:"MS Gothic",s:2.5g,t:"{text}",c:#{color},p:5)')
                    ogr_layer.CreateFeature(text_feature)
                    text_feature = None

    def _set_dgn_common_fields(self, feature, defn, level, color_index, layer, geom_type):
        values = {
            "Level": level,
            "ColorIndex": color_index,
            "Weight": max(0, min(31, int(round(self.layer_size_value(layer, "stroke_width", self.default_stroke_width(geom_type)))))),
            "Style": 0,
        }
        for name, value in values.items():
            if defn.GetFieldIndex(name) >= 0:
                feature.SetField(name, value)

    def _memo_label_geometry(self, geometry, geom_type):
        try:
            if geom_type == "line":
                length = geometry.length()
                if length > 0:
                    return geometry.interpolate(length / 2.0)
            if geom_type == "polygon":
                point = geometry.pointOnSurface()
                if point and not point.isEmpty():
                    return point
            if geom_type == "point":
                return geometry.centroid()
            return geometry.centroid()
        except Exception:
            try:
                return geometry.centroid()
            except Exception:
                return None

    def _dxf_geometry_style(self, layer, geom_type, color):
        stroke_width = self.layer_size_value(layer, "stroke_width", self.default_stroke_width(geom_type))
        point_size = self.layer_size_value(layer, "point_size", self.default_point_size())
        if geom_type == "point":
            return f"SYMBOL(c:#{color},s:{point_size:g}g)"
        return f"PEN(c:#{color},w:{stroke_width:g}px)"

    def _feature_text(self, feature, field_name):
        try:
            if feature.fields().indexOf(field_name) >= 0:
                value = feature[field_name]
                return "" if value is None else str(value)
        except Exception:
            pass
        return ""

    def _dxf_style_text(self, text):
        text = str(text).replace("\\", "\\\\").replace('"', '\\"')
        return text.replace("\r\n", "\\P").replace("\n", "\\P").replace("\r", "\\P")

    def _ogr_srs_from_layer(self, layer):
        crs = layer.crs()
        if crs and crs.isValid() and crs.postgisSrid() > 0:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(crs.postgisSrid())
            return srs
        return None

    def save_state(self):
        self.write_gpkg_management_state()
        return {
            "version": 4,
            "gpkg_path": self.gpkg_path,
            "gpkg_paths": dict(self.gpkg_paths),
        }

    def restore_state(self, state):
        if not isinstance(state, dict):
            return
        self.layers.clear()
        self.active_inspection_type = INSPECTION_TYPE_FREE
        self.last_free_geom_type = "line"
        self.free_groups = []
        self.gpkg_paths = {inspection_type: "" for inspection_type in INSPECTION_TYPES}
        saved_paths = state.get("gpkg_paths", {})
        if isinstance(saved_paths, dict):
            for key, path in saved_paths.items():
                if key in INSPECTION_TYPES:
                    self.gpkg_paths[key] = self.resolve_saved_gpkg_path(path)
        legacy_path = self.resolve_saved_gpkg_path(state.get("gpkg_path", ""))
        if legacy_path and not any(self.gpkg_paths.values()):
            self.gpkg_paths[INSPECTION_TYPE_FREE] = legacy_path
        self.sync_active_gpkg_path()
        if self.gpkg_path:
            for key in INSPECTION_TYPES:
                self.gpkg_paths[key] = self.gpkg_path
        if self.gpkg_path and os.path.exists(self.gpkg_path):
            self.load_layers_from_gpkg()
        self.refresh_ui()

    def resolve_saved_gpkg_path(self, path):
        path = path or ""
        if path and not os.path.exists(path):
            alt = os.path.join(self.project_home(), os.path.basename(path)) if self.project_home() else ""
            if alt and os.path.exists(alt):
                path = alt
        return path if path else ""

    def clear_inspection_state(self, remove_layers=True):
        if remove_layers:
            removed_any = False
            for layer in list(self.inspection_layers()):
                try:
                    self.force_removed_layer_canvas_refresh(layer)
                    QgsProject.instance().removeMapLayer(layer.id())
                    removed_any = True
                except Exception:
                    pass
            if self.close_project_trash_layers_and_group():
                removed_any = True
            if removed_any:
                QApplication.processEvents()
                self.force_removed_layer_canvas_refresh()
        self.layers.clear()
        self.trash_layer_ids.clear()
        self.free_groups.clear()
        self.active_layer_id = ""
        self.gpkg_path = ""
        self.gpkg_paths = {inspection_type: "" for inspection_type in INSPECTION_TYPES}
        self.active_inspection_type = INSPECTION_TYPE_FREE
        self.operation_mode = "create"
        self.refresh_ui()

    def clear_inspection_type_state(self, inspection_type, remove_layers=True, clear_path=True):
        inspection_type = inspection_type if inspection_type in INSPECTION_TYPES else self.active_inspection_type
        if remove_layers:
            removed_any = False
            for layer in list(self.inspection_layers()):
                if self.layer_inspection_type(layer) == inspection_type:
                    try:
                        self.force_removed_layer_canvas_refresh(layer)
                        QgsProject.instance().removeMapLayer(layer.id())
                        removed_any = True
                    except Exception:
                        pass
            if inspection_type == self.active_inspection_type:
                if self.close_project_trash_layers_and_group():
                    removed_any = True
            if removed_any:
                QApplication.processEvents()
                self.force_removed_layer_canvas_refresh()
        for source, info in list(self.layers.items()):
            if info.get("inspection_type") == inspection_type:
                self.layers.pop(source, None)
        if inspection_type == INSPECTION_TYPE_FREE:
            self.free_groups.clear()
            self.active_free_group_name = ""
        if clear_path:
            self.set_inspection_gpkg_path(inspection_type, "")
        if inspection_type == self.active_inspection_type:
            self.trash_layer_ids.clear()
            self.active_layer_id = ""
        self.refresh_ui()

    def cleanup_before_unload(self):
        self.cleanup_layer_tree_copy_menu()
        self.disconnect_guide_layer_refresh_signals()
        self.restore_selection_color()
        try:
            if self.map_tool and self.iface.mapCanvas().mapTool() == self.map_tool:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
        except Exception:
            pass
        self.map_tool = None

