from .i18n import tr_text
import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorLayer,
    Qgis,
)

try:
    from osgeo import ogr
except Exception:
    ogr = None


GUIDE_ROLE_LINE = "guide_line"
GUIDE_ROLE_DONE = "guide_done"
GUIDE_ROLE_AREA = "guide_area"
CONNECT_TOLERANCE_M = 5.0


class InspectionGuideLineBuilder:
    def __init__(self, tab):
        self.tab = tab

    def polygon_layer_candidates(self):
        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                if not self.tab.is_qgis_layer_import_candidate(layer):
                    continue
                if self.tab.qgis_layer_geom_type(layer) != "polygon":
                    continue
                layers.append(layer)
            except Exception:
                continue
        layers.sort(key=lambda layer: layer.name())
        return layers

    def _source_layer_crs_is_valid(self, layer):
        try:
            crs = layer.crs()
            return bool(crs and crs.isValid())
        except Exception:
            return False

    def create_mesh(self, source_layer, id_field_name, cols, rows):
        if ogr is None:
            QMessageBox.critical(self.tab, tr_text("検査メッシュ作成"), tr_text("GDAL/OGRを読み込めないため検査メッシュを作成できません。"))
            return None
        if not source_layer or not source_layer.isValid():
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("図郭ポリゴンレイヤを選択してください。"))
            return None
        if not id_field_name or source_layer.fields().indexOf(id_field_name) < 0:
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("図郭IDフィールドを選択してください。"))
            return None
        if cols <= 0 or rows <= 0:
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("横・縦の分割数を正しく入力してください。"))
            return None
        if cols > 999 or rows > 999:
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("横・縦の分割数は999以下にしてください。"))
            return None
        if not self.tab.ensure_project_metric_crs_for_inspection():
            return None
        if not self._source_layer_crs_is_valid(source_layer):
            QMessageBox.warning(
                self.tab,
                tr_text("検査メッシュ作成"),
                tr_text("選択した図郭ポリゴンレイヤの座標系が未設定です。\n先にレイヤの座標系を設定してください。"),
            )
            return None
        if not self.tab.ensure_gpkg_path(self._target_inspection_type()):
            return None

        tile_items = self._source_tile_items(source_layer, id_field_name)
        if not tile_items:
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("有効な図郭ポリゴンと図郭IDを取得できませんでした。"))
            return None

        mesh_features = []
        total = cols * rows
        pad = len(str(total))
        for tile in tile_items:
            mesh_features.extend(self._mesh_features_for_tile(tile["geometry"], tile["tile_name"], cols, rows, pad))

        if not mesh_features:
            QMessageBox.warning(self.tab, tr_text("検査メッシュ作成"), tr_text("検査メッシュポリゴンを作成できませんでした。"))
            return None

        driver = ogr.GetDriverByName("GPKG")
        gpkg_path = self.tab.inspection_gpkg_path(self._target_inspection_type())
        ds = self.tab.open_or_create_inspection_gpkg(gpkg_path, driver)
        if ds is None:
            QMessageBox.critical(self.tab, tr_text("検査メッシュ作成"), tr_text("検査GPKGを開けません。"))
            return None
        try:
            descriptors = []
            mesh_display = self._unique_display_name("検査メッシュ")
            mesh_source = self._create_polygon_layer(
                ds, mesh_display, "000000", 0.4, GUIDE_ROLE_LINE, labels_enabled=False,
                extra_specs=self._mesh_field_specs(),
            )
            self._write_features(ds.GetLayerByName(mesh_source), mesh_features)
            descriptors.append(self._descriptor(mesh_source, mesh_display, "000000", 0.4, GUIDE_ROLE_LINE, False))

            done_display = self._unique_display_name("検査メッシュ済")
            done_source = self._create_polygon_layer(
                ds, done_display, "000000", 0.4, GUIDE_ROLE_DONE, labels_enabled=False,
                extra_specs=self._mesh_field_specs(),
            )
            descriptors.append(self._descriptor(done_source, done_display, "000000", 0.4, GUIDE_ROLE_DONE, False))
        finally:
            ds = None

        loaded = []
        for descriptor in descriptors:
            layer = self.tab.load_layer(descriptor["source_name"], descriptor)
            if layer:
                loaded.append(layer)
        self._place_loaded_layers_at_root_top(loaded)
        self.tab.refresh_ui()
        self.tab.set_status(tr_text(f"✅ 検査メッシュ作成: {len(mesh_features)} 件"))
        QgsMessageLog.logMessage(
            f"GUIDE_MESH_CREATED source={source_layer.name()} tiles={len(tile_items)} meshes={len(mesh_features)} cols={cols} rows={rows} id_field={id_field_name}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return loaded

    def create(self, source_layer, source_mode, width_m):
        if ogr is None:
            QMessageBox.critical(self.tab, tr_text("検査線作成"), tr_text("GDAL/OGRを読み込めないため検査線を作成できません。"))
            return None
        if not source_layer or not source_layer.isValid():
            QMessageBox.warning(self.tab, tr_text("検査線作成"), tr_text("作業範囲または図郭のポリゴンレイヤを選択してください。"))
            return None
        if width_m <= 0:
            QMessageBox.warning(self.tab, tr_text("検査線作成"), tr_text("検査線の幅を正しく入力してください。"))
            return None
        if not self.tab.ensure_project_metric_crs_for_inspection():
            return None
        if not self._source_layer_crs_is_valid(source_layer):
            QMessageBox.warning(
                self.tab,
                tr_text("検査線作成"),
                tr_text("選択したポリゴンレイヤの座標系が未設定です。\n先にレイヤの座標系を設定してください。"),
            )
            return None
        if not self.tab.ensure_gpkg_path(self._target_inspection_type()):
            return None

        areas = self._connected_areas(source_layer)
        if not areas:
            QMessageBox.warning(self.tab, tr_text("検査線作成"), tr_text("有効なポリゴンを取得できませんでした。"))
            return None

        areas = self._sort_areas(areas)
        line_features = []
        for area_index, area_geom in enumerate(areas, start=1):
            area_id = f"A-{area_index}"
            pieces = self._guide_pieces_for_area(area_geom, width_m)
            pad = max(3, len(str(len(pieces))))
            for line_index, geom in enumerate(pieces, start=1):
                memo = f"{area_id}_{line_index:0{pad}d}"
                line_features.append({
                    "geometry": geom,
                    "memo": memo,
                    "area_id": area_id,
                    "line_no": line_index,
                    "width_m": width_m,
                })

        if not line_features:
            QMessageBox.warning(self.tab, tr_text("検査線作成"), tr_text("検査線ポリゴンを作成できませんでした。"))
            return None

        driver = ogr.GetDriverByName("GPKG")
        gpkg_path = self.tab.inspection_gpkg_path(self._target_inspection_type())
        ds = self.tab.open_or_create_inspection_gpkg(gpkg_path, driver)
        if ds is None:
            QMessageBox.critical(self.tab, tr_text("検査線作成"), tr_text("検査GPKGを開けません。"))
            return None
        try:
            descriptors = []
            if source_mode == "tile":
                area_display = self._unique_display_name("検査範囲")
                area_source = self._create_polygon_layer(
                    ds, area_display, "0080ff", 0.6, GUIDE_ROLE_AREA, labels_enabled=False
                )
                self._write_features(
                    ds.GetLayerByName(area_source),
                    [
                        {
                            "geometry": geom,
                            "memo": f"A-{idx}",
                            "area_id": f"A-{idx}",
                            "line_no": 0,
                            "width_m": 0,
                        }
                        for idx, geom in enumerate(areas, start=1)
                    ],
                )
                descriptors.append(self._descriptor(area_source, area_display, "0080ff", 0.6, GUIDE_ROLE_AREA, False))

            line_display = self._unique_display_name("検査線")
            line_source = self._create_polygon_layer(
                ds, line_display, "000000", 0.4, GUIDE_ROLE_LINE, labels_enabled=False
            )
            self._write_features(ds.GetLayerByName(line_source), line_features)
            descriptors.append(self._descriptor(line_source, line_display, "000000", 0.4, GUIDE_ROLE_LINE, False))

            done_display = self._unique_display_name("検査済")
            done_source = self._create_polygon_layer(
                ds, done_display, "000000", 0.4, GUIDE_ROLE_DONE, labels_enabled=False
            )
            descriptors.append(self._descriptor(done_source, done_display, "000000", 0.4, GUIDE_ROLE_DONE, False))
        finally:
            ds = None

        loaded = []
        for descriptor in descriptors:
            layer = self.tab.load_layer(descriptor["source_name"], descriptor)
            if layer:
                loaded.append(layer)
        self._place_loaded_layers_at_root_top(loaded)
        self.tab.refresh_ui()
        self.tab.set_status(tr_text(f"✅ 検査線作成: {len(line_features)} 件"))
        QgsMessageLog.logMessage(
            f"GUIDE_LINES_CREATED source={source_layer.name()} mode={source_mode} areas={len(areas)} lines={len(line_features)} width={width_m}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return loaded

    def _unique_display_name(self, base):
        used = set()
        for layer in self.tab.inspection_layers():
            try:
                used.add(self.tab.layer_base_name(layer))
            except Exception:
                used.add(layer.name())
        if base not in used:
            return base
        number = 2
        while True:
            candidate = f"{base}_{number}"
            if candidate not in used:
                return candidate
            number += 1

    def _target_inspection_type(self):
        return self.tab.active_inspection_type

    def _create_polygon_layer(self, ds, display_name, color, stroke_width, guide_role, labels_enabled=False, extra_specs=None):
        extra_fields = []
        specs = extra_specs or [
            ("area_id", ogr.OFTString, 32),
            ("line_no", ogr.OFTInteger, 0),
            ("width_m", ogr.OFTReal, 0),
        ]
        for name, field_type, width in specs:
            field = ogr.FieldDefn(name, field_type)
            if width:
                field.SetWidth(width)
            extra_fields.append({"field_defn": field})
        prefix = "inspection" if self.tab.is_free_inspection() else "manual"
        source_base = f"{prefix}_polygon_{display_name}"
        source_name = self.tab.unique_source_layer_name(source_base, ds)
        self.tab.create_inspection_layer(
            0, "", display_name, color, "polygon", custom=True,
            inspection_type=self._target_inspection_type(), extra_fields=extra_fields,
            source_name_override=source_name, multi_geometry=True, dataset=ds,
        )
        return source_name

    def _descriptor(self, source_name, display_name, color, stroke_width, guide_role, labels_enabled):
        return {
            "round_no": 0,
            "code": "",
            "name": display_name,
            "color": color,
            "geom_type": "polygon",
            "stroke_width": stroke_width,
            "point_size": self.tab.default_point_size(),
            "source_name": source_name,
            "inspection_type": self._target_inspection_type(),
            "group_name": "",
            "custom": True,
            "guide_role": guide_role,
            "labels_enabled": labels_enabled,
            "gpkg_path": self.tab.inspection_gpkg_path(self._target_inspection_type()),
        }

    def _place_loaded_layers_at_root_top(self, layers):
        target_group = self.tab.ensure_inspection_root_group(self._target_inspection_type())
        if target_group is None:
            return
        for index, layer in enumerate(layer for layer in layers if layer):
            try:
                self.tab.place_layer_at_group_index(layer, target_group, index)
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"検査線レイヤ配置エラー: {layer.name()} / {exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

    def _write_features(self, target_layer, items):
        if target_layer is None:
            raise RuntimeError("検査線レイヤを作成できません")
        defn = target_layer.GetLayerDefn()
        now = self.tab.now_text()
        started_transaction = self.tab._begin_ogr_layer_transaction(target_layer)
        written = 0
        try:
            for index, item in enumerate(items, start=1):
                geom = item["geometry"]
                if not geom or geom.isEmpty():
                    continue
                ogr_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
                if ogr_geom is None:
                    continue
                try:
                    ogr_geom = ogr.ForceToMultiPolygon(ogr_geom)
                except Exception:
                    pass
                feature = ogr.Feature(defn)
                feature.SetGeometry(ogr_geom)
                values = {
                    "memo": item.get("memo", ""),
                    "round_no": 0,
                    "item_code": "",
                    "item_name": "",
                    "geom_type": "polygon",
                    "created_at": now,
                    "updated_at": now,
                    "area_id": item.get("area_id", ""),
                    "line_no": item.get("line_no", 0),
                    "width_m": item.get("width_m", 0),
                    "NAME": item.get("NAME", ""),
                    "tile_name": item.get("tile_name", ""),
                    "mesh_no": item.get("mesh_no", 0),
                    "mesh_row": item.get("mesh_row", 0),
                    "mesh_col": item.get("mesh_col", 0),
                    "split_cols": item.get("split_cols", 0),
                    "split_rows": item.get("split_rows", 0),
                }
                for name, value in values.items():
                    self.tab._set_ogr_field(feature, defn, name, value)
                self.tab.create_ogr_feature(target_layer, feature)
                written += 1
                feature = None
                if index % 250 == 0:
                    QApplication.processEvents()
            if started_transaction:
                self.tab._commit_ogr_layer_transaction(target_layer)
        except Exception:
            if started_transaction:
                self.tab._rollback_ogr_layer_transaction(target_layer)
            raise
        QgsMessageLog.logMessage(
            f"GUIDE_FEATURES_WRITTEN layer={target_layer.GetName()} count={written} transaction={started_transaction}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

    def _mesh_field_specs(self):
        return [
            ("NAME", ogr.OFTString, 160),
            ("tile_name", ogr.OFTString, 160),
            ("mesh_no", ogr.OFTInteger, 0),
            ("mesh_row", ogr.OFTInteger, 0),
            ("mesh_col", ogr.OFTInteger, 0),
            ("split_cols", ogr.OFTInteger, 0),
            ("split_rows", ogr.OFTInteger, 0),
        ]

    def _source_tile_items(self, layer, id_field_name):
        transform = None
        try:
            src_crs = layer.crs()
            dst_crs = QgsProject.instance().crs()
            if src_crs and dst_crs and src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        except Exception:
            transform = None
        items = []
        for feature in layer.getFeatures():
            try:
                tile_name = str(feature[id_field_name] or "").strip()
            except Exception:
                tile_name = ""
            if not tile_name:
                continue
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            geom = QgsGeometry(geom)
            try:
                if transform is not None:
                    geom.transform(transform)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査メッシュ作成 座標変換エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                continue
            geom = self._make_valid(geom)
            if self._has_polygon_area(geom):
                items.append({"tile_name": tile_name, "geometry": geom})
        items.sort(key=lambda item: (-item["geometry"].boundingBox().yMaximum(), item["geometry"].boundingBox().xMinimum(), item["tile_name"]))
        return items

    def _mesh_features_for_tile(self, tile_geom, tile_name, cols, rows, pad):
        box = tile_geom.boundingBox()
        width = box.width() / cols
        height = box.height() / rows
        if width <= 0 or height <= 0:
            return []
        features = []
        mesh_no = 0
        for row in range(rows):
            y_max = box.yMaximum() - row * height
            y_min = box.yMaximum() - (row + 1) * height
            if row == rows - 1:
                y_min = box.yMinimum()
            for col in range(cols):
                x_min = box.xMinimum() + col * width
                x_max = box.xMinimum() + (col + 1) * width
                if col == cols - 1:
                    x_max = box.xMaximum()
                mesh_no += 1
                rect = QgsGeometry.fromRect(QgsRectangle(x_min, y_min, x_max, y_max))
                try:
                    clipped = self._make_valid(tile_geom.intersection(rect))
                except Exception:
                    clipped = None
                for part in self._polygon_parts(clipped):
                    if not self._has_polygon_area(part):
                        continue
                    suffix = str(mesh_no).zfill(pad)
                    mesh_name = f"{tile_name}{suffix}"
                    features.append({
                        "geometry": part,
                        "memo": mesh_name,
                        "NAME": mesh_name,
                        "tile_name": tile_name,
                        "mesh_no": mesh_no,
                        "mesh_row": row + 1,
                        "mesh_col": col + 1,
                        "split_cols": cols,
                        "split_rows": rows,
                    })
        return features

    def _connected_areas(self, layer):
        geoms = self._source_geometries(layer)
        if not geoms:
            return []
        features = []
        for idx, geom in enumerate(geoms):
            feature = QgsFeature()
            feature.setId(idx)
            feature.setGeometry(geom)
            features.append(feature)
        index = QgsSpatialIndex()
        for feature in features:
            index.addFeature(feature)
        visited = set()
        areas = []
        by_id = {feature.id(): feature.geometry() for feature in features}
        for feature in features:
            fid = feature.id()
            if fid in visited:
                continue
            queue = [fid]
            visited.add(fid)
            component = []
            while queue:
                current_id = queue.pop(0)
                current_geom = by_id[current_id]
                component.append(current_geom)
                search_rect = current_geom.boundingBox().buffered(CONNECT_TOLERANCE_M)
                for candidate_id in index.intersects(search_rect):
                    if candidate_id in visited:
                        continue
                    candidate_geom = by_id.get(candidate_id)
                    if not candidate_geom:
                        continue
                    if self._geometries_connected(current_geom, candidate_geom):
                        visited.add(candidate_id)
                        queue.append(candidate_id)
            merged = self._merge_geometries(component)
            if merged and not merged.isEmpty():
                areas.append(merged)
        return [geom for geom in areas if geom and not geom.isEmpty()]

    def _source_geometries(self, layer):
        transform = None
        try:
            src_crs = layer.crs()
            dst_crs = QgsProject.instance().crs()
            if src_crs and dst_crs and src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        except Exception:
            transform = None
        geoms = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            geom = QgsGeometry(geom)
            try:
                if transform is not None:
                    geom.transform(transform)
            except Exception as exc:
                QgsMessageLog.logMessage(f"検査線作成 座標変換エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                continue
            geom = self._make_valid(geom)
            if geom and not geom.isEmpty():
                geoms.extend(self._polygon_parts(geom))
        return geoms

    def _geometries_connected(self, left, right):
        try:
            if left.intersects(right):
                return True
        except Exception:
            pass
        try:
            return left.distance(right) <= CONNECT_TOLERANCE_M
        except Exception:
            return False

    def _merge_geometries(self, geoms):
        if not geoms:
            return None
        try:
            return self._make_valid(QgsGeometry.unaryUnion(geoms))
        except Exception:
            merged = QgsGeometry(geoms[0])
            for geom in geoms[1:]:
                try:
                    merged = merged.combine(geom)
                except Exception:
                    pass
            return self._make_valid(merged)

    def _make_valid(self, geom):
        if not geom or geom.isEmpty():
            return geom
        try:
            if not geom.isGeosValid():
                fixed = geom.makeValid()
                if fixed and not fixed.isEmpty():
                    return fixed
        except Exception:
            pass
        return geom

    def _sort_areas(self, areas):
        def key(geom):
            box = geom.boundingBox()
            return (-box.yMaximum(), box.xMinimum())
        return sorted(areas, key=key)

    def _guide_pieces_for_area(self, area_geom, width_m):
        buffered = self._make_valid(self._square_buffer(area_geom, 10.0))
        if not buffered or buffered.isEmpty():
            return []
        box = buffered.boundingBox()
        min_x = box.xMinimum() - width_m
        max_x = box.xMaximum() + width_m
        y_top = box.yMaximum()
        y_min = box.yMinimum()
        rows = []
        y = y_top
        while y > y_min:
            next_y = max(y_min, y - width_m)
            rect = QgsRectangle(min_x, next_y, max_x, y)
            strip = QgsGeometry.fromRect(rect)
            try:
                clipped = self._make_valid(buffered.intersection(strip))
            except Exception:
                clipped = None
            pieces = self._polygon_parts(clipped)
            pieces.sort(key=lambda geom: geom.boundingBox().xMinimum())
            rows.extend(pieces)
            if math.isclose(next_y, y, abs_tol=0.000001):
                break
            y = next_y
        return rows

    def _square_buffer(self, geom, distance):
        try:
            return geom.buffer(distance, 1, Qgis.EndCapStyle.Square, Qgis.JoinStyle.Miter, 2.0)
        except Exception:
            try:
                return geom.buffer(distance, 1)
            except Exception:
                return None

    def _polygon_parts(self, geom):
        if not geom or geom.isEmpty():
            return []
        try:
            polygon_geom = QgsGeometry(geom)
            if polygon_geom.convertGeometryCollectionToSubclass(Qgis.GeometryType.Polygon):
                geom = polygon_geom
        except Exception:
            pass
        parts = []
        try:
            if geom.isMultipart():
                for polygon in geom.asMultiPolygon():
                    part = QgsGeometry.fromPolygonXY(polygon)
                    if self._has_polygon_area(part):
                        parts.append(part)
                return parts
            polygon = geom.asPolygon()
            if polygon:
                part = QgsGeometry.fromPolygonXY(polygon)
                if self._has_polygon_area(part):
                    return [part]
        except Exception:
            pass
        return parts

    def _has_polygon_area(self, geom):
        if not geom or geom.isEmpty():
            return False
        try:
            return geom.area() > 0.000001
        except Exception:
            return False
