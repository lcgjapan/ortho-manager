import math
import os
import re
import sqlite3

from qgis.PyQt.QtCore import QObject, Qt, QDateTime, QEvent, QRect, QTimer
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap, QKeySequence, QShortcut
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QScrollArea, QInputDialog, QColorDialog, QMenu,
    QWidgetAction, QSizePolicy, QRubberBand, QButtonGroup, QTextEdit, QApplication, QLineEdit,
    QKeySequenceEdit
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsMessageLog, Qgis, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
    QgsSingleSymbolRenderer, QgsFeatureRequest, QgsRectangle,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling, QgsSettings,
    QgsLayerTreeLayer
)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker, QgsSnapIndicator
from .i18n import tr
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


INSPECTION_PROJECT_KEY = "OrthoManager"
INSPECTION_PROJECT_ENTRY = "inspection"
INSPECTION_GROUP = "🔎 オルソ検査"
FREE_INSPECTION_GROUP = "🔎 自由式検査"
LEGACY_INSPECTION_GROUP = "🔎 検査"
INSPECTION_PROP_PREFIX = "OrthoManager/inspection/"
INSPECTION_TYPE_ORTHO = "ortho"
INSPECTION_TYPE_FREE = "free"
GEOM_TYPE_LABELS = {"polygon": "ポリゴン", "line": "ライン", "point": "点"}
SHP_EXPORT_PER_LAYER = "shp_per_layer"
SHP_EXPORT_MERGED = "shp_merged"
DXF_EXPORT_ONE_FILE = "dxf_one_file"
DXF_EXPORT_PER_LAYER = "dxf_per_layer"
TEST_DXF_EXPORT_ONE_FILE = "ac2000_dxf_one_file"
TEST_DXF_EXPORT_PER_LAYER = "ac2000_dxf_per_layer"
DGN_EXPORT_ONE_FILE = "dgn_one_file"
DGN_EXPORT_PER_LAYER = "dgn_per_layer"
DGN_LEGACY_EXPORT_ONE_FILE = "dgn_legacy_one_file"
DGN_LEGACY_EXPORT_PER_LAYER = "dgn_legacy_per_layer"
CONTEXT_ACTION_ORDER_KEY = "OrthoManager/inspection/context_action_order"
CONTEXT_ACTION_BUTTON_WIDTH = 48
CONTEXT_ACTION_DEFAULT_ORDER = ["pan", "select", "layer_change", "delete", "edit", "move", "merge"]
INSPECTION_SHORTCUTS_KEY_PREFIX = "OrthoManager/inspection/shortcuts/"
INSPECTION_DELETE_CONFIRM_KEY = "OrthoManager/inspection/delete_confirm"
INSPECTION_SHORTCUT_DEFINITIONS = [
    ("pan", "パン", ""),
    ("select", "選択", ""),
    ("layer_change", "移層", ""),
    ("delete", "削除", "Del"),
    ("edit", "編集", ""),
    ("move", "移動", ""),
    ("merge", "統合", ""),
    ("continuous", "連続", ""),
    ("shape_polygon", "多角", ""),
    ("shape_rectangle", "矩形", ""),
    ("shape_ellipse", "楕円", ""),
    ("shape_circle", "正円", ""),
    ("shape_line", "ライン", ""),
    ("shape_point", "点", ""),
]


ROUND_ITEMS = {
    1: [
        ("01", "歪み", "ff0000"),
        ("02", "ズレ", "ff00ff"),
        ("03", "ハレーション", "ff8000"),
        ("04", "伸び", "00ff00"),
        ("05", "BLズレ", "ffff00"),
        ("06", "BL交差", "808000"),
        ("07", "GCPズレ", "00ffff"),
        ("08", "その他", "8000ff"),
        ("09", "隣接地区接合", "8080ff"),
    ],
    2: [
        ("21", "修正漏れ", "ff0000"),
        ("22", "修正不可", "0000ff"),
        ("23", "とりあえずOK", "808080"),
        ("24", "修正OK", "c0c0c0"),
        ("25", "再修正", "ff0000"),
    ],
    3: [
        ("31", "修正漏れ", "ff0000"),
        ("32", "修正不可", "0000ff"),
        ("33", "とりあえずOK", "808080"),
        ("34", "修正OK", "c0c0c0"),
        ("35", "再修正", "ff0000"),
    ],
    4: [
        ("41", "修正漏れ", "ff0000"),
        ("42", "修正不可", "0000ff"),
        ("43", "とりあえずOK", "808080"),
        ("44", "修正OK", "c0c0c0"),
        ("45", "再修正", "ff0000"),
    ],
}


def _safe_layer_name(text):
    text = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
    return text[:80] if text else "inspection"


def _base_name(code, name):
    return f"{code}_{name}" if code else name


class InspectionLayerMenuButton(QPushButton):
    def __init__(self, text, tab, source_name, menu, menu_pos, parent=None):
        super().__init__(text, parent)
        self.tab = tab
        self.source_name = source_name
        self.menu = menu
        self.menu_pos = menu_pos
        self.press_pos = None
        self.right_press_pos = None
        self.dragging = False
        self.setProperty("inspection_source", source_name)

    def _event_global_pos(self, event):
        try:
            return event.globalPosition().toPoint()
        except Exception:
            return event.globalPos()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.right_press_pos = event.pos()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_pos = event.pos()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.pos() - self.press_pos
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.tab.update_layer_drag_target(self.source_name, self._event_global_pos(event), self)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.right_press_pos is not None:
            event.accept()
            global_pos = self._event_global_pos(event)
            self.right_press_pos = None
            QTimer.singleShot(0, lambda: self.tab.show_layer_management_menu(self.source_name, global_pos))
            return
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            event.accept()
            self.unsetCursor()
            target_source = self.tab.layer_source_at_global_pos(self._event_global_pos(event))
            self.tab.clear_layer_drag_visual()
            QTimer.singleShot(0, lambda: self.tab.handle_layer_button_drop(self.source_name, target_source, self.menu_pos, self.menu))
            self.press_pos = None
            self.dragging = False
            return
        self.unsetCursor()
        self.press_pos = None
        self.right_press_pos = None
        self.dragging = False
        super().mouseReleaseEvent(event)


class InspectionGroupMenuButton(QPushButton):
    def __init__(self, text, tab, group_name, menu, menu_pos, parent=None):
        super().__init__(text, parent)
        self.tab = tab
        self.group_name = group_name or ""
        self.menu = menu
        self.menu_pos = menu_pos
        self.press_pos = None
        self.right_press_pos = None
        self.dragging = False
        self.setProperty("inspection_drop_target", f"__free_group_bottom__:{self.group_name}")
        self.setProperty("inspection_group_name", self.group_name)

    def _event_global_pos(self, event):
        try:
            return event.globalPosition().toPoint()
        except Exception:
            return event.globalPos()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.right_press_pos = event.pos()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_pos = event.pos()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.group_name and self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.pos() - self.press_pos
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.tab.update_free_group_drag_target(self.group_name, self._event_global_pos(event), self)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.right_press_pos is not None:
            event.accept()
            global_pos = self._event_global_pos(event)
            self.right_press_pos = None
            QTimer.singleShot(0, lambda: self.tab.show_free_group_management_menu(self.group_name, global_pos, self.menu_pos))
            return
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            event.accept()
            self.unsetCursor()
            target_group, position, _button = self.tab.free_group_drop_target_at_global_pos(self._event_global_pos(event))
            self.tab.clear_free_group_drag_visual()
            QTimer.singleShot(0, lambda: self.tab.handle_free_group_button_drop(self.group_name, target_group, position, self.menu_pos, self.menu))
            self.press_pos = None
            self.right_press_pos = None
            self.dragging = False
            return
        self.unsetCursor()
        self.press_pos = None
        self.right_press_pos = None
        self.dragging = False
        super().mouseReleaseEvent(event)


class InspectionActionMenuButton(QPushButton):
    def __init__(self, text, tab, action_key, menu, menu_pos, parent=None):
        super().__init__(text, parent)
        self.tab = tab
        self.action_key = action_key
        self.menu = menu
        self.menu_pos = menu_pos
        self.press_pos = None
        self.dragging = False
        self.setProperty("inspection_action_key", action_key)

    def _event_global_pos(self, event):
        try:
            return event.globalPosition().toPoint()
        except Exception:
            return event.globalPos()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_pos = event.pos()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.pos() - self.press_pos
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.tab.update_action_drag_target(self.action_key, self._event_global_pos(event), self)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            event.accept()
            self.unsetCursor()
            target_key, _target_widget = self.tab.action_drop_target_at_global_pos(self._event_global_pos(event))
            if not target_key:
                target_key = self.tab.action_drag_highlight_target
            self.tab.clear_action_drag_visual()
            QTimer.singleShot(0, lambda: self.tab.handle_action_button_drop(self.action_key, target_key, self.menu_pos, self.menu))
            self.press_pos = None
            self.dragging = False
            return
        self.unsetCursor()
        self.press_pos = None
        self.dragging = False
        super().mouseReleaseEvent(event)


class InspectionMapTool(QgsMapTool):
    def __init__(self, canvas, tab):
        super().__init__(canvas)
        self.canvas = canvas
        self.tab = tab
        self.points = []
        self.rubber_band = None
        self.vertex_markers = []
        self.select_start_point = None
        self.select_start_pixel = None
        self.select_band = None
        self.shape_start_point = None
        self.shape_start_pixel = None
        self.last_shape_preview_pixel = None
        self.move_start_point = None
        self.move_start_pixel = None
        self.move_dragging = False
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.snap_indicator.setVisible(False)

    def deactivate(self):
        self._clear_rubber_band()
        self._clear_select_band()
        self._clear_move_state()
        self._clear_snap_indicator()
        super().deactivate()

    def flags(self):
        if getattr(self.tab, "operation_mode", "") in ("create", "edit", "move"):
            return QgsMapTool.Flag.EditTool
        return super().flags()

    def _clear_rubber_band(self):
        if self.rubber_band:
            try:
                self.canvas.scene().removeItem(self.rubber_band)
            except Exception:
                pass
            self.rubber_band = None
        self._clear_vertex_markers()
        self.points = []
        self.shape_start_point = None
        self.shape_start_pixel = None
        self.last_shape_preview_pixel = None
        self._clear_snap_indicator()

    def _clear_vertex_markers(self):
        for marker in self.vertex_markers:
            try:
                self.canvas.scene().removeItem(marker)
            except Exception:
                pass
        self.vertex_markers = []

    def _clear_select_band(self):
        if self.select_band:
            try:
                self.select_band.hide()
                self.select_band.deleteLater()
            except Exception:
                pass
            self.select_band = None
        self.select_start_point = None
        self.select_start_pixel = None

    def _clear_move_state(self):
        self.tab.clear_feature_move_preview()
        self.move_start_point = None
        self.move_start_pixel = None
        self.move_dragging = False

    def _clear_snap_indicator(self):
        try:
            self.snap_indicator.setVisible(False)
        except Exception:
            pass

    def _snap_match(self, event):
        try:
            utils = self.canvas.snappingUtils()
            if utils:
                try:
                    layer = self.tab.active_layer()
                    if layer:
                        utils.setCurrentLayer(layer)
                except Exception:
                    pass
                match = utils.snapToMap(event.pixelPoint())
                if match and match.isValid():
                    return match
        except Exception:
            pass
        try:
            match = event.mapPointMatch()
            if match and match.isValid():
                return match
        except Exception:
            pass
        return None

    def _update_snap_indicator(self, match):
        try:
            if match and match.isValid():
                self.snap_indicator.setMatch(match)
                self.snap_indicator.setVisible(True)
            else:
                self.snap_indicator.setVisible(False)
        except Exception:
            pass

    def _event_map_point(self, event, use_snap=False):
        if use_snap:
            match = self._snap_match(event)
            self._update_snap_indicator(match)
            if match and match.isValid():
                try:
                    return QgsPointXY(match.point())
                except Exception:
                    pass
            try:
                return QgsPointXY(event.snapPoint())
            except Exception:
                pass
        return QgsPointXY(event.mapPoint())

    def _ensure_select_band(self):
        if self.select_band:
            return
        self.select_band = QRubberBand(QRubberBand.Shape.Rectangle, self.canvas.viewport())

    def _update_select_band(self, end_pixel):
        if not self.select_start_pixel:
            return
        self._ensure_select_band()
        rect = QRect(self.select_start_pixel, end_pixel).normalized()
        self.select_band.setGeometry(rect)
        self.select_band.show()

    def _ensure_rubber_band(self, layer):
        if self.rubber_band:
            return
        geom_type = Qgis.GeometryType.Line
        if self.tab.active_geom_type == "polygon":
            geom_type = Qgis.GeometryType.Polygon
        self.rubber_band = QgsRubberBand(self.canvas, geom_type)
        stroke_color = QColor(f"#{self.tab.active_color or 'ff0000'}")
        stroke_color.setAlpha(220)
        fill_color = QColor(stroke_color)
        fill_color.setAlpha(35 if geom_type == Qgis.GeometryType.Polygon else 0)
        try:
            self.rubber_band.setStrokeColor(stroke_color)
            self.rubber_band.setFillColor(fill_color)
            if geom_type == Qgis.GeometryType.Polygon:
                self.rubber_band.setBrushStyle(Qt.BrushStyle.SolidPattern)
        except Exception:
            self.rubber_band.setColor(stroke_color)
        self.rubber_band.setWidth(self.tab.preview_rubber_band_width(layer))

    def _has_capture_state(self):
        return bool(self.points or self.vertex_markers or self.shape_start_point or self.rubber_band)

    def _remove_rubber_band_only(self):
        if self.rubber_band:
            try:
                self.canvas.scene().removeItem(self.rubber_band)
            except Exception:
                pass
            self.rubber_band = None

    def _rebuild_capture_preview(self, preview_point=None):
        layer = self.tab.active_layer()
        if not layer or not self.points:
            return
        self._ensure_rubber_band(layer)
        geom_type = Qgis.GeometryType.Polygon if self.tab.active_geom_type == "polygon" else Qgis.GeometryType.Line
        try:
            self.rubber_band.reset(geom_type)
            self.rubber_band.setWidth(self.tab.preview_rubber_band_width(layer))
        except Exception:
            self._remove_rubber_band_only()
            self._ensure_rubber_band(layer)
        draw_points = [QgsPointXY(point) for point in self.points]
        if preview_point is not None:
            draw_points.append(QgsPointXY(preview_point))
            if self.tab.active_geom_type == "polygon" and len(self.points) >= 2:
                draw_points.append(QgsPointXY(self.points[0]))
        last_index = len(draw_points) - 1
        for index, point in enumerate(draw_points):
            self.rubber_band.addPoint(QgsPointXY(point), index == last_index)
        self.rubber_band.show()

    def _remove_last_capture_point(self):
        if not self.points:
            return False
        self.points.pop()
        if self.vertex_markers:
            marker = self.vertex_markers.pop()
            try:
                self.canvas.scene().removeItem(marker)
            except Exception:
                pass
        self._remove_rubber_band_only()
        layer = self.tab.active_layer()
        if layer and self.points:
            self._rebuild_capture_preview()
        return True

    def _add_capture_vertex_marker(self, point):
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(QgsPointXY(point))
        color = QColor(f"#{self.tab.active_color or 'ff0000'}")
        color.setAlpha(255)
        marker.setColor(color)
        marker.setIconSize(11)
        marker.setPenWidth(3)
        try:
            marker.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
        except Exception:
            try:
                marker.setIconType(QgsVertexMarker.ICON_CROSS)
            except Exception:
                pass
        try:
            marker.setZValue(1000)
        except Exception:
            pass
        self.vertex_markers.append(marker)

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if self.tab.operation_mode == "create" and self.points:
                try:
                    event.accept()
                except Exception:
                    pass
                self._finish_capture()
                return
            if self.tab.operation_mode == "edit":
                try:
                    event.accept()
                except Exception:
                    pass
                self.tab.finish_edit_mode(defer_pan=True)
                return
            self.tab.show_context_menu(self.canvas.mapToGlobal(event.pixelPoint()))
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        point = self._event_map_point(event)
        mode = self.tab.operation_mode
        if mode in ("select", "layer_change_select"):
            self.select_start_point = QgsPointXY(point)
            self.select_start_pixel = event.pixelPoint()
            self._ensure_select_band()
            self._update_select_band(self.select_start_pixel)
            return
        if mode == "layer_change":
            self.tab.set_status("移層: 右クリックメニューから移動先項目を選択してください")
            return
        if mode == "delete":
            self.tab.delete_feature_at(point)
            return
        if mode == "move":
            if self.tab.begin_feature_move_at(point):
                self.move_start_point = QgsPointXY(point)
                self.move_start_pixel = event.pixelPoint()
                self.move_dragging = False
            return
        if mode == "edit":
            self.tab.prepare_edit_layer_at(point)
            return
        if mode == "merge":
            self.tab.toggle_merge_feature_at(point)
            return

        layer = self.tab.active_layer()
        if not layer:
            self.tab.select_feature_at(point)
            return

        geom_type = self.tab.active_geom_type
        capture_point = self._event_map_point(event, use_snap=True)
        if geom_type == "point":
            self.tab.add_geometry_feature(layer, QgsGeometry.fromPointXY(capture_point))
            return

        if geom_type == "polygon" and self.tab.active_capture_shape != "polygon":
            self.shape_start_point = QgsPointXY(capture_point)
            self.shape_start_pixel = event.pixelPoint()
            self.last_shape_preview_pixel = event.pixelPoint()
            self._ensure_rubber_band(layer)
            self._update_shape_preview(capture_point)
            return

        self._ensure_rubber_band(layer)
        self.points.append(QgsPointXY(capture_point))
        self._add_capture_vertex_marker(capture_point)
        self._rebuild_capture_preview()

    def canvasMoveEvent(self, event):
        if self.tab.operation_mode in ("select", "layer_change_select") and self.select_start_point:
            self._clear_snap_indicator()
            self._update_select_band(event.pixelPoint())
        elif self.tab.operation_mode == "move" and self.move_start_point:
            self._clear_snap_indicator()
            self.move_dragging = True
            self.tab.update_feature_move_preview(self.move_start_point, self._event_map_point(event))
        elif self.tab.operation_mode == "create":
            snap_point = self._event_map_point(event, use_snap=True)
            if not self.tab.active_layer():
                return
            if self.shape_start_point:
                try:
                    pixel = event.pixelPoint()
                    if self.last_shape_preview_pixel:
                        if abs(pixel.x() - self.last_shape_preview_pixel.x()) < 2 and abs(pixel.y() - self.last_shape_preview_pixel.y()) < 2:
                            return
                    self.last_shape_preview_pixel = pixel
                except Exception:
                    pass
                self._update_shape_preview(snap_point)
            elif self.points:
                self._rebuild_capture_preview(snap_point)
        else:
            self._clear_snap_indicator()

    def canvasReleaseEvent(self, event):
        if self.tab.operation_mode == "move" and self.move_start_point:
            self._clear_snap_indicator()
            start_pixel = self.move_start_pixel
            end_pixel = event.pixelPoint()
            moved = False
            try:
                moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
            except Exception:
                moved = self.move_dragging
            start_point = self.move_start_point
            end_point = self._event_map_point(event)
            self.move_start_point = None
            self.move_start_pixel = None
            self.move_dragging = False
            if moved:
                self.tab.finish_feature_move(start_point, end_point)
            else:
                self.tab.clear_feature_move_preview()
                self.tab.set_status("移動: ドラッグすると選択データを移動します")
            return
        if self.shape_start_point and self.tab.operation_mode == "create":
            start_pixel = self.shape_start_pixel
            end_pixel = event.pixelPoint()
            moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
            if moved:
                layer = self.tab.active_layer()
                geometry = self.tab.geometry_from_shape(
                    self.tab.active_capture_shape,
                    self.shape_start_point,
                    self._event_map_point(event, use_snap=True),
                )
                if layer and geometry:
                    self.tab.add_geometry_feature(layer, geometry)
            self._clear_rubber_band()
            return
        if self.tab.operation_mode not in ("select", "layer_change_select") or not self.select_start_point:
            return
        start_pixel = self.select_start_pixel
        end_pixel = event.pixelPoint()
        start_point = self.select_start_point
        end_point = self._event_map_point(event)
        moved = False
        try:
            moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
        except Exception:
            moved = True
        modifiers = event.modifiers()
        self._clear_select_band()
        if moved:
            self.tab.select_features_in_rect(self.tab.rectangle_from_points(start_point, end_point), modifiers)
        else:
            self.tab.select_feature_at(end_point, modifiers)

    def canvasDoubleClickEvent(self, event):
        if self.tab.operation_mode == "edit":
            return
        if self.points:
            try:
                event.accept()
            except Exception:
                pass
            return
        else:
            if self.tab.operation_mode != "edit":
                self.tab.edit_memo_at(event.mapPoint())

    def keyPressEvent(self, event):
        key = event.key()
        if self.tab.operation_mode == "create":
            if key == Qt.Key.Key_Escape:
                if self._has_capture_state():
                    self._clear_rubber_band()
                    self.tab.set_status("作成をキャンセルしました")
                    event.accept()
                    return
            elif key == Qt.Key.Key_Backspace:
                if self.shape_start_point:
                    self._clear_rubber_band()
                    self.tab.set_status("作成開始前に戻しました")
                    event.accept()
                    return
                if self._remove_last_capture_point():
                    message = "1つ前の点に戻しました" if self.points else "作成開始前に戻しました"
                    self.tab.set_status(message)
                    event.accept()
                    return
        if self.tab.handle_shortcut_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _finish_capture(self):
        layer = self.tab.active_layer()
        if not layer:
            self._clear_rubber_band()
            return
        geom_type = self.tab.active_geom_type
        if geom_type == "polygon":
            if len(self.points) < 3:
                self.tab.set_status("ポリゴンは3点以上必要です")
                self._clear_rubber_band()
                return
            pts = list(self.points)
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            geometry = QgsGeometry.fromPolygonXY([pts])
        else:
            if len(self.points) < 2:
                self.tab.set_status("ラインは2点以上必要です")
                self._clear_rubber_band()
                return
            geometry = QgsGeometry.fromPolylineXY(list(self.points))
        self.tab.add_geometry_feature(layer, geometry)
        self._clear_rubber_band()

    def _update_shape_preview(self, end_point):
        if not self.shape_start_point or not self.rubber_band:
            return
        geometry = self.tab.geometry_from_shape(self.tab.active_capture_shape, self.shape_start_point, end_point)
        if not geometry:
            return
        try:
            self.rubber_band.setToGeometry(geometry, None)
            self.rubber_band.show()
            return
        except Exception:
            pass
        polygons = geometry.asPolygon()
        if not polygons:
            return
        self.rubber_band.reset(Qgis.GeometryType.Polygon)
        for point in polygons[0]:
            self.rubber_band.addPoint(QgsPointXY(point), False)
        self.rubber_band.show()



