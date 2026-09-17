from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import os
import time
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMessageLog, Qgis
from .ortho_manager_dockwidget import OrthoManagerDockWidget
from .layer_lock import LOCK_PROPERTY, SELECT_LOCK_PROPERTY
from .layer_visibility_hotkey import LayerVisibilityHotkey
from .xyz_status_tool import XyzStatusTool


class OrthoManager:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dockwidget = None
        self.xyz_status_tool = None
        self.layer_visibility_hotkey = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(QIcon(icon_path), "OrthoManager", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dockwidget)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu("&OrthoManager", self.action)

        self.xyz_status_tool = XyzStatusTool(self.iface)
        self.xyz_status_tool.install()
        self.layer_visibility_hotkey = LayerVisibilityHotkey(self.iface)
        self.layer_visibility_hotkey.install()

        self.dockwidget = OrthoManagerDockWidget(self.iface)
        self.dockwidget.xyz_status_tool = self.xyz_status_tool
        self.dockwidget.layer_visibility_hotkey = self.layer_visibility_hotkey
        self.layer_visibility_hotkey.dock = self.dockwidget
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.hide()

        QgsProject.instance().readProject.connect(self._on_project_read)
        QgsProject.instance().writeProject.connect(self._on_project_write)
        QgsProject.instance().cleared.connect(self._on_project_cleared)

    def toggle_dockwidget(self):
        if self.dockwidget.isVisible():
            self.dockwidget.hide()
        else:
            self.dockwidget.show()

    def _on_project_read(self, doc):
        self._log_project_start()
        restored = self.dockwidget.restore_from_project()
        if restored or self.dockwidget.vrt_registry or self._project_has_ortho_manager_locks():
            self.dockwidget.show()

    def _project_has_ortho_manager_locks(self):
        root = QgsProject.instance().layerTreeRoot()

        def truthy(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in ("1", "true", "yes", "on")

        def walk(node):
            if node is None:
                return False
            try:
                if truthy(node.customProperty(LOCK_PROPERTY, False)) or truthy(node.customProperty(SELECT_LOCK_PROPERTY, False)):
                    return True
            except Exception:
                _om_record_ignored_exception(__name__, 73)
            try:
                layer = node.layer()
            except Exception:
                layer = None
            if layer is not None:
                try:
                    if truthy(layer.customProperty(LOCK_PROPERTY, False)) or truthy(layer.customProperty(SELECT_LOCK_PROPERTY, False)):
                        return True
                except Exception:
                    _om_record_ignored_exception(__name__, 83)
            try:
                children = node.children()
            except Exception:
                children = []
            for child in children:
                if walk(child):
                    return True
            return False

        return walk(root)

    def _log_project_start(self):
        try:
            project_path = QgsProject.instance().fileName()
            project_name = os.path.basename(project_path) if project_path else "未保存プロジェクト"
            mark_time = time.strftime("%Y-%m-%d %H:%M:%S")
            QgsMessageLog.logMessage(
                f"===== OrthoManager PROJECT START {mark_time} project={project_name} =====",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception:
            _om_record_ignored_exception(__name__, 106)

    def _on_project_write(self, doc):
        self.dockwidget.save_to_project()

    def _on_project_cleared(self):
        self.dockwidget.reset_all()

    def unload(self):
        try:
            QgsProject.instance().readProject.disconnect(self._on_project_read)
            QgsProject.instance().writeProject.disconnect(self._on_project_write)
            QgsProject.instance().cleared.disconnect(self._on_project_cleared)
        except Exception:
            _om_record_ignored_exception(__name__, 120)
        self.iface.removePluginRasterMenu("&OrthoManager", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.xyz_status_tool:
            try:
                self.xyz_status_tool.cleanup()
            except Exception:
                _om_record_ignored_exception(__name__, 127)
            self.xyz_status_tool = None
        if self.layer_visibility_hotkey:
            try:
                self.layer_visibility_hotkey.cleanup()
            except Exception:
                _om_record_ignored_exception(__name__, 133)
            self.layer_visibility_hotkey = None
        if self.dockwidget:
            try:
                self.dockwidget.cleanup_before_unload()
            except Exception:
                _om_record_ignored_exception(__name__, 139)
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()
            self.dockwidget = None
