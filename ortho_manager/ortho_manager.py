import os
import time
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMessageLog, Qgis
from .ortho_manager_dockwidget import OrthoManagerDockWidget


class OrthoManager:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dockwidget = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(QIcon(icon_path), "OrthoManager", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dockwidget)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu("&OrthoManager", self.action)

        self.dockwidget = OrthoManagerDockWidget(self.iface)
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
        self.dockwidget.restore_from_project()
        if self.dockwidget.vrt_registry:
            self.dockwidget.show()

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
            pass

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
            pass
        self.iface.removePluginRasterMenu("&OrthoManager", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            try:
                self.dockwidget.cleanup_before_unload()
            except Exception:
                pass
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()
            self.dockwidget = None