class InspectionExportDialog(QDialog):
    def __init__(self, tab, layers, parent=None):
        super().__init__(parent)
        self.tab = tab
        self.layers = layers
        self.layer_checks = []
        self.setWindowTitle("検査書出")
        self.resize(460, 500)

        layout = QVBoxLayout(self)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("形式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SHP", "DXF（R12）", "DXF（AutoCAD 2000系）", "DGN V7"])
        self.format_combo.currentTextChanged.connect(self.update_export_modes)
        fmt_row.addWidget(self.format_combo)
        layout.addLayout(fmt_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("出力方法:"))
        self.mode_combo = QComboBox()
        mode_row.addWidget(self.mode_combo)
        layout.addLayout(mode_row)
        self.update_export_modes(self.format_combo.currentText())

        layout.addWidget(QLabel("書き出す検査レイヤ:"))
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
            self.mode_combo.addItem("レイヤごとにSHP作成", SHP_EXPORT_PER_LAYER)
            self.mode_combo.addItem("同じ図形タイプなら1つのSHPにまとめる", SHP_EXPORT_MERGED)
        elif fmt == "DXF（R12）":
            self.mode_combo.addItem("1つのDXF（R12）にまとめる", DXF_EXPORT_ONE_FILE)
            self.mode_combo.addItem("レイヤごとにDXF（R12）作成", DXF_EXPORT_PER_LAYER)
        elif fmt == "DXF（AutoCAD 2000系）":
            self.mode_combo.addItem("1つのDXF（AutoCAD 2000系）にまとめる", TEST_DXF_EXPORT_ONE_FILE)
            self.mode_combo.addItem("レイヤごとにDXF（AutoCAD 2000系）作成", TEST_DXF_EXPORT_PER_LAYER)
        else:
            self.mode_combo.addItem("1つのDGN V7にまとめる（Level分け）", DGN_LEGACY_EXPORT_ONE_FILE)
            self.mode_combo.addItem("レイヤごとにDGN V7作成", DGN_LEGACY_EXPORT_PER_LAYER)

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
        self.setWindowTitle("検査メモ")
        self.resize(360, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter: OK / Ctrl+Enter: 改行"))
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
        self.setWindowTitle("検査ショートカット設定")
        self.resize(420, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("検査ONでOrthoManagerの検査マップ操作中だけ有効です。"))
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        row = 0
        shortcuts = tab.inspection_shortcuts()
        for key, label, default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            grid.addWidget(QLabel(label), row, 0)
            editor = QKeySequenceEdit()
            current = shortcuts.get(key, default_value) or ""
            if current:
                editor.setKeySequence(QKeySequence(current))
            editor.setToolTip("空欄にすると未設定になります。")
            clear_btn = QPushButton("クリア")
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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)

    def restore_defaults(self):
        for key, _label, default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            self.editors[key].setKeySequence(QKeySequence(default_value or ""))

    def values(self):
        result = {}
        used = {}
        for key, label, _default_value in INSPECTION_SHORTCUT_DEFINITIONS:
            text = self.editors[key].keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            if not text:
                result[key] = ""
                continue
            norm = self.tab.normalize_shortcut_text(text)
            if norm in used:
                QMessageBox.warning(self, "ショートカット重複", f"「{used[norm]}」と「{label}」に同じキーが設定されています。")
                return None
            used[norm] = label
            result[key] = text
        return result

class VectorImportOptionsDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths or [])
        self.setWindowTitle("ベクタ取込")
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

        self.group_check = QCheckBox("1つのグループとして読み込む")
        self.group_check.setChecked(single_dxf or file_count > 1)
        layout.addWidget(self.group_check)

        grid = QGridLayout()
        grid.addWidget(QLabel("グループ名:"), 0, 0)
        self.name_mode_combo = QComboBox()
        if single_dxf:
            self.name_mode_combo.addItem("DXFファイル名を使う", "file")
            self.name_mode_combo.addItem("手動入力", "manual")
        else:
            self.name_mode_combo.addItem("手動入力", "manual")
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
        self.setWindowTitle("QGISレイヤ取込")
        self.resize(460, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("検査GPKGへコピーするQGISレイヤを選択してください。"))

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
            pass
        return ""

    def selected_layer_ids(self):
        return [chk.property("layer_id") for chk in self.checks if chk.isChecked()]


