from .diagnostics import record_ignored_exception as _om_record_ignored_exception
"""Editing helpers for the OrthoManager inspection tab.

This mixin keeps edit-mode and duplicate-vertex handling out of
inspection_tab.py while preserving the existing InspectionTabWidget API.
"""

from .i18n import tr_text
from qgis.PyQt.QtCore import QEvent, QTimer, Qt
from qgis.PyQt.QtGui import QColor, QKeyEvent
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    Qgis,
)
from qgis.gui import QgsRubberBand, QgsVertexMarker

from .inspection_constants import INSPECTION_PROP_PREFIX


class InspectionEditingMixin:
    def start_edit(self):
        if self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon"):
            self.set_status(tr_text("移層中です。パンで解除してください"))
            return
        self.clear_inspection_selection()
        self.clear_edit_overlap_candidates()
        self.clear_direct_overlap_vertex_edit()
        self.clear_edit_overlap_anchor()
        self.suspend_edit_hover_prepare = False
        self.operation_mode = "edit"
        self.ensure_map_tool()
        self.set_status(tr_text("編集モード: 左クリックは通常編集。重複頂点は右クリックで対象レイヤを切替"))

    def clear_edit_overlap_candidates(self):
        self.edit_overlap_candidates = []
        self.edit_overlap_index = -1
        self.edit_overlap_point = None

    def clear_direct_overlap_vertex_edit(self, clear_candidates=True):
        if clear_candidates:
            self.edit_overlap_vertex_candidates = []
            self.edit_overlap_vertex_index = -1
            self.ignore_next_direct_overlap_release = False
            self.just_finished_direct_overlap_vertex_edit = False
        self.clear_direct_overlap_vertex_preview()
        marker = getattr(self, "edit_overlap_vertex_marker", None)
        if marker:
            try:
                self.iface.mapCanvas().scene().removeItem(marker)
            except Exception:
                try:
                    marker.hide()
                    marker.deleteLater()
                except Exception:
                    _om_record_ignored_exception(__name__, 62)
        self.edit_overlap_vertex_marker = None

    def clear_edit_overlap_anchor(self):
        self.edit_overlap_anchor_point = None
        self.edit_overlap_anchor_candidates = []
        self.edit_overlap_anchor_index = -1

    def has_direct_overlap_vertex_edit(self):
        candidates = getattr(self, "edit_overlap_vertex_candidates", []) or []
        index = getattr(self, "edit_overlap_vertex_index", -1)
        return 0 <= index < len(candidates)

    def current_direct_overlap_vertex_candidate(self):
        if not self.has_direct_overlap_vertex_edit():
            return None
        return self.edit_overlap_vertex_candidates[self.edit_overlap_vertex_index]

    def overlap_vertex_candidates_cross_layers(self, candidates):
        layer_ids = set()
        for candidate in candidates or []:
            layer = candidate.get("layer") if isinstance(candidate, dict) else None
            if layer:
                try:
                    layer_ids.add(layer.id())
                except Exception:
                    _om_record_ignored_exception(__name__, 88)
        return len(layer_ids) > 1

    def map_point_to_layer_point(self, layer, point):
        layer_point = QgsPointXY(point)
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
                transform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                layer_point = transform.transform(layer_point)
        except Exception:
            _om_record_ignored_exception(__name__, 100)
        return layer_point

    def layer_point_to_map_point(self, layer, point):
        map_point = QgsPointXY(point)
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                map_point = transform.transform(map_point)
        except Exception:
            _om_record_ignored_exception(__name__, 112)
        return map_point

    def find_overlap_vertex_candidates_at(self, point, tolerance_factor=12):
        self.refresh_pending_data_change_layers()
        canvas = self.iface.mapCanvas()
        tolerance = canvas.mapUnitsPerPixel() * tolerance_factor
        candidates = []
        seen = set()
        for layer in reversed(self.selectable_inspection_layers()):
            layer_point = self.map_point_to_layer_point(layer, point)
            rect = QgsRectangle(
                layer_point.x() - tolerance,
                layer_point.y() - tolerance,
                layer_point.x() + tolerance,
                layer_point.y() + tolerance,
            )
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom:
                    continue
                try:
                    vertex_point, vertex_index, _prev_index, _next_index, sqr_dist = geom.closestVertex(layer_point)
                except Exception:
                    _om_record_ignored_exception(__name__, 137); continue
                if vertex_index < 0 or sqr_dist > tolerance * tolerance:
                    continue
                key = (layer.id(), feature.id(), vertex_index)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "key": key,
                    "layer": layer,
                    "feature_id": feature.id(),
                    "vertex_index": vertex_index,
                    "layer_point": QgsPointXY(vertex_point),
                    "map_point": self.layer_point_to_map_point(layer, vertex_point),
                })
        return candidates

    def remember_edit_overlap_anchor_at(self, point):
        candidates = self.find_overlap_vertex_candidates_at(point, tolerance_factor=12)
        if len(candidates) <= 1:
            self.clear_edit_overlap_anchor()
            return False
        index = 0
        if self.active_layer_id:
            for candidate_index, candidate in enumerate(candidates):
                layer = candidate.get("layer")
                if layer and layer.id() == self.active_layer_id:
                    index = candidate_index
                    break
        self.edit_overlap_anchor_point = QgsPointXY(point)
        self.edit_overlap_anchor_candidates = candidates
        self.edit_overlap_anchor_index = index
        return True

    def _set_direct_overlap_vertex_marker(self, candidate):
        if not candidate:
            return
        canvas = self.iface.mapCanvas()
        marker = getattr(self, "edit_overlap_vertex_marker", None)
        if marker is None:
            marker = QgsVertexMarker(canvas)
            marker.setColor(QColor("#ff8c00"))
            marker.setIconSize(14)
            marker.setPenWidth(4)
            try:
                marker.setIconType(QgsVertexMarker.IconType.ICON_BOX)
            except Exception:
                try:
                    marker.setIconType(QgsVertexMarker.ICON_BOX)
                except Exception:
                    _om_record_ignored_exception(__name__, 187)
            try:
                marker.setZValue(1300)
            except Exception:
                _om_record_ignored_exception(__name__, 191)
            self.edit_overlap_vertex_marker = marker
        marker.setCenter(candidate["map_point"])
        marker.show()

    def begin_direct_overlap_vertex_edit_at(self, point):
        return False

    def switch_direct_overlap_vertex_candidate_at(self, point):
        anchor_point = self.edit_overlap_anchor_point or point
        if not anchor_point:
            return False
        candidates = self.find_overlap_vertex_candidates_at(anchor_point, tolerance_factor=12)
        if len(candidates) <= 1:
            self.clear_direct_overlap_vertex_edit()
            return False

        current_index = -1
        anchor_index = getattr(self, "edit_overlap_anchor_index", -1)
        if 0 <= anchor_index < len(candidates):
            current_index = anchor_index

        if current_index < 0 and self.active_layer_id:
            for candidate_index, candidate in enumerate(candidates):
                layer = candidate.get("layer")
                if layer and layer.id() == self.active_layer_id:
                    current_index = candidate_index
                    break

        next_index = current_index + 1
        if next_index >= len(candidates):
            self.clear_direct_overlap_vertex_edit()
            return False

        candidate = candidates[next_index]
        layer = candidate["layer"]
        self.clear_direct_overlap_vertex_edit()
        self.stop_qgis_vertex_tool_for_direct_overlap()
        self.commit_other_edit_layers_for_active_vertex_tool(layer)
        if not self.prepare_layer_edit(layer, activate_tool=False):
            return False
        self.apply_edit_preview_width(layer)
        self.trigger_vertex_tool(layer, force_restart=True)
        QTimer.singleShot(80, lambda l=layer: self.trigger_vertex_tool(l, force_restart=False))
        self.clear_inspection_selection()
        self.clear_edit_overlap_candidates()
        self.edit_overlap_anchor_point = QgsPointXY(anchor_point)
        self.edit_overlap_anchor_candidates = candidates
        self.edit_overlap_anchor_index = next_index
        self.suspend_edit_hover_prepare = True
        self.set_status(
            tr_text(f"重複頂点切替: {next_index + 1}/{len(candidates)} {self.display_layer_name(layer)}。"
            "対象レイヤを切替えました。頂点を左クリックして移動してください")
        )
        return True

    def cycle_direct_overlap_vertex_candidate(self):
        candidates = list(getattr(self, "edit_overlap_vertex_candidates", []) or [])
        if len(candidates) <= 1:
            return False
        next_index = getattr(self, "edit_overlap_vertex_index", -1) + 1
        if next_index >= len(candidates):
            self.clear_direct_overlap_vertex_edit()
            return False
        candidate = candidates[next_index]
        layer = candidate["layer"]
        if not self.prepare_layer_edit(layer, activate_tool=False):
            self.edit_overlap_vertex_index = next_index
            return True
        self.edit_overlap_vertex_index = next_index
        self._set_direct_overlap_vertex_marker(candidate)
        self.clear_direct_overlap_vertex_preview()
        self.set_status(
            tr_text(f"重複頂点切替: {next_index + 1}/{len(candidates)} {self.display_layer_name(layer)}。"
            "ドラッグで移動")
        )
        return True

    def clear_direct_overlap_vertex_preview(self):
        band = getattr(self, "edit_overlap_vertex_preview_band", None)
        if band:
            try:
                self.iface.mapCanvas().scene().removeItem(band)
            except Exception:
                try:
                    band.hide()
                    band.deleteLater()
                except Exception:
                    _om_record_ignored_exception(__name__, 279)
        self.edit_overlap_vertex_preview_band = None

    def _geometry_with_direct_overlap_vertex(self, candidate, map_point):
        if not candidate:
            return None, None, None
        layer = candidate["layer"]
        feature_id = candidate["feature_id"]
        feature = next(layer.getFeatures(QgsFeatureRequest().setFilterFids([feature_id])), None)
        if feature is None:
            return layer, None, None
        geom = QgsGeometry(feature.geometry())
        if not geom:
            return layer, feature, None
        layer_point = self.map_point_to_layer_point(layer, map_point)
        try:
            if not geom.moveVertex(layer_point.x(), layer_point.y(), candidate["vertex_index"]):
                return layer, feature, None
        except Exception:
            return layer, feature, None
        return layer, feature, geom

    def update_direct_overlap_vertex_preview(self, map_point):
        candidate = self.current_direct_overlap_vertex_candidate()
        if not candidate:
            return
        layer, _feature, geom = self._geometry_with_direct_overlap_vertex(candidate, map_point)
        if not layer or not geom:
            return
        self.clear_direct_overlap_vertex_preview()
        band = QgsRubberBand(self.iface.mapCanvas(), layer.geometryType())
        color = QColor("#ff8c00")
        fill = QColor("#ff8c00")
        fill.setAlpha(35 if layer.geometryType() == Qgis.GeometryType.Polygon else 0)
        try:
            band.setStrokeColor(color)
            band.setFillColor(fill)
            if layer.geometryType() == Qgis.GeometryType.Polygon:
                band.setBrushStyle(Qt.BrushStyle.SolidPattern)
        except Exception:
            band.setColor(color)
        band.setWidth(self.preview_rubber_band_width(layer))
        try:
            band.setToGeometry(geom, layer)
        except Exception:
            return
        band.show()
        self.edit_overlap_vertex_preview_band = band
        preview_candidate = dict(candidate)
        preview_candidate["map_point"] = QgsPointXY(map_point)
        self._set_direct_overlap_vertex_marker(preview_candidate)

    def finish_direct_overlap_vertex_move(self, map_point):
        candidate = self.current_direct_overlap_vertex_candidate()
        if not candidate:
            return False
        layer = candidate["layer"]
        feature_id = candidate["feature_id"]
        if not self.prepare_layer_edit(layer, activate_tool=False):
            self.clear_direct_overlap_vertex_preview()
            return False
        layer_point = self.map_point_to_layer_point(layer, map_point)
        ok = False
        try:
            layer.beginEditCommand("重複頂点移動")
        except Exception:
            _om_record_ignored_exception(__name__, 345)
        try:
            ok = bool(layer.moveVertex(layer_point.x(), layer_point.y(), feature_id, candidate["vertex_index"]))
            updated_idx = layer.fields().indexOf("updated_at")
            if updated_idx >= 0:
                layer.changeAttributeValue(feature_id, updated_idx, self.now_text())
        except Exception:
            ok = False
        try:
            if ok:
                layer.endEditCommand()
            else:
                layer.destroyEditCommand()
        except Exception:
            _om_record_ignored_exception(__name__, 359)
        self.clear_direct_overlap_vertex_preview()
        if not ok:
            self.set_status(tr_text("重複頂点移動: 頂点を更新できませんでした"))
            return False
        map_point_xy = QgsPointXY(map_point)
        candidate["layer_point"] = layer_point
        candidate["map_point"] = map_point_xy
        self._set_direct_overlap_vertex_marker(candidate)
        try:
            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
        except Exception:
            _om_record_ignored_exception(__name__, 372)
        self.set_status(
            tr_text(f"重複頂点移動: {self.display_layer_name(layer)}。右クリックで次の重複頂点へ切替")
        )
        return True

    def direct_overlap_vertex_snap_point(self, map_point, snap_pixel=None, tolerance_factor=18):
        current = self.current_direct_overlap_vertex_candidate()
        if not current:
            return None
        canvas = self.iface.mapCanvas()
        tolerance = canvas.mapUnitsPerPixel() * tolerance_factor
        pixel_tolerance = tolerance_factor
        best_point = None
        best_dist = None
        current_key = current.get("key")
        coord_transform = None
        if snap_pixel is not None:
            try:
                coord_transform = canvas.getCoordinateTransform()
            except Exception:
                coord_transform = None
        for layer in self.direct_overlap_vertex_snap_layers():
            layer_point = self.map_point_to_layer_point(layer, map_point)
            rect = QgsRectangle(
                layer_point.x() - tolerance,
                layer_point.y() - tolerance,
                layer_point.x() + tolerance,
                layer_point.y() + tolerance,
            )
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom:
                    continue
                try:
                    vertex_point, vertex_index, _prev_index, _next_index, sqr_dist = geom.closestVertex(layer_point)
                except Exception:
                    _om_record_ignored_exception(__name__, 410); continue
                if vertex_index < 0 or sqr_dist > tolerance * tolerance:
                    continue
                key = (layer.id(), feature.id(), vertex_index)
                if key == current_key:
                    continue
                snap_point = self.layer_point_to_map_point(layer, vertex_point)
                if coord_transform is not None and snap_pixel is not None:
                    try:
                        candidate_pixel = coord_transform.transform(snap_point)
                        dx = candidate_pixel.x() - snap_pixel.x()
                        dy = candidate_pixel.y() - snap_pixel.y()
                        dist = dx * dx + dy * dy
                        if dist > pixel_tolerance * pixel_tolerance:
                            continue
                    except Exception:
                        dist = (snap_point.x() - map_point.x()) ** 2 + (snap_point.y() - map_point.y()) ** 2
                else:
                    dist = (snap_point.x() - map_point.x()) ** 2 + (snap_point.y() - map_point.y()) ** 2
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_point = QgsPointXY(snap_point)
        return best_point

    def direct_overlap_vertex_snap_layers(self):
        layers = []
        seen_ids = set()

        def add_layer(layer):
            if not layer or layer.id() in seen_ids:
                return
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                return
            try:
                if not self.layer_has_visible_tree_node(layer.id()):
                    return
            except Exception:
                _om_record_ignored_exception(__name__, 447)
            seen_ids.add(layer.id())
            layers.append(layer)

        for layer in self.selectable_inspection_layers():
            add_layer(layer)
        try:
            project_layers = QgsProject.instance().mapLayers().values()
        except Exception:
            project_layers = []
        for layer in project_layers:
            add_layer(layer)
        return layers

    def find_edit_layer_candidates_at(self, point, tolerance_factor=12):
        self.refresh_pending_data_change_layers()
        rect = self._search_rect(point, tolerance_factor=tolerance_factor)
        rect_geom = QgsGeometry.fromRect(rect)
        point_geom = QgsGeometry.fromPointXY(point)
        tolerance = max(rect.width(), rect.height()) / 2.0
        edge_candidates = []
        fill_candidates = []
        seen_layer_ids = set()

        def add_candidate(target, layer, feature, area=0):
            if not layer or not feature:
                return
            if layer.id() in seen_layer_ids:
                return
            seen_layer_ids.add(layer.id())
            target.append((area, layer, feature))

        for layer in reversed(self.selectable_inspection_layers()):
            request = QgsFeatureRequest().setFilterRect(rect)
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom:
                    continue
                if layer.geometryType() == Qgis.GeometryType.Polygon:
                    if self.polygon_edges_hit_rect(geom, rect_geom):
                        add_candidate(edge_candidates, layer, feature)
                        break
                    if geom.contains(point_geom) or geom.intersects(rect_geom):
                        try:
                            area = geom.area()
                        except Exception:
                            area = 0
                        fill_candidates.append((area, layer, feature))
                elif geom.intersects(rect_geom):
                    add_candidate(edge_candidates, layer, feature)
                    break
                else:
                    try:
                        if geom.distance(point_geom) <= tolerance:
                            add_candidate(edge_candidates, layer, feature)
                            break
                    except Exception:
                        _om_record_ignored_exception(__name__, 504)

        if edge_candidates:
            return [(layer, feature) for _area, layer, feature in edge_candidates]

        fill_candidates.sort(key=lambda item: item[0])
        result = []
        seen_layer_ids = set()
        for _area, layer, feature in fill_candidates:
            if layer.id() in seen_layer_ids:
                continue
            seen_layer_ids.add(layer.id())
            result.append((layer, feature))
        return result

    def set_edit_overlap_candidates(self, point, candidates, active_layer):
        self.edit_overlap_point = QgsPointXY(point) if point is not None else None
        self.edit_overlap_candidates = list(candidates or [])
        self.edit_overlap_index = -1
        if active_layer:
            for index, (candidate_layer, _feature) in enumerate(self.edit_overlap_candidates):
                if candidate_layer.id() == active_layer.id():
                    self.edit_overlap_index = index
                    break

    def cycle_edit_overlap_candidate(self):
        candidates = list(getattr(self, "edit_overlap_candidates", []) or [])
        if len(candidates) <= 1:
            return False
        next_index = getattr(self, "edit_overlap_index", -1) + 1
        if next_index >= len(candidates):
            self.clear_edit_overlap_candidates()
            return False
        layer, _feature = candidates[next_index]
        if not self.prepare_layer_edit(layer, activate_tool=True):
            self.edit_overlap_index = next_index
            return True
        self.edit_overlap_index = next_index
        self.edit_overlap_candidates = candidates
        self.set_status(tr_text(f"重複頂点切替: {next_index + 1}/{len(candidates)} {self.display_layer_name(layer)}"))
        return True

    def edit_feature_at(self, point):
        layer, feature = self.find_feature_at(point, tolerance_factor=12)
        if not layer:
            self.set_status(tr_text("編集対象が見つかりません"))
            return
        self.clear_inspection_selection()
        self._activate_vertex_edit(layer)
        self.operation_mode = "create"

    def prepare_edit_layer_at(self, point, activate_tool=True, quiet=False):
        if self.has_direct_overlap_vertex_edit():
            return True
        candidates = self.find_edit_layer_candidates_at(point, tolerance_factor=12)
        layer = candidates[0][0] if candidates else None
        candidate_layer_ids = [candidate_layer.id() for candidate_layer, _feature in candidates]
        previous_layer_ids = [
            candidate_layer.id()
            for candidate_layer, _feature in getattr(self, "edit_overlap_candidates", []) or []
        ]
        keep_active_layer = (
            candidates
            and self.active_layer_id in candidate_layer_ids
            and (
                candidate_layer_ids == previous_layer_ids
                or getattr(self, "edit_overlap_anchor_point", None) is not None
            )
        )
        if keep_active_layer:
            for candidate_layer, _feature in candidates:
                if candidate_layer.id() == self.active_layer_id:
                    layer = candidate_layer
                    break
        if not layer:
            if not quiet:
                self.set_status(tr_text("編集対象が見つかりません"))
            self.clear_edit_overlap_candidates()
            return False
        self.clear_inspection_selection()
        if not self.prepare_layer_edit(layer, activate_tool=activate_tool):
            return False
        self.set_edit_overlap_candidates(point, candidates, layer)
        if not quiet:
            if len(candidates) > 1:
                self.set_status(tr_text(f"編集モード: {self.display_layer_name(layer)}（重複 {len(candidates)} 件。右クリックで切替）"))
            else:
                self.set_status(tr_text(f"編集モード: {self.display_layer_name(layer)}"))
        return True

    def edit_selected_feature(self):
        targets = self.selected_vector_targets()
        if len(targets) != 1 or len(targets[0][1]) != 1:
            return False
        self.clear_inspection_selection()
        return self._activate_vertex_edit(targets[0][0])

    def _activate_vertex_edit(self, layer):
        if self.block_locked_layers([layer], "編集できません", "図形を編集"):
            return False
        self.clear_edit_overlap_candidates()
        self.clear_direct_overlap_vertex_edit()
        if not self.prepare_layer_edit(layer, activate_tool=True):
            return False
        self.set_status(tr_text(f"編集モード: {self.display_layer_name(layer)}"))
        return True

    def edit_layer_detail(self, layer):
        details = []
        try:
            details.append(f"provider={layer.providerType()}")
        except Exception:
            _om_record_ignored_exception(__name__, 616)
        try:
            if layer.readOnly():
                details.append("readOnly=True")
        except Exception:
            _om_record_ignored_exception(__name__, 621)
        try:
            if not layer.supportsEditing():
                details.append("supportsEditing=False")
        except Exception:
            _om_record_ignored_exception(__name__, 626)
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
                    _om_record_ignored_exception(__name__, 637)
        except Exception:
            _om_record_ignored_exception(__name__, 639)
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
            _om_record_ignored_exception(__name__, 653)

    def prepare_layer_edit(self, layer, activate_tool=False):
        if self.block_locked_layers([layer], "編集できません", "図形を編集"):
            return False
        try:
            needs_refresh = layer.id() in self._layers_needing_edit_refresh
        except Exception:
            needs_refresh = False
        if needs_refresh and not layer.isEditable():
            self.refresh_vector_layer_after_data_change(layer, reload_data=True, mark_edit_refresh=False)
            try:
                self._layers_needing_edit_refresh.discard(layer.id())
            except Exception:
                _om_record_ignored_exception(__name__, 667)
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
                    _om_record_ignored_exception(__name__, 678)
                if not layer.supportsEditing():
                    detail = self.edit_layer_detail(layer)
                    self.set_status(tr_text(f"編集開始できません: {self.display_layer_name(layer)}（{detail}）"))
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
                    self.set_status(tr_text(f"編集開始できません: {self.display_layer_name(layer)}（{detail}）"))
                    self.log_edit_start_failed(layer, "startEditing=False")
                    return False
            except Exception as exc:
                self.set_status(tr_text(f"編集開始できません: {self.display_layer_name(layer)}（{exc}）"))
                self.log_edit_start_failed(layer, f"例外: {exc}")
                return False
        if not activate_tool:
            return True
        self.apply_edit_preview_width(layer)
        QTimer.singleShot(0, lambda l=layer: self.trigger_vertex_tool(l, force_restart=True))
        return True

    def set_qgis_active_edit_layer(self, layer):
        try:
            self.iface.setActiveLayer(layer)
        except Exception:
            _om_record_ignored_exception(__name__, 713)
        try:
            view = self.iface.layerTreeView()
            if view:
                view.setCurrentLayer(layer)
        except Exception:
            _om_record_ignored_exception(__name__, 719)
        try:
            nodes = self.layer_tree_nodes_for_layer(layer.id())
            visible_nodes = [node for _parent, node in nodes if self.layer_tree_node_visible(node)]
            target_node = visible_nodes[0] if visible_nodes else (nodes[0][1] if nodes else None)
            if target_node is not None:
                target_node.setItemVisibilityChecked(True)
        except Exception:
            _om_record_ignored_exception(__name__, 727)

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
                _om_record_ignored_exception(__name__, 750)
        return False

    def forward_qgis_vertex_tool_key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        canvas = self.iface.mapCanvas()
        if not canvas:
            return False
        press = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
        release = QKeyEvent(QEvent.Type.KeyRelease, key, modifiers)
        sent = False
        try:
            tool = canvas.mapTool()
            if tool is not None and tool is not self.map_tool:
                tool.keyPressEvent(press)
                tool.keyReleaseEvent(release)
                sent = True
        except Exception:
            sent = False
        if not sent:
            for target in (canvas, getattr(canvas, "viewport", lambda: None)()):
                if target is None:
                    continue
                try:
                    QApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyPress, key, modifiers))
                    QApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyRelease, key, modifiers))
                    sent = True
                    break
                except Exception:
                    _om_record_ignored_exception(__name__, 778)
        try:
            QApplication.processEvents()
        except Exception:
            _om_record_ignored_exception(__name__, 782)
        return sent

    def cancel_qgis_vertex_tool_interaction(self):
        return self.forward_qgis_vertex_tool_key(Qt.Key.Key_Escape)

    def commit_other_edit_layers_for_active_vertex_tool(self, active_layer):
        active_layer_id = active_layer.id() if active_layer is not None else None
        touched_layers = []
        for layer in self.inspection_layers():
            try:
                if layer.id() == active_layer_id or not layer.isEditable():
                    continue
                if layer.commitChanges():
                    touched_layers.append(layer)
                else:
                    layer.rollBack()
            except Exception as exc:
                try:
                    QgsMessageLog.logMessage(
                        f"INSPECTION_EDIT_OTHER_LAYER_SAVE_FAILED "
                        f"layer={self.display_layer_name(layer)} error={exc}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                except Exception:
                    _om_record_ignored_exception(__name__, 808)
        for layer in touched_layers:
            self.refresh_vector_layer_after_data_change(layer, reload_data=True, mark_edit_refresh=False)
            try:
                self._layers_needing_edit_refresh.discard(layer.id())
            except Exception:
                _om_record_ignored_exception(__name__, 814)

    def stop_qgis_vertex_tool_for_direct_overlap(self):
        self.cancel_qgis_vertex_tool_interaction()
        QApplication.processEvents()
        for action_name in ("actionVertexToolActiveLayer", "actionVertexTool"):
            try:
                action = getattr(self.iface, action_name)()
                if action and action.isChecked():
                    action.trigger()
                    QApplication.processEvents()
            except Exception:
                _om_record_ignored_exception(__name__, 826)
        self.cancel_qgis_vertex_tool_interaction()
        QApplication.processEvents()
        self.ensure_map_tool()
        try:
            self.iface.mapCanvas().refresh()
        except Exception:
            _om_record_ignored_exception(__name__, 833)

    def finish_edit_mode(self, defer_pan=False, switch_to_pan_after=True, return_to_selection_after=True):
        self.clear_edit_overlap_candidates()
        self.clear_direct_overlap_vertex_edit()
        self.clear_edit_overlap_anchor()
        self.suspend_edit_hover_prepare = False
        saved = 0
        touched_layers = []
        for layer in self.inspection_layers():
            try:
                if layer.isEditable():
                    if layer.commitChanges():
                        saved += 1
                        touched_layers.append(layer)
                    else:
                        layer.rollBack()
                layer.removeSelection()
            except Exception:
                _om_record_ignored_exception(__name__, 852)
        for layer in touched_layers:
            self.refresh_vector_layer_after_data_change(layer, reload_data=True, mark_edit_refresh=False)
            try:
                self._layers_needing_edit_refresh.discard(layer.id())
            except Exception:
                _om_record_ignored_exception(__name__, 858)
        self.restore_edit_preview_width()
        self.refresh_counts()
        if switch_to_pan_after:
            if return_to_selection_after:
                self.operation_mode = "pan_pending"
                if defer_pan:
                    QTimer.singleShot(160, lambda: self.return_to_last_selection_mode("編集保存完了"))
                else:
                    self.return_to_last_selection_mode("編集保存完了")
                self.set_status(tr_text(f"編集保存完了: {saved} レイヤ"))
                return
            if defer_pan:
                self.operation_mode = "pan_pending"
                QTimer.singleShot(160, self.switch_to_pan)
            else:
                self.operation_mode = "pan_pending"
                self.switch_to_pan()
        self.set_status(tr_text(f"編集保存完了: {saved} レイヤ"))
