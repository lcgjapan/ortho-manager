from qgis.PyQt.QtCore import QObject, QTimer, QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    Qgis,
)
from qgis.gui import QgsLayerTreeViewIndicator


LOCK_PROPERTY = "OrthoManager/vector_data_locked"


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class LayerLockManager(QObject):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._indicators = {}
        self._connected_nodes = {}
        self._selection_connections = {}
        self._locked_icon = self._make_lock_icon(True)
        self._unlocked_icon = self._make_lock_icon(False)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self.refresh)
        self._connect_tree_signals()
        self.refresh()

    def cleanup(self):
        self._disconnect_tree_signals()
        self._disconnect_node_signals()
        self._disconnect_layer_selection_signals()
        self._remove_all_indicators()

    def schedule_refresh(self, *args):
        try:
            self._refresh_timer.start()
        except Exception:
            pass

    def refresh(self):
        self._remove_stale_indicators()
        for node in self._walk_nodes(self.root()):
            if isinstance(node, (QgsLayerTreeGroup, QgsLayerTreeLayer)):
                self._connect_node_signals(node)
                self._ensure_indicator(node)
        self._connect_layer_selection_signals()
        self.apply_read_only_state()

    def is_layer_locked(self, layer):
        if layer is None:
            return False
        try:
            if _truthy(layer.customProperty(LOCK_PROPERTY, False)):
                return True
        except Exception:
            pass
        for _parent, node in self._layer_nodes(layer):
            if self.is_node_effectively_locked(node):
                return True
        return False

    def is_node_effectively_locked(self, node):
        current = node
        while current is not None:
            try:
                if isinstance(current, QgsLayerTreeLayer):
                    layer = current.layer()
                    if layer is not None and _truthy(layer.customProperty(LOCK_PROPERTY, False)):
                        return True
                elif _truthy(current.customProperty(LOCK_PROPERTY, False)):
                    return True
            except Exception:
                pass
            try:
                current = current.parent()
            except Exception:
                current = None
        return False

    def set_layer_locked(self, layer, locked):
        if layer is None:
            return
        try:
            if locked:
                layer.setCustomProperty(LOCK_PROPERTY, True)
                self._clear_layer_selection(layer)
            else:
                layer.removeCustomProperty(LOCK_PROPERTY)
        except Exception:
            pass
        self.apply_read_only_state()
        self.schedule_refresh()

    def set_group_locked(self, group, locked):
        if group is None:
            return
        try:
            if locked:
                group.setCustomProperty(LOCK_PROPERTY, True)
                for layer in self._group_vector_layers(group):
                    self._clear_layer_selection(layer)
            else:
                group.removeCustomProperty(LOCK_PROPERTY)
        except Exception:
            pass
        self.apply_read_only_state()
        self.schedule_refresh()

    def root(self):
        return QgsProject.instance().layerTreeRoot()

    def _connect_tree_signals(self):
        root = self.root()
        for signal_name in ("addedChildren", "removedChildren", "customPropertyChanged", "nameChanged"):
            try:
                getattr(root, signal_name).connect(self.schedule_refresh)
            except Exception:
                pass
        try:
            QgsProject.instance().layersAdded.connect(self.schedule_refresh)
        except Exception:
            pass
        try:
            QgsProject.instance().layersWillBeRemoved.connect(self.schedule_refresh)
        except Exception:
            pass

    def _disconnect_tree_signals(self):
        root = self.root()
        for signal_name in ("addedChildren", "removedChildren", "customPropertyChanged", "nameChanged"):
            try:
                getattr(root, signal_name).disconnect(self.schedule_refresh)
            except Exception:
                pass
        try:
            QgsProject.instance().layersAdded.disconnect(self.schedule_refresh)
        except Exception:
            pass
        try:
            QgsProject.instance().layersWillBeRemoved.disconnect(self.schedule_refresh)
        except Exception:
            pass

    def _connect_node_signals(self, node):
        key = self._node_key(node)
        if key in self._connected_nodes:
            return
        connected = []
        for signal_name in ("addedChildren", "removedChildren", "customPropertyChanged", "nameChanged"):
            try:
                signal = getattr(node, signal_name)
                signal.connect(self.schedule_refresh)
                connected.append(signal)
            except Exception:
                pass
        self._connected_nodes[key] = connected

    def _disconnect_node_signals(self):
        for signals in self._connected_nodes.values():
            for signal in signals:
                try:
                    signal.disconnect(self.schedule_refresh)
                except Exception:
                    pass
        self._connected_nodes.clear()

    def _connect_layer_selection_signals(self):
        live_ids = set()
        for layer in QgsProject.instance().mapLayers().values():
            if not self._is_vector_layer(layer):
                continue
            layer_id = layer.id()
            live_ids.add(layer_id)
            if layer_id in self._selection_connections:
                continue
            handler = lambda *args, lyr=layer: self._on_layer_selection_changed(lyr)
            try:
                layer.selectionChanged.connect(handler)
                self._selection_connections[layer_id] = (layer, handler)
            except Exception:
                pass
        for layer_id in list(self._selection_connections.keys()):
            if layer_id not in live_ids:
                layer, handler = self._selection_connections.pop(layer_id)
                try:
                    layer.selectionChanged.disconnect(handler)
                except Exception:
                    pass

    def _disconnect_layer_selection_signals(self):
        for layer, handler in self._selection_connections.values():
            try:
                layer.selectionChanged.disconnect(handler)
            except Exception:
                pass
        self._selection_connections.clear()

    def _on_layer_selection_changed(self, layer):
        if self.is_layer_locked(layer):
            self._clear_layer_selection(layer)

    def _walk_nodes(self, node):
        if node is None:
            return
        yield node
        try:
            children = node.children()
        except Exception:
            children = []
        for child in children:
            yield from self._walk_nodes(child)

    def _node_key(self, node):
        try:
            return int(node.__hash__())
        except Exception:
            return id(node)

    def _is_vector_layer(self, layer):
        return isinstance(layer, QgsVectorLayer)

    def _layer_nodes(self, layer):
        nodes = []
        layer_id = layer.id()
        for node in self._walk_nodes(self.root()):
            if isinstance(node, QgsLayerTreeLayer) and node.layerId() == layer_id:
                try:
                    parent = node.parent()
                except Exception:
                    parent = None
                nodes.append((parent, node))
        return nodes

    def _group_vector_layers(self, group):
        layers = []
        try:
            for node in group.findLayers():
                layer = node.layer()
                if self._is_vector_layer(layer):
                    layers.append(layer)
        except Exception:
            pass
        return layers

    def _clear_layer_selection(self, layer):
        if not self._is_vector_layer(layer):
            return
        try:
            layer.removeSelection()
        except Exception:
            pass

    def _ensure_indicator(self, node):
        view = self.iface.layerTreeView()
        if view is None:
            return
        key = self._node_key(node)
        indicator = self._indicators.get(key)
        if indicator is None:
            indicator = QgsLayerTreeViewIndicator(view)
            try:
                indicator.clicked.connect(lambda *args, n=node: self._toggle_node(n))
            except Exception:
                pass
            self._indicators[key] = indicator
            try:
                view.addIndicator(node, indicator)
            except Exception:
                self._indicators.pop(key, None)
                return
        locked = self.is_node_effectively_locked(node)
        indicator.setIcon(self._locked_icon if locked else self._unlocked_icon)
        indicator.setToolTip("OrthoManager: ベクタデータロック ON" if locked else "OrthoManager: ベクタデータロック OFF")
        try:
            indicator.changed.emit()
        except Exception:
            try:
                indicator.changed()
            except Exception:
                pass

    def _toggle_node(self, node):
        try:
            if isinstance(node, QgsLayerTreeLayer):
                layer = node.layer()
                if layer is not None:
                    self.set_layer_locked(layer, not _truthy(layer.customProperty(LOCK_PROPERTY, False)))
            elif isinstance(node, QgsLayerTreeGroup):
                self.set_group_locked(node, not _truthy(node.customProperty(LOCK_PROPERTY, False)))
        except RuntimeError:
            self.schedule_refresh()

    def _remove_all_indicators(self):
        view = self.iface.layerTreeView()
        if view is not None:
            for node in list(self._walk_nodes(self.root())):
                key = self._node_key(node)
                indicator = self._indicators.get(key)
                if indicator is not None:
                    try:
                        view.removeIndicator(node, indicator)
                    except Exception:
                        pass
        self._indicators.clear()

    def _remove_stale_indicators(self):
        live_keys = {self._node_key(node) for node in self._walk_nodes(self.root())}
        for key in list(self._indicators.keys()):
            if key not in live_keys:
                self._indicators.pop(key, None)
        for key in list(self._connected_nodes.keys()):
            if key not in live_keys:
                self._connected_nodes.pop(key, None)

    def apply_read_only_state(self):
        for layer in QgsProject.instance().mapLayers().values():
            if not self._is_vector_layer(layer):
                continue
            locked = self.is_layer_locked(layer)
            if locked:
                self._clear_layer_selection(layer)
            try:
                if layer.readOnly() != locked:
                    layer.setReadOnly(locked)
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"LAYER_LOCK_READONLY_FAILED layer={layer.name()} locked={locked} error={exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

    def _make_lock_icon(self, locked):
        pixmap = QPixmap(QSize(18, 18))
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#d93025" if locked else "#5f6368")
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(QColor("#d93025" if locked else "#ffffff"))
        painter.drawRoundedRect(4, 8, 10, 7, 1.5, 1.5)
        painter.setBrush(QColor(0, 0, 0, 0))
        if locked:
            painter.drawArc(6, 3, 6, 8, 0, 180 * 16)
        else:
            painter.drawArc(7, 3, 6, 8, 25 * 16, 210 * 16)
        painter.end()
        return QIcon(pixmap)
