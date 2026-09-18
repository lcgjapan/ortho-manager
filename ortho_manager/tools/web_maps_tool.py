import math
import os

from qgis.PyQt.QtCore import QProcess, QStandardPaths, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsConfigureShortcutsDialog
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
)

from ..i18n import tr


OPEN_MODE_KEY = "OrthoManager/web_maps/open_mode"
BASEMAP_PROPERTY = "ortho_manager/basemap_id"
BASEMAP_GROUP_PROPERTY = "ortho_manager/basemap_group"
BASEMAP_GROUP_NAME = "背景地図（OrthoManager）"


BASEMAPS = (
    ("seamlessphoto", "tools.web_maps.basemap.seamlessphoto", "地理院 全国最新写真", "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", 2, 18, "国土地理院"),
    ("ort", "tools.web_maps.basemap.ort", "地理院 基本図オルソ（2007年～・一部地域）", "https://cyberjapandata.gsi.go.jp/xyz/ort/{z}/{x}/{y}.jpg", 14, 18, "国土地理院"),
    ("airphoto", "tools.web_maps.basemap.airphoto", "地理院 簡易空中写真（2004年～・一部地域）", "https://cyberjapandata.gsi.go.jp/xyz/airphoto/{z}/{x}/{y}.png", 14, 18, "国土地理院"),
    ("std", "tools.web_maps.basemap.std", "地理院 標準地図", "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png", 2, 18, "国土地理院"),
    ("pale", "tools.web_maps.basemap.pale", "地理院 淡色地図", "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", 2, 18, "国土地理院"),
    ("blank", "tools.web_maps.basemap.blank", "地理院 白地図", "https://cyberjapandata.gsi.go.jp/xyz/blank/{z}/{x}/{y}.png", 2, 14, "国土地理院"),
    ("relief", "tools.web_maps.basemap.relief", "地理院 色別標高図", "https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png", 2, 15, "国土地理院"),
    ("hillshademap", "tools.web_maps.basemap.hillshade", "地理院 陰影起伏図", "https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png", 2, 16, "国土地理院"),
    ("osm", "tools.web_maps.basemap.osm", "OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 0, 19, "© OpenStreetMap contributors"),
)


def calculate_web_zoom(scale):
    if scale <= 0:
        return 2
    return int(max(0, min(21, math.log2(591657550.5 / scale))))


def google_maps_url(latitude, longitude, zoom, reuse=False):
    base = f"https://www.google.com/maps/@{latitude:.8f},{longitude:.8f},{int(zoom)}z"
    return base + ("?om_reuse=1" if reuse else "")


def find_chrome_executable():
    candidates = []
    for name in ("chrome.exe", "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = QStandardPaths.findExecutable(name)
        if found:
            candidates.append(found)
    for environment_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = str(os.environ.get(environment_name, "") or "").strip()
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return ""


class WebMapsToolWidget(QWidget):
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self.dock = dock
        self.iface = dock.iface
        self._build_ui()
        self.refresh_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        self.basemap_group = QGroupBox()
        basemap_layout = QVBoxLayout(self.basemap_group)
        row = QHBoxLayout()
        self.basemap_combo = QComboBox()
        for basemap in BASEMAPS:
            self.basemap_combo.addItem("", basemap[0])
        self.add_basemap_button = QPushButton()
        self.add_basemap_button.clicked.connect(self.add_selected_basemap)
        row.addWidget(self.basemap_combo, 1)
        row.addWidget(self.add_basemap_button)
        basemap_layout.addLayout(row)
        self.basemap_note = QLabel()
        self.basemap_note.setWordWrap(True)
        basemap_layout.addWidget(self.basemap_note)
        layout.addWidget(self.basemap_group)

        self.google_group = QGroupBox()
        google_layout = QVBoxLayout(self.google_group)
        self.open_google_button = QPushButton()
        self.open_google_button.clicked.connect(self.open_google_maps)
        google_layout.addWidget(self.open_google_button)

        self.shortcut_title = QLabel()
        self.shortcut_title.setStyleSheet("font-weight: 600;")
        google_layout.addWidget(self.shortcut_title)
        self.shortcut_note = QLabel()
        self.shortcut_note.setWordWrap(True)
        google_layout.addWidget(self.shortcut_note)
        self.shortcut_settings_button = QPushButton()
        self.shortcut_settings_button.clicked.connect(self.open_shortcut_settings)
        google_layout.addWidget(self.shortcut_settings_button)

        mode_row = QHBoxLayout()
        self.new_tab_radio = QRadioButton()
        self.reuse_tab_radio = QRadioButton()
        mode_row.addWidget(self.new_tab_radio)
        mode_row.addWidget(self.reuse_tab_radio)
        mode_row.addStretch(1)
        google_layout.addLayout(mode_row)
        mode = str(QgsSettings().value(OPEN_MODE_KEY, "new") or "new")
        self.reuse_tab_radio.setChecked(mode == "reuse")
        self.new_tab_radio.setChecked(mode != "reuse")
        self.new_tab_radio.toggled.connect(self._save_open_mode)
        self.reuse_tab_radio.toggled.connect(self._save_open_mode)

        self.chrome_title = QLabel()
        self.chrome_title.setStyleSheet("font-weight: 600;")
        google_layout.addWidget(self.chrome_title)
        self.chrome_note = QLabel()
        self.chrome_note.setWordWrap(True)
        google_layout.addWidget(self.chrome_note)
        chrome_row = QHBoxLayout()
        self.open_extension_folder_button = QPushButton()
        self.open_extension_folder_button.clicked.connect(self.open_extension_folder)
        self.open_chrome_extensions_button = QPushButton()
        self.open_chrome_extensions_button.clicked.connect(self.open_chrome_extensions)
        chrome_row.addWidget(self.open_extension_folder_button)
        chrome_row.addWidget(self.open_chrome_extensions_button)
        google_layout.addLayout(chrome_row)
        self.chrome_address_label = QLabel()
        self.chrome_address_label.setWordWrap(True)
        google_layout.addWidget(self.chrome_address_label)
        self.chrome_address_edit = QLineEdit("chrome://extensions/")
        self.chrome_address_edit.setReadOnly(True)
        self.chrome_address_edit.setCursorPosition(0)
        google_layout.addWidget(self.chrome_address_edit)
        self.chrome_steps = QLabel()
        self.chrome_steps.setWordWrap(True)
        google_layout.addWidget(self.chrome_steps)
        layout.addWidget(self.google_group)
        layout.addStretch(1)

    def refresh_texts(self):
        self.note_label.setText(tr("tools.web_maps.note"))
        self.basemap_group.setTitle(tr("tools.web_maps.basemap_group"))
        for index, basemap in enumerate(BASEMAPS):
            self.basemap_combo.setItemText(index, tr(basemap[1]))
        self.add_basemap_button.setText(tr("tools.web_maps.add_basemap"))
        self.basemap_note.setText(tr("tools.web_maps.basemap_note"))
        self.google_group.setTitle(tr("tools.web_maps.google_group"))
        self.open_google_button.setText(tr("tools.web_maps.open_google"))
        self.shortcut_title.setText(tr("tools.web_maps.shortcut_title"))
        self.shortcut_note.setText(tr("tools.web_maps.shortcut_note"))
        self.shortcut_settings_button.setText(tr("tools.web_maps.shortcut_settings"))
        self.new_tab_radio.setText(tr("tools.web_maps.new_tab"))
        self.reuse_tab_radio.setText(tr("tools.web_maps.reuse_tab"))
        self.chrome_title.setText(tr("tools.web_maps.chrome_title"))
        self.chrome_note.setText(tr("tools.web_maps.chrome_note"))
        self.open_extension_folder_button.setText(tr("tools.web_maps.extension_folder"))
        self.open_chrome_extensions_button.setText(tr("tools.web_maps.chrome_settings"))
        self.chrome_address_label.setText(tr("tools.web_maps.chrome_address"))
        self.chrome_steps.setText(tr("tools.web_maps.chrome_steps"))

    def open_shortcut_settings(self):
        dialog = QgsConfigureShortcutsDialog(self)
        dialog.setWindowTitle(tr("tools.web_maps.shortcut_dialog_title"))
        dialog.setFilter("OrthoManager")
        dialog.exec()

    def _message(self, text, level=Qgis.MessageLevel.Info):
        self.iface.messageBar().pushMessage("OrthoManager", text, level=level, duration=5)

    def _save_open_mode(self):
        mode = "reuse" if self.reuse_tab_radio.isChecked() else "new"
        QgsSettings().setValue(OPEN_MODE_KEY, mode)

    def _managed_group(self):
        root = QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if str(child.customProperty(BASEMAP_GROUP_PROPERTY, "")) == "1":
                return child
        group = root.addGroup(BASEMAP_GROUP_NAME)
        group.setCustomProperty(BASEMAP_GROUP_PROPERTY, "1")
        return group

    def _select_managed_layer(self, layer):
        group = self._managed_group()
        for child in group.children():
            child.setItemVisibilityChecked(child.layerId() == layer.id())
        self.iface.setActiveLayer(layer)
        self.iface.mapCanvas().refresh()

    def add_selected_basemap(self):
        basemap_id = self.basemap_combo.currentData()
        definition = next((item for item in BASEMAPS if item[0] == basemap_id), None)
        if definition is None:
            return
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if str(layer.customProperty(BASEMAP_PROPERTY, "")) == basemap_id:
                self._select_managed_layer(layer)
                self._message(tr("tools.web_maps.basemap_existing"))
                return
        _, _, layer_name, tile_url, zmin, zmax, attribution = definition
        encoded_url = QUrl.toPercentEncoding(tile_url).data().decode("ascii")
        source = f"type=xyz&url={encoded_url}&zmin={zmin}&zmax={zmax}&crs=EPSG:3857"
        layer = QgsRasterLayer(source, layer_name, "wms")
        if not layer.isValid():
            self._message(tr("tools.web_maps.basemap_failed"), Qgis.MessageLevel.Warning)
            return
        layer.setCustomProperty(BASEMAP_PROPERTY, basemap_id)
        layer.serverProperties().setAttribution(attribution)
        project.addMapLayer(layer, False)
        group = self._managed_group()
        group.addLayer(layer)
        self._select_managed_layer(layer)
        self._message(tr("tools.web_maps.basemap_added"))

    def open_google_maps(self):
        try:
            canvas = self.iface.mapCanvas()
            source_crs = canvas.mapSettings().destinationCrs()
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            center = transform.transform(canvas.center())
            zoom = calculate_web_zoom(canvas.scale())
            reuse = self.reuse_tab_radio.isChecked()
            url = google_maps_url(center.y(), center.x(), zoom, reuse=reuse)
            if not QDesktopServices.openUrl(QUrl(url)):
                raise RuntimeError("browser open failed")
            self._message(tr("tools.web_maps.google_sent"))
        except Exception:
            self._message(tr("tools.web_maps.google_failed"), Qgis.MessageLevel.Warning)

    def extension_folder(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chrome_extension"))

    def open_extension_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.extension_folder()))

    def open_chrome_extensions(self):
        chrome = find_chrome_executable()
        if not chrome:
            self._message(tr("tools.web_maps.chrome_open_failed"), Qgis.MessageLevel.Warning)
            return
        result = QProcess.startDetached(chrome, ["--new-tab", "about:blank"])
        started = result[0] if isinstance(result, tuple) else bool(result)
        if not started:
            self._message(tr("tools.web_maps.chrome_open_failed"), Qgis.MessageLevel.Warning)
