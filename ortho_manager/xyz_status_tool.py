from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import math
import time

from qgis.PyQt.QtWidgets import QLabel, QLineEdit, QWidget
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsDoubleRange,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointCloudLayer,
    QgsPointXY,
    QgsProject,
    QgsRasterBlock,
    QgsRasterLayer,
    QgsRasterLayerElevationProperties,
    QgsRectangle,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgsStatusBar


XYZ_STATUS_ENABLED_KEY = "OrthoManager/xyz_status_enabled"

RASTER_IMAGE_COLOR_INTERPRETATIONS = {
    Qgis.RasterColorInterpretation.PaletteIndex,
    Qgis.RasterColorInterpretation.RedBand,
    Qgis.RasterColorInterpretation.GreenBand,
    Qgis.RasterColorInterpretation.BlueBand,
    Qgis.RasterColorInterpretation.AlphaBand,
    Qgis.RasterColorInterpretation.HueBand,
    Qgis.RasterColorInterpretation.SaturationBand,
    Qgis.RasterColorInterpretation.LightnessBand,
    Qgis.RasterColorInterpretation.CyanBand,
    Qgis.RasterColorInterpretation.MagentaBand,
    Qgis.RasterColorInterpretation.YellowBand,
    Qgis.RasterColorInterpretation.BlackBand,
    Qgis.RasterColorInterpretation.YCbCr_YBand,
    Qgis.RasterColorInterpretation.YCbCr_CbBand,
    Qgis.RasterColorInterpretation.YCbCr_CrBand,
    Qgis.RasterColorInterpretation.ContinuousPalette,
}

RASTER_NON_ELEVATION_DATA_TYPES = {
    Qgis.DataType.UnknownDataType,
    Qgis.DataType.Byte,
    Qgis.DataType.CInt16,
    Qgis.DataType.CInt32,
    Qgis.DataType.CFloat32,
    Qgis.DataType.CFloat64,
    Qgis.DataType.ARGB32,
    Qgis.DataType.ARGB32_Premultiplied,
}

VECTOR_Z_FIELD_NAMES = {
    "z",
    "z_m",
    "zcoord",
    "z_coord",
    "zcoordinate",
    "z_coordinate",
    "zvalue",
    "z_value",
    "z値",
    "標高",
    "高さ",
    "height",
    "height_m",
    "elevation",
    "elevation_m",
    "elev",
    "elev_m",
    "altitude",
    "altitude_m",
    "alt",
    "el",
    "h",
    "rastervalu",
}


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


