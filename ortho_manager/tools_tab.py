from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QStackedWidget, QSizePolicy
)

from .i18n import tr
from .tools.elevation_raster_tool import ElevationRasterToolWidget
from .tools.rrim_tool import RrimToolWidget


class ToolsTabWidget(QWidget):
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self.dock = dock
        self._tool_rows = []
        self._build_ui()
        self.refresh_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight:bold; color:#1f2937;")
        selector_row.addWidget(self.title_label)

        self.tool_combo = QComboBox()
        self.tool_combo.setMinimumWidth(180)
        self.tool_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        selector_row.addWidget(self.tool_combo)
        selector_row.addStretch(1)
        layout.addLayout(selector_row)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.elevation_raster_tool = ElevationRasterToolWidget(self.dock)
        self._add_tool("tools.elevation_raster.name", self.elevation_raster_tool)
        self.rrim_tool = RrimToolWidget(self.dock)
        self._add_tool("tools.rrim.name", self.rrim_tool)

        self.tool_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.tool_combo.setCurrentIndex(0)

        layout.addWidget(self.stack, 1)

    def _add_tool(self, label_key, widget):
        self.tool_combo.addItem(tr(label_key))
        self.stack.addWidget(widget)
        self._tool_rows.append((label_key, widget))

    def refresh_texts(self):
        self.title_label.setText(tr("tools.title"))
        current_index = self.tool_combo.currentIndex()
        for index, (label_key, widget) in enumerate(self._tool_rows):
            self.tool_combo.setItemText(index, tr(label_key))
            if hasattr(widget, "refresh_texts"):
                widget.refresh_texts()
        if 0 <= current_index < self.tool_combo.count():
            self.tool_combo.setCurrentIndex(current_index)
