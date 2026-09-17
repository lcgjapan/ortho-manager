from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import os
import time

from qgis.PyQt.QtCore import Qt, QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMessageLog, Qgis

from .i18n import tr, tr_text


POINT_CLOUD_EXTENSIONS = (".las", ".laz", ".copc", ".copc.laz")


def is_supported_point_cloud_path(path):
    name = str(path or "").lower()
    return name.endswith(POINT_CLOUD_EXTENSIONS)


class PointCloudSourceListWindow(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.manager = manager
        self.setMinimumSize(760, 460)
        self._build_ui()
        self.refresh_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        path_row = QHBoxLayout()
        self.path_label = QLabel()
        self.vpc_path_edit = QLineEdit()
        self.vpc_path_edit.setReadOnly(True)
        path_row.addWidget(self.path_label)
        path_row.addWidget(self.vpc_path_edit, 1)
        layout.addLayout(path_row)

        header_row = QHBoxLayout()
        self.header_label = QLabel()
        self.header_label.setStyleSheet("font-weight:bold;")
        self.count_label = QLabel()
        header_row.addWidget(self.header_label)
        header_row.addStretch()
        header_row.addWidget(self.count_label)
        layout.addLayout(header_row)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self._filter_list)
        self.btn_clear_search = QPushButton("×")
        self.btn_clear_search.setFixedWidth(28)
        self.btn_clear_search.clicked.connect(self._clear_search)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(self.btn_clear_search)
        layout.addLayout(search_row)

        self.source_listwidget = QListWidget()
        self.source_listwidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.source_listwidget, 1)

        option_row = QHBoxLayout()
        self.chk_subfolders = QCheckBox()
        self.chk_subfolders.setChecked(bool(self.manager.include_subfolders))
        self.chk_subfolders.toggled.connect(self.manager.set_include_subfolders)
        option_row.addWidget(self.chk_subfolders)
        option_row.addStretch()
        layout.addLayout(option_row)

        btn_row = QHBoxLayout()
        self.btn_add_folder = QPushButton()
        self.btn_add_folder.clicked.connect(self.manager.add_from_folder)
        self.btn_add_files = QPushButton()
        self.btn_add_files.clicked.connect(self.manager.add_files)
        self.btn_select_map = QPushButton()
        self.btn_select_map.clicked.connect(self.manager.activate_overlay_select_tool)
        self.btn_select_map.setStyleSheet(self.manager.vrt_tab._btn_style("#f39c12"))
        self.btn_remove = QPushButton()
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self._clear_all)
        btn_row.addWidget(self.btn_add_folder)
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_select_map)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

    def refresh_texts(self):
        self.setWindowTitle(tr("vpc.window.title"))
        self.path_label.setText(tr("vpc.label.vpc_path"))
        self.vpc_path_edit.setPlaceholderText(tr("vpc.placeholder.vpc_path"))
        self.header_label.setText(tr("vpc.window.title"))
        self.search_edit.setPlaceholderText(tr("vpc.placeholder.search"))
        self.chk_subfolders.setText(tr("vpc.checkbox.subfolders"))
        self.btn_add_folder.setText(tr("vpc.btn.add_folder"))
        self.btn_add_files.setText(tr("vpc.btn.add_files"))
        self.btn_select_map.setText(tr("vpc.btn.map_remove"))
        self.btn_remove.setText(tr("vpc.btn.remove"))
        self.btn_clear.setText(tr("vpc.btn.clear"))
        self.update_path_display()
        self.update_count()

    def reload_list(self):
        self.source_listwidget.clear()
        for path in self.manager.display_source_list():
            item = QListWidgetItem(path)
            item.setToolTip(path)
            self.source_listwidget.addItem(item)
        self.update_path_display()
        self.update_count()
        self._filter_list(self.search_edit.text())

    def update_path_display(self):
        self.vpc_path_edit.setText(self.manager.vpc_path())

    def update_count(self):
        self.count_label.setText(tr("vpc.label.file_count").format(count=len(self.manager.source_list())))

    def _filter_list(self, keyword):
        keyword = (keyword or "").lower()
        for i in range(self.source_listwidget.count()):
            item = self.source_listwidget.item(i)
            item.setHidden(keyword not in item.text().lower())

    def _clear_search(self):
        self.search_edit.clear()
        self._filter_list("")

    def _remove_selected(self):
        selected_paths = {item.text() for item in self.source_listwidget.selectedItems()}
        if not selected_paths:
            selected_paths = self.manager.selected_overlay_paths()
        if not selected_paths:
            QMessageBox.information(
                self,
                tr_text("情報"),
                tr_text("削除対象がありません。\n一覧から選択するか、「マップから削除」で範囲を選択してください。"),
            )
            return
        reply = QMessageBox.question(
            self,
            tr_text("確認"),
            tr_text(
                f"{len(selected_paths)} 件の点群をVPC一覧から削除して更新しますか？\n\n"
                "元のLAS/LAZ/COPCファイルは削除されません。\n"
                "このVPC用にOrthoManagerが自動生成した表示用COPC（copc.laz）は削除されます。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.manager.remove_paths(list(selected_paths))
        self.manager.clear_overlay_selection()
        self.manager.restore_previous_map_tool()

    def _clear_all(self):
        if not self.manager.source_list():
            return
        reply = QMessageBox.question(
            self,
            tr_text("確認"),
            tr_text(
                "点群一覧を空にしますか？\n\n"
                "元のLAS/LAZ/COPCファイルは削除されません。\n"
                "このVPC用にOrthoManagerが自動生成した表示用COPC（copc.laz）は削除されます。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.manager.clear_sources()


class PointCloudVpcManager:
    def __init__(self, vrt_tab):
        self.vrt_tab = vrt_tab
        self.main_ui = vrt_tab.main_ui
        self.include_subfolders = False
        self.source_list_window = None
        self.grp_vpc = None
        self.previous_map_tool = None

    def build_ui(self, parent_layout):
        self.grp_vpc = QGroupBox()
        layout = QVBoxLayout(self.grp_vpc)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        combo_row = QHBoxLayout()
        self.vpc_combo = QComboBox()
        self.vpc_combo.setMinimumWidth(0)
        self.vpc_combo.setMaximumWidth(260)
        self.vpc_combo.setMinimumContentsLength(12)
        self.vpc_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        try:
            self.vpc_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        except Exception:
            _om_record_ignored_exception(__name__, 218)
        self.vpc_combo.currentIndexChanged.connect(self.switch_vpc)
        self.vpc_combo.activated.connect(self.activate_combo_target)
        combo_row.addWidget(self.vpc_combo, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(combo_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_new = QPushButton()
        self.btn_new.setFixedWidth(48)
        self.btn_new.clicked.connect(self.new_vpc)
        self.btn_new.setStyleSheet(self.vrt_tab._btn_style("#27ae60"))
        self.btn_rename = QPushButton()
        self.btn_rename.setFixedWidth(66)
        self.btn_rename.clicked.connect(self.rename_vpc)
        self.btn_rename.setStyleSheet(self.vrt_tab._btn_style("#2980b9"))
        self.btn_rename.setEnabled(False)
        self.btn_load = QPushButton()
        self.btn_load.setFixedWidth(66)
        self.btn_load.clicked.connect(self.load_existing_vpc)
        self.btn_load.setStyleSheet(self.vrt_tab._btn_style("#8e44ad"))
        self.btn_delete = QPushButton()
        self.btn_delete.setFixedWidth(46)
        self.btn_delete.clicked.connect(self.delete_vpc)
        self.btn_delete.setStyleSheet(self.vrt_tab._btn_style("#e74c3c"))
        self.btn_source_list = QPushButton()
        self.btn_source_list.setFixedWidth(78)
        self.btn_source_list.clicked.connect(self.open_source_list_window)
        self.btn_source_list.setStyleSheet(self.vrt_tab._btn_style("#34495e"))
        self.btn_organize = QPushButton()
        self.btn_organize.setFixedWidth(78)
        self.btn_organize.clicked.connect(self.organize_layers)
        self.btn_organize.setStyleSheet(self.vrt_tab._btn_style("#7f8c8d"))
        self.btn_update_vpc = QPushButton()
        self.btn_update_vpc.setFixedWidth(78)
        self.btn_update_vpc.clicked.connect(self.update_vpc)
        self.btn_update_vpc.setStyleSheet(self.vrt_tab._btn_style("#7f8c8d"))
        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_rename)
        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)
        btn_row2.addWidget(self.btn_organize)
        btn_row2.addWidget(self.btn_update_vpc)
        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        file_row = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet("font-weight:bold;")
        file_row.addWidget(self.count_label)
        file_row.addSpacing(52)
        file_row.addWidget(self.btn_source_list)
        file_row.addStretch()
        layout.addLayout(file_row)

        parent_layout.addWidget(self.grp_vpc)
        self.refresh_texts()
        self.refresh_action_buttons()

    def refresh_texts(self):
        if not self.grp_vpc:
            return
        self.grp_vpc.setTitle(tr("vpc.group"))
        self.btn_new.setText(tr("vpc.btn.new"))
        self.btn_rename.setText(tr("vpc.btn.rename"))
        self.btn_load.setText(tr("vpc.btn.load"))
        self.btn_delete.setText(tr("vpc.btn.delete"))
        self.btn_organize.setText(tr("vpc.btn.organize"))
        self.btn_update_vpc.setText(tr("vpc.btn.update"))
        self.btn_update_vpc.setToolTip(tr("vpc.btn.update.tooltip"))
        self.btn_source_list.setText(tr("vpc.btn.source_list"))
        self.update_count()
        if self.source_list_window is not None:
            self.source_list_window.refresh_texts()

    def source_list(self):
        return self.main_ui.vpc_registry.get(self.main_ui.current_vpc_name, {}).get("source_list", [])

    def vpc_path(self):
        return self.main_ui.vpc_registry.get(self.main_ui.current_vpc_name, {}).get("path", "")

    def display_source_list(self):
        return list(self.source_list())

    def _combo_display_text(self, full_name):
        width = self.vpc_combo.width() if self.vpc_combo.width() > 40 else 230
        return self.vpc_combo.fontMetrics().elidedText(
            full_name,
            Qt.TextElideMode.ElideMiddle,
            max(80, min(width, self.vpc_combo.maximumWidth()) - 30),
        )

    def _add_combo_item(self, full_name):
        was_blocked = self.vpc_combo.blockSignals(True)
        self.vpc_combo.addItem(self._combo_display_text(full_name))
        idx = self.vpc_combo.count() - 1
        self.vpc_combo.setItemData(idx, full_name, Qt.ItemDataRole.UserRole)
        self.vpc_combo.setItemData(idx, full_name, Qt.ItemDataRole.ToolTipRole)
        self.vpc_combo.blockSignals(was_blocked)

    def current_combo_name(self):
        idx = self.vpc_combo.currentIndex()
        if idx < 0:
            return ""
        return self.vpc_combo.itemData(idx, Qt.ItemDataRole.UserRole) or self.vpc_combo.currentText()

    def set_current_vpc_name(self, name):
        idx = self.vpc_combo.findData(name, Qt.ItemDataRole.UserRole)
        if idx >= 0:
            self.vpc_combo.setCurrentIndex(idx)
        else:
            self.vpc_combo.setCurrentText(name)

    def populate_combo(self):
        if not hasattr(self, "vpc_combo"):
            return
        self.vpc_combo.blockSignals(True)
        self.vpc_combo.clear()
        for name in self.main_ui.vpc_registry:
            self._add_combo_item(name)
        if self.main_ui.current_vpc_name:
            self.set_current_vpc_name(self.main_ui.current_vpc_name)
        self.vpc_combo.blockSignals(False)
        self.update_combo_tooltip()
        self.refresh_action_buttons()

    def activate_combo_target(self, index):
        self.set_scale_target_vpc()
        self.update_combo_tooltip()
        self.refresh_action_buttons()

    def update_combo_tooltip(self):
        if not hasattr(self, "vpc_combo"):
            return
        current = self.current_combo_name()
        self.vpc_combo.setToolTip(current)
        for i in range(self.vpc_combo.count()):
            full_name = self.vpc_combo.itemData(i, Qt.ItemDataRole.UserRole) or self.vpc_combo.itemText(i)
            self.vpc_combo.setItemText(i, self._combo_display_text(full_name))
            self.vpc_combo.setItemData(i, full_name, Qt.ItemDataRole.ToolTipRole)

    def refresh_action_buttons(self):
        has_current = bool(self.main_ui.current_vpc_name or self.main_ui.vpc_registry)
        if hasattr(self, "btn_rename"):
            self.btn_rename.setEnabled(has_current)
        if hasattr(self, "btn_delete"):
            self.btn_delete.setEnabled(has_current)
        if hasattr(self, "btn_organize"):
            self.btn_organize.setEnabled(has_current)
        if hasattr(self, "btn_update_vpc"):
            self.btn_update_vpc.setEnabled(has_current)
        if hasattr(self, "btn_source_list"):
            self.btn_source_list.setEnabled(has_current)

    def set_scale_target_vpc(self):
        if hasattr(self.vrt_tab, "set_scale_target_mode"):
            self.vrt_tab.set_scale_target_mode("vpc")
            return
        self.main_ui.scale_target_mode = "vpc"
        try:
            self.vrt_tab.sync_scale_highlight_from_current_target()
        except Exception:
            _om_record_ignored_exception(__name__, 385)

    def update_count(self):
        text = tr("vpc.label.file_count").format(count=len(self.source_list()))
        if hasattr(self, "count_label"):
            self.count_label.setText(text)
        if self.source_list_window is not None:
            self.source_list_window.update_count()

    def update_path_display(self):
        if self.source_list_window is not None:
            self.source_list_window.update_path_display()

    def reload_source_listwidget(self):
        self.update_count()
        if self.source_list_window is not None:
            self.source_list_window.reload_list()

    def project_default_dir(self):
        return self.vrt_tab._project_default_dir()

    def _safe_default_dir(self):
        for folder in (
            self.current_source_dir(),
            self.current_vpc_file_dir(),
            self.project_default_dir(),
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.expanduser("~"),
        ):
            try:
                if folder and os.path.isdir(folder):
                    return os.path.normpath(folder)
            except Exception:
                _om_record_ignored_exception(__name__, 418)
        return ""

    def _last_vpc_dialog_dir(self):
        try:
            folder = QSettings().value("OrthoManager/last_vpc_dialog_dir", "", type=str)
            if folder and os.path.isdir(folder):
                return os.path.normpath(folder)
        except Exception:
            _om_record_ignored_exception(__name__, 427)
        return ""

    def _remember_vpc_dialog_path(self, path):
        try:
            folder = path if os.path.isdir(path) else os.path.dirname(os.path.normpath(str(path or "")))
            if folder and os.path.isdir(folder):
                QSettings().setValue("OrthoManager/last_vpc_dialog_dir", os.path.normpath(folder))
        except Exception:
            _om_record_ignored_exception(__name__, 436)

    def current_source_dir(self):
        for path in self.source_list():
            try:
                folder = os.path.dirname(os.path.normpath(os.path.abspath(path)))
            except Exception:
                folder = ""
            if folder and os.path.isdir(folder):
                return folder
        return ""

    def current_vpc_file_dir(self):
        try:
            entry = self.main_ui.vpc_registry.get(self.main_ui.current_vpc_name, {})
            path = entry.get("path", "") if isinstance(entry, dict) else ""
            folder = os.path.dirname(os.path.normpath(os.path.abspath(path))) if path else ""
            if folder and os.path.isdir(folder):
                return folder
        except Exception:
            _om_record_ignored_exception(__name__, 456)
        return ""

    def new_vpc_default_dir(self):
        return self._last_vpc_dialog_dir() or self._safe_default_dir()

    def source_add_default_dir(self):
        return self._last_vpc_dialog_dir() or self.current_source_dir() or self.project_default_dir() or self._safe_default_dir()

    def switch_vpc(self, index):
        name = self.current_combo_name()
        if not name or name == self.main_ui.current_vpc_name:
            self.set_scale_target_vpc()
            self.update_combo_tooltip()
            self.refresh_action_buttons()
            return
        self.main_ui.current_vpc_name = name
        self.reload_source_listwidget()
        self.update_path_display()
        self.update_combo_tooltip()
        self.refresh_action_buttons()
        self.set_scale_target_vpc()
        self.main_ui._set_status(tr_text(f"🔄 VPC切り替え: {name}（{len(self.source_list())} ファイル）"))

    def new_vpc(self):
        path, _ = QFileDialog.getSaveFileName(self.vrt_tab, tr_text("新しいVPCの保存先"), self.new_vpc_default_dir(), "Virtual Point Cloud (*.vpc)")
        if not path:
            return
        self._remember_vpc_dialog_path(path)
        if not path.lower().endswith(".vpc"):
            path += ".vpc"
        base_name = os.path.splitext(os.path.basename(path))[0]
        ok_name, message = self.main_ui.validate_vpc_base_name(base_name)
        if not ok_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), message)
            return
        name = self.main_ui.format_vpc_display_name(base_name)
        if name in self.main_ui.vpc_registry:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"「{name}」はすでに登録されています"))
            return
        self.main_ui.vpc_registry[name] = {
            "path": path,
            "source_list": [],
            "group_crs_authid": "",
            "initial_crs_pending": True,
        }
        self._add_combo_item(name)
        self.main_ui.current_vpc_name = name
        self.set_scale_target_vpc()
        self.set_current_vpc_name(name)
        self.update_combo_tooltip()
        self.reload_source_listwidget()
        self.update_path_display()
        self.refresh_action_buttons()
        self.main_ui._set_status(tr_text(f"✅ 新規VPC: {name}"))
        QTimer.singleShot(0, self.open_source_list_window)

    def rename_vpc(self):
        old_name = self.main_ui.current_vpc_name
        if not old_name:
            return
        old_base_name = self.main_ui.strip_vpc_display_prefix(old_name)
        new_base_name, ok = QInputDialog.getText(
            self.vrt_tab,
            tr_text("VPC名前変更"),
            tr_text("新しいVPC名:"),
            text=old_base_name,
        )
        if not ok:
            return
        new_base_name = self.main_ui.strip_vpc_display_prefix(new_base_name)
        if new_base_name.lower().endswith(".vpc"):
            new_base_name = os.path.splitext(new_base_name)[0]
        new_name = self.main_ui.format_vpc_display_name(new_base_name)
        ok_name, message = self.main_ui.validate_vpc_base_name(new_base_name)
        if not ok_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), message)
            return
        if new_name in self.main_ui.vpc_registry and new_name != old_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"「{new_name}」はすでに登録されています"))
            return
        if new_name == old_name:
            return

        ok, reason, detail = self.main_ui.rename_vpc_entry(old_name, new_name)
        if not ok:
            if reason == "file_exists":
                names = "\n".join(os.path.basename(p) for p in detail)
                QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"同じ名前の関連ファイルがすでに存在します。\n\n{names}"))
            elif reason == "invalid":
                QMessageBox.warning(self.vrt_tab, tr_text("警告"), str(detail))
            elif reason == "rename_failed":
                QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"関連ファイル名の変更に失敗しました。\n\n{detail}"))
            elif reason == "duplicate":
                QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"「{new_name}」はすでに登録されています"))
            else:
                QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPC名の変更に失敗しました"))
            return

        self.populate_combo()
        self.set_current_vpc_name(new_name)
        self.reload_source_listwidget()
        self.update_path_display()
        self.main_ui.iface.mapCanvas().refresh()
        self.main_ui._set_status(tr_text(f"✏️ VPC名を変更しました: {old_name} → {new_name}"))

    def load_existing_vpc(self):
        path, _ = QFileDialog.getOpenFileName(self.vrt_tab, tr_text("VPCファイルを選択"), self.new_vpc_default_dir(), "Virtual Point Cloud (*.vpc)")
        if not path:
            return
        self._remember_vpc_dialog_path(path)
        base_name = os.path.splitext(os.path.basename(path))[0]
        ok_name, message = self.main_ui.validate_vpc_base_name(base_name)
        if not ok_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), message)
            return
        name = self.main_ui.format_vpc_display_name(base_name)
        source_list = self.main_ui.read_point_cloud_sources_from_vpc(path)
        raw_source_list = list(source_list)
        source_list = self.restore_original_sources_from_managed_copc(source_list, path)
        source_records = self.main_ui._read_vpc_source_records(path)
        orphaned_copc_records = self.main_ui._read_vpc_orphaned_copc_records(path)
        group_crs_authid = self.main_ui._read_vpc_group_crs_authid(path)
        orphan_result = self._audit_orphaned_copc_on_load(orphaned_copc_records, path, vpc_name=name)
        if isinstance(orphan_result, dict):
            if orphan_result.get("action") == "cancel":
                return
            orphaned_copc_records = list(orphan_result.get("orphaned_copc_records", orphaned_copc_records) or [])
        else:
            orphan_result = {"action": "continue", "save_metadata": False}
        audit_result = self._audit_vpc_sources_on_load(
            source_list,
            source_records,
            path,
            orphaned_copc_records=orphaned_copc_records,
            vpc_name=name,
        )
        if isinstance(audit_result, dict):
            if audit_result.get("action") == "cancel":
                return
            source_list = list(audit_result.get("source_list", source_list) or [])
            source_records = list(audit_result.get("source_records", source_records) or [])
            orphaned_copc_records = list(audit_result.get("orphaned_copc_records", orphaned_copc_records) or [])
        else:
            audit_result = {"action": "continue", "save_metadata": False}
        if name in self.main_ui.vpc_registry:
            reply = QMessageBox.question(
                self.vrt_tab,
                tr_text("確認"),
                tr_text(f"「{name}」はすでに登録されています。上書きしますか？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.main_ui._remove_vpc_group(name)
        else:
            self._add_combo_item(name)
        self.main_ui._set_vpc_progress(10, "VPCファイル確認中")
        self.main_ui.vpc_registry[name] = {
            "path": path,
            "source_list": source_list,
            "source_records": source_records,
            "orphaned_copc_records": orphaned_copc_records,
            "group_crs_authid": group_crs_authid,
            "initial_crs_pending": not bool(group_crs_authid),
        }
        if audit_result.get("action") != "exclude" and (source_list != raw_source_list or audit_result.get("save_metadata") or orphan_result.get("save_metadata")):
            self.main_ui.write_vpc_embedded_metadata(path, self.main_ui.vpc_registry[name])
        self.main_ui.current_vpc_name = name
        self.set_scale_target_vpc()
        self.set_current_vpc_name(name)
        self.reload_source_listwidget()
        self.update_path_display()
        self.refresh_action_buttons()
        if audit_result.get("action") == "exclude":
            if audit_result.get("delete_copc"):
                self.main_ui._remove_vpc_group(name)
                deleted, failed, skipped = self._delete_vpc_copc_paths(
                    audit_result.get("delete_copc_paths", []),
                    path,
                    label="VPC_SOURCE_MISSING_ON_LOAD_COPC_DELETE",
                )
                if failed:
                    QMessageBox.warning(
                        self.vrt_tab,
                        tr_text("警告"),
                        tr_text(f"対応COPCの一部を削除できませんでした。\n\n削除: {deleted} 件\n失敗: {failed} 件\nスキップ: {skipped} 件"),
                    )
            if not source_list:
                ok, err_msg = self.main_ui.write_empty_vpc_file(path, group_crs_authid)
                if not ok:
                    QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"空VPCとして保存できませんでした。\n\n{err_msg}"))
                    return
                self.main_ui.write_vpc_embedded_metadata(path, self.main_ui.vpc_registry[name])
                self.main_ui._remove_vpc_group(name)
                self.main_ui._set_status(tr_text(f"✅ 空のVPCを読み込みました: {name}（0 ファイル）"))
                return
            self.build_vpc()
            return
        if not source_list:
            self.main_ui._remove_vpc_group(name)
            self.main_ui._set_status(tr_text(f"✅ 空のVPCを読み込みました: {name}（0 ファイル）"))
            return
        self.main_ui._set_vpc_progress(40, "点群CRS確認中")
        selected_crs = self.main_ui._handle_vpc_crs_before_overlay_build(name)
        if not (selected_crs and selected_crs.isValid()):
            self.main_ui._set_status(tr_text("⚠️ 点群CRSが未設定のため、VPC読み込みを中止しました"))
            return
        layer = self.main_ui._load_vpc_layer(path, name, progress_percent=70)
        if layer:
            self.main_ui._set_vpc_progress(100, "点群表示完了")
            self.main_ui._set_status(tr_text(f"✅ VPC読み込み完了: {name}（{len(source_list)} ファイル）"))
        else:
            overlay_layer = self.main_ui._load_vpc_overlay_only(path, name)
            if overlay_layer:
                self.main_ui._set_status(tr_text(f"⚠️ VPC点群本体は読めませんでしたが、範囲を表示しました: {name}"))
            else:
                self.main_ui._set_status(tr_text(f"⚠️ VPC読み込み後の表示に失敗しました: {name}"))

    def organize_layers(self):
        self.set_scale_target_vpc()
        name = self.main_ui.current_vpc_name
        if not name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCが選択されていません。"))
            return
        entry = self.main_ui.vpc_registry.get(name, {})
        path = entry.get("path", "")
        if not path or not os.path.exists(path):
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCファイルが見つかりません。"))
            return
        selected_crs = self.main_ui._handle_vpc_crs_before_overlay_build(name)
        if not (selected_crs and selected_crs.isValid()):
            self.main_ui._set_status(tr_text("⚠️ 点群CRSが未設定のため、VPCレイヤ整理を中止しました"))
            return
        result = self.main_ui._organize_vpc_group_layers(name, path)
        if result:
            moved = result.get("moved", 0) if isinstance(result, dict) else 0
            removed_extra = result.get("removed_extra", 0) if isinstance(result, dict) else 0
            self.main_ui._set_status(tr_text(f"✅ VPCレイヤ整理: {name} (戻し{moved}件 / 外出し{removed_extra}件)"))
        else:
            self.main_ui._set_status(tr_text(f"⚠️ 整理できるVPC点群レイヤがありません: {name}"))

    def update_vpc(self):
        self.set_scale_target_vpc()
        name = self.main_ui.current_vpc_name
        if not name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCが選択されていません。"))
            return
        entry = self.main_ui.vpc_registry.get(name, {})
        path = entry.get("path", "")
        if not path or not os.path.exists(path):
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCファイルが見つかりません。VPC読込後に実行してください。"))
            return
        original_sources = self.restore_original_sources_from_managed_copc(entry.get("source_list", []), path)
        if not original_sources:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCに更新対象の点群ファイルがありません。"))
            return
        entry["source_list"] = original_sources
        self.main_ui.vpc_registry[name] = entry
        self.main_ui._set_vpc_progress(0, "VPC更新準備中（一時的に表示を切り替えます）")
        QApplication.processEvents()
        self.main_ui._remove_vpc_group(name)
        QTimer.singleShot(0, self.build_vpc)

    def delete_vpc(self):
        if not self.main_ui.current_vpc_name:
            return
        name = self.main_ui.current_vpc_name
        box = QMessageBox(self.vrt_tab)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr_text("確認"))
        box.setText(tr_text(f"「{name}」をOrthoManagerの一覧から削除しますか？\n※VPCファイル自体は削除されません"))
        delete_button = box.addButton(tr_text("VPCだけ削除"), QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton(tr_text("中止"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (cancel_button, None) or clicked != delete_button:
            return
        self.main_ui._remove_vpc_group(name)
        idx = self.vpc_combo.currentIndex()
        if name in self.main_ui.vpc_registry:
            del self.main_ui.vpc_registry[name]
        self.main_ui.current_vpc_name = ""
        self.vpc_combo.removeItem(idx)
        if self.main_ui.vpc_registry:
            next_name = list(self.main_ui.vpc_registry.keys())[0]
            self.main_ui.current_vpc_name = next_name
            self.set_current_vpc_name(next_name)
        self.reload_source_listwidget()
        self.update_path_display()
        self.update_combo_tooltip()
        self.refresh_action_buttons()
        self.main_ui.iface.mapCanvas().refresh()
        self.main_ui._set_status(tr_text("🗑 VPCを削除しました"))

    def open_source_list_window(self):
        if not self.main_ui.current_vpc_name and self.main_ui.vpc_registry:
            self.main_ui.current_vpc_name = list(self.main_ui.vpc_registry.keys())[0]
            self.set_current_vpc_name(self.main_ui.current_vpc_name)
        if not self.main_ui.current_vpc_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCが選択されていません。"))
            return
        self.set_scale_target_vpc()
        if self.source_list_window is None:
            try:
                parent = self.main_ui.iface.mainWindow()
            except Exception:
                parent = self.vrt_tab
            self.source_list_window = PointCloudSourceListWindow(self, parent)
        self.source_list_window.reload_list()
        self.source_list_window.show()
        self.source_list_window.raise_()
        self.source_list_window.activateWindow()

    def set_include_subfolders(self, checked):
        self.include_subfolders = bool(checked)
        QgsMessageLog.logMessage(
            f"VPC_FOLDER_OPTION include_subfolders={self.include_subfolders}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

    def _normalize_path(self, path):
        return os.path.normcase(os.path.abspath(os.path.normpath(str(path or ""))))

    def _source_records_by_source_path(self, source_records):
        records_by_source = {}
        for record in source_records or []:
            if not isinstance(record, dict):
                continue
            source_path = record.get("source_path", "")
            if not source_path:
                continue
            records_by_source[self._normalize_path(source_path)] = record
        return records_by_source

    def _delete_vpc_copc_paths(self, copc_paths, vpc_path, label="VPC_COPC_DELETE"):
        deleted = 0
        failed = 0
        skipped = 0
        try:
            copc_root = os.path.normcase(os.path.abspath(self.main_ui._copc_cache_root_for_vpc(vpc_path)))
        except Exception:
            copc_root = ""
        for copc_path in copc_paths or []:
            if not copc_path:
                continue
            try:
                copc_abs = os.path.normcase(os.path.abspath(str(copc_path)))
                if not copc_root or os.path.commonpath([copc_root, copc_abs]) != copc_root:
                    skipped += 1
                    continue
                if not os.path.exists(copc_path):
                    skipped += 1
                    continue
                os.remove(copc_path)
                deleted += 1
            except Exception as e:
                failed += 1
                QgsMessageLog.logMessage(
                    f"{label}_FAILED path={copc_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
        QgsMessageLog.logMessage(
            f"{label} deleted={deleted} failed={failed} skipped={skipped}",
            "OrthoManager",
            Qgis.MessageLevel.Info if failed == 0 else Qgis.MessageLevel.Warning,
        )
        return deleted, failed, skipped

    def _merge_orphaned_copc_records(self, base_records, add_records):
        merged = []
        seen = set()
        for record in list(base_records or []) + list(add_records or []):
            if not isinstance(record, dict):
                continue
            copc_path = record.get("copc_path", "")
            source_path = record.get("source_path", "")
            key = self._normalize_path(copc_path or source_path)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(dict(record))
        return merged

    def _vpc_audit_dialog_header(self, vpc_path, vpc_name=""):
        display_name = self.main_ui.format_vpc_display_name(vpc_name or os.path.splitext(os.path.basename(vpc_path or ""))[0])
        path_text = os.path.normpath(os.path.abspath(vpc_path)) if vpc_path else ""
        if path_text:
            return f"対象VPC: {display_name}\nVPCファイル: {path_text}\n\n"
        return f"対象VPC: {display_name}\n\n"

    def _vpc_audit_sample_text(self, title, items, limit=5):
        values = [str(item) for item in (items or []) if str(item or "").strip()]
        total = len(values)
        if not total:
            return f"{title}: 0 件"
        sample = "\n".join(values[:limit])
        if total > limit:
            return f"{title}: {total} 件\n以下は先頭 {limit} 件です。\n\n{sample}\nほか {total - limit} 件"
        return f"{title}: {total} 件\n\n{sample}"

    def _audit_orphaned_copc_on_load(self, orphaned_records, vpc_path, vpc_name=""):
        existing_records = []
        stale_records = []
        for record in orphaned_records or []:
            if not isinstance(record, dict):
                continue
            copc_path = record.get("copc_path", "")
            if copc_path and os.path.exists(copc_path):
                existing_records.append(record)
            else:
                stale_records.append(record)
        if not existing_records:
            return {
                "action": "continue",
                "orphaned_copc_records": [],
                "save_metadata": bool(stale_records),
            }
        sample = self._vpc_audit_sample_text(
            "残っているCOPC",
            [r.get("copc_path", "") for r in existing_records],
        )
        box = QMessageBox(self.vrt_tab)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr_text("VPC元データの確認"))
        box.setText(
            tr_text(
                f"{self._vpc_audit_dialog_header(vpc_path, vpc_name)}"
                f"以前VPCから外した点群のCOPCが残っています。\n\n{sample}\n\n処理を選択してください。"
            )
        )
        delete_button = box.addButton(tr_text("COPCを削除"), QMessageBox.ButtonRole.DestructiveRole)
        keep_button = box.addButton(tr_text("残す"), QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton(tr_text("読み込み中止"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            QgsMessageLog.logMessage(
                f"VPC_ORPHANED_COPC_ON_LOAD_CANCELLED count={len(existing_records)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return {"action": "cancel"}
        if clicked == delete_button:
            deleted, failed, skipped = self._delete_vpc_copc_paths(
                [r.get("copc_path", "") for r in existing_records],
                vpc_path,
                label="VPC_ORPHANED_COPC_ON_LOAD_DELETE",
            )
            if failed:
                QMessageBox.warning(
                    self.vrt_tab,
                    tr_text("警告"),
                    tr_text(f"残ったCOPCの一部を削除できませんでした。\n\n削除: {deleted} 件\n失敗: {failed} 件\nスキップ: {skipped} 件"),
                )
                kept_records = [
                    r for r in existing_records
                    if r.get("copc_path", "") and os.path.exists(r.get("copc_path", ""))
                ]
            else:
                kept_records = []
            return {
                "action": "continue",
                "orphaned_copc_records": kept_records,
                "save_metadata": True,
            }
        QgsMessageLog.logMessage(
            f"VPC_ORPHANED_COPC_ON_LOAD_KEEP count={len(existing_records)}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return {
            "action": "continue",
            "orphaned_copc_records": list(existing_records),
            "save_metadata": bool(stale_records),
        }

    def _audit_vpc_sources_on_load(self, source_list, source_records, vpc_path, orphaned_copc_records=None, vpc_name=""):
        records_by_source = self._source_records_by_source_path(source_records)
        source_paths = [
            p for p in (source_list or [])
            if p and not self._is_managed_copc_path(p, vpc_path)
        ]
        missing_source_list = [p for p in source_paths if not os.path.exists(p)]
        changed_sources = []

        if records_by_source:
            for source_path in source_paths:
                if not os.path.exists(source_path):
                    continue
                source_key = self._normalize_path(source_path)
                previous = records_by_source.get(source_key)
                if not previous:
                    continue
                current = self.main_ui._point_cloud_source_record(source_path)
                reasons = []
                for field in ("size", "mtime_ns", "point_count"):
                    if previous.get(field) is not None and current.get(field) is not None and previous.get(field) != current.get(field):
                        reasons.append(field)
                previous_scale = previous.get("scale_offset")
                current_scale = current.get("scale_offset")
                if previous_scale and current_scale and not self.main_ui._scale_offset_values_match(previous_scale, current_scale):
                    reasons.append("scale_offset")
                if reasons:
                    changed_sources.append((source_path, reasons))

        if not missing_source_list and not changed_sources:
            return {
                "action": "continue",
                "source_list": list(source_list or []),
                "source_records": list(source_records or []),
                "save_metadata": False,
            }

        missing_copc_by_source = {}
        for source_path in missing_source_list:
            record = records_by_source.get(self._normalize_path(source_path), {})
            copc_path = record.get("copc_path", "") if isinstance(record, dict) else ""
            if not copc_path:
                try:
                    copc_path = self.main_ui._copc_cache_path_for_source(source_path, vpc_path)
                except Exception:
                    copc_path = ""
            if copc_path and os.path.exists(copc_path):
                missing_copc_by_source[self._normalize_path(source_path)] = os.path.normpath(os.path.abspath(copc_path))

        if missing_source_list:
            sample = self._vpc_audit_sample_text("見つからないファイル", missing_source_list)
            box = QMessageBox(self.vrt_tab)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr_text("VPC元データの確認"))
            box.setText(
                tr_text(
                    f"{self._vpc_audit_dialog_header(vpc_path, vpc_name)}"
                    f"元LAS/LAZが見つからないファイルがあります。\n\n{sample}\n\n処理を選択してください。"
                )
            )
            use_copc_button = None
            if len(missing_copc_by_source) == len(missing_source_list):
                if len(missing_source_list) == len(source_paths):
                    use_copc_button = box.addButton(tr_text("COPCだけのVPCとして保存"), QMessageBox.ButtonRole.AcceptRole)
                else:
                    use_copc_button = box.addButton(tr_text("COPCで表示を続ける"), QMessageBox.ButtonRole.AcceptRole)
            if len(missing_source_list) == len(source_paths):
                exclude_button = box.addButton(tr_text("空VPCとして保存"), QMessageBox.ButtonRole.DestructiveRole)
                exclude_delete_copc_button = box.addButton(tr_text("空VPCとして保存＋COPCも削除"), QMessageBox.ButtonRole.DestructiveRole) if missing_copc_by_source else None
            else:
                exclude_button = box.addButton(tr_text("VPCから外して保存"), QMessageBox.ButtonRole.DestructiveRole)
                exclude_delete_copc_button = box.addButton(tr_text("VPCから外して保存＋COPCも削除"), QMessageBox.ButtonRole.DestructiveRole) if missing_copc_by_source else None
            cancel_button = box.addButton(tr_text("読み込み中止"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            QgsMessageLog.logMessage(
                f"VPC_SOURCE_MISSING_ON_LOAD count={len(missing_source_list)} copc_available={len(missing_copc_by_source)} sample={sample}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            if clicked == cancel_button:
                QgsMessageLog.logMessage(
                    f"VPC_SOURCE_MISSING_ON_LOAD_CANCELLED count={len(missing_source_list)}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                return {"action": "cancel"}
            if use_copc_button is not None and clicked == use_copc_button:
                if len(missing_source_list) == len(source_paths):
                    resolved_source_list = [
                        missing_copc_by_source.get(self._normalize_path(p), p)
                        for p in (source_list or [])
                        if os.path.exists(p) or self._normalize_path(p) in missing_copc_by_source
                    ]
                    return {
                        "action": "continue",
                        "source_list": resolved_source_list,
                        "source_records": self.main_ui._vpc_source_records(resolved_source_list),
                        "save_metadata": True,
                    }
                return {
                    "action": "continue",
                    "source_list": list(source_list or []),
                    "source_records": list(source_records or []),
                    "save_metadata": False,
                }
            if clicked == exclude_button or (exclude_delete_copc_button is not None and clicked == exclude_delete_copc_button):
                missing_keys = {self._normalize_path(p) for p in missing_source_list}
                delete_selected = exclude_delete_copc_button is not None and clicked == exclude_delete_copc_button
                delete_copc_paths = list(missing_copc_by_source.values())
                delete_copc_keys = {self._normalize_path(p) for p in delete_copc_paths}
                resolved_source_list = [p for p in (source_list or []) if p and os.path.exists(p)]
                resolved_records = [
                    r for r in (source_records or [])
                    if isinstance(r, dict) and self._normalize_path(r.get("source_path", "")) not in missing_keys
                ]
                base_orphans = [
                    r for r in (orphaned_copc_records or [])
                    if isinstance(r, dict) and self._normalize_path(r.get("copc_path", "")) not in delete_copc_keys
                ] if delete_selected else orphaned_copc_records
                missing_orphans = []
                if not delete_selected:
                    for source_path in missing_source_list:
                        record = records_by_source.get(self._normalize_path(source_path), {})
                        if not isinstance(record, dict):
                            record = {}
                        copc_path = missing_copc_by_source.get(self._normalize_path(source_path), record.get("copc_path", ""))
                        if not copc_path:
                            continue
                        orphan = dict(record)
                        orphan["source_path"] = source_path
                        orphan["copc_path"] = copc_path
                        orphan["orphaned_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        missing_orphans.append(orphan)
                return {
                    "action": "exclude",
                    "source_list": resolved_source_list,
                    "source_records": resolved_records,
                    "orphaned_copc_records": self._merge_orphaned_copc_records(base_orphans, missing_orphans),
                    "save_metadata": True,
                    "delete_copc": delete_selected,
                    "delete_copc_paths": delete_copc_paths,
                }
            return {"action": "cancel"}

        if changed_sources:
            sample_lines = [f"{path} ({','.join(reasons)})" for path, reasons in changed_sources]
            sample = self._vpc_audit_sample_text("変化したファイル", sample_lines)
            box = QMessageBox(self.vrt_tab)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr_text("VPC元データの確認"))
            box.setText(
                tr_text(
                    f"{self._vpc_audit_dialog_header(vpc_path, vpc_name)}"
                    f"元LAS/LAZが前回VPC作成時から変化しています。\n"
                    f"表示中のCOPCは古い可能性があります。VPC更新で該当COPCを作り直してください。\n\n{sample}"
                )
            )
            continue_button = box.addButton(tr_text("このまま表示"), QMessageBox.ButtonRole.AcceptRole)
            cancel_button = box.addButton(tr_text("読み込み中止"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            QgsMessageLog.logMessage(
                f"VPC_SOURCE_CHANGED_ON_LOAD count={len(changed_sources)} sample={sample}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            if box.clickedButton() != continue_button:
                return {"action": "cancel"}

        return {
            "action": "continue",
            "source_list": list(source_list or []),
            "source_records": list(source_records or []),
            "save_metadata": False,
        }

    def _source_remove_keys(self, source_path, vpc_path):
        keys = {self._normalize_path(source_path)}
        try:
            for copc_path in self.main_ui._copc_cache_paths_for_source(source_path, vpc_path):
                keys.add(self._normalize_path(copc_path))
        except Exception:
            _om_record_ignored_exception(__name__, 1117)
        return keys

    def _is_managed_copc_path(self, path, vpc_path):
        if not path or not vpc_path:
            return False
        try:
            copc_root = os.path.normcase(os.path.abspath(self.main_ui._copc_cache_root_for_vpc(vpc_path)))
            path_abs = os.path.normcase(os.path.abspath(str(path)))
            return os.path.commonpath([copc_root, path_abs]) == copc_root
        except Exception:
            return False

    def _source_stem_from_managed_copc(self, copc_path):
        name = os.path.basename(str(copc_path or ""))
        lower = name.lower()
        if lower.endswith(".copc.laz"):
            stem = name[:-len(".copc.laz")]
        else:
            stem = os.path.splitext(name)[0]
        parts = stem.split("_")
        if len(parts) >= 2 and len(parts[1]) == 12:
            return parts[0]
        return stem

    def _candidate_original_source_dirs(self, source_list, vpc_path):
        dirs = []
        seen = set()

        def add_dir(path):
            if not path:
                return
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen:
                return
            seen.add(norm)
            dirs.append(os.path.abspath(path))

        for source_path in source_list:
            if not source_path or self._is_managed_copc_path(source_path, vpc_path):
                continue
            add_dir(os.path.dirname(os.path.abspath(source_path)))
        if vpc_path:
            vpc_dir = os.path.dirname(os.path.abspath(vpc_path))
            vpc_base = os.path.basename(vpc_dir)
            if vpc_base.lower().endswith("vpc") and len(vpc_base) > 3:
                add_dir(os.path.join(os.path.dirname(vpc_dir), vpc_base[:-3]))
        return dirs

    def restore_original_sources_from_managed_copc(self, source_list, vpc_path):
        source_list = list(source_list or [])
        if not vpc_path:
            return source_list
        candidate_dirs = self._candidate_original_source_dirs(source_list, vpc_path)
        if not candidate_dirs:
            return source_list
        restored = []
        changed = False
        for source_path in source_list:
            if not self._is_managed_copc_path(source_path, vpc_path):
                restored.append(source_path)
                continue
            source_stem = self._source_stem_from_managed_copc(source_path)
            replacement = ""
            for folder in candidate_dirs:
                for ext in (".las", ".laz"):
                    candidate = os.path.join(folder, source_stem + ext)
                    if os.path.exists(candidate):
                        replacement = os.path.normpath(candidate)
                        break
                if replacement:
                    break
            if replacement:
                restored.append(replacement)
                changed = True
                QgsMessageLog.logMessage(
                    f"VPC_SOURCE_RESTORED_FROM_MANAGED_COPC copc={source_path} source={replacement}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            else:
                restored.append(source_path)
        if not changed:
            return source_list
        unique = []
        seen = set()
        for path in restored:
            key = self._normalize_path(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def selected_overlay_paths(self):
        name = self.main_ui.current_vpc_name
        overlay_layer = self.main_ui._get_vpc_overlay_layer(name) if name else None
        if not overlay_layer:
            return set()
        paths = set()
        for feat in overlay_layer.selectedFeatures():
            try:
                path = feat.attribute("path")
            except Exception:
                path = ""
            if path:
                paths.add(os.path.normpath(str(path)))
        return paths

    def clear_overlay_selection(self):
        name = self.main_ui.current_vpc_name
        overlay_layer = self.main_ui._get_vpc_overlay_layer(name) if name else None
        if overlay_layer:
            overlay_layer.removeSelection()

    def activate_overlay_select_tool(self):
        self.set_scale_target_vpc()
        name = self.main_ui.current_vpc_name
        if not name:
            QMessageBox.warning(self.source_list_window or self.vrt_tab, tr_text("警告"), tr_text("VPCが選択されていません。"))
            return
        overlay_layer = self.main_ui._get_vpc_overlay_layer(name)
        if not overlay_layer:
            QMessageBox.information(
                self.source_list_window or self.vrt_tab,
                tr_text("情報"),
                tr_text("このVPCには範囲オーバーレイがありません。VPCを作成またはレイヤ整理してください。"),
            )
            return
        canvas = self.main_ui.iface.mapCanvas()
        self.previous_map_tool = canvas.mapTool()
        self.main_ui.iface.setActiveLayer(overlay_layer)
        try:
            self.main_ui.iface.actionSelect().trigger()
            self.main_ui._set_status(tr_text("🖱 マップ上で削除したい点群範囲をクリックして選択してください。選択後に「選択削除」を押します。"))
        except Exception as e:
            QgsMessageLog.logMessage(f"VPC_SELECT_TOOL_FAILED error={e}", "OrthoManager", Qgis.MessageLevel.Warning)

    def restore_previous_map_tool(self):
        if not self.previous_map_tool:
            return
        try:
            self.main_ui.iface.mapCanvas().setMapTool(self.previous_map_tool)
        except Exception:
            _om_record_ignored_exception(__name__, 1261)
        self.previous_map_tool = None

    def _add_paths(self, paths):
        self.set_scale_target_vpc()
        if not self.main_ui.current_vpc_name:
            return 0, 0
        entry = self.main_ui.vpc_registry.setdefault(
            self.main_ui.current_vpc_name,
            {"path": "", "source_list": [], "group_crs_authid": "", "initial_crs_pending": True},
        )
        entry.setdefault("group_crs_authid", "")
        entry.setdefault("initial_crs_pending", True)
        source_list = entry.setdefault("source_list", [])
        restored_list = self.restore_original_sources_from_managed_copc(source_list, entry.get("path", ""))
        if restored_list != source_list:
            entry["source_list"] = restored_list
            source_list = entry["source_list"]
        existing = {self._normalize_path(p) for p in source_list}
        existing_stems = set()
        for source_path in source_list:
            lower_name = os.path.basename(str(source_path or "")).lower()
            if lower_name.endswith(".copc.laz"):
                stem_text = os.path.basename(str(source_path))[:-len(".copc.laz")]
            else:
                stem_text = os.path.splitext(os.path.basename(str(source_path)))[0]
            existing_stems.add(self.main_ui._safe_ascii_file_stem(stem_text).lower())
        added_paths = []
        added = 0
        skipped = 0
        name_skipped = 0
        for path in paths:
            if not is_supported_point_cloud_path(path):
                continue
            norm_path = os.path.normpath(os.path.abspath(path))
            key = self._normalize_path(norm_path)
            if key in existing:
                skipped += 1
                continue
            lower_name = os.path.basename(norm_path).lower()
            if lower_name.endswith(".copc.laz"):
                stem_text = os.path.basename(norm_path)[:-len(".copc.laz")]
            else:
                stem_text = os.path.splitext(os.path.basename(norm_path))[0]
            stem_key = self.main_ui._safe_ascii_file_stem(stem_text).lower()
            if stem_key in existing_stems:
                name_skipped += 1
                continue
            existing.add(key)
            existing_stems.add(stem_key)
            source_list.append(norm_path)
            added_paths.append(norm_path)
            added += 1
        self.reload_source_listwidget()
        if added:
            vpc_path = entry.get("path", "")
            if vpc_path:
                self.main_ui._set_vpc_progress(0, "VPC更新準備中（一時的に表示を切り替えます）")
                QApplication.processEvents()
                self.main_ui._remove_vpc_group(self.main_ui.current_vpc_name)
                self._delete_managed_copc_for_sources(added_paths, vpc_path)
            self.main_ui._set_status(tr_text(f"✅ 点群ファイルを追加: {added} 件"))
            QTimer.singleShot(0, self.build_vpc)
        if skipped:
            QMessageBox.information(
                self.source_list_window or self.vrt_tab,
                tr_text("情報"),
                tr_text(f"同じ点群ファイルは追加済みのため、{skipped} 件は追加しませんでした。"),
            )
        if name_skipped:
            QMessageBox.warning(
                self.source_list_window or self.vrt_tab,
                tr_text("警告"),
                tr_text(f"同じ名前の点群ファイルが既にあるため、{name_skipped} 件は追加しませんでした。同名ファイルは別VPCで管理してください。"),
            )
        return added, skipped + name_skipped

    def add_from_folder(self):
        self.set_scale_target_vpc()
        if not self.main_ui.current_vpc_name:
            return
        folder = QFileDialog.getExistingDirectory(self.source_list_window or self.vrt_tab, tr_text("フォルダを選択"), self.source_add_default_dir())
        if not folder:
            return
        self._remember_vpc_dialog_path(folder)
        found = []
        include_subfolders = bool(self.include_subfolders)
        if include_subfolders:
            for root, dirs, files in os.walk(folder):
                for filename in files:
                    path = os.path.join(root, filename)
                    if is_supported_point_cloud_path(path):
                        found.append(path)
        else:
            try:
                for filename in os.listdir(folder):
                    path = os.path.join(folder, filename)
                    if os.path.isfile(path) and is_supported_point_cloud_path(path):
                        found.append(path)
            except Exception as e:
                QMessageBox.warning(self.source_list_window or self.vrt_tab, tr_text("警告"), tr_text(f"フォルダの読み込みに失敗しました。\n\n{e}"))
                return
        QgsMessageLog.logMessage(
            f"VPC_ADD_FOLDER folder={folder} include_subfolders={include_subfolders} found={len(found)}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        if not found:
            QMessageBox.information(self.source_list_window or self.vrt_tab, tr_text("情報"), tr_text("対応する点群ファイルが見つかりませんでした。"))
            return
        self._add_paths(found)

    def add_files(self):
        self.set_scale_target_vpc()
        if not self.main_ui.current_vpc_name:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self.source_list_window or self.vrt_tab,
            tr_text("点群ファイルを選択"),
            self.source_add_default_dir(),
            "Point Cloud (*.las *.laz *.copc *.copc.laz);;All Files (*)",
        )
        if not paths:
            return
        self._remember_vpc_dialog_path(paths[0])
        self._add_paths(paths)

    def _managed_copc_paths_for_sources(self, source_paths, vpc_path):
        if not vpc_path:
            return {}
        try:
            cache_root = os.path.abspath(self.main_ui._copc_cache_root_for_vpc(vpc_path))
            cache_root_key = os.path.normcase(cache_root)
        except Exception:
            return {}
        managed = {}
        for source_path in source_paths or []:
            source_name = str(source_path or "").lower()
            if not (source_name.endswith(".las") or source_name.endswith(".laz")):
                continue
            try:
                source_abs = os.path.abspath(str(source_path))
                source_key = os.path.normcase(source_abs)
                if source_name.endswith(".copc.laz") and os.path.commonpath([cache_root_key, source_key]) == cache_root_key:
                    copc_path = source_abs
                elif source_name.endswith(".copc.laz"):
                    continue
                else:
                    copc_paths = self.main_ui._copc_cache_paths_for_source(source_path, vpc_path)
                    for copc_path in copc_paths:
                        copc_abs = os.path.abspath(copc_path)
                        if os.path.normcase(os.path.commonpath([cache_root_key, os.path.normcase(copc_abs)])) != cache_root_key:
                            continue
                        managed[self._normalize_path(copc_abs)] = copc_abs
                    continue
                if os.path.normcase(os.path.commonpath([cache_root_key, os.path.normcase(copc_path)])) != cache_root_key:
                    continue
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_COPC_CACHE_PATH_FAILED src={source_path} vpc={vpc_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                continue
            managed[self._normalize_path(copc_path)] = copc_path
        return managed

    def _delete_managed_copc_for_sources(self, source_paths, vpc_path):
        managed = self._managed_copc_paths_for_sources(source_paths, vpc_path)
        removed = 0
        for copc_path in managed.values():
            if not os.path.exists(copc_path):
                continue
            try:
                os.remove(copc_path)
                removed += 1
                QgsMessageLog.logMessage(
                    f"VPC_COPC_CACHE_REMOVED copc={copc_path}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_COPC_CACHE_REMOVE_FAILED copc={copc_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
        return removed, set(managed.keys())

    def remove_paths(self, paths):
        self.set_scale_target_vpc()
        if not self.main_ui.current_vpc_name:
            return
        entry = self.main_ui.vpc_registry.get(self.main_ui.current_vpc_name, {})
        vpc_path = entry.get("path", "")
        source_list = self.restore_original_sources_from_managed_copc(entry.get("source_list", []), vpc_path)
        entry["source_list"] = source_list
        remove_keys = {self._normalize_path(p) for p in paths}
        before_count = len(source_list)
        removed_sources = [p for p in source_list if self._source_remove_keys(p, vpc_path) & remove_keys]
        entry["source_list"] = [p for p in source_list if not (self._source_remove_keys(p, vpc_path) & remove_keys)]
        removed_count = before_count - len(entry["source_list"])
        self.reload_source_listwidget()
        if removed_count <= 0:
            QMessageBox.information(self.source_list_window or self.vrt_tab, tr_text("情報"), tr_text("VPC一覧に一致する点群がありませんでした。"))
            return
        self.main_ui._set_vpc_progress(0, "VPC更新準備中（一時的に表示を切り替えます）")
        QApplication.processEvents()
        self.main_ui._remove_vpc_group(self.main_ui.current_vpc_name)
        removed_copc_count, managed_copc_keys = self._delete_managed_copc_for_sources(removed_sources, vpc_path)
        if managed_copc_keys:
            entry["copc_source_list"] = [
                p for p in entry.get("copc_source_list", [])
                if self._normalize_path(p) not in managed_copc_keys
            ]
            entry["processing_source_list"] = [
                p for p in entry.get("processing_source_list", [])
                if self._normalize_path(p) not in managed_copc_keys
            ]
        if removed_copc_count:
            QgsMessageLog.logMessage(
                f"VPC_COPC_CACHE_REMOVE_DONE count={removed_copc_count}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        self.main_ui._set_status(tr_text(f"🗑 点群ファイルを一覧から削除: {removed_count} 件"))
        if entry["source_list"]:
            self.main_ui.write_vpc_embedded_metadata(vpc_path, entry)
            QTimer.singleShot(0, self.build_vpc)
        else:
            path = vpc_path
            crs_authid = entry.get("group_crs_authid", "")
            ok, err_msg = self.main_ui.write_empty_vpc_file(path, crs_authid)
            if not ok:
                QgsMessageLog.logMessage(f"VPC_EMPTY_UPDATE_FAILED path={path} error={err_msg}", "OrthoManager", Qgis.MessageLevel.Warning)
            self.main_ui.write_vpc_embedded_metadata(path, entry)

    def clear_sources(self):
        self.set_scale_target_vpc()
        if not self.main_ui.current_vpc_name:
            return
        entry = self.main_ui.vpc_registry.get(self.main_ui.current_vpc_name, {})
        removed_sources = list(entry.get("source_list", []))
        path = entry.get("path", "")
        self.main_ui._remove_vpc_group(self.main_ui.current_vpc_name)
        self._delete_managed_copc_for_sources(removed_sources, path)
        entry["source_list"] = []
        entry["processing_source_list"] = []
        entry["copc_source_list"] = []
        crs_authid = entry.get("group_crs_authid", "")
        ok, err_msg = self.main_ui.write_empty_vpc_file(path, crs_authid)
        if not ok:
            QgsMessageLog.logMessage(f"VPC_EMPTY_UPDATE_FAILED path={path} error={err_msg}", "OrthoManager", Qgis.MessageLevel.Warning)
        self.main_ui.write_vpc_embedded_metadata(path, entry)
        self.reload_source_listwidget()
        self.main_ui._reset_map_display_caches("vpc_clear_sources", schedule_prefetch=True)
        self.main_ui._set_status(tr_text("🗑 点群一覧を空にしました"))

    def _format_elapsed_time(self, elapsed_seconds):
        total_seconds = max(0, int(round(elapsed_seconds)))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours:
            return f"{hours}時間{minutes}分{seconds}秒"
        if minutes:
            return f"{minutes}分{seconds}秒"
        return f"{seconds}秒"

    def _log_build_display_elapsed(self, name, path, count, started_at, result):
        elapsed = time.perf_counter() - started_at
        QgsMessageLog.logMessage(
            (
                "VPC_BUILD_DISPLAY_TIME "
                f"name={name} count={count} result={result} "
                f"seconds={elapsed:.1f} duration={self._format_elapsed_time(elapsed)} "
                f"path={path}"
            ),
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

    def _log_cache_refresh_step(self, step, started_at, ok=True, detail=""):
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        message = f"VPC_CACHE_REFRESH_STEP step={step} ok={int(bool(ok))} elapsed_ms={elapsed_ms}"
        if detail:
            message += f" detail={detail}"
        QgsMessageLog.logMessage(message, "OrthoManager", Qgis.MessageLevel.Info)

    def _run_canvas_cache_step(self, step, started_at, method_name):
        ok_count = 0
        fail_count = 0
        for canvas in self.main_ui._map_canvases():
            method = getattr(canvas, method_name, None)
            if not method:
                continue
            try:
                method()
                ok_count += 1
            except Exception:
                fail_count += 1
        self._log_cache_refresh_step(step, started_at, fail_count == 0, f"method={method_name} ok={ok_count} failed={fail_count}")

    def _refresh_shadow_vpc_prefix(self, vpc_path):
        stem = os.path.splitext(os.path.basename(str(vpc_path or "")))[0]
        return f"{stem}__om_refresh_"

    def _cleanup_refresh_shadow_vpcs(self, vpc_path, keep_path="", started_at=None):
        folder = os.path.dirname(os.path.abspath(str(vpc_path or "")))
        prefix = self._refresh_shadow_vpc_prefix(vpc_path)
        keep_key = self._normalize_path(keep_path) if keep_path else ""
        removed = 0
        locked = 0
        if not folder or not os.path.isdir(folder):
            return
        for name in os.listdir(folder):
            lower_name = name.lower()
            if not (name.startswith(prefix) and lower_name.endswith(".vpc")):
                continue
            path = os.path.join(folder, name)
            if keep_key and self._normalize_path(path) == keep_key:
                continue
            try:
                os.remove(path)
                removed += 1
            except Exception:
                locked += 1
        if started_at is not None:
            self._log_cache_refresh_step(
                "cleanup_shadow_vpc",
                started_at,
                locked == 0,
                f"removed={removed} locked={locked}",
            )

    def _cleanup_refresh_copc_hardlinks(self, vpc_path, keep_paths=None, started_at=None):
        copc_folder = self.main_ui._copc_cache_root_for_vpc(vpc_path)
        keep_keys = {self._normalize_path(p) for p in (keep_paths or []) if p}
        removed = 0
        locked = 0
        if not os.path.isdir(copc_folder):
            return
        for name in os.listdir(copc_folder):
            lower_name = name.lower()
            if "__om_refresh_" not in name or not lower_name.endswith(".copc.laz"):
                continue
            path = os.path.join(copc_folder, name)
            if self._normalize_path(path) in keep_keys:
                continue
            try:
                os.remove(path)
                removed += 1
            except Exception:
                locked += 1
        if started_at is not None:
            self._log_cache_refresh_step(
                "cleanup_shadow_copc",
                started_at,
                locked == 0,
                f"removed={removed} locked={locked}",
            )

    def build_vpc(self):
        self.set_scale_target_vpc()
        name = self.main_ui.current_vpc_name
        if not name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCが選択されていません。"))
            return
        entry = self.main_ui.vpc_registry.get(name, {})
        restored_source_list = self.restore_original_sources_from_managed_copc(entry.get("source_list", []), entry.get("path", ""))
        if restored_source_list != entry.get("source_list", []):
            entry["source_list"] = restored_source_list
            self.main_ui.vpc_registry[name] = entry
            self.reload_source_listwidget()
        original_source_list = [p for p in entry.get("source_list", []) if p]
        missing_source_list = [p for p in original_source_list if not os.path.exists(p)]
        if missing_source_list:
            records_by_source = {}
            for record in entry.get("source_records", []) or []:
                if not isinstance(record, dict):
                    continue
                source_path = record.get("source_path", "")
                if not source_path:
                    continue
                records_by_source[self._normalize_path(source_path)] = record
            missing_copc_by_source = {}
            for source_path in missing_source_list:
                record = records_by_source.get(self._normalize_path(source_path), {})
                copc_path = record.get("copc_path", "") if isinstance(record, dict) else ""
                if not copc_path:
                    copc_path = self.main_ui._copc_cache_path_for_source(source_path, entry.get("path", ""))
                if copc_path and os.path.exists(copc_path):
                    missing_copc_by_source[self._normalize_path(source_path)] = os.path.normpath(os.path.abspath(copc_path))
            sample = self._vpc_audit_sample_text("見つからないファイル", missing_source_list)
            box = QMessageBox(self.vrt_tab)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr_text("元LASが見つかりません"))
            box.setText(
                tr_text(
                    f"{self._vpc_audit_dialog_header(entry.get('path', ''), name)}"
                    f"元LAS/LAZが見つからないファイルがあります。\n\n{sample}"
                )
            )
            use_copc_button = None
            if len(missing_copc_by_source) == len(missing_source_list):
                if len(missing_source_list) == len(original_source_list):
                    use_copc_button = box.addButton(tr_text("COPCだけのVPCとして保存"), QMessageBox.ButtonRole.AcceptRole)
                else:
                    use_copc_button = box.addButton(tr_text("COPCを残して表示"), QMessageBox.ButtonRole.AcceptRole)
            exclude_button = box.addButton(tr_text("VPCから外して更新"), QMessageBox.ButtonRole.DestructiveRole)
            cancel_button = box.addButton(tr_text("中止"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel_button:
                QgsMessageLog.logMessage(
                    f"VPC_SOURCE_MISSING_CANCELLED count={len(missing_source_list)}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                return
            if use_copc_button is not None and clicked == use_copc_button:
                source_list = [
                    missing_copc_by_source.get(self._normalize_path(p), p)
                    for p in original_source_list
                    if os.path.exists(p) or self._normalize_path(p) in missing_copc_by_source
                ]
                if len(missing_source_list) == len(original_source_list):
                    entry["source_list"] = list(source_list)
            elif clicked == exclude_button:
                source_list = [p for p in original_source_list if p and os.path.exists(p)]
                entry["source_list"] = list(source_list)
                entry["source_records"] = [
                    r for r in entry.get("source_records", []) or []
                    if isinstance(r, dict) and self._normalize_path(r.get("source_path", "")) not in {self._normalize_path(p) for p in missing_source_list}
                ]
            else:
                return
            self.main_ui.vpc_registry[name] = entry
            self.reload_source_listwidget()
            QgsMessageLog.logMessage(
                f"VPC_SOURCE_MISSING count={len(missing_source_list)} copc_available={len(missing_copc_by_source)} action={'copc' if use_copc_button is not None and clicked == use_copc_button else 'exclude'} sample={sample}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        else:
            source_list = [p for p in original_source_list if p and os.path.exists(p)]
        if not source_list:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPCに入れる点群ファイルがありません。"))
            return
        path = entry.get("path", "")
        if not path:
            path, _ = QFileDialog.getSaveFileName(self.vrt_tab, tr_text("VPCの保存先"), self.new_vpc_default_dir(), "Virtual Point Cloud (*.vpc)")
            if not path:
                return
            self._remember_vpc_dialog_path(path)
            if not path.lower().endswith(".vpc"):
                path += ".vpc"
            entry["path"] = path
        ok_name, message = self.main_ui.validate_vpc_base_name(os.path.splitext(os.path.basename(path))[0])
        if not ok_name:
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), message)
            return
        folder = os.path.dirname(os.path.abspath(path))
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)

        selected_crs = self.main_ui._handle_vpc_crs_before_overlay_build(name)
        if not (selected_crs and selected_crs.isValid()):
            self.main_ui._set_status(tr_text("⚠️ 点群CRSが未設定のため、VPC作成を中止しました"))
            return

        started_at = time.perf_counter()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.main_ui._set_vpc_progress(0, f"VPC作成準備中（{len(source_list)} ファイル）")
        QApplication.processEvents()
        try:
            result = self.main_ui.run_virtual_point_cloud_algorithm(source_list, path, progress_callback=self.main_ui._set_vpc_progress)
        except Exception as e:
            QMessageBox.critical(self.vrt_tab, tr_text("エラー"), tr_text(f"VPC作成に失敗しました。\n\n{e}"))
            QgsMessageLog.logMessage(f"VPC_BUILD_FAILED path={path} error={e}", "OrthoManager", Qgis.MessageLevel.Critical)
            self._log_build_display_elapsed(name, path, len(source_list), started_at, "failed")
            self.main_ui._set_status(tr_text("❌ VPC作成に失敗しました"), log=False, style="error")
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not os.path.exists(path):
            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text("VPC作成処理は終了しましたが、VPCファイルを確認できませんでした。"))
            return

        entry["path"] = path
        entry["source_list"] = list(source_list)
        entry["subst_mappings"] = []
        entry["runtime_vpc_path"] = ""
        if isinstance(result, dict):
            if result.get("_ORTHO_VPC_PROCESSING_SOURCES") is not None:
                entry["processing_source_list"] = result.get("_ORTHO_VPC_PROCESSING_SOURCES") or []
            if result.get("_ORTHO_VPC_COPC_SOURCES") is not None:
                entry["copc_source_list"] = result.get("_ORTHO_VPC_COPC_SOURCES") or []
            if result.get("_ORTHO_VPC_SOURCE_RECORDS") is not None:
                entry["source_records"] = result.get("_ORTHO_VPC_SOURCE_RECORDS") or []
        self.main_ui.vpc_registry[name] = entry
        self.main_ui.write_vpc_embedded_metadata(path, entry)
        self.main_ui._remove_vpc_group(name)
        layer = self.main_ui._load_vpc_layer(path, name, progress_percent=94)
        if layer:
            self.main_ui._reload_vpc_point_cloud_provider(layer, reason="vpc_rebuild")
        self.reload_source_listwidget()
        self.update_path_display()
        if layer:
            self.main_ui._set_vpc_progress(100, "点群表示完了")
            self.main_ui._reset_map_display_caches("vpc_build_done", schedule_prefetch=True)
            self._log_build_display_elapsed(name, path, len(source_list), started_at, "point_cloud")
            self.main_ui._set_status(tr_text(f"✅ VPC作成完了・点群表示: {name}（{len(source_list)} ファイル）"))
        else:
            overlay_layer = self.main_ui._load_vpc_overlay_only(path, name)
            if overlay_layer:
                self.main_ui._reset_map_display_caches("vpc_build_overlay_only", schedule_prefetch=True)
                self._log_build_display_elapsed(name, path, len(source_list), started_at, "overlay_only")
                self.main_ui._set_status(tr_text(f"⚠️ VPC作成完了。点群本体は読めませんでしたが、範囲を表示しました: {name}"))
            else:
                self.main_ui._reset_map_display_caches("vpc_build_no_display", schedule_prefetch=True)
                self._log_build_display_elapsed(name, path, len(source_list), started_at, "no_display")
                self.main_ui._set_status(tr_text(f"✅ VPC作成完了: {name}（{len(source_list)} ファイル）※表示なし"))