class XyzStatusTool:
    def __init__(self, iface):
        self.iface = iface
        self.label = None
        self.labels = {}
        self._latest_results = {"raster": None, "vector": None, "point_cloud": None}
        self._hidden_locator_widgets = []
        self._connected_canvases = []
        self._last_update_sec = 0.0
        self._last_point = None
        self.enabled = setting_bool(
            QgsSettings().value(XYZ_STATUS_ENABLED_KEY, True),
            True,
        )

    def install(self):
        self._ensure_labels()
        self._connect_canvases()
        self.set_enabled(self.enabled)

    def cleanup(self):
        self._disconnect_canvases()
        self._restore_locator_widgets()
        for label in list(self.labels.values()):
            self._remove_status_widget(label)
            try:
                label.deleteLater()
            except Exception:
                _om_record_ignored_exception(__name__, 126)
        self.labels = {}
        if self.label is not None:
            self._remove_status_widget(self.label)
            try:
                self.label.deleteLater()
            except Exception:
                _om_record_ignored_exception(__name__, 133)
            self.label = None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        QgsSettings().setValue(XYZ_STATUS_ENABLED_KEY, self.enabled)
        self._ensure_labels()
        for label in self.labels.values():
            label.setVisible(self.enabled)
            if not self.enabled:
                label.setText("")
        if self.enabled:
            self._update_label(None, None, None)

    def refresh_from_settings(self):
        self.set_enabled(setting_bool(QgsSettings().value(XYZ_STATUS_ENABLED_KEY, True), True))

    def _ensure_labels(self):
        if self.labels:
            return
        specs = (
            ("raster", "Z(R)", 72),
            ("vector", "Z(V)", 72),
            ("point_cloud", "Z(P)", 72),
        )
        for key, prefix, width in specs:
            label = QLabel(f"{prefix}: --")
            label.setMinimumWidth(width)
            label.setStyleSheet(
                "QLabel{padding:1px 5px;color:#263238;background:#eef3f5;border-left:1px solid #c7d0d5;}"
            )
            label.setToolTip(f"{prefix}: --")
            self.labels[key] = label
        self._add_status_widgets(list(self.labels.values()))

    def _add_status_widgets(self, widgets):
        self._hide_locator_widgets()
        for widget in reversed(widgets):
            self._add_status_widget(widget)

    def _hide_locator_widgets(self):
        try:
            status_bar = self.iface.mainWindow().statusBar()
        except Exception:
            return
        for widget in status_bar.findChildren(QLineEdit):
            try:
                if not self._looks_like_locator_widget(widget):
                    continue
                if widget in self._hidden_locator_widgets:
                    continue
                self._hidden_locator_widgets.append(widget)
                widget.setVisible(False)
            except Exception:
                _om_record_ignored_exception(__name__, 187); continue

    def _restore_locator_widgets(self):
        for widget in list(self._hidden_locator_widgets):
            try:
                widget.setVisible(True)
            except Exception:
                _om_record_ignored_exception(__name__, 194)
        self._hidden_locator_widgets = []

    def _looks_like_locator_widget(self, widget):
        text_parts = []
        for name in ("placeholderText", "toolTip", "statusTip", "whatsThis", "objectName", "accessibleName"):
            try:
                value = getattr(widget, name)
                if callable(value):
                    value = value()
                if value:
                    text_parts.append(str(value))
            except Exception:
                _om_record_ignored_exception(__name__, 207); continue
        text = " ".join(text_parts).lower()
        return "ctrl+k" in text or "ctrl + k" in text or "検索" in text or "locator" in text

    def _insert_widgets_before_coordinates(self, widgets):
        try:
            status_bar = self.iface.mainWindow().statusBar()
            layout = status_bar.layout()
            if layout is None:
                return False
            insert_index = self._coordinate_insert_index(status_bar, layout)
            if insert_index is None:
                return False
            for offset, widget in enumerate(widgets):
                layout.insertWidget(insert_index + offset, widget)
            return True
        except Exception:
            return False

    def _coordinate_insert_index(self, status_bar, layout):
        coordinate_label = self._find_status_widget(status_bar, self._looks_like_coordinate_label)
        if coordinate_label is not None:
            top_widget = self._top_status_widget(coordinate_label, status_bar)
            index = self._layout_index(layout, top_widget)
            if index is not None:
                return index
        coordinate_widget = self._find_status_widget(status_bar, self._looks_like_coordinate_widget)
        if coordinate_widget is not None:
            top_widget = self._top_status_widget(coordinate_widget, status_bar)
            index = self._layout_index(layout, top_widget)
            if index is not None:
                return index
        return None

    def _find_status_widget(self, root, predicate):
        for widget in root.findChildren(QWidget):
            try:
                if predicate(widget):
                    return widget
            except Exception:
                _om_record_ignored_exception(__name__, 247); continue
        return None

    def _top_status_widget(self, widget, status_bar):
        current = widget
        while current is not None:
            parent = current.parentWidget()
            if parent is None or parent == status_bar:
                return current
            current = parent
        return widget

    def _layout_index(self, layout, widget):
        if widget is None:
            return None
        try:
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is not None and item.widget() == widget:
                    return index
        except Exception:
            return None
        return None

    def _looks_like_coordinate_label(self, widget):
        text = self._widget_text(widget)
        if not text:
            return False
        normalized = text.strip().lower()
        return normalized in {"座標", "座標:", "coordinate", "coordinates", "坐标", "坐標"}

    def _looks_like_coordinate_widget(self, widget):
        text = self._widget_text(widget)
        if not text or "," not in text:
            return False
        return any(char.isdigit() for char in text) and ("-" in text or "." in text)

    def _widget_text(self, widget):
        for name in ("text", "currentText", "placeholderText", "toolTip"):
            try:
                value = getattr(widget, name)
                if callable(value):
                    value = value()
                if value:
                    return str(value)
            except Exception:
                _om_record_ignored_exception(__name__, 293); continue
        return ""

    def _add_status_widget(self, widget):
        try:
            status_bar = self.iface.statusBarIface()
            anchor_left = getattr(QgsStatusBar, "AnchorLeft", None)
            if anchor_left is None:
                anchor_left = getattr(getattr(QgsStatusBar, "Anchor", None), "AnchorLeft", None)
            if anchor_left is not None:
                status_bar.addPermanentWidget(widget, 0, anchor_left)
                return
            status_bar.addPermanentWidget(widget)
            return
        except Exception:
            _om_record_ignored_exception(__name__, 308)
        self.iface.mainWindow().statusBar().addPermanentWidget(widget)

    def _remove_status_widget(self, widget):
        try:
            self.iface.statusBarIface().removeWidget(widget)
            return
        except Exception:
            _om_record_ignored_exception(__name__, 316)
        try:
            self.iface.mainWindow().statusBar().removeWidget(widget)
        except Exception:
            _om_record_ignored_exception(__name__, 320)

    def _map_canvases(self):
        canvases = []
        try:
            for canvas in self.iface.mapCanvases() or []:
                if canvas and canvas not in canvases:
                    canvases.append(canvas)
        except Exception:
            _om_record_ignored_exception(__name__, 329)
        try:
            canvas = self.iface.mapCanvas()
            if canvas and canvas not in canvases:
                canvases.append(canvas)
        except Exception:
            _om_record_ignored_exception(__name__, 335)
        return canvases

    def _connect_canvases(self):
        for canvas in self._map_canvases():
            if canvas in self._connected_canvases:
                continue
            try:
                canvas.xyCoordinates.connect(self._on_xy_coordinates)
                self._connected_canvases.append(canvas)
            except Exception:
                _om_record_ignored_exception(__name__, 346)

    def _disconnect_canvases(self):
        for canvas in list(self._connected_canvases):
            try:
                canvas.xyCoordinates.disconnect(self._on_xy_coordinates)
            except Exception:
                _om_record_ignored_exception(__name__, 353)
        self._connected_canvases = []

    def _on_xy_coordinates(self, point):
        if not self.enabled or not self.labels:
            return
        now = time.monotonic()
        if now - self._last_update_sec < 0.08:
            self._last_point = QgsPointXY(point)
            return
        self._last_update_sec = now
        self._last_point = QgsPointXY(point)
        try:
            canvas = self.iface.mapCanvas()
            raster_result = self._sample_visible_rasters(canvas, point)
            vector_result = self._sample_visible_vectors(canvas, point)
            point_cloud_result = self._sample_visible_point_clouds(canvas, point)
            self._update_label(raster_result, vector_result, point_cloud_result)
        except Exception:
            self._update_label(None, None, None)

    def _update_label(self, raster_result, vector_result, point_cloud_result):
        self._latest_results = {
            "raster": raster_result,
            "vector": vector_result,
            "point_cloud": point_cloud_result,
        }
        self._set_result_label("raster", "Z(R)", "Raster", raster_result)
        self._set_result_label("vector", "Z(V)", "Vector", vector_result)
        self._set_result_label("point_cloud", "Z(P)", "Point cloud", point_cloud_result)

    def _set_result_label(self, key, prefix, label_name, result):
        label = self.labels.get(key)
        if label is None:
            return
        label.setText(self._format_result(prefix, result))
        if result:
            label.setToolTip(f"{label_name}: {result['layer']} = {result['z']:.3f} m")
        else:
            label.setToolTip(f"{prefix}: --")

    def _format_result(self, prefix, result):
        if not result:
            return f"{prefix}: --"
        return f"{prefix}: {result['z']:.3f}m"

    def _visible_canvas_layers(self, canvas):
        try:
            layers = list(canvas.layers() or [])
        except Exception:
            layers = list(QgsProject.instance().mapLayers().values())
        root = QgsProject.instance().layerTreeRoot()
        visible = []
        for layer in layers:
            if not layer or not layer.isValid():
                continue
            try:
                node = root.findLayer(layer.id())
                if node is not None and not node.isVisible():
                    continue
            except Exception:
                _om_record_ignored_exception(__name__, 414)
            visible.append(layer)
        return visible

    def _sample_visible_rasters(self, canvas, project_point):
        for layer in self._visible_canvas_layers(canvas):
            if not isinstance(layer, QgsRasterLayer):
                continue
            try:
                if not self._is_elevation_raster_layer(layer):
                    continue
                layer_point = self._to_layer_point(layer, project_point)
                if not layer.extent().contains(layer_point):
                    continue
                value, ok = layer.dataProvider().sample(layer_point, 1)
                if ok and value is not None and math.isfinite(float(value)):
                    return {"z": float(value), "layer": layer.name()}
            except Exception:
                _om_record_ignored_exception(__name__, 432); continue
        return None

    def _is_elevation_raster_layer(self, layer):
        try:
            elevation_properties = layer.elevationProperties()
            if elevation_properties is not None and elevation_properties.hasElevation():
                return True
        except Exception:
            _om_record_ignored_exception(__name__, 441)
        try:
            provider_properties = layer.dataProvider().elevationProperties()
            if provider_properties is not None and provider_properties.containsElevationData():
                return True
        except Exception:
            _om_record_ignored_exception(__name__, 447)
        try:
            if QgsRasterLayerElevationProperties.layerLooksLikeDem(layer):
                return True
        except Exception:
            _om_record_ignored_exception(__name__, 452)
        return self._looks_like_single_band_elevation_raster(layer)

    def _looks_like_single_band_elevation_raster(self, layer):
        provider = layer.dataProvider()
        if provider is None:
            return False
        try:
            if provider.bandCount() != 1:
                return False
        except Exception:
            try:
                if layer.bandCount() != 1:
                    return False
            except Exception:
                return False
        try:
            if provider.colorInterpretation(1) in RASTER_IMAGE_COLOR_INTERPRETATIONS:
                return False
        except Exception:
            _om_record_ignored_exception(__name__, 472)
        try:
            data_type = provider.sourceDataType(1)
        except Exception:
            try:
                data_type = provider.dataType(1)
            except Exception:
                return False
        try:
            if data_type in RASTER_NON_ELEVATION_DATA_TYPES:
                return False
        except Exception:
            _om_record_ignored_exception(__name__, 484)
        try:
            return bool(QgsRasterBlock.typeIsNumeric(data_type))
        except Exception:
            return data_type not in RASTER_NON_ELEVATION_DATA_TYPES

    def _sample_visible_vectors(self, canvas, project_point):
        best = None
        for layer in self._visible_canvas_layers(canvas):
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                layer_point = self._to_layer_point(layer, project_point)
                tolerance = self._layer_tolerance(canvas, layer, project_point, layer_point)
                candidate = self._nearest_vector_z(layer, layer_point, tolerance)
                if candidate is None:
                    continue
                if best is None or candidate["distance"] < best["distance"]:
                    best = candidate
            except Exception:
                _om_record_ignored_exception(__name__, 504); continue
        return best

    def _sample_visible_point_clouds(self, canvas, project_point):
        best = None
        for layer in self._visible_canvas_layers(canvas):
            if not isinstance(layer, QgsPointCloudLayer):
                continue
            try:
                layer_point = self._to_layer_point(layer, project_point)
                tolerance = self._layer_tolerance(canvas, layer, project_point, layer_point)
                candidate = self._point_cloud_z(layer, layer_point, tolerance)
                if candidate is None:
                    continue
                if best is None or candidate["distance"] < best["distance"]:
                    best = candidate
            except Exception:
                _om_record_ignored_exception(__name__, 521); continue
        return best

    def _to_layer_point(self, layer, project_point):
        project = QgsProject.instance()
        source_crs = project.crs()
        dest_crs = layer.crs()
        if source_crs == dest_crs:
            return QgsPointXY(project_point)
        transform = QgsCoordinateTransform(source_crs, dest_crs, project.transformContext())
        return transform.transform(QgsPointXY(project_point))

    def _layer_tolerance(self, canvas, layer, project_point, layer_point):
        try:
            map_tol = max(canvas.mapUnitsPerPixel() * 12.0, 0.001)
        except Exception:
            map_tol = 1.0
        try:
            project = QgsProject.instance()
            source_crs = project.crs()
            dest_crs = layer.crs()
            if source_crs == dest_crs:
                return map_tol
            transform = QgsCoordinateTransform(source_crs, dest_crs, project.transformContext())
            p2 = transform.transform(QgsPointXY(project_point.x() + map_tol, project_point.y()))
            return max(abs(p2.x() - layer_point.x()), map_tol)
        except Exception:
            return map_tol

    def _nearest_vector_z(self, layer, layer_point, tolerance):
        rect = QgsRectangle(
            layer_point.x() - tolerance,
            layer_point.y() - tolerance,
            layer_point.x() + tolerance,
            layer_point.y() + tolerance,
        )
        request = QgsFeatureRequest().setFilterRect(rect).setLimit(120)
        best = None
        point_geom = QgsGeometry.fromPointXY(layer_point)
        for feature in layer.getFeatures(request):
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            candidates = (
                self._segment_interpolated_z_candidate(layer, geometry, layer_point, tolerance),
                self._nearest_vertex_z_candidate(layer, geometry, layer_point, tolerance),
                self._attribute_z_candidate(layer, feature, geometry, point_geom, tolerance),
                self._polygon_surface_z_candidate(layer, geometry, layer_point),
            )
            for candidate in candidates:
                if candidate is None:
                    continue
                if best is None or candidate["distance"] < best["distance"]:
                    best = candidate
        return best

    def _point_cloud_z(self, layer, layer_point, tolerance):
        try:
            provider = layer.dataProvider()
            if provider is None:
                return None
        except Exception:
            return None
        rect = QgsRectangle(
            layer_point.x() - tolerance,
            layer_point.y() - tolerance,
            layer_point.x() + tolerance,
            layer_point.y() + tolerance,
        )
        try:
            results = provider.identify(tolerance, QgsGeometry.fromRect(rect), QgsDoubleRange(), 20)
        except Exception:
            return None
        best = None
        for item in results or []:
            z_value = self._point_cloud_identify_z(item)
            if z_value is None:
                continue
            distance = self._point_cloud_identify_distance(item, layer_point)
            if distance > tolerance:
                continue
            if best is None or distance < best["distance"]:
                best = {"z": z_value, "layer": layer.name(), "distance": distance}
        return best

    def _point_cloud_identify_z(self, item):
        attributes = self._identify_attributes(item)
        z_value = self._mapping_value_as_float(attributes, "z")
        if z_value is not None:
            return z_value
        for name in ("Z", "z"):
            try:
                value = getattr(item, name)
                if callable(value):
                    value = value()
                z_value = self._to_finite_float(value)
                if z_value is not None:
                    return z_value
            except Exception:
                _om_record_ignored_exception(__name__, 620); continue
        return None

    def _point_cloud_identify_distance(self, item, layer_point):
        attributes = self._identify_attributes(item)
        x_value = self._mapping_value_as_float(attributes, "x")
        y_value = self._mapping_value_as_float(attributes, "y")
        if x_value is None or y_value is None:
            return 0.0
        try:
            return math.hypot(x_value - layer_point.x(), y_value - layer_point.y())
        except Exception:
            return 0.0

    def _identify_attributes(self, item):
        if isinstance(item, dict):
            return item
        if isinstance(item, (list, tuple)):
            try:
                return dict(item)
            except Exception:
                return {}
        for name in ("attributes", "mAttributes", "attributeMap"):
            try:
                value = getattr(item, name)
                if callable(value):
                    value = value()
                if isinstance(value, dict):
                    return value
            except Exception:
                _om_record_ignored_exception(__name__, 650); continue
        return {}

    def _mapping_value_as_float(self, mapping, target_name):
        if not isinstance(mapping, dict):
            return None
        target = str(target_name).strip().lower()
        for key, value in mapping.items():
            if str(key).strip().lower() != target:
                continue
            result = self._to_finite_float(value)
            if result is not None:
                return result
        return None

    def _segment_interpolated_z_candidate(self, layer, geometry, layer_point, tolerance):
        try:
            sqr_distance, closest_point, after_vertex, _left_of = geometry.closestSegmentWithContext(layer_point)
        except Exception:
            return None
        try:
            if sqr_distance < 0:
                return None
            distance = math.sqrt(max(float(sqr_distance), 0.0))
        except Exception:
            return None
        if distance > tolerance:
            return None
        try:
            before_vertex, _after_next = geometry.adjacentVertices(after_vertex)
            if before_vertex < 0 or after_vertex < 0:
                return None
            p1 = geometry.vertexAt(before_vertex)
            p2 = geometry.vertexAt(after_vertex)
        except Exception:
            return None
        z1 = self._point_z(p1)
        z2 = self._point_z(p2)
        if z1 is None or z2 is None:
            return None
        try:
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            length_sq = dx * dx + dy * dy
            if length_sq <= 0:
                z_value = z1
            else:
                t = ((closest_point.x() - p1.x()) * dx + (closest_point.y() - p1.y()) * dy) / length_sq
                t = max(0.0, min(1.0, t))
                z_value = z1 + (z2 - z1) * t
            if math.isfinite(float(z_value)):
                return {"z": float(z_value), "layer": layer.name(), "distance": distance}
        except Exception:
            return None
        return None

    def _nearest_vertex_z_candidate(self, layer, geometry, layer_point, tolerance):
        best = None
        for vertex in geometry.vertices():
            try:
                z_value = self._point_z(vertex)
                if z_value is None:
                    continue
                distance = math.hypot(vertex.x() - layer_point.x(), vertex.y() - layer_point.y())
                if distance > tolerance:
                    continue
                if best is None or distance < best["distance"]:
                    best = {"z": z_value, "layer": layer.name(), "distance": distance}
            except Exception:
                _om_record_ignored_exception(__name__, 719); continue
        return best

    def _attribute_z_candidate(self, layer, feature, geometry, point_geom, tolerance):
        z_value = self._feature_z_attribute(layer, feature)
        if z_value is None:
            return None
        try:
            distance = float(geometry.distance(point_geom))
        except Exception:
            return None
        if distance > tolerance:
            return None
        return {"z": z_value, "layer": layer.name(), "distance": distance}

    def _polygon_surface_z_candidate(self, layer, geometry, layer_point):
        try:
            if not geometry.contains(layer_point):
                return None
        except Exception:
            return None
        z_value = self._polygon_surface_z(geometry, layer_point)
        if z_value is None:
            return None
        return {"z": z_value, "layer": layer.name(), "distance": 0.0}

    def _polygon_surface_z(self, geometry, layer_point):
        vertices = []
        seen_xy = set()
        for vertex in geometry.vertices():
            z_value = self._point_z(vertex)
            if z_value is None:
                continue
            key = (round(float(vertex.x()), 9), round(float(vertex.y()), 9))
            if key in seen_xy:
                continue
            seen_xy.add(key)
            vertices.append((float(vertex.x()), float(vertex.y()), float(z_value)))
        if not vertices:
            return None
        z_values = [vertex[2] for vertex in vertices]
        if max(z_values) - min(z_values) <= 0.001:
            return sum(z_values) / len(z_values)
        if len(vertices) < 3:
            return None
        return self._interpolate_polygon_z_from_vertices(vertices, layer_point)

    def _interpolate_polygon_z_from_vertices(self, vertices, layer_point):
        point_x = float(layer_point.x())
        point_y = float(layer_point.y())
        nearest = sorted(
            vertices,
            key=lambda vertex: (vertex[0] - point_x) * (vertex[0] - point_x)
            + (vertex[1] - point_y) * (vertex[1] - point_y),
        )[:15]
        best_inside = None
        best_plane = None
        for i in range(len(nearest) - 2):
            for j in range(i + 1, len(nearest) - 1):
                for k in range(j + 1, len(nearest)):
                    result = self._triangle_interpolated_z(nearest[i], nearest[j], nearest[k], point_x, point_y)
                    if result is None:
                        continue
                    z_value, inside_score, distance_score = result
                    if inside_score >= -1.0e-9:
                        if best_inside is None or distance_score < best_inside[1]:
                            best_inside = (z_value, distance_score)
                    elif best_plane is None or distance_score < best_plane[1]:
                        best_plane = (z_value, distance_score)
        if best_inside is not None:
            return best_inside[0]
        if best_plane is not None:
            return best_plane[0]
        return None

    def _triangle_interpolated_z(self, p1, p2, p3, point_x, point_y):
        x1, y1, z1 = p1
        x2, y2, z2 = p2
        x3, y3, z3 = p3
        denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(denominator) <= 1.0e-12:
            return None
        a = ((y2 - y3) * (point_x - x3) + (x3 - x2) * (point_y - y3)) / denominator
        b = ((y3 - y1) * (point_x - x3) + (x1 - x3) * (point_y - y3)) / denominator
        c = 1.0 - a - b
        z_value = a * z1 + b * z2 + c * z3
        if not math.isfinite(float(z_value)):
            return None
        inside_score = min(a, b, c)
        distance_score = max(
            (x1 - point_x) * (x1 - point_x) + (y1 - point_y) * (y1 - point_y),
            (x2 - point_x) * (x2 - point_x) + (y2 - point_y) * (y2 - point_y),
            (x3 - point_x) * (x3 - point_x) + (y3 - point_y) * (y3 - point_y),
        )
        return float(z_value), inside_score, distance_score

    def _feature_z_attribute(self, layer, feature):
        try:
            fields = layer.fields()
        except Exception:
            return None
        for index, field in enumerate(fields):
            try:
                name = field.name()
            except Exception:
                _om_record_ignored_exception(__name__, 824); continue
            if self._normalize_z_field_name(name) not in VECTOR_Z_FIELD_NAMES:
                continue
            try:
                value = feature.attribute(index)
            except Exception:
                try:
                    value = feature[name]
                except Exception:
                    value = None
            z_value = self._to_finite_float(value)
            if z_value is not None:
                return z_value
        return None

    def _normalize_z_field_name(self, name):
        text = str(name).strip().lower()
        for char in (" ", "-", ".", "＿"):
            text = text.replace(char, "_")
        return text

    def _point_z(self, point):
        try:
            if not point.is3D():
                return None
            return self._to_finite_float(point.z())
        except Exception:
            return None

    def _to_finite_float(self, value):
        if value is None:
            return None
        try:
            text = str(value).strip()
            if not text:
                return None
            number = float(text.replace(",", ""))
            if math.isfinite(number):
                return number
        except Exception:
            return None
        return None
