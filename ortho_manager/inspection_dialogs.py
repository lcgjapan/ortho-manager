from .diagnostics import record_ignored_exception as _om_record_ignored_exception
from .i18n import tr_text
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QKeySequenceEdit,
)
from qgis.core import Qgis, QgsProject

from .inspection_constants import (
    DGN_LEGACY_EXPORT_ONE_FILE,
    DGN_LEGACY_EXPORT_PER_LAYER,
    DXF_EXPORT_ONE_FILE,
    DXF_EXPORT_PER_LAYER,
    GEOM_TYPE_LABELS,
    INSPECTION_HOLD_SHORTCUT_KEYS,
    INSPECTION_SHORTCUT_DEFINITIONS,
    INSPECTION_ANGLE_SNAP_ALLOWED_DEGREES,
    INSPECTION_ANGLE_SNAP_BASIS_DEFAULT,
    INSPECTION_ANGLE_SNAP_BASIS_MAP,
    INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE,
    INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES,
    SHP_EXPORT_MERGED,
    SHP_EXPORT_PER_LAYER,
    TEST_DXF_EXPORT_ONE_FILE,
    TEST_DXF_EXPORT_PER_LAYER,
)


class InspectionExportDialog(QDialog):
    def __init__(self, tab, layers, parent=None):
        super().__init__(parent)
        self.tab = tab
        self.layers = layers
        self.layer_checks = []
        self.setWindowTitle(tr_text("検査書出"))
        self.resize(460, 500)

        layout = QVBoxLayout(self)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel(tr_text("形式:")))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SHP", "DXF（R12）", tr_text("DXF（AutoCAD 2000系）"), "DGN V7"])
        self.format_combo.currentTextChanged.connect(self.update_export_modes)
        fmt_row.addWidget(self.format_combo)
        layout.addLayout(fmt_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr_text("出力方法:")))
        self.mode_combo = QComboBox()
        mode_row.addWidget(self.mode_combo)
        layout.addLayout(mode_row)
        self.update_export_modes(self.format_combo.currentText())

        layout.addWidget(QLabel(tr_text("書き出す検査レイヤ:")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for layer in layers:
            count = layer.featureCount()
            geom_label = tab.layer_geom_type_label(layer)
            label = f"{tab.layer_base_name(layer)}（{geom_label} / {count}）"
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.setProperty("layer_id", layer.id())
            inner_layout.addWidget(chk)
            self.layer_checks.append(chk)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_export_modes(self, fmt):
        self.mode_combo.clear()
        if fmt == "SHP":
            self.mode_combo.addItem(tr_text("レイヤごとにSHP作成"), SHP_EXPORT_PER_LAYER)
            self.mode_combo.addItem(tr_text("同じ図形タイプなら1つのSHPにまとめる"), SHP_EXPORT_MERGED)
        elif fmt == "DXF（R12）":
            self.mode_combo.addItem(tr_text("1つのDXF（R12）にまとめる"), DXF_EXPORT_ONE_FILE)
            self.mode_combo.addItem(tr_text("レイヤごとにDXF（R12）作成"), DXF_EXPORT_PER_LAYER)
        elif fmt == "DXF（AutoCAD 2000系）":
            self.mode_combo.addItem(tr_text("1つのDXF（AutoCAD 2000系）にまとめる"), TEST_DXF_EXPORT_ONE_FILE)
            self.mode_combo.addItem(tr_text("レイヤごとにDXF（AutoCAD 2000系）作成"), TEST_DXF_EXPORT_PER_LAYER)
        else:
            self.mode_combo.addItem(tr_text("1つのDGN V7にまとめる（Level分け）"), DGN_LEGACY_EXPORT_ONE_FILE)
            self.mode_combo.addItem(tr_text("レイヤごとにDGN V7作成"), DGN_LEGACY_EXPORT_PER_LAYER)

    def selected_layers(self):
        result = []
        for chk in self.layer_checks:
            if chk.isChecked():
                layer = QgsProject.instance().mapLayer(chk.property("layer_id"))
                if layer and layer.featureCount() > 0:
                    result.append(layer)
        return result

    def selected_format(self):
        return self.format_combo.currentText()

    def selected_output_mode(self):
        return self.mode_combo.currentData()


class MemoTextEdit(QTextEdit):
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.insertPlainText("\n")
            else:
                self.dialog.accept()
            return
        super().keyPressEvent(event)


class MemoDialog(QDialog):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr_text("検査メモ"))
        self.resize(360, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr_text("Enter: OK / Ctrl+Enter: 改行")))
        self.text_edit = MemoTextEdit(self)
        self.text_edit.setPlainText(text or "")
        layout.addWidget(self.text_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.text_edit.setFocus()

    def text(self):
        return self.text_edit.toPlainText()


class InspectionShortcutDialog(QDialog):
    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.tab = tab
        self.editors = {}
        self.setWindowTitle(tr_text("検査ショートカット設定"))
        self.resize(420, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr_text("検査ONでOrthoManagerの検査マップ操作中だけ有効です。")))
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel(tr_text("指定角度単位")))
        self.angle_snap_combo = QComboBox()
        angle_items = {
            0: "OFF",
            90: "90°",
            45: "45°",
            30: "30°",
            15: "15°",
        }
        for value in INSPECTION_ANGLE_SNAP_ALLOWED_DEGREES:
            self.angle_snap_combo.addItem(angle_items.get(value, f"{value}°"), value)
        current_degrees = tab.inspection_angle_snap_degrees()
        angle_index = self.angle_snap_combo.findData(current_degrees)
        if angle_index < 0:
            angle_index = self.angle_snap_combo.findData(INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES)
        self.angle_snap_combo.setCurrentIndex(max(angle_index, 0))
        angle_row.addWidget(self.angle_snap_combo)
        angle_row.addStretch()
        layout.addLayout(angle_row)
        basis_row = QHBoxLayout()
        basis_row.addWidget(QLabel(tr_text("角度補正基準")))
        self.angle_snap_basis_combo = QComboBox()
        self.angle_snap_basis_combo.addItem(tr_text("地図座標基準"), INSPECTION_ANGLE_SNAP_BASIS_MAP)
        self.angle_snap_basis_combo.addItem(tr_text("直前辺基準"), INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE)
        basis = tab.inspection_angle_snap_basis()
        basis_index = self.angle_snap_basis_combo.findData(basis)
        if basis_index < 0:
            basis_index = self.angle_snap_basis_combo.findData(INSPECTION_ANGLE_SNAP_BASIS_DEFAULT)
        self.angle_snap_basis_combo.setCurrentIndex(max(basis_index, 0))
        basis_row.addWidget(self.angle_snap_basis_combo)
        basis_row.addStretch()
        layout.addLayout(basis_row)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        row = 0
        shortcuts = tab.inspection_shortcuts()
        for key, label, default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            display_label = tr_text(label)
            grid.addWidget(QLabel(display_label), row, 0)
            editor = QKeySequenceEdit()
            self._apply_key_sequence_placeholder(editor)
            current = shortcuts.get(key, default_value) or ""
            if current:
                editor.setKeySequence(QKeySequence(current))
            editor.setToolTip(tr_text("空欄にすると未設定になります。"))
            clear_btn = QPushButton(tr_text("クリア"))
            clear_btn.setFixedWidth(56)
            clear_btn.clicked.connect(lambda _=False, e=editor: e.clear())
            grid.addWidget(editor, row, 1)
            grid.addWidget(clear_btn, row, 2)
            self.editors[key] = editor
            row += 1
        layout.addLayout(grid)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        restore_button = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if ok_button:
            ok_button.setText("OK")
        if cancel_button:
            cancel_button.setText(tr_text("キャンセル"))
        if restore_button:
            restore_button.setText(tr_text("デフォルトに戻す"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if restore_button:
            restore_button.clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)

    def _apply_key_sequence_placeholder(self, editor):
        placeholder = tr_text("ショートカットを押してください")
        try:
            if hasattr(editor, "setPlaceholderText"):
                editor.setPlaceholderText(placeholder)
        except Exception:
            _om_record_ignored_exception(__name__, 246)
        try:
            for child in editor.findChildren(QLineEdit):
                child.setPlaceholderText(placeholder)
        except Exception:
            _om_record_ignored_exception(__name__, 251)

    def restore_defaults(self):
        index = self.angle_snap_combo.findData(INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES)
        self.angle_snap_combo.setCurrentIndex(max(index, 0))
        basis_index = self.angle_snap_basis_combo.findData(INSPECTION_ANGLE_SNAP_BASIS_DEFAULT)
        self.angle_snap_basis_combo.setCurrentIndex(max(basis_index, 0))
        for key, _label, default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            self.editors[key].setKeySequence(QKeySequence(default_value or ""))

    def angle_snap_degrees(self):
        try:
            return int(self.angle_snap_combo.currentData())
        except Exception:
            return INSPECTION_ANGLE_SNAP_DEFAULT_DEGREES

    def angle_snap_basis(self):
        value = self.angle_snap_basis_combo.currentData()
        if value in (INSPECTION_ANGLE_SNAP_BASIS_MAP, INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE):
            return value
        return INSPECTION_ANGLE_SNAP_BASIS_DEFAULT

    def values(self):
        result = {}
        used = {}
        for key, label, _default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            display_label = tr_text(label)
            text = self.editors[key].keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            if not text:
                result[key] = ""
                continue
            norm = self.tab.normalize_shortcut_text(text)
            if key in INSPECTION_HOLD_SHORTCUT_KEYS and not self.tab.valid_hold_shortcut_text(text):
                QMessageBox.warning(self, tr_text("補助キー設定"), tr_text(f"「{display_label}」は単独キーだけ設定できます。Ctrl/Shift/Alt付き、Esc、Backspace、Delete、Spaceなどは使えません。"))
                return None
            if norm in used:
                QMessageBox.warning(self, tr_text("ショートカット重複"), tr_text(f"「{used[norm]}」と「{display_label}」に同じキーが設定されています。"))
                return None
            used[norm] = display_label
            result[key] = text
        return result


class VectorImportOptionsDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths or [])
        self.setWindowTitle(tr_text("ベクタ取込"))
        self.resize(420, 170)
        layout = QVBoxLayout(self)

        file_count = len(self.paths)
        dxf_count = sum(1 for path in self.paths if os.path.splitext(path)[1].lower() == ".dxf")
        shp_count = sum(1 for path in self.paths if os.path.splitext(path)[1].lower() == ".shp")
        single_dxf = file_count == 1 and dxf_count == 1
        default_name = ""
        if single_dxf:
            default_name = os.path.splitext(os.path.basename(self.paths[0]))[0]
        elif file_count > 1:
            default_name = "取込ベクタグループ"

        self.group_check = QCheckBox(tr_text("1つのグループとして読み込む"))
        self.group_check.setChecked(single_dxf or file_count > 1)
        layout.addWidget(self.group_check)

        grid = QGridLayout()
        grid.addWidget(QLabel(tr_text("グループ名:")), 0, 0)
        self.name_mode_combo = QComboBox()
        if single_dxf:
            self.name_mode_combo.addItem(tr_text("DXFファイル名を使う"), "file")
            self.name_mode_combo.addItem(tr_text("手動入力"), "manual")
        else:
            self.name_mode_combo.addItem(tr_text("手動入力"), "manual")
        grid.addWidget(self.name_mode_combo, 0, 1)
        self.group_name_edit = QLineEdit(default_name)
        grid.addWidget(self.group_name_edit, 1, 1)
        layout.addLayout(grid)

        info = "DXF内のLayerは検査レイヤとして分けて読み込みます。"
        if shp_count > 1:
            info = "複数SHPは選択したグループ内にまとめて読み込みます。"
        layout.addWidget(QLabel(info))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name_mode_combo.currentIndexChanged.connect(self._sync_group_name)
        self.group_check.toggled.connect(self._sync_enabled)
        self._sync_group_name()
        self._sync_enabled()

    def _sync_group_name(self):
        if self.name_mode_combo.currentData() == "file" and self.paths:
            self.group_name_edit.setText(os.path.splitext(os.path.basename(self.paths[0]))[0])

    def _sync_enabled(self):
        enabled = self.group_check.isChecked()
        self.name_mode_combo.setEnabled(enabled)
        self.group_name_edit.setEnabled(enabled)

    def options(self):
        use_group = self.group_check.isChecked()
        name = self.group_name_edit.text().strip() if use_group else ""
        return {"use_group": use_group, "group_name": name}


