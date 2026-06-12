from .i18n import tr_text
import math

from qgis.PyQt.QtCore import QRect, Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication, QPushButton, QRubberBand
from qgis.core import QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsProject, QgsRectangle, QgsVectorLayer, Qgis
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker, QgsSnapIndicator

from .inspection_constants import INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE


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
        self.drag_enabled = False
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
        if self.drag_enabled and self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
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
        if self.drag_enabled and event.button() == Qt.MouseButton.LeftButton and self.dragging:
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
        self.drag_enabled = False
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
        if self.drag_enabled and self.group_name and self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
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
        if self.drag_enabled and event.button() == Qt.MouseButton.LeftButton and self.dragging:
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
        self.select_polygon_points = []
        self.select_polygon_band = None
        self.select_polygon_markers = []
        self.select_polygon_modifiers = Qt.KeyboardModifier.NoModifier
        self.shape_start_point = None
        self.shape_start_pixel = None
        self.last_shape_preview_pixel = None
        self.move_start_point = None
        self.move_start_pixel = None
        self.move_dragging = False
        self.edit_vertex_start_point = None
        self.edit_vertex_start_pixel = None
        self.edit_vertex_dragging = False
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.snap_indicator.setVisible(False)
        self.fixed_angle_90_reference_point = None
        self.fixed_angle_90_reference_marker = None
        self.fixed_angle_90_reference_band = None
        self.fixed_angle_90_reference_line_direction = None
        self.fixed_angle_90_constraint_enabled = True
        self.fixed_angle_90_copied_length = None
        self.fixed_angle_90_length_band = None
        self.parallel_direction_unit = None
        self.parallel_direction_band = None
        self.angle_copy_small_radians = None
        self.angle_copy_vertex = None
        self.angle_copy_unit_a = None
        self.angle_copy_unit_b = None
        self.angle_copy_band = None
        self.pressed_hold_shortcut_keys = set()

    def deactivate(self):
        self._clear_rubber_band()
        self._clear_select_band()
        self._clear_select_polygon()
        self._clear_move_state()
        self._clear_direct_vertex_state()
        self._clear_fixed_angle_90_reference()
        self._clear_fixed_angle_90_length_copy()
        self._clear_parallel_direction_copy()
        self._clear_angle_copy()
        self.fixed_angle_90_constraint_enabled = True
        self.pressed_hold_shortcut_keys.clear()
        try:
            self.tab.clear_direct_overlap_vertex_edit()
        except Exception:
            pass
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

    def _clear_direct_vertex_state(self):
        self.edit_vertex_start_point = None
        self.edit_vertex_start_pixel = None
        self.edit_vertex_dragging = False

    def _clear_capture_state(self):
        self._clear_rubber_band()
        self._clear_vertex_markers()
        self._clear_fixed_angle_90_reference()
        self._clear_fixed_angle_90_length_copy()
        self._clear_parallel_direction_copy()
        self._clear_angle_copy()
        self.fixed_angle_90_constraint_enabled = True
        self.pressed_hold_shortcut_keys.clear()
        self.points = []
        self.shape_start_point = None
        self.shape_start_pixel = None
        self.last_shape_preview_pixel = None

    def _clear_vertex_markers(self):
        for marker in self.vertex_markers:
            try:
                self.canvas.scene().removeItem(marker)
            except Exception:
                pass
        self.vertex_markers = []

    def _clear_fixed_angle_90_reference(self):
        if self.fixed_angle_90_reference_marker:
            try:
                self.canvas.scene().removeItem(self.fixed_angle_90_reference_marker)
            except Exception:
                pass
        if self.fixed_angle_90_reference_band:
            try:
                self.canvas.scene().removeItem(self.fixed_angle_90_reference_band)
            except Exception:
                pass
        self.fixed_angle_90_reference_marker = None
        self.fixed_angle_90_reference_band = None
        self.fixed_angle_90_reference_point = None
        self.fixed_angle_90_reference_line_direction = None

    def _clear_fixed_angle_90_length_copy(self):
        if self.fixed_angle_90_length_band:
            try:
                self.canvas.scene().removeItem(self.fixed_angle_90_length_band)
            except Exception:
                pass
        self.fixed_angle_90_length_band = None
        self.fixed_angle_90_copied_length = None

    def _clear_parallel_direction_copy(self):
        if self.parallel_direction_band:
            try:
                self.canvas.scene().removeItem(self.parallel_direction_band)
            except Exception:
                pass
        self.parallel_direction_band = None
        self.parallel_direction_unit = None

    def _clear_angle_copy(self):
        if self.angle_copy_band:
            try:
                self.canvas.scene().removeItem(self.angle_copy_band)
            except Exception:
                pass
        self.angle_copy_band = None
        self.angle_copy_small_radians = None
        self.angle_copy_vertex = None
        self.angle_copy_unit_a = None
        self.angle_copy_unit_b = None

    def _set_fixed_angle_90_reference(self, point):
        self._clear_parallel_direction_copy()
        self._clear_fixed_angle_90_reference()
        point = self._fixed_angle_90_reference_snap_point(point)
        self.fixed_angle_90_reference_point = QgsPointXY(point)
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(QgsPointXY(point))
        marker.setColor(QColor("#00bcd4"))
        marker.setIconSize(14)
        marker.setPenWidth(4)
        try:
            marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        except Exception:
            try:
                marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
            except Exception:
                pass
        try:
            marker.setZValue(1200)
        except Exception:
            pass
        self.fixed_angle_90_reference_marker = marker
        if len(self.points) >= 2:
            previous_unit = self._fixed_angle_90_unit(self._fixed_angle_90_vector(self.points[-2], self.points[-1]))
            if previous_unit is not None:
                self._update_fixed_angle_90_reference_line(previous_unit)
        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 参照点を指定しました。次の点を整列します"))

    def _fixed_angle_90_reference_snap_point(self, point):
        if not self.points:
            return QgsPointXY(point)
        try:
            tolerance = max(float(self.canvas.mapUnitsPerPixel()) * 14.0, 1e-9)
        except Exception:
            tolerance = 1e-9
        raw = QgsPointXY(point)
        nearest = None
        nearest_distance = None
        for candidate in self.points:
            distance = self._fixed_angle_90_length(self._fixed_angle_90_vector(raw, candidate))
            if nearest_distance is None or distance < nearest_distance:
                nearest = QgsPointXY(candidate)
                nearest_distance = distance
        if nearest is not None and nearest_distance is not None and nearest_distance <= tolerance:
            return nearest
        return raw

    def _update_fixed_angle_90_reference_line(self, direction):
        if self.fixed_angle_90_reference_point is None or direction is None:
            return
        self.fixed_angle_90_reference_line_direction = direction
        reference = QgsPointXY(self.fixed_angle_90_reference_point)
        try:
            extent = self.canvas.extent()
            length = max(extent.width(), extent.height()) * 2.0
        except Exception:
            length = 1000.0
        if length <= 0:
            length = 1000.0
        start = QgsPointXY(reference.x() - direction[0] * length, reference.y() - direction[1] * length)
        end = QgsPointXY(reference.x() + direction[0] * length, reference.y() + direction[1] * length)
        if self.fixed_angle_90_reference_band is None:
            self.fixed_angle_90_reference_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
            color = QColor("#00bcd4")
            color.setAlpha(210)
            try:
                self.fixed_angle_90_reference_band.setStrokeColor(color)
            except Exception:
                self.fixed_angle_90_reference_band.setColor(color)
            self.fixed_angle_90_reference_band.setWidth(2)
            try:
                self.fixed_angle_90_reference_band.setLineStyle(Qt.PenStyle.DashLine)
            except Exception:
                pass
        try:
            self.fixed_angle_90_reference_band.reset(Qgis.GeometryType.Line)
            self.fixed_angle_90_reference_band.addPoint(start, False)
            self.fixed_angle_90_reference_band.addPoint(end, True)
            self.fixed_angle_90_reference_band.show()
        except Exception:
            pass

    def _aux_copy_tolerance(self):
        try:
            return max(float(self.canvas.mapUnitsPerPixel()) * 14.0, 1e-9)
        except Exception:
            return 1e-9

    def _visible_vector_aux_layers(self):
        layers = []
        seen_ids = set()
        try:
            nodes = QgsProject.instance().layerTreeRoot().findLayers()
        except Exception:
            nodes = []
        for node in nodes:
            try:
                layer = node.layer()
            except Exception:
                layer = None
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            try:
                visible = node.itemVisibilityCheckedRecursive()
            except Exception:
                try:
                    visible = node.isVisible()
                except Exception:
                    visible = True
            if not visible or layer.id() in seen_ids:
                continue
            try:
                if layer.geometryType() not in (Qgis.GeometryType.Line, Qgis.GeometryType.Polygon):
                    continue
            except Exception:
                continue
            seen_ids.add(layer.id())
            layers.append(layer)
        return layers

    def _geometry_aux_parts(self, geometry, layer):
        if not geometry:
            return []
        parts = []
        try:
            geom_type = layer.geometryType()
        except Exception:
            return parts
        try:
            if geom_type == Qgis.GeometryType.Line:
                lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
                for line in lines:
                    if line and len(line) >= 2:
                        parts.append([QgsPointXY(point) for point in line])
            elif geom_type == Qgis.GeometryType.Polygon:
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
                for polygon in polygons:
                    for ring in polygon or []:
                        if ring and len(ring) >= 3:
                            parts.append([QgsPointXY(point) for point in ring])
        except Exception:
            pass
        return parts

    def _nearest_edge_from_points(self, raw, points, tolerance, nearest=None, nearest_distance=None):
        if not points or len(points) < 2:
            return nearest, nearest_distance
        for index in range(len(points) - 1):
            start = QgsPointXY(points[index])
            end = QgsPointXY(points[index + 1])
            segment = self._fixed_angle_90_vector(start, end)
            segment_length_sq = segment[0] * segment[0] + segment[1] * segment[1]
            if segment_length_sq <= 0:
                continue
            raw_delta = self._fixed_angle_90_vector(start, raw)
            ratio = self._fixed_angle_90_dot(raw_delta, segment) / segment_length_sq
            ratio = min(1.0, max(0.0, ratio))
            closest = QgsPointXY(start.x() + segment[0] * ratio, start.y() + segment[1] * ratio)
            distance = self._fixed_angle_90_length(self._fixed_angle_90_vector(raw, closest))
            if distance > tolerance:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest = (start, end, math.sqrt(segment_length_sq))
                nearest_distance = distance
        return nearest, nearest_distance

    def _fixed_angle_90_nearest_edge(self, point):
        tolerance = self._aux_copy_tolerance()
        raw = QgsPointXY(point)
        nearest = None
        nearest_distance = None
        nearest, nearest_distance = self._nearest_edge_from_points(
            raw, self.points, tolerance, nearest=nearest, nearest_distance=nearest_distance
        )
        for layer in self._visible_vector_aux_layers():
            try:
                layer_point = self.tab.map_point_to_layer_point(layer, raw)
                rect = QgsRectangle(
                    layer_point.x() - tolerance,
                    layer_point.y() - tolerance,
                    layer_point.x() + tolerance,
                    layer_point.y() + tolerance,
                )
                request = QgsFeatureRequest().setFilterRect(rect)
            except Exception:
                continue
            for feature in layer.getFeatures(request):
                for part in self._geometry_aux_parts(feature.geometry(), layer):
                    map_part = []
                    for part_point in part:
                        try:
                            map_part.append(QgsPointXY(self.tab.layer_point_to_map_point(layer, part_point)))
                        except Exception:
                            map_part.append(QgsPointXY(part_point))
                    nearest, nearest_distance = self._nearest_edge_from_points(
                        raw, map_part, tolerance, nearest=nearest, nearest_distance=nearest_distance
                    )
        return nearest

    def _nearest_angle_vertex_from_points(self, raw, points, tolerance, closed=False, nearest=None, nearest_distance=None):
        if not points:
            return nearest, nearest_distance
        vertices = [QgsPointXY(point) for point in points]
        if len(vertices) < 3:
            return nearest, nearest_distance
        if closed and self._fixed_angle_90_same_point(vertices[0], vertices[-1]):
            vertices = vertices[:-1]
        if len(vertices) < 3:
            return nearest, nearest_distance
        indexes = range(len(vertices)) if closed else range(1, len(vertices) - 1)
        for index in indexes:
            previous = vertices[index - 1]
            vertex = vertices[index]
            next_point = vertices[(index + 1) % len(vertices)]
            unit_a = self._fixed_angle_90_unit(self._fixed_angle_90_vector(vertex, previous))
            unit_b = self._fixed_angle_90_unit(self._fixed_angle_90_vector(vertex, next_point))
            if unit_a is None or unit_b is None:
                continue
            distance = self._fixed_angle_90_length(self._fixed_angle_90_vector(raw, vertex))
            if distance > tolerance:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest = (previous, vertex, next_point, unit_a, unit_b)
                nearest_distance = distance
        return nearest, nearest_distance

    def _fixed_angle_90_nearest_angle_vertex(self, point):
        tolerance = self._aux_copy_tolerance()
        raw = QgsPointXY(point)
        nearest = None
        nearest_distance = None
        nearest, nearest_distance = self._nearest_angle_vertex_from_points(
            raw, self.points, tolerance, closed=False, nearest=nearest, nearest_distance=nearest_distance
        )
        for layer in self._visible_vector_aux_layers():
            try:
                layer_point = self.tab.map_point_to_layer_point(layer, raw)
                rect = QgsRectangle(
                    layer_point.x() - tolerance,
                    layer_point.y() - tolerance,
                    layer_point.x() + tolerance,
                    layer_point.y() + tolerance,
                )
                request = QgsFeatureRequest().setFilterRect(rect)
                closed = layer.geometryType() == Qgis.GeometryType.Polygon
            except Exception:
                continue
            for feature in layer.getFeatures(request):
                for part in self._geometry_aux_parts(feature.geometry(), layer):
                    map_part = []
                    for part_point in part:
                        try:
                            map_part.append(QgsPointXY(self.tab.layer_point_to_map_point(layer, part_point)))
                        except Exception:
                            map_part.append(QgsPointXY(part_point))
                    nearest, nearest_distance = self._nearest_angle_vertex_from_points(
                        raw, map_part, tolerance, closed=closed, nearest=nearest, nearest_distance=nearest_distance
                    )
        return nearest

    def _set_fixed_angle_90_length_copy(self, point):
        edge = self._fixed_angle_90_nearest_edge(point)
        if edge is None:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: コピーする辺を選択してください"))
            return False
        start, end, length = edge
        if length <= 0:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: コピーする辺を選択してください"))
            return False
        self._clear_fixed_angle_90_length_copy()
        self.fixed_angle_90_copied_length = length
        band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        color = QColor("#ff9800")
        color.setAlpha(230)
        try:
            band.setStrokeColor(color)
        except Exception:
            band.setColor(color)
        band.setWidth(4)
        try:
            band.setZValue(1150)
        except Exception:
            pass
        try:
            band.reset(Qgis.GeometryType.Line)
            band.addPoint(QgsPointXY(start), False)
            band.addPoint(QgsPointXY(end), True)
            band.show()
        except Exception:
            pass
        self.fixed_angle_90_length_band = band
        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 辺長をコピーしました: {length:.3f}"))
        return True

    def _set_parallel_direction_copy(self, point):
        edge = self._fixed_angle_90_nearest_edge(point)
        if edge is None:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向をコピーする辺を選択してください"))
            return False
        start, end, _length = edge
        unit = self._fixed_angle_90_unit(self._fixed_angle_90_vector(start, end))
        if unit is None:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向をコピーする辺を選択してください"))
            return False
        self._clear_fixed_angle_90_reference()
        self._clear_parallel_direction_copy()
        self.parallel_direction_unit = unit
        band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        color = QColor("#1976d2")
        color.setAlpha(230)
        try:
            band.setStrokeColor(color)
        except Exception:
            band.setColor(color)
        band.setWidth(4)
        try:
            band.setZValue(1140)
        except Exception:
            pass
        try:
            band.reset(Qgis.GeometryType.Line)
            band.addPoint(QgsPointXY(start), False)
            band.addPoint(QgsPointXY(end), True)
            band.show()
        except Exception:
            pass
        self.parallel_direction_band = band
        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向をコピーしました"))
        return True

    def _selected_angle_copy_radians(self):
        return self.angle_copy_small_radians

    def _selected_angle_copy_degrees(self):
        radians_value = self._selected_angle_copy_radians()
        if radians_value is None:
            return None
        return math.degrees(radians_value)

    def _set_angle_copy(self, point):
        angle_vertex = self._fixed_angle_90_nearest_angle_vertex(point)
        if angle_vertex is None:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 角度をコピーする角を選択してください"))
            return False
        _previous, vertex, _next_point, unit_a, unit_b = angle_vertex
        dot = max(-1.0, min(1.0, self._fixed_angle_90_dot(unit_a, unit_b)))
        small = math.acos(dot)
        if small <= 1e-9:
            self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 角度をコピーする角を選択してください"))
            return False
        self._clear_parallel_direction_copy()
        self._clear_angle_copy()
        self.angle_copy_small_radians = small
        self.angle_copy_vertex = QgsPointXY(vertex)
        self.angle_copy_unit_a = unit_a
        self.angle_copy_unit_b = unit_b
        self._update_angle_copy_arc()
        degrees = self._selected_angle_copy_degrees()
        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 角度をコピーしました: {degrees:.1f}°"))
        return True

    def _update_angle_copy_arc(self):
        if (
            self.angle_copy_vertex is None
            or self.angle_copy_unit_a is None
            or self.angle_copy_unit_b is None
            or self.angle_copy_small_radians is None
        ):
            return
        vertex = QgsPointXY(self.angle_copy_vertex)
        try:
            radius = max(float(self.canvas.mapUnitsPerPixel()) * 26.0, 1e-9)
        except Exception:
            radius = 1.0
        start_angle = math.atan2(self.angle_copy_unit_a[1], self.angle_copy_unit_a[0])
        end_angle = math.atan2(self.angle_copy_unit_b[1], self.angle_copy_unit_b[0])
        delta = (end_angle - start_angle) % (math.pi * 2.0)
        sweep = delta if delta <= math.pi else delta - (math.pi * 2.0)
        steps = max(12, int(abs(sweep) / (math.pi / 18.0)))
        if self.angle_copy_band is None:
            self.angle_copy_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
            color = QColor("#8e24aa")
            color.setAlpha(230)
            try:
                self.angle_copy_band.setStrokeColor(color)
            except Exception:
                self.angle_copy_band.setColor(color)
            self.angle_copy_band.setWidth(3)
            try:
                self.angle_copy_band.setLineStyle(Qt.PenStyle.DashLine)
            except Exception:
                pass
            try:
                self.angle_copy_band.setZValue(1160)
            except Exception:
                pass
        try:
            self.angle_copy_band.reset(Qgis.GeometryType.Line)
            for index in range(steps + 1):
                ratio = index / float(steps)
                angle = start_angle + sweep * ratio
                arc_point = QgsPointXY(
                    vertex.x() + math.cos(angle) * radius,
                    vertex.y() + math.sin(angle) * radius,
                )
                self.angle_copy_band.addPoint(arc_point, index == steps)
            self.angle_copy_band.show()
        except Exception:
            pass

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

    def _clear_select_polygon(self):
        if self.select_polygon_band:
            try:
                self.canvas.scene().removeItem(self.select_polygon_band)
            except Exception:
                pass
            self.select_polygon_band = None
        for marker in self.select_polygon_markers:
            try:
                self.canvas.scene().removeItem(marker)
            except Exception:
                pass
        self.select_polygon_markers = []
        self.select_polygon_points = []
        self.select_polygon_modifiers = Qt.KeyboardModifier.NoModifier

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

    def _snap_match(self, event, set_current_layer=True):
        try:
            utils = self.canvas.snappingUtils()
            if utils:
                if set_current_layer:
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

    def _direct_overlap_vertex_snap_point(self, event):
        try:
            if self.tab.operation_mode != "edit" or not self.tab.has_direct_overlap_vertex_edit():
                return None
            return self.tab.direct_overlap_vertex_snap_point(QgsPointXY(event.mapPoint()), event.pixelPoint())
        except Exception:
            return None

    def _event_map_point(self, event, use_snap=False, set_current_layer=True, allow_line_close=True):
        if use_snap:
            close_point = self._line_close_snap_point(event) if allow_line_close else None
            if close_point is not None:
                self._clear_snap_indicator()
                return close_point
            direct_overlap_edit = (
                self.tab.operation_mode == "edit"
                and self.tab.has_direct_overlap_vertex_edit()
            )
            match = self._snap_match(event, set_current_layer=(set_current_layer and not direct_overlap_edit))
            self._update_snap_indicator(match)
            if match and match.isValid():
                try:
                    return QgsPointXY(match.point())
                except Exception:
                    pass
            if direct_overlap_edit:
                direct_overlap_point = self._direct_overlap_vertex_snap_point(event)
                if direct_overlap_point is not None:
                    self._clear_snap_indicator()
                    return direct_overlap_point
            try:
                return QgsPointXY(event.snapPoint())
            except Exception:
                pass
        return QgsPointXY(event.mapPoint())

    def _angle_constrained_point(self, start_point, end_point, modifiers, basis_angle=None):
        if start_point is None:
            return QgsPointXY(end_point)
        start = QgsPointXY(start_point)
        end = QgsPointXY(end_point)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx == 0 and dy == 0:
            return end
        try:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                if abs(dx) >= abs(dy):
                    return QgsPointXY(end.x(), start.y())
                return QgsPointXY(start.x(), end.y())
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                degrees = self.tab.inspection_angle_snap_degrees()
                if degrees <= 0:
                    return end
                step = math.radians(float(degrees))
                if step <= 0:
                    return end
                distance = math.hypot(dx, dy)
                angle = math.atan2(dy, dx)
                if basis_angle is None:
                    snapped_angle = round(angle / step) * step
                else:
                    snapped_angle = basis_angle + round((angle - basis_angle) / step) * step
                return QgsPointXY(
                    start.x() + distance * math.cos(snapped_angle),
                    start.y() + distance * math.sin(snapped_angle),
                )
        except Exception:
            return end
        return end

    def _fixed_angle_90_enabled(self):
        return (
            self.tab.operation_mode == "create"
            and self.tab.active_geom_type == "polygon"
            and self.tab.active_capture_shape == "fixed_angle_90"
        )

    def _polygon_auxiliary_enabled(self):
        if self.tab.operation_mode != "create":
            return False
        if self.tab.active_geom_type == "line":
            return True
        return self.tab.active_geom_type == "polygon" and self.tab.active_capture_shape in ("polygon", "fixed_angle_90")

    def _capture_shape_label(self):
        if self.tab.active_geom_type == "line":
            return "ライン"
        if self._fixed_angle_90_enabled():
            return "直角多角"
        return "多角"

    def _hold_shortcut_key_from_event(self, event):
        try:
            return self.tab.hold_shortcut_key_from_event(event)
        except Exception:
            return ""

    def _polygon_auxiliary_hold_shortcut_context_enabled(self, key):
        if key in ("parallel_direction_copy", "angle_copy"):
            return (
                self.tab.operation_mode == "create"
                and (
                    self.tab.active_geom_type == "line"
                    or (self.tab.active_geom_type == "polygon" and self.tab.active_capture_shape == "polygon")
                )
            )
        return self._polygon_auxiliary_enabled()

    def _polygon_auxiliary_hold_shortcut_active(self, key):
        return key in self.pressed_hold_shortcut_keys and self._polygon_auxiliary_hold_shortcut_context_enabled(key)

    def _shape_center_mode_from_modifiers(self, modifiers):
        return (
            self.tab.operation_mode == "create"
            and self.tab.active_geom_type == "polygon"
            and self.tab.active_capture_shape in ("ellipse", "circle")
            and bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        )

    def _capture_shape_from_modifiers(self, modifiers):
        if (
            self.tab.operation_mode == "create"
            and self.tab.active_geom_type == "polygon"
            and self.tab.active_capture_shape == "ellipse"
            and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ):
            return "circle"
        return self.tab.active_capture_shape

    def _fixed_angle_90_constraint_active(self):
        return self._fixed_angle_90_enabled() and self.fixed_angle_90_constraint_enabled

    def _toggle_fixed_angle_90_constraint(self):
        self.fixed_angle_90_constraint_enabled = not self.fixed_angle_90_constraint_enabled
        if not self.fixed_angle_90_constraint_enabled:
            self._clear_fixed_angle_90_reference()
            self._clear_fixed_angle_90_length_copy()
        if self.points:
            self._rebuild_capture_preview()
        state = "ON" if self.fixed_angle_90_constraint_enabled else "OFF"
        self.tab.set_status(tr_text(f"直角多角: 90度固定 {state}"))

    def _fixed_angle_90_vector(self, start_point, end_point):
        start = QgsPointXY(start_point)
        end = QgsPointXY(end_point)
        return end.x() - start.x(), end.y() - start.y()

    def _fixed_angle_90_length(self, vector):
        return math.hypot(vector[0], vector[1])

    def _fixed_angle_90_unit(self, vector):
        length = self._fixed_angle_90_length(vector)
        if length <= 0:
            return None
        return vector[0] / length, vector[1] / length

    def _fixed_angle_90_perp(self, unit_vector):
        return -unit_vector[1], unit_vector[0]

    def _fixed_angle_90_rotate(self, unit_vector, radians_value):
        cos_value = math.cos(radians_value)
        sin_value = math.sin(radians_value)
        return (
            unit_vector[0] * cos_value - unit_vector[1] * sin_value,
            unit_vector[0] * sin_value + unit_vector[1] * cos_value,
        )

    def _fixed_angle_90_same_point(self, point_a, point_b, tolerance=1e-9):
        return self._fixed_angle_90_length(self._fixed_angle_90_vector(point_a, point_b)) <= tolerance

    def _fixed_angle_90_cross(self, vector_a, vector_b):
        return vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0]

    def _fixed_angle_90_dot(self, vector_a, vector_b):
        return vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]

    def _fixed_angle_90_parallel(self, unit_a, unit_b, tolerance=1e-6):
        return abs(self._fixed_angle_90_cross(unit_a, unit_b)) <= tolerance

    def _fixed_angle_90_perpendicular(self, unit_a, unit_b, tolerance=1e-6):
        return abs(self._fixed_angle_90_dot(unit_a, unit_b)) <= tolerance

    def _fixed_angle_90_projected_point(self, point, commit=False):
        if len(self.points) < 2:
            return QgsPointXY(point)
        start = QgsPointXY(self.points[-1])
        previous_vector = self._fixed_angle_90_vector(self.points[-2], self.points[-1])
        previous_unit = self._fixed_angle_90_unit(previous_vector)
        if previous_unit is None:
            return QgsPointXY(point)
        raw_vector = self._fixed_angle_90_vector(start, point)
        distance = self._fixed_angle_90_length(raw_vector)
        if distance <= 0:
            return QgsPointXY(point)
        if (
            self.fixed_angle_90_reference_point is not None
            and self._fixed_angle_90_same_point(self.fixed_angle_90_reference_point, start)
        ):
            forward = previous_unit
            backward = (-previous_unit[0], -previous_unit[1])
            direction = forward
            if self._fixed_angle_90_dot(raw_vector, backward) > self._fixed_angle_90_dot(raw_vector, forward):
                direction = backward
            copied_length = self.fixed_angle_90_copied_length
            if copied_length is not None and copied_length > 0:
                distance = copied_length
            result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
            self._update_fixed_angle_90_reference_line(direction)
            if commit:
                self._clear_fixed_angle_90_reference()
                self._clear_fixed_angle_90_length_copy()
                self.tab.set_status(tr_text("直角多角: 直前辺の延長線上に点を追加しました"))
            return result
        perp_a = self._fixed_angle_90_perp(previous_unit)
        perp_b = (-perp_a[0], -perp_a[1])
        direction = perp_a
        if self._fixed_angle_90_dot(raw_vector, perp_b) > self._fixed_angle_90_dot(raw_vector, perp_a):
            direction = perp_b
        aligned = self._fixed_angle_90_reference_aligned_point(start, direction, previous_unit, point)
        if aligned is not None:
            if commit:
                self._clear_fixed_angle_90_reference()
                self._clear_fixed_angle_90_length_copy()
                self.tab.set_status(tr_text("直角多角: 参照点に整列しました"))
            return aligned
        copied_length = self.fixed_angle_90_copied_length
        if copied_length is not None and copied_length > 0:
            distance = copied_length
        result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
        if commit and copied_length is not None:
            self._clear_fixed_angle_90_length_copy()
            self.tab.set_status(tr_text("直角多角: コピーした辺長で点を追加しました"))
        return result

    def _polygon_auxiliary_projected_point(self, point, modifiers, basis_angle=None, commit=False):
        start = QgsPointXY(self.points[-1])
        target = self._angle_constrained_point(start, point, modifiers, basis_angle=basis_angle)
        direction = self._fixed_angle_90_unit(self._fixed_angle_90_vector(start, target))
        if direction is None:
            return QgsPointXY(point)
        if self.angle_copy_small_radians is not None and len(self.points) >= 2:
            raw_vector = self._fixed_angle_90_vector(start, point)
            distance = self._fixed_angle_90_length(raw_vector)
            if distance <= 0:
                return QgsPointXY(point)
            base = self._fixed_angle_90_unit(self._fixed_angle_90_vector(start, self.points[-2]))
            angle = self._selected_angle_copy_radians()
            if base is not None and angle is not None:
                forward = self._fixed_angle_90_rotate(base, angle)
                backward = self._fixed_angle_90_rotate(base, -angle)
                direction = forward
                if self._fixed_angle_90_dot(raw_vector, backward) > self._fixed_angle_90_dot(raw_vector, forward):
                    direction = backward
                copied_length = self.fixed_angle_90_copied_length
                used_copied_length = copied_length is not None and copied_length > 0
                if used_copied_length:
                    distance = copied_length
                result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
                if commit:
                    self._clear_angle_copy()
                    if used_copied_length:
                        self._clear_fixed_angle_90_length_copy()
                        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: コピー角度・コピー辺長で点を追加しました"))
                    else:
                        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: コピー角度で点を追加しました"))
                return result
        if self.parallel_direction_unit is not None:
            raw_vector = self._fixed_angle_90_vector(start, point)
            distance = self._fixed_angle_90_length(raw_vector)
            if distance <= 0:
                return QgsPointXY(point)
            forward = self.parallel_direction_unit
            backward = (-forward[0], -forward[1])
            direction = forward
            if self._fixed_angle_90_dot(raw_vector, backward) > self._fixed_angle_90_dot(raw_vector, forward):
                direction = backward
            copied_length = self.fixed_angle_90_copied_length
            used_copied_length = copied_length is not None and copied_length > 0
            if used_copied_length:
                distance = copied_length
            result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
            if commit:
                self._clear_parallel_direction_copy()
                if used_copied_length:
                    self._clear_fixed_angle_90_length_copy()
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向・コピー辺長で点を追加しました"))
                else:
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向で点を追加しました"))
            return result
        if self.fixed_angle_90_reference_point is not None:
            reference = QgsPointXY(self.fixed_angle_90_reference_point)
            if len(self.points) >= 2 and self._fixed_angle_90_same_point(reference, start):
                previous_unit = self._fixed_angle_90_unit(self._fixed_angle_90_vector(self.points[-2], self.points[-1]))
                if previous_unit is not None:
                    raw_vector = self._fixed_angle_90_vector(start, point)
                    forward = previous_unit
                    backward = (-previous_unit[0], -previous_unit[1])
                    direction = forward
                    if self._fixed_angle_90_dot(raw_vector, backward) > self._fixed_angle_90_dot(raw_vector, forward):
                        direction = backward
                    distance = self._fixed_angle_90_length(raw_vector)
                    copied_length = self.fixed_angle_90_copied_length
                    if copied_length is not None and copied_length > 0:
                        distance = copied_length
                    result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
                    self._update_fixed_angle_90_reference_line(direction)
                    if commit:
                        self._clear_fixed_angle_90_reference()
                        self._clear_fixed_angle_90_length_copy()
                        self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 直前辺の延長線上に点を追加しました"))
                    return result
            delta = self._fixed_angle_90_vector(start, reference)
            distance = self._fixed_angle_90_dot(delta, direction)
            result = QgsPointXY(start.x() + direction[0] * distance, start.y() + direction[1] * distance)
            self._update_fixed_angle_90_reference_line(direction)
            if commit:
                self._clear_fixed_angle_90_reference()
                self._clear_fixed_angle_90_length_copy()
                self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 参照点に整列しました"))
            return result
        copied_length = self.fixed_angle_90_copied_length
        if copied_length is not None and copied_length > 0:
            result = QgsPointXY(start.x() + direction[0] * copied_length, start.y() + direction[1] * copied_length)
            if commit:
                self._clear_fixed_angle_90_length_copy()
                self.tab.set_status(tr_text(f"{self._capture_shape_label()}: コピーした辺長で点を追加しました"))
            return result
        return target

    def _fixed_angle_90_reference_aligned_point(self, start_point, direction, previous_unit, raw_point):
        if self.fixed_angle_90_reference_point is None:
            return None
        reference = QgsPointXY(self.fixed_angle_90_reference_point)
        raw = QgsPointXY(raw_point)
        candidates = []
        for align_dir in (previous_unit, direction):
            if align_dir is None:
                continue
            intersection = self._fixed_angle_90_line_intersection(start_point, direction, reference, align_dir)
            if intersection is not None:
                candidates.append((intersection, align_dir))
                continue
            offset = self._fixed_angle_90_vector(start_point, reference)
            if abs(self._fixed_angle_90_cross(offset, direction)) <= 1e-6:
                raw_delta = self._fixed_angle_90_vector(start_point, raw)
                distance = self._fixed_angle_90_dot(raw_delta, direction)
                candidates.append((
                    QgsPointXY(
                        start_point.x() + direction[0] * distance,
                        start_point.y() + direction[1] * distance,
                    ),
                    align_dir,
                ))
        if not candidates:
            return None
        point, align_dir = min(
            candidates,
            key=lambda candidate: self._fixed_angle_90_length(self._fixed_angle_90_vector(raw, candidate[0])),
        )
        self._update_fixed_angle_90_reference_line(align_dir)
        return point

    def _fixed_angle_90_line_intersection(self, point_a, dir_a, point_b, dir_b):
        denominator = self._fixed_angle_90_cross(dir_a, dir_b)
        if abs(denominator) <= 1e-9:
            return None
        delta = self._fixed_angle_90_vector(point_a, point_b)
        t = self._fixed_angle_90_cross(delta, dir_b) / denominator
        return QgsPointXY(point_a.x() + dir_a[0] * t, point_a.y() + dir_a[1] * t)

    def _fixed_angle_90_append_unique(self, points, point):
        point = QgsPointXY(point)
        if points and self._fixed_angle_90_same_point(points[-1], point):
            return
        points.append(point)

    def _fixed_angle_90_closed_points(self):
        if len(self.points) < 3:
            return None
        pts = [QgsPointXY(point) for point in self.points]
        first = pts[0]
        second = pts[1]
        last = pts[-1]
        before_last = pts[-2]
        first_vector = self._fixed_angle_90_vector(first, second)
        previous_vector = self._fixed_angle_90_vector(before_last, last)
        first_unit = self._fixed_angle_90_unit(first_vector)
        previous_unit = self._fixed_angle_90_unit(previous_vector)
        if first_unit is None or previous_unit is None:
            return None
        closing_unit = self._fixed_angle_90_unit(self._fixed_angle_90_vector(last, first))
        if (
            closing_unit is not None
            and self._fixed_angle_90_perpendicular(previous_unit, closing_unit)
            and self._fixed_angle_90_perpendicular(first_unit, closing_unit)
        ):
            direct_closed = list(pts)
            self._fixed_angle_90_append_unique(direct_closed, first)
            if self._fixed_angle_90_ring_is_valid(direct_closed):
                return direct_closed
        closed = list(pts)
        if self._fixed_angle_90_perpendicular(previous_unit, first_unit):
            dir_from_last = self._fixed_angle_90_perp(previous_unit)
            dir_to_first = self._fixed_angle_90_perp(first_unit)
            corner = self._fixed_angle_90_line_intersection(last, dir_from_last, first, dir_to_first)
            if corner is None:
                return None
            self._fixed_angle_90_append_unique(closed, corner)
            self._fixed_angle_90_append_unique(closed, first)
        elif self._fixed_angle_90_parallel(previous_unit, first_unit):
            delta = self._fixed_angle_90_vector(last, first)
            along_previous = self._fixed_angle_90_dot(delta, previous_unit)
            perp_unit = self._fixed_angle_90_perp(previous_unit)
            along_perp = self._fixed_angle_90_dot(delta, perp_unit)
            if abs(along_previous) <= 1e-9:
                self._fixed_angle_90_append_unique(closed, first)
            elif abs(along_perp) <= 1e-9:
                return None
            else:
                corner_a = QgsPointXY(
                    last.x() + perp_unit[0] * (along_perp / 2.0),
                    last.y() + perp_unit[1] * (along_perp / 2.0),
                )
                corner_b = QgsPointXY(
                    corner_a.x() + previous_unit[0] * along_previous,
                    corner_a.y() + previous_unit[1] * along_previous,
                )
                self._fixed_angle_90_append_unique(closed, corner_a)
                self._fixed_angle_90_append_unique(closed, corner_b)
                self._fixed_angle_90_append_unique(closed, first)
        else:
            return None
        if not self._fixed_angle_90_ring_is_valid(closed):
            return None
        return closed

    def _fixed_angle_90_ring_is_valid(self, closed_points):
        if len(closed_points) < 4:
            return False
        ring = [QgsPointXY(point) for point in closed_points]
        if not self._fixed_angle_90_same_point(ring[0], ring[-1]):
            ring.append(QgsPointXY(ring[0]))
        vertices = ring[:-1]
        count = len(vertices)
        if count < 3:
            return False
        for index in range(count):
            previous_point = vertices[index - 1]
            current_point = vertices[index]
            next_point = vertices[(index + 1) % count]
            incoming = self._fixed_angle_90_vector(current_point, previous_point)
            outgoing = self._fixed_angle_90_vector(current_point, next_point)
            incoming_length = self._fixed_angle_90_length(incoming)
            outgoing_length = self._fixed_angle_90_length(outgoing)
            if incoming_length <= 1e-9 or outgoing_length <= 1e-9:
                return False
            tolerance = max(1e-9, incoming_length * outgoing_length * 1e-6)
            dot = self._fixed_angle_90_dot(incoming, outgoing)
            if abs(dot) <= tolerance:
                continue
            cross = abs(self._fixed_angle_90_cross(incoming, outgoing))
            if dot < 0 and cross <= tolerance:
                continue
            return False
        return True

    def _capture_point_with_angle_constraint(self, point, modifiers, commit=False):
        if not self.points:
            return QgsPointXY(point)
        if self.tab.operation_mode != "create":
            return QgsPointXY(point)
        basis_angle = None
        try:
            if (
                modifiers & Qt.KeyboardModifier.ControlModifier
                and self.tab.inspection_angle_snap_basis() == INSPECTION_ANGLE_SNAP_BASIS_PREVIOUS_EDGE
                and len(self.points) >= 2
            ):
                previous_start = QgsPointXY(self.points[-2])
                previous_end = QgsPointXY(self.points[-1])
                previous_dx = previous_end.x() - previous_start.x()
                previous_dy = previous_end.y() - previous_start.y()
                if previous_dx != 0 or previous_dy != 0:
                    basis_angle = math.atan2(previous_dy, previous_dx)
        except Exception:
            basis_angle = None
        if self._fixed_angle_90_enabled():
            if modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                return self._angle_constrained_point(self.points[-1], point, modifiers, basis_angle=basis_angle)
            if not self.fixed_angle_90_constraint_enabled:
                return QgsPointXY(point)
            return self._fixed_angle_90_projected_point(point, commit=commit)
        if self.tab.active_geom_type == "polygon" and self.tab.active_capture_shape != "polygon":
            return QgsPointXY(point)
        if self.tab.active_geom_type not in ("polygon", "line"):
            return QgsPointXY(point)
        if (
            (self.tab.active_geom_type == "line" or (self.tab.active_geom_type == "polygon" and self.tab.active_capture_shape == "polygon"))
            and (
                self.fixed_angle_90_reference_point is not None
                or self.fixed_angle_90_copied_length is not None
                or self.parallel_direction_unit is not None
                or self.angle_copy_small_radians is not None
            )
        ):
            return self._polygon_auxiliary_projected_point(point, modifiers, basis_angle=basis_angle, commit=commit)
        return self._angle_constrained_point(self.points[-1], point, modifiers, basis_angle=basis_angle)

    def _line_close_snap_point(self, event):
        if self.tab.operation_mode != "create" or self.tab.active_geom_type != "line":
            return None
        if len(self.points) < 2:
            return None
        first = QgsPointXY(self.points[0])
        try:
            first_pixel = self.canvas.getCoordinateTransform().transform(first)
            event_pixel = event.pixelPoint()
            dx = first_pixel.x() - event_pixel.x()
            dy = first_pixel.y() - event_pixel.y()
            if (dx * dx + dy * dy) <= 144:
                return first
        except Exception:
            pass
        return None

    def _ensure_select_band(self):
        if self.select_band:
            return
        self.select_band = QRubberBand(QRubberBand.Shape.Rectangle, self.canvas.viewport())

    def _ensure_select_polygon_band(self):
        if self.select_polygon_band:
            return
        self.select_polygon_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
        stroke_color = QColor("#1456d9")
        stroke_color.setAlpha(230)
        fill_color = QColor(stroke_color)
        fill_color.setAlpha(35)
        try:
            self.select_polygon_band.setStrokeColor(stroke_color)
            self.select_polygon_band.setFillColor(fill_color)
            self.select_polygon_band.setBrushStyle(Qt.BrushStyle.SolidPattern)
        except Exception:
            self.select_polygon_band.setColor(stroke_color)
        self.select_polygon_band.setWidth(2)

    def _update_select_band(self, end_pixel):
        if not self.select_start_pixel:
            return
        self._ensure_select_band()
        rect = QRect(self.select_start_pixel, end_pixel).normalized()
        self.select_band.setGeometry(rect)
        self.select_band.show()

    def _add_select_polygon_marker(self, point):
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(QgsPointXY(point))
        marker.setColor(QColor("#1456d9"))
        marker.setIconSize(9)
        marker.setPenWidth(2)
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
        self.select_polygon_markers.append(marker)

    def _rebuild_select_polygon_preview(self, preview_point=None):
        if not self.select_polygon_points:
            return
        self._ensure_select_polygon_band()
        try:
            self.select_polygon_band.reset(Qgis.GeometryType.Polygon)
            self.select_polygon_band.setWidth(2)
        except Exception:
            try:
                self.canvas.scene().removeItem(self.select_polygon_band)
            except Exception:
                pass
            self.select_polygon_band = None
            self._ensure_select_polygon_band()
        draw_points = [QgsPointXY(point) for point in self.select_polygon_points]
        if preview_point is not None:
            draw_points.append(QgsPointXY(preview_point))
        if len(draw_points) >= 2:
            draw_points.append(QgsPointXY(draw_points[0]))
        last_index = len(draw_points) - 1
        for index, point in enumerate(draw_points):
            self.select_polygon_band.addPoint(QgsPointXY(point), index == last_index)
        self.select_polygon_band.show()

    def _finish_select_polygon(self):
        if len(self.select_polygon_points) < 3:
            self._clear_select_polygon()
            if self.tab.operation_mode == "layer_change_select_polygon":
                self.tab.set_status(tr_text("移層: 多角選は3点以上指定してください"))
            else:
                self.tab.set_status(tr_text("多角選: 3点以上指定してください"))
            return
        points = [QgsPointXY(point) for point in self.select_polygon_points]
        points.append(QgsPointXY(points[0]))
        geometry = QgsGeometry.fromPolygonXY([points])
        modifiers = self.select_polygon_modifiers
        self._clear_select_polygon()
        self.tab.select_features_in_geometry(geometry, modifiers)

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
        return bool(
            self.points
            or self.vertex_markers
            or self.shape_start_point
            or self.rubber_band
            or self.fixed_angle_90_reference_point
            or self.fixed_angle_90_copied_length
            or self.parallel_direction_unit
        )

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
            if self.tab.operation_mode in ("select_polygon", "layer_change_select_polygon") and self.select_polygon_points:
                try:
                    event.accept()
                except Exception:
                    pass
                self._finish_select_polygon()
                return
            if self.tab.operation_mode == "move":
                try:
                    event.accept()
                except Exception:
                    pass
                self._clear_move_state()
                self.tab.return_to_last_selection_mode("移動終了")
                return
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
                self._clear_direct_vertex_state()
                point = self._event_map_point(event)
                if self.tab.switch_direct_overlap_vertex_candidate_at(point):
                    return
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
        if mode in ("select_polygon", "layer_change_select_polygon"):
            if not self.select_polygon_points:
                self.select_polygon_modifiers = event.modifiers()
            self.select_polygon_points.append(QgsPointXY(point))
            self._add_select_polygon_marker(point)
            self._rebuild_select_polygon_preview()
            if mode == "layer_change_select_polygon":
                self.tab.set_status(tr_text("移層: 多角選で移動対象を再選択中。右クリックで確定"))
            else:
                self.tab.set_status(tr_text("多角選: 左クリックで頂点追加、右クリックで確定"))
            return
        if mode == "layer_change":
            self.tab.set_status(tr_text("移層: 右クリックメニューから移動先項目を選択してください"))
            return
        if mode == "restore":
            self.select_start_point = QgsPointXY(point)
            self.select_start_pixel = event.pixelPoint()
            self._ensure_select_band()
            self._update_select_band(self.select_start_pixel)
            return
        if mode == "delete":
            self.tab.delete_feature_at(point)
            return
        if mode == "move":
            move_anchor_point = self._event_map_point(
                event, use_snap=True, set_current_layer=False, allow_line_close=False
            )
            if self.tab.begin_feature_move_at(point, anchor_point=move_anchor_point):
                self.tab.update_map_cursor()
                self.move_start_point = QgsPointXY(move_anchor_point)
                self.move_start_pixel = event.pixelPoint()
                self.move_dragging = False
            return
        if mode == "edit":
            self._clear_direct_vertex_state()
            self.tab.suspend_edit_hover_prepare = False
            self.tab.remember_edit_overlap_anchor_at(point)
            self.tab.prepare_edit_layer_at(point)
            return
        if mode == "merge":
            self.tab.toggle_merge_feature_at(point)
            return
        if mode != "create":
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

        if self._polygon_auxiliary_hold_shortcut_active("angle_copy"):
            self._set_angle_copy(capture_point)
            return

        if self._polygon_auxiliary_hold_shortcut_active("parallel_direction_copy"):
            self._set_parallel_direction_copy(capture_point)
            return

        if self._polygon_auxiliary_hold_shortcut_active("fixed_angle_90_reference"):
            self._set_fixed_angle_90_reference(capture_point)
            return

        if self._polygon_auxiliary_hold_shortcut_active("fixed_angle_90_length_copy"):
            self._set_fixed_angle_90_length_copy(capture_point)
            return

        if geom_type == "polygon" and self.tab.active_capture_shape in ("rectangle", "ellipse", "circle"):
            self.shape_start_point = QgsPointXY(capture_point)
            self.shape_start_pixel = event.pixelPoint()
            self.last_shape_preview_pixel = event.pixelPoint()
            self._ensure_rubber_band(layer)
            self._update_shape_preview(capture_point)
            return

        self._ensure_rubber_band(layer)
        capture_point = self._capture_point_with_angle_constraint(capture_point, event.modifiers(), commit=True)
        self.points.append(QgsPointXY(capture_point))
        self._add_capture_vertex_marker(capture_point)
        self._rebuild_capture_preview()

    def canvasMoveEvent(self, event):
        if self.move_start_point and self.tab.operation_mode != "move":
            self._clear_move_state()
            return
        if self.edit_vertex_start_point and self.tab.operation_mode != "edit":
            self._clear_direct_vertex_state()
            return
        if self.tab.operation_mode in ("select", "layer_change_select", "restore") and self.select_start_point:
            self._clear_snap_indicator()
            self._update_select_band(event.pixelPoint())
        elif self.tab.operation_mode in ("select_polygon", "layer_change_select_polygon") and self.select_polygon_points:
            self._clear_snap_indicator()
            self._rebuild_select_polygon_preview(self._event_map_point(event))
        elif self.tab.operation_mode == "move" and self.move_start_point:
            if not self.move_dragging:
                self.tab.clear_selection_highlight()
            self.move_dragging = True
            self.tab.update_feature_move_preview(
                self.move_start_point,
                self._event_map_point(event, use_snap=True, set_current_layer=False, allow_line_close=False),
            )
        elif self.tab.operation_mode == "move":
            self._event_map_point(event, use_snap=True, set_current_layer=False, allow_line_close=False)
        elif self.tab.operation_mode == "edit" and self.edit_vertex_start_point and self.tab.has_direct_overlap_vertex_edit():
            self.edit_vertex_dragging = True
            self.tab.update_direct_overlap_vertex_preview(self._event_map_point(event, use_snap=True))
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
                modifiers = event.modifiers()
                self._update_shape_preview(
                    snap_point,
                    center_mode=self._shape_center_mode_from_modifiers(modifiers),
                    shape=self._capture_shape_from_modifiers(modifiers),
                )
            elif self.points:
                snap_point = self._capture_point_with_angle_constraint(snap_point, event.modifiers())
                self._rebuild_capture_preview(snap_point)
        else:
            self._clear_snap_indicator()

    def canvasReleaseEvent(self, event):
        if (
            self.tab.operation_mode == "edit"
            and self.tab.just_finished_direct_overlap_vertex_edit
            and event.button() == Qt.MouseButton.LeftButton
        ):
            try:
                event.accept()
            except Exception:
                pass
            return
        if self.move_start_point and self.tab.operation_mode != "move":
            self._clear_move_state()
            return
        if self.edit_vertex_start_point and self.tab.operation_mode != "edit":
            self._clear_direct_vertex_state()
            return
        if self.tab.operation_mode == "move" and self.move_start_point:
            start_pixel = self.move_start_pixel
            end_pixel = event.pixelPoint()
            moved = False
            try:
                moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
            except Exception:
                moved = self.move_dragging
            start_point = self.move_start_point
            end_point = self._event_map_point(event, use_snap=True, set_current_layer=False, allow_line_close=False)
            self._clear_snap_indicator()
            self.move_start_point = None
            self.move_start_pixel = None
            self.move_dragging = False
            if moved:
                self.tab.finish_feature_move(start_point, end_point)
            else:
                self.tab.clear_feature_move_preview()
                self.tab.refresh_selection_highlight()
                self.tab.set_status(tr_text("移動: ドラッグすると選択データを移動します"))
            return
        if self.tab.operation_mode == "edit" and self.edit_vertex_start_point and self.tab.has_direct_overlap_vertex_edit():
            try:
                event.accept()
            except Exception:
                pass
            if self.tab.ignore_next_direct_overlap_release:
                self.tab.ignore_next_direct_overlap_release = False
                return
            start_pixel = self.edit_vertex_start_pixel
            end_pixel = event.pixelPoint()
            moved = False
            try:
                moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
            except Exception:
                moved = self.edit_vertex_dragging
            end_point = self._event_map_point(event, use_snap=True)
            self._clear_direct_vertex_state()
            if moved:
                self.tab.finish_direct_overlap_vertex_move(end_point)
            else:
                self.tab.clear_direct_overlap_vertex_preview()
            self.tab.clear_direct_overlap_vertex_edit()
            self.tab.clear_edit_overlap_anchor()
            self.tab.stop_qgis_vertex_tool_for_direct_overlap()
            self.tab.just_finished_direct_overlap_vertex_edit = True
            self.tab.suspend_edit_hover_prepare = False
            return
        if self.shape_start_point and self.tab.operation_mode == "create":
            start_pixel = self.shape_start_pixel
            end_pixel = event.pixelPoint()
            moved = abs(end_pixel.x() - start_pixel.x()) > 4 or abs(end_pixel.y() - start_pixel.y()) > 4
            if moved:
                layer = self.tab.active_layer()
                modifiers = event.modifiers()
                geometry = self.tab.geometry_from_shape(
                    self._capture_shape_from_modifiers(modifiers),
                    self.shape_start_point,
                    self._event_map_point(event, use_snap=True),
                    center_mode=self._shape_center_mode_from_modifiers(modifiers),
                )
                if layer and geometry:
                    self.tab.add_geometry_feature(layer, geometry)
            self._clear_capture_state()
            return
        if self.tab.operation_mode not in ("select", "layer_change_select", "restore") or not self.select_start_point:
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
        if self.tab.operation_mode == "restore":
            if moved:
                self.tab.select_trash_features_in_rect(self.tab.rectangle_from_points(start_point, end_point), modifiers)
            else:
                self.tab.select_trash_feature_at(end_point, modifiers)
        elif moved:
            self.tab.select_features_in_rect(self.tab.rectangle_from_points(start_point, end_point), modifiers)
        else:
            self.tab.select_feature_at(end_point, modifiers)

    def canvasDoubleClickEvent(self, event):
        if self.tab.operation_mode in ("select_polygon", "layer_change_select_polygon"):
            try:
                event.accept()
            except Exception:
                pass
            return
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
        if self.tab.handle_qgis_feature_clipboard_key(event):
            event.accept()
            return
        hold_key = self._hold_shortcut_key_from_event(event)
        if hold_key and self._polygon_auxiliary_hold_shortcut_context_enabled(hold_key):
            try:
                if not event.isAutoRepeat():
                    self.pressed_hold_shortcut_keys.add(hold_key)
            except Exception:
                self.pressed_hold_shortcut_keys.add(hold_key)
            event.accept()
            return
        if self.tab.operation_mode in ("select_polygon", "layer_change_select_polygon"):
            if key == Qt.Key.Key_Escape:
                self._clear_select_polygon()
                self.tab.set_status(tr_text("多角選をキャンセルしました"))
                event.accept()
                return
            if key == Qt.Key.Key_Backspace:
                if self.select_polygon_points:
                    self.select_polygon_points.pop()
                    if self.select_polygon_markers:
                        marker = self.select_polygon_markers.pop()
                        try:
                            self.canvas.scene().removeItem(marker)
                        except Exception:
                            pass
                    if self.select_polygon_points:
                        self._rebuild_select_polygon_preview()
                    else:
                        self._clear_select_polygon()
                    event.accept()
                    return
        if self.tab.operation_mode == "create":
            if key == Qt.Key.Key_Alt and self._fixed_angle_90_enabled():
                try:
                    if event.isAutoRepeat():
                        event.accept()
                        return
                except Exception:
                    pass
                self._toggle_fixed_angle_90_constraint()
                event.accept()
                return
            if key == Qt.Key.Key_Escape:
                if self._has_capture_state():
                    self._clear_capture_state()
                    self.tab.set_status(tr_text("作成をキャンセルしました"))
                    event.accept()
                    return
            elif key == Qt.Key.Key_Backspace:
                if self.fixed_angle_90_reference_point is not None:
                    self._clear_fixed_angle_90_reference()
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 参照点を解除しました"))
                    event.accept()
                    return
                if self.fixed_angle_90_copied_length is not None:
                    self._clear_fixed_angle_90_length_copy()
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 辺長コピーを解除しました"))
                    event.accept()
                    return
                if self.parallel_direction_unit is not None:
                    self._clear_parallel_direction_copy()
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 平行方向コピーを解除しました"))
                    event.accept()
                    return
                if self.angle_copy_small_radians is not None:
                    self._clear_angle_copy()
                    self.tab.set_status(tr_text(f"{self._capture_shape_label()}: 角度コピーを解除しました"))
                    event.accept()
                    return
                if self.shape_start_point:
                    self._clear_rubber_band()
                    self.tab.set_status(tr_text("作成開始前に戻しました"))
                    event.accept()
                    return
                if self._remove_last_capture_point():
                    message = "1つ前の点に戻しました" if self.points else "作成開始前に戻しました"
                    self.tab.set_status(message)
                    event.accept()
                    return
        if self.tab.operation_mode == "move":
            is_undo = key == Qt.Key.Key_Backspace
            try:
                is_undo = is_undo or (
                    key == Qt.Key.Key_Z
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                )
            except Exception:
                pass
            if is_undo:
                if self.tab.undo_last_feature_move():
                    event.accept()
                    return
        if self.tab.operation_mode == "edit" and key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            try:
                modifiers = event.modifiers()
            except Exception:
                modifiers = Qt.KeyboardModifier.NoModifier
            self.tab.forward_qgis_vertex_tool_key(key, modifiers)
            event.accept()
            return
        if self.tab.handle_shortcut_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        hold_key = self._hold_shortcut_key_from_event(event)
        if hold_key:
            try:
                if not event.isAutoRepeat():
                    self.pressed_hold_shortcut_keys.discard(hold_key)
            except Exception:
                self.pressed_hold_shortcut_keys.discard(hold_key)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _finish_capture(self):
        layer = self.tab.active_layer()
        if not layer:
            self._clear_rubber_band()
            return
        geom_type = self.tab.active_geom_type
        if geom_type == "polygon":
            if len(self.points) < 3:
                self.tab.set_status(tr_text("ポリゴンは3点以上必要です"))
                self._clear_rubber_band()
                return
            if self._fixed_angle_90_enabled() and self.fixed_angle_90_constraint_enabled:
                pts = self._fixed_angle_90_closed_points()
                if pts is None:
                    self.tab.set_status(tr_text("直角多角: 最後の角度を90度で閉じられません。最後の点を調整してください"))
                    self._rebuild_capture_preview()
                    return
            else:
                pts = list(self.points)
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            geometry = QgsGeometry.fromPolygonXY([pts])
        else:
            if len(self.points) < 2:
                self.tab.set_status(tr_text("ラインは2点以上必要です"))
                self._clear_rubber_band()
                return
            geometry = QgsGeometry.fromPolylineXY(list(self.points))
        self.tab.add_geometry_feature(layer, geometry)
        self._clear_capture_state()

    def _finish_fixed_angle_90_reference_capture(self, event):
        if (
            not self._fixed_angle_90_enabled()
            or self.fixed_angle_90_reference_point is None
            or len(self.points) < 2
        ):
            return False
        if self._fixed_angle_90_same_point(self.fixed_angle_90_reference_point, self.points[0]):
            final_point = self._fixed_angle_90_reference_line_point(self._event_map_point(event, use_snap=True))
            if final_point is None:
                return False
            return self._finish_fixed_angle_90_direct_points(final_point)
        final_point = self._fixed_angle_90_projected_point(self._event_map_point(event, use_snap=True), commit=False)
        if self._fixed_angle_90_same_point(self.points[-1], final_point):
            return False
        self.points.append(QgsPointXY(final_point))
        closed_points = self._fixed_angle_90_closed_points()
        if closed_points is None:
            self.points.pop()
            return False
        self._clear_fixed_angle_90_reference()
        self._clear_fixed_angle_90_length_copy()
        self._finish_capture()
        return True

    def _fixed_angle_90_reference_line_point(self, raw_point):
        reference = QgsPointXY(self.fixed_angle_90_reference_point)
        direction = self.fixed_angle_90_reference_line_direction
        if direction is None:
            first_unit = self._fixed_angle_90_unit(self._fixed_angle_90_vector(self.points[0], self.points[1]))
            if first_unit is None:
                return None
            direction = self._fixed_angle_90_perp(first_unit)
        unit = self._fixed_angle_90_unit(direction)
        if unit is None:
            return None
        delta = self._fixed_angle_90_vector(reference, raw_point)
        distance = self._fixed_angle_90_dot(delta, unit)
        return QgsPointXY(reference.x() + unit[0] * distance, reference.y() + unit[1] * distance)

    def _finish_fixed_angle_90_direct_points(self, final_point):
        if self._fixed_angle_90_same_point(self.points[-1], final_point):
            return False
        layer = self.tab.active_layer()
        if not layer:
            return False
        pts = [QgsPointXY(point) for point in self.points]
        pts.append(QgsPointXY(final_point))
        if not self._fixed_angle_90_same_point(pts[0], pts[-1]):
            pts.append(QgsPointXY(pts[0]))
        if len(pts) < 4:
            return False
        geometry = QgsGeometry.fromPolygonXY([pts])
        self._clear_fixed_angle_90_reference()
        self._clear_fixed_angle_90_length_copy()
        self.tab.add_geometry_feature(layer, geometry)
        self._clear_capture_state()
        return True

    def _update_shape_preview(self, end_point, center_mode=False, shape=None):
        if not self.shape_start_point or not self.rubber_band:
            return
        geometry = self.tab.geometry_from_shape(
            shape or self.tab.active_capture_shape,
            self.shape_start_point,
            end_point,
            center_mode=center_mode,
        )
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



