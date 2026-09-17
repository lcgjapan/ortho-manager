import time

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QComboBox, QPushButton,
    QSizePolicy, QCheckBox
)
from qgis.core import QgsMessageLog, Qgis, QgsSettings

from .i18n import LANGUAGES, current_language, set_current_language, tr
from .layer_visibility_hotkey import SPACE_LAYER_VISIBILITY_ENABLED_KEY, setting_bool as space_setting_bool
from .xyz_status_tool import XYZ_STATUS_ENABLED_KEY, setting_bool


class SettingsTabWidget(QWidget):
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self.dock = dock
        self._build_ui()
        self.refresh_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight:bold; font-size:13px;")
        layout.addWidget(self.title_label)

        self.language_group = QGroupBox()
        language_layout = QVBoxLayout(self.language_group)
        language_layout.setContentsMargins(8, 8, 8, 8)
        language_layout.setSpacing(6)

        language_row = QHBoxLayout()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_combo)
        language_row.addStretch(1)
        language_layout.addLayout(language_row)

        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        self.language_note.setStyleSheet("color:#555; font-size:11px;")
        language_layout.addWidget(self.language_note)
        layout.addWidget(self.language_group)

        self.log_group = QGroupBox()
        log_layout = QHBoxLayout(self.log_group)
        log_layout.setContentsMargins(8, 8, 8, 8)
        self.btn_log_start = QPushButton()
        self.btn_log_start.setFixedWidth(90)
        self.btn_log_start.clicked.connect(self._mark_log_start)
        self.btn_log_start.setStyleSheet(
            "QPushButton{background:#607d8b;color:white;border:none;border-radius:4px;padding:5px;font-size:11px;}"
            "QPushButton:hover{background:#607d8bCC;}"
        )
        log_layout.addWidget(self.btn_log_start)
        log_layout.addStretch(1)
        layout.addWidget(self.log_group)

        self.xyz_group = QGroupBox()
        xyz_layout = QVBoxLayout(self.xyz_group)
        xyz_layout.setContentsMargins(8, 8, 8, 8)
        xyz_layout.setSpacing(6)
        self.xyz_checkbox = QCheckBox()
        self.xyz_checkbox.stateChanged.connect(self._on_xyz_changed)
        xyz_layout.addWidget(self.xyz_checkbox)
        self.xyz_note = QLabel()
        self.xyz_note.setWordWrap(True)
        self.xyz_note.setStyleSheet("color:#555; font-size:11px;")
        xyz_layout.addWidget(self.xyz_note)
        layout.addWidget(self.xyz_group)

        self.hotkey_group = QGroupBox()
        hotkey_layout = QVBoxLayout(self.hotkey_group)
        hotkey_layout.setContentsMargins(8, 8, 8, 8)
        hotkey_layout.setSpacing(6)
        self.space_layer_checkbox = QCheckBox()
        self.space_layer_checkbox.stateChanged.connect(self._on_space_layer_changed)
        hotkey_layout.addWidget(self.space_layer_checkbox)
        self.space_layer_note = QLabel()
        self.space_layer_note.setWordWrap(True)
        self.space_layer_note.setStyleSheet("color:#555; font-size:11px;")
        hotkey_layout.addWidget(self.space_layer_note)
        layout.addWidget(self.hotkey_group)

        self.future_group = QGroupBox()
        future_layout = QVBoxLayout(self.future_group)
        future_layout.setContentsMargins(8, 8, 8, 8)
        self.future_note = QLabel()
        self.future_note.setWordWrap(True)
        self.future_note.setStyleSheet("color:#555;")
        future_layout.addWidget(self.future_note)
        layout.addWidget(self.future_group)

        self.rating_group = QGroupBox()
        rating_layout = QVBoxLayout(self.rating_group)
        rating_layout.setContentsMargins(8, 8, 8, 8)
        self.rating_note = QLabel()
        self.rating_note.setWordWrap(True)
        self.rating_note.setStyleSheet("color:#555;")
        rating_layout.addWidget(self.rating_note)
        layout.addWidget(self.rating_group)

        layout.addStretch(1)

        self._set_combo_language(current_language())
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

    def _set_combo_language(self, language):
        index = self.language_combo.findData(language)
        if index < 0:
            index = self.language_combo.findData("ja")
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)

    def _on_language_changed(self, *_args):
        language = self.language_combo.currentData() or "ja"
        set_current_language(language)
        self.refresh_texts()
        if hasattr(self.dock, "refresh_language"):
            self.dock.refresh_language()
        if hasattr(self.dock, "set_status"):
            self.dock.set_status(tr("status.language_changed", language))

    def _mark_log_start(self):
        mark_time = time.strftime("%Y-%m-%d %H:%M:%S")
        run_id = time.strftime("%Y%m%d_%H%M%S")
        QgsMessageLog.logMessage(
            f"===== OrthoManager LOG START {mark_time} run={run_id} =====",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        if hasattr(self.dock, "set_status"):
            self.dock.set_status(tr("settings.status.log_start"))

    def _on_xyz_changed(self, *_args):
        enabled = self.xyz_checkbox.isChecked()
        QgsSettings().setValue(XYZ_STATUS_ENABLED_KEY, enabled)
        tool = getattr(self.dock, "xyz_status_tool", None)
        if tool is not None:
            tool.set_enabled(enabled)
        if hasattr(self.dock, "set_status"):
            key = "settings.status.xyz_on" if enabled else "settings.status.xyz_off"
            self.dock.set_status(tr(key))

    def _on_space_layer_changed(self, *_args):
        enabled = self.space_layer_checkbox.isChecked()
        QgsSettings().setValue(SPACE_LAYER_VISIBILITY_ENABLED_KEY, enabled)
        tool = getattr(self.dock, "layer_visibility_hotkey", None)
        if tool is not None:
            tool.set_enabled(enabled)
        if hasattr(self.dock, "set_status"):
            key = "settings.status.space_layer_on" if enabled else "settings.status.space_layer_off"
            self.dock.set_status(tr(key))

    def _sync_xyz_checkbox(self):
        enabled = setting_bool(QgsSettings().value(XYZ_STATUS_ENABLED_KEY, True), True)
        self.xyz_checkbox.blockSignals(True)
        self.xyz_checkbox.setChecked(enabled)
        self.xyz_checkbox.blockSignals(False)

    def _sync_space_layer_checkbox(self):
        enabled = space_setting_bool(QgsSettings().value(SPACE_LAYER_VISIBILITY_ENABLED_KEY, True), True)
        self.space_layer_checkbox.blockSignals(True)
        self.space_layer_checkbox.setChecked(enabled)
        self.space_layer_checkbox.blockSignals(False)

    def refresh_texts(self):
        language = current_language()
        self.title_label.setText(tr("settings.title", language))
        self.language_group.setTitle(tr("settings.language_group", language))
        self.language_label.setText(tr("settings.language_label", language))
        self.language_note.setText(tr("settings.language_note", language))
        self.log_group.setTitle(tr("settings.log_group", language))
        self.btn_log_start.setText(tr("settings.btn.log_start", language))
        self.btn_log_start.setToolTip(tr("settings.tooltip.log_start", language))
        self.xyz_group.setTitle(tr("settings.xyz_group", language))
        self.xyz_checkbox.setText(tr("settings.xyz_checkbox", language))
        self.xyz_checkbox.setToolTip(tr("settings.tooltip.xyz_checkbox", language))
        self.xyz_note.setText(tr("settings.xyz_note", language))
        self.hotkey_group.setTitle(tr("settings.hotkey_group", language))
        self.space_layer_checkbox.setText(tr("settings.space_layer_checkbox", language))
        self.space_layer_checkbox.setToolTip(tr("settings.tooltip.space_layer_checkbox", language))
        self.space_layer_note.setText(tr("settings.space_layer_note", language))
        self.future_group.setTitle(tr("settings.future_group", language))
        self.future_note.setText(tr("settings.future_note", language))
        self.rating_group.setTitle(tr("settings.rating_group", language))
        self.rating_note.setText(tr("settings.rating_note", language))
        self._set_combo_language(language)
        self._sync_xyz_checkbox()
        self._sync_space_layer_checkbox()