class InspectionTabWidget(QWidget):
    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui
        self.iface = main_ui.iface
        self.gpkg_path = ""
        self.layers = {}
        self.active_inspection_type = INSPECTION_TYPE_ORTHO
        self.last_free_geom_type = "line"
        self.free_groups = []
        self.active_free_group_name = ""
        self.active_layer_id = ""
        self.active_geom_type = "polygon"
        self.active_color = "ff0000"
        self.operation_mode = "create"
        self.map_tool = None
        self.buttons_by_source = {}
        self.round_buttons = {}
        self.inspection_enabled = False
        self.continuous_capture_enabled = False
        self.active_capture_shape = "polygon"
        self.context_filter_canvas = None
        self.round_menu_expanded = {}
        self.free_group_menu_expanded = {}
        self._original_selection_colors = {}
        self.drag_highlight_button = None
        self.drag_highlight_target = ""
        self.drag_source_button = None
        self.drag_preview_label = None
        self.action_drag_highlight_button = None
        self.action_drag_highlight_target = ""
        self.action_drag_source_button = None
        self.action_drag_preview_label = None
        self.group_drag_highlight_button = None
        self.group_drag_highlight_target = ""
        self.group_drag_source_button = None
        self.group_drag_preview_label = None
        self.feature_move_targets = []
        self.feature_move_preview_bands = []
        self._edit_preview_width_overridden = False
        self._original_digitizing_line_width = None
        self._original_digitizing_line_width_had_key = False
        self._build_ui()
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

        type_row = QHBoxLayout()
        self.inspection_type_buttons = QButtonGroup(self)
        self.inspection_type_buttons.setExclusive(True)
        self.btn_type_ortho = QPushButton()
        self.btn_type_free = QPushButton()
        for button, inspection_type in (
            (self.btn_type_ortho, INSPECTION_TYPE_ORTHO),
            (self.btn_type_free, INSPECTION_TYPE_FREE),
        ):
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, t=inspection_type: self.set_inspection_type(t))
            self.inspection_type_buttons.addButton(button)
            type_row.addWidget(button)
        top_layout.addLayout(type_row)

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

        self.rounds_box = QGroupBox()
        rounds_layout = QHBoxLayout(self.rounds_box)
        for round_no in (2, 3, 4):
            button = QPushButton()
            button.clicked.connect(lambda _=False, r=round_no: self.add_round(r))
            self.round_buttons[round_no] = button
            rounds_layout.addWidget(button)
        layout.addWidget(self.rounds_box)

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
        for button in (self.btn_select, self.btn_delete, self.btn_edit, self.btn_merge, self.btn_shortcut_settings):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        action_layout.addWidget(self.btn_select, 0, 0)
        action_layout.addWidget(self.btn_delete, 0, 1)
        action_layout.addWidget(self.btn_edit, 1, 0)
        action_layout.addWidget(self.btn_merge, 1, 1)
        action_layout.addWidget(self.btn_shortcut_settings, 2, 0, 1, 2)
        action_layout.addWidget(self.chk_delete_confirm, 3, 0, 1, 2)
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
        layout.addStretch()
        self.inspection_qshortcuts = []
        self.refresh_inspection_qshortcuts()
        self.refresh_ui()

    def refresh_texts(self):
        if not hasattr(self, "top_group"):
            return
        self.top_group.setTitle(tr("inspection.group.management"))
        self.btn_type_ortho.setText(tr("inspection.type.ortho"))
        self.btn_type_free.setText(tr("inspection.type.free"))
        self.btn_new.setText(tr("inspection.btn.new"))
        self.btn_load.setText(tr("inspection.btn.load"))
        self.btn_export.setText(tr("inspection.btn.export"))
        self.btn_on.setText(tr("inspection.btn.on"))
        self.rounds_box.setTitle(tr("inspection.group.rounds"))
        for round_no, button in self.round_buttons.items():
            button.setText(tr("inspection.btn.round_add").format(round=round_no))
        self.items_box.setTitle(tr("inspection.group.items"))
        self.action_box.setTitle(tr("inspection.group.edit"))
        self.btn_select.setText(tr("inspection.btn.select_feature"))
        self.btn_delete.setText(tr("inspection.btn.delete"))
        self.btn_edit.setText(tr("inspection.btn.edit"))
        self.btn_merge.setText(tr("inspection.btn.merge"))
        self.btn_shortcut_settings.setText(tr("inspection.btn.shortcut"))
        self.chk_delete_confirm.setText(tr("inspection.chk.delete_confirm"))
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

    def _refresh_delete_inspection_type_text(self):
        key = "inspection.btn.type_delete.free" if self.is_free_inspection() else "inspection.btn.type_delete.ortho"
        self.btn_delete_inspection_type.setText(tr(key))

    def set_status(self, text):
        if hasattr(self.main_ui, "_set_status"):
            self.main_ui._set_status(text)
        else:
            QgsMessageLog.logMessage(text, "OrthoManager", Qgis.MessageLevel.Info)

    def project_home(self):
        project = QgsProject.instance()
        home = project.homePath()
        if home:
            return home
        path = project.fileName()
        if path:
            return os.path.dirname(path)
        return ""

    def default_gpkg_path(self):
        home = self.project_home()
        project = QgsProject.instance()
        base = os.path.splitext(os.path.basename(project.fileName() or ""))[0]
        if not base:
            base = "ortho_project"
        return os.path.join(home, f"{base}_inspection.gpkg") if home else ""

    def ensure_gpkg_path(self):
        if self.gpkg_path:
            return self.gpkg_path
        default_path = self.default_gpkg_path()
        if default_path:
            self.gpkg_path = default_path
            return self.gpkg_path
        path, _ = QFileDialog.getSaveFileName(
            self, "検査GPKGの保存先", "", "GeoPackage (*.gpkg)"
        )
        if not path:
            return ""
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        self.gpkg_path = path
        return path

    def set_inspection_type(self, inspection_type):
        if inspection_type not in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE):
            inspection_type = INSPECTION_TYPE_ORTHO
        if self.active_inspection_type == inspection_type:
            self.refresh_ui()
            return
        self.finish_edit_for_mode_switch()
        self.active_inspection_type = inspection_type
        self.active_layer_id = ""
        self.refresh_ui()
        label = "オルソ検査" if inspection_type == INSPECTION_TYPE_ORTHO else "自由式検査"
        self.set_status(f"検査タイプ: {label}")

    def is_free_inspection(self):
        return self.active_inspection_type == INSPECTION_TYPE_FREE

    def active_inspection_label(self):
        return "自由式検査" if self.is_free_inspection() else "オルソ検査"

    def create_new_inspection(self):
        path = self.ensure_gpkg_path()
        if not path:
            return
        if os.path.exists(path):
            message = "同じ名前の検査GPKGが既にあります。\n既存ファイルに1回目検査レイヤを作成しますか？"
            if self.is_free_inspection():
                message = "同じ名前の検査GPKGが既にあります。\nこのGPKGで自由式検査を開始しますか？"
            reply = QMessageBox.question(
                self, "検査GPKGを使用しますか？",
                message
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.is_free_inspection():
            self.ensure_inspection_root_group()
            self.organize_inspection_layers(silent=True)
        else:
            self.add_round(1)
        self.refresh_ui()
        self.set_status(f"✅ 新規{self.active_inspection_label()}を作成しました")

    def load_inspection_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "検査GPKGを読み込み", "", "GeoPackage (*.gpkg)")
        if not path:
            return
        self.clear_inspection_state(remove_layers=True)
        self.gpkg_path = path
        self.load_layers_from_gpkg()
        self.refresh_ui()
        self.set_status("✅ 検査GPKGを読み込みました")

    def add_round(self, round_no):
        if self.is_free_inspection():
            QMessageBox.information(self, "自由式検査", "自由式検査では標準検査回を作成しません。レイヤ追加から作成してください。")
            return
        if not OGR_OK:
            QMessageBox.critical(self, "GDAL/OGRエラー", "GDAL/OGRを読み込めないため検査レイヤを作成できません。")
            return
        path = self.ensure_gpkg_path()
        if not path:
            return
        for code, name, color in ROUND_ITEMS.get(round_no, []):
            self.create_inspection_layer(round_no, code, name, color, "polygon", custom=False, inspection_type=INSPECTION_TYPE_ORTHO)
        self.load_layers_from_gpkg()
        self.refresh_ui()

    def add_manual_layer(self, insert_above_source=None, free_group_name=None):
        if not isinstance(insert_above_source, str):
            insert_above_source = None
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
        name, ok = QInputDialog.getText(self, "検査レイヤ追加", "レイヤ名:")
        if not ok or not name.strip():
            return
        geom_items = ["ポリゴン", "ライン", "点"]
        default_geom_index = 0
        if inspection_type == INSPECTION_TYPE_FREE:
            default_geom_index = {"polygon": 0, "line": 1, "point": 2}.get(self.last_free_geom_type, 1)
        geom, ok = QInputDialog.getItem(self, "形状選択", "形状:", geom_items, default_geom_index, False)
        if not ok:
            return
        color = QColorDialog.getColor(QColor("#ff0000"), self, "表示色")
        if not color.isValid():
            color = QColor("#ff0000")
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
        self.refresh_ui()

    def import_qgis_project_layers(self, insert_above_source=None):
        self.log_import_code_marker("QGIS_LAYER_IMPORT")
        if not isinstance(insert_above_source, str):
            insert_above_source = None
        if not OGR_OK:
            QMessageBox.critical(self, "QGISレイヤ取込", "GDAL/OGRを読み込めないためQGISレイヤを取り込めません。")
            return
        if not self.ensure_gpkg_path():
            return

        candidates = self.qgis_layer_import_candidates()
        if not candidates:
            QMessageBox.information(self, "QGISレイヤ取込", "取り込めるQGISベクタレイヤがありません。")
            return
        dialog = QgisLayerImportDialog(candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_ids = set(dialog.selected_layer_ids())
        source_layers = [layer for layer in candidates if layer.id() in selected_ids]
        if not source_layers:
            QMessageBox.information(self, "QGISレイヤ取込", "取り込むレイヤを選択してください。")
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
            QMessageBox.critical(self, "QGISレイヤ取込", f"QGISレイヤを取り込めませんでした。\n{exc}")
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
        self.refresh_ui()

        message = f"✅ QGISレイヤ取込: {len(created_layers)} レイヤ / {feature_count} 地物"
        if skipped_count:
            message += f" / 未対応 {skipped_count}"
        self.set_status(message)
        if errors:
            preview = "\n".join(errors[:8])
            if len(errors) > 8:
                preview += f"\n...ほか {len(errors) - 8} 件"
            QMessageBox.warning(self, "QGISレイヤ取込", f"一部取り込めませんでした。\n{preview}")

        if created_layers:
            box = QMessageBox(self)
            box.setWindowTitle("QGISレイヤ取込")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("取り込み前のQGISレイヤをレイヤパネルから外しますか？")
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
            f"INSPECTION_IMPORT_CODE_MARKER action={action} marker=fix4 file={__file__} mtime={mtime}",
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
            if name in (INSPECTION_GROUP, FREE_INSPECTION_GROUP, LEGACY_INSPECTION_GROUP):
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
        target_ds = self.open_or_create_inspection_gpkg(self.gpkg_path, driver)
        if target_ds is None:
            raise RuntimeError(f"検査GPKGを開けません: {self.gpkg_path}")
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
            except Exception as exc:
                skipped += 1
                errors.append(f"{src_layer.name()} / {geom_type}: {exc}")
        return descriptor, written, skipped, errors

    def import_vector_layers(self, insert_above_source=None):
        self.log_import_code_marker("VECTOR_IMPORT")
        if not isinstance(insert_above_source, str):
            insert_above_source = None
        if not OGR_OK:
            QMessageBox.critical(self, "ベクタ取込", "GDAL/OGRを読み込めないためDXF/SHPを取り込めません。")
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
            QMessageBox.information(self, "ベクタ取込", "グループ名を入力してください。")
            return

        try:
            descriptors, feature_count, skipped_count, errors = self._import_vector_files(
                paths, inspection_type, round_no, group_name
            )
        except Exception as exc:
            QMessageBox.critical(self, "ベクタ取込", f"DXF/SHPを取り込めませんでした。\n{exc}")
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
            QMessageBox.warning(self, "ベクタ取込", f"一部取り込めませんでした。\n{preview}")

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
        target_ds = self.open_or_create_inspection_gpkg(self.gpkg_path, driver)
        if target_ds is None:
            raise RuntimeError(f"検査GPKGを開けません: {self.gpkg_path}")
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
            dialog.setWindowTitle("取込ファイルの座標系")
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
        ogr_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
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
            dialog.setWindowTitle("取込ファイルの座標系")
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
            QMessageBox.information(self, "レイヤ名変更", "変更できる検査レイヤがありません。")
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
            label, ok = QInputDialog.getItem(self, "レイヤ名変更", "変更するレイヤ:", labels, current_index, False)
            if not ok:
                return
            layer = layers[labels.index(label)]
        old_name = layer.customProperty(INSPECTION_PROP_PREFIX + "name", self.layer_base_name(layer))
        new_name, ok = QInputDialog.getText(self, "レイヤ名変更", "新しいレイヤ名:", text=str(old_name))
        new_name = new_name.strip() if ok else ""
        if not new_name:
            return
        if QMessageBox.question(
            self,
            "レイヤ名変更",
            f"「{self.display_layer_name(layer)}」を「{new_name}」へ変更しますか？\nGPKG内の物理レイヤ名は変更しません。",
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
        self.refresh_ui()
        self.set_status(f"✅ レイヤ名変更: {new_name}")

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
        label, ok = QInputDialog.getItem(self, title, "対象レイヤ:", labels, current_index, False)
        if not ok:
            return None
        return layers[labels.index(label)]

    def change_inspection_color(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.ordered_inspection_layers()
        if not layers:
            QMessageBox.information(self, "色変更", "色変更できる検査レイヤがありません。")
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
        self.refresh_ui()
        self.set_status(f"✅ 色変更: {self.display_layer_name(layer)}")

    def change_layer_size(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.ordered_inspection_layers()
        if not layers:
            QMessageBox.information(self, "線・点サイズ変更", "変更できる検査レイヤがありません。")
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
            "線・点サイズ変更",
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
            QMessageBox.warning(self, "線・点サイズ変更", "数値を入力してください。")
            return
        if value <= 0:
            QMessageBox.warning(self, "線・点サイズ変更", "0より大きい数値を入力してください。")
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
        self.refresh_ui()
        self.set_status(f"✅ {label} {value_text}: {self.display_layer_name(layer)}")

    def move_manual_layer_round(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.manual_layers()
        if not layers:
            QMessageBox.information(self, "レイヤ移動", "移動できる手動追加レイヤがありません。")
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
                "レイヤ移動",
                "移動するレイヤ:\nレイヤ追加したレイヤのみ対象になります。",
                labels,
                current_layer_index,
                False,
            )
            if not ok:
                return
            layer = layers[labels.index(label)]
        if not layer or not self.is_manual_layer(layer):
            QMessageBox.information(self, "レイヤ移動", "レイヤ追加したレイヤのみ対象になります。")
            return
        existing_rounds = sorted(self.standard_rounds())
        choices = [("追加レイヤ", 0)] + [(f"{round_no}回目検査", round_no) for round_no in existing_rounds]
        if len(choices) <= 1:
            QMessageBox.information(self, "レイヤ移動", "移動先の検査回がまだ作成されていません。")
            return
        current_round = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        current_index = 0
        for index, (_label, round_no) in enumerate(choices):
            if round_no == current_round:
                current_index = index
                break
        labels = [label for label, _round_no in choices]
        choice, ok = QInputDialog.getItem(self, "レイヤ移動", "移動先:", labels, current_index, False)
        if not ok:
            return
        new_round = dict(choices).get(choice, 0)
        if QMessageBox.question(
            self,
            "レイヤ移動",
            f"「{self.display_layer_name(layer)}」を「{choice}」へ移動しますか？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.set_layer_round(layer, new_round)
        self.move_layer_node_to_round_group(layer, new_round)
        self.refresh_counts()
        self.set_status(f"✅ レイヤ移動: {choice}")

    def free_group_names(self):
        names = []
        for name in self.free_groups:
            name = str(name or "").strip()
            if name and name not in names:
                names.append(name)
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) != INSPECTION_TYPE_FREE:
                continue
            name = str(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def add_free_group(self):
        if not self.is_free_inspection():
            return
        if not self.ensure_gpkg_path():
            return
        name, ok = QInputDialog.getText(self, "グループ追加", "グループ名:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.free_group_names():
            QMessageBox.information(self, "グループ追加", "同じ名前のグループが既にあります。")
            return
        self.free_groups.append(name)
        self.active_free_group_name = name
        self.ensure_free_group(name)
        self.refresh_ui()
        self.set_status(f"✅ グループ追加: {name}")

    def rename_free_group(self, old_name=None):
        if not self.is_free_inspection():
            return
        groups = self.free_group_names()
        if old_name == "":
            QMessageBox.information(self, "グループ名変更", "自由式検査直下のレイヤはグループではありません。")
            return
        elif not groups:
            QMessageBox.information(self, "グループ名変更", "変更できる自由式グループがありません。")
            return
        elif old_name not in groups:
            choices = groups
            old_label, ok = QInputDialog.getItem(self, "グループ名変更", "対象グループ:", choices, 0, False)
            if not ok:
                return
            old_name = old_label
        old_title = self.free_group_title(old_name)
        new_name, ok = QInputDialog.getText(self, "グループ名変更", "新しいグループ名:", QLineEdit.EchoMode.Normal, old_title)
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name != old_name and new_name in groups:
            QMessageBox.information(self, "グループ名変更", "同じ名前のグループが既にあります。")
            return
        self.free_groups = [new_name if name == old_name else name for name in self.free_groups]
        if self.active_free_group_name == old_name:
            self.active_free_group_name = new_name
        for layer in self.inspection_layers():
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE and layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") == old_name:
                self.set_layer_group_name(layer, new_name)
        root_group = self.ensure_inspection_root_group()
        old_groups = self.direct_child_groups(root_group, old_name)
        for group in old_groups:
            try:
                group.setName(new_name)
            except Exception:
                pass
        self.organize_inspection_layers(silent=True)
        self.refresh_ui()
        self.set_status(f"✅ グループ名変更: {old_title} → {new_name}")

    def set_layer_group_name(self, layer, group_name):
        group_name = str(group_name or "").strip()
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", group_name)
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "inspection_type", INSPECTION_TYPE_FREE)
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["group_name"] = group_name
            self.layers[source]["inspection_type"] = INSPECTION_TYPE_FREE
        if group_name and group_name not in self.free_groups:
            self.free_groups.append(group_name)

    def delete_manual_layer(self, layer=None):
        if not isinstance(layer, QgsVectorLayer):
            layer = None
        layers = self.manual_layers()
        if not layers:
            QMessageBox.information(self, "手動削除", "削除できる手動追加レイヤがありません。")
            return
        if layer is None:
            layer = self.choose_layer_dialog("手動削除", layers, self.active_layer())
            if not layer:
                return
        if not self.is_manual_layer(layer):
            QMessageBox.information(self, "手動削除", "手動追加レイヤだけ削除できます。")
            return
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if QMessageBox.question(
            self,
            "手動レイヤ削除",
            f"手動追加レイヤ「{self.display_layer_name(layer)}」を削除しますか？\nQGIS上のレイヤとGPKG内の該当レイヤを削除します。",
        ) != QMessageBox.StandardButton.Yes:
            return
        layer_id = layer.id()
        QgsProject.instance().removeMapLayer(layer_id)
        self.layers.pop(source, None)
        if self.active_layer_id == layer_id:
            self.active_layer_id = ""
        QApplication.processEvents()
        deleted = self.delete_gpkg_layer(source)
        self.refresh_ui()
        if deleted:
            self.set_status(f"🗑 手動レイヤ削除: {source}")
        else:
            QMessageBox.warning(self, "手動レイヤ削除", "QGIS上のレイヤは削除しましたが、GPKG内レイヤの削除に失敗しました。QGIS再起動後に再実行してください。")

    def delete_gpkg_layer(self, source_name):
        if not OGR_OK or not self.gpkg_path or not os.path.exists(self.gpkg_path):
            return False
        try:
            ds = ogr.Open(self.gpkg_path, 1)
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

    def delete_layers_physically(self, layers):
        if not layers:
            return []
        project = QgsProject.instance()
        sources = []
        for layer in layers:
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if source:
                sources.append(source)
            try:
                project.removeMapLayer(layer.id())
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        QApplication.processEvents()
        failed = []
        for source in sources:
            self.layers.pop(source, None)
            if not self.delete_gpkg_layer(source):
                failed.append(source)
        if self.active_layer_id and not project.mapLayer(self.active_layer_id):
            self.active_layer_id = ""
        return failed

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

    def delete_current_inspection_type(self):
        is_free = self.is_free_inspection()
        root_group_name = FREE_INSPECTION_GROUP if is_free else INSPECTION_GROUP
        title = "自由式検査削除" if is_free else "オルソ検査削除"
        layers = self.current_inspection_layers()
        root = QgsProject.instance().layerTreeRoot()
        group_exists = root.findGroup(root_group_name) is not None
        if not layers and not group_exists:
            QMessageBox.information(self, title, "削除できる検査グループまたは検査レイヤがありません。")
            return
        if is_free:
            message = (
                "自由式検査グループ内の全レイヤをGPKGから完全削除します。\n"
                "空の自由式検査グループだけがある場合は、グループだけ削除します。\n"
                "削除した地物は元に戻せません。\n"
                "削除後は自由式検査で新しいレイヤを追加できます。\n\n"
                "続行しますか？"
            )
        else:
            message = (
                "オルソ検査グループ内の全検査回・全レイヤをGPKGから完全削除します。\n"
                "空のオルソ検査グループだけがある場合は、グループだけ削除します。\n"
                "削除した地物は元に戻せません。\n"
                "削除後は新規検査で1回目から作成し直せます。\n\n"
                "続行しますか？"
            )
        if QMessageBox.question(self, title, message) != QMessageBox.StandardButton.Yes:
            return
        failed = self.delete_layers_physically(layers) if layers else []
        if is_free:
            self.free_groups.clear()
        self.remove_direct_group(root_group_name)
        self.refresh_ui()
        if failed:
            QMessageBox.warning(self, title, "一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed))
        else:
            self.set_status(f"✅ {title}: {len(layers)} レイヤ")
    def delete_ortho_round(self):
        rounds = sorted(self.standard_rounds())
        if not rounds:
            QMessageBox.information(self, "検査回削除", "削除できる検査回がありません。")
            return
        choices = [f"{round_no}回目検査" for round_no in rounds]
        choice, ok = QInputDialog.getItem(self, "検査回削除", "削除する検査回:", choices, 0, False)
        if not ok:
            return
        round_no = int(choice.split("回目", 1)[0])
        layers = [
            layer for layer in self.inspection_layers()
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_ORTHO
            and int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0) == round_no
        ]
        if not layers:
            QMessageBox.information(self, "検査回削除", "削除対象レイヤがありません。")
            return
        message = (
            f"{choice}の標準レイヤと、その検査回内の手動追加レイヤをGPKGから完全削除します。\n"
            "削除した地物は元に戻せません。\n"
            f"削除後は「{round_no}回目追加」で空の検査回として再作成できます。\n\n"
            "続行しますか？"
        )
        if QMessageBox.question(self, "検査回削除", message) != QMessageBox.StandardButton.Yes:
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
            QMessageBox.warning(self, "検査回削除", "一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed))
        else:
            self.set_status(f"✅ 検査回削除: {choice}")

    def delete_free_group(self, group_name=None):
        groups = self.free_group_names()
        if group_name == "":
            QMessageBox.information(self, "グループ削除", "自由式検査直下はグループではありません。レイヤは手動削除してください。")
            return
        elif not groups:
            QMessageBox.information(self, "グループ削除", "削除できる自由式グループがありません。")
            return
        elif group_name not in groups:
            choices = groups
            group_label, ok = QInputDialog.getItem(self, "グループ削除", "削除するグループ:", choices, 0, False)
            if not ok:
                return
            group_name = group_label
        layers = [
            layer for layer in self.inspection_layers()
            if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE
            and layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") == group_name
        ]
        group_title = self.free_group_title(group_name)
        message = (
            f"自由式グループ「{group_title}」内のレイヤをGPKGから完全削除します。\n"
            "削除した地物は元に戻せません。\n"
            "空グループの場合はグループ表示だけ削除します。\n\n"
            "続行しますか？"
        )
        if QMessageBox.question(self, "グループ削除", message) != QMessageBox.StandardButton.Yes:
            return
        failed = self.delete_layers_physically(layers)
        if self.active_free_group_name == group_name:
            self.active_free_group_name = ""
        self.free_groups = [name for name in self.free_groups if name != group_name]
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        if group_name:
            for group in self.direct_child_groups(root_group, group_name):
                try:
                    root_group.removeChildNode(group)
                except Exception:
                    pass
        self.refresh_ui()
        if failed:
            QMessageBox.warning(self, "グループ削除", "一部のGPKGレイヤ削除に失敗しました。\nQGIS再起動後に再実行してください。\n" + "\n".join(failed))
        else:
            self.set_status(f"✅ グループ削除: {group_title}")

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
            QMessageBox.information(self, "空地物削除", "ジオメトリなしの検査地物はありません。")
            return
        if QMessageBox.question(self, "空地物削除", f"ジオメトリなしの検査地物 {total} 件を削除しますか？") != QMessageBox.StandardButton.Yes:
            return
        for layer, ids in targets:
            layer.dataProvider().deleteFeatures(ids)
            layer.removeSelection()
            layer.updateExtents()
            layer.triggerRepaint()
        self.refresh_counts()
        self.set_status(f"🧹 空地物削除: {total} 件")

    def organize_inspection_layers(self, silent=False):
        self.ensure_inspection_root_group()
        removed_duplicates = self.remove_duplicate_loaded_inspection_layers()
        moved = 0
        for layer in self.inspection_layers():
            if self.move_layer_node_to_inspection_group(layer):
                moved += 1
        self.refresh_counts()
        if not silent:
            extra = f" / 重複削除:{removed_duplicates}" if removed_duplicates else ""
            self.set_status(f"✅ レイヤ整理: {moved} レイヤ{extra}")

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
        return self.place_layer_at_group_index(layer, target_group, None)

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
        path = self.ensure_gpkg_path()
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
        if crs and crs.isValid() and crs.postgisSrid() > 0:
            try:
                srs.ImportFromEPSG(crs.postgisSrid())
            except Exception:
                return None
            return srs
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
        if not self.gpkg_path or not os.path.exists(self.gpkg_path):
            return
        if not OGR_OK:
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
            self.load_layer(source_name, descriptor)
        ds = None
        self.organize_inspection_layers(silent=True)

    def _is_inspection_source(self, source_name):
        return source_name.startswith("r") or source_name.startswith("manual_") or source_name.startswith("inspection_")

    def _descriptors_from_existing_layers(self):
        result = {}
        for layer in self.inspection_layers():
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
        return {
            "round_no": 0, "code": "", "name": name, "color": "ff0000",
            "geom_type": geom_type, "stroke_width": self.default_stroke_width(geom_type),
            "point_size": self.default_point_size(), "source_name": source_name,
            "inspection_type": inspection_type, "group_name": "", "custom": True
        }

    def default_color_for_code(self, code):
        for items in ROUND_ITEMS.values():
            for item_code, _name, color in items:
                if item_code == code:
                    return color
        return "ff0000"

    def load_layer(self, source_name, descriptor):
        if source_name in self.layers:
            layer = QgsProject.instance().mapLayer(self.layers[source_name].get("layer_id", ""))
            if layer:
                self.apply_layer_metadata(layer, descriptor)
                self.layers[source_name] = {**descriptor, "layer_id": layer.id()}
                self.place_layer_for_descriptor(layer, descriptor)
                return layer
        layer = self.find_loaded_layer_by_source(source_name)
        if layer:
            self.apply_layer_metadata(layer, descriptor)
            self.layers[source_name] = {**descriptor, "layer_id": layer.id()}
            self.place_layer_for_descriptor(layer, descriptor)
            return layer
        uri = f"{self.gpkg_path}|layername={source_name}"
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

    def find_loaded_layer_by_source(self, source_name):
        for layer in self.inspection_layers():
            if layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") == source_name:
                return layer
        return None

    def ensure_round_group(self, round_no):
        main = self.ensure_inspection_root_group(INSPECTION_TYPE_ORTHO)
        group_name = f"{round_no}回目検査" if round_no else "追加レイヤ"
        group = self.ensure_direct_group(main, group_name)
        return group

    def ensure_free_group(self, group_name):
        main = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        group_name = str(group_name or "").strip()
        if not group_name:
            return main
        if group_name not in self.free_groups:
            self.free_groups.append(group_name)
        return self.ensure_direct_group(main, group_name)

    def ensure_named_inspection_group(self, inspection_type, group_name):
        group_name = str(group_name or "").strip()
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
        return FREE_INSPECTION_GROUP if inspection_type == INSPECTION_TYPE_FREE else INSPECTION_GROUP

    def ensure_inspection_root_group(self, inspection_type=None):
        if inspection_type not in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE):
            inspection_type = self.active_inspection_type
        root = QgsProject.instance().layerTreeRoot()
        return self.ensure_direct_group(root, self.root_group_name_for_type(inspection_type))

    def inspection_root_groups(self, inspection_type=None):
        if inspection_type not in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE):
            inspection_type = self.active_inspection_type
        root = QgsProject.instance().layerTreeRoot()
        groups = []
        for name in (self.root_group_name_for_type(inspection_type), LEGACY_INSPECTION_GROUP):
            for group in self.direct_child_groups(root, name):
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
        source_name = descriptor.get("source_name", "")
        layer.setCustomProperty(INSPECTION_PROP_PREFIX + "source_name", source_name)
        for key in ("round_no", "code", "name", "color", "geom_type", "custom", "stroke_width", "point_size", "inspection_type", "group_name", "preserve_style"):
            layer.setCustomProperty(INSPECTION_PROP_PREFIX + key, descriptor.get(key, ""))
        if not self.layer_preserve_style(layer):
            self.apply_style(layer, descriptor)
        self.update_layer_display_name(layer)

    def apply_style(self, layer, descriptor):
        color = QColor(f"#{descriptor.get('color', 'ff0000')}")
        geom_type = descriptor.get("geom_type", "polygon")
        stroke_width = self.size_from_descriptor(descriptor, "stroke_width", self.default_stroke_width(geom_type))
        point_size = self.size_from_descriptor(descriptor, "point_size", self.default_point_size())
        if geom_type == "polygon":
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
        for layer in self.inspection_layers():
            self.update_layer_display_name(layer)
        self.refresh_ui()

    def refresh_ui(self):
        path_text = self.gpkg_path or tr("inspection.path.none")
        self.path_label.setText(tr("inspection.path").format(path=path_text))
        self.path_label.setToolTip(self.gpkg_path)
        self.btn_type_ortho.setChecked(self.active_inspection_type == INSPECTION_TYPE_ORTHO)
        self.btn_type_free.setChecked(self.active_inspection_type == INSPECTION_TYPE_FREE)
        self.rounds_box.setVisible(not self.is_free_inspection())
        self._rebuild_item_buttons()
        existing_rounds = self.standard_rounds()
        for round_no, button in self.round_buttons.items():
            button.setEnabled(not self.is_free_inspection() and round_no not in existing_rounds and bool(self.gpkg_path))
        has_layers = bool(self.current_inspection_layers())
        has_manual_layers = bool(self.manual_layers())
        self.btn_import_qgis_layer.setEnabled(True)
        self.btn_rename_item.setEnabled(has_layers)
        self.btn_color_item.setEnabled(has_layers)
        self.btn_move_manual.setEnabled(has_manual_layers)
        self.btn_move_manual.setVisible(not self.is_free_inspection())
        self.btn_add_group.setVisible(self.is_free_inspection())
        self.btn_rename_group.setVisible(False)
        self.btn_delete_free_group.setVisible(False)
        self.btn_delete_round.setVisible(not self.is_free_inspection())
        self.btn_add_group.setEnabled(self.is_free_inspection() and bool(self.gpkg_path))
        self.btn_rename_group.setEnabled(False)
        self.btn_delete_free_group.setEnabled(False)
        self.btn_delete_round.setEnabled(not self.is_free_inspection() and bool(existing_rounds))
        self._refresh_delete_inspection_type_text()
        root_group_name = FREE_INSPECTION_GROUP if self.is_free_inspection() else INSPECTION_GROUP
        root_group_exists = QgsProject.instance().layerTreeRoot().findGroup(root_group_name) is not None
        self.btn_delete_inspection_type.setEnabled(bool(self.current_inspection_layers()) or root_group_exists)
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
            if isinstance(layer, QgsVectorLayer) and layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""):
                result.append(layer)
        return result

    def inspection_layers(self):
        result = []
        seen_sources = set()
        for layer in self.raw_inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if source in seen_sources:
                continue
            seen_sources.add(source)
            result.append(layer)
        return result

    def current_inspection_layers(self):
        return [
            layer for layer in self.inspection_layers()
            if self.layer_inspection_type(layer) == self.active_inspection_type
        ]

    def remove_duplicate_loaded_inspection_layers(self):
        by_source = {}
        remove_ids = []
        for layer in self.raw_inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if not source:
                continue
            preferred_id = self.layers.get(source, {}).get("layer_id", "")
            if source not in by_source:
                by_source[source] = layer
                continue
            keep_layer = by_source[source]
            if preferred_id and layer.id() == preferred_id:
                remove_ids.append(keep_layer.id())
                by_source[source] = layer
            else:
                remove_ids.append(layer.id())
        for layer_id in remove_ids:
            try:
                QgsProject.instance().removeMapLayer(layer_id)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査重複レイヤ削除エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        for source, layer in by_source.items():
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
        if self.operation_mode in ("layer_change", "layer_change_select"):
            self.move_selected_to_layer(layer)
            return
        self.finish_edit_for_mode_switch()
        self.active_layer_id = layer.id()
        self.active_geom_type = layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.operation_mode = "create"
        self.iface.setActiveLayer(layer)
        self.ensure_map_tool()
        self.refresh_ui()
        self.set_status(f"検査入力: {self.layer_base_name(layer)}")

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
            self.clear_inspection_selection()
            self.restore_selection_color()
            self.btn_on.setStyleSheet("")
            self.operation_mode = "create"
            try:
                canvas = self.iface.mapCanvas()
                if self.map_tool and canvas.mapTool() == self.map_tool:
                    canvas.unsetMapTool(self.map_tool)
            except Exception:
                pass

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

    def update_map_cursor(self):
        if not self.map_tool:
            return
        cursor = Qt.CursorShape.CrossCursor
        if self.operation_mode in ("delete", "merge", "layer_change", "move"):
            cursor = Qt.CursorShape.PointingHandCursor
        elif self.operation_mode == "layer_change_select":
            self.map_tool.setCursor(self.yellow_select_cursor())
            return
        elif self.operation_mode == "edit":
            self.map_tool.setCursor(self.red_edit_cursor())
            try:
                self.iface.mapCanvas().viewport().setCursor(self.red_edit_cursor())
            except Exception:
                pass
            return
        elif self.operation_mode == "select":
            self.map_tool.setCursor(self.yellow_select_cursor())
            return
        self.map_tool.setCursor(QCursor(cursor))

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

    def switch_to_pan(self):
        if self.operation_mode == "edit":
            self.finish_edit_mode(defer_pan=True)
            return
        self.clear_feature_move_preview()
        self.feature_move_targets = []
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
        self.set_status("パンモード")

    def finish_edit_for_mode_switch(self):
        self.clear_feature_move_preview()
        self.feature_move_targets = []
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
        if self.inspection_enabled and obj == self.context_filter_canvas:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
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
                    self.finish_edit_mode(defer_pan=True)
                    return True
                try:
                    global_pos = event.globalPosition().toPoint()
                except Exception:
                    try:
                        global_pos = event.globalPos()
                    except Exception:
                        global_pos = obj.mapToGlobal(event.pos())
                self.show_context_menu(global_pos)
                return True
            if self.operation_mode == "edit":
                if event.type() == QEvent.Type.MouseMove:
                    point = self.map_point_from_mouse_event(event)
                    if point:
                        self.prepare_edit_layer_at(point, activate_tool=True, quiet=True)
                    try:
                        obj.setCursor(self.red_edit_cursor())
                    except Exception:
                        pass
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

    def show_context_menu(self, global_pos):
        menu = QMenu()
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

    def inspection_shortcuts(self):
        settings = QgsSettings()
        shortcuts = self.inspection_shortcut_defaults()
        for key in shortcuts:
            try:
                value = settings.value(INSPECTION_SHORTCUTS_KEY_PREFIX + key, shortcuts[key])
            except Exception:
                value = shortcuts[key]
            shortcuts[key] = str(value or "").strip()
        return shortcuts

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
        self.refresh_inspection_qshortcuts()
        self.set_status("✅ 検査ショートカットを保存しました")

    def shortcut_focus_allows_run(self):
        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QTextEdit, QKeySequenceEdit)):
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
            if value and self.normalize_shortcut_text(value) == event_norm:
                return self.run_inspection_shortcut(key)
        return False

    def run_inspection_shortcut(self, key):
        actions = {
            "pan": self.switch_to_pan,
            "select": self.start_select,
            "layer_change": self.start_layer_change,
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
            self.set_status(f"連続: {state}")
            return True
        shape_map = {
            "shape_polygon": ("polygon", "polygon", "多角"),
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
            self.set_status("検査項目を選択してください")
            return True
        layer_geom = self.layer_geom_type_key(layer)
        if layer_geom != geom_key:
            layer_label = GEOM_TYPE_LABELS.get(layer_geom, "不明")
            target_label = GEOM_TYPE_LABELS.get(geom_key, label)
            self.set_status(f"この検査項目は{layer_label}です。{target_label}入力には切り替えられません")
            return True
        self.finish_edit_for_mode_switch()
        self.active_geom_type = geom_key
        if shape:
            self.active_capture_shape = shape
        self.operation_mode = "create"
        self.iface.setActiveLayer(layer)
        self.ensure_map_tool()
        self.set_status(f"検査入力: {self.layer_base_name(layer)} / {label}")
        return True
    def context_action_definitions(self):
        return {
            "pan": (tr("inspection.menu.action.pan"), self.switch_to_pan, tr("inspection.menu.tip.pan")),
            "select": (tr("inspection.menu.action.select"), self.start_select, tr("inspection.menu.tip.select")),
            "layer_change": (tr("inspection.menu.action.layer_change"), self.start_layer_change, tr("inspection.menu.tip.layer_change")),
            "delete": (tr("inspection.menu.action.delete"), self.start_delete, tr("inspection.menu.tip.delete")),
            "edit": (tr("inspection.menu.action.edit"), self.start_edit, tr("inspection.menu.tip.edit")),
            "move": (tr("inspection.menu.action.move"), self.start_move, tr("inspection.menu.tip.move")),
            "merge": (tr("inspection.menu.action.merge"), self.start_merge, tr("inspection.menu.tip.merge")),
        }

    def context_action_order(self):
        default_order = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            raw = QgsSettings().value(CONTEXT_ACTION_ORDER_KEY, "")
        except Exception:
            raw = ""
        saved = []
        if raw:
            saved = [part.strip() for part in str(raw).split(",") if part.strip()]
        order = [key for key in saved if key in default_order]
        for key in default_order:
            if key not in order:
                order.append(key)
        return order[:len(default_order)]

    def context_action_rows(self):
        default_order = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            raw = QgsSettings().value(CONTEXT_ACTION_ORDER_KEY, "")
        except Exception:
            raw = ""
        raw = str(raw or "")
        if "|" not in raw:
            order = self.context_action_order()
            return [order[:4], order[4:]]
        rows = []
        seen = set()
        for part in raw.split("|", 1):
            row = []
            for key in [item.strip() for item in part.split(",") if item.strip()]:
                if key in default_order and key not in seen:
                    row.append(key)
                    seen.add(key)
            rows.append(row)
        while len(rows) < 2:
            rows.append([])
        for key in default_order:
            if key not in seen:
                rows[1].append(key)
        if not rows[0] and rows[1]:
            rows[0].append(rows[1].pop(0))
        return [rows[0], rows[1]]

    def save_context_action_order(self, order):
        valid = [key for key in order if key in CONTEXT_ACTION_DEFAULT_ORDER]
        if not valid:
            valid = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            QgsSettings().setValue(CONTEXT_ACTION_ORDER_KEY, ",".join(valid))
        except Exception:
            pass

    def save_context_action_rows(self, rows):
        seen = set()
        cleaned = [[], []]
        for row_index in range(2):
            for key in rows[row_index] if row_index < len(rows) else []:
                if key in CONTEXT_ACTION_DEFAULT_ORDER and key not in seen:
                    cleaned[row_index].append(key)
                    seen.add(key)
        for key in CONTEXT_ACTION_DEFAULT_ORDER:
            if key not in seen:
                cleaned[1].append(key)
        if not cleaned[0] and cleaned[1]:
            cleaned[0].append(cleaned[1].pop(0))
        try:
            QgsSettings().setValue(
                CONTEXT_ACTION_ORDER_KEY,
                ",".join(cleaned[0]) + "|" + ",".join(cleaned[1]),
            )
        except Exception:
            pass

    def context_action_is_active(self, action_key):
        mode = self.operation_mode
        active_by_mode = {
            "pan": "pan",
            "pan_pending": "pan",
            "select": "select",
            "layer_change": "layer_change",
            "layer_change_select": "layer_change",
            "delete": "delete",
            "edit": "edit",
            "move": "move",
            "merge": "merge",
        }
        return active_by_mode.get(mode) == action_key

    def add_context_action_drop_zone(self, row, row_index, slot_index, expand=False):
        zone = QPushButton("")
        zone.setFlat(True)
        zone.setFixedHeight(24)
        zone.setMinimumWidth(22 if expand else 10)
        if expand:
            zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            zone.setFixedWidth(10)
        target = f"__action_slot__:{row_index}:{slot_index}"
        zone.setProperty("inspection_action_drop_target", target)
        base_style = (
            "QPushButton{border:none;background:transparent;padding:0;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        zone.setProperty("base_style", base_style)
        zone.setStyleSheet(base_style)
        row.addWidget(zone)

    def add_context_action_button(self, row, menu, menu_pos, action_key, row_index, slot_index):
        definitions = self.context_action_definitions()
        if action_key not in definitions:
            return
        text, slot, tooltip = definitions[action_key]
        btn = InspectionActionMenuButton(text, self, action_key, menu, menu_pos)
        btn.setFixedWidth(CONTEXT_ACTION_BUTTON_WIDTH)
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.setChecked(self.context_action_is_active(action_key))
        btn.setProperty("inspection_action_row", row_index)
        btn.setProperty("inspection_action_index", slot_index)
        base_style = (
            "QPushButton{border:1px solid #b8c0cc;border-radius:3px;"
            "background:#ffffff;color:#202020;padding:3px 0;}"
            "QPushButton:hover{background:#dcecff;border:1px solid #6b8fd6;}"
            "QPushButton:checked{background:#2d8cff;color:white;font-weight:bold;border:1px solid #1f66c2;}"
        )
        btn.setProperty("base_style", base_style)
        btn.setStyleSheet(base_style)
        btn.clicked.connect(lambda _=False, s=slot, m=menu: (m.close(), s()))
        row.addWidget(btn)

    def add_context_action_row(self, top_rows, menu, menu_pos, row_index, action_keys):
        row_widget = QWidget()
        row_widget.setProperty("inspection_action_row", row_index)
        row_widget.setProperty("inspection_action_row_len", len(action_keys))
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for slot_index, action_key in enumerate(action_keys):
            self.add_context_action_drop_zone(row, row_index, slot_index)
            self.add_context_action_button(row, menu, menu_pos, action_key, row_index, slot_index)
        self.add_context_action_drop_zone(row, row_index, len(action_keys), expand=True)
        top_rows.addWidget(row_widget)

    def populate_context_menu(self, menu, global_pos):
        top_action = QWidgetAction(menu)
        top_widget = QWidget(menu)
        top_rows = QVBoxLayout(top_widget)
        top_rows.setContentsMargins(4, 2, 4, 2)
        top_rows.setSpacing(2)
        layer_change_mode = self.operation_mode in ("layer_change", "layer_change_select")
        if layer_change_mode:
            row = QHBoxLayout()
            row.setSpacing(2)
            btn_pan = QPushButton(tr("inspection.menu.main"))
            btn_pan.setFixedWidth(CONTEXT_ACTION_BUTTON_WIDTH)
            btn_pan.clicked.connect(lambda _=False, m=menu, p=global_pos: (m.close(), self.show_main_menu(p)))
            row.addWidget(btn_pan)
            menu.setStyleSheet("QMenu{background:#fff6c8;} QMenu::item:selected{background:#ffe58a;color:#202020;}")
            top_widget.setStyleSheet("background:#fff6c8;")
            for text, slot, width in [
                (tr("inspection.menu.reselect"), self.restart_layer_change_selection, 56),
                (tr("inspection.menu.cancel"), self.cancel_layer_change, 50),
            ]:
                btn = QPushButton(text)
                btn.setFixedWidth(width)
                btn.clicked.connect(lambda _=False, s=slot, m=menu: (m.close(), s()))
                row.addWidget(btn)
            top_rows.addLayout(row)
        else:
            rows = self.context_action_rows()
            self.add_context_action_row(top_rows, menu, global_pos, 0, rows[0])
            self.add_context_action_row(top_rows, menu, global_pos, 1, rows[1])
        top_action.setDefaultWidget(top_widget)
        menu.addAction(top_action)
        if not layer_change_mode:
            self.add_capture_options_row(menu)
        menu.addSeparator()
        if self.is_free_inspection():
            grouped = {"": []}
            group_order = [""]
            free_group_names = self.free_group_names()
            for name in free_group_names:
                grouped.setdefault(name, [])
                group_order.append(name)
            for layer in self.ordered_inspection_layers():
                desc = self.layer_descriptor(layer)
                group_name = str(desc.get("group_name", "") or "")
                if group_name not in grouped:
                    grouped[group_name] = []
                    group_order.append(group_name)
                grouped[group_name].append(layer)
            has_free_items = bool(free_group_names) or any(grouped.get(name) for name in grouped)
            if not has_free_items:
                self.add_menu_button(
                    menu, tr("inspection.menu.add_group"),
                    lambda: self.add_free_group(), close_menu=True, bold=True, indent=0
                )
                self.add_menu_button(
                    menu, tr("inspection.menu.add_layer"),
                    lambda: self.add_manual_layer(free_group_name=""), close_menu=True, bold=True, indent=0
                )
            direct_layers = grouped.get("", [])
            for layer in direct_layers:
                desc = self.layer_descriptor(layer)
                source = desc.get("source_name")
                self.add_layer_menu_button(
                    menu,
                    self.layer_base_name(layer),
                    source,
                    lambda s=source: self.activate_layer_by_source(s),
                    close_menu=True,
                    bold=False,
                    indent=0,
                )
            self.add_free_group_bottom_drop_button(menu, "", indent=0)
            for group_name in [name for name in group_order if name]:
                layers = grouped.get(group_name, [])
                title = group_name
                expanded = self.free_group_menu_expanded.get(group_name, True)
                self.add_free_group_menu_button(
                    menu,
                    f"{'➖' if expanded else '➕'} {title}",
                    lambda g=group_name, p=global_pos: self.toggle_free_group_menu(g, p),
                    group_name,
                    global_pos,
                    close_menu=True,
                    bold=True,
                    indent=0,
                )
                if not expanded:
                    continue
                for layer in layers:
                    desc = self.layer_descriptor(layer)
                    source = desc.get("source_name")
                    self.add_layer_menu_button(
                        menu,
                        self.layer_base_name(layer),
                        source,
                        lambda s=source: self.activate_layer_by_source(s),
                        close_menu=True,
                        bold=False,
                        indent=26,
                    )
                self.add_free_group_bottom_drop_button(menu, group_name, indent=26)
            if has_free_items:
                menu.addSeparator()
                self.add_menu_button(
                    menu, tr("inspection.menu.add_layer"),
                    lambda: self.add_manual_layer(free_group_name=""), close_menu=True, bold=True, indent=0
                )
                self.add_menu_button(
                    menu, tr("inspection.menu.add_group"),
                    lambda: self.add_free_group(), close_menu=True, bold=True, indent=0
                )
        else:
            grouped = {}
            group_order = []
            for layer in self.ordered_inspection_layers():
                desc = self.layer_descriptor(layer)
                if desc.get("geom_type") != "polygon":
                    continue
                round_no = int(desc.get("round_no", 0) or 0)
                if round_no not in grouped:
                    grouped[round_no] = []
                    group_order.append(round_no)
                grouped[round_no].append(layer)
            for round_no in group_order:
                title = tr("inspection.menu.manual_layers") if round_no == 0 else tr("inspection.menu.round_title").format(round=round_no)
                expanded = self.round_menu_expanded.get(round_no, True)
                self.add_menu_button(
                    menu,
                    f"{'➖' if expanded else '➕'} {title}",
                    lambda r=round_no, p=global_pos: self.toggle_round_menu(r, p),
                    close_menu=True,
                    bold=True,
                    indent=0,
                )
                if not expanded:
                    continue
                for layer in grouped[round_no]:
                    desc = self.layer_descriptor(layer)
                    source = desc.get("source_name")
                    self.add_layer_menu_button(
                        menu,
                        self.layer_base_name(layer),
                        source,
                        lambda s=source: self.activate_layer_by_source(s),
                        close_menu=True,
                        bold=False,
                        indent=26,
                    )
                self.add_round_bottom_drop_button(menu, round_no, indent=26)

    def refresh_context_menu(self, menu, global_pos):
        if menu:
            menu.clear()
            self.populate_context_menu(menu, global_pos)
            menu.update()
            return
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def add_capture_options_row(self, menu):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 1, 4, 1)
        chk = QCheckBox(tr("inspection.menu.continuous"))
        chk.setToolTip(tr("inspection.menu.continuous_tooltip"))
        chk.setChecked(self.continuous_capture_enabled)
        chk.toggled.connect(self.set_continuous_capture)
        layout.addWidget(chk)
        group = QButtonGroup(widget)
        group.setExclusive(True)
        for key, text in [
            ("polygon", tr("inspection.menu.shape_polygon")),
            ("rectangle", tr("inspection.menu.shape_rectangle")),
            ("ellipse", tr("inspection.menu.shape_ellipse")),
            ("circle", tr("inspection.menu.shape_circle")),
        ]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(self.active_capture_shape == key)
            btn.setFixedWidth(38)
            btn.setStyleSheet(
                "QPushButton{padding:2px 3px;}"
                "QPushButton:checked{background:#2d8cff;color:white;font-weight:bold;}"
            )
            btn.clicked.connect(lambda _=False, k=key: self.set_capture_shape(k))
            group.addButton(btn)
            layout.addWidget(btn)
        layout.addStretch()
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_menu_button(self, menu, text, callback, close_menu=True, bold=False, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 1, 4, 1)
        button = QPushButton(text)
        button.setFlat(True)
        button.setMinimumWidth(170)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:3px 6px;color:#202020;}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_group_menu_button(self, menu, text, callback, group_name, menu_pos, close_menu=True, bold=False, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_group_bottom__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        widget.setProperty("inspection_group_name", group_name or "")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 1, 4, 1)
        button = InspectionGroupMenuButton(text, self, group_name, menu, menu_pos, widget)
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setProperty("inspection_drop_target", target)
        button.setProperty("inspection_group_name", group_name or "")
        base_style = (
            "QPushButton{border:none;text-align:left;padding:3px 6px;color:#202020;}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_layer_menu_button(self, menu, text, source_name, callback, close_menu=True, bold=False, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        widget.setProperty("inspection_source", source_name)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 1, 4, 1)
        button = InspectionLayerMenuButton(text, self, source_name, menu, QCursor.pos(), widget)
        button.setFlat(True)
        button.setMinimumWidth(170)
        layer = self.layer_by_source(source_name)
        text_color = "#0645ad" if layer and self.is_manual_layer(layer) else "#202020"
        base_style = (
            f"QPushButton{{border:none;text-align:left;padding:3px 6px;color:{text_color};}}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_round_bottom_drop_button(self, menu, round_no, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__round_bottom__:{round_no}"
        widget.setProperty("inspection_drop_target", target)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(8)
        button.setProperty("inspection_drop_target", target)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_group_bottom_drop_button(self, menu, group_name, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_group_bottom__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(8)
        button.setProperty("inspection_drop_target", target)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def layer_source_at_global_pos(self, global_pos):
        source, _button = self.layer_button_at_global_pos(global_pos)
        return source

    def layer_button_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            drop_target = widget.property("inspection_drop_target")
            if drop_target:
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_drop_target") == drop_target:
                        button = child
                return drop_target, button
            source = widget.property("inspection_source")
            if source:
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_source") == source:
                        button = child
                if button:
                    local_pos = button.mapFromGlobal(global_pos)
                    if local_pos.y() > button.height() / 2:
                        return f"__after__:{source}", button
                return source, button
            widget = widget.parentWidget()
        return "", None

    def free_group_drop_target_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            group_name = widget.property("inspection_group_name")
            if group_name is not None:
                group_name = str(group_name or "").strip()
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_group_name") is not None:
                        button = child
                if button:
                    local_pos = button.mapFromGlobal(global_pos)
                    position = "after" if local_pos.y() > button.height() / 2 else "before"
                    return group_name, position, button
            widget = widget.parentWidget()
        return "", "", None

    def clear_free_group_drag_highlight(self):
        if self.group_drag_highlight_button:
            base_style = self.group_drag_highlight_button.property("base_style")
            if base_style:
                self.group_drag_highlight_button.setStyleSheet(base_style)
        self.group_drag_highlight_button = None
        self.group_drag_highlight_target = ""

    def clear_free_group_drag_visual(self):
        self.clear_free_group_drag_highlight()
        if self.group_drag_source_button:
            base_style = self.group_drag_source_button.property("base_style")
            if base_style:
                self.group_drag_source_button.setStyleSheet(base_style)
        self.group_drag_source_button = None
        if self.group_drag_preview_label:
            self.group_drag_preview_label.hide()

    def update_free_group_drag_target(self, group_name, global_pos, source_button=None):
        group_name = str(group_name or "").strip()
        if not group_name:
            return
        if source_button and source_button is not self.group_drag_source_button:
            if self.group_drag_source_button:
                base_style = self.group_drag_source_button.property("base_style")
                if base_style:
                    self.group_drag_source_button.setStyleSheet(base_style)
            self.group_drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;text-align:left;padding:3px 6px;"
                "background:#f3f4f6;color:#8a8f98;font-weight:bold;}"
            )
        self.update_free_group_drag_preview(group_name, global_pos)
        target_group, position, button = self.free_group_drop_target_at_global_pos(global_pos)
        if not target_group or target_group == group_name:
            target_key = ""
            button = None
        else:
            target_key = f"{position}:{target_group}"
        if button is self.group_drag_highlight_button and target_key == self.group_drag_highlight_target:
            return
        self.clear_free_group_drag_highlight()
        if not target_key or not button:
            return
        base_style = button.property("base_style") or "QPushButton{border:none;text-align:left;padding:3px 6px;color:#202020;}"
        line_side = "border-bottom" if position == "after" else "border-top"
        button.setStyleSheet(
            str(base_style).replace("border:none;", f"border:none;{line_side}:3px solid #1456d9;")
        )
        self.group_drag_highlight_button = button
        self.group_drag_highlight_target = target_key
        side_label = "下" if position == "after" else "上"
        self.set_status(f"グループ移動先: {self.free_group_title(target_group)} の{side_label}")

    def update_free_group_drag_preview(self, group_name, global_pos):
        label_text = self.free_group_title(group_name)
        if not self.group_drag_preview_label:
            self.group_drag_preview_label = QLabel()
            try:
                self.group_drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.group_drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.group_drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.group_drag_preview_label.setText(label_text)
        self.group_drag_preview_label.adjustSize()
        self.group_drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.group_drag_preview_label.show()

    def clear_layer_drag_highlight(self):
        if self.drag_highlight_button:
            base_style = self.drag_highlight_button.property("base_style")
            if base_style:
                self.drag_highlight_button.setStyleSheet(base_style)
        self.drag_highlight_button = None
        self.drag_highlight_target = ""

    def clear_layer_drag_visual(self):
        self.clear_layer_drag_highlight()
        if self.drag_source_button:
            base_style = self.drag_source_button.property("base_style")
            if base_style:
                self.drag_source_button.setStyleSheet(base_style)
        self.drag_source_button = None
        if self.drag_preview_label:
            self.drag_preview_label.hide()

    def update_layer_drag_target(self, source_name, global_pos, source_button=None):
        if source_button and source_button is not self.drag_source_button:
            if self.drag_source_button:
                base_style = self.drag_source_button.property("base_style")
                if base_style:
                    self.drag_source_button.setStyleSheet(base_style)
            self.drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;text-align:left;padding:3px 6px;"
                "background:#f3f4f6;color:#8a8f98;}"
            )
        self.update_layer_drag_preview(source_name, global_pos)
        target_source, button = self.layer_button_at_global_pos(global_pos)
        if target_source == source_name or target_source == f"__after__:{source_name}":
            target_source = ""
            button = None
        if button is self.drag_highlight_button and target_source == self.drag_highlight_target:
            return
        self.clear_layer_drag_highlight()
        if not target_source or not button:
            return
        base_style = button.property("base_style") or "QPushButton{border:none;text-align:left;padding:3px 6px;color:#202020;}"
        line_side = "border-bottom" if self.is_after_drop_target(target_source) or self.is_round_bottom_drop_target(target_source) or self.is_free_group_bottom_drop_target(target_source) else "border-top"
        button.setStyleSheet(
            str(base_style).replace("border:none;", f"border:none;{line_side}:3px solid #1456d9;")
        )
        self.drag_highlight_button = button
        self.drag_highlight_target = target_source
        if target_source.startswith("__round_bottom__:"):
            round_no = self.round_no_from_drop_target(target_source)
            self.set_status(f"移動先: {self.round_title(round_no)} の一番下")
        elif target_source.startswith("__free_group_bottom__:"):
            group_name = self.group_name_from_drop_target(target_source)
            self.set_status(f"移動先: {self.free_group_title(group_name)} の一番下")
        elif self.is_after_drop_target(target_source):
            layer = self.layer_by_source(self.source_from_after_drop_target(target_source))
            if layer:
                self.set_status(f"移動先: {self.display_layer_name(layer)} の下")
        else:
            layer = self.layer_by_source(target_source)
            if layer:
                self.set_status(f"移動先: {self.display_layer_name(layer)} の上")

    def round_title(self, round_no):
        return "手動レイヤ" if round_no == 0 else f"{round_no}回目検査"

    def round_no_from_drop_target(self, target_source):
        try:
            return int(str(target_source).split(":", 1)[1])
        except Exception:
            return None

    def is_round_bottom_drop_target(self, target_source):
        return str(target_source).startswith("__round_bottom__:")

    def is_free_group_bottom_drop_target(self, target_source):
        return str(target_source).startswith("__free_group_bottom__:")

    def group_name_from_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_free_group_bottom_drop_target(target_source) else ""

    def free_group_title(self, group_name):
        return group_name if group_name else "自由式検査直下"

    def is_after_drop_target(self, target_source):
        return str(target_source).startswith("__after__:")

    def source_from_after_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_after_drop_target(target_source) else target_source

    def is_action_slot_target(self, target_key):
        return str(target_key).startswith("__action_slot__:")

    def action_slot_from_target(self, target_key):
        if not self.is_action_slot_target(target_key):
            return None, None
        parts = str(target_key).split(":")
        try:
            return int(parts[1]), int(parts[2])
        except Exception:
            return None, None

    def action_drop_target_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            drop_target = widget.property("inspection_action_drop_target")
            if drop_target:
                button = widget if isinstance(widget, QPushButton) else None
                return str(drop_target), button
            action_key = widget.property("inspection_action_key")
            if action_key:
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_action_key") == action_key:
                        button = child
                if button:
                    local_pos = button.mapFromGlobal(global_pos)
                    row_index = button.property("inspection_action_row")
                    slot_index = button.property("inspection_action_index")
                    try:
                        row_index = int(row_index)
                        slot_index = int(slot_index)
                    except Exception:
                        row_index = 0
                        slot_index = 0
                    if local_pos.x() > button.width() / 2:
                        slot_index += 1
                    return f"__action_slot__:{row_index}:{slot_index}", button
            row_index = widget.property("inspection_action_row")
            row_len = widget.property("inspection_action_row_len")
            if row_index is not None and row_len is not None:
                try:
                    return f"__action_slot__:{int(row_index)}:{int(row_len)}", widget
                except Exception:
                    pass
            widget = widget.parentWidget()
        return "", None

    def clear_action_drag_highlight(self):
        if self.action_drag_highlight_button:
            base_style = self.action_drag_highlight_button.property("base_style")
            if base_style:
                self.action_drag_highlight_button.setStyleSheet(base_style)
        self.action_drag_highlight_button = None
        self.action_drag_highlight_target = ""

    def clear_action_drag_visual(self):
        self.clear_action_drag_highlight()
        if self.action_drag_source_button:
            base_style = self.action_drag_source_button.property("base_style")
            if base_style:
                self.action_drag_source_button.setStyleSheet(base_style)
        self.action_drag_source_button = None
        if self.action_drag_preview_label:
            self.action_drag_preview_label.hide()

    def update_action_drag_target(self, action_key, global_pos, source_button=None):
        if source_button and source_button is not self.action_drag_source_button:
            if self.action_drag_source_button:
                base_style = self.action_drag_source_button.property("base_style")
                if base_style:
                    self.action_drag_source_button.setStyleSheet(base_style)
            self.action_drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;border-radius:3px;"
                "background:#f3f4f6;color:#8a8f98;padding:3px 0;}"
            )
        self.update_action_drag_preview(action_key, global_pos)
        target_key, target_widget = self.action_drop_target_at_global_pos(global_pos)
        row_index, slot_index = self.action_slot_from_target(target_key)
        rows = self.context_action_rows()
        source_row = None
        source_index = None
        for idx, row in enumerate(rows):
            if action_key in row:
                source_row = idx
                source_index = row.index(action_key)
                break
        if row_index is None or slot_index is None:
            target_key = ""
        elif source_row == row_index and (slot_index == source_index or slot_index == source_index + 1):
            target_key = ""
        if target_key == self.action_drag_highlight_target:
            return
        self.clear_action_drag_highlight()
        if not target_key:
            return
        if isinstance(target_widget, QPushButton):
            base_style = target_widget.property("base_style") or ""
            target_widget.setStyleSheet(
                "QPushButton{border-left:3px solid #1456d9;background:#e7f0ff;padding:0;}"
            )
            self.action_drag_highlight_button = target_widget
        else:
            self.action_drag_highlight_button = None
        self.action_drag_highlight_target = target_key
        self.set_status(f"ボタン移動先: {row_index + 1}行目 {slot_index + 1}番目")

    def update_action_drag_preview(self, action_key, global_pos):
        label_text = self.context_action_definitions().get(action_key, (action_key, None, ""))[0]
        if not self.action_drag_preview_label:
            self.action_drag_preview_label = QLabel()
            try:
                self.action_drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.action_drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.action_drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.action_drag_preview_label.setText(label_text)
        self.action_drag_preview_label.adjustSize()
        self.action_drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.action_drag_preview_label.show()

    def handle_action_button_drop(self, action_key, target_key, menu_pos, menu=None):
        row_index, slot_index = self.action_slot_from_target(target_key)
        if row_index is None or slot_index is None:
            self.refresh_context_menu(menu, menu_pos)
            return
        if action_key not in CONTEXT_ACTION_DEFAULT_ORDER or row_index not in (0, 1):
            self.refresh_context_menu(menu, menu_pos)
            return
        rows = self.context_action_rows()
        source_row = None
        source_index = None
        for idx, row in enumerate(rows):
            if action_key in row:
                source_row = idx
                source_index = row.index(action_key)
                break
        if source_row is not None:
            rows[source_row].remove(action_key)
        if source_row == row_index and source_index is not None and source_index < slot_index:
            slot_index -= 1
        slot_index = max(0, min(slot_index, len(rows[row_index])))
        rows[row_index].insert(slot_index, action_key)
        self.save_context_action_rows(rows)
        self.set_status("✅ 右クリックボタン配置を保存しました")
        self.refresh_context_menu(menu, menu_pos)

    def update_layer_drag_preview(self, source_name, global_pos):
        layer = self.layer_by_source(source_name)
        label_text = self.layer_base_name(layer) if layer else source_name
        if not self.drag_preview_label:
            self.drag_preview_label = QLabel()
            try:
                self.drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.drag_preview_label.setText(label_text)
        self.drag_preview_label.adjustSize()
        self.drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.drag_preview_label.show()

    def show_layer_management_menu(self, source_name, global_pos, return_pos=None):
        layer = self.layer_by_source(source_name)
        if not layer:
            return
        menu = QMenu()
        title_action = menu.addAction(self.layer_base_name(layer))
        title_action.setEnabled(False)
        menu.addSeparator()
        add_action = menu.addAction(tr("inspection.btn.layer_add"))
        add_action.triggered.connect(lambda _=False, s=source_name: self.add_manual_layer(insert_above_source=s))
        import_action = menu.addAction(tr("inspection.btn.vector_import"))
        import_action.triggered.connect(lambda _=False, s=source_name: self.import_vector_layers(insert_above_source=s))
        rename_action = menu.addAction(tr("inspection.menu.layer_rename"))
        rename_action.triggered.connect(lambda _=False, l=layer: self.rename_inspection_item(l))
        color_action = menu.addAction(tr("inspection.menu.color"))
        color_action.triggered.connect(lambda _=False, l=layer: self.change_inspection_color(l))
        size_action = menu.addAction(tr("inspection.menu.size"))
        size_action.triggered.connect(lambda _=False, l=layer: self.change_layer_size(l))
        delete_action = menu.addAction(tr("inspection.btn.manual_delete"))
        delete_action.setEnabled(self.is_manual_layer(layer))
        delete_action.triggered.connect(lambda _=False, l=layer: self.delete_manual_layer(l))
        menu.exec(global_pos)
        if return_pos:
            QTimer.singleShot(0, lambda: self.show_context_menu(return_pos))

    def show_free_group_management_menu(self, group_name, global_pos, return_pos=None):
        if not self.is_free_inspection():
            return
        menu = QMenu()
        title_action = menu.addAction(self.free_group_title(group_name))
        title_action.setEnabled(False)
        menu.addSeparator()
        add_action = menu.addAction(tr("inspection.btn.layer_add"))
        add_action.triggered.connect(lambda _=False, g=group_name: self.add_manual_layer(free_group_name=g))
        rename_action = menu.addAction(tr("inspection.menu.group_rename"))
        rename_action.triggered.connect(lambda _=False, g=group_name: self.rename_free_group(g))
        delete_action = menu.addAction(tr("inspection.menu.group_delete"))
        delete_action.triggered.connect(lambda _=False, g=group_name: self.delete_free_group(g))
        menu.exec(global_pos)
        if return_pos:
            QTimer.singleShot(0, lambda: self.show_context_menu(return_pos))

    def handle_free_group_button_drop(self, source_group, target_group, position, menu_pos, menu=None):
        source_group = str(source_group or "").strip()
        target_group = str(target_group or "").strip()
        position = "after" if position == "after" else "before"
        if not source_group or not target_group or source_group == target_group:
            self.refresh_context_menu(menu, menu_pos)
            return
        groups = self.free_group_names()
        if source_group not in groups or target_group not in groups:
            self.refresh_context_menu(menu, menu_pos)
            return
        groups = [name for name in groups if name != source_group]
        target_index = groups.index(target_group)
        if position == "after":
            target_index += 1
        groups.insert(target_index, source_group)
        self.free_groups = groups
        self.reorder_free_group_layer_tree()
        self.refresh_counts()
        side_label = "下" if position == "after" else "上"
        self.set_status(f"✅ グループ並び替え: {self.free_group_title(source_group)} → {self.free_group_title(target_group)} の{side_label}")
        self.refresh_context_menu(menu, menu_pos)

    def reorder_free_group_layer_tree(self):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        desired = [name for name in self.free_group_names() if name]
        if not desired:
            return
        for name in desired:
            self.ensure_direct_group(root_group, name)
        try:
            children = list(root_group.children())
        except Exception:
            return
        group_indices = []
        for index, child in enumerate(children):
            try:
                child.children()
                is_group = True
            except Exception:
                is_group = False
            try:
                if is_group and child.name() in desired:
                    group_indices.append(index)
            except Exception:
                pass
        insert_index = min(group_indices) if group_indices else len(children)
        for name in desired:
            group = self.ensure_direct_group(root_group, name)
            try:
                children = list(root_group.children())
                current_index = children.index(group)
            except Exception:
                continue
            if current_index != insert_index:
                try:
                    clone = group.clone()
                    root_group.insertChildNode(insert_index, clone)
                    root_group.removeChildNode(group)
                    group = clone
                except Exception as exc:
                    QgsMessageLog.logMessage(f"自由式グループ並び替えエラー: {name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    continue
            insert_index += 1
        QApplication.processEvents()

    def handle_layer_button_drop(self, source_name, target_source, menu_pos, menu=None):
        if not target_source or source_name == target_source:
            self.refresh_context_menu(menu, menu_pos)
            return
        layer = self.layer_by_source(source_name)
        if not layer:
            self.refresh_context_menu(menu, menu_pos)
            return
        if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE:
            if self.is_free_group_bottom_drop_target(target_source):
                group_name = self.group_name_from_drop_target(target_source)
                self.set_layer_group_name(layer, group_name)
                self.active_free_group_name = group_name
                if self.place_layer_at_group_bottom(layer, self.ensure_free_group(group_name)):
                    self.refresh_counts()
                    self.set_status(f"✅ レイヤ移動: {self.free_group_title(group_name)} の一番下")
                self.refresh_context_menu(menu, menu_pos)
                return
            after_target = self.is_after_drop_target(target_source)
            if after_target:
                target_source = self.source_from_after_drop_target(target_source)
                if source_name == target_source:
                    self.refresh_context_menu(menu, menu_pos)
                    return
            target_layer = self.layer_by_source(target_source)
            if not target_layer:
                self.refresh_context_menu(menu, menu_pos)
                return
            if self.layer_inspection_type(target_layer) != INSPECTION_TYPE_FREE:
                QMessageBox.information(self, "レイヤ移動", "自由式検査レイヤは自由式検査グループ内だけで移動できます。")
                self.refresh_context_menu(menu, menu_pos)
                return
            group_name = target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")
            self.set_layer_group_name(layer, group_name)
            placed = self.place_layer_after(layer, target_layer) if after_target else self.place_layer_before(layer, target_layer)
            if placed:
                self.refresh_counts()
                self.set_status(f"✅ レイヤ並び替え: {self.display_layer_name(layer)}")
            self.refresh_context_menu(menu, menu_pos)
            return
        source_round = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        if self.is_round_bottom_drop_target(target_source):
            target_round = self.round_no_from_drop_target(target_source)
            if target_round is None:
                self.refresh_context_menu(menu, menu_pos)
                return
            if source_round != target_round:
                if not self.is_manual_layer(layer):
                    QMessageBox.information(self, "レイヤ移動", "標準検査レイヤは検査回をまたいで移動できません。")
                    self.refresh_context_menu(menu, menu_pos)
                    return
                self.set_layer_round(layer, target_round)
            if self.place_layer_at_round_bottom(layer, target_round):
                self.refresh_counts()
                self.set_status(f"✅ レイヤ移動: {self.round_title(target_round)} の一番下")
            self.refresh_context_menu(menu, menu_pos)
            return
        after_target = self.is_after_drop_target(target_source)
        if after_target:
            target_source = self.source_from_after_drop_target(target_source)
            if source_name == target_source:
                self.refresh_context_menu(menu, menu_pos)
                return
        target_layer = self.layer_by_source(target_source)
        if not layer or not target_layer:
            self.refresh_context_menu(menu, menu_pos)
            return
        if self.layer_inspection_type(target_layer) != INSPECTION_TYPE_ORTHO:
            QMessageBox.information(self, "レイヤ移動", "オルソ検査レイヤはオルソ検査グループ内だけで移動できます。")
            self.refresh_context_menu(menu, menu_pos)
            return
        target_round = int(target_layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        if source_round != target_round:
            if not self.is_manual_layer(layer):
                QMessageBox.information(self, "レイヤ移動", "標準検査レイヤは検査回をまたいで移動できません。")
                self.refresh_context_menu(menu, menu_pos)
                return
            self.set_layer_round(layer, target_round)
        placed = self.place_layer_after(layer, target_layer) if after_target else self.place_layer_before(layer, target_layer)
        if placed:
            self.refresh_counts()
            self.set_status(f"✅ レイヤ並び替え: {self.display_layer_name(layer)}")
        self.refresh_context_menu(menu, menu_pos)

    def set_continuous_capture(self, enabled):
        self.continuous_capture_enabled = enabled

    def set_capture_shape(self, shape):
        self.finish_edit_for_mode_switch()
        self.active_capture_shape = shape
        labels = {
            "polygon": "多角形",
            "rectangle": "長方形",
            "ellipse": "楕円",
            "circle": "正円",
        }
        self.set_status(f"作成形状: {labels.get(shape, shape)}")

    def toggle_round_menu(self, round_no, global_pos):
        self.round_menu_expanded[round_no] = not self.round_menu_expanded.get(round_no, True)
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def toggle_free_group_menu(self, group_name, global_pos):
        self.free_group_menu_expanded[group_name] = not self.free_group_menu_expanded.get(group_name, True)
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def show_main_menu(self, global_pos):
        self.finish_edit_for_mode_switch()
        self.operation_mode = "pan"
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def start_layer_change(self):
        self.finish_edit_for_mode_switch()
        if not self.selected_vector_targets():
            self.restart_layer_change_selection()
            return
        self.operation_mode = "layer_change"
        self.ensure_map_tool()
        self.set_status("移層: 右クリックメニューから移動先項目を選択してください")
        QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))

    def restart_layer_change_selection(self):
        self.finish_edit_for_mode_switch()
        self.operation_mode = "layer_change_select"
        self.ensure_map_tool()
        self.set_status("移層: 移動対象を再選択してください")

    def cancel_layer_change(self):
        self.switch_to_pan()

    def start_select(self):
        self.finish_edit_for_mode_switch()
        self.operation_mode = "select"
        self.ensure_map_tool()
        self.set_status("選択する検査図形をクリック、またはドラッグ選択してください")

    def start_delete(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select"):
            self.set_status("移層中です。パンで解除してください")
            return
        if self.delete_selected_features():
            return
        self.set_status("先に地物選択で削除対象を選択してください")

    def start_move(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select"):
            self.set_status("移層中です。パンで解除してください")
            return
        self.operation_mode = "move"
        self.ensure_map_tool()
        if self.selected_vector_targets():
            self.set_status("移動: 選択データをドラッグしてください")
        else:
            self.set_status("移動: 動かしたい検査データをクリックしてドラッグしてください")

    def start_edit(self):
        if self.operation_mode in ("layer_change", "layer_change_select"):
            self.set_status("移層中です。パンで解除してください")
            return
        self.clear_inspection_selection()
        self.operation_mode = "edit"
        self.ensure_map_tool()
        self.set_status("編集モード: マウス下の検査レイヤを自動で編集対象にします。右クリックで終了します")

    def start_merge(self):
        self.finish_edit_for_mode_switch()
        if self.operation_mode in ("layer_change", "layer_change_select"):
            self.set_status("移層中です。パンで解除してください")
            return
        if self.merge_selected_features():
            return
        self.set_status("先に地物選択で統合対象を選択してください")

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

    def geometry_from_shape(self, shape, point_a, point_b):
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
            if self.operation_mode == "layer_change_select":
                self.set_status("移層: 移動する検査図形を選択してください")
            else:
                self.set_status("選択解除")
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
        self.iface.setActiveLayer(layer)
        if self.operation_mode == "layer_change_select":
            self.update_map_cursor()
            self.set_status("移層: 選択中。右クリックで変更先を選択してください")
        else:
            self.set_status(f"選択: {self.display_layer_name(layer)}")
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
        if total:
            if self.operation_mode == "layer_change_select":
                self.update_map_cursor()
                self.set_status(f"移層: {total} 件選択中。右クリックで変更先を選択してください")
            else:
                self.set_status(f"選択: {total} 件")
        else:
            if self.operation_mode == "layer_change_select":
                self.set_status("移層: 移動する検査図形を選択してください")
            else:
                self.set_status("選択解除")
        return total > 0

    def clear_inspection_selection(self):
        for layer in self.selectable_inspection_layers():
            try:
                layer.removeSelection()
            except Exception:
                pass

    def delete_feature_at(self, point):
        layer, feature = self.find_feature_at(point)
        if not layer:
            self.set_status("削除対象が見つかりません")
            return
        if not self.confirm_delete_if_needed("検査図形を削除", "選択した検査図形を削除しますか？"):
            return
        self._delete_features(layer, [feature.id()])
        self.operation_mode = "create"

    def edit_feature_at(self, point):
        layer, feature = self.find_feature_at(point, tolerance_factor=12)
        if not layer:
            self.set_status("編集対象が見つかりません")
            return
        self.clear_inspection_selection()
        self._activate_vertex_edit(layer)
        self.operation_mode = "create"

    def prepare_edit_layer_at(self, point, activate_tool=True, quiet=False):
        layer, feature = self.find_feature_at(point, allow_polygon_fill=True, tolerance_factor=12)
        if not layer:
            if not quiet:
                self.set_status("編集対象が見つかりません")
            return False
        self.clear_inspection_selection()
        if not self.prepare_layer_edit(layer, activate_tool=activate_tool):
            return False
        if not quiet:
            self.set_status(f"編集モード: {self.display_layer_name(layer)}")
        return True

    def toggle_merge_feature_at(self, point):
        layer, feature = self.find_feature_at(point)
        if not layer:
            self.set_status("統合対象が見つかりません")
            return
        if layer.geometryType() not in (Qgis.GeometryType.Polygon, Qgis.GeometryType.Line):
            QMessageBox.warning(self, "統合できません", "統合はポリゴンまたはラインだけ対象です。")
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
        if len(selected) >= 2:
            self.merge_selected_features(layer)
            self.operation_mode = "create"

    def edit_memo_at(self, point):
        layer, feature = self.find_feature_at(point, allow_polygon_fill=True)
        if not layer:
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
        layer.triggerRepaint()
        layer.setLabelsEnabled(True)
        self.refresh_counts()

    def add_geometry_feature(self, layer, geometry):
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
            try:
                layer.reload()
            except Exception:
                pass
            layer.updateExtents()
            layer.triggerRepaint()
            self.refresh_counts()
            self.set_status(f"✅ 検査図形を追加: {self.layer_base_name(layer)}")
            if not self.continuous_capture_enabled:
                QTimer.singleShot(120, self.switch_to_pan)
        else:
            QMessageBox.warning(self, "追加失敗", "検査図形を追加できませんでした。")

    def now_text(self):
        return QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate)

    def selected_vector_targets(self):
        return [(l, list(l.selectedFeatureIds())) for l in self.selectable_inspection_layers() if l.selectedFeatureIds()]

    def begin_feature_move_at(self, point):
        targets = self.selected_vector_targets()
        clicked_layer, clicked_feature = self.find_feature_at(point, allow_polygon_fill=True, tolerance_factor=12)
        if clicked_layer and clicked_feature:
            clicked_selected = clicked_feature.id() in set(clicked_layer.selectedFeatureIds())
            if not targets or not clicked_selected:
                self.clear_inspection_selection()
                clicked_layer.selectByIds([clicked_feature.id()])
                self.iface.setActiveLayer(clicked_layer)
                targets = [(clicked_layer, [clicked_feature.id()])]
        if not targets:
            if not clicked_layer:
                self.set_status("移動対象が見つかりません")
                return False
        self.feature_move_targets = [(layer, list(ids)) for layer, ids in targets if layer and ids]
        total = sum(len(ids) for _layer, ids in self.feature_move_targets)
        if not total:
            self.set_status("移動対象が選択されていません")
            return False
        self.update_feature_move_preview(point, point)
        self.set_status(f"移動: {total} 件をドラッグ中")
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
            self.set_status("移動対象が選択されていません")
            return False
        now = self.now_text()
        moved = 0
        failed_layers = []
        for layer, ids in targets:
            dx, dy = self.layer_delta_from_map_points(layer, start_point, end_point)
            if abs(dx) + abs(dy) <= 0:
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
                geometry_changes[feature.id()] = geom
            if not geometry_changes:
                continue
            provider = layer.dataProvider()
            if not provider.changeGeometryValues(geometry_changes):
                failed_layers.append(self.display_layer_name(layer))
                continue
            updated_idx = layer.fields().indexOf("updated_at")
            if updated_idx >= 0:
                provider.changeAttributeValues({fid: {updated_idx: now} for fid in geometry_changes.keys()})
            layer.updateExtents()
            layer.triggerRepaint()
            moved += len(geometry_changes)
        self.clear_feature_move_preview()
        self.refresh_counts()
        self.feature_move_targets = self.selected_vector_targets()
        if failed_layers:
            QMessageBox.warning(self, "移動できません", "一部レイヤを移動できませんでした。\n" + "\n".join(failed_layers[:8]))
        if moved:
            self.set_status(f"✅ 移動: {moved} 件")
            return True
        self.set_status("移動できませんでした")
        return False

    def move_selected_to_layer(self, target_layer):
        targets = self.selected_vector_targets()
        if not targets:
            self.set_status("移動対象が選択されていません")
            self.operation_mode = "layer_change_select"
            self.ensure_map_tool()
            return False
        if any(layer.geometryType() != target_layer.geometryType() for layer, _ids in targets):
            QMessageBox.warning(self, "移層できません", "形状タイプが違うレイヤへは移動できません。")
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))
            return True
        total = sum(len(ids) for _layer, ids in targets)
        if QMessageBox.question(
            self,
            "移層",
            f"選択中の {total} 件を「{self.layer_base_name(target_layer)}」へ移動しますか？",
        ) != QMessageBox.StandardButton.Yes:
            self.operation_mode = "layer_change"
            self.ensure_map_tool()
            self.set_status("移層: 右クリックメニューから移動先項目を選択してください")
            QTimer.singleShot(0, lambda: self.show_context_menu(QCursor.pos()))
            return True
        desc = self.layer_descriptor(target_layer)
        new_features = []
        delete_map = []
        now = self.now_text()
        for layer, ids in targets:
            if layer.id() == target_layer.id():
                continue
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
                new_features.append(new_feature)
            delete_map.append((layer, ids))
        if new_features:
            target_layer.dataProvider().addFeatures(new_features)
        for layer, ids in delete_map:
            layer.dataProvider().deleteFeatures(ids)
            layer.removeSelection()
            layer.updateExtents()
            layer.triggerRepaint()
        target_layer.updateExtents()
        target_layer.triggerRepaint()
        self.active_layer_id = target_layer.id()
        self.active_geom_type = target_layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = target_layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.iface.setActiveLayer(target_layer)
        self.refresh_counts()
        self.switch_to_pan()
        self.set_status(f"✅ 移層: {self.layer_base_name(target_layer)}")
        return True

    def delete_selected_features(self):
        targets = self.selected_vector_targets()
        if not targets:
            return False
        count = sum(len(ids) for _layer, ids in targets)
        if not self.confirm_delete_if_needed("地物を削除", f"選択中の {count} 件を削除しますか？"):
            return True
        for layer, ids in targets:
            self._delete_features(layer, ids)
        return True

    def _delete_features(self, layer, ids):
        layer.dataProvider().deleteFeatures(ids)
        layer.removeSelection()
        layer.triggerRepaint()
        self.refresh_counts()
        self.set_status(f"🗑 {len(ids)} 件を削除しました")

    def edit_selected_feature(self):
        targets = self.selected_vector_targets()
        if len(targets) != 1 or len(targets[0][1]) != 1:
            return False
        self.clear_inspection_selection()
        return self._activate_vertex_edit(targets[0][0])

    def _activate_vertex_edit(self, layer):
        if not self.prepare_layer_edit(layer, activate_tool=True):
            return False
        self.set_status(f"編集モード: {self.display_layer_name(layer)}")
        return True

    def edit_layer_detail(self, layer):
        details = []
        try:
            details.append(f"provider={layer.providerType()}")
        except Exception:
            pass
        try:
            if layer.readOnly():
                details.append("readOnly=True")
        except Exception:
            pass
        try:
            if not layer.supportsEditing():
                details.append("supportsEditing=False")
        except Exception:
            pass
        try:
            provider = layer.dataProvider()
            if provider:
                details.append(f"caps={provider.capabilitiesString()}")
                try:
                    caps = provider.capabilities()
                    change_geom = Qgis.VectorProviderCapability.ChangeGeometries
                    if not caps & change_geom:
                        details.append("ChangeGeometriesなし")
                except Exception:
                    pass
        except Exception:
            pass
        return " / ".join(details) if details else "詳細不明"

    def log_edit_start_failed(self, layer, reason):
        try:
            detail = self.edit_layer_detail(layer)
            source = layer.source()
            QgsMessageLog.logMessage(
                f"INSPECTION_EDIT_START_FAILED layer={self.display_layer_name(layer)} "
                f"reason={reason} detail={detail} source={source}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        except Exception:
            pass

    def prepare_layer_edit(self, layer, activate_tool=False):
        self.active_layer_id = layer.id()
        self.active_geom_type = layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", self.layer_geom_type_key(layer))
        self.active_color = layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.set_qgis_active_edit_layer(layer)
        if not layer.isEditable():
            try:
                try:
                    if layer.readOnly():
                        layer.setReadOnly(False)
                except Exception:
                    pass
                if not layer.supportsEditing():
                    detail = self.edit_layer_detail(layer)
                    self.set_status(f"編集開始できません: {self.display_layer_name(layer)}（{detail}）")
                    self.log_edit_start_failed(layer, "supportsEditing=False")
                    return False
                started = False
                try:
                    tools = self.iface.vectorLayerTools()
                    if tools:
                        result = tools.startEditing(layer)
                        started = bool(result) or layer.isEditable()
                except Exception as exc:
                    self.log_edit_start_failed(layer, f"vectorLayerTools.startEditing例外: {exc}")
                if not started and not layer.isEditable():
                    started = bool(layer.startEditing())
                if not started and not layer.isEditable():
                    detail = self.edit_layer_detail(layer)
                    self.set_status(f"編集開始できません: {self.display_layer_name(layer)}（{detail}）")
                    self.log_edit_start_failed(layer, "startEditing=False")
                    return False
            except Exception as exc:
                self.set_status(f"編集開始できません: {self.display_layer_name(layer)}（{exc}）")
                self.log_edit_start_failed(layer, f"例外: {exc}")
                return False
        if not activate_tool:
            return True
        self.apply_edit_preview_width(layer)
        QgsMessageLog.logMessage(
            f"INSPECTION_EDIT_TARGET layer={self.display_layer_name(layer)} id={layer.id()}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        QTimer.singleShot(0, lambda l=layer: self.trigger_vertex_tool(l, force_restart=True))
        return True

    def set_qgis_active_edit_layer(self, layer):
        try:
            self.iface.setActiveLayer(layer)
        except Exception:
            pass
        try:
            view = self.iface.layerTreeView()
            if view:
                view.setCurrentLayer(layer)
        except Exception:
            pass
        try:
            nodes = self.layer_tree_nodes_for_layer(layer.id())
            visible_nodes = [node for _parent, node in nodes if self.layer_tree_node_visible(node)]
            target_node = visible_nodes[0] if visible_nodes else (nodes[0][1] if nodes else None)
            if target_node is not None:
                target_node.setItemVisibilityChecked(True)
        except Exception:
            pass

    def trigger_vertex_tool(self, layer=None, force_restart=False):
        if layer is not None:
            self.set_qgis_active_edit_layer(layer)
        try:
            action = self.iface.actionVertexToolActiveLayer()
            if force_restart and action.isChecked():
                action.trigger()
                QApplication.processEvents()
            if not action.isChecked():
                action.trigger()
            return True
        except Exception:
            try:
                action = self.iface.actionVertexTool()
                if force_restart and action.isChecked():
                    action.trigger()
                    QApplication.processEvents()
                if not action.isChecked():
                    action.trigger()
                return True
            except Exception:
                pass
        return False

    def finish_edit_mode(self, defer_pan=False, switch_to_pan_after=True):
        saved = 0
        for layer in self.inspection_layers():
            try:
                if layer.isEditable():
                    if layer.commitChanges():
                        saved += 1
                    else:
                        layer.rollBack()
                layer.removeSelection()
            except Exception:
                pass
        self.restore_edit_preview_width()
        self.refresh_counts()
        if switch_to_pan_after:
            if defer_pan:
                self.operation_mode = "pan_pending"
                QTimer.singleShot(160, self.switch_to_pan)
            else:
                self.operation_mode = "pan_pending"
                self.switch_to_pan()
        self.set_status(f"編集保存完了: {saved} レイヤ")

    def merge_selected_features(self, forced_layer=None):
        targets = [(forced_layer, list(forced_layer.selectedFeatureIds()))] if forced_layer else self.selected_vector_targets()
        targets = [(layer, ids) for layer, ids in targets if layer and ids]
        total_count = sum(len(ids) for _layer, ids in targets)
        if total_count < 2:
            return False
        geometry_types = {layer.geometryType() for layer, _ids in targets}
        if len(geometry_types) != 1 or next(iter(geometry_types)) not in (Qgis.GeometryType.Polygon, Qgis.GeometryType.Line):
            QMessageBox.warning(self, "統合できません", "統合は同じ種類のポリゴンまたはラインだけ対象です。")
            return True
        geometry_type = next(iter(geometry_types))
        is_line_merge = geometry_type == Qgis.GeometryType.Line
        feature_label = "ライン" if is_line_merge else "ポリゴン"
        target_layer = self.choose_merge_target_layer([layer for layer, _ids in targets], geometry_type)
        if not target_layer:
            return True
        features, geoms = self.collect_merge_features(targets, target_layer)
        if len(features) != total_count or len(geoms) != total_count:
            QMessageBox.warning(self, "統合できません", f"選択した{feature_label}を正しく取得できませんでした。")
            return True
        if is_line_merge:
            geom = self.build_single_line_merge_geometry(geoms)
            if not geom:
                QMessageBox.warning(
                    self,
                    "統合できません",
                    "端点がつながっているラインだけ統合できます。\n離れているライン、分岐するライン、複数線になる形状は保存しません。",
                )
                return True
        elif not self.merge_geometries_have_area_overlap(geoms):
            QMessageBox.warning(
                self,
                "統合できません",
                "面で重なっているポリゴンだけ統合できます。\n離れている、または辺だけ接しているポリゴンは統合できません。",
            )
            return True
        else:
            geom = self.build_single_merge_geometry(geoms)
            if not geom:
                QMessageBox.warning(
                    self,
                    "統合できません",
                    "統合後の形状が単一ポリゴンになりませんでした。\n離れた形状や不正な形状は保存しません。",
                )
                return True
        if QMessageBox.question(
            self,
            f"{feature_label}統合",
            f"{total_count} 件の{feature_label}を統合し、統合後レイヤ「{self.display_layer_name(target_layer)}」へ保存しますか？",
        ) != QMessageBox.StandardButton.Yes:
            return True
        new_feature = self.build_merge_feature(target_layer, features, geom)
        if not self.apply_merge_edits(target_layer, targets, new_feature, feature_label):
            return True
        for layer, _ids in targets:
            layer.removeSelection()
            layer.updateExtents()
            layer.triggerRepaint()
            try:
                layer.reload()
            except Exception:
                pass
        target_layer.updateExtents()
        target_layer.triggerRepaint()
        try:
            target_layer.reload()
        except Exception:
            pass
        self.active_layer_id = target_layer.id()
        self.active_geom_type = target_layer.customProperty(INSPECTION_PROP_PREFIX + "geom_type", "polygon")
        self.active_color = target_layer.customProperty(INSPECTION_PROP_PREFIX + "color", "ff0000")
        self.iface.setActiveLayer(target_layer)
        self.refresh_counts()
        self.set_status(f"✅ {feature_label}を統合しました")
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
        started = []
        commanded = []
        try:
            for layer in involved:
                if not layer.isEditable():
                    if not layer.startEditing():
                        QMessageBox.warning(self, "統合できません", f"レイヤを編集状態にできませんでした。\n{self.display_layer_name(layer)}")
                        return False
                    started.append(layer)
                layer.beginEditCommand(f"{feature_label}統合")
                commanded.append(layer)
            if not target_layer.addFeature(new_feature):
                QMessageBox.warning(self, "統合できません", f"統合後{feature_label}を保存できませんでした。元の{feature_label}は残しています。")
                return False
            for layer, ids in targets:
                if ids and not layer.deleteFeatures(ids):
                    QMessageBox.warning(self, "統合できません", f"元{feature_label}を削除できませんでした。\n{self.display_layer_name(layer)}")
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
                    "統合保存エラー",
                    "統合の保存でエラーが出ました。\n" + "\n".join(commit_errors),
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
        candidate_layers = [layer for layer in self.selectable_inspection_layers() if layer.geometryType() == geometry_type]
        if not candidate_layers:
            return None
        labels = [self.display_layer_name(layer) for layer in candidate_layers]
        label, ok = QInputDialog.getItem(self, "統合後レイヤ選択", "統合後の保存先レイヤ:", labels, 0, False)
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
            QMessageBox.information(self, "検査書出", "書き出す検査データがありません。")
            return
        dialog = InspectionExportDialog(self, layers, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_layers()
        if not selected:
            QMessageBox.information(self, "検査書出", "データがあるレイヤが選択されていません。")
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
            QMessageBox.warning(self, "SHP書き出し", "\n".join(errors))
        else:
            self.set_status(f"✅ SHP書き出し完了: {len(layers)} レイヤ")

    def export_shp_merged(self, layers, folder):
        if not OGR_OK:
            QMessageBox.critical(self, "SHP書き出し", "GDAL/OGRを読み込めないためSHPを書き出せません。")
            return
        geom_types = self.selected_geom_type_keys(layers)
        if len(geom_types) != 1:
            labels = "、".join(GEOM_TYPE_LABELS.get(key, key) for key in sorted(geom_types))
            QMessageBox.warning(
                self,
                "SHP書き出し",
                f"1つのSHPには同じ図形タイプだけ出力できます。\n選択データには {labels} が混在しているため、1つのSHPにまとめられません。\n「レイヤごとにSHP作成」を選んでください。",
            )
            return
        geom_type = next(iter(geom_types))
        suffix = {"polygon": "polygon", "line": "line", "point": "point"}.get(geom_type, "polygon")
        out_path = os.path.join(folder, f"inspection_{suffix}.shp")
        self._delete_shapefile_set(out_path)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.CreateDataSource(out_path)
        if ds is None:
            QMessageBox.critical(self, "SHP書き出し", "SHPを作成できませんでした。")
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
            QMessageBox.warning(self, "SHP書き出し", "\n".join(errors[:20]))
        else:
            self.set_status(f"✅ SHP書き出し完了: 1 ファイル（{count} 件）")

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
            self.set_status(f"✅ DXF（R12）書き出し完了: 1 ファイル（{len(layers)} レイヤ）")

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
            QMessageBox.warning(self, "DXF（R12）書き出し", "書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20]))
        else:
            self.set_status(f"✅ DXF（R12）書き出し完了: {written} ファイル")




    def export_test_dxf(self, layers, path):
        if self._write_test_dxf(layers, path):
            self.set_status(f"✅ DXF（AutoCAD 2000系）書き出し完了: 1 ファイル（{len(layers)} レイヤ）")

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
            QMessageBox.warning(self, "DXF（AutoCAD 2000系）書き出し", "書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20]))
        else:
            self.set_status(f"✅ DXF（AutoCAD 2000系）書き出し完了: {written} ファイル")

    def _write_test_dxf(self, layers, path):
        return self._write_ogr_dxf(layers, path)

    def _write_ogr_dxf(self, layers, path):
        title = "DXF（AutoCAD 2000系）書き出し"
        if not OGR_OK:
            QMessageBox.critical(self, title, "GDAL/OGRを読み込めないためDXFを書き出せません。")
            return False
        driver = ogr.GetDriverByName("DXF")
        if driver is None:
            QMessageBox.critical(self, title, "このQGIS環境ではDXF書き出しドライバが使えません。")
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
            gdal.SetConfigOption("DXF_WRITE_HATCH", "FALSE")
            ds = driver.CreateDataSource(path)
            if ds is None:
                QMessageBox.critical(self, title, "DXFを作成できませんでした。")
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
            QMessageBox.critical(self, title, f"DXFを書き出せませんでした。\n{exc}")
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
            QMessageBox.critical(self, error_title, f"DXFを書き出せませんでした。\n{exc}")
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
            self.set_status(f"✅ {label}書き出し完了: 1 ファイル（{len(layers)} レイヤ）")

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
            QMessageBox.warning(self, f"{label}書き出し", "書き出しに失敗したレイヤがあります。\n" + "\n".join(errors[:20]))
        else:
            self.set_status(f"✅ {label}書き出し完了: {written} ファイル")

    def _write_dgn(self, layers, path, legacy=False):
        label = "DGN V7" if legacy else "DGN V8/2004以降"
        if not OGR_OK:
            QMessageBox.critical(self, f"{label}書き出し", "GDAL/OGRを読み込めないためDGNを書き出せません。")
            return False
        driver_name = "DGN" if legacy else "DGNv8"
        driver = ogr.GetDriverByName(driver_name)
        if driver is None:
            if legacy:
                QMessageBox.critical(self, "DGN V7書き出し", "このQGIS環境ではDGN V7書き出しドライバが使えません。")
            else:
                QMessageBox.critical(
                    self,
                    "DGN V8/2004以降 書き出し",
                    "このQGIS環境にはDGN V8/2004以降を書き出すDGNv8ドライバがありません。\n"
                    "標準のQGIS/GDALではDGN V7だけが作成可能です。\n"
                    "DXF（R12）またはDGN V7を使ってください。",
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
                QMessageBox.critical(self, f"{label}書き出し", f"{label}を作成できませんでした。")
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
            QMessageBox.critical(self, f"{label}書き出し", f"{label}を書き出せませんでした。\n{exc}")
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
        return {
            "version": 2,
            "gpkg_path": self.gpkg_path,
            "inspection_type": self.active_inspection_type,
            "last_free_geom_type": self.last_free_geom_type,
            "free_groups": self.free_group_names(),
            "layers": [self.layer_descriptor(layer) for layer in self.inspection_layers()],
        }

    def restore_state(self, state):
        if not isinstance(state, dict):
            return
        self.layers.clear()
        inspection_type = state.get("inspection_type", INSPECTION_TYPE_ORTHO)
        self.active_inspection_type = inspection_type if inspection_type in (INSPECTION_TYPE_ORTHO, INSPECTION_TYPE_FREE) else INSPECTION_TYPE_ORTHO
        self.last_free_geom_type = state.get("last_free_geom_type", "line") or "line"
        self.free_groups = [str(name).strip() for name in state.get("free_groups", []) if str(name).strip()]
        for layer in self.inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if source:
                self.layers[source] = {**self.layer_descriptor(layer), "layer_id": layer.id()}
        path = state.get("gpkg_path", "")
        if path and not os.path.exists(path):
            alt = os.path.join(self.project_home(), os.path.basename(path)) if self.project_home() else ""
            if alt and os.path.exists(alt):
                path = alt
        self.gpkg_path = path if path else ""
        descriptors = {d.get("source_name"): d for d in state.get("layers", []) if isinstance(d, dict)}
        if self.gpkg_path and os.path.exists(self.gpkg_path):
            for source, descriptor in descriptors.items():
                self.load_layer(source, descriptor)
            if not descriptors:
                self.load_layers_from_gpkg()
        for group_name in self.free_group_names():
            self.ensure_free_group(group_name)
        self.refresh_ui()

    def clear_inspection_state(self, remove_layers=True):
        if remove_layers:
            for layer in list(self.inspection_layers()):
                QgsProject.instance().removeMapLayer(layer.id())
        self.layers.clear()
        self.free_groups.clear()
        self.active_layer_id = ""
        self.gpkg_path = ""
        self.operation_mode = "create"
        self.refresh_ui()

    def cleanup_before_unload(self):
        self.restore_selection_color()
        try:
            if self.map_tool and self.iface.mapCanvas().mapTool() == self.map_tool:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
        except Exception:
            pass
        self.map_tool = None