class QgisLayerImportDialog(QDialog):
    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self.layers = list(layers or [])
        self.checks = []
        self.owner = parent
        self.setWindowTitle(tr_text("QGISレイヤ取込"))
        self.resize(460, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr_text("検査GPKGへコピーするQGISレイヤを選択してください。")))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for layer in self.layers:
            group_name = self._group_name(layer)
            group_label = group_name if group_name else "グループなし"
            label = f"[{group_label}] {layer.name()}（{GEOM_TYPE_LABELS.get(self._geom_type(layer), 'ベクタ')} / {layer.featureCount()}）"
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.setProperty("layer_id", layer.id())
            inner_layout.addWidget(chk)
            self.checks.append(chk)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _geom_type(self, layer):
        if layer.geometryType() == Qgis.GeometryType.Line:
            return "line"
        if layer.geometryType() == Qgis.GeometryType.Point:
            return "point"
        if layer.geometryType() == Qgis.GeometryType.Polygon:
            return "polygon"
        return ""

    def _group_name(self, layer):
        try:
            if self.owner and hasattr(self.owner, "qgis_layer_source_group_name"):
                return self.owner.qgis_layer_source_group_name(layer)
        except Exception:
            _om_record_ignored_exception(__name__, 405)
        return ""

    def selected_layer_ids(self):
        return [chk.property("layer_id") for chk in self.checks if chk.isChecked()]
