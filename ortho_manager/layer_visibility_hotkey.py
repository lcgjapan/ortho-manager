from .diagnostics import record_ignored_exception as _om_record_ignored_exception
from qgis.PyQt.QtCore import QObject, QEvent, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
)
from qgis.core import QgsProject, QgsSettings


SPACE_LAYER_VISIBILITY_ENABLED_KEY = "OrthoManager/space_layer_visibility_enabled"


def setting_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _qt_key_space():
    return Qt.Key.Key_Space


def _qt_no_modifier():
    return Qt.KeyboardModifier.NoModifier


def _qevent_key_press():
    return QEvent.Type.KeyPress


class LayerVisibilityHotkey(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.enabled = setting_bool(
            QgsSettings().value(SPACE_LAYER_VISIBILITY_ENABLED_KEY, True),
            True,
        )
        self._installed = False
        self.dock = None

    def install(self):
        app = QApplication.instance()
        if app is None or self._installed:
            return
        app.installEventFilter(self)
        self._installed = True

    def cleanup(self):
        app = QApplication.instance()
        if app is not None and self._installed:
            try:
                app.removeEventFilter(self)
            except Exception:
                _om_record_ignored_exception(__name__, 79)
        self._installed = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        QgsSettings().setValue(SPACE_LAYER_VISIBILITY_ENABLED_KEY, self.enabled)

    def refresh_from_settings(self):
        self.set_enabled(
            setting_bool(
                QgsSettings().value(SPACE_LAYER_VISIBILITY_ENABLED_KEY, True),
                True,
            )
        )

    def eventFilter(self, watched, event):
        try:
            if not self.enabled:
                return False
            if event.type() != _qevent_key_press():
                return False
            if event.key() != _qt_key_space():
                return False
            if event.modifiers() != _qt_no_modifier():
                return False
            if event.isAutoRepeat():
                return True
            if not self._focus_allows_space_toggle():
                return False
            toggled_count = self.toggle_selected_layer_tree_nodes()
            if toggled_count <= 0:
                return False
            return True
        except Exception:
            return False

    def _focus_allows_space_toggle(self):
        app = QApplication.instance()
        if app is None:
            return False
        try:
            if app.activeModalWidget() is not None:
                return False
        except Exception:
            _om_record_ignored_exception(__name__, 123)
        focus_widget = app.focusWidget()
        if focus_widget is None:
            return False
        if isinstance(
            focus_widget,
            (
                QAbstractButton,
                QAbstractItemView,
                QAbstractSpinBox,
                QComboBox,
                QLineEdit,
                QMenu,
                QPlainTextEdit,
                QTextEdit,
            ),
        ):
            return False
        return self._is_widget_in_map_canvas(focus_widget)

    def _is_widget_in_map_canvas(self, widget):
        try:
            canvas = self.iface.mapCanvas()
        except Exception:
            return False
        current = widget
        while current is not None:
            if current is canvas:
                return True
            try:
                current = current.parentWidget()
            except Exception:
                return False
        return False

    def toggle_selected_layer_tree_nodes(self):
        view = self._layer_tree_view()
        if view is None:
            return 0
        nodes = self._selected_nodes(view)
        if not nodes:
            return 0
        target_visible = not all(self._node_is_checked(node) for node in nodes)
        count = 0
        for node in nodes:
            if self._set_node_visibility(node, target_visible):
                count += 1
        if count:
            self._refresh_canvas()
            self._set_status(count, target_visible)
        return count

    def _layer_tree_view(self):
        try:
            return self.iface.layerTreeView()
        except Exception:
            return None

    def _selected_nodes(self, view):
        nodes = []
        try:
            nodes = list(view.selectedNodes(True) or [])
        except Exception:
            nodes = []
        if not nodes:
            try:
                node = view.currentNode()
                if node is not None:
                    nodes = [node]
            except Exception:
                nodes = []
        unique = []
        seen = set()
        for node in nodes:
            try:
                key = id(node)
            except Exception:
                key = None
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            unique.append(node)
        return unique

    def _node_is_checked(self, node):
        try:
            return bool(node.itemVisibilityChecked())
        except Exception:
            try:
                return bool(node.isVisible())
            except Exception:
                return False

    def _set_node_visibility(self, node, visible):
        try:
            children = node.children()
        except Exception:
            children = None
        try:
            if children is not None:
                node.setItemVisibilityCheckedRecursive(visible)
            else:
                node.setItemVisibilityChecked(visible)
            return True
        except Exception:
            return False

    def _refresh_canvas(self):
        try:
            canvas = self.iface.mapCanvas()
            if canvas is not None:
                canvas.refresh()
        except Exception:
            _om_record_ignored_exception(__name__, 237)
        try:
            QgsProject.instance().layerTreeRoot().visibilityChanged.emit()
        except Exception:
            _om_record_ignored_exception(__name__, 241)

    def _set_status(self, count, visible):
        dock = self.dock
        if dock is None or not hasattr(dock, "set_status"):
            return
        text = "選択レイヤ表示 ON" if visible else "選択レイヤ表示 OFF"
        if count > 1:
            text = f"{text} ({count})"
        try:
            dock.set_status(text)
        except Exception:
            _om_record_ignored_exception(__name__, 253)
